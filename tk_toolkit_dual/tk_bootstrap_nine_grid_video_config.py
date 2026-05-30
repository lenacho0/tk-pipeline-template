#!/usr/bin/env python3
"""补齐多图九宫格视频生成的模型配置记录。"""
from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import APP_TOKEN, TABLE_CONFIG, feishu_headers, get_feishu_token, safe_list_records, safe_request  # noqa: E402
from tk_nine_grid_video import IMAGE_STAGE_NAME, PLAN_STAGE_NAME, VIDEO_STAGE_NAME  # noqa: E402
from tk_nine_grid_video_prompt import (  # noqa: E402
    NINE_GRID_IMAGE_SYSTEM_PROMPT,
    NINE_GRID_PLAN_SYSTEM_PROMPT,
    NINE_GRID_VIDEO_SYSTEM_PROMPT,
)


def extract_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(item.get("text", "") if isinstance(item, dict) else str(item) for item in value)
    return str(value) if value else ""


def build_wanted_config_records() -> List[Dict[str, Any]]:
    return [
        {
            "环节": PLAN_STAGE_NAME,
            "模型名称": "gemini-3.1-pro-preview",
            "AI供应商": "AIHubMix",
            "AI能力类型": "文本",
            "AI任务类型": "脚本解析拆分",
            "AI参数JSON": "",
            "是否统一AI预设": "是",
            "API Key": "",
            "API 代理地址": "https://aihubmix.com/gemini",
            "调用方式": "Gemini 原生 SDK",
            "状态": "测试中",
            "提示词": NINE_GRID_PLAN_SYSTEM_PROMPT,
            "备注": "多图九宫格方案生成提示词真源；API Key 复用正式文本模型配置或由记录字段路由选择。",
        },
        {
            "环节": IMAGE_STAGE_NAME,
            "模型名称": "gpt-image-2",
            "AI供应商": "OTU",
            "AI能力类型": "图片",
            "AI任务类型": "图生图/参考图重绘",
            "AI参数JSON": json.dumps({"size": "720x1280", "aspect_ratio": "9:16"}, ensure_ascii=False),
            "是否统一AI预设": "是",
            "API Key": "",
            "API 代理地址": "https://otuapi.com",
            "画面尺寸": "720x1280",
            "画面比例": "9:16",
            "调用方式": "专用 API",
            "状态": "测试中",
            "提示词": NINE_GRID_IMAGE_SYSTEM_PROMPT,
            "备注": "多图九宫格图片生成通用提示词；供应商和模型以记录字段或统一 AI 路由为准。",
        },
        {
            "环节": VIDEO_STAGE_NAME,
            "模型名称": "veo_3_1-fast-fl",
            "AI供应商": "OTU",
            "AI能力类型": "视频",
            "AI任务类型": "首帧图生视频",
            "AI参数JSON": json.dumps({"size": "720x1280", "aspect_ratio": "9:16", "seconds": "10"}, ensure_ascii=False),
            "是否统一AI预设": "是",
            "API Key": "",
            "API 代理地址": "https://otuapi.com",
            "画面尺寸": "720x1280",
            "画面比例": "9:16",
            "调用方式": "专用 API",
            "状态": "测试中",
            "提示词": NINE_GRID_VIDEO_SYSTEM_PROMPT,
            "备注": "多图九宫格视频生成通用提示词；供应商和模型以记录字段或统一 AI 路由为准。",
        },
    ]


def existing_stage_records(token: str) -> Dict[str, str]:
    records = {}
    for rec in safe_list_records(token, TABLE_CONFIG):
        stage = extract_text((rec.get("fields") or {}).get("环节")).strip()
        if stage:
            records[stage] = rec.get("record_id") or rec.get("id") or ""
    return records


def config_field_names(token: str) -> set:
    data = safe_request(
        "get",
        f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_CONFIG}/fields?page_size=100",
        headers=feishu_headers(token),
        timeout=30,
        max_attempts=3,
        acceptable_codes=(0,),
    )
    names = set()
    for item in (data.get("data") or {}).get("items", []) or []:
        name = item.get("field_name") or item.get("name")
        if name:
            names.add(name)
    return names


def create_config_record(token: str, fields: Dict[str, Any], existing_fields: set) -> str:
    filtered_fields = {key: value for key, value in fields.items() if key in existing_fields}
    data = safe_request(
        "post",
        f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_CONFIG}/records",
        headers=feishu_headers(token),
        json={"fields": filtered_fields},
        timeout=30,
        max_attempts=3,
        acceptable_codes=(0,),
    )
    record = (data.get("data") or {}).get("record") or {}
    return record.get("record_id") or record.get("id") or ""


def main() -> None:
    token = get_feishu_token()
    existing = existing_stage_records(token)
    existing_fields = config_field_names(token)
    created = []
    skipped = []
    for fields in build_wanted_config_records():
        stage = fields["环节"]
        if existing.get(stage):
            skipped.append({"stage": stage, "record_id": existing[stage]})
            continue
        record_id = create_config_record(token, fields, existing_fields)
        created.append({"stage": stage, "record_id": record_id})
    print(json.dumps({"created": created, "skipped": skipped}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
