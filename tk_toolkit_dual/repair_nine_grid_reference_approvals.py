#!/usr/bin/env python3
"""
一次性收口九宫格参考图审核推进状态。

默认 dry-run 只输出候选和将执行的动作；加 --write 才会推进父任务并写回飞书。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tk_nine_grid_video as nine_grid  # noqa: E402


def _text(value: Any) -> str:
    return nine_grid.extract_text(value).strip()


def _build_actions(token: str, records: List[Dict[str, Any]], parent_record_id: str = "") -> Dict[str, Any]:
    assets_by_parent: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    boards_by_parent: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    candidates: List[Dict[str, Any]] = []
    missing_file: List[Dict[str, Any]] = []

    for rec in records:
        fields = rec.get("fields") or {}
        parent_id = _text(fields.get("父任务记录ID"))
        if parent_record_id and parent_id != parent_record_id:
            continue
        record_type = _text(fields.get("记录类型"))
        if record_type == nine_grid.ASSET_RECORD_TYPE:
            assets_by_parent[parent_id].append(rec)
            if _text(fields.get("参考图审核状态")) != "通过":
                continue
            candidates.append(rec)
            if not nine_grid._asset_reference_file_token(token, fields):
                missing_file.append(rec)
        elif record_type == "Board分段":
            boards_by_parent[parent_id].append(rec)

    mark_actions = []
    for rec in candidates:
        fields = rec.get("fields") or {}
        if not nine_grid._asset_reference_file_token(token, fields):
            continue
        parent_id = _text(fields.get("父任务记录ID"))
        mark_actions.append({
            "action": "mark_handled",
            "record_id": rec["record_id"],
            "parent_record_id": parent_id,
            "task_name": _text(fields.get("任务名称")),
        })

    advance_parent_ids = []
    for parent_id in sorted({item["parent_record_id"] for item in mark_actions if item["parent_record_id"]}):
        if any(_text((rec.get("fields") or {}).get("图片生成状态")) == "不触发" for rec in boards_by_parent.get(parent_id, [])):
            advance_parent_ids.append(parent_id)

    parents = []
    for parent_id in sorted(set(assets_by_parent) | set(boards_by_parent)):
        parent_assets = assets_by_parent.get(parent_id, [])
        parent_boards = boards_by_parent.get(parent_id, [])
        parents.append({
            "parent_record_id": parent_id,
            "asset_count": len(parent_assets),
            "passed_candidate_count": sum(1 for rec in parent_assets if _text((rec.get("fields") or {}).get("参考图审核状态")) == "通过"),
            "handled_asset_count": sum(1 for rec in parent_assets if _text((rec.get("fields") or {}).get("参考图审核状态")) == nine_grid.REFERENCE_REVIEW_HANDLED_STATUS),
            "untriggered_board_count": sum(1 for rec in parent_boards if _text((rec.get("fields") or {}).get("图片生成状态")) == "不触发"),
        })

    return {
        "candidate_count": len(candidates),
        "parent_count": len({item["parent_record_id"] for item in mark_actions if item["parent_record_id"]}),
        "missing_file_count": len(missing_file),
        "would_mark_handled_count": len(mark_actions),
        "would_advance_parent_count": len(advance_parent_ids),
        "advance_parent_ids": advance_parent_ids,
        "actions": mark_actions,
        "parents": parents,
    }


def repair_reference_approvals(
    token: str,
    *,
    records: Optional[List[Dict[str, Any]]] = None,
    parent_record_id: str = "",
    write: bool = False,
) -> Dict[str, Any]:
    table_records = records if records is not None else nine_grid.safe_list_records(token, nine_grid.TABLE_NINE_GRID_VIDEO)
    summary = _build_actions(token, table_records, parent_record_id=parent_record_id)
    summary["write"] = write

    if not write:
        return summary

    advance_results = []
    for parent_id in summary["advance_parent_ids"]:
        result = nine_grid.advance_boards_after_reference_approval(token, parent_id)
        advance_results.append(result)

    marked = 0
    for action in summary["actions"]:
        nine_grid.safe_update_record(
            token,
            nine_grid.TABLE_NINE_GRID_VIDEO,
            action["record_id"],
            nine_grid.filter_existing_fields(token, nine_grid.TABLE_NINE_GRID_VIDEO, {
                "参考图审核状态": nine_grid.REFERENCE_REVIEW_HANDLED_STATUS,
                "参考图操作": "不触发",
                "错误信息": "",
            }),
        )
        marked += 1

    summary["advanced_parent_count"] = len(advance_results)
    summary["marked_handled_count"] = marked
    summary["advance_results"] = advance_results
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="收口九宫格参考图审核推进状态")
    parser.add_argument("--write", action="store_true", help="实际写回飞书；默认只 dry-run")
    parser.add_argument("--parent-record-id", default="", help="只处理指定父任务记录ID")
    args = parser.parse_args()

    token = nine_grid.get_feishu_token()
    summary = repair_reference_approvals(token, parent_record_id=args.parent_record_id, write=args.write)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
