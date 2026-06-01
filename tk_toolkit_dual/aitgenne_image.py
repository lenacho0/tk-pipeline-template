#!/usr/bin/env python3
from __future__ import annotations

import base64
import json
import os
import time
from typing import Any, Callable, Dict, List, Optional

import requests

from common import extract_text
from media_specs import adapt_image_metadata


DEFAULT_AITGENNE_API_BASE = "https://api.aitgenne.com"
DEFAULT_AITGENNE_IMAGE_MODEL = "gpt-image-2"
DEFAULT_AITGENNE_IMAGE_SIZE = "1024x1024"
DEFAULT_AITGENNE_ASPECT_RATIO = "9:16"
SUBMIT_TIMEOUT = 180
DOWNLOAD_TIMEOUT = 300
RETRY_INTERVAL = 8
MAX_SUBMIT_REQUEST_ERRORS = 3


def _aitgenne_v1_base(api_base: str = "") -> str:
    base = (api_base or DEFAULT_AITGENNE_API_BASE).strip().rstrip("/")
    if base.endswith("/v1/images/generations"):
        return base[: -len("/images/generations")]
    if base.endswith("/v1/images/edits"):
        return base[: -len("/images/edits")]
    if base.endswith("/v1"):
        return base
    return f"{base}/v1"


def aitgenne_images_endpoint(api_base: str = "", *, edit: bool = False) -> str:
    suffix = "edits" if edit else "generations"
    return f"{_aitgenne_v1_base(api_base)}/images/{suffix}"


def submit_aitgenne_image_generation(
    config: Dict[str, str],
    prompt: str,
    *,
    input_mode: str = "text-to-image",
    image_path: str = "",
    image_url: str = "",
    reference_image_paths: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    size: str = DEFAULT_AITGENNE_IMAGE_SIZE,
    aspect_ratio: str = DEFAULT_AITGENNE_ASPECT_RATIO,
    post: Callable[..., Any] = requests.post,
) -> Dict[str, Any]:
    if not config.get("api_key"):
        raise ValueError("Aitgenne 图片生成缺少 API Key")
    references = [path for path in (reference_image_paths or []) if path]
    edit_paths = [path for path in [image_path] if path] + references
    if edit_paths:
        return _submit_aitgenne_image_edit(
            config,
            prompt,
            edit_paths,
            metadata=metadata,
            size=size,
            aspect_ratio=aspect_ratio,
            post=post,
        )

    url = aitgenne_images_endpoint(config.get("api_base") or DEFAULT_AITGENNE_API_BASE)
    submit_metadata = adapt_image_metadata(
        metadata,
        size=size or DEFAULT_AITGENNE_IMAGE_SIZE,
        aspect_ratio=aspect_ratio,
        default_aspect_ratio=DEFAULT_AITGENNE_ASPECT_RATIO,
    )
    payload = {
        "model": config.get("model") or DEFAULT_AITGENNE_IMAGE_MODEL,
        "prompt": prompt,
        "size": size or DEFAULT_AITGENNE_IMAGE_SIZE,
        "metadata": submit_metadata,
    }
    if input_mode:
        payload["input_mode"] = input_mode
    if image_url:
        payload["image_url"] = image_url
    headers = {
        "Authorization": f"Bearer {config['api_key']}",
        "Content-Type": "application/json",
    }
    last_error = None
    for attempt in range(1, MAX_SUBMIT_REQUEST_ERRORS + 1):
        try:
            resp = post(url, headers=headers, json=payload, timeout=SUBMIT_TIMEOUT)
            break
        except requests.RequestException as exc:
            last_error = exc
            if attempt >= MAX_SUBMIT_REQUEST_ERRORS:
                raise RuntimeError(f"Aitgenne 图片生成提交网络连续失败: error={exc}") from exc
            time.sleep(RETRY_INTERVAL)
    else:
        raise RuntimeError(f"Aitgenne 图片生成提交网络连续失败: error={last_error}")
    try:
        body = resp.json()
    except Exception:
        body = {"raw_text": resp.text[:1000]}
    if resp.status_code >= 400:
        raise RuntimeError(f"Aitgenne 图片生成提交失败: HTTP {resp.status_code}, body={str(body)[:1200]}")
    if not _result_has_image(body):
        raise RuntimeError(f"Aitgenne 图片生成未返回图片结果: {str(body)[:1200]}")
    return body


