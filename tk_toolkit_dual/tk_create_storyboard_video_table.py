#!/usr/bin/env python3
"""创建 004-故事板视频生成表。"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from ai_model_catalog import IMAGE_MODEL_OPTIONS, STORYBOARD_VIDEO_MODEL_WITH_DEFAULT_OPTIONS
from tk_create_script_doc_shots_table import (
    attachment,
    create_missing_fields,
    create_table,
    datetime_field,
    link,
    list_tables,
    list_views,
    load_config,
    number,
    opt,
    run_json,
    select,
    text,
    update_config,
)
from tk_create_prompt_image_video_table import create_or_update_views


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATHS = [
    SCRIPT_DIR / "config.json",
    SCRIPT_DIR / "config.ryan.json",
]
TABLE_NAME = "004-故事板视频生成表"

RUN_STATUS_OPTIONS = [opt("不触发", "Gray"), opt("待生成"), opt("生成中", "Orange"), opt("成功", "Green"), opt("失败", "Red")]
PARSE_STATUS_OPTIONS = [opt("不触发", "Gray"), opt("待解析"), opt("解析中", "Orange"), opt("成功", "Green"), opt("失败", "Red")]
RECORD_TYPE_OPTIONS = [opt("母任务", "Blue"), opt("Storyboard分段", "Green")]
RECORD_STATE_OPTIONS = [opt("有效", "Green"), opt("已废弃", "Gray")]
REVIEW_STATUS_OPTIONS = [opt("待确认", "Gray"), opt("通过", "Green"), opt("不通过", "Red")]
DOCUMENT_SOURCE_OPTIONS = [opt("正文", "Green"), opt("附件", "Blue")]
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


STORYBOARD_VIDEO_FIELDS = [
    text("任务名称"),
    select("记录类型", RECORD_TYPE_OPTIONS),
    select("记录状态", RECORD_STATE_OPTIONS),
    text("父任务记录ID"),
    text("批次ID"),
    text("故事板文档正文"),
    attachment("故事板Markdown附件"),
    select("故事板文档来源", DOCUMENT_SOURCE_OPTIONS),
    link("关联产品记录", "__PRODUCT_TABLE_ID__"),
    link("选择模特", "__MODEL_TABLE_ID__"),
    attachment("上传产品图"),
    attachment("上传模特图"),
    attachment("上传参考图"),
    select("解析状态", PARSE_STATUS_OPTIONS),
    text("解析结果JSON"),
    number("总Storyboard数"),
    number("Storyboard编号"),
    text("Time Range"),
    text("故事板标题"),
    text("原始Prompt块"),
    text("生图提示词"),
    text("图生视频提示词"),
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
    select("视频生成模型", STORYBOARD_VIDEO_MODEL_WITH_DEFAULT_OPTIONS),
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

ALL_FIELD_NAMES = [field["name"] for field in STORYBOARD_VIDEO_FIELDS]

TABLE_DEFINITION = {
    "key": "storyboard_video",
    "name": TABLE_NAME,
    "fields": STORYBOARD_VIDEO_FIELDS,
    "views": {
        "01-任务入口": [
            "任务名称", "记录类型", "记录状态", "故事板文档正文", "故事板Markdown附件",
            "故事板文档来源", "关联产品记录", "选择模特", "上传产品图", "上传模特图", "上传参考图",
            "解析状态", "总Storyboard数", "批次ID", "错误信息",
        ],
        "02-故事板图片审核": [
            "任务名称", "记录状态", "父任务记录ID", "Storyboard编号", "Time Range", "故事板标题",
            "生图提示词", "关联产品记录", "选择模特", "上传产品图", "上传模特图", "上传参考图",
            "图片AI模型", "图片画面尺寸", "图片画面比例", "图片生成状态",
            "生成图片", "图片审核状态", "图片错误信息",
        ],
        "03-故事板视频结果": [
            "任务名称", "记录状态", "父任务记录ID", "Storyboard编号", "Time Range", "生成图片",
            "图生视频提示词", "图片审核状态", "视频生成模型", "视频时长秒",
            "视频画面尺寸", "视频画面比例", "视频生成状态", "生成视频", "视频URL", "视频错误信息",
        ],
        "98-失败处理": [
            "任务名称", "记录类型", "记录状态", "父任务记录ID", "批次ID",
            "解析状态", "图片生成状态", "视频生成状态",
            "错误信息", "图片错误信息", "视频错误信息",
            "图片任务ID", "视频任务ID", "解析结果JSON", "历史生成记录JSON",
        ],
        "99-全字段系统视图": ALL_FIELD_NAMES,
    },
}

VIEW_FILTERS = {
    "01-任务入口": {"logic": "and", "conditions": [["记录类型", "intersects", ["母任务"]]]},
    "02-故事板图片审核": {"logic": "and", "conditions": [["记录类型", "intersects", ["Storyboard分段"]]]},
    "03-故事板视频结果": {"logic": "and", "conditions": [["记录类型", "intersects", ["Storyboard分段"]]]},
    "98-失败处理": {
        "logic": "or",
        "conditions": [
            ["解析状态", "intersects", ["失败"]],
            ["图片生成状态", "intersects", ["失败"]],
            ["视频生成状态", "intersects", ["失败"]],
            ["错误信息", "non_empty"],
            ["图片错误信息", "non_empty"],
            ["视频错误信息", "non_empty"],
        ],
    },
}


def resolved_fields(config):
    tables = (config.get("feishu") or {}).get("tables") or {}
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


def apply_view_filters(base_token, table_id, filters=VIEW_FILTERS):
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
                updated += 1
                break
            except RuntimeError as exc:
                if "800004135" not in str(exc) or attempt == 3:
                    raise
                time.sleep(2 + attempt * 2)
    return updated


def main():
    parser = argparse.ArgumentParser(description="Create storyboard video table")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATHS[0]))
    parser.add_argument("--update-config", action="store_true")
    args = parser.parse_args()

    config_path = Path(args.config)
    config = load_config(config_path)
    base_token = config["feishu"]["bitable_app_token"]
    tables = list_tables(base_token)
    configured = (config.get("feishu") or {}).get("tables") or {}
    fields = resolved_fields(config)
    table_id = configured.get("storyboard_video") or tables.get(TABLE_NAME)
    created_table = False
    if not table_id:
        table_id = create_table(base_token, TABLE_NAME, fields)
        created_table = True
    if not table_id:
        raise RuntimeError(f"创建表失败：{TABLE_NAME} 未返回 table_id")
    created_fields = create_missing_fields(base_token, table_id, fields)
    view_result = create_or_update_views(base_token, table_id, TABLE_DEFINITION["views"])
    filter_count = apply_view_filters(base_token, table_id)
    if args.update_config:
        for path in DEFAULT_CONFIG_PATHS:
            if path.exists():
                update_config(path, {"storyboard_video": table_id})
    print(json.dumps({
        "table_name": TABLE_NAME,
        "table_id": table_id,
        "created_table": created_table,
        "created_fields": created_fields,
        "views": view_result,
        "filters_updated": filter_count,
        "config_updated": bool(args.update_config),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
