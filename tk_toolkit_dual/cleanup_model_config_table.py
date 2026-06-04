#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import datetime as dt
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ai_model_catalog  # noqa: E402
from common import (  # noqa: E402
    APP_TOKEN,
    CONFIG_RECORDS,
    TABLE_CONFIG,
    extract_text,
    feishu_headers,
    get_feishu_token,
    safe_list_records,
    safe_request,
    safe_update_record,
)


BACKUP_PATH = Path("docs/tk-pipeline/model-config-cleanup-backup-2026-05-31.json")
UNIFIED_CONFIG_TABLE_NAME = "初始化-模型与API配置"
CONFIG_PROMPT_STAGES = {
    "多图九宫格方案生成",
    "多图九宫格图片生成",
    "多图九宫格视频生成",
}
AIHUBMIX_VEO_STAGE = "分镜视频生成-Veo"
EXPLICIT_STATUS_BY_STAGE = {
    AIHUBMIX_VEO_STAGE: "启用",
}
ROUTE_SWITCH_STAGE = "统一AI路由启用状态"
AUTO_REVIEW_SUFFIX = "一键审核通过模式"
TEXT_STAGES = {
    "脚本文档结构化拆分-Gemini",
    "故事板图片提示词拆分-Gemini",
    "多角色首尾帧解析-Gemini",
    "多图九宫格方案生成",
}
IMAGE_STAGES = {
    "图片生成-OTU",
    "故事板图片生成-OTU",
    "多图九宫格图片生成",
}
VIDEO_STAGES = {
    "分镜视频生成-Veo",
    "分镜视频生成-OTU",
    "故事板视频生成-Omni",
    "多图九宫格视频生成",
}
VIDEO_EDIT_STAGES = {"视频编辑-HappyHorse"}
VOICE_STAGES = {"语音合成-MiniMax"}
LEGACY_CONFIG_TABLE_NAME = "初始化-API密钥与旧运行配置"
LEGACY_CONFIG_VIEW_RENAMES = {
    "供应商密钥-管理员": "01-运行配置-管理员",
    "配置总览": "02-旧运行配置总览",
    "排错-全字段": "99-旧配置排错全字段",
}
MIGRATED_FIELD_NAMES: Set[str] = set()
OBSOLETE_VIEWS_BY_TABLE = {
    TABLE_CONFIG: {
        "统一AI预设",
        "模型目录",
        "归档-候选旧模型",
    },
}
ARCHIVE_PREFIX = "归档："
SECRET_FIELD_NAMES = {"API Key"}
OBSOLETE_VIEW_NAMES = {
    "00-生产运行配置",
    "01-统一AI Catalog",
    "02-链路提示词配置",
    "02-旧运行配置总览",
    "04-提示词配置",
    "90-归档-旧预设",
    "90-归档旧配置",
    "99-全字段排错",
    "99-旧配置排错全字段",
}
MEDIA_DIMENSION_DEFAULTS = {
    "图片生成-OTU": ("720x1280", "9:16"),
    "分镜视频生成-OTU": ("720x1280", "9:16"),
    "故事板图片生成-OTU": ("1280x720", "16:9"),
    "故事板视频生成-Omni": ("720x1280", "9:16"),
    "多图九宫格图片生成": ("720x1280", "9:16"),
    "多图九宫格视频生成": ("720x1280", "9:16"),
}
TASK_DEFAULT_APP_TABLE_FIELD = "应用表格"
TASK_DEFAULT_APP_TABLE_OPTIONS = [
    "001-多角色首尾帧生成表",
    "002-首尾帧视频生成表",
    "003-1脚本文档-任务表",
    "003-2脚本文档-参考资产表",
    "003-3脚本文档-分镜生产表",
    "004-故事板图片视频生成表",
    "005-多图九宫格视频生成表",
    "006-视频编辑任务表",
]
MODEL_CATALOG_CAPABILITY_OPTIONS = ["文本", "图片", "视频", "视频编辑", "语音"]
MODEL_CATALOG_VIEW_NAME = "03-模型目录"
MODEL_CATALOG_VISIBLE_FIELDS = ["配置类型", "供应商", "能力类型", "显示名称", "模型名称", "调用方式", "API 代理地址", "测试状态", "是否生产可用", "备注"]
FORCED_PRIMARY_FIELD_ALLOWANCE = 1


def opt(name: str, hue: str = "Blue", lightness: str = "Lighter") -> Dict[str, str]:
    return {"name": name, "hue": hue, "lightness": lightness}


