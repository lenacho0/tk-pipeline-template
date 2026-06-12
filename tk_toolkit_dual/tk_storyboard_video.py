#!/usr/bin/env python3
"""004-故事板视频生成表 worker。"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (  # noqa: E402
    APP_TOKEN,
    TABLE_STORYBOARD_VIDEO,
    WORKSPACE,
    build_error_payload,
    extract_text,
    feishu_headers,
    get_feishu_token,
    safe_get_record,
    safe_list_records,
    safe_request,
    safe_update_record,
)
from tk_model_config_center import TASK_TABLES, apply_task_default_to_fields  # noqa: E402
from tk_prompt_image_video import download_feishu_attachment_raw, run_image, run_video  # noqa: E402
from tk_reference_media import compact_json  # noqa: E402
from tk_shot_storyboard import filter_existing_fields  # noqa: E402


BASE_WORK_DIR = Path(WORKSPACE) / "storyboard_video_work"
STORYBOARD_RECORD_TYPE = "Storyboard分段"
PARENT_RECORD_TYPE = "母任务"
TEXT_ATTACHMENT_SUFFIXES = {".md", ".markdown", ".txt"}
FENCED_CODE_RE = re.compile(r"```[^\n]*\n(?P<body>.*?)\n```", re.DOTALL)
PROMPT_HEADER_RE = re.compile(r"Storyboard\s+0*(?P<number>\d+)\s+(?P<kind>Image|Video)\s+Prompt\s*:", re.IGNORECASE)
TIME_RANGE_RE = re.compile(r"Time\s+Range\s*:\s*(?P<range>[^\n\r.]+(?:s|秒)?)", re.IGNORECASE)
OLD_REFERENCE_LINE_RE = re.compile(
    r"^\s*(middle reference strip|middle low-information reference strip|.+reference area|.+reference anchor|global reference restrictions)\s*:",
    re.IGNORECASE,
)
REFERENCE_ANCHOR_LINES = [
    "Middle low-information reference strip: use one compact reference band with fixed identity/color/package anchors only; keep this band visually secondary.",
    "Person reference anchor: one fixed identity anchor only (same person, single half-body neutral anchor, same outfit/hair). Keep it as one still identity cue.",
    "Pet reference anchor: one fixed body/fur-color anchor only (same pet, single neutral still anchor). Keep it as one still identity cue.",
    "Product reference anchor: single front package anchor only. The reference strip contains the package face only; application items appear only inside story action frames when required.",
    "Global reference restrictions: keep every reference anchor single, static, compact, and secondary; avoid reference catalogs, alternate identity studies, pose collections, packaging catalogs, repeated views, or asset boards.",
]


def ensure_table() -> None:
    if not TABLE_STORYBOARD_VIDEO:
        raise RuntimeError("config.json 尚未配置 storyboard_video 表 ID")


def ensure_work_dir(record_id: str) -> Path:
    work_dir = BASE_WORK_DIR / record_id
    work_dir.mkdir(parents=True, exist_ok=True)
    return work_dir


def _attachment_items(value: Any) -> List[Dict[str, str]]:
    if not isinstance(value, list):
        return []
    result: List[Dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        token = extract_text(item.get("file_token")).strip()
        name = extract_text(item.get("name")).strip()
        if token:
            result.append({"file_token": token, "name": name})
    return result


def resolve_storyboard_document_input(
    token: str,
    fields: Mapping[str, Any],
    work_dir: Path,
    *,
    download_fn: Callable[[str, str, Path], Any] = download_feishu_attachment_raw,
) -> Dict[str, Any]:
    body = extract_text(fields.get("故事板文档正文")).strip()
    attachments = _attachment_items(fields.get("故事板Markdown附件"))
    if body:
        return {
            "source": "正文",
            "markdown": body,
            "attachment_ignored": bool(attachments),
        }
    if not attachments:
        raise ValueError("缺少故事板文档输入：请填写故事板文档正文，或上传 .md / .markdown / .txt 附件")
    selected = None
    for item in attachments:
        suffix = Path(item.get("name") or "").suffix.lower()
        if suffix in TEXT_ATTACHMENT_SUFFIXES:
            selected = item
            break
    if not selected:
        raise ValueError("故事板Markdown附件仅支持 .md / .markdown / .txt")
    safe_name = Path(selected.get("name") or "storyboard.md").name
    local_path = work_dir / safe_name
    downloaded = download_fn(token, selected["file_token"], local_path)
    path = Path(downloaded) if isinstance(downloaded, (str, Path)) else local_path
    markdown = path.read_text(encoding="utf-8").strip()
    if not markdown:
        raise ValueError(f"故事板Markdown附件内容为空: {safe_name}")
    return {
        "source": "附件",
        "markdown": markdown,
        "attachment_name": safe_name,
        "attachment_file_token": selected["file_token"],
        "attachment_path": str(path),
        "attachment_ignored": False,
    }


def _candidate_prompt_blocks(markdown: str) -> List[str]:
    blocks = [match.group("body").strip() for match in FENCED_CODE_RE.finditer(markdown)]
    return blocks or [markdown]


def _extract_prompts(markdown: str, kind: str) -> Dict[int, str]:
    prompts: Dict[int, str] = {}
    for block in _candidate_prompt_blocks(markdown):
        match = PROMPT_HEADER_RE.search(block)
        if not match or match.group("kind").lower() != kind.lower():
            continue
        number = int(match.group("number"))
        prompts[number] = block.strip()
    return prompts


def _time_range_for_prompt(prompt: str) -> str:
    match = TIME_RANGE_RE.search(prompt)
    return match.group("range").strip() if match else ""


def normalize_storyboard_image_prompt(prompt: str) -> str:
    lines = (prompt or "").splitlines()
    normalized: List[str] = []
    inserted_reference_anchor = False
    removed_reference_line = False
    for line in lines:
        if OLD_REFERENCE_LINE_RE.match(line) or line.strip().lower().startswith("use three reference areas"):
            removed_reference_line = True
            if not inserted_reference_anchor:
                normalized.extend(REFERENCE_ANCHOR_LINES)
                inserted_reference_anchor = True
            continue
        normalized.append(line)
    if not inserted_reference_anchor and removed_reference_line:
        normalized.extend(REFERENCE_ANCHOR_LINES)
    return "\n".join(normalized).strip()


def parse_storyboard_markdown_package(markdown: str) -> Dict[str, Any]:
    raw = (markdown or "").strip()
    if not raw:
        raise ValueError("故事板 Markdown 为空")
    image_prompts = _extract_prompts(raw, "Image")
    video_prompts = _extract_prompts(raw, "Video")
    if not image_prompts or not video_prompts:
        raise ValueError("未找到 Storyboard Image Prompt 和 Storyboard Video Prompt")
    image_numbers = set(image_prompts)
    video_numbers = set(video_prompts)
    if image_numbers != video_numbers:
        missing_video = sorted(image_numbers - video_numbers)
        missing_image = sorted(video_numbers - image_numbers)
        raise ValueError(f"故事板提示词不成对: 缺视频={missing_video}, 缺图片={missing_image}")
    storyboards = []
    for number in sorted(image_numbers):
        raw_image_prompt = image_prompts[number]
        image_prompt = normalize_storyboard_image_prompt(raw_image_prompt)
        video_prompt = video_prompts[number]
        storyboards.append({
            "storyboard_number": number,
            "storyboard_title": f"Storyboard {number:02d}",
            "time_range": _time_range_for_prompt(image_prompt),
            "image_prompt": image_prompt,
            "video_prompt": video_prompt,
            "raw_prompt_block": "\n\n".join([raw_image_prompt, video_prompt]),
        })
    return {
        "task_type": "STORYBOARD_VIDEO_PACKAGE",
        "total_storyboards": len(storyboards),
        "storyboards": storyboards,
    }


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


def cleanup_child_storyboards(token: str, parent_record_id: str) -> int:
    deleted = 0
    for rec in safe_list_records(token, TABLE_STORYBOARD_VIDEO):
        fields = rec.get("fields") or {}
        if extract_text(fields.get("父任务记录ID")).strip() != parent_record_id:
            continue
        if extract_text(fields.get("记录类型")).strip() != STORYBOARD_RECORD_TYPE:
            continue
        safe_request(
            "delete",
            f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_STORYBOARD_VIDEO}/records/{rec['record_id']}",
            headers=feishu_headers(token),
            timeout=30,
            max_attempts=3,
            acceptable_codes=(0,),
        )
        deleted += 1
    return deleted


def apply_storyboard_default_models(token: str, records: List[Dict[str, Dict[str, Any]]]) -> List[Dict[str, Dict[str, Any]]]:
    app_table = TASK_TABLES["storyboard_video"]
    result = []
    for item in records:
        fields = dict(item["fields"])
        fields = apply_task_default_to_fields(
            token,
            fields,
            app_table=app_table,
            stage="图片生成默认",
            model_field="图片AI模型",
            size_field="图片画面尺寸",
            ratio_field="图片画面比例",
            params_field="图片AI参数JSON",
        )
        fields = apply_task_default_to_fields(
            token,
            fields,
            app_table=app_table,
            stage="图生视频生成默认",
            model_field="视频生成模型",
            size_field="视频画面尺寸",
            ratio_field="视频画面比例",
            params_field="视频AI参数JSON",
        )
        result.append({"fields": fields})
    return result


def _link_record_ids_for_write(value: Any) -> List[str]:
    ids: List[str] = []
    if isinstance(value, str) and value.strip().startswith("rec"):
        ids.append(value.strip())
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item.strip().startswith("rec"):
                ids.append(item.strip())
            elif isinstance(item, dict):
                if item.get("id"):
                    ids.append(str(item["id"]).strip())
                for record_id in item.get("record_ids") or []:
                    ids.append(str(record_id).strip())
    return [record_id for record_id in ids if record_id]


def build_child_storyboard_records(
    parent_fields: Mapping[str, Any],
    payload: Mapping[str, Any],
    *,
    parent_record_id: str,
    batch_id: str,
) -> List[Dict[str, Dict[str, Any]]]:
    inherited_fields = {
        key: parent_fields.get(key)
        for key in ("上传产品图", "上传模特图", "上传参考图")
        if parent_fields.get(key)
    }
    for key in ("关联产品记录", "选择模特"):
        ids = _link_record_ids_for_write(parent_fields.get(key))
        if ids:
            inherited_fields[key] = ids
    task_name = extract_text(parent_fields.get("任务名称")).strip()
    total = int(payload.get("total_storyboards") or 0)
    records = []
    for board in payload.get("storyboards") or []:
        number = int(board["storyboard_number"])
        fields = {
            "任务名称": f"{task_name or '故事板'} - Storyboard {number:02d}",
            "记录类型": STORYBOARD_RECORD_TYPE,
            "记录状态": "有效",
            "父任务记录ID": parent_record_id,
            "批次ID": batch_id,
            "Storyboard编号": number,
            "总Storyboard数": total,
            "Time Range": board.get("time_range", ""),
            "故事板标题": board.get("storyboard_title", f"Storyboard {number:02d}"),
            "原始Prompt块": board.get("raw_prompt_block", ""),
            "生图提示词": board.get("image_prompt", ""),
            "图生视频提示词": board.get("video_prompt", ""),
            "图片生成状态": "待生成",
            "图片审核状态": "待确认",
            "视频生成状态": "不触发",
            "错误信息": "",
            **inherited_fields,
        }
        records.append({"fields": fields})
    return records


def parse_parent_record(record_id: str, *, token: Optional[str] = None, dry_run: bool = False) -> Dict[str, Any]:
    ensure_table()
    token = token or get_feishu_token()
    fields = safe_get_record(token, TABLE_STORYBOARD_VIDEO, record_id)
    work_dir = ensure_work_dir(record_id)
    document = resolve_storyboard_document_input(token, fields, work_dir)
    payload = parse_storyboard_markdown_package(document["markdown"])
    payload = {**payload, "document_source": {k: v for k, v in document.items() if k != "markdown"}}
    batch_id = f"STORYBOARD-{time.strftime('%Y%m%d%H%M%S')}-{record_id[-6:]}"
    child_records = apply_storyboard_default_models(
        token,
        build_child_storyboard_records(fields, payload, parent_record_id=record_id, batch_id=batch_id),
    )
    summary = {
        "record_id": record_id,
        "dry_run": dry_run,
        "status": "dry_run_ready" if dry_run else "success",
        "batch_id": batch_id,
        "storyboard_count": len(child_records),
        "document_source": payload["document_source"],
    }
    if dry_run:
        return summary
    safe_update_record(token, TABLE_STORYBOARD_VIDEO, record_id, filter_existing_fields(token, TABLE_STORYBOARD_VIDEO, {
        "记录类型": PARENT_RECORD_TYPE,
        "记录状态": "有效",
        "故事板文档来源": document["source"],
        "解析状态": "解析中",
        "错误信息": "",
    }))
    deleted = cleanup_child_storyboards(token, record_id)
    create_records(token, TABLE_STORYBOARD_VIDEO, [
        {"fields": filter_existing_fields(token, TABLE_STORYBOARD_VIDEO, item["fields"])}
        for item in child_records
    ])
    safe_update_record(token, TABLE_STORYBOARD_VIDEO, record_id, filter_existing_fields(token, TABLE_STORYBOARD_VIDEO, {
        "解析状态": "成功",
        "解析结果JSON": compact_json(payload, 20000),
        "总Storyboard数": len(child_records),
        "批次ID": batch_id,
        "错误信息": "",
    }))
    summary["deleted_children"] = deleted
    return summary


def run_action(action: str, record_id: str, *, dry_run: bool = False) -> Dict[str, Any]:
    if action == "parse":
        return parse_parent_record(record_id, dry_run=dry_run)
    if action == "image":
        return run_image(get_feishu_token(), record_id, dry_run=dry_run, table_key="storyboard_video")
    if action == "video":
        return run_video(get_feishu_token(), record_id, dry_run=dry_run, table_key="storyboard_video")
    raise ValueError(f"未知 action: {action}")


def _failure_update_for_action(action: str, message: str) -> Dict[str, Any]:
    if action == "parse":
        return {"解析状态": "失败", "错误信息": message[:1000]}
    if action == "image":
        return {"图片生成状态": "失败", "图片错误信息": message[:1000], "错误信息": message[:1000]}
    if action == "video":
        return {"视频生成状态": "失败", "视频错误信息": message[:1000], "错误信息": message[:1000]}
    return {"错误信息": message[:1000]}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run 004 storyboard video worker")
    parser.add_argument("action", choices=["parse", "image", "video"])
    parser.add_argument("record_id")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        result = run_action(args.action, args.record_id, dry_run=args.dry_run)
        print(compact_json(result))
    except Exception as exc:
        payload = build_error_payload(exc, stage=f"tk_storyboard_video.py {args.action}")
        print(json.dumps({"error": payload}, ensure_ascii=False), file=sys.stderr)
        try:
            if TABLE_STORYBOARD_VIDEO:
                token = get_feishu_token()
                safe_update_record(
                    token,
                    TABLE_STORYBOARD_VIDEO,
                    args.record_id,
                    filter_existing_fields(token, TABLE_STORYBOARD_VIDEO, _failure_update_for_action(args.action, payload["message"])),
                )
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
