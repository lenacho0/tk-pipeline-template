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
    safe_list_records,
    safe_request,
    safe_update_record,
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
from tk_storyboard import safe_download_attachment, upload_image_to_feishu  # noqa: E402


SPLIT_STAGE_NAME = "故事板图片提示词拆分"
IMAGE_STAGE_NAME = "故事板图片生成-OTU"
OMNI_STAGE_NAME = "故事板视频生成-Omni"
DEFAULT_OMNI_MODEL = "omni_flash-10s"
DEFAULT_OMNI_SIZE = "1280x720"
MAX_REFERENCE_IMAGES = 7
BASE_WORK_DIR = Path(WORKSPACE) / "storyboard_video_work"
POLL_INTERVAL = 15
MAX_POLL_SECONDS = 2400
SUBMIT_TIMEOUT = 180
POLL_TIMEOUT = 45


STORYBOARD_PROMPT_RULES = """
I have finalized the shot-by-shot text script for this short commerce micro-drama.

Read the full script content and embed it into the mandatory visual grid layout rules below.

Requirements:
1. Split the script into multiple storyboard image prompts at roughly one storyboard image per 10 seconds.
2. The plot must stay continuous across storyboard images. Shot numbers must be consecutive, and characters, pets, products, scenes, outfits, and props must remain consistent.
3. Each storyboard must be an independent 16:9 horizontal storyboard production board.
4. Visual content from the script must be embedded only in English.
5. Dialogue / voiceover from the script must be embedded only in Thai.
6. Output complete English prompts that can be used directly to generate narrative storyboard images.
7. Read the full script and derive the Storyboard 01 core conflict scene and golden 3-second / dramatic hook from the script itself. Do not ask for or rely on separate user-entered conflict/hook fields.

Mandatory visual grid layout:
- Overall canvas: 16:9 horizontal, pure white background.
- The image is strictly divided from top to bottom into three independent sections.
- Top section: full-width header. The far-left bold title is "短视频带货分镜制作".
- To the right of the title is a horizontal table whose fields differ by storyboard number.
- For Storyboard 01 only, the right-side table must include: Storyboard 编号, Time Range, 产品名称, 目标人群, 核心冲突场景, 黄金3秒/戏剧钩子. The 黄金3秒/戏剧钩子 text must be highlighted in red.
- For Storyboard 02 onward, the top header table must include only: Storyboard 编号, Time Range, 产品名称, 目标人群.
- Important: from Storyboard 02 onward, the prompt must not include 核心冲突场景 or 黄金3秒/戏剧钩子 in the top header table.
""".strip()


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
        "environment_tokens": _extract_attachment_tokens(parent_fields.get("环境图")),
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
        "分镜视频URL": "",
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


def build_storyboard_prompt_generation_request(fields: Dict[str, Any]) -> str:
    script = extract_text(fields.get("脚本内容")).strip()
    product_name = extract_text(fields.get("产品名称")).strip()
    target_audience = extract_text(fields.get("目标人群")).strip()
    character_summary = extract_text(fields.get("角色参考摘要")).strip()
    return f"""
{STORYBOARD_PROMPT_RULES}

Return strict JSON only. Do not wrap it in Markdown.
JSON schema:
{{
  "storyboards": [
    {{
      "storyboard_no": 1,
      "time_range": "0-10s",
      "image_prompt": "Complete English prompt for this 16:9 storyboard production board",
      "video_prompt": "Prompt for generating a real video segment from this storyboard image and the uploaded product/character/environment references"
    }}
  ]
}}

Global business fields:
- Product name: {product_name}
- Target audience: {target_audience}

Selected character references:
{character_summary or "- No character reference summary was provided."}

Keep every selected human/pet character consistent across all storyboards. Do not merge, replace, omit, or casually change any selected character unless the script explicitly calls for a character to be off-screen.

Full finalized script:
{script}
""".strip()