CONFIG_FIELD_SPECS = [
    {
        "name": "配置类型",
        "type": "select",
        "multiple": False,
        "options": [opt("运行环节", "Green"), opt("任务默认", "Blue"), opt("模型目录", "Purple"), opt("路由开关", "Orange"), opt("自动审核", "Wathet")],
    },
    {
        "name": "应用表格",
        "type": "select",
        "multiple": False,
        "options": [opt(item, "Blue") for item in TASK_DEFAULT_APP_TABLE_OPTIONS],
    },
    {
        "name": "任务环节",
        "type": "text",
    },
    {
        "name": "默认槽位",
        "type": "select",
        "multiple": False,
        "options": [opt(item, "Wathet") for item in ["stage", "参考图", "关键帧", "视频", "首帧图", "尾帧图", "分镜图", "故事板图片", "图片", "口播音频", "视频编辑"]],
    },
    {
        "name": "生效来源",
        "type": "select",
        "multiple": False,
        "options": [opt("线上配置", "Green"), opt("代码默认", "Gray")],
    },
    {
        "name": "供应商",
        "type": "select",
        "multiple": False,
        "options": [opt("AIHubMix", "Blue"), opt("Aitgenne", "Orange"), opt("OTU", "Green")],
    },
    {
        "name": "能力类型",
        "type": "select",
        "multiple": False,
        "options": [opt(item, "Blue") for item in MODEL_CATALOG_CAPABILITY_OPTIONS],
    },
    {
        "name": "显示名称",
        "type": "text",
    },
    {
        "name": "测试状态",
        "type": "select",
        "multiple": False,
        "options": [opt(item, "Blue") for item in ["未测试", "测试通过", "测试失败", "停用"]],
    },
    {
        "name": "是否生产可用",
        "type": "select",
        "multiple": False,
        "options": [opt(item, "Green") for item in ["是", "否"]],
    },
    {
        "name": "画面尺寸",
        "type": "select",
        "multiple": False,
        "options": [
            opt("1024x1024", "Gray"),
            opt("720x1280", "Green"),
            opt("1080x1920", "Blue"),
            opt("1280x720", "Gray"),
            opt("1440x2560", "Purple"),
            opt("2K", "Blue"),
            opt("4K", "Purple"),
        ],
    },
    {
        "name": "画面比例",
        "type": "select",
        "multiple": False,
        "options": [opt("9:16", "Green"), opt("16:9", "Gray"), opt("1:1", "Gray")],
    },
]


@dataclass(frozen=True)
class RecordUpdate:
    record_id: str
    category: str
    fields: Dict[str, Any]


@dataclass(frozen=True)
class CleanupPlan:
    summary: Dict[str, int]
    record_updates: List[RecordUpdate]


@dataclass(frozen=True)
class DeleteAuditItem:
    record_id: str
    stage: str
    reason: str
    api_key_status: str


@dataclass(frozen=True)
class DeleteAudit:
    candidates: List[DeleteAuditItem]
    skipped: List[DeleteAuditItem]

    def to_public_dict(self) -> Dict[str, Any]:
        return {
            "candidate_count": len(self.candidates),
            "skipped_count": len(self.skipped),
            "candidates": [item.__dict__ for item in self.candidates],
            "skipped": [item.__dict__ for item in self.skipped],
        }


def _record_id(record: Mapping[str, Any]) -> str:
    return str(record.get("record_id") or record.get("id") or "")


def _fields(record: Mapping[str, Any]) -> Dict[str, Any]:
    fields = record.get("fields") if isinstance(record, Mapping) else {}
    return fields if isinstance(fields, dict) else {}


def _text(fields: Mapping[str, Any], name: str) -> str:
    value = fields.get(name)
    if isinstance(value, list):
        parts: List[str] = []
        for item in value:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("name") or item.get("value") or "").strip())
            else:
                parts.append(str(item).strip())
        joined = "".join(part for part in parts if part)
        if joined:
            return joined.strip()
    return extract_text(value).strip()


def _has_api_key(fields: Mapping[str, Any]) -> bool:
    return bool(_text(fields, "API Key"))


def _api_key_status(fields: Mapping[str, Any]) -> str:
    return "存在" if _has_api_key(fields) else "为空"


def _same_patch(fields: Mapping[str, Any], patch: Mapping[str, Any]) -> bool:
    return all(_text(fields, key) == str(value) for key, value in patch.items())


def _archive_remark(existing: str, reason: str) -> str:
    archive = f"{ARCHIVE_PREFIX}{reason}"
    if ARCHIVE_PREFIX in existing:
        return existing
    return f"{archive}；{existing}" if existing else archive


def _prepend_remark_once(existing: str, prefix: str) -> str:
    if not prefix:
        return existing
    if prefix in existing:
        return existing
    return f"{prefix}；{existing}" if existing else prefix


def _clean_existing_remark_for_type(existing: str, row_type: str) -> str:
    if row_type == "自动审核" and existing.startswith("表级自动审核通过开关；"):
        return ""
    if row_type == "运行环节":
        return existing.replace("模型固定", "默认模型").replace("代码默认", "兜底默认")
    return existing


def _semantic_remark_patch(fields: Mapping[str, Any], row_type: str) -> Dict[str, str]:
    existing = _clean_existing_remark_for_type(_text(fields, "备注"), row_type)
    stage = _text(fields, "环节")
    if row_type == "路由开关" and stage == ROUTE_SWITCH_STAGE:
        mode = _text(fields, "模型名称") or _text(fields, "状态") or "关闭"
        desired = (
            f"统一AI路由开关：当前模式={mode}；记录级模型/参数优先；"
            "模式为“指定记录启用”时，仅对任务记录中开启“使用统一AI路由”的记录生效。"
        )
        return {} if existing == desired else {"备注": desired}
    role_prefixes = {
        "运行环节": "运行环节配置：API/提示词/兜底源；任务记录自己的模型/参数优先。",
        "任务默认": "任务默认配置：仅在任务记录未指定模型/参数时用于初始化/补默认。",
        "模型目录": "模型目录：候选模型清单，不直接触发运行。",
        "自动审核": "自动审核开关：表级控制；启用后仅自动放行本表新生成成功且有附件 token 的审核闸门。",
    }
    prefix = role_prefixes.get(row_type, "")
    if not prefix:
        return {}
    desired = _prepend_remark_once(existing, prefix)
    return {} if desired == existing else {"备注": desired}


