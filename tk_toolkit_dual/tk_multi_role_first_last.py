#!/usr/bin/env python3
"""
多角色事故救场关键帧/视频 worker。

用法:
  python3 tk_multi_role_first_last.py parse <parent_record_id>
  python3 tk_multi_role_first_last.py reference-image <asset_record_id>
  python3 tk_multi_role_first_last.py keyframe-image <keyframe_record_id>
  python3 tk_multi_role_first_last.py video <video_record_id>
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import requests
from google import genai
from google.genai import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (  # noqa: E402
    APP_TOKEN,
    TABLE_CONFIG,
    TABLE_MULTI_ROLE_FIRST_LAST,
    TABLE_PRODUCT,
    WORKSPACE,
    build_error_payload,
    extract_linked_record_ids,
    extract_text,
    feishu_headers,
    get_feishu_token,
    get_product_record,
    latest_media_token,
    log_event,
    safe_get_record,
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
    poll_otu_image_task,
    submit_otu_image_task,
)
from tk_shot_script_gen import extract_json_object  # noqa: E402
from tk_shot_storyboard import (  # noqa: E402
    download_feishu_media,
    filter_existing_fields,
    get_tmp_download_url_for_attachment,
)
from tk_shot_video import (  # noqa: E402
    DEFAULT_ASPECT_RATIO,
    DEFAULT_GEMINI_API_BASE,
    DEFAULT_MODEL as DEFAULT_NATIVE_VIDEO_MODEL,
    DEFAULT_OTU_MODEL,
    DEFAULT_OTU_SIZE,
    call_native_veo_first_frame_task,
    download_video,
    download_native_veo_video,
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
    upload_video_to_feishu,
    video_item_url,
    videos_url,
)
import ai_routing  # noqa: E402
import ai_model_catalog  # noqa: E402
from image_generation import (  # noqa: E402
    config_records_for_image_slot,
    image_params_with_model_overrides,
    image_slot_field_patch,
    resolve_image_route_from_slot,
    run_image_generation,
)
from tk_model_config_center import TASK_TABLES, apply_task_default_to_fields, apply_task_default_to_record, load_stage_config_fields  # noqa: E402
from tk_auto_review import TABLE_AUTO_REVIEW_STAGE_NAMES, auto_review_enabled  # noqa: E402


AUTO_REVIEW_STAGE_NAME = TABLE_AUTO_REVIEW_STAGE_NAMES["multi_role_first_last"]
PARSE_STAGE_NAME = "多角色首尾帧解析-Gemini"
IMAGE_STAGE_NAME = "图片生成-OTU"
VIDEO_STAGE_NAME = "分镜视频生成-OTU"
AIHUBMIX_VIDEO_STAGE_NAME = "分镜视频生成-Veo"
PARENT_RECORD_TYPE = "母任务"
ASSET_RECORD_TYPE = "参考资产"
KEYFRAME_RECORD_TYPE = "关键帧"
VIDEO_RECORD_TYPE = "视频片段"
ACTIVE_RECORD_STATES = {"", "有效"}
KEYFRAME_TYPES = ["S01_FIRST", "S01_TAIL_SHARED_S02_FIRST", "S02_TAIL"]
CANONICAL_KEYFRAME_DEPENDENCIES = {
    "S01_FIRST": "",
    "S01_TAIL_SHARED_S02_FIRST": "S01_FIRST",
    "S02_TAIL": "S01_TAIL_SHARED_S02_FIRST",
}
VIDEO_CLIP_TYPES = ["S01", "S02"]
BASE_WORK_DIR = Path(WORKSPACE) / "multi_role_first_last_work"
SUBMIT_TIMEOUT = 180


DEFAULT_PARSE_PROMPT = """
你是多角色事故救场短视频的首尾帧生产规划器。用户会给你一个强冲突事故/救场脚本。

请只做结构化拆解，不改写创意，不虚构产品能力。角色数量必须由脚本决定，可以是 3 个、4 个、5 个或更多，不要写死。

输出严格 JSON，不要 markdown，不要解释。顶层格式：
{
  "roles": [
    {
      "role_id": "role_a",
      "role_name": "角色名称",
      "story_function": "discoverer | rescuer | troublemaker | witness | helper | other",
      "visual_description": "外观与身份描述",
      "needs_reference_image": true
    }
  ],
  "conflict_mechanism": {
    "discoverer_role_id": "role_id 或空",
    "rescuer_role_id": "role_id 或空",
    "troublemaker_role_id": "role_id 或空",
    "accident_source": "事故源"
  },
  "assets": [
    {
      "asset_id": "role_a",
      "asset_type": "human | pet | environment",
      "asset_name": "参考资产名称",
      "prompt": "生成该角色/环境参考图的完整提示词",
      "source_role_ids": ["role_a"]
    }
  ],
  "keyframes": [
    {
      "keyframe_type": "S01_FIRST | S01_TAIL_SHARED_S02_FIRST | S02_TAIL",
      "title": "画面标题",
      "prompt": "完整生图提示词",
      "visible_role_ids": ["实际出现在画面里的 role_id"],
      "reference_requirements": {
        "use_product_reference": false,
        "asset_ids": ["本画面需要传入的 asset_id"],
        "depends_on_keyframe_type": "",
        "reason": "为什么只使用这些参考图"
      }
    }
  ],
  "videos": [
    {
      "clip_type": "S01 | S02",
      "title": "片段标题",
      "first_keyframe_type": "S01_FIRST",
      "last_keyframe_type": "S01_TAIL_SHARED_S02_FIRST",
      "prompt": "图生视频提示词",
      "duration_sec": 8
    }
  ]
}

视频口播与音频规则：
- videos[].prompt 必须整体使用英文描述 visual/action/camera/environment/product action/SFX/ambient noise/restrictions。
- If the input script contains Chinese visual/action/production directions, faithfully translate Chinese visual/action directions into English inside videos[].prompt while preserving every concrete conflict detail, product action, visible problem anchor, camera beat, and reaction reversal.
- videos[].prompt must not contain Chinese or CJK text: no Chinese explanations, Chinese action descriptions, Chinese parenthetical notes, or Chinese review notes.
- preserve Thai dialogue exactly: keep Thai dialogue and Thai voiceover text in Thai, and do not translate Thai speech into English or Chinese.
- videos[].prompt 如果包含人物/宠物画面内说话，必须用冒号直接承接泰语台词，例如：The influencer says in Thai: กลิ่นฉี่แมวแรงมาก ทำยังไงดีเนี่ย
- 画外旁白使用：Thai voiceover: [泰语口播]
- 不得用英文引号包住台词；台词只作为音频层，不得生成字幕、贴纸或画面文字。
- 单独写清楚 dialogue、ambient noise、sound effects、voice tone/timbre；没有口播时写 No speech. Natural ambient sound only.

参考资产规则：
- assets[] 只允许 human / pet / environment。产品、产品包装、瓶身、喷雾瓶、清洁剂/除味剂/除臭剂/去味剂不得进入 assets[]，不得生成 product_ref / product / bottle / spray_bottle 等产品参考资产。
- 产品一致性只能通过 keyframes[].reference_requirements.use_product_reference=true 表达，由系统从关联产品记录读取真实上传产品图。
- human / pet 资产只生成该资产本身，不要混入其他角色、产品或完整剧情。
- human 资产必须生成 single person 的真实人物参考图：one angle, front-facing upper-body portrait, full unobstructed face visible, pure white background；人物必须正对镜头，腰部以上半身构图，完整露出全脸，双眼、鼻子、嘴巴清晰可见。
- human 资产必须写成 UGC smartphone photo 风格：普通手机拍摄质感、自然光感、日常衣着、本地素人感、natural skin texture、毛孔、细纹、小瑕疵、轻微不完美；背景仍必须是 pure white background；not studio, not advertising, not commercial portrait, not fashion model, not beauty retouching。
- human 资产必须明确禁止 no side profile、侧脸、背影、低头遮脸、墨镜遮脸、头发/手/道具遮挡脸部。
- human 资产必须明确禁止 no multi-view、多视角拼图、角色设定表、character sheet、no contact sheet、turnaround、正侧背多角度、before/after split、海报、字幕、logo、水印。
- environment 资产必须是无人无产品的事故现场环境底图，只能描述房间、家具、材质、光线、机位、可行动空间、生活道具和脚本明确写出的固定问题发生点。
- environment 资产必须根据脚本判断环境图中应该出现什么问题锚点；只保留脚本明确写出的可见问题发生点和位置细节。
- environment 资产不能默认套用尿渍，不能默认套用虫害，也不能默认套用污渍、破损或任何固定事故类型；脚本没有明确可见问题锚点时，不得编造事故点。
- environment prompt 必须是直接给图片模型使用的画面描述，只写场景中可见内容；不得写 source script、if present、if one exists、when present in the script、script-defined 这类元指令。
- environment 资产严禁出现任何人物、宠物、产品包装、喷雾瓶、手、身体局部、倒影、海报/屏幕中的人物或动物。
- 如果脚本文档要求“场景图不要出现人物/产品/宠物”，必须完全遵守；不要把角色站位规划写进 environment prompt。

关键帧固定三张：
1. S01_FIRST
2. S01_TAIL_SHARED_S02_FIRST
3. S02_TAIL

关键帧依赖关系固定：
- S01_FIRST 的 depends_on_keyframe_type 必须为空。
- S01_TAIL_SHARED_S02_FIRST 的 depends_on_keyframe_type 必须是 S01_FIRST。
- S02_TAIL 的 depends_on_keyframe_type 必须是 S01_TAIL_SHARED_S02_FIRST。

