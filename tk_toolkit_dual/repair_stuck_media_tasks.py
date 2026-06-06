#!/usr/bin/env python3
"""
一次性修复卡住的生图/生视频记录。

默认 dry-run 只输出计划；加 --write 才会下载、上传附件并写回飞书。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import repair_stuck_video_tasks as video_repair  # noqa: E402
import tk_first_last_video as first_last  # noqa: E402
import tk_multi_role_first_last as multi_role  # noqa: E402
import tk_nine_grid_video as nine_grid  # noqa: E402
import tk_script_doc_shots as script_doc  # noqa: E402
from common import (  # noqa: E402
    WORKSPACE,
    build_error_payload,
    extract_text,
    get_feishu_token,
    safe_list_records,
    safe_update_record,
    upload_image_to_feishu,
)
from otu_image import download_otu_image_result, extract_otu_result_url  # noqa: E402
from tk_shot_video import (  # noqa: E402
    download_video,
    extract_video_url,
    format_url_field_value,
    get_table_field_types,
    upload_video_to_feishu,
    video_item_url,
)


TARGET_STATUSES = {"待生成", "生成中", "失败"}
RUNNING_UPSTREAM_STATUSES = {"queued", "in_progress", "processing", "pending", "running", "submitted"}
TERMINAL_FAILED_STATUSES = {"failed", "error", "cancelled", "canceled"}
COMPLETED_STATUSES = {"completed", "succeeded", "success", "done"}
URL_RE = re.compile(r"https?://[^\s'\",\])>}]+")
RETRY_STATE_FILE = Path(__file__).with_name(".retry_state.ryan.json")
DEAD_LETTER_FILE = Path(__file__).with_name(".dead_letter_tasks.ryan.json")


@dataclass(frozen=True)
class MediaSpec:
    key: str
    label: str
    media_type: str
    table_id: str
    script: str
    action: str
    status_field: str
    attachment_field: str
    task_id_field: str
    error_field: str
    filter_fn: Callable[[str, str, Dict[str, Any]], Dict[str, Any]]
    file_suffix: str
    file_ext: str
    file_token_field: str = ""
    local_path_field: str = ""
    url_field: str = ""
    operation_field: str = ""
    success_review_field: str = ""
    success_review_value: str = "待确认"


def _media_specs() -> Dict[str, MediaSpec]:
    return {
        "first_last_first_frame": MediaSpec(
            key="first_last_first_frame",
            label="首尾帧首帧图",
            media_type="image",
            table_id=first_last.TABLE_FIRST_LAST_VIDEO,
            script="tk_first_last_video.py",
            action="first-frame",
            status_field="首帧图生成状态",
            attachment_field="首帧图",
            file_token_field="首帧图file_token",
            local_path_field="首帧图本地路径",
            task_id_field="首帧图任务ID",
            error_field="首帧图错误信息",
            filter_fn=first_last.filter_existing_fields,
            file_suffix="first_frame",
            file_ext=".png",
            success_review_field="首帧审核状态",
        ),
        "first_last_last_frame": MediaSpec(
            key="first_last_last_frame",
            label="首尾帧尾帧图",
            media_type="image",
            table_id=first_last.TABLE_FIRST_LAST_VIDEO,
            script="tk_first_last_video.py",
            action="last-frame",
            status_field="尾帧图生成状态",
            attachment_field="尾帧图",
            file_token_field="尾帧图file_token",
            local_path_field="尾帧图本地路径",
            task_id_field="尾帧图任务ID",
            error_field="尾帧图错误信息",
            filter_fn=first_last.filter_existing_fields,
            file_suffix="last_frame",
            file_ext=".png",
            success_review_field="尾帧审核状态",
        ),
        "first_last_video": MediaSpec(
            key="first_last_video",
            label="首尾帧视频",
            media_type="video",
            table_id=first_last.TABLE_FIRST_LAST_VIDEO,
            script="tk_first_last_video.py",
            action="video",
            status_field="视频生成状态",
            attachment_field="首尾帧视频",
            file_token_field="首尾帧视频file_token",
            local_path_field="本地视频路径",
            task_id_field="视频任务ID",
            error_field="视频错误信息",
            url_field="首尾帧视频URL",
            filter_fn=first_last.filter_existing_fields,
            file_suffix="first_last_video",
            file_ext=".mp4",
        ),
        "nine_grid_reference": MediaSpec(
            key="nine_grid_reference",
            label="九宫格参考图",
            media_type="image",
            table_id=nine_grid.TABLE_NINE_GRID_VIDEO,
            script="tk_nine_grid_video.py",
            action="reference",
            status_field="参考图生成状态",
            attachment_field="参考图",
            file_token_field="参考图file_token",
            local_path_field="参考图本地路径",
            task_id_field="参考图任务ID",
            error_field="参考图错误信息",
            filter_fn=nine_grid.filter_existing_fields,
            file_suffix="reference",
            file_ext=".png",
            success_review_field="参考图审核状态",
        ),
        "nine_grid_image": MediaSpec(
            key="nine_grid_image",
            label="九宫格图",
            media_type="image",
            table_id=nine_grid.TABLE_NINE_GRID_VIDEO,
            script="tk_nine_grid_video.py",
            action="image",
            status_field="图片生成状态",
            attachment_field="九宫格图",
            task_id_field="图片任务ID",
            error_field="图片错误信息",
            filter_fn=nine_grid.filter_existing_fields,
            file_suffix="nine_grid",
            file_ext=".png",
        ),
        "nine_grid_video": MediaSpec(
            key="nine_grid_video",
            label="九宫格视频",
            media_type="video",
            table_id=nine_grid.TABLE_NINE_GRID_VIDEO,
            script="tk_nine_grid_video.py",
            action="video",
            status_field="视频生成状态",
            attachment_field="分镜视频",
            local_path_field="视频本地路径",
            task_id_field="视频任务ID",
            error_field="视频错误信息",
            url_field="分镜视频URL",
            filter_fn=nine_grid.filter_existing_fields,
            file_suffix="nine_grid_video",
            file_ext=".mp4",
        ),
        "multi_role_reference": MediaSpec(
            key="multi_role_reference",
            label="多角色参考图",
            media_type="image",
            table_id=multi_role.TABLE_MULTI_ROLE_FIRST_LAST,
            script="tk_multi_role_first_last.py",
            action="reference-image",
            status_field="参考图生成状态",
            attachment_field="参考图",
            file_token_field="参考图file_token",
            local_path_field="参考图本地路径",
            task_id_field="参考图任务ID",
            error_field="参考图错误信息",
            filter_fn=multi_role.filter_existing_fields,
            file_suffix="reference",
            file_ext=".png",
            success_review_field="参考图审核状态",
        ),
        "multi_role_keyframe": MediaSpec(
            key="multi_role_keyframe",
            label="多角色关键帧图",
            media_type="image",
            table_id=multi_role.TABLE_MULTI_ROLE_FIRST_LAST,
            script="tk_multi_role_first_last.py",
            action="keyframe-image",
            status_field="关键帧生成状态",
            attachment_field="关键帧图",
            file_token_field="关键帧图file_token",
            local_path_field="关键帧图本地路径",
            task_id_field="关键帧任务ID",
            error_field="关键帧错误信息",
            filter_fn=multi_role.filter_existing_fields,
            file_suffix="keyframe",
            file_ext=".png",
            success_review_field="关键帧审核状态",
        ),
        "multi_role_video": MediaSpec(
            key="multi_role_video",
            label="多角色视频片段",
            media_type="video",
            table_id=multi_role.TABLE_MULTI_ROLE_FIRST_LAST,
            script="tk_multi_role_first_last.py",
            action="video",
            status_field="视频生成状态",
            attachment_field="视频片段",
            file_token_field="视频片段file_token",
            local_path_field="视频本地路径",
            task_id_field="视频任务ID",
            error_field="视频错误信息",
            url_field="视频片段URL",
            operation_field="视频操作",
            filter_fn=multi_role.filter_existing_fields,
            file_suffix="multi_role_clip",
            file_ext=".mp4",
        ),
        "script_doc_reference": MediaSpec(
            key="script_doc_reference",
            label="脚本文档参考底图",
            media_type="image",
            table_id=script_doc.TABLE_SCRIPT_DOC_REFERENCE_ASSETS,
            script="tk_script_doc_shots.py",
            action="reference-image",
            status_field="参考图生成状态",
            attachment_field="参考图",
            file_token_field="参考图file_token",
            local_path_field="参考图本地路径",
            task_id_field="参考图任务ID",
            error_field="错误信息",
            filter_fn=script_doc.filter_existing_fields,
            file_suffix="reference",
            file_ext=".png",
        ),
    }


MEDIA_SPECS = _media_specs()


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def load_json_map(path: Any) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    return data if isinstance(data, dict) else {}


def save_json_map(path: Any, data: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def dispatcher_task_key(spec: MediaSpec, record_id: str) -> str:
    return f"{spec.script}::{spec.action}::{record_id}"


def clear_dispatcher_state_for_record(spec: MediaSpec, record_id: str, *, write: bool = False) -> Dict[str, Any]:
    key = dispatcher_task_key(spec, record_id)
    retry_state = load_json_map(RETRY_STATE_FILE)
    dead_letters = load_json_map(DEAD_LETTER_FILE)
    removed_retry_keys = [key] if key in retry_state else []
    removed_dead_letter_keys = [key] if key in dead_letters else []
    if write:
        for item in removed_retry_keys:
            retry_state.pop(item, None)
        for item in removed_dead_letter_keys:
            dead_letters.pop(item, None)
        if removed_retry_keys:
            save_json_map(RETRY_STATE_FILE, retry_state)
        if removed_dead_letter_keys:
            save_json_map(DEAD_LETTER_FILE, dead_letters)
    return {"removed_retry_keys": removed_retry_keys, "removed_dead_letter_keys": removed_dead_letter_keys}


def with_dispatcher_state_cleanup(action_result: Dict[str, Any], spec: MediaSpec, record_id: str, write: bool) -> Dict[str, Any]:
    cleanup = clear_dispatcher_state_for_record(spec, record_id, write=write)
    if cleanup["removed_retry_keys"] or cleanup["removed_dead_letter_keys"]:
        action_result = dict(action_result)
        action_result["dispatcher_state_cleanup"] = cleanup
    return action_result


def attachment_items(value: Any) -> List[Dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict) and item.get("file_token")]
    if isinstance(value, dict) and value.get("file_token"):
        return [value]
    return []


def first_url(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("link", "url", "text"):
            candidate = first_url(value.get(key))
            if candidate:
                return candidate
        return ""
    if isinstance(value, list):
        for item in value:
            candidate = first_url(item)
            if candidate:
                return candidate
        return ""
    text = extract_text(value).strip()
    if not text:
        return ""
    match = URL_RE.search(text)
    return (match.group(0) if match else text).rstrip("'\",.;")


def has_live_process(script: str, record_id: str) -> bool:
    try:
        result = subprocess.run(["ps", "-axo", "pid,command"], check=True, text=True, capture_output=True)
    except Exception:
        return False
    current_pid = str(os.getpid())
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        pid, _, command = stripped.partition(" ")
        if pid == current_pid:
            continue
        if script in command and record_id in command:
            return True
    return False


def filter_fields(token: str, spec: MediaSpec, payload: Dict[str, Any]) -> Dict[str, Any]:
    return spec.filter_fn(token, spec.table_id, payload)


def task_status(body: Dict[str, Any]) -> str:
    nested = body.get("data") if isinstance(body.get("data"), dict) else {}
    result = body.get("result") if isinstance(body.get("result"), dict) else {}
    return extract_text(body.get("status") or nested.get("status") or result.get("status")).strip().lower()


def is_completed(body: Dict[str, Any], media_type: str) -> bool:
    return task_status(body) in COMPLETED_STATUSES or (media_type == "image" and bool(extract_otu_result_url(body)))


def is_failed(body: Dict[str, Any]) -> bool:
    return task_status(body) in TERMINAL_FAILED_STATUSES


def is_running_upstream(body: Dict[str, Any]) -> bool:
    status = task_status(body)
    return status in RUNNING_UPSTREAM_STATUSES or not status


def fetch_json(url: str, api_key: str) -> Dict[str, Any]:
    resp = requests.get(url, headers={"Authorization": f"Bearer {api_key}"}, timeout=45)
    try:
        body = resp.json()
    except Exception:
        body = {"raw_text": resp.text[:1000]}
    if resp.status_code >= 400:
        raise RuntimeError(f"任务查询失败: HTTP {resp.status_code}, body={str(body)[:1000]}")
    return body if isinstance(body, dict) else {"raw": body}


def _stage_config_for_spec(spec: MediaSpec, token: str, fields: Dict[str, Any]) -> Dict[str, str]:
    if spec.key.startswith("first_last_"):
        if spec.media_type == "video":
            _, cfg = first_last.get_stage_config(
                first_last.VIDEO_STAGE_NAME,
                default_model=first_last.DEFAULT_OTU_MODEL,
                default_api_base=first_last.DEFAULT_OTU_API_BASE,
                default_size=first_last.DEFAULT_OTU_SIZE,
            )
            return cfg
        _, cfg = first_last.get_stage_config(
            first_last.IMAGE_STAGE_NAME,
            default_model=first_last.DEFAULT_OTU_IMAGE_MODEL,
            default_api_base=first_last.DEFAULT_OTU_API_BASE,
            default_size=first_last.DEFAULT_OTU_IMAGE_SIZE,
        )
        return cfg
    if spec.key.startswith("multi_role_"):
        if spec.media_type == "video":
            _, cfg = multi_role.get_stage_config(
                multi_role.VIDEO_STAGE_NAME,
                default_model=multi_role.DEFAULT_OTU_MODEL,
                default_api_base=multi_role.DEFAULT_OTU_API_BASE,
                default_size=multi_role.DEFAULT_OTU_SIZE,
            )
            return cfg
        _, cfg = multi_role.get_stage_config(
            multi_role.IMAGE_STAGE_NAME,
            default_model=multi_role.DEFAULT_OTU_IMAGE_MODEL,
            default_api_base=multi_role.DEFAULT_OTU_API_BASE,
            default_size=multi_role.DEFAULT_OTU_IMAGE_SIZE,
        )
        return cfg
    if spec.key == "nine_grid_video":
        _, cfg = nine_grid.get_config_record(
            nine_grid.VIDEO_STAGE_NAME,
            default_model=nine_grid.DEFAULT_VIDEO_MODEL,
            default_api_base=nine_grid.DEFAULT_OTU_API_BASE,
            default_size=nine_grid.DEFAULT_VIDEO_SIZE,
        )
        route = nine_grid._route_for_prefixed_fields(
            fields,
            "视频",
            cfg,
            capability="视频",
            task_type="首帧图生视频",
            default_provider=nine_grid.DEFAULT_VIDEO_PROVIDER,
            default_model=nine_grid.DEFAULT_VIDEO_MODEL,
            config_records=nine_grid._stage_config_records(token),
        )
        return {"api_base": route.api_base or nine_grid.DEFAULT_OTU_API_BASE, "api_key": route.api_key, "model": route.model}
    if spec.key.startswith("nine_grid_"):
        stage = nine_grid.REFERENCE_STAGE_NAME if spec.key == "nine_grid_reference" else nine_grid.IMAGE_STAGE_NAME
        _, cfg = nine_grid.get_config_record(
            stage,
            default_model=nine_grid.DEFAULT_OTU_IMAGE_MODEL,
            default_api_base=nine_grid.DEFAULT_OTU_API_BASE,
            default_size=nine_grid.DEFAULT_IMAGE_SIZE,
        )
        return cfg
    if spec.key == "script_doc_reference":
        cfg = script_doc.get_model_config(token, f"stage:{script_doc.IMAGE_STAGE_NAME}")
        return {
            "api_base": cfg.get("api_base") or script_doc.DEFAULT_OTU_API_BASE,
            "api_key": cfg.get("api_key") or cfg.get("API Key") or "",
            "model": cfg.get("model") or script_doc.DEFAULT_OTU_IMAGE_MODEL,
        }
    raise ValueError(f"未知媒体任务配置: {spec.key}")


def query_task(token: str, spec: MediaSpec, fields: Dict[str, Any], task_id: str) -> Tuple[Dict[str, Any], str]:
    if spec.key == "multi_role_video":
        return video_repair.query_multi_role_task("", fields, task_id)
    if spec.key == "nine_grid_video":
        return video_repair.query_nine_grid_task(token, fields, task_id)
    cfg = _stage_config_for_spec(spec, token, fields)
    if not cfg.get("api_key"):
        raise ValueError(f"{spec.label} 缺少 API Key，无法查询上游任务")
    body = fetch_json(video_item_url(cfg.get("api_base") or "https://otuapi.com", task_id), cfg["api_key"])
    if spec.media_type == "image":
        return body, extract_otu_result_url(body)
    media_url = extract_video_url(body)
    if is_completed(body, spec.media_type) and not media_url:
        media_url = video_item_url(cfg.get("api_base") or "https://otuapi.com", task_id) + "/content"
    return body, media_url


def repair_download_path(spec: MediaSpec, record_id: str) -> str:
    path = Path(WORKSPACE) / "repair_stuck_media" / spec.key / record_id / f"{record_id}_{spec.file_suffix}{spec.file_ext}"
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def download_media(url: str, local_path: str, media_type: str) -> str:
    if media_type == "image":
        return download_otu_image_result(url, local_path)
    return download_video(url, local_path)


def upload_media(token: str, local_path: str, file_name: str, media_type: str) -> str:
    if media_type == "image":
        return upload_image_to_feishu(token, local_path, file_name)
    return upload_video_to_feishu(token, local_path, file_name)


def _success_payload(token: str, spec: MediaSpec, fields: Dict[str, Any], file_token: str, local_path: str, media_url: str) -> Dict[str, Any]:
    file_name = Path(local_path).name
    payload: Dict[str, Any] = {
        spec.status_field: "成功",
        spec.attachment_field: [{"file_token": file_token, "name": file_name}],
        spec.task_id_field: extract_text(fields.get(spec.task_id_field)).strip(),
        spec.error_field: "",
    }
    if spec.error_field != "错误信息":
        payload["错误信息"] = ""
    if spec.file_token_field:
        payload[spec.file_token_field] = file_token
    if spec.local_path_field and local_path:
        payload[spec.local_path_field] = local_path
    if spec.operation_field:
        payload[spec.operation_field] = "不触发"
    if spec.success_review_field:
        payload[spec.success_review_field] = spec.success_review_value
    if spec.url_field and media_url:
        field_types = get_table_field_types(token, spec.table_id)
        payload[spec.url_field] = format_url_field_value(media_url, field_types.get(spec.url_field, 0))
    return filter_fields(token, spec, payload)


def mark_existing_attachment_success(
    token: str,
    spec: MediaSpec,
    record_id: str,
    fields: Dict[str, Any],
    attachment: Dict[str, Any],
    media_url: str,
    write: bool,
) -> Dict[str, Any]:
    file_token = str(attachment.get("file_token") or "").strip()
    name = attachment.get("name") or f"{record_id}_{spec.file_suffix}{spec.file_ext}"
    payload = _success_payload(token, spec, fields, file_token, "", media_url)
    payload[spec.attachment_field] = [{"file_token": file_token, "name": name}]
    if not write:
        return with_dispatcher_state_cleanup({"action": "mark_existing_attachment_success", "payload": payload}, spec, record_id, write)
    safe_update_record(token, spec.table_id, record_id, payload)
    return with_dispatcher_state_cleanup({"action": "marked_existing_attachment_success", "file_token": file_token, "name": name}, spec, record_id, write)


def upload_local_media(token: str, spec: MediaSpec, record_id: str, fields: Dict[str, Any], local_path: str, media_url: str, write: bool) -> Dict[str, Any]:
    if not write:
        return with_dispatcher_state_cleanup({"action": "upload_local_media", "local_path": local_path, "media_url": media_url}, spec, record_id, write)
    file_name = f"{record_id}_{spec.file_suffix}{spec.file_ext}"
    file_token = upload_media(token, local_path, file_name, spec.media_type)
    payload = _success_payload(token, spec, fields, file_token, local_path, media_url)
    safe_update_record(token, spec.table_id, record_id, payload)
    return with_dispatcher_state_cleanup(
        {"action": "uploaded_media", "file_token": file_token, "local_path": local_path, "media_url": media_url},
        spec,
        record_id,
        write,
    )


def restore_running(token: str, spec: MediaSpec, record_id: str, fields: Dict[str, Any], task_id: str, write: bool) -> Dict[str, Any]:
    fields_to_write = {
        spec.status_field: "生成中",
        spec.task_id_field: task_id,
        spec.error_field: f"repair: 恢复轮询已有上游任务，避免重复提交。task_id={task_id}"[:1000],
    }
    if spec.error_field != "错误信息":
        fields_to_write["错误信息"] = ""
    payload = filter_fields(token, spec, fields_to_write)
    if not write:
        return with_dispatcher_state_cleanup({"action": "restore_running", "payload": payload}, spec, record_id, write)
    safe_update_record(token, spec.table_id, record_id, payload)
    return with_dispatcher_state_cleanup({"action": "restore_running_written", "payload": payload}, spec, record_id, write)


def reset_for_resubmit(token: str, spec: MediaSpec, record_id: str, message: str, write: bool) -> Dict[str, Any]:
    fields_to_write = {
        spec.status_field: "待生成",
        spec.task_id_field: "",
        spec.error_field: f"repair: {message}"[:1000],
    }
    if spec.error_field != "错误信息":
        fields_to_write["错误信息"] = ""
    payload = filter_fields(token, spec, fields_to_write)
    if not write:
        return with_dispatcher_state_cleanup({"action": "reset_for_resubmit", "payload": payload}, spec, record_id, write)
    safe_update_record(token, spec.table_id, record_id, payload)
    return with_dispatcher_state_cleanup({"action": "reset_for_resubmit_written", "payload": payload}, spec, record_id, write)


def mark_policy_blocked(token: str, spec: MediaSpec, record_id: str, message: str, write: bool) -> Dict[str, Any]:
    fields_to_write = {
        spec.status_field: "失败",
        spec.error_field: f"repair: 上游判定提示词或图片违规，请修改后重试。{message}"[:1000],
    }
    if spec.error_field != "错误信息":
        fields_to_write["错误信息"] = ""
    payload = filter_fields(token, spec, fields_to_write)
    if not write:
        return with_dispatcher_state_cleanup({"action": "mark_policy_blocked", "payload": payload}, spec, record_id, write)
    safe_update_record(token, spec.table_id, record_id, payload)
    return with_dispatcher_state_cleanup({"action": "mark_policy_blocked_written", "payload": payload}, spec, record_id, write)


def is_terminal_manual_failure(spec: MediaSpec, fields: Dict[str, Any]) -> bool:
    status = extract_text(fields.get(spec.status_field)).strip()
    message = extract_text(fields.get(spec.error_field) or fields.get("错误信息")).strip()
    return status == "失败" and (
        "废弃" == message
        or "上游判定提示词或图片违规" in message
        or "请修改后重试" in message
    )


def is_deprecated_record(fields: Dict[str, Any]) -> bool:
    return extract_text(fields.get("记录状态")).strip() == "已废弃"


def existing_local_path(spec: MediaSpec, fields: Dict[str, Any]) -> str:
    if not spec.local_path_field:
        return ""
    explicit = extract_text(fields.get(spec.local_path_field)).strip()
    return explicit if explicit and Path(explicit).exists() else ""


def repair_record(token: str, spec: MediaSpec, record: Dict[str, Any], write: bool) -> Optional[Dict[str, Any]]:
    record_id = record["record_id"]
    fields = record.get("fields") or {}
    status = extract_text(fields.get(spec.status_field)).strip()
    if status not in TARGET_STATUSES:
        return None
    if is_deprecated_record(fields) or is_terminal_manual_failure(spec, fields):
        return None
    if attachment_items(fields.get(spec.attachment_field)) and status == "成功":
        return None
    if has_live_process(spec.script, record_id):
        return {"record_id": record_id, "spec": spec.key, "label": spec.label, "status": status, "action": "skip_live_process"}

    current_attachment = attachment_items(fields.get(spec.attachment_field))
    media_url = first_url(fields.get(spec.url_field)) if spec.url_field else ""
    local_path = existing_local_path(spec, fields)
    task_id = extract_text(fields.get(spec.task_id_field)).strip()

    try:
        if current_attachment and status != "成功":
            return {
                "record_id": record_id,
                "spec": spec.key,
                "label": spec.label,
                "status": status,
                **mark_existing_attachment_success(token, spec, record_id, fields, current_attachment[0], media_url, write),
            }
        if local_path and not task_id:
            return {
                "record_id": record_id,
                "spec": spec.key,
                "label": spec.label,
                "status": status,
                **upload_local_media(token, spec, record_id, fields, local_path, media_url, write),
            }
        if media_url:
            target_path = repair_download_path(spec, record_id)
            if write:
                download_media(media_url, target_path, spec.media_type)
            return {
                "record_id": record_id,
                "spec": spec.key,
                "label": spec.label,
                "status": status,
                **upload_local_media(token, spec, record_id, fields, target_path, media_url, write),
            }
        if task_id:
            body, upstream_url = query_task(token, spec, fields, task_id)
            if is_completed(body, spec.media_type) and upstream_url:
                target_path = repair_download_path(spec, record_id)
                if write:
                    download_media(upstream_url, target_path, spec.media_type)
                result = upload_local_media(token, spec, record_id, fields, target_path, upstream_url, write)
                return {"record_id": record_id, "spec": spec.key, "label": spec.label, "status": status, "task_id": task_id, **result}
            payload = build_error_payload(body, stage=f"repair_{spec.key}")
            if is_failed(body) and payload["error_code"] == "UPSTREAM_POLICY_BLOCKED":
                return {
                    "record_id": record_id,
                    "spec": spec.key,
                    "label": spec.label,
                    "status": status,
                    "task_id": task_id,
                    **mark_policy_blocked(token, spec, record_id, payload["message"], write),
                }
            if is_running_upstream(body):
                return {
                    "record_id": record_id,
                    "spec": spec.key,
                    "label": spec.label,
                    "status": status,
                    "task_id": task_id,
                    **restore_running(token, spec, record_id, fields, task_id, write),
                }
            return {
                "record_id": record_id,
                "spec": spec.key,
                "label": spec.label,
                "status": status,
                "task_id": task_id,
                **reset_for_resubmit(token, spec, record_id, "上游任务失败或无可下载结果，清空旧 task 等待重新提交。", write),
            }
        if status == "失败":
            return {
                "record_id": record_id,
                "spec": spec.key,
                "label": spec.label,
                "status": status,
                **reset_for_resubmit(token, spec, record_id, "没有可复用结果，清空旧 task 等待重新提交。", write),
            }
        return {"record_id": record_id, "spec": spec.key, "label": spec.label, "status": status, "action": "no_repairable_artifact"}
    except Exception as exc:
        return {
            "record_id": record_id,
            "spec": spec.key,
            "label": spec.label,
            "status": status,
            "action": "repair_error",
            "error": str(exc)[:1000],
        }


def candidate_records(records: Iterable[Dict[str, Any]], spec: MediaSpec) -> Iterable[Dict[str, Any]]:
    for record in records:
        fields = record.get("fields") or {}
        status = extract_text(fields.get(spec.status_field)).strip()
        if status not in TARGET_STATUSES:
            continue
        if is_deprecated_record(fields) or is_terminal_manual_failure(spec, fields):
            continue
        if (
            status == "失败"
            or extract_text(fields.get(spec.task_id_field)).strip()
            or (spec.url_field and first_url(fields.get(spec.url_field)))
            or existing_local_path(spec, fields)
            or attachment_items(fields.get(spec.attachment_field))
            or extract_text(fields.get(spec.error_field)).strip()
        ):
            yield record


def selected_specs(kind_filter: str) -> List[MediaSpec]:
    specs = list(MEDIA_SPECS.values())
    if kind_filter == "images":
        return [spec for spec in specs if spec.media_type == "image"]
    if kind_filter == "videos":
        return [spec for spec in specs if spec.media_type == "video"]
    return specs


def run(
    write: bool,
    limit: int = 0,
    *,
    kind_filter: str = "all",
    record_ids: Optional[Iterable[str]] = None,
) -> List[Dict[str, Any]]:
    token = get_feishu_token()
    outputs: List[Dict[str, Any]] = []
    record_id_set = {str(item).strip() for item in (record_ids or []) if str(item).strip()}
    records_by_table: Dict[str, List[Dict[str, Any]]] = {}
    for spec in selected_specs(kind_filter):
        if not spec.table_id:
            continue
        if spec.table_id not in records_by_table:
            records_by_table[spec.table_id] = safe_list_records(token, spec.table_id)
        for record in candidate_records(records_by_table[spec.table_id], spec):
            if record_id_set and record.get("record_id") not in record_id_set:
                continue
            action = repair_record(token, spec, record, write)
            if action:
                outputs.append(action)
            if limit and len(outputs) >= limit:
                return outputs
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair stuck image/video task records")
    parser.add_argument("--write", action="store_true", help="执行写回；默认仅 dry-run")
    parser.add_argument("--dry-run", action="store_true", help="只读预览（默认）")
    parser.add_argument("--kind", choices=["all", "images", "videos"], default="all", help="处理媒体类型")
    parser.add_argument("--limit", type=int, default=0, help="最多处理/展示多少条")
    parser.add_argument("--record-id", action="append", default=[], help="只处理指定记录；可重复传入")
    args = parser.parse_args()

    write = args.write and not args.dry_run
    result = run(write=write, limit=args.limit, kind_filter=args.kind, record_ids=args.record_id)
    print(compact_json({"mode": "write" if write else "dry-run", "kind": args.kind, "count": len(result), "records": result}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
