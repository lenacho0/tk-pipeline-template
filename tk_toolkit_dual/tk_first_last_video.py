#!/usr/bin/env python3
"""
首尾帧视频专用表 worker。

用法:
  python3 tk_first_last_video.py parse <record_id>
  python3 tk_first_last_video.py first-frame <record_id>
  python3 tk_first_last_video.py advance-first-review <record_id>
  python3 tk_first_last_video.py last-frame <record_id>
  python3 tk_first_last_video.py advance-last-review <record_id>
  python3 tk_first_last_video.py video <record_id>
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (  # noqa: E402
    APP_TOKEN,
    TABLE_CONFIG,
    TABLE_FIRST_LAST_VIDEO,
    TABLE_PRODUCT,
    WORKSPACE,
    build_error_payload,
    extract_linked_record_ids,
    extract_text,
    feishu_headers,
    get_feishu_token,
    log_event,
    safe_get_record,
    safe_list_records,
    safe_request,
    safe_update_record,
    upload_image_to_feishu,
    with_retry,
)
from otu_image import (  # noqa: E402
    DEFAULT_OTU_API_BASE,
    DEFAULT_OTU_IMAGE_MODEL,
    DEFAULT_OTU_IMAGE_SIZE,
    download_otu_image_result,
    extract_otu_result_url,
    normalize_image_model_choice,
    poll_otu_image_task,
    submit_otu_image_task,
)
from tk_shot_script_gen import extract_json_object  # noqa: E402
from tk_shot_storyboard import (  # noqa: E402
    download_feishu_media,
    filter_existing_fields,
    get_attachment_token,
    get_tmp_download_url_for_attachment,
)
from tk_shot_video import (  # noqa: E402
    DEFAULT_ASPECT_RATIO,
    DEFAULT_OTU_MODEL,
    DEFAULT_OTU_SIZE,
    download_video,
    extract_video_url,
    format_url_field_value,
    get_table_field_types,
    normalize_seconds,
    poll_otu_video_task,
    upload_video_to_feishu,
    video_item_url,
    videos_url,
)


IMAGE_STAGE_NAME = "图片生成-OTU"
VIDEO_STAGE_NAME = "分镜视频生成-OTU"
BASE_WORK_DIR = Path(WORKSPACE) / "first_last_video_work"
SUBMIT_TIMEOUT = 180
PARENT_RECORD_TYPE = "母任务"
CHILD_RECORD_TYPE = "场景子任务"
ACTIVE_RECORD_STATES = {"", "有效"}
STALE_WRITEBACK_MARKER = "停止写回，避免旧任务覆盖新结果"
MAX_PRODUCT_REFERENCES = 4


def compact_json(value: Any, max_chars: int = 20000) -> str:
    text = json.dumps(value, ensure_ascii=False, indent=2, default=str)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 200] + "\n...TRUNCATED..."


def ensure_first_last_table() -> None:
    if not TABLE_FIRST_LAST_VIDEO:
        raise RuntimeError("config.json 尚未配置 first_last_video 表 ID")


def ensure_work_dir(record_id: str) -> Path:
    work_dir = BASE_WORK_DIR / record_id
    work_dir.mkdir(parents=True, exist_ok=True)
    return work_dir


def ensure_stage_work_dir(record_id: str, stage: str, version: int) -> Path:
    work_dir = ensure_work_dir(record_id) / f"{stage}_v{version}"
    work_dir.mkdir(parents=True, exist_ok=True)
    return work_dir


def normalize_int(value: Any, default: int = 0) -> int:
    text = extract_text(value).strip()
    if not text:
        return default
    try:
        return int(float(text))
    except Exception:
        return default


def current_version(fields: Dict[str, Any], field_name: str) -> int:
    return max(1, normalize_int(fields.get(field_name), 1))


def next_version(fields: Dict[str, Any], field_name: str) -> int:
    return current_version(fields, field_name) + 1


def record_type(fields: Dict[str, Any]) -> str:
    return extract_text(fields.get("记录类型")).strip()


def record_state(fields: Dict[str, Any]) -> str:
    return extract_text(fields.get("记录状态")).strip()


def is_active_record(fields: Dict[str, Any]) -> bool:
    return record_state(fields) in ACTIVE_RECORD_STATES


def ensure_active_child_or_single(fields: Dict[str, Any]) -> None:
    state = record_state(fields)
    if state not in ACTIVE_RECORD_STATES:
        raise RuntimeError(f"记录状态已变更为 {state or '<empty>'}，停止处理，避免引用废弃记录")
    if record_type(fields) == PARENT_RECORD_TYPE:
        raise ValueError("母任务只用于批量拆分场景，不能直接生成图片或视频")


def make_batch_id(record_id: str) -> str:
    return f"FLV-BATCH-{time.strftime('%Y%m%d%H%M%S')}-{record_id[-6:]}"


def create_records(token: str, table_id: str, records: List[Dict[str, Dict[str, Any]]]) -> int:
    created = 0
    for i in range(0, len(records), 10):
        batch = records[i:i + 10]
        safe_request(
            "post",
            f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/records/batch_create",
            headers=feishu_headers(token),
            json={"records": batch},
            timeout=30,
            max_attempts=3,
            acceptable_codes=(0,),
        )
        created += len(batch)
    return created


def download_feishu_attachment_raw(token: str, file_token: str, save_path: Path) -> Path:
    url = f"https://open.feishu.cn/open-apis/drive/v1/medias/{file_token}/download"
    resp = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=300, stream=True)
    if resp.status_code != 200:
        raise RuntimeError(f"飞书附件下载失败: HTTP {resp.status_code}, file_token={file_token}")
    save_path = Path(save_path)
    save_path.parent.mkdir(parents=True, exist_ok=True)
    with save_path.open("wb") as f:
        for chunk in resp.iter_content(8192):
            if chunk:
                f.write(chunk)
    if save_path.stat().st_size <= 0:
        raise RuntimeError(f"飞书附件下载结果为空: {save_path}")
    return save_path


def video_result_reset_fields(status: str = "不触发") -> Dict[str, Any]:
    return {
        "首尾帧视频": [],
        "首尾帧视频URL": None,
        "首尾帧视频file_token": "",
        "视频任务ID": "",
        "本地视频路径": "",
        "视频生成原始响应JSON": "",
        "视频错误信息": "",
        "视频生成时间": None,
        "视频生成状态": status,
        "错误信息": "",
    }


def last_frame_result_reset_fields(status: str = "不触发") -> Dict[str, Any]:
    fields = {
        "尾帧图": [],
        "尾帧图本地路径": "",
        "尾帧图file_token": "",
        "尾帧图任务ID": "",
        "尾帧图原始响应JSON": "",
        "尾帧图错误信息": "",
        "尾帧图生成时间": None,
        "尾帧图生成状态": status,
        "尾帧审核状态": "待确认",
    }
    fields.update(video_result_reset_fields("不触发"))
    return fields


def first_frame_result_reset_fields(status: str = "不触发") -> Dict[str, Any]:
    fields = {
        "首帧图": [],
        "首帧图本地路径": "",
        "首帧图file_token": "",
        "首帧图任务ID": "",
        "首帧图原始响应JSON": "",
        "首帧图错误信息": "",
        "首帧图生成时间": None,
        "首帧图生成状态": status,
        "首帧审核状态": "待确认",
    }
    fields.update(last_frame_result_reset_fields("不触发"))
    return fields


def ensure_current_generation(
    token: str,
    record_id: str,
    status_field: str,
    expected_status: str,
    version_field: str,
    expected_version: int,
    task_field: str = "",
    task_id: str = "",
) -> None:
    latest = safe_get_record(token, TABLE_FIRST_LAST_VIDEO, record_id)
    state = record_state(latest)
    if state not in ACTIVE_RECORD_STATES:
        raise RuntimeError(f"记录状态已变更为 {state or '<empty>'}，停止写回，避免旧任务覆盖新结果")
    current_status = extract_text(latest.get(status_field)).strip()
    if current_status != expected_status:
        raise RuntimeError(f"{status_field} 已变更为 {current_status or '<empty>'}，停止写回，避免旧任务覆盖新结果")
    current_stage_version = normalize_int(latest.get(version_field), 0)
    if current_stage_version != expected_version:
        raise RuntimeError(f"{version_field} 已变更，停止写回，避免旧任务覆盖新结果")
    if task_field and task_id:
        current_task_id = extract_text(latest.get(task_field)).strip()
        if current_task_id != task_id:
            raise RuntimeError(f"{task_field} 已变更，停止写回，避免旧任务覆盖新结果")


def is_stale_writeback_error(exc: Exception) -> bool:
    return STALE_WRITEBACK_MARKER in str(exc)


def extract_link_ids(value: Any) -> List[str]:
    linked_ids = extract_linked_record_ids(value)
    if linked_ids:
        return linked_ids
    if isinstance(value, list):
        return [str(item).strip() for item in value if isinstance(item, str) and item.strip()]
    return []


def extract_attachment_tokens(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    tokens: List[str] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        file_token = str(item.get("file_token") or "").strip()
        if file_token:
            tokens.append(file_token)
    return tokens


def first_text(fields: Dict[str, Any], names: List[str]) -> str:
    for name in names:
        text = extract_text(fields.get(name)).strip()
        if text:
            return text
    return ""


def parse_product_reference_snapshot(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        data = value
    else:
        raw = extract_text(value).strip()
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except Exception:
            try:
                data = extract_json_object(raw)
            except Exception:
                return {}
    if not isinstance(data, dict):
        return {}

    product_record_id = extract_text(data.get("product_record_id")).strip()
    product_name = extract_text(data.get("product_name")).strip()
    raw_tokens = data.get("file_tokens") or data.get("product_tokens") or data.get("reference_file_tokens") or []
    product_tokens = [extract_text(token).strip() for token in raw_tokens if extract_text(token).strip()] if isinstance(raw_tokens, list) else []
    if not product_record_id or not product_tokens:
        return {}
    return {
        "product_record_id": product_record_id,
        "product_name": product_name,
        "product_tokens": product_tokens[:MAX_PRODUCT_REFERENCES],
        "snapshot_used": True,
    }


def resolve_product_reference_context(token: str, fields: Dict[str, Any], record_id: str = "") -> Dict[str, Any]:
    snapshot = parse_product_reference_snapshot(fields.get("产品参考图file_tokenJSON"))
    if snapshot:
        snapshot["source_record_id"] = record_id
        return snapshot

    product_ids = extract_link_ids(fields.get("关联产品记录"))
    if not product_ids and record_type(fields) == CHILD_RECORD_TYPE:
        parent_record_id = extract_text(fields.get("父任务记录ID")).strip()
        if parent_record_id:
            parent_fields = safe_get_record(token, TABLE_FIRST_LAST_VIDEO, parent_record_id)
            snapshot = parse_product_reference_snapshot(parent_fields.get("产品参考图file_tokenJSON"))
            if snapshot:
                snapshot["source_record_id"] = record_id
                return snapshot
            product_ids = extract_link_ids(parent_fields.get("关联产品记录"))
    if len(product_ids) != 1:
        raise ValueError("关联产品记录必须选择 1 个产品")

    product_record_id = product_ids[0]
    product_fields = safe_get_record(token, TABLE_PRODUCT, product_record_id)
    product_tokens = extract_attachment_tokens(product_fields.get("产品图片"))
    if not product_tokens:
        raise ValueError("产品记录缺少产品图片")
    product_name = first_text(product_fields, ["产品名称-zh", "产品名称-th", "产品", "产品名称", "产品名"])
    return {
        "product_record_id": product_record_id,
        "product_name": product_name,
        "product_tokens": product_tokens[:MAX_PRODUCT_REFERENCES],
        "source_record_id": record_id,
        "snapshot_used": False,
    }


def product_reference_snapshot(context: Dict[str, Any]) -> str:
    return compact_json({
        "product_record_id": context.get("product_record_id", ""),
        "product_name": context.get("product_name", ""),
        "file_tokens": context.get("product_tokens") or [],
        "snapshot_used": bool(context.get("snapshot_used")),
    }, 4000)


def product_reference_record_fields(context: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "关联产品记录": [context["product_record_id"]],
        "产品名称": context.get("product_name", ""),
        "产品参考图file_tokenJSON": product_reference_snapshot(context),
    }


def collect_product_reference_images(token: str, context: Dict[str, Any], work_dir: Path) -> List[Dict[str, str]]:
    refs: List[Dict[str, str]] = []
    for idx, file_token in enumerate(context.get("product_tokens") or [], start=1):
        local_path = work_dir / f"reference_product_{idx}.png"
        downloaded = download_feishu_media(token, file_token, local_path)
        refs.append({
            "role": f"product:{idx}",
            "path": str(downloaded),
            "file_token": file_token,
        })
    return refs


def reference_urls_for_refs(token: str, refs: List[Dict[str, str]]) -> List[str]:
    urls: List[str] = []
    for ref in refs:
        file_token = ref.get("file_token", "")
        if not file_token:
            continue
        url = get_tmp_download_url_for_attachment(token, file_token)
        if url:
            urls.append(url)
    return urls


def normalize_parse_payload(payload: Any) -> Dict[str, str]:
    data = payload
    if isinstance(payload, str):
        data = extract_json_object(payload)
    if not isinstance(data, dict):
        raise ValueError("首尾帧文档拆分结果必须是 JSON 对象")
    aliases = {
        "first_frame_prompt": ("first_frame_prompt", "首帧生图提示词", "first_prompt"),
        "last_frame_prompt": ("last_frame_prompt", "尾帧生图提示词", "end_frame_prompt", "last_prompt"),
        "video_prompt": ("video_prompt", "首尾帧生视频提示词", "first_last_video_prompt"),
    }
    normalized: Dict[str, str] = {}
    for target_key, keys in aliases.items():
        value = ""
        for key in keys:
            value = extract_text(data.get(key)).strip()
            if value:
                break
        if not value:
            raise ValueError(f"首尾帧文档拆分结果缺少 {target_key}")
        normalized[target_key] = value
    return normalized


def normalize_batch_parse_payload(payload: Any) -> Dict[str, List[Dict[str, Any]]]:
    data = payload
    if isinstance(payload, str):
        data = extract_json_object(payload)
    if isinstance(data, list):
        data = {"scenes": data}
    if not isinstance(data, dict):
        raise ValueError("批量拆分结果必须是 JSON 对象")
    scenes = data.get("scenes") or data.get("场景列表") or data.get("shots")
    if not isinstance(scenes, list) or not scenes:
        raise ValueError("批量拆分结果缺少 scenes")

    normalized_scenes: List[Dict[str, Any]] = []
    for index, scene in enumerate(scenes, start=1):
        if not isinstance(scene, dict):
            raise ValueError(f"scene {index} 必须是 JSON 对象")
        try:
            prompts = normalize_parse_payload(scene)
        except ValueError as exc:
            raise ValueError(f"scene {index} {exc}") from exc
        scene_no = normalize_int(scene.get("scene_no") or scene.get("场景编号") or scene.get("shot_no"), index)
        title = (
            extract_text(scene.get("title")).strip()
            or extract_text(scene.get("scene_title")).strip()
            or extract_text(scene.get("场景标题")).strip()
            or f"场景{scene_no}"
        )
        normalized_scenes.append({
            "scene_no": scene_no,
            "title": title,
            **prompts,
        })
    return {"scenes": normalized_scenes}


def extract_markdown_prompt_block(section: str) -> str:
    fenced = re.search(r"```(?:[A-Za-z0-9_-]+)?\s*\n(.*?)\n```", section, flags=re.DOTALL)
    if fenced:
        return fenced.group(1).strip()
    body = re.sub(r"^###\s+.*$", "", section, count=1, flags=re.MULTILINE).strip()
    body = body.split("中文拍摄理解", 1)[0].strip()
    return body


def _required_markdown_message(detail: str) -> str:
    return (
        "Markdown 格式不符合要求："
        f"{detail}。请使用 `## S01 场景标题`，并为每个场景填写 "
        "`### S01-1 首帧生图提示词`、`### S01-2 尾帧生图 / 编辑提示词`、"
        "`### S01-3 首尾帧图生视频提示词`，提示词建议放在 Markdown 代码块中。"
    )


def require_structured_markdown_scenes(raw_doc: str) -> Dict[str, List[Dict[str, Any]]]:
    text = raw_doc or ""
    scene_matches = list(re.finditer(r"(?m)^##\s*S(\d{1,3})\s+(.+?)\s*$", text))
    if not scene_matches:
        raise ValueError(_required_markdown_message("缺少场景标题 `## S01 场景标题`"))

    scenes: List[Dict[str, Any]] = []
    for idx, match in enumerate(scene_matches):
        scene_no = int(match.group(1))
        title = match.group(2).strip()
        scene_start = match.end()
        scene_end = scene_matches[idx + 1].start() if idx + 1 < len(scene_matches) else len(text)
        scene_block = text[scene_start:scene_end]
        sub_matches = list(re.finditer(r"(?m)^###\s*S\d{1,3}-(\d+)\s+(.+?)\s*$", scene_block))
        if not sub_matches:
            raise ValueError(_required_markdown_message(f"S{scene_no:02d} 缺少 `### S{scene_no:02d}-1/2/3` 提示词小节"))

        prompts: Dict[str, str] = {}
        for sub_idx, sub_match in enumerate(sub_matches):
            part_no = int(sub_match.group(1))
            heading = sub_match.group(2)
            part_start = sub_match.end()
            part_end = sub_matches[sub_idx + 1].start() if sub_idx + 1 < len(sub_matches) else len(scene_block)
            prompt = extract_markdown_prompt_block(scene_block[part_start:part_end])
            if not prompt:
                continue
            if part_no == 1 and "首帧" in heading:
                prompts["first_frame_prompt"] = prompt
            elif part_no == 2 and "尾帧" in heading:
                prompts["last_frame_prompt"] = prompt
            elif part_no == 3 and "视频" in heading:
                prompts["video_prompt"] = prompt

        required_parts = [
            ("first_frame_prompt", f"`### S{scene_no:02d}-1 首帧生图提示词`"),
            ("last_frame_prompt", f"`### S{scene_no:02d}-2 尾帧生图 / 编辑提示词`"),
            ("video_prompt", f"`### S{scene_no:02d}-3 首尾帧图生视频提示词`"),
        ]
        missing = [label for key, label in required_parts if not prompts.get(key)]
        if missing:
            raise ValueError(_required_markdown_message(f"S{scene_no:02d} 缺少 {', '.join(missing)} 或对应提示词内容"))
        scenes.append({
            "scene_no": scene_no,
            "title": title,
            **prompts,
        })

    return {"scenes": scenes}


def parse_structured_markdown_scenes(raw_doc: str) -> Dict[str, List[Dict[str, Any]]]:
    try:
        return require_structured_markdown_scenes(raw_doc)
    except ValueError:
        return {}


def require_single_markdown_scene(raw_doc: str) -> Dict[str, str]:
    payload = require_structured_markdown_scenes(raw_doc)
    scenes = payload["scenes"]
    if len(scenes) != 1:
        raise ValueError(_required_markdown_message(f"单条文档拆分只允许 1 个场景，当前为 {len(scenes)} 个；多场景请使用批量拆分"))
    return {
        "first_frame_prompt": scenes[0]["first_frame_prompt"],
        "last_frame_prompt": scenes[0]["last_frame_prompt"],
        "video_prompt": scenes[0]["video_prompt"],
    }


def read_source_document_text(token: str, record_id: str, fields: Dict[str, Any]) -> str:
    raw_doc = extract_text(fields.get("首尾帧文档")).strip()
    if raw_doc:
        return raw_doc

    attachment_token = get_attachment_token(fields.get("首尾帧文档附件"))
    if attachment_token:
        source_dir = ensure_stage_work_dir(record_id, "source_document", current_version(fields, "拆分版本"))
        downloaded = download_feishu_attachment_raw(token, attachment_token, source_dir / f"{record_id}_source_document.txt")
        path = Path(downloaded)
        data = path.read_bytes()
        return data.decode("utf-8", errors="ignore").strip()

    return ""


def build_child_scene_records(
    parent_record_id: str,
    parent_fields: Dict[str, Any],
    scenes: List[Dict[str, Any]],
    *,
    batch_id: str,
    split_version: int,
    product_context: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Dict[str, Any]]]:
    task_name = extract_text(parent_fields.get("任务名称")).strip() or f"首尾帧任务-{parent_record_id[-6:]}"
    target_seconds = normalize_int(parent_fields.get("目标时长秒"), 8)
    records: List[Dict[str, Dict[str, Any]]] = []
    for scene in scenes:
        scene_no = normalize_int(scene.get("scene_no"), len(records) + 1)
        title = extract_text(scene.get("title")).strip() or f"场景{scene_no}"
        fields = {
            "记录类型": CHILD_RECORD_TYPE,
            "记录状态": "有效",
            "任务名称": f"{task_name}-场景{scene_no:02d}-{title}",
            "父任务记录ID": parent_record_id,
            "批次ID": batch_id,
            "场景编号": scene_no,
            "场景标题": title,
            "目标时长秒": target_seconds,
            "文档拆分状态": "成功",
            "拆分结果JSON": compact_json(scene, 8000),
            "拆分版本": split_version,
            "首帧生图提示词": scene["first_frame_prompt"],
            "尾帧生图提示词": scene["last_frame_prompt"],
            "首尾帧生视频提示词": scene["video_prompt"],
            "首帧图操作": "不触发",
            "首帧图版本": 1,
            "首帧图生成状态": "待生成",
            "首帧审核状态": "待确认",
            "尾帧图操作": "不触发",
            "尾帧图版本": 1,
            "尾帧图生成状态": "不触发",
            "尾帧审核状态": "待确认",
            "视频操作": "不触发",
            "视频版本": 1,
            "视频通道": "OTU",
            "视频生成模型": f"OTU / {DEFAULT_OTU_MODEL}",
            "视频生成状态": "不触发",
            "错误信息": "",
        }
        if product_context:
            fields.update(product_reference_record_fields(product_context))
        records.append({"fields": fields})
    return records


def deprecate_existing_children(token: str, parent_record_id: str) -> int:
    deprecated = 0
    for rec in safe_list_records(token, TABLE_FIRST_LAST_VIDEO):
        fields = rec.get("fields", {})
        if extract_text(fields.get("父任务记录ID")).strip() != parent_record_id:
            continue
        if record_type(fields) != CHILD_RECORD_TYPE:
            continue
        if record_state(fields) == "已废弃":
            continue
        safe_update_record(token, TABLE_FIRST_LAST_VIDEO, rec["record_id"], filter_existing_fields(token, TABLE_FIRST_LAST_VIDEO, {
            "记录状态": "已废弃",
            "首帧图生成状态": "不触发",
            "尾帧图生成状态": "不触发",
            "视频生成状态": "不触发",
            "首帧图操作": "不触发",
            "尾帧图操作": "不触发",
            "视频操作": "不触发",
            "错误信息": "父任务已重新拆分场景，此子任务已废弃。",
        }))
        deprecated += 1
    return deprecated


def batch_parse_document(record_id: str, *, dry_run: bool = False, raw_model_output: Any = None, force: bool = False) -> Dict[str, Any]:
    ensure_first_last_table()
    token = get_feishu_token()
    fields = safe_get_record(token, TABLE_FIRST_LAST_VIDEO, record_id)
    raw_doc = read_source_document_text(token, record_id, fields)
    if not raw_doc:
        raise ValueError("首尾帧文档为空；长文档请上传到“首尾帧文档附件”")
    product_context = resolve_product_reference_context(token, fields, record_id)
    raw_split_version = normalize_int(fields.get("拆分版本"), 0)
    split_version = raw_split_version + 1 if raw_split_version > 0 else 1
    batch_id = make_batch_id(record_id)
    summary = {"record_id": record_id, "dry_run": dry_run, "raw_doc_chars": len(raw_doc), "split_version": split_version, "batch_id": batch_id}
    if dry_run:
        summary["status"] = "dry_run_ready"
        return summary

    safe_update_record(token, TABLE_FIRST_LAST_VIDEO, record_id, filter_existing_fields(token, TABLE_FIRST_LAST_VIDEO, {
        "记录类型": PARENT_RECORD_TYPE,
        "记录状态": "有效",
        "拆分状态": "拆分中",
        "文档拆分状态": "拆分中",
        "拆分版本": split_version,
        "错误信息": "",
        **product_reference_record_fields(product_context),
    }))

    if raw_model_output is None:
        raw_model_output = require_structured_markdown_scenes(raw_doc)
        summary["parser"] = "structured_markdown"
    payload = normalize_batch_parse_payload(raw_model_output)
    scenes = payload["scenes"]
    deprecated = deprecate_existing_children(token, record_id)
    child_records = build_child_scene_records(record_id, fields, scenes, batch_id=batch_id, split_version=split_version, product_context=product_context)
    created = create_records(token, TABLE_FIRST_LAST_VIDEO, child_records)
    safe_update_record(token, TABLE_FIRST_LAST_VIDEO, record_id, filter_existing_fields(token, TABLE_FIRST_LAST_VIDEO, {
        "记录类型": PARENT_RECORD_TYPE,
        "记录状态": "有效",
        "当前批次ID": batch_id,
        "批次ID": batch_id,
        "拆分状态": "成功",
        "文档拆分状态": "成功",
        "场景拆分操作": "不触发",
        "拆分结果JSON": compact_json(payload, 10000),
        "拆分版本": split_version,
        "总场景数": len(scenes),
        "错误信息": "",
        **product_reference_record_fields(product_context),
    }))
    summary.update({"status": "success", "created_records": created, "deprecated_records": deprecated, "scene_count": len(scenes)})
    return summary


def request_split_regeneration(record_id: str) -> Dict[str, Any]:
    return batch_parse_document(record_id, force=True)


def request_first_frame_regeneration(record_id: str) -> Dict[str, Any]:
    ensure_first_last_table()
    token = get_feishu_token()
    fields = safe_get_record(token, TABLE_FIRST_LAST_VIDEO, record_id)
    ensure_active_child_or_single(fields)
    version = next_version(fields, "首帧图版本")
    patch = first_frame_result_reset_fields("待生成")
    patch.update({
        "首帧图版本": version,
        "首帧图操作": "不触发",
        "错误信息": "",
    })
    safe_update_record(token, TABLE_FIRST_LAST_VIDEO, record_id, filter_existing_fields(token, TABLE_FIRST_LAST_VIDEO, patch))
    return {"record_id": record_id, "status": "triggered", "stage": "first_frame", "version": version}


def request_last_frame_regeneration(record_id: str) -> Dict[str, Any]:
    ensure_first_last_table()
    token = get_feishu_token()
    fields = safe_get_record(token, TABLE_FIRST_LAST_VIDEO, record_id)
    ensure_active_child_or_single(fields)
    version = next_version(fields, "尾帧图版本")
    patch = last_frame_result_reset_fields("待生成")
    patch.update({
        "尾帧图版本": version,
        "尾帧图操作": "不触发",
        "错误信息": "",
    })
    safe_update_record(token, TABLE_FIRST_LAST_VIDEO, record_id, filter_existing_fields(token, TABLE_FIRST_LAST_VIDEO, patch))
    return {"record_id": record_id, "status": "triggered", "stage": "last_frame", "version": version}


def request_video_regeneration(record_id: str) -> Dict[str, Any]:
    ensure_first_last_table()
    token = get_feishu_token()
    fields = safe_get_record(token, TABLE_FIRST_LAST_VIDEO, record_id)
    ensure_active_child_or_single(fields)
    version = next_version(fields, "视频版本")
    patch = video_result_reset_fields("待生成")
    patch.update({
        "视频版本": version,
        "视频操作": "不触发",
        "错误信息": "",
    })
    safe_update_record(token, TABLE_FIRST_LAST_VIDEO, record_id, filter_existing_fields(token, TABLE_FIRST_LAST_VIDEO, patch))
    return {"record_id": record_id, "status": "triggered", "stage": "video", "version": version}


def get_stage_config(
    stage_name: str,
    *,
    default_model: str,
    default_api_base: str,
    default_size: str = "",
) -> Tuple[str, Dict[str, str]]:
    token = get_feishu_token()
    for rec in safe_list_records(token, TABLE_CONFIG):
        fields = rec.get("fields", {})
        if extract_text(fields.get("环节")).strip() != stage_name:
            continue
        cfg = {
            "model": extract_text(fields.get("模型名称")).strip() or default_model,
            "api_key": extract_text(fields.get("API Key")).strip(),
            "api_base": extract_text(fields.get("API 代理地址")).strip() or default_api_base,
            "size": extract_text(fields.get("画面尺寸")).strip() or default_size,
            "aspect_ratio": extract_text(fields.get("画面比例")).strip() or DEFAULT_ASPECT_RATIO,
        }
        if not cfg["api_key"]:
            raise ValueError(f"{stage_name} 缺少 API Key")
        return rec.get("record_id") or rec.get("id") or "", cfg
    raise ValueError(f"找不到模型配置: {stage_name}")


def parse_document(record_id: str, *, dry_run: bool = False, raw_model_output: Any = None) -> Dict[str, Any]:
    ensure_first_last_table()
    token = get_feishu_token()
    fields = safe_get_record(token, TABLE_FIRST_LAST_VIDEO, record_id)
    if record_type(fields) == PARENT_RECORD_TYPE:
        return batch_parse_document(record_id, dry_run=dry_run, raw_model_output=raw_model_output)
    raw_doc = read_source_document_text(token, record_id, fields)
    if not raw_doc:
        raise ValueError("首尾帧文档为空")
    summary = {"record_id": record_id, "dry_run": dry_run, "raw_doc_chars": len(raw_doc)}
    if dry_run:
        summary["status"] = "dry_run_ready"
        return summary

    safe_update_record(token, TABLE_FIRST_LAST_VIDEO, record_id, filter_existing_fields(token, TABLE_FIRST_LAST_VIDEO, {
        "文档拆分状态": "拆分中",
        "错误信息": "",
    }))

    if raw_model_output is None:
        raw_model_output = require_single_markdown_scene(raw_doc)

    payload = normalize_parse_payload(raw_model_output)
    safe_update_record(token, TABLE_FIRST_LAST_VIDEO, record_id, filter_existing_fields(token, TABLE_FIRST_LAST_VIDEO, {
        "记录类型": record_type(fields) or CHILD_RECORD_TYPE,
        "记录状态": "有效",
        "文档拆分状态": "成功",
        "拆分结果JSON": compact_json(payload, 10000),
        "拆分版本": current_version(fields, "拆分版本"),
        "首帧生图提示词": payload["first_frame_prompt"],
        "尾帧生图提示词": payload["last_frame_prompt"],
        "首尾帧生视频提示词": payload["video_prompt"],
        "首帧图操作": "不触发",
        "首帧图版本": current_version(fields, "首帧图版本"),
        "首帧图生成状态": "待生成",
        "首帧图错误信息": "",
        "首帧审核状态": "待确认",
        "尾帧图操作": "不触发",
        "尾帧图版本": current_version(fields, "尾帧图版本"),
        "尾帧图生成状态": "不触发",
        "尾帧图错误信息": "",
        "尾帧审核状态": "待确认",
        "视频操作": "不触发",
        "视频版本": current_version(fields, "视频版本"),
        "视频通道": "OTU",
        "视频生成模型": f"OTU / {DEFAULT_OTU_MODEL}",
        "视频生成状态": "不触发",
        "视频错误信息": "",
        "错误信息": "",
    }))
    summary.update({"status": "success", "prompt_fields": list(payload.keys())})
    return summary


def render_first_frame(record_id: str, *, dry_run: bool = False) -> Dict[str, Any]:
    ensure_first_last_table()
    token = get_feishu_token()
    fields = safe_get_record(token, TABLE_FIRST_LAST_VIDEO, record_id)
    ensure_active_child_or_single(fields)
    prompt = extract_text(fields.get("首帧生图提示词")).strip()
    if not prompt:
        raise ValueError("首帧生图提示词为空")
    version = current_version(fields, "首帧图版本")
    work_dir = ensure_stage_work_dir(record_id, "first_frame", version)
    product_context = resolve_product_reference_context(token, fields, record_id)
    summary = {
        "record_id": record_id,
        "dry_run": dry_run,
        "prompt_chars": len(prompt),
        "product_record_id": product_context["product_record_id"],
        "product_reference_count": len(product_context["product_tokens"]),
    }
    if dry_run:
        summary["status"] = "dry_run_ready"
        return summary

    _, cfg = get_stage_config(
        IMAGE_STAGE_NAME,
        default_model=DEFAULT_OTU_IMAGE_MODEL,
        default_api_base=DEFAULT_OTU_API_BASE,
        default_size=DEFAULT_OTU_IMAGE_SIZE,
    )
    model_name = normalize_image_model_choice(cfg.get("model") or DEFAULT_OTU_IMAGE_MODEL)
    start_fields = first_frame_result_reset_fields("生成中")
    start_fields.update({
        "首帧图版本": version,
        "首帧图生成状态": "生成中",
        "首帧图错误信息": "",
        **product_reference_record_fields(product_context),
    })
    safe_update_record(token, TABLE_FIRST_LAST_VIDEO, record_id, filter_existing_fields(token, TABLE_FIRST_LAST_VIDEO, start_fields))
    out_path = str(work_dir / f"{record_id}_first_frame_v{version}.png")
    product_refs = collect_product_reference_images(token, product_context, work_dir)
    reference_urls = reference_urls_for_refs(token, product_refs)
    reference_summary = {
        "product_record_id": product_context["product_record_id"],
        "product_name": product_context.get("product_name", ""),
        "reference_roles": [ref["role"] for ref in product_refs],
        "reference_file_tokens": [ref["file_token"] for ref in product_refs],
        "reference_paths": [ref.get("path", "") for ref in product_refs],
        "reference_urls": reference_urls,
        "input_mode": "image-to-image",
        "remote_reference_urls": bool(reference_urls),
    }
    submit_task_id, submit_body = submit_otu_image_task(
        {"api_key": cfg["api_key"], "api_base": cfg.get("api_base") or DEFAULT_OTU_API_BASE, "model": model_name},
        prompt,
        input_mode="image-to-image",
        image_path=product_refs[0]["path"],
        metadata={
            "reference_roles": [ref["role"] for ref in product_refs],
            "product_record_id": product_context["product_record_id"],
            "product_reference_file_tokens": [ref["file_token"] for ref in product_refs],
            "urls": reference_urls,
            "aspectRatio": "9:16",
        },
        size=cfg.get("size") or DEFAULT_OTU_IMAGE_SIZE,
    )
    safe_update_record(token, TABLE_FIRST_LAST_VIDEO, record_id, filter_existing_fields(token, TABLE_FIRST_LAST_VIDEO, {
        "首帧图任务ID": submit_task_id,
        "首帧图版本": version,
        "首帧图原始响应JSON": compact_json({"submit": submit_body, "references": reference_summary}, 10000),
        "首帧图错误信息": f"已提交 OTU 首帧图任务，正在轮询。task_id={submit_task_id}" if submit_task_id else "",
    }))
    result = submit_body if not submit_task_id else poll_otu_image_task({"api_key": cfg["api_key"], "api_base": cfg.get("api_base") or DEFAULT_OTU_API_BASE, "model": model_name}, submit_task_id)
    result_url = extract_otu_result_url(result) or extract_otu_result_url(submit_body)
    if not result_url:
        raise RuntimeError("OTU 首帧图任务完成但未返回图片地址")
    download_otu_image_result(result_url, out_path)
    file_token = with_retry(lambda: upload_image_to_feishu(token, out_path, f"{record_id}_first_frame.png"), max_attempts=3, label="upload first frame")
    ensure_current_generation(token, record_id, "首帧图生成状态", "生成中", "首帧图版本", version, "首帧图任务ID", submit_task_id)
    safe_update_record(token, TABLE_FIRST_LAST_VIDEO, record_id, filter_existing_fields(token, TABLE_FIRST_LAST_VIDEO, {
        "首帧图": [{"file_token": file_token}],
        "首帧图file_token": file_token,
        "首帧图本地路径": out_path,
        "首帧图任务ID": submit_task_id,
        "首帧图版本": version,
        "首帧图原始响应JSON": compact_json({"submit": submit_body, "result": result, "references": reference_summary}, 10000),
        "首帧图生成状态": "成功",
        "首帧图生成时间": int(time.time() * 1000),
        "首帧图错误信息": "",
        "首帧审核状态": "待确认",
        "错误信息": "",
        **product_reference_record_fields(product_context),
    }))
    summary.update({"status": "success", "file_token": file_token, "output_path": out_path})
    return summary


def advance_first_review(record_id: str) -> Dict[str, Any]:
    ensure_first_last_table()
    token = get_feishu_token()
    fields = safe_get_record(token, TABLE_FIRST_LAST_VIDEO, record_id)
    if not is_active_record(fields) or record_type(fields) == PARENT_RECORD_TYPE:
        return {"record_id": record_id, "status": "skipped", "review_status": extract_text(fields.get("首帧审核状态")).strip(), "record_state": record_state(fields)}
    review_status = extract_text(fields.get("首帧审核状态")).strip()
    if review_status != "通过":
        return {"record_id": record_id, "status": "skipped", "review_status": review_status}
    safe_update_record(token, TABLE_FIRST_LAST_VIDEO, record_id, filter_existing_fields(token, TABLE_FIRST_LAST_VIDEO, {
        "首帧审核状态": "已触发尾帧",
        "尾帧图生成状态": "待生成",
        "尾帧图错误信息": "",
        "错误信息": "",
    }))
    return {"record_id": record_id, "status": "triggered"}


def render_last_frame(record_id: str, *, dry_run: bool = False) -> Dict[str, Any]:
    ensure_first_last_table()
    token = get_feishu_token()
    fields = safe_get_record(token, TABLE_FIRST_LAST_VIDEO, record_id)
    ensure_active_child_or_single(fields)
    prompt = extract_text(fields.get("尾帧生图提示词")).strip()
    if not prompt:
        raise ValueError("尾帧生图提示词为空")
    first_frame_token = extract_text(fields.get("首帧图file_token")).strip()
    if not first_frame_token:
        raise ValueError("缺少当前首帧图file_token，无法生成尾帧图")
    version = current_version(fields, "尾帧图版本")
    work_dir = ensure_stage_work_dir(record_id, "last_frame", version)
    first_frame_path = download_feishu_media(token, first_frame_token, work_dir / f"{record_id}_first_frame_ref_v{version}.png")
    product_context = resolve_product_reference_context(token, fields, record_id)
    summary = {
        "record_id": record_id,
        "dry_run": dry_run,
        "prompt_chars": len(prompt),
        "first_frame_path": str(first_frame_path),
        "product_record_id": product_context["product_record_id"],
        "product_reference_count": len(product_context["product_tokens"]),
    }
    if dry_run:
        summary["status"] = "dry_run_ready"
        return summary

    _, cfg = get_stage_config(
        IMAGE_STAGE_NAME,
        default_model=DEFAULT_OTU_IMAGE_MODEL,
        default_api_base=DEFAULT_OTU_API_BASE,
        default_size=DEFAULT_OTU_IMAGE_SIZE,
    )
    model_name = normalize_image_model_choice(cfg.get("model") or DEFAULT_OTU_IMAGE_MODEL)
    start_fields = last_frame_result_reset_fields("生成中")
    start_fields.update({
        "尾帧图版本": version,
        "尾帧图生成状态": "生成中",
        "尾帧图错误信息": "",
        **product_reference_record_fields(product_context),
    })
    safe_update_record(token, TABLE_FIRST_LAST_VIDEO, record_id, filter_existing_fields(token, TABLE_FIRST_LAST_VIDEO, start_fields))
    out_path = str(work_dir / f"{record_id}_last_frame_v{version}.png")
    product_refs = collect_product_reference_images(token, product_context, work_dir)
    first_frame_url = get_tmp_download_url_for_attachment(token, first_frame_token)
    product_reference_urls = reference_urls_for_refs(token, product_refs)
    reference_urls = ([first_frame_url] if first_frame_url else []) + product_reference_urls
    reference_roles = ["first_frame"] + [ref["role"] for ref in product_refs]
    reference_file_tokens = [first_frame_token] + [ref["file_token"] for ref in product_refs]
    image_size = cfg.get("size") or DEFAULT_OTU_IMAGE_SIZE
    reference_summary = {
        "product_record_id": product_context["product_record_id"],
        "product_name": product_context.get("product_name", ""),
        "reference_roles": reference_roles,
        "reference_file_tokens": reference_file_tokens,
        "product_reference_file_tokens": product_context.get("product_tokens") or [],
        "reference_paths": [str(first_frame_path)] + [ref.get("path", "") for ref in product_refs],
        "reference_urls": reference_urls,
        "input_mode": "image-to-image",
        "remote_reference_urls": bool(reference_urls),
        "aspect_ratio": "9:16",
        "size": image_size,
    }
    submit_task_id, submit_body = submit_otu_image_task(
        {"api_key": cfg["api_key"], "api_base": cfg.get("api_base") or DEFAULT_OTU_API_BASE, "model": model_name},
        prompt,
        input_mode="image-to-image",
        image_path=str(first_frame_path),
        metadata={
            "reference_roles": reference_roles,
            "product_record_id": product_context["product_record_id"],
            "product_reference_file_tokens": product_context.get("product_tokens") or [],
            "urls": reference_urls,
            "aspectRatio": "9:16",
        },
        size=image_size,
    )
    safe_update_record(token, TABLE_FIRST_LAST_VIDEO, record_id, filter_existing_fields(token, TABLE_FIRST_LAST_VIDEO, {
        "尾帧图任务ID": submit_task_id,
        "尾帧图版本": version,
        "尾帧图原始响应JSON": compact_json({"submit": submit_body, "references": reference_summary}, 10000),
        "尾帧图错误信息": f"已提交 OTU 尾帧图任务，正在轮询。task_id={submit_task_id}" if submit_task_id else "",
    }))
    result = submit_body if not submit_task_id else poll_otu_image_task({"api_key": cfg["api_key"], "api_base": cfg.get("api_base") or DEFAULT_OTU_API_BASE, "model": model_name}, submit_task_id)
    result_url = extract_otu_result_url(result) or extract_otu_result_url(submit_body)
    if not result_url:
        raise RuntimeError("OTU 尾帧图任务完成但未返回图片地址")
    download_otu_image_result(result_url, out_path)
    file_token = with_retry(lambda: upload_image_to_feishu(token, out_path, f"{record_id}_last_frame.png"), max_attempts=3, label="upload last frame")
    ensure_current_generation(token, record_id, "尾帧图生成状态", "生成中", "尾帧图版本", version, "尾帧图任务ID", submit_task_id)
    safe_update_record(token, TABLE_FIRST_LAST_VIDEO, record_id, filter_existing_fields(token, TABLE_FIRST_LAST_VIDEO, {
        "尾帧图": [{"file_token": file_token}],
        "尾帧图file_token": file_token,
        "尾帧图本地路径": out_path,
        "尾帧图任务ID": submit_task_id,
        "尾帧图版本": version,
        "尾帧图原始响应JSON": compact_json({"submit": submit_body, "result": result, "references": reference_summary}, 10000),
        "尾帧图生成状态": "成功",
        "尾帧图生成时间": int(time.time() * 1000),
        "尾帧图错误信息": "",
        "尾帧审核状态": "待确认",
        "错误信息": "",
        **product_reference_record_fields(product_context),
    }))
    summary.update({"status": "success", "file_token": file_token, "output_path": out_path})
    return summary


def advance_last_review(record_id: str) -> Dict[str, Any]:
    ensure_first_last_table()
    token = get_feishu_token()
    fields = safe_get_record(token, TABLE_FIRST_LAST_VIDEO, record_id)
    if not is_active_record(fields) or record_type(fields) == PARENT_RECORD_TYPE:
        return {"record_id": record_id, "status": "skipped", "review_status": extract_text(fields.get("尾帧审核状态")).strip(), "record_state": record_state(fields)}
    review_status = extract_text(fields.get("尾帧审核状态")).strip()
    if review_status != "通过":
        return {"record_id": record_id, "status": "skipped", "review_status": review_status}
    safe_update_record(token, TABLE_FIRST_LAST_VIDEO, record_id, filter_existing_fields(token, TABLE_FIRST_LAST_VIDEO, {
        "尾帧审核状态": "已触发视频",
        "视频生成状态": "待生成",
        "视频错误信息": "",
        "错误信息": "",
    }))
    return {"record_id": record_id, "status": "triggered"}


def submit_first_last_video_task(
    config: Dict[str, str],
    prompt: str,
    first_frame_path: str,
    last_frame_path: str,
    *,
    seconds: str,
    size: str = DEFAULT_OTU_SIZE,
    aspect_ratio: str = DEFAULT_ASPECT_RATIO,
) -> Tuple[str, Dict[str, Any]]:
    url = videos_url(config.get("api_base") or DEFAULT_OTU_API_BASE)
    headers = {"Authorization": f"Bearer {config['api_key']}"}

    def _submit_once() -> Tuple[str, Dict[str, Any]]:
        with open(first_frame_path, "rb") as first_file, open(last_frame_path, "rb") as last_file:
            files = [
                ("input_reference[]", (os.path.basename(first_frame_path), first_file, "image/png")),
                ("input_reference[]", (os.path.basename(last_frame_path), last_file, "image/png")),
            ]
            data = {
                "model": config.get("model") or DEFAULT_OTU_MODEL,
                "prompt": prompt,
                "seconds": seconds,
                "size": size or DEFAULT_OTU_SIZE,
                "aspect_ratio": aspect_ratio or DEFAULT_ASPECT_RATIO,
            }
            resp = requests.post(url, headers=headers, data=data, files=files, timeout=SUBMIT_TIMEOUT)
        try:
            body = resp.json()
        except Exception:
            body = {"raw_text": resp.text[:1000]}
        if resp.status_code >= 400:
            raise RuntimeError(f"OTU 首尾帧视频任务提交失败: HTTP {resp.status_code}, body={str(body)[:1200]}")
        task_id = extract_text(body.get("id") or body.get("task_id") or (body.get("data") or {}).get("id") or (body.get("data") or {}).get("task_id")).strip()
        if not task_id:
            raise RuntimeError(f"OTU 首尾帧视频任务提交未返回任务 ID: {str(body)[:1200]}")
        return task_id, body

    return with_retry(_submit_once, max_attempts=4, label=f"submit first/last OTU video {url}")


def render_video(record_id: str, *, dry_run: bool = False) -> Dict[str, Any]:
    ensure_first_last_table()
    token = get_feishu_token()
    fields = safe_get_record(token, TABLE_FIRST_LAST_VIDEO, record_id)
    ensure_active_child_or_single(fields)
    prompt = extract_text(fields.get("首尾帧生视频提示词")).strip()
    existing_task_id = extract_text(fields.get("视频任务ID")).strip()
    version = current_version(fields, "视频版本")
    work_dir = ensure_stage_work_dir(record_id, "video", version)
    _, cfg = get_stage_config(
        VIDEO_STAGE_NAME,
        default_model=DEFAULT_OTU_MODEL,
        default_api_base=DEFAULT_OTU_API_BASE,
        default_size=DEFAULT_OTU_SIZE,
    )
    seconds = normalize_seconds(fields.get("目标时长秒"))
    size = cfg.get("size") or DEFAULT_OTU_SIZE
    aspect_ratio = cfg.get("aspect_ratio") or DEFAULT_ASPECT_RATIO
    output_path = str(work_dir / f"{record_id}_first_last_video_v{version}.mp4")
    summary = {
        "record_id": record_id,
        "dry_run": dry_run,
        "model": cfg.get("model") or DEFAULT_OTU_MODEL,
        "seconds": seconds,
        "size": size,
        "aspect_ratio": aspect_ratio,
        "prompt_chars": len(prompt),
        "output_path": output_path,
    }
    if existing_task_id:
        summary["existing_task_id"] = existing_task_id
    if dry_run:
        summary["status"] = "dry_run_ready"
        return summary

    field_types = get_table_field_types(token, TABLE_FIRST_LAST_VIDEO)
    if existing_task_id:
        task_id = existing_task_id
        safe_update_record(token, TABLE_FIRST_LAST_VIDEO, record_id, filter_existing_fields(token, TABLE_FIRST_LAST_VIDEO, {
            "视频通道": "OTU",
            "视频生成模型": f"OTU / {cfg.get('model') or DEFAULT_OTU_MODEL}",
            "视频生成状态": "生成中",
            "视频任务ID": task_id,
            "视频版本": version,
            "视频错误信息": f"恢复轮询已有 OTU 首尾帧视频任务。task_id={task_id}",
            "错误信息": "",
        }))
    else:
        if not prompt:
            raise ValueError("首尾帧生视频提示词为空")
        first_frame_token = extract_text(fields.get("首帧图file_token")).strip()
        last_frame_token = extract_text(fields.get("尾帧图file_token")).strip()
        if not first_frame_token:
            raise ValueError("缺少当前首帧图file_token，无法生成首尾帧视频")
        if not last_frame_token:
            raise ValueError("缺少当前尾帧图file_token，无法生成首尾帧视频")
        first_frame_path = download_feishu_media(token, first_frame_token, work_dir / f"{record_id}_video_first_frame_v{version}.png")
        last_frame_path = download_feishu_media(token, last_frame_token, work_dir / f"{record_id}_video_last_frame_v{version}.png")
        start_fields = video_result_reset_fields("生成中")
        start_fields.update({
            "视频通道": "OTU",
            "视频生成模型": f"OTU / {cfg.get('model') or DEFAULT_OTU_MODEL}",
            "视频生成状态": "生成中",
            "视频版本": version,
            "视频错误信息": "",
        })
        safe_update_record(token, TABLE_FIRST_LAST_VIDEO, record_id, filter_existing_fields(token, TABLE_FIRST_LAST_VIDEO, start_fields))
        task_id, submit_body = submit_first_last_video_task(
            cfg,
            prompt,
            str(first_frame_path),
            str(last_frame_path),
            seconds=seconds,
            size=size,
            aspect_ratio=aspect_ratio,
        )
        safe_update_record(token, TABLE_FIRST_LAST_VIDEO, record_id, filter_existing_fields(token, TABLE_FIRST_LAST_VIDEO, {
            "视频任务ID": task_id,
            "视频版本": version,
            "视频生成原始响应JSON": compact_json({"submit": submit_body}, 10000),
            "视频错误信息": f"已提交 OTU 首尾帧视频任务，正在轮询。task_id={task_id}",
        }))
    result = poll_otu_video_task(cfg, task_id)
    video_url = extract_video_url(result)
    if not video_url:
        content_url = video_item_url(cfg.get("api_base") or DEFAULT_OTU_API_BASE, task_id) + "/content"
        video_url = content_url
    download_video(video_url, output_path)
    file_token = upload_video_to_feishu(token, output_path, f"{record_id}_first_last_video.mp4")
    ensure_current_generation(token, record_id, "视频生成状态", "生成中", "视频版本", version, "视频任务ID", task_id)
    success_fields: Dict[str, Any] = {
        "视频通道": "OTU",
        "视频生成模型": f"OTU / {cfg.get('model') or DEFAULT_OTU_MODEL}",
        "视频生成状态": "成功",
        "首尾帧视频": [{"file_token": file_token, "name": Path(output_path).name}],
        "视频任务ID": task_id,
        "视频版本": version,
        "本地视频路径": output_path,
        "首尾帧视频file_token": file_token,
        "视频生成原始响应JSON": compact_json(result, 10000),
        "视频错误信息": "",
        "视频生成时间": int(time.time() * 1000),
        "错误信息": "",
    }
    if video_url:
        success_fields["首尾帧视频URL"] = format_url_field_value(video_url, field_types.get("首尾帧视频URL", 0))
    safe_update_record(token, TABLE_FIRST_LAST_VIDEO, record_id, filter_existing_fields(token, TABLE_FIRST_LAST_VIDEO, success_fields))
    summary.update({"status": "success", "task_id": task_id, "video_url": video_url, "file_token": file_token})
    return summary


def _failure_update_for_action(action: str, message: str) -> Dict[str, Any]:
    if action == "parse":
        return {"文档拆分状态": "失败", "错误信息": message[:1000]}
    if action in {"batch-parse", "regenerate-split"}:
        return {"拆分状态": "失败", "文档拆分状态": "失败", "场景拆分操作": "不触发", "错误信息": message[:1000]}
    if action == "regenerate-first-frame":
        return {"首帧图操作": "不触发", "首帧图生成状态": "失败", "首帧图错误信息": message[:1000], "错误信息": message[:1000]}
    if action == "regenerate-last-frame":
        return {"尾帧图操作": "不触发", "尾帧图生成状态": "失败", "尾帧图错误信息": message[:1000], "错误信息": message[:1000]}
    if action == "regenerate-video":
        return {"视频操作": "不触发", "视频生成状态": "失败", "视频错误信息": message[:1000], "错误信息": message[:1000]}
    if action == "first-frame":
        return {"首帧图生成状态": "失败", "首帧图错误信息": message[:1000], "错误信息": message[:1000]}
    if action == "last-frame":
        return {"尾帧图生成状态": "失败", "尾帧图错误信息": message[:1000], "错误信息": message[:1000]}
    if action == "video":
        return {"视频生成状态": "失败", "视频错误信息": message[:1000], "错误信息": message[:1000]}
    return {"错误信息": message[:1000]}


def main() -> int:
    parser = argparse.ArgumentParser(description="首尾帧视频生成")
    parser.add_argument("action", choices=[
        "parse",
        "batch-parse",
        "regenerate-split",
        "regenerate-first-frame",
        "first-frame",
        "advance-first-review",
        "regenerate-last-frame",
        "last-frame",
        "advance-last-review",
        "regenerate-video",
        "video",
    ])
    parser.add_argument("record_id")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    try:
        if args.action == "parse":
            result = parse_document(args.record_id, dry_run=args.dry_run)
        elif args.action == "batch-parse":
            result = batch_parse_document(args.record_id, dry_run=args.dry_run)
        elif args.action == "regenerate-split":
            result = request_split_regeneration(args.record_id)
        elif args.action == "regenerate-first-frame":
            result = request_first_frame_regeneration(args.record_id)
        elif args.action == "first-frame":
            result = render_first_frame(args.record_id, dry_run=args.dry_run)
        elif args.action == "advance-first-review":
            result = advance_first_review(args.record_id)
        elif args.action == "regenerate-last-frame":
            result = request_last_frame_regeneration(args.record_id)
        elif args.action == "last-frame":
            result = render_last_frame(args.record_id, dry_run=args.dry_run)
        elif args.action == "advance-last-review":
            result = advance_last_review(args.record_id)
        elif args.action == "regenerate-video":
            result = request_video_regeneration(args.record_id)
        else:
            result = render_video(args.record_id, dry_run=args.dry_run)
        print(compact_json(result))
        return 0
    except Exception as exc:
        payload = build_error_payload(exc, stage=f"first_last_video_{args.action}")
        log_event("ERROR", "first/last video task failed", action=args.action, record_id=args.record_id, error=payload["message"], error_code=payload["error_code"])
        if not is_stale_writeback_error(exc):
            try:
                token = get_feishu_token()
                if TABLE_FIRST_LAST_VIDEO:
                    safe_update_record(token, TABLE_FIRST_LAST_VIDEO, args.record_id, filter_existing_fields(token, TABLE_FIRST_LAST_VIDEO, _failure_update_for_action(args.action, payload["message"])))
            except Exception:
                pass
        print(f"ERROR_CODE={payload['error_code']} RETRYABLE={str(payload['retryable']).lower()} MESSAGE={payload['message']}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
