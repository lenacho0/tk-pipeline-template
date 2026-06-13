#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from view_visibility import SNAPSHOT_PATH, build_visibility_snapshot, load_visibility_snapshot


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATHS = [SCRIPT_DIR / "config.json", SCRIPT_DIR / "config.ryan.json"]
SYNC_TABLE_KEYS = [
    "config",
    "multi_role_first_last",
    "first_last_video",
    "script_doc_tasks",
    "script_doc_reference_assets",
    "script_doc_shots",
    "script_doc_unified",
    "storyboard_video",
    "nine_grid_video",
    "prompt_image_video",
    "video_edit",
    "voice_library",
    "text_audio",
    "product",
    "model_appearance",
]


def load_config(config_path: Optional[Path] = None) -> Dict[str, Any]:
    paths = [Path(config_path)] if config_path else DEFAULT_CONFIG_PATHS
    for path in paths:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    raise FileNotFoundError("找不到 config.json/config.ryan.json")


def run_json(args: list[str]) -> Dict[str, Any]:
    proc = subprocess.run(args, cwd=str(SCRIPT_DIR.parent), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
    return json.loads(proc.stdout or "{}")


def list_views(base_token: str, table_id: str) -> list[Dict[str, Any]]:
    data = run_json([
        "lark-cli", "base", "+view-list",
        "--as", "user",
        "--base-token", base_token,
        "--table-id", table_id,
        "--limit", "200",
        "--format", "json",
    ])
    raw = data.get("data") or {}
    views = raw.get("views") or raw.get("items") or []
    return views if isinstance(views, list) else []


def get_visible_fields(base_token: str, table_id: str, view_id: str) -> list[str]:
    data = run_json([
        "lark-cli", "base", "+view-get-visible-fields",
        "--as", "user",
        "--base-token", base_token,
        "--table-id", table_id,
        "--view-id", view_id,
        "--format", "json",
    ])
    raw = data.get("data") or {}
    fields = raw.get("visible_fields") or []
    return [str(field) for field in fields]


def _visible_fields_from_definition(definition: Any) -> Optional[list[str]]:
    if isinstance(definition, Mapping):
        fields = definition.get("visible_fields")
    else:
        fields = definition
    if isinstance(fields, list):
        return [str(field) for field in fields]
    return None


def load_local_view_specs() -> Dict[str, Dict[str, list[str]]]:
    specs: Dict[str, Dict[str, list[str]]] = {}

    def add(table_key: str, views: Mapping[str, Any]) -> None:
        specs[table_key] = {}
        for name, definition in views.items():
            fields = _visible_fields_from_definition(definition)
            if fields is not None:
                specs[table_key][str(name)] = fields

    try:
        module = importlib.import_module("tk_create_multi_role_first_last_table")
        add("multi_role_first_last", module.TABLE_DEFINITION["views"])
    except Exception:
        pass
    try:
        module = importlib.import_module("tk_create_first_last_video_table")
        add("first_last_video", module.TABLE_DEFINITION["views"])
    except Exception:
        pass
    try:
        module = importlib.import_module("tk_create_script_doc_shots_table")
        for item in module.TABLE_DEFINITIONS:
            add(item["key"], item["views"])
        add("script_doc_unified", module.UNIFIED_TABLE_DEFINITION["views"])
    except Exception:
        pass
    try:
        module = importlib.import_module("tk_create_storyboard_video_table")
        add("storyboard_video", module.TABLE_DEFINITION["views"])
    except Exception:
        pass
    try:
        module = importlib.import_module("tk_create_nine_grid_video_table")
        add("nine_grid_video", module.TABLE_DEFINITION["views"])
    except Exception:
        pass
    try:
        module = importlib.import_module("tk_create_prompt_image_video_table")
        add("prompt_image_video", module.TABLE_DEFINITION["views"])
    except Exception:
        pass
    try:
        module = importlib.import_module("tk_create_video_edit_table")
        add("video_edit", module.TABLE_DEFINITION["views"])
    except Exception:
        pass
    try:
        module = importlib.import_module("cleanup_model_config_table")
        field_names = [field["name"] for field in module.CONFIG_FIELD_SPECS]
        add("config", module.build_view_definitions(field_names))
    except Exception:
        pass
    return specs


def diff_view_fields(live: list[str], expected: Optional[list[str]]) -> Dict[str, Any]:
    if expected is None:
        return {"not_in_local_spec": True}
    extra_live = [field for field in live if field not in expected]
    missing_live = [field for field in expected if field not in live]
    return {
        "extra_live": extra_live,
        "missing_live": missing_live,
        "order_changed": not extra_live and not missing_live and live != expected,
    }


def collect_table_visibility(base_token: str, table_key: str, table_id: str) -> Dict[str, Any]:
    views: Dict[str, Any] = {}
    for view in list_views(base_token, table_id):
        view_name = str(view.get("name") or view.get("view_name") or "")
        view_id = str(view.get("id") or view.get("view_id") or "")
        if not view_name or not view_id:
            continue
        views[view_name] = {
            "view_id": view_id,
            "visible_fields": get_visible_fields(base_token, table_id, view_id),
        }
    return {
        "table_key": table_key,
        "table_id": table_id,
        "views": views,
    }


def summarize(snapshot: Mapping[str, Any], *, previous: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    local_specs = load_local_view_specs()
    tables = snapshot.get("tables") or {}
    previous_tables = (previous or {}).get("tables") or {}
    summary = []
    for table_key, table in tables.items():
        views = table.get("views") or {}
        local = local_specs.get(str(table_key), {})
        local_diff_count = 0
        changed_from_snapshot = 0
        sample_diffs = []
        previous_views = (previous_tables.get(table_key) or {}).get("views") or {}
        for view_name, view in views.items():
            live_fields = view.get("visible_fields") or []
            diff = diff_view_fields(live_fields, local.get(view_name))
            differs = diff.get("not_in_local_spec") or diff.get("extra_live") or diff.get("missing_live") or diff.get("order_changed")
            if differs:
                local_diff_count += 1
                if len(sample_diffs) < 5:
                    sample_diffs.append({
                        "view_name": view_name,
                        "live_count": len(live_fields),
                        "local_count": None if diff.get("not_in_local_spec") else len(local.get(view_name) or []),
                        **diff,
                    })
            previous_fields = (previous_views.get(view_name) or {}).get("visible_fields")
            if previous_fields is not None and previous_fields != live_fields:
                changed_from_snapshot += 1
            elif previous_fields is None and previous:
                changed_from_snapshot += 1
        summary.append({
            "table_key": table_key,
            "table_id": table.get("table_id"),
            "view_count": len(views),
            "diff_count_vs_local_spec": local_diff_count,
            "changed_view_count_vs_existing_snapshot": changed_from_snapshot,
            "sample_diffs": sample_diffs,
        })
    return {
        "table_count": len(tables),
        "view_count": sum(len((table.get("views") or {})) for table in tables.values()),
        "tables": summary,
    }


def collect_snapshot(config: Mapping[str, Any]) -> Dict[str, Any]:
    feishu = config.get("feishu") or {}
    base_token = feishu["bitable_app_token"]
    configured_tables = feishu.get("tables") or {}
    table_entries = []
    for table_key in SYNC_TABLE_KEYS:
        table_id = configured_tables.get(table_key)
        if not table_id:
            continue
        table_entries.append(collect_table_visibility(base_token, table_key, table_id))
    return build_visibility_snapshot(base_token=base_token, table_entries=table_entries)


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync current ryan Base view visible fields into a local snapshot")
    parser.add_argument("--config", type=Path, help="config.json path")
    parser.add_argument("--output", type=Path, default=SNAPSHOT_PATH, help="snapshot output path")
    parser.add_argument("--write", action="store_true", help="write snapshot file; default only prints summary")
    args = parser.parse_args()

    config = load_config(args.config)
    snapshot = collect_snapshot(config)
    previous = load_visibility_snapshot(args.output) if args.output.exists() else None
    result = {
        "write": bool(args.write),
        "output": str(args.output),
        "summary": summarize(snapshot, previous=previous),
    }
    if args.write:
        args.output.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