def normalize_storyboard_payload(payload: Any) -> Dict[str, Any]:
    data = payload
    if isinstance(payload, str):
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
        image_prompt = extract_text(item.get("image_prompt")).strip()
        if not image_prompt:
            raise ValueError(f"storyboards[{idx}] 缺少 image_prompt")
        storyboard_no = int(item.get("storyboard_no") or idx)
        normalized.append({
            "storyboard_no": storyboard_no,
            "time_range": extract_text(item.get("time_range")).strip() or f"Storyboard {storyboard_no:02d}",
            "image_prompt": image_prompt,
            "video_prompt": extract_text(item.get("video_prompt")).strip(),
        })
    return {"storyboards": normalized}


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
    for item in storyboards:
        no = int(item["storyboard_no"])
        fields = {
            "记录类型": "Storyboard分段",
            "任务名称": f"{task_name}-Storyboard{no:02d}",
            "父任务记录ID": parent_record_id,
            "批次ID": batch_id,
            "关联产品记录": parent_fields.get("关联产品记录", []),
            "选择模特": parent_fields.get("选择模特", []),
            "Storyboard编号": no,
            "Time Range": item["time_range"],
            "故事板图片提示词": item["image_prompt"],
            "故事板图片生成状态": "待生成",
            "视频提示词": item.get("video_prompt", ""),
            "视频生成状态": "不触发",
            "错误信息": "",
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
    record_id = CONFIG_RECORDS.get("storyboard_video_prompt") or CONFIG_RECORDS.get("shot_script_gen")
    if not record_id:
        raise ValueError("config_records 缺少 storyboard_video_prompt 或 shot_script_gen")
    cfg = get_model_config(token, record_id)
    if not cfg.get("api_key"):
        raise ValueError("故事板提示词拆分配置缺少 API Key")
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

    prompt = build_storyboard_prompt_generation_request(fields)
    summary = {"record_id": record_id, "dry_run": dry_run, "prompt_chars": len(prompt)}
    if dry_run:
        summary["status"] = "dry_run_ready"
        return summary

    safe_update_record(token, TABLE_STORYBOARD_VIDEO, record_id, filter_existing_fields(token, TABLE_STORYBOARD_VIDEO, {
        "拆分状态": "拆分中",
        "错误信息": "",
    }))

    if raw_model_output is None:
        cfg = get_text_generation_config(token)
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
        }
        if not cfg["api_key"]:
            raise ValueError(f"{stage_name} 缺少 API Key")
        return rec.get("record_id") or rec.get("id") or "", cfg
    raise ValueError(f"找不到模型配置: {stage_name}")


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
    required = [{"role": "product:1", "file_token": product_tokens[0]}]
    required.extend(
        {"role": f"character:{idx}", "file_token": file_token}
        for idx, file_token in enumerate(character_tokens, start=1)
    )
    if len(required) > max_count:
        raise ValueError(
            f"参考图数量超过上限：第一张产品图 + 已选模特图共 {len(required)} 张，"
            f"当前最多可用 {max_count} 张；请减少模特数量"
        )

    optional: List[Dict[str, str]] = []
    optional.extend(
        {"role": f"product:{idx}", "file_token": file_token}
        for idx, file_token in enumerate(product_tokens[1:], start=2)
    )
    optional.extend(
        {"role": f"environment:{idx}", "file_token": file_token}
        for idx, file_token in enumerate(context["environment_tokens"], start=1)
    )
    selected = required + optional[: max_count - len(required)]

    refs: List[Dict[str, str]] = []
    for item in selected:
        safe_role = item["role"].replace(":", "_")
        local_path = task_dir / f"reference_{safe_role}.png"
        downloaded = download_fn(token, item["file_token"], str(local_path))
        refs.append({"role": item["role"], "path": _downloaded_path(downloaded, local_path), "file_token": item["file_token"]})
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
    lines = []
    for idx, ref in enumerate(refs, start=1):
        role = ref.get("role", "reference")
        if role.startswith("product"):
            lines.append(f"Reference image {idx} = product reference. Keep product packaging, shape, label, color, logo, and proportions unchanged.")
        elif role.startswith("character"):
            lines.append(f"Reference image {idx} = character reference. Keep the same character identity, face/body/pet traits, outfit, and visual style.")
        elif role.startswith("environment"):
            lines.append(f"Reference image {idx} = environment reference. Keep the same location, lighting logic, props, and atmosphere when relevant.")
    lines.append("Use all references as identity anchors, not optional inspiration.")
    return "\n".join(lines)


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
    summary = {"record_id": record_id, "dry_run": dry_run, "reference_count": len(refs), "prompt_chars": len(prompt)}
    if dry_run:
        summary["status"] = "dry_run_ready"
        return summary

    _, cfg = get_stage_config(
        IMAGE_STAGE_NAME,
        default_model=DEFAULT_OTU_IMAGE_MODEL,
        default_api_base=DEFAULT_OTU_API_BASE,
        default_size=DEFAULT_OTU_IMAGE_SIZE,
    )
    model_name = normalize_image_model_choice(cfg.get("model") or DEFAULT_OTU_IMAGE_MODEL)
    safe_update_record(token, TABLE_STORYBOARD_VIDEO, record_id, filter_existing_fields(token, TABLE_STORYBOARD_VIDEO, {
        **image_regeneration_reset_fields(),
        "故事板图片生成状态": "生成中",
        "故事板图片错误信息": "",
    }))
    out_path = str(work_dir / f"{record_id}_storyboard.png")
    submit_task_id, submit_body = submit_otu_image_task(
        {"api_key": cfg["api_key"], "api_base": cfg.get("api_base") or DEFAULT_OTU_API_BASE, "model": model_name},
        prompt,
        input_mode="image-to-image" if refs else "text-to-image",
        image_path=refs[0]["path"] if refs else "",
        metadata={"urls": reference_urls, "reference_roles": [ref["role"] for ref in refs], "aspectRatio": "16:9"},
        size=cfg.get("size") or DEFAULT_OTU_IMAGE_SIZE,
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


def build_omni_video_prompt(child_fields: Dict[str, Any], parent_fields: Dict[str, Any]) -> str:
    explicit = extract_text(child_fields.get("视频提示词")).strip()
    image_prompt = extract_text(child_fields.get("故事板图片提示词")).strip()
    product = extract_text(parent_fields.get("产品名称")).strip()
    target = extract_text(parent_fields.get("目标人群")).strip()
    time_range = extract_text(child_fields.get("Time Range")).strip()
    return f"""
Generate one real 16:9 horizontal short commerce drama video segment from the uploaded references.

Reference order:
1. Storyboard production board: use only to understand scene sequence, composition, characters, product placement, Thai dialogue, and timing.
2. Product image(s): hard product identity anchors.
3. Character image(s): hard character identity anchors.
4. Environment image(s): optional scene identity anchors.

Do not render the storyboard board itself. Do not show grid lines, white board background, header tables, Chinese layout labels, red highlight text, panel numbers, captions, subtitles, stickers, watermarks, or UI. The final output must be the real full-screen story world, not a storyboard sheet.

Product: {product}
Target audience: {target}
Time range: {time_range}

Storyboard image prompt / visual understanding:
{image_prompt}

Video direction:
{explicit or "Animate the continuous story moments shown in the storyboard as one coherent 10-second segment. Preserve product, character, environment, outfit, prop, and lighting continuity. Use only Thai dialogue/voiceover if spoken lines appear; never speak Chinese or English prompt notes."}
""".strip()


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
) -> Tuple[str, Dict[str, Any]]:
    if not refs:
        raise ValueError("Omni 图生视频至少需要 1 张参考图")
    url = videos_url(config.get("api_base") or DEFAULT_OTU_API_BASE)
    headers = {"Authorization": f"Bearer {config['api_key']}"}
    opened = []
    files: List[Tuple[str, Tuple[Any, ...]]] = [
        ("model", (None, config.get("model") or DEFAULT_OMNI_MODEL)),
        ("prompt", (None, prompt)),
        ("size", (None, size or DEFAULT_OMNI_SIZE)),
    ]
    try:
        for ref in refs[:7]:
            path = ref.get("path", "")
            if not path or not os.path.exists(path):
                raise ValueError(f"Omni 参考图不存在: {ref.get('role')}")
            f = open(path, "rb")
            opened.append(f)
            files.append(("input_reference[]", (os.path.basename(path), f, "image/png")))
        resp = requests.post(url, headers=headers, files=files, timeout=SUBMIT_TIMEOUT)
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
    prompt = build_omni_video_prompt(fields, parent_fields)
    _, cfg = get_stage_config(OMNI_STAGE_NAME, default_model=DEFAULT_OMNI_MODEL, default_api_base=DEFAULT_OTU_API_BASE, default_size=DEFAULT_OMNI_SIZE)
    cfg["model"] = cfg.get("model") or DEFAULT_OMNI_MODEL
    size = cfg.get("size") or DEFAULT_OMNI_SIZE
    output_path = str(work_dir / f"{record_id}_omni.mp4")
    summary = {
        "record_id": record_id,
        "dry_run": dry_run,
        "reference_count": len(refs),
        "model": cfg["model"],
        "size": size,
        "prompt_chars": len(prompt),
        "output_path": output_path,
    }
    if dry_run:
        summary["status"] = "dry_run_ready"
        return summary

    field_types = get_table_field_types(token, TABLE_STORYBOARD_VIDEO)
    safe_update_record(token, TABLE_STORYBOARD_VIDEO, record_id, filter_existing_fields(token, TABLE_STORYBOARD_VIDEO, {
        **video_regeneration_reset_fields(),
        "视频生成状态": "生成中",
        "视频错误信息": "",
    }))
    task_id, submit_body = submit_omni_video_task(cfg, prompt, refs, size=size)
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
