#!/usr/bin/env python3
"""Unify Feishu video model fields to 视频生成模型.

The script is dry-run by default. With --write it backs up old field definitions
and record values, creates/syncs 视频生成模型 options, copies old values when the
new field is empty, updates views, then deletes legacy fields.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
import time
from typing import Any, Dict, Iterable, List, Sequence

import ai_routing
import sync_ai_model_catalog_to_feishu as sync_catalog
import tk_create_first_last_video_table as first_last_table
import tk_create_multi_role_first_last_table as multi_role_table
import tk_create_nine_grid_video_table as nine_grid_table
import tk_create_prompt_image_video_table as prompt_image_video_table
import tk_create_script_doc_shots_table as script_doc_tables
import tk_create_storyboard_video_table as storyboard_table


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = SCRIPT_DIR / "config.json"
BACKUP_DIR = Path("docs/tk-pipeline")
LEGACY_VIDEO_MODEL_FIELD = "视频AI模型"
UNIFIED_VIDEO_MODEL_FIELD = "视频生成模型"
GLOBAL_LEGACY_FIELDS = ["AI供应商", "AI能力类型", "AI任务类型", "AI模型", "AI参数JSON"]


TABLE_SPECS = [
    {
        "key": "multi_role_first_last",
        "label": "001-多角色开头钩子",
        "delete_fields": [LEGACY_VIDEO_MODEL_FIELD, *GLOBAL_LEGACY_FIELDS],
    },
    {
        "key": "first_last_video",
        "label": "002-产品使用场景",
        "delete_fields": [LEGACY_VIDEO_MODEL_FIELD, *GLOBAL_LEGACY_FIELDS],
    },
    {
        "key": "script_doc_unified",
        "label": "003-爆款视频复刻",
        "delete_fields": [LEGACY_VIDEO_MODEL_FIELD, *GLOBAL_LEGACY_FIELDS],
    },
    {
        "key": "script_doc_tasks",
        "label": "003-旧任务表",
        "delete_fields": [LEGACY_VIDEO_MODEL_FIELD, *GLOBAL_LEGACY_FIELDS],
    },
    {
        "key": "script_doc_shots",
        "label": "003-旧分镜生产表",
        "delete_fields": [LEGACY_VIDEO_MODEL_FIELD, *GLOBAL_LEGACY_FIELDS],
    },
    {
        "key": "storyboard_video",
        "label": "004-故事板",
        "delete_fields": [LEGACY_VIDEO_MODEL_FIELD],
    },
    {
        "key": "nine_grid_video",
        "label": "005-多图N宫格",
        "delete_fields": ["视频AI供应商", LEGACY_VIDEO_MODEL_FIELD],
    },
    {
        "key": "prompt_image_video",
        "label": "008-产品展示CTA",
        "delete_fields": [LEGACY_VIDEO_MODEL_FIELD],
    },
]


KEY_FIELDS = [
    "任务名称",
    "记录类型",
    "父任务记录ID",
    "批次ID",
    "Board编号",
    "Storyboard编号",
    "分镜序号",
]


def now_stamp() -> str:
    return dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def text(value: Any) -> str:
    return ai_routing._norm(value)


def redacted(data: Any) -> str:
    return json.dumps(ai_routing.redact_secret(data), ensure_ascii=False, indent=2, sort_keys=True)


def table_id(config: Dict[str, Any], table_key: str) -> str:
    return str((((config.get("feishu") or {}).get("tables") or {}).get(table_key)) or "")


def field_map(token: str, app_token: str, tid: str) -> Dict[str, Dict[str, Any]]:
    return {
        sync_catalog.field_name(item): item
        for item in sync_catalog.list_api_fields(token, app_token, tid)
        if sync_catalog.field_name(item)
    }


def list_records(token: str, app_token: str, tid: str) -> List[Dict[str, Any]]:
    return sync_catalog.list_records(token, app_token, tid)


def update_record(token: str, app_token: str, tid: str, record_id: str, fields: Dict[str, Any]) -> None:
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{tid}/records/{record_id}"
    sync_catalog.request_json("put", url, token, json={"fields": fields})


def delete_field(token: str, app_token: str, tid: str, item: Dict[str, Any]) -> None:
    fid = sync_catalog.field_id(item)
    if not fid:
        raise RuntimeError(f"字段缺少 field_id: {sync_catalog.field_name(item)}")
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{tid}/fields/{fid}"
    sync_catalog.request_json("delete", url, token)


def relevant_option_updates(config: Dict[str, Any]) -> List[sync_catalog.FieldOptionUpdate]:
    return [
        update for update in sync_catalog.build_field_option_updates(config)
        if update.field_name == UNIFIED_VIDEO_MODEL_FIELD
    ]


def select_field_payload(name: str, options: Sequence[Dict[str, str]]) -> Dict[str, Any]:
    return {"name": name, "type": "select", "multiple": False, "options": list(options)}


def apply_video_field_option_updates(
    token: str,
    app_token: str,
    base_token: str,
    updates: Sequence[sync_catalog.FieldOptionUpdate],
    *,
    dry_run: bool,
) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for update in updates:
        fields_by_name = field_map(token, app_token, update.table_id)
        payload = select_field_payload(update.field_name, update.options)
        if update.field_name in fields_by_name:
            status = "dry_run_update" if dry_run else "updated"
            if not dry_run:
                sync_catalog.run_json([
                    "lark-cli", "base", "+field-update",
                    "--base-token", base_token,
                    "--table-id", update.table_id,
                    "--field-id", update.field_name,
                    "--json", json.dumps(payload, ensure_ascii=False),
                    "--yes",
                ])
        else:
            status = "dry_run_create" if dry_run else "created"
            if not dry_run:
                sync_catalog.run_json([
                    "lark-cli", "base", "+field-create",
                    "--base-token", base_token,
                    "--table-id", update.table_id,
                    "--json", json.dumps(payload, ensure_ascii=False),
                ])
        results.append({
            "table_key": update.table_key,
            "table_id": update.table_id,
            "field_name": update.field_name,
            "option_count": len(update.options),
            "status": status,
        })
    return results


def backup_payload(
    token: str,
    app_token: str,
    base_token: str,
    config: Dict[str, Any],
) -> Dict[str, Any]:
    tables: List[Dict[str, Any]] = []
    for spec in TABLE_SPECS:
        tid = table_id(config, spec["key"])
        if not tid:
            continue
        fields_by_name = field_map(token, app_token, tid)
        wanted = [name for name in spec["delete_fields"] if name in fields_by_name]
        records = list_records(token, app_token, tid)
        record_values = []
        for record in records:
            rf = record.get("fields") or {}
            values = {name: rf.get(name) for name in wanted if text(rf.get(name))}
            if not values:
                continue
            keys = {name: rf.get(name) for name in KEY_FIELDS if text(rf.get(name))}
            record_values.append({
                "record_id": record.get("record_id"),
                "keys": keys,
                "values": values,
            })
        tables.append({
            "table_key": spec["key"],
            "label": spec["label"],
            "table_id": tid,
            "delete_fields": wanted,
            "field_definitions": [fields_by_name[name] for name in wanted],
            "record_values": record_values,
        })
    return {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "note": "Only legacy video/global routing fields are backed up. API Key fields are not included.",
        "tables": tables,
    }


def migrate_record_values(
    token: str,
    app_token: str,
    base_token: str,
    config: Dict[str, Any],
    *,
    dry_run: bool,
) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for spec in TABLE_SPECS:
        tid = table_id(config, spec["key"])
        if not tid:
            continue
        fields_by_name = field_map(token, app_token, tid)
        if UNIFIED_VIDEO_MODEL_FIELD not in fields_by_name:
            results.append({"table_key": spec["key"], "status": "missing_unified_field"})
            continue
        has_old_model = LEGACY_VIDEO_MODEL_FIELD in fields_by_name
        records = list_records(token, app_token, tid)
        copied = 0
        old_non_empty = 0
        new_empty_with_old = 0
        for record in records:
            rf = record.get("fields") or {}
            old_value = text(rf.get(LEGACY_VIDEO_MODEL_FIELD)) if has_old_model else ""
            new_value = text(rf.get(UNIFIED_VIDEO_MODEL_FIELD))
            if old_value:
                old_non_empty += 1
            if old_value and not new_value:
                new_empty_with_old += 1
                if not dry_run:
                    update_record(token, app_token, tid, str(record["record_id"]), {UNIFIED_VIDEO_MODEL_FIELD: old_value})
                    time.sleep(0.05)
                copied += 1
        results.append({
            "table_key": spec["key"],
            "table_id": tid,
            "old_model_non_empty": old_non_empty,
            "new_empty_with_old": new_empty_with_old,
            "copied": copied if not dry_run else f"would_copy_{copied}",
        })
    return results


def update_views(base_token: str, config: Dict[str, Any], *, dry_run: bool) -> List[Dict[str, Any]]:
    targets = [
        ("multi_role_first_last", multi_role_table.TABLE_DEFINITION["views"], script_doc_tables.create_or_update_views),
        ("first_last_video", first_last_table.TABLE_DEFINITION["views"], script_doc_tables.create_or_update_views),
        ("script_doc_unified", script_doc_tables.UNIFIED_TABLE_DEFINITION["views"], script_doc_tables.create_or_update_views),
        (
            "script_doc_tasks",
            next(item for item in script_doc_tables.TABLE_DEFINITIONS if item["key"] == "script_doc_tasks")["views"],
            script_doc_tables.create_or_update_views,
        ),
        (
            "script_doc_shots",
            next(item for item in script_doc_tables.TABLE_DEFINITIONS if item["key"] == "script_doc_shots")["views"],
            script_doc_tables.create_or_update_views,
        ),
        ("storyboard_video", storyboard_table.TABLE_DEFINITION["views"], script_doc_tables.create_or_update_views),
        ("nine_grid_video", nine_grid_table.TABLE_DEFINITION["views"], script_doc_tables.create_or_update_views),
        ("prompt_image_video", prompt_image_video_table.TABLE_DEFINITION["views"], script_doc_tables.create_or_update_views),
    ]
    results: List[Dict[str, Any]] = []
    for key, views, updater in targets:
        tid = table_id(config, key)
        if not tid:
            continue
        if dry_run:
            results.append({"table_key": key, "table_id": tid, "status": "would_update_views", "view_count": len(views)})
        else:
            results.append({"table_key": key, "table_id": tid, "views": updater(base_token, tid, views)})
    if not dry_run:
        storyboard_tid = table_id(config, "storyboard_video")
        if storyboard_tid:
            results.append({
                "table_key": "storyboard_video",
                "filters_updated": storyboard_table.apply_view_filters(base_token, storyboard_tid),
            })
        multi_tid = table_id(config, "multi_role_first_last")
        if multi_tid:
            results.append({
                "table_key": "multi_role_first_last",
                "filters_updated": multi_role_table.apply_view_filters(base_token, multi_tid),
            })
        nine_tid = table_id(config, "nine_grid_video")
        if nine_tid:
            results.append({
                "table_key": "nine_grid_video",
                "filters_updated": nine_grid_table.apply_nine_grid_view_filters(base_token, nine_tid),
            })
    return results


def delete_legacy_fields(
    token: str,
    app_token: str,
    base_token: str,
    config: Dict[str, Any],
    *,
    dry_run: bool,
) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for spec in TABLE_SPECS:
        tid = table_id(config, spec["key"])
        if not tid:
            continue
        fields_by_name = field_map(token, app_token, tid)
        deleted = []
        missing = []
        for name in spec["delete_fields"]:
            item = fields_by_name.get(name)
            if not item:
                missing.append(name)
                continue
            if not dry_run:
                delete_field(token, app_token, tid, item)
                time.sleep(0.2)
            deleted.append(name)
        results.append({
            "table_key": spec["key"],
            "table_id": tid,
            "deleted": deleted if not dry_run else [f"would_delete:{name}" for name in deleted],
            "already_missing": missing,
        })
    return results


def verify_fields(token: str, app_token: str, config: Dict[str, Any]) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for spec in TABLE_SPECS:
        tid = table_id(config, spec["key"])
        if not tid:
            continue
        fields_by_name = field_map(token, app_token, tid)
        results.append({
            "table_key": spec["key"],
            "table_id": tid,
            "has_unified_field": UNIFIED_VIDEO_MODEL_FIELD in fields_by_name,
            "legacy_fields_remaining": [name for name in spec["delete_fields"] if name in fields_by_name],
        })
    return results


def write_backup(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(redacted(payload) + "\n", encoding="utf-8")


def assert_no_unmigrated_values(migration_results: Sequence[Dict[str, Any]]) -> None:
    blockers = [
        item for item in migration_results
        if isinstance(item.get("new_empty_with_old"), int) and item.get("new_empty_with_old", 0)
    ]
    if blockers:
        raise RuntimeError(f"迁移后仍有旧模型值未复制: {blockers}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate video model field to 视频生成模型 and delete legacy fields")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--write", action="store_true", help="Apply migration and delete fields")
    parser.add_argument("--backup-output", default=str(BACKUP_DIR / f"video-model-field-unification-backup-{now_stamp()}.json"))
    parser.add_argument("--skip-delete", action="store_true", help="Do not delete legacy fields after migration")
    parser.add_argument("--skip-view-update", action="store_true")
    args = parser.parse_args()

    config = sync_catalog.load_config(Path(args.config))
    app_token = config["feishu"]["bitable_app_token"]
    base_token = app_token
    token = sync_catalog.get_feishu_token(config)
    dry_run = not args.write

    backup = backup_payload(token, app_token, base_token, config)
    backup_path = Path(args.backup_output)
    if args.write:
        write_backup(backup_path, backup)

    option_updates = relevant_option_updates(config)
    field_options = apply_video_field_option_updates(token, app_token, base_token, option_updates, dry_run=dry_run)
    migration = migrate_record_values(token, app_token, base_token, config, dry_run=dry_run)
    if args.write:
        post_migration = migrate_record_values(token, app_token, base_token, config, dry_run=True)
        assert_no_unmigrated_values(post_migration)
    else:
        post_migration = []
    views = [] if args.skip_view_update else update_views(base_token, config, dry_run=dry_run)
    deleted = [] if args.skip_delete else delete_legacy_fields(token, app_token, base_token, config, dry_run=dry_run)
    verification = verify_fields(token, app_token, config)

    output = {
        "mode": "write" if args.write else "dry_run",
        "backup_output": str(backup_path) if args.write else "",
        "backup_summary": [
            {
                "table_key": item["table_key"],
                "delete_fields": item["delete_fields"],
                "record_value_count": len(item["record_values"]),
            }
            for item in backup.get("tables", [])
        ],
        "field_options": field_options,
        "migration": migration,
        "post_migration_check": post_migration,
        "views": views,
        "delete": deleted,
        "verification": verification,
    }
    print(redacted(output))


if __name__ == "__main__":
    main()