def _infer_provider(stage: str, api_base: str, model: str) -> str:
    if " / " in model:
        return model.split(" / ", 1)[0].strip()
    lower_base = (api_base or "").lower()
    if "otuapi" in lower_base or stage in {"图片生成-OTU", "分镜视频生成-OTU", "故事板图片生成-OTU", "故事板视频生成-Omni", "多图九宫格图片生成", "多图九宫格视频生成"}:
        return "OTU"
    if "aitgenne" in lower_base or stage in {"语音合成-MiniMax", "视频编辑-HappyHorse"}:
        return "Aitgenne"
    if "aihubmix" in lower_base or "gemini" in lower_base or stage.endswith("-Gemini") or stage == "分镜视频生成-Veo":
        return "AIHubMix"
    return ""


def _infer_capability(stage: str, model: str) -> str:
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


def _record_type_patch(fields: Mapping[str, Any]) -> Dict[str, Any]:
    existing_type = _text(fields, "配置类型")
    if existing_type:
        return {}
    stage = _text(fields, "环节")
    model = _text(fields, "模型名称")
    api_base = _text(fields, "API 代理地址")
    if stage == ROUTE_SWITCH_STAGE:
        row_type = "路由开关"
    elif stage.endswith(AUTO_REVIEW_SUFFIX):
        row_type = "自动审核"
    elif stage.startswith("统一AI预设-"):
        row_type = "模型目录"
    elif stage:
        row_type = "运行环节"
    else:
        return {}

    patch: Dict[str, Any] = {}
    if _text(fields, "配置类型") != row_type:
        patch["配置类型"] = row_type
    if not _text(fields, "生效来源"):
        patch["生效来源"] = "线上配置"
    if row_type == "运行环节":
        provider = _infer_provider(stage, api_base, model)
        capability = _infer_capability(stage, model)
        if provider and not _text(fields, "供应商"):
            patch["供应商"] = provider
        if capability and not _text(fields, "能力类型"):
            patch["能力类型"] = capability
    return patch


def build_cleanup_plan(records: Sequence[Mapping[str, Any]]) -> CleanupPlan:
    production_models = {entry.display_name for entry in ai_model_catalog.production_models()}
    inspectable_models = {
        entry.display_name: entry.status
        for entry in ai_model_catalog.catalog_entries(ai_model_catalog.INSPECTABLE_STATUSES)
    }
    counts = {
        "production_config_count": 0,
        "route_switch_count": 0,
        "prompt_stage_config_count": 0,
        "current_catalog_preset_count": 0,
        "archived_preset_count": 0,
    }
    updates: List[RecordUpdate] = []

    for record in records:
        fields = _fields(record)
        rid = _record_id(record)
        stage = _text(fields, "环节")
        model = _text(fields, "模型名称")
        if not rid:
            continue

        existing_type = _text(fields, "配置类型")
        patch: Dict[str, Any] = _record_type_patch(fields)
        effective_type = existing_type or str(patch.get("配置类型") or "")
        category = ""
        if existing_type in {"任务默认", "模型目录"}:
            category = "single_source_record"
        elif _has_api_key(fields):
            counts["production_config_count"] += 1
            category = "production_config"
            patch["是否统一AI预设"] = "否"
        elif stage == ROUTE_SWITCH_STAGE:
            counts["route_switch_count"] += 1
            category = "route_switch"
            patch["是否统一AI预设"] = "否"
        elif stage in CONFIG_PROMPT_STAGES:
            counts["prompt_stage_config_count"] += 1
            category = "prompt_stage_config"
            patch["是否统一AI预设"] = "否"
        elif stage.startswith("统一AI预设-") and model in production_models:
            counts["current_catalog_preset_count"] += 1
            category = "current_catalog_preset"
            patch["是否统一AI预设"] = "是"
            patch["状态"] = "启用"
        elif stage.startswith("统一AI预设-"):
            counts["archived_preset_count"] += 1
            category = "archived_preset"
            catalog_status = inspectable_models.get(model)
            reason = (
                f"候选/非生产模型，catalog_status={catalog_status}"
                if catalog_status
                else "旧命名统一AI预设，已由供应商/模型显示名预设替代"
            )
            patch["是否统一AI预设"] = "否"
            patch["状态"] = "停用"
            patch["备注"] = _archive_remark(_text(fields, "备注"), reason)

        explicit_status = EXPLICIT_STATUS_BY_STAGE.get(stage)
        if explicit_status and not _text(fields, "状态"):
            category = category or "status_normalization"
            patch.setdefault("状态", explicit_status)

        if _text(fields, "配置类型") not in {"任务默认", "模型目录"} and stage in MEDIA_DIMENSION_DEFAULTS:
            size, ratio = MEDIA_DIMENSION_DEFAULTS[stage]
            category = category or "media_dimension_config"
            patch.setdefault("画面尺寸", size)
            patch.setdefault("画面比例", ratio)

        if effective_type:
            semantic_source = dict(fields)
            if "备注" in patch:
                semantic_source["备注"] = patch["备注"]
            semantic_patch = _semantic_remark_patch(semantic_source, effective_type)
            if semantic_patch:
                category = category or "semantic_remark"
                patch.update(semantic_patch)

        if patch and not _same_patch(fields, patch):
            updates.append(RecordUpdate(record_id=rid, category=category, fields=patch))

    return CleanupPlan(summary=counts, record_updates=updates)


