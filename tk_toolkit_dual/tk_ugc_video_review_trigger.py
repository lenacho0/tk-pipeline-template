#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from typing import Any, Callable, Dict, Iterable, List, Optional

from ugc_config import load_ugc_table_ids
from ugc_utils import extract_text
from tk_ugc_reroll import list_ugc_records
from tk_ugc_six_grid import get_feishu_token, update_ugc_record
from tk_ugc_shot_videos import run_ugc06_video_generation

STATUS_RUNNING = "处理中"
STATUS_SUCCESS = "成功"
STATUS_FAILED = "失败"
ACTION_IDLE = "不触发"
ACTION_REGEN_VIDEO = "重新生成分镜视频"
ACTION_GENERATE_VIDEO = "生成分镜视频"


def norm(value: Any) -> str:
    return extract_text(value).strip()


def should_regenerate_video(fields: Dict[str, Any]) -> bool:
    return norm(fields.get("分镜视频操作")) in {ACTION_REGEN_VIDEO, ACTION_GENERATE_VIDEO}


def build_result_update(status: str, result: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "分镜视频操作": ACTION_IDLE,
        "分镜视频执行状态": status,
        "分镜视频执行结果": json.dumps(result, ensure_ascii=False, indent=2, default=str)[:60000],
    }


def process_video_regen_record(
    record: Dict[str, Any],
    *,
    write: bool,
    call_models: bool,
    video_fn: Callable[..., Dict[str, Any]] = run_ugc06_video_generation,
) -> Dict[str, Any]:
    if not call_models:
        raise ValueError("重新生成分镜视频 会触发真实视频模型调用，需要显式 --call-models")
    record_id = record.get("record_id") or ""
    result = video_fn(record_id, dry_run=not write, allow_overwrite=True)
    return {"stage": "ugc06_video_regen", "source_record_id": record_id, "status": "success", "result": result}


def run_video_review_stage(
    *,
    token: str,
    ugc06_table: str,
    limit: int,
    write: bool,
    call_models: bool,
    records: Optional[Iterable[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    records_list = list(records) if records is not None else list_ugc_records(token, ugc06_table, page_size=500)
    pending = [record for record in records_list if should_regenerate_video(record.get("fields") or {})]
    outputs: List[Dict[str, Any]] = []
    for record in pending[:limit]:
        record_id = record.get("record_id") or ""
        if write:
            update_ugc_record(token, ugc06_table, record_id, {"分镜视频执行状态": STATUS_RUNNING})
        try:
            processed = process_video_regen_record(record, write=write, call_models=call_models)
            if write:
                update_ugc_record(token, ugc06_table, record_id, build_result_update(STATUS_SUCCESS, processed))
            outputs.append(processed)
        except Exception as exc:
            failure = {"stage": "ugc06_video_regen", "source_record_id": record_id, "status": "failed", "error": str(exc)}
            if write:
                update_ugc_record(token, ugc06_table, record_id, build_result_update(STATUS_FAILED, failure))
            outputs.append(failure)
    return {"stage": "ugc06_video_review", "dry_run": not write, "call_models": call_models, "pending_count": len(pending), "processed": outputs}


def main() -> int:
    parser = argparse.ArgumentParser(description="Poll UGC-06 video review action fields and regenerate individual shot videos.")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--call-models", action="store_true")
    args = parser.parse_args()
    token = get_feishu_token()
    table_ids = load_ugc_table_ids()
    result = run_video_review_stage(
        token=token,
        ugc06_table=table_ids["ugc_06_shot_videos"],
        limit=args.limit,
        write=args.write,
        call_models=args.call_models,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
