#!/usr/bin/env python3
"""Shared switch and guards for automatic review approval."""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, Iterable, Optional, Set

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (  # noqa: E402
    APP_TOKEN,
    TABLE_CONFIG,
    extract_text,
    feishu_headers,
    get_feishu_token,
    latest_media_token,
    safe_list_records,
    safe_request,
)


LEGACY_GLOBAL_AUTO_REVIEW_STAGE_NAME = "首尾帧/视频链路一键审核通过模式"
TABLE_AUTO_REVIEW_STAGE_NAMES = {
    "multi_role_first_last": "001-多角色首尾帧生成表一键审核通过模式",
    "first_last_video": "002-首尾帧视频生成表一键审核通过模式",
    "script_doc_shots": "003-脚本文档分镜链路一键审核通过模式",
    "script_doc_unified": "003-脚本文档生产表一键审核通过模式",
    "storyboard_video": "004-故事板视频生成表一键审核通过模式",
    "nine_grid_video": "005-多图宫格视频生成表一键审核通过模式",
    "prompt_image_video": "008-图生视频生成表一键审核通过模式",
}
AUTO_REVIEW_STAGE_ALIASES = {
    "005-多图宫格视频生成表一键审核通过模式": ("005-多图九宫格视频生成表一键审核通过模式",),
}
ENABLED_VALUES = {"启用", "开启", "是", "true", "1", "enabled", "enable", "on"}


def _norm(value: Any) -> str:
    return extract_text(value).strip()


def auto_review_enabled(
    token: str,
    *,
    stage_name: str = "",
    config_records: Optional[Iterable[Dict[str, Any]]] = None,
) -> bool:
    """Return whether a table-level auto-review switch is enabled.

    Missing config table, missing stage name, or missing switch record is intentionally treated as off.
    """
    if not TABLE_CONFIG or not stage_name:
        return False
    try:
        records = list(config_records) if config_records is not None else safe_list_records(token, TABLE_CONFIG)
    except Exception:
        return False
    stage_names = {stage_name, *AUTO_REVIEW_STAGE_ALIASES.get(stage_name, ())}
    for rec in records:
        fields = rec.get("fields") or {}
        if _norm(fields.get("环节")) not in stage_names:
            continue
        return _norm(fields.get("状态")).lower() in ENABLED_VALUES
    return False


def generated_result_can_auto_review(
    fields: Dict[str, Any],
    *,
    attachment_field: str,
    token_field: str,
    version_field: str = "",
    first_version_only: bool = False,
    operation_field: str = "",
    regeneration_values: Optional[Set[str]] = None,
) -> bool:
    if not latest_media_token(fields, attachment_field, token_field):
        return False
    if first_version_only and version_field:
        try:
            version = int(float(_norm(fields.get(version_field)) or fields.get(version_field) or 1))
        except Exception:
            version = 1
        if version != 1:
            return False
    if operation_field and regeneration_values:
        if _norm(fields.get(operation_field)) in regeneration_values:
            return False
    return True


def ensure_table_auto_review_switch_records(token: str, *, write: bool = False) -> Dict[str, Any]:
    if not TABLE_CONFIG:
        return {"status": "missing_config_table"}
    existing = {}
    for rec in safe_list_records(token, TABLE_CONFIG):
        fields = rec.get("fields") or {}
        stage_name = _norm(fields.get("环节"))
        if stage_name in TABLE_AUTO_REVIEW_STAGE_NAMES.values():
            existing[stage_name] = {
                "record_id": rec.get("record_id") or rec.get("id"),
                "enabled": _norm(fields.get("状态")).lower() in ENABLED_VALUES,
            }
    missing = [stage_name for stage_name in TABLE_AUTO_REVIEW_STAGE_NAMES.values() if stage_name not in existing]
    if not missing:
        return {"status": "exists", "records": existing}
    created = []
    would_create = []
    for stage_name in missing:
        payload = {
            "fields": {
                "配置类型": "自动审核",
                "环节": stage_name,
                "状态": "停用",
                "备注": "表级自动审核通过开关；启用后仅自动放行本表新生成成功且有附件 token 的审核闸门。",
            }
        }
        if not write:
            would_create.append(payload["fields"])
            continue
        result = safe_request(
            "post",
            f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_CONFIG}/records",
            headers=feishu_headers(token),
            json=payload,
            timeout=30,
            max_attempts=3,
        )
        record = ((result.get("data") or {}).get("record") or {})
        created.append({"stage_name": stage_name, "record_id": record.get("record_id") or record.get("id")})
    if not write:
        return {"status": "missing", "existing": existing, "would_create": would_create}
    return {"status": "created", "existing": existing, "created": created}


