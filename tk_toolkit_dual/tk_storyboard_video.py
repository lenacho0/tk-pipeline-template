#!/usr/bin/env python3
"""
故事板图片 + Omni 图生视频生成。

用法:
  python3 tk_storyboard_video.py split <parent_record_id>
  python3 tk_storyboard_video.py image <storyboard_record_id>
  python3 tk_storyboard_video.py video <storyboard_record_id>
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import requests
from google import genai

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (  # noqa: E402
    APP_TOKEN,
    CONFIG_RECORDS,
    TABLE_CONFIG,
    TABLE_MODEL,
    TABLE_PRODUCT,
    TABLE_STORYBOARD_VIDEO,
    WORKSPACE,
    build_error_payload,
    extract_linked_record_ids,
    extract_text,
    feishu_headers,
    get_feishu_token,
    get_model_config,
    log_event,
    safe_get_record,
    safe_download_attachment,
    safe_list_records,
    safe_request,
    safe_update_record,
    upload_image_to_feishu,
    with_retry,
)
from otu_image import (  # noqa: E402
    DEFAULT_OTU_API_BASE,
    DEFAULT_OTU_IMAGE_MODEL,
    DEFAULT_OTU_IMAGE_SIZE,
    download_otu_image_result,
    extract_otu_result_url,
    normalize_image_model_choice,
    poll_otu_image_task,
    submit_otu_image_task,
)
from tk_shot_script_gen import extract_json_object  # noqa: E402
from tk_shot_storyboard import build_reference_urls, filter_existing_fields  # noqa: E402
from tk_shot_video import download_video, format_url_field_value, get_table_field_types, upload_video_to_feishu  # noqa: E402
from tk_storyboard_video_prompt import (  # noqa: E402
    STORYBOARD_IMAGE_PROMPT_SPLIT_SYSTEM_PROMPT,
    STORYBOARD_OMNI_VIDEO_PROMPT,
)
import ai_routing  # noqa: E402


SPLIT_STAGE_NAME = "故事板图片提示词拆分-Gemini"
IMAGE_STAGE_NAME = "故事板图片生成-OTU"
OMNI_STAGE_NAME = "故事板视频生成-Omni"
DEFAULT_OMNI_MODEL = "omni_flash-10s"
DEFAULT_OMNI_SIZE = "720x1280"
DEFAULT_OMNI_ASPECT_RATIO = "9:16"
DEFAULT_STORYBOARD_IMAGE_MODEL = DEFAULT_OTU_IMAGE_MODEL
DEFAULT_STORYBOARD_IMAGE_SIZE = "1280x720"
DEFAULT_STORYBOARD_IMAGE_ASPECT_RATIO = "16:9"
MAX_REFERENCE_IMAGES = 7
BASE_WORK_DIR = Path(WORKSPACE) / "storyboard_video_work"
POLL_INTERVAL = 15
MAX_POLL_SECONDS = 2400
SUBMIT_TIMEOUT = 180
POLL_TIMEOUT = 45


STORYBOARD_PROMPT_RULES = STORYBOARD_IMAGE_PROMPT_SPLIT_SYSTEM_PROMPT
OMNI_VIDEO_PROMPT_RULES = STORYBOARD_OMNI_VIDEO_PROMPT


def compact_json(value: Any, max_chars: int = 20000) -> str:
    text = json.dumps(value, ensure_ascii=False, indent=2, default=str)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 200] + "\n...TRUNCATED..."


def ensure_storyboard_table() -> None:
    if not TABLE_STORYBOARD_VIDEO:
        raise RuntimeError("config.json 尚未配置 storyboard_video 表 ID")


def ensure_work_dir(record_id: str) -> Path:
    work_dir = BASE_WORK_DIR / record_id
    work_dir.mkdir(parents=True, exist_ok=True)
    return work_dir


def _extract_attachment_token(value: Any) -> str:
    tokens = _extract_attachment_tokens(value)
    return tokens[0] if tokens else ""


def _extract_attachment_tokens(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    tokens: List[str] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        token = str(item.get("file_token") or "").strip()
        if token:
            tokens.append(token)
    return tokens


def _extract_link_ids(value: Any) -> List[str]:
    linked = extract_linked_record_ids(value)
    if linked:
        return linked
    if isinstance(value, list):
        return [str(item).strip() for item in value if isinstance(item, str) and item.strip()]
    return []


def _require_single_link(fields: Dict[str, Any], field_name: str, label: str) -> str:
    ids = _extract_link_ids(fields.get(field_name))
    if len(ids) != 1:
        raise ValueError(f"{field_name}必须选择 1 个{label}")
    return ids[0]


def _require_link_ids(fields: Dict[str, Any], field_name: str, label: str) -> List[str]:
    ids = _extract_link_ids(fields.get(field_name))
    if not ids:
        raise ValueError(f"{field_name}必须至少选择 1 个{label}")
    return ids


def _require_attachment_tokens(fields: Dict[str, Any], field_name: str, label: str) -> List[str]:
    tokens = _extract_attachment_tokens(fields.get(field_name))
    if not tokens:
        raise ValueError(f"{field_name}必须上传至少 1 张{label}")
    return tokens


def _first_text(fields: Dict[str, Any], names: Iterable[str]) -> str:
    for name in names:
        value = extract_text(fields.get(name)).strip()
        if value:
            return value
    return ""


def resolve_parent_reference_context(
    token: str,
    parent_fields: Dict[str, Any],
    *,
    get_record_fn: Callable[[str, str, str], Dict[str, Any]] = safe_get_record,
    product_table_id: str = TABLE_PRODUCT,
    model_table_id: str = TABLE_MODEL,
) -> Dict[str, Any]:
    product_record_id = _require_single_link(parent_fields, "关联产品记录", "产品")
    model_record_ids = _require_link_ids(parent_fields, "选择模特", "模特")
    environment_tokens = _require_attachment_tokens(parent_fields, "环境图", "环境参考图")
    product_fields = get_record_fn(token, product_table_id, product_record_id)

    product_tokens = _extract_attachment_tokens(product_fields.get("产品图片"))
    if not product_tokens:
        raise ValueError("产品记录缺少产品图片")

    characters: List[Dict[str, str]] = []
    for index, model_record_id in enumerate(model_record_ids, start=1):
        model_fields = get_record_fn(token, model_table_id, model_record_id)
        model_name = _first_text(model_fields, ["模特名称", "名称", "任务名称"]) or model_record_id
        photo_tokens = _extract_attachment_tokens(model_fields.get("模特照片"))
        if not photo_tokens:
            raise ValueError(f"模特记录 {model_name or model_record_id} 缺少模特照片")
        characters.append({
            "record_id": model_record_id,
            "name": model_name,
            "type": _first_text(model_fields, ["模特类型", "类型"]),
            "appearance": _first_text(model_fields, ["外观描述", "特殊标记", "品种", "毛色/肤色"]),
            "photo_token": photo_tokens[0],
            "index": str(index),
        })

    product_name = _first_text(product_fields, ["产品名称-zh", "产品名称-th", "产品", "产品名称", "产品名"])
    target_audience = _first_text(product_fields, ["目标用户", "目标人群"])
    return {
        "product_record_id": product_record_id,
        "model_record_id": model_record_ids[0],
        "model_record_ids": model_record_ids,
        "product_name": product_name,
        "target_audience": target_audience,
        "product_tokens": product_tokens,
        "characters": characters,
        "character_tokens": [character["photo_token"] for character in characters],
        "environment_tokens": environment_tokens,
    }


def build_character_reference_summary(characters: List[Dict[str, str]]) -> str:
    lines = []
    for index, character in enumerate(characters, start=1):
        name = character.get("name") or character.get("record_id") or f"Character {index}"
        model_type = character.get("type") or "unspecified"
        appearance = character.get("appearance") or "no extra appearance notes"
        lines.append(f"- Character {index}: name={name}; type={model_type}; appearance={appearance}")
    return "\n".join(lines)


def apply_parent_reference_snapshots(fields: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(fields)
    merged["产品名称"] = context.get("product_name", "")
    merged["目标人群"] = context.get("target_audience", "")
    merged["角色参考摘要"] = build_character_reference_summary(context.get("characters") or [])
    return merged


def parent_fields_with_reference_snapshots(token: str, parent_fields: Dict[str, Any]) -> Dict[str, Any]:
    context = resolve_parent_reference_context(token, parent_fields)
    return apply_parent_reference_snapshots(parent_fields, context)


def video_regeneration_reset_fields() -> Dict[str, Any]:
    return {
        "分镜视频": [],
        "分镜视频URL": None,
        "视频任务ID": "",
        "视频错误信息": "",
        "视频生成时间": None,
        "错误信息": "",
    }


def image_regeneration_reset_fields() -> Dict[str, Any]:
    fields = {
        "故事板图": [],
        "故事板图片任务ID": "",
        "故事板图片错误信息": "",
        "故事板图片生成时间": None,
    }
    fields.update(video_regeneration_reset_fields())
    fields["视频生成状态"] = "不触发"
    return fields


def _as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _downloaded_path(downloaded: Any, fallback: Path) -> str:
    if isinstance(downloaded, (str, os.PathLike)):
        return str(downloaded)
    return str(fallback)


def _strip_markdown_code_block(text: str) -> str:
    stripped = text.strip()
    blocks = re.findall(r"```[^\n`]*\n(.*?)```", stripped, flags=re.DOTALL)
    for block in blocks:
        if re.search(r"(?im)^\s*Storyboard\s+\d{1,2}\s+Prompt\s*:", block):
            return block.strip()
        if re.search(r"(?im)^\s*Omni\s+Video\s+Prompt\s*:", block):
            return block.strip()
    return stripped


def parse_omni_video_prompt_template(raw_prompt: str) -> str:
    prompt = _strip_markdown_code_block(raw_prompt or OMNI_VIDEO_PROMPT_RULES).strip()
    prompt = re.sub(r"(?im)^\s*Omni\s+Video\s+Prompt\s*:\s*", "", prompt, count=1).strip()
    return prompt or _strip_markdown_code_block(OMNI_VIDEO_PROMPT_RULES).strip()


def _fallback_time_range(storyboard_no: int) -> str:
    start = max(storyboard_no - 1, 0) * 10
    return f"{start}-{start + 10}s"


def _normalize_time_range(value: str) -> str:
    return re.sub(r"\s+", "", value.strip())


def extract_storyboard_time_range(storyboard_no: int, prompt: str) -> str:
    patterns = [
        r"(?i)\bTime\s*Range\s*[:：]\s*([0-9]+\s*-\s*[0-9]+\s*s)",
        r"[（(]\s*([0-9]+\s*-\s*[0-9]+\s*s)\s*[）)]",
    ]
    for pattern in patterns:
        match = re.search(pattern, prompt)
        if match:
            return _normalize_time_range(match.group(1))
    return _fallback_time_range(storyboard_no)


def parse_storyboard_markdown_payload(raw_text: str) -> List[Dict[str, Any]]:
    text = _strip_markdown_code_block(raw_text)
    heading_re = re.compile(r"(?im)^\s*Storyboard\s+(\d{1,2})\s+Prompt\s*:\s*$")
    matches = list(heading_re.finditer(text))
    if not matches:
        return []
    storyboards = []
    for idx, match in enumerate(matches):
        storyboard_no = int(match.group(1))
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        image_prompt = text[start:end].strip()
        if not image_prompt:
            raise ValueError(f"Storyboard {storyboard_no:02d} Prompt 内容为空")
        storyboards.append({
            "storyboard_no": storyboard_no,
            "time_range": extract_storyboard_time_range(storyboard_no, image_prompt),
            "image_prompt": image_prompt,
            "video_prompt": "",
        })
    return storyboards


def build_storyboard_prompt_generation_request(fields: Dict[str, Any], *, system_prompt: str = "") -> str:
    script = extract_text(fields.get("脚本内容")).strip()
    product_name = extract_text(fields.get("产品名称")).strip()
    target_audience = extract_text(fields.get("目标人群")).strip()
    character_summary = extract_text(fields.get("角色参考摘要")).strip()
    rules = extract_text(system_prompt).strip() or STORYBOARD_PROMPT_RULES
    return f"""
{rules}