def _submit_aitgenne_image_edit(
    config: Dict[str, str],
    prompt: str,
    image_paths: List[str],
    *,
    metadata: Optional[Dict[str, Any]] = None,
    size: str = DEFAULT_AITGENNE_IMAGE_SIZE,
    aspect_ratio: str = DEFAULT_AITGENNE_ASPECT_RATIO,
    post: Callable[..., Any] = requests.post,
) -> Dict[str, Any]:
    url = aitgenne_images_endpoint(config.get("api_base") or DEFAULT_AITGENNE_API_BASE, edit=True)
    submit_metadata = adapt_image_metadata(
        metadata,
        size=size or DEFAULT_AITGENNE_IMAGE_SIZE,
        aspect_ratio=aspect_ratio,
        default_aspect_ratio=DEFAULT_AITGENNE_ASPECT_RATIO,
    )
    headers = {"Authorization": f"Bearer {config['api_key']}"}
    data = {
        "model": config.get("model") or DEFAULT_AITGENNE_IMAGE_MODEL,
        "prompt": prompt,
        "size": size or DEFAULT_AITGENNE_IMAGE_SIZE,
        "metadata": json.dumps(submit_metadata, ensure_ascii=False),
    }
    last_error = None
    for attempt in range(1, MAX_SUBMIT_REQUEST_ERRORS + 1):
        opened = []
        try:
            files = []
            for path in image_paths:
                image_file = open(path, "rb")
                opened.append(image_file)
                files.append(("image[]", (os.path.basename(path), image_file, "image/png")))
            resp = post(url, headers=headers, data=data, files=files, timeout=SUBMIT_TIMEOUT)
            break
        except requests.RequestException as exc:
            last_error = exc
            if attempt >= MAX_SUBMIT_REQUEST_ERRORS:
                raise RuntimeError(f"Aitgenne 图片编辑提交网络连续失败: error={exc}") from exc
            time.sleep(RETRY_INTERVAL)
        finally:
            for handle in opened:
                handle.close()
    else:
        raise RuntimeError(f"Aitgenne 图片编辑提交网络连续失败: error={last_error}")
    try:
        body = resp.json()
    except Exception:
        body = {"raw_text": resp.text[:1000]}
    if resp.status_code >= 400:
        raise RuntimeError(f"Aitgenne 图片编辑提交失败: HTTP {resp.status_code}, body={str(body)[:1200]}")
    if not _result_has_image(body):
        raise RuntimeError(f"Aitgenne 图片编辑未返回图片结果: {str(body)[:1200]}")
    return body


def _read_image_b64(path: str) -> str:
    with open(path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("ascii")


def _result_items(data: Dict[str, Any]) -> list:
    items = data.get("data")
    if isinstance(items, list):
        return [item for item in items if isinstance(item, dict)]
    nested = data.get("result") if isinstance(data.get("result"), dict) else {}
    items = nested.get("data")
    if isinstance(items, list):
        return [item for item in items if isinstance(item, dict)]
    return []


def _result_has_image(data: Dict[str, Any]) -> bool:
    return bool(extract_aitgenne_image_url(data) or extract_aitgenne_image_b64(data))


def extract_aitgenne_image_url(data: Dict[str, Any]) -> str:
    candidates = [data.get("url"), data.get("image_url"), data.get("result_url")]
    nested = data.get("data") if isinstance(data.get("data"), dict) else {}
    candidates.extend([nested.get("url"), nested.get("image_url"), nested.get("result_url")])
    for item in _result_items(data):
        candidates.extend([item.get("url"), item.get("image_url"), item.get("result_url")])
    for value in candidates:
        if isinstance(value, str) and value.startswith("http"):
            return value
    return ""


def extract_aitgenne_image_b64(data: Dict[str, Any]) -> str:
    candidates = [data.get("b64_json"), data.get("image_base64")]
    nested = data.get("data") if isinstance(data.get("data"), dict) else {}
    candidates.extend([nested.get("b64_json"), nested.get("image_base64")])
    for item in _result_items(data):
        candidates.extend([item.get("b64_json"), item.get("image_base64")])
    for value in candidates:
        text = extract_text(value).strip()
        if text:
            return text
    return ""


def save_aitgenne_image_result(
    data: Dict[str, Any],
    out_path: str,
    *,
    get: Callable[..., Any] = requests.get,
) -> str:
    image_b64 = extract_aitgenne_image_b64(data)
    if image_b64:
        with open(out_path, "wb") as f:
            f.write(base64.b64decode(image_b64))
        return out_path
    image_url = extract_aitgenne_image_url(data)
    if image_url:
        resp = get(image_url, timeout=DOWNLOAD_TIMEOUT)
        resp.raise_for_status()
        with open(out_path, "wb") as f:
            f.write(resp.content)
        return out_path
    raise RuntimeError(f"Aitgenne 图片生成结果中没有可保存的图片: {str(data)[:1200]}")
