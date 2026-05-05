#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from typing import Any, Callable, Dict, Iterable, List, Optional

from ugc_config import UGC_BASE_TOKEN, load_ugc_table_ids
from ugc_reroll_utils import make_group_id, next_candidate_index
from ugc_utils import extract_linked_record_ids, extract_text
from tk_ugc_six_grid import GRID_STATUS_FIELD, LEGACY_GRID_STATUS_FIELD, get_feishu_token, get_ugc_record, run_image_generation, run_prepare, update_ugc_record
from tk_ugc_shot_images import create_or_preview_shot_records
from tk_ugc_video_prompts import create_or_preview_ugc06_records
from tk_ugc_shot_videos import run_ugc06_video_generation

RecordGetter = Callable[[str, str, str], Dict[str, Any]]
RecordUpdater = Callable[[str, str, str, Dict[str, Any]], Any]


def _candidate_records(existing_candidates: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return list(existing_candidates or [])


def plan_grid_reroll(
    ugc03_record_id: str,
    *,
    count: int = 1,
    source_record_id: str = "",
    existing_candidates: Iterable[Dict[str, Any]] = (),
) -> Dict[str, Any]:
    group_id = make_group_id("grid", ugc03_record_id)
    start = next_candidate_index(_candidate_records(existing_candidates))
    candidates = [
        {
            "candidate_group_id": group_id,
            "candidate_index": start + i,
            "ugc03_record_id": ugc03_record_id,
            "reroll_source_record_id": source_record_id,
        }
        for i in range(max(0, count))
    ]
    return {"type": "grid", "ugc03_record_id": ugc03_record_id, "source_record_id": source_record_id, "candidates": candidates}


def plan_video_reroll(
    ugc05_record_id: str,
    *,
    count: int = 1,
    source_record_id: str = "",
    existing_candidates: Iterable[Dict[str, Any]] = (),
) -> Dict[str, Any]:
    group_id = make_group_id("video", ugc05_record_id)
    start = next_candidate_index(_candidate_records(existing_candidates))
    candidates = [
        {
            "candidate_group_id": group_id,
            "candidate_index": start + i,
            "ugc05_record_id": ugc05_record_id,
            "reroll_source_record_id": source_record_id,
        }
        for i in range(max(0, count))
    ]
    return {"type": "video", "ugc05_record_id": ugc05_record_id, "source_record_id": source_record_id, "candidates": candidates}


def plan_video_reroll_from_ugc06(
    ugc06_record_id: str,
    *,
    count: int = 1,
    token: Optional[str] = None,
    get_record_fn: RecordGetter = get_ugc_record,
    existing_candidates: Iterable[Dict[str, Any]] = (),
) -> Dict[str, Any]:
    token = token or get_feishu_token()
    table_ids = load_ugc_table_ids()
    fields = get_record_fn(token, table_ids["ugc_06_shot_videos"], ugc06_record_id)
    ugc05_ids = extract_linked_record_ids(fields.get("关联分镜图片"))
    if not ugc05_ids:
        fallback = extract_text(fields.get("来源UGC05候选记录ID")).strip()
        if fallback:
            ugc05_ids = [fallback]
    if len(ugc05_ids) != 1:
        raise ValueError(f"UGC-06 {ugc06_record_id} 必须且只能关联 1 条 UGC-05 分镜图片，actual={ugc05_ids}")
    return plan_video_reroll(
        ugc05_ids[0],
        count=count,
        source_record_id=ugc06_record_id,
        existing_candidates=existing_candidates,
    )


def execute_grid_plan(
    plan: Dict[str, Any],
    *,
    write: bool = False,
    call_image: bool = False,
    create_shots: bool = False,
) -> Dict[str, Any]:
    results = []
    created_record_ids: List[str] = []
    for item in plan.get("candidates") or []:
        prepared = run_prepare(
            item["ugc03_record_id"],
            write=write,
            candidate_group_id=item["candidate_group_id"],
            candidate_index=item["candidate_index"],
            reroll_source_record_id=item.get("reroll_source_record_id", ""),
        )
        ugc04_record_id = prepared.get("ugc04_record_id") or ""
        if ugc04_record_id:
            created_record_ids.append(ugc04_record_id)
        if write and call_image and ugc04_record_id:
            prepared["image_generation"] = run_image_generation(ugc04_record_id, call_image=True, write=True)
        if write and create_shots and ugc04_record_id:
            prepared["shot_records"] = create_or_preview_shot_records(ugc04_record_id, write=True)
        results.append(prepared)
    return {"plan": plan, "write": write, "call_image": call_image, "create_shots": create_shots, "created_record_ids": created_record_ids, "results": results}


def execute_video_plan(plan: Dict[str, Any], *, write: bool = False, call_video: bool = False) -> Dict[str, Any]:
    results = []
    created_record_ids: List[str] = []
    for item in plan.get("candidates") or []:
        created = create_or_preview_ugc06_records(
            [item["ugc05_record_id"]],
            write=write,
            candidate_group_id=item["candidate_group_id"],
            candidate_index=item["candidate_index"],
            reroll_source_record_id=item.get("reroll_source_record_id", ""),
        )
        for record in created.get("created_records") or []:
            record_id = record.get("record_id") or ""
            if record_id:
                created_record_ids.append(record_id)
                if call_video:
                    record["video_generation"] = run_ugc06_video_generation(record_id, dry_run=False)
        results.append(created)
    return {"plan": plan, "write": write, "call_video": call_video, "created_record_ids": created_record_ids, "results": results}


def list_ugc_records(token: str, table_id: str, *, page_size: int = 500) -> List[Dict[str, Any]]:
    from common import feishu_headers, safe_request

    records: List[Dict[str, Any]] = []
    page_token = ""
    while True:
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{UGC_BASE_TOKEN}/tables/{table_id}/records?page_size={page_size}"
        if page_token:
            url += f"&page_token={page_token}"
        data = safe_request("get", url, headers=feishu_headers(token), timeout=30, max_attempts=3)
        records.extend(data.get("data", {}).get("items") or [])
        if not data.get("data", {}).get("has_more"):
            break
        page_token = data.get("data", {}).get("page_token") or ""
        if not page_token:
            break
    return records


def filter_candidate_group(records: Iterable[Dict[str, Any]], group_id: str) -> List[Dict[str, Any]]:
    return [record for record in records if extract_text((record.get("fields") or {}).get("重生成组ID")).strip() == group_id]


def candidate_success_status(fields: Dict[str, Any], status_field: str = "") -> str:
    if status_field:
        value = extract_text(fields.get(status_field)).strip()
        if value or status_field != GRID_STATUS_FIELD:
            return value
        return extract_text(fields.get(LEGACY_GRID_STATUS_FIELD)).strip()
    if "视频生成状态" in fields:
        return extract_text(fields.get("视频生成状态")).strip()
    return extract_text(fields.get(GRID_STATUS_FIELD) or fields.get(LEGACY_GRID_STATUS_FIELD)).strip()


def apply_selection(
    *,
    table_id: str,
    group_id: str,
    selected_record_id: str,
    records: Iterable[Dict[str, Any]],
    token: str,
    update_record_fn: RecordUpdater = update_ugc_record,
    allow_non_success: bool = False,
    status_field: str = "",
) -> Dict[str, Any]:
    group_records = filter_candidate_group(records, group_id)
    if not group_records:
        raise ValueError(f"未找到候选组记录: {group_id}")
    selected = [record for record in group_records if record.get("record_id") == selected_record_id]
    if len(selected) != 1:
        raise ValueError(f"候选组 {group_id} 中未唯一找到选择记录: {selected_record_id}")
    selected_status = candidate_success_status(selected[0].get("fields") or {}, status_field=status_field)
    if selected_status != "成功" and not allow_non_success:
        raise ValueError(f"选择记录 {selected_record_id} 尚未成功，当前状态={selected_status or '空'}；如需强制请选择 allow_non_success")
    updates: List[Dict[str, Any]] = []
    for record in group_records:
        record_id = record.get("record_id") or ""
        new_status = "采用" if record_id == selected_record_id else "弃用"
        update_fields = {"候选状态": new_status}
        update_record_fn(token, table_id, record_id, update_fields)
        updates.append({"record_id": record_id, "fields": update_fields})
    return {"group_id": group_id, "selected_record_id": selected_record_id, "updates": updates}


def main() -> int:
    parser = argparse.ArgumentParser(description="UGC reroll candidate planner/orchestrator. Defaults to dry-run; no model calls.")
    sub = parser.add_subparsers(dest="command", required=True)

    grid = sub.add_parser("grid", help="Plan/create UGC-04 grid reroll candidates from one UGC-03 script version")
    grid.add_argument("--ugc03-record-id", required=True)
    grid.add_argument("--source-record-id", default="")
    grid.add_argument("--count", type=int, default=1)
    grid.add_argument("--write", action="store_true", help="Create candidate UGC-04 records")
    grid.add_argument("--dry-run", action="store_true", help="Compatibility flag; default behavior is already dry-run unless --write/--call-image/--create-shots is set")
    grid.add_argument("--call-image", action="store_true", help="Sequentially call image model for newly-created UGC-04 candidates")
    grid.add_argument("--create-shots", action="store_true", help="Create UGC-05 records from successful new UGC-04 candidates")

    video = sub.add_parser("video", help="Plan/create UGC-06 video reroll candidates from a UGC-05 shot image or source UGC-06")
    video_src = video.add_mutually_exclusive_group(required=True)
    video_src.add_argument("--ugc05-record-id")
    video_src.add_argument("--ugc06-record-id", help="Source UGC-06 record; its linked UGC-05 will be used")
    video.add_argument("--source-record-id", default="")
    video.add_argument("--count", type=int, default=1)
    video.add_argument("--write", action="store_true", help="Create UGC-06 candidate records; does not call video model unless --call-video is set")
    video.add_argument("--dry-run", action="store_true", help="Compatibility flag; default behavior is already dry-run unless --write/--call-video is set")
    video.add_argument("--call-video", action="store_true", help="Sequentially call video model for newly-created UGC-06 candidates")

    select_grid = sub.add_parser("select-grid", help="Mark one UGC-04 candidate adopted and discard siblings in the same group")
    select_grid.add_argument("--group-id", required=True)
    select_grid.add_argument("--record-id", required=True)
    select_grid.add_argument("--write", action="store_true")
    select_grid.add_argument("--dry-run", action="store_true", help="Compatibility flag; default behavior previews updates unless --write is set")
    select_grid.add_argument("--allow-non-success", action="store_true")

    select_video = sub.add_parser("select-video", help="Mark one UGC-06 video candidate adopted and discard siblings in the same group")
    select_video.add_argument("--group-id", required=True)
    select_video.add_argument("--record-id", required=True)
    select_video.add_argument("--write", action="store_true")
    select_video.add_argument("--dry-run", action="store_true", help="Compatibility flag; default behavior previews updates unless --write is set")
    select_video.add_argument("--allow-non-success", action="store_true")

    args = parser.parse_args()
    token = get_feishu_token() if args.command.startswith("select-") else None
    if args.command == "grid":
        plan = plan_grid_reroll(args.ugc03_record_id, count=args.count, source_record_id=args.source_record_id)
        result = execute_grid_plan(plan, write=args.write, call_image=args.call_image, create_shots=args.create_shots) if (args.write or args.call_image or args.create_shots) else plan
    elif args.command == "video":
        if args.ugc06_record_id:
            plan = plan_video_reroll_from_ugc06(args.ugc06_record_id, count=args.count)
        else:
            plan = plan_video_reroll(args.ugc05_record_id, count=args.count, source_record_id=args.source_record_id)
        result = execute_video_plan(plan, write=args.write, call_video=args.call_video) if (args.write or args.call_video) else plan
    elif args.command in ("select-grid", "select-video"):
        table_ids = load_ugc_table_ids()
        table_id = table_ids["ugc_04_six_grid_storyboard"] if args.command == "select-grid" else table_ids["ugc_06_shot_videos"]
        records = list_ugc_records(token, table_id)
        preview = apply_selection(
            table_id=table_id,
            group_id=args.group_id,
            selected_record_id=args.record_id,
            records=records,
            token=token,
            update_record_fn=update_ugc_record if args.write else (lambda token, table, rid, fields: None),
            allow_non_success=args.allow_non_success,
            status_field=GRID_STATUS_FIELD if args.command == "select-grid" else "视频生成状态",
        )
        result = {"dry_run": not args.write, **preview}
    else:
        raise ValueError(f"unsupported command: {args.command}")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
