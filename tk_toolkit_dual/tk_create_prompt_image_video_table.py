#!/usr/bin/env python3
"""创建 008-图生视频生成表。"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from ai_model_catalog import IMAGE_MODEL_OPTIONS, PROMPT_IMAGE_VIDEO_MODEL_WITH_DEFAULT_OPTIONS
from tk_create_script_doc_shots_table import (
    create_missing_fields,
    create_table,
    list_tables,
    load_config,
    run_json,
    update_config,
)
from view_visibility import apply_view_visibility_snapshot


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATHS = [
    SCRIPT_DIR / "config.json",
    SCRIPT_DIR / "config.ryan.json",
]
TABLE_NAME = "008-图生视频生成表"


class ViewVisibleFieldsMismatch(RuntimeError):
    pass


def opt(name, hue="Blue", lightness="Lighter"):
    return {"name": name, "hue": hue, "lightness": lightness}


def text(name, url=False):
    data = {"name": name, "type": "text"}
    if url:
        data["style"] = {"type": "url"}
    return data


def number(name, precision=0):
    return {
        "name": name,
        "type": "number",
        "style": {"type": "plain", "precision": precision, "percentage": False, "thousands_separator": False},
    }


def datetime_field(name):
    return {"name": name, "type": "datetime", "style": {"format": "yyyy/MM/dd HH:mm"}}


def attachment(name):
    return {"name": name, "type": "attachment"}


def link(name, table_id):
    return {"name": name, "type": "link", "link_table": table_id, "bidirectional": False}


def select(name, options):
    return {"name": name, "type": "select", "multiple": False, "options": options}


RUN_STATUS_OPTIONS = [opt("不触发", "Gray"), opt("待生成"), opt("生成中", "Orange"), opt("成功", "Green"), opt("失败", "Red")]
REVIEW_STATUS_OPTIONS = [opt("待确认", "Gray"), opt("通过", "Green"), opt("不通过", "Red")]
IMAGE_SIZE_OPTIONS = [
    opt("720x1280", "Green"),
    opt("1080x1920", "Blue"),
    opt("1024x1024", "Gray"),
    opt("1280x720", "Gray"),
    opt("1440x2560", "Purple"),
    opt("2K", "Blue"),
    opt("4K", "Purple"),
]
IMAGE_ASPECT_RATIO_OPTIONS = [opt("9:16", "Green"), opt("16:9", "Gray"), opt("1:1", "Gray")]
VIDEO_SIZE_OPTIONS = [opt("720x1280", "Green"), opt("1080x1920", "Blue"), opt("1280x720", "Gray")]
VIDEO_ASPECT_RATIO_OPTIONS = [opt("9:16", "Green"), opt("16:9", "Gray")]
SET_VISIBLE_FIELDS_STEP_PAUSE_SECONDS = 2


PROMPT_IMAGE_VIDEO_FIELDS = [
    text("任务名称"),
    text("生图提示词"),
    text("图生视频提示词"),
    link("关联产品记录", "__PRODUCT_TABLE_ID__"),
    link("选择模特", "__MODEL_TABLE_ID__"),
    attachment("上传产品图"),
    attachment("上传模特图"),
    attachment("上传参考图"),
    select("图片AI模型", IMAGE_MODEL_OPTIONS),
    text("图片AI参数JSON"),
    select("图片画面尺寸", IMAGE_SIZE_OPTIONS),
    select("图片画面比例", IMAGE_ASPECT_RATIO_OPTIONS),
    number("图片版本"),
    select("图片生成状态", RUN_STATUS_OPTIONS),
    attachment("生成图片"),
    text("图片file_token"),
    text("图片本地路径"),
    text("图片任务ID"),
    text("图片原始响应JSON"),
    select("图片审核状态", REVIEW_STATUS_OPTIONS),
    text("图片错误信息"),
    datetime_field("图片生成时间"),
    select("视频生成模型", PROMPT_IMAGE_VIDEO_MODEL_WITH_DEFAULT_OPTIONS),
    text("视频AI参数JSON"),
    number("视频时长秒"),
    select("视频画面尺寸", VIDEO_SIZE_OPTIONS),
    select("视频画面比例", VIDEO_ASPECT_RATIO_OPTIONS),
    number("视频版本"),
    select("视频生成状态", RUN_STATUS_OPTIONS),
    attachment("生成视频"),
    text("视频URL", url=True),
    text("生成视频file_token"),
    text("视频本地路径"),
    text("视频任务ID"),
    text("视频原始响应JSON"),
    text("视频错误信息"),
    datetime_field("视频生成时间"),
    number("参考图数量"),
    text("参考图清单JSON"),
    text("历史生成记录JSON"),
    text("错误信息"),
    datetime_field("生成时间"),
]


ALL_FIELD_NAMES = [field["name"] for field in PROMPT_IMAGE_VIDEO_FIELDS]


TABLE_DEFINITION = {
    "key": "prompt_image_video",
    "name": TABLE_NAME,
    "fields": PROMPT_IMAGE_VIDEO_FIELDS,
    "views": {
        "01-用户入口": [
            "任务名称", "生图提示词", "图生视频提示词", "关联产品记录", "选择模特",
            "上传产品图", "上传模特图", "上传参考图", "图片AI模型", "图片画面尺寸", "图片画面比例",
            "图片生成状态", "图片审核状态",
            "视频生成模型", "视频时长秒", "视频画面尺寸", "视频画面比例",
            "视频生成状态",
        ],
        "02-图片审核": [
            "任务名称", "生图提示词", "关联产品记录", "选择模特",
            "上传产品图", "上传模特图", "上传参考图", "参考图数量",
            "图片AI模型", "图片生成状态", "生成图片", "图片审核状态",
            "图片版本", "图片错误信息",
            "图生视频提示词", "视频生成模型", "视频生成状态",
        ],
        "03-视频结果": [
            "任务名称", "生成图片", "图生视频提示词", "图片审核状态", "视频生成模型",
            "视频时长秒", "视频画面尺寸", "视频画面比例",
            "视频版本", "视频生成状态", "生成视频", "视频URL", "视频错误信息",
        ],
        "98-失败处理": [
            "任务名称", "图片生成状态", "图片错误信息", "图片任务ID",
            "图片原始响应JSON", "视频生成状态", "视频错误信息",
            "视频任务ID", "视频原始响应JSON", "错误信息",
            "参考图数量", "参考图清单JSON", "历史生成记录JSON",
        ],
        "99-全字段系统视图": ALL_FIELD_NAMES,
    },
}


def resolved_fields(config, fields):
    tables = (config.get("feishu") or {}).get("tables", {})
    product_table = tables.get("product", "")
    model_table = tables.get("model_appearance", "")
    resolved = []
    for field in fields:
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


def list_views(base_token, table_id):
    data = run_json([
        "lark-cli", "base", "+view-list",
        "--base-token", base_token,
        "--table-id", table_id,
        "--limit", "100",
    ])
    raw = data.get("data") or {}
    items = raw.get("items") or raw.get("views") or []
    result = {}
    for item in items:
        name = item.get("name") or item.get("view_name")
        view_id = item.get("id") or item.get("view_id")
        if name and view_id:
            result[str(name)] = str(view_id)
    return result


def list_field_names(base_token, table_id):
    data = run_json([
        "lark-cli", "base", "+field-list",
        "--base-token", base_token,
        "--table-id", table_id,
    ])
    raw = data.get("data") or {}
    items = raw.get("items") or raw.get("fields") or []
    result = set()
    for item in items:
        name = item.get("name") or item.get("field_name")
        if name:
            result.add(str(name))
    return result


def view_visible_fields(base_token, table_id, view_id):
    data = run_json([
        "lark-cli", "base", "+view-get-visible-fields",
        "--base-token", base_token,
        "--table-id", table_id,
        "--view-id", view_id,
    ])
    raw = data.get("data") or {}
    fields = raw.get("visible_fields") or []
    return [str(field) for field in fields]


def visible_fields_match(actual_fields, expected_fields):
    if actual_fields == expected_fields:
        return True
    if len(expected_fields) == len(ALL_FIELD_NAMES) and set(actual_fields) == set(expected_fields):
        return True
    return False


def ensure_view_visible_fields(base_token, table_id, view_id, view_name, expected_fields):
    actual_fields = view_visible_fields(base_token, table_id, view_id)
    if visible_fields_match(actual_fields, expected_fields):
        return
    raise ViewVisibleFieldsMismatch(
        f"视图字段未按预期生效：{view_name} "
        f"期望 {len(expected_fields)} 个字段，实际 {len(actual_fields)} 个字段"
    )


def create_view(base_token, table_id, view_name):
    data = run_json([
        "lark-cli", "base", "+view-create",
        "--base-token", base_token,
        "--table-id", table_id,
        "--json", json.dumps({"name": view_name, "type": "grid"}, ensure_ascii=False),
    ])
    view = (data.get("data") or {}).get("view") or {}
    view_id = view.get("id") or view.get("view_id")
    if not view_id:
        view_id = list_views(base_token, table_id).get(view_name)
    if not view_id:
        raise RuntimeError(f"创建视图后未返回 view_id：{view_name}")
    return str(view_id)


def delete_view(base_token, table_id, view_id):
    run_json([
        "lark-cli", "base", "+view-delete",
        "--base-token", base_token,
        "--table-id", table_id,
        "--view-id", view_id,
        "--yes",
    ])


def set_view_visible_fields_once(base_token, table_id, view_id, view_name, visible_fields):
    for attempt in range(4):
        try:
            run_json([
                "lark-cli", "base", "+view-set-visible-fields",
                "--base-token", base_token,
                "--table-id", table_id,
                "--view-id", view_id,
                "--json", json.dumps({"visible_fields": visible_fields}, ensure_ascii=False),
            ])
            ensure_view_visible_fields(base_token, table_id, view_id, view_name, visible_fields)
            return
        except RuntimeError as exc:
            text = str(exc)
            if "800070003" in text or "no operation produced" in text:
                ensure_view_visible_fields(base_token, table_id, view_id, view_name, visible_fields)
                return
            if "800004135" not in text or attempt == 3:
                raise
            time.sleep(2 + attempt * 2)


def staged_visible_field_targets(current_fields, target_fields):
    if visible_fields_match(current_fields, target_fields) or len(target_fields) <= 2:
        return [target_fields]
    stages = [target_fields[:2]]
    stages.extend(target_fields[:idx] for idx in range(3, len(target_fields) + 1))
    return stages


def set_view_visible_fields(base_token, table_id, view_id, view_name, visible_fields):
    current_fields = view_visible_fields(base_token, table_id, view_id)
    stages = staged_visible_field_targets(current_fields, visible_fields)
    for idx, stage_fields in enumerate(stages):
        set_view_visible_fields_once(base_token, table_id, view_id, view_name, stage_fields)
        if idx < len(stages) - 1:
            time.sleep(SET_VISIBLE_FIELDS_STEP_PAUSE_SECONDS)


def create_or_update_views(base_token, table_id, view_definitions):
    view_definitions = apply_view_visibility_snapshot(table_id, view_definitions)
    field_names = list_field_names(base_token, table_id)
    existing = list_views(base_token, table_id)
    created = 0
    updated = 0
    rebuilt = 0
    for name, visible_fields in view_definitions.items():
        missing = [field_name for field_name in visible_fields if field_name not in field_names]
        if missing:
            raise RuntimeError(f"视图 {name} 引用了不存在的字段：{', '.join(missing)}")

        view_id = existing.get(name)
        if not view_id:
            view_id = create_view(base_token, table_id, name)
            created += 1

        try:
            set_view_visible_fields(base_token, table_id, view_id, name, visible_fields)
        except ViewVisibleFieldsMismatch:
            delete_view(base_token, table_id, view_id)
            view_id = create_view(base_token, table_id, name)
            set_view_visible_fields(base_token, table_id, view_id, name, visible_fields)
            rebuilt += 1
        updated += 1
    return {"created": created, "updated": updated, "rebuilt": rebuilt}


def main():
    parser = argparse.ArgumentParser(description="Create 008 prompt image-to-video table")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATHS[0]))
    parser.add_argument("--update-config", action="store_true")
    args = parser.parse_args()

    config_path = Path(args.config)
    config = load_config(config_path)
    base_token = config["feishu"]["bitable_app_token"]
    tables = list_tables(base_token)
    configured_tables = (config.get("feishu") or {}).get("tables") or {}

    table_id = configured_tables.get(TABLE_DEFINITION["key"]) or tables.get(TABLE_DEFINITION["name"])
    fields = resolved_fields(config, TABLE_DEFINITION["fields"])
    created_table = False
    if not table_id:
        table_id = create_table(base_token, TABLE_DEFINITION["name"], fields)
        created_table = True
    if not table_id:
        raise RuntimeError(f"创建表失败：{TABLE_DEFINITION['name']} 未返回 table_id")

    created_fields = create_missing_fields(base_token, table_id, fields)
    view_result = create_or_update_views(base_token, table_id, TABLE_DEFINITION["views"])
    if args.update_config:
        for path in DEFAULT_CONFIG_PATHS:
            if path.exists():
                update_config(path, {TABLE_DEFINITION["key"]: table_id})
    print(json.dumps({
        "table_name": TABLE_DEFINITION["name"],
        "table_id": table_id,
        "created_table": created_table,
        "created_fields": created_fields,
        "views": view_result,
        "config_updated": bool(args.update_config),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
