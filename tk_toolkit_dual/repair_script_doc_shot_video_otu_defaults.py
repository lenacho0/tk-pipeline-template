#!/usr/bin/env python3
"""
修复有「视频通道」字段的视频表里尚未生成的旧 AIHubMix 默认记录。

默认 dry-run 只列出候选；加 --write 才写回飞书。
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import (  # noqa: E402
    TABLE_FIRST_LAST_VIDEO,
    TABLE_MULTI_ROLE_FIRST_LAST,
    TABLE_SCRIPT_DOC_SHOTS,
    extract_text,
    get_feishu_token,
    safe_list_records,
    safe_update_record,
)
from tk_model_config_center import TASK_TABLES, load_task_default_fields  # noqa: E402
from tk_script_doc_shots import filter_existing_fields  # noqa: E402


@dataclass(frozen=True)
class TableRepairSpec:
    table_key: str
    table_name: str
    table_id: str
    default_stage: str


TABLE_REPAIR_SPECS = (
    TableRepairSpec(
        "first_last_video",
        "002-首尾帧视频生成表",
        TABLE_FIRST_LAST_VIDEO,
        "首尾帧视频生成默认",
    ),
    TableRepairSpec(
        "multi_role_first_last",
        "001-多角色首尾帧生成表",
        TABLE_MULTI_ROLE_FIRST_LAST,
        "视频片段生成默认",
    ),
    TableRepairSpec(
        "script_doc_shots",
        "003-3脚本文档-分镜生产表",
        TABLE_SCRIPT_DOC_SHOTS,
        "分镜视频生成默认",
    ),
)

ACTIVE_STATUSES = {"", "不触发", "待生成"}
LEGACY_MODEL_VALUES = {
    "",
    "默认",
    "默认（配置表）",
    "默认(配置表)",
    "配置表默认",
    "OTU / 默认",
    "OTU / 默认（配置表）",
    "OTU / 默认(配置表)",
    "OTU / 配置表默认",
    "AIHubMix / 默认",
    "AIHubMix / 默认（配置表）",
    "AIHubMix / 默认(配置表)",
    "AIHubMix / 配置表默认",
    "AIHubMix / veo-3.1-fast-generate-preview",
}
OTU_PLACEHOLDER_MODEL_VALUES = {
    "OTU / 默认",
    "OTU / 默认（配置表）",
    "OTU / 默认(配置表)",
    "OTU / 配置表默认",
}
AIHUBMIX_PLACEHOLDER_MODEL_VALUES = LEGACY_MODEL_VALUES - OTU_PLACEHOLDER_MODEL_VALUES


def normalized_text(value: Any) -> str:
    return extract_text(value).strip()


def is_candidate(fields: Dict[str, Any]) -> bool:
    status = normalized_text(fields.get("视频生成状态"))
    channel = normalized_text(fields.get("视频通道"))
    model = normalized_text(fields.get("视频生成模型"))
    if status not in ACTIVE_STATUSES:
        return False
    if channel == "OTU":
        return model in OTU_PLACEHOLDER_MODEL_VALUES
    if channel == "AIHubMix":
        return model in AIHUBMIX_PLACEHOLDER_MODEL_VALUES
    return False


def default_patch(token: str, spec: TableRepairSpec) -> Dict[str, Any]:
    defaults = load_task_default_fields(
        token,
        TASK_TABLES[spec.table_key],
        spec.default_stage,
    ) or {}
    return {
        "视频通道": defaults.get("默认供应商") or "OTU",
        "视频生成模型": defaults.get("默认模型显示名称") or "OTU / veo_3_1-fast-fl",
        "视频画面尺寸": defaults.get("画面尺寸") or "720x1280",
        "视频画面比例": defaults.get("画面比例") or "9:16",
    }


def repair(*, write: bool = False, limit: int = 0) -> Dict[str, Any]:
    token = get_feishu_token()
    tables: List[Dict[str, Any]] = []
    total_candidates = 0
    total_updated = 0

    for spec in TABLE_REPAIR_SPECS:
        if not spec.table_id:
            raise RuntimeError(f"config.json 尚未配置 {spec.table_key} 表 ID")
        patch = default_patch(token, spec)
        candidates: List[Dict[str, Any]] = []
        updated = 0

        for record in safe_list_records(token, spec.table_id):
            if limit and total_candidates >= limit:
                break
            record_id = str(record.get("record_id") or record.get("id") or "")
            fields = record.get("fields") or {}
            if not is_candidate(fields):
                continue
            candidate = {
                "table_key": spec.table_key,
                "table_name": spec.table_name,
                "record_id": record_id,
                "任务名称": normalized_text(fields.get("任务名称")),
                "视频生成状态": normalized_text(fields.get("视频生成状态")),
                "视频通道": normalized_text(fields.get("视频通道")),
                "视频生成模型": normalized_text(fields.get("视频生成模型")),
            }
            candidates.append(candidate)
            total_candidates += 1
            if write:
                writable_patch = filter_existing_fields(token, spec.table_id, patch)
                safe_update_record(token, spec.table_id, record_id, writable_patch)
                updated += 1
                total_updated += 1

        tables.append({
            "table_key": spec.table_key,
            "table_name": spec.table_name,
            "table_id": spec.table_id,
            "candidate_count": len(candidates),
            "updated": updated,
            "patch": patch,
            "candidates": candidates,
        })

    return {
        "dry_run": not write,
        "candidate_count": total_candidates,
        "updated": total_updated,
        "tables": tables,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="修复视频表旧 AIHubMix 默认值")
    parser.add_argument("--write", action="store_true", help="实际写回飞书；默认只 dry-run")
    parser.add_argument("--limit", type=int, default=0, help="最多处理多少条候选；默认不限制")
    args = parser.parse_args()

    result = repair(write=args.write, limit=args.limit)
    print(f"candidate_count={result['candidate_count']} updated={result['updated']}")
    for table in result["tables"]:
        print(
            f"table={table['table_name']} table_id={table['table_id']} "
            f"dry_run={result['dry_run']} candidates={table['candidate_count']} updated={table['updated']}"
        )
        print(f"patch={table['patch']}")
        for item in table["candidates"]:
            print(
                f"- {item['record_id']} | {item['任务名称']} | "
                f"status={item['视频生成状态']} | channel={item['视频通道']} | model={item['视频生成模型']}"
            )


if __name__ == "__main__":
    main()
