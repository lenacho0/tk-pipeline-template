#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from typing import Any, Callable, Dict, Iterable, List, Optional

from ugc_config import load_ugc_table_ids
from ugc_utils import extract_text
from tk_ugc_reroll import list_ugc_records
from tk_ugc_six_grid import get_feishu_token, update_ugc_record
from tk_ugc_shot_images import enhance_existing_ugc05_record, regenerate_single_ugc05_shot
from tk_ugc_video_prompts import create_or_preview_ugc06_records
from tk_ugc_shot_videos import run_ugc06_video_generation

STATUS_RUNNING = "处理中"
STATUS_SUCCESS = "成功"
STATUS_FAILED = "失败"
ACTION_IDLE = "不触发"
ACTION_HD = "确认分镜图并高清化"
ACTION_REGEN_SHOT = "重新生成单张分镜图"
ACTION_REENHANCE = "重新高清化"
ACTION_VIDEO = "生成分镜视频"
REVIEW_PASS = "通过"


def norm(value: Any) -> str:
    return extract_text(value).strip()


def build_result_update(status: str, result: Dict[str, Any], *, reset_field: str = "") -> Dict[str, Any]:
    fields = {
        "分镜图执行状态": status,
        "分镜图执行结果": json.dumps(result, ensure_ascii=False, indent=2, default=str)[:60000],
    }
    if reset_field:
        fields[reset_field] = ACTION_IDLE
    return fields


def should_regenerate_shot(fields: Dict[str, Any]) -> bool:
    return norm(fields.get("分镜图操作")) == ACTION_REGEN_SHOT


def should_enhance(fields: Dict[str, Any]) -> bool:
    return norm(fields.get("分镜图审核状态")) == REVIEW_PASS and norm(fields.get("分镜图操作")) == ACTION_HD


def should_reenhance(fields: Dict[str, Any]) -> bool:
    return norm(fields.get("高清图操作")) == ACTION_REENHANCE


def should_generate_video(fields: Dict[str, Any]) -> bool:
    return norm(fields.get("高清图审核状态")) == REVIEW_PASS and norm(fields.get("高清图操作")) == ACTION_VIDEO


def process_regenerate_shot_record(
    record: Dict[str, Any],
    *,
    write: bool,
    call_models: bool,
    regenerate_fn: Callable[..., Dict[str, Any]] = regenerate_single_ugc05_shot,
) -> Dict[str, Any]:
    if not call_models:
        raise ValueError("重新生成单张分镜图 会触发真实图片模型调用，需要显式 --call-models")
    record_id = record.get("record_id") or ""
    result = regenerate_fn(record_id, write=write)
    return {"stage": "ugc05_single_shot_regen", "source_record_id": record_id, "status": "success", "result": result}


def process_enhance_record(
    record: Dict[str, Any],
    *,
    write: bool,
    call_models: bool,
    enhance_fn: Callable[..., Dict[str, Any]] = enhance_existing_ugc05_record,
) -> Dict[str, Any]:
    if not call_models:
        raise ValueError("确认分镜图并高清化 会触发真实图片模型调用，需要显式 --call-models")
    record_id = record.get("record_id") or ""
    result = enhance_fn(record_id, write=write)
    return {"stage": "ugc05_enhance", "source_record_id": record_id, "status": "success", "result": result}


def process_video_record(
    record: Dict[str, Any],
    *,
    write: bool,
    call_models: bool,
    create_ugc06_fn: Callable[..., Dict[str, Any]] = create_or_preview_ugc06_records,
    video_fn: Callable[..., Dict[str, Any]] = run_ugc06_video_generation,
) -> Dict[str, Any]:
    if not call_models:
        raise ValueError("生成分镜视频 会触发真实视频模型调用，需要显式 --call-models")
    record_id = record.get("record_id") or ""
    created = create_ugc06_fn([record_id], write=write)
    generated: List[Dict[str, Any]] = []
    for item in created.get("created_records") or []:
        ugc06_record_id = item.get("record_id") or ""
        if ugc06_record_id:
            generated.append(video_fn(ugc06_record_id, dry_run=not write))
    return {
        "stage": "ugc06_video",
        "source_record_id": record_id,
        "status": "success",
        "result": {"ugc06_records": created, "video_generation": generated},
    }


def run_review_stage(
    *,
    token: str,
    ugc05_table: str,
    limit: int,
    write: bool,
    call_models: bool,
    records: Optional[Iterable[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    records_list = list(records) if records is not None else list_ugc_records(token, ugc05_table, page_size=500)
    pending = []
    for record in records_list:
        fields = record.get("fields") or {}
        if should_regenerate_shot(fields):
            pending.append(("regen_shot", record))
        elif should_enhance(fields):
            pending.append(("enhance", record))
        elif should_reenhance(fields):
            pending.append(("reenhance", record))
        elif should_generate_video(fields):
            pending.append(("video", record))
    outputs: List[Dict[str, Any]] = []
    for action, record in pending[:limit]:
        record_id = record.get("record_id") or ""
        reset_field = "高清图操作" if action in {"video", "reenhance"} else "分镜图操作"
        if write:
            update_ugc_record(token, ugc05_table, record_id, {"分镜图执行状态": STATUS_RUNNING})
        try:
            if action == "regen_shot":
                processed = process_regenerate_shot_record(record, write=write, call_models=call_models)
            elif action in {"enhance", "reenhance"}:
                processed = process_enhance_record(record, write=write, call_models=call_models)
                if action == "reenhance":
                    processed["stage"] = "ugc05_reenhance"
            else:
                processed = process_video_record(record, write=write, call_models=call_models)
            if write:
                update_ugc_record(token, ugc05_table, record_id, build_result_update(STATUS_SUCCESS, processed, reset_field=reset_field))
            outputs.append(processed)
        except Exception as exc:
            failure = {"stage": action, "source_record_id": record_id, "status": "failed", "error": str(exc)}
            if write:
                update_ugc_record(token, ugc05_table, record_id, build_result_update(STATUS_FAILED, failure, reset_field=reset_field))
            outputs.append(failure)
    return {"stage": "ugc05_review", "dry_run": not write, "call_models": call_models, "pending_count": len(pending), "processed": outputs}


def main() -> int:
    parser = argparse.ArgumentParser(description="Poll UGC-05 review action fields and run confirmed HD/video stages.")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--call-models", action="store_true")
    args = parser.parse_args()
    token = get_feishu_token()
    table_ids = load_ugc_table_ids()
    result = run_review_stage(
        token=token,
        ugc05_table=table_ids["ugc_05_shot_images"],
        limit=args.limit,
        write=args.write,
        call_models=args.call_models,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