但每张关键帧使用哪些产品/角色/环境参考图，必须根据脚本画面内容决定，不按帧位硬编码。
- 如果关键帧画面出现产品本体、产品包装、瓶身、喷雾瓶、清洁剂/除味剂/除臭剂/去味剂，或出现拿起、展示、喷洒、倒出、擦拭等产品使用动作，该关键帧 reference_requirements.use_product_reference 必须为 true，即使它是 S01_FIRST。
- 只有纯人物/宠物/环境铺垫、且明确没有产品出镜或产品使用动作的关键帧，才允许 use_product_reference 为 false。
""".strip()


def compact_json(value: Any, max_chars: int = 20000) -> str:
    text = json.dumps(value, ensure_ascii=False, indent=2, default=str)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 200] + "\n...TRUNCATED..."


def _as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _csv(items: Iterable[Any]) -> str:
    return ",".join(str(item).strip() for item in items if str(item).strip())


def _split_csv(value: Any) -> List[str]:
    raw = extract_text(value).strip()
    return [item.strip() for item in raw.split(",") if item.strip()]


def _yes(value: Any) -> bool:
    return extract_text(value).strip().lower() in {"是", "yes", "true", "1", "需要", "y"}


def _attachment_tokens(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    tokens = []
    for item in value:
        if isinstance(item, dict) and item.get("file_token"):
            tokens.append(str(item["file_token"]).strip())
    return [token for token in tokens if token]


def _link_ids(value: Any) -> List[str]:
    ids = extract_linked_record_ids(value)
    if ids:
        return ids
    text = extract_text(value).strip()
    return [text] if text.startswith("rec") else []


def current_version(fields: Dict[str, Any], name: str) -> int:
    raw = fields.get(name)
    try:
        return int(float(extract_text(raw) or raw or 1))
    except Exception:
        return 1


def next_version(fields: Dict[str, Any], name: str) -> int:
    return current_version(fields, name) + 1


def ensure_multi_role_table() -> None:
    if not TABLE_MULTI_ROLE_FIRST_LAST:
        raise RuntimeError("config.json 尚未配置 multi_role_first_last 表 ID")


def ensure_active_record(fields: Dict[str, Any]) -> None:
    state = extract_text(fields.get("记录状态")).strip()
    if state not in ACTIVE_RECORD_STATES:
        raise RuntimeError(f"记录状态已变更为 {state or '<empty>'}，停止处理")


def record_type(fields: Dict[str, Any]) -> str:
    return extract_text(fields.get("记录类型")).strip()


def review_passed(value: Any) -> bool:
    return extract_text(value).strip() in {"通过", "已触发下游"}


def make_batch_id(record_id: str) -> str:
    return f"MRFL-BATCH-{time.strftime('%Y%m%d%H%M%S')}-{record_id[-6:]}"


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


def _base_v3_filter_records(token: str, table_id: str, filter_payload: Dict[str, Any], *, limit: int = 100) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    offset = 0
    while True:
        encoded_filter = urllib.parse.quote(json.dumps(filter_payload, ensure_ascii=False))
        url = (
            f"https://open.feishu.cn/open-apis/base/v3/bases/{APP_TOKEN}/tables/{table_id}/records"
            f"?filter={encoded_filter}&limit={limit}&offset={offset}"
        )
        data = safe_request(
            "get",
            url,
            headers=feishu_headers(token),
            timeout=30,
            max_attempts=3,
            acceptable_codes=(0,),
        )
        payload = data.get("data") or {}
        field_names = payload.get("fields") or []
        rows = payload.get("data") or []
        record_ids = payload.get("record_id_list") or []
        for idx, row in enumerate(rows):
            record_id = record_ids[idx] if idx < len(record_ids) else ""
            fields = {
                field_name: row[field_idx] if field_idx < len(row) else None
                for field_idx, field_name in enumerate(field_names)
                if field_name
            }
            records.append({"record_id": record_id, "fields": fields})
        if not payload.get("has_more"):
            break
        if not rows:
            break
        offset += len(rows)
    return records


def list_multi_role_records_for_parent(token: str, parent_record_id: str, *, include_deprecated: bool = False) -> List[Dict[str, Any]]:
    filter_payload = {
        "logic": "and",
        "conditions": [["父任务记录ID", "==", parent_record_id]],
    }
    records = _base_v3_filter_records(token, TABLE_MULTI_ROLE_FIRST_LAST, filter_payload)
    result = []
    for rec in records:
        fields = rec.get("fields", {})
        if extract_text(fields.get("父任务记录ID")).strip() != parent_record_id:
            continue
        if not include_deprecated and extract_text(fields.get("记录状态")).strip() == "已废弃":
            continue
        result.append(rec)
    return result


def ensure_stage_work_dir(record_id: str, stage: str, version: int = 1) -> Path:
    path = BASE_WORK_DIR / record_id / f"{stage}_v{version}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def normalize_role(role: Dict[str, Any], idx: int) -> Dict[str, Any]:
    role_id = extract_text(role.get("role_id") or role.get("id")).strip() or f"role_{idx}"
    return {
        "role_id": role_id,
        "role_name": extract_text(role.get("role_name") or role.get("name")).strip() or role_id,
        "story_function": extract_text(role.get("story_function") or role.get("function")).strip() or "other",
        "visual_description": extract_text(role.get("visual_description") or role.get("description")).strip(),
        "needs_reference_image": bool(role.get("needs_reference_image", True)),
    }


ENVIRONMENT_EMPTY_SCENE_PREFIX = """
EMPTY ENVIRONMENT REFERENCE PLATE ONLY.
Generate one empty lived-in home environment reference image for later compositing. Show only the room, furniture, surfaces, lighting, camera angle, non-character household props, and any visible problem marks explicitly described in Scene details. If Scene details include visible problem marks, render exactly those marks and their described locations. If no problem mark is described, do not invent any visible problem mark or odor source. Do not include any people, pets, product bottles, spray packaging, hands, body parts, reflections of people or animals, posters/screens containing people or animals, text, subtitles, logos, or watermarks.
""".strip()

ENVIRONMENT_LEGACY_PREFIX_PATTERNS = [
    re.compile(r"^Generate one empty but lived-in local home environment reference plate\b", re.IGNORECASE),
    re.compile(r"^Generate an empty scene master/background plate\b", re.IGNORECASE),
    re.compile(r"^Generate one empty lived-in home environment reference image\b", re.IGNORECASE),
    re.compile(r"^Show only the room, furniture, surfaces\b", re.IGNORECASE),
    re.compile(r"^If Scene details include visible problem marks\b", re.IGNORECASE),
    re.compile(r"^If no problem mark is described\b", re.IGNORECASE),
    re.compile(r"^The space should feel like a real local UGC phone photo\b", re.IGNORECASE),
    re.compile(r"^Do not include any people, pets, product bottles\b", re.IGNORECASE),
]
ENVIRONMENT_META_CLEANUP_PATTERNS = [
    re.compile(r"\bfrom the source script\b", re.IGNORECASE),
    re.compile(r"\bin the source script\b", re.IGNORECASE),
    re.compile(r"\bwhen present in the script\b", re.IGNORECASE),
    re.compile(r"\bif one exists\b", re.IGNORECASE),
    re.compile(r"\bscript-defined\b", re.IGNORECASE),
    re.compile(r"\bexplicit visible problem anchor\b", re.IGNORECASE),
    re.compile(r"\bsource script\b", re.IGNORECASE),
]
ENVIRONMENT_EMPTY_META_SENTENCE_PATTERNS = [
    re.compile(r"^Do not add any problem mark that is not explicitly present\\.?$", re.IGNORECASE),
]

ENVIRONMENT_FORBIDDEN_TERMS = {
    "person", "people", "human", "woman", "man", "girl", "boy", "lady", "landlord",
    "renter", "roommate", "child", "kid", "dog", "cat", "pet", "puppy", "animal",
    "bottle", "spray", "product", "角色", "人物", "人像", "真人", "女人", "男人",
    "女孩", "男孩", "房东", "租客", "室友", "孩子", "小孩", "小狗", "狗狗", "猫",
    "宠物", "动物", "产品", "喷雾", "瓶",
}

ENVIRONMENT_NEGATION_TERMS = {
    "without", "forbidden", "do not", "don't", "must not", "禁止", "不要",
    "不得", "不能", "无人物", "无人", "不出现", "严禁",
}

ENVIRONMENT_ALLOWED_NEGATIVE_PHRASES = {
    "no people", "no person", "no humans", "no human", "no woman", "no man",
    "no pets", "no pet", "no dog", "no dogs", "no cat", "no cats", "no animal",
    "no animals", "no product", "no product bottle", "no spray", "no bottle",
    "without people", "without pets", "without product", "without product bottle",
    "do not include any people", "do not include any pets", "do not include any product",
    "forbidden from appearing", "禁止人物", "禁止宠物", "禁止产品", "不要出现人物",
    "不要出现宠物", "不要出现产品", "不得出现人物", "不得出现宠物", "不得出现产品",
}

ENVIRONMENT_PROBLEM_ANCHOR_TERMS = {
    "urine stain", "pee stain", "wet patch", "visible problem area", "accident point",
    "problem area", "dirty area", "damaged spot", "damaged area", "broken spot",
    "broken area", "odor source", "smell source", "污渍", "尿渍", "湿痕",
    "湿斑", "破损", "损坏", "脏污", "问题区域", "事故点", "异味来源",
}

ENVIRONMENT_PROBLEM_ANCHOR_PATTERNS = [
    re.compile(r"\bstains?\b", re.IGNORECASE),
]

ENVIRONMENT_PROBLEM_SUBJECT_CLEANUP_PATTERNS = [
    (re.compile(r"\b(cat|dog|pet|puppy|animal)\s+(urine stain|pee stain|wet patch|stain)\b", re.IGNORECASE), r"\2"),
    (re.compile(r"\b(person|people|human|woman|man|girl|boy|lady|landlord|renter|roommate|child|kid|cat|dog|pet|puppy|animal|product|spray|bottle)\b", re.IGNORECASE), ""),
    (re.compile(r"(人物|人像|真人|女人|男人|女孩|男孩|房东|租客|室友|孩子|小孩|小狗|狗狗|猫|宠物|动物|产品|喷雾|瓶)"), ""),
]


def _environment_prompt_parts(prompt: str) -> List[str]:
    parts: List[str] = []
    for line in prompt.replace("\r\n", "\n").split("\n"):
        line = line.strip()
        if not line:
            continue
        parts.extend(part.strip() for part in re.split(r"(?<=[.!?。！？])\s+", line) if part.strip())
    return parts


def _has_environment_problem_anchor(text: str) -> bool:
    lowered = text.lower()
    return (
        any(term in lowered for term in ENVIRONMENT_PROBLEM_ANCHOR_TERMS)
        or any(pattern.search(text) for pattern in ENVIRONMENT_PROBLEM_ANCHOR_PATTERNS)
    )


def _strip_environment_prefix(prompt: str) -> str:
    text = prompt.replace(ENVIRONMENT_EMPTY_SCENE_PREFIX, "")
    lowered = text.lower()
    for marker in ("scene details to keep:", "scene details:"):
        idx = lowered.rfind(marker)
        if idx >= 0:
            return text[idx + len(marker):]
    return text


def sanitize_environment_prompt(prompt: str) -> str:
    source_prompt = _strip_environment_prefix(prompt)
    cleaned_parts: List[str] = []
    for text in _environment_prompt_parts(source_prompt):
        stripped_marker = text.strip().lower().rstrip(".。:：")
        if stripped_marker in {"empty environment reference plate only", "scene details to keep", "scene details"}:
            continue
        if any(pattern.search(text) for pattern in ENVIRONMENT_LEGACY_PREFIX_PATTERNS):
            continue
        for pattern in ENVIRONMENT_META_CLEANUP_PATTERNS:
            text = pattern.sub("", text)
        text = re.sub(r"\s{2,}", " ", text)
        text = re.sub(r"\s+([,.;:!?。！？])", r"\1", text).strip(" ,")
        if not text:
            continue
        if any(pattern.search(text) for pattern in ENVIRONMENT_EMPTY_META_SENTENCE_PATTERNS):
            continue
        lowered = text.lower()
        has_forbidden_positive = any(term in lowered for term in ENVIRONMENT_FORBIDDEN_TERMS)
        has_problem_anchor = _has_environment_problem_anchor(text)
        has_negation = (
            any(term in lowered for term in ENVIRONMENT_NEGATION_TERMS)
            or any(phrase in lowered for phrase in ENVIRONMENT_ALLOWED_NEGATIVE_PHRASES)
        )
        if has_forbidden_positive and has_problem_anchor:
            for pattern, replacement in ENVIRONMENT_PROBLEM_SUBJECT_CLEANUP_PATTERNS:
                text = pattern.sub(replacement, text)
            text = re.sub(r"\s{2,}", " ", text)
            text = re.sub(r"\s+([,.;:!?。！？])", r"\1", text).strip(" ,")
            if not text:
                continue
            lowered = text.lower()
            has_forbidden_positive = any(term in lowered for term in ENVIRONMENT_FORBIDDEN_TERMS)
        if has_forbidden_positive and not has_negation:
            continue
        if has_forbidden_positive and not any(phrase in lowered for phrase in ENVIRONMENT_ALLOWED_NEGATIVE_PHRASES) and "forbidden" not in lowered:
            continue
        cleaned_parts.append(text)
    cleaned = "\n".join(cleaned_parts).strip()
    if cleaned:
        return f"{ENVIRONMENT_EMPTY_SCENE_PREFIX}\n\nScene details:\n{cleaned}"
    return ENVIRONMENT_EMPTY_SCENE_PREFIX


def normalize_asset(asset: Dict[str, Any], idx: int) -> Dict[str, Any]:
    asset_type = extract_text(asset.get("asset_type") or asset.get("type")).strip().lower() or "human"
    if asset_type not in {"human", "pet", "environment"}:
        raise ValueError(f"assets[{idx}] asset_type 无效: {asset_type}")
    asset_id = extract_text(asset.get("asset_id") or asset.get("id")).strip() or f"{asset_type}_{idx}"
    prompt = extract_text(asset.get("prompt") or asset.get("reference_prompt")).strip()
    if not prompt:
        raise ValueError(f"assets[{idx}] 缺少 prompt")
    if asset_type == "environment":
        prompt = sanitize_environment_prompt(prompt)
    return {
        "asset_id": asset_id,
        "asset_type": asset_type,
        "asset_name": extract_text(asset.get("asset_name") or asset.get("name")).strip() or asset_id,
        "prompt": prompt,
        "source_role_ids": [extract_text(x).strip() for x in _as_list(asset.get("source_role_ids")) if extract_text(x).strip()],
    }


def normalize_reference_requirements(raw: Any) -> Dict[str, Any]:
    data = raw if isinstance(raw, dict) else {}
    asset_ids = []
    for item in _as_list(data.get("asset_ids")):
        text = extract_text(item).strip()
        if text and text not in asset_ids:
            asset_ids.append(text)
    return {
        "use_product_reference": bool(data.get("use_product_reference")),
        "asset_ids": asset_ids,
        "depends_on_keyframe_type": extract_text(data.get("depends_on_keyframe_type")).strip(),
        "reason": extract_text(data.get("reason")).strip(),
    }


PRODUCT_REFERENCE_TERMS = (
    "product",
    "branded",
    "package",
    "packaging",
    "label",
    "bottle",
    "spray",
    "sprayer",
    "cleaner",
    "deodorizer",
    "deodoriser",
    "odor remover",
    "odour remover",
    "enzyme",
    "detergent",
    "产品",
    "包装",
    "瓶身",
    "瓶子",
    "喷雾",
    "喷瓶",
    "清洁剂",
    "除味剂",
    "除臭剂",
    "祛味剂",
    "去味剂",
    "除味",
    "除臭",
    "祛味",
    "去味",
    "喷洒",
    "展示产品",
    "拿着产品",
    "使用产品",
)
PRODUCT_REFERENCE_NEGATIONS = (
    "no product",
    "without product",
    "product not visible",
    "no bottle",
    "without bottle",
    "no spray bottle",
    "without spray bottle",
    "无产品",
    "没有产品",
    "不出现产品",
    "产品不出镜",
    "无瓶",
    "没有瓶",
    "没有喷雾",
)

PRODUCT_ASSET_ID_TERMS = (
    "product",
    "product_ref",
    "product_reference",
    "product_image",
    "bottle",
    "spray_bottle",
    "sprayer",
    "package",
    "packaging",
    "产品",
    "商品",
    "包装",
    "瓶",
    "喷雾",
    "喷瓶",
)


def keyframe_text_implies_product_reference(*values: Any) -> bool:
    text = " ".join(extract_text(value).strip() for value in values if extract_text(value).strip()).lower()
    if not text:
        return False
    if any(negation in text for negation in PRODUCT_REFERENCE_NEGATIONS):
        return False
    return any(term in text for term in PRODUCT_REFERENCE_TERMS)


def product_reference_asset_id_like(value: Any) -> bool:
    text = extract_text(value).strip().lower()
    if not text:
        return False
    return any(term in text for term in PRODUCT_ASSET_ID_TERMS)


def raw_asset_is_product_reference(asset: Dict[str, Any]) -> bool:
    asset_type = extract_text(asset.get("asset_type") or asset.get("type")).strip().lower()
    if asset_type == "product":
        return True
    values = [
        asset.get("asset_id") or asset.get("id"),
        asset.get("asset_name") or asset.get("name"),
        asset.get("prompt") or asset.get("reference_prompt"),
    ]
    if asset_type == "object":
        return product_reference_asset_id_like(values[0]) or keyframe_text_implies_product_reference(*values)
    return False


def raw_asset_is_unsupported_object(asset: Dict[str, Any]) -> bool:
    asset_type = extract_text(asset.get("asset_type") or asset.get("type")).strip().lower()
    return asset_type in {"object", "product"}


def normalize_keyframe(frame: Dict[str, Any], idx: int) -> Dict[str, Any]:
    frame_type = extract_text(frame.get("keyframe_type") or frame.get("type")).strip() or KEYFRAME_TYPES[idx - 1]
    if frame_type not in KEYFRAME_TYPES:
        raise ValueError(f"keyframes[{idx}] keyframe_type 无效: {frame_type}")
    prompt = extract_text(frame.get("prompt") or frame.get("image_prompt")).strip()
    if not prompt:
        raise ValueError(f"keyframes[{idx}] 缺少 prompt")
    refs = normalize_reference_requirements(frame.get("reference_requirements"))
    if not refs["use_product_reference"] and keyframe_text_implies_product_reference(prompt, frame.get("title"), refs.get("reason")):
        refs["use_product_reference"] = True
    visible_role_ids = [extract_text(x).strip() for x in _as_list(frame.get("visible_role_ids")) if extract_text(x).strip()]
    return {
        "keyframe_type": frame_type,
        "title": extract_text(frame.get("title")).strip() or frame_type,
        "prompt": prompt,
        "visible_role_ids": visible_role_ids,
        "reference_requirements": refs,
    }


def enforce_keyframe_dependency_chain(frames: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    for frame in frames:
        refs = frame["reference_requirements"]
        refs["depends_on_keyframe_type"] = CANONICAL_KEYFRAME_DEPENDENCIES[frame["keyframe_type"]]
    return frames


def normalize_video_clip(clip: Dict[str, Any], idx: int) -> Dict[str, Any]:
    clip_type = extract_text(clip.get("clip_type") or clip.get("type")).strip() or VIDEO_CLIP_TYPES[idx - 1]
    if clip_type not in VIDEO_CLIP_TYPES:
        raise ValueError(f"videos[{idx}] clip_type 无效: {clip_type}")
    first_type = extract_text(clip.get("first_keyframe_type")).strip()
    last_type = extract_text(clip.get("last_keyframe_type")).strip()
    if first_type not in KEYFRAME_TYPES or last_type not in KEYFRAME_TYPES:
        raise ValueError(f"videos[{idx}] 首尾关键帧类型无效")
    prompt = extract_text(clip.get("prompt") or clip.get("video_prompt")).strip()
    if not prompt:
        raise ValueError(f"videos[{idx}] 缺少 prompt")
    return {
        "clip_type": clip_type,
        "title": extract_text(clip.get("title")).strip() or clip_type,
        "first_keyframe_type": first_type,
        "last_keyframe_type": last_type,
        "prompt": prompt,
        "duration_sec": int(float(clip.get("duration_sec") or 8)),
    }


def _default_videos() -> List[Dict[str, Any]]:
    return [
        {
            "clip_type": "S01",
            "title": "S01",
            "first_keyframe_type": "S01_FIRST",
            "last_keyframe_type": "S01_TAIL_SHARED_S02_FIRST",
            "prompt": "Animate S01 from accident discovery to rescue entry while preserving character and room continuity.",
            "duration_sec": 8,
        },
        {
            "clip_type": "S02",
            "title": "S02",
            "first_keyframe_type": "S01_TAIL_SHARED_S02_FIRST",
            "last_keyframe_type": "S02_TAIL",
            "prompt": "Animate S02 from product action to visible result while preserving the shared start frame.",
            "duration_sec": 8,
        },
    ]


def normalize_plan_payload(payload: Any) -> Dict[str, Any]:
    data = payload
    if isinstance(payload, str):
        data = extract_json_object(payload)
    if not isinstance(data, dict):
        raise ValueError("多角色首尾帧解析结果必须是 JSON 对象")
    roles = [normalize_role(role, idx) for idx, role in enumerate(_as_list(data.get("roles")), start=1)]
    if not roles:
        raise ValueError("解析结果缺少 roles")
    role_ids = {role["role_id"] for role in roles}
    raw_assets = [asset for asset in _as_list(data.get("assets")) if isinstance(asset, dict)]
    product_asset_ids = {
        extract_text(asset.get("asset_id") or asset.get("id")).strip()
        for asset in raw_assets
        if raw_asset_is_product_reference(asset)
    }
    product_asset_ids = {asset_id for asset_id in product_asset_ids if asset_id}
    unsupported_object_asset_ids = {
        extract_text(asset.get("asset_id") or asset.get("id")).strip()
        for asset in raw_assets
        if raw_asset_is_unsupported_object(asset)
    }
    unsupported_object_asset_ids = {asset_id for asset_id in unsupported_object_asset_ids if asset_id}
    assets = [
        normalize_asset(asset, idx)
        for idx, asset in enumerate(
            [asset for asset in raw_assets if not raw_asset_is_unsupported_object(asset)],
            start=1,
        )
    ]
    if not assets:
        for role in roles:
            if role["needs_reference_image"]:
                assets.append(normalize_asset({
                    "asset_id": role["role_id"],
                    "asset_type": "human",
                    "asset_name": role["role_name"],
                    "prompt": role["visual_description"] or role["role_name"],
                    "source_role_ids": [role["role_id"]],
                }, len(assets) + 1))
    asset_ids = {asset["asset_id"] for asset in assets}
    keyframes = [normalize_keyframe(frame, idx) for idx, frame in enumerate(_as_list(data.get("keyframes")), start=1)]
    by_frame_type = {frame["keyframe_type"]: frame for frame in keyframes}
    missing_frames = [frame_type for frame_type in KEYFRAME_TYPES if frame_type not in by_frame_type]
    if missing_frames:
        raise ValueError(f"解析结果缺少关键帧: {','.join(missing_frames)}")
    normalized_keyframes = enforce_keyframe_dependency_chain([by_frame_type[frame_type] for frame_type in KEYFRAME_TYPES])
    for frame in normalized_keyframes:
        refs = frame["reference_requirements"]
        cleaned_asset_ids = []
        removed_unsupported_asset = False
        removed_product_asset = False
        for asset_id in refs["asset_ids"]:
            if asset_id in unsupported_object_asset_ids:
                removed_unsupported_asset = True
                if asset_id in product_asset_ids or product_reference_asset_id_like(asset_id):
                    removed_product_asset = True
                continue
            if product_reference_asset_id_like(asset_id):
                removed_unsupported_asset = True
                removed_product_asset = True
                continue
            cleaned_asset_ids.append(asset_id)
        if removed_unsupported_asset:
            refs["asset_ids"] = cleaned_asset_ids
        if removed_product_asset:
            refs["use_product_reference"] = True
        missing_assets = [asset_id for asset_id in refs["asset_ids"] if asset_id not in asset_ids]
        if missing_assets:
            raise ValueError(f"{frame['keyframe_type']} 引用了不存在的参考资产: {','.join(missing_assets)}")
        missing_roles = [role_id for role_id in frame["visible_role_ids"] if role_id not in role_ids]
        if missing_roles:
            raise ValueError(f"{frame['keyframe_type']} 引用了不存在的角色: {','.join(missing_roles)}")
        dep = refs["depends_on_keyframe_type"]
        if dep and dep not in KEYFRAME_TYPES:
            raise ValueError(f"{frame['keyframe_type']} 依赖关键帧无效: {dep}")
    videos_raw = _as_list(data.get("videos")) or _default_videos()
    videos = [normalize_video_clip(clip, idx) for idx, clip in enumerate(videos_raw, start=1)]
    by_clip = {clip["clip_type"]: clip for clip in videos}
    missing_clips = [clip_type for clip_type in VIDEO_CLIP_TYPES if clip_type not in by_clip]
    if missing_clips:
        raise ValueError(f"解析结果缺少视频片段: {','.join(missing_clips)}")
    return {
        "roles": roles,
        "conflict_mechanism": data.get("conflict_mechanism") if isinstance(data.get("conflict_mechanism"), dict) else {},
        "assets": assets,
        "keyframes": normalized_keyframes,
        "videos": [by_clip[clip_type] for clip_type in VIDEO_CLIP_TYPES],
    }


def build_parse_prompt(parent_fields: Dict[str, Any], script: str, *, system_prompt: str = DEFAULT_PARSE_PROMPT) -> str:
    product = extract_text(parent_fields.get("产品名称") or parent_fields.get("关联产品记录")).strip() or "见关联产品记录"
    return f"""
{system_prompt or DEFAULT_PARSE_PROMPT}

