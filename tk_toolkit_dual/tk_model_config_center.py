#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
import argparse
import json
import os
import subprocess
import datetime as dt
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import ai_model_catalog
from common import (
    APP_TOKEN,
    TABLE_CONFIG,
    TABLE_FIRST_LAST_VIDEO,
    TABLE_MULTI_ROLE_FIRST_LAST,
    TABLE_NINE_GRID_VIDEO,
    TABLE_PROMPT_IMAGE_VIDEO,
    TABLE_SCRIPT_DOC_REFERENCE_ASSETS,
    TABLE_SCRIPT_DOC_SHOTS,
    TABLE_VIDEO_EDIT,
    extract_text,
    feishu_headers,
    get_feishu_token,
    safe_list_records,
    safe_request,
    safe_update_record,
)


MODEL_CATALOG_VIEW_NAME = "03-模型目录"

CONFIG_TYPE_FIELD = "配置类型"
CONFIG_TYPE_RUNTIME_STAGE = "运行环节"
CONFIG_TYPE_TASK_DEFAULT = "任务默认"
CONFIG_TYPE_MODEL_CATALOG = "模型目录"
TASK_STAGE_FIELD = "任务环节"
DEFAULT_SLOT_FIELD = "默认槽位"
SOURCE_MODE_FIELD = "生效来源"
SOURCE_MODE_ONLINE = "线上配置"
SOURCE_MODE_CODE = "代码默认"
PROVIDER_FIELD = "供应商"
CAPABILITY_FIELD = "能力类型"
DISPLAY_NAME_FIELD = "显示名称"

MODEL_CATALOG_VIEWS = {
    "01-生产可用模型": {"logic": "and", "conditions": [["是否生产可用", "intersects", ["是"]]]},
    "02-待测试模型": {"logic": "and", "conditions": [["测试状态", "intersects", ["未测试"]]]},
    "03-测试失败": {"logic": "and", "conditions": [["测试状态", "intersects", ["测试失败"]]]},
    "90-停用归档": {"logic": "or", "conditions": [["接入状态", "intersects", ["停用"]], ["是否生产可用", "intersects", ["否"]]]},
    "99-排错全字段": {"conditions": []},
}

TASK_DEFAULT_VIEWS = {
    "01-运行默认配置": {"logic": "and", "conditions": [["状态", "intersects", ["启用"]]]},
    "02-提示词配置": {"logic": "and", "conditions": [["系统提示词", "non_empty"]]},
    "90-归档旧配置": {"logic": "and", "conditions": [["状态", "intersects", ["停用"]]]},
    "99-排错全字段": {"conditions": []},
}

MODEL_CATALOG_VIEW_FIELDS = {
    "01-生产可用模型": ["供应商", "能力类型", "显示名称", "模型名称", "调用方式", "API代理地址", "默认参数JSON", "测试状态", "最后测试时间", "测试结果摘要", "备注"],
    "02-待测试模型": ["供应商", "能力类型", "显示名称", "模型名称", "调用方式", "API代理地址", "默认参数JSON", "接入状态", "测试状态", "备注"],
    "03-测试失败": ["供应商", "能力类型", "显示名称", "模型名称", "调用方式", "测试状态", "测试结果摘要", "备注"],
    "90-停用归档": ["供应商", "能力类型", "显示名称", "模型名称", "接入状态", "测试状态", "是否生产可用", "备注"],
}

TASK_DEFAULT_VIEW_FIELDS = {
    "01-运行默认配置": ["应用表格", "环节", "默认供应商", "默认模型", "默认模型显示名称", "画面尺寸", "画面比例", "AI参数JSON", "状态", "备注"],
    "02-提示词配置": ["应用表格", "环节", "默认供应商", "默认模型", "系统提示词", "状态", "备注"],
    "90-归档旧配置": ["应用表格", "环节", "默认供应商", "默认模型显示名称", "状态", "备注"],
}

BACKUP_PATH = Path("docs/tk-pipeline/model-config-center-migration-backup-2026-06-02.json")

PRODUCTION_RUNTIME_STATUSES = {"启用", "测试中", ""}

TEXT_STAGES = {
    "脚本文档结构化拆分-Gemini",
    "多角色首尾帧解析-Gemini",
    "多图九宫格方案生成",
}
IMAGE_STAGES = {
    "图片生成-OTU",
    "多图九宫格图片生成",
}
VIDEO_STAGES = {
    "分镜视频生成-Veo",
    "分镜视频生成-OTU",
    "多图九宫格视频生成",
}
VIDEO_EDIT_STAGES = {"视频编辑-HappyHorse"}
VOICE_STAGES = {"语音合成-MiniMax"}
VIDEO_EDIT_SOURCE_CONFIG_STAGE = "视频编辑-HappyHorse"

TASK_TABLES = {
    "multi_role_first_last": "001-多角色首尾帧生成表",
    "first_last_video": "002-首尾帧视频生成表",
    "script_doc_tasks": "003-1脚本文档-任务表",
    "script_doc_reference_assets": "003-2脚本文档-参考资产表",
    "script_doc_shots": "003-3脚本文档-分镜生产表",
    "nine_grid_video": "005-多图九宫格视频生成表",
    "video_edit": "006-视频编辑任务表",
    "prompt_image_video": "008-图生视频生成表",
}


@dataclass(frozen=True)
class RuntimeDefaultSpec:
    table_key: str
    stage: str
    source_config_stage: str
    slot_name: str = ""


RUNTIME_DEFAULT_SPECS: Tuple[RuntimeDefaultSpec, ...] = (
    RuntimeDefaultSpec("multi_role_first_last", "多角色解析默认", "多角色首尾帧解析-Gemini"),
    RuntimeDefaultSpec("multi_role_first_last", "参考图生成默认", "图片生成-OTU", "参考图"),
    RuntimeDefaultSpec("multi_role_first_last", "关键帧生成默认", "图片生成-OTU", "关键帧"),
    RuntimeDefaultSpec("multi_role_first_last", "视频片段生成默认", "分镜视频生成-OTU", "视频"),
    RuntimeDefaultSpec("first_last_video", "首帧图生成默认", "图片生成-OTU", "首帧图"),
    RuntimeDefaultSpec("first_last_video", "尾帧图生成默认", "图片生成-OTU", "尾帧图"),
    RuntimeDefaultSpec("first_last_video", "首尾帧视频生成默认", "分镜视频生成-OTU", "视频"),
    RuntimeDefaultSpec("script_doc_tasks", "脚本文档结构化拆分默认", "脚本文档结构化拆分-Gemini"),
    RuntimeDefaultSpec("script_doc_reference_assets", "参考底图生成默认", "图片生成-OTU", "参考图"),
    RuntimeDefaultSpec("script_doc_shots", "分镜图生成默认", "图片生成-OTU", "分镜图"),
    RuntimeDefaultSpec("script_doc_shots", "尾帧图生成默认", "图片生成-OTU", "尾帧图"),
    RuntimeDefaultSpec("script_doc_shots", "口播音频生成默认", "语音合成-MiniMax", "口播音频"),
    RuntimeDefaultSpec("script_doc_shots", "分镜视频生成默认", "分镜视频生成-Veo", "视频"),
    RuntimeDefaultSpec("nine_grid_video", "九宫格方案生成默认", "多图九宫格方案生成"),
    RuntimeDefaultSpec("nine_grid_video", "参考图生成默认", "多图九宫格图片生成", "参考图"),
    RuntimeDefaultSpec("nine_grid_video", "九宫格图片生成默认", "多图九宫格图片生成", "图片"),
    RuntimeDefaultSpec("nine_grid_video", "九宫格视频生成默认", "多图九宫格视频生成", "视频"),
    RuntimeDefaultSpec("video_edit", "视频编辑默认", VIDEO_EDIT_SOURCE_CONFIG_STAGE, "视频编辑"),
    RuntimeDefaultSpec("prompt_image_video", "图片生成默认", "图片生成-OTU", "图片"),
    RuntimeDefaultSpec("prompt_image_video", "图生视频生成默认", "分镜视频生成-OTU", "视频"),
)


