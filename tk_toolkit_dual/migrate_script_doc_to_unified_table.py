#!/usr/bin/env python3
"""Copy legacy 003 script-doc rows into the new unified 003 table.

Default mode is dry-run. Use --write only after the unified table exists and
feishu.tables.script_doc_unified is configured.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, Iterable, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (  # noqa: E402
    APP_TOKEN,
    TABLE_SCRIPT_DOC_REFERENCE_ASSETS,
    TABLE_SCRIPT_DOC_SHOTS,
    TABLE_SCRIPT_DOC_TASKS,
    TABLE_SCRIPT_DOC_UNIFIED,
    feishu_headers,
    get_feishu_token,
    safe_list_records,
    safe_request,
)
from tk_create_script_doc_shots_table import UNIFIED_REMOVED_FIELDS  # noqa: E402
from tk_script_doc_shots import filter_existing_fields  # noqa: E402


SOURCE_TABLES = [
    ("003-1脚本文档-任务表", TABLE_SCRIPT_DOC_TASKS, "文档任务"),
    ("003-2脚本文档-参考资产表", TABLE_SCRIPT_DOC_REFERENCE_ASSETS, "参考资产"),
    ("003-3脚本文档-分镜生产表", TABLE_SCRIPT_DOC_SHOTS, "分镜"),
]


def sanitize_fields(fields: Dict[str, Any], record_type: str, old_source: str, old_record_id: str, parent_map: Dict[str, str]) -> Dict[str, Any]:
    cleaned = {
        key: value
        for key, value in fields.items()
        if key not in UNIFIED_REMOVED_FIELDS and not key.startswith("口播音频")
    }
    if record_type == "文档任务" and "脚本文档" not in cleaned:
        raw_doc = fields.get("脚本文档") or fields.get("脚本文档正文")
        if raw_doc:
            cleaned["脚本文档"] = raw_doc
    old_parent_id = str(cleaned.get("父文档记录ID") or "").strip()
    if old_parent_id and old_parent_id in parent_map:
        cleaned["父文档记录ID"] = parent_map[old_parent_id]
        cleaned["关联任务"] = [parent_map[old_parent_id]]
    cleaned["记录类型"] = record_type
    return cleaned


def create_unified_records(token: str, records: List[Dict[str, Any]]) -> List[str]:
    created_ids: List[str] = []
    for record in records:
        payload = {"fields": filter_existing_fields(token, TABLE_SCRIPT_DOC_UNIFIED, record)}
        data = safe_request(
            "post",
            f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_SCRIPT_DOC_UNIFIED}/records",
            headers=feishu_headers(token),
            json=payload,
            timeout=30,
            max_attempts=3,
            acceptable_codes=(0,),
        )
        created = ((data.get("data") or {}).get("record") or {})
        created_ids.append(created.get("record_id") or created.get("id") or "")
    return created_ids


def load_source_records(token: str) -> Dict[str, List[Dict[str, Any]]]:
    loaded: Dict[str, List[Dict[str, Any]]] = {}
    for source_name, table_id, _record_type in SOURCE_TABLES:
        if not table_id:
            loaded[source_name] = []
            continue
        loaded[source_name] = safe_list_records(token, table_id)
    return loaded


def build_migration_plan(source_records: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    return {
        "target_table": TABLE_SCRIPT_DOC_UNIFIED,
        "sources": {
            name: {
                "count": len(records),
                "sample_record_ids": [record.get("record_id") for record in records[:5]],
            }
            for name, records in source_records.items()
        },
        "omitted_fields": sorted(UNIFIED_REMOVED_FIELDS),
    }


def migrate(*, write: bool) -> Dict[str, Any]:
    if not TABLE_SCRIPT_DOC_UNIFIED:
        raise RuntimeError("config.json 尚未配置 feishu.tables.script_doc_unified")
    token = get_feishu_token()
    source_records = load_source_records(token)
    plan = build_migration_plan(source_records)
    if not write:
        plan["status"] = "dry_run"
        return plan

    parent_map: Dict[str, str] = {}
    created_summary: Dict[str, int] = {}
    for source_name, _table_id, record_type in SOURCE_TABLES:
        rows = source_records[source_name]
        payloads = [
            sanitize_fields(row.get("fields") or {}, record_type, source_name, row.get("record_id") or "", parent_map)
            for row in rows
        ]
        created_ids = create_unified_records(token, payloads)
        created_summary[source_name] = len([item for item in created_ids if item])
        if record_type == "文档任务":
            for row, new_id in zip(rows, created_ids):
                old_id = row.get("record_id") or ""
                if old_id and new_id:
                    parent_map[old_id] = new_id

    plan["status"] = "written"
    plan["created"] = created_summary
    plan["parent_map_count"] = len(parent_map)
    return plan


def main() -> int:
    parser = argparse.ArgumentParser(description="迁移旧 003 三表数据到 003-脚本文档生产表")
    parser.add_argument("--write", action="store_true", help="真实写入；默认只 dry-run")
    args = parser.parse_args()
    result = migrate(write=args.write)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
