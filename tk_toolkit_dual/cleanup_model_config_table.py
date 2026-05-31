#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Dict, Iterable, List, Mapping, Sequence

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ai_model_catalog  # noqa: E402
from common import (  # noqa: E402
    APP_TOKEN,
    TABLE_CONFIG,
    extract_text,
    feishu_headers,
    get_feishu_token,
    safe_list_records,
    safe_request,
    safe_update_record,
)


BACKUP_PATH = Path("docs/tk-pipeline/model-config-cleanup-backup-2026-05-31.json")
CONFIG_PROMPT_STAGES = {
    "多图九宫格方案生成",
    "多图九宫格图片生成",
    "多图九宫格视频生成",
}
ROUTE_SWITCH_STAGE = "统一AI路由启用状态"
ARCHIVE_PREFIX = "归档："
SECRET_FIELD_NAMES = {"API Key"}


@dataclass(frozen=True)
class RecordUpdate:
    record_id: str
    category: str
    fields: Dict[str, Any]


@dataclass(frozen=True)
class CleanupPlan:
    summary: Dict[str, int]
    record_updates: List[RecordUpdate]


def _record_id(record: Mapping[str, Any]) -> str:
    return str(record.get("record_id") or record.get("id") or "")


def _fields(record: Mapping[str, Any]) -> Dict[str, Any]:
    fields = record.get("fields") if isinstance(record, Mapping) else {}
    return fields if isinstance(fields, dict) else {}


def _text(fields: Mapping[str, Any], name: str) -> str:
    return extract_text(fields.get(name)).strip()


def _has_api_key(fields: Mapping[str, Any]) -> bool:
    return bool(_text(fields, "API Key"))


def _same_patch(fields: Mapping[str, Any], patch: Mapping[str, Any]) -> bool:
    return all(_text(fields, key) == str(value) for key, value in patch.items())


def _archive_remark(existing: str, reason: str) -> str:
    archive = f"{ARCHIVE_PREFIX}{reason}"
    if ARCHIVE_PREFIX in existing:
        return existing
    return f"{archive}；{existing}" if existing else archive


def build_cleanup_plan(records: Sequence[Mapping[str, Any]]) -> CleanupPlan:
    production_models = {entry.display_name for entry in ai_model_catalog.production_models()}
    inspectable_models = {
        entry.display_name: entry.status
        for entry in ai_model_catalog.catalog_entries(ai_model_catalog.INSPECTABLE_STATUSES)
    }
    counts = {
        "production_config_count": 0,
        "route_switch_count": 0,
        "prompt_stage_config_count": 0,
        "current_catalog_preset_count": 0,
        "archived_preset_count": 0,
    }
    updates: List[RecordUpdate] = []

    for record in records:
        fields = _fields(record)
        rid = _record_id(record)
        stage = _text(fields, "环节")
        model = _text(fields, "模型名称")
        if not rid:
            continue

        patch: Dict[str, Any] = {}
        category = ""
        if _has_api_key(fields):
            counts["production_config_count"] += 1
            category = "production_config"
            patch = {"是否统一AI预设": "否"}
        elif stage == ROUTE_SWITCH_STAGE:
            counts["route_switch_count"] += 1
            category = "route_switch"
            patch = {"是否统一AI预设": "否"}
        elif stage in CONFIG_PROMPT_STAGES:
            counts["prompt_stage_config_count"] += 1
            category = "prompt_stage_config"
            patch = {"是否统一AI预设": "否"}
        elif stage.startswith("统一AI预设-") and model in production_models:
            counts["current_catalog_preset_count"] += 1
            category = "current_catalog_preset"
            patch = {"是否统一AI预设": "是", "状态": "启用"}
        elif stage.startswith("统一AI预设-"):
            counts["archived_preset_count"] += 1
            category = "archived_preset"
            catalog_status = inspectable_models.get(model)
            reason = (
                f"候选/非生产模型，catalog_status={catalog_status}"
                if catalog_status
                else "旧命名统一AI预设，已由供应商/模型显示名预设替代"
            )
            patch = {
                "是否统一AI预设": "否",
                "状态": "停用",
                "备注": _archive_remark(_text(fields, "备注"), reason),
            }

        if patch and not _same_patch(fields, patch):
            updates.append(RecordUpdate(record_id=rid, category=category, fields=patch))

    return CleanupPlan(summary=counts, record_updates=updates)


def _redact_field_item(field: Mapping[str, Any]) -> Dict[str, Any]:
    name = str(field.get("field_name") or field.get("name") or "")
    safe_name = "[REDACTED_SECRET_FIELD]" if name in SECRET_FIELD_NAMES else name
    return {
        "field_id": field.get("field_id") or field.get("id"),
        "field_name": safe_name,
        "type": field.get("type"),
    }


