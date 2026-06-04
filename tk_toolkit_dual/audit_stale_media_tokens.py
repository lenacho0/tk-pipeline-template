#!/usr/bin/env python3
"""只读审计附件字段与缓存 file_token 字段是否不一致。"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, Iterable, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (  # noqa: E402
    TABLE_FIRST_LAST_VIDEO,
    TABLE_MULTI_ROLE_FIRST_LAST,
    TABLE_NINE_GRID_VIDEO,
    TABLE_SCRIPT_DOC_REFERENCE_ASSETS,
    TABLE_SCRIPT_DOC_SHOTS,
    extract_attachment_tokens,
    extract_text,
    get_feishu_token,
    safe_list_records,
)


TABLE_SPECS = [
    {
        "key": "001",
        "name": "001-多角色首尾帧生成表",
        "table_id": TABLE_MULTI_ROLE_FIRST_LAST,
        "pairs": [
            ("参考图", "参考图file_token"),
            ("关键帧图", "关键帧图file_token"),
            ("视频片段", "视频片段file_token"),
        ],
    },
    {
        "key": "002",
        "name": "002-首尾帧视频生成表",
        "table_id": TABLE_FIRST_LAST_VIDEO,
        "pairs": [
            ("首帧图", "首帧图file_token"),
            ("尾帧图", "尾帧图file_token"),
            ("首尾帧视频", "首尾帧视频file_token"),
        ],
    },
    {
        "key": "003-ref",
        "name": "003-2脚本文档-参考资产表",
        "table_id": TABLE_SCRIPT_DOC_REFERENCE_ASSETS,
        "pairs": [("参考图", "参考图file_token")],
    },
    {
        "key": "003-shot",
        "name": "003-3脚本文档-分镜生产表",
        "table_id": TABLE_SCRIPT_DOC_SHOTS,
        "pairs": [
            ("分镜图", "分镜图file_token"),
            ("尾帧图", "尾帧图file_token"),
            ("分镜视频", "分镜视频file_token"),
        ],
    },
    {
        "key": "005",
        "name": "005-多图九宫格视频生成表",
        "table_id": TABLE_NINE_GRID_VIDEO,
        "pairs": [
            ("参考图", "参考图file_token"),
            ("九宫格图", "九宫格图file_token"),
            ("分镜视频", "分镜视频file_token"),
        ],
    },
]


def audit_records(
    records: Iterable[Dict[str, Any]],
    pairs: Iterable[tuple[str, str]],
    *,
    table_key: str,
    table_name: str,
) -> List[Dict[str, str]]:
    findings: List[Dict[str, str]] = []
    for rec in records:
        fields = rec.get("fields") or {}
        record_id = extract_text(rec.get("record_id")).strip()
        task_name = extract_text(fields.get("任务名称") or fields.get("标题") or fields.get("资产名称")).strip()
        for attachment_field, cached_field in pairs:
            attachment_tokens = extract_attachment_tokens(fields.get(attachment_field))
            latest_attachment = attachment_tokens[-1] if attachment_tokens else ""
            cached_token = extract_text(fields.get(cached_field)).strip()
            if not latest_attachment:
                continue
            if cached_token == latest_attachment:
                continue
            findings.append({
                "table_key": table_key,
                "table_name": table_name,
                "record_id": record_id,
                "task_name": task_name,
                "attachment_field": attachment_field,
                "cached_field": cached_field,
                "latest_attachment_token": latest_attachment,
                "cached_token": cached_token,
                "status": "missing_cache" if not cached_token else "stale_cache",
            })
    return findings


def selected_specs(keys: List[str]) -> List[Dict[str, Any]]:
    if not keys or keys == ["all"]:
        return TABLE_SPECS
    wanted = set(keys)
    return [spec for spec in TABLE_SPECS if spec["key"] in wanted]


def run_audit(keys: List[str]) -> List[Dict[str, str]]:
    token = get_feishu_token()
    findings: List[Dict[str, str]] = []
    for spec in selected_specs(keys):
        table_id = spec.get("table_id") or ""
        if not table_id:
            continue
        records = safe_list_records(token, table_id)
        findings.extend(audit_records(
            records,
            spec["pairs"],
            table_key=spec["key"],
            table_name=spec["name"],
        ))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="只读审计附件最新 token 与缓存 file_token 是否不一致")
    parser.add_argument("--table", action="append", default=["all"], help="表 key：all/001/002/003-ref/003-shot/005，可重复传")
    parser.add_argument("--pretty", action="store_true", help="格式化 JSON 输出")
    args = parser.parse_args()
    keys = [item for value in args.table for item in str(value).split(",") if item]
    findings = run_audit(keys)
    print(json.dumps(findings, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
