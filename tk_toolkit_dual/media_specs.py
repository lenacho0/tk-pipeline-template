#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class MediaSpec:
    size: str = ""
    aspect_ratio: str = ""
    seconds: str = ""
    source: str = ""
    slot_name: str = ""
    capability: str = ""

    def summary(self) -> Dict[str, str]:
        return {
            "size": self.size,
            "aspect_ratio": self.aspect_ratio,
            "seconds": self.seconds,
            "source": self.source,
            "slot_name": self.slot_name,
            "capability": self.capability,
        }


def _metadata_value(metadata: Optional[Dict[str, Any]], *keys: str) -> str:
    if not isinstance(metadata, dict):
        return ""
    for key in keys:
        value = metadata.get(key)
        if value is not None:
            text = str(value).strip()
            if text:
                return text
    return ""


def adapt_image_metadata(
    metadata: Optional[Dict[str, Any]] = None,
    *,
    size: str = "",
    aspect_ratio: str = "",
    default_aspect_ratio: str = "9:16",
) -> Dict[str, Any]:
    adapted: Dict[str, Any] = dict(metadata or {})
    effective_size = (size or _metadata_value(adapted, "size", "画面尺寸")).strip()
    effective_aspect_ratio = (
        aspect_ratio
        or _metadata_value(adapted, "aspect_ratio", "aspectRatio", "画面比例")
        or default_aspect_ratio
    ).strip()
    if effective_size:
        adapted["size"] = effective_size
    if effective_aspect_ratio:
        adapted["aspectRatio"] = effective_aspect_ratio
        adapted["aspect_ratio"] = effective_aspect_ratio
    return adapted


def media_spec_from_values(
    *,
    size: str = "",
    aspect_ratio: str = "",
    seconds: str = "",
    source: str = "",
    slot_name: str = "",
    capability: str = "",
) -> MediaSpec:
    return MediaSpec(
        size=str(size or "").strip(),
        aspect_ratio=str(aspect_ratio or "").strip(),
        seconds=str(seconds or "").strip(),
        source=str(source or "").strip(),
        slot_name=str(slot_name or "").strip(),
        capability=str(capability or "").strip(),
    )