def build_backup_snapshot(
    *,
    fields: Sequence[Mapping[str, Any]],
    views: Sequence[Mapping[str, Any]],
    records: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    snapshot_records = []
    for record in records:
        rf = _fields(record)
        prompt = _text(rf, "提示词")
        snapshot_records.append({
            "record_id": _record_id(record),
            "环节": _text(rf, "环节"),
            "是否统一AI预设": _text(rf, "是否统一AI预设"),
            "应用表格_count": len(rf.get("应用表格") or []) if isinstance(rf.get("应用表格"), list) else (1 if rf.get("应用表格") else 0),
            "AI供应商": _text(rf, "AI供应商"),
            "AI能力类型": _text(rf, "AI能力类型"),
            "AI任务类型": _text(rf, "AI任务类型"),
            "模型名称": _text(rf, "模型名称"),
            "API 代理地址": _text(rf, "API 代理地址"),
            "AI参数JSON": _text(rf, "AI参数JSON"),
            "调用方式": _text(rf, "调用方式"),
            "提示词_chars": len(prompt),
            "has_api_key": _has_api_key(rf),
            "状态": _text(rf, "状态"),
            "备注": _text(rf, "备注"),
        })
    return {
        "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "base_id": APP_TOKEN,
        "table_id": TABLE_CONFIG,
        "fields": [_redact_field_item(item) for item in fields],
        "views": [
            {
                "view_id": item.get("view_id") or item.get("id"),
                "view_name": item.get("view_name") or item.get("name"),
                "view_type": item.get("view_type") or item.get("type"),
            }
            for item in views
        ],
        "records": snapshot_records,
    }


def build_view_definitions(field_names: Sequence[str]) -> Dict[str, Dict[str, Any]]:
    all_fields = list(field_names)
    return {
        "00-生产运行配置": {
            "visible_fields": ["环节", "状态", "模型名称", "API 代理地址", "应用表格", "备注"],
            "filter": {
                "logic": "or",
                "conditions": [["API Key", "non_empty"], ["环节", "intersects", [ROUTE_SWITCH_STAGE]]],
            },
        },
        "01-统一AI Catalog": {
            "visible_fields": ["环节", "AI供应商", "AI能力类型", "AI任务类型", "模型名称", "AI参数JSON", "调用方式", "状态", "备注"],
            "filter": {
                "logic": "and",
                "conditions": [["是否统一AI预设", "intersects", ["是"]], ["状态", "intersects", ["启用"]]],
            },
        },
        "02-链路提示词配置": {
            "visible_fields": ["环节", "状态", "AI供应商", "AI能力类型", "AI任务类型", "模型名称", "API 代理地址", "AI参数JSON", "调用方式", "提示词", "备注"],
            "filter": {"logic": "and", "conditions": [["环节", "intersects", sorted(CONFIG_PROMPT_STAGES)]]},
        },
        "90-归档-旧预设": {
            "visible_fields": ["环节", "是否统一AI预设", "AI供应商", "AI能力类型", "AI任务类型", "模型名称", "状态", "备注"],
            "filter": {"logic": "and", "conditions": [["状态", "intersects", ["停用"]]]},
        },
        "99-全字段排错": {
            "visible_fields": all_fields,
            "filter": {"conditions": []},
        },
    }


def redacted_json(data: Any) -> str:
    return json.dumps(redact_public_output(data), ensure_ascii=False, indent=2, sort_keys=True)


def redact_public_output(data: Any) -> Any:
    if isinstance(data, dict):
        redacted = {}
        for key, value in data.items():
            safe_key = "base_id" if key == "base_token" else key
            redacted[safe_key] = redact_public_output(value)
        return redacted
    if isinstance(data, list):
        return [redact_public_output(item) for item in data]
    if isinstance(data, str):
        if data in SECRET_FIELD_NAMES:
            return "[REDACTED_SECRET_FIELD]"
        return data.replace("API Key", "[REDACTED_SECRET_FIELD]")
    return data


def list_fields(token: str) -> List[Dict[str, Any]]:
    data = safe_request(
        "get",
        f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_CONFIG}/fields?page_size=200",
        headers=feishu_headers(token),
        timeout=30,
        max_attempts=3,
        acceptable_codes=(0,),
    )
    return (data.get("data") or {}).get("items") or []


def list_views(token: str) -> List[Dict[str, Any]]:
    data = safe_request(
        "get",
        f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_CONFIG}/views?page_size=200",
        headers=feishu_headers(token),
        timeout=30,
        max_attempts=3,
        acceptable_codes=(0,),
    )
    return (data.get("data") or {}).get("items") or []


