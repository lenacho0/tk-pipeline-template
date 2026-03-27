from __future__ import annotations

import json
import subprocess
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .cli import process_one
from .config import load_config
from .io_utils import ensure_dir, load_urls_from_input, write_results_csv
from .models import DownloadResult
from .provider import MediaProviderClient

ROOT = Path('/Users/ryanlynn/.openclaw/workspace-tk')
TOOL_DIR = ROOT / 'tools' / 'media_bulk_downloader'
DOWNLOAD_ROOT = ROOT / 'downloads' / 'media_bulk_web'
ENV_FILE = ROOT / '.env'
INDEX_HTML = TOOL_DIR / 'web' / 'index.html'
APP_CSS = TOOL_DIR / 'web' / 'app.css'
APP_JS = TOOL_DIR / 'web' / 'app.js'

LAST_RUN: dict = {
    'status': 'idle',
    'summary': None,
    'results': [],
    'output_dir': None,
    'started_at': None,
}


def execute_batch(items, output_root: Path) -> dict:
    config = load_config(ENV_FILE)
    client = MediaProviderClient(config)
    results: list[DownloadResult] = []

    for item in items:
        try:
            result = process_one(client, config, item, output_root, True)
        except Exception as exc:  # noqa: BLE001
            result = DownloadResult(item=item, status='failed', error=str(exc), attempts=config.retry_count)
        results.append(result)

    results.sort(key=lambda x: (x.item.platform, x.item.normalized_url))
    meta_dir = output_root / '_meta'
    ensure_dir(meta_dir)
    write_results_csv(meta_dir / 'results.csv', results)
    write_results_csv(meta_dir / 'failed.csv', [r for r in results if r.status == 'failed'])
    summary = {
        'total': len(results),
        'success': sum(1 for r in results if r.status == 'success'),
        'failed': sum(1 for r in results if r.status == 'failed'),
        'skipped': sum(1 for r in results if r.status == 'skipped'),
    }
    (meta_dir / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')

    payload = {
        'summary': summary,
        'output_dir': str(output_root),
        'results': [
            {
                'status': r.status,
                'platform': r.item.platform,
                'source_url': r.item.source_url,
                'file_path': str(r.file_path) if r.file_path else None,
                'error': r.error,
            }
            for r in results
        ],
    }
    LAST_RUN['status'] = 'done'
    LAST_RUN['summary'] = payload['summary']
    LAST_RUN['results'] = payload['results']
    LAST_RUN['output_dir'] = payload['output_dir']
    return payload


def run_batch(urls_text: str) -> dict:
    ensure_dir(DOWNLOAD_ROOT)
    run_id = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_root = DOWNLOAD_ROOT / run_id
    ensure_dir(output_root)
    items = load_urls_from_input(None, ','.join([line.strip() for line in urls_text.splitlines() if line.strip()]))
    if not items:
        raise ValueError('No valid URLs found')
    payload = execute_batch(items, output_root)
    payload['run_id'] = run_id
    return payload


def rerun_failed() -> dict:
    results = LAST_RUN.get('results') or []
    failed_urls = [item['source_url'] for item in results if item.get('status') == 'failed' and item.get('source_url')]
    if not failed_urls:
        raise ValueError('No failed items to rerun')
    ensure_dir(DOWNLOAD_ROOT)
    run_id = datetime.now().strftime('%Y%m%d_%H%M%S') + '_rerun'
    output_root = DOWNLOAD_ROOT / run_id
    ensure_dir(output_root)
    items = load_urls_from_input(None, ','.join(failed_urls))
    payload = execute_batch(items, output_root)
    payload['run_id'] = run_id
    return payload


def open_output_dir() -> None:
    output_dir = LAST_RUN.get('output_dir')
    if not output_dir:
        raise ValueError('No output directory available yet')
    subprocess.Popen(['open', output_dir])


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: bytes, content_type: str = 'text/html; charset=utf-8') -> None:
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data: dict, status: int = 200) -> None:
        self._send(status, json.dumps(data, ensure_ascii=False).encode('utf-8'), 'application/json; charset=utf-8')

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path in ('/', '/index.html'):
            self._send(200, INDEX_HTML.read_bytes())
            return
        if parsed.path == '/app.css':
            self._send(200, APP_CSS.read_bytes(), 'text/css; charset=utf-8')
            return
        if parsed.path == '/app.js':
            self._send(200, APP_JS.read_bytes(), 'application/javascript; charset=utf-8')
            return
        if parsed.path == '/api/status':
            self._json(LAST_RUN)
            return
        self._send(404, b'Not Found', 'text/plain; charset=utf-8')

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        length = int(self.headers.get('Content-Length', '0'))
        raw = self.rfile.read(length) if length > 0 else b'{}'
        data = json.loads(raw.decode('utf-8')) if raw else {}
        try:
            if parsed.path == '/api/run':
                urls_text = str(data.get('urls', ''))
                LAST_RUN['status'] = 'running'
                LAST_RUN['started_at'] = datetime.now().isoformat()
                self._json(run_batch(urls_text))
                return
            if parsed.path == '/api/rerun-failed':
                LAST_RUN['status'] = 'running'
                LAST_RUN['started_at'] = datetime.now().isoformat()
                self._json(rerun_failed())
                return
            if parsed.path == '/api/open-output':
                open_output_dir()
                self._json({'ok': True})
                return
            self._send(404, b'Not Found', 'text/plain; charset=utf-8')
        except Exception as exc:  # noqa: BLE001
            LAST_RUN['status'] = 'error'
            self._json({'error': str(exc)}, 400)


def main() -> None:
    server = ThreadingHTTPServer(('127.0.0.1', 8765), Handler)
    print('Web UI running at http://127.0.0.1:8765')
    server.serve_forever()


if __name__ == '__main__':
    main()
