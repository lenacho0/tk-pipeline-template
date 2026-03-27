from __future__ import annotations

import json
from datetime import datetime
from http import HTTPStatus
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


def run_batch(urls_text: str) -> dict:
    config = load_config(ENV_FILE)
    ensure_dir(DOWNLOAD_ROOT)
    run_id = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_root = DOWNLOAD_ROOT / run_id
    ensure_dir(output_root)

    items = load_urls_from_input(None, ','.join([line.strip() for line in urls_text.splitlines() if line.strip()]))
    if not items:
        raise ValueError('No valid URLs found')

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
        'run_id': run_id,
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
    return payload


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: bytes, content_type: str = 'text/html; charset=utf-8') -> None:
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

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
            self._send(200, json.dumps(LAST_RUN, ensure_ascii=False).encode('utf-8'), 'application/json; charset=utf-8')
            return
        self._send(404, b'Not Found', 'text/plain; charset=utf-8')

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != '/api/run':
            self._send(404, b'Not Found', 'text/plain; charset=utf-8')
            return
        length = int(self.headers.get('Content-Length', '0'))
        raw = self.rfile.read(length)
        data = json.loads(raw.decode('utf-8'))
        urls_text = str(data.get('urls', ''))
        try:
            LAST_RUN['status'] = 'running'
            LAST_RUN['started_at'] = datetime.now().isoformat()
            payload = run_batch(urls_text)
            LAST_RUN['status'] = 'done'
            LAST_RUN['summary'] = payload['summary']
            LAST_RUN['results'] = payload['results']
            LAST_RUN['output_dir'] = payload['output_dir']
            self._send(200, json.dumps(payload, ensure_ascii=False).encode('utf-8'), 'application/json; charset=utf-8')
        except Exception as exc:  # noqa: BLE001
            LAST_RUN['status'] = 'error'
            self._send(400, json.dumps({'error': str(exc)}, ensure_ascii=False).encode('utf-8'), 'application/json; charset=utf-8')


def main() -> None:
    server = ThreadingHTTPServer(('127.0.0.1', 8765), Handler)
    print('Web UI running at http://127.0.0.1:8765')
    server.serve_forever()


if __name__ == '__main__':
    main()