@dataclass(frozen=True)
class ConfigCenterPlan:
    model_catalog_rows: List[Dict[str, Any]]
    task_default_rows: List[Dict[str, Any]]
    legacy_archive_updates: List[Dict[str, Any]]
    validation_errors: List[str]


@dataclass(frozen=True)
class RuntimeDefaultBackfillSpec:
    table_key: str
    app_table: str
    stage: str
    status_field: str
    model_field: str = ""
    size_field: str = ""
    ratio_field: str = ""
    params_field: str = ""
    placeholder_values: Tuple[str, ...] = ()
    active_statuses: Tuple[str, ...] = ()


TABLE_IDS_BY_KEY: Dict[str, str] = {
    "multi_role_first_last": TABLE_MULTI_ROLE_FIRST_LAST,
    "first_last_video": TABLE_FIRST_LAST_VIDEO,
    "script_doc_reference_assets": TABLE_SCRIPT_DOC_REFERENCE_ASSETS,
    "script_doc_shots": TABLE_SCRIPT_DOC_SHOTS,
    "nine_grid_video": TABLE_NINE_GRID_VIDEO,
    "video_edit": TABLE_VIDEO_EDIT,
    "prompt_image_video": TABLE_PROMPT_IMAGE_VIDEO,
}


ACTIVE_BACKFILL_STATUSES = {"待生成", "生成中", "成功"}


RUNTIME_DEFAULT_BACKFILL_SPECS: Tuple[RuntimeDefaultBackfillSpec, ...] = (
    RuntimeDefaultBackfillSpec("multi_role_first_last", TASK_TABLES["multi_role_first_last"], "参考图生成默认", "参考图生成状态", "参考图AI模型", "参考图画面尺寸", "参考图画面比例", "参考图AI参数JSON"),
    RuntimeDefaultBackfillSpec("multi_role_first_last", TASK_TABLES["multi_role_first_last"], "关键帧生成默认", "关键帧生成状态", "关键帧AI模型", "关键帧画面尺寸", "关键帧画面比例", "关键帧AI参数JSON"),
    RuntimeDefaultBackfillSpec("multi_role_first_last", TASK_TABLES["multi_role_first_last"], "视频片段生成默认", "视频生成状态", "视频生成模型", "视频画面尺寸", "视频画面比例", "视频AI参数JSON"),
    RuntimeDefaultBackfillSpec("first_last_video", TASK_TABLES["first_last_video"], "首帧图生成默认", "首帧图生成状态", "首帧图AI模型", "首帧图画面尺寸", "首帧图画面比例", "首帧图AI参数JSON"),
    RuntimeDefaultBackfillSpec("first_last_video", TASK_TABLES["first_last_video"], "尾帧图生成默认", "尾帧图生成状态", "尾帧图AI模型", "尾帧图画面尺寸", "尾帧图画面比例", "尾帧图AI参数JSON"),
    RuntimeDefaultBackfillSpec("first_last_video", TASK_TABLES["first_last_video"], "首尾帧视频生成默认", "视频生成状态", "视频生成模型", "视频画面尺寸", "视频画面比例", "视频AI参数JSON"),
    RuntimeDefaultBackfillSpec("script_doc_reference_assets", TASK_TABLES["script_doc_reference_assets"], "参考底图生成默认", "参考图生成状态", "参考图AI模型", "参考图画面尺寸", "参考图画面比例", "参考图AI参数JSON"),
    RuntimeDefaultBackfillSpec("script_doc_shots", TASK_TABLES["script_doc_shots"], "分镜图生成默认", "分镜图生成状态", "分镜图AI模型", "分镜图画面尺寸", "分镜图画面比例", "分镜图AI参数JSON"),
    RuntimeDefaultBackfillSpec("script_doc_shots", TASK_TABLES["script_doc_shots"], "尾帧图生成默认", "尾帧图生成状态", "尾帧图AI模型", "尾帧图画面尺寸", "尾帧图画面比例", "尾帧图AI参数JSON"),
    RuntimeDefaultBackfillSpec("script_doc_shots", TASK_TABLES["script_doc_shots"], "分镜视频生成默认", "视频生成状态", "视频生成模型", "视频画面尺寸", "视频画面比例", "视频AI参数JSON"),
    RuntimeDefaultBackfillSpec("nine_grid_video", TASK_TABLES["nine_grid_video"], "参考图生成默认", "参考图生成状态", "参考图AI模型", "参考图画面尺寸", "参考图画面比例", "参考图AI参数JSON"),
    RuntimeDefaultBackfillSpec("nine_grid_video", TASK_TABLES["nine_grid_video"], "九宫格图片生成默认", "图片生成状态", "图片AI模型", "图片画面尺寸", "图片画面比例", "图片AI参数JSON"),
    RuntimeDefaultBackfillSpec("nine_grid_video", TASK_TABLES["nine_grid_video"], "九宫格视频生成默认", "视频生成状态", "视频生成模型", "视频画面尺寸", "视频画面比例", "视频AI参数JSON"),
    RuntimeDefaultBackfillSpec("video_edit", TASK_TABLES["video_edit"], "视频编辑默认", "编辑状态", "", "输出分辨率"),
    RuntimeDefaultBackfillSpec("prompt_image_video", TASK_TABLES["prompt_image_video"], "图片生成默认", "图片生成状态", "图片AI模型", "图片画面尺寸", "图片画面比例", "图片AI参数JSON", active_statuses=("", "不触发", "待生成", "生成中", "成功", "失败")),
    RuntimeDefaultBackfillSpec("prompt_image_video", TASK_TABLES["prompt_image_video"], "图生视频生成默认", "视频生成状态", "视频AI模型", "视频画面尺寸", "视频画面比例", "视频AI参数JSON", active_statuses=("", "不触发", "待生成", "生成中", "成功", "失败")),
)


def opt(name: str, hue: str = "Blue", lightness: str = "Lighter") -> Dict[str, str]:
    return {"name": name, "hue": hue, "lightness": lightness}


def text_field(name: str) -> Dict[str, Any]:
    return {"name": name, "type": "text"}


