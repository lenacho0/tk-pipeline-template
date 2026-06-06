#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

import requests

from common import extract_text
from otu_image import DEFAULT_OTU_API_BASE


DEFAULT_OMNI_MODEL = "omni_flash-10s"
DEFAULT_OMNI_SIZE = "720x1280"
DEFAULT_OMNI_ASPECT_RATIO = "9:16"
SUBMIT_TIMEOUT = 180
POLL_TIMEOUT = 45
POLL_INTERVAL = 15
MAX_POLL_SECONDS = 2400


def compact_json(value: Any, max_chars: int = 20000) -> str:
    text = json.dumps(value, ensure_ascii=False, indent=2, default=str)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 200] + "\n...TRUNCATED..."


def videos_url(api_base: str) -> str:
    base = (api_base or DEFAULT_OTU_API_BASE).rstrip("/")
    if base.endswith("/v1/videos"):
        return base
    if base.endswith("/v1"):
        return f"{base}/videos"
    return f"{base}/v1/videos"


def video_item_url(api_base: str, task_id: str) -> str:
    return f"{videos_url(api_base).rstrip('/')}/{task_id}"


def submit_omni_video_task(
    config: Dict[str, str],
    prompt: str,
    refs: List[Dict[str, str]],
    *,
    size: str = DEFAULT_OMNI_SIZE,
    aspect_ratio: str = DEFAULT_OMNI_ASPECT_RATIO,
) -> Tuple[str, Dict[str, Any]]:
    if not refs:
        raise ValueError("Omni 图生视频至少需要 1 张参考图")
    url = videos_url(config.get("api_base") or DEFAULT_OTU_API_BASE)
    headers = {"Authorization": f"Bearer {config['api_key']}"}
    data = {
        "model": config.get("model") or DEFAULT_OMNI_MODEL,
        "prompt": prompt,
        "size": size or DEFAULT_OMNI_SIZE,
        "aspect_ratio": aspect_ratio or DEFAULT_OMNI_ASPECT_RATIO,
    }
    opened = []
    files: List[Tuple[str, Tuple[Any, ...]]] = []
    try:
        for ref in refs[:7]:
            path = ref.get("path", "")
            if not path or not os.path.exists(path):
                raise ValueError(f"Omni 参考图不存在: {ref.get('role')}")
            handle = open(path, "rb")
            opened.append(handle)
            files.append(("input_reference[]", (os.path.basename(path), handle, "image/png")))
        resp = requests.post(url, headers=headers, data=data, files=files, timeout=SUBMIT_TIMEOUT)
    finally:
        for handle in opened:
            handle.close()
    try:
        body = resp.json()
    except Exception:
        body = {"raw_text": resp.text[:1000]}
    if resp.status_code >= 400:
        raise RuntimeError(f"Omni 视频任务提交失败: HTTP {resp.status_code}, body={str(body)[:1200]}")
    task_id = extract_text(body.get("id") or body.get("task_id") or (body.get("data") or {}).get("id") or (body.get("data") or {}).get("task_id")).strip()
    if not task_id:
        raise RuntimeError(f"Omni 视频任务提交未返回任务 ID: {str(body)[:1200]}")
    return task_id, body


def poll_omni_video_task(config: Dict[str, str], task_id: str) -> Dict[str, Any]:
    url = video_item_url(config.get("api_base") or DEFAULT_OTU_API_BASE, task_id)
    headers = {"Authorization": f"Bearer {config['api_key']}"}
    start = time.time()
    last_body: Dict[str, Any] = {}
    while time.time() - start < MAX_POLL_SECONDS:
        resp = requests.get(url, headers=headers, timeout=POLL_TIMEOUT)
        try:
            body = resp.json()
        except Exception:
            body = {"raw_text": resp.text[:1000]}
        last_body = body if isinstance(body, dict) else {"raw": body}
        if resp.status_code >= 400:
            raise RuntimeError(f"Omni 视频任务轮询失败: HTTP {resp.status_code}, body={str(last_body)[:1200]}")
        status = extract_text(last_body.get("status") or (last_body.get("data") or {}).get("status")).lower()
        if status in {"completed", "succeeded", "success", "done"}:
            return last_body
        if status in {"failed", "error", "cancelled", "canceled"}:
            raise RuntimeError(f"Omni 视频生成失败: {str(last_body)[:1500]}")
        time.sleep(POLL_INTERVAL)
    raise TimeoutError(f"Omni 视频任务超时: task_id={task_id}, last={str(last_body)[:1200]}")


def _render_reference_contact_sheet(refs: List[Dict[str, str]], out_path: Path) -> None:
    from PIL import Image, ImageDraw, ImageOps

    tiles = []
    for ref in refs:
        path = ref.get("path", "")
        if not path or not os.path.exists(path):
            continue
        with Image.open(path) as img:
            tiles.append((ref, img.convert("RGB").copy()))
    if not tiles:
        raise ValueError("缺少可用参考图，无法生成参考图索引板")

    tile_w, tile_h = 520, 420
    label_h = 44
    cols = min(4, len(tiles))
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tile_w, rows * (tile_h + label_h)), "white")
    draw = ImageDraw.Draw(sheet)

    for idx, (ref, img) in enumerate(tiles):
        col = idx % cols
        row = idx // cols
        x = col * tile_w
        y = row * (tile_h + label_h)
        label = f"{idx + 1}. {ref.get('role', 'reference')}"
        if ref.get("name"):
            label += f" - {ref['name']}"
        draw.rectangle([x, y, x + tile_w - 1, y + label_h - 1], fill=(0, 110, 100))
        draw.text((x + 12, y + 12), label[:70], fill="white")
        fitted = ImageOps.contain(img, (tile_w - 20, tile_h - 20))
        px = x + (tile_w - fitted.width) // 2
        py = y + label_h + (tile_h - fitted.height) // 2
        sheet.paste(fitted, (px, py))
        draw.rectangle([x, y, x + tile_w - 1, y + tile_h + label_h - 1], outline=(200, 200, 200), width=2)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)


def build_reference_contact_sheet(refs: List[Dict[str, str]], out_path: Path) -> str:
    _render_reference_contact_sheet(refs, out_path)
    return str(out_path)
