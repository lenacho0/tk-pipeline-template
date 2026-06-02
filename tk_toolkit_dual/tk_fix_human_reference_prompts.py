#!/usr/bin/env python3
"""Fix pending human reference prompts to the white-background front-facing rule."""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Callable, Dict, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import (  # noqa: E402
    TABLE_MULTI_ROLE_FIRST_LAST,
    TABLE_NINE_GRID_VIDEO,
    TABLE_SCRIPT_DOC_REFERENCE_ASSETS,
    extract_text,
    get_feishu_token,
    safe_list_records,
    safe_update_record,
)
from tk_multi_role_first_last import (  # noqa: E402
    build_reference_image_generation_prompt as build_multi_role_prompt,
)
from tk_nine_grid_video import (  # noqa: E402
    build_reference_image_generation_prompt as build_nine_grid_prompt,
)
from tk_script_doc_shots import build_reference_image_prompt  # noqa: E402
from tk_shot_storyboard import filter_existing_fields  # noqa: E402


PENDING_STATUSES = {"待生成", "失败"}
REGENERATE_OPERATIONS = {"重新生成参考图"}


def _is_human(fields: Dict[str, Any], type_field: str) -> bool:
    return extract_text(fields.get(type_field)).strip().lower() in {"human", "person", "人物", "角色"}


def _needs_prompt_update(fields: Dict[str, Any]) -> bool:
    status = extract_text(fields.get("参考图生成状态")).strip()
    operation = extract_text(fields.get("参考图操作")).strip()
    return status in PENDING_STATUSES or operation in REGENERATE_OPERATIONS


def _already_strict(prompt: str) -> bool:
    return all(
        phrase in prompt
        for phrase in ["pure white background", "front-facing upper-body", "full unobstructed face visible"]
    )


def _candidate_records(
    token: str,
    *,
    table_id: str,
    table_name: str,
    type_field: str,
    prompt_builder: Callable[[Dict[str, Any]], str],
) -> List[Dict[str, Any]]:
    if not table_id:
        return []
    candidates: List[Dict[str, Any]] = []
    for rec in safe_list_records(token, table_id):
        fields = rec.get("fields") or {}
        if not _is_human(fields, type_field):
            continue
        if not _needs_prompt_update(fields):
            continue
        old_prompt = extract_text(fields.get("参考提示词")).strip()
        if not old_prompt:
            continue
        new_prompt = prompt_builder(fields)
        if not new_prompt or new_prompt == old_prompt or _already_strict(old_prompt):
            continue
        candidates.append({
            "table": table_name,
            "table_id": table_id,
            "record_id": rec["record_id"],
            "status": extract_text(fields.get("参考图生成状态")).strip(),
            "operation": extract_text(fields.get("参考图操作")).strip(),
            "old_prompt_chars": len(old_prompt),
            "new_prompt_chars": len(new_prompt),
            "new_prompt": new_prompt,
        })
    return candidates


def collect_candidates(token: str) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    candidates.extend(_candidate_records(
        token,
        table_id=TABLE_MULTI_ROLE_FIRST_LAST,
        table_name="001-多角色首尾帧生成表",
        type_field="资产类型",
        prompt_builder=build_multi_role_prompt,
    ))
    candidates.extend(_candidate_records(
        token,
        table_id=TABLE_NINE_GRID_VIDEO,
        table_name="多图九宫格视频生成表",
        type_field="资产类型",
        prompt_builder=build_nine_grid_prompt,
    ))
    candidates.extend(_candidate_records(
        token,
        table_id=TABLE_SCRIPT_DOC_REFERENCE_ASSETS,
        table_name="003-2脚本文档-参考资产表",
        type_field="参考类型",
        prompt_builder=build_reference_image_prompt,
    ))
    return candidates


def main() -> None:
    parser = argparse.ArgumentParser(description="Fix pending human reference prompts to front-facing white-background rules.")
    parser.add_argument("--write", action="store_true", help="Write prompt updates to Feishu. Defaults to dry-run.")
    args = parser.parse_args()

    token = get_feishu_token()
    candidates = collect_candidates(token)
    if args.write:
        for item in candidates:
            safe_update_record(
                token,
                item["table_id"],
                item["record_id"],
                filter_existing_fields(token, item["table_id"], {"参考提示词": item["new_prompt"]}),
            )

    output = {
        "mode": "write" if args.write else "dry_run",
        "count": len(candidates),
        "records": [
            {key: value for key, value in item.items() if key not in {"new_prompt", "table_id"}}
            for item in candidates
        ],
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