def select_field(name: str, options: Sequence[str], *, multiple: bool = False) -> Dict[str, Any]:
    return {"name": name, "type": "select", "multiple": multiple, "options": [opt(item) for item in options]}


def link_field(name: str, link_table: str) -> Dict[str, Any]:
    return {"name": name, "type": "link", "link_table": link_table, "bidirectional": False}


def model_catalog_fields() -> List[Dict[str, Any]]:
    return [
        select_field("供应商", ["AIHubMix", "Aitgenne", "OTU"]),
        select_field("能力类型", ["文本", "图片", "视频", "视频编辑", "语音"]),
        text_field("模型名称"),
        text_field("显示名称"),
        select_field("调用方式", [
            "Gemini 原生 SDK",
            "OpenAI兼容 chat/completions",
            "OpenAI兼容 /v1/images/generations",
            "OTU /v1/videos JSON image task",
            "OTU /v1/videos multipart",
            "Gemini native Veo",
            "happyhorse视频",
            "happyhorse视频编辑",
            "视频统一格式",
            "专用 API",
        ]),
        text_field("API代理地址"),
        text_field("默认参数JSON"),
        select_field("接入状态", ["已适配", "需开发适配器", "停用"]),
        select_field("测试状态", ["未测试", "测试通过", "测试失败", "停用"]),
        text_field("最后测试时间"),
        text_field("测试结果摘要"),
        select_field("是否生产可用", ["是", "否"]),
        text_field("备注"),
    ]


def task_default_fields(model_catalog_table_id: str) -> List[Dict[str, Any]]:
    return [
        select_field("应用表格", list(TASK_TABLES.values())),
        text_field("环节"),
        select_field("默认供应商", ["AIHubMix", "Aitgenne", "OTU"]),
        link_field("默认模型", model_catalog_table_id),
        text_field("默认模型显示名称"),
        select_field("画面尺寸", ["1024x1024", "720x1280", "1080x1920", "1280x720", "1440x2560", "2K", "4K"]),
        select_field("画面比例", ["9:16", "16:9", "1:1"]),
        text_field("AI参数JSON"),
        text_field("系统提示词"),
        select_field("状态", ["启用", "停用"]),
        text_field("备注"),
    ]