def _redact_field_item(field: Mapping[str, Any]) -> Dict[str, Any]:
    name = str(field.get("field_name") or field.get("name") or "")
    safe_name = "[REDACTED_SECRET_FIELD]" if name in SECRET_FIELD_NAMES else name
    return {
        "field_id": field.get("field_id") or field.get("id"),
        "field_name": safe_name,
        "type": field.get("type"),
    }


def build_backup_snapshot(
    *,
    fields: Sequence[Mapping[str, Any]],
    views: Sequence[Mapping[str, Any]],
    records: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    snapshot_records = []
    for record in records:
        rf = _fields(record)
        prompt = _text(rf, "提示词")
        snapshot_records.append({
            "record_id": _record_id(record),
            "环节": _text(rf, "环节"),
            "是否统一AI预设": _text(rf, "是否统一AI预设"),
            "应用表格_count": len(rf.get("应用表格") or []) if isinstance(rf.get("应用表格"), list) else (1 if rf.get("应用表格") else 0),
            "AI供应商": _text(rf, "AI供应商"),
            "AI能力类型": _text(rf, "AI能力类型"),
            "AI任务类型": _text(rf, "AI任务类型"),
            "模型名称": _text(rf, "模型名称"),
            "API 代理地址": _text(rf, "API 代理地址"),
            "AI参数JSON": _text(rf, "AI参数JSON"),
            "调用方式": _text(rf, "调用方式"),
            "提示词_chars": len(prompt),
            "api_key_status": _api_key_status(rf),
            "状态": _text(rf, "状态"),
            "备注": _text(rf, "备注"),
        })
    return {
        "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "base_id": APP_TOKEN,
        "table_id": TABLE_CONFIG,
        "fields": [_redact_field_item(item) for item in fields],
        "views": [
            {
                "view_id": item.get("view_id") or item.get("id"),
                "view_name": item.get("view_name") or item.get("name"),
                "view_type": item.get("view_type") or item.get("type"),
            }
            for item in views
        ],
        "records": snapshot_records,
    }


def build_view_definitions(field_names: Sequence[str]) -> Dict[str, Dict[str, Any]]:
    all_fields = [name for name in field_names if name not in MIGRATED_FIELD_NAMES]
    return {
        "01-运行配置-管理员": {
            "visible_fields": ["配置类型", "环节", "状态", "生效来源", "供应商", "能力类型", "模型名称", "API Key", "API 代理地址", "调用方式", "提示词", "画面尺寸", "画面比例", "AI参数JSON", "备注"],
            "filter": {
                "logic": "and",
                "conditions": [["配置类型", "intersects", ["运行环节", "路由开关", "自动审核"]], ["状态", "intersects", ["启用", "测试中"]]],
            },
        },
        "02-任务默认配置": {
            "visible_fields": ["配置类型", "应用表格", "任务环节", "默认槽位", "状态", "生效来源", "供应商", "模型名称", "画面尺寸", "画面比例", "AI参数JSON", "提示词", "备注"],
            "filter": {"logic": "and", "conditions": [["配置类型", "intersects", ["任务默认"]]]},
        },
        MODEL_CATALOG_VIEW_NAME: {
            "visible_fields": MODEL_CATALOG_VISIBLE_FIELDS,
            "filter": {"logic": "and", "conditions": [["配置类型", "intersects", ["模型目录"]]]},
        },
        "05-自动审核开关": {
            "visible_fields": ["配置类型", "环节", "状态", "备注"],
            "filter": {"logic": "and", "conditions": [["配置类型", "intersects", ["自动审核"]]]},
        },
        "99-排错全字段": {
            "visible_fields": all_fields,
            "filter": {"conditions": []},
        },
    }


def redacted_json(data: Any) -> str:
    return json.dumps(redact_public_output(data), ensure_ascii=False, indent=2, sort_keys=True)


def redact_public_output(data: Any) -> Any:
    if isinstance(data, dict):
        redacted = {}
        for key, value in data.items():
            safe_key = "base_id" if key == "base_token" else key
            redacted[safe_key] = redact_public_output(value)
        return redacted
    if isinstance(data, list):
        return [redact_public_output(item) for item in data]
    if isinstance(data, str):
        if data in SECRET_FIELD_NAMES:
            return "[REDACTED_SECRET_FIELD]"
        return data.replace("API Key", "[REDACTED_SECRET_FIELD]")
    return data


def list_fields(token: str) -> List[Dict[str, Any]]:
    data = safe_request(
        "get",
        f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_CONFIG}/fields?page_size=200",
        headers=feishu_headers(token),
        timeout=30,
        max_attempts=3,
        acceptable_codes=(0,),
    )
    return (data.get("data") or {}).get("items") or []


