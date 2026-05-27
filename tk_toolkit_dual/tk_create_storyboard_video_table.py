#!/usr/bin/env python3
"""
创建“故事板图片视频生成表”。

用法:
  python3 tk_create_storyboard_video_table.py --update-config
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from tk_create_script_doc_shots_table import (
    DEFAULT_CONFIG_PATHS,
    attachment,
    create_missing_fields,
    create_or_update_views,
    create_table,
    datetime_field,
    list_tables,
    load_config,
    number,
    opt,
    select,
    text,
    update_config,
)


TABLE_NAME = "故事板图片视频生成表"

RUN_STATUS_OPTIONS = [opt("不触发", "Gray"), opt("待生成"), opt("生成中", "Orange"), opt("成功", "Green"), opt("失败", "Red")]
SPLIT_STATUS_OPTIONS = [opt("不触发", "Gray"), opt("待拆分"), opt("拆分中", "Orange"), opt("成功", "Green"), opt("失败", "Red")]
RECORD_TYPE_OPTIONS = [opt("母任务", "Blue"), opt("Storyboard分段", "Green")]
VIDEO_CHANNEL_OPTIONS = [opt("OTU", "Green")]
VIDEO_MODEL_OPTIONS = [opt("OTU / omni_flash-10s", "Green")]

STORYBOARD_VIDEO_FIELDS = [
    text("任务名称"),
    select("记录类型", RECORD_TYPE_OPTIONS),
    text("父任务记录ID"),
    text("批次ID"),
    text("脚本内容"),
    text("产品名称"),
    text("目标人群"),
    text("核心冲突场景"),
    text("黄金3秒/戏剧钩子"),
    attachment("产品图"),
    attachment("角色图"),
    attachment("环境图"),
    select("拆分状态", SPLIT_STATUS_OPTIONS),
    text("拆分结果JSON"),
    number("总故事板数"),
    number("Storyboard编号"),
    text("Time Range"),
    text("故事板图片提示词"),
    select("故事板图片生成状态", RUN_STATUS_OPTIONS),
    attachment("故事板图"),
    text("故事板图本地路径"),
    text("故事板图file_token"),
    text("故事板图片任务ID"),
    text("故事板图片原始响应JSON"),
    text("故事板图片错误信息"),
    datetime_field("故事板图片生成时间"),
    text("视频提示词"),
    select("视频通道", VIDEO_CHANNEL_OPTIONS),
    select("视频生成模型", VIDEO_MODEL_OPTIONS),
    select("视频生成状态", RUN_STATUS_OPTIONS),
    attachment("分镜视频"),
    text("视频任务ID"),
    text("本地视频路径"),
    text("分镜视频URL", url=True),
    text("分镜视频file_token"),
    text("视频生成原始响应JSON"),
    text("视频错误信息"),
    datetime_field("视频生成时间"),
    text("错误信息"),
    text("失败分类"),
    datetime_field("生成时间"),
]

TABLE_DEFINITION = {
    "key": "storyboard_video",
    "name": TABLE_NAME,
    "fields": STORYBOARD_VIDEO_FIELDS,
    "views": {
        "01-母任务入口": [
            "记录类型", "任务名称", "脚本内容", "产品名称", "目标人群", "核心冲突场景", "黄金3秒/戏剧钩子",
            "产品图", "角色图", "环境图", "拆分状态", "总故事板数", "错误信息",
        ],
        "02-故事板图片": [
            "记录类型", "任务名称", "父任务记录ID", "Storyboard编号", "Time Range", "故事板图片提示词",
            "故事板图片生成状态", "故事板图", "故事板图片错误信息", "故事板图file_token",
        ],
        "03-Omni视频": [
            "记录类型", "任务名称", "父任务记录ID", "Storyboard编号", "Time Range", "故事板图",
            "视频提示词", "视频通道", "视频生成模型", "视频生成状态", "分镜视频", "分镜视频URL",
            "视频错误信息", "视频任务ID", "本地视频路径", "分镜视频file_token", "视频生成时间",
        ],
        "99-排错": [
            "记录类型", "任务名称", "父任务记录ID", "批次ID", "拆分状态", "拆分结果JSON", "故事板图片提示词",
            "故事板图片任务ID", "故事板图片原始响应JSON", "故事板图片错误信息", "视频任务ID",
            "视频生成原始响应JSON", "视频错误信息", "错误信息", "失败分类", "故事板图本地路径", "本地视频路径",
        ],
    },
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Create storyboard image/video table")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATHS[0]))
    parser.add_argument("--update-config", action="store_true")
    args = parser.parse_args()

    config_path = Path(args.config)
    config = load_config(config_path)
    base_token = config["feishu"]["bitable_app_token"]
    tables = list_tables(base_token)
    table_id = tables.get(TABLE_NAME)
    created_table = False
    if not table_id:
        table_id = create_table(base_token, TABLE_NAME, STORYBOARD_VIDEO_FIELDS)
        created_table = True
    if not table_id:
        raise RuntimeError(f"创建表失败：{TABLE_NAME} 未返回 table_id")

    created_fields = create_missing_fields(base_token, table_id, STORYBOARD_VIDEO_FIELDS)
    view_result = create_or_update_views(base_token, table_id, TABLE_DEFINITION["views"])

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
        "config_updated": bool(args.update_config),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
