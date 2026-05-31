#!/usr/bin/env python3
"""
创建“首尾帧视频生成表”。

用法:
  python3 tk_create_first_last_video_table.py --update-config
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from tk_create_script_doc_shots_table import (
    DEFAULT_CONFIG_PATHS,
    AI_CAPABILITY_OPTIONS,
    AI_MODEL_OPTIONS,
    AI_PROVIDER_OPTIONS,
    AI_TASK_TYPE_OPTIONS,
    attachment,
    create_missing_fields,
    create_or_update_views,
    create_table,
    datetime_field,
    list_tables,
    load_config,
    link,
    number,
    opt,
    run_json,
    select,
    text,
    update_config,
    resolved_fields,
    YES_NO_OPTIONS,
)
from ai_model_catalog import IMAGE_MODEL_OPTIONS, TEXT_MODEL_OPTIONS, VIDEO_AI_MODEL_OPTIONS


TABLE_NAME = "首尾帧视频生成表"
OBSOLETE_VIEW_NAMES = ["Grid View", "02-首帧审核", "03-尾帧审核", "04-视频结果"]
RENAMED_FIELDS = {
    "批量拆分状态": "拆分状态",
}

RUN_STATUS_OPTIONS = [opt("不触发", "Gray"), opt("待生成"), opt("生成中", "Orange"), opt("成功", "Green"), opt("失败", "Red")]
SPLIT_STATUS_OPTIONS = [opt("不触发", "Gray"), opt("待拆分"), opt("拆分中", "Orange"), opt("成功", "Green"), opt("失败", "Red")]
RECORD_TYPE_OPTIONS = [opt("母任务", "Purple"), opt("场景子任务", "Blue")]
RECORD_STATE_OPTIONS = [opt("有效", "Green"), opt("已废弃", "Red")]
SPLIT_OPERATION_OPTIONS = [opt("不触发", "Gray"), opt("重新拆分场景", "Orange")]
FIRST_FRAME_OPERATION_OPTIONS = [opt("不触发", "Gray"), opt("重新生成首帧图", "Orange")]
LAST_FRAME_OPERATION_OPTIONS = [opt("不触发", "Gray"), opt("重新生成尾帧图", "Orange")]
VIDEO_OPERATION_OPTIONS = [opt("不触发", "Gray"), opt("重新生成首尾帧视频", "Orange")]
FIRST_REVIEW_STATUS_OPTIONS = [opt("待确认", "Gray"), opt("通过", "Green"), opt("不通过", "Red"), opt("已触发尾帧", "Blue")]
LAST_REVIEW_STATUS_OPTIONS = [opt("待确认", "Gray"), opt("通过", "Green"), opt("不通过", "Red"), opt("已触发视频", "Blue")]
VIDEO_CHANNEL_OPTIONS = [opt("OTU", "Green")]
VIDEO_MODEL_OPTIONS = VIDEO_AI_MODEL_OPTIONS


FIRST_LAST_VIDEO_FIELDS = [
    text("任务名称"),
    select("记录类型", RECORD_TYPE_OPTIONS),
    select("记录状态", RECORD_STATE_OPTIONS),
    text("父任务记录ID"),
    text("批次ID"),
    text("当前批次ID"),
    number("场景编号"),
    text("场景标题"),
    link("关联产品记录", "__PRODUCT_TABLE_ID__"),
    text("产品名称"),
    text("产品参考图file_tokenJSON"),
    text("首尾帧文档"),
    attachment("首尾帧文档附件"),
    number("目标时长秒"),
    select("使用统一AI路由", YES_NO_OPTIONS),
    select("拆分AI模型", TEXT_MODEL_OPTIONS),
    text("拆分AI参数JSON"),
    select("首帧图AI模型", IMAGE_MODEL_OPTIONS),
    text("首帧图AI参数JSON"),
    select("尾帧图AI模型", IMAGE_MODEL_OPTIONS),
    text("尾帧图AI参数JSON"),
    select("视频AI模型", VIDEO_AI_MODEL_OPTIONS),
    text("视频AI参数JSON"),
    select("AI供应商", AI_PROVIDER_OPTIONS),
    select("AI能力类型", AI_CAPABILITY_OPTIONS),
    select("AI任务类型", AI_TASK_TYPE_OPTIONS),
    select("AI模型", AI_MODEL_OPTIONS),
    text("AI参数JSON"),
    select("文档拆分状态", SPLIT_STATUS_OPTIONS),
    select("拆分状态", SPLIT_STATUS_OPTIONS),
    number("总场景数"),
    select("场景拆分操作", SPLIT_OPERATION_OPTIONS),
    text("拆分结果JSON"),
    number("拆分版本"),
    text("首帧生图提示词"),
    text("尾帧生图提示词"),
    text("首尾帧生视频提示词"),
    select("首帧图操作", FIRST_FRAME_OPERATION_OPTIONS),
    number("首帧图版本"),
    select("首帧图生成状态", RUN_STATUS_OPTIONS),
    attachment("首帧图"),
    text("首帧图本地路径"),
    text("首帧图file_token"),
    text("首帧图任务ID"),
    text("首帧图原始响应JSON"),
    text("首帧图错误信息"),
    datetime_field("首帧图生成时间"),
    select("首帧审核状态", FIRST_REVIEW_STATUS_OPTIONS),
    text("首帧审核备注"),
    select("尾帧图操作", LAST_FRAME_OPERATION_OPTIONS),
    number("尾帧图版本"),
    select("尾帧图生成状态", RUN_STATUS_OPTIONS),
    attachment("尾帧图"),
    text("尾帧图本地路径"),
    text("尾帧图file_token"),
    text("尾帧图任务ID"),
    text("尾帧图原始响应JSON"),
    text("尾帧图错误信息"),
    datetime_field("尾帧图生成时间"),
    select("尾帧审核状态", LAST_REVIEW_STATUS_OPTIONS),
    text("尾帧审核备注"),
    select("视频操作", VIDEO_OPERATION_OPTIONS),
    number("视频版本"),
    select("视频通道", VIDEO_CHANNEL_OPTIONS),
    select("视频生成模型", VIDEO_MODEL_OPTIONS),
    select("视频生成状态", RUN_STATUS_OPTIONS),
    attachment("首尾帧视频"),
    text("视频任务ID"),
    text("本地视频路径"),
    text("首尾帧视频URL", url=True),
    text("首尾帧视频file_token"),
    text("视频生成原始响应JSON"),
    text("视频错误信息"),
    datetime_field("视频生成时间"),
    text("历史生成记录JSON"),
    text("错误信息"),
    text("失败分类"),
    datetime_field("生成时间"),
]


TABLE_DEFINITION = {
    "key": "first_last_video",
    "name": TABLE_NAME,
    "fields": FIRST_LAST_VIDEO_FIELDS,
    "views": {
        "01-用户入口": [
            "任务名称",
            "关联产品记录",
            "首尾帧文档",
            "首尾帧文档附件",
            "目标时长秒",
            "拆分AI模型",
            "拆分AI参数JSON",
            "拆分状态",
            "场景拆分操作",
            "总场景数",
            "错误信息",
        ],
        "02-场景子任务": [
            "任务名称",
            "记录状态",
            "父任务记录ID",
            "批次ID",
            "场景编号",
            "场景标题",
            "关联产品记录",
            "产品名称",
            "首帧生图提示词",
            "首帧图AI模型",
            "首帧图AI参数JSON",
            "首帧图操作",
            "尾帧生图提示词",
            "尾帧图AI模型",
            "尾帧图AI参数JSON",
            "尾帧图操作",
            "首尾帧生视频提示词",
            "视频AI模型",
            "视频AI参数JSON",
            "视频操作",
            "场景拆分操作",
            "首帧图生成状态",
            "尾帧图生成状态",
            "视频生成状态",
            "错误信息",
        ],
        "高级AI参数": [
            "任务名称",
            "记录类型",
            "场景编号",
            "使用统一AI路由",
            "拆分AI模型",
            "拆分AI参数JSON",
            "首帧图AI模型",
            "首帧图AI参数JSON",
            "尾帧图AI模型",
            "尾帧图AI参数JSON",
            "视频AI模型",
            "视频AI参数JSON",
            "视频通道",
            "视频生成模型",
            "视频生成状态",
        ],
        "03-首帧审核": [
            "任务名称",
            "场景编号",
            "首帧生图提示词",
            "首帧图AI模型",
            "首帧图AI参数JSON",
            "首帧图操作",
            "首帧图版本",
            "首帧图生成状态",
            "首帧图",
            "首帧审核状态",
            "首帧审核备注",
            "首帧图错误信息",
        ],
        "04-尾帧审核": [
            "任务名称",
            "场景编号",
            "尾帧生图提示词",
            "尾帧图AI模型",
            "尾帧图AI参数JSON",
            "尾帧图操作",
            "尾帧图版本",
            "尾帧图生成状态",
            "尾帧图",
            "尾帧审核状态",
            "尾帧审核备注",
            "尾帧图错误信息",
        ],
        "05-视频结果": [
            "任务名称",
            "场景编号",
            "目标时长秒",
            "首帧图",
            "尾帧图",
            "首尾帧生视频提示词",
            "视频AI模型",
            "视频AI参数JSON",
            "视频操作",
            "视频版本",
            "视频通道",
            "视频生成模型",
            "视频生成状态",
            "首尾帧视频",
            "首尾帧视频URL",
            "视频错误信息",
        ],
        "99-排错": [
            "任务名称",
            "记录类型",
            "记录状态",
            "父任务记录ID",
            "批次ID",
            "当前批次ID",
            "关联产品记录",
            "产品名称",
            "产品参考图file_tokenJSON",
            "使用统一AI路由",
            "拆分AI模型",
            "拆分AI参数JSON",
            "首帧图AI模型",
            "首帧图AI参数JSON",
            "尾帧图AI模型",
            "尾帧图AI参数JSON",
            "视频AI模型",
            "视频AI参数JSON",
            "AI供应商",
            "AI能力类型",
            "AI任务类型",
            "AI模型",
            "AI参数JSON",
            "场景拆分操作",
            "拆分状态",
            "文档拆分状态",
            "拆分结果JSON",
            "拆分版本",
            "首帧图操作",
            "首帧图版本",
            "首帧图任务ID",
            "首帧图原始响应JSON",
            "首帧图错误信息",
            "尾帧图操作",
            "尾帧图版本",
            "尾帧图任务ID",
            "尾帧图原始响应JSON",
            "尾帧图错误信息",
            "视频操作",
            "视频版本",
            "视频任务ID",
            "视频生成原始响应JSON",
            "视频错误信息",
            "错误信息",
            "失败分类",
            "首帧图本地路径",
            "尾帧图本地路径",
            "本地视频路径",
            "历史生成记录JSON",
            "使用统一AI路由",
            "AI供应商",
            "AI能力类型",
            "AI任务类型",
            "AI模型",
            "AI参数JSON",
        ],
    },
}


def list_field_items(base_token: str, table_id: str) -> list[dict]:
    data = run_json([
        "lark-cli", "base", "+field-list",
        "--base-token", base_token,
        "--table-id", table_id,
        "--limit", "200",
    ])
    raw = data.get("data", {})
    return raw.get("items") or raw.get("fields") or []


def field_id(item: dict) -> str:
    return item.get("id") or item.get("field_id") or ""


def migrate_renamed_fields(base_token: str, table_id: str) -> list[str]:
    items = list_field_items(base_token, table_id)
    by_name = {item.get("name") or item.get("field_name"): item for item in items}
    desired_by_name = {field["name"]: field for field in FIRST_LAST_VIDEO_FIELDS}
    renamed: list[str] = []
    for old_name, new_name in RENAMED_FIELDS.items():
        if new_name in by_name or old_name not in by_name:
            continue
        target_field = desired_by_name.get(new_name)
        old_field_id = field_id(by_name[old_name])
        if not target_field or not old_field_id:
            continue
        run_json([
            "lark-cli", "base", "+field-update",
            "--base-token", base_token,
            "--table-id", table_id,
            "--field-id", old_field_id,
            "--json", json.dumps(target_field, ensure_ascii=False),
            "--yes",
        ])
        renamed.append(f"{old_name} -> {new_name}")
    return renamed


def prune_obsolete_views(base_token: str, table_id: str, obsolete_view_names: list[str] = OBSOLETE_VIEW_NAMES) -> list[str]:
    data = run_json([
        "lark-cli", "base", "+view-list",
        "--base-token", base_token,
        "--table-id", table_id,
        "--limit", "100",
    ])
    raw = data.get("data", {})
    items = raw.get("items") or raw.get("views") or []
    by_name = {
        item.get("name"): item.get("id") or item.get("view_id")
        for item in items
        if item.get("name") and (item.get("id") or item.get("view_id"))
    }
    deleted: list[str] = []
    for name in obsolete_view_names:
        view_id = by_name.get(name)
        if not view_id:
            continue
        run_json([
            "lark-cli", "base", "+view-delete",
            "--base-token", base_token,
            "--table-id", table_id,
            "--view-id", view_id,
            "--yes",
        ])
        deleted.append(name)
    return deleted


def resolve_first_last_table_id(config: dict, tables: dict) -> str:
    configured = ((config.get("feishu") or {}).get("tables") or {}).get("first_last_video", "")
    return configured or tables.get(TABLE_NAME, "")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create first/last frame video table")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATHS[0]))
    parser.add_argument("--update-config", action="store_true")
    parser.add_argument("--prune-obsolete-views", action="store_true")
    args = parser.parse_args()

    config_path = Path(args.config)
    config = load_config(config_path)
    base_token = config["feishu"]["bitable_app_token"]
    tables = list_tables(base_token)
    table_id = resolve_first_last_table_id(config, tables)
    fields = resolved_fields(config, FIRST_LAST_VIDEO_FIELDS)
    created_table = False
    if not table_id:
        table_id = create_table(base_token, TABLE_NAME, fields)
        created_table = True
    if not table_id:
        raise RuntimeError(f"创建表失败：{TABLE_NAME} 未返回 table_id")

    renamed_fields = [] if created_table else migrate_renamed_fields(base_token, table_id)
    created_fields = create_missing_fields(base_token, table_id, fields)
    view_result = create_or_update_views(base_token, table_id, TABLE_DEFINITION["views"])
    pruned_views = prune_obsolete_views(base_token, table_id) if args.prune_obsolete_views else []

    if args.update_config:
        for path in DEFAULT_CONFIG_PATHS:
            if path.exists():
                update_config(path, {"first_last_video": table_id})

    print(json.dumps({
        "table_name": TABLE_NAME,
        "table_id": table_id,
        "created_table": created_table,
        "renamed_fields": renamed_fields,
        "created_fields": created_fields,
        "views": view_result,
        "pruned_views": pruned_views,
        "config_updated": bool(args.update_config),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
