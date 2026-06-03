#!/usr/bin/env python3
"""
创建“006-视频编辑任务表”。

用法:
  python3 tk_create_video_edit_table.py --update-config
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
    list_tables,
    load_config,
    opt,
    select,
    text,
    update_config,
)


TABLE_NAME = "006-视频编辑任务表"

RESOLUTION_OPTIONS = [opt("720P", "Green"), opt("1080P", "Blue")]
AUDIO_STRATEGY_OPTIONS = [opt("保留原音频", "Green"), opt("自动处理音频", "Blue")]
EDIT_STATUS_OPTIONS = [opt("不触发", "Gray"), opt("待生成"), opt("生成中", "Orange"), opt("成功", "Green"), opt("失败", "Red")]

VIDEO_EDIT_FIELDS = [
    text("任务名称"),
    attachment("源视频"),
    text("编辑指令"),
    attachment("参考图"),
    select("输出分辨率", RESOLUTION_OPTIONS),
    select("音频策略", AUDIO_STRATEGY_OPTIONS),
    select("编辑状态", EDIT_STATUS_OPTIONS),
    attachment("结果视频"),
    text("视频任务ID"),
    text("错误信息"),
]

TABLE_DEFINITION = {
    "key": "video_edit",
    "name": TABLE_NAME,
    "fields": VIDEO_EDIT_FIELDS,
    "views": {
        "01-任务入口": [
            "任务名称", "源视频", "编辑指令", "参考图", "输出分辨率", "音频策略",
            "编辑状态", "结果视频", "错误信息",
        ],
        "02-结果查看": [
            "任务名称", "编辑状态", "结果视频", "错误信息",
        ],
        "99-排错": [
            "任务名称", "源视频", "编辑指令", "参考图", "输出分辨率", "音频策略",
            "编辑状态", "结果视频", "视频任务ID", "错误信息",
        ],
    },
}


def resolve_video_edit_table_id(config, base_token, tables, *, create_table_fn=create_table):
    configured = ((config.get("feishu") or {}).get("tables") or {}).get("video_edit", "")
    if configured:
        return configured, False

    if tables.get(TABLE_NAME):
        return tables[TABLE_NAME], False

    table_id = create_table_fn(base_token, TABLE_NAME, VIDEO_EDIT_FIELDS)
    return table_id, True


def ensure_video_edit_table(*, update_config_files: bool = False, dry_run: bool = False, config_paths=None):
    config_paths = [Path(path) for path in (config_paths or DEFAULT_CONFIG_PATHS)]
    existing_paths = [path for path in config_paths if path.exists()]
    if not existing_paths:
        raise FileNotFoundError("找不到 config.json/config.ryan.json，无法创建视频编辑表")

    config = load_config(existing_paths[0])
    base_token = config["feishu"]["bitable_app_token"]

    tables = list_tables(base_token)
    table_id, created = resolve_video_edit_table_id(config, base_token, tables)
    if dry_run:
        return {"table_id": table_id, "created": created, "updated_config": []}

    create_missing_fields(base_token, table_id, VIDEO_EDIT_FIELDS)
    create_or_update_views(base_token, table_id, TABLE_DEFINITION["views"])

    updated_config = []
    if update_config_files:
        for path in existing_paths:
            update_config(path, {"video_edit": table_id})
            updated_config.append(str(path))

    return {"table_id": table_id, "created": created, "updated_config": updated_config}


def main():
    parser = argparse.ArgumentParser(description="创建 006-视频编辑任务表")
    parser.add_argument("--update-config", action="store_true", help="把 video_edit table_id 写回本地 config")
    parser.add_argument("--dry-run", action="store_true", help="只解析目标表，不创建字段/视图")
    args = parser.parse_args()

    result = ensure_video_edit_table(update_config_files=args.update_config, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
