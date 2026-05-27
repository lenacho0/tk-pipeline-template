#!/usr/bin/env python3
"""
补齐故事板图片/Omni 视频的模型配置记录。

API Key 从环境变量读取，避免写入仓库：
  STORYBOARD_VIDEO_OTU_API_KEY=... python3 tk_bootstrap_storyboard_video_config.py
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import APP_TOKEN, TABLE_CONFIG, feishu_headers, get_feishu_token, safe_list_records, safe_request  # noqa: E402


IMAGE_STAGE_NAME = "故事板图片生成-OTU"
OMNI_STAGE_NAME = "故事板视频生成-Omni"
DEFAULT_API_BASE = "https://otuapi.com"
DEFAULT_IMAGE_MODEL = "gpt-image-2"
DEFAULT_IMAGE_SIZE = "1024x1024"
DEFAULT_OMNI_MODEL = "omni_flash-10s"
DEFAULT_OMNI_SIZE = "1280x720"


def extract_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(item.get("text", "") if isinstance(item, dict) else str(item) for item in value)
    return str(value) if value else ""


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
    api_key = os.environ.get("STORYBOARD_VIDEO_OTU_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("缺少环境变量 STORYBOARD_VIDEO_OTU_API_KEY")
    token = get_feishu_token()
    existing = existing_stage_records(token)
    existing_fields = config_field_names(token)
    wanted: List[Dict[str, Any]] = [
        {
            "环节": IMAGE_STAGE_NAME,
            "模型名称": DEFAULT_IMAGE_MODEL,
            "API Key": api_key,
            "API 代理地址": DEFAULT_API_BASE,
            "画面尺寸": DEFAULT_IMAGE_SIZE,
            "画面比例": "16:9",
            "调用方式": "专用 API",
            "状态": "启用",
            "备注": "故事板制作板 16:9 图片生成配置；API Key 由本地脚本初始化写入。",
        },
        {
            "环节": OMNI_STAGE_NAME,
            "模型名称": DEFAULT_OMNI_MODEL,
            "API Key": api_key,
            "API 代理地址": DEFAULT_API_BASE,
            "画面尺寸": DEFAULT_OMNI_SIZE,
            "画面比例": "16:9",
            "调用方式": "专用 API",
            "状态": "启用",
            "备注": "Omni 10s 故事板图生视频配置；模型固定 omni_flash-10s，横屏尺寸由代码默认 1280x720。",
        },
    ]
    created = []
    skipped = []
    for fields in wanted:
        stage = fields["环节"]
        if existing.get(stage):
            skipped.append({"stage": stage, "record_id": existing[stage]})
            continue
        record_id = create_config_record(token, fields, existing_fields)
        created.append({"stage": stage, "record_id": record_id})
    print(json.dumps({"created": created, "skipped": skipped}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