def create_missing_config_fields(base_token: str, existing_field_names: Sequence[str], *, dry_run: bool) -> List[Dict[str, Any]]:
    existing = set(existing_field_names)
    results = []
    for spec in CONFIG_FIELD_SPECS:
        name = spec["name"]
        if name in existing:
            results.append({"field_name": name, "status": "exists"})
            continue
        if not dry_run:
            run_json([
                "lark-cli", "base", "+field-create",
                "--base-token", base_token,
                "--table-id", TABLE_CONFIG,
                "--json", json.dumps(spec, ensure_ascii=False),
            ])
        existing.add(name)
        results.append({"field_name": name, "status": "dry_run" if dry_run else "created"})
    return results


def list_views(token: str) -> List[Dict[str, Any]]:
    data = safe_request(
        "get",
        f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_CONFIG}/views?page_size=200",
        headers=feishu_headers(token),
        timeout=30,
        max_attempts=3,
        acceptable_codes=(0,),
    )
    return (data.get("data") or {}).get("items") or []


def list_tables(token: str) -> List[Dict[str, Any]]:
    data = safe_request(
        "get",
        f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables?page_size=100",
        headers=feishu_headers(token),
        timeout=30,
        max_attempts=3,
        acceptable_codes=(0,),
    )
    return (data.get("data") or {}).get("items") or []


def list_fields_for_table(token: str, table_id: str) -> List[Dict[str, Any]]:
    data = safe_request(
        "get",
        f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/fields?page_size=200",
        headers=feishu_headers(token),
        timeout=30,
        max_attempts=3,
        acceptable_codes=(0,),
    )
    return (data.get("data") or {}).get("items") or []


def list_views_for_table(token: str, table_id: str) -> List[Dict[str, Any]]:
    data = safe_request(
        "get",
        f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/views?page_size=200",
        headers=feishu_headers(token),
        timeout=30,
        max_attempts=3,
        acceptable_codes=(0,),
    )
    return (data.get("data") or {}).get("items") or []


def run_json(argv: Sequence[str]) -> Dict[str, Any]:
    command = list(argv)
    proc = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output = (proc.stdout or proc.stderr or "").strip()
    if proc.returncode != 0:
        raise RuntimeError(f"command failed rc={proc.returncode}: {' '.join(command)}\n{output}")
    if not output:
        return {}
    return json.loads(output)


def existing_view_map(views: Sequence[Mapping[str, Any]]) -> Dict[str, str]:
    mapping = {}
    for item in views:
        name = item.get("view_name") or item.get("name")
        view_id = item.get("view_id") or item.get("id")
        if name and view_id:
            mapping[str(name)] = str(view_id)
    return mapping


def ensure_view(base_token: str, view_name: str, view_id_by_name: Dict[str, str]) -> str:
    existing = view_id_by_name.get(view_name)
    if existing:
        return existing
    data = run_json([
        "lark-cli", "base", "+view-create",
        "--base-token", base_token,
        "--table-id", TABLE_CONFIG,
        "--json", json.dumps({"name": view_name, "type": "grid"}, ensure_ascii=False),
    ])
    view = (data.get("data") or {}).get("view") or {}
    view_id = view.get("id") or view.get("view_id")
    if not view_id:
        refreshed = existing_view_map(list_views(get_feishu_token()))
        view_id = refreshed.get(view_name)
    if not view_id:
        raise RuntimeError(f"创建视图后未返回 view_id: {view_name}")
    view_id_by_name[view_name] = view_id
    return str(view_id)


def configure_view(base_token: str, view_id: str, definition: Mapping[str, Any]) -> None:
    for command, payload in [
        ("+view-set-visible-fields", {"visible_fields": definition["visible_fields"]}),
        ("+view-set-filter", definition.get("filter") or {"conditions": []}),
    ]:
        for attempt in range(4):
            try:
                run_json([
                    "lark-cli", "base", command,
                    "--base-token", base_token,
                    "--table-id", TABLE_CONFIG,
                    "--view-id", view_id,
                    "--json", json.dumps(payload, ensure_ascii=False),
                ])
                break
            except RuntimeError as exc:
                text = str(exc)
                if "800070003" in text or "no operation produced" in text:
                    break
                if "800004135" not in text or attempt == 3:
                    raise
                time.sleep(2 + attempt * 2)


def cli_list_views(base_token: str) -> List[Dict[str, Any]]:
    data = run_json([
        "lark-cli", "base", "+view-list",
        "--base-token", base_token,
        "--table-id", TABLE_CONFIG,
        "--format", "json",
    ])
    payload = data.get("data") or {}
    views = payload.get("views") or payload.get("items") or []
    return views if isinstance(views, list) else []


def visible_field_count_from_view(view: Mapping[str, Any]) -> Optional[int]:
    meta = view.get("_meta") if isinstance(view.get("_meta"), Mapping) else {}
    raw = meta.get("visible_fields") or view.get("visible_fields") or view.get("field_count")
    if isinstance(raw, int):
        return raw
    if isinstance(raw, list):
        return len(raw)
    if isinstance(raw, str):
        match = re.search(r"\d+", raw)
        if match:
            return int(match.group(0))
    return None