def ensure_auto_review_switch_record(token: str, *, write: bool = False) -> Dict[str, Any]:
    return ensure_table_auto_review_switch_records(token, write=write)


def _record_id(record: Dict[str, Any]) -> str:
    return str(record.get("record_id") or record.get("id") or "").strip()


def _delete_config_record(token: str, record_id: str) -> None:
    safe_request(
        "delete",
        f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_CONFIG}/records/{record_id}",
        headers=feishu_headers(token),
        timeout=30,
        max_attempts=3,
    )


def sync_table_auto_review_switch_records(token: str, *, write: bool = False) -> Dict[str, Any]:
    if not TABLE_CONFIG:
        return {"status": "missing_config_table"}
    records = safe_list_records(token, TABLE_CONFIG)
    table_stage_names = set(TABLE_AUTO_REVIEW_STAGE_NAMES.values())
    keep_by_stage: Dict[str, Dict[str, Any]] = {}
    delete_ids = []

    for rec in records:
        fields = rec.get("fields") or {}
        stage_name = _norm(fields.get("环节"))
        record_id = _record_id(rec)
        if not record_id:
            continue
        if stage_name == LEGACY_GLOBAL_AUTO_REVIEW_STAGE_NAME:
            delete_ids.append(record_id)
            continue
        if stage_name not in table_stage_names:
            continue
        if stage_name not in keep_by_stage:
            keep_by_stage[stage_name] = rec
        else:
            delete_ids.append(record_id)

    missing = [stage_name for stage_name in TABLE_AUTO_REVIEW_STAGE_NAMES.values() if stage_name not in keep_by_stage]
    created = []
    if write:
        for record_id in delete_ids:
            _delete_config_record(token, record_id)
        for stage_name in missing:
            payload = {
                "fields": {
                    "配置类型": "自动审核",
                    "环节": stage_name,
                    "状态": "停用",
                    "备注": "表级自动审核通过开关；启用后仅自动放行本表新生成成功且有附件 token 的审核闸门。",
                }
            }
            result = safe_request(
                "post",
                f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_CONFIG}/records",
                headers=feishu_headers(token),
                json=payload,
                timeout=30,
                max_attempts=3,
            )
            record = ((result.get("data") or {}).get("record") or {})
            created.append({"stage_name": stage_name, "record_id": record.get("record_id") or record.get("id")})
    return {
        "status": "synced" if write else "dry_run",
        "kept": {
            stage_name: {
                "record_id": _record_id(rec),
                "enabled": _norm((rec.get("fields") or {}).get("状态")).lower() in ENABLED_VALUES,
            }
            for stage_name, rec in keep_by_stage.items()
        },
        "delete_record_ids": delete_ids,
        "missing_stage_names": missing,
        "created": created,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync table-level auto-review switch records")
    parser.add_argument("--ensure", action="store_true", help="create the switch record when missing")
    parser.add_argument("--sync", action="store_true", help="delete legacy/duplicate switches and create missing table switches")
    parser.add_argument("--write", action="store_true", help="apply changes; without this, show a dry-run plan")
    args = parser.parse_args()
    token = get_feishu_token()
    if args.sync:
        result = sync_table_auto_review_switch_records(token, write=args.write)
    else:
        result = ensure_auto_review_switch_record(token, write=args.ensure)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
