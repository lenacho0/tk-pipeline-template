#!/usr/bin/env python3
from __future__ import annotations

import base64
import os
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

from common import extract_text
from media_specs import adapt_image_metadata

DEFAULT_OTU_API_BASE = "https://otuapi.com"
DEFAULT_OTU_IMAGE_MODEL = "gpt-image-2"
DEFAULT_OTU_IMAGE_SIZE = "1024x1024"
DEFAULT_ASPECT_RATIO = "9:16"
MAX_OTU_IMAGE_REFERENCES = 5
SUBMIT_TIMEOUT = 180
POLL_TIMEOUT = 45
DOWNLOAD_TIMEOUT = 300
POLL_INTERVAL = 15
MAX_POLL_SECONDS = 2400
MAX_SUBMIT_REQUEST_ERRORS = 3
MAX_POLL_REQUEST_ERRORS = 8
QUEUED_ZERO_PROGRESS_TIMEOUT_SECONDS = 600


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
    result = data.get("result") if isinstance(data.get("result"), dict) else {}
    result_items = result.get("data") if isinstance(result.get("data"), list) else []
    if result_items and isinstance(result_items[0], dict):
        candidates.append(result_items[0].get("url"))
    for key in ("result_urls", "urls"):
        value = data.get(key) or nested.get(key)
        if isinstance(value, list) and value:
            candidates.append(value[0])
    for value in candidates:
        if isinstance(value, str) and value.startswith("http"):
            return value
    return ""


def _mime_type_for_image_path(path: str) -> str:
    suffix = os.path.splitext(path)[1].lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    return "image/png"


def _image_path_to_data_url(path: str) -> str:
    with open(path, "rb") as image_file:
        image_b64 = base64.b64encode(image_file.read()).decode("ascii")
    return f"data:{_mime_type_for_image_path(path)};base64,{image_b64}"


def _reference_priority(role: str, *, source: str, index: int) -> Tuple[int, int]:
    raw = (role or "").lower()
    if "product" in raw or "产品" in raw:
        return 0, index
    if source in {"image_path", "image_url"} or "primary" in raw or "首帧" in raw or "主参考" in raw:
        return 1, index
    if "model" in raw or "模特" in raw or "person" in raw or "human" in raw:
        return 2, index
    return 3, index


def _limited_reference_urls(
    metadata_urls: List[str],
    roles: List[str],
    *,
    image_url: str = "",
    image_path: str = "",
    reference_image_paths: Optional[List[str]] = None,
) -> List[str]:
    items: List[Dict[str, Any]] = []

    def append_item(url: str, role: str, source: str) -> None:
        if not url:
            return
        index = len(items)
        items.append({
            "url": url,
            "role": role,
            "source": source,
            "index": index,
        })

    for idx, url in enumerate(metadata_urls):
        append_item(url, roles[idx] if idx < len(roles) else "", "metadata_url")
    role_offset = len(metadata_urls)
    if image_url:
        append_item(image_url, roles[role_offset] if role_offset < len(roles) else "primary_reference", "image_url")
        role_offset += 1
    if image_path:
        append_item(_image_path_to_data_url(image_path), roles[role_offset] if role_offset < len(roles) else "primary_reference", "image_path")
        role_offset += 1
    for path in reference_image_paths or []:
        append_item(_image_path_to_data_url(path), roles[role_offset] if role_offset < len(roles) else "", "reference_image_path")
        role_offset += 1

    deduped: List[Dict[str, Any]] = []
    seen = set()
    for item in items:
        if item["url"] in seen:
            continue
        seen.add(item["url"])
        deduped.append(item)
    deduped.sort(key=lambda item: _reference_priority(item.get("role", ""), source=item.get("source", ""), index=int(item.get("index", 0))))
    return [item["url"] for item in deduped[:MAX_OTU_IMAGE_REFERENCES]]