def view_visible_field_count(base_token: str, view_name: str) -> Optional[int]:
    for view in cli_list_views(base_token):
        name = view.get("view_name") or view.get("name")
        if name == view_name:
            return visible_field_count_from_view(view)
    return None


def view_needs_visible_field_rebuild(view_name: str, definition: Mapping[str, Any], visible_field_count: Optional[int]) -> bool:
    if view_name != MODEL_CATALOG_VIEW_NAME or visible_field_count is None:
        return False
    expected_max = len(definition["visible_fields"]) + FORCED_PRIMARY_FIELD_ALLOWANCE
    return visible_field_count > expected_max


def rebuild_view_definition(
    base_token: str,
    view_name: str,
    definition: Mapping[str, Any],
    view_id_by_name: Dict[str, str],
) -> Dict[str, Any]:
    old_view_id = view_id_by_name.get(view_name)
    if not old_view_id:
        raise RuntimeError(f"重建视图前未找到 view_id: {view_name}")

    archived_name = f"{view_name}-旧字段全量待删除-{dt.datetime.now().strftime('%Y%m%d%H%M%S')}"
    run_json([
        "lark-cli", "base", "+view-rename",
        "--base-token", base_token,
        "--table-id", TABLE_CONFIG,
        "--view-id", old_view_id,
        "--name", archived_name,
    ])
    view_id_by_name.pop(view_name, None)
    view_id_by_name[archived_name] = old_view_id

    new_view_id = ensure_view(base_token, view_name, view_id_by_name)
    configure_view(base_token, new_view_id, definition)
    visible_field_count = view_visible_field_count(base_token, view_name)
    if view_needs_visible_field_rebuild(view_name, definition, visible_field_count):
        raise RuntimeError(f"{view_name} 重建后仍显示 {visible_field_count} 个字段")

    run_json([
        "lark-cli", "base", "+view-delete",
        "--base-token", base_token,
        "--table-id", TABLE_CONFIG,
        "--view-id", old_view_id,
        "--yes",
    ])
    view_id_by_name.pop(archived_name, None)
    return {
        "view_id": new_view_id,
        "visible_field_count": visible_field_count,
        "replaced_view_id": old_view_id,
        "archived_view_name": archived_name,
    }


def apply_view_definitions(base_token: str, views: Mapping[str, Mapping[str, Any]], *, dry_run: bool) -> List[Dict[str, Any]]:
    existing = existing_view_map(list_views(get_feishu_token())) if not dry_run else {}
    results = []
    for view_name, definition in views.items():
        view_id = existing.get(view_name, f"dry-run:{view_name}")
        visible_field_count = None
        status = "dry_run" if dry_run else "updated"
        rebuild = None
        if not dry_run:
            view_id = ensure_view(base_token, view_name, existing)
            configure_view(base_token, view_id, definition)
            visible_field_count = view_visible_field_count(base_token, view_name)
            if view_needs_visible_field_rebuild(view_name, definition, visible_field_count):
                rebuild = rebuild_view_definition(base_token, view_name, definition, existing)
                view_id = rebuild["view_id"]
                visible_field_count = rebuild["visible_field_count"]
                status = "rebuilt"
        results.append({
            "view_name": view_name,
            "view_id": view_id,
            "visible_fields": definition["visible_fields"],
            "filter": definition.get("filter") or {"conditions": []},
            "visible_field_count": visible_field_count,
            "rebuild": rebuild,
            "status": status,
        })
    return results


def rename_legacy_config_table(base_token: str, *, dry_run: bool) -> Dict[str, Any]:
    current_name = ""
    for table in list_tables(get_feishu_token()):
        table_id = table.get("table_id") or table.get("id")
        if table_id == TABLE_CONFIG:
            current_name = str(table.get("name") or table.get("table_name") or "")
            break
    if not dry_run and current_name != LEGACY_CONFIG_TABLE_NAME:
        run_json([
            "lark-cli", "base", "+table-update",
            "--base-token", base_token,
            "--table-id", TABLE_CONFIG,
            "--name", LEGACY_CONFIG_TABLE_NAME,
        ])
    return {
        "table_id": TABLE_CONFIG,
        "from": current_name or "dry-run/current-name-not-read",
        "to": LEGACY_CONFIG_TABLE_NAME,
        "status": "dry_run" if dry_run else ("unchanged" if current_name == LEGACY_CONFIG_TABLE_NAME else "renamed"),
    }


def ensure_unified_config_table_name(base_token: str, *, dry_run: bool) -> Dict[str, Any]:
    current_name = ""
    for table in list_tables(get_feishu_token()):
        table_id = table.get("table_id") or table.get("id")
        if table_id == TABLE_CONFIG:
            current_name = str(table.get("name") or table.get("table_name") or "")
            break
    if not dry_run and current_name and current_name != UNIFIED_CONFIG_TABLE_NAME:
        run_json([
            "lark-cli", "base", "+table-update",
            "--base-token", base_token,
            "--table-id", TABLE_CONFIG,
            "--name", UNIFIED_CONFIG_TABLE_NAME,
        ])
    return {
        "table_id": TABLE_CONFIG,
        "from": current_name or "unknown",
        "to": UNIFIED_CONFIG_TABLE_NAME,
        "status": "dry_run" if dry_run else ("unchanged" if current_name == UNIFIED_CONFIG_TABLE_NAME else "renamed"),
    }


