#!/usr/bin/env python3
"""Rebind a local config file to a copied Feishu Base.

The first-time colleague setup path is:
1. Copy the production Base in Feishu UI.
2. Put the copied Base token and Feishu app credentials in config.local.json.
3. Run this script to rewrite table_id and config record_id values for that copy.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping

import requests


TABLE_ALIASES: Dict[str, List[str]] = {
    "config": ["初始化-模型与API配置", "模型与API配置"],
    "voice_library": ["初始化-音色库", "音色库"],
    "text_audio": ["初始化-口播音频生成", "文案转音频表", "文案音频生成表"],
    "product": ["初始化-产品信息", "产品信息"],
    "model_appearance": ["初始化-模特形象", "模特形象"],
    "script_doc_tasks": ["003-1脚本文档-任务表", "脚本文档-任务表"],
    "script_doc_reference_assets": ["003-2脚本文档-参考资产表", "脚本文档-参考资产表"],
    "script_doc_shots": ["003-3脚本文档-分镜生产表", "脚本文档-分镜生产表"],
    "script_doc_unified": ["003-脚本文档生产表"],
    "first_last_video": ["002-首尾帧视频生成表", "首尾帧视频生成表"],
    "multi_role_first_last": ["001-多角色首尾帧生成表", "多角色首尾帧生成表"],
    "nine_grid_video": ["005-多图九宫格视频生成表", "多图九宫格视频生成表"],
    "video_edit": ["006-视频编辑任务表"],
}

CONFIG_RECORD_STAGES: Dict[str, str] = {
    "script_doc_text_split": "脚本文档结构化拆分-Gemini",
    "main_image_otu": "图片生成-OTU",
}


def read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def extract_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(item.get("text", "") if isinstance(item, dict) else str(item) for item in value)
    return str(value) if value else ""


def first_match(aliases: Iterable[str], items_by_name: Mapping[str, str]) -> str:
    for name in aliases:
        value = items_by_name.get(name)
        if value:
            return value
    return ""


def rebind_config_data(
    config: Mapping[str, Any],
    tables_by_name: Mapping[str, str],
    config_records_by_stage: Mapping[str, str],
) -> Dict[str, Any]:
    updated = copy.deepcopy(dict(config))
    tables = updated.setdefault("feishu", {}).setdefault("tables", {})
    config_records = updated.setdefault("config_records", {})

    missing_tables: List[str] = []
    resolved_tables: Dict[str, str] = {}
    for key, aliases in TABLE_ALIASES.items():
        table_id = first_match(aliases, tables_by_name)
        if table_id:
            tables[key] = table_id
            resolved_tables[key] = table_id
        else:
            missing_tables.append(key)

    missing_config_records: List[str] = []
    resolved_config_records: Dict[str, str] = {}
    for key, stage in CONFIG_RECORD_STAGES.items():
        record_id = config_records_by_stage.get(stage, "")
        if record_id:
            config_records[key] = record_id
            resolved_config_records[key] = record_id
        else:
            missing_config_records.append(key)

    cleared_products = bool(updated.get("products"))
    updated["products"] = {}

    return {
        "ready": not missing_tables and not missing_config_records,
        "config": updated,
        "resolved_tables": resolved_tables,
        "resolved_config_records": resolved_config_records,
        "missing_tables": missing_tables,
        "missing_config_records": missing_config_records,
        "cleared_products": cleared_products,
    }


def get_tenant_token(app_id: str, app_secret: str) -> str:
    resp = requests.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": app_id, "app_secret": app_secret},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    token = data.get("tenant_access_token")
    if not token:
        raise RuntimeError(f"获取飞书 tenant_access_token 失败: code={data.get('code')} msg={data.get('msg')}")
    return token


def feishu_headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def list_tables(base_token: str, tenant_token: str) -> Dict[str, str]:
    items: Dict[str, str] = {}
    page_token = ""
    while True:
        params = {"page_size": 100}
        if page_token:
            params["page_token"] = page_token
        resp = requests.get(
            f"https://open.feishu.cn/open-apis/bitable/v1/apps/{base_token}/tables",
            headers=feishu_headers(tenant_token),
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"读取 Base 表列表失败: code={data.get('code')} msg={data.get('msg')}")
        payload = data.get("data") or {}
        for item in payload.get("items") or []:
            name = item.get("name") or item.get("table_name")
            table_id = item.get("table_id") or item.get("id")
            if name and table_id:
                items[name] = table_id
        if not payload.get("has_more"):
            break
        page_token = payload.get("page_token") or ""
    return items


def list_config_records(base_token: str, table_id: str, tenant_token: str) -> Dict[str, str]:
    items: Dict[str, str] = {}
    page_token = ""
    while True:
        params = {"page_size": 100}
        if page_token:
            params["page_token"] = page_token
        resp = requests.get(
            f"https://open.feishu.cn/open-apis/bitable/v1/apps/{base_token}/tables/{table_id}/records",
            headers=feishu_headers(tenant_token),
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"读取模型配置记录失败: code={data.get('code')} msg={data.get('msg')}")
        payload = data.get("data") or {}
        for item in payload.get("items") or []:
            fields = item.get("fields") or {}
            stage = extract_text(fields.get("环节")).strip()
            record_id = item.get("record_id") or item.get("id") or ""
            if stage and record_id:
                items[stage] = record_id
        if not payload.get("has_more"):
            break
        page_token = payload.get("page_token") or ""
    return items


def redacted_summary(result: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "ready": result["ready"],
        "resolved_tables": result["resolved_tables"],
        "resolved_config_records": result["resolved_config_records"],
        "missing_tables": result["missing_tables"],
        "missing_config_records": result["missing_config_records"],
        "cleared_products": result["cleared_products"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebind config.local.json to a copied Feishu Base")
    parser.add_argument("--config", default=str(Path(__file__).resolve().parent / "config.local.json"))
    parser.add_argument("--write", action="store_true", help="write discovered ids back to the config file")
    parser.add_argument("--dry-run", action="store_true", help="discover and print ids without writing; this is the default")
    args = parser.parse_args()

    config_path = Path(args.config)
    config = read_json(config_path)
    feishu = config.get("feishu") or {}
    base_token = str(feishu.get("bitable_app_token") or "").strip()
    app_id = str(feishu.get("app_id") or "").strip()
    app_secret = str(feishu.get("app_secret") or "").strip()
    if not base_token or not app_id or not app_secret:
        raise RuntimeError("config 缺少 feishu.app_id / app_secret / bitable_app_token")

    tenant_token = get_tenant_token(app_id, app_secret)
    tables_by_name = list_tables(base_token, tenant_token)
    config_table_id = first_match(TABLE_ALIASES["config"], tables_by_name)
    config_records_by_stage = list_config_records(base_token, config_table_id, tenant_token) if config_table_id else {}
    result = rebind_config_data(config, tables_by_name, config_records_by_stage)

    if args.write:
        if not result["ready"]:
            raise RuntimeError("发现缺失项，拒绝写回；请先补齐复制 Base: " + json.dumps(redacted_summary(result), ensure_ascii=False))
        write_json(config_path, result["config"])

    print(json.dumps(redacted_summary(result), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