def submit_otu_image_task(
    config: Dict[str, str],
    prompt: str,
    *,
    input_mode: str,
    image_path: str = "",
    image_url: str = "",
    reference_image_paths: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    size: str = DEFAULT_OTU_IMAGE_SIZE,
    aspect_ratio: str = "",
) -> Tuple[str, Dict[str, Any]]:
    url = f"{(config.get('api_base') or DEFAULT_OTU_API_BASE).rstrip('/')}/v1/videos"
    headers = {"Authorization": f"Bearer {config['api_key']}"}
    submit_metadata = adapt_image_metadata(
        metadata,
        size=size,
        aspect_ratio=aspect_ratio,
        default_aspect_ratio=DEFAULT_ASPECT_RATIO,
    )
    payload: Dict[str, Any] = {
        "model": config.get("model") or DEFAULT_OTU_IMAGE_MODEL,
        "prompt": prompt,
        "metadata": submit_metadata,
        "input_mode": input_mode,
        "size": size,
    }
    reference_image_paths = [path for path in (reference_image_paths or []) if path]
    reference_urls = _limited_reference_urls(
        list(submit_metadata.get("urls") or []) if isinstance(submit_metadata.get("urls"), list) else [],
        [extract_text(role).strip() for role in (submit_metadata.get("reference_roles") or [])] if isinstance(submit_metadata.get("reference_roles"), list) else [],
        image_url=image_url,
        image_path=image_path,
        reference_image_paths=reference_image_paths,
    )
    if reference_urls:
        submit_metadata["urls"] = reference_urls
    last_submit_error: Optional[requests.RequestException] = None
    for attempt in range(1, MAX_SUBMIT_REQUEST_ERRORS + 1):
        try:
            json_headers = dict(headers)
            json_headers["Content-Type"] = "application/json"
            resp = requests.post(url, headers=json_headers, json=payload, timeout=SUBMIT_TIMEOUT)
            break
        except requests.RequestException as exc:
            last_submit_error = exc
            if attempt >= MAX_SUBMIT_REQUEST_ERRORS:
                raise RuntimeError(f"OTU 图片任务提交网络连续失败: error={exc}") from exc
            time.sleep(POLL_INTERVAL)
    else:
        raise RuntimeError(f"OTU 图片任务提交网络连续失败: error={last_submit_error}")
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


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _float_or_none(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def poll_otu_image_task(
    config: Dict[str, str],
    task_id: str,
    *,
    queued_zero_progress_timeout_seconds: int = QUEUED_ZERO_PROGRESS_TIMEOUT_SECONDS,
    max_poll_seconds: int = MAX_POLL_SECONDS,
) -> Dict[str, Any]:
    url = f"{(config.get('api_base') or DEFAULT_OTU_API_BASE).rstrip('/')}/v1/videos/{task_id}"
    headers = {"Authorization": f"Bearer {config['api_key']}"}
    start = time.time()
    last_body: Dict[str, Any] = {}
    consecutive_request_errors = 0
    queued_zero_started_at: Optional[float] = None
    while time.time() - start < max_poll_seconds:
        try:
            resp = requests.get(url, headers=headers, timeout=POLL_TIMEOUT)
        except requests.RequestException as exc:
            consecutive_request_errors += 1
            last_body = {
                "poll_error": str(exc),
                "consecutive_request_errors": consecutive_request_errors,
            }
            if consecutive_request_errors > MAX_POLL_REQUEST_ERRORS:
                raise RuntimeError(f"OTU 图片任务轮询网络连续失败: task_id={task_id}, error={exc}") from exc
            time.sleep(POLL_INTERVAL)
            continue
        consecutive_request_errors = 0
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
        data = last_body.get("data") if isinstance(last_body.get("data"), dict) else {}
        result = last_body.get("result") if isinstance(last_body.get("result"), dict) else {}
        progress = _float_or_none(_first_present(
            last_body.get("progress"),
            data.get("progress"),
            result.get("progress"),
        ))
        created_at = _float_or_none(_first_present(
            last_body.get("created_at"),
            data.get("created_at"),
            result.get("created_at"),
        ))
        if status == "queued" and progress == 0:
            now = time.time()
            if (
                created_at is not None
                and now >= created_at
                and now - created_at >= queued_zero_progress_timeout_seconds
            ):
                raise TimeoutError(
                    "OTU 图片任务 queued progress=0 timeout: "
                    f"task_id={task_id}, status={status}, progress={int(progress)}, "
                    f"created_at={created_at}, last={str(last_body)[:1200]}"
                )
            if queued_zero_started_at is None:
                queued_zero_started_at = now
            elif now - queued_zero_started_at >= queued_zero_progress_timeout_seconds:
                raise TimeoutError(
                    "OTU 图片任务 queued progress=0 timeout: "
                    f"task_id={task_id}, status={status}, progress={int(progress)}, "
                    f"created_at={created_at}, last={str(last_body)[:1200]}"
                )
        else:
            queued_zero_started_at = None
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
