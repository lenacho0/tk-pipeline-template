#!/usr/bin/env python3
from __future__ import annotations

import base64
import os
import time
from typing import Any, Dict, Optional, Tuple

import requests

from common import extract_text

DEFAULT_OTU_API_BASE = "https://otuapi.com"
DEFAULT_OTU_IMAGE_MODEL = "gpt-image-2"
DEFAULT_OTU_IMAGE_SIZE = "1024x1024"
DEFAULT_ASPECT_RATIO = "9:16"
SUBMIT_TIMEOUT = 180
POLL_TIMEOUT = 45
DOWNLOAD_TIMEOUT = 300
POLL_INTERVAL = 15
MAX_POLL_SECONDS = 2400


def normalize_image_channel(value: Any) -> str:
    raw = extract_text(value).strip().lower().replace("_", "-").replace(" ", "")
    if raw in {"otu", "otuapi", "otu-api", "outapi", "out-api", "便宜通道"}:
        return "OTU"
    return "AIHubMix"


def normalize_image_model_choice(value: Any) -> str:
    raw = extract_text(value).strip().lower().replace("_", "-").replace(" ", "")
    if raw in {"gpt-image-2", "gptimage2"}:
        return "gpt-image-2"
    if raw in {"gpt-image-2-2k", "gptimage22k"}:
        return "gpt-image-2-2K"
    if raw in {"gpt-image-2-4k", "gptimage24k"}:
        return "gpt-image-2-4K"
    if raw in {"待确认", "pending", "default", "默认", "默认（配置表）", "默认(配置表)", "配置表默认", ""}:
        return DEFAULT_OTU_IMAGE_MODEL
    return extract_text(value).strip()


def split_prefixed_model_choice(value: Any) -> Tuple[str, str]:
    raw = extract_text(value).strip()
    if " / " in raw:
        prefix, rest = raw.split(" / ", 1)
        return normalize_image_channel(prefix), rest.strip()
    return "", raw


def is_default_model_choice(value: Any) -> bool:
    raw = extract_text(value).strip().lower().replace("_", "-").replace(" ", "")
    return not raw or raw in {"待确认", "pending", "default", "默认", "默认（配置表）", "默认(配置表)", "配置表默认"}


def format_model_choice_for_display(channel: str, model: str) -> str:
    base_channel = normalize_image_channel(channel)
    raw = extract_text(model).strip() or "默认（配置表）"
    if " / " in raw:
        return raw
    return f"{base_channel} / {raw}"


def resolve_selected_image_model(model_choice: Any, config: Dict[str, str], channel: str) -> str:
    choice_channel, raw = split_prefixed_model_choice(model_choice)
    if choice_channel and choice_channel != normalize_image_channel(channel):
        raise ValueError(f"图片通道={channel} 时不能选择 {choice_channel} 模型：{raw}")
    if normalize_image_channel(raw) != normalize_image_channel(channel) and raw in {"gpt-image-2", "gpt-image-2-2K", "gpt-image-2-4K"}:
        raise ValueError(f"图片通道={channel} 与所选模型不匹配：{raw}")
    return normalize_image_model_choice(raw) if not is_default_model_choice(raw) else config.get("model") or DEFAULT_OTU_IMAGE_MODEL


def image_model_write_value(model: str, channel: str = "OTU") -> str:
    return format_model_choice_for_display(channel, normalize_image_model_choice(model))


def extract_otu_result_url(data: Dict[str, Any]) -> str:
    candidates = [
        data.get("video_url"),
        data.get("result_url"),
        data.get("url"),
        data.get("download_url"),
    ]
    nested = data.get("data") if isinstance(data.get("data"), dict) else {}
    candidates.extend([nested.get("video_url"), nested.get("result_url"), nested.get("url"), nested.get("download_url")])
    for key in ("result_urls", "urls"):
        value = data.get(key) or nested.get(key)
        if isinstance(value, list) and value:
            candidates.append(value[0])
    for value in candidates:
        if isinstance(value, str) and value.startswith("http"):
            return value
    return ""


def submit_otu_image_task(
    config: Dict[str, str],
    prompt: str,
    *,
    input_mode: str,
    image_path: str = "",
    image_url: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    size: str = DEFAULT_OTU_IMAGE_SIZE,
) -> Tuple[str, Dict[str, Any]]:
    url = f"{(config.get('api_base') or DEFAULT_OTU_API_BASE).rstrip('/')}/v1/videos"
    headers = {
        "Authorization": f"Bearer {config['api_key']}",
        "Content-Type": "application/json",
    }
    submit_metadata = {"aspectRatio": DEFAULT_ASPECT_RATIO}
    if metadata:
        submit_metadata.update(metadata)
    payload: Dict[str, Any] = {
        "model": config.get("model") or DEFAULT_OTU_IMAGE_MODEL,
        "prompt": prompt,
        "metadata": submit_metadata,
        "input_mode": input_mode,
        "size": size,
    }
    if image_url:
        payload["image_url"] = image_url
    if image_path:
        with open(image_path, "rb") as image_file:
            payload["image_base64"] = base64.b64encode(image_file.read()).decode("ascii")
    resp = requests.post(url, headers=headers, json=payload, timeout=SUBMIT_TIMEOUT)
    try:
        body = resp.json()
    except Exception:
        body = {"raw_text": resp.text[:1000]}
    if resp.status_code >= 400:
        raise RuntimeError(f"OTU 图片任务提交失败: HTTP {resp.status_code}, body={str(body)[:1200]}")
    task_id = extract_text(
        body.get("id")
        or body.get("task_id")
        or (body.get("data") or {}).get("id")
        or (body.get("data") or {}).get("task_id")
    ).strip()
    if not task_id:
        url_result = extract_otu_result_url(body)
        if url_result:
            return "", body
        raise RuntimeError(f"OTU 图片任务提交未返回任务 ID: {str(body)[:1200]}")
    return task_id, body


def poll_otu_image_task(config: Dict[str, str], task_id: str) -> Dict[str, Any]:
    url = f"{(config.get('api_base') or DEFAULT_OTU_API_BASE).rstrip('/')}/v1/videos/{task_id}"
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
            raise RuntimeError(f"OTU 图片任务轮询失败: HTTP {resp.status_code}, body={str(last_body)[:1200]}")
        status = extract_text(
            last_body.get("status")
            or (last_body.get("data") or {}).get("status")
            or (last_body.get("result") or {}).get("status")
        ).lower()
        if status in {"completed", "succeeded", "success", "done"} or extract_otu_result_url(last_body):
            return last_body
        if status in {"failed", "error", "cancelled", "canceled"}:
            raise RuntimeError(f"OTU 图片生成失败: {str(last_body)[:1500]}")
        time.sleep(POLL_INTERVAL)
    raise TimeoutError(f"OTU 图片任务超时: task_id={task_id}, last={str(last_body)[:1200]}")


def download_otu_image_result(result_url: str, save_path: str) -> str:
    resp = requests.get(result_url, timeout=DOWNLOAD_TIMEOUT, stream=True, allow_redirects=True)
    if resp.status_code != 200:
        raise RuntimeError(f"OTU 图片下载失败: HTTP {resp.status_code}, url={result_url[:300]}")
    with open(save_path, "wb") as f:
        for chunk in resp.iter_content(8192):
            if chunk:
                f.write(chunk)
    if os.path.getsize(save_path) < 10000:
        raise RuntimeError(f"OTU 图片下载成功但文件过小: {save_path}")
    return save_path