## 目标参数
- 关联产品：{product}
- 目标单段时长：{extract_text(parent_fields.get("目标时长秒")).strip() or "8"} 秒

## 输入脚本
{script}
""".strip()


def gemini_text_or_policy_error(response: Any) -> str:
    text = getattr(response, "text", "") or ""
    if text:
        return text
    feedback = getattr(response, "prompt_feedback", None)
    block_reason = extract_text(getattr(feedback, "block_reason", "")).strip()
    block_message = extract_text(getattr(feedback, "block_reason_message", "")).strip()
    if block_reason or block_message:
        detail = " ".join(part for part in [block_reason, block_message] if part)
        raise RuntimeError(f"Gemini 文本模型安全拦截: {detail}")
    return ""


HUMAN_REFERENCE_IMAGE_RULES = """
Human reference image hard rules:
- Generate exactly one single person only.
- Use a pure white background.
- Use a front-facing upper-body portrait, framed from waist or chest up.
- The person must look straight at the camera.
- The full unobstructed face visible: both eyes, nose, and mouth must be clear and sharp.
- Keep natural skin texture, pores, fine lines, minor blemishes, everyday clothing, and ordinary local UGC realism.
- no side profile, no back view, no looking down, no covered face, no sunglasses, no hair/hand/prop blocking the face.
- no multi-view, no contact sheet, no character sheet, no turnaround, no collage, no split panels, no before/after split.
- No text, subtitles, labels, logo, watermark, product, pets, or extra people.
""".strip()


def _is_human_reference_fields(fields: Dict[str, Any]) -> bool:
    asset_type = extract_text(fields.get("参考类型") or fields.get("资产类型")).strip().lower()
    return asset_type in {"human", "person", "人物", "角色"}


def build_reference_image_generation_prompt(fields: Dict[str, Any]) -> str:
    prompt = extract_text(fields.get("参考提示词")).strip()
    if not _is_human_reference_fields(fields):
        return prompt
    if all(phrase in prompt for phrase in ["pure white background", "front-facing upper-body", "full unobstructed face visible"]):
        return prompt
    return f"""
{HUMAN_REFERENCE_IMAGE_RULES}

