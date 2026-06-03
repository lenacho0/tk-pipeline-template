#!/usr/bin/env python3
"""
一次性修复九宫格/多角色视频卡住记录。

默认 dry-run 只输出计划；加 --write 才会下载、上传附件并写回飞书。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tk_multi_role_first_last as multi_role  # noqa: E402
import tk_nine_grid_video as nine_grid  # noqa: E402
from common import (  # noqa: E402
    WORKSPACE,
    build_error_payload,
    extract_text,
    get_feishu_token,
    safe_get_record,
    safe_list_records,
    safe_update_record,
)
from tk_shot_video import (  # noqa: E402
    download_video,
    extract_video_url,
    format_url_field_value,
    get_table_field_types,
    upload_video_to_feishu,
    video_item_url,
)


TARGET_STATUSES = {"待生成", "生成中", "失败"}
URL_RE = re.compile(r"https?://[^\s'\",\])>}]+")
RETRY_STATE_FILE = Path(__file__).with_name(".retry_state.ryan.json")
DEAD_LETTER_FILE = Path(__file__).with_name(".dead_letter_tasks.ryan.json")


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


def dispatcher_task_key(kind: str, record_id: str, action: str = "video") -> str:
    script = "tk_multi_role_first_last.py" if kind == "multi_role" else "tk_nine_grid_video.py"
    return f"{script}::{action}::{record_id}"


def clear_dispatcher_state_for_record(kind: str, record_id: str, *, action: str = "video", write: bool = False) -> Dict[str, Any]:
    key = dispatcher_task_key(kind, record_id, action)
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
    return {
        "removed_retry_keys": removed_retry_keys,
        "removed_dead_letter_keys": removed_dead_letter_keys,
    }


def with_dispatcher_state_cleanup(action_result: Dict[str, Any], kind: str, record_id: str, write: bool) -> Dict[str, Any]:
    cleanup = clear_dispatcher_state_for_record(kind, record_id, action="video", write=write)
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
        result = subprocess.run(
            ["ps", "-axo", "pid,command"],
            check=True,
            text=True,
            capture_output=True,
        )
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


def existing_local_video_path(fields: Dict[str, Any], record_id: str, kind: str) -> str:
    explicit = extract_text(fields.get("视频本地路径")).strip()
    if explicit and Path(explicit).exists():
        return explicit

    if kind == "multi_role":
        base = Path(WORKSPACE) / "multi_role_first_last_work" / record_id
        pattern = "*_video_v*.mp4"
    else:
        base = Path(WORKSPACE) / "nine_grid_video_work" / record_id
        pattern = "*_nine_grid_video.mp4"
    candidates = sorted(base.glob(f"**/{pattern}"), key=lambda path: path.stat().st_mtime, reverse=True) if base.exists() else []
    return str(candidates[0]) if candidates else ""


def repair_download_path(record_id: str, kind: str) -> str:
    stage_dir = "multi_role_first_last_work" if kind == "multi_role" else "nine_grid_video_work"
    suffix = "multi_role_clip" if kind == "multi_role" else "nine_grid_video"
    path = Path(WORKSPACE) / stage_dir / record_id / "repair" / f"{record_id}_{suffix}.mp4"
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def fetch_json(url: str, api_key: str) -> Dict[str, Any]:
    resp = requests.get(url, headers={"Authorization": f"Bearer {api_key}"}, timeout=45)
    try:
        body = resp.json()
    except Exception:
        body = {"raw_text": resp.text[:1000]}
    if resp.status_code >= 400:
        raise RuntimeError(f"任务查询失败: HTTP {resp.status_code}, body={str(body)[:1000]}")
    return body if isinstance(body, dict) else {"raw": body}


def task_status(body: Dict[str, Any]) -> str:
    nested = body.get("data") if isinstance(body.get("data"), dict) else {}
    return extract_text(body.get("status") or nested.get("status")).strip().lower()


def is_completed(body: Dict[str, Any]) -> bool:
    return task_status(body) in {"completed", "succeeded", "success", "done"}


def is_failed(body: Dict[str, Any]) -> bool:
    return task_status(body) in {"failed", "error", "cancelled", "canceled"}


def task_created_at(body: Dict[str, Any]) -> Optional[float]:
    nested = body.get("data") if isinstance(body.get("data"), dict) else {}
    value = body.get("created_at", nested.get("created_at"))
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def local_video_is_current_for_task(local_path: str, task_body: Dict[str, Any]) -> bool:
    created_at = task_created_at(task_body)
    if created_at is None:
        return True
    try:
        return Path(local_path).stat().st_mtime >= created_at
    except OSError:
        return False


def query_multi_role_task(record_id: str, fields: Dict[str, Any], task_id: str) -> Tuple[Dict[str, Any], str]:
    _, cfg = multi_role.get_stage_config(
        multi_role.VIDEO_STAGE_NAME,
        default_model=multi_role.DEFAULT_OTU_MODEL,
        default_api_base=multi_role.DEFAULT_OTU_API_BASE,
        default_size=multi_role.DEFAULT_OTU_SIZE,
    )
    body = fetch_json(video_item_url(cfg.get("api_base") or multi_role.DEFAULT_OTU_API_BASE, task_id), cfg["api_key"])
    video_url = extract_video_url(body)
    if is_completed(body) and not video_url:
        video_url = video_item_url(cfg.get("api_base") or multi_role.DEFAULT_OTU_API_BASE, task_id) + "/content"
    return body, video_url


def query_nine_grid_task(token: str, fields: Dict[str, Any], task_id: str) -> Tuple[Dict[str, Any], str]:
    _, cfg = nine_grid.get_config_record(
        nine_grid.VIDEO_STAGE_NAME,
        default_model="omni_flash-10s",
        default_api_base="https://otuapi.com",
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
    model_name = nine_grid.ai_routing.parse_model_display(route.model)["model"] or route.model
    if route.provider == "OTU":
        url = f"{(route.api_base or nine_grid.DEFAULT_OTU_API_BASE).rstrip('/')}/v1/videos/{task_id}"
        body = fetch_json(url, route.api_key)
        video_url = extract_video_url(body)
        if is_completed(body) and not video_url:
            video_url = video_item_url(route.api_base or nine_grid.DEFAULT_OTU_API_BASE, task_id) + "/content"
        return body, video_url
    body = fetch_json(nine_grid.reference_video_item_url(route, task_id), route.api_key)
    return body, extract_video_url(body)


def status_field(kind: str) -> str:
    return "视频生成状态"


def attachment_field(kind: str) -> str:
    return "视频片段" if kind == "multi_role" else "分镜视频"


def is_terminal_manual_failure(fields: Dict[str, Any]) -> bool:
    status = extract_text(fields.get("视频生成状态")).strip()
    message = extract_text(fields.get("视频错误信息") or fields.get("错误信息")).strip()
    return status == "失败" and (
        "上游判定提示词或图片违规" in message
        or "请修改后重试" in message
    )


def url_field(kind: str) -> str:
    return "视频片段URL" if kind == "multi_role" else "分镜视频URL"


def table_id(kind: str) -> str:
    return multi_role.TABLE_MULTI_ROLE_FIRST_LAST if kind == "multi_role" else nine_grid.TABLE_NINE_GRID_VIDEO


def filter_fields(token: str, kind: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    table = table_id(kind)
    if kind == "multi_role":
        return multi_role.filter_existing_fields(token, table, fields)
    return nine_grid.filter_existing_fields(token, table, fields)


def success_payload(token: str, kind: str, record_id: str, fields: Dict[str, Any], file_token: str, local_path: str, video_url: str) -> Dict[str, Any]:
    field_types = get_table_field_types(token, table_id(kind))
    payload: Dict[str, Any] = {
        status_field(kind): "成功",
        attachment_field(kind): [{"file_token": file_token, "name": Path(local_path).name}],
        "视频任务ID": extract_text(fields.get("视频任务ID")).strip(),
        "视频本地路径": local_path,
        "视频错误信息": "",
        "错误信息": "",
    }
    if kind == "multi_role":
        payload["视频片段file_token"] = file_token
        payload["视频操作"] = "不触发"
    if video_url:
        payload[url_field(kind)] = format_url_field_value(video_url, field_types.get(url_field(kind), 0))
    return filter_fields(token, kind, payload)


def upload_local_video(token: str, kind: str, record_id: str, fields: Dict[str, Any], local_path: str, video_url: str, write: bool) -> Dict[str, Any]:
    if not write:
        return with_dispatcher_state_cleanup({"action": "upload_local_video", "local_path": local_path, "video_url": video_url}, kind, record_id, write)
    file_name = f"{record_id}_{'multi_role_clip' if kind == 'multi_role' else 'nine_grid_video'}.mp4"
    file_token = upload_video_to_feishu(token, local_path, file_name)
    payload = success_payload(token, kind, record_id, fields, file_token, local_path, video_url)
    safe_update_record(token, table_id(kind), record_id, payload)
    return with_dispatcher_state_cleanup(
        {"action": "uploaded_local_video", "file_token": file_token, "local_path": local_path, "video_url": video_url},
        kind,
        record_id,
        write,
    )


def mark_existing_attachment_success(
    token: str,
    kind: str,
    record_id: str,
    fields: Dict[str, Any],
    attachment: Dict[str, Any],
    video_url: str,
    write: bool,
) -> Dict[str, Any]:
    file_token = str(attachment.get("file_token") or "").strip()
    name = attachment.get("name") or f"{record_id}_{'multi_role_clip' if kind == 'multi_role' else 'nine_grid_video'}.mp4"
    field_types = get_table_field_types(token, table_id(kind))
    payload: Dict[str, Any] = {
        status_field(kind): "成功",
        attachment_field(kind): [{"file_token": file_token, "name": name}],
        "视频任务ID": extract_text(fields.get("视频任务ID")).strip(),
        "视频错误信息": "",
        "错误信息": "",
    }
    if kind == "multi_role":
        payload["视频片段file_token"] = file_token
        payload["视频操作"] = "不触发"
    if video_url:
        payload[url_field(kind)] = format_url_field_value(video_url, field_types.get(url_field(kind), 0))
    payload = filter_fields(token, kind, payload)
    if not write:
        return with_dispatcher_state_cleanup({"action": "mark_existing_attachment_success", "payload": payload}, kind, record_id, write)
    safe_update_record(token, table_id(kind), record_id, payload)
    return with_dispatcher_state_cleanup({"action": "marked_existing_attachment_success", "file_token": file_token, "name": name}, kind, record_id, write)


def restore_history_video(token: str, record_id: str, fields: Dict[str, Any], write: bool) -> Optional[Dict[str, Any]]:
    history = attachment_items(fields.get("历史视频"))
    if not history:
        return None
    item = history[0]
    file_token = item["file_token"]
    name = item.get("name") or f"{record_id}_multi_role_clip.mp4"
    if not write:
        return {"action": "restore_history_video", "file_token": file_token, "name": name}
    payload = multi_role.filter_existing_fields(token, multi_role.TABLE_MULTI_ROLE_FIRST_LAST, {
        "视频生成状态": "成功",
        "视频片段": [{"file_token": file_token, "name": name}],
        "视频片段file_token": file_token,
        "视频操作": "不触发",
        "视频错误信息": "",
        "错误信息": "",
    })
    safe_update_record(token, multi_role.TABLE_MULTI_ROLE_FIRST_LAST, record_id, payload)
    return {"action": "restored_history_video", "file_token": file_token, "name": name}


def reset_for_resubmit(token: str, kind: str, record_id: str, message: str, write: bool) -> Dict[str, Any]:
    payload = filter_fields(token, kind, {
        status_field(kind): "待生成",
        "视频任务ID": "",
        "视频本地路径": "",
        "视频错误信息": f"repair: {message}"[:1000],
        "错误信息": "",
    })
    if not write:
        return with_dispatcher_state_cleanup({"action": "reset_for_resubmit", "payload": payload}, kind, record_id, write)
    safe_update_record(token, table_id(kind), record_id, payload)
    return with_dispatcher_state_cleanup({"action": "reset_for_resubmit_written", "payload": payload}, kind, record_id, write)


def mark_policy_blocked(token: str, kind: str, record_id: str, message: str, write: bool) -> Dict[str, Any]:
    payload = filter_fields(token, kind, {
        status_field(kind): "失败",
        "视频错误信息": f"repair: 上游判定提示词或图片违规，请修改后重试。{message}"[:1000],
        "错误信息": "",
    })
    if not write:
        return with_dispatcher_state_cleanup({"action": "mark_policy_blocked", "payload": payload}, kind, record_id, write)
    safe_update_record(token, table_id(kind), record_id, payload)
    return with_dispatcher_state_cleanup({"action": "mark_policy_blocked_written", "payload": payload}, kind, record_id, write)


def repair_record(token: str, kind: str, record: Dict[str, Any], write: bool) -> Optional[Dict[str, Any]]:
    record_id = record["record_id"]
    fields = record.get("fields") or {}
    status = extract_text(fields.get(status_field(kind))).strip()
    if status not in TARGET_STATUSES:
        return None
    if is_terminal_manual_failure(fields):
        return None
    if attachment_items(fields.get(attachment_field(kind))) and status == "成功":
        return None
    script = "tk_multi_role_first_last.py" if kind == "multi_role" else "tk_nine_grid_video.py"
    if has_live_process(script, record_id):
        return {"record_id": record_id, "kind": kind, "status": status, "action": "skip_live_process"}

    current_attachment = attachment_items(fields.get(attachment_field(kind)))
    video_url = first_url(fields.get(url_field(kind)))
    local_path = existing_local_video_path(fields, record_id, kind)
    task_id = extract_text(fields.get("视频任务ID")).strip()

    try:
        if current_attachment and status != "成功":
            return {
                "record_id": record_id,
                "kind": kind,
                "status": status,
                **mark_existing_attachment_success(token, kind, record_id, fields, current_attachment[0], video_url, write),
            }

        if kind == "multi_role":
            history_action = restore_history_video(token, record_id, fields, write)
            if history_action:
                return {"record_id": record_id, "kind": kind, "status": status, **history_action}

        if local_path and Path(local_path).exists() and not task_id:
            return {"record_id": record_id, "kind": kind, "status": status, **upload_local_video(token, kind, record_id, fields, local_path, video_url, write)}

        if video_url:
            target_path = repair_download_path(record_id, kind)
            if write:
                download_video(video_url, target_path)
            return {"record_id": record_id, "kind": kind, "status": status, **upload_local_video(token, kind, record_id, fields, target_path, video_url, write)}

        if task_id:
            body, upstream_url = query_multi_role_task(record_id, fields, task_id) if kind == "multi_role" else query_nine_grid_task(token, fields, task_id)
            if is_completed(body) and upstream_url:
                target_path = repair_download_path(record_id, kind)
                if write:
                    download_video(upstream_url, target_path)
                return {"record_id": record_id, "kind": kind, "status": status, "task_id": task_id, **upload_local_video(token, kind, record_id, fields, target_path, upstream_url, write)}
            if local_path and Path(local_path).exists() and local_video_is_current_for_task(local_path, body):
                return {"record_id": record_id, "kind": kind, "status": status, "task_id": task_id, **upload_local_video(token, kind, record_id, fields, local_path, video_url, write)}
            payload = build_error_payload(body, stage=f"repair_{kind}_video")
            if is_failed(body) and payload["error_code"] == "UPSTREAM_POLICY_BLOCKED":
                return {"record_id": record_id, "kind": kind, "status": status, "task_id": task_id, **mark_policy_blocked(token, kind, record_id, payload["message"], write)}
            return {"record_id": record_id, "kind": kind, "status": status, "task_id": task_id, **reset_for_resubmit(token, kind, record_id, "上游任务未完成或无可下载结果，清空旧 task 等待重新提交。", write)}

        if status == "失败":
            return {
                "record_id": record_id,
                "kind": kind,
                "status": status,
                **reset_for_resubmit(token, kind, record_id, "没有可复用视频，清空旧 task 等待重新提交。", write),
            }
        return {"record_id": record_id, "kind": kind, "status": status, "action": "no_repairable_artifact"}
    except Exception as exc:
        return {"record_id": record_id, "kind": kind, "status": status, "action": "repair_error", "error": str(exc)[:1000]}


def candidate_records(records: Iterable[Dict[str, Any]], kind: str) -> Iterable[Dict[str, Any]]:
    for record in records:
        fields = record.get("fields") or {}
        status = extract_text(fields.get(status_field(kind))).strip()
        if status not in TARGET_STATUSES:
            continue
        if is_terminal_manual_failure(fields):
            continue
        if (
            extract_text(fields.get("视频任务ID")).strip()
            or first_url(fields.get(url_field(kind)))
            or extract_text(fields.get("视频本地路径")).strip()
            or attachment_items(fields.get(attachment_field(kind)))
            or attachment_items(fields.get("历史视频"))
            or extract_text(fields.get("视频错误信息")).strip()
        ):
            yield record


def run(
    write: bool,
    limit: int = 0,
    *,
    kind_filter: str = "",
    record_ids: Optional[Iterable[str]] = None,
) -> List[Dict[str, Any]]:
    token = get_feishu_token()
    outputs: List[Dict[str, Any]] = []
    record_id_set = {str(item).strip() for item in (record_ids or []) if str(item).strip()}
    targets = [
        ("nine_grid", nine_grid.TABLE_NINE_GRID_VIDEO),
        ("multi_role", multi_role.TABLE_MULTI_ROLE_FIRST_LAST),
    ]
    for kind, table in targets:
        if kind_filter and kind != kind_filter:
            continue
        for record in candidate_records(safe_list_records(token, table), kind):
            if record_id_set and record.get("record_id") not in record_id_set:
                continue
            action = repair_record(token, kind, record, write)
            if action:
                outputs.append(action)
            if limit and len(outputs) >= limit:
                return outputs
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair stuck nine-grid and multi-role video records")
    parser.add_argument("--write", action="store_true", help="执行写回；默认仅 dry-run")
    parser.add_argument("--dry-run", action="store_true", help="只读预览（默认）")
    parser.add_argument("--limit", type=int, default=0, help="最多处理/展示多少条")
    parser.add_argument("--kind", choices=["nine_grid", "multi_role"], default="", help="只处理指定链路")
    parser.add_argument("--record-id", action="append", default=[], help="只处理指定记录；可重复传入")
    args = parser.parse_args()

    write = args.write and not args.dry_run
    result = run(write=write, limit=args.limit, kind_filter=args.kind, record_ids=args.record_id)
    print(compact_json({
        "mode": "write" if write else "dry-run",
        "count": len(result),
        "records": result,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