def run_json(argv: Sequence[str]) -> Dict[str, Any]:
    proc = subprocess.run(list(argv), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output = (proc.stdout or proc.stderr or "").strip()
    if proc.returncode != 0:
        raise RuntimeError(f"command failed rc={proc.returncode}: {' '.join(argv)}\n{output}")
    if not output:
        return {}
    return json.loads(output)


def existing_view_map(views: Sequence[Mapping[str, Any]]) -> Dict[str, str]:
    mapping = {}
    for item in views:
        name = item.get("view_name") or item.get("name")
        view_id = item.get("view_id") or item.get("id")
        if name and view_id:
            mapping[str(name)] = str(view_id)
    return mapping


def ensure_view(base_token: str, view_name: str, view_id_by_name: Dict[str, str]) -> str:
    existing = view_id_by_name.get(view_name)
    if existing:
        return existing
    data = run_json([
        "lark-cli", "base", "+view-create",
        "--base-token", base_token,
        "--table-id", TABLE_CONFIG,
        "--json", json.dumps({"name": view_name, "type": "grid"}, ensure_ascii=False),
    ])
    view = (data.get("data") or {}).get("view") or {}
    view_id = view.get("id") or view.get("view_id")
    if not view_id:
        refreshed = existing_view_map(list_views(get_feishu_token()))
        view_id = refreshed.get(view_name)
    if not view_id:
        raise RuntimeError(f"创建视图后未返回 view_id: {view_name}")
    view_id_by_name[view_name] = view_id
    return str(view_id)


def apply_view_definitions(base_token: str, views: Mapping[str, Mapping[str, Any]], *, dry_run: bool) -> List[Dict[str, Any]]:
    existing = existing_view_map(list_views(get_feishu_token())) if not dry_run else {}
    results = []
    for view_name, definition in views.items():
        view_id = existing.get(view_name, f"dry-run:{view_name}")
        if not dry_run:
            view_id = ensure_view(base_token, view_name, existing)
            for command, payload in [
                ("+view-set-visible-fields", {"visible_fields": definition["visible_fields"]}),
                ("+view-set-filter", definition.get("filter") or {"conditions": []}),
            ]:
                for attempt in range(4):
                    try:
                        run_json([
                            "lark-cli", "base", command,
                            "--base-token", base_token,
                            "--table-id", TABLE_CONFIG,
                            "--view-id", view_id,
                            "--json", json.dumps(payload, ensure_ascii=False),
                        ])
                        break
                    except RuntimeError as exc:
                        text = str(exc)
                        if "800070003" in text or "no operation produced" in text:
                            break
                        if "800004135" not in text or attempt == 3:
                            raise
                        time.sleep(2 + attempt * 2)
        results.append({
            "view_name": view_name,
            "view_id": view_id,
            "visible_fields": definition["visible_fields"],
            "filter": definition.get("filter") or {"conditions": []},
            "status": "dry_run" if dry_run else "updated",
        })
    return results


def write_backup(path: Path, snapshot: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(redacted_json(snapshot) + "\n", encoding="utf-8")


def apply_record_updates(token: str, updates: Sequence[RecordUpdate], *, dry_run: bool) -> List[Dict[str, Any]]:
    results = []
    for update in updates:
        if not dry_run:
            safe_update_record(token, TABLE_CONFIG, update.record_id, update.fields)
        results.append({
            "record_id": update.record_id,
            "category": update.category,
            "fields": update.fields,
            "status": "dry_run" if dry_run else "updated",
        })
    return results


def run_cleanup(*, write: bool, backup_path: Path) -> Dict[str, Any]:
    token = get_feishu_token()
    fields = list_fields(token)
    views = list_views(token)
    records = safe_list_records(token, TABLE_CONFIG)
    field_names = [item.get("field_name") or item.get("name") for item in fields if item.get("field_name") or item.get("name")]
    plan = build_cleanup_plan(records)
    view_definitions = build_view_definitions(field_names)
    backup = build_backup_snapshot(fields=fields, views=views, records=records)
    write_backup(backup_path, backup)
    record_results = apply_record_updates(token, plan.record_updates, dry_run=not write)
    view_results = apply_view_definitions(APP_TOKEN, view_definitions, dry_run=not write)
    return {
        "mode": "write" if write else "dry_run",
        "backup_path": str(backup_path),
        "summary": plan.summary,
        "record_updates": record_results,
        "views": view_results,
        "business_tables_touched": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="整理初始化-模型与API配置表：视图 + 归档")
    parser.add_argument("--write", action="store_true", help="实际写入飞书；默认只 dry-run")
    parser.add_argument("--backup-path", default=str(BACKUP_PATH))
    args = parser.parse_args()
    result = run_cleanup(write=args.write, backup_path=Path(args.backup_path))
    print(redacted_json(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
