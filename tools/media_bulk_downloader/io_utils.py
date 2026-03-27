from __future__ import annotations

import csv
import re
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from .models import DownloadResult, InputItem


SUPPORTED_PLATFORMS = {
    "instagram": ["instagram.com", "www.instagram.com"],
    "tiktok": ["tiktok.com", "www.tiktok.com", "vt.tiktok.com"],
    "youtube": ["youtube.com", "www.youtube.com", "youtu.be"],
    "douyin": ["douyin.com", "www.douyin.com", "v.douyin.com"],
    "xiaohongshu": ["xiaohongshu.com", "www.xiaohongshu.com", "xhslink.com"],
}


URL_RE = re.compile(r"https?://\S+")


def detect_platform(url: str) -> str:
    host = urlparse(url).netloc.lower()
    for platform, hosts in SUPPORTED_PLATFORMS.items():
        if any(host == item or host.endswith(f'.{item}') for item in hosts):
            return platform
    return "unknown"


def normalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    clean = parsed._replace(query="", fragment="")
    path = clean.path.rstrip("/") or "/"
    clean = clean._replace(path=path)
    return urlunparse(clean)


def load_urls_from_input(input_path: Path | None, raw_urls: str | None, url_column: str = "url") -> list[InputItem]:
    urls: list[tuple[int | None, str, str | None]] = []

    if raw_urls:
        chunks = [part.strip() for part in raw_urls.split(",") if part.strip()]
        for idx, url in enumerate(chunks, start=1):
            urls.append((idx, url, "args"))

    if input_path:
        suffix = input_path.suffix.lower()
        if suffix == ".csv":
            with input_path.open("r", encoding="utf-8-sig", newline="") as fh:
                reader = csv.DictReader(fh)
                for idx, row in enumerate(reader, start=2):
                    value = (row.get(url_column) or "").strip()
                    if value:
                        urls.append((idx, value, input_path.name))
        else:
            for idx, line in enumerate(input_path.read_text(encoding="utf-8").splitlines(), start=1):
                for match in URL_RE.findall(line):
                    urls.append((idx, match, input_path.name))

    seen: set[str] = set()
    items: list[InputItem] = []
    for row_number, source_url, source_label in urls:
        normalized = normalize_url(source_url)
        if normalized in seen:
            continue
        seen.add(normalized)
        items.append(
            InputItem(
                source_url=source_url,
                normalized_url=normalized,
                platform=detect_platform(normalized),
                row_number=row_number,
                source_label=source_label,
            )
        )
    return items


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_results_csv(path: Path, results: list[DownloadResult]) -> None:
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow([
            "status",
            "platform",
            "source_url",
            "normalized_url",
            "file_path",
            "attempts",
            "error",
        ])
        for result in results:
            writer.writerow([
                result.status,
                result.item.platform,
                result.item.source_url,
                result.item.normalized_url,
                str(result.file_path) if result.file_path else "",
                result.attempts,
                result.error or "",
            ])
