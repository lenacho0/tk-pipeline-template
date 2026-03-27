from __future__ import annotations

import mimetypes
import time
from pathlib import Path
from urllib import request

from .config import AppConfig
from .io_utils import ensure_dir
from .models import DownloadResult, InputItem, ResolvedMedia


def build_output_filename(item: InputItem, media: ResolvedMedia) -> str:
    stem = media.content_id or item.normalized_url.rstrip("/").split("/")[-1] or "media"
    ext = media.ext or mimetypes.guess_extension(media.media_type) or ".mp4"
    ext = ext if str(ext).startswith(".") else f".{ext}"
    platform = item.platform or "unknown"
    safe_stem = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in stem)
    return f"{platform}_{safe_stem}{ext}"


def download_media(config: AppConfig, item: InputItem, media: ResolvedMedia, root_dir: Path, skip_existing: bool = True) -> DownloadResult:
    platform_dir = root_dir / item.platform
    ensure_dir(platform_dir)
    filename = build_output_filename(item, media)
    output_path = platform_dir / filename

    if skip_existing and output_path.exists() and output_path.stat().st_size > 0:
        return DownloadResult(item=item, status="skipped", file_path=output_path, resolved_media=media, skipped=True)

    last_error: Exception | None = None
    for attempt in range(1, config.retry_count + 1):
        try:
            req = request.Request(media.download_url, headers={"User-Agent": "media-bulk-downloader/0.1"})
            with request.urlopen(req, timeout=config.timeout_seconds) as resp, output_path.open("wb") as fh:
                while True:
                    chunk = resp.read(1024 * 128)
                    if not chunk:
                        break
                    fh.write(chunk)
            if output_path.stat().st_size <= 0:
                raise ValueError("Downloaded file is empty")
            return DownloadResult(
                item=item,
                status="success",
                file_path=output_path,
                resolved_media=media,
                attempts=attempt,
            )
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if output_path.exists():
                output_path.unlink(missing_ok=True)
            if attempt < config.retry_count:
                time.sleep(min(2 ** (attempt - 1), 6))

    return DownloadResult(
        item=item,
        status="failed",
        resolved_media=media,
        error=str(last_error),
        attempts=config.retry_count,
    )
