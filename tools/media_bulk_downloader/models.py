from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class InputItem:
    source_url: str
    normalized_url: str
    platform: str
    row_number: int | None = None
    source_label: str | None = None


@dataclass
class ResolvedMedia:
    download_url: str
    platform: str
    media_type: str = "video"
    title: str | None = None
    creator: str | None = None
    content_id: str | None = None
    ext: str | None = None
    thumbnail_url: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class DownloadResult:
    item: InputItem
    status: str
    file_path: Path | None = None
    resolved_media: ResolvedMedia | None = None
    error: str | None = None
    attempts: int = 0
    skipped: bool = False