def rename_legacy_views(base_token: str, *, dry_run: bool) -> List[Dict[str, Any]]:
    existing = existing_view_map(list_views(get_feishu_token()))
    results = []
    for old_name, new_name in LEGACY_CONFIG_VIEW_RENAMES.items():
        view_id = existing.get(old_name)
        if not view_id:
            results.append({"from": old_name, "to": new_name, "status": "missing"})
            continue
        if not dry_run:
            run_json([
                "lark-cli", "base", "+view-rename",
                "--base-token", base_token,
                "--table-id", TABLE_CONFIG,
                "--view-id", view_id,
                "--name", new_name,
            ])
        results.append({
            "from": old_name,
            "to": new_name,
            "view_id": view_id,
            "status": "dry_run" if dry_run else "renamed",
        })
    return results


def delete_obsolete_views(base_token: str, *, dry_run: bool) -> List[Dict[str, Any]]:
    results = []
    names_by_table = {table_id: set(names) for table_id, names in OBSOLETE_VIEWS_BY_TABLE.items()}
    names_by_table.setdefault(TABLE_CONFIG, set()).update(OBSOLETE_VIEW_NAMES)
    token = get_feishu_token()
    for table_id, names in sorted(names_by_table.items()):
        existing = existing_view_map(list_views_for_table(token, table_id))
        for view_name in sorted(names):
            view_id = existing.get(view_name)
            if not view_id:
                continue
            if not dry_run:
                run_json([
                    "lark-cli", "base", "+view-delete",
                    "--base-token", base_token,
                    "--table-id", table_id,
                    "--view-id", view_id,
                    "--yes",
                ])
            results.append({
                "table_id": table_id,
                "view_name": view_name,
                "view_id": view_id,
                "status": "dry_run" if dry_run else "deleted",
            })
    return results


def delete_migrated_fields(base_token: str, *, dry_run: bool) -> List[Dict[str, Any]]:
    fields = list_fields_for_table(get_feishu_token(), TABLE_CONFIG)
    by_name = {
        str(item.get("field_name") or item.get("name") or ""): str(item.get("field_id") or item.get("id") or "")
        for item in fields
    }
    results = []
    for field_name in sorted(MIGRATED_FIELD_NAMES):
        field_id = by_name.get(field_name)
        if not field_id:
            results.append({"field_name": field_name, "status": "missing"})
            continue
        if not dry_run:
            run_json([
                "lark-cli", "base", "+field-delete",
                "--base-token", base_token,
                "--table-id", TABLE_CONFIG,
                "--field-id", field_id,
                "--yes",
            ])
        results.append({"field_name": field_name, "field_id": field_id, "status": "dry_run" if dry_run else "deleted"})
    return results


def write_backup(path: Path, snapshot: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(redacted_json(snapshot) + "\n", encoding="utf-8")


def apply_record_updates(token: str, updates: Sequence[RecordUpdate], *, dry_run: bool) -> List[Dict[str, Any]]:
    results = []
    for update in updates:
        if not dry_run:
            safe_update_record(token, TABLE_CONFIG, update.record_id, update.fields)
        results.append({
            "record_id": update.record_id,
            "category": update.category,
            "fields": update.fields,
            "status": "dry_run" if dry_run else "updated",
        })
    return results


def _key_source_signature(fields: Mapping[str, Any]) -> str:
    api_base = _text(fields, "API 代理地址").rstrip("/")
    call_type = _text(fields, "调用方式")
    if not api_base and not call_type:
        return ""
    return f"{api_base}|{call_type}"


def _iter_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _iter_strings(item)
    elif isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray)):
        for item in value:
            yield from _iter_strings(item)


def configured_record_ids(config_records: Mapping[str, Any]) -> Set[str]:
    return {item for item in _iter_strings(config_records) if item.startswith("rec")}


def task_default_source_record_ids(records: Sequence[Mapping[str, Any]]) -> Set[str]:
    source_ids: Set[str] = set()
    for record in records:
        for value in _fields(record).values():
            for text in _iter_strings(value):
                source_ids.update(re.findall(r"source_record_id=([A-Za-z0-9_]+)", text))
    return source_ids


