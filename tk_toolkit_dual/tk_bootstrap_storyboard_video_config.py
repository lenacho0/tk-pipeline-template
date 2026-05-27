#!/usr/bin/env python3
"""
补齐故事板图片/Omni 视频的模型配置记录。

图片/视频 API Key 从环境变量读取，避免写入仓库：
  STORYBOARD_VIDEO_OTU_API_KEY=... python3 tk_bootstrap_storyboard_video_config.py

故事板图片提示词拆分只写入可编辑系统提示词，不需要 OTU API Key。
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import APP_TOKEN, TABLE_CONFIG, feishu_headers, get_feishu_token, safe_list_records, safe_request  # noqa: E402


SPLIT_STAGE_NAME = "故事板图片提示词拆分"
IMAGE_STAGE_NAME = "故事板图片生成-OTU"
OMNI_STAGE_NAME = "故事板视频生成-Omni"
DEFAULT_API_BASE = "https://otuapi.com"
DEFAULT_IMAGE_MODEL = "gpt-image-2"
DEFAULT_IMAGE_SIZE = "1024x1024"
DEFAULT_OMNI_MODEL = "omni_flash-10s"
DEFAULT_OMNI_SIZE = "1280x720"
DEFAULT_SPLIT_PROMPT = """
我已经确定了本次带货微短剧的镜头文本脚本。
【已定稿脚本内容指令】
我会上传或粘贴一段完整脚本。

请你仔细读取我上传的脚本内容，并将其无缝嵌入到以下【强制视觉网格排版】规则中。

要求：
1. 根据脚本实际时长，按“每张故事板约10秒”的节奏拆分成多张故事板图片提示词。
2. 多张故事板之间剧情必须连贯，镜头编号连续，人物、宠物、产品、场景、服装、道具必须保持一致。
3. 每张故事板都需要是一张独立的 16:9 横版分镜制作板。
4. 脚本中的画面内容仅嵌入英文内容。
5. 脚本中的对白/口播仅嵌入泰文内容。
6. 最终为我输出多段可直接用于生成剧情故事板图片的完整【英文】提示词。
7. 从完整脚本中自动提取 Storyboard 01 的核心冲突场景和黄金3秒/戏剧钩子。
8. 每个 image_prompt 都必须明确描述顶部表头区、中部素材/参考区、底部剧情分镜区；中部素材/参考区不得省略。

【强制视觉网格排版与约束】
整体画幅：16:9 横版，纯白背景。画面严格从上到下分为三个独立区块。

第一区块（顶部表头，横向占满全宽）：
最左侧大字加粗标题：“短视频带货分镜制作”。
右侧紧跟一个横向表格，表格内容需要根据 Storyboard 编号区分展示。
如果是 Storyboard 01，右侧横向表格必须包含：Storyboard 编号、Time Range、产品名称、目标人群、核心冲突场景、黄金3秒/戏剧钩子（文字使用红色高亮）。
如果是 Storyboard 02、Storyboard 03 或后续故事板，右侧横向表格只需要包含：Storyboard 编号、Time Range、产品名称、目标人群。
只有第一张故事板 Storyboard 01 需要出现“核心冲突场景”和“黄金3秒/戏剧钩子”。
从 Storyboard 02 开始，顶部表头中不得再出现“核心冲突场景”和“黄金3秒/戏剧钩子”这两个字段。

第二区块（中部素材区）：
中部素材区的排版必须根据实际脚本中出场的角色来决定，不要固定为三栏。
如果脚本中只有 1 个人物 + 宠物 + 产品：放置 1 个人物参考区、1 个宠物参考区、1 个产品参考区。
如果脚本中有 2 个人物 + 宠物 + 产品：放置 角色A参考区、角色B参考区、宠物参考区、产品参考区。
如果脚本中只有宠物 + 产品：放置 宠物参考区、产品参考区。
每个参考区根据实际对象展示：正面、面部/局部特写、服装或外观特征、产品正面和其它角度。

第三区块（底部剧情分镜区）：
根据当前 Storyboard 的 Time Range 展示连续剧情分镜面板。
剧情分镜中的画面描述、动作、场景、道具、视觉效果只允许使用英文。
对白/口播只允许使用泰文，并放在对应分镜画面下方或底部对白区域。
不要出现中文对白、中文剧情说明、英文对白翻译、无关字幕、UI、水印。

Return strict JSON only. Do not wrap it in Markdown.
Each storyboards[].image_prompt must be the complete final English prompt that can be sent directly to the image-generation API. Do not output partial structured fragments.
JSON schema:
{
  "storyboards": [
    {
      "storyboard_no": 1,
      "time_range": "0-10s",
      "image_prompt": "Complete final English image-generation prompt. It must include the top header section, the middle material/reference section, and the bottom story/dialogue section.",
      "video_prompt": "Prompt for generating a real video segment from this storyboard image and references"
    }
  ]
}
""".strip()


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
    token = get_feishu_token()
    existing = existing_stage_records(token)
    existing_fields = config_field_names(token)
    wanted: List[Dict[str, Any]] = [
        {
            "环节": SPLIT_STAGE_NAME,
            "调用方式": "复用 shot_script_gen 文本模型",
            "状态": "启用",
            "提示词": DEFAULT_SPLIT_PROMPT,
            "备注": "故事板图片提示词拆分系统提示词；模型/API 复用 shot_script_gen，可在此字段直接调整规则。",
        },
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
        if stage in {IMAGE_STAGE_NAME, OMNI_STAGE_NAME} and not api_key:
            skipped.append({"stage": stage, "reason": "missing STORYBOARD_VIDEO_OTU_API_KEY"})
            continue
        record_id = create_config_record(token, fields, existing_fields)
        created.append({"stage": stage, "record_id": record_id})
    print(json.dumps({"created": created, "skipped": skipped}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
