#!/usr/bin/env python3
"""
创建“故事板图片视频生成表”。

用法:
  python3 tk_create_storyboard_video_table.py --update-config
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from tk_create_script_doc_shots_table import (
    AI_CAPABILITY_OPTIONS,
    AI_MODEL_OPTIONS,
    AI_PROVIDER_OPTIONS,
    AI_TASK_TYPE_OPTIONS,
    DEFAULT_CONFIG_PATHS,
    YES_NO_OPTIONS,
    attachment,
    create_missing_fields,
    create_or_update_views,
    create_table,
    datetime_field,
    link,
    list_views,
    list_tables,
    load_config,
    number,
    opt,
    run_json,
    select,
    text,
    update_config,
)
from common import extract_text, get_feishu_token, safe_list_records, safe_update_record


TABLE_NAME = "故事板图片视频生成表"

RUN_STATUS_OPTIONS = [opt("不触发", "Gray"), opt("待生成"), opt("生成中", "Orange"), opt("成功", "Green"), opt("失败", "Red")]
SPLIT_STATUS_OPTIONS = [opt("不触发", "Gray"), opt("待拆分"), opt("拆分中", "Orange"), opt("成功", "Green"), opt("失败", "Red")]
RECORD_TYPE_OPTIONS = [opt("母任务", "Blue"), opt("Storyboard分段", "Green")]
STORYBOARD_IMAGE_MODEL_OPTIONS = [opt("gpt-image-2", "Green"), opt("gpt-image-2-2K", "Blue"), opt("gpt-image-2-4K", "Purple")]
STORYBOARD_IMAGE_SIZE_OPTIONS = [opt("1280x720", "Green"), opt("720x1280", "Blue"), opt("1024x1024", "Gray")]
STORYBOARD_IMAGE_ASPECT_RATIO_OPTIONS = [opt("16:9", "Green"), opt("9:16", "Blue"), opt("1:1", "Gray")]
STORYBOARD_IMAGE_DEFAULT_FIELDS = {
    "故事板图片模型": "gpt-image-2",
    "故事板图片画面尺寸": "1280x720",
    "故事板图片画面比例": "16:9",
}
OMNI_MODEL_OPTIONS = [opt("omni_flash-10s", "Green")]
OMNI_SIZE_OPTIONS = [opt("720x1280", "Green"), opt("1280x720", "Blue")]
OMNI_ASPECT_RATIO_OPTIONS = [opt("9:16", "Green"), opt("16:9", "Blue")]
OMNI_DEFAULT_FIELDS = {
    "Omni模型": "omni_flash-10s",
    "Omni画面尺寸": "720x1280",
    "Omni画面比例": "9:16",
}
OBSOLETE_FIELDS = [
    "产品名称",
    "目标人群",
    "核心冲突场景",
    "黄金3秒/戏剧钩子",
    "产品图",
    "角色图",
    "故事板图本地路径",
    "故事板图file_token",
    "故事板图片原始响应JSON",
    "视频通道",
    "视频生成模型",
    "本地视频路径",
    "分镜视频file_token",
    "视频生成原始响应JSON",
    "失败分类",
    "生成时间",
]

STORYBOARD_VIDEO_FIELDS = [
    text("任务名称"),
    select("记录类型", RECORD_TYPE_OPTIONS),
    text("父任务记录ID"),
    text("批次ID"),
    text("脚本内容"),
    link("关联产品记录", "__PRODUCT_TABLE_ID__"),
    link("选择模特", "__MODEL_TABLE_ID__"),
    attachment("环境图"),
    select("使用统一AI路由", YES_NO_OPTIONS),
    select("AI供应商", AI_PROVIDER_OPTIONS),
    select("AI能力类型", AI_CAPABILITY_OPTIONS),
    select("AI任务类型", AI_TASK_TYPE_OPTIONS),
    select("AI模型", AI_MODEL_OPTIONS),
    text("AI参数JSON"),
    select("拆分状态", SPLIT_STATUS_OPTIONS),
    text("拆分结果JSON"),
    number("总故事板数"),
    number("Storyboard编号"),
    text("Time Range"),
    text("故事板图片提示词"),
    select("故事板图片模型", STORYBOARD_IMAGE_MODEL_OPTIONS),
    select("故事板图片画面尺寸", STORYBOARD_IMAGE_SIZE_OPTIONS),
    select("故事板图片画面比例", STORYBOARD_IMAGE_ASPECT_RATIO_OPTIONS),
    select("故事板图片生成状态", RUN_STATUS_OPTIONS),
    attachment("故事板图"),
    text("故事板图片任务ID"),
    text("故事板图片错误信息"),
    datetime_field("故事板图片生成时间"),
    text("视频提示词"),
    select("Omni模型", OMNI_MODEL_OPTIONS),
    select("Omni画面尺寸", OMNI_SIZE_OPTIONS),
    select("Omni画面比例", OMNI_ASPECT_RATIO_OPTIONS),
    select("视频生成状态", RUN_STATUS_OPTIONS),
    attachment("分镜视频"),
    text("视频任务ID"),
    text("分镜视频URL", url=True),
    text("视频错误信息"),
    datetime_field("视频生成时间"),
    text("错误信息"),
]

TABLE_DEFINITION = {
    "key": "storyboard_video",
    "name": TABLE_NAME,
    "fields": STORYBOARD_VIDEO_FIELDS,
    "views": {
        "01-母任务入口": [
            "任务名称", "脚本内容", "关联产品记录", "选择模特", "环境图", "拆分状态", "错误信息",
        ],
        "02-故事板图片": [
            "记录类型", "任务名称", "父任务记录ID", "Storyboard编号", "Time Range",
            "故事板图片提示词", "故事板图片模型", "故事板图片画面尺寸", "故事板图片画面比例",
            "故事板图片生成状态", "故事板图", "故事板图片错误信息",
        ],
        "03-Omni视频": [
            "记录类型", "任务名称", "父任务记录ID", "Storyboard编号", "Time Range", "故事板图",
            "视频提示词", "Omni模型", "Omni画面尺寸", "Omni画面比例",
            "视频生成状态", "分镜视频", "分镜视频URL", "视频错误信息", "视频生成时间",
        ],
        "高级AI参数": [
            "记录类型", "任务名称", "父任务记录ID", "Storyboard编号",
            "使用统一AI路由", "AI供应商", "AI能力类型", "AI任务类型", "AI模型", "AI参数JSON",
            "故事板图片模型", "故事板图片画面尺寸", "故事板图片画面比例",
            "Omni模型", "Omni画面尺寸", "Omni画面比例",
        ],
        "99-排错": [
            "记录类型", "任务名称", "父任务记录ID", "批次ID", "关联产品记录", "选择模特",
            "拆分状态", "拆分结果JSON", "故事板图片提示词",
            "故事板图片模型", "故事板图片画面尺寸", "故事板图片画面比例",
            "故事板图片任务ID", "故事板图片错误信息", "故事板图片生成时间",
            "视频提示词", "Omni模型", "Omni画面尺寸", "Omni画面比例",
            "视频任务ID", "视频错误信息", "视频生成时间", "错误信息",
            "使用统一AI路由", "AI供应商", "AI能力类型", "AI任务类型", "AI模型", "AI参数JSON",
        ],
    },
}

VIEW_FILTERS = {
    "01-母任务入口": {
        "logic": "and",
        "conditions": [["记录类型", "intersects", ["母任务"]]],
    },
    "02-故事板图片": {
        "logic": "and",
        "conditions": [["记录类型", "intersects", ["Storyboard分段"]]],
    },
    "03-Omni视频": {
        "logic": "and",
        "conditions": [["记录类型", "intersects", ["Storyboard分段"]]],
    },
}


def resolved_storyboard_fields(config):
    tables = (config.get("feishu") or {}).get("tables", {})
    product_table = tables.get("product", "")
    model_table = tables.get("model_appearance", "")
    resolved = []
    for field in STORYBOARD_VIDEO_FIELDS:
        item = dict(field)
        if item.get("link_table") == "__PRODUCT_TABLE_ID__":
            if not product_table:
                continue
            item["link_table"] = product_table
        if item.get("link_table") == "__MODEL_TABLE_ID__":
            if not model_table:
                continue
            item["link_table"] = model_table
        resolved.append(item)
    return resolved


def field_value_is_non_empty(value):
    if value is None:
        return False
    if value == "" or value == []:
        return False
    if isinstance(value, str) and not value.strip():
        return False
    return True


def prune_obsolete_fields(base_token, table_id, field_names=OBSOLETE_FIELDS):
    token = get_feishu_token()
    records = safe_list_records(token, table_id)
    non_empty = sorted({
        field_name
        for rec in records
        for field_name in field_names
        if field_value_is_non_empty((rec.get("fields") or {}).get(field_name))
    })
    if non_empty:
        raise RuntimeError(f"以下字段存在非空数据，已中止删除: {', '.join(non_empty)}")

    raw_fields = run_json([
        "lark-cli", "base", "+field-list",
        "--base-token", base_token,
        "--table-id", table_id,
        "--limit", "200",
    ]).get("data", {})
    field_items = raw_fields.get("items") or raw_fields.get("fields") or []
    existing_names = set()
    field_ids_by_name = {}
    for item in field_items:
        if isinstance(item, dict):
            name = item.get("name") or item.get("field_name")
            if name:
                existing_names.add(name)
                field_id = item.get("id") or item.get("field_id")
                if field_id:
                    field_ids_by_name[name] = field_id

    deleted = []
    for field_name in field_names:
        if existing_names and field_name not in existing_names:
            continue
        field_id = field_ids_by_name.get(field_name) or field_name
        run_json([
            "lark-cli", "base", "+field-delete",
            "--base-token", base_token,
            "--table-id", table_id,
            "--field-id", field_id,
            "--yes",
        ])
        deleted.append(field_name)
    return deleted


def resolve_storyboard_table_id(config, base_token, tables, *, create_table_fn=create_table, fields=None):
    configured = ((config.get("feishu") or {}).get("tables") or {}).get("storyboard_video", "")
    if configured:
        return configured, False
    table_id = tables.get(TABLE_NAME)
    if table_id:
        return table_id, False
    table_id = create_table_fn(base_token, TABLE_NAME, fields or [])
    return table_id, True


def backfill_storyboard_omni_defaults(token, table_id):
    updated = 0
    for rec in safe_list_records(token, table_id):
        fields = rec.get("fields") or {}
        if extract_text(fields.get("记录类型")).strip() != "Storyboard分段":
            continue
        defaults = {
            name: value
            for name, value in OMNI_DEFAULT_FIELDS.items()
            if not extract_text(fields.get(name)).strip()
        }
        if not defaults:
            continue
        record_id = rec.get("record_id") or rec.get("id")
        if not record_id:
            continue
        safe_update_record(token, table_id, record_id, defaults)
        updated += 1
    return updated


def backfill_storyboard_image_defaults(token, table_id):
    updated = 0
    for rec in safe_list_records(token, table_id):
        fields = rec.get("fields") or {}
        if extract_text(fields.get("记录类型")).strip() != "Storyboard分段":
            continue
        defaults = {
            name: value
            for name, value in STORYBOARD_IMAGE_DEFAULT_FIELDS.items()
            if not extract_text(fields.get(name)).strip()
        }
        if not defaults:
            continue
        record_id = rec.get("record_id") or rec.get("id")
        if not record_id:
            continue
        safe_update_record(token, table_id, record_id, defaults)
        updated += 1
    return updated


def _looks_like_storyboard_segment(fields):
    return bool(
        extract_text(fields.get("父任务记录ID")).strip()
        or extract_text(fields.get("故事板图片提示词")).strip()
        or extract_text(fields.get("Storyboard编号")).strip()
        or extract_text(fields.get("故事板图片生成状态")).strip()
        or extract_text(fields.get("视频生成状态")).strip()
    )


def _looks_like_parent_task(fields):
    return bool(
        extract_text(fields.get("脚本内容")).strip()
        or fields.get("关联产品记录")
        or fields.get("选择模特")
        or fields.get("环境图")
        or extract_text(fields.get("拆分状态")).strip()
    )


def backfill_storyboard_record_types(token, table_id):
    updated = 0
    for rec in safe_list_records(token, table_id):
        fields = rec.get("fields") or {}
        current_type = extract_text(fields.get("记录类型")).strip()
        wanted_type = ""
        if _looks_like_storyboard_segment(fields):
            wanted_type = "Storyboard分段"
        elif not current_type and _looks_like_parent_task(fields):
            wanted_type = "母任务"
        if not wanted_type or current_type == wanted_type:
            continue
        record_id = rec.get("record_id") or rec.get("id")
        if not record_id:
            continue
        safe_update_record(token, table_id, record_id, {"记录类型": wanted_type})
        updated += 1
    return updated


def backfill_storyboard_parent_task_names(token, table_id):
    updated = 0
    for rec in safe_list_records(token, table_id):
        fields = rec.get("fields") or {}
        if extract_text(fields.get("记录类型")).strip() != "母任务":
            continue
        if extract_text(fields.get("任务名称")).strip():
            continue
        record_id = rec.get("record_id") or rec.get("id")
        if not record_id:
            continue
        safe_update_record(token, table_id, record_id, {"任务名称": f"故事板任务-{record_id[-6:]}"})
        updated += 1
    return updated


def apply_storyboard_view_filters(base_token, table_id, filters=VIEW_FILTERS):
    existing = list_views(base_token, table_id)
    updated = 0
    for name, filter_config in filters.items():
        view_id = existing.get(name)
        if not view_id:
            continue
        for attempt in range(4):
            try:
                run_json([
                    "lark-cli", "base", "+view-set-filter",
                    "--base-token", base_token,
                    "--table-id", table_id,
                    "--view-id", view_id,
                    "--json", json.dumps(filter_config, ensure_ascii=False),
                ])
                break
            except RuntimeError as exc:
                if "800004135" not in str(exc) or attempt == 3:
                    raise
                time.sleep(2 + attempt * 2)
        updated += 1
    return updated


def main() -> None:
    parser = argparse.ArgumentParser(description="Create storyboard image/video table")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATHS[0]))
    parser.add_argument("--update-config", action="store_true")
    parser.add_argument("--prune-obsolete-fields", action="store_true")
    args = parser.parse_args()

    config_path = Path(args.config)
    config = load_config(config_path)
    base_token = config["feishu"]["bitable_app_token"]
    fields = resolved_storyboard_fields(config)
    tables = list_tables(base_token)
    table_id, created_table = resolve_storyboard_table_id(config, base_token, tables, fields=fields)
    if not table_id:
        raise RuntimeError(f"创建表失败：{TABLE_NAME} 未返回 table_id")

    created_fields = create_missing_fields(base_token, table_id, fields)
    view_result = create_or_update_views(base_token, table_id, TABLE_DEFINITION["views"])
    filtered_views = apply_storyboard_view_filters(base_token, table_id)
    token = get_feishu_token()
    backfilled_record_types = backfill_storyboard_record_types(token, table_id)
    backfilled_parent_names = backfill_storyboard_parent_task_names(token, table_id)
    backfilled_image_defaults = backfill_storyboard_image_defaults(token, table_id)
    backfilled_omni_defaults = backfill_storyboard_omni_defaults(token, table_id)
    pruned_fields = prune_obsolete_fields(base_token, table_id) if args.prune_obsolete_fields else []

    if args.update_config:
        for path in DEFAULT_CONFIG_PATHS:
            if path.exists():
                update_config(path, {"storyboard_video": table_id})

    print(json.dumps({
        "table_name": TABLE_NAME,
        "table_id": table_id,
        "created_table": created_table,
        "created_fields": created_fields,
        "filtered_views": filtered_views,
        "backfilled_record_types": backfilled_record_types,
        "backfilled_parent_names": backfilled_parent_names,
        "backfilled_image_defaults": backfilled_image_defaults,
        "backfilled_omni_defaults": backfilled_omni_defaults,
        "pruned_fields": pruned_fields,
        "views": view_result,
        "config_updated": bool(args.update_config),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
