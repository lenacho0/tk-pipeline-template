from __future__ import annotations

import json
import time
from typing import Any
from urllib import error, parse, request

from .config import AppConfig
from .models import InputItem, ResolvedMedia


class MediaProviderClient:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def resolve(self, item: InputItem) -> ResolvedMedia:
        last_error: Exception | None = None
        for attempt in range(1, self.config.retry_count + 1):
            try:
                return self._resolve_once(item)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt >= self.config.retry_count:
                    break
                time.sleep(min(2 ** (attempt - 1), 6))
        raise RuntimeError(f"Resolve failed for {item.source_url}: {last_error}") from last_error

    def _resolve_once(self, item: InputItem) -> ResolvedMedia:
        payload = json.dumps({"url": item.source_url}).encode("utf-8")
        endpoint = self._build_media_endpoint()
        req = request.Request(
            endpoint,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "x-api-key": self.config.api_key,
                "accept-language": "zh",
                "User-Agent": "media-bulk-downloader/0.1",
            },
            method="POST",
        )
        with request.urlopen(req, timeout=self.config.timeout_seconds) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return self._parse_media_response(item, data)

    def _build_media_endpoint(self) -> str:
        base = self.config.base_url.rstrip("/")
        return f"{base}/openapi/extract/post"

    def _parse_media_response(self, item: InputItem, data: dict[str, Any]) -> ResolvedMedia:
        candidates = self._collect_candidates(data)
        if not candidates:
            raise ValueError(f"No downloadable media found in API response for {item.source_url}")

        candidates.sort(key=self._candidate_sort_key)
        best = candidates[0]
        return ResolvedMedia(
            download_url=best["download_url"],
            platform=item.platform,
            media_type=best.get("media_type", "video"),
            title=best.get("title"),
            creator=best.get("creator"),
            content_id=best.get("content_id"),
            ext=best.get("ext", "mp4"),
            thumbnail_url=best.get("thumbnail_url"),
            raw=data,
        )

    def _collect_candidates(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []

        def add_candidate(url: str, meta: dict[str, Any] | None = None) -> None:
            if not url:
                return
            info = dict(meta or {})
            info["download_url"] = url
            candidates.append(info)

        possible_lists = [
            data.get("medias"),
            data.get("media"),
            data.get("data"),
            data.get("resources"),
            data.get("items"),
        ]

        for block in possible_lists:
            if isinstance(block, list):
                for entry in block:
                    if isinstance(entry, str):
                        add_candidate(entry)
                    elif isinstance(entry, dict):
                        add_candidate(
                            entry.get("resource_url")
                            or entry.get("url")
                            or entry.get("download_url")
                            or entry.get("play")
                            or entry.get("src"),
                            entry,
                        )
            elif isinstance(block, dict):
                add_candidate(
                    block.get("resource_url")
                    or block.get("url")
                    or block.get("download_url")
                    or block.get("play")
                    or block.get("src"),
                    block,
                )

        for key in ("resource_url", "url", "download_url", "play", "video"):
            value = data.get(key)
            if isinstance(value, str):
                add_candidate(value, data)
            elif isinstance(value, dict):
                add_candidate(value.get("url") or value.get("download_url"), value)

        deduped: list[dict[str, Any]] = []
        seen: set[str] = set()
        for candidate in candidates:
            url = candidate["download_url"]
            if url in seen:
                continue
            seen.add(url)
            deduped.append(candidate)
        return deduped

    def _candidate_sort_key(self, candidate: dict[str, Any]) -> tuple[int, int, int]:
        media_type = str(candidate.get("media_type", "")).lower()
        ext = str(candidate.get("ext", "")).lower()
        resource_url = str(candidate.get("download_url", "")).lower()
        is_video = 0 if media_type == "video" else 1
        is_mp4 = 0 if ".mp4" in resource_url or ext == "mp4" else 1
        has_formats = 0 if candidate.get("formats") else 1
        return (is_video, is_mp4, has_formats)
