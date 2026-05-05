#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from typing import Any, Callable, Dict, Iterable, List, Optional

from ugc_config import load_ugc_table_ids
from ugc_utils import extract_text
from tk_ugc_six_grid import get_feishu_token, update_ugc_record, run_image_generation
from tk_ugc_shot_images import create_or_preview_shot_records

STATUS_RUNNING = "处理中"
STATUS_SUCCESS = "成功"
STATUS_FAILED = "失败"
ONE_CLICK_GRID_FIELD = "一键重生成9宫格"
ONE_CLICK_STATUS_FIELD = "一键重生成状态"
ONE_CLICK_RESULT_FIELD = "一键重生成结果"


def normalize_select_text(value: Any) -> str:
    return extract_text(value).strip()


def checkbox_checked(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, list):
        return any(checkbox_checked(v) for v in value)
    if isinstance(value, dict):
        for key in ("checked", "value", "text", "name"):
            if key in value and checkbox_checked(value.get(key)):
                return True
        return False
    text = extract_text(value).strip().lower()
    return text in {"true", "1", "yes", "y", "是", "已勾选", "checked"}


def should_process_one_click_grid_record(record: Dict[str, Any]) -> bool:
    fields = record.get("fields") or {}
    return checkbox_checked(fields.get(ONE_CLICK_GRID_FIELD))


def build_one_click_result_update(status: str, result: Dict[str, Any]) -> Dict[str, Any]:
    return {
        ONE_CLICK_GRID_FIELD: False,
        ONE_CLICK_STATUS_FIELD: status,
        ONE_CLICK_RESULT_FIELD: json.dumps(result, ensure_ascii=False, indent=2, default=str)[:60000],
    }


def process_one_click_grid_record(
    record: Dict[str, Any],
    *,
    write: bool,
    call_models: bool,
    image_generate_fn: Callable[..., Dict[str, Any]] = run_image_generation,
    shot_records_fn: Callable[..., Dict[str, Any]] = create_or_preview_shot_records,
) -> Dict[str, Any]:
    if not call_models:
        raise ValueError("一键重生成9宫格会触发真实图片模型调用，需要显式 --call-models")
    record_id = record.get("record_id") or ""
    image_result = image_generate_fn(record_id, call_image=True, write=write)
    shot_result = shot_records_fn(record_id, write=write, overwrite_existing=True)
    return {
        "stage": "grid",
        "mode": "overwrite_current_grid_and_shots",
        "source_record_id": record_id,
        "status": "success",
        "result": {
            "image_generation": image_result,
            "shot_records": shot_result,
        },
    }


def list_records(token: str, table_id: str, *, limit: int = 200) -> List[Dict[str, Any]]:
    from tk_ugc_reroll import list_ugc_records

    return list_ugc_records(token, table_id, page_size=min(max(limit, 1), 500))[:limit]


def run_stage(
    *,
    stage: str,
    token: str,
    table_id: str,
    limit: int,
    write: bool,
    call_models: bool,
    records: Optional[Iterable[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    records_list = list(records) if records is not None else list_records(token, table_id, limit=limit)
    if stage != "grid":
        return {
            "stage": stage,
            "dry_run": not write,
            "call_models": call_models,
            "one_click_pending_count": 0,
            "processed": [],
            "skipped_reason": "旧候选池触发字段已删除；当前仅支持 UGC-04 一键覆盖重生成。",
        }

    pending = [record for record in records_list if should_process_one_click_grid_record(record)]
    outputs: List[Dict[str, Any]] = []
    for record in pending[:limit]:
        record_id = record.get("record_id") or ""
        if write:
            update_ugc_record(token, table_id, record_id, {ONE_CLICK_STATUS_FIELD: STATUS_RUNNING})
        try:
            processed = process_one_click_grid_record(record, write=write, call_models=call_models)
            if write:
                update_ugc_record(token, table_id, record_id, build_one_click_result_update(STATUS_SUCCESS, processed))
            outputs.append(processed)
        except Exception as exc:
            failure = {"stage": stage, "mode": "overwrite_current_grid", "source_record_id": record_id, "status": "failed", "error": str(exc)}
            if write:
                update_ugc_record(token, table_id, record_id, build_one_click_result_update(STATUS_FAILED, failure))
            outputs.append(failure)
    return {"stage": stage, "dry_run": not write, "call_models": call_models, "one_click_pending_count": len(pending), "processed": outputs}


def main() -> int:
    parser = argparse.ArgumentParser(description="Poll Feishu UGC one-click reroll trigger fields and overwrite current UGC-04 grid images.")
    parser.add_argument("--stage", choices=["grid", "video", "all"], default="grid")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--write", action="store_true", help="Update source records and write generated assets. Default is dry-run.")
    parser.add_argument("--call-models", action="store_true", help="Allow real image model calls. Required for one-click regeneration.")
    args = parser.parse_args()

    token = get_feishu_token()
    table_ids = load_ugc_table_ids()
    stages = ["grid", "video"] if args.stage == "all" else [args.stage]
    table_by_stage = {
        "grid": table_ids["ugc_04_six_grid_storyboard"],
        "video": table_ids["ugc_06_shot_videos"],
    }
    results = [
        run_stage(
            stage=stage,
            token=token,
            table_id=table_by_stage[stage],
            limit=args.limit,
            write=args.write,
            call_models=args.call_models,
        )
        for stage in stages
    ]
    print(json.dumps({"results": results}, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
