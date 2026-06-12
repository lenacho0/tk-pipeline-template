#!/usr/bin/env python3
"""008-图生视频生成表 worker。"""
from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass, field
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Tuple

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ai_routing  # noqa: E402
from common import (  # noqa: E402
    TABLE_CONFIG,
    TABLE_MODEL,
    TABLE_PRODUCT,
    TABLE_PROMPT_IMAGE_VIDEO,
    TABLE_STORYBOARD_VIDEO,
    WORKSPACE,
    aitgenne_get,
    aitgenne_post,
    build_error_payload,
    extract_attachment_tokens,
    extract_linked_record_ids,
    extract_text,
    get_feishu_token,
    get_model_config,
    latest_media_token,
    safe_get_record,
    safe_list_records,
    safe_update_record,
    upload_image_to_feishu,
)
from image_generation import (  # noqa: E402
    config_records_for_image_slot,
    image_params_with_model_overrides,
    image_slot_field_patch,
    resolve_image_route_from_slot,
    run_image_generation,
)
from otu_image import DEFAULT_OTU_API_BASE, DEFAULT_OTU_IMAGE_MODEL, DEFAULT_OTU_IMAGE_SIZE  # noqa: E402
from tk_model_config_center import TASK_TABLES, apply_task_default_to_record  # noqa: E402
from tk_reference_media import (  # noqa: E402
    build_reference_contact_sheet,
    poll_omni_video_task,
    submit_omni_video_task,
)
from tk_auto_review import TABLE_AUTO_REVIEW_STAGE_NAMES, auto_review_enabled  # noqa: E402
from tk_shot_storyboard import filter_existing_fields, get_tmp_download_url_for_attachment  # noqa: E402
from tk_shot_video import (  # noqa: E402
    DEFAULT_API_BASE,
    DEFAULT_ASPECT_RATIO,
    DEFAULT_MODEL as DEFAULT_NATIVE_VIDEO_MODEL,
    DEFAULT_OTU_MODEL,
    DEFAULT_OTU_SIZE,
    call_native_veo_first_frame_task,
    download_native_veo_video,
    download_video,
    download_video_without_env_proxy,
    extract_native_generated_video,
    extract_video_url,
    format_url_field_value,
    get_native_veo_client,
    get_table_field_types,
    is_native_veo_operation_id,
    native_generated_video_uri,
    normalize_native_veo_resolution,
    normalize_seconds,
    operation_to_dict,
    poll_native_veo_operation,
    poll_otu_video_task,
    submit_otu_video_task,
    upload_video_to_feishu,
)


AUTO_REVIEW_STAGE_NAME = TABLE_AUTO_REVIEW_STAGE_NAMES["prompt_image_video"]
IMAGE_STAGE_NAME = "图片生成-OTU"
DEFAULT_VIDEO_STAGE_NAME = "分镜视频生成-OTU"
PRODUCT_VISUAL_ANALYSIS_STAGE_NAME = "多角色首尾帧解析-Gemini"
BASE_WORK_DIR = Path(WORKSPACE) / "prompt_image_video_work"
STORYBOARD_BASE_WORK_DIR = Path(WORKSPACE) / "storyboard_video_work"
DEFAULT_TABLE_KEY = "prompt_image_video"
STORYBOARD_TABLE_KEY = "storyboard_video"
MAX_IMAGE_REFERENCES = 7
MAX_OMNI_VIDEO_REFERENCES = 7
POLL_INTERVAL = 15
MAX_POLL_SECONDS = 2400
POLL_TIMEOUT = 45
SUBMIT_TIMEOUT = 180


@dataclass
class VideoGenerationResult:
    provider: str
    task_id: str
    submit_body: Dict[str, Any]
    result_body: Dict[str, Any]
    output_path: str
    request_summary: Dict[str, Any] = field(default_factory=dict)
    video_url: str = ""


def table_id_for_key(table_key: str = DEFAULT_TABLE_KEY) -> str:
    if table_key == STORYBOARD_TABLE_KEY:
        return TABLE_STORYBOARD_VIDEO
    return TABLE_PROMPT_IMAGE_VIDEO


def base_work_dir_for_key(table_key: str = DEFAULT_TABLE_KEY) -> Path:
    if table_key == STORYBOARD_TABLE_KEY:
        return STORYBOARD_BASE_WORK_DIR
    return BASE_WORK_DIR


def app_table_for_key(table_key: str = DEFAULT_TABLE_KEY) -> str:
    return TASK_TABLES[table_key]


def auto_review_stage_for_key(table_key: str = DEFAULT_TABLE_KEY) -> str:
    return TABLE_AUTO_REVIEW_STAGE_NAMES[table_key]


def compact_json(value: Any, max_chars: int = 20000) -> str:
    text = json.dumps(value, ensure_ascii=False, indent=2, default=str)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 200] + "\n...TRUNCATED..."


def parse_json_object(value: Any, *, field_name: str) -> Dict[str, Any]:
    raw = extract_text(value).strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field_name} 不是合法 JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{field_name} 顶层必须是对象")
    return parsed


def normalize_int(value: Any, default: int = 1) -> int:
    raw = extract_text(value).strip()
    if not raw:
        return default
    try:
        return int(float(raw))
    except Exception:
        return default


def current_version(fields: Dict[str, Any], field_name: str) -> int:
    return max(1, normalize_int(fields.get(field_name), 1))


def ensure_table(table_key: str = DEFAULT_TABLE_KEY) -> None:
    if not table_id_for_key(table_key):
        raise RuntimeError(f"config.json 尚未配置 {table_key} 表 ID")


def ensure_work_dir(record_id: str, stage: str, version: int, table_key: str = DEFAULT_TABLE_KEY) -> Path:
    work_dir = base_work_dir_for_key(table_key) / record_id / f"{stage}_v{version}"
    work_dir.mkdir(parents=True, exist_ok=True)
    return work_dir


