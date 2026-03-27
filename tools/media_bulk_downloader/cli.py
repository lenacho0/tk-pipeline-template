from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .config import load_config
from .downloader import download_media
from .io_utils import ensure_dir, load_urls_from_input, write_results_csv
from .models import DownloadResult, InputItem
from .provider import MediaProviderClient


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bulk media downloader powered by Henghengmao API")
    parser.add_argument("--input", type=Path, help="Path to txt/csv file containing media URLs")
    parser.add_argument("--urls", help="Comma-separated list of media URLs")
    parser.add_argument("--url-column", default="url", help="CSV column name containing URLs")
    parser.add_argument("--env-file", type=Path, default=Path(".env"), help="Path to env file")
    parser.add_argument("--output", type=Path, default=Path("downloads"), help="Download output root")
    parser.add_argument("--concurrency", type=int, default=None, help="Concurrent workers")
    parser.add_argument("--retry", type=int, default=None, help="Retry count override")
    parser.add_argument("--skip-existing", action="store_true", default=True)
    parser.add_argument("--failed-only", type=Path, help="Replay only failed URLs from a prior failed.csv/results.csv")
    return parser.parse_args()


def load_failed_only(path: Path) -> str:
    import csv

    urls: list[str] = []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            if (row.get("status") or "").lower() == "failed":
                url = (row.get("source_url") or "").strip()
                if url:
                    urls.append(url)
    return ",".join(urls)


def process_one(client: MediaProviderClient, config, item: InputItem, output_root: Path, skip_existing: bool) -> DownloadResult:
    media = client.resolve(item)
    return download_media(config, item, media, output_root, skip_existing=skip_existing)


def main() -> int:
    args = parse_args()
    config = load_config(args.env_file)
    if args.retry is not None:
        config.retry_count = args.retry
    if args.concurrency is not None:
        config.concurrency = args.concurrency
    output_root = args.output or config.output_dir
    ensure_dir(output_root)

    raw_urls = args.urls
    if args.failed_only:
        raw_urls = load_failed_only(args.failed_only)

    items = load_urls_from_input(args.input, raw_urls, url_column=args.url_column)
    if not items:
        raise SystemExit("No valid URLs found.")

    client = MediaProviderClient(config)
    results: list[DownloadResult] = []

    with ThreadPoolExecutor(max_workers=max(config.concurrency, 1)) as executor:
        futures = {
            executor.submit(process_one, client, config, item, output_root, args.skip_existing): item
            for item in items
        }
        for future in as_completed(futures):
            item = futures[future]
            try:
                result = future.result()
            except Exception as exc:  # noqa: BLE001
                result = DownloadResult(item=item, status="failed", error=str(exc), attempts=config.retry_count)
            results.append(result)
            print(f"[{result.status.upper()}] {item.platform}: {item.source_url}")
            if result.error:
                print(f"  error: {result.error}")
            if result.file_path:
                print(f"  file: {result.file_path}")

    results.sort(key=lambda x: (x.item.platform, x.item.normalized_url))
    write_results_csv(output_root / "results.csv", results)
    write_results_csv(output_root / "failed.csv", [r for r in results if r.status == "failed"])
    manifest = {
        "total": len(results),
        "success": sum(1 for r in results if r.status == "success"),
        "failed": sum(1 for r in results if r.status == "failed"),
        "skipped": sum(1 for r in results if r.status == "skipped"),
    }
    (output_root / "summary.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print("Done.")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0 if manifest["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
