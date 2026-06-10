#!/usr/bin/env python3
"""
创建脚本文档逐分镜链路的三张表：
- 脚本文档-任务表
- 脚本文档-参考资产表
- 脚本文档-分镜生产表

用法:
  python3 tk_create_script_doc_shots_table.py --update-config
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from ai_model_catalog import (
    AI_CAPABILITY_OPTIONS,
    AI_MODEL_OPTIONS,
    AI_PROVIDER_OPTIONS,
    AI_TASK_TYPE_OPTIONS,
    IMAGE_MODEL_OPTIONS,
    FIRST_LAST_VIDEO_MODEL_OPTIONS,
    FIRST_LAST_VIDEO_MODEL_WITH_DEFAULT_OPTIONS,
    TEXT_MODEL_OPTIONS,
)

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATHS = [
    SCRIPT_DIR / "config.json",
    SCRIPT_DIR / "config.ryan.json",
]
TASK_TABLE_NAME = "脚本文档-任务表"
ASSET_TABLE_NAME = "脚本文档-参考资产表"
SHOT_TABLE_NAME = "脚本文档-分镜生产表"
UNIFIED_TABLE_NAME = "003-脚本文档生产表"


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
PARSE_STATUS_OPTIONS = [opt("待解析"), opt("解析中", "Orange"), opt("成功", "Green"), opt("失败", "Red")]
REVIEW_STATUS_OPTIONS = [opt("待确认", "Gray"), opt("通过", "Green"), opt("不通过", "Red")]
VIDEO_CHANNEL_OPTIONS = [opt("OTU", "Green"), opt("AIHubMix")]
END_FRAME_MODE_OPTIONS = [opt("不启用", "Gray"), opt("启用", "Green")]
YES_NO_OPTIONS = [opt("否", "Gray"), opt("是", "Green")]
RECORD_TYPE_OPTIONS = [opt("文档任务", "Purple"), opt("参考资产", "Blue"), opt("分镜", "Green")]
RECORD_STATE_OPTIONS = [opt("有效", "Green"), opt("已废弃", "Red")]
UNIFIED_OMITTED_FIELDS = {
    "口播音频状态",
    "口播音频",
    "口播音频时长秒",
    "口播音频路径",
    "口播音频下载链接",
    "口播音频FileToken",
    "口播音频错误信息",
}
UNIFIED_REMOVED_FIELDS = UNIFIED_OMITTED_FIELDS | {
    "记录状态",
    "旧表来源",
    "旧记录ID",
    "脚本文档标题",
    "脚本文档正文",
    "脚本文档链接",
    "产品名",
    "关联产品",
    "选择产品",
    "口播音色ID",
    "口播文本",
    "AI供应商",
    "AI能力类型",
    "AI任务类型",
    "AI模型",
    "AI参数JSON",
    "视频AI模型",
    "解析结果JSON",
    "解析后逐镜头脚本",
    "参考图file_token",
    "参考图本地路径",
    "参考图原始响应JSON",
    "分镜原文",
    "人物描述",
    "场景描述",
    "产品焦点",
    "连续性要求",
    "文本",
    "提示词",
    "参考图选择原因",
    "分镜图本地路径",
    "分镜图file_token",
    "分镜图原始响应JSON",
    "分镜图生成时间",
    "尾帧图提示词",
    "尾帧图本地路径",
    "尾帧图file_token",
    "尾帧图原始响应JSON",
    "尾帧图生成时间",
    "本地视频路径",
    "分镜视频file_token",
    "视频生成原始响应JSON",
    "视频生成时间",
    "生成时间",
    "发布平台",
}
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


TASK_FIELDS = [
    text("任务名称"),
    text("批次ID"),
    text("脚本文档标题"),
    text("脚本文档正文"),
    text("脚本文档链接", url=True),
    attachment("脚本文档附件"),
    text("产品名"),
    text("关联产品"),
    {"name": "关联产品记录", "type": "link", "link_table": "__PRODUCT_TABLE_ID__", "bidirectional": False},
    text("选择产品"),
    text("分镜风格"),
    text("视频时长"),
    text("口播音色ID"),
    select("使用统一AI路由", YES_NO_OPTIONS),
    select("解析AI模型", TEXT_MODEL_OPTIONS),
    text("解析AI参数JSON"),
    select("分镜图AI模型", IMAGE_MODEL_OPTIONS),
    text("分镜图AI参数JSON"),
    select("分镜图画面尺寸", IMAGE_SIZE_OPTIONS),
    select("分镜图画面比例", IMAGE_ASPECT_RATIO_OPTIONS),
    select("尾帧图AI模型", IMAGE_MODEL_OPTIONS),
    text("尾帧图AI参数JSON"),
    select("尾帧图画面尺寸", IMAGE_SIZE_OPTIONS),
    select("尾帧图画面比例", IMAGE_ASPECT_RATIO_OPTIONS),
    select("视频AI模型", FIRST_LAST_VIDEO_MODEL_OPTIONS),
    text("视频AI参数JSON"),
    select("视频生成模型", FIRST_LAST_VIDEO_MODEL_WITH_DEFAULT_OPTIONS),
    select("视频画面尺寸", VIDEO_SIZE_OPTIONS),
    select("视频画面比例", VIDEO_ASPECT_RATIO_OPTIONS),
    select("AI供应商", AI_PROVIDER_OPTIONS),
    select("AI能力类型", AI_CAPABILITY_OPTIONS),
    select("AI任务类型", AI_TASK_TYPE_OPTIONS),
    select("AI模型", AI_MODEL_OPTIONS),
    text("AI参数JSON"),
    select("解析状态", PARSE_STATUS_OPTIONS),
    text("解析结果JSON"),
    text("解析后逐镜头脚本"),
    number("总分镜数"),
    text("解析错误信息"),
]

ASSET_FIELDS = [
    text("参考名称"),
    link("关联任务", "__TASK_TABLE_ID__"),
    text("父文档记录ID"),
    text("资产ID"),
    select("参考类型", [opt("pet"), opt("environment"), opt("human")]),
    text("参考提示词"),
    select("参考图AI模型", IMAGE_MODEL_OPTIONS),
    text("参考图AI参数JSON"),
    select("参考图画面尺寸", IMAGE_SIZE_OPTIONS),
    select("参考图画面比例", IMAGE_ASPECT_RATIO_OPTIONS),
    select("参考图生成状态", RUN_STATUS_OPTIONS),
    attachment("参考图"),
    text("参考图file_token"),
    text("参考图本地路径"),
    text("参考图任务ID"),
    text("参考图原始响应JSON"),
    select("参考图审核状态", REVIEW_STATUS_OPTIONS),
    text("参考图修改要求"),
    text("错误信息"),
]

SHOT_FIELDS = [
    text("任务名称"),
    link("关联任务", "__TASK_TABLE_ID__"),
    text("父文档记录ID"),
    text("批次ID"),
    number("分镜序号"),
    number("总分镜数"),
    text("分镜原文"),
    text("口播文本"),
    text("口播音色ID"),
    select("口播音频状态", RUN_STATUS_OPTIONS),
    attachment("口播音频"),
    number("口播音频时长秒", precision=3),
    text("口播音频路径"),
    text("口播音频下载链接", url=True),
    text("口播音频FileToken"),
    text("口播音频错误信息"),
    number("目标时长秒", precision=1),
    text("画面描述"),
    text("人物描述"),
    text("场景描述"),
    text("产品焦点"),
    text("连续性要求"),
    text("结构化分镜JSON"),
    text("文本"),
    text("图片提示词"),
    text("提示词"),
    text("视频提示词"),
    select("使用统一AI路由", YES_NO_OPTIONS),
    select("分镜图AI模型", IMAGE_MODEL_OPTIONS),
    text("分镜图AI参数JSON"),
    select("分镜图画面尺寸", IMAGE_SIZE_OPTIONS),
    select("分镜图画面比例", IMAGE_ASPECT_RATIO_OPTIONS),
    select("尾帧图AI模型", IMAGE_MODEL_OPTIONS),
    text("尾帧图AI参数JSON"),
    select("尾帧图画面尺寸", IMAGE_SIZE_OPTIONS),
    select("尾帧图画面比例", IMAGE_ASPECT_RATIO_OPTIONS),
    select("视频AI模型", FIRST_LAST_VIDEO_MODEL_OPTIONS),
    text("视频AI参数JSON"),
    select("视频画面尺寸", VIDEO_SIZE_OPTIONS),
    select("视频画面比例", VIDEO_ASPECT_RATIO_OPTIONS),
    select("AI供应商", AI_PROVIDER_OPTIONS),
    select("AI能力类型", AI_CAPABILITY_OPTIONS),
    select("AI任务类型", AI_TASK_TYPE_OPTIONS),
    select("AI模型", AI_MODEL_OPTIONS),
    text("AI参数JSON"),
    select("需要产品参考图", [opt("否", "Gray"), opt("是", "Green")]),
    text("参考资产ID列表"),
    text("参考图选择原因"),
    select("分镜图生成状态", RUN_STATUS_OPTIONS),
    attachment("分镜图"),
    text("分镜图本地路径"),
    text("分镜图file_token"),
    text("分镜图任务ID"),
    text("分镜图原始响应JSON"),
    text("分镜图错误信息"),
    datetime_field("分镜图生成时间"),
    select("首尾帧视频模式", END_FRAME_MODE_OPTIONS),
    text("尾帧画面描述"),
    text("尾帧图提示词"),
    select("尾帧图生成状态", RUN_STATUS_OPTIONS),
    attachment("尾帧图"),
    text("尾帧图本地路径"),
    text("尾帧图file_token"),
    text("尾帧图任务ID"),
    text("尾帧图原始响应JSON"),
    text("尾帧图错误信息"),
    datetime_field("尾帧图生成时间"),
    select("视频通道", VIDEO_CHANNEL_OPTIONS),
    select("视频生成模型", FIRST_LAST_VIDEO_MODEL_WITH_DEFAULT_OPTIONS),
    select("视频生成状态", RUN_STATUS_OPTIONS),
    attachment("分镜视频"),
    text("视频任务ID"),
    text("本地视频路径"),
    text("分镜视频URL", url=True),
    text("分镜视频file_token"),
    text("视频生成原始响应JSON"),
    text("视频错误信息"),
    datetime_field("视频生成时间"),
    text("发布视频标题"),
    text("发布视频标签"),
    text("发布文案"),
    text("发布平台"),
    select("发布状态", [opt("未发布", "Gray"), opt("待发布"), opt("已发布", "Green"), opt("失败", "Red")]),
    text("错误信息"),
    text("失败分类"),
    datetime_field("生成时间"),
]

TABLE_DEFINITIONS = [
    {
        "key": "script_doc_tasks",
        "name": TASK_TABLE_NAME,
        "fields": TASK_FIELDS,
        "views": {
            "01-用户入口": ["任务名称", "脚本文档标题", "脚本文档正文", "关联产品记录", "分镜风格", "视频时长", "口播音色ID", "解析AI模型", "解析AI参数JSON", "解析状态", "总分镜数", "批次ID"],
            "高级AI参数": ["任务名称", "使用统一AI路由", "解析AI模型", "解析AI参数JSON", "分镜图AI模型", "分镜图AI参数JSON", "分镜图画面尺寸", "分镜图画面比例", "尾帧图AI模型", "尾帧图AI参数JSON", "尾帧图画面尺寸", "尾帧图画面比例", "视频生成模型", "视频画面尺寸", "视频画面比例", "解析状态"],
            "99-解析排错": ["任务名称", "解析状态", "解析错误信息", "解析结果JSON", "解析后逐镜头脚本", "批次ID", "使用统一AI路由", "解析AI模型", "解析AI参数JSON", "分镜图AI模型", "分镜图AI参数JSON", "分镜图画面尺寸", "分镜图画面比例", "尾帧图AI模型", "尾帧图AI参数JSON", "尾帧图画面尺寸", "尾帧图画面比例", "视频生成模型", "视频AI模型", "视频AI参数JSON", "视频画面尺寸", "视频画面比例", "AI供应商", "AI能力类型", "AI任务类型", "AI模型", "AI参数JSON"],
        },
    },
    {
        "key": "script_doc_reference_assets",
        "name": ASSET_TABLE_NAME,
        "fields": ASSET_FIELDS,
        "views": {
            "01-参考图确认": ["参考名称", "关联任务", "资产ID", "参考类型", "参考提示词", "参考图AI模型", "参考图生成状态", "参考图", "参考图审核状态", "参考图修改要求"],
            "99-参考图排错": ["参考名称", "关联任务", "资产ID", "参考图AI模型", "参考图AI参数JSON", "参考图画面尺寸", "参考图画面比例", "参考图生成状态", "错误信息", "参考图任务ID", "参考图原始响应JSON", "参考图file_token", "参考图本地路径"],
        },
    },
    {
        "key": "script_doc_shots",
        "name": SHOT_TABLE_NAME,
        "fields": SHOT_FIELDS,
        "views": {
            "01-分镜图生成": ["任务名称", "关联任务", "分镜序号", "画面描述", "图片提示词", "分镜图AI模型", "分镜图AI参数JSON", "分镜图画面尺寸", "分镜图画面比例", "需要产品参考图", "参考资产ID列表", "分镜图生成状态", "分镜图", "分镜图错误信息", "首尾帧视频模式", "尾帧画面描述", "尾帧图AI模型", "尾帧图AI参数JSON", "尾帧图画面尺寸", "尾帧图画面比例", "尾帧图生成状态", "尾帧图", "尾帧图错误信息"],
            "02-口播音频": ["任务名称", "关联任务", "分镜序号", "口播文本", "口播音频状态", "口播音频", "口播音频下载链接", "口播音频错误信息"],
            "03-分镜视频": ["任务名称", "关联任务", "分镜序号", "目标时长秒", "分镜图生成状态", "分镜图", "首尾帧视频模式", "尾帧画面描述", "尾帧图生成状态", "尾帧图", "尾帧图错误信息", "视频提示词", "视频通道", "视频生成模型", "视频画面尺寸", "视频画面比例", "视频生成状态", "分镜视频", "分镜视频URL", "视频错误信息", "视频任务ID", "本地视频路径", "分镜视频file_token", "视频生成时间"],
            "04-发布素材": ["任务名称", "关联任务", "分镜序号", "发布视频标题", "发布文案", "发布视频标签", "发布状态"],
            "高级AI参数": ["任务名称", "关联任务", "分镜序号", "使用统一AI路由", "分镜图AI模型", "分镜图AI参数JSON", "分镜图画面尺寸", "分镜图画面比例", "尾帧图AI模型", "尾帧图AI参数JSON", "尾帧图画面尺寸", "尾帧图画面比例", "视频通道", "视频生成模型", "视频画面尺寸", "视频画面比例", "视频生成状态"],
            "99-排错": ["任务名称", "关联任务", "分镜序号", "错误信息", "失败分类", "分镜图错误信息", "尾帧图错误信息", "口播音频错误信息", "视频错误信息", "结构化分镜JSON", "文本", "提示词", "尾帧图提示词", "分镜图任务ID", "分镜图原始响应JSON", "尾帧图任务ID", "尾帧图原始响应JSON", "视频生成原始响应JSON", "视频任务ID", "分镜图file_token", "尾帧图file_token", "分镜视频file_token", "口播音频FileToken", "分镜图本地路径", "尾帧图本地路径", "本地视频路径", "口播音频路径", "发布平台", "生成时间", "分镜图生成时间", "尾帧图生成时间", "视频生成时间", "使用统一AI路由", "分镜图AI模型", "分镜图AI参数JSON", "分镜图画面尺寸", "分镜图画面比例", "尾帧图AI模型", "尾帧图AI参数JSON", "尾帧图画面尺寸", "尾帧图画面比例", "视频生成模型", "视频AI模型", "视频AI参数JSON", "视频画面尺寸", "视频画面比例", "AI供应商", "AI能力类型", "AI任务类型", "AI模型", "AI参数JSON"],
        },
    },
]


def unified_field(field):
    item = dict(field)
    if item.get("link_table") == "__TASK_TABLE_ID__":
        item["link_table"] = "__UNIFIED_TABLE_ID__"
    return item


def merge_unified_fields():
    merged = [
        text("任务名称"),
        select("记录类型", RECORD_TYPE_OPTIONS),
    ]
    seen = {item["name"] for item in merged}
    for field in TASK_FIELDS + ASSET_FIELDS + SHOT_FIELDS:
        name = field["name"]
        if name == "脚本文档标题" and "脚本文档" not in seen:
            merged.append(text("脚本文档"))
            seen.add("脚本文档")
        if name in seen or name in UNIFIED_REMOVED_FIELDS:
            continue
        merged.append(unified_field(field))
        seen.add(name)
    return merged


UNIFIED_SCRIPT_DOC_FIELDS = merge_unified_fields()


def view_filter(record_type):
    return {"logic": "and", "conditions": [["记录类型", "is", [record_type]]]}


UNIFIED_TABLE_DEFINITION = {
    "key": "script_doc_unified",
    "name": UNIFIED_TABLE_NAME,
    "fields": UNIFIED_SCRIPT_DOC_FIELDS,
    "views": {
        "01-文档入口": {
            "visible_fields": ["任务名称", "脚本文档", "脚本文档附件", "关联产品记录", "视频时长", "解析状态", "总分镜数", "解析错误信息"],
            "filter": view_filter("文档任务"),
        },
        "02-参考图确认": {
            "visible_fields": ["任务名称", "参考名称", "参考类型", "参考提示词", "参考图AI模型", "参考图生成状态", "参考图", "参考图审核状态", "参考图修改要求", "错误信息"],
            "filter": view_filter("参考资产"),
        },
        "03-分镜图生成": {
            "visible_fields": ["任务名称", "分镜序号", "画面描述", "图片提示词", "分镜图AI模型", "分镜图生成状态", "分镜图", "首尾帧视频模式", "尾帧画面描述", "尾帧图生成状态", "尾帧图", "分镜图错误信息"],
            "filter": view_filter("分镜"),
        },
        "04-分镜视频": {
            "visible_fields": ["任务名称", "分镜序号", "目标时长秒", "分镜图", "尾帧图", "视频提示词", "视频通道", "视频生成模型", "视频生成状态", "分镜视频", "分镜视频URL", "视频错误信息"],
            "filter": view_filter("分镜"),
        },
        "05-发布素材": {
            "visible_fields": ["任务名称", "分镜序号", "发布视频标题", "发布文案", "发布视频标签", "发布状态"],
            "filter": view_filter("分镜"),
        },
        "高级AI参数": {
            "visible_fields": ["任务名称", "使用统一AI路由", "解析AI模型", "解析AI参数JSON", "参考图AI模型", "参考图AI参数JSON", "参考图画面尺寸", "参考图画面比例", "分镜图AI模型", "分镜图AI参数JSON", "分镜图画面尺寸", "分镜图画面比例", "尾帧图AI模型", "尾帧图AI参数JSON", "尾帧图画面尺寸", "尾帧图画面比例", "视频通道", "视频生成模型", "视频AI参数JSON", "视频画面尺寸", "视频画面比例"],
            "filter": {"conditions": []},
        },
        "99-排错全字段": {
            "visible_fields": [field["name"] for field in UNIFIED_SCRIPT_DOC_FIELDS],
            "filter": {"conditions": []},
        },
    },
}


def run_json(args):
    proc = subprocess.run(args, text=True, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "lark-cli command failed").strip())
    return json.loads(proc.stdout)


def load_base_token(config_path):
    data = json.loads(config_path.read_text(encoding="utf-8"))
    return data["feishu"]["bitable_app_token"]


def load_config(config_path):
    return json.loads(config_path.read_text(encoding="utf-8"))


def resolved_fields(config, fields, task_table_id=""):
    product_table = (config.get("feishu") or {}).get("tables", {}).get("product", "")
    resolved = []
    for field in fields:
        item = dict(field)
        if item.get("link_table") == "__PRODUCT_TABLE_ID__":
            if not product_table:
                continue
            item["link_table"] = product_table
        if item.get("link_table") == "__TASK_TABLE_ID__":
            if not task_table_id:
                continue
            item["link_table"] = task_table_id
        if item.get("link_table") == "__UNIFIED_TABLE_ID__":
            if not task_table_id:
                continue
            item["link_table"] = task_table_id
        resolved.append(item)
    return resolved


def list_tables(base_token):
    data = run_json(["lark-cli", "base", "+table-list", "--base-token", base_token, "--limit", "100"])
    raw = data.get("data", {})
    items = raw.get("items") or raw.get("tables") or []
    return {item.get("name") or item.get("table_name"): item.get("id") or item.get("table_id") for item in items}


def list_fields(base_token, table_id):
    data = run_json(["lark-cli", "base", "+field-list", "--base-token", base_token, "--table-id", table_id, "--limit", "200"])
    raw = data.get("data", {})
    items = raw.get("items") or raw.get("fields") or []
    names = set()
    for item in items:
        name = item.get("name") or item.get("field_name")
        if name:
            names.add(name)
    return names


def create_table(base_token, table_name, fields):
    data = run_json([
        "lark-cli", "base", "+table-create",
        "--base-token", base_token,
        "--name", table_name,
        "--fields", json.dumps(fields[:20], ensure_ascii=False),
    ])
    table = (data.get("data") or {}).get("table") or {}
    return table.get("id") or table.get("table_id")


def create_missing_fields(base_token, table_id, fields):
    existing = list_fields(base_token, table_id)
    created = 0
    for field in fields:
        if field["name"] in existing:
            continue
        run_json([
            "lark-cli", "base", "+field-create",
            "--base-token", base_token,
            "--table-id", table_id,
            "--json", json.dumps(field, ensure_ascii=False),
        ])
        created += 1
    return created


def list_views(base_token, table_id):
    data = run_json(["lark-cli", "base", "+view-list", "--base-token", base_token, "--table-id", table_id, "--limit", "100"])
    raw = data.get("data", {})
    items = raw.get("items") or raw.get("views") or []
    return {item.get("name"): item.get("id") or item.get("view_id") for item in items}


def create_or_update_views(base_token, table_id, view_definitions):
    existing = list_views(base_token, table_id)
    created = 0
    updated = 0
    for name, definition in view_definitions.items():
        if isinstance(definition, dict):
            visible_fields = definition.get("visible_fields", [])
            view_filter_definition = definition.get("filter")
        else:
            visible_fields = definition
            view_filter_definition = None
        view_id = existing.get(name)
        if not view_id:
            data = run_json([
                "lark-cli", "base", "+view-create",
                "--base-token", base_token,
                "--table-id", table_id,
                "--json", json.dumps({"name": name, "type": "grid"}, ensure_ascii=False),
            ])
            view = (data.get("data") or {}).get("view") or {}
            view_id = view.get("id") or view.get("view_id")
            if not view_id:
                view_id = list_views(base_token, table_id).get(name)
            created += 1
        if view_id and visible_fields is not None:
            for attempt in range(4):
                try:
                    run_json([
                        "lark-cli", "base", "+view-set-visible-fields",
                        "--base-token", base_token,
                        "--table-id", table_id,
                        "--view-id", view_id,
                        "--json", json.dumps({"visible_fields": visible_fields}, ensure_ascii=False),
                    ])
                    break
                except RuntimeError as exc:
                    if "800070003" in str(exc) or "no operation produced" in str(exc):
                        break
                    if '"code": 2200' in str(exc) or '"code":2200' in str(exc):
                        print(f"WARNING: skip visible fields for view {name}: {exc}", file=sys.stderr)
                        break
                    if "800004135" not in str(exc) or attempt == 3:
                        raise
                    time.sleep(2 + attempt * 2)
            if view_filter_definition is not None:
                run_json([
                    "lark-cli", "base", "+view-set-filter",
                    "--base-token", base_token,
                    "--table-id", table_id,
                    "--view-id", view_id,
                    "--json", json.dumps(view_filter_definition, ensure_ascii=False),
                ])
            updated += 1
    return {"created": created, "updated": updated}


def update_config(config_path, table_ids):
    data = json.loads(config_path.read_text(encoding="utf-8"))
    tables = data.setdefault("feishu", {}).setdefault("tables", {})
    tables.update(table_ids)
    config_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def ensure_unified_table(config, base_token, tables, *, update_config_files=False):
    configured_tables = (config.get("feishu") or {}).get("tables") or {}
    table_id = configured_tables.get("script_doc_unified") or tables.get(UNIFIED_TABLE_NAME)
    fields = resolved_fields(config, UNIFIED_SCRIPT_DOC_FIELDS, task_table_id=table_id or "")
    created_table = False
    if not table_id:
        table_id = create_table(base_token, UNIFIED_TABLE_NAME, fields)
        created_table = True
    if not table_id:
        raise RuntimeError(f"创建表失败：{UNIFIED_TABLE_NAME} 未返回 table_id")
    fields = resolved_fields(config, UNIFIED_SCRIPT_DOC_FIELDS, task_table_id=table_id)
    created_fields = create_missing_fields(base_token, table_id, fields)
    view_result = create_or_update_views(base_token, table_id, UNIFIED_TABLE_DEFINITION["views"])
    if update_config_files:
        for path in DEFAULT_CONFIG_PATHS:
            if path.exists():
                update_config(path, {"script_doc_unified": table_id})
    return {
        "table_name": UNIFIED_TABLE_NAME,
        "table_id": table_id,
        "created_table": created_table,
        "created_fields": created_fields,
        "views": view_result,
    }


def main():
    parser = argparse.ArgumentParser(description="Create script doc shots table")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATHS[0]))
    parser.add_argument("--update-config", action="store_true")
    parser.add_argument("--unified", action="store_true", help="只创建/更新 003-脚本文档生产表，不改旧三表")
    args = parser.parse_args()

    config_path = Path(args.config)
    config = load_config(config_path)
    base_token = config["feishu"]["bitable_app_token"]
    tables = list_tables(base_token)
    if args.unified:
        result = ensure_unified_table(config, base_token, tables, update_config_files=args.update_config)
        print(json.dumps({
            "tables": [result],
            "config_updated": bool(args.update_config),
        }, ensure_ascii=False, indent=2))
        return

    configured_tables = (config.get("feishu") or {}).get("tables") or {}
    table_ids = {}
    results = []
    task_table_id = configured_tables.get("script_doc_tasks") or tables.get(TASK_TABLE_NAME)
    for definition in TABLE_DEFINITIONS:
        table_id = configured_tables.get(definition["key"]) or tables.get(definition["name"])
        fields = resolved_fields(config, definition["fields"], task_table_id=task_table_id or "")
        created_table = False
        if not table_id:
            table_id = create_table(base_token, definition["name"], fields)
            created_table = True
        if not table_id:
            raise RuntimeError(f"创建表失败：{definition['name']} 未返回 table_id")
        if definition["key"] == "script_doc_tasks":
            task_table_id = table_id
        fields = resolved_fields(config, definition["fields"], task_table_id=task_table_id)
        created_fields = create_missing_fields(base_token, table_id, fields)
        view_result = create_or_update_views(base_token, table_id, definition["views"])
        table_ids[definition["key"]] = table_id
        results.append({
            "table_name": definition["name"],
            "table_id": table_id,
            "created_table": created_table,
            "created_fields": created_fields,
            "views": view_result,
        })
    if args.update_config:
        for path in DEFAULT_CONFIG_PATHS:
            if path.exists():
                update_config(path, table_ids)
    print(json.dumps({
        "tables": results,
        "config_updated": bool(args.update_config),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