def run_json(argv: Sequence[str]) -> Dict[str, Any]:
    proc = subprocess.run(list(argv), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output = (proc.stdout or proc.stderr or "").strip()
    if proc.returncode != 0:
        raise RuntimeError(f"command failed rc={proc.returncode}: {' '.join(argv)}\n{output}")
    return json.loads(output) if output else {}


def list_tables(base_token: str) -> Dict[str, str]:
    data = run_json(["lark-cli", "base", "+table-list", "--base-token", base_token, "--limit", "100"])
    items = (data.get("data") or {}).get("tables") or (data.get("data") or {}).get("items") or []
    return {item.get("name") or item.get("table_name"): item.get("id") or item.get("table_id") for item in items}


def list_tables_api(token: str, *, base_token: str = APP_TOKEN) -> Dict[str, str]:
    result: Dict[str, str] = {}
    page_token = ""
    while True:
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{base_token}/tables?page_size=100"
        if page_token:
            url += f"&page_token={page_token}"
        data = safe_request("get", url, headers=feishu_headers(token), timeout=15, max_attempts=3)
        payload = data.get("data") or {}
        for item in payload.get("items") or []:
            name = item.get("name") or item.get("table_name")
            table_id = item.get("table_id") or item.get("id")
            if name and table_id:
                result[str(name)] = str(table_id)
        if not payload.get("has_more"):
            break
        page_token = str(payload.get("page_token") or "")
        if not page_token:
            break
    return result


def list_field_names_api(token: str, table_id: str, *, base_token: str = APP_TOKEN) -> set:
    result = set()
    page_token = ""
    while True:
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{base_token}/tables/{table_id}/fields?page_size=200"
        if page_token:
            url += f"&page_token={page_token}"
        data = safe_request("get", url, headers=feishu_headers(token), timeout=15, max_attempts=3)
        payload = data.get("data") or {}
        for item in payload.get("items") or []:
            name = item.get("field_name") or item.get("name")
            if name:
                result.add(str(name))
        if not payload.get("has_more"):
            break
        page_token = str(payload.get("page_token") or "")
        if not page_token:
            break
    return result


def create_table(base_token: str, table_name: str, fields: Sequence[Mapping[str, Any]]) -> str:
    data = run_json([
        "lark-cli", "base", "+table-create",
        "--base-token", base_token,
        "--name", table_name,
        "--fields", json.dumps(list(fields)[:20], ensure_ascii=False),
    ])
    table = (data.get("data") or {}).get("table") or {}
    table_id = table.get("id") or table.get("table_id")
    if not table_id:
        raise RuntimeError(f"创建表失败，未返回 table_id: {table_name}")
    return str(table_id)


def list_field_names(base_token: str, table_id: str) -> set:
    data = run_json(["lark-cli", "base", "+field-list", "--base-token", base_token, "--table-id", table_id, "--limit", "200"])
    fields = (data.get("data") or {}).get("fields") or (data.get("data") or {}).get("items") or []
    return {item.get("name") or item.get("field_name") for item in fields if item.get("name") or item.get("field_name")}


def create_missing_fields(base_token: str, table_id: str, fields: Sequence[Mapping[str, Any]], *, dry_run: bool) -> List[Dict[str, Any]]:
    existing = list_field_names(base_token, table_id)
    results = []
    for field in fields:
        name = str(field.get("name") or "")
        if name in existing:
            results.append({"field_name": name, "status": "exists"})
            continue
        if not dry_run:
            run_json([
                "lark-cli", "base", "+field-create",
                "--base-token", base_token,
                "--table-id", table_id,
                "--json", json.dumps(field, ensure_ascii=False),
            ])
        results.append({"field_name": name, "status": "dry_run" if dry_run else "created"})
    return results


def ensure_table(base_token: str, table_name: str, fields: Sequence[Mapping[str, Any]], *, dry_run: bool) -> Dict[str, Any]:
    table_id = list_tables(base_token).get(table_name)
    if table_id:
        field_results = create_missing_fields(base_token, table_id, fields, dry_run=dry_run)
        return {"table_name": table_name, "table_id": table_id, "created": False, "fields": field_results}
    if dry_run:
        return {"table_name": table_name, "table_id": f"dry-run:{table_name}", "created": True, "fields": [{"field_name": item["name"], "status": "dry_run"} for item in fields]}
    table_id = create_table(base_token, table_name, fields)
    field_results = create_missing_fields(base_token, table_id, fields, dry_run=False)
    return {"table_name": table_name, "table_id": table_id, "created": True, "fields": field_results}


def list_views(base_token: str, table_id: str) -> Dict[str, str]:
    data = run_json(["lark-cli", "base", "+view-list", "--base-token", base_token, "--table-id", table_id, "--limit", "100"])
    views = (data.get("data") or {}).get("views") or (data.get("data") or {}).get("items") or []
    return {item.get("name") or item.get("view_name"): item.get("id") or item.get("view_id") for item in views if item.get("name") or item.get("view_name")}


def all_field_names(fields: Sequence[Mapping[str, Any]]) -> List[str]:
    return [str(item["name"]) for item in fields]


def ensure_views(
    base_token: str,
    table_id: str,
    view_filters: Mapping[str, Mapping[str, Any]],
    view_fields: Mapping[str, Sequence[str]],
    *,
    all_fields: Sequence[str],
    dry_run: bool,
) -> List[Dict[str, Any]]:
    if dry_run:
        return [{"view_name": name, "status": "dry_run"} for name in view_filters]
    existing = list_views(base_token, table_id)
    results = []
    for name, filter_config in view_filters.items():
        view_id = existing.get(name)
        created = False
        if not view_id:
            data = run_json([
                "lark-cli", "base", "+view-create",
                "--base-token", base_token,
                "--table-id", table_id,
                "--json", json.dumps({"name": name, "type": "grid"}, ensure_ascii=False),
            ])
            view = (data.get("data") or {}).get("view") or {}
            view_id = view.get("id") or view.get("view_id") or list_views(base_token, table_id).get(name)
            created = True
        visible_fields = list(view_fields.get(name) or all_fields)
        if view_id:
            for command, payload in [
                ("+view-set-visible-fields", {"visible_fields": visible_fields}),
                ("+view-set-filter", dict(filter_config)),
            ]:
                run_json([
                    "lark-cli", "base", command,
                    "--base-token", base_token,
                    "--table-id", table_id,
                    "--view-id", view_id,
                    "--json", json.dumps(payload, ensure_ascii=False),
                ])
        results.append({"view_name": name, "view_id": view_id, "created": created, "status": "updated"})
    return results


def _fields(record: Mapping[str, Any]) -> Dict[str, Any]:
    data = record.get("fields") if isinstance(record, Mapping) else {}
    return data if isinstance(data, dict) else {}


def _record_id(record: Mapping[str, Any]) -> str:
    return str(record.get("record_id") or record.get("id") or "")


def text(fields: Mapping[str, Any], name: str) -> str:
    return extract_text(fields.get(name)).strip()


def normalize_stage(value: str) -> str:
    return (value or "").strip()


def infer_capability(stage: str, provider: str, model: str) -> str:
    if stage in TEXT_STAGES:
        return "文本"
    if stage in IMAGE_STAGES:
        return "图片"
    if stage in VIDEO_STAGES:
        return "视频"
    if stage in VIDEO_EDIT_STAGES:
        return "视频编辑"
    if stage in VOICE_STAGES:
        return "语音"
    for entry in ai_model_catalog.catalog_entries(ai_model_catalog.INSPECTABLE_STATUSES):
        if model in {entry.model, entry.display_name}:
            return entry.capability
    return ""


def infer_provider(stage: str, api_base: str, model: str, explicit: str = "") -> str:
    if explicit:
        return explicit
    if " / " in model:
        return model.split(" / ", 1)[0].strip()
    lower_base = (api_base or "").lower()
    if "otuapi" in lower_base or stage in {"图片生成-OTU", "分镜视频生成-OTU", "多图九宫格图片生成", "多图九宫格视频生成"}:
        return "OTU"
    if "aitgenne" in lower_base or stage in {"语音合成-MiniMax", "视频编辑-HappyHorse"}:
        return "Aitgenne"
    if "aihubmix" in lower_base or "gemini" in lower_base or stage.endswith("-Gemini") or stage == "分镜视频生成-Veo":
        return "AIHubMix"
    return ""


def raw_model_name(display_or_model: str) -> str:
    return display_or_model.split(" / ", 1)[1].strip() if " / " in display_or_model else display_or_model.strip()


def display_name(provider: str, model: str) -> str:
    model = raw_model_name(model)
    return f"{provider} / {model}" if provider else model


def source_mode(fields: Mapping[str, Any]) -> str:
    return text(fields, SOURCE_MODE_FIELD) or SOURCE_MODE_ONLINE


def is_online_config(fields: Mapping[str, Any]) -> bool:
    return source_mode(fields) != SOURCE_MODE_CODE


def is_active_runtime_status(fields: Mapping[str, Any]) -> bool:
    return text(fields, "状态") in {"启用", "测试中", ""}


def config_type(fields: Mapping[str, Any]) -> str:
    return text(fields, CONFIG_TYPE_FIELD)


def stage_text(fields: Mapping[str, Any]) -> str:
    return text(fields, "环节")


def provider_text(fields: Mapping[str, Any]) -> str:
    return text(fields, PROVIDER_FIELD) or text(fields, "默认供应商") or text(fields, "AI供应商")


def model_display_from_fields(fields: Mapping[str, Any]) -> str:
    explicit_display = text(fields, DISPLAY_NAME_FIELD) or text(fields, "默认模型显示名称")
    if explicit_display:
        return explicit_display
    provider = provider_text(fields) or infer_provider(stage_text(fields), text(fields, "API 代理地址"), text(fields, "模型名称"), "")
    return display_name(provider, text(fields, "模型名称"))


def runtime_stage_record_matches(fields: Mapping[str, Any], stage: str) -> bool:
    if stage_text(fields) != stage:
        return False
    row_type = config_type(fields)
    return row_type in {"", CONFIG_TYPE_RUNTIME_STAGE}


def task_default_record_matches(fields: Mapping[str, Any], app_table: str, stage: str) -> bool:
    if config_type(fields) != CONFIG_TYPE_TASK_DEFAULT:
        return False
    if not cell_matches(fields.get("应用表格"), app_table):
        return False
    return text(fields, TASK_STAGE_FIELD) == stage or text(fields, "环节") == stage


def normalize_task_default_fields(fields: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "默认供应商": provider_text(fields),
        "默认模型显示名称": model_display_from_fields(fields),
        "画面尺寸": text(fields, "画面尺寸"),
        "画面比例": text(fields, "画面比例"),
        "AI参数JSON": text(fields, "AI参数JSON"),
        "系统提示词": text(fields, "系统提示词") or text(fields, "提示词"),
        "状态": text(fields, "状态"),
        "备注": text(fields, "备注"),
    }


def fallback_stage_config(
    *,
    default_model: str,
    default_api_base: str,
    default_size: str = "",
    default_aspect_ratio: str = "9:16",
    api_key: str = "",
) -> Dict[str, str]:
    return {
        "model": raw_model_name(default_model),
        "provider": display_name("", default_model).split(" / ", 1)[0] if " / " in default_model else "",
        "api_key": api_key,
        "api_base": default_api_base,
        "size": default_size,
        "aspect_ratio": default_aspect_ratio,
        "call_type": "",
        "prompt": "",
        "params": "",
    }


def config_from_stage_fields(
    fields: Mapping[str, Any],
    *,
    default_model: str,
    default_api_base: str,
    default_size: str = "",
    default_aspect_ratio: str = "9:16",
) -> Dict[str, str]:
    provider = provider_text(fields) or infer_provider(stage_text(fields), text(fields, "API 代理地址"), text(fields, "模型名称"), "")
    online = is_online_config(fields)
    raw_model = text(fields, "模型名称") if online else ""
    model_display = raw_model or default_model
    bits = display_name(provider, model_display)
    return {
        "model": raw_model_name(bits or default_model),
        "provider": provider,
        "api_key": text(fields, "API Key"),
        "api_base": (text(fields, "API 代理地址") if online else "") or default_api_base,
        "size": (text(fields, "画面尺寸") if online else "") or default_size,
        "aspect_ratio": (text(fields, "画面比例") if online else "") or default_aspect_ratio,
        "call_type": text(fields, "调用方式") if online else "",
        "prompt": text(fields, "提示词") if online else "",
        "params": text(fields, "AI参数JSON") if online else "",
    }


def catalog_status_for_model(provider: str, capability: str, model: str, runtime_status: str) -> Dict[str, str]:
    entry = ai_model_catalog.find_model(provider, capability, raw_model_name(model), include_candidate=True)
    if entry and entry.status in ai_model_catalog.PRODUCTION_STATUSES and runtime_status in PRODUCTION_RUNTIME_STATUSES:
        return {"接入状态": "已适配", "测试状态": "测试通过", "是否生产可用": "是"}
    if entry and entry.status == ai_model_catalog.STATUS_CANDIDATE:
        return {"接入状态": "已适配", "测试状态": "未测试", "是否生产可用": "否"}
    if runtime_status in {"停用"}:
        return {"接入状态": "停用", "测试状态": "停用", "是否生产可用": "否"}
    return {"接入状态": "需开发适配器", "测试状态": "未测试", "是否生产可用": "否"}


def build_model_catalog_rows(records: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    rows_by_display: Dict[str, Dict[str, Any]] = {}
    for record in records:
        fields = _fields(record)
        stage = normalize_stage(text(fields, "环节"))
        model = text(fields, "模型名称")
        if not model or model in {"关闭", "仅dry-run", "指定记录启用", "全量启用"}:
            continue
        api_base = text(fields, "API 代理地址")
        provider = infer_provider(stage, api_base, model, text(fields, "AI供应商"))
        capability = text(fields, "AI能力类型") or infer_capability(stage, provider, model)
        if not provider or not capability:
            continue
        display = display_name(provider, model)
        status = catalog_status_for_model(provider, capability, model, text(fields, "状态"))
        row = {
            "供应商": provider,
            "能力类型": capability,
            "模型名称": raw_model_name(model),
            "显示名称": display,
            "调用方式": text(fields, "调用方式") or default_call_type(provider, capability, raw_model_name(model)),
            "API代理地址": api_base,
            "默认参数JSON": text(fields, "AI参数JSON"),
            "最后测试时间": "",
            "测试结果摘要": "由现有运行配置迁移；后续由 smoke test 自动更新。",
            "备注": text(fields, "备注"),
            **status,
        }
        existing = rows_by_display.get(display)
        if not existing or existing.get("是否生产可用") != "是":
            rows_by_display[display] = row
    for entry in ai_model_catalog.production_models():
        display = entry.display_name
        rows_by_display.setdefault(display, {
            "供应商": entry.provider,
            "能力类型": entry.capability,
            "模型名称": entry.model,
            "显示名称": display,
            "调用方式": default_call_type(entry.provider, entry.capability, entry.model),
            "API代理地址": default_api_base(entry.provider, entry.capability),
            "默认参数JSON": json.dumps(default_params(entry.provider, entry.capability, entry.model), ensure_ascii=False, sort_keys=True),
            "接入状态": "已适配",
            "测试状态": "未测试",
            "最后测试时间": "",
            "测试结果摘要": "来自本地模型目录，等待 smoke test 写回。",
            "是否生产可用": "否",
            "备注": entry.notes,
        })
    return sorted(rows_by_display.values(), key=lambda item: (item["供应商"], item["能力类型"], item["显示名称"]))


def source_records_by_stage(records: Sequence[Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
    result: Dict[str, Dict[str, Any]] = {}
    for record in records:
        fields = _fields(record)
        stage = normalize_stage(text(fields, "环节"))
        if stage and not stage.startswith("统一AI预设-"):
            result[stage] = {"record_id": _record_id(record), "fields": fields}
    return result


def build_task_default_rows(records: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    sources = source_records_by_stage(records)
    rows: List[Dict[str, Any]] = []
    for spec in RUNTIME_DEFAULT_SPECS:
        source = sources.get(spec.source_config_stage)
        if not source:
            continue
        fields = source["fields"]
        provider = infer_provider(spec.source_config_stage, text(fields, "API 代理地址"), text(fields, "模型名称"), text(fields, "AI供应商"))
        model_display = display_name(provider, text(fields, "模型名称"))
        rows.append({
            "配置类型": CONFIG_TYPE_TASK_DEFAULT,
            "应用表格": TASK_TABLES[spec.table_key],
            "任务环节": spec.stage,
            "默认槽位": spec.slot_name or "stage",
            "环节": spec.source_config_stage,
            "生效来源": SOURCE_MODE_ONLINE,
            "供应商": provider,
            "能力类型": infer_capability(spec.source_config_stage, provider, text(fields, "模型名称")),
            "模型名称": model_display,
            "显示名称": model_display,
            "默认供应商": provider,
            "默认模型显示名称": model_display,
            "画面尺寸": text(fields, "画面尺寸"),
            "画面比例": text(fields, "画面比例"),
            "AI参数JSON": text(fields, "AI参数JSON"),
            "系统提示词": text(fields, "提示词"),
            "状态": "启用" if text(fields, "状态") != "停用" else "停用",
            "备注": f"source_config={spec.source_config_stage}; source_record_id={source['record_id']}; slot={spec.slot_name or 'stage'}",
        })
    return rows


def archive_legacy_preset_updates(records: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    updates: List[Dict[str, Any]] = []
    for record in records:
        fields = _fields(record)
        stage = text(fields, "环节")
        if not stage.startswith("统一AI预设-"):
            continue
        remark = text(fields, "备注")
        if "归档" not in remark:
            remark = f"归档：已迁移到 初始化-模型与API配置 / {MODEL_CATALOG_VIEW_NAME}；{remark}" if remark else f"归档：已迁移到 初始化-模型与API配置 / {MODEL_CATALOG_VIEW_NAME}"
        updates.append({
            "record_id": _record_id(record),
            "fields": {
                "状态": "停用",
                "是否统一AI预设": "否",
                "备注": remark,
            },
        })
    return updates


def validate_task_default_rows(rows: Sequence[Mapping[str, Any]], catalog_rows: Sequence[Mapping[str, Any]]) -> List[str]:
    production_models = {
        str(item.get("显示名称") or "")
        for item in catalog_rows
        if item.get("接入状态") == "已适配"
        and item.get("测试状态") == "测试通过"
        and item.get("是否生产可用") == "是"
    }
    errors = []
    for row in rows:
        model = str(row.get("默认模型显示名称") or "")
        if model not in production_models:
            errors.append(f"{row.get('应用表格')} / {row.get('环节')} 默认模型不可生产使用: {model}")
    return errors


def build_config_center_plan(records: Sequence[Mapping[str, Any]]) -> ConfigCenterPlan:
    catalog = build_model_catalog_rows(records)
    defaults = build_task_default_rows(records)
    return ConfigCenterPlan(
        model_catalog_rows=catalog,
        task_default_rows=defaults,
        legacy_archive_updates=archive_legacy_preset_updates(records),
        validation_errors=validate_task_default_rows(defaults, catalog),
    )


def default_patch_for_slot(fields: Mapping[str, Any], slot_name: str, default_fields: Mapping[str, Any]) -> Dict[str, Any]:
    return default_patch_for_fields(
        fields,
        default_fields,
        model_field=f"{slot_name}AI模型",
        size_field=f"{slot_name}画面尺寸",
        ratio_field=f"{slot_name}画面比例",
        params_field=f"{slot_name}AI参数JSON",
    )


def default_patch_for_fields(
    fields: Mapping[str, Any],
    default_fields: Mapping[str, Any],
    *,
    model_field: str = "",
    size_field: str = "",
    ratio_field: str = "",
    params_field: str = "",
    prompt_field: str = "",
    placeholder_values: Sequence[str] = (),
) -> Dict[str, Any]:
    patch: Dict[str, Any] = {}
    placeholders = {item.strip() for item in placeholder_values if item.strip()}
    mapping = {
        model_field: default_fields.get("默认模型显示名称"),
        size_field: default_fields.get("画面尺寸"),
        ratio_field: default_fields.get("画面比例"),
        params_field: default_fields.get("AI参数JSON"),
        prompt_field: default_fields.get("系统提示词"),
    }
    for name, value in mapping.items():
        if not name:
            continue
        current = extract_text(fields.get(name)).strip()
        if value and (not current or current in placeholders):
            patch[name] = value
    return patch


def cell_texts(value: Any) -> List[str]:
    if isinstance(value, list):
        values: List[str] = []
        for item in value:
            if isinstance(item, dict):
                if item.get("text") is not None:
                    values.append(str(item.get("text") or "").strip())
                elif item.get("name") is not None:
                    values.append(str(item.get("name") or "").strip())
                elif item.get("record_ids"):
                    values.extend(str(rid) for rid in item.get("record_ids") or [])
                else:
                    values.append(extract_text(item).strip())
            else:
                values.append(str(item).strip())
        return [item for item in values if item]
    text_value = extract_text(value).strip()
    return [text_value] if text_value else []


def cell_matches(value: Any, expected: str) -> bool:
    return expected in cell_texts(value)


_TABLE_ID_CACHE: Dict[Tuple[str, str], Optional[str]] = {}
_TASK_DEFAULT_CACHE: Dict[Tuple[str, str, str], Optional[Dict[str, Any]]] = {}
_STAGE_CONFIG_CACHE: Dict[Tuple[str, str, str, str, str, str], Tuple[str, Dict[str, str]]] = {}


def find_table_id_by_name(token: str, table_name: str, *, base_token: str = APP_TOKEN) -> Optional[str]:
    cache_key = (base_token, table_name)
    if cache_key in _TABLE_ID_CACHE:
        return _TABLE_ID_CACHE[cache_key]
    table_id = list_tables_api(token, base_token=base_token).get(table_name)
    if table_id:
        _TABLE_ID_CACHE[cache_key] = table_id
        return table_id
    _TABLE_ID_CACHE[cache_key] = None
    return None


def load_task_default_fields(token: str, app_table: str, stage: str) -> Optional[Dict[str, Any]]:
    if token in {"t", "token", "test-token", "fake-token"} or token.startswith("test_"):
        return None
    cache_key = (APP_TOKEN, app_table, stage)
    if cache_key in _TASK_DEFAULT_CACHE:
        cached = _TASK_DEFAULT_CACHE[cache_key]
        return dict(cached) if cached else None

    config_matches: List[Dict[str, Any]] = []
    code_default_seen = False
    for record in safe_list_records(token, TABLE_CONFIG):
        fields = record.get("fields") or {}
        if not task_default_record_matches(fields, app_table, stage):
            continue
        if text(fields, "状态") == "停用":
            continue
        if not is_online_config(fields):
            code_default_seen = True
            continue
        config_matches.append(normalize_task_default_fields(fields))
    if len(config_matches) == 1:
        _TASK_DEFAULT_CACHE[cache_key] = dict(config_matches[0])
        return dict(config_matches[0])
    if len(config_matches) > 1:
        raise RuntimeError(f"{app_table} / {stage} 默认配置重复: {len(config_matches)} 条启用记录")
    if code_default_seen:
        _TASK_DEFAULT_CACHE[cache_key] = None
        return None

    raise RuntimeError(f"初始化-模型与API配置中找不到 {app_table} / {stage} 的启用任务默认配置")


def load_stage_config_fields(
    token: str,
    stage: str,
    *,
    default_model: str,
    default_api_base: str,
    default_size: str = "",
    default_aspect_ratio: str = "9:16",
    require_api_key: bool = False,
) -> Tuple[str, Dict[str, str]]:
    cache_key = (APP_TOKEN, stage, default_model, default_api_base, default_size, default_aspect_ratio)
    if cache_key in _STAGE_CONFIG_CACHE:
        record_id, cached = _STAGE_CONFIG_CACHE[cache_key]
        return record_id, dict(cached)
    matches: List[Tuple[str, Dict[str, Any]]] = []
    for record in safe_list_records(token, TABLE_CONFIG):
        fields = record.get("fields") or {}
        if not runtime_stage_record_matches(fields, stage):
            continue
        if not is_active_runtime_status(fields):
            continue
        matches.append((str(record.get("record_id") or record.get("id") or ""), fields))
    if len(matches) > 1:
        online = [item for item in matches if is_online_config(item[1])]
        matches = online or matches
    if len(matches) > 1:
        raise RuntimeError(f"{stage} 运行配置重复: {len(matches)} 条启用记录")
    if matches:
        record_id, fields = matches[0]
        cfg = config_from_stage_fields(
            fields,
            default_model=default_model,
            default_api_base=default_api_base,
            default_size=default_size,
            default_aspect_ratio=default_aspect_ratio,
        )
        if require_api_key and not cfg["api_key"]:
            raise ValueError(f"{stage} 缺少 API Key")
        _STAGE_CONFIG_CACHE[cache_key] = (record_id, dict(cfg))
        return record_id, cfg
    cfg = fallback_stage_config(
        default_model=default_model,
        default_api_base=default_api_base,
        default_size=default_size,
        default_aspect_ratio=default_aspect_ratio,
    )
    if require_api_key and not cfg["api_key"]:
        raise ValueError(f"{stage} 缺少 API Key")
    return "", cfg


def apply_task_default_to_record(
    token: str,
    table_id: str,
    record_id: str,
    fields: Mapping[str, Any],
    *,
    app_table: str,
    stage: str,
    model_field: str = "",
    size_field: str = "",
    ratio_field: str = "",
    params_field: str = "",
    prompt_field: str = "",
    placeholder_values: Sequence[str] = (),
    update_fn: Callable[[str, str, str, Dict[str, Any]], Any] = safe_update_record,
    field_filter: Optional[Callable[[str, str, Mapping[str, Any]], Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    default_fields = load_task_default_fields(token, app_table, stage)
    if not default_fields:
        return dict(fields)
    patch = default_patch_for_fields(
        fields,
        default_fields,
        model_field=model_field,
        size_field=size_field,
        ratio_field=ratio_field,
        params_field=params_field,
        prompt_field=prompt_field,
        placeholder_values=placeholder_values,
    )
    if not patch:
        return dict(fields)
    writable_patch = field_filter(token, table_id, patch) if field_filter else patch
    dropped = sorted(set(patch) - set(writable_patch))
    if dropped:
        raise RuntimeError(f"{app_table} / {stage} 默认配置字段不存在或不可写: {', '.join(dropped)}")
    if writable_patch:
        update_fn(token, table_id, record_id, writable_patch)
    merged = dict(fields)
    merged.update(writable_patch)
    return merged


def apply_task_default_to_fields(
    token: str,
    fields: Mapping[str, Any],
    *,
    app_table: str,
    stage: str,
    model_field: str = "",
    size_field: str = "",
    ratio_field: str = "",
    params_field: str = "",
    prompt_field: str = "",
    placeholder_values: Sequence[str] = (),
) -> Dict[str, Any]:
    default_fields = load_task_default_fields(token, app_table, stage)
    if not default_fields:
        return dict(fields)
    patch = default_patch_for_fields(
        fields,
        default_fields,
        model_field=model_field,
        size_field=size_field,
        ratio_field=ratio_field,
        params_field=params_field,
        prompt_field=prompt_field,
        placeholder_values=placeholder_values,
    )
    merged = dict(fields)
    merged.update(patch)
    return merged


def is_deprecated_record(fields: Mapping[str, Any]) -> bool:
    return text(fields, "记录状态") == "已废弃"


def backfill_runtime_defaults(
    token: Optional[str] = None,
    *,
    specs: Sequence[RuntimeDefaultBackfillSpec] = RUNTIME_DEFAULT_BACKFILL_SPECS,
    write: bool = False,
    update_fn: Callable[[str, str, str, Dict[str, Any]], Any] = safe_update_record,
) -> Dict[str, Any]:
    token = token or get_feishu_token()
    result = {
        "mode": "write" if write else "dry_run",
        "stages": [],
        "totals": {
            "records": 0,
            "active": 0,
            "missing": 0,
            "would_update": 0,
            "updated": 0,
        },
    }
    for spec in specs:
        table_id = TABLE_IDS_BY_KEY.get(spec.table_key, "")
        stage_result = {
            "table_key": spec.table_key,
            "table_id": table_id,
            "app_table": spec.app_table,
            "stage": spec.stage,
            "status_field": spec.status_field,
            "records": 0,
            "active": 0,
            "missing": 0,
            "would_update": 0,
            "updated": 0,
            "skipped_status": 0,
            "skipped_deprecated": 0,
            "skipped_no_patch": 0,
            "skipped_schema_missing": 0,
            "schema_missing_fields": [],
            "examples": [],
        }
        if not table_id:
            stage_result["status"] = "table_missing"
            result["stages"].append(stage_result)
            continue

        allowed_fields = list_field_names_api(token, table_id)
        schema_missing_fields = set()
        default_fields = load_task_default_fields(token, spec.app_table, spec.stage)
        active_statuses = set(spec.active_statuses or ACTIVE_BACKFILL_STATUSES)
        for record in safe_list_records(token, table_id):
            fields = record.get("fields") or {}
            stage_result["records"] += 1
            result["totals"]["records"] += 1
            if is_deprecated_record(fields):
                stage_result["skipped_deprecated"] += 1
                continue
            status = text(fields, spec.status_field)
            if status not in active_statuses:
                stage_result["skipped_status"] += 1
                continue
            stage_result["active"] += 1
            result["totals"]["active"] += 1
            patch = default_patch_for_fields(
                fields,
                default_fields,
                model_field=spec.model_field,
                size_field=spec.size_field,
                ratio_field=spec.ratio_field,
                params_field=spec.params_field,
                placeholder_values=spec.placeholder_values,
            )
            if not patch:
                stage_result["skipped_no_patch"] += 1
                continue
            writable_patch = {key: value for key, value in patch.items() if key in allowed_fields}
            dropped_schema = sorted(set(patch) - set(writable_patch))
            schema_missing_fields.update(dropped_schema)
            record_id = _record_id(record)
            stage_result["missing"] += 1
            result["totals"]["missing"] += 1
            if not writable_patch:
                stage_result["skipped_schema_missing"] += 1
                continue
            stage_result["would_update"] += 1
            result["totals"]["would_update"] += 1
            if len(stage_result["examples"]) < 3:
                stage_result["examples"].append({
                    "record_id": record_id,
                    "name": text(fields, "任务名称")[:80],
                    "status": status,
                    "patch": writable_patch,
                })
            if write:
                update_fn(token, table_id, record_id, writable_patch)
                stage_result["updated"] += 1
                result["totals"]["updated"] += 1
        stage_result["schema_missing_fields"] = sorted(schema_missing_fields)
        result["stages"].append(stage_result)
    return result


def list_records(token: str, table_id: str) -> List[Dict[str, Any]]:
    return safe_list_records(token, table_id)


def normalize_key(value: Any) -> str:
    return extract_text(value).strip().lower().replace("_", "-").replace(" ", "")


def record_key(fields: Mapping[str, Any], key_fields: Sequence[str]) -> str:
    return "::".join(normalize_key(fields.get(name)) for name in key_fields)


def filter_fields_for_table(base_token: str, table_id: str, row: Mapping[str, Any]) -> Dict[str, Any]:
    allowed = list_field_names(base_token, table_id)
    return {key: value for key, value in row.items() if key in allowed}


def upsert_rows(
    token: str,
    base_token: str,
    table_id: str,
    rows: Sequence[Mapping[str, Any]],
    *,
    key_fields: Sequence[str],
    dry_run: bool,
) -> List[Dict[str, Any]]:
    existing = list_records(token, table_id) if not str(table_id).startswith("dry-run:") else []
    by_key = {record_key(record.get("fields") or {}, key_fields): record for record in existing}
    results = []
    for row in rows:
        desired = filter_fields_for_table(base_token, table_id, row) if not dry_run else dict(row)
        key = record_key(desired, key_fields)
        existing_record = by_key.get(key)
        action = "update" if existing_record else "create"
        if not dry_run:
            if existing_record:
                safe_update_record(token, table_id, existing_record["record_id"], desired)
            else:
                safe_request(
                    "post",
                    f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/records",
                    headers=feishu_headers(token),
                    json={"fields": desired},
                    timeout=30,
                    max_attempts=3,
                )
        results.append({"key": key, "action": "dry_run_" + action if dry_run else action, "field_count": len(desired)})
    return results


def catalog_record_id_by_display(token: str, table_id: str) -> Dict[str, str]:
    if str(table_id).startswith("dry-run:"):
        return {}
    result = {}
    for record in list_records(token, table_id):
        fields = record.get("fields") or {}
        display = text(fields, "显示名称")
        if display:
            result[display] = record.get("record_id") or record.get("id") or ""
    return result


def attach_model_links(task_rows: Sequence[Mapping[str, Any]], model_record_ids: Mapping[str, str]) -> List[Dict[str, Any]]:
    rows = []
    for row in task_rows:
        copied = dict(row)
        model_display = str(copied.get("默认模型显示名称") or "")
        record_id = model_record_ids.get(model_display)
        if record_id:
            copied["默认模型"] = [record_id]
        rows.append(copied)
    return rows


def redact_config_record(record: Mapping[str, Any]) -> Dict[str, Any]:
    fields = _fields(record)
    safe_fields = {}
    for name, value in fields.items():
        if name == "API Key":
            safe_fields[name] = "[REDACTED]"
        elif name == "提示词":
            safe_fields[name] = f"[prompt chars={len(extract_text(value))}]"
        else:
            safe_fields[name] = value
    return {"record_id": _record_id(record), "fields": safe_fields}


def write_backup(path: Path, records: Sequence[Mapping[str, Any]], plan: ConfigCenterPlan) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source_table": "初始化-模型与API配置",
        "source_table_id": TABLE_CONFIG,
        "model_catalog_rows": len(plan.model_catalog_rows),
        "task_default_rows": len(plan.task_default_rows),
        "legacy_archive_updates": len(plan.legacy_archive_updates),
        "records": [redact_config_record(record) for record in records],
    }
    path.write_text(redacted_json(payload) + "\n", encoding="utf-8")


def apply_legacy_archive(token: str, updates: Sequence[Mapping[str, Any]], *, dry_run: bool) -> List[Dict[str, Any]]:
    results = []
    for update in updates:
        record_id = str(update.get("record_id") or "")
        fields = dict(update.get("fields") or {})
        if not dry_run:
            fields = filter_fields_for_table(APP_TOKEN, TABLE_CONFIG, fields)
        if not dry_run and record_id:
            if fields:
                safe_update_record(token, TABLE_CONFIG, record_id, fields)
                status = "updated"
            else:
                status = "skipped_no_writable_fields"
        else:
            status = "dry_run"
        results.append({"record_id": record_id, "status": status, "fields": fields})
    return results


def run_migration(*, write: bool, backup_path: Path = BACKUP_PATH) -> Dict[str, Any]:
    token = get_feishu_token()
    records = safe_list_records(token, TABLE_CONFIG)
    plan = build_config_center_plan(records)
    write_backup(backup_path, records, plan)

    dry_run = not write
    catalog_rows = []
    for row in plan.model_catalog_rows:
        catalog_rows.append({
            "配置类型": CONFIG_TYPE_MODEL_CATALOG,
            "供应商": row.get("供应商"),
            "能力类型": row.get("能力类型"),
            "模型名称": row.get("模型名称"),
            "显示名称": row.get("显示名称"),
            "调用方式": row.get("调用方式"),
            "API 代理地址": row.get("API代理地址"),
            "AI参数JSON": row.get("默认参数JSON"),
            "状态": "启用" if row.get("是否生产可用") == "是" else "测试中",
            "生效来源": SOURCE_MODE_ONLINE,
            "测试状态": row.get("测试状态"),
            "是否生产可用": row.get("是否生产可用"),
            "备注": row.get("备注"),
        })
    catalog_results = upsert_rows(
        token,
        APP_TOKEN,
        TABLE_CONFIG,
        catalog_rows,
        key_fields=[CONFIG_TYPE_FIELD, DISPLAY_NAME_FIELD],
        dry_run=dry_run,
    )

    default_results = upsert_rows(
        token,
        APP_TOKEN,
        TABLE_CONFIG,
        plan.task_default_rows,
        key_fields=[CONFIG_TYPE_FIELD, "应用表格", TASK_STAGE_FIELD],
        dry_run=dry_run,
    )
    archive_results = apply_legacy_archive(token, plan.legacy_archive_updates, dry_run=dry_run)
    return {
        "mode": "write" if write else "dry_run",
        "backup_path": str(backup_path),
        "config_table": {"table_name": "初始化-模型与API配置", "table_id": TABLE_CONFIG},
        "model_catalog_records": catalog_results,
        "task_default_records": default_results,
        "legacy_archive_updates": archive_results,
        "validation_errors": plan.validation_errors,
    }


def default_api_base(provider: str, capability: str) -> str:
    if provider == "OTU":
        return "https://otuapi.com"
    if provider == "Aitgenne":
        return "https://api.aitgenne.com/v1"
    if provider == "AIHubMix" and capability == "文本":
        return "https://aihubmix.com/gemini"
    if provider == "AIHubMix":
        return "https://aihubmix.com"
    return ""


def default_call_type(provider: str, capability: str, model: str) -> str:
    entry = ai_model_catalog.find_model(provider, capability, model, include_candidate=True)
    if entry and entry.call_types:
        return entry.call_types[0]
    if provider == "OTU" and capability == "图片":
        return "OTU /v1/videos JSON image task"
    if provider == "OTU" and capability == "视频":
        return "OTU /v1/videos multipart"
    if provider == "AIHubMix" and capability == "文本":
        return "Gemini 原生 SDK"
    if provider == "AIHubMix" and capability == "视频":
        return "Gemini native Veo"
    if provider == "Aitgenne" and capability == "文本":
        return "OpenAI兼容 chat/completions"
    return "专用 API"


def default_params(provider: str, capability: str, model: str) -> Dict[str, Any]:
    if capability == "图片":
        size = "720x1280"
        if model.endswith("-2K"):
            size = "1080x1920"
        elif model.endswith("-4K"):
            size = "1440x2560"
        return {"size": size, "aspect_ratio": "9:16"}
    if capability == "视频":
        return {"size": "720x1280", "aspect_ratio": "9:16", "seconds": "8"}
    if capability == "视频编辑":
        return {"resolution": "720P", "audio_setting": "origin"}
    return {}


def redacted_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="AI 模型配置中心迁移/审计")
    parser.add_argument("--write", action="store_true", help="实际创建/更新飞书表；默认只 dry-run")
    parser.add_argument("--backup-path", default=str(BACKUP_PATH), help="脱敏备份输出路径")
    parser.add_argument("--audit-runtime-default-backfill", action="store_true", help="审计任务表默认配置字段缺失情况，不写回")
    parser.add_argument("--backfill-runtime-defaults", action="store_true", help="回填任务表缺失的运行默认配置字段；需配合 --write 才实际写入")
    args = parser.parse_args()
    if args.audit_runtime_default_backfill or args.backfill_runtime_defaults:
        result = backfill_runtime_defaults(write=args.write if args.backfill_runtime_defaults else False)
    else:
        result = run_migration(write=args.write, backup_path=Path(args.backup_path))
    print(redacted_json(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
