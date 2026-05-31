#!/usr/bin/env python3
"""
创建“多图九宫格视频生成表”。

用法:
  python3 tk_create_nine_grid_video_table.py --update-config
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from tk_create_script_doc_shots_table import (
    AI_PROVIDER_OPTIONS,
    DEFAULT_CONFIG_PATHS,
    attachment,
    create_missing_fields,
    create_or_update_views,
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
from ai_model_catalog import IMAGE_MODEL_OPTIONS, TEXT_MODEL_OPTIONS, VIDEO_AI_MODEL_OPTIONS


TABLE_NAME = "多图九宫格视频生成表"

RUN_STATUS_OPTIONS = [opt("不触发", "Gray"), opt("待生成"), opt("生成中", "Orange"), opt("成功", "Green"), opt("失败", "Red")]
PLAN_STATUS_OPTIONS = [opt("不触发", "Gray"), opt("待生成"), opt("生成中", "Orange"), opt("成功", "Green"), opt("失败", "Red")]
RECORD_TYPE_OPTIONS = [opt("母任务", "Blue"), opt("参考资产", "Purple"), opt("Board分段", "Green")]
REVIEW_STATUS_OPTIONS = [opt("待确认", "Orange"), opt("通过", "Green"), opt("不通过", "Red")]
REFERENCE_SOURCE_OPTIONS = [opt("AI自动生成", "Green"), opt("手动上传", "Blue"), opt("选择模特表", "Purple")]
ENVIRONMENT_SOURCE_OPTIONS = [opt("AI自动生成", "Green"), opt("手动上传", "Blue")]
ASSET_TYPE_OPTIONS = [opt("human", "Blue"), opt("pet", "Green"), opt("environment", "Purple")]
REFERENCE_OPERATION_OPTIONS = [opt("不触发", "Gray"), opt("重新生成参考图", "Orange")]

IMAGE_SIZE_OPTIONS = [opt("720x1280", "Green"), opt("1080x1920", "Blue"), opt("1024x1024", "Gray")]
IMAGE_ASPECT_RATIO_OPTIONS = [opt("9:16", "Green"), opt("1:1", "Gray")]
VIDEO_SIZE_OPTIONS = [opt("720x1280", "Green"), opt("1080x1920", "Blue"), opt("1280x720", "Gray")]
VIDEO_ASPECT_RATIO_OPTIONS = [opt("9:16", "Green"), opt("16:9", "Gray")]


def prefixed_field_group(prefix: str, model_options):
    return [
        select(f"{prefix}AI供应商", AI_PROVIDER_OPTIONS),
        select(f"{prefix}AI模型", model_options),
        text(f"{prefix}AI参数JSON"),
    ]


NINE_GRID_VIDEO_FIELDS = [
    text("任务名称"),
    select("记录类型", RECORD_TYPE_OPTIONS),
    text("父任务记录ID"),
    text("批次ID"),
    text("脚本内容"),
    link("关联产品记录", "__PRODUCT_TABLE_ID__"),
    select("人物/宠物默认来源", REFERENCE_SOURCE_OPTIONS),
    select("环境图来源", ENVIRONMENT_SOURCE_OPTIONS),
    link("选择模特", "__MODEL_TABLE_ID__"),
    attachment("环境图"),
    *prefixed_field_group("参考图", IMAGE_MODEL_OPTIONS),
    *prefixed_field_group("方案", TEXT_MODEL_OPTIONS),
    select("方案生成状态", PLAN_STATUS_OPTIONS),
    text("方案JSON"),
    text("方案Markdown"),
    text("资产ID"),
    select("资产类型", ASSET_TYPE_OPTIONS),
    text("资产名称"),
    text("资产角色说明"),
    text("参考提示词"),
    select("参考图来源", REFERENCE_SOURCE_OPTIONS),
    select("参考图生成状态", RUN_STATUS_OPTIONS),
    attachment("参考图"),
    text("参考图file_token"),
    text("参考图本地路径"),
    text("参考图任务ID"),
    text("参考图错误信息"),
    datetime_field("参考图生成时间"),
    select("参考图审核状态", REVIEW_STATUS_OPTIONS),
    select("参考图操作", REFERENCE_OPERATION_OPTIONS),
    number("总Board数"),
    number("Board编号"),
    text("Time Range"),
    text("叙事任务"),
    text("起始画面"),
    text("结束画面"),
    text("衔接锚点"),
    text("九格摘要JSON"),
    select("审核状态", REVIEW_STATUS_OPTIONS),
    text("审核备注"),
    text("九宫格图片提示词"),
    *prefixed_field_group("图片", IMAGE_MODEL_OPTIONS),
    select("图片画面尺寸", IMAGE_SIZE_OPTIONS),
    select("图片画面比例", IMAGE_ASPECT_RATIO_OPTIONS),
    select("图片生成状态", RUN_STATUS_OPTIONS),
    attachment("九宫格图"),
    text("图片任务ID"),
    text("图片错误信息"),
    datetime_field("图片生成时间"),
    text("视频提示词"),
    *prefixed_field_group("视频", VIDEO_AI_MODEL_OPTIONS),
    select("视频画面尺寸", VIDEO_SIZE_OPTIONS),
    select("视频画面比例", VIDEO_ASPECT_RATIO_OPTIONS),
    select("视频生成状态", RUN_STATUS_OPTIONS),
    attachment("分镜视频"),
    text("视频任务ID"),
    text("分镜视频URL", url=True),
    text("视频错误信息"),
    datetime_field("视频生成时间"),
    text("错误信息"),
]


TABLE_DEFINITION = {
    "key": "nine_grid_video",
    "name": TABLE_NAME,
    "fields": NINE_GRID_VIDEO_FIELDS,
    "views": {
        "01-任务入口": [
            "任务名称", "脚本内容", "关联产品记录", "人物/宠物默认来源", "环境图来源",
            "方案AI模型", "方案AI参数JSON", "方案生成状态", "错误信息",
        ],
        "02-参考资产确认": [
            "记录类型", "任务名称", "父任务记录ID", "资产ID", "资产类型", "资产名称",
            "资产角色说明", "参考图来源", "选择模特", "参考提示词",
            "参考图AI模型", "参考图AI参数JSON", "参考图生成状态", "参考图",
            "参考图审核状态", "参考图操作", "参考图错误信息",
        ],
        "02-方案审核": [
            "记录类型", "任务名称", "父任务记录ID", "Board编号", "Time Range", "叙事任务",
            "起始画面", "结束画面", "衔接锚点", "九格摘要JSON", "审核状态", "审核备注",
        ],
        "03-九宫格生成": [
            "记录类型", "任务名称", "父任务记录ID", "Board编号", "Time Range",
            "九宫格图片提示词", "图片AI模型", "图片AI参数JSON",
            "图片画面尺寸", "图片画面比例", "图片生成状态", "九宫格图", "图片错误信息",
        ],
        "04-视频生成": [
            "记录类型", "任务名称", "父任务记录ID", "Board编号", "Time Range", "九宫格图",
            "视频提示词", "视频AI模型", "视频AI参数JSON",
            "视频画面尺寸", "视频画面比例", "视频生成状态", "分镜视频", "分镜视频URL", "视频错误信息",
        ],
        "高级AI参数": [
            "记录类型", "任务名称", "父任务记录ID", "Board编号",
            "参考图AI模型", "参考图AI参数JSON",
            "方案AI模型", "方案AI参数JSON",
            "图片AI模型", "图片AI参数JSON",
            "视频AI模型", "视频AI参数JSON",
        ],
        "99-排错": [
            "记录类型", "任务名称", "父任务记录ID", "批次ID", "关联产品记录", "选择模特",
            "人物/宠物默认来源", "环境图来源", "资产ID", "资产类型", "参考图来源",
            "参考图生成状态", "参考图审核状态", "参考图任务ID", "参考图file_token",
            "参考图本地路径", "参考图错误信息", "参考图生成时间",
            "方案生成状态", "方案JSON", "方案Markdown", "九格摘要JSON",
            "图片任务ID", "图片错误信息", "图片生成时间",
            "视频任务ID", "视频错误信息", "视频生成时间", "错误信息",
            "参考图AI供应商", "参考图AI模型", "参考图AI参数JSON",
            "方案AI供应商", "方案AI模型", "方案AI参数JSON",
            "图片AI供应商", "图片AI模型", "图片AI参数JSON",
            "视频AI供应商", "视频AI模型", "视频AI参数JSON",
        ],
    },
}


VIEW_FILTERS = {
    "01-任务入口": {"logic": "and", "conditions": [["记录类型", "intersects", ["母任务"]]]},
    "02-参考资产确认": {"logic": "and", "conditions": [["记录类型", "intersects", ["参考资产"]]]},
    "02-方案审核": {"logic": "and", "conditions": [["记录类型", "intersects", ["Board分段"]]]},
    "03-九宫格生成": {"logic": "and", "conditions": [["记录类型", "intersects", ["Board分段"]]]},
    "04-视频生成": {"logic": "and", "conditions": [["记录类型", "intersects", ["Board分段"]]]},
}


def resolved_nine_grid_fields(config):
    tables = (config.get("feishu") or {}).get("tables", {})
    product_table = tables.get("product", "")
    model_table = tables.get("model_appearance", "")
    resolved = []
    for field in NINE_GRID_VIDEO_FIELDS:
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


def resolve_nine_grid_table_id(config, base_token, tables, *, create_table_fn=create_table, fields=None):
    configured = ((config.get("feishu") or {}).get("tables") or {}).get("nine_grid_video", "")
    if configured:
        return configured, False
    table_id = tables.get(TABLE_NAME)
    if table_id:
        return table_id, False
    table_id = create_table_fn(base_token, TABLE_NAME, fields or [])
    return table_id, True


def apply_nine_grid_view_filters(base_token, table_id, filters=VIEW_FILTERS):
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
    parser = argparse.ArgumentParser(description="Create multi-image nine-grid video table")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATHS[0]))
    parser.add_argument("--update-config", action="store_true")
    args = parser.parse_args()

    config_path = Path(args.config)
    config = load_config(config_path)
    base_token = config["feishu"]["bitable_app_token"]
    fields = resolved_nine_grid_fields(config)
    tables = list_tables(base_token)
    table_id, created_table = resolve_nine_grid_table_id(config, base_token, tables, fields=fields)
    if not table_id:
        raise RuntimeError(f"创建表失败：{TABLE_NAME} 未返回 table_id")

    created_fields = create_missing_fields(base_token, table_id, fields)
    view_result = create_or_update_views(base_token, table_id, TABLE_DEFINITION["views"])
    filtered_views = apply_nine_grid_view_filters(base_token, table_id)

    if args.update_config:
        for path in DEFAULT_CONFIG_PATHS:
            if path.exists():
                update_config(path, {"nine_grid_video": table_id})

    print(json.dumps({
        "table_name": TABLE_NAME,
        "table_id": table_id,
        "created_table": created_table,
        "created_fields": created_fields,
        "filtered_views": filtered_views,
        "views": view_result,
        "config_updated": bool(args.update_config),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