【本次任务上下文】
- Product name: {product_name}
- Target audience: {target_audience}

【已选择人物/宠物参考】
{character_summary or "- No character reference summary was provided."}

Keep every selected human/pet character consistent across all storyboards. Do not merge, replace, omit, or casually change any selected character unless the script explicitly calls for a character to be off-screen.

【参考图优先于脚本文字外观】
本次任务的【关联产品记录】、【选择模特】和【环境图】是视觉身份的最高优先级来源。
如果脚本里的人物服装、发型、脸型、年龄感、产品瓶型、标签颜色、包装文字、场景家具或光线描述与参考图冲突，必须以参考图为准。
不得根据脚本自行改写人物服装、脸、发型、体型或宠物外观；只能写“same as the selected character reference image / same outfit as reference image”。
不得根据脚本自行改写产品瓶型、喷头、标签、颜色、logo、包装比例或文字；只能写“same exact product as the product reference image”。
角色A/角色B只是剧情身份，不得覆盖所选模特照片里的真实视觉身份。最终 Storyboard Prompt 中如需描述角色外观，必须绑定到参考图，而不是使用脚本文字发散。

【自动化预检硬性要求】
为确保下游图片生成不会遗漏版式，每段 Storyboard Prompt 必须原样包含以下文本：
- 【强制垫图指令】
- 顶部表头
- 中部素材区
- 固定环境参考区
- 核心分镜区
- 微剧情分镜
- 镜头网格
- 顶部栏
- 画面区
- 底部表格
- 时间轴
- 景别
- 运镜
- 画面内容
- 情绪
- 日常口语化对白

