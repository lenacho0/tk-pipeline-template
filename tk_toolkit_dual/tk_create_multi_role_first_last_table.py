#!/usr/bin/env python3
"""
创建“多角色首尾帧生成表”。

用法:
  python3 tk_create_multi_role_first_last_table.py --update-config
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from tk_create_script_doc_shots_table import (
    create_missing_fields,
    create_or_update_views,
    create_table,
    list_tables,
    load_config,
    resolved_fields as resolve_common_fields,
    update_config,
)


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATHS = [
    SCRIPT_DIR / "config.json",
    SCRIPT_DIR / "config.ryan.json",
]
TABLE_NAME = "多角色首尾帧生成表"


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


RECORD_TYPE_OPTIONS = [opt("母任务"), opt("参考资产"), opt("关键帧"), opt("视频片段")]
RECORD_STATE_OPTIONS = [opt("有效", "Green"), opt("已废弃", "Gray")]
RUN_STATUS_OPTIONS = [opt("不触发", "Gray"), opt("待生成"), opt("生成中", "Orange"), opt("成功", "Green"), opt("失败", "Red")]
REVIEW_STATUS_OPTIONS = [opt("待确认", "Gray"), opt("通过", "Green"), opt("不通过", "Red"), opt("已触发下游", "Blue")]
REFERENCE_OPERATION_OPTIONS = [opt("不触发", "Gray"), opt("重新生成参考图", "Orange")]
KEYFRAME_OPERATION_OPTIONS = [opt("不触发", "Gray"), opt("重新生成关键帧图", "Orange")]
VIDEO_OPERATION_OPTIONS = [opt("不触发", "Gray"), opt("重新生成视频片段", "Orange")]
ASSET_TYPE_OPTIONS = [opt("human"), opt("pet"), opt("environment"), opt("object")]
KEYFRAME_TYPE_OPTIONS = [
    opt("S01_FIRST"),
    opt("S01_TAIL_SHARED_S02_FIRST"),
    opt("S02_TAIL"),
]
VIDEO_CLIP_OPTIONS = [opt("S01"), opt("S02")]
YES_NO_OPTIONS = [opt("否", "Gray"), opt("是", "Green")]
VIDEO_CHANNEL_OPTIONS = [opt("OTU", "Green")]
VIDEO_MODEL_OPTIONS = [opt("默认（配置表）", "Gray"), opt("OTU / veo_3_1-fast-fl", "Green")]


MULTI_ROLE_FIRST_LAST_FIELDS = [
    text("任务名称"),
    select("记录类型", RECORD_TYPE_OPTIONS),
    select("记录状态", RECORD_STATE_OPTIONS),
    text("父任务记录ID"),
    text("批次ID"),
    text("输入脚本"),
    link("关联产品记录", "__PRODUCT_TABLE_ID__"),
    text("产品名称"),
    number("目标时长秒"),
    select("拆解状态", RUN_STATUS_OPTIONS),
    text("拆解结果JSON"),
    number("总角色数"),
    number("总关键帧数"),
    number("总视频片段数"),
    text("角色机制JSON"),
    text("错误信息"),
    text("失败分类"),
    datetime_field("生成时间"),
    text("资产ID"),
    select("参考类型", ASSET_TYPE_OPTIONS),
    text("参考名称"),
    text("来源角色ID列表"),
    text("参考提示词"),
    select("参考图操作", REFERENCE_OPERATION_OPTIONS),
    number("参考图版本"),
    select("参考图生成状态", RUN_STATUS_OPTIONS),
    attachment("参考图"),
    text("参考图file_token"),
    text("参考图本地路径"),
    text("参考图任务ID"),
    text("参考图原始响应JSON"),
    select("参考图审核状态", REVIEW_STATUS_OPTIONS),
    text("参考图修改要求"),
    text("参考图错误信息"),
    datetime_field("参考图生成时间"),
    select("关键帧类型", KEYFRAME_TYPE_OPTIONS),
    text("关键帧标题"),
    text("关键帧提示词"),
    select("需要产品参考图", YES_NO_OPTIONS),
    text("参考资产ID列表"),
    text("画面出场角色ID列表"),
    text("依赖关键帧类型"),
    text("依赖关键帧记录ID"),
    text("依赖关键帧file_token"),
    text("参考图选择原因"),
    text("参考图清单JSON"),
    text("原始请求JSON"),
    select("关键帧操作", KEYFRAME_OPERATION_OPTIONS),
    number("关键帧版本"),
    select("关键帧生成状态", RUN_STATUS_OPTIONS),
    attachment("关键帧图"),
    text("关键帧图file_token"),
    text("关键帧图本地路径"),
    text("关键帧任务ID"),
    text("关键帧原始响应JSON"),
    select("关键帧审核状态", REVIEW_STATUS_OPTIONS),
    text("关键帧审核备注"),
    text("关键帧错误信息"),
    datetime_field("关键帧生成时间"),
    select("视频片段类型", VIDEO_CLIP_OPTIONS),
    text("首关键帧类型"),
    text("尾关键帧类型"),
    text("首关键帧file_token"),
    text("尾关键帧file_token"),
    text("视频提示词"),
    select("视频操作", VIDEO_OPERATION_OPTIONS),
    number("视频版本"),
    select("视频通道", VIDEO_CHANNEL_OPTIONS),
    select("视频生成模型", VIDEO_MODEL_OPTIONS),
    select("视频生成状态", RUN_STATUS_OPTIONS),
    attachment("视频片段"),
    text("视频任务ID"),
    text("视频本地路径"),
    text("视频片段URL", url=True),
    text("视频片段file_token"),
    text("视频原始响应JSON"),
    text("视频错误信息"),
    datetime_field("视频生成时间"),
    text("历史生成记录JSON"),
]


TABLE_DEFINITION = {
    "key": "multi_role_first_last",
    "name": TABLE_NAME,
    "fields": MULTI_ROLE_FIRST_LAST_FIELDS,
    "views": {
        "01-用户入口": [
            "任务名称", "输入脚本", "关联产品记录", "目标时长秒", "拆解状态",
            "总角色数", "总关键帧数", "总视频片段数", "错误信息",
        ],
        "02-参考图确认": [
            "任务名称", "记录状态", "父任务记录ID", "资产ID", "参考类型", "参考名称",
            "来源角色ID列表", "参考提示词", "参考图操作", "参考图版本", "参考图生成状态",
            "参考图", "参考图审核状态", "参考图修改要求", "参考图错误信息",
        ],
        "03-关键帧审核": [
            "任务名称", "记录状态", "父任务记录ID", "关键帧类型", "关键帧标题",
            "关键帧提示词", "需要产品参考图", "参考资产ID列表", "依赖关键帧类型",
            "参考图选择原因", "参考图清单JSON", "关键帧操作", "关键帧版本",
            "关键帧生成状态", "关键帧图", "关键帧审核状态", "关键帧错误信息",
        ],
        "04-视频结果": [
            "任务名称", "记录状态", "父任务记录ID", "视频片段类型", "首关键帧类型",
            "尾关键帧类型", "视频提示词", "视频操作", "视频版本", "视频生成状态",
            "视频片段", "视频片段URL", "视频错误信息",
        ],
        "99-排错": [
            "任务名称", "记录类型", "记录状态", "父任务记录ID", "批次ID", "拆解结果JSON",
            "角色机制JSON", "参考图清单JSON", "原始请求JSON", "参考图任务ID", "关键帧任务ID",
            "视频任务ID", "参考图原始响应JSON", "关键帧原始响应JSON", "视频原始响应JSON",
            "错误信息", "失败分类", "历史生成记录JSON",
        ],
    },
}


def resolve_fields(config):
    return resolve_common_fields(config, MULTI_ROLE_FIRST_LAST_FIELDS)


def main():
    parser = argparse.ArgumentParser(description="Create multi-role first/last frame table")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATHS[0]))
    parser.add_argument("--update-config", action="store_true")
    args = parser.parse_args()
    config_path = Path(args.config)
    config = load_config(config_path)
    base_token = config["feishu"]["bitable_app_token"]
    fields = resolve_fields(config)
    tables = list_tables(base_token)
    table_id = ((config.get("feishu") or {}).get("tables") or {}).get("multi_role_first_last", "") or tables.get(TABLE_NAME, "")
    created_table = False
    if not table_id:
        table_id = create_table(base_token, TABLE_NAME, fields)
        created_table = True
    if not table_id:
        raise RuntimeError(f"创建表失败：{TABLE_NAME} 未返回 table_id")
    created_fields = create_missing_fields(base_token, table_id, fields)
    view_result = create_or_update_views(base_token, table_id, TABLE_DEFINITION["views"])
    if args.update_config:
        for path in DEFAULT_CONFIG_PATHS:
            if path.exists():
                update_config(path, {"multi_role_first_last": table_id})
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