def attachment_items(value: Any) -> List[Dict[str, str]]:
    if not isinstance(value, list):
        return []
    items: List[Dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        token = extract_text(item.get("file_token")).strip()
        if token:
            items.append({"file_token": token, "name": extract_text(item.get("name")).strip()})
    return items


def _downloaded_path(downloaded: Any, fallback_path: Path) -> str:
    if isinstance(downloaded, (str, Path)):
        return str(downloaded)
    return str(fallback_path)


def download_feishu_attachment_raw(token: str, file_token: str, save_path: Path) -> Path:
    resp = requests.get(
        f"https://open.feishu.cn/open-apis/drive/v1/medias/{file_token}/download",
        headers={"Authorization": f"Bearer {token}"},
        timeout=300,
        stream=True,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"飞书附件下载失败: HTTP {resp.status_code}, file_token={file_token}")
    save_path.parent.mkdir(parents=True, exist_ok=True)
    with save_path.open("wb") as f:
        for chunk in resp.iter_content(8192):
            if chunk:
                f.write(chunk)
    if save_path.stat().st_size <= 0:
        raise RuntimeError(f"飞书附件下载结果为空: {save_path}")
    return save_path


def _append_ref(refs: List[Dict[str, str]], role: str, file_token: str, name: str = "") -> None:
    token = extract_text(file_token).strip()
    if token:
        refs.append({"role": role, "file_token": token, "name": name})


def collect_image_reference_manifest(
    token: str,
    fields: Dict[str, Any],
    *,
    get_record_fn: Callable[[str, str, str], Dict[str, Any]] = safe_get_record,
) -> List[Dict[str, str]]:
    refs: List[Dict[str, str]] = []
    for product_id in extract_linked_record_ids(fields.get("关联产品记录")):
        product_fields = get_record_fn(token, TABLE_PRODUCT, product_id)
        for idx, file_token in enumerate(extract_attachment_tokens(product_fields.get("产品图片")), start=1):
            _append_ref(refs, f"product_table:{idx}", file_token, extract_text(product_fields.get("产品名称-zh")).strip())
    for idx, item in enumerate(attachment_items(fields.get("上传产品图")), start=1):
        _append_ref(refs, f"uploaded_product:{idx}", item["file_token"], item.get("name", ""))
    for model_id in extract_linked_record_ids(fields.get("选择模特")):
        model_fields = get_record_fn(token, TABLE_MODEL, model_id)
        model_name = extract_text(model_fields.get("模特名称")).strip()
        for idx, file_token in enumerate(extract_attachment_tokens(model_fields.get("模特照片")), start=1):
            _append_ref(refs, f"model_table:{idx}", file_token, model_name)
    for idx, item in enumerate(attachment_items(fields.get("上传模特图")), start=1):
        _append_ref(refs, f"uploaded_model:{idx}", item["file_token"], item.get("name", ""))
    for idx, item in enumerate(attachment_items(fields.get("上传参考图")), start=1):
        _append_ref(refs, f"uploaded_reference:{idx}", item["file_token"], item.get("name", ""))
    if len(refs) > MAX_IMAGE_REFERENCES:
        raise ValueError(f"参考图数量超过上限：当前 {len(refs)} 张，最多可用 {MAX_IMAGE_REFERENCES} 张")
    return refs


def collect_image_references(
    token: str,
    fields: Dict[str, Any],
    work_dir: Path,
    *,
    get_record_fn: Callable[[str, str, str], Dict[str, Any]] = safe_get_record,
    download_fn: Callable[[str, str, Path], Any] = download_feishu_attachment_raw,
) -> List[Dict[str, str]]:
    manifest = collect_image_reference_manifest(token, fields, get_record_fn=get_record_fn)
    refs: List[Dict[str, str]] = []
    for idx, item in enumerate(manifest, start=1):
        safe_role = item["role"].replace(":", "_")
        local_path = work_dir / f"reference_{idx:02d}_{safe_role}.png"
        downloaded = download_fn(token, item["file_token"], local_path)
        refs.append({**item, "path": _downloaded_path(downloaded, local_path)})
    return refs


def product_reference_refs(refs: List[Dict[str, str]]) -> List[Dict[str, str]]:
    return [
        ref for ref in refs
        if ref.get("role", "").startswith("product_table:") or ref.get("role", "").startswith("uploaded_product:")
    ]


def _line_panel_divider_score(img: Any, *, vertical: bool) -> Tuple[float, float, float]:
    width, height = img.size
    primary = width if vertical else height
    secondary = height if vertical else width
    if primary < 80 or secondary < 80:
        return 0.0, 0.0, 255.0
    center = primary // 2
    sample_step = max(1, secondary // 160)
    good = 0
    total = 0
    brightness_sum = 0.0
    spread_sum = 0.0
    for offset in (-1, 0, 1):
        pos = min(primary - 1, max(0, center + offset))
        for other in range(0, secondary, sample_step):
            pixel = img.getpixel((pos, other) if vertical else (other, pos))
            if not isinstance(pixel, tuple) or len(pixel) < 3:
                continue
            r, g, b = pixel[:3]
            brightness = (r + g + b) / 3
            spread = max(r, g, b) - min(r, g, b)
            brightness_sum += brightness
            spread_sum += spread
            if brightness >= 215 and max(r, g, b) - min(r, g, b) <= 35:
                good += 1
            total += 1
    if total <= 0:
        return 0.0, 0.0, 255.0
    return good / total, brightness_sum / total, spread_sum / total


def _line_looks_like_panel_divider(img: Any, *, vertical: bool) -> bool:
    fraction, avg_brightness, avg_spread = _line_panel_divider_score(img, vertical=vertical)
    return fraction >= 0.62 or (fraction >= 0.30 and avg_brightness >= 210 and avg_spread <= 90)


def _is_probable_two_by_two_product_sheet(image_path: str) -> bool:
    try:
        from PIL import Image

        with Image.open(image_path) as raw:
            img = raw.convert("RGB")
            width, height = img.size
            if width < 600 or height < 600:
                return False
            if not (0.82 <= width / height <= 1.22):
                return False
            return (
                _line_looks_like_panel_divider(img, vertical=True)
                and _line_looks_like_panel_divider(img, vertical=False)
            )
    except Exception:
        return False


def prepare_product_reference_images(refs: List[Dict[str, str]], work_dir: Path) -> List[Dict[str, str]]:
    prepared: List[Dict[str, str]] = []
    for idx, ref in enumerate(refs, start=1):
        path = ref.get("path", "")
        if ref not in product_reference_refs([ref]) or not path or not _is_probable_two_by_two_product_sheet(path):
            prepared.append(ref)
            continue
        try:
            from PIL import Image

            with Image.open(path) as raw:
                img = raw.convert("RGB")
                width, height = img.size
                crop = img.crop((0, 0, width // 2, height // 2))
                safe_role = ref.get("role", f"product_{idx}").replace(":", "_")
                out_path = work_dir / f"reference_{idx:02d}_{safe_role}_front_panel.png"
                crop.save(out_path)
            prepared.append({**ref, "source_path": path, "path": str(out_path)})
        except Exception:
            prepared.append(ref)
    return prepared


def describe_product_reference_images(token: str, refs: List[Dict[str, str]]) -> str:
    product_refs = product_reference_refs(refs)
    if not product_refs:
        return ""
    image_paths = [ref.get("path", "") for ref in product_refs if ref.get("path") and os.path.exists(ref.get("path", ""))]
    if not image_paths:
        return ""
    try:
        prompt = (
            "Analyze the attached product package reference image(s). "
            "Return 2-4 concise English bullet lines that describe only visible product identity details: "
            "brand/logo text, main title text, dominant package colors, package shape, label layout, animal/graphic elements, and dosage/spec text if visible. "
            "Do not infer from the product category and do not mention anything not visible."
        )
        return _call_product_visual_model(token, prompt, image_paths[:3], max_tokens=300).strip()[:1800]
    except Exception:
        return ""


def _mime_type_for_image(path: str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    return "image/png"


def _call_product_visual_model(token: str, prompt: str, image_paths: List[str], *, max_tokens: int = 300) -> str:
    cfg = get_model_config(token, PRODUCT_VISUAL_ANALYSIS_STAGE_NAME)
    api_key = (cfg.get("api_key") or "").strip()
    if not api_key:
        return ""
    model_name = (cfg.get("model") or "gemini-2.5-flash").strip()
    if "gemini" in model_name.lower() and "gemini" in (cfg.get("call_type") or "").lower():
        from google import genai
        from google.genai import types

        parts: List[Any] = []
        for path in image_paths:
            with open(path, "rb") as f:
                parts.append(types.Part(inline_data={
                    "mime_type": _mime_type_for_image(path),
                    "data": base64.b64encode(f.read()).decode("ascii"),
                }))
        parts.append(types.Part(text=prompt))
        client = genai.Client(api_key=api_key, http_options={"base_url": cfg.get("api_base") or "https://aihubmix.com/gemini"})
        response = client.models.generate_content(
            model=model_name,
            contents=[types.Content(role="user", parts=parts)],
        )
        return (getattr(response, "text", "") or "").strip()

    model_bits = ai_routing.parse_model_display(model_name)
    raw_model = model_bits.get("model") or model_name
    api_base = (cfg.get("api_base") or "").rstrip("/")
    if not api_base:
        return ""
    content: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]
    for path in image_paths:
        with open(path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode("ascii")
        content.append({"type": "image_url", "image_url": {"url": f"data:{_mime_type_for_image(path)};base64,{image_b64}"}})
    url = api_base if api_base.endswith("/chat/completions") else f"{api_base}/chat/completions"
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": raw_model, "messages": [{"role": "user", "content": content}], "max_tokens": max_tokens},
        timeout=90,
    )
    if resp.status_code >= 400:
        return ""
    body = resp.json()
    choices = body.get("choices") if isinstance(body, dict) else []
    if choices and isinstance(choices[0], dict):
        message = choices[0].get("message") or {}
        return extract_text(message.get("content")).strip()
    return ""


def _extract_json_object_from_text(text: str) -> Dict[str, Any]:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`").strip()
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            raise
        parsed = json.loads(raw[start:end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("视觉审核返回 JSON 顶层不是对象")
    return parsed


def verify_generated_product_identity(
    token: str,
    refs: List[Dict[str, str]],
    generated_image_path: str,
    visual_description: str = "",
) -> Dict[str, Any]:
    product_refs = product_reference_refs(refs)
    if not product_refs:
        return {"required": False, "passed": True, "reason": "no product reference"}
    product_paths = [
        ref.get("path", "")
        for ref in product_refs
        if ref.get("path") and os.path.exists(ref.get("path", ""))
    ]
    if not product_paths:
        return {"required": True, "passed": False, "reason": "产品参考图本地文件不存在，无法做一致性审核"}
    if not generated_image_path or not os.path.exists(generated_image_path):
        return {"required": True, "passed": False, "reason": "生成图片本地文件不存在，无法做一致性审核"}

    details = visual_description.strip()
    details_block = f"\nKnown visible product identity details:\n{details}\n" if details else ""
    prompt = (
        "You are a strict product package identity auditor.\n"
        "The first image(s) are the required product package reference. The final image is an AI-generated result.\n"
        "Decide only whether the product package identity in the generated image matches the reference.\n"
        "Pass only if the generated package preserves the same brand/logo impression, main title text, dominant colors, package shape, label layout, graphic/animal elements, and visible specification/dosage text.\n"
        "Fail if it is a generic package, another brand, a competitor product, or if the label/packaging identity materially changes.\n"
        "Do not judge beauty, composition, lighting, background, or model pose.\n"
        f"{details_block}"
        "Return strict JSON only with this shape: "
        "{\"passed\": true|false, \"reason\": \"short reason\", \"missing_or_changed\": [\"item\"], \"confidence\": 0.0}"
    )
    raw = _call_product_visual_model(
        token,
        prompt,
        [*product_paths[:3], generated_image_path],
        max_tokens=450,
    )
    if not raw:
        return {"required": True, "passed": False, "reason": "产品一致性审核模型未返回结果"}
    try:
        parsed = _extract_json_object_from_text(raw)
    except Exception as exc:
        return {
            "required": True,
            "passed": False,
            "reason": f"产品一致性审核返回无法解析: {exc}",
            "raw_response": raw[:2000],
        }
    missing = parsed.get("missing_or_changed")
    if not isinstance(missing, list):
        missing = []
    reason = extract_text(parsed.get("reason")).strip() or ("same product" if parsed.get("passed") else "product identity mismatch")
    return {
        "required": True,
        "passed": bool(parsed.get("passed")),
        "reason": reason,
        "missing_or_changed": [extract_text(item).strip() for item in missing if extract_text(item).strip()],
        "confidence": parsed.get("confidence"),
        "raw_response": raw[:2000],
    }


def build_product_reference_lock_prompt(refs: List[Dict[str, str]], visual_description: str = "") -> str:
    product_refs = product_reference_refs(refs)
    if not product_refs:
        return ""
    roles = ", ".join(ref["role"] for ref in product_refs)
    names = ", ".join(ref.get("name", "") for ref in product_refs if ref.get("name"))
    name_line = f" Selected product name: {names}." if names else ""
    visual_line = f"\nVISIBLE PRODUCT IDENTITY DETAILS:\n{visual_description.strip()}\n" if visual_description.strip() else ""
    return (
        "PRODUCT REFERENCE LOCK:\n"
        f"- The selected product reference role(s) are {roles}.{name_line}\n"
        "- Treat product_table:* and uploaded_product:* reference images as the highest-priority source for the product.\n"
        "- Preserve the exact bottle/package silhouette, box shape, trigger or cap shape, label color blocks, animal illustration/logo area, text placement, and size ratio from the product reference.\n"
        "- If a product reference was cropped from a multi-view product sheet, use the focused front package view as the product identity source.\n"
        "- Do not invent a generic bottle or package, do not replace the label, and do not use a different product package.\n"
        "- If the user prompt conflicts with product reference visual details, the product reference wins."
        f"{visual_line}"
    )


def selected_config_record_for_model(config_records: Iterable[Dict[str, Any]], model_choice: str) -> Dict[str, Any]:
    bits = ai_routing.parse_model_display(model_choice)
    provider = bits["provider"]
    if not provider:
        raise ValueError(f"模型选择必须包含供应商前缀: {model_choice}")
    fields = ai_routing.config_record_for_model(config_records, provider, model_choice)
    if not fields:
        raise ValueError(f"模型配置缺失或停用: {model_choice}")
    return fields


def _route_model_name(route: ai_routing.AiRoute) -> str:
    return ai_routing.parse_model_display(route.model)["model"] or route.model


def is_otu_omni_video_route(route: ai_routing.AiRoute) -> bool:
    return route.provider == "OTU" and _route_model_name(route) == "omni_flash-10s"


def config_fields_to_runtime(fields: Mapping[str, Any], *, default_model: str = "") -> Dict[str, str]:
    return {
        "model": extract_text(fields.get("模型名称")).strip() or default_model,
        "provider": extract_text(fields.get("供应商") or fields.get("AI供应商")).strip(),
        "api_key": extract_text(fields.get("API Key")).strip(),
        "api_base": extract_text(fields.get("API 代理地址")).strip(),
        "call_type": extract_text(fields.get("调用方式")).strip(),
        "size": extract_text(fields.get("画面尺寸")).strip(),
        "aspect_ratio": extract_text(fields.get("画面比例")).strip(),
        "params": extract_text(fields.get("AI参数JSON")).strip(),
    }


def resolve_video_route(fields: Dict[str, Any], token: Optional[str] = None) -> ai_routing.AiRoute:
    token = token or get_feishu_token()
    model_choice = extract_text(fields.get("视频生成模型")).strip()
    params = parse_json_object(fields.get("视频AI参数JSON"), field_name="视频AI参数JSON")
    size = extract_text(fields.get("视频画面尺寸")).strip()
    aspect_ratio = extract_text(fields.get("视频画面比例")).strip()
    seconds = extract_text(fields.get("视频时长秒")).strip()
    if size:
        params["size"] = size
    if aspect_ratio:
        params["aspect_ratio"] = aspect_ratio
    if seconds:
        params["seconds"] = seconds

    config_records = safe_list_records(token, TABLE_CONFIG)
    if model_choice and not model_choice.startswith("默认"):
        cfg = config_fields_to_runtime(selected_config_record_for_model(config_records, model_choice))
    else:
        cfg = get_model_config(token, DEFAULT_VIDEO_STAGE_NAME)
        model = cfg.get("model") or DEFAULT_OTU_MODEL
        if " / " not in model:
            model = f"OTU / {model}"
        cfg["provider"] = ai_routing.parse_model_display(model)["provider"] or cfg.get("provider") or "OTU"
        cfg["model"] = model
    route = ai_routing.route_from_record(
        {
            ai_routing.AI_MODEL_FIELD: cfg["model"],
            ai_routing.AI_CAPABILITY_FIELD: "视频",
            ai_routing.AI_TASK_TYPE_FIELD: "首帧图生视频",
            ai_routing.AI_PARAMS_FIELD: json.dumps(params, ensure_ascii=False),
        },
        {
            **cfg,
            "capability": "视频",
            "task_type": "首帧图生视频",
            "params": params,
        },
        config_records=config_records,
    )
    route.params.update(params)
    if not route.api_key:
        raise ValueError(f"模型配置缺少 API Key: {route.model}")
    return route


def collect_omni_video_references(
    token: str,
    fields: Dict[str, Any],
    work_dir: Path,
    *,
    generated_image_token: str,
    generated_image_path: str,
) -> List[Dict[str, str]]:
    extra_refs = collect_image_references(token, fields, work_dir)
    if len(extra_refs) > MAX_OMNI_VIDEO_REFERENCES - 1:
        raise ValueError(
            f"Omni 参考图数量超过上限：生成图固定 1 张，附加参考图当前 {len(extra_refs)} 张，最多 {MAX_OMNI_VIDEO_REFERENCES - 1} 张"
        )
    prepared_refs = prepare_product_reference_images(extra_refs, work_dir)
    return [
        {
            "role": "generated_image",
            "file_token": generated_image_token,
            "name": "008 generated image",
            "path": generated_image_path,
        },
        *prepared_refs,
    ]


def _extract_result_url(data: Mapping[str, Any]) -> str:
    routed_url = ai_routing.extract_video_result_url(data)
    if routed_url:
        return routed_url
    candidates = [
        data.get("upsample_video_url"),
        data.get("video_url"),
        data.get("result_url"),
        data.get("url"),
        data.get("download_url"),
    ]
    for key in ("detail", "data", "result", "output"):
        nested = data.get(key) if isinstance(data.get(key), Mapping) else {}
        candidates.extend([nested.get("upsample_video_url"), nested.get("video_url"), nested.get("result_url"), nested.get("url"), nested.get("download_url")])
    for key in ("result_urls", "urls", "videos"):
        value = data.get(key)
        if isinstance(value, list) and value:
            first = value[0]
            if isinstance(first, str):
                candidates.append(first)
            elif isinstance(first, Mapping):
                candidates.extend([first.get("url"), first.get("video_url"), first.get("download_url")])
    for value in candidates:
        text = extract_text(value).strip()
        if text.startswith("http"):
            return text
    return ""


def poll_happyhorse_video_task(route: ai_routing.AiRoute, task_id: str) -> Dict[str, Any]:
    url = ai_routing.media_task_endpoint(route, task_id)
    headers = {"Authorization": f"Bearer {route.api_key}"}
    start = time.time()
    last_body: Dict[str, Any] = {}
    while time.time() - start < MAX_POLL_SECONDS:
        resp = aitgenne_get(url, headers=headers, timeout=POLL_TIMEOUT)
        try:
            body = resp.json()
        except Exception:
            body = {"raw_text": resp.text[:1000]}
        last_body = body if isinstance(body, dict) else {"raw": body}
        if resp.status_code >= 400:
            raise RuntimeError(f"Aitgenne 视频任务轮询失败: HTTP {resp.status_code}, body={str(last_body)[:1200]}")
        status = ai_routing.extract_video_status(last_body)
        if status in {"completed", "succeeded", "success", "done"} or _extract_result_url(last_body):
            return last_body
        if status in {"failed", "error", "cancelled", "canceled"}:
            raise RuntimeError(f"Aitgenne 视频生成失败: {str(last_body)[:1500]}")
        time.sleep(POLL_INTERVAL)
    raise TimeoutError(f"Aitgenne 视频任务超时: task_id={task_id}, last={str(last_body)[:1200]}")


def run_video_generation(
    route: ai_routing.AiRoute,
    prompt: str,
    image_path: str,
    out_path: str,
    *,
    image_url: str = "",
    refs: Optional[List[Dict[str, str]]] = None,
) -> VideoGenerationResult:
    params = dict(route.params or {})
    size = extract_text(params.get("size")).strip() or DEFAULT_OTU_SIZE
    aspect_ratio = extract_text(params.get("aspect_ratio")).strip() or DEFAULT_ASPECT_RATIO
    seconds = normalize_seconds(params.get("seconds") or params.get("视频时长") or "8")
    model_name = _route_model_name(route)
    if is_otu_omni_video_route(route):
        submitted_refs = refs or []
        if not submitted_refs:
            raise ValueError("Omni 参考图生视频至少需要 1 张参考图")
        if len(submitted_refs) > MAX_OMNI_VIDEO_REFERENCES:
            raise ValueError(f"Omni 参考图数量超过上限：当前 {len(submitted_refs)} 张，最多 {MAX_OMNI_VIDEO_REFERENCES} 张")
        cfg = {"api_key": route.api_key, "api_base": route.api_base or DEFAULT_OTU_API_BASE, "model": model_name}
        task_id, submit_body = submit_omni_video_task(cfg, prompt, submitted_refs, size=size, aspect_ratio=aspect_ratio)
        result_body = poll_omni_video_task(cfg, task_id)
        video_url = extract_video_url(result_body)
        if not video_url:
            raise RuntimeError(f"OTU Omni 生成完成但未返回可下载视频 URL: {compact_json(result_body, 1200)}")
        download_video(video_url, out_path)
        return VideoGenerationResult(
            provider=route.provider,
            task_id=task_id,
            submit_body=submit_body,
            result_body=result_body,
            output_path=out_path,
            request_summary={
                "mode": "reference_image_video",
                "reference_count": len(submitted_refs),
                "reference_roles": [ref.get("role", "") for ref in submitted_refs],
                "size": size,
                "aspect_ratio": aspect_ratio,
            },
            video_url=video_url,
        )
    if route.provider == "OTU":
        cfg = {"api_key": route.api_key, "api_base": route.api_base or DEFAULT_OTU_API_BASE, "model": model_name}
        task_id, submit_body = submit_otu_video_task(cfg, prompt, image_path, seconds, size, aspect_ratio)
        result_body = poll_otu_video_task(cfg, task_id)
        video_url = extract_video_url(result_body)
        if not video_url:
            raise RuntimeError(f"OTU 生成完成但未返回可下载视频 URL: {compact_json(result_body, 1200)}")
        download_video(video_url, out_path)
        return VideoGenerationResult(
            provider=route.provider,
            task_id=task_id,
            submit_body=submit_body,
            result_body=result_body,
            output_path=out_path,
            request_summary={"reference_count": 1, "size": size, "aspect_ratio": aspect_ratio, "seconds": seconds},
            video_url=video_url,
        )
    if route.provider == "Aitgenne" and ai_routing.is_aitgenne_unified_video_model(route):
        submitted_refs = refs or []
        reference_urls = [extract_text(ref.get("url")).strip() for ref in submitted_refs if extract_text(ref.get("url")).strip()]
        if not reference_urls and image_url:
            reference_urls = [image_url]
        if not reference_urls:
            raise ValueError("Aitgenne unified 图生视频需要至少 1 张参考图 URL")
        payload = ai_routing.build_aitgenne_unified_video_payload(route, prompt, reference_urls, aspect_ratio=aspect_ratio)
        resp = aitgenne_post(
            ai_routing.media_endpoint(route),
            headers={"Authorization": f"Bearer {route.api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=SUBMIT_TIMEOUT,
        )
        try:
            submit_body = resp.json()
        except Exception:
            submit_body = {"raw_text": resp.text[:1000]}
        if resp.status_code >= 400:
            raise RuntimeError(f"Aitgenne 视频任务提交失败: HTTP {resp.status_code}, body={str(submit_body)[:1200]}")
        task_id = ai_routing.extract_video_task_id(submit_body)
        if not task_id:
            raise RuntimeError(f"Aitgenne 视频任务提交未返回任务 ID: {str(submit_body)[:1200]}")
        result_body = poll_happyhorse_video_task(route, task_id)
        video_url = _extract_result_url(result_body)
        if not video_url:
            raise RuntimeError(f"Aitgenne 生成完成但未返回可下载视频 URL: {compact_json(result_body, 1200)}")
        download_video_without_env_proxy(video_url, out_path)
        return VideoGenerationResult(
            provider=route.provider,
            task_id=task_id,
            submit_body=submit_body,
            result_body=result_body,
            output_path=out_path,
            request_summary={
                "mode": "aitgenne_unified_video",
                "reference_count": len(reference_urls),
                "reference_urls": reference_urls,
                "size": size,
                "aspect_ratio": aspect_ratio,
            },
            video_url=video_url,
        )
    if route.provider == "Aitgenne" and ai_routing.is_aitgenne_happyhorse_model(route):
        if not image_url:
            raise ValueError("Aitgenne HappyHorse 图生视频需要生成图片的临时下载 URL")
        payload = ai_routing.build_happyhorse_video_payload(route, prompt, [image_url], size=size, aspect_ratio=aspect_ratio, seconds=seconds)
        resp = aitgenne_post(
            ai_routing.media_endpoint(route),
            headers={"Authorization": f"Bearer {route.api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=SUBMIT_TIMEOUT,
        )
        try:
            submit_body = resp.json()
        except Exception:
            submit_body = {"raw_text": resp.text[:1000]}
        if resp.status_code >= 400:
            raise RuntimeError(f"Aitgenne 视频任务提交失败: HTTP {resp.status_code}, body={str(submit_body)[:1200]}")
        task_id = ai_routing.extract_video_task_id(submit_body)
        if not task_id:
            raise RuntimeError(f"Aitgenne 视频任务提交未返回任务 ID: {str(submit_body)[:1200]}")
        result_body = poll_happyhorse_video_task(route, task_id)
        video_url = _extract_result_url(result_body)
        if not video_url:
            raise RuntimeError(f"Aitgenne 生成完成但未返回可下载视频 URL: {compact_json(result_body, 1200)}")
        download_video_without_env_proxy(video_url, out_path)
        return VideoGenerationResult(
            provider=route.provider,
            task_id=task_id,
            submit_body=submit_body,
            result_body=result_body,
            output_path=out_path,
            request_summary={"reference_count": 1, "size": size, "aspect_ratio": aspect_ratio, "seconds": seconds},
            video_url=video_url,
        )
    if route.provider == "AIHubMix":
        cfg = {"api_key": route.api_key, "api_base": route.api_base or DEFAULT_API_BASE, "model": model_name or DEFAULT_NATIVE_VIDEO_MODEL}
        client = get_native_veo_client(cfg)
        resolution = normalize_native_veo_resolution(size)
        operation = call_native_veo_first_frame_task(client, cfg["model"], prompt, image_path, seconds=seconds, aspect_ratio=aspect_ratio, resolution=resolution)
        task_id = native_generated_video_uri(extract_native_generated_video(operation)) if not is_native_veo_operation_id(operation) else operation_to_dict(operation).get("name", "")
        result = operation if not is_native_veo_operation_id(operation) else poll_native_veo_operation(client, operation)
        generated_video = extract_native_generated_video(result)
        video_uri = native_generated_video_uri(generated_video)
        download_native_veo_video(client, generated_video, out_path)
        return VideoGenerationResult(
            provider=route.provider,
            task_id=task_id or video_uri,
            submit_body=operation_to_dict(operation),
            result_body=operation_to_dict(result),
            output_path=out_path,
            request_summary={"reference_count": 1, "size": size, "aspect_ratio": aspect_ratio, "seconds": seconds, "resolution": resolution},
            video_url=video_uri,
        )
    raise ValueError(f"不支持的视频模型供应商: {route.provider}")


def load_history(fields: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = extract_text(fields.get("历史生成记录JSON")).strip()
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except Exception:
        return []
    return parsed if isinstance(parsed, list) else []


def history_patch(fields: Dict[str, Any], item: Dict[str, Any]) -> str:
    history = load_history(fields)
    history.append(item)
    return compact_json(history[-50:])


def maybe_auto_approve_image(
    token: str,
    record_id: str,
    fields: Dict[str, Any],
    *,
    file_token: str,
    table_key: str = DEFAULT_TABLE_KEY,
) -> Dict[str, Any]:
    table_id = table_id_for_key(table_key)
    if not auto_review_enabled(token, stage_name=auto_review_stage_for_key(table_key)):
        return {"status": "disabled"}
    if not file_token:
        return {"status": "skipped", "reason": "missing_file_token"}
    patch = {
        "图片审核状态": "通过",
        "错误信息": "",
    }
    if extract_text(fields.get("图生视频提示词")).strip():
        patch["视频生成状态"] = "待生成"
    safe_update_record(token, table_id, record_id, filter_existing_fields(token, table_id, patch))
    return {"status": "auto_approved", "triggered_video": patch.get("视频生成状态") == "待生成"}


def apply_prompt_image_default_to_record(
    token: str,
    record_id: str,
    fields: Dict[str, Any],
    *,
    table_key: str = DEFAULT_TABLE_KEY,
) -> Dict[str, Any]:
    table_id = table_id_for_key(table_key)
    return apply_task_default_to_record(
        token,
        table_id,
        record_id,
        fields,
        app_table=app_table_for_key(table_key),
        stage="图片生成默认",
        model_field="图片AI模型",
        size_field="图片画面尺寸",
        ratio_field="图片画面比例",
        params_field="图片AI参数JSON",
        field_filter=filter_existing_fields,
    )


def apply_prompt_video_default_to_record(
    token: str,
    record_id: str,
    fields: Dict[str, Any],
    *,
    table_key: str = DEFAULT_TABLE_KEY,
) -> Dict[str, Any]:
    table_id = table_id_for_key(table_key)
    return apply_task_default_to_record(
        token,
        table_id,
        record_id,
        fields,
        app_table=app_table_for_key(table_key),
        stage="图生视频生成默认",
        model_field="视频生成模型",
        size_field="视频画面尺寸",
        ratio_field="视频画面比例",
        params_field="视频AI参数JSON",
        field_filter=filter_existing_fields,
    )


def run_image(
    token: str,
    record_id: str,
    *,
    regenerate: bool = False,
    dry_run: bool = False,
    table_key: str = DEFAULT_TABLE_KEY,
) -> Dict[str, Any]:
    ensure_table(table_key)
    table_id = table_id_for_key(table_key)
    fields = safe_get_record(token, table_id, record_id)
    if table_key == DEFAULT_TABLE_KEY:
        fields = apply_prompt_image_default_to_record(token, record_id, fields)
    else:
        fields = apply_prompt_image_default_to_record(token, record_id, fields, table_key=table_key)
    prompt = extract_text(fields.get("生图提示词")).strip()
    if not prompt:
        raise ValueError("生图提示词为空")
    has_existing_image = bool(latest_media_token(fields, "生成图片", "图片file_token"))
    version = current_version(fields, "图片版本") + (1 if (regenerate or has_existing_image) else 0)
    work_dir = ensure_work_dir(record_id, "image", version, table_key=table_key)
    refs = collect_image_references(token, fields, work_dir)
    refs = prepare_product_reference_images(refs, work_dir)
    image_params = parse_json_object(fields.get("图片AI参数JSON"), field_name="图片AI参数JSON")
    size = extract_text(fields.get("图片画面尺寸")).strip() or image_params.get("size") or DEFAULT_OTU_IMAGE_SIZE
    aspect_ratio = extract_text(fields.get("图片画面比例")).strip() or image_params.get("aspect_ratio") or "9:16"
    if size:
        image_params["size"] = size
    if aspect_ratio:
        image_params["aspect_ratio"] = aspect_ratio
    cfg = get_model_config(token, IMAGE_STAGE_NAME)
    config_records = config_records_for_image_slot(fields, "图片", lambda: safe_list_records(token, TABLE_CONFIG))
    route = resolve_image_route_from_slot(fields, "图片", cfg, task_type="文生图/图生图", params=image_params, config_records=config_records)
    image_params = image_params_with_model_overrides(route, image_params)
    route.params.update(image_params)
    summary = {
        "record_id": record_id,
        "dry_run": dry_run,
        "prompt_chars": len(prompt),
        "reference_count": len(refs),
        "reference_manifest": [{k: ref[k] for k in ("role", "file_token", "name") if k in ref} for ref in refs],
        "version": version,
        "model": route.model,
    }
    if dry_run:
        summary["status"] = "dry_run_ready"
        return summary
    safe_update_record(token, table_id, record_id, filter_existing_fields(token, table_id, {
        "图片版本": version,
        **image_slot_field_patch("图片", image_params),
        "图片生成状态": "生成中",
        "图片错误信息": "",
        "错误信息": "",
        "参考图数量": len(refs),
        "参考图清单JSON": compact_json(summary["reference_manifest"]),
    }))
    out_path = str(work_dir / f"{record_id}_image_v{version}.png")
    image_kwargs = {
        "input_mode": "image-to-image" if refs else "text-to-image",
        "reference_image_paths": [ref["path"] for ref in refs],
    }
    if route.provider == "OTU" and refs:
        image_kwargs["reference_count_override"] = len(refs)
        if len(refs) == 1:
            image_kwargs["image_path"] = refs[0]["path"]
        else:
            image_kwargs["image_path"] = build_reference_contact_sheet(refs, work_dir / "reference_contact_sheet.png")
        image_kwargs["reference_image_paths"] = None
    product_visual_description = describe_product_reference_images(token, refs)
    product_lock_prompt = build_product_reference_lock_prompt(refs, product_visual_description)
    final_prompt = "\n\n".join(part for part in [product_lock_prompt, prompt] if part).strip()
    result = run_image_generation(
        route,
        final_prompt,
        out_path,
        **image_kwargs,
        metadata=image_params,
        size=str(image_params.get("size") or size),
        aspect_ratio=str(image_params.get("aspect_ratio") or aspect_ratio),
        on_task_submitted=lambda task_id: safe_update_record(token, table_id, record_id, filter_existing_fields(token, table_id, {
            "图片任务ID": task_id,
            "图片错误信息": f"已提交图片任务，正在轮询。task_id={task_id}",
        })),
    )
    file_token = upload_image_to_feishu(token, result.output_path, Path(result.output_path).name)
    success_fields = {
        **image_slot_field_patch("图片", image_params),
        "图片版本": version,
        "图片生成状态": "成功",
        "生成图片": [{"file_token": file_token, "name": Path(result.output_path).name}],
        "图片file_token": file_token,
        "图片本地路径": result.output_path,
        "图片任务ID": result.task_id,
        "图片原始响应JSON": compact_json({
            "submit": result.submit_body,
            "result": result.result_body,
            "request_summary": result.request_summary,
        }),
        "图片审核状态": "待确认",
        "图片错误信息": "",
        "错误信息": "",
        "图片生成时间": int(time.time() * 1000),
        "生成时间": int(time.time() * 1000),
        "历史生成记录JSON": history_patch(fields, {"stage": "image", "version": version, "file_token": file_token, "task_id": result.task_id, "time": int(time.time() * 1000)}),
    }
    safe_update_record(token, table_id, record_id, filter_existing_fields(token, table_id, success_fields))
    auto_review_summary = maybe_auto_approve_image(token, record_id, {**fields, **success_fields}, file_token=file_token, table_key=table_key)
    summary.update({"status": "success", "file_token": file_token, "task_id": result.task_id, "auto_review": auto_review_summary})
    return summary


def run_video(
    token: str,
    record_id: str,
    *,
    regenerate: bool = False,
    dry_run: bool = False,
    table_key: str = DEFAULT_TABLE_KEY,
) -> Dict[str, Any]:
    ensure_table(table_key)
    table_id = table_id_for_key(table_key)
    fields = safe_get_record(token, table_id, record_id)
    if table_key == DEFAULT_TABLE_KEY:
        fields = apply_prompt_video_default_to_record(token, record_id, fields)
    else:
        fields = apply_prompt_video_default_to_record(token, record_id, fields, table_key=table_key)
    if extract_text(fields.get("图片审核状态")).strip() != "通过":
        raise ValueError("图片审核状态必须为通过，才能生成视频")
    prompt = extract_text(fields.get("图生视频提示词")).strip()
    if not prompt:
        raise ValueError("图生视频提示词为空")
    image_token = latest_media_token(fields, "生成图片", "图片file_token")
    if not image_token:
        raise ValueError("缺少已生成图片，无法图生视频")
    has_existing_video = bool(latest_media_token(fields, "生成视频", "生成视频file_token"))
    version = current_version(fields, "视频版本") + (1 if (regenerate or has_existing_video) else 0)
    work_dir = ensure_work_dir(record_id, "video", version, table_key=table_key)
    image_save_path = work_dir / f"generated_image_v{current_version(fields, '图片版本')}.png"
    image_path = Path(_downloaded_path(download_feishu_attachment_raw(token, image_token, image_save_path), image_save_path))
    route = resolve_video_route(fields, token)
    image_url = get_tmp_download_url_for_attachment(token, image_token) if route.provider == "Aitgenne" else ""
    refs = None
    if is_otu_omni_video_route(route) or ai_routing.is_aitgenne_unified_components_model(route):
        refs = collect_omni_video_references(
            token,
            fields,
            work_dir,
            generated_image_token=image_token,
            generated_image_path=str(image_path),
        )
        if ai_routing.is_aitgenne_unified_components_model(route):
            if len(refs) > 3:
                raise ValueError(f"Aitgenne components 参考图数量超过上限：当前 {len(refs)} 张，最多 3 张")
            for ref in refs:
                file_token = extract_text(ref.get("file_token")).strip()
                if file_token:
                    ref["url"] = get_tmp_download_url_for_attachment(token, file_token)
    out_path = str(work_dir / f"{record_id}_video_v{version}.mp4")
    summary = {
        "record_id": record_id,
        "dry_run": dry_run,
        "prompt_chars": len(prompt),
        "first_frame_image_path": str(image_path),
        "version": version,
        "model": route.model,
    }
    if refs is not None:
        summary["reference_count"] = len(refs)
        summary["reference_roles"] = [ref.get("role", "") for ref in refs]
    if dry_run:
        summary["status"] = "dry_run_ready"
        return summary
    safe_update_record(token, table_id, record_id, filter_existing_fields(token, table_id, {
        "视频版本": version,
        "视频生成状态": "生成中",
        "视频错误信息": "",
        "错误信息": "",
    }))
    video_generation_kwargs = {"image_url": image_url}
    if refs is not None:
        video_generation_kwargs["refs"] = refs
    result = run_video_generation(route, prompt, str(image_path), out_path, **video_generation_kwargs)
    file_token = upload_video_to_feishu(token, result.output_path, Path(result.output_path).name)
    success_fields = {
        "视频版本": version,
        "视频生成状态": "成功",
        "生成视频": [{"file_token": file_token, "name": Path(result.output_path).name}],
        "生成视频file_token": file_token,
        "视频本地路径": result.output_path,
        "视频任务ID": result.task_id,
        "视频原始响应JSON": compact_json({"submit": result.submit_body, "result": result.result_body, "request_summary": result.request_summary}),
        "视频错误信息": "",
        "错误信息": "",
        "视频生成时间": int(time.time() * 1000),
        "生成时间": int(time.time() * 1000),
        "历史生成记录JSON": history_patch(fields, {"stage": "video", "version": version, "file_token": file_token, "task_id": result.task_id, "time": int(time.time() * 1000)}),
    }
    if result.video_url:
        field_types = get_table_field_types(token, table_id)
        success_fields["视频URL"] = format_url_field_value(result.video_url, field_types.get("视频URL", 0))
    safe_update_record(token, table_id, record_id, filter_existing_fields(token, table_id, success_fields))
    summary.update({"status": "success", "file_token": file_token, "task_id": result.task_id, "video_url": result.video_url})
    return summary


def run_action(action: str, record_id: str, *, dry_run: bool = False) -> Dict[str, Any]:
    token = get_feishu_token()
    if action == "image":
        return run_image(token, record_id, dry_run=dry_run)
    if action == "regenerate-image":
        return run_image(token, record_id, regenerate=True, dry_run=dry_run)
    if action == "video":
        return run_video(token, record_id, dry_run=dry_run)
    if action == "regenerate-video":
        return run_video(token, record_id, regenerate=True, dry_run=dry_run)
    raise ValueError(f"未知 action: {action}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run 008 prompt image-to-video worker")
    parser.add_argument("action", choices=["image", "video", "regenerate-image", "regenerate-video"])
    parser.add_argument("record_id")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        result = run_action(args.action, args.record_id, dry_run=args.dry_run)
        print(compact_json(result))
    except Exception as exc:
        error_payload = build_error_payload(exc, stage=f"tk_prompt_image_video.py {args.action}")
        print(json.dumps({"error": error_payload}, ensure_ascii=False), file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