这些中文词是故事板图片中需要渲染的版式标签；画面描述仍使用英文，对白/口播仍使用泰文。

【完整脚本内容】
{script}
""".strip()


def normalize_storyboard_payload(payload: Any) -> Dict[str, Any]:
    data = payload
    if isinstance(payload, str):
        storyboards_from_markdown = parse_storyboard_markdown_payload(payload)
        if storyboards_from_markdown:
            data = {"storyboards": storyboards_from_markdown}
        else:
            data = extract_json_object(payload)
    if not isinstance(data, dict):
        raise ValueError("故事板拆分结果必须是 JSON 对象")
    storyboards = _as_list(data.get("storyboards"))
    if not storyboards:
        raise ValueError("故事板拆分结果缺少 storyboards")
    normalized = []
    for idx, item in enumerate(storyboards, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"storyboards[{idx}] 必须是对象")
        storyboard_no = int(item.get("storyboard_no") or idx)
        image_prompt = extract_text(item.get("image_prompt")).strip()
        if not image_prompt:
            raise ValueError(f"storyboards[{idx}] 缺少 image_prompt")
        validate_storyboard_image_prompt(storyboard_no, image_prompt)
        normalized.append({
            "storyboard_no": storyboard_no,
            "time_range": extract_text(item.get("time_range")).strip() or f"Storyboard {storyboard_no:02d}",
            "image_prompt": image_prompt,
            "video_prompt": extract_text(item.get("video_prompt")).strip(),
        })
    return {"storyboards": normalized}


def validate_storyboard_image_prompt(storyboard_no: int, image_prompt: str) -> None:
    missing = []
    if not _contains_any_marker(image_prompt, ("强制垫图指令",)):
        missing.append("强制垫图指令")
    if not _contains_any_marker(image_prompt, ("第一区块", "顶部表头", "top header", "section 1")):
        missing.append("顶部表头")
    has_material_zone = _contains_any_marker(image_prompt, (
        "中部素材区",
        "素材区",
        "人物参考区",
        "宠物参考区",
        "产品参考区",
        "middle material",
        "material/reference",
        "reference section",
        "reference area",
        "character reference",
        "pet reference",
        "product reference",
    ))
    if not has_material_zone:
        missing.append("素材区")
    if not _contains_any_marker(image_prompt, (
        "固定环境参考区",
        "环境参考",
        "固定场景",
        "environment reference",
        "fixed environment",
        "fixed scene",
    )):
        missing.append("固定环境参考区")
    if not _contains_any_marker(image_prompt, ("核心分镜区", "微剧情分镜", "core storyboard", "storyboard grid")):
        missing.append("核心分镜区")
    if not _contains_any_marker(image_prompt, ("镜头网格", "shot grid", "storyboard grid", "grid cells")):
        missing.append("镜头网格")
    if not _contains_any_marker(image_prompt, ("顶部栏", "top bar", "shot number and name")):
        missing.append("顶部栏")
    if not _contains_any_marker(image_prompt, ("画面区", "image area", "visual area", "storyboard illustration")):
        missing.append("画面区")
    if not _contains_any_marker(image_prompt, ("底部表格", "bottom table")):
        missing.append("底部表格")
    required_bottom_fields = (
        ("时间轴", ("时间轴", "timeline", "time axis")),
        ("景别", ("景别", "shot size", "shot scale", "shot type")),
        ("运镜", ("运镜", "camera movement", "camera motion")),
        ("画面内容", ("画面内容", "visual content", "scene content", "picture content")),
        ("情绪", ("情绪", "emotion", "emotional arc")),
        ("日常口语化对白", ("日常口语化对白", "colloquial dialogue", "everyday spoken dialogue", "daily colloquial dialogue")),
    )
    for field_name, markers in required_bottom_fields:
        if not _contains_any_marker(image_prompt, markers):
            missing.append(field_name)
    if storyboard_no == 1:
        if not _contains_any_marker(image_prompt, ("核心冲突场景", "core conflict", "conflict scene")):
            missing.append("核心冲突场景")
        if not _contains_any_marker(image_prompt, (
            "黄金3秒/戏剧钩子",
            "黄金3秒",
            "golden 3",
            "golden three",
            "3-second hook",
            "3s hook",
            "dramatic hook",
        )):
            missing.append("黄金3秒/戏剧钩子")
        if missing:
            raise ValueError(f"Storyboard 01 image_prompt 缺少: {', '.join(missing)}")
        return
    if missing:
        raise ValueError(f"Storyboard {storyboard_no:02d} image_prompt 缺少: {', '.join(missing)}")
    forbidden = []
    for labels in (
        ("核心冲突场景", "Core conflict scene", "Core conflict"),
        (
            "黄金3秒/戏剧钩子",
            "Golden 3-second / dramatic hook",
            "Golden 3-second dramatic hook",
            "Golden 3-second hook",
            "Golden 3s hook",
            "Dramatic hook",
        ),
    ):
        matched = _find_field_label(image_prompt, labels)
        if matched:
            forbidden.append(matched)
    if forbidden:
        raise ValueError(f"Storyboard {storyboard_no:02d} image_prompt 不应包含: {', '.join(forbidden)}")


def _contains_any_marker(text: str, markers: Iterable[str]) -> bool:
    text_lower = text.lower()
    return any(marker.lower() in text_lower for marker in markers)


def _find_field_label(text: str, labels: Iterable[str]) -> str:
    text_lower = text.lower()
    for label in labels:
        label_lower = label.lower()
        if f"{label_lower}:" in text_lower or f"{label_lower}：" in text_lower:
            return label
    return ""


def _prefixed_omni_model_value(model: str = DEFAULT_OMNI_MODEL) -> str:
    raw = extract_text(model).strip() or DEFAULT_OMNI_MODEL
    if " / " in raw:
        return raw
    return f"OTU / {raw}"


def build_child_storyboard_records(
    parent_fields: Dict[str, Any],
    payload: Dict[str, Any],
    *,
    parent_record_id: str,
    batch_id: str,
) -> List[Dict[str, Dict[str, Any]]]:
    records = []
    storyboards = payload.get("storyboards", [])
    total = len(storyboards)
    task_name = extract_text(parent_fields.get("任务名称")).strip() or f"故事板任务-{parent_record_id[-6:]}"
    inherited_route_fields = {
        name: parent_fields.get(name)
        for name in (
            "使用统一AI路由",
            "故事板图片AI模型",
            "故事板图片AI参数JSON",
            "视频AI模型",
            "视频AI参数JSON",
            "AI供应商",
            "AI能力类型",
            "AI任务类型",
            "AI模型",
            "AI参数JSON",
        )
        if parent_fields.get(name)
    }
    for item in storyboards:
        no = int(item["storyboard_no"])
        fields = {
            "记录类型": "Storyboard分段",
            "任务名称": f"{task_name}-Storyboard{no:02d}",
            "父任务记录ID": parent_record_id,
            "批次ID": batch_id,
            "关联产品记录": _extract_link_ids(parent_fields.get("关联产品记录")),
            "选择模特": _extract_link_ids(parent_fields.get("选择模特")),
            "Storyboard编号": no,
            "Time Range": item["time_range"],
            "故事板图片提示词": item["image_prompt"],
            "故事板图片模型": DEFAULT_STORYBOARD_IMAGE_MODEL,
            "故事板图片画面尺寸": DEFAULT_STORYBOARD_IMAGE_SIZE,
            "故事板图片画面比例": DEFAULT_STORYBOARD_IMAGE_ASPECT_RATIO,
            "故事板图片生成状态": "待生成",
            "视频提示词": item.get("video_prompt", ""),
            "Omni模型": DEFAULT_OMNI_MODEL,
            "Omni画面尺寸": DEFAULT_OMNI_SIZE,
            "Omni画面比例": DEFAULT_OMNI_ASPECT_RATIO,
            "视频生成状态": "不触发",
            "错误信息": "",
            **inherited_route_fields,
        }
        if total:
            fields["总故事板数"] = total
        records.append({"fields": fields})
    return records


def create_records(token: str, table_id: str, records: List[Dict[str, Dict[str, Any]]]) -> int:
    created = 0
    for i in range(0, len(records), 10):
        batch = records[i:i + 10]
        safe_request(
            "post",
            f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/records/batch_create",
            headers=feishu_headers(token),
            json={"records": batch},
            timeout=30,
            max_attempts=3,
            acceptable_codes=(0,),
        )
        created += len(batch)
    return created


def cleanup_child_storyboards(token: str, parent_record_id: str) -> int:
    deleted = 0
    for rec in safe_list_records(token, TABLE_STORYBOARD_VIDEO):
        fields = rec.get("fields", {})
        if extract_text(fields.get("父任务记录ID")).strip() != parent_record_id:
            continue
        if extract_text(fields.get("记录类型")).strip() != "Storyboard分段":
            continue
        safe_request(
            "delete",
            f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_STORYBOARD_VIDEO}/records/{rec['record_id']}",
            headers=feishu_headers(token),
            timeout=30,
            max_attempts=3,
            acceptable_codes=(0,),
        )
        deleted += 1
    return deleted


def get_text_generation_config(token: str) -> Dict[str, str]:
    record_id = CONFIG_RECORDS.get("storyboard_text_split")
    if not record_id:
        raise ValueError("config_records 缺少 storyboard_text_split")
    cfg = get_model_config(token, record_id)
    if not cfg.get("api_key"):
        raise ValueError(f"{SPLIT_STAGE_NAME} 缺少 API Key")
    prompt = extract_text(cfg.get("prompt")).strip()
    cfg["prompt"] = prompt or STORYBOARD_PROMPT_RULES
    cfg["prompt_record_id"] = record_id if prompt else ""
    return cfg


def split_storyboards(record_id: str, *, dry_run: bool = False, raw_model_output: Any = None) -> Dict[str, Any]:
    ensure_storyboard_table()
    token = get_feishu_token()
    fields = safe_get_record(token, TABLE_STORYBOARD_VIDEO, record_id)
    script = extract_text(fields.get("脚本内容")).strip()
    if not script:
        raise ValueError("脚本内容为空")
    context = resolve_parent_reference_context(token, fields)
    fields = apply_parent_reference_snapshots(fields, context)

    cfg = get_text_generation_config(token)
    prompt = build_storyboard_prompt_generation_request(fields, system_prompt=cfg.get("prompt") or STORYBOARD_PROMPT_RULES)
    config_records = safe_list_records(token, TABLE_CONFIG) if (not dry_run or ai_routing.record_wants_unified_route(fields)) else []
    use_unified_route = ai_routing.unified_route_enabled(fields, config_records)
    unified_route = None
    if use_unified_route:
        unified_route = ai_routing.route_from_slot(fields, "拆分", {
            **cfg,
            "provider": "AIHubMix",
            "capability": "文本",
            "task_type": "故事板提示词拆分",
            "model": cfg.get("model") or "AIHubMix / gemini-3.1-pro-preview",
        }, capability="文本", task_type="故事板提示词拆分")
    summary = {"record_id": record_id, "dry_run": dry_run, "prompt_chars": len(prompt)}
    if unified_route:
        summary["unified_ai_route"] = ai_routing.build_dry_run_summary(unified_route, prompt)
    if dry_run:
        summary["status"] = "dry_run_ready"
        return summary
    if unified_route and ai_routing.unified_route_dry_run_only(config_records):
        summary["status"] = "unified_ai_dry_run_ready"
        return summary

    safe_update_record(token, TABLE_STORYBOARD_VIDEO, record_id, filter_existing_fields(token, TABLE_STORYBOARD_VIDEO, {
        "拆分状态": "拆分中",
        "错误信息": "",
    }))

    if raw_model_output is None:
        if unified_route:
            result = with_retry(lambda: ai_routing.call_text_model(unified_route, prompt), max_attempts=3, label="unified storyboard prompt split")
            raw_model_output = result.text
        else:
            client = genai.Client(api_key=cfg["api_key"], http_options={"base_url": cfg.get("api_base") or "https://aihubmix.com/gemini"})
            response = with_retry(
                lambda: client.models.generate_content(model=cfg.get("model") or "gemini-2.5-flash", contents=[prompt]),
                max_attempts=3,
                label="storyboard prompt split",
            )
            raw_model_output = getattr(response, "text", "") or ""

    payload = normalize_storyboard_payload(raw_model_output)
    batch_id = f"STORYBOARD-{time.strftime('%Y%m%d%H%M%S')}-{record_id[-6:]}"
    child_records = build_child_storyboard_records(fields, payload, parent_record_id=record_id, batch_id=batch_id)
    deleted = cleanup_child_storyboards(token, record_id)
    create_records(token, TABLE_STORYBOARD_VIDEO, [
        {"fields": filter_existing_fields(token, TABLE_STORYBOARD_VIDEO, item["fields"])}
        for item in child_records
    ])
    safe_update_record(token, TABLE_STORYBOARD_VIDEO, record_id, filter_existing_fields(token, TABLE_STORYBOARD_VIDEO, {
        "记录类型": "母任务",
        "拆分状态": "成功",
        "拆分结果JSON": compact_json(payload, 10000),
        "总故事板数": len(child_records),
        "批次ID": batch_id,
        "错误信息": "",
    }))
    summary.update({
        "status": "success",
        "batch_id": batch_id,
        "deleted_children": deleted,
        "storyboard_count": len(child_records),
    })
    return summary


def get_stage_config(stage_name: str, *, default_model: str, default_api_base: str, default_size: str = "") -> Tuple[str, Dict[str, str]]:
    token = get_feishu_token()
    for rec in safe_list_records(token, TABLE_CONFIG):
        fields = rec.get("fields", {})
        if extract_text(fields.get("环节")).strip() != stage_name:
            continue
        cfg = {
            "model": extract_text(fields.get("模型名称")).strip() or default_model,
            "api_key": extract_text(fields.get("API Key")).strip(),
            "api_base": extract_text(fields.get("API 代理地址")).strip() or default_api_base,
            "size": extract_text(fields.get("画面尺寸")).strip() or default_size,
            "prompt": extract_text(fields.get("提示词")).strip(),
            "params": extract_text(fields.get("AI参数JSON")).strip(),
        }
        if not cfg["api_key"]:
            raise ValueError(f"{stage_name} 缺少 API Key")
        return rec.get("record_id") or rec.get("id") or "", cfg
    raise ValueError(f"找不到模型配置: {stage_name}")


def maybe_unified_media_summary(
    token: str,
    fields: Dict[str, Any],
    cfg: Dict[str, str],
    *,
    capability: str,
    task_type: str,
    model: str,
    slot_name: str,
    prompt: str,
    params: Dict[str, Any],
    reference_count: int,
) -> Optional[Dict[str, Any]]:
    if not ai_routing.record_wants_unified_route(fields):
        return None
    config_records = safe_list_records(token, TABLE_CONFIG)
    if not ai_routing.unified_route_enabled(fields, config_records):
        return None
    route = ai_routing.route_from_slot(fields, slot_name, {
        **cfg,
        "provider": "OTU",
        "capability": capability,
        "task_type": task_type,
        "model": f"OTU / {model}",
        "params": params,
    }, capability=capability, task_type=task_type)
    return ai_routing.build_media_request_summary(route, prompt, reference_count=reference_count)


def collect_parent_reference_images(
    token: str,
    parent_fields: Dict[str, Any],
    task_dir: Path,
    *,
    max_count: int = MAX_REFERENCE_IMAGES,
    download_fn: Callable[[str, str, str], Any] = safe_download_attachment,
    get_record_fn: Callable[[str, str, str], Dict[str, Any]] = safe_get_record,
) -> List[Dict[str, str]]:
    context = resolve_parent_reference_context(token, parent_fields, get_record_fn=get_record_fn)
    product_tokens = context["product_tokens"]
    character_tokens = context["character_tokens"]
    environment_tokens = context["environment_tokens"]
    required = [{"role": "product:1", "file_token": product_tokens[0], "name": context.get("product_name", "selected product")}]
    required.extend(
        {
            "role": f"character:{idx}",
            "file_token": character["photo_token"],
            "name": character.get("name") or f"Character {idx}",
            "type": character.get("type", ""),
        }
        for idx, character in enumerate(context.get("characters") or [], start=1)
        for file_token in [character["photo_token"]]
    )
    required.append({"role": "environment:1", "file_token": environment_tokens[0], "name": "selected environment"})
    if len(required) > max_count:
        raise ValueError(
            f"参考图数量超过上限：第一张产品图 + 已选模特图 + 环境图共 {len(required)} 张，"
            f"当前最多可用 {max_count} 张；请减少模特数量"
        )

    optional: List[Dict[str, str]] = []
    optional.extend(
        {"role": f"product:{idx}", "file_token": file_token, "name": context.get("product_name", "selected product")}
        for idx, file_token in enumerate(product_tokens[1:], start=2)
    )
    optional.extend(
        {"role": f"environment:{idx}", "file_token": file_token, "name": "selected environment"}
        for idx, file_token in enumerate(environment_tokens[1:], start=2)
    )
    selected = required + optional[: max_count - len(required)]

    refs: List[Dict[str, str]] = []
    for item in selected:
        safe_role = item["role"].replace(":", "_")
        local_path = task_dir / f"reference_{safe_role}.png"
        downloaded = download_fn(token, item["file_token"], str(local_path))
        refs.append({
            "role": item["role"],
            "path": _downloaded_path(downloaded, local_path),
            "file_token": item["file_token"],
            "name": item.get("name", ""),
            "type": item.get("type", ""),
        })
    return refs


def collect_omni_reference_images(
    token: str,
    child_fields: Dict[str, Any],
    parent_fields: Dict[str, Any],
    task_dir: Path,
    *,
    download_fn: Callable[[str, str, str], Any] = safe_download_attachment,
    get_record_fn: Callable[[str, str, str], Dict[str, Any]] = safe_get_record,
) -> List[Dict[str, str]]:
    task_dir.mkdir(parents=True, exist_ok=True)
    storyboard_token = _extract_attachment_token(child_fields.get("故事板图"))
    if not storyboard_token:
        raise ValueError("Storyboard分段缺少故事板图附件")
    refs: List[Dict[str, str]] = []
    storyboard_path = task_dir / "reference_storyboard.png"
    downloaded = download_fn(token, storyboard_token, str(storyboard_path))
    refs.append({"role": "storyboard", "path": _downloaded_path(downloaded, storyboard_path), "file_token": storyboard_token})
    refs.extend(collect_parent_reference_images(token, parent_fields, task_dir, max_count=MAX_REFERENCE_IMAGES - 1, download_fn=download_fn, get_record_fn=get_record_fn))
    return refs


def build_image_reference_note(refs: List[Dict[str, str]]) -> str:
    lines = [
        "Highest-priority visual rule: reference images override the storyboard text.",
        "Ignore any conflicting text in the storyboard prompt about character outfit, face, hair, body, product bottle shape, label, color, logo, packaging, furniture, or lighting.",
        "Use the text prompt only for layout, sequence, actions, timing, emotion, and dialogue.",
    ]
    for idx, ref in enumerate(refs, start=1):
        role = ref.get("role", "reference")
        name = ref.get("name", "").strip()
        name_note = f" ({name})" if name else ""
        if role.startswith("product"):
            lines.append(
                f"Reference image {idx} = product reference{name_note}. Copy this exact product. "
                "Keep packaging, bottle shape, nozzle, label, color, logo, text placement, and proportions unchanged; do not redraw it as a different product."
            )
        elif role.startswith("character"):
            lines.append(
                f"Reference image {idx} = character reference{name_note}. Copy this exact selected model/pet identity. "
                "Keep the same face, hair, body, outfit, clothing color, footwear, and visual style; do not replace with script-invented clothing."
            )
        elif role.startswith("environment"):
            lines.append(
                f"Reference image {idx} = environment reference{name_note}. Treat it as the fixed location anchor: keep the same room, furniture, "
                "background anchors, problem spot, lighting logic, props, and atmosphere across every storyboard and shot."
            )
    lines.append("Use all references as identity anchors, not optional inspiration.")
    return "\n".join(lines)


def _render_reference_contact_sheet(refs: List[Dict[str, str]], out_path: Path) -> None:
    from PIL import Image, ImageDraw, ImageOps

    tiles = []
    for ref in refs:
        path = ref.get("path", "")
        if not path or not os.path.exists(path):
            continue
        with Image.open(path) as img:
            tiles.append((ref, img.convert("RGB").copy()))
    if not tiles:
        raise ValueError("缺少可用参考图，无法生成参考图索引板")

    tile_w, tile_h = 520, 420
    label_h = 44
    cols = min(4, len(tiles))
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tile_w, rows * (tile_h + label_h)), "white")
    draw = ImageDraw.Draw(sheet)

    for idx, (ref, img) in enumerate(tiles):
        col = idx % cols
        row = idx // cols
        x = col * tile_w
        y = row * (tile_h + label_h)
        label = f"{idx + 1}. {ref.get('role', 'reference')}"
        if ref.get("name"):
            label += f" - {ref['name']}"
        draw.rectangle([x, y, x + tile_w - 1, y + label_h - 1], fill=(0, 110, 100))
        draw.text((x + 12, y + 12), label[:70], fill="white")
        fitted = ImageOps.contain(img, (tile_w - 20, tile_h - 20))
        px = x + (tile_w - fitted.width) // 2
        py = y + label_h + (tile_h - fitted.height) // 2
        sheet.paste(fitted, (px, py))
        draw.rectangle([x, y, x + tile_w - 1, y + tile_h + label_h - 1], outline=(200, 200, 200), width=2)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)


def build_reference_contact_sheet(refs: List[Dict[str, str]], out_path: Path) -> str:
    _render_reference_contact_sheet(refs, out_path)
    return str(out_path)


def resolve_storyboard_image_record_parameters(fields: Dict[str, Any]) -> Dict[str, str]:
    return {
        "model": extract_text(fields.get("故事板图片模型")).strip() or DEFAULT_STORYBOARD_IMAGE_MODEL,
        "size": extract_text(fields.get("故事板图片画面尺寸")).strip() or DEFAULT_STORYBOARD_IMAGE_SIZE,
        "aspect_ratio": extract_text(fields.get("故事板图片画面比例")).strip() or DEFAULT_STORYBOARD_IMAGE_ASPECT_RATIO,
    }


def missing_storyboard_image_default_fields(fields: Dict[str, Any]) -> Dict[str, str]:
    defaults = {
        "故事板图片模型": DEFAULT_STORYBOARD_IMAGE_MODEL,
        "故事板图片画面尺寸": DEFAULT_STORYBOARD_IMAGE_SIZE,
        "故事板图片画面比例": DEFAULT_STORYBOARD_IMAGE_ASPECT_RATIO,
    }
    return {name: value for name, value in defaults.items() if not extract_text(fields.get(name)).strip()}


def render_storyboard_image(record_id: str, *, dry_run: bool = False) -> Dict[str, Any]:
    ensure_storyboard_table()
    token = get_feishu_token()
    fields = safe_get_record(token, TABLE_STORYBOARD_VIDEO, record_id)
    parent_record_id = extract_text(fields.get("父任务记录ID")).strip()
    if not parent_record_id:
        raise ValueError("Storyboard分段缺少父任务记录ID")
    parent_fields = safe_get_record(token, TABLE_STORYBOARD_VIDEO, parent_record_id)
    prompt = extract_text(fields.get("故事板图片提示词")).strip()
    if not prompt:
        raise ValueError("故事板图片提示词为空")
    work_dir = ensure_work_dir(record_id)
    refs = collect_parent_reference_images(token, parent_fields, work_dir)
    reference_urls = build_reference_urls(token, refs)
    prompt = f"{build_image_reference_note(refs)}\n\n{prompt}".strip()
    record_params = resolve_storyboard_image_record_parameters(fields)
    model_name = normalize_image_model_choice(record_params["model"])
    size = record_params["size"]
    aspect_ratio = record_params["aspect_ratio"]
    _, cfg = get_stage_config(
        IMAGE_STAGE_NAME,
        default_model=DEFAULT_OTU_IMAGE_MODEL,
        default_api_base=DEFAULT_OTU_API_BASE,
        default_size=DEFAULT_STORYBOARD_IMAGE_SIZE,
    )
    summary = {
        "record_id": record_id,
        "dry_run": dry_run,
        "reference_count": len(refs),
        "model": model_name,
        "size": size,
        "aspect_ratio": aspect_ratio,
        "prompt_chars": len(prompt),
    }
    route_summary = maybe_unified_media_summary(
        token,
        fields,
        cfg,
        capability="图片",
        task_type="图生图/参考图重绘",
        model=model_name,
        slot_name="故事板图片",
        prompt=prompt,
        params={"size": size, "aspect_ratio": aspect_ratio},
        reference_count=len(refs),
    )
    if route_summary:
        summary["unified_ai_route"] = route_summary
    if dry_run:
        summary["status"] = "dry_run_ready"
        return summary
    if route_summary and ai_routing.unified_route_dry_run_only(safe_list_records(token, TABLE_CONFIG)):
        summary["status"] = "unified_ai_dry_run_ready"
        return summary

    primary_reference_path = build_reference_contact_sheet(refs, work_dir / "reference_contact_sheet.png")

    safe_update_record(token, TABLE_STORYBOARD_VIDEO, record_id, filter_existing_fields(token, TABLE_STORYBOARD_VIDEO, {
        **image_regeneration_reset_fields(),
        **missing_storyboard_image_default_fields(fields),
        "故事板图片生成状态": "生成中",
        "故事板图片错误信息": "",
    }))
    out_path = str(work_dir / f"{record_id}_storyboard.png")
    submit_task_id, submit_body = submit_otu_image_task(
        {"api_key": cfg["api_key"], "api_base": cfg.get("api_base") or DEFAULT_OTU_API_BASE, "model": model_name},
        prompt,
        input_mode="image-to-image" if refs else "text-to-image",
        image_path=primary_reference_path if refs else "",
        metadata={
            "urls": reference_urls,
            "reference_roles": [ref["role"] for ref in refs],
            "aspectRatio": aspect_ratio,
            "aspect_ratio": aspect_ratio,
        },
        size=size,
    )
    if submit_task_id:
        safe_update_record(token, TABLE_STORYBOARD_VIDEO, record_id, filter_existing_fields(token, TABLE_STORYBOARD_VIDEO, {
            "故事板图片任务ID": submit_task_id,
            "故事板图片错误信息": f"已提交 OTU 故事板图片任务，正在轮询。task_id={submit_task_id}",
        }))
    result = submit_body if not submit_task_id else poll_otu_image_task({"api_key": cfg["api_key"], "api_base": cfg.get("api_base") or DEFAULT_OTU_API_BASE, "model": model_name}, submit_task_id)
    result_url = extract_otu_result_url(result) or extract_otu_result_url(submit_body)
    if not result_url:
        raise RuntimeError("OTU 故事板图片任务完成但未返回图片地址")
    download_otu_image_result(result_url, out_path)
    file_token = with_retry(lambda: upload_image_to_feishu(token, out_path, f"{record_id}_storyboard.png"), max_attempts=3, label="upload storyboard image")
    ensure_record_current_generation(token, record_id, "故事板图片生成状态", "生成中", "故事板图片任务ID", submit_task_id)
    safe_update_record(token, TABLE_STORYBOARD_VIDEO, record_id, filter_existing_fields(token, TABLE_STORYBOARD_VIDEO, {
        "故事板图": [{"file_token": file_token}],
        "故事板图片任务ID": submit_task_id,
        "故事板图片生成状态": "成功",
        "故事板图片生成时间": int(time.time() * 1000),
        "故事板图片错误信息": "",
        "视频生成状态": "待生成",
        "错误信息": "",
    }))
    summary.update({"status": "success", "file_token": file_token, "output_path": out_path})
    return summary


def build_omni_video_prompt(child_fields: Dict[str, Any], parent_fields: Dict[str, Any], *, system_prompt: str = "") -> str:
    return parse_omni_video_prompt_template(system_prompt or OMNI_VIDEO_PROMPT_RULES)


def resolve_omni_record_parameters(fields: Dict[str, Any]) -> Dict[str, str]:
    return {
        "model": extract_text(fields.get("Omni模型")).strip() or DEFAULT_OMNI_MODEL,
        "size": extract_text(fields.get("Omni画面尺寸")).strip() or DEFAULT_OMNI_SIZE,
        "aspect_ratio": extract_text(fields.get("Omni画面比例")).strip() or DEFAULT_OMNI_ASPECT_RATIO,
    }


def missing_omni_default_fields(fields: Dict[str, Any]) -> Dict[str, str]:
    defaults = {
        "Omni模型": DEFAULT_OMNI_MODEL,
        "Omni画面尺寸": DEFAULT_OMNI_SIZE,
        "Omni画面比例": DEFAULT_OMNI_ASPECT_RATIO,
    }
    return {name: value for name, value in defaults.items() if not extract_text(fields.get(name)).strip()}


def videos_url(api_base: str) -> str:
    base = (api_base or DEFAULT_OTU_API_BASE).rstrip("/")
    if base.endswith("/v1/videos"):
        return base
    if base.endswith("/v1"):
        return f"{base}/videos"
    return f"{base}/v1/videos"


def video_item_url(api_base: str, task_id: str) -> str:
    return f"{videos_url(api_base).rstrip('/')}/{task_id}"


def submit_omni_video_task(
    config: Dict[str, str],
    prompt: str,
    refs: List[Dict[str, str]],
    *,
    size: str = DEFAULT_OMNI_SIZE,
    aspect_ratio: str = DEFAULT_OMNI_ASPECT_RATIO,
) -> Tuple[str, Dict[str, Any]]:
    if not refs:
        raise ValueError("Omni 图生视频至少需要 1 张参考图")
    url = videos_url(config.get("api_base") or DEFAULT_OTU_API_BASE)
    headers = {"Authorization": f"Bearer {config['api_key']}"}
    opened = []
    data = {
        "model": config.get("model") or DEFAULT_OMNI_MODEL,
        "prompt": prompt,
        "size": size or DEFAULT_OMNI_SIZE,
        "aspect_ratio": aspect_ratio or DEFAULT_OMNI_ASPECT_RATIO,
    }
    files: List[Tuple[str, Tuple[Any, ...]]] = []
    try:
        for ref in refs[:7]:
            path = ref.get("path", "")
            if not path or not os.path.exists(path):
                raise ValueError(f"Omni 参考图不存在: {ref.get('role')}")
            f = open(path, "rb")
            opened.append(f)
            files.append(("input_reference[]", (os.path.basename(path), f, "image/png")))
        resp = requests.post(url, headers=headers, data=data, files=files, timeout=SUBMIT_TIMEOUT)
    finally:
        for f in opened:
            f.close()
    try:
        body = resp.json()
    except Exception:
        body = {"raw_text": resp.text[:1000]}
    if resp.status_code >= 400:
        raise RuntimeError(f"Omni 视频任务提交失败: HTTP {resp.status_code}, body={str(body)[:1200]}")
    task_id = extract_text(body.get("id") or body.get("task_id") or (body.get("data") or {}).get("id") or (body.get("data") or {}).get("task_id")).strip()
    if not task_id:
        raise RuntimeError(f"Omni 视频任务提交未返回任务 ID: {str(body)[:1200]}")
    return task_id, body


def poll_omni_video_task(config: Dict[str, str], task_id: str) -> Dict[str, Any]:
    url = video_item_url(config.get("api_base") or DEFAULT_OTU_API_BASE, task_id)
    headers = {"Authorization": f"Bearer {config['api_key']}"}
    start = time.time()
    last_body: Dict[str, Any] = {}
    while time.time() - start < MAX_POLL_SECONDS:
        resp = requests.get(url, headers=headers, timeout=POLL_TIMEOUT)
        try:
            body = resp.json()
        except Exception:
            body = {"raw_text": resp.text[:1000]}
        last_body = body if isinstance(body, dict) else {"raw": body}
        if resp.status_code >= 400:
            raise RuntimeError(f"Omni 视频任务轮询失败: HTTP {resp.status_code}, body={str(last_body)[:1200]}")
        status = extract_text(last_body.get("status") or (last_body.get("data") or {}).get("status")).lower()
        if status in {"completed", "succeeded", "success", "done"}:
            return last_body
        if status in {"failed", "error", "cancelled", "canceled"}:
            raise RuntimeError(f"Omni 视频生成失败: {str(last_body)[:1500]}")
        time.sleep(POLL_INTERVAL)
    raise TimeoutError(f"Omni 视频任务超时: task_id={task_id}, last={str(last_body)[:1200]}")


def extract_video_url(result: Dict[str, Any]) -> str:
    candidates = [
        result.get("video_url"),
        result.get("result_url"),
        result.get("download_url"),
        result.get("url"),
    ]
    nested = result.get("data") if isinstance(result.get("data"), dict) else {}
    candidates.extend([nested.get("video_url"), nested.get("result_url"), nested.get("download_url"), nested.get("url")])
    for value in candidates:
        if isinstance(value, str) and value.startswith("http"):
            return value
    return ""


def ensure_record_current_generation(
    token: str,
    record_id: str,
    status_field: str,
    expected: str,
    task_field: str = "",
    task_id: str = "",
) -> None:
    latest = safe_get_record(token, TABLE_STORYBOARD_VIDEO, record_id)
    current = extract_text(latest.get(status_field)).strip()
    if current != expected:
        raise RuntimeError(f"记录状态已变更为 {current or '<empty>'}，停止写回，避免旧任务覆盖新结果")
    if task_field and task_id:
        current_task_id = extract_text(latest.get(task_field)).strip()
        if current_task_id != task_id:
            raise RuntimeError(f"{task_field} 已变更，停止写回，避免旧任务覆盖新结果")


def render_omni_video(record_id: str, *, dry_run: bool = False) -> Dict[str, Any]:
    ensure_storyboard_table()
    token = get_feishu_token()
    fields = safe_get_record(token, TABLE_STORYBOARD_VIDEO, record_id)
    parent_record_id = extract_text(fields.get("父任务记录ID")).strip()
    if not parent_record_id:
        raise ValueError("Storyboard分段缺少父任务记录ID")
    parent_fields = safe_get_record(token, TABLE_STORYBOARD_VIDEO, parent_record_id)
    parent_fields = parent_fields_with_reference_snapshots(token, parent_fields)
    work_dir = ensure_work_dir(record_id)
    refs = collect_omni_reference_images(token, fields, parent_fields, work_dir)
    _, cfg = get_stage_config(OMNI_STAGE_NAME, default_model=DEFAULT_OMNI_MODEL, default_api_base=DEFAULT_OTU_API_BASE, default_size=DEFAULT_OMNI_SIZE)
    prompt = build_omni_video_prompt(fields, parent_fields, system_prompt=cfg.get("prompt") or OMNI_VIDEO_PROMPT_RULES)
    record_params = resolve_omni_record_parameters(fields)
    cfg["model"] = record_params["model"]
    size = record_params["size"]
    aspect_ratio = record_params["aspect_ratio"]
    output_path = str(work_dir / f"{record_id}_omni.mp4")
    summary = {
        "record_id": record_id,
        "dry_run": dry_run,
        "reference_count": len(refs),
        "model": cfg["model"],
        "size": size,
        "aspect_ratio": aspect_ratio,
        "prompt_chars": len(prompt),
        "output_path": output_path,
    }
    route_summary = maybe_unified_media_summary(
        token,
        fields,
        cfg,
        capability="视频",
        task_type="首帧图生视频",
        model=cfg["model"],
        slot_name="视频",
        prompt=prompt,
        params={"size": size, "aspect_ratio": aspect_ratio},
        reference_count=len(refs),
    )
    if route_summary:
        summary["unified_ai_route"] = route_summary
    if dry_run:
        summary["status"] = "dry_run_ready"
        return summary
    if route_summary and ai_routing.unified_route_dry_run_only(safe_list_records(token, TABLE_CONFIG)):
        summary["status"] = "unified_ai_dry_run_ready"
        return summary

    field_types = get_table_field_types(token, TABLE_STORYBOARD_VIDEO)
    safe_update_record(token, TABLE_STORYBOARD_VIDEO, record_id, filter_existing_fields(token, TABLE_STORYBOARD_VIDEO, {
        **video_regeneration_reset_fields(),
        **missing_omni_default_fields(fields),
        "视频提示词": prompt[:10000],
        "视频生成状态": "生成中",
        "视频错误信息": "",
    }))
    task_id, submit_body = submit_omni_video_task(cfg, prompt, refs, size=size, aspect_ratio=aspect_ratio)
    safe_update_record(token, TABLE_STORYBOARD_VIDEO, record_id, filter_existing_fields(token, TABLE_STORYBOARD_VIDEO, {
        "视频任务ID": task_id,
        "视频错误信息": f"已提交 Omni 图生视频任务，正在轮询。task_id={task_id}",
    }))
    result = poll_omni_video_task(cfg, task_id)
    video_url = extract_video_url(result)
    if not video_url:
        raise RuntimeError(f"Omni 生成完成但未返回 video_url: {compact_json(result, 1200)}")
    download_video(video_url, output_path)
    file_token = upload_video_to_feishu(token, output_path, f"{record_id}_omni.mp4")
    ensure_record_current_generation(token, record_id, "视频生成状态", "生成中", "视频任务ID", task_id)
    success_fields = {
        "视频生成状态": "成功",
        "分镜视频": [{"file_token": file_token, "name": Path(output_path).name}],
        "视频任务ID": task_id,
        "视频错误信息": "",
        "视频生成时间": int(time.time() * 1000),
        "错误信息": "",
    }
    if video_url:
        success_fields["分镜视频URL"] = format_url_field_value(video_url, field_types.get("分镜视频URL", 0))
    safe_update_record(token, TABLE_STORYBOARD_VIDEO, record_id, filter_existing_fields(token, TABLE_STORYBOARD_VIDEO, success_fields))
    summary.update({"status": "success", "task_id": task_id, "video_url": video_url, "file_token": file_token})
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="故事板图片 + Omni 视频生成")
    parser.add_argument("action", choices=["split", "image", "video"])
    parser.add_argument("record_id")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    try:
        if args.action == "split":
            result = split_storyboards(args.record_id, dry_run=args.dry_run)
        elif args.action == "image":
            result = render_storyboard_image(args.record_id, dry_run=args.dry_run)
        else:
            result = render_omni_video(args.record_id, dry_run=args.dry_run)
        print(compact_json(result))
        return 0
    except Exception as exc:
        stage = {"split": "split_storyboard_prompts", "image": "generate_storyboard_image", "video": "generate_omni_video"}[args.action]
        payload = build_error_payload(exc, stage=stage)
        log_event("ERROR", "storyboard video task failed", action=args.action, record_id=args.record_id, error=payload["message"], error_code=payload["error_code"])
        if not args.dry_run:
            try:
                token = get_feishu_token()
                if args.action == "split" and TABLE_STORYBOARD_VIDEO:
                    safe_update_record(token, TABLE_STORYBOARD_VIDEO, args.record_id, filter_existing_fields(token, TABLE_STORYBOARD_VIDEO, {
                        "拆分状态": "失败",
                        "错误信息": payload["message"][:1000],
                    }))
                elif args.action == "image" and TABLE_STORYBOARD_VIDEO:
                    safe_update_record(token, TABLE_STORYBOARD_VIDEO, args.record_id, filter_existing_fields(token, TABLE_STORYBOARD_VIDEO, {
                        "故事板图片生成状态": "失败",
                        "故事板图片错误信息": payload["message"][:1000],
                        "错误信息": payload["message"][:1000],
                    }))
                elif args.action == "video" and TABLE_STORYBOARD_VIDEO:
                    safe_update_record(token, TABLE_STORYBOARD_VIDEO, args.record_id, filter_existing_fields(token, TABLE_STORYBOARD_VIDEO, {
                        "视频生成状态": "失败",
                        "视频错误信息": payload["message"][:1000],
                        "错误信息": payload["message"][:1000],
                    }))
            except Exception:
                pass
        print(f"ERROR_CODE={payload['error_code']} RETRYABLE={str(payload['retryable']).lower()} MESSAGE={payload['message']}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
