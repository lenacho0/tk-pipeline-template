#!/usr/bin/env python3
"""
003-3 脚本文档单镜头分镜视频生成。

用法:
  python3 tk_shot_video.py <script_doc_shot_record_id>
  python3 tk_shot_video.py <script_doc_shot_record_id> --dry-run
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

import requests
from google import genai
from google.genai import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (  # noqa: E402
    APP_TOKEN,
    TABLE_CONFIG,
    TABLE_SCRIPT_DOC_SHOTS,
    WORKSPACE,
    build_error_payload,
    extract_text,
    feishu_headers,
    get_feishu_token,
    log_event,
    safe_get_record,
    safe_list_records,
    safe_request,
    safe_update_record,
    with_retry,
)
from tk_shot_storyboard import build_image_to_video_prompt  # noqa: E402
from otu_image import (  # noqa: E402
    DEFAULT_ASPECT_RATIO as OTU_DEFAULT_ASPECT_RATIO,
    DEFAULT_OTU_API_BASE,
    DEFAULT_OTU_IMAGE_MODEL,
    DEFAULT_OTU_IMAGE_SIZE,
    download_otu_image_result,
    extract_otu_result_url,
    format_model_choice_for_display,
    image_model_write_value,
    is_default_model_choice,
    normalize_image_channel,
    normalize_image_model_choice,
    poll_otu_image_task,
    resolve_selected_image_model,
    split_prefixed_model_choice,
    submit_otu_image_task,
)


STAGE_NAME = "分镜视频生成-Veo"
OTU_STAGE_NAME = "分镜视频生成-OTU"
BASE_WORK_DIR = Path(WORKSPACE) / "shot_video_work"
DEFAULT_MODEL = "veo-3.1-fast-generate-preview"
DEFAULT_OTU_MODEL = "veo_3_1-fast-fl"
DEFAULT_SEEDDANCE_MODEL = "doubao-seedance-2-0-fast-260128"
DEFAULT_API_BASE = "https://aihubmix.com"
DEFAULT_GEMINI_API_BASE = "https://aihubmix.com/gemini"
DEFAULT_SIZE = "720p"
DEFAULT_OTU_SIZE = "720x1280"
DEFAULT_ASPECT_RATIO = "9:16"
DEFAULT_SECONDS = "8"
ALLOWED_SECONDS = {"4", "6", "8"}
POLL_INTERVAL = 15
MAX_POLL_SECONDS = 2400
SUBMIT_TIMEOUT = 180
POLL_TIMEOUT = 45
DOWNLOAD_TIMEOUT = 300

RecordGetter = Callable[[str, str, str], Dict[str, Any]]
RecordUpdater = Callable[[str, str, str, Dict[str, Any]], Any]
Downloader = Callable[[str, str], str]
Uploader = Callable[[str, str, str], str]
ReferenceDownloader = Callable[[str, str, Path], Path]
NativeClientFactory = Callable[[Dict[str, str]], Any]


def resolve_video_table(table: str = "script_doc") -> str:
    if table in ("script_doc", "script_doc_shots", TABLE_SCRIPT_DOC_SHOTS):
        if not TABLE_SCRIPT_DOC_SHOTS:
            raise ValueError("config.json 尚未配置 script_doc_shots 表 ID")
        return TABLE_SCRIPT_DOC_SHOTS
    raise ValueError("不再支持旧 shot_storyboard 表，请使用 script_doc")


def compact_json(value: Any, max_chars: int = 20000) -> str:
    text = json.dumps(value, ensure_ascii=False, indent=2, default=str)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 200] + "\n...TRUNCATED..."


def normalize_seconds(value: Any) -> str:
    raw = extract_text(value).strip()
    digits = "".join(ch for ch in raw if ch.isdigit())
    seconds = digits or DEFAULT_SECONDS
    return seconds if seconds in ALLOWED_SECONDS else DEFAULT_SECONDS


def normalize_video_provider(value: Any) -> str:
    raw = extract_text(value).strip().lower().replace("_", "-").replace(" ", "")
    if not raw or raw in {"待确认", "pending", "default", "默认", "默认（配置表）", "默认(配置表)", "配置表默认"}:
        return "veo3.1"
    if raw in {"seeddance", "seeddance2", "seeddance2.0", "seed-dance", "seed-dance-2.0", "seedance", "seedance2.0"}:
        return "seeddance2.0"
    if raw in {"veo", "veo3", "veo3.1", "veo-3.1"} or raw.startswith("veo-3.1") or raw.startswith("veo3.1"):
        return "veo3.1"
    return "veo3.1"


def normalize_video_channel(value: Any) -> str:
    raw = extract_text(value).strip().lower().replace("_", "-").replace(" ", "")
    if raw in {"otu", "otuapi", "otu-api", "outapi", "out-api", "便宜通道"}:
        return "OTU"
    return "AIHubMix"


def video_channel_write_value(channel: str) -> str:
    return "OTU" if normalize_video_channel(channel) == "OTU" else "AIHubMix"


def split_prefixed_model_choice(value: Any) -> Tuple[str, str]:
    raw = extract_text(value).strip()
    if " / " in raw:
        prefix, rest = raw.split(" / ", 1)
        channel = normalize_video_channel(prefix)
        return channel, rest.strip()
    return "", raw


def is_default_model_choice(value: Any) -> bool:
    raw = extract_text(value).strip().lower().replace("_", "-").replace(" ", "")
    return not raw or raw in {"待确认", "pending", "default", "默认", "默认（配置表）", "默认(配置表)", "配置表默认"}


def infer_model_channel(model_choice: Any) -> str:
    _, raw = split_prefixed_model_choice(model_choice)
    normalized = extract_text(raw).strip().lower().replace("_", "-").replace(" ", "")
    if normalized in {"gpt-image-2", "gpt-image-2-2k", "gpt-image-2-4k"}:
        return "OTU"
    if normalized == "veo_3_1-fast-fl":
        return "OTU"
    if normalized in {"veo3.1", "seeddance2.0", "veo-3.1-fast-generate-preview"}:
        return "AIHubMix"
    return ""


def format_model_choice_for_display(channel: str, model: str) -> str:
    base_channel = normalize_video_channel(channel)
    raw = extract_text(model).strip() or "默认（配置表）"
    if " / " in raw:
        return raw
    return f"{base_channel} / {raw}"


def resolve_selected_model(model_choice: Any, config: Dict[str, str], channel: str) -> str:
    choice_channel, raw = split_prefixed_model_choice(model_choice)
    if choice_channel and choice_channel != normalize_video_channel(channel):
        raise ValueError(f"视频通道={channel} 时不能选择 {choice_channel} 模型：{raw}")
    inferred_channel = infer_model_channel(raw)
    if inferred_channel and inferred_channel != normalize_video_channel(channel):
        raise ValueError(f"视频通道={channel} 与所选模型不匹配：{raw}")
    if is_default_model_choice(raw) or raw in {"veo3.1", "seeddance2.0"}:
        return config.get("model") or DEFAULT_MODEL
    return raw


def image_model_write_value(model: str, channel: str = "OTU") -> str:
    return format_model_choice_for_display(channel, normalize_image_model_choice(model))
def video_model_write_value(config: Dict[str, str], provider: str, table_id: str, channel: str = "AIHubMix") -> str:
    return format_model_choice_for_display(channel, config.get("model") or (DEFAULT_OTU_MODEL if normalize_video_channel(channel) == "OTU" else DEFAULT_MODEL))


def normalize_api_base(api_base: str) -> str:
    return (api_base or DEFAULT_API_BASE).rstrip("/")


def videos_url(api_base: str) -> str:
    base = normalize_api_base(api_base)
    if base.endswith("/v1"):
        return f"{base}/videos"
    if base.endswith("/v1/videos"):
        return base
    return f"{base}/v1/videos"


def video_item_url(api_base: str, task_id: str) -> str:
    return f"{videos_url(api_base).rstrip('/')}/{task_id}"


def video_content_url(api_base: str, task_id: str) -> str:
    return f"{video_item_url(api_base, task_id)}/content"


def get_model_config(stage_name: str = STAGE_NAME) -> Tuple[str, Dict[str, str]]:
    token = get_feishu_token()
    for rec in safe_list_records(token, TABLE_CONFIG):
        fields = rec.get("fields", {})
        if extract_text(fields.get("环节")).strip() == stage_name:
            cfg = {
                "model": extract_text(fields.get("模型名称")).strip() or DEFAULT_MODEL,
                "api_key": extract_text(fields.get("API Key")).strip(),
                "api_base": extract_text(fields.get("API 代理地址")).strip() or DEFAULT_API_BASE,
                "size": extract_text(fields.get("画面尺寸")).strip() or DEFAULT_SIZE,
                "aspect_ratio": extract_text(fields.get("画面比例")).strip() or DEFAULT_ASPECT_RATIO,
                "call_type": extract_text(fields.get("调用方式")).strip(),
            }
            if not cfg["api_key"]:
                raise ValueError(f"{stage_name} 缺少 API Key")
            return rec.get("record_id") or rec.get("id") or "", cfg
    raise ValueError(f"找不到模型配置: {stage_name}")


def resolve_model_config_stage(channel: str, provider: str) -> str:
    if normalize_video_channel(channel) == "OTU":
        return OTU_STAGE_NAME
    if provider == "seeddance2.0":
        return STAGE_NAME
    return STAGE_NAME


def resolve_image_model_config_stage(channel: str) -> str:
    return OTU_IMAGE_STAGE_NAME


def ensure_work_dir(record_id: str) -> Path:
    work_dir = BASE_WORK_DIR / record_id
    work_dir.mkdir(parents=True, exist_ok=True)
    return work_dir


def safe_filename_part(value: Any) -> str:
    text = extract_text(value).strip()
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("._-")


def resolve_shot_video_filename(record_id: str, fields: Dict[str, Any]) -> str:
    source_script_id = safe_filename_part(fields.get("源逐镜头脚本记录ID")) or safe_filename_part(record_id)
    shot_number_text = (
        extract_text(fields.get("分镜序号")).strip()
        or extract_text(fields.get("镜头序号")).strip()
        or extract_text(fields.get("Shot No")).strip()
    )
    match = re.search(r"\d+", shot_number_text)
    if not match:
        return f"{source_script_id}_video.mp4"
    return f"{source_script_id}_shot{int(match.group(0)):02d}_video.mp4"


def get_attachment_token(value: Any) -> str:
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict) and item.get("file_token"):
                return str(item.get("file_token")).strip()
    return ""


def resolve_voiceover_audio_dependency(fields: Dict[str, Any], provider: str) -> Dict[str, Any]:
    voiceover_text = extract_text(fields.get("口播文本")).strip()
    required = provider == "seeddance2.0" and bool(voiceover_text)
    status = extract_text(fields.get("口播音频状态")).strip()
    file_token = get_attachment_token(fields.get("口播音频"))
    local_path = extract_text(fields.get("口播音频路径")).strip()
    dependency = {
        "required": required,
        "status": status,
        "file_token": file_token,
        "local_path": local_path,
    }
    if required:
        if status != "成功":
            raise ValueError("SeedDance 2.0 有口播镜头必须先生成口播音频，要求 口播音频状态=成功")
        if not file_token and not local_path:
            raise ValueError("SeedDance 2.0 有口播镜头缺少可用口播音频：需要 口播音频 附件或 口播音频路径")
    return dependency


def download_feishu_media(token: str, file_token: str, save_path: Path) -> Path:
    url = f"https://open.feishu.cn/open-apis/drive/v1/medias/{file_token}/download"
    resp = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=DOWNLOAD_TIMEOUT, stream=True)
    if resp.status_code != 200:
        raise RuntimeError(f"飞书附件下载失败: HTTP {resp.status_code}, file_token={file_token}")
    with save_path.open("wb") as f:
        for chunk in resp.iter_content(8192):
            if chunk:
                f.write(chunk)
    if save_path.stat().st_size < 1000:
        raise RuntimeError(f"飞书附件下载结果过小: {save_path}")
    return save_path


def resolve_reference_image(
    token: str,
    record_id: str,
    fields: Dict[str, Any],
    work_dir: Path,
    *,
    download_fn: ReferenceDownloader = download_feishu_media,
) -> Path:
    file_token = get_attachment_token(fields.get("分镜图"))
    if not file_token:
        raise ValueError(f"003-3 {record_id} 缺少分镜图附件")
    return download_fn(token, file_token, work_dir / f"{record_id}_shot.png")


def is_end_frame_mode_enabled(fields: Dict[str, Any]) -> bool:
    raw = extract_text(fields.get("首尾帧视频模式")).strip().lower().replace(" ", "")
    return raw in {"启用", "是", "yes", "true", "1", "enabled", "enable"}


def resolve_last_frame_image(
    token: str,
    record_id: str,
    fields: Dict[str, Any],
    work_dir: Path,
    *,
    download_fn: ReferenceDownloader = download_feishu_media,
) -> Optional[Path]:
    if not is_end_frame_mode_enabled(fields):
        return None
    status = extract_text(fields.get("尾帧图生成状态")).strip()
    if status != "成功":
        raise ValueError("首尾帧视频模式已启用，必须先满足 尾帧图生成状态=成功")
    file_token = get_attachment_token(fields.get("尾帧图"))
    if not file_token:
        raise ValueError("首尾帧视频模式已启用，但缺少尾帧图附件")
    return download_fn(token, file_token, work_dir / f"{record_id}_last_frame.png")


def build_model_prompt(fields: Dict[str, Any]) -> str:
    prompt = extract_text(fields.get("视频提示词")).strip()
    if not prompt:
        raise ValueError("003-3 记录缺少视频提示词")
    return prompt


def _parse_shot_meta(fields: Dict[str, Any]) -> Dict[str, Any]:
    raw = extract_text(fields.get("文本")).strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def rebuild_model_prompt_for_provider(fields: Dict[str, Any], provider: str) -> str:
    meta = _parse_shot_meta(fields)
    shot = {
        "duration_sec": extract_text(fields.get("目标时长秒")).strip(),
        "visual": extract_text(fields.get("画面描述")).strip(),
        "camera": extract_text(meta.get("camera")).strip(),
        "action": extract_text(meta.get("action")).strip(),
        "emotion": extract_text(meta.get("emotion")).strip(),
        "speaker": extract_text(meta.get("speaker")).strip(),
        "speaker_visible": bool(meta.get("speaker_visible")),
        "continuity_notes": extract_text(fields.get("连续性要求")).strip(),
        "product_visibility": extract_text(fields.get("产品焦点")).strip(),
        "must_show": meta.get("must_show") if isinstance(meta.get("must_show"), list) else [],
        "forbidden": meta.get("forbidden") if isinstance(meta.get("forbidden"), list) else [],
    }
    return build_image_to_video_prompt(
        shot,
        idx=1,
        total_shots=1,
        product_name=extract_text(fields.get("产品名")).strip(),
        voiceover_text=extract_text(fields.get("口播文本")).strip(),
        voice_id=extract_text(fields.get("口播音色ID")).strip(),
        video_model=provider,
        screen_text=extract_text(meta.get("screen_text")).strip(),
        screen_text_zh=extract_text(meta.get("screen_text_zh")).strip(),
        video_prompt_notes=extract_text(meta.get("video_prompt_notes")).strip(),
    )


def resolve_model_prompt(fields: Dict[str, Any], provider: str) -> Tuple[str, bool]:
    prompt = build_model_prompt(fields)
    if provider == "seeddance2.0" and "使用参考音频作为最终口播内容" not in prompt:
        return rebuild_model_prompt_for_provider(fields, provider), True
    if provider == "veo3.1" and "使用参考音频作为最终口播内容" in prompt:
        return rebuild_model_prompt_for_provider(fields, provider), True
    return prompt, False


def submit_aihubmix_video_task(
    config: Dict[str, str],
    prompt: str,
    image_path: str,
    seconds: str,
    size: str = DEFAULT_SIZE,
    aspect_ratio: str = DEFAULT_ASPECT_RATIO,
) -> Tuple[str, Dict[str, Any]]:
    url = videos_url(config.get("api_base") or DEFAULT_API_BASE)
    headers = {"Authorization": f"Bearer {config['api_key']}"}
    with open(image_path, "rb") as image_file:
        files = {
            "prompt": (None, prompt),
            "model": (None, config.get("model") or DEFAULT_MODEL),
            "size": (None, size or DEFAULT_SIZE),
            "aspect_ratio": (None, aspect_ratio or DEFAULT_ASPECT_RATIO),
            "seconds": (None, seconds),
            "input_reference[]": (os.path.basename(image_path), image_file, "image/png"),
        }
        resp = requests.post(url, headers=headers, files=files, timeout=SUBMIT_TIMEOUT)
    try:
        body = resp.json()
    except Exception:
        body = {"raw_text": resp.text[:1000]}
    if resp.status_code >= 400:
        raise RuntimeError(f"AIHubMix 视频任务提交失败: HTTP {resp.status_code}, body={str(body)[:1200]}")
    task_id = extract_text(
        body.get("id")
        or body.get("task_id")
        or (body.get("data") or {}).get("id")
        or (body.get("data") or {}).get("task_id")
    ).strip()
    if not task_id:
        raise RuntimeError(f"AIHubMix 视频任务提交未返回任务 ID: {str(body)[:1200]}")
    return task_id, body


def submit_otu_video_task(
    config: Dict[str, str],
    prompt: str,
    image_path: str,
    seconds: str,
    size: str = DEFAULT_OTU_SIZE,
    aspect_ratio: str = DEFAULT_ASPECT_RATIO,
    *,
    last_frame_path: Optional[str] = None,
) -> Tuple[str, Dict[str, Any]]:
    url = videos_url(config.get("api_base") or DEFAULT_OTU_API_BASE)
    model_name = config.get("model") or DEFAULT_OTU_MODEL
    headers = {"Authorization": f"Bearer {config['api_key']}"}
    with open(image_path, "rb") as image_file:
        files = [("input_reference[]", (os.path.basename(image_path), image_file, "image/png"))]
        last_file = open(last_frame_path, "rb") if last_frame_path else None
        try:
            if last_file:
                files.append(("input_reference[]", (os.path.basename(last_frame_path), last_file, "image/png")))
            data = {
                "model": model_name,
                "prompt": prompt,
                "seconds": seconds,
                "size": size or DEFAULT_OTU_SIZE,
                "aspect_ratio": aspect_ratio or DEFAULT_ASPECT_RATIO,
            }
            resp = requests.post(url, headers=headers, data=data, files=files, timeout=SUBMIT_TIMEOUT)
        finally:
            if last_file:
                last_file.close()
    try:
        body = resp.json()
    except Exception:
        body = {"raw_text": resp.text[:1000]}
    if resp.status_code >= 400:
        raise RuntimeError(f"OTU 视频任务提交失败: HTTP {resp.status_code}, body={str(body)[:1200]}")
    task_id = extract_text(
        body.get("id")
        or body.get("task_id")
        or (body.get("data") or {}).get("id")
        or (body.get("data") or {}).get("task_id")
    ).strip()
    if not task_id:
        raise RuntimeError(f"OTU 视频任务提交未返回任务 ID: {str(body)[:1200]}")
    return task_id, body


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


def poll_aihubmix_video_task(config: Dict[str, str], task_id: str) -> Dict[str, Any]:
    url = video_item_url(config.get("api_base") or DEFAULT_API_BASE, task_id)
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
            raise RuntimeError(f"AIHubMix 视频任务轮询失败: HTTP {resp.status_code}, body={str(last_body)[:1200]}")
        status = extract_text(
            last_body.get("status")
            or (last_body.get("data") or {}).get("status")
            or (last_body.get("result") or {}).get("status")
        ).lower()
        if status in {"completed", "succeeded", "success", "done"}:
            return last_body
        if status in {"failed", "error", "cancelled", "canceled"}:
            raise RuntimeError(f"AIHubMix 视频生成失败: {str(last_body)[:1500]}")
        time.sleep(POLL_INTERVAL)
    raise TimeoutError(f"AIHubMix 视频任务超时: task_id={task_id}, last={str(last_body)[:1200]}")


def poll_otu_video_task(config: Dict[str, str], task_id: str) -> Dict[str, Any]:
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
            raise RuntimeError(f"OTU 视频任务轮询失败: HTTP {resp.status_code}, body={str(last_body)[:1200]}")
        status = extract_text(
            last_body.get("status")
            or (last_body.get("data") or {}).get("status")
            or (last_body.get("result") or {}).get("status")
        ).lower()
        if status in {"completed", "succeeded", "success", "done"}:
            return last_body
        if status in {"failed", "error", "cancelled", "canceled"}:
            raise RuntimeError(f"OTU 视频生成失败: {str(last_body)[:1500]}")
        time.sleep(POLL_INTERVAL)
    raise TimeoutError(f"OTU 视频任务超时: task_id={task_id}, last={str(last_body)[:1200]}")


def iter_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from iter_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from iter_strings(item)


def extract_video_url(result: Dict[str, Any]) -> str:
    preferred_keys = ("video_url", "result_url", "download_url", "url")
    stack = [result]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for key in preferred_keys:
                val = cur.get(key)
                if isinstance(val, str) and val.startswith("http"):
                    return val
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)
    for text in iter_strings(result):
        if text.startswith("http") and (".mp4" in text or "/video/" in text or "videos-" in text):
            return text
    return ""


def download_video(video_url: str, save_path: str) -> str:
    resp = requests.get(video_url, timeout=DOWNLOAD_TIMEOUT, stream=True, allow_redirects=True)
    if resp.status_code != 200:
        raise RuntimeError(f"视频下载失败: HTTP {resp.status_code}, url={video_url[:300]}")
    with open(save_path, "wb") as f:
        for chunk in resp.iter_content(8192):
            if chunk:
                f.write(chunk)
    if os.path.getsize(save_path) < 10000:
        raise RuntimeError(f"视频下载成功但文件过小: {save_path}")
    return save_path


def download_video_content(config: Dict[str, str], task_id: str, save_path: str) -> str:
    url = video_content_url(config.get("api_base") or DEFAULT_API_BASE, task_id)
    headers = {"Authorization": f"Bearer {config['api_key']}"}
    resp = requests.get(url, headers=headers, timeout=DOWNLOAD_TIMEOUT, stream=True, allow_redirects=True)
    if resp.status_code != 200:
        raise RuntimeError(f"视频 content 下载失败: HTTP {resp.status_code}, task_id={task_id}")
    with open(save_path, "wb") as f:
        for chunk in resp.iter_content(8192):
            if chunk:
                f.write(chunk)
    if os.path.getsize(save_path) < 10000:
        raise RuntimeError(f"视频 content 下载成功但文件过小: {save_path}")
    return save_path


def native_veo_api_base(config: Dict[str, str]) -> str:
    base = normalize_api_base(config.get("api_base") or DEFAULT_GEMINI_API_BASE)
    if base.endswith("/gemini"):
        return base
    return DEFAULT_GEMINI_API_BASE


def get_native_veo_client(config: Dict[str, str]):
    return genai.Client(
        api_key=config["api_key"],
        http_options=types.HttpOptions(base_url=native_veo_api_base(config)),
    )


def call_native_veo_first_frame_task(
    config: Dict[str, str],
    prompt: str,
    image_path: str,
    seconds: str,
    size: str = DEFAULT_SIZE,
    aspect_ratio: str = DEFAULT_ASPECT_RATIO,
    *,
    last_frame_path: Optional[str] = None,
    client: Any = None,
):
    client = client or get_native_veo_client(config)
    with open(image_path, "rb") as image_file:
        first_frame = types.Image(image_bytes=image_file.read(), mime_type="image/png")
    last_frame = None
    if last_frame_path:
        with open(last_frame_path, "rb") as last_file:
            last_frame = types.Image(image_bytes=last_file.read(), mime_type="image/png")
    return client.models.generate_videos(
        model=config.get("model") or DEFAULT_MODEL,
        prompt=prompt,
        image=first_frame,
        config=types.GenerateVideosConfig(
            duration_seconds=int(normalize_seconds(seconds)),
            resolution=size or DEFAULT_SIZE,
            aspect_ratio=aspect_ratio or DEFAULT_ASPECT_RATIO,
            last_frame=last_frame,
        ),
    )


def operation_to_dict(operation: Any) -> Dict[str, Any]:
    if hasattr(operation, "model_dump"):
        return operation.model_dump(mode="json", by_alias=True, exclude_none=True)
    if isinstance(operation, dict):
        return operation
    result: Dict[str, Any] = {}
    for key in ("name", "done", "error", "metadata"):
        if hasattr(operation, key):
            result[key] = getattr(operation, key)
    response = getattr(operation, "response", None) or getattr(operation, "result", None)
    if response is not None:
        result["response"] = operation_to_dict(response)
    return result


def poll_native_veo_operation(client: Any, operation: Any) -> Any:
    start = time.time()
    current = operation
    original_operation_name = extract_text(getattr(operation, "name", "")).strip()
    while time.time() - start < MAX_POLL_SECONDS:
        if getattr(current, "done", False):
            if getattr(current, "error", None):
                raise RuntimeError(f"Veo 首帧视频生成失败: {compact_json(operation_to_dict(current), 1500)}")
            if not (getattr(current, "response", None) or getattr(current, "result", None)):
                raw_operation = fetch_native_veo_operation_dict(client, current, fallback_operation_name=original_operation_name)
                if raw_operation:
                    return raw_operation
            return current
        time.sleep(POLL_INTERVAL)
        try:
            current = client.operations.get(current)
        except Exception:
            raw_operation = fetch_native_veo_operation_dict(client, current, fallback_operation_name=original_operation_name)
            if raw_operation:
                return raw_operation
            raise
    raise TimeoutError(f"Veo 首帧视频任务超时: {getattr(operation, 'name', '')}")


def fetch_native_veo_operation_dict(client: Any, operation: Any, fallback_operation_name: str = "") -> Optional[Dict[str, Any]]:
    operation_name = fallback_operation_name or extract_text(getattr(operation, "name", "")).strip()
    if not operation_name or not hasattr(client.operations, "_get_videos_operation"):
        return None
    raw = client.operations._get_videos_operation(operation_name=operation_name)
    return raw if isinstance(raw, dict) else None


def _dict_get_first(mapping: Dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping:
            return mapping.get(key)
    return None


def extract_native_generated_video(operation: Any) -> Any:
    if isinstance(operation, dict):
        response = _dict_get_first(operation, "response", "result") or {}
        if not isinstance(response, dict):
            response = {}
        videos = _dict_get_first(response, "generated_videos", "generatedVideos", "videos")
        if not videos and isinstance(operation.get("videos"), list):
            videos = operation.get("videos")
        if not videos:
            raise RuntimeError(f"Veo 首帧视频生成完成但未返回视频: {compact_json(operation, 1500)}")
        generated = videos[0]
        if isinstance(generated, dict):
            return generated.get("video") or generated
        return generated

    response = getattr(operation, "response", None) or getattr(operation, "result", None)
    videos = getattr(response, "generated_videos", None) if response is not None else None
    if not videos:
        raise RuntimeError(f"Veo 首帧视频生成完成但未返回视频: {compact_json(operation_to_dict(operation), 1500)}")
    generated = videos[0]
    return getattr(generated, "video", None) or generated


def download_native_veo_video(client: Any, generated_video: Any, save_path: str) -> str:
    if isinstance(generated_video, dict):
        encoded = _dict_get_first(generated_video, "bytesBase64Encoded", "bytes_base64_encoded", "videoBytes", "video_bytes")
        if encoded:
            with open(save_path, "wb") as f:
                f.write(base64.b64decode(encoded))
            if os.path.getsize(save_path) < 10000:
                raise RuntimeError(f"Veo 首帧视频下载成功但文件过小: {save_path}")
            return save_path
        uri = extract_text(generated_video.get("uri")).strip()
        if uri:
            content = client.files.download(file=generated_video)
            with open(save_path, "wb") as f:
                f.write(content)
            if os.path.getsize(save_path) < 10000:
                raise RuntimeError(f"Veo 首帧视频下载成功但文件过小: {save_path}")
            return save_path
        raise RuntimeError(f"Veo 首帧视频缺少可下载内容: {compact_json(generated_video, 1000)}")

    video_bytes = getattr(generated_video, "video_bytes", None)
    if video_bytes:
        with open(save_path, "wb") as f:
            f.write(video_bytes)
        if os.path.getsize(save_path) < 10000:
            raise RuntimeError(f"Veo 首帧视频下载成功但文件过小: {save_path}")
        return save_path

    content = client.files.download(file=generated_video)
    with open(save_path, "wb") as f:
        f.write(content)
    if os.path.getsize(save_path) < 10000:
        raise RuntimeError(f"Veo 首帧视频下载成功但文件过小: {save_path}")
    return save_path


def native_generated_video_uri(generated_video: Any) -> str:
    if isinstance(generated_video, dict):
        return extract_text(generated_video.get("uri")).strip()
    return extract_text(getattr(generated_video, "uri", "")).strip()


def is_native_veo_operation_id(task_id: str) -> bool:
    raw = extract_text(task_id).strip()
    return raw.startswith("operations/") or "/operations/" in raw


def submit_seeddance_video_task(
    config: Dict[str, str],
    prompt: str,
    image_path: str,
    seconds: str,
    size: str = DEFAULT_SIZE,
    aspect_ratio: str = DEFAULT_ASPECT_RATIO,
) -> Tuple[str, Dict[str, Any]]:
    url = videos_url(config.get("api_base") or DEFAULT_API_BASE)
    model_name = config.get("model") or DEFAULT_SEEDDANCE_MODEL
    headers = {"Authorization": f"Bearer {config['api_key']}"}
    with open(image_path, "rb") as image_file:
        files = {"image": (os.path.basename(image_path), image_file, "image/png")}
        data = {
            "model": model_name,
            "prompt": prompt,
            "seconds": seconds,
            "size": size or DEFAULT_SIZE,
            "aspect_ratio": aspect_ratio or DEFAULT_ASPECT_RATIO,
        }
        resp = requests.post(url, headers=headers, data=data, files=files, timeout=SUBMIT_TIMEOUT)
    try:
        body = resp.json()
    except Exception:
        body = {"raw_text": resp.text[:1000]}
    if resp.status_code >= 400:
        raise RuntimeError(f"SeedDance 2.0 视频任务提交失败: HTTP {resp.status_code}, body={str(body)[:1200]}")
    task_id = extract_text(
        body.get("id")
        or body.get("task_id")
        or (body.get("data") or {}).get("id")
        or (body.get("data") or {}).get("task_id")
    ).strip()
    if not task_id:
        raise RuntimeError(f"SeedDance 2.0 视频任务提交未返回任务 ID: {str(body)[:1200]}")
    return task_id, body


def poll_seeddance_video_task(config: Dict[str, str], task_id: str) -> Dict[str, Any]:
    url = video_item_url(config.get("api_base") or DEFAULT_API_BASE, task_id)
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
            raise RuntimeError(f"SeedDance 2.0 视频任务轮询失败: HTTP {resp.status_code}, body={str(last_body)[:1200]}")
        status = extract_text(
            last_body.get("status")
            or (last_body.get("data") or {}).get("status")
            or (last_body.get("result") or {}).get("status")
        ).lower()
        if status in {"completed", "succeeded", "success", "done"}:
            return last_body
        if status in {"failed", "error", "cancelled", "canceled"}:
            raise RuntimeError(f"SeedDance 2.0 视频生成失败: {str(last_body)[:1500]}")
        time.sleep(POLL_INTERVAL)
    raise TimeoutError(f"SeedDance 2.0 视频任务超时: task_id={task_id}, last={str(last_body)[:1200]}")


def upload_video_to_feishu(token: str, file_path: str, file_name: str) -> str:
    with open(file_path, "rb") as f:
        resp = requests.post(
            "https://open.feishu.cn/open-apis/drive/v1/medias/upload_all",
            headers={"Authorization": f"Bearer {token}"},
            data={
                "file_name": file_name,
                "parent_type": "bitable_file",
                "parent_node": APP_TOKEN,
                "size": str(os.path.getsize(file_path)),
            },
            files={"file": (file_name, f, "video/mp4")},
            timeout=300,
        )
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"飞书视频上传失败: {data.get('msg') or data}")
    return data["data"]["file_token"]


def get_table_field_names(token: str, table_id: str) -> set:
    field_names = set()
    page_token = None
    while True:
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/fields?page_size=100"
        if page_token:
            url += f"&page_token={page_token}"
        data = safe_request("get", url, headers=feishu_headers(token), timeout=30, max_attempts=3, acceptable_codes=(0,))
        for item in data.get("data", {}).get("items", []) or []:
            name = item.get("field_name")
            if name:
                field_names.add(name)
        if not data.get("data", {}).get("has_more"):
            break
        page_token = data.get("data", {}).get("page_token")
    return field_names


def get_table_field_types(token: str, table_id: str) -> Dict[str, int]:
    field_types: Dict[str, int] = {}
    page_token = None
    while True:
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/fields?page_size=100"
        if page_token:
            url += f"&page_token={page_token}"
        data = safe_request("get", url, headers=feishu_headers(token), timeout=30, max_attempts=3, acceptable_codes=(0,))
        for item in data.get("data", {}).get("items", []) or []:
            name = item.get("field_name")
            if name:
                field_types[name] = int(item.get("type") or 0)
        if not data.get("data", {}).get("has_more"):
            break
        page_token = data.get("data", {}).get("page_token")
    return field_types


def format_url_field_value(url: str, field_type: int = 0) -> Any:
    if field_type == 15:
        return {"link": url, "text": url}
    return url


def filter_existing_fields(token: str, table_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    existing = get_table_field_names(token, table_id)
    return {key: value for key, value in fields.items() if key in existing}


def build_success_fields(
    config: Dict[str, str],
    task_id: str,
    result: Dict[str, Any],
    video_url: str,
    local_path: str,
    file_token: str,
    *,
    provider: str = "veo3.1",
    channel: str = "AIHubMix",
    table_id: str = "",
    field_types: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    fields = {
        "视频通道": video_channel_write_value(channel),
        "视频生成模型": video_model_write_value(config, provider, table_id, channel),
        "视频生成状态": "成功",
        "分镜视频": [{"file_token": file_token, "name": Path(local_path).name}],
        "本地视频路径": local_path,
        "分镜视频file_token": file_token,
        "视频任务ID": task_id,
        "视频生成原始响应JSON": compact_json(result),
        "视频错误信息": "",
        "视频生成时间": int(time.time() * 1000),
    }
    if video_url:
        fields["分镜视频URL"] = format_url_field_value(video_url, (field_types or {}).get("分镜视频URL", 0))
    return fields


def run_shot_video_generation(
    record_id: str,
    *,
    dry_run: bool = False,
    table: str = "script_doc",
    token: Optional[str] = None,
    get_record_fn: RecordGetter = safe_get_record,
    update_record_fn: RecordUpdater = safe_update_record,
    native_client_factory: NativeClientFactory = get_native_veo_client,
    native_submitter: Callable[..., Any] = call_native_veo_first_frame_task,
    native_poller: Callable[[Any, Any], Any] = poll_native_veo_operation,
    native_downloader: Callable[[Any, Any, str], str] = download_native_veo_video,
    seeddance_submitter: Callable[..., Tuple[str, Dict[str, Any]]] = submit_seeddance_video_task,
    seeddance_poller: Callable[[Dict[str, str], str], Dict[str, Any]] = poll_seeddance_video_task,
    seeddance_downloader: Downloader = download_video,
    otu_submitter: Callable[..., Tuple[str, Dict[str, Any]]] = submit_otu_video_task,
    otu_poller: Callable[[Dict[str, str], str], Dict[str, Any]] = poll_otu_video_task,
    otu_downloader: Downloader = download_video,
    uploader: Uploader = upload_video_to_feishu,
) -> Dict[str, Any]:
    table_id = resolve_video_table(table)
    token = token or get_feishu_token()
    fields = get_record_fn(token, table_id, record_id)
    status = extract_text(fields.get("视频生成状态")).strip()
    if status == "成功" and not dry_run:
        raise ValueError(f"003-3 {record_id} 已成功生成视频，拒绝重复生成")
    force_new_task = status == "待生成"

    channel = normalize_video_channel(fields.get("视频通道"))
    model_choice = extract_text(fields.get("视频生成模型")).strip()
    provider = normalize_video_provider(model_choice)
    cfg_record_id, config = get_model_config(resolve_model_config_stage(channel, provider))
    runtime_config = dict(config)
    runtime_config["model"] = resolve_selected_model(model_choice, config, channel)
    work_dir = ensure_work_dir(record_id)
    image_path = resolve_reference_image(token, record_id, fields, work_dir)
    last_frame_path = resolve_last_frame_image(token, record_id, fields, work_dir)
    if last_frame_path and provider != "veo3.1":
        raise ValueError("首尾帧视频模式仅支持 Veo 视频模型")
    prompt, prompt_rebuilt = resolve_model_prompt(fields, provider)
    seconds = normalize_seconds(fields.get("目标时长秒"))
    size = config.get("size") or (DEFAULT_OTU_SIZE if channel == "OTU" else DEFAULT_SIZE)
    aspect_ratio = config.get("aspect_ratio") or DEFAULT_ASPECT_RATIO
    output_filename = resolve_shot_video_filename(record_id, fields)
    output_path = str(work_dir / output_filename)
    voiceover_dependency = resolve_voiceover_audio_dependency(fields, provider)
    raw_existing_task_id = extract_text(fields.get("视频任务ID")).strip()
    existing_task_id = "" if force_new_task else raw_existing_task_id
    summary: Dict[str, Any] = {
        "record_id": record_id,
        "table_id": table_id,
        "dry_run": dry_run,
        "config_record_id": cfg_record_id,
        "video_channel": channel,
        "video_provider": provider,
        "model": runtime_config["model"],
        "api_base": native_veo_api_base(config) if channel == "AIHubMix" and provider == "veo3.1" else normalize_api_base(config.get("api_base") or (DEFAULT_OTU_API_BASE if channel == "OTU" else DEFAULT_API_BASE)),
        "first_frame_image_path": str(image_path),
        "end_frame_mode": bool(last_frame_path),
        "last_frame_image_path": str(last_frame_path) if last_frame_path else "",
        "voiceover_audio_dependency": voiceover_dependency,
        "prompt_rebuilt_for_provider": prompt_rebuilt,
        "prompt_chars": len(prompt),
        "seconds": seconds,
        "size": size,
        "aspect_ratio": aspect_ratio,
        "output_path": output_path,
    }
    if dry_run:
        summary["status"] = "dry_run_ready"
        return summary

    field_types = get_table_field_types(token, table_id) if update_record_fn is safe_update_record else {}

    task_id = ""
    try:
        if force_new_task and raw_existing_task_id:
            update_record_fn(token, table_id, record_id, filter_existing_fields(token, table_id, {
                "视频任务ID": "",
                "视频生成原始响应JSON": "",
            }))
        if prompt_rebuilt:
            update_record_fn(token, table_id, record_id, filter_existing_fields(token, table_id, {
                "视频提示词": prompt[:10000],
            }))
        if channel == "OTU":
            update_record_fn(token, table_id, record_id, filter_existing_fields(token, table_id, {
                "视频通道": video_channel_write_value(channel),
                "视频生成模型": video_model_write_value(runtime_config, provider, table_id, channel),
                "视频生成状态": "生成中",
                "视频错误信息": "准备提交 OTU 首帧图生视频任务...",
            }))
            if existing_task_id:
                task_id = existing_task_id
                result = otu_poller(runtime_config, task_id)
            else:
                task_id, submit_body = otu_submitter(runtime_config, prompt, str(image_path), seconds, size, aspect_ratio, last_frame_path=str(last_frame_path) if last_frame_path else None)
                update_record_fn(token, table_id, record_id, filter_existing_fields(token, table_id, {
                    "视频任务ID": task_id,
                    "视频生成原始响应JSON": compact_json({"submit": submit_body}),
                    "视频错误信息": f"已提交 OTU 图生视频任务，正在轮询。task_id={task_id}",
                }))
                result = otu_poller(runtime_config, task_id)
            video_url = extract_video_url(result)
            if not video_url:
                raise RuntimeError(f"OTU 生成完成但未返回可下载视频 URL: {compact_json(result, 1200)}")
            otu_downloader(video_url, output_path)
            video_file_token = uploader(token, output_path, output_filename)
            success_fields = build_success_fields(config, task_id, result, video_url, output_path, video_file_token, provider=provider, channel=channel, table_id=table_id, field_types=field_types)
            update_record_fn(token, table_id, record_id, filter_existing_fields(token, table_id, success_fields))
            summary.update({
                "status": "success",
                "task_id": task_id,
                "video_url": video_url,
                "video_file_token": video_file_token,
                "output_size": os.path.getsize(output_path),
            })
            return summary

        if provider == "seeddance2.0":
            update_record_fn(token, table_id, record_id, filter_existing_fields(token, table_id, {
                "视频通道": video_channel_write_value(channel),
                "视频生成模型": video_model_write_value(runtime_config, provider, table_id, channel),
                "视频生成状态": "生成中",
                "视频错误信息": "准备提交 SeedDance 2.0 首帧图生视频任务；如有口播，已要求参考音频先生成成功。",
            }))
            task_id, submit_body = seeddance_submitter(runtime_config, prompt, str(image_path), seconds, size, aspect_ratio)
            update_record_fn(token, table_id, record_id, filter_existing_fields(token, table_id, {
                "视频任务ID": task_id,
                "视频生成原始响应JSON": compact_json({"submit": submit_body}),
                "视频错误信息": f"已提交 SeedDance 2.0 图生视频任务，正在轮询。task_id={task_id}",
            }))
            result = seeddance_poller(runtime_config, task_id)
            video_url = extract_video_url(result)
            if not video_url:
                raise RuntimeError(f"SeedDance 2.0 生成完成但未返回可下载视频 URL: {compact_json(result, 1200)}")
            seeddance_downloader(video_url, output_path)
            video_file_token = uploader(token, output_path, output_filename)
            success_fields = build_success_fields(config, task_id, result, video_url, output_path, video_file_token, provider=provider, channel=channel, table_id=table_id, field_types=field_types)
            update_record_fn(token, table_id, record_id, filter_existing_fields(token, table_id, success_fields))
            summary.update({
                "status": "success",
                "task_id": task_id,
                "video_url": video_url,
                "video_file_token": video_file_token,
                "output_size": os.path.getsize(output_path),
            })
            return summary

        update_record_fn(token, table_id, record_id, filter_existing_fields(token, table_id, {
            "视频通道": video_channel_write_value(channel),
            "视频生成模型": video_model_write_value(runtime_config, provider, table_id, channel),
            "视频生成状态": "生成中",
            "视频错误信息": "准备提交 AIHubMix Gemini/Veo 首帧视频任务...",
        }))
        client = native_client_factory(runtime_config)
        if existing_task_id and is_native_veo_operation_id(existing_task_id):
            task_id = existing_task_id
            operation = types.GenerateVideosOperation(name=existing_task_id)
            update_record_fn(token, table_id, record_id, filter_existing_fields(token, table_id, {
                "视频通道": video_channel_write_value(channel),
                "视频生成模型": video_model_write_value(runtime_config, provider, table_id, channel),
                "视频生成状态": "生成中",
                "视频错误信息": f"检测到已有 AIHubMix Gemini/Veo operation，复用并继续轮询下载。task_id={task_id}",
            }))
        else:
            if existing_task_id:
                update_record_fn(token, table_id, record_id, filter_existing_fields(token, table_id, {
                    "视频任务ID": "",
                    "视频错误信息": f"旧视频任务ID不是 Gemini/Veo operation，已忽略并重新提交。old_task_id={existing_task_id}",
                }))
            operation = native_submitter(runtime_config, prompt, str(image_path), seconds, size, aspect_ratio, last_frame_path=str(last_frame_path) if last_frame_path else None, client=client)
            task_id = extract_text(getattr(operation, "name", "")).strip()
            if not task_id:
                raise RuntimeError(f"Veo 首帧视频任务提交未返回 operation name: {compact_json(operation_to_dict(operation), 1200)}")
            update_record_fn(token, table_id, record_id, filter_existing_fields(token, table_id, {
                "视频任务ID": task_id,
                "视频生成原始响应JSON": compact_json({"submit": operation_to_dict(operation)}),
                "视频错误信息": f"已提交 AIHubMix Gemini/Veo 首帧视频任务，正在轮询。task_id={task_id}",
            }))
        completed_operation = native_poller(client, operation)
        generated_video = extract_native_generated_video(completed_operation)
        result = operation_to_dict(completed_operation)
        video_url = native_generated_video_uri(generated_video)
        try:
            native_downloader(client, generated_video, output_path)
        except Exception as download_exc:
            raw_operation = fetch_native_veo_operation_dict(client, completed_operation, fallback_operation_name=task_id)
            if not raw_operation:
                raise download_exc
            generated_video = extract_native_generated_video(raw_operation)
            result = raw_operation
            video_url = native_generated_video_uri(generated_video)
            native_downloader(client, generated_video, output_path)
        video_file_token = uploader(token, output_path, output_filename)
        success_fields = build_success_fields(config, task_id, result, video_url, output_path, video_file_token, provider=provider, channel=channel, table_id=table_id, field_types=field_types)
        update_record_fn(token, table_id, record_id, filter_existing_fields(token, table_id, success_fields))
        summary.update({
            "status": "success",
            "task_id": task_id,
            "video_url": video_url,
            "video_file_token": video_file_token,
            "output_size": os.path.getsize(output_path),
        })
        return summary
    except Exception as exc:
        payload = build_error_payload(exc, stage="generate_shot_video")
        error_message = f"错误[{payload['error_code']}]: {payload['message']}"
        try:
            update_record_fn(token, table_id, record_id, filter_existing_fields(token, table_id, {
                "视频生成状态": "失败",
                "视频任务ID": task_id,
                "视频错误信息": error_message[:1000],
            }))
        except Exception:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="003-3 单镜头 AIHubMix/Veo 分镜视频生成")
    parser.add_argument("record_id", help="003-3 script_doc_shots record_id")
    parser.add_argument("--table", default="script_doc", choices=["script_doc"], help="选择来源表")
    parser.add_argument("--dry-run", action="store_true", help="只验证输入和配置，不提交视频任务")
    parser.add_argument("--output-file", help="保存运行摘要 JSON")
    args = parser.parse_args()
    try:
        result = run_shot_video_generation(args.record_id, dry_run=args.dry_run, table=args.table)
        text = compact_json(result)
        print(text)
        if args.output_file:
            Path(args.output_file).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output_file).write_text(text, encoding="utf-8")
        return 0
    except Exception as exc:
        payload = build_error_payload(exc, stage="generate_shot_video")
        log_event("ERROR", "shot video task failed", record_id=args.record_id, error=payload["message"], error_code=payload["error_code"])
        print(f"ERROR_CODE={payload['error_code']} RETRYABLE={str(payload['retryable']).lower()} MESSAGE={payload['message']}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
