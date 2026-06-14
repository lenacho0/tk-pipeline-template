#!/usr/bin/env python3
"""Audit and optionally repair media version fields.

Default mode is dry-run. Use --write to update only version fields.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, Iterable, List, Mapping, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (  # noqa: E402
    TABLE_FIRST_LAST_VIDEO,
    TABLE_MULTI_ROLE_FIRST_LAST,
    TABLE_PROMPT_IMAGE_VIDEO,
    TABLE_STORYBOARD_VIDEO,
    extract_text,
    get_feishu_token,
    safe_list_records,
    safe_update_record,
)


MULTI_ROLE_TABLE_LABEL = "001-多角色首尾帧生成表"
FIRST_LAST_TABLE_LABEL = "002-首尾帧视频生成表"
STORYBOARD_TABLE_LABEL = "004-故事板视频生成表"
PROMPT_IMAGE_TABLE_LABEL = "008-图生视频生成表"


def version_int(value: Any) -> int:
    try:
        return max(1, int(float(extract_text(value).strip() or value or 1)))
    except Exception:
        return 1


def parse_history(fields: Mapping[str, Any]) -> List[Dict[str, Any]]:
    raw = extract_text(fields.get("历史生成记录JSON")).strip()
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, dict)]


def history_max_version(fields: Mapping[str, Any], stage: str) -> int:
    max_version = 0
    for item in parse_history(fields):
        if extract_text(item.get("stage")).strip() != stage:
            continue
        raw_version = item.get("version")
        if raw_version is None:
            continue
        max_version = max(max_version, version_int(raw_version))
    return max_version


def _update_entry(table: str, record_id: str, fields: Dict[str, int], reason: str) -> Dict[str, Any]:
    return {
        "table": table,
        "record_id": record_id,
        "fields": fields,
        "reason": reason,
    }


def audit_prompt_like_records(records: Iterable[Dict[str, Any]], *, table_label: str) -> List[Dict[str, Any]]:
    updates: List[Dict[str, Any]] = []
    for rec in records:
        fields = rec.get("fields") or {}
        patch: Dict[str, int] = {}
        image_history_version = history_max_version(fields, "image")
        if image_history_version > version_int(fields.get("图片版本")):
            patch["图片版本"] = image_history_version
        video_history_version = history_max_version(fields, "video")
        if video_history_version > version_int(fields.get("视频版本")):
            patch["视频版本"] = video_history_version
        if patch:
            updates.append(_update_entry(table_label, rec["record_id"], patch, "history"))
    return updates


def _multi_role_key(fields: Mapping[str, Any]) -> Tuple[str, str, str, str, str]:
    kind = extract_text(fields.get("记录类型")).strip()
    parent_id = extract_text(fields.get("父任务记录ID")).strip()
    if kind == "参考资产":
        return kind, parent_id, extract_text(fields.get("资产ID")).strip(), "参考图版本", "reference_image"
    if kind == "关键帧":
        return kind, parent_id, extract_text(fields.get("关键帧类型")).strip(), "关键帧版本", "keyframe_image"
    if kind == "视频片段":
        return kind, parent_id, extract_text(fields.get("视频片段类型")).strip(), "视频版本", "video"
    return "", "", "", "", ""


def audit_multi_role_records(records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    records = list(records)
    deprecated_versions: Dict[Tuple[str, str, str], int] = {}
    for rec in records:
        fields = rec.get("fields") or {}
        kind, parent_id, key, version_field, _stage = _multi_role_key(fields)
        if not kind or not parent_id or not key:
            continue
        if extract_text(fields.get("记录状态")).strip() != "已废弃":
            continue
        group_key = (kind, parent_id, key)
        deprecated_versions[group_key] = max(
            deprecated_versions.get(group_key, 0),
            version_int(fields.get(version_field)),
        )

    updates: List[Dict[str, Any]] = []
    for rec in records:
        fields = rec.get("fields") or {}
        kind, parent_id, key, version_field, stage = _multi_role_key(fields)
        if not kind or not parent_id or not key:
            continue
        current = version_int(fields.get(version_field))
        target = max(current, history_max_version(fields, stage))
        reason = "history" if target > current else ""
        if extract_text(fields.get("记录状态")).strip() != "已废弃":
            deprecated_target = deprecated_versions.get((kind, parent_id, key), 0) + 1
            if deprecated_target > target:
                target = deprecated_target
                reason = "deprecated_sibling"
        if target > current:
            updates.append(_update_entry(MULTI_ROLE_TABLE_LABEL, rec["record_id"], {version_field: target}, reason))
    return updates


def _first_last_key(fields: Mapping[str, Any]) -> Tuple[str, int]:
    if extract_text(fields.get("记录类型")).strip() != "场景子任务":
        return "", 0
    parent_id = extract_text(fields.get("父任务记录ID")).strip()
    if not parent_id:
        return "", 0
    raw_scene_no = extract_text(fields.get("场景编号")).strip() or fields.get("场景编号")
    try:
        scene_no = int(float(raw_scene_no))
    except Exception:
        scene_no = 0
    return parent_id, scene_no


def audit_first_last_records(records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    records = list(records)
    version_fields = ("首帧图版本", "尾帧图版本", "视频版本")
    deprecated_versions: Dict[Tuple[str, int], Dict[str, int]] = {}
    for rec in records:
        fields = rec.get("fields") or {}
        parent_id, scene_no = _first_last_key(fields)
        if not parent_id or scene_no <= 0:
            continue
        if extract_text(fields.get("记录状态")).strip() != "已废弃":
            continue
        group_versions = deprecated_versions.setdefault((parent_id, scene_no), {})
        for version_field in version_fields:
            group_versions[version_field] = max(
                group_versions.get(version_field, 0),
                version_int(fields.get(version_field)),
            )

    updates: List[Dict[str, Any]] = []
    for rec in records:
        fields = rec.get("fields") or {}
        parent_id, scene_no = _first_last_key(fields)
        if not parent_id or scene_no <= 0:
            continue
        if extract_text(fields.get("记录状态")).strip() == "已废弃":
            continue
        deprecated_target = deprecated_versions.get((parent_id, scene_no), {})
        patch: Dict[str, int] = {}
        for version_field in version_fields:
            target = deprecated_target.get(version_field, 0) + 1
            if target > version_int(fields.get(version_field)):
                patch[version_field] = target
        if patch:
            updates.append(_update_entry(FIRST_LAST_TABLE_LABEL, rec["record_id"], patch, "deprecated_sibling"))
    return updates


def collect_updates(token: str, table: str = "all") -> List[Dict[str, Any]]:
    updates: List[Dict[str, Any]] = []
    if table in {"all", "multi_role"}:
        updates.extend(audit_multi_role_records(safe_list_records(token, TABLE_MULTI_ROLE_FIRST_LAST)))
    if table in {"all", "first_last"}:
        updates.extend(audit_first_last_records(safe_list_records(token, TABLE_FIRST_LAST_VIDEO)))
    if table in {"all", "storyboard"}:
        updates.extend(audit_prompt_like_records(safe_list_records(token, TABLE_STORYBOARD_VIDEO), table_label=STORYBOARD_TABLE_LABEL))
    if table in {"all", "prompt_image"}:
        updates.extend(audit_prompt_like_records(safe_list_records(token, TABLE_PROMPT_IMAGE_VIDEO), table_label=PROMPT_IMAGE_TABLE_LABEL))
    return updates


def table_id_for_label(label: str) -> str:
    return {
        MULTI_ROLE_TABLE_LABEL: TABLE_MULTI_ROLE_FIRST_LAST,
        FIRST_LAST_TABLE_LABEL: TABLE_FIRST_LAST_VIDEO,
        STORYBOARD_TABLE_LABEL: TABLE_STORYBOARD_VIDEO,
        PROMPT_IMAGE_TABLE_LABEL: TABLE_PROMPT_IMAGE_VIDEO,
    }[label]


def apply_updates(token: str, updates: Iterable[Dict[str, Any]]) -> int:
    written = 0
    for update in updates:
        safe_update_record(token, table_id_for_label(update["table"]), update["record_id"], dict(update["fields"]))
        written += 1
    return written


def main(argv: List[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Audit and optionally repair media version fields")
    parser.add_argument("--table", choices=["all", "multi_role", "first_last", "storyboard", "prompt_image"], default="all")
    parser.add_argument("--write", action="store_true", help="write version-field updates; default is dry-run")
    args = parser.parse_args(argv)

    token = get_feishu_token()
    updates = collect_updates(token, args.table)
    written = apply_updates(token, updates) if args.write else 0
    print(json.dumps({
        "dry_run": not args.write,
        "candidate_count": len(updates),
        "written_count": written,
        "updates": updates,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