Character source prompt:
{prompt}
""".strip()


def build_child_records(parent_record_id: str, parent_fields: Dict[str, Any], payload: Dict[str, Any], *, batch_id: str) -> List[Dict[str, Dict[str, Any]]]:
    task_name = extract_text(parent_fields.get("任务名称")).strip() or f"多角色首尾帧-{parent_record_id[-6:]}"
    target_seconds = int(float(extract_text(parent_fields.get("目标时长秒")).strip() or 8))
    inherited_route_fields = {
        name: parent_fields.get(name)
        for name in (
            "使用统一AI路由",
            "参考图AI模型",
            "参考图AI参数JSON",
            "参考图画面尺寸",
            "参考图画面比例",
            "关键帧AI模型",
            "关键帧AI参数JSON",
            "关键帧画面尺寸",
            "关键帧画面比例",
            "视频生成模型",
            "视频AI参数JSON",
            "视频画面尺寸",
            "视频画面比例",
        )
        if parent_fields.get(name)
    }
    inherited_route_fields.setdefault("使用统一AI路由", "是")
    records: List[Dict[str, Dict[str, Any]]] = []
    for asset in payload["assets"]:
        records.append({"fields": {
            "任务名称": f"{task_name}-参考-{asset['asset_name']}",
            "记录类型": ASSET_RECORD_TYPE,
            "记录状态": "有效",
            "父任务记录ID": parent_record_id,
            "批次ID": batch_id,
            "资产ID": asset["asset_id"],
            "参考类型": asset["asset_type"],
            "参考名称": asset["asset_name"],
            "来源角色ID列表": _csv(asset.get("source_role_ids", [])),
            "参考提示词": asset["prompt"],
            "参考图操作": "不触发",
            "参考图版本": 1,
            "参考图生成状态": "待生成",
            "参考图审核状态": "待确认",
            "错误信息": "",
            **inherited_route_fields,
        }})
    for frame in payload["keyframes"]:
        refs = frame["reference_requirements"]
        waits_for_reference_assets = bool(refs["asset_ids"])
        waits_for_previous_keyframe = bool(refs["depends_on_keyframe_type"])
        records.append({"fields": {
            "任务名称": f"{task_name}-{frame['keyframe_type']}",
            "记录类型": KEYFRAME_RECORD_TYPE,
            "记录状态": "有效",
            "父任务记录ID": parent_record_id,
            "批次ID": batch_id,
            "关键帧类型": frame["keyframe_type"],
            "关键帧标题": frame["title"],
            "关键帧提示词": frame["prompt"],
            "需要产品参考图": "是" if refs["use_product_reference"] else "否",
            "参考资产ID列表": _csv(refs["asset_ids"]),
            "画面出场角色ID列表": _csv(frame.get("visible_role_ids", [])),
            "依赖关键帧类型": refs["depends_on_keyframe_type"],
            "参考图选择原因": refs["reason"],
            "关键帧操作": "不触发",
            "关键帧版本": 1,
            "关键帧生成状态": "不触发" if (waits_for_reference_assets or waits_for_previous_keyframe) else "待生成",
            "关键帧审核状态": "待确认",
            "错误信息": "",
            **inherited_route_fields,
        }})
    for clip in payload["videos"]:
        records.append({"fields": {
            "任务名称": f"{task_name}-视频-{clip['clip_type']}",
            "记录类型": VIDEO_RECORD_TYPE,
            "记录状态": "有效",
            "父任务记录ID": parent_record_id,
            "批次ID": batch_id,
            "视频片段类型": clip["clip_type"],
            "首关键帧类型": clip["first_keyframe_type"],
            "尾关键帧类型": clip["last_keyframe_type"],
            "视频提示词": clip["prompt"],
            "目标时长秒": clip["duration_sec"] or target_seconds,
            "视频操作": "不触发",
            "视频版本": 1,
            "视频通道": "OTU",
            "视频生成模型": f"OTU / {DEFAULT_OTU_MODEL}",
            "视频生成状态": "不触发",
            "错误信息": "",
            **inherited_route_fields,
        }})
    return records


def apply_child_default_models(token: str, records: List[Dict[str, Dict[str, Any]]]) -> List[Dict[str, Dict[str, Any]]]:
    for record in records:
        fields = record.get("fields") or {}
        kind = extract_text(fields.get("记录类型")).strip()
        if kind == ASSET_RECORD_TYPE:
            fields = apply_task_default_to_fields(
                token,
                fields,
                app_table=TASK_TABLES["multi_role_first_last"],
                stage="参考图生成默认",
                model_field="参考图AI模型",
                size_field="参考图画面尺寸",
                ratio_field="参考图画面比例",
                params_field="参考图AI参数JSON",
            )
        elif kind == KEYFRAME_RECORD_TYPE:
            fields = apply_task_default_to_fields(
                token,
                fields,
                app_table=TASK_TABLES["multi_role_first_last"],
                stage="关键帧生成默认",
                model_field="关键帧AI模型",
                size_field="关键帧画面尺寸",
                ratio_field="关键帧画面比例",
                params_field="关键帧AI参数JSON",
            )
        elif kind == VIDEO_RECORD_TYPE:
            fields = apply_task_default_to_fields(
                token,
                fields,
                app_table=TASK_TABLES["multi_role_first_last"],
                stage="视频片段生成默认",
                channel_field="视频通道",
                model_field="视频生成模型",
                size_field="视频画面尺寸",
                ratio_field="视频画面比例",
                params_field="视频AI参数JSON",
                placeholder_values=(f"OTU / {DEFAULT_OTU_MODEL}", "默认（配置表）"),
            )
        record["fields"] = fields
    return records


def get_stage_config(stage_name: str, *, default_model: str, default_api_base: str, default_size: str = "") -> Tuple[str, Dict[str, str]]:
    token = get_feishu_token()
    return load_stage_config_fields(
        token,
        stage_name,
        default_model=default_model,
        default_api_base=default_api_base,
        default_size=default_size,
        default_aspect_ratio=DEFAULT_ASPECT_RATIO,
        require_api_key=True,
    )


def _parse_params_json(raw: Any, field_name: str) -> Dict[str, Any]:
    text_value = extract_text(raw).strip()
    if not text_value:
        return {}
    try:
        data = json.loads(text_value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field_name} 不是合法 JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{field_name} 顶层必须是对象")
    return data


def resolve_media_dimensions(
    fields: Dict[str, Any],
    slot_name: str,
    cfg: Dict[str, Any],
    *,
    default_size: str,
    default_aspect_ratio: str = DEFAULT_ASPECT_RATIO,
) -> Dict[str, str]:
    cfg_params = _parse_params_json(cfg.get("params"), "配置AI参数JSON")
    slot_params = _parse_params_json(fields.get(f"{slot_name}AI参数JSON"), f"{slot_name}AI参数JSON")
    return {
        "size": (
            extract_text(fields.get(f"{slot_name}画面尺寸")).strip()
            or extract_text(slot_params.get("size") or slot_params.get("画面尺寸")).strip()
            or extract_text(cfg_params.get("size") or cfg_params.get("画面尺寸")).strip()
            or extract_text(cfg.get("size")).strip()
            or default_size
        ),
        "aspect_ratio": (
            extract_text(fields.get(f"{slot_name}画面比例")).strip()
            or extract_text(slot_params.get("aspect_ratio") or slot_params.get("画面比例")).strip()
            or extract_text(cfg_params.get("aspect_ratio") or cfg_params.get("画面比例")).strip()
            or extract_text(cfg.get("aspect_ratio")).strip()
            or default_aspect_ratio
        ),
    }


def _usable_model_choice(value: Any) -> str:
    raw = extract_text(value).strip()
    normalized = raw.lower().replace("_", "-").replace(" ", "")
    if normalized in {"", "默认", "默认（配置表）", "默认(配置表)", "配置表默认", "待确认", "pending", "default"}:
        return ""
    return raw


def resolve_video_generation_model(fields: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, str]:
    raw = (
        _usable_model_choice(fields.get("视频生成模型"))
        or _usable_model_choice(cfg.get("model"))
        or DEFAULT_OTU_MODEL
    )
    source = "视频生成模型" if _usable_model_choice(fields.get("视频生成模型")) else (
        "配置表" if _usable_model_choice(cfg.get("model")) else "代码默认值"
    )
    bits = ai_routing.parse_model_display(raw)
    provider = bits["provider"] or "OTU"
    model = bits["model"] or raw
    display = raw if bits["provider"] else f"{provider} / {model}"
    if not ai_model_catalog.is_first_last_video_model(display, provider):
        raise ValueError(f"首尾帧视频模型不支持参考图视频模型: {display}")
    return {"model": model, "provider": provider, "display": display, "source": source}


def selected_video_provider_hint(fields: Dict[str, Any]) -> str:
    raw = _usable_model_choice(fields.get("视频生成模型"))
    bits = ai_routing.parse_model_display(raw)
    return bits["provider"] or "OTU"


def video_channel_for_provider(provider: str) -> str:
    if provider in {"OTU", "AIHubMix", "Aitgenne"}:
        return provider
    return provider or "OTU"


def _config_value_for_provider(config_records: List[Dict[str, Any]], provider: str, *field_names: str) -> str:
    for rec in config_records or []:
        fields = rec.get("fields") if isinstance(rec, dict) else {}
        if not isinstance(fields, dict):
            continue
        if not ai_routing.config_record_matches_provider(fields, provider):
            continue
        for field_name in field_names:
            value = extract_text(fields.get(field_name)).strip()
            if value:
                return value
    return ""


def reference_video_route_for_model(
    token: str,
    provider: str,
    display_model: str,
    *,
    task_type: str,
    params: Dict[str, Any],
) -> ai_routing.AiRoute:
    config_records = safe_list_records(token, TABLE_CONFIG) if TABLE_CONFIG else []
    if provider == "Aitgenne":
        config_fields = ai_routing.config_record_for_model(config_records, provider, display_model)
        if config_fields is None:
            raise ValueError(f"未找到模型配置: {display_model}")
        api_key = extract_text(config_fields.get("API Key") or config_fields.get("api_key")).strip()
        if not api_key:
            raise ValueError(f"模型配置缺少 API Key: {display_model}")
        api_base = extract_text(config_fields.get("API 代理地址") or config_fields.get("api_base")).strip() or "https://api.aitgenne.com/v1"
    else:
        api_key = ai_routing.api_key_for_provider(config_records, provider)
        api_base = _config_value_for_provider(config_records, provider, "API 代理地址", "api_base")
    route = ai_routing.AiRoute(
        provider=provider,
        capability="视频",
        task_type=task_type,
        model=display_model,
        call_type="",
        api_base=api_base,
        api_key=api_key,
        params=dict(params or {}),
    )
    return ai_routing.validate_route(route)


def video_task_route_tag(provider: str, model: str) -> str:
    model_name = ai_routing.parse_model_display(model)["model"] or model
    return f"provider={provider} model={model_name}"


def aitgenne_video_resolution(size: Any) -> str:
    text = extract_text(size).strip().upper()
    if text in {"1080P", "1080"} or "1080" in text or "1920" in text:
        return "1080P"
    return "720P"


def is_legacy_aitgenne_video_payload_error(error_text: str) -> bool:
    return any(marker in error_text for marker in ("InvalidParameter", "input.media", "parameters.resolution"))


def existing_video_task_matches_channel(fields: Dict[str, Any], channel: str, display_model: str, task_id: str) -> bool:
    if not task_id:
        return False
    status = extract_text(fields.get("视频生成状态")).strip()
    if status != "生成中":
        return False
    error_text = extract_text(fields.get("视频错误信息")).strip()
    if channel == "Aitgenne" and is_legacy_aitgenne_video_payload_error(error_text):
        return False
    tag = video_task_route_tag(channel, display_model)
    if tag in error_text:
        return True
    if "provider=" in error_text or "model=" in error_text:
        return False
    if channel == "OTU":
        return task_id.startswith("task_")
    if channel == "AIHubMix":
        return is_native_veo_operation_id(task_id)
    return False


def current_video_task_still_matches(token: str, record_id: str, expected_version: int, expected_task_id: str) -> Tuple[bool, Dict[str, Any]]:
    current = safe_get_record(token, TABLE_MULTI_ROLE_FIRST_LAST, record_id)
    current_task_id = extract_text(current.get("视频任务ID")).strip()
    try:
        current_version_value = int(float(extract_text(current.get("视频版本")).strip() or current.get("视频版本") or 1))
    except Exception:
        current_version_value = 1
    return (
        current_version_value == expected_version and (not current_task_id or current_task_id == expected_task_id),
        {"视频任务ID": current_task_id, "视频版本": current_version_value},
    )


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
    config_records = config_records_for_image_slot(fields, slot_name, lambda: safe_list_records(token, TABLE_CONFIG))
    if not ai_routing.unified_route_enabled(fields, config_records):
        return None
    model_bits = ai_routing.parse_model_display(model)
    provider = model_bits["provider"] or ai_routing.parse_model_display(cfg.get("model"))["provider"] or cfg.get("provider") or "OTU"
    route_fields = dict(fields)
    route_fields[ai_routing.slot_model_field(slot_name)] = model
    route = ai_routing.route_from_slot(route_fields, slot_name, {
        **cfg,
        "provider": provider,
        "capability": capability,
        "task_type": task_type,
        "model": model if model_bits["provider"] else f"{provider} / {model}",
        "params": params,
    }, capability=capability, task_type=task_type, config_records=config_records)
    if capability == "视频" and not ai_model_catalog.is_first_last_video_model(route.model, route.provider):
        raise ValueError(f"首尾帧视频模型不支持参考图视频模型: {route.model}")
    return ai_routing.build_media_request_summary(route, prompt, reference_count=reference_count)


def deprecate_existing_children(token: str, parent_record_id: str) -> int:
    deprecated = 0
    for rec in list_multi_role_records_for_parent(token, parent_record_id):
        fields = rec.get("fields", {})
        if record_type(fields) == PARENT_RECORD_TYPE or extract_text(fields.get("记录状态")).strip() == "已废弃":
            continue
        safe_update_record(token, TABLE_MULTI_ROLE_FIRST_LAST, rec["record_id"], filter_existing_fields(token, TABLE_MULTI_ROLE_FIRST_LAST, {
            "记录状态": "已废弃",
            "参考图生成状态": "不触发",
            "关键帧生成状态": "不触发",
            "视频生成状态": "不触发",
            "错误信息": "父任务已重新拆解，此记录已废弃。",
        }))
        deprecated += 1
    return deprecated


def parse_task(record_id: str, *, dry_run: bool = False, raw_model_output: Any = None) -> Dict[str, Any]:
    ensure_multi_role_table()
    token = get_feishu_token()
    fields = safe_get_record(token, TABLE_MULTI_ROLE_FIRST_LAST, record_id)
    script = extract_text(fields.get("输入脚本")).strip()
    if not script:
        raise ValueError("输入脚本为空")
    config_records = safe_list_records(token, TABLE_CONFIG) if (not dry_run or ai_routing.record_wants_unified_route(fields)) else []
    use_unified_route = ai_routing.unified_route_enabled(fields, config_records)
    cfg: Dict[str, str] = {}
    if use_unified_route or not dry_run:
        _, cfg = get_stage_config(PARSE_STAGE_NAME, default_model="gemini-2.5-flash", default_api_base="https://aihubmix.com/gemini")
    prompt = build_parse_prompt(fields, script, system_prompt=(cfg.get("prompt") or DEFAULT_PARSE_PROMPT) if cfg else DEFAULT_PARSE_PROMPT)
    unified_route = None
    if use_unified_route:
        unified_route = ai_routing.route_from_slot(fields, "拆解", {
            **cfg,
            "provider": "AIHubMix",
            "capability": "文本",
            "task_type": "多角色首尾帧解析",
            "model": cfg.get("model") or "AIHubMix / gemini-2.5-flash",
        }, capability="文本", task_type="多角色首尾帧解析", config_records=config_records)
    summary = {"record_id": record_id, "dry_run": dry_run, "prompt_chars": len(prompt)}
    if unified_route:
        summary["unified_ai_route"] = ai_routing.build_dry_run_summary(unified_route, prompt)
    if dry_run:
        summary["status"] = "dry_run_ready"
        return summary
    if unified_route and ai_routing.unified_route_dry_run_only(config_records):
        summary["status"] = "unified_ai_dry_run_ready"
        return summary
    safe_update_record(token, TABLE_MULTI_ROLE_FIRST_LAST, record_id, filter_existing_fields(token, TABLE_MULTI_ROLE_FIRST_LAST, {
        "记录类型": PARENT_RECORD_TYPE,
        "记录状态": "有效",
        "拆解状态": "生成中",
        "错误信息": "",
    }))
    if raw_model_output is None:
        if unified_route:
            result = with_retry(lambda: ai_routing.call_text_model(unified_route, prompt), max_attempts=3, label="unified multi-role first-last parse")
            raw_model_output = result.text
        else:
            client = genai.Client(api_key=cfg["api_key"], http_options={"base_url": cfg.get("api_base") or "https://aihubmix.com/gemini"})
            response = with_retry(
                lambda: client.models.generate_content(model=cfg.get("model") or "gemini-2.5-flash", contents=[prompt]),
                max_attempts=3,
                label="multi-role first-last parse",
            )
            raw_model_output = gemini_text_or_policy_error(response)
    payload = normalize_plan_payload(raw_model_output)
    batch_id = make_batch_id(record_id)
    deprecated = deprecate_existing_children(token, record_id)
    child_records = apply_child_default_models(token, build_child_records(record_id, fields, payload, batch_id=batch_id))
    create_records(token, TABLE_MULTI_ROLE_FIRST_LAST, [
        {"fields": filter_existing_fields(token, TABLE_MULTI_ROLE_FIRST_LAST, item["fields"])}
        for item in child_records
    ])
    safe_update_record(token, TABLE_MULTI_ROLE_FIRST_LAST, record_id, filter_existing_fields(token, TABLE_MULTI_ROLE_FIRST_LAST, {
        "记录类型": PARENT_RECORD_TYPE,
        "记录状态": "有效",
        "批次ID": batch_id,
        "拆解状态": "成功",
        "拆解结果JSON": compact_json(payload, 20000),
        "角色机制JSON": compact_json(payload.get("conflict_mechanism", {}), 8000),
        "总角色数": len(payload["roles"]),
        "总关键帧数": len(payload["keyframes"]),
        "总视频片段数": len(payload["videos"]),
        "错误信息": "",
    }))
    summary.update({"status": "success", "batch_id": batch_id, "created_records": len(child_records), "deprecated_records": deprecated})
    return summary


def _downloaded_path(downloaded: Any, fallback: Path) -> str:
    if isinstance(downloaded, (str, os.PathLike)):
        return str(downloaded)
    return str(fallback)


def _require_reference_url(url_getter: Callable[[str, str], str], token: str, file_token: str, role: str) -> str:
    url = extract_text(url_getter(token, file_token)).strip()
    if not url:
        raise ValueError(f"参考图 URL 缺失: {role} file_token={file_token}")
    return url


def collect_keyframe_references(
    token: str,
    keyframe_fields: Dict[str, Any],
    parent_fields: Dict[str, Any],
    all_records: List[Dict[str, Any]],
    task_dir: Path,
    *,
    product_getter: Callable[[str, Any], Tuple[Optional[str], Optional[Dict[str, Any]]]] = get_product_record,
    download_fn: Callable[[str, str, Path], Any] = download_feishu_media,
    url_getter: Callable[[str, str], str] = get_tmp_download_url_for_attachment,
) -> List[Dict[str, str]]:
    task_dir.mkdir(parents=True, exist_ok=True)
    refs: List[Dict[str, str]] = []
    parent_id = extract_text(keyframe_fields.get("父任务记录ID")).strip()
    dep_type = extract_text(keyframe_fields.get("依赖关键帧类型")).strip()
    if dep_type:
        dep = None
        for rec in all_records:
            fields = rec.get("fields", {})
            if (
                extract_text(fields.get("父任务记录ID")).strip() == parent_id
                and record_type(fields) == KEYFRAME_RECORD_TYPE
                and extract_text(fields.get("关键帧类型")).strip() == dep_type
                and extract_text(fields.get("记录状态")).strip() != "已废弃"
            ):
                dep = {"record_id": rec.get("record_id", ""), "fields": fields}
                break
        if not dep:
            raise ValueError(f"依赖关键帧不存在: {dep_type}")
        dep_fields = dep["fields"]
        if not review_passed(dep_fields.get("关键帧审核状态")):
            raise ValueError(f"依赖关键帧尚未审核通过: {dep_type}")
        file_token = latest_media_token(dep_fields, "关键帧图", "关键帧图file_token")
        if not file_token:
            raise ValueError(f"依赖关键帧缺少图片: {dep_type}")
        local_path = task_dir / f"base_{dep_type}.png"
        downloaded = download_fn(token, file_token, local_path)
        refs.append({
            "role": f"base_keyframe:{dep_type}",
            "file_token": file_token,
            "path": _downloaded_path(downloaded, local_path),
            "url": _require_reference_url(url_getter, token, file_token, f"base_keyframe:{dep_type}"),
            "primary": True,
        })

    if _yes(keyframe_fields.get("需要产品参考图")):
        product_value = parent_fields.get("关联产品记录") or keyframe_fields.get("关联产品记录")
        _, product_fields = product_getter(token, product_value)
        product_tokens = _attachment_tokens((product_fields or {}).get("产品图片"))
        if not product_tokens:
            raise ValueError("该关键帧需要产品参考图，但产品表缺少 产品图片")
        for idx, file_token in enumerate(product_tokens, start=1):
            local_path = task_dir / f"reference_product_{idx}.png"
            downloaded = download_fn(token, file_token, local_path)
            refs.append({
                "role": f"product:{idx}",
                "file_token": file_token,
                "path": _downloaded_path(downloaded, local_path),
                "url": _require_reference_url(url_getter, token, file_token, f"product:{idx}"),
                "primary": False,
            })

    requested_assets = _split_csv(keyframe_fields.get("参考资产ID列表"))
    if not requested_assets:
        return refs
    assets_by_id: Dict[str, Dict[str, Any]] = {}
    for rec in all_records:
        fields = rec.get("fields", {})
        if extract_text(fields.get("父任务记录ID")).strip() != parent_id:
            continue
        if record_type(fields) != ASSET_RECORD_TYPE:
            continue
        asset_id = extract_text(fields.get("资产ID")).strip()
        if asset_id and extract_text(fields.get("记录状态")).strip() != "已废弃":
            assets_by_id[asset_id] = fields
    for asset_id in requested_assets:
        asset = assets_by_id.get(asset_id)
        if not asset:
            raise ValueError(f"关键帧需要参考资产 {asset_id}，但未找到对应参考图记录")
        if not review_passed(asset.get("参考图审核状态")):
            raise ValueError(f"关键帧需要参考资产 {asset_id}，但参考图未审核通过")
        file_token = latest_media_token(asset, "参考图", "参考图file_token")
        if not file_token:
            raise ValueError(f"关键帧需要参考资产 {asset_id}，但参考图附件缺失")
        asset_type = extract_text(asset.get("参考类型")).strip() or "asset"
        local_path = task_dir / f"reference_{asset_id}.png"
        downloaded = download_fn(token, file_token, local_path)
        refs.append({
            "role": f"{asset_type}:{asset_id}",
            "file_token": file_token,
            "path": _downloaded_path(downloaded, local_path),
            "url": _require_reference_url(url_getter, token, file_token, f"{asset_type}:{asset_id}"),
            "primary": False,
        })
    return refs


def _reference_manifest(refs: List[Dict[str, str]]) -> List[Dict[str, str]]:
    return [
        {"role": ref["role"], "file_token": ref["file_token"], "path": ref["path"], "url": ref["url"], "primary": bool(ref.get("primary"))}
        for ref in refs
    ]


def _primary_base_reference(refs: List[Dict[str, str]]) -> Dict[str, str]:
    for ref in refs:
        if ref.get("primary"):
            return ref
    return {}


AITGENNE_DEPENDENT_KEYFRAME_CONTINUITY_PROMPT = (
    "Continuity constraint: Treat the previous keyframe image as the only source of truth for people identities, "
    "clothing, poses, camera framing, room layout, pet appearance, and scene continuity. Use product reference images "
    "only to correct bottle shape, spray nozzle, label layout, colors, logo placement, and packaging proportions. "
    "Do not use product references or any other reference to change the people, clothing, pet, room, camera angle, or composition inherited from the previous keyframe."
)


def _is_product_reference(ref: Dict[str, str]) -> bool:
    return extract_text(ref.get("role")).strip().startswith("product:")


def _submitted_keyframe_references(route: ai_routing.AiRoute, refs: List[Dict[str, str]], primary: Dict[str, str]) -> List[Dict[str, str]]:
    if primary and route.provider == "Aitgenne":
        return [ref for ref in refs if ref.get("primary") or _is_product_reference(ref)]
    return refs


def _keyframe_generation_prompt(prompt: str, route: ai_routing.AiRoute, primary: Dict[str, str]) -> str:
    if primary and route.provider == "Aitgenne":
        return f"{prompt}\n\n{AITGENNE_DEPENDENT_KEYFRAME_CONTINUITY_PROMPT}"
    return prompt


def _active_child_records(records: List[Dict[str, Any]], parent_id: str, wanted_type: str) -> List[Dict[str, Any]]:
    result = []
    for rec in records:
        fields = rec.get("fields", {})
        if extract_text(fields.get("父任务记录ID")).strip() != parent_id:
            continue
        if record_type(fields) != wanted_type:
            continue
        if extract_text(fields.get("记录状态")).strip() == "已废弃":
            continue
        result.append(rec)
    return result


def _asset_ready_map(records: List[Dict[str, Any]], parent_id: str) -> Dict[str, bool]:
    ready = {}
    for rec in _active_child_records(records, parent_id, ASSET_RECORD_TYPE):
        fields = rec.get("fields", {})
        asset_id = extract_text(fields.get("资产ID")).strip()
        if asset_id:
            ready[asset_id] = (
                review_passed(fields.get("参考图审核状态"))
                and bool(latest_media_token(fields, "参考图", "参考图file_token"))
            )
    return ready


def _keyframe_ready_map(records: List[Dict[str, Any]], parent_id: str) -> Dict[str, bool]:
    ready = {}
    for rec in _active_child_records(records, parent_id, KEYFRAME_RECORD_TYPE):
        fields = rec.get("fields", {})
        frame_type = extract_text(fields.get("关键帧类型")).strip()
        if frame_type:
            ready[frame_type] = (
                review_passed(fields.get("关键帧审核状态"))
                and bool(latest_media_token(fields, "关键帧图", "关键帧图file_token"))
            )
    return ready


def keyframe_dependencies_ready(records: List[Dict[str, Any]], parent_id: str, keyframe_fields: Dict[str, Any]) -> bool:
    asset_ready = _asset_ready_map(records, parent_id)
    for asset_id in _split_csv(keyframe_fields.get("参考资产ID列表")):
        if not asset_ready.get(asset_id):
            return False
    dep_type = extract_text(keyframe_fields.get("依赖关键帧类型")).strip()
    if dep_type and not _keyframe_ready_map(records, parent_id).get(dep_type):
        return False
    return True


def keyframe_dependency_wait_reason(records: List[Dict[str, Any]], parent_id: str, keyframe_fields: Dict[str, Any]) -> str:
    dep_type = extract_text(keyframe_fields.get("依赖关键帧类型")).strip()
    if not dep_type:
        return ""
    for rec in _active_child_records(records, parent_id, KEYFRAME_RECORD_TYPE):
        fields = rec.get("fields", {})
        if extract_text(fields.get("关键帧类型")).strip() != dep_type:
            continue
        if review_passed(fields.get("关键帧审核状态")) and latest_media_token(fields, "关键帧图", "关键帧图file_token"):
            return ""
        return f"等待依赖关键帧通过后自动触发: {dep_type}"
    return f"等待依赖关键帧通过后自动触发: {dep_type}"


def video_dependencies_ready(records: List[Dict[str, Any]], parent_id: str, video_fields: Dict[str, Any]) -> bool:
    keyframe_ready = _keyframe_ready_map(records, parent_id)
    return (
        bool(keyframe_ready.get(extract_text(video_fields.get("首关键帧类型")).strip()))
        and bool(keyframe_ready.get(extract_text(video_fields.get("尾关键帧类型")).strip()))
    )


def video_dependency_wait_reason(records: List[Dict[str, Any]], parent_id: str, video_fields: Dict[str, Any]) -> str:
    keyframe_ready = _keyframe_ready_map(records, parent_id)
    for field_name in ("首关键帧类型", "尾关键帧类型"):
        keyframe_type = extract_text(video_fields.get(field_name)).strip()
        if keyframe_type and not keyframe_ready.get(keyframe_type):
            return f"等待视频依赖关键帧通过后自动触发: {keyframe_type}"
    return ""


def trigger_ready_videos_for_parent(token: str, parent_id: str, records: List[Dict[str, Any]]) -> int:
    triggered = 0
    for rec in _active_child_records(records, parent_id, VIDEO_RECORD_TYPE):
        video_fields = rec.get("fields", {})
        status = extract_text(video_fields.get("视频生成状态")).strip()
        if status not in {"不触发", "失败", ""}:
            continue
        if not video_dependencies_ready(records, parent_id, video_fields):
            continue
        safe_update_record(token, TABLE_MULTI_ROLE_FIRST_LAST, rec["record_id"], filter_existing_fields(token, TABLE_MULTI_ROLE_FIRST_LAST, {
            "视频生成状态": "待生成",
            "视频错误信息": "",
            "错误信息": "",
        }))
        triggered += 1
    return triggered


def advance_ready_videos(record_id: str) -> Dict[str, Any]:
    ensure_multi_role_table()
    token = get_feishu_token()
    fields = safe_get_record(token, TABLE_MULTI_ROLE_FIRST_LAST, record_id)
    ensure_active_record(fields)
    parent_id = extract_text(fields.get("父任务记录ID")).strip() or record_id
    records = list_multi_role_records_for_parent(token, parent_id)
    triggered_videos = trigger_ready_videos_for_parent(token, parent_id, records)
    return {
        "record_id": record_id,
        "parent_record_id": parent_id,
        "status": "advanced",
        "triggered_videos": triggered_videos,
    }


def advance_reference_review(record_id: str) -> Dict[str, Any]:
    ensure_multi_role_table()
    token = get_feishu_token()
    fields = safe_get_record(token, TABLE_MULTI_ROLE_FIRST_LAST, record_id)
    ensure_active_record(fields)
    if record_type(fields) != ASSET_RECORD_TYPE:
        raise ValueError("只有参考资产记录可以推进下游关键帧")
    parent_id = extract_text(fields.get("父任务记录ID")).strip()
    records = list_multi_role_records_for_parent(token, parent_id)
    triggered = 0
    for rec in _active_child_records(records, parent_id, KEYFRAME_RECORD_TYPE):
        keyframe_fields = rec.get("fields", {})
        if review_passed(keyframe_fields.get("关键帧审核状态")):
            continue
        status = extract_text(keyframe_fields.get("关键帧生成状态")).strip()
        if status not in {"不触发", "失败", ""}:
            continue
        if not keyframe_dependencies_ready(records, parent_id, keyframe_fields):
            continue
        safe_update_record(token, TABLE_MULTI_ROLE_FIRST_LAST, rec["record_id"], filter_existing_fields(token, TABLE_MULTI_ROLE_FIRST_LAST, {
            "关键帧生成状态": "待生成",
            "关键帧错误信息": "",
            "错误信息": "",
        }))
        triggered += 1
    safe_update_record(token, TABLE_MULTI_ROLE_FIRST_LAST, record_id, filter_existing_fields(token, TABLE_MULTI_ROLE_FIRST_LAST, {
        "参考图审核状态": "已触发下游",
    }))
    return {"record_id": record_id, "status": "advanced", "triggered_keyframes": triggered}


def maybe_auto_advance_reference_review(token: str, record_id: str, fields: Dict[str, Any], *, file_token: str) -> Dict[str, Any]:
    if not auto_review_enabled(token, stage_name=AUTO_REVIEW_STAGE_NAME):
        return {"status": "disabled"}
    if not file_token:
        return {"status": "skipped", "reason": "missing_file_token"}
    if current_version(fields, "参考图版本") != 1:
        return {"status": "manual_regeneration"}
    safe_update_record(token, TABLE_MULTI_ROLE_FIRST_LAST, record_id, filter_existing_fields(token, TABLE_MULTI_ROLE_FIRST_LAST, {
        "参考图审核状态": "通过",
        "错误信息": "",
    }))
    advance_summary = advance_reference_review(record_id)
    return {"status": "auto_approved", "advance": advance_summary}


def advance_keyframe_review(record_id: str) -> Dict[str, Any]:
    ensure_multi_role_table()
    token = get_feishu_token()
    fields = safe_get_record(token, TABLE_MULTI_ROLE_FIRST_LAST, record_id)
    ensure_active_record(fields)
    if record_type(fields) != KEYFRAME_RECORD_TYPE:
        raise ValueError("只有关键帧记录可以推进下游关键帧/视频")
    parent_id = extract_text(fields.get("父任务记录ID")).strip()
    records = list_multi_role_records_for_parent(token, parent_id)
    triggered_keyframes = 0
    for rec in _active_child_records(records, parent_id, KEYFRAME_RECORD_TYPE):
        keyframe_fields = rec.get("fields", {})
        if review_passed(keyframe_fields.get("关键帧审核状态")):
            continue
        status = extract_text(keyframe_fields.get("关键帧生成状态")).strip()
        if status not in {"不触发", "失败", ""}:
            continue
        if not keyframe_dependencies_ready(records, parent_id, keyframe_fields):
            continue
        safe_update_record(token, TABLE_MULTI_ROLE_FIRST_LAST, rec["record_id"], filter_existing_fields(token, TABLE_MULTI_ROLE_FIRST_LAST, {
            "关键帧生成状态": "待生成",
            "关键帧错误信息": "",
            "错误信息": "",
        }))
        triggered_keyframes += 1
    triggered_videos = trigger_ready_videos_for_parent(token, parent_id, records)
    safe_update_record(token, TABLE_MULTI_ROLE_FIRST_LAST, record_id, filter_existing_fields(token, TABLE_MULTI_ROLE_FIRST_LAST, {
        "关键帧审核状态": "已触发下游",
    }))
    return {
        "record_id": record_id,
        "status": "advanced",
        "triggered_keyframes": triggered_keyframes,
        "triggered_videos": triggered_videos,
    }


def maybe_auto_advance_keyframe_review(token: str, record_id: str, fields: Dict[str, Any], *, file_token: str) -> Dict[str, Any]:
    if not auto_review_enabled(token, stage_name=AUTO_REVIEW_STAGE_NAME):
        return {"status": "disabled"}
    if not file_token:
        return {"status": "skipped", "reason": "missing_file_token"}
    version = current_version(fields, "关键帧版本")
    reapprove = version != 1 and keyframe_regeneration_reapprove_allowed(fields)
    if version != 1 and not reapprove:
        return {"status": "manual_regeneration"}
    safe_update_record(token, TABLE_MULTI_ROLE_FIRST_LAST, record_id, filter_existing_fields(token, TABLE_MULTI_ROLE_FIRST_LAST, {
        "关键帧审核状态": "通过",
        "错误信息": "",
    }))
    advance_summary = advance_keyframe_review(record_id)
    return {"status": "auto_reapproved" if reapprove else "auto_approved", "advance": advance_summary}


def render_reference_image(record_id: str, *, dry_run: bool = False) -> Dict[str, Any]:
    ensure_multi_role_table()
    token = get_feishu_token()
    fields = safe_get_record(token, TABLE_MULTI_ROLE_FIRST_LAST, record_id)
    fields = apply_task_default_to_record(
        token,
        TABLE_MULTI_ROLE_FIRST_LAST,
        record_id,
        fields,
        app_table=TASK_TABLES["multi_role_first_last"],
        stage="参考图生成默认",
        model_field="参考图AI模型",
        size_field="参考图画面尺寸",
        ratio_field="参考图画面比例",
        params_field="参考图AI参数JSON",
        field_filter=filter_existing_fields,
    )
    ensure_active_record(fields)
    if record_type(fields) != ASSET_RECORD_TYPE:
        raise ValueError("只有参考资产记录可以生成参考图")
    asset_type = extract_text(fields.get("参考类型") or fields.get("资产类型")).strip().lower()
    if asset_type and asset_type not in {"human", "pet", "environment"}:
        raise ValueError(f"参考类型不支持自动生成参考图: {asset_type}")
    raw_prompt = extract_text(fields.get("参考提示词")).strip()
    if not raw_prompt:
        raise ValueError("参考提示词为空")
    prompt = build_reference_image_generation_prompt(fields)
    version = current_version(fields, "参考图版本")
    work_dir = ensure_stage_work_dir(record_id, "reference_image", version)
    _, cfg = get_stage_config(IMAGE_STAGE_NAME, default_model=DEFAULT_OTU_IMAGE_MODEL, default_api_base=DEFAULT_OTU_API_BASE, default_size=DEFAULT_OTU_IMAGE_SIZE)
    output_path = str(work_dir / f"{record_id}_reference_v{version}.png")
    model_name = cfg.get("model") or DEFAULT_OTU_IMAGE_MODEL
    image_params = resolve_media_dimensions(fields, "参考图", cfg, default_size=DEFAULT_OTU_IMAGE_SIZE)
    size = image_params["size"]
    aspect_ratio = image_params["aspect_ratio"]
    config_records = config_records_for_image_slot(fields, "参考图", lambda: safe_list_records(token, TABLE_CONFIG))
    route = resolve_image_route_from_slot(
        fields,
        "参考图",
        cfg,
        task_type="文生图",
        params=image_params,
        config_records=config_records,
    )
    image_params = image_params_with_model_overrides(route, image_params)
    route.params.update(image_params)
    size = image_params["size"]
    aspect_ratio = image_params["aspect_ratio"]
    summary = {"record_id": record_id, "dry_run": dry_run, "prompt_chars": len(prompt), "model": model_name, "size": size, "aspect_ratio": aspect_ratio, "output_path": output_path}
    route_summary = maybe_unified_media_summary(
        token,
        fields,
        cfg,
        capability="图片",
        task_type="文生图",
        model=model_name,
        slot_name="参考图",
        prompt=prompt,
        params=image_params,
        reference_count=0,
    )
    if route_summary:
        summary["unified_ai_route"] = route_summary
    if dry_run:
        summary["status"] = "dry_run_ready"
        return summary
    if route_summary and ai_routing.unified_route_dry_run_only(config_records):
        summary["status"] = "unified_ai_dry_run_ready"
        return summary
    start_fields = {
        **image_slot_field_patch("参考图", image_params),
        "参考图生成状态": "生成中",
        "参考图版本": version,
        "参考图错误信息": "",
        "错误信息": "",
    }
    safe_update_record(token, TABLE_MULTI_ROLE_FIRST_LAST, record_id, filter_existing_fields(token, TABLE_MULTI_ROLE_FIRST_LAST, start_fields))
    existing_task_id = extract_text(fields.get("参考图任务ID")).strip()
    image_result = run_image_generation(
        route,
        prompt,
        output_path,
        input_mode="text-to-image",
        metadata={"urls": [], "reference_roles": []},
        size=size,
        aspect_ratio=aspect_ratio,
        existing_task_id=existing_task_id,
        otu_submitter=submit_otu_image_task,
        otu_poller=poll_otu_image_task,
        otu_downloader=download_otu_image_result,
        on_task_submitted=lambda task_id: safe_update_record(
            token,
            TABLE_MULTI_ROLE_FIRST_LAST,
            record_id,
            filter_existing_fields(token, TABLE_MULTI_ROLE_FIRST_LAST, {
                "参考图任务ID": task_id,
                "参考图版本": version,
                "参考图错误信息": f"已提交 {route.provider} 参考图任务，正在轮询。task_id={task_id}",
            }),
        ),
    )
    task_id = image_result.task_id
    submit_body = image_result.submit_body
    result = image_result.result_body
    if not existing_task_id:
        safe_update_record(token, TABLE_MULTI_ROLE_FIRST_LAST, record_id, filter_existing_fields(token, TABLE_MULTI_ROLE_FIRST_LAST, {
            "参考图任务ID": task_id,
            "参考图原始响应JSON": compact_json({"submit": submit_body, "request_summary": image_result.request_summary}, 10000),
        }))
    file_token = upload_image_to_feishu(token, output_path, f"{record_id}_reference.png")
    safe_update_record(token, TABLE_MULTI_ROLE_FIRST_LAST, record_id, filter_existing_fields(token, TABLE_MULTI_ROLE_FIRST_LAST, {
        **image_slot_field_patch("参考图", image_params),
        "参考图": [{"file_token": file_token, "name": Path(output_path).name}],
        "参考图file_token": file_token,
        "参考图本地路径": output_path,
        "参考图任务ID": task_id,
        "参考图版本": version,
        "参考图生成状态": "成功",
        "参考图审核状态": "待确认",
        "参考图原始响应JSON": compact_json({"submit": submit_body, "result": result, "request_summary": image_result.request_summary}, 10000),
        "参考图错误信息": "",
        "参考图生成时间": int(time.time() * 1000),
        "错误信息": "",
    }))
    auto_review_summary = maybe_auto_advance_reference_review(token, record_id, fields, file_token=file_token)
    summary.update({"status": "success", "task_id": task_id, "file_token": file_token})
    summary["auto_review"] = auto_review_summary
    return summary


def _parent_fields(token: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    parent_id = extract_text(fields.get("父任务记录ID")).strip()
    if not parent_id:
        return {}
    return safe_get_record(token, TABLE_MULTI_ROLE_FIRST_LAST, parent_id)


def render_keyframe_image(record_id: str, *, dry_run: bool = False) -> Dict[str, Any]:
    ensure_multi_role_table()
    token = get_feishu_token()
    fields = safe_get_record(token, TABLE_MULTI_ROLE_FIRST_LAST, record_id)
    fields = apply_task_default_to_record(
        token,
        TABLE_MULTI_ROLE_FIRST_LAST,
        record_id,
        fields,
        app_table=TASK_TABLES["multi_role_first_last"],
        stage="关键帧生成默认",
        model_field="关键帧AI模型",
        size_field="关键帧画面尺寸",
        ratio_field="关键帧画面比例",
        params_field="关键帧AI参数JSON",
        field_filter=filter_existing_fields,
    )
    ensure_active_record(fields)
    if record_type(fields) != KEYFRAME_RECORD_TYPE:
        raise ValueError("只有关键帧记录可以生成关键帧图")
    prompt = extract_text(fields.get("关键帧提示词")).strip()
    if not prompt:
        raise ValueError("关键帧提示词为空")
    version = current_version(fields, "关键帧版本")
    work_dir = ensure_stage_work_dir(record_id, "keyframe_image", version)
    parent_fields = _parent_fields(token, fields)
    parent_id = extract_text(fields.get("父任务记录ID")).strip()
    all_records = list_multi_role_records_for_parent(token, parent_id)
    wait_reason = keyframe_dependency_wait_reason(all_records, parent_id, fields)
    if wait_reason:
        safe_update_record(token, TABLE_MULTI_ROLE_FIRST_LAST, record_id, filter_existing_fields(token, TABLE_MULTI_ROLE_FIRST_LAST, {
            "关键帧生成状态": "不触发",
            "关键帧错误信息": wait_reason,
            "错误信息": wait_reason,
        }))
        return {"record_id": record_id, "status": "waiting_dependency", "reason": wait_reason}
    refs = collect_keyframe_references(token, fields, parent_fields, all_records, work_dir)
    primary = _primary_base_reference(refs)
    _, cfg = get_stage_config(IMAGE_STAGE_NAME, default_model=DEFAULT_OTU_IMAGE_MODEL, default_api_base=DEFAULT_OTU_API_BASE, default_size=DEFAULT_OTU_IMAGE_SIZE)
    output_path = str(work_dir / f"{record_id}_keyframe_v{version}.png")
    model_name = cfg.get("model") or DEFAULT_OTU_IMAGE_MODEL
    image_params = resolve_media_dimensions(fields, "关键帧", cfg, default_size=DEFAULT_OTU_IMAGE_SIZE)
    size = image_params["size"]
    aspect_ratio = image_params["aspect_ratio"]
    config_records = config_records_for_image_slot(fields, "关键帧", lambda: safe_list_records(token, TABLE_CONFIG))
    route = resolve_image_route_from_slot(
        fields,
        "关键帧",
        cfg,
        task_type="图生图/参考图重绘",
        params=image_params,
        config_records=config_records,
    )
    image_params = image_params_with_model_overrides(route, image_params)
    route.params.update(image_params)
    size = image_params["size"]
    aspect_ratio = image_params["aspect_ratio"]
    submitted_refs = _submitted_keyframe_references(route, refs, primary)
    manifest = _reference_manifest(submitted_refs)
    generation_prompt = _keyframe_generation_prompt(prompt, route, primary)
    summary = {
        "record_id": record_id,
        "dry_run": dry_run,
        "prompt_chars": len(generation_prompt),
        "model": model_name,
        "size": size,
        "aspect_ratio": aspect_ratio,
        "reference_count": len(submitted_refs),
        "collected_reference_count": len(refs),
        "output_path": output_path,
    }
    route_summary = maybe_unified_media_summary(
        token,
        fields,
        cfg,
        capability="图片",
        task_type="图生图/参考图重绘",
        model=model_name,
        slot_name="关键帧",
        prompt=generation_prompt,
        params=image_params,
        reference_count=len(submitted_refs),
    )
    if route_summary:
        summary["unified_ai_route"] = route_summary
    if dry_run:
        summary["status"] = "dry_run_ready"
        return summary
    if route_summary and ai_routing.unified_route_dry_run_only(config_records):
        summary["status"] = "unified_ai_dry_run_ready"
        return summary
    safe_update_record(token, TABLE_MULTI_ROLE_FIRST_LAST, record_id, filter_existing_fields(token, TABLE_MULTI_ROLE_FIRST_LAST, {
        **image_slot_field_patch("关键帧", image_params),
        "关键帧生成状态": "生成中",
        "关键帧版本": version,
        "依赖关键帧file_token": primary.get("file_token", ""),
        "参考图清单JSON": compact_json(manifest, 12000),
        "关键帧错误信息": "",
        "错误信息": "",
    }))
    metadata = {
        "urls": [ref["url"] for ref in submitted_refs],
        "reference_roles": [ref["role"] for ref in submitted_refs],
        "reference_manifest": manifest,
    }
    reference_image_paths = [ref["path"] for ref in submitted_refs if ref.get("path") and not ref.get("primary")]
    input_mode = "image-to-image" if primary.get("path") or reference_image_paths else "text-to-image"
    existing_task_id = extract_text(fields.get("关键帧任务ID")).strip()
    image_result = run_image_generation(
        route,
        generation_prompt,
        output_path,
        input_mode=input_mode,
        image_path=primary.get("path", ""),
        image_url=primary.get("url", ""),
        reference_image_paths=reference_image_paths,
        metadata=metadata,
        size=size,
        aspect_ratio=aspect_ratio,
        existing_task_id=existing_task_id,
        otu_submitter=submit_otu_image_task,
        otu_poller=poll_otu_image_task,
        otu_downloader=download_otu_image_result,
        on_task_submitted=lambda task_id: safe_update_record(
            token,
            TABLE_MULTI_ROLE_FIRST_LAST,
            record_id,
            filter_existing_fields(token, TABLE_MULTI_ROLE_FIRST_LAST, {
                "关键帧任务ID": task_id,
                "关键帧版本": version,
                "关键帧错误信息": f"已提交 {route.provider} 关键帧图任务，正在轮询。task_id={task_id}",
            }),
        ),
    )
    task_id = image_result.task_id
    submit_body = image_result.submit_body
    result = image_result.result_body
    if not existing_task_id:
        request_log = {
            "request_summary": image_result.request_summary,
            "submitted_reference_roles": [ref["role"] for ref in submitted_refs],
            "reference_manifest": manifest,
            "metadata": metadata,
            "submit": submit_body,
        }
        safe_update_record(token, TABLE_MULTI_ROLE_FIRST_LAST, record_id, filter_existing_fields(token, TABLE_MULTI_ROLE_FIRST_LAST, {
            "关键帧任务ID": task_id,
            "原始请求JSON": compact_json(request_log, 12000),
            "关键帧原始响应JSON": compact_json({"request_summary": image_result.request_summary, "submit": submit_body}, 10000),
        }))
    file_token = upload_image_to_feishu(token, output_path, f"{record_id}_keyframe.png")
    safe_update_record(token, TABLE_MULTI_ROLE_FIRST_LAST, record_id, filter_existing_fields(token, TABLE_MULTI_ROLE_FIRST_LAST, {
        **image_slot_field_patch("关键帧", image_params),
        "关键帧图": [{"file_token": file_token, "name": Path(output_path).name}],
        "关键帧图file_token": file_token,
        "关键帧图本地路径": output_path,
        "关键帧任务ID": task_id,
        "关键帧版本": version,
        "关键帧生成状态": "成功",
        "关键帧审核状态": "待确认",
        "关键帧原始响应JSON": compact_json({"request_summary": image_result.request_summary, "submit": submit_body, "result": result}, 10000),
        "关键帧错误信息": "",
        "关键帧生成时间": int(time.time() * 1000),
        "错误信息": "",
    }))
    auto_review_summary = maybe_auto_advance_keyframe_review(token, record_id, fields, file_token=file_token)
    summary.update({"status": "success", "task_id": task_id, "file_token": file_token})
    summary["auto_review"] = auto_review_summary
    return summary


def _find_keyframe_for_clip(all_records: List[Dict[str, Any]], parent_id: str, keyframe_type: str) -> Dict[str, Any]:
    for rec in all_records:
        fields = rec.get("fields", {})
        if (
            extract_text(fields.get("父任务记录ID")).strip() == parent_id
            and record_type(fields) == KEYFRAME_RECORD_TYPE
            and extract_text(fields.get("关键帧类型")).strip() == keyframe_type
            and extract_text(fields.get("记录状态")).strip() != "已废弃"
        ):
            if not review_passed(fields.get("关键帧审核状态")):
                raise ValueError(f"视频依赖关键帧尚未审核通过: {keyframe_type}")
            file_token = latest_media_token(fields, "关键帧图", "关键帧图file_token")
            if not file_token:
                raise ValueError(f"视频依赖关键帧缺少图片: {keyframe_type}")
            return {"record_id": rec.get("record_id", ""), "fields": fields, "file_token": file_token}
    raise ValueError(f"视频依赖关键帧不存在: {keyframe_type}")


def submit_otu_video_task(config: Dict[str, str], prompt: str, first_frame_path: str, last_frame_path: str, *, seconds: str, size: str, aspect_ratio: str) -> Tuple[str, Dict[str, Any]]:
    url = videos_url(config.get("api_base") or DEFAULT_OTU_API_BASE)
    headers = {"Authorization": f"Bearer {config['api_key']}"}

    def _submit_once() -> Tuple[str, Dict[str, Any]]:
        with open(first_frame_path, "rb") as first_file, open(last_frame_path, "rb") as last_file:
            files = [
                ("input_reference[]", (os.path.basename(first_frame_path), first_file, "image/png")),
                ("input_reference[]", (os.path.basename(last_frame_path), last_file, "image/png")),
            ]
            data = {
                "model": config.get("model") or DEFAULT_OTU_MODEL,
                "prompt": prompt,
                "seconds": seconds,
                "size": size or DEFAULT_OTU_SIZE,
                "aspect_ratio": aspect_ratio or DEFAULT_ASPECT_RATIO,
            }
            resp = requests.post(url, headers=headers, data=data, files=files, timeout=SUBMIT_TIMEOUT)
        try:
            body = resp.json()
        except Exception:
            body = {"raw_text": resp.text[:1000]}
        if resp.status_code >= 400:
            raise RuntimeError(f"OTU 多角色视频任务提交失败: HTTP {resp.status_code}, body={str(body)[:1200]}")
        task_id = extract_text(body.get("id") or body.get("task_id") or (body.get("data") or {}).get("id") or (body.get("data") or {}).get("task_id")).strip()
        if not task_id:
            raise RuntimeError(f"OTU 多角色视频任务提交未返回任务 ID: {str(body)[:1200]}")
        return task_id, body

    return with_retry(_submit_once, max_attempts=4, label="submit multi-role first-last OTU video")


def submit_reference_video_task(
    route: ai_routing.AiRoute,
    prompt: str,
    first_frame_path: str,
    last_frame_path: str,
    *,
    seconds: str,
    size: str,
    aspect_ratio: str,
    reference_urls: Optional[List[str]] = None,
) -> Tuple[str, Dict[str, Any]]:
    if not route.api_key:
        raise ValueError(f"{route.provider} / {route.model} 缺少 API Key")
    model_name = ai_routing.parse_model_display(route.model)["model"] or route.model
    endpoint = ai_routing.media_endpoint(route)
    if route.provider == "Aitgenne" and ai_routing.is_aitgenne_happyhorse_model(route):
        urls = [extract_text(url).strip() for url in (reference_urls or []) if extract_text(url).strip()]
        if not urls:
            raise ValueError("Aitgenne 多角色视频缺少参考图 URL")
        payload = ai_routing.build_happyhorse_video_payload(
            route,
            prompt,
            urls,
            size=size,
            aspect_ratio=aspect_ratio,
            seconds=seconds,
        )

        def _submit_json_once() -> Tuple[str, Dict[str, Any]]:
            resp = requests.post(
                endpoint,
                headers={"Authorization": f"Bearer {route.api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=SUBMIT_TIMEOUT,
            )
            try:
                body = resp.json()
            except Exception:
                body = {"raw_text": resp.text[:1000]}
            if resp.status_code >= 400:
                raise RuntimeError(f"{route.provider} 多角色视频任务提交失败: HTTP {resp.status_code}, body={str(body)[:1200]}")
            task_id = ai_routing.extract_video_task_id(body)
            if not task_id:
                raise RuntimeError(f"{route.provider} 多角色视频任务提交未返回任务 ID: {str(body)[:1200]}")
            return task_id, body

        return with_retry(_submit_json_once, max_attempts=4, label=f"submit multi-role {route.provider} video {endpoint}")

    if route.provider == "Aitgenne":
        urls = [extract_text(url).strip() for url in (reference_urls or []) if extract_text(url).strip()]
        if len(urls) < 2:
            raise ValueError("Aitgenne 多角色视频缺少参考图 URL")
        payload = ai_routing.build_aitgenne_unified_video_payload(
            route,
            prompt,
            urls[:2],
            aspect_ratio=aspect_ratio or DEFAULT_ASPECT_RATIO,
        )

        def _submit_aitgenne_once() -> Tuple[str, Dict[str, Any]]:
            resp = requests.post(
                endpoint,
                headers={"Authorization": f"Bearer {route.api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=SUBMIT_TIMEOUT,
            )
            try:
                body = resp.json()
            except Exception:
                body = {"raw_text": resp.text[:1000]}
            if resp.status_code >= 400:
                raise RuntimeError(f"{route.provider} 多角色视频任务提交失败: HTTP {resp.status_code}, body={str(body)[:1200]}")
            task_id = ai_routing.extract_video_task_id(body)
            if not task_id:
                raise RuntimeError(f"{route.provider} 多角色视频任务提交未返回任务 ID: {str(body)[:1200]}")
            return task_id, body

        return with_retry(_submit_aitgenne_once, max_attempts=4, label=f"submit multi-role {route.provider} video {endpoint}")

    def _submit_once() -> Tuple[str, Dict[str, Any]]:
        with open(first_frame_path, "rb") as first_file, open(last_frame_path, "rb") as last_file:
            files = [
                ("input_reference[]", (os.path.basename(first_frame_path), first_file, "image/png")),
                ("input_reference[]", (os.path.basename(last_frame_path), last_file, "image/png")),
            ]
            resp = requests.post(
                endpoint,
                headers={"Authorization": f"Bearer {route.api_key}"},
                data={
                    "model": model_name,
                    "prompt": prompt,
                    "seconds": seconds,
                    "size": size or DEFAULT_OTU_SIZE,
                    "aspect_ratio": aspect_ratio or DEFAULT_ASPECT_RATIO,
                },
                files=files,
                timeout=SUBMIT_TIMEOUT,
            )
        try:
            body = resp.json()
        except Exception:
            body = {"raw_text": resp.text[:1000]}
        if resp.status_code >= 400:
            raise RuntimeError(f"{route.provider} 多角色视频任务提交失败: HTTP {resp.status_code}, body={str(body)[:1200]}")
        task_id = extract_text(body.get("id") or body.get("task_id") or (body.get("data") or {}).get("id") or (body.get("data") or {}).get("task_id")).strip()
        if not task_id:
            raise RuntimeError(f"{route.provider} 多角色视频任务提交未返回任务 ID: {str(body)[:1200]}")
        return task_id, body

    return with_retry(_submit_once, max_attempts=4, label=f"submit multi-role {route.provider} video {endpoint}")


def reference_video_item_url(route: ai_routing.AiRoute, task_id: str) -> str:
    return ai_routing.media_task_endpoint(route, task_id)


def poll_reference_video_task(route: ai_routing.AiRoute, task_id: str) -> Dict[str, Any]:
    if not route.api_key:
        raise ValueError(f"{route.provider} / {route.model} 缺少 API Key")
    url = reference_video_item_url(route, task_id)
    headers = {"Authorization": f"Bearer {route.api_key}"}
    start = time.time()
    last_body: Dict[str, Any] = {}
    while time.time() - start < 2400:
        resp = requests.get(url, headers=headers, timeout=45)
        try:
            body = resp.json()
        except Exception:
            body = {"raw_text": resp.text[:1000]}
        last_body = body if isinstance(body, dict) else {"raw": body}
        if resp.status_code >= 400:
            raise RuntimeError(f"{route.provider} 多角色视频任务轮询失败: HTTP {resp.status_code}, body={str(last_body)[:1200]}")
        status = ai_routing.extract_video_status(last_body)
        if status in {"completed", "succeeded", "success", "done"}:
            return last_body
        if status in {"failed", "error", "cancelled", "canceled"}:
            raise RuntimeError(f"{route.provider} 多角色视频生成失败: {str(last_body)[:1200]}")
        time.sleep(8)
    raise TimeoutError(f"{route.provider} 多角色视频任务轮询超时: task_id={task_id}, last={str(last_body)[:1200]}")


def render_video_clip(record_id: str, *, dry_run: bool = False) -> Dict[str, Any]:
    ensure_multi_role_table()
    token = get_feishu_token()
    fields = safe_get_record(token, TABLE_MULTI_ROLE_FIRST_LAST, record_id)
    fields = apply_task_default_to_record(
        token,
        TABLE_MULTI_ROLE_FIRST_LAST,
        record_id,
        fields,
        app_table=TASK_TABLES["multi_role_first_last"],
        stage="视频片段生成默认",
        channel_field="视频通道",
        model_field="视频生成模型",
        size_field="视频画面尺寸",
        ratio_field="视频画面比例",
        params_field="视频AI参数JSON",
        placeholder_values=(f"OTU / {DEFAULT_OTU_MODEL}", DEFAULT_OTU_MODEL, "默认（配置表）"),
        field_filter=filter_existing_fields,
    )
    ensure_active_record(fields)
    if record_type(fields) != VIDEO_RECORD_TYPE:
        raise ValueError("只有视频片段记录可以生成视频")
    prompt = extract_text(fields.get("视频提示词")).strip()
    if not prompt:
        raise ValueError("视频提示词为空")
    parent_id = extract_text(fields.get("父任务记录ID")).strip()
    first_type = extract_text(fields.get("首关键帧类型")).strip()
    last_type = extract_text(fields.get("尾关键帧类型")).strip()
    all_records = list_multi_role_records_for_parent(token, parent_id)
    wait_reason = video_dependency_wait_reason(all_records, parent_id, fields)
    if wait_reason:
        safe_update_record(token, TABLE_MULTI_ROLE_FIRST_LAST, record_id, filter_existing_fields(token, TABLE_MULTI_ROLE_FIRST_LAST, {
            "视频生成状态": "不触发",
            "视频错误信息": wait_reason,
            "错误信息": wait_reason,
        }))
        return {"record_id": record_id, "status": "waiting_dependency", "reason": wait_reason}
    first = _find_keyframe_for_clip(all_records, parent_id, first_type)
    last = _find_keyframe_for_clip(all_records, parent_id, last_type)
    version = current_version(fields, "视频版本")
    work_dir = ensure_stage_work_dir(record_id, "video", version)
    provider_hint = selected_video_provider_hint(fields)
    stage_name = AIHUBMIX_VIDEO_STAGE_NAME if provider_hint == "AIHubMix" else VIDEO_STAGE_NAME
    _, cfg = get_stage_config(
        stage_name,
        default_model=DEFAULT_NATIVE_VIDEO_MODEL if provider_hint == "AIHubMix" else DEFAULT_OTU_MODEL,
        default_api_base=DEFAULT_GEMINI_API_BASE if provider_hint == "AIHubMix" else DEFAULT_OTU_API_BASE,
        default_size=DEFAULT_OTU_SIZE,
    )
    video_model = resolve_video_generation_model(fields, cfg)
    runtime_cfg = {**cfg, "model": video_model["model"]}
    channel = video_channel_for_provider(video_model["provider"])
    seconds = normalize_seconds(fields.get("目标时长秒") or 8)
    video_params = resolve_media_dimensions(fields, "视频", runtime_cfg, default_size=DEFAULT_OTU_SIZE, default_aspect_ratio=DEFAULT_ASPECT_RATIO)
    size = video_params["size"]
    aspect_ratio = video_params["aspect_ratio"]
    reference_route: Optional[ai_routing.AiRoute] = None
    if channel == "Aitgenne":
        reference_route = reference_video_route_for_model(
            token,
            video_model["provider"],
            video_model["display"],
            task_type="首尾帧视频",
            params={"size": size, "seconds": seconds, "aspect_ratio": aspect_ratio},
        )
        runtime_cfg = {**runtime_cfg, "api_key": reference_route.api_key, "api_base": reference_route.api_base}
    native_resolution = normalize_native_veo_resolution(size) if channel == "AIHubMix" else ""
    output_path = str(work_dir / f"{record_id}_video_v{version}.mp4")
    summary = {
        "record_id": record_id,
        "dry_run": dry_run,
        "first_keyframe": first_type,
        "last_keyframe": last_type,
        "model": video_model["model"],
        "model_source": video_model["source"],
        "seconds": seconds,
        "size": size,
        "native_resolution": native_resolution or None,
        "aspect_ratio": aspect_ratio,
        "output_path": output_path,
    }
    route_summary = maybe_unified_media_summary(
        token,
        fields,
        runtime_cfg,
        capability="视频",
        task_type="首尾帧视频",
        model=video_model["display"],
        slot_name="视频",
        prompt=prompt,
        params={"size": size, "seconds": seconds, "aspect_ratio": aspect_ratio},
        reference_count=2,
    )
    if route_summary:
        summary["unified_ai_route"] = route_summary
    if dry_run:
        summary["status"] = "dry_run_ready"
        return summary
    if route_summary and ai_routing.unified_route_dry_run_only(safe_list_records(token, TABLE_CONFIG)):
        summary["status"] = "unified_ai_dry_run_ready"
        return summary
    existing_task_id = extract_text(fields.get("视频任务ID")).strip()
    if existing_task_id and not existing_video_task_matches_channel(fields, channel, video_model["display"], existing_task_id):
        safe_update_record(token, TABLE_MULTI_ROLE_FIRST_LAST, record_id, filter_existing_fields(token, TABLE_MULTI_ROLE_FIRST_LAST, {
            "视频任务ID": "",
            "视频原始响应JSON": "",
            "视频错误信息": f"旧视频任务ID不属于当前视频通道/模型，已忽略并重新提交。current={video_task_route_tag(channel, video_model['display'])}; old_task_id={existing_task_id}",
        }))
        existing_task_id = ""
    field_types = get_table_field_types(token, TABLE_MULTI_ROLE_FIRST_LAST)
    native_client: Any = None
    if existing_task_id:
        task_id = existing_task_id
        safe_update_record(token, TABLE_MULTI_ROLE_FIRST_LAST, record_id, filter_existing_fields(token, TABLE_MULTI_ROLE_FIRST_LAST, {
            "视频通道": channel,
            "视频生成模型": video_model["display"],
            "视频生成状态": "生成中",
            "视频任务ID": task_id,
            "视频版本": version,
            "视频错误信息": f"恢复轮询已有 {channel} 视频任务。task_id={task_id}",
        }))
    else:
        first_path = download_feishu_media(token, first["file_token"], work_dir / f"{record_id}_{first_type}.png")
        last_path = download_feishu_media(token, last["file_token"], work_dir / f"{record_id}_{last_type}.png")
        reference_urls = []
        if channel == "Aitgenne":
            reference_urls = [
                get_tmp_download_url_for_attachment(token, first["file_token"]),
                get_tmp_download_url_for_attachment(token, last["file_token"]),
            ]
        safe_update_record(token, TABLE_MULTI_ROLE_FIRST_LAST, record_id, filter_existing_fields(token, TABLE_MULTI_ROLE_FIRST_LAST, {
            "首关键帧file_token": first["file_token"],
            "尾关键帧file_token": last["file_token"],
            "视频通道": channel,
            "视频生成模型": video_model["display"],
            "视频生成状态": "生成中",
            "视频版本": version,
            "视频错误信息": (
                f"准备提交 AIHubMix Gemini/Veo 视频任务... 视频画面尺寸={size}, native_resolution={native_resolution}"
                if channel == "AIHubMix"
                else f"准备提交 Aitgenne 视频任务... {video_task_route_tag(channel, video_model['display'])}"
                if channel == "Aitgenne"
                else ""
            ),
            "错误信息": "",
        }))
        if channel == "OTU":
            task_id, submit_body = submit_otu_video_task(runtime_cfg, prompt, str(first_path), str(last_path), seconds=seconds, size=size, aspect_ratio=aspect_ratio)
            safe_update_record(token, TABLE_MULTI_ROLE_FIRST_LAST, record_id, filter_existing_fields(token, TABLE_MULTI_ROLE_FIRST_LAST, {
                "视频任务ID": task_id,
                "视频原始响应JSON": compact_json({"submit": submit_body, "first_keyframe": first_type, "last_keyframe": last_type}, 10000),
                "视频错误信息": f"已提交 OTU 视频任务，正在轮询。task_id={task_id}",
            }))
        elif channel == "Aitgenne":
            if reference_route is None:
                raise RuntimeError("Aitgenne 视频路由未初始化")
            task_id, submit_body = submit_reference_video_task(
                reference_route,
                prompt,
                str(first_path),
                str(last_path),
                seconds=seconds,
                size=size,
                aspect_ratio=aspect_ratio,
                reference_urls=reference_urls,
            )
            safe_update_record(token, TABLE_MULTI_ROLE_FIRST_LAST, record_id, filter_existing_fields(token, TABLE_MULTI_ROLE_FIRST_LAST, {
                "视频任务ID": task_id,
                "视频原始响应JSON": compact_json({"submit": submit_body, "first_keyframe": first_type, "last_keyframe": last_type}, 10000),
                "视频错误信息": f"已提交 Aitgenne 视频任务，正在轮询。{video_task_route_tag(channel, video_model['display'])} task_id={task_id}",
            }))
        else:
            native_client = get_native_veo_client(runtime_cfg)
            operation = call_native_veo_first_frame_task(
                runtime_cfg,
                prompt,
                str(first_path),
                seconds,
                native_resolution,
                aspect_ratio,
                last_frame_path=str(last_path),
                client=native_client,
            )
            task_id = extract_text(getattr(operation, "name", "")).strip()
            if not task_id:
                raise RuntimeError(f"Veo 多角色视频任务提交未返回 operation name: {compact_json(operation_to_dict(operation), 1200)}")
            safe_update_record(token, TABLE_MULTI_ROLE_FIRST_LAST, record_id, filter_existing_fields(token, TABLE_MULTI_ROLE_FIRST_LAST, {
                "视频任务ID": task_id,
                "视频原始响应JSON": compact_json({"submit": operation_to_dict(operation), "first_keyframe": first_type, "last_keyframe": last_type}, 10000),
                "视频错误信息": f"已提交 AIHubMix Gemini/Veo 视频任务，正在轮询。task_id={task_id}; 视频画面尺寸={size}, native_resolution={native_resolution}",
            }))
    if channel == "OTU":
        result = poll_otu_video_task(runtime_cfg, task_id)
        video_url = extract_video_url(result) or (video_item_url(runtime_cfg.get("api_base") or DEFAULT_OTU_API_BASE, task_id) + "/content")
        download_video(video_url, output_path)
    elif channel == "Aitgenne":
        if reference_route is None:
            raise RuntimeError("Aitgenne 视频路由未初始化")
        result = poll_reference_video_task(reference_route, task_id)
        video_url = extract_video_url(result)
        if not video_url:
            raise RuntimeError(f"Aitgenne 多角色视频生成完成但未返回 video_url: {compact_json(result, 1200)}")
        download_video(video_url, output_path)
    else:
        client = native_client or get_native_veo_client(runtime_cfg)
        operation = types.GenerateVideosOperation(name=task_id) if existing_task_id else operation
        completed_operation = poll_native_veo_operation(client, operation)
        generated_video = extract_native_generated_video(completed_operation)
        result = operation_to_dict(completed_operation)
        video_url = native_generated_video_uri(generated_video)
        download_native_veo_video(client, generated_video, output_path)
    still_current, current_marker = current_video_task_still_matches(token, record_id, version, task_id)
    if not still_current:
        summary.update({
            "status": "stale_writeback_skipped",
            "task_id": task_id,
            "current_task_id": current_marker.get("视频任务ID"),
            "current_version": current_marker.get("视频版本"),
        })
        return summary
    repair_fields: Dict[str, Any] = {
        "视频生成状态": "生成中",
        "视频任务ID": task_id,
        "视频版本": version,
        "视频本地路径": output_path,
        "视频错误信息": "视频已下载到本地，等待飞书上传附件。",
        "错误信息": "",
    }
    if video_url:
        repair_fields["视频片段URL"] = format_url_field_value(video_url, field_types.get("视频片段URL", 0))
    safe_update_record(token, TABLE_MULTI_ROLE_FIRST_LAST, record_id, filter_existing_fields(token, TABLE_MULTI_ROLE_FIRST_LAST, repair_fields))
    file_token = upload_video_to_feishu(token, output_path, f"{record_id}_multi_role_clip.mp4")
    success_fields: Dict[str, Any] = {
        "视频通道": channel,
        "视频生成模型": video_model["display"],
        "视频生成状态": "成功",
        "视频操作": "不触发",
        "视频片段": [{"file_token": file_token, "name": Path(output_path).name}],
        "视频任务ID": task_id,
        "视频版本": version,
        "视频本地路径": output_path,
        "视频片段file_token": file_token,
        "视频原始响应JSON": compact_json(result, 10000),
        "视频错误信息": "",
        "视频生成时间": int(time.time() * 1000),
        "错误信息": "",
    }
    if video_url:
        success_fields["视频片段URL"] = format_url_field_value(video_url, field_types.get("视频片段URL", 0))
    safe_update_record(token, TABLE_MULTI_ROLE_FIRST_LAST, record_id, filter_existing_fields(token, TABLE_MULTI_ROLE_FIRST_LAST, success_fields))
    summary.update({"status": "success", "task_id": task_id, "file_token": file_token, "video_url": video_url})
    return summary


def _history_entries(fields: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = extract_text(fields.get("历史生成记录JSON")).strip()
    try:
        history = json.loads(raw) if raw else []
    except Exception:
        history = []
    if not isinstance(history, list):
        history = []
    return [item for item in history if isinstance(item, dict)]


def _append_history(fields: Dict[str, Any], stage: str, extra: Optional[Dict[str, Any]] = None) -> str:
    history = _history_entries(fields)
    history.append({
        "stage": stage,
        "time": int(time.time() * 1000),
        "reference_file_token": latest_media_token(fields, "参考图", "参考图file_token"),
        "keyframe_file_token": latest_media_token(fields, "关键帧图", "关键帧图file_token"),
        "video_file_token": extract_text(fields.get("视频片段file_token")).strip(),
    })
    if extra:
        history[-1].update(extra)
    return compact_json(history[-20:], 12000)


def keyframe_regeneration_reapprove_allowed(fields: Dict[str, Any]) -> bool:
    for item in reversed(_history_entries(fields)):
        if item.get("stage") != "keyframe_image":
            continue
        return bool(item.get("auto_reapprove_after_regen"))
    return False


def request_reference_regeneration(record_id: str) -> Dict[str, Any]:
    ensure_multi_role_table()
    token = get_feishu_token()
    fields = safe_get_record(token, TABLE_MULTI_ROLE_FIRST_LAST, record_id)
    ensure_active_record(fields)
    if record_type(fields) != ASSET_RECORD_TYPE:
        raise ValueError("只有参考资产记录可以重新生成参考图")
    version = next_version(fields, "参考图版本")
    patch = {
        "参考图操作": "不触发",
        "参考图版本": version,
        "参考图生成状态": "待生成",
        "参考图": [],
        "参考图file_token": "",
        "参考图本地路径": "",
        "参考图任务ID": "",
        "参考图原始响应JSON": "",
        "参考图审核状态": "待确认",
        "参考图错误信息": "",
        "历史生成记录JSON": _append_history(fields, "reference_image"),
        "错误信息": "",
    }
    safe_update_record(token, TABLE_MULTI_ROLE_FIRST_LAST, record_id, filter_existing_fields(token, TABLE_MULTI_ROLE_FIRST_LAST, patch))
    return {"record_id": record_id, "status": "triggered", "version": version}


def request_keyframe_regeneration(record_id: str) -> Dict[str, Any]:
    ensure_multi_role_table()
    token = get_feishu_token()
    fields = safe_get_record(token, TABLE_MULTI_ROLE_FIRST_LAST, record_id)
    ensure_active_record(fields)
    if record_type(fields) != KEYFRAME_RECORD_TYPE:
        raise ValueError("只有关键帧记录可以重新生成关键帧图")
    version = next_version(fields, "关键帧版本")
    previous_review_status = extract_text(fields.get("关键帧审核状态")).strip()
    parent_id = extract_text(fields.get("父任务记录ID")).strip()
    wait_reason = ""
    if parent_id:
        wait_reason = keyframe_dependency_wait_reason(list_multi_role_records_for_parent(token, parent_id), parent_id, fields)
    generation_status = "不触发" if wait_reason else "待生成"
    patch = {
        "关键帧操作": "不触发",
        "关键帧版本": version,
        "关键帧生成状态": generation_status,
        "关键帧图": [],
        "关键帧图file_token": "",
        "关键帧图本地路径": "",
        "关键帧任务ID": "",
        "关键帧原始响应JSON": "",
        "原始请求JSON": "",
        "参考图清单JSON": "",
        "关键帧审核状态": "待确认",
        "关键帧错误信息": wait_reason,
        "历史生成记录JSON": _append_history(fields, "keyframe_image", {
            "previous_keyframe_review_status": previous_review_status,
            "auto_reapprove_after_regen": review_passed(previous_review_status),
        }),
        "错误信息": wait_reason,
    }
    safe_update_record(token, TABLE_MULTI_ROLE_FIRST_LAST, record_id, filter_existing_fields(token, TABLE_MULTI_ROLE_FIRST_LAST, patch))
    return {"record_id": record_id, "status": "waiting_dependency" if wait_reason else "triggered", "version": version, "reason": wait_reason}


def request_video_regeneration(record_id: str) -> Dict[str, Any]:
    ensure_multi_role_table()
    token = get_feishu_token()
    fields = safe_get_record(token, TABLE_MULTI_ROLE_FIRST_LAST, record_id)
    ensure_active_record(fields)
    if record_type(fields) != VIDEO_RECORD_TYPE:
        raise ValueError("只有视频片段记录可以重新生成视频")
    version = next_version(fields, "视频版本")
    parent_id = extract_text(fields.get("父任务记录ID")).strip()
    wait_reason = ""
    if parent_id:
        wait_reason = video_dependency_wait_reason(list_multi_role_records_for_parent(token, parent_id), parent_id, fields)
    generation_status = "不触发" if wait_reason else "待生成"
    patch = {
        "视频操作": "不触发",
        "视频版本": version,
        "视频生成状态": generation_status,
        "视频片段": [],
        "视频任务ID": "",
        "视频本地路径": "",
        "视频片段URL": None,
        "视频片段file_token": "",
        "视频原始响应JSON": "",
        "视频错误信息": wait_reason,
        "历史生成记录JSON": _append_history(fields, "video"),
        "错误信息": wait_reason,
    }
    safe_update_record(token, TABLE_MULTI_ROLE_FIRST_LAST, record_id, filter_existing_fields(token, TABLE_MULTI_ROLE_FIRST_LAST, patch))
    return {"record_id": record_id, "status": "waiting_dependency" if wait_reason else "triggered", "version": version, "reason": wait_reason}


def _failure_update_for_action(action: str, message: str) -> Dict[str, Any]:
    if action == "parse":
        return {"拆解状态": "失败", "错误信息": message[:1000]}
    if action in {"reference-image", "regenerate-reference-image"}:
        return {"参考图操作": "不触发", "参考图生成状态": "失败", "参考图错误信息": message[:1000], "错误信息": message[:1000]}
    if action in {"keyframe-image", "regenerate-keyframe"}:
        return {"关键帧操作": "不触发", "关键帧生成状态": "失败", "关键帧错误信息": message[:1000], "错误信息": message[:1000]}
    if action in {"video", "regenerate-video"}:
        return {"视频操作": "不触发", "视频生成状态": "失败", "视频错误信息": message[:1000], "错误信息": message[:1000]}
    return {"错误信息": message[:1000]}


def main() -> None:
    parser = argparse.ArgumentParser(description="多角色事故救场关键帧/视频生成")
    parser.add_argument("action", choices=[
        "parse",
        "reference-image",
        "keyframe-image",
        "video",
        "advance-reference-review",
        "advance-keyframe-review",
        "advance-ready-videos",
        "regenerate-reference-image",
        "regenerate-keyframe",
        "regenerate-video",
    ])
    parser.add_argument("record_id")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    try:
        if args.action == "parse":
            result = parse_task(args.record_id, dry_run=args.dry_run)
        elif args.action == "reference-image":
            result = render_reference_image(args.record_id, dry_run=args.dry_run)
        elif args.action == "keyframe-image":
            result = render_keyframe_image(args.record_id, dry_run=args.dry_run)
        elif args.action == "video":
            result = render_video_clip(args.record_id, dry_run=args.dry_run)
        elif args.action == "advance-reference-review":
            result = advance_reference_review(args.record_id)
        elif args.action == "advance-keyframe-review":
            result = advance_keyframe_review(args.record_id)
        elif args.action == "advance-ready-videos":
            result = advance_ready_videos(args.record_id)
        elif args.action == "regenerate-reference-image":
            result = request_reference_regeneration(args.record_id)
        elif args.action == "regenerate-keyframe":
            result = request_keyframe_regeneration(args.record_id)
        elif args.action == "regenerate-video":
            result = request_video_regeneration(args.record_id)
        else:
            raise ValueError(f"unsupported action: {args.action}")
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    except Exception as exc:
        payload = build_error_payload(exc, stage=f"multi_role_first_last_{args.action}")
        print(
            f"ERROR_CODE={payload.get('error_code', 'RUNTIME_BUG')} "
            f"RETRYABLE={'true' if payload.get('retryable') else 'false'} "
            f"MESSAGE={payload.get('message', str(exc))}",
            file=sys.stderr,
        )
        log_event("ERROR", "multi-role first-last failed", action=args.action, record_id=args.record_id, error=payload)
        if not args.dry_run:
            try:
                token = get_feishu_token()
                if TABLE_MULTI_ROLE_FIRST_LAST:
                    safe_update_record(token, TABLE_MULTI_ROLE_FIRST_LAST, args.record_id, filter_existing_fields(token, TABLE_MULTI_ROLE_FIRST_LAST, _failure_update_for_action(args.action, payload["message"])))
            except Exception as write_exc:
                log_event("ERROR", "multi-role failure writeback failed", error=str(write_exc)[:500])
        raise


if __name__ == "__main__":
    main()