def production_code_reference_stages(stages: Sequence[str], *, root: Optional[Path] = None) -> Set[str]:
    if not stages:
        return set()
    root = root or Path(__file__).resolve().parent
    remaining = {stage for stage in stages if stage}
    referenced: Set[str] = set()
    for path in root.glob("*.py"):
        if not remaining:
            break
        if path.name == Path(__file__).name or path.name.startswith("test_"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        matched = {stage for stage in remaining if stage in text}
        referenced.update(matched)
        remaining.difference_update(matched)
    return referenced


def build_delete_audit(
    records: Sequence[Mapping[str, Any]],
    task_default_records: Sequence[Mapping[str, Any]],
    *,
    config_record_ids: Optional[Set[str]] = None,
    code_referenced_stages: Optional[Set[str]] = None,
) -> DeleteAudit:
    config_record_ids = configured_record_ids(CONFIG_RECORDS) if config_record_ids is None else config_record_ids
    task_default_sources = task_default_source_record_ids(task_default_records)
    candidate_stages = [
        _text(_fields(record), "环节")
        for record in records
        if _text(_fields(record), "状态") == "停用" and _text(_fields(record), "环节").startswith("统一AI预设-")
    ]
    code_referenced_stages = production_code_reference_stages(candidate_stages) if code_referenced_stages is None else code_referenced_stages
    active_key_signatures = {
        _key_source_signature(_fields(record))
        for record in records
        if _text(_fields(record), "状态") in {"启用", "测试中"} and _has_api_key(_fields(record))
    }
    active_key_signatures.discard("")

    candidates: List[DeleteAuditItem] = []
    skipped: List[DeleteAuditItem] = []
    for record in records:
        fields = _fields(record)
        rid = _record_id(record)
        stage = _text(fields, "环节")
        if not rid or _text(fields, "状态") != "停用" or not stage.startswith("统一AI预设-"):
            continue

        reason = ""
        if rid in task_default_sources:
            reason = "被任务默认配置引用"
        elif rid in config_record_ids:
            reason = "被 config_records 引用"
        elif stage in code_referenced_stages:
            reason = "被生产代码常量引用"
        elif _has_api_key(fields) and _key_source_signature(fields) not in active_key_signatures:
            reason = "停用记录含唯一密钥来源"

        item = DeleteAuditItem(
            record_id=rid,
            stage=stage,
            reason=reason or "安全删除：停用旧统一AI预设，无引用且密钥来源可替代",
            api_key_status=_api_key_status(fields),
        )
        if reason:
            skipped.append(item)
        else:
            candidates.append(item)

    return DeleteAudit(candidates=candidates, skipped=skipped)


def delete_audited_records(base_token: str, candidates: Sequence[DeleteAuditItem], *, dry_run: bool) -> List[Dict[str, Any]]:
    if not candidates:
        return []
    record_ids = [item.record_id for item in candidates]
    if not dry_run:
        argv = [
            "lark-cli", "base", "+record-delete",
            "--base-token", base_token,
            "--table-id", TABLE_CONFIG,
        ]
        for record_id in record_ids:
            argv.extend(["--record-id", record_id])
        argv.append("--yes")
        run_json(argv)
    return [
        {
            "record_id": item.record_id,
            "stage": item.stage,
            "reason": item.reason,
            "api_key_status": item.api_key_status,
            "status": "dry_run_delete" if dry_run else "deleted",
        }
        for item in candidates
    ]


def run_cleanup(*, write: bool, backup_path: Path) -> Dict[str, Any]:
    token = get_feishu_token()
    fields = list_fields(token)
    views = list_views(token)
    records = safe_list_records(token, TABLE_CONFIG)
    field_names = [item.get("field_name") or item.get("name") for item in fields if item.get("field_name") or item.get("name")]
    field_results = create_missing_config_fields(APP_TOKEN, field_names, dry_run=not write)
    effective_field_names = list(field_names)
    for result in field_results:
        if result["field_name"] not in effective_field_names:
            effective_field_names.append(result["field_name"])
    plan = build_cleanup_plan(records)
    view_definitions = build_view_definitions(effective_field_names)
    backup = build_backup_snapshot(fields=fields, views=views, records=records)
    write_backup(backup_path, backup)
    writable_fields = set(effective_field_names)
    record_fields_by_id = {_record_id(record): _fields(record) for record in records}
    filtered_updates = [
        RecordUpdate(
            record_id=update.record_id,
            category=update.category,
            fields={key: value for key, value in update.fields.items() if key in writable_fields},
        )
        for update in plan.record_updates
    ]
    filtered_updates = [
        update
        for update in filtered_updates
        if update.fields and not _same_patch(record_fields_by_id.get(update.record_id, {}), update.fields)
    ]
    record_results = apply_record_updates(token, filtered_updates, dry_run=not write)
    delete_audit = build_delete_audit(records, [])
    view_rename_results = rename_legacy_views(APP_TOKEN, dry_run=not write)
    table_name_result = ensure_unified_config_table_name(APP_TOKEN, dry_run=not write)
    view_results = apply_view_definitions(APP_TOKEN, view_definitions, dry_run=not write)
    obsolete_view_results = delete_obsolete_views(APP_TOKEN, dry_run=not write)
    return {
        "mode": "write" if write else "dry_run",
        "backup_path": str(backup_path),
        "summary": plan.summary,
        "record_updates": record_results,
        "delete_audit": delete_audit.to_public_dict(),
        "deleted_records": [],
        "fields": field_results,
        "legacy_table": {"table_id": TABLE_CONFIG, "status": "not_touched"},
        "config_table_name": table_name_result,
        "model_catalog_options": [],
        "video_edit_catalog": {"status": "not_touched"},
        "task_default_app_table_field": {"status": "not_touched"},
        "video_edit_default": {"status": "not_touched"},
        "legacy_view_renames": view_rename_results,
        "views": view_results,
        "obsolete_views": obsolete_view_results,
        "migrated_fields": [],
        "business_tables_touched": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="整理初始化-模型与API配置表：视图 + 归档")
    parser.add_argument("--write", action="store_true", help="实际写入飞书；默认只 dry-run")
    parser.add_argument("--backup-path", default=str(BACKUP_PATH))
    args = parser.parse_args()
    result = run_cleanup(write=args.write, backup_path=Path(args.backup_path))
    print(redacted_json(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
