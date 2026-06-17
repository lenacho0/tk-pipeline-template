#!/usr/bin/env python3
"""
多图宫格方案、宫格图片、整板视频生成。

用法:
  python3 tk_nine_grid_video.py plan <parent_record_id>
  python3 tk_nine_grid_video.py image <board_record_id>
  python3 tk_nine_grid_video.py video <board_record_id>
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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (  # noqa: E402
    APP_TOKEN,
    TABLE_CONFIG,
    TABLE_MODEL,
    TABLE_NINE_GRID_VIDEO,
    TABLE_PRODUCT,
    WORKSPACE,
    aitgenne_get,
    aitgenne_post,
    build_error_payload,
    extract_linked_record_ids,
    extract_text,
    feishu_headers,
    get_feishu_token,
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
    download_otu_image_result,
    extract_otu_result_url,
    poll_otu_image_task,
    submit_otu_image_task,
)
from tk_nine_grid_video_prompt import (  # noqa: E402
    NINE_GRID_IMAGE_SYSTEM_PROMPT,
    NINE_GRID_PLAN_SYSTEM_PROMPT,
    NINE_GRID_VIDEO_SYSTEM_PROMPT,
)
from tk_shot_script_gen import extract_json_object  # noqa: E402
from tk_reference_media import (  # noqa: E402
    build_reference_contact_sheet,
    compact_json,
    poll_omni_video_task,
    submit_omni_video_task,
)
from tk_shot_storyboard import build_reference_urls, filter_existing_fields  # noqa: E402
from tk_shot_video import (  # noqa: E402
    download_video,
    download_video_without_env_proxy,
    extract_video_url,
    format_url_field_value,
    get_table_field_types,
    upload_video_to_feishu,
)
import ai_model_catalog  # noqa: E402
import ai_routing  # noqa: E402
from aitgenne_image import (  # noqa: E402
    DEFAULT_AITGENNE_API_BASE,
    save_aitgenne_image_result,
    submit_aitgenne_image_generation,
)
from image_generation import image_execution_params, run_image_generation  # noqa: E402
from tk_model_config_center import TASK_TABLES, apply_task_default_to_fields, apply_task_default_to_record, load_stage_config_fields  # noqa: E402
from tk_auto_review import TABLE_AUTO_REVIEW_STAGE_NAMES, auto_review_enabled  # noqa: E402


AUTO_REVIEW_STAGE_NAME = TABLE_AUTO_REVIEW_STAGE_NAMES["nine_grid_video"]
PLAN_STAGE_NAME = "多图宫格方案生成"
IMAGE_STAGE_NAME = "多图宫格图片生成"
VIDEO_STAGE_NAME = "多图宫格视频生成"
REFERENCE_STAGE_NAME = "多图宫格图片生成"
INPUT_MODE_DIRECT_DOC = "文档直拆"
INPUT_MODE_LEGACY_AI_PLAN = "AI方案生成（旧）"
DEFAULT_TEXT_PROVIDER = "AIHubMix"
DEFAULT_TEXT_MODEL = "AIHubMix / gemini-3.1-pro-preview"
DEFAULT_IMAGE_PROVIDER = "OTU"
DEFAULT_IMAGE_MODEL = "OTU / gpt-image-2"
DEFAULT_VIDEO_PROVIDER = "OTU"
DEFAULT_VIDEO_MODEL = "OTU / omni_flash-10s"
DEFAULT_IMAGE_SIZE = "720x1280"
DEFAULT_VIDEO_SIZE = "720x1280"
DEFAULT_ASPECT_RATIO = "9:16"
BASE_WORK_DIR = Path(WORKSPACE) / "nine_grid_video_work"
SUPPORTED_GRID_LAYOUTS = {
    4: "2x2",
    6: "3x2",
    8: "4x2",
    9: "3x3",
}
SUPPORTED_GRID_COUNTS_TEXT = "4/6/8/9"
DEFAULT_AI_PLAN_GRID_COUNT = 4
MAX_REFERENCE_IMAGES = 7
REFERENCE_VIDEO_MAX_IMAGES = 9
OTU_NINE_GRID_VIDEO_MAX_POLL_SECONDS = 2400
OTU_NINE_GRID_VIDEO_POLL_INTERVAL = 15
OTU_NINE_GRID_VIDEO_POLL_TIMEOUT = 45
OTU_NINE_GRID_QUEUED_ZERO_PROGRESS_TIMEOUT_SECONDS = 600
THAI_TEXT_RE = re.compile(r"[\u0E00-\u0E7F]")
CJK_TEXT_RE = re.compile(r"[\u3400-\u9FFF]")
TIME_RANGE_RE = re.compile(
    r"(?P<start>\d+(?:\.\d+)?)\s*[-–—]\s*(?P<end>\d+(?:\.\d+)?)\s*s?",
    re.IGNORECASE,
)
DIRECT_DOC_TIME_RANGE_RE = re.compile(
    r"(?P<start>\d+(?:\.\d+)?)\s*[-–—]\s*(?P<end>\d+(?:\.\d+)?)\s*s\b",
    re.IGNORECASE,
)
MARKDOWN_HEADING_RE = re.compile(r"^(?P<marks>#{2,3})\s+(?P<title>.+?)\s*$", re.MULTILINE)
FENCED_CODE_RE = re.compile(r"```[^\n]*\n(?P<body>.*?)\n```", re.DOTALL)
NINE_GRID_VIDEO_TRANSLATION_INSTRUCTION = (
    "Faithfully translate any Chinese visual/action directions into English while preserving all Thai dialogue exactly. "
    "Do not rewrite, soften, add, remove, or sanitize story details."
)
REFERENCE_SOURCE_AI = "AI自动生成"
REFERENCE_SOURCE_MANUAL = "手动上传"
REFERENCE_SOURCE_MODEL_TABLE = "选择模特表"
ASSET_RECORD_TYPE = "参考资产"
REFERENCE_REVIEW_PASSED_STATUSES = {"通过", "已触发下游"}
REFERENCE_REVIEW_HANDLED_STATUS = "已触发下游"
ENVIRONMENT_EMPTY_SCENE_PREFIX = """
EMPTY ENVIRONMENT REFERENCE PLATE ONLY.
Generate one empty but lived-in local home environment reference image for later use as a consistency reference. Show only the room, furniture, surfaces, material texture, natural lighting, camera angle, non-character household props, and any visible problem marks explicitly described in Scene details. If Scene details include visible problem marks, render exactly those marks and their described locations. If no problem mark is described, do not invent any visible problem mark or odor source. The space should feel like a real local UGC phone photo, not a cleaned advertising set: include everyday household clutter, mild mess, wear marks, imperfect surfaces, localized details, small practical objects, cables, bowls, laundry, slippers, bags, tissue boxes, cleaning items, or other plausible daily-life objects when appropriate to the scene. Do not include any people, pets, product bottles, spray packaging, hands, body parts, reflections of people or animals, posters/screens containing people or animals, text, subtitles, logos, or watermarks.
""".strip()
ENVIRONMENT_LEGACY_PREFIX_PATTERNS = [
    re.compile(r"^Generate one empty but lived-in local home environment reference plate\b", re.IGNORECASE),
    re.compile(r"^Generate one empty lived-in home environment reference image\b", re.IGNORECASE),
    re.compile(r"^Generate an empty scene master/background plate\b", re.IGNORECASE),
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
ENVIRONMENT_FORBIDDEN_SOURCE_TERMS = {
    "dog", "cat", "pet", "animal",
    "狗", "猫", "宠物", "动物",
}
ENVIRONMENT_FORBIDDEN_ENTITY_TERMS = {
    "person", "people", "human", "woman", "man", "girl", "boy", "lady",
    "bottle", "spray", "product", "hand",
    "人物", "人像", "真人", "女人", "男人", "女孩", "男孩", "产品", "喷雾", "瓶", "手",
}
ENVIRONMENT_FORBIDDEN_TERMS = ENVIRONMENT_FORBIDDEN_ENTITY_TERMS | ENVIRONMENT_FORBIDDEN_SOURCE_TERMS
ENVIRONMENT_NEGATION_TERMS = {
    "no ", "without", "forbidden", "do not", "don't", "must not",
    "禁止", "不要", "不得", "不能", "无人物", "无人", "不出现", "严禁",
}
ENVIRONMENT_PROBLEM_EVIDENCE_TERMS = {
    "urine", "pee", "stain", "stains", "stained", "ring", "wet patch", "wet patches",
    "yellow urine", "urine ring", "urine stain", "cat urine", "dog urine",
    "尿", "尿渍", "尿迹", "尿圈", "黄色尿渍", "黄色尿迹", "黄尿", "污渍", "湿斑", "湿痕",
}
ENVIRONMENT_FORBIDDEN_CLEANUP_PATTERNS = [
    (re.compile(r"\b(cat|dog|pet|puppy|animal)\s+(urine stain|pee stain|wet patch|stain)\b", re.IGNORECASE), r"\2"),
    (re.compile(r"\b(person|people|human|woman|man|girl|boy|lady|cat|dog|pet|puppy|animal|product|spray|bottle|hand)\b", re.IGNORECASE), ""),
    (re.compile(r"(人物|人像|真人|女人|男人|女孩|男孩|小狗|狗狗|猫|宠物|动物|产品|喷雾|瓶|手)"), ""),
]
SECRET_FALLBACK_STAGES = {
    IMAGE_STAGE_NAME: ("图片生成-OTU",),
    VIDEO_STAGE_NAME: ("分镜视频生成-OTU",),
}
STAGE_NAME_ALIASES = {
    "多图宫格方案生成": ("多图九宫格方案生成",),
    "多图宫格图片生成": ("多图九宫格图片生成",),
    "多图宫格视频生成": ("多图九宫格视频生成",),
}


def ensure_nine_grid_table() -> None:
    if not TABLE_NINE_GRID_VIDEO:
        raise RuntimeError("config.json 尚未配置 nine_grid_video 表 ID")


def ensure_work_dir(record_id: str) -> Path:
    work_dir = BASE_WORK_DIR / record_id
    work_dir.mkdir(parents=True, exist_ok=True)
    return work_dir


def _as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _attachment_tokens(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    tokens: List[str] = []
    for item in value:
        if isinstance(item, dict) and item.get("file_token"):
            tokens.append(str(item["file_token"]).strip())
    return [token for token in tokens if token]


def _extract_link_ids(value: Any) -> List[str]:
    linked = extract_linked_record_ids(value)
    if linked:
        return linked
    if isinstance(value, list):
        return [str(item).strip() for item in value if isinstance(item, str) and item.strip()]
    return []


def _strip_markdown_code_block(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        lines = stripped.splitlines()
        return "\n".join(lines[1:-1]).strip()
    return stripped


def _markdown_sections(markdown: str) -> List[Dict[str, Any]]:
    matches = list(MARKDOWN_HEADING_RE.finditer(markdown))
    sections: List[Dict[str, Any]] = []
    for idx, match in enumerate(matches):
        level = len(match.group("marks"))
        next_start = len(markdown)
        for later in matches[idx + 1:]:
            if len(later.group("marks")) <= level:
                next_start = later.start()
                break
        sections.append({
            "level": level,
            "title": match.group("title").strip(),
            "body": markdown[match.end():next_start].strip(),
        })
    return sections


def _prompt_body_from_section(body: str, title: str) -> str:
    match = FENCED_CODE_RE.search(body)
    prompt = (match.group("body") if match else body).strip()
    if not prompt:
        raise ValueError(f"{title} 提示词为空")
    return prompt


REFERENCE_PROMPT_TITLE_MARKERS = ("参考图提示词", "参考图生成提示词")

REFERENCE_TYPE_KEYWORDS = {
    "product": ("产品", "product"),
    "pet": ("宠物", "猫", "狗", "pet", "cat", "dog"),
    "environment": ("环境", "场景", "卧室", "门槛", "room", "scene", "environment"),
    "human": (
        "人物", "主人", "伴侣", "爸爸", "妈妈", "父亲", "母亲", "家人", "家属", "室友", "房东", "租客", "男友", "女友",
        "孩子", "儿童", "小孩", "男孩", "女孩",
        "人", "human", "man", "woman", "person", "father", "mother", "dad", "mom", "roommate", "landlord", "tenant", "owner",
        "child", "kid", "boy", "girl",
    ),
}


def _is_reference_prompt_title(title: str) -> bool:
    return any(marker in title for marker in REFERENCE_PROMPT_TITLE_MARKERS)


def _contains_reference_keyword(text: str, asset_type: str) -> bool:
    lowered = text.lower()
    return any(keyword in text or keyword in lowered for keyword in REFERENCE_TYPE_KEYWORDS[asset_type])


def _reference_asset_kind(title: str, prompt: str = "") -> str:
    for asset_type in ("product", "human", "pet", "environment"):
        if _contains_reference_keyword(title, asset_type):
            return asset_type
    for asset_type in ("product", "human", "pet", "environment"):
        if _contains_reference_keyword(prompt, asset_type):
            return asset_type
    return ""


def _reference_title_without_prompt_suffix(title: str) -> str:
    name = title.strip()
    for suffix in ("参考图生成提示词", "参考图提示词"):
        if name.endswith(suffix):
            name = name[:-len(suffix)].strip()
            break
    return name.strip(" -_｜|：:")


def _reference_title_name(title: str, asset_type: str, index: int) -> str:
    for marker in ("｜", "|", "：", ":"):
        if marker in title:
            name = title.split(marker, 1)[1].strip()
            for suffix in ("参考图生成提示词", "参考图提示词"):
                if name.endswith(suffix):
                    name = name[:-len(suffix)].strip()
            if name:
                return name
    fallback = _reference_title_without_prompt_suffix(title)
    type_labels = {
        "human": ("人物", "human"),
        "pet": ("宠物", "pet"),
        "environment": ("环境", "environment"),
        "product": ("产品", "product"),
    }
    if fallback and fallback not in type_labels.get(asset_type, ()):
        return fallback
    defaults = {"human": "人物", "pet": "宠物", "environment": "环境"}
    return f"{defaults.get(asset_type, asset_type)}{index}"


def _extract_board_index(title: str, suffix: str) -> Optional[int]:
    if suffix not in title:
        return None
    match = re.search(r"\bBoard\s*0*(\d+)\b", title, re.IGNORECASE)
    if not match:
        return None
    return int(match.group(1))


def _extract_board_index_any(title: str, suffixes: Iterable[str]) -> Optional[int]:
    for suffix in suffixes:
        board_index = _extract_board_index(title, suffix)
        if board_index is not None:
            return board_index
    return None


def grid_layout_for_count(grid_count: int) -> str:
    layout = SUPPORTED_GRID_LAYOUTS.get(grid_count)
    if not layout:
        raise ValueError(f"宫格数量仅支持 {SUPPORTED_GRID_COUNTS_TEXT} 宫格")
    return layout


def grid_count_label(grid_count: int) -> str:
    return f"{grid_count}宫格"


def _parse_grid_count(value: Any, *, default: int = 0) -> int:
    text = extract_text(value).strip()
    if not text:
        return default
    match = re.search(r"\d+", text)
    if not match:
        return default
    grid_count = int(match.group(0))
    grid_layout_for_count(grid_count)
    return grid_count


def _selected_grid_count(fields: Dict[str, Any], *, default: int = 0) -> int:
    return _parse_grid_count(fields.get("宫格数量"), default=default)


def _field_value(fields: Dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in fields and fields.get(name) not in (None, ""):
            return fields.get(name)
    return ""


def _cell_count_for_board(board: Dict[str, Any]) -> int:
    return len(_as_list(board.get("cells")))


def _validate_grid_count(grid_count: int, *, requested_grid_count: int = 0) -> int:
    grid_layout_for_count(grid_count)
    if requested_grid_count and grid_count != requested_grid_count:
        raise ValueError(f"宫格数量不一致：用户选择 {requested_grid_count} 宫格，但文档/方案包含 {grid_count} 个 Cell")
    return grid_count


def _derive_time_range_from_video_prompt(prompt: str) -> str:
    matches = list(DIRECT_DOC_TIME_RANGE_RE.finditer(prompt))
    if not matches:
        return ""
    starts = [float(match.group("start")) for match in matches]
    ends = [float(match.group("end")) for match in matches]
    start = min(starts)
    end = max(ends)
    return f"{start:.1f}-{end:.1f}s"


def _extract_cells_from_image_prompt(prompt: str) -> List[Dict[str, Any]]:
    matches = list(re.finditer(r"^Cell\s+(\d+)\s*:\s*(.*?)(?=^Cell\s+\d+\s*:|\Z)", prompt, re.MULTILINE | re.DOTALL))
    cells: List[Dict[str, Any]] = []
    for match in matches:
        try:
            cell_index = int(match.group(1))
        except ValueError:
            continue
        summary = " ".join(match.group(2).strip().split())
        if not summary:
            continue
        cells.append({
            "cell_index": cell_index,
            "visual_node": summary,
            "character_action": "",
            "product_state": "",
            "environment_anchor": "",
            "emotion": "",
            "camera": "",
            "dialogue_or_voiceover": "",
        })
    if not cells:
        for raw_line in prompt.replace("\r\n", "\n").split("\n"):
            line = raw_line.strip()
            match = re.match(r"^S(\d{1,2})\s*:\s*(.+)$", line, re.IGNORECASE)
            if not match:
                continue
            try:
                cell_index = int(match.group(1))
            except ValueError:
                continue
            summary = " ".join(match.group(2).strip().split())
            if not summary:
                continue
            cells.append({
                "cell_index": cell_index,
                "visual_node": summary,
                "character_action": "",
                "product_state": "",
                "environment_anchor": "",
                "emotion": "",
                "camera": "",
                "dialogue_or_voiceover": "",
            })
    cells = sorted(cells, key=lambda item: item["cell_index"])
    if not cells:
        return []
    _validate_grid_count(len(cells))
    return cells


def parse_direct_markdown_document(markdown: str, *, requested_grid_count: int = 0) -> Dict[str, Any]:
    text = extract_text(markdown).strip()
    if not text:
        raise ValueError("脚本内容为空")
    sections = _markdown_sections(text)
    reference_items: List[Dict[str, Any]] = []
    product_reference_prompt = ""
    type_counts: Dict[str, int] = {}
    image_prompts: Dict[int, str] = {}
    video_prompts: Dict[int, str] = {}
    for section in sections:
        title = section["title"]
        if section["level"] == 3 and _is_reference_prompt_title(title):
            prompt = _prompt_body_from_section(section["body"], title)
            asset_type = _reference_asset_kind(title, prompt)
            if asset_type == "product":
                product_reference_prompt = prompt
                continue
            if asset_type not in {"human", "pet", "environment"}:
                raise ValueError(f"未知参考图类型: {title}")
            type_counts[asset_type] = type_counts.get(asset_type, 0) + 1
            reference_items.append({
                "role": asset_type,
                "name": _reference_title_name(title, asset_type, type_counts[asset_type]),
                "purpose": prompt,
                "prompt": prompt,
                "direct_prompt": True,
            })
            continue
        image_index = _extract_board_index_any(title, ("宫格分镜图提示词", "九宫格分镜图提示词"))
        if image_index is not None:
            image_prompts[image_index] = _prompt_body_from_section(section["body"], title)
            continue
        video_index = _extract_board_index(title, "图生视频提示词")
        if video_index is not None:
            video_prompts[video_index] = _prompt_body_from_section(section["body"], title)

    if not image_prompts:
        raise ValueError("文档缺少 Board 宫格分镜图提示词")
    boards: List[Dict[str, Any]] = []
    inferred_grid_count = 0
    for board_index in sorted(image_prompts):
        if board_index not in video_prompts:
            raise ValueError(f"Board {board_index} 缺少图生视频提示词")
        image_prompt = image_prompts[board_index]
        video_prompt = video_prompts[board_index]
        cells = _extract_cells_from_image_prompt(image_prompt)
        if not cells:
            raise ValueError("文档宫格分镜图提示词缺少 Cell 列表")
        board_grid_count = _validate_grid_count(len(cells), requested_grid_count=requested_grid_count)
        if inferred_grid_count and board_grid_count != inferred_grid_count:
            raise ValueError(f"宫格数量不一致：同一母任务下 Board 宫格数量必须一致，已发现 {inferred_grid_count} 和 {board_grid_count}")
        inferred_grid_count = board_grid_count
        boards.append({
            "board_index": board_index,
            "grid_count": board_grid_count,
            "grid_layout": grid_layout_for_count(board_grid_count),
            "time_range": _derive_time_range_from_video_prompt(video_prompt),
            "narrative_task": "",
            "start_frame": "",
            "end_frame": "",
            "handoff_anchor": "",
            "cells": cells,
            "image_prompt": image_prompt,
            "video_prompt": video_prompt,
            "direct_prompt": True,
        })
    extra_video_boards = sorted(set(video_prompts) - set(image_prompts))
    if extra_video_boards:
        raise ValueError(f"Board {extra_video_boards[0]} 缺少宫格分镜图提示词")
    return {
        "task_type": "MULTI_IMAGE_NINE_GRID_DIRECT_DOC",
        "grid_count": inferred_grid_count,
        "grid_layout": grid_layout_for_count(inferred_grid_count),
        "script_analysis": {},
        "reference_manifest": {"required_references": reference_items},
        "product_reference_prompt": product_reference_prompt,
        "boards": boards,
        "continuity_check": {},
    }


def normalize_nine_grid_plan_payload(payload: Any, *, requested_grid_count: int = DEFAULT_AI_PLAN_GRID_COUNT) -> Dict[str, Any]:
    data = payload
    if isinstance(payload, str):
        stripped = _strip_markdown_code_block(payload)
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            data = extract_json_object(stripped)
    if not isinstance(data, dict):
        raise ValueError("宫格方案结果必须是 JSON 对象")
    if extract_text(data.get("task_type")).strip() != "MULTI_IMAGE_NINE_GRID_PLAN":
        raise ValueError("宫格方案 task_type 必须是 MULTI_IMAGE_NINE_GRID_PLAN")
    boards = _as_list(data.get("boards"))
    if not boards:
        raise ValueError("宫格方案缺少 boards")
    normalized_boards = []
    expected_grid_count = _parse_grid_count(data.get("grid_count") or data.get("宫格数量"), default=requested_grid_count)
    expected_grid_count = _validate_grid_count(expected_grid_count or DEFAULT_AI_PLAN_GRID_COUNT)
    for idx, board in enumerate(boards, start=1):
        if not isinstance(board, dict):
            raise ValueError(f"boards[{idx}] 必须是对象")
        cells = _as_list(board.get("cells"))
        board_grid_count = _validate_grid_count(len(cells), requested_grid_count=expected_grid_count)
        normalized_cells = []
        for cell_idx, cell in enumerate(cells, start=1):
            if not isinstance(cell, dict):
                raise ValueError(f"Board {idx} cell {cell_idx} 必须是对象")
            normalized_cells.append({
                "cell_index": int(cell.get("cell_index") or cell_idx),
                "visual_node": extract_text(cell.get("visual_node")).strip(),
                "character_action": extract_text(cell.get("character_action")).strip(),
                "product_state": extract_text(cell.get("product_state")).strip(),
                "environment_anchor": extract_text(cell.get("environment_anchor")).strip(),
                "emotion": extract_text(cell.get("emotion")).strip(),
                "camera": extract_text(cell.get("camera")).strip(),
                "dialogue_or_voiceover": extract_text(cell.get("dialogue_or_voiceover")).strip(),
            })
        normalized_board = dict(board)
        normalized_board["board_index"] = int(board.get("board_index") or idx)
        normalized_board["grid_count"] = board_grid_count
        normalized_board["grid_layout"] = grid_layout_for_count(board_grid_count)
        normalized_board["cells"] = normalized_cells
        normalized_board["image_prompt"] = extract_text(board.get("image_prompt")).strip() or build_board_image_prompt(normalized_board)
        normalized_board["video_prompt"] = extract_text(board.get("video_prompt")).strip() or build_board_video_prompt(normalized_board)
        normalized_boards.append(normalized_board)
    normalized = dict(data)
    normalized["grid_count"] = expected_grid_count
    normalized["grid_layout"] = grid_layout_for_count(expected_grid_count)
    normalized["boards"] = normalized_boards
    return normalized


def build_board_image_prompt(board: Dict[str, Any]) -> str:
    grid_count = _cell_count_for_board(board) or int(board.get("grid_count") or DEFAULT_AI_PLAN_GRID_COUNT)
    layout = grid_layout_for_count(grid_count)
    lines = [
        f"Create one vertical 9:16 image containing exactly {grid_count} panels arranged in a {layout} storyboard grid.",
        "Each panel is a vertical 9:16 smartphone UGC video still.",
        "Read panels left to right, top to bottom.",
        "Use the uploaded character, pet, product, and environment reference images as strict identity anchors.",
        "Do not place reference-sheet images inside the timeline panels.",
        "No subtitles, no stickers, no watermarks, no UI, no poster text, no panel numbers.",
        "Avoid visible borders, thick black grid lines, comic panel outlines, gutters, or table-like layout.",
        "Keep the same person/pet/product/environment across all panels.",
    ]
    for cell in _as_list(board.get("cells")):
        lines.append(
            f"Cell {cell.get('cell_index')}: {cell.get('visual_node')}; "
            f"action: {cell.get('character_action')}; product: {cell.get('product_state')}; "
            f"environment: {cell.get('environment_anchor')}; emotion: {cell.get('emotion')}; camera: {cell.get('camera')}."
        )
    return "\n".join(lines)


def contains_thai_text(text: Any) -> bool:
    return bool(THAI_TEXT_RE.search(extract_text(text)))


def parse_seconds_time_range(text: Any) -> Optional[Tuple[float, float]]:
    match = TIME_RANGE_RE.search(extract_text(text))
    if not match:
        return None
    start = float(match.group("start"))
    end = float(match.group("end"))
    if end < start:
        start, end = end, start
    return start, end


def ranges_overlap(left: Tuple[float, float], right: Tuple[float, float]) -> bool:
    left_start, left_end = left
    right_start, right_end = right
    return left_start < right_end and left_end > right_start


def sanitize_script_thai_dialogue_line(line: str) -> str:
    thai_match = THAI_TEXT_RE.search(line)
    if not thai_match:
        return ""
    tail = line[thai_match.start():]
    cjk_match = CJK_TEXT_RE.search(tail)
    if cjk_match:
        tail = tail[:cjk_match.start()]
    tail = tail.strip(" \t\r\n,，;；")
    if not tail:
        return ""
    return tail


def extract_script_thai_dialogue(script: str) -> List[Dict[str, Any]]:
    lines: List[Dict[str, Any]] = []
    current_time_range: Optional[Tuple[float, float]] = None
    seen = set()
    for raw_line in script.replace("\r\n", "\n").split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        parsed_range = parse_seconds_time_range(line)
        if parsed_range:
            current_time_range = parsed_range
        if not contains_thai_text(line):
            continue
        dialogue = sanitize_script_thai_dialogue_line(line)
        if not dialogue or dialogue in seen:
            continue
        seen.add(dialogue)
        lines.append({"text": dialogue, "time_range": current_time_range})
    return lines


def select_script_thai_dialogue_for_board(script: str, board: Dict[str, Any]) -> List[str]:
    dialogue_items = extract_script_thai_dialogue(script)
    if not dialogue_items:
        return []
    board_range = parse_seconds_time_range(board.get("time_range"))
    if not board_range:
        return [item["text"] for item in dialogue_items]
    selected = [
        item["text"]
        for item in dialogue_items
        if item.get("time_range") and ranges_overlap(item["time_range"], board_range)
    ]
    return selected or [item["text"] for item in dialogue_items]


def script_dialogue_items_for_board(script: str, board: Dict[str, Any]) -> List[Dict[str, Any]]:
    dialogue_items = extract_script_thai_dialogue(script)
    if not dialogue_items:
        return []
    board_range = parse_seconds_time_range(board.get("time_range"))
    if not board_range:
        return dialogue_items
    selected = [
        item for item in dialogue_items
        if item.get("time_range") and ranges_overlap(item["time_range"], board_range)
    ]
    return selected or dialogue_items


def extract_board_cell_thai_dialogue(board: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    seen = set()
    for cell in _as_list(board.get("cells")):
        dialogue = sanitize_script_thai_dialogue_line(extract_text(cell.get("dialogue_or_voiceover")).strip())
        if not dialogue or not contains_thai_text(dialogue):
            continue
        if dialogue in seen:
            continue
        seen.add(dialogue)
        lines.append(dialogue)
    return lines


def extract_cell_thai_dialogue(cell: Dict[str, Any]) -> List[str]:
    dialogue = sanitize_script_thai_dialogue_line(extract_text(cell.get("dialogue_or_voiceover")).strip())
    if not dialogue or not contains_thai_text(dialogue):
        return []
    return [dialogue]


def _format_seconds(value: float) -> str:
    text = f"{value:.1f}"
    return text[:-2] if text.endswith(".0") else text


def board_cell_time_range(board: Dict[str, Any], cell_index: int) -> Optional[Tuple[float, float]]:
    board_range = parse_seconds_time_range(board.get("time_range"))
    cells = _as_list(board.get("cells"))
    total_cells = len(cells) or 9
    if not board_range or total_cells <= 0:
        return None
    start, end = board_range
    duration = max(end - start, 0.0)
    step = duration / total_cells if total_cells else 0.0
    offset = max(cell_index - 1, 0)
    cell_start = start + step * offset
    cell_end = end if cell_index >= total_cells else start + step * (offset + 1)
    return cell_start, cell_end


def format_cell_time_label(board: Dict[str, Any], cell_index: int) -> str:
    cell_range = board_cell_time_range(board, cell_index)
    if not cell_range:
        return f"Cell {cell_index} / approx storyboard beat {cell_index}"
    return f"Cell {cell_index} / approx {_format_seconds(cell_range[0])}-{_format_seconds(cell_range[1])}s"


def dialogue_for_cell(
    board: Dict[str, Any],
    cell: Dict[str, Any],
    script_dialogue_items: List[Dict[str, Any]],
) -> List[str]:
    cell_index = int(cell.get("cell_index") or 0)
    cell_range = board_cell_time_range(board, cell_index)
    selected: List[str] = []
    if cell_range:
        selected = [
            item["text"]
            for item in script_dialogue_items
            if item.get("time_range") and ranges_overlap(item["time_range"], cell_range)
        ]
    if selected:
        return selected
    return extract_cell_thai_dialogue(cell)


def build_audio_dialogue_section(dialogue_lines: List[str]) -> str:
    if not dialogue_lines:
        return ""
    lines = [
        "Audio constraints:",
        "All Thai dialogue lines above are exact audio lines; preserve them verbatim, in order, and in the same language.",
        "Do not translate, rewrite, summarize, add, remove, or move dialogue.",
        "Dialogue and voiceover are audio only. No subtitles, captions, stickers, labels, or visible Thai text.",
        "Use natural local Thai TikTok delivery matched to each character's emotion.",
    ]
    return "\n".join(lines)


def append_audio_dialogue_to_video_prompt(prompt: str, dialogue_lines: List[str]) -> str:
    clean_prompt = extract_text(prompt).strip()
    if "Audio / spoken dialogue" in clean_prompt:
        section_lines = [line for line in dialogue_lines if line and line not in clean_prompt]
    else:
        section_lines = [line for line in dialogue_lines if line]
    section = build_audio_dialogue_section(section_lines)
    if not section:
        return clean_prompt
    if clean_prompt:
        return f"{clean_prompt}\n\n{section}"
    return section


def build_board_video_prompt_for_record(parent_fields: Dict[str, Any], board: Dict[str, Any]) -> str:
    return build_timed_board_video_prompt_for_record(parent_fields, board)


def build_timed_board_video_prompt_for_record(parent_fields: Dict[str, Any], board: Dict[str, Any]) -> str:
    script = extract_text(parent_fields.get("脚本内容")).strip()
    script_items = script_dialogue_items_for_board(script, board)
    fallback_lines = extract_board_cell_thai_dialogue(board)
    prompt_intro = extract_text(board.get("video_prompt")).strip()
    board_time = extract_text(board.get("time_range")).strip()
    narrative_task = extract_text(board.get("narrative_task")).strip()
    grid_count = _cell_count_for_board(board) or int(board.get("grid_count") or DEFAULT_AI_PLAN_GRID_COUNT)
    lines = [
        f"Generate one continuous {board_time or '8-12s'} vertical 9:16 TikTok UGC smartphone video from the current Board {grid_count}-panel storyboard.",
        "Use the multi-panel storyboard image as a narrative order reference only; do not render a split-screen, grid, panel borders, UI, or captions.",
        "Follow the cells left to right, top to bottom, while keeping one continuous scene and natural action flow.",
        "Reference / consistency guard:",
        "- Keep the same person, pet, product, room, furniture, lighting, problem location, and product package from the uploaded references.",
        "- If the visual storyboard conflicts with the product reference image, the product reference image wins.",
    ]
    if narrative_task:
        lines.append(f"- Narrative task: {narrative_task}")
    if prompt_intro:
        lines.append(f"- Existing board direction to preserve visually: {prompt_intro}")
    lines.append("")
    lines.append("Timeline beats:")
    used_dialogue: List[str] = []
    cells = _as_list(board.get("cells"))
    for idx, cell in enumerate(cells, start=1):
        cell_index = int(cell.get("cell_index") or idx)
        cell_dialogue = dialogue_for_cell(board, cell, script_items)
        if not cell_dialogue and not script_items and fallback_lines:
            cell_dialogue = extract_cell_thai_dialogue(cell)
        used_dialogue.extend(cell_dialogue)
        dialogue_text = " / ".join(cell_dialogue) if cell_dialogue else "No speech; natural room tone only."
        lines.extend([
            "",
            f"{format_cell_time_label(board, cell_index)}:",
            f"Visual: {extract_text(cell.get('visual_node')).strip() or 'Continue the storyboard action.'}",
            f"Action: {extract_text(cell.get('character_action')).strip() or 'Keep the characters moving naturally according to the storyboard.'}",
            f"Camera: {extract_text(cell.get('camera')).strip() or 'Natural handheld smartphone framing.'}",
            f"Emotion: {extract_text(cell.get('emotion')).strip() or 'Natural UGC reaction.'}",
            f"Dialogue/Voiceover: {dialogue_text}",
            "SFX/Ambient: Use realistic home room tone and only the product/action sounds implied by this beat.",
        ])
    lines.append("")
    lines.append(build_audio_dialogue_section(used_dialogue or fallback_lines))
    lines.extend([
        "",
        "Negative constraints:",
        "No subtitles, captions, labels, stickers, watermarks, logos, poster text, visible Thai text, split-screen grid, panel borders, or reference-sheet layout.",
    ])
    return "\n".join(part for part in lines if part is not None).strip()


def build_board_video_prompt(board: Dict[str, Any]) -> str:
    return build_timed_board_video_prompt_for_record(
        {},
        board,
    )



def build_nine_grid_video_reference_note(refs: List[Dict[str, str]]) -> str:
    if not refs:
        return ""
    lines = ["Reference image order (highest priority first):"]
    has_product_ref = any((ref.get("role") or "").startswith("product:") for ref in refs)
    for idx, ref in enumerate(refs, start=1):
        role = ref.get("role", "")
        name = ref.get("name", "").strip()
        name_note = f" ({name})" if name else ""
        if role == "nine_grid":
            product_guard = (
                " Treat product appearance inside this storyboard as low priority; use it only for action placement."
                if has_product_ref else ""
            )
            lines.append(
                f"Reference image {idx} = current Board multi-panel storyboard. "
                "Use it as the narrative, action-sequence, composition, and character-position reference; "
                "do not render it as a split-screen grid, panel layout, border, or UI."
                f"{product_guard}"
            )
        elif role.startswith("product:"):
            lines.append(
                f"Reference image {idx} = exact product reference{name_note}. "
                "This image has highest priority for the product packaging, bottle silhouette, trigger or cap shape, "
                "label color blocks, logo area, text placement, and proportions. "
                "If the storyboard image conflicts with the product reference image, the product reference image wins."
            )
        elif role.startswith("human:"):
            lines.append(
                f"Reference image {idx} = human character reference{name_note}. "
                "Use this image to lock the character identity, face, hairstyle, body type, outfit, and visual style when that character appears in the multi-panel sequence."
            )
    lines.append("Do not reinterpret later reference images as storyboard panels; use them only for identity and product consistency.")
    return "\n".join(lines)


def _is_aitgenne_omni_flash(route: ai_routing.AiRoute, model_name: Optional[str] = None) -> bool:
    parsed_model = model_name or ai_routing.parse_model_display(route.model)["model"] or route.model
    return route.provider == "Aitgenne" and parsed_model == "omni-flash"


def _aitgenne_reference_limit(route: ai_routing.AiRoute) -> int:
    if route.provider != "Aitgenne" or ai_routing.is_aitgenne_happyhorse_model(route):
        return REFERENCE_VIDEO_MAX_IMAGES
    if ai_routing.is_aitgenne_unified_components_model(route):
        return 3
    if ai_routing.is_aitgenne_unified_video_model(route):
        return 2
    return REFERENCE_VIDEO_MAX_IMAGES


def _reference_roles_summary(refs: List[Dict[str, str]]) -> str:
    return ",".join(ref.get("role", "") for ref in refs if ref.get("role"))


def build_video_model_prompt_for_route(raw_prompt: str, route: ai_routing.AiRoute, refs: Optional[List[Dict[str, str]]] = None) -> str:
    del route
    reference_note = build_nine_grid_video_reference_note(refs or [])
    return "\n\n".join(
        part
        for part in [NINE_GRID_VIDEO_SYSTEM_PROMPT, reference_note, NINE_GRID_VIDEO_TRANSLATION_INSTRUCTION, raw_prompt]
        if part
    ).strip()


def reference_video_item_url(route: ai_routing.AiRoute, task_id: str) -> str:
    return ai_routing.media_task_endpoint(route, task_id)


def video_task_route_tag(route: ai_routing.AiRoute) -> str:
    model_name = ai_routing.parse_model_display(route.model)["model"] or route.model
    return f"provider={route.provider} model={model_name}"


def aitgenne_video_resolution(size: Any) -> str:
    text = extract_text(size).strip().upper()
    if text in {"1080P", "1080"} or "1080" in text or "1920" in text:
        return "1080P"
    return "720P"


def is_legacy_aitgenne_video_payload_error(error_text: str) -> bool:
    return any(marker in error_text for marker in ("InvalidParameter", "input.media", "parameters.resolution"))


def existing_video_task_matches_route(fields: Dict[str, Any], route: ai_routing.AiRoute, task_id: str) -> bool:
    if not task_id:
        return False
    status = extract_text(fields.get("视频生成状态")).strip()
    if status != "生成中":
        return False
    error_text = extract_text(fields.get("视频错误信息")).strip()
    if route.provider == "Aitgenne" and is_legacy_aitgenne_video_payload_error(error_text):
        return False
    tag = video_task_route_tag(route)
    if tag in error_text:
        return True
    if "provider=" in error_text or "model=" in error_text:
        return False
    return route.provider == "OTU" and task_id.startswith("task_")


def submit_reference_video_task(
    route: ai_routing.AiRoute,
    prompt: str,
    refs: List[Dict[str, str]],
    *,
    size: str = DEFAULT_VIDEO_SIZE,
    aspect_ratio: str = DEFAULT_ASPECT_RATIO,
    seconds: str = "10",
) -> Tuple[str, Dict[str, Any]]:
    if not refs:
        raise ValueError("参考图生视频至少需要 1 张参考图")
    if not route.api_key:
        raise ValueError(f"{route.provider} / {route.model} 缺少 API Key")
    model_name = ai_routing.parse_model_display(route.model)["model"] or route.model
    if route.provider == "Aitgenne" and ai_routing.is_aitgenne_happyhorse_model(route):
        urls = [extract_text(ref.get("url")).strip() for ref in refs[:REFERENCE_VIDEO_MAX_IMAGES] if extract_text(ref.get("url")).strip()]
        if not urls:
            raise ValueError("Aitgenne 参考图生视频缺少参考图 URL")
        payload = ai_routing.build_happyhorse_video_payload(
            route,
            prompt,
            urls,
            size=size,
            aspect_ratio=aspect_ratio,
            seconds=seconds,
        )
        resp = aitgenne_post(
            ai_routing.media_endpoint(route),
            headers={"Authorization": f"Bearer {route.api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=180,
        )
        try:
            body = resp.json()
        except Exception:
            body = {"raw_text": resp.text[:1000]}
        if resp.status_code >= 400:
            raise RuntimeError(f"{route.provider} 参考图视频任务提交失败: HTTP {resp.status_code}, body={str(body)[:1200]}")
        task_id = ai_routing.extract_video_task_id(body)
        if not task_id:
            raise RuntimeError(f"{route.provider} 参考图视频任务提交未返回任务 ID: {str(body)[:1200]}")
        return task_id, body

    if route.provider == "Aitgenne":
        limit = _aitgenne_reference_limit(route)
        urls = [extract_text(ref.get("url")).strip() for ref in refs[:limit] if extract_text(ref.get("url")).strip()]
        if not urls:
            raise ValueError("Aitgenne 参考图生视频缺少参考图 URL")
        payload = ai_routing.build_aitgenne_unified_video_payload(
            route,
            prompt,
            urls,
            aspect_ratio=aspect_ratio or DEFAULT_ASPECT_RATIO,
        )
        resp = aitgenne_post(
            ai_routing.media_endpoint(route),
            headers={"Authorization": f"Bearer {route.api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=180,
        )
        try:
            body = resp.json()
        except Exception:
            body = {"raw_text": resp.text[:1000]}
        if resp.status_code >= 400:
            raise RuntimeError(f"{route.provider} 参考图视频任务提交失败: HTTP {resp.status_code}, body={str(body)[:1200]}")
        task_id = ai_routing.extract_video_task_id(body)
        if not task_id:
            raise RuntimeError(f"{route.provider} 参考图视频任务提交未返回任务 ID: {str(body)[:1200]}")
        return task_id, body

    opened = []
    files: List[Tuple[str, Tuple[Any, ...]]] = []
    try:
        for ref in refs[:REFERENCE_VIDEO_MAX_IMAGES]:
            path = ref.get("path", "")
            if not path or not os.path.exists(path):
                raise ValueError(f"参考图不存在: {ref.get('role')}")
            handle = open(path, "rb")
            opened.append(handle)
            files.append(("input_reference[]", (os.path.basename(path), handle, "image/png")))
        resp = requests.post(
            ai_routing.media_endpoint(route),
            headers={"Authorization": f"Bearer {route.api_key}"},
            data={
                "model": model_name,
                "prompt": prompt,
                "seconds": str(seconds or "10"),
                "size": size or DEFAULT_VIDEO_SIZE,
                "aspect_ratio": aspect_ratio or DEFAULT_ASPECT_RATIO,
            },
            files=files,
            timeout=180,
        )
    finally:
        for handle in opened:
            handle.close()
    try:
        body = resp.json()
    except Exception:
        body = {"raw_text": resp.text[:1000]}
    if resp.status_code >= 400:
        raise RuntimeError(f"{route.provider} 参考图视频任务提交失败: HTTP {resp.status_code}, body={str(body)[:1200]}")
    task_id = extract_text(body.get("id") or body.get("task_id") or (body.get("data") or {}).get("id") or (body.get("data") or {}).get("task_id")).strip()
    if not task_id:
        raise RuntimeError(f"{route.provider} 参考图视频任务提交未返回任务 ID: {str(body)[:1200]}")
    return task_id, body


def poll_reference_video_task(route: ai_routing.AiRoute, task_id: str) -> Dict[str, Any]:
    if not route.api_key:
        raise ValueError(f"{route.provider} / {route.model} 缺少 API Key")
    url = reference_video_item_url(route, task_id)
    headers = {"Authorization": f"Bearer {route.api_key}"}
    start = time.time()
    last_body: Dict[str, Any] = {}
    while time.time() - start < 2400:
        resp = aitgenne_get(url, headers=headers, timeout=45)
        try:
            body = resp.json()
        except Exception:
            body = {"raw_text": resp.text[:1000]}
        last_body = body if isinstance(body, dict) else {"raw": body}
        if resp.status_code >= 400:
            raise RuntimeError(f"{route.provider} 参考图视频任务轮询失败: HTTP {resp.status_code}, body={str(last_body)[:1200]}")
        status = ai_routing.extract_video_status(last_body)
        if status in {"completed", "succeeded", "success", "done"}:
            return last_body
        if status in {"failed", "error", "cancelled", "canceled"}:
            raise RuntimeError(f"{route.provider} 参考图视频生成失败: {str(last_body)[:1500]}")
        time.sleep(15)
    raise TimeoutError(f"{route.provider} 参考图视频任务超时: task_id={task_id}, last={str(last_body)[:1200]}")


def _progress_number(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def poll_otu_nine_grid_video_task(
    config: Dict[str, str],
    task_id: str,
    *,
    queued_zero_progress_timeout_seconds: int = OTU_NINE_GRID_QUEUED_ZERO_PROGRESS_TIMEOUT_SECONDS,
    max_poll_seconds: int = OTU_NINE_GRID_VIDEO_MAX_POLL_SECONDS,
    poll_interval: int = OTU_NINE_GRID_VIDEO_POLL_INTERVAL,
    poll_timeout: int = OTU_NINE_GRID_VIDEO_POLL_TIMEOUT,
    now_fn: Callable[[], float] = time.time,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> Dict[str, Any]:
    if not config.get("api_key"):
        raise ValueError(f"OTU / {config.get('model') or DEFAULT_VIDEO_MODEL} 缺少 API Key")
    url = f"{(config.get('api_base') or DEFAULT_OTU_API_BASE).rstrip('/')}/v1/videos/{task_id}"
    headers = {"Authorization": f"Bearer {config['api_key']}"}
    start = now_fn()
    queued_zero_started_at: Optional[float] = None
    last_body: Dict[str, Any] = {}
    while True:
        now = now_fn()
        if now - start >= max_poll_seconds:
            raise TimeoutError(f"OTU 宫格视频任务超时: task_id={task_id}, last={compact_json(last_body, 1200)}")
        resp = requests.get(url, headers=headers, timeout=poll_timeout)
        try:
            body = resp.json()
        except Exception:
            body = {"raw_text": resp.text[:1000]}
        last_body = body if isinstance(body, dict) else {"raw": body}
        if resp.status_code >= 400:
            raise RuntimeError(f"OTU 宫格视频任务轮询失败: HTTP {resp.status_code}, body={str(last_body)[:1200]}")

        nested = last_body.get("data") if isinstance(last_body.get("data"), dict) else {}
        status = extract_text(last_body.get("status") or nested.get("status")).lower()
        progress = _progress_number(last_body.get("progress", nested.get("progress")))
        if status in {"completed", "succeeded", "success", "done"}:
            return last_body
        if status in {"failed", "error", "cancelled", "canceled"}:
            raise RuntimeError(f"OTU 宫格视频生成失败: {str(last_body)[:1500]}")

        if status == "queued" and progress == 0:
            created_at = _progress_number(last_body.get("created_at", nested.get("created_at")))
            if created_at is not None and now >= created_at and now - created_at >= queued_zero_progress_timeout_seconds:
                raise TimeoutError(
                    f"OTU 宫格视频 queued progress=0 timeout，自 created_at 已超过 "
                    f"{queued_zero_progress_timeout_seconds}s: task_id={task_id}, last={compact_json(last_body, 1200)}"
                )
            if queued_zero_started_at is None:
                queued_zero_started_at = now
            elif now - queued_zero_started_at >= queued_zero_progress_timeout_seconds:
                raise TimeoutError(
                    f"OTU 宫格视频 queued progress=0 timeout，超过 {queued_zero_progress_timeout_seconds}s: "
                    f"task_id={task_id}, last={compact_json(last_body, 1200)}"
                )
        else:
            queued_zero_started_at = None
        sleep_fn(poll_interval)


def _field_with_default(fields: Dict[str, Any], name: str, default: str) -> str:
    return extract_text(fields.get(name)).strip() or default


def _usable_model_choice(value: Any) -> str:
    raw = extract_text(value).strip()
    normalized = raw.lower().replace("_", "-").replace(" ", "")
    if normalized in {"", "默认", "默认(配置表)", "默认（配置表）", "配置表默认", "default"}:
        return ""
    return raw


def _prefixed_route_fields(fields: Dict[str, Any], prefix: str, *, default_provider: str, default_model: str) -> Dict[str, str]:
    if prefix == "视频":
        model = (
            _usable_model_choice(fields.get("视频生成模型"))
            or default_model
        )
    elif prefix == "方案":
        model = _field_with_default(fields, "文本AI模型", _field_with_default(fields, f"{prefix}AI模型", default_model))
    else:
        model = _field_with_default(fields, f"{prefix}AI模型", default_model)
    model_provider = ai_routing.parse_model_display(model)["provider"]
    return {
        "provider": model_provider or _field_with_default(fields, f"{prefix}AI供应商", default_provider),
        "model": model,
        "params": extract_text(fields.get(f"{prefix}AI参数JSON")).strip(),
    }


def _parse_params(text: str) -> Dict[str, Any]:
    if not text:
        return {}
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("AI参数JSON 顶层必须是对象")
    return parsed


def _image_param_fields(prefix: str, params: Dict[str, Any]) -> Dict[str, Any]:
    patched_params = dict(params)
    size = extract_text(patched_params.get("size")).strip()
    aspect_ratio = extract_text(patched_params.get("aspect_ratio")).strip()
    fields: Dict[str, Any] = {}
    if size:
        fields[f"{prefix}画面尺寸"] = size
        patched_params["size"] = size
    if aspect_ratio:
        fields[f"{prefix}画面比例"] = aspect_ratio
        patched_params["aspect_ratio"] = aspect_ratio
    if patched_params:
        fields[f"{prefix}AI参数JSON"] = compact_json(patched_params, 4000)
    return fields


def _slug_asset_id(value: str, fallback: str) -> str:
    text = extract_text(value).strip().lower()
    text = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "_", text).strip("_")
    return text or fallback


def _reference_role_to_asset_type(role: str) -> str:
    normalized = extract_text(role).strip().lower()
    if normalized in {"character", "human", "person", "人物", "角色"}:
        return "human"
    if normalized in {"pet", "animal", "宠物"}:
        return "pet"
    if normalized in {"environment", "scene", "room", "场景", "环境"}:
        return "environment"
    return normalized


def _environment_prompt_parts(prompt: str) -> List[str]:
    parts: List[str] = []
    for line in prompt.replace("\r\n", "\n").split("\n"):
        line = line.strip()
        if not line:
            continue
        parts.extend(part.strip() for part in re.split(r"(?<=[.!?。！？])\s+", line) if part.strip())
    return parts


def _contains_environment_term(text: str, term: str) -> bool:
    lowered = text.lower()
    normalized = term.lower()
    if normalized.strip() != normalized:
        return normalized in lowered
    if re.fullmatch(r"[a-z0-9 ]+", normalized):
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])", lowered))
    return normalized in lowered


def _environment_term_hits(text: str, terms: Iterable[str]) -> set:
    return {term for term in terms if _contains_environment_term(text, term)}


def _strip_environment_reference_prefix(prompt: str) -> str:
    text = prompt.replace(ENVIRONMENT_EMPTY_SCENE_PREFIX, "")
    lowered = text.lower()
    for marker in ("scene details to keep:", "scene details:"):
        idx = lowered.rfind(marker)
        if idx >= 0:
            return text[idx + len(marker):]
    return text


def sanitize_environment_reference_prompt(prompt: str) -> str:
    source_prompt = _strip_environment_reference_prefix(prompt)
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
        forbidden_hits = _environment_term_hits(text, ENVIRONMENT_FORBIDDEN_TERMS)
        has_negation = bool(_environment_term_hits(text, ENVIRONMENT_NEGATION_TERMS))
        if forbidden_hits and not has_negation:
            for pattern, replacement in ENVIRONMENT_FORBIDDEN_CLEANUP_PATTERNS:
                text = pattern.sub(replacement, text)
            text = re.sub(r"\s{2,}", " ", text)
            text = re.sub(r"\s+([,.;:!?。！？])", r"\1", text).strip(" ,")
            if not text:
                continue
        cleaned_parts.append(text)
    cleaned = "\n".join(cleaned_parts).strip()
    if cleaned:
        return f"{ENVIRONMENT_EMPTY_SCENE_PREFIX}\n\nScene details:\n{cleaned}"
    return ENVIRONMENT_EMPTY_SCENE_PREFIX


def build_reference_asset_prompt(reference: Dict[str, Any]) -> str:
    asset_type = _reference_role_to_asset_type(reference.get("asset_type") or reference.get("role"))
    name = extract_text(reference.get("asset_name") or reference.get("name")).strip()
    purpose = extract_text(reference.get("purpose") or reference.get("asset_role_description")).strip()
    if asset_type == "environment":
        return sanitize_environment_reference_prompt(
            "\n".join(part for part in [f"Scene: {name}" if name else "", purpose] if part).strip()
        )
    if asset_type == "pet":
        return (
            "Generate one clean full-body pet identity reference image for later video consistency. "
            f"Pet name/role: {name or 'selected pet'}. "
            f"Visual purpose: {purpose or 'lock breed, fur color, body shape, markings, expression, and scale'}. "
            "Show only this pet, no product, no extra animals, no text, no watermark."
        )
    return (
        "Generate one realistic front-facing upper-body human identity reference portrait for later video consistency on a white background. "
        f"Character name/role: {name or 'selected character'}. "
        f"Visual purpose: {purpose or 'lock face, hair, outfit, body type, age impression, and everyday UGC style'}. "
        "Use exactly one single person, pure white background, waist-or-chest-up framing, and a straight-to-camera pose. "
        "The full unobstructed face visible: both eyes, nose, and mouth must be clear and sharp. "
        "The person must look like an ordinary non-professional local person with ordinary local UGC realism and phone snapshot texture, not a studio model, influencer ad model, beauty campaign, or polished catalog render. "
        "Keep visible natural skin texture, pores, fine lines, minor blemishes, uneven skin tone, natural expression, and practical everyday clothing. "
        "no side profile, no back view, no looking down, no covered face, no sunglasses, no hair/hand/prop blocking the face. "
        "no multi-view, no contact sheet, no character sheet, no turnaround, no collage, no split panels, no before/after split. "
        "Show only this character, no product, no extra people, no pets, no text, no logo, no watermark."
    )


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
    asset_type = _reference_role_to_asset_type(fields.get("参考类型") or fields.get("资产类型"))
    return asset_type == "human"


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


def build_plan_generation_request(fields: Dict[str, Any], *, system_prompt: str = "") -> str:
    script = extract_text(fields.get("脚本内容")).strip()
    product_links = _extract_link_ids(fields.get("关联产品记录"))
    model_links = _extract_link_ids(fields.get("选择模特"))
    grid_count = _selected_grid_count(fields, default=DEFAULT_AI_PLAN_GRID_COUNT)
    grid_layout = grid_layout_for_count(grid_count)
    rules = extract_text(system_prompt).strip() or NINE_GRID_PLAN_SYSTEM_PROMPT
    return f"""
{rules}

【本次任务上下文】
- Product record ids: {", ".join(product_links) or "none"}
- Character / pet model record ids: {", ".join(model_links) or "none"}
- Environment image count: {len(_as_list(fields.get("环境图")))}
- Grid count: {grid_count}
- Grid layout: {grid_layout}

【完整脚本内容】
{script}
""".strip()


def build_plan_review_markdown(payload: Dict[str, Any]) -> str:
    lines = ["# 多图宫格方案审核稿"]
    analysis = payload.get("script_analysis") or {}
    lines.append(f"- 脚本类型：{extract_text(analysis.get('script_type')).strip()}")
    lines.append(f"- 核心冲突：{extract_text(analysis.get('core_conflict')).strip()}")
    for board in payload.get("boards") or []:
        lines.append("")
        lines.append(f"## Board {int(board.get('board_index') or 0):02d}｜{extract_text(board.get('time_range')).strip()}")
        lines.append(f"- 叙事任务：{extract_text(board.get('narrative_task')).strip()}")
        lines.append(f"- 衔接锚点：{extract_text(board.get('handoff_anchor')).strip()}")
        for cell in board.get("cells") or []:
            lines.append(f"- 第 {cell.get('cell_index')} 格：{cell.get('visual_node')}")
    return "\n".join(lines).strip()


def build_direct_markdown_review(payload: Dict[str, Any]) -> str:
    lines = ["# 多图宫格文档直拆审核稿"]
    product_prompt = extract_text(payload.get("product_reference_prompt")).strip()
    if product_prompt:
        lines.append("")
        lines.append("## 产品参考图提示词")
        lines.append(product_prompt)
    refs = _as_list((payload.get("reference_manifest") or {}).get("required_references"))
    if refs:
        lines.append("")
        lines.append("## 参考资产")
        for item in refs:
            lines.append(f"- {extract_text(item.get('role')).strip()}｜{extract_text(item.get('name')).strip()}")
    for board in payload.get("boards") or []:
        lines.append("")
        lines.append(f"## Board {int(board.get('board_index') or 0):02d}｜{extract_text(board.get('time_range')).strip()}")
        lines.append(f"- 宫格图片提示词 chars：{len(extract_text(board.get('image_prompt')))}")
        lines.append(f"- 图生视频提示词 chars：{len(extract_text(board.get('video_prompt')))}")
        cells = _as_list(board.get("cells"))
        if cells:
            lines.append(f"- Cell 摘要数：{len(cells)}")
    return "\n".join(lines).strip()


def _reference_manifest_items(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    manifest = payload.get("reference_manifest") if isinstance(payload, dict) else {}
    items = _as_list((manifest or {}).get("required_references")) if isinstance(manifest, dict) else []
    manifest_items = [item for item in items if isinstance(item, dict)]
    analysis = payload.get("script_analysis") if isinstance(payload, dict) else {}
    if not isinstance(analysis, dict):
        return manifest_items
    fallback_items: List[Dict[str, Any]] = []
    for name in _as_list(analysis.get("characters")):
        fallback_items.append({"role": "human", "name": name, "purpose": "lock character identity"})
    for name in _as_list(analysis.get("pets")):
        fallback_items.append({"role": "pet", "name": name, "purpose": "lock pet identity"})
    environment = extract_text(analysis.get("environment")).strip()
    if environment:
        fallback_items.append({"role": "environment", "name": environment, "purpose": "lock empty scene layout"})
    if not manifest_items:
        return fallback_items

    merged = list(manifest_items)
    for asset_type in ("human", "pet", "environment"):
        existing_count = sum(
            1 for item in manifest_items
            if _reference_role_to_asset_type(item.get("role") or item.get("asset_type")) == asset_type
        )
        fallback_for_type = [
            item for item in fallback_items
            if _reference_role_to_asset_type(item.get("role") or item.get("asset_type")) == asset_type
        ]
        if existing_count < len(fallback_for_type):
            merged.extend(fallback_for_type[existing_count:])
    return merged


def build_reference_asset_records(
    parent_fields: Dict[str, Any],
    payload: Dict[str, Any],
    *,
    parent_record_id: str,
    batch_id: str,
) -> List[Dict[str, Dict[str, Any]]]:
    records = []
    seen: Dict[str, int] = {}
    task_name = extract_text(parent_fields.get("任务名称")).strip() or f"宫格任务-{parent_record_id[-6:]}"
    default_people_source = _field_with_default(parent_fields, "人物/宠物默认来源", REFERENCE_SOURCE_AI)
    environment_source = _field_with_default(parent_fields, "环境图来源", REFERENCE_SOURCE_AI)
    for raw in _reference_manifest_items(payload):
        asset_type = _reference_role_to_asset_type(raw.get("role") or raw.get("asset_type"))
        if asset_type == "product":
            continue
        if asset_type not in {"human", "pet", "environment"}:
            continue
        name = extract_text(raw.get("name") or raw.get("asset_name")).strip() or asset_type
        base_asset_id = _slug_asset_id(name, f"{asset_type}_{len(records) + 1}")
        count = seen.get(base_asset_id, 0) + 1
        seen[base_asset_id] = count
        asset_id = base_asset_id if count == 1 else f"{base_asset_id}_{count}"
        source = environment_source if asset_type == "environment" else default_people_source
        if asset_type == "environment" and source not in {REFERENCE_SOURCE_AI, REFERENCE_SOURCE_MANUAL}:
            source = REFERENCE_SOURCE_AI
        generation_status = "待生成" if source == REFERENCE_SOURCE_AI else "不触发"
        fields = {
            "记录类型": ASSET_RECORD_TYPE,
            "任务名称": f"{task_name}-{asset_id}",
            "父任务记录ID": parent_record_id,
            "批次ID": batch_id,
            "关联产品记录": _extract_link_ids(parent_fields.get("关联产品记录")),
            "资产ID": asset_id,
            "资产类型": asset_type,
            "资产名称": name,
            "资产角色说明": extract_text(raw.get("purpose")).strip(),
            "参考提示词": (
                extract_text(raw.get("prompt")).strip()
                if raw.get("direct_prompt")
                else build_reference_asset_prompt({
                    "asset_type": asset_type,
                    "asset_name": name,
                    "purpose": extract_text(raw.get("purpose")).strip(),
                })
            ),
            "参考图来源": source,
            "参考图AI供应商": _field_with_default(parent_fields, "参考图AI供应商", DEFAULT_IMAGE_PROVIDER),
            "参考图AI模型": _field_with_default(parent_fields, "参考图AI模型", DEFAULT_IMAGE_MODEL),
            "参考图AI参数JSON": extract_text(parent_fields.get("参考图AI参数JSON")).strip(),
            "参考图画面尺寸": _field_with_default(parent_fields, "参考图画面尺寸", DEFAULT_IMAGE_SIZE),
            "参考图画面比例": _field_with_default(parent_fields, "参考图画面比例", DEFAULT_ASPECT_RATIO),
            "参考图生成状态": generation_status,
            "参考图审核状态": "待确认",
            "参考图操作": "不触发",
            "错误信息": "",
        }
        records.append({"fields": fields})
    return records


def build_child_board_records(
    parent_fields: Dict[str, Any],
    payload: Dict[str, Any],
    *,
    parent_record_id: str,
    batch_id: str,
    await_reference_assets: bool = False,
) -> List[Dict[str, Dict[str, Any]]]:
    records = []
    boards = payload.get("boards") or []
    total = len(boards)
    task_name = extract_text(parent_fields.get("任务名称")).strip() or f"宫格任务-{parent_record_id[-6:]}"
    for board in boards:
        no = int(board.get("board_index") or len(records) + 1)
        grid_count = int(board.get("grid_count") or payload.get("grid_count") or _cell_count_for_board(board) or DEFAULT_AI_PLAN_GRID_COUNT)
        grid_layout = extract_text(board.get("grid_layout") or payload.get("grid_layout")).strip() or grid_layout_for_count(grid_count)
        video_prompt = (
            extract_text(board.get("video_prompt")).strip()
            if board.get("direct_prompt")
            else build_board_video_prompt_for_record(parent_fields, board)
        )
        fields = {
            "记录类型": "Board分段",
            "任务名称": f"{task_name}-Board{no:02d}",
            "父任务记录ID": parent_record_id,
            "批次ID": batch_id,
            "关联产品记录": _extract_link_ids(parent_fields.get("关联产品记录")),
            "选择模特": _extract_link_ids(parent_fields.get("选择模特")),
            "总Board数": total,
            "Board编号": no,
            "宫格数量": grid_count_label(grid_count),
            "宫格布局": grid_layout,
            "Time Range": extract_text(board.get("time_range")).strip(),
            "叙事任务": extract_text(board.get("narrative_task")).strip(),
            "起始画面": extract_text(board.get("start_frame")).strip(),
            "结束画面": extract_text(board.get("end_frame")).strip(),
            "衔接锚点": extract_text(board.get("handoff_anchor")).strip(),
            "宫格摘要JSON": compact_json(board.get("cells") or [], 10000),
            "九格摘要JSON": compact_json(board.get("cells") or [], 10000),
            "审核状态": "待确认",
            "宫格图片提示词": extract_text(board.get("image_prompt")).strip(),
            "九宫格图片提示词": extract_text(board.get("image_prompt")).strip(),
            "图片AI供应商": _field_with_default(parent_fields, "图片AI供应商", DEFAULT_IMAGE_PROVIDER),
            "图片AI模型": _field_with_default(parent_fields, "图片AI模型", DEFAULT_IMAGE_MODEL),
            "图片AI参数JSON": extract_text(parent_fields.get("图片AI参数JSON")).strip(),
            "图片画面尺寸": DEFAULT_IMAGE_SIZE,
            "图片画面比例": DEFAULT_ASPECT_RATIO,
            "图片生成状态": "不触发" if await_reference_assets else "待生成",
            "视频提示词": video_prompt,
            "视频生成模型": (
                _usable_model_choice(parent_fields.get("视频生成模型"))
                or DEFAULT_VIDEO_MODEL
            ),
            "视频AI参数JSON": extract_text(parent_fields.get("视频AI参数JSON")).strip(),
            "视频画面尺寸": DEFAULT_VIDEO_SIZE,
            "视频画面比例": DEFAULT_ASPECT_RATIO,
            "视频生成状态": "不触发",
            "错误信息": "",
        }
        records.append({"fields": fields})
    return records


def apply_nine_grid_reference_default_models(token: str, records: List[Dict[str, Dict[str, Any]]]) -> List[Dict[str, Dict[str, Any]]]:
    for record in records:
        record["fields"] = apply_task_default_to_fields(
            token,
            record.get("fields") or {},
            app_table=TASK_TABLES["nine_grid_video"],
            stage="参考图生成默认",
            model_field="参考图AI模型",
            size_field="参考图画面尺寸",
            ratio_field="参考图画面比例",
            params_field="参考图AI参数JSON",
            placeholder_values=(DEFAULT_IMAGE_MODEL,),
        )
    return records


def apply_nine_grid_board_default_models(token: str, records: List[Dict[str, Dict[str, Any]]]) -> List[Dict[str, Dict[str, Any]]]:
    for record in records:
        fields = record.get("fields") or {}
        fields = apply_task_default_to_fields(
            token,
            fields,
            app_table=TASK_TABLES["nine_grid_video"],
            stage="宫格图片生成默认",
            model_field="图片AI模型",
            size_field="图片画面尺寸",
            ratio_field="图片画面比例",
            params_field="图片AI参数JSON",
            placeholder_values=(DEFAULT_IMAGE_MODEL,),
        )
        fields = apply_task_default_to_fields(
            token,
            fields,
            app_table=TASK_TABLES["nine_grid_video"],
            stage="宫格视频生成默认",
            model_field="视频生成模型",
            size_field="视频画面尺寸",
            ratio_field="视频画面比例",
            params_field="视频AI参数JSON",
            placeholder_values=(DEFAULT_VIDEO_MODEL,),
        )
        record["fields"] = fields
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


def list_reference_asset_records(token: str, parent_record_id: str) -> List[Dict[str, Any]]:
    records = []
    for rec in safe_list_records(token, TABLE_NINE_GRID_VIDEO):
        fields = rec.get("fields") or {}
        if extract_text(fields.get("父任务记录ID")).strip() != parent_record_id:
            continue
        if extract_text(fields.get("记录类型")).strip() != ASSET_RECORD_TYPE:
            continue
        records.append(rec)
    return records


def _asset_has_approved_reference(token: str, fields: Dict[str, Any]) -> bool:
    if not reference_review_passed(fields.get("参考图审核状态")):
        return False
    return bool(_asset_reference_file_token(token, fields))


def reference_review_passed(value: Any) -> bool:
    return extract_text(value).strip() in REFERENCE_REVIEW_PASSED_STATUSES


def advance_boards_after_reference_approval(token: str, parent_record_id: str) -> Dict[str, Any]:
    records = safe_list_records(token, TABLE_NINE_GRID_VIDEO)
    asset_records: List[Dict[str, Any]] = []
    board_records: List[Dict[str, Any]] = []
    for rec in records:
        fields = rec.get("fields") or {}
        if extract_text(fields.get("父任务记录ID")).strip() != parent_record_id:
            continue
        record_type = extract_text(fields.get("记录类型")).strip()
        if record_type == ASSET_RECORD_TYPE:
            asset_records.append(rec)
        elif record_type == "Board分段":
            board_records.append(rec)

    if not asset_records:
        return {
            "status": "no_reference_assets",
            "parent_record_id": parent_record_id,
            "asset_count": 0,
            "board_count": len(board_records),
            "advanced_boards": 0,
        }

    approved_assets = [
        rec for rec in asset_records
        if _asset_has_approved_reference(token, rec.get("fields") or {})
    ]
    if len(approved_assets) != len(asset_records):
        return {
            "status": "waiting_for_reference_approval",
            "parent_record_id": parent_record_id,
            "asset_count": len(asset_records),
            "approved_asset_count": len(approved_assets),
            "board_count": len(board_records),
            "advanced_boards": 0,
        }

    advanced = 0
    for rec in board_records:
        fields = rec.get("fields") or {}
        if extract_text(fields.get("图片生成状态")).strip() != "不触发":
            continue
        safe_update_record(
            token,
            TABLE_NINE_GRID_VIDEO,
            rec["record_id"],
            filter_existing_fields(token, TABLE_NINE_GRID_VIDEO, {
                "图片生成状态": "待生成",
                "错误信息": "",
            }),
        )
        advanced += 1

    return {
        "status": "advanced" if advanced else "no_boards_to_advance",
        "parent_record_id": parent_record_id,
        "asset_count": len(asset_records),
        "approved_asset_count": len(approved_assets),
        "board_count": len(board_records),
        "advanced_boards": advanced,
    }


def advance_boards_for_reference_asset(record_id: str, *, dry_run: bool = False) -> Dict[str, Any]:
    ensure_nine_grid_table()
    token = get_feishu_token()
    fields = safe_get_record(token, TABLE_NINE_GRID_VIDEO, record_id)
    if extract_text(fields.get("记录类型")).strip() != ASSET_RECORD_TYPE:
        raise ValueError("只有参考资产记录可以推进宫格图片生成")
    parent_record_id = extract_text(fields.get("父任务记录ID")).strip()
    if not parent_record_id:
        raise ValueError("参考资产缺少父任务记录ID")
    if dry_run:
        return {"status": "dry_run_ready", "record_id": record_id, "parent_record_id": parent_record_id}
    summary = advance_boards_after_reference_approval(token, parent_record_id)
    safe_update_record(
        token,
        TABLE_NINE_GRID_VIDEO,
        record_id,
        filter_existing_fields(token, TABLE_NINE_GRID_VIDEO, {
            "参考图审核状态": REFERENCE_REVIEW_HANDLED_STATUS,
            "参考图操作": "不触发",
            "错误信息": "",
        }),
    )
    summary["record_id"] = record_id
    return summary


def maybe_auto_approve_reference_asset(token: str, record_id: str, fields: Dict[str, Any], *, file_token: str) -> Dict[str, Any]:
    if not auto_review_enabled(token, stage_name=AUTO_REVIEW_STAGE_NAME):
        return {"status": "disabled"}
    if not file_token:
        return {"status": "skipped", "reason": "missing_file_token"}
    if extract_text(fields.get("参考图操作")).strip() == "重新生成参考图":
        return {"status": "manual_regeneration"}
    parent_record_id = extract_text(fields.get("父任务记录ID")).strip()
    if not parent_record_id:
        return {"status": "skipped", "reason": "missing_parent_record_id"}
    safe_update_record(
        token,
        TABLE_NINE_GRID_VIDEO,
        record_id,
        filter_existing_fields(token, TABLE_NINE_GRID_VIDEO, {
            "参考图审核状态": REFERENCE_REVIEW_HANDLED_STATUS,
            "参考图操作": "不触发",
            "错误信息": "",
        }),
    )
    advance_summary = advance_boards_after_reference_approval(token, parent_record_id)
    return {"status": "auto_approved", "advance": advance_summary}


def upsert_reference_asset_records(token: str, parent_record_id: str, records: List[Dict[str, Dict[str, Any]]]) -> Dict[str, int]:
    existing = {
        extract_text((rec.get("fields") or {}).get("资产ID")).strip(): rec
        for rec in list_reference_asset_records(token, parent_record_id)
        if extract_text((rec.get("fields") or {}).get("资产ID")).strip()
    }
    created = 0
    updated = 0
    for item in records:
        fields = dict(item["fields"])
        asset_id = extract_text(fields.get("资产ID")).strip()
        current = existing.get(asset_id)
        if not current:
            create_records(token, TABLE_NINE_GRID_VIDEO, [{"fields": filter_existing_fields(token, TABLE_NINE_GRID_VIDEO, fields)}])
            created += 1
            continue
        current_fields = current.get("fields") or {}
        if _attachment_token(current_fields.get("参考图")) or extract_text(current_fields.get("参考图file_token")).strip():
            fields.pop("参考图生成状态", None)
            fields.pop("参考图审核状态", None)
        safe_update_record(
            token,
            TABLE_NINE_GRID_VIDEO,
            current["record_id"],
            filter_existing_fields(token, TABLE_NINE_GRID_VIDEO, fields),
        )
        updated += 1
    return {"created": created, "updated": updated}


def cleanup_child_boards(token: str, parent_record_id: str) -> int:
    deleted = 0
    for rec in safe_list_records(token, TABLE_NINE_GRID_VIDEO):
        fields = rec.get("fields") or {}
        if extract_text(fields.get("父任务记录ID")).strip() != parent_record_id:
            continue
        if extract_text(fields.get("记录类型")).strip() != "Board分段":
            continue
        safe_request(
            "delete",
            f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_NINE_GRID_VIDEO}/records/{rec['record_id']}",
            headers=feishu_headers(token),
            timeout=30,
            max_attempts=3,
            acceptable_codes=(0,),
        )
        deleted += 1
    return deleted


def _stage_config_records(token: str) -> List[Dict[str, Any]]:
    return safe_list_records(token, TABLE_CONFIG)


def get_config_record(stage_name: str, *, default_model: str, default_api_base: str, default_size: str = "") -> Tuple[str, Dict[str, str]]:
    token = get_feishu_token()
    records = safe_list_records(token, TABLE_CONFIG)
    record_id = ""
    cfg: Dict[str, str] = {}
    for candidate_stage in (stage_name, *STAGE_NAME_ALIASES.get(stage_name, ())):
        record_id, cfg = load_stage_config_fields(
            token,
            candidate_stage,
            default_model=default_model,
            default_api_base=default_api_base,
            default_size=default_size,
            default_aspect_ratio=DEFAULT_ASPECT_RATIO,
            require_api_key=False,
        )
        if record_id:
            break
    if record_id:
        if not cfg["api_key"]:
            for fallback_stage in SECRET_FALLBACK_STAGES.get(stage_name, ()):
                for fallback_rec in records:
                    fallback_fields = fallback_rec.get("fields") or {}
                    if extract_text(fallback_fields.get("环节")).strip() != fallback_stage:
                        continue
                    fallback_key = extract_text(fallback_fields.get("API Key")).strip()
                    if not fallback_key:
                        continue
                    cfg["api_key"] = fallback_key
                    if not cfg["api_base"]:
                        cfg["api_base"] = extract_text(fallback_fields.get("API 代理地址")).strip()
                    break
                if cfg["api_key"]:
                    break
        return record_id, cfg
    return "", {
        "provider": "",
        "capability": "",
        "task_type": "",
        "model": default_model,
        "api_key": "",
        "api_base": default_api_base,
        "size": default_size,
        "call_type": "",
        "prompt": "",
    }


def _route_for_prefixed_fields(
    fields: Dict[str, Any],
    prefix: str,
    cfg: Dict[str, str],
    *,
    capability: str,
    task_type: str,
    default_provider: str,
    default_model: str,
    config_records: Optional[Iterable[Dict[str, Any]]] = None,
) -> ai_routing.AiRoute:
    route_fields = _prefixed_route_fields(fields, prefix, default_provider=default_provider, default_model=default_model)
    config = dict(cfg)
    config["provider"] = extract_text(config.get("provider")).strip() or default_provider
    config["capability"] = capability
    config["task_type"] = task_type
    route = ai_routing.route_from_record(
        {
            ai_routing.AI_PROVIDER_FIELD: route_fields["provider"],
            ai_routing.AI_CAPABILITY_FIELD: capability,
            ai_routing.AI_TASK_TYPE_FIELD: task_type,
            ai_routing.AI_MODEL_FIELD: route_fields["model"],
            ai_routing.AI_PARAMS_FIELD: route_fields["params"],
        },
        config,
        config_records=config_records,
    )
    return route


def _input_mode(fields: Dict[str, Any]) -> str:
    raw = extract_text(fields.get("输入模式")).strip()
    if raw == INPUT_MODE_LEGACY_AI_PLAN:
        return INPUT_MODE_LEGACY_AI_PLAN
    return INPUT_MODE_DIRECT_DOC


def split_nine_grid_direct_markdown(
    token: str,
    record_id: str,
    fields: Dict[str, Any],
    *,
    dry_run: bool = False,
) -> Dict[str, Any]:
    script = extract_text(fields.get("脚本内容")).strip()
    requested_grid_count = _selected_grid_count(fields, default=0)
    payload = parse_direct_markdown_document(script, requested_grid_count=requested_grid_count)
    batch_id = f"NINEGRID-{time.strftime('%Y%m%d%H%M%S')}-{record_id[-6:]}"
    asset_records = apply_nine_grid_reference_default_models(
        token,
        build_reference_asset_records(fields, payload, parent_record_id=record_id, batch_id=batch_id),
    )
    child_records = apply_nine_grid_board_default_models(
        token,
        build_child_board_records(
            fields,
            payload,
            parent_record_id=record_id,
            batch_id=batch_id,
            await_reference_assets=bool(asset_records),
        ),
    )
    summary = {
        "record_id": record_id,
        "dry_run": dry_run,
        "status": "dry_run_ready" if dry_run else "success",
        "input_mode": INPUT_MODE_DIRECT_DOC,
        "batch_id": batch_id,
        "grid_count": payload.get("grid_count"),
        "grid_layout": payload.get("grid_layout"),
        "reference_asset_count": len(asset_records),
        "board_count": len(child_records),
    }
    if dry_run:
        return summary

    asset_upsert = upsert_reference_asset_records(token, record_id, asset_records)
    deleted = cleanup_child_boards(token, record_id)
    create_records(token, TABLE_NINE_GRID_VIDEO, [
        {"fields": filter_existing_fields(token, TABLE_NINE_GRID_VIDEO, item["fields"])}
        for item in child_records
    ])
    safe_update_record(token, TABLE_NINE_GRID_VIDEO, record_id, filter_existing_fields(token, TABLE_NINE_GRID_VIDEO, {
        "记录类型": "母任务",
        "输入模式": INPUT_MODE_DIRECT_DOC,
        "宫格数量": grid_count_label(int(payload.get("grid_count") or DEFAULT_AI_PLAN_GRID_COUNT)),
        "宫格布局": extract_text(payload.get("grid_layout")).strip(),
        "方案生成状态": "成功",
        "方案JSON": compact_json(payload, 20000),
        "方案Markdown": build_direct_markdown_review(payload)[:20000],
        "总Board数": len(child_records),
        "批次ID": batch_id,
        "错误信息": "",
    }))
    summary.update({
        "reference_assets": asset_upsert,
        "deleted_children": deleted,
    })
    return summary


def split_nine_grid_plan(record_id: str, *, dry_run: bool = False, raw_model_output: Any = None) -> Dict[str, Any]:
    ensure_nine_grid_table()
    token = get_feishu_token()
    fields = safe_get_record(token, TABLE_NINE_GRID_VIDEO, record_id)
    script = extract_text(fields.get("脚本内容")).strip()
    if not script:
        raise ValueError("脚本内容为空")
    if _input_mode(fields) == INPUT_MODE_DIRECT_DOC:
        return split_nine_grid_direct_markdown(token, record_id, fields, dry_run=dry_run)
    _, cfg = get_config_record(PLAN_STAGE_NAME, default_model="gemini-3.1-pro-preview", default_api_base="https://aihubmix.com/gemini")
    prompt = build_plan_generation_request(fields, system_prompt=cfg.get("prompt") or NINE_GRID_PLAN_SYSTEM_PROMPT)
    config_records = _stage_config_records(token)
    route = _route_for_prefixed_fields(
        fields,
        "方案",
        cfg,
        capability="文本",
        task_type="多图宫格方案生成",
        default_provider=DEFAULT_TEXT_PROVIDER,
        default_model=DEFAULT_TEXT_MODEL,
        config_records=config_records,
    )
    summary = {
        "record_id": record_id,
        "dry_run": dry_run,
        "prompt_chars": len(prompt),
        "route": ai_routing.build_dry_run_summary(route, prompt),
    }
    if dry_run:
        summary["status"] = "dry_run_ready"
        return summary

    if ai_routing.unified_route_dry_run_only(config_records):
        summary["status"] = "unified_ai_dry_run_ready"
        return summary

    safe_update_record(token, TABLE_NINE_GRID_VIDEO, record_id, filter_existing_fields(token, TABLE_NINE_GRID_VIDEO, {
        "方案生成状态": "生成中",
        "错误信息": "",
    }))
    if raw_model_output is None:
        result = with_retry(lambda: ai_routing.call_text_model(route, prompt), max_attempts=3, label="nine grid plan generation")
        raw_model_output = result.text
    requested_grid_count = _selected_grid_count(fields, default=DEFAULT_AI_PLAN_GRID_COUNT)
    payload = normalize_nine_grid_plan_payload(raw_model_output, requested_grid_count=requested_grid_count)
    batch_id = f"NINEGRID-{time.strftime('%Y%m%d%H%M%S')}-{record_id[-6:]}"
    asset_records = apply_nine_grid_reference_default_models(
        token,
        build_reference_asset_records(fields, payload, parent_record_id=record_id, batch_id=batch_id),
    )
    asset_upsert = upsert_reference_asset_records(token, record_id, asset_records)
    child_records = apply_nine_grid_board_default_models(
        token,
        build_child_board_records(
            fields,
            payload,
            parent_record_id=record_id,
            batch_id=batch_id,
            await_reference_assets=bool(asset_records),
        ),
    )
    deleted = cleanup_child_boards(token, record_id)
    create_records(token, TABLE_NINE_GRID_VIDEO, [
        {"fields": filter_existing_fields(token, TABLE_NINE_GRID_VIDEO, item["fields"])}
        for item in child_records
    ])
    safe_update_record(token, TABLE_NINE_GRID_VIDEO, record_id, filter_existing_fields(token, TABLE_NINE_GRID_VIDEO, {
        "记录类型": "母任务",
        "宫格数量": grid_count_label(int(payload.get("grid_count") or requested_grid_count)),
        "宫格布局": extract_text(payload.get("grid_layout")).strip(),
        "方案生成状态": "成功",
        "方案JSON": compact_json(payload, 20000),
        "方案Markdown": build_plan_review_markdown(payload)[:20000],
        "总Board数": len(child_records),
        "批次ID": batch_id,
        "错误信息": "",
    }))
    summary.update({
        "status": "success",
        "batch_id": batch_id,
        "reference_assets": asset_upsert,
        "grid_count": payload.get("grid_count"),
        "grid_layout": payload.get("grid_layout"),
        "reference_asset_count": len(asset_records),
        "deleted_children": deleted,
        "board_count": len(child_records),
    })
    return summary


def _attachment_token(value: Any) -> str:
    tokens = _attachment_tokens(value)
    return tokens[-1] if tokens else ""


def _downloaded_path(downloaded: Any, fallback: Path) -> str:
    if isinstance(downloaded, (str, os.PathLike)):
        return str(downloaded)
    return str(fallback)


def _first_text(fields: Dict[str, Any], names: Iterable[str]) -> str:
    for name in names:
        value = extract_text(fields.get(name)).strip()
        if value:
            return value
    return ""


def _product_reference_items(
    token: str,
    parent_fields: Dict[str, Any],
    *,
    get_record_fn: Callable[[str, str, str], Dict[str, Any]] = safe_get_record,
) -> List[Dict[str, str]]:
    product_ids = _extract_link_ids(parent_fields.get("关联产品记录"))
    if not product_ids:
        return []
    product_fields = get_record_fn(token, TABLE_PRODUCT, product_ids[0])
    product_name = _first_text(product_fields, ["产品名称-zh", "产品名称-th", "产品", "产品名称", "产品名"])
    product_tokens = _attachment_tokens(product_fields.get("产品图片"))
    if not product_tokens:
        return []
    return [{"role": "product:1", "file_token": product_tokens[-1], "name": product_name or "selected product"}]


def first_product_reference_item(
    token: str,
    parent_fields: Dict[str, Any],
    *,
    get_record_fn: Optional[Callable[[str, str, str], Dict[str, Any]]] = None,
) -> Dict[str, str]:
    product_ids = _extract_link_ids(parent_fields.get("关联产品记录"))
    if not product_ids:
        raise ValueError("宫格视频生成缺少关联产品记录")
    get_record = get_record_fn or safe_get_record
    product_fields = get_record(token, TABLE_PRODUCT, product_ids[0])
    product_tokens = _attachment_tokens(product_fields.get("产品图片"))
    if not product_tokens:
        raise ValueError("产品记录缺少产品图片")
    product_name = _first_text(product_fields, ["产品名称-zh", "产品名称-th", "产品", "产品名称", "产品名"])
    return {"role": "product:1", "file_token": product_tokens[-1], "name": product_name or "selected product"}


def collect_nine_grid_video_product_reference(
    token: str,
    parent_fields: Dict[str, Any],
    task_dir: Path,
    *,
    product_item: Optional[Dict[str, str]] = None,
    download_fn: Callable[[str, str, str], Any] = safe_download_attachment,
    get_record_fn: Optional[Callable[[str, str, str], Dict[str, Any]]] = None,
) -> Dict[str, str]:
    item = product_item or first_product_reference_item(token, parent_fields, get_record_fn=get_record_fn)
    local_path = task_dir / "reference_product_1.png"
    downloaded = download_fn(token, item["file_token"], str(local_path))
    return {
        "role": item["role"],
        "path": _downloaded_path(downloaded, local_path),
        "file_token": item["file_token"],
        "name": item.get("name", ""),
        "type": "product",
    }


def collect_nine_grid_video_human_reference_items(
    token: str,
    parent_record_id: str,
    *,
    records: Optional[List[Dict[str, Any]]] = None,
    max_count: int = MAX_REFERENCE_IMAGES - 2,
    get_record_fn: Callable[[str, str, str], Dict[str, Any]] = safe_get_record,
) -> List[Dict[str, str]]:
    asset_records = records if records is not None else list_reference_asset_records(token, parent_record_id)
    selected: List[Dict[str, str]] = []
    for rec in asset_records:
        fields = rec.get("fields") or {}
        if extract_text(fields.get("记录类型")).strip() != ASSET_RECORD_TYPE:
            continue
        if extract_text(fields.get("父任务记录ID")).strip() != parent_record_id:
            continue
        if not reference_review_passed(fields.get("参考图审核状态")):
            continue
        if extract_text(fields.get("资产类型")).strip() != "human":
            continue
        asset_id = extract_text(fields.get("资产ID")).strip() or rec.get("record_id", "human")
        file_token = _asset_reference_file_token(token, fields, get_record_fn=get_record_fn)
        if not file_token:
            continue
        selected.append({
            "role": f"human:{asset_id}",
            "file_token": file_token,
            "name": extract_text(fields.get("资产名称")).strip(),
            "type": "human",
        })
        if len(selected) >= max_count:
            break
    return selected


def collect_nine_grid_video_human_references(
    token: str,
    parent_record_id: str,
    task_dir: Path,
    *,
    items: Optional[List[Dict[str, str]]] = None,
    download_fn: Callable[[str, str, str], Any] = safe_download_attachment,
    get_record_fn: Callable[[str, str, str], Dict[str, Any]] = safe_get_record,
) -> List[Dict[str, str]]:
    selected = items if items is not None else collect_nine_grid_video_human_reference_items(token, parent_record_id, get_record_fn=get_record_fn)
    refs: List[Dict[str, str]] = []
    for item in selected[:MAX_REFERENCE_IMAGES - 2]:
        safe_role = item["role"].replace(":", "_")
        local_path = task_dir / f"reference_{safe_role}.png"
        downloaded = download_fn(token, item["file_token"], str(local_path))
        refs.append({
            "role": item["role"],
            "path": _downloaded_path(downloaded, local_path),
            "file_token": item["file_token"],
            "name": item.get("name", ""),
            "type": "human",
        })
    return refs


def _asset_reference_file_token(
    token: str,
    fields: Dict[str, Any],
    *,
    get_record_fn: Callable[[str, str, str], Dict[str, Any]] = safe_get_record,
) -> str:
    direct_token = _attachment_token(fields.get("参考图")) or extract_text(fields.get("参考图file_token")).strip()
    if direct_token:
        return direct_token
    if extract_text(fields.get("参考图来源")).strip() != REFERENCE_SOURCE_MODEL_TABLE:
        return ""
    model_ids = _extract_link_ids(fields.get("选择模特"))
    if not model_ids:
        return ""
    model_fields = get_record_fn(token, TABLE_MODEL, model_ids[0])
    return _attachment_token(model_fields.get("模特照片"))


def collect_nine_grid_reference_images(
    token: str,
    parent_fields: Dict[str, Any],
    parent_record_id: str,
    task_dir: Path,
    *,
    records: Optional[List[Dict[str, Any]]] = None,
    max_count: int = MAX_REFERENCE_IMAGES,
    download_fn: Callable[[str, str, str], Any] = safe_download_attachment,
    get_record_fn: Callable[[str, str, str], Dict[str, Any]] = safe_get_record,
) -> List[Dict[str, str]]:
    selected: List[Dict[str, str]] = []
    selected.extend(_product_reference_items(token, parent_fields, get_record_fn=get_record_fn)[:1])
    asset_records = records if records is not None else list_reference_asset_records(token, parent_record_id)
    for rec in asset_records:
        fields = rec.get("fields") or {}
        if extract_text(fields.get("记录类型")).strip() != ASSET_RECORD_TYPE:
            continue
        if extract_text(fields.get("父任务记录ID")).strip() != parent_record_id:
            continue
        if not reference_review_passed(fields.get("参考图审核状态")):
            continue
        asset_type = extract_text(fields.get("资产类型")).strip() or "asset"
        asset_id = extract_text(fields.get("资产ID")).strip() or rec.get("record_id", "asset")
        file_token = _asset_reference_file_token(token, fields, get_record_fn=get_record_fn)
        if not file_token:
            continue
        selected.append({
            "role": f"{asset_type}:{asset_id}",
            "file_token": file_token,
            "name": extract_text(fields.get("资产名称")).strip(),
            "type": asset_type,
        })
    if len(selected) > max_count:
        raise ValueError(f"参考图数量超过上限：产品图 + 已审核参考资产共 {len(selected)} 张，当前最多可用 {max_count} 张")
    if not any(item["role"].startswith("environment:") for item in selected):
        raise ValueError("缺少已审核通过的环境参考资产")

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


def build_product_reference_lock_prompt(refs: List[Dict[str, str]]) -> str:
    product_refs = [ref for ref in refs if ref.get("role", "").startswith("product:")]
    if not product_refs:
        return ""
    roles = ", ".join(ref["role"] for ref in product_refs)
    names = ", ".join(ref.get("name", "") for ref in product_refs if ref.get("name"))
    name_line = f" Selected product name: {names}." if names else ""
    return (
        "PRODUCT REFERENCE LOCK:\n"
        f"- The selected product reference role(s) are {roles}.{name_line}\n"
        "- Treat product reference images as the highest-priority source for the product.\n"
        "- Preserve the exact bottle/package silhouette, trigger or cap shape, label color blocks, animal illustration/logo area, text placement, and size ratio from product:*.\n"
        "- Do not invent a generic spray bottle, do not replace the label, and do not use a different product package.\n"
        "- If the script text conflicts with product:* visual details, product:* wins."
    )


def ensure_nine_grid_record_current_generation(
    token: str,
    record_id: str,
    status_field: str,
    expected: str,
    task_field: str = "",
    task_id: str = "",
) -> None:
    latest = safe_get_record(token, TABLE_NINE_GRID_VIDEO, record_id)
    current = extract_text(latest.get(status_field)).strip()
    if current != expected:
        raise RuntimeError(f"记录状态已变更为 {current or '<empty>'}，停止写回，避免旧任务覆盖新结果")
    if task_field and task_id:
        current_task_id = extract_text(latest.get(task_field)).strip()
        if current_task_id != task_id:
            raise RuntimeError(f"{task_field} 已变更，停止写回，避免旧任务覆盖新结果")


def render_reference_asset(record_id: str, *, dry_run: bool = False) -> Dict[str, Any]:
    ensure_nine_grid_table()
    token = get_feishu_token()
    fields = safe_get_record(token, TABLE_NINE_GRID_VIDEO, record_id)
    fields = apply_task_default_to_record(
        token,
        TABLE_NINE_GRID_VIDEO,
        record_id,
        fields,
        app_table=TASK_TABLES["nine_grid_video"],
        stage="参考图生成默认",
        model_field="参考图AI模型",
        size_field="参考图画面尺寸",
        ratio_field="参考图画面比例",
        params_field="参考图AI参数JSON",
        field_filter=filter_existing_fields,
    )
    if extract_text(fields.get("记录类型")).strip() != ASSET_RECORD_TYPE:
        raise ValueError("只有参考资产记录可以生成参考图")
    source = extract_text(fields.get("参考图来源")).strip() or REFERENCE_SOURCE_AI
    if source != REFERENCE_SOURCE_AI:
        raise ValueError("只有参考图来源=AI自动生成 的资产可以自动生成参考图")
    raw_prompt = extract_text(fields.get("参考提示词")).strip()
    if not raw_prompt:
        raise ValueError("参考提示词为空")
    current_status = extract_text(fields.get("参考图生成状态")).strip()
    raw_existing_task_id = extract_text(fields.get("参考图任务ID")).strip() if current_status == "生成中" else ""
    prompt = build_reference_image_generation_prompt(fields)
    _, cfg = get_config_record(REFERENCE_STAGE_NAME, default_model="gpt-image-2", default_api_base="https://otuapi.com", default_size=DEFAULT_IMAGE_SIZE)
    params = {
        "size": DEFAULT_IMAGE_SIZE,
        "aspect_ratio": DEFAULT_ASPECT_RATIO,
    }
    params.update(_parse_params(extract_text(fields.get("参考图AI参数JSON")).strip()))
    params["size"] = extract_text(fields.get("参考图画面尺寸")).strip() or params.get("size") or DEFAULT_IMAGE_SIZE
    params["aspect_ratio"] = extract_text(fields.get("参考图画面比例")).strip() or params.get("aspect_ratio") or DEFAULT_ASPECT_RATIO
    route = _route_for_prefixed_fields(
        fields,
        "参考图",
        cfg,
        capability="图片",
        task_type="文生图",
        default_provider=DEFAULT_IMAGE_PROVIDER,
        default_model=DEFAULT_IMAGE_MODEL,
        config_records=_stage_config_records(token),
    )
    route.params.update(params)
    execution = image_execution_params(
        route,
        size=params.get("size") or DEFAULT_IMAGE_SIZE,
        aspect_ratio=params.get("aspect_ratio") or DEFAULT_ASPECT_RATIO,
    )
    original_size = params.get("size") or DEFAULT_IMAGE_SIZE
    params.update({"size": execution["size"], "aspect_ratio": execution["aspect_ratio"]})
    route.params.update(params)
    existing_task_id = raw_existing_task_id if route.provider == "OTU" and original_size == execution["size"] else ""
    summary = {
        "record_id": record_id,
        "dry_run": dry_run,
        "prompt_chars": len(prompt),
        "route": ai_routing.build_media_request_summary(route, prompt, reference_count=0),
    }
    if dry_run:
        summary["status"] = "dry_run_ready"
        return summary
    if ai_routing.unified_route_dry_run_only(_stage_config_records(token)):
        summary["status"] = "unified_ai_dry_run_ready"
        return summary
    work_dir = ensure_work_dir(record_id)
    model_name = execution["model"]
    out_path = str(work_dir / f"{record_id}_reference.png")
    if existing_task_id:
        safe_update_record(token, TABLE_NINE_GRID_VIDEO, record_id, filter_existing_fields(token, TABLE_NINE_GRID_VIDEO, {
            **_image_param_fields("参考图", params),
            "参考图任务ID": existing_task_id,
            "参考图生成状态": "生成中",
            "参考图错误信息": f"恢复轮询已有 OTU 参考图任务。task_id={existing_task_id}",
            "错误信息": "",
        }))
    else:
        safe_update_record(token, TABLE_NINE_GRID_VIDEO, record_id, filter_existing_fields(token, TABLE_NINE_GRID_VIDEO, {
            **_image_param_fields("参考图", params),
            "参考图": [],
            "参考图file_token": "",
            "参考图本地路径": "",
            "参考图任务ID": "",
            "参考图错误信息": "",
            "参考图生成时间": None,
            "参考图生成状态": "生成中",
            "错误信息": "",
        }))
    task_id = ""
    if route.provider == "OTU":
        model_name = execution["model"]
        if existing_task_id:
            task_id = existing_task_id
            submit_body = {"id": task_id}
        else:
            task_id, submit_body = submit_otu_image_task(
                {"api_key": route.api_key, "api_base": route.api_base or DEFAULT_OTU_API_BASE, "model": model_name},
                prompt,
                input_mode="text-to-image",
                metadata={
                    "urls": [],
                    "reference_roles": [],
                    "size": params.get("size") or DEFAULT_IMAGE_SIZE,
                    "aspectRatio": params.get("aspect_ratio") or DEFAULT_ASPECT_RATIO,
                    "aspect_ratio": params.get("aspect_ratio") or DEFAULT_ASPECT_RATIO,
                },
                size=params.get("size") or DEFAULT_IMAGE_SIZE,
                aspect_ratio=params.get("aspect_ratio") or DEFAULT_ASPECT_RATIO,
            )
            if task_id:
                safe_update_record(token, TABLE_NINE_GRID_VIDEO, record_id, filter_existing_fields(token, TABLE_NINE_GRID_VIDEO, {
                    "参考图任务ID": task_id,
                    "参考图错误信息": f"已提交参考图任务，正在轮询。task_id={task_id}",
                }))
        result = submit_body if not task_id else poll_otu_image_task(
            {"api_key": route.api_key, "api_base": route.api_base or DEFAULT_OTU_API_BASE, "model": model_name},
            task_id,
        )
        result_url = extract_otu_result_url(result) or extract_otu_result_url(submit_body)
        if not result_url:
            raise RuntimeError("参考图任务完成但未返回图片地址")
        download_otu_image_result(result_url, out_path)
    elif route.provider == "Aitgenne":
        result = submit_aitgenne_image_generation(
            {"api_key": route.api_key, "api_base": route.api_base or DEFAULT_AITGENNE_API_BASE, "model": model_name},
            prompt,
            size=params.get("size") or DEFAULT_IMAGE_SIZE,
            aspect_ratio=params.get("aspect_ratio") or DEFAULT_ASPECT_RATIO,
        )
        save_aitgenne_image_result(result, out_path)
    else:
        raise NotImplementedError(f"当前参考图真实提交暂不支持供应商：{route.provider}")
    file_token = with_retry(
        lambda: upload_image_to_feishu(token, out_path, f"{record_id}_reference.png"),
        max_attempts=3,
        label="upload grid reference image",
    )
    safe_update_record(token, TABLE_NINE_GRID_VIDEO, record_id, filter_existing_fields(token, TABLE_NINE_GRID_VIDEO, {
        **_image_param_fields("参考图", params),
        "参考图": [{"file_token": file_token, "name": Path(out_path).name}],
        "参考图file_token": file_token,
        "参考图本地路径": out_path,
        "参考图任务ID": task_id,
        "参考图生成状态": "成功",
        "参考图审核状态": "待确认",
        "参考图操作": "不触发",
        "参考图生成时间": int(time.time() * 1000),
        "参考图错误信息": "",
        "错误信息": "",
    }))
    auto_review_summary = maybe_auto_approve_reference_asset(token, record_id, fields, file_token=file_token)
    summary.update({"status": "success", "task_id": task_id, "file_token": file_token, "output_path": out_path})
    summary["auto_review"] = auto_review_summary
    return summary


def render_nine_grid_image(record_id: str, *, dry_run: bool = False) -> Dict[str, Any]:
    ensure_nine_grid_table()
    token = get_feishu_token()
    fields = safe_get_record(token, TABLE_NINE_GRID_VIDEO, record_id)
    fields = apply_task_default_to_record(
        token,
        TABLE_NINE_GRID_VIDEO,
        record_id,
        fields,
        app_table=TASK_TABLES["nine_grid_video"],
        stage="宫格图片生成默认",
        model_field="图片AI模型",
        size_field="图片画面尺寸",
        ratio_field="图片画面比例",
        params_field="图片AI参数JSON",
        field_filter=filter_existing_fields,
    )
    parent_record_id = extract_text(fields.get("父任务记录ID")).strip()
    if not parent_record_id:
        raise ValueError("Board分段缺少父任务记录ID")
    parent_fields = safe_get_record(token, TABLE_NINE_GRID_VIDEO, parent_record_id)
    prompt = extract_text(_field_value(fields, "宫格图片提示词", "九宫格图片提示词")).strip()
    if not prompt:
        raise ValueError("宫格图片提示词为空")
    current_status = extract_text(fields.get("图片生成状态")).strip()
    raw_existing_task_id = extract_text(fields.get("图片任务ID")).strip() if current_status == "生成中" else ""
    _, cfg = get_config_record(IMAGE_STAGE_NAME, default_model="gpt-image-2", default_api_base="https://otuapi.com", default_size=DEFAULT_IMAGE_SIZE)
    json_params = _parse_params(extract_text(fields.get("图片AI参数JSON")).strip())
    params = {
        **json_params,
        "size": extract_text(fields.get("图片画面尺寸")).strip() or json_params.get("size") or cfg.get("size") or DEFAULT_IMAGE_SIZE,
        "aspect_ratio": extract_text(fields.get("图片画面比例")).strip() or json_params.get("aspect_ratio") or cfg.get("aspect_ratio") or DEFAULT_ASPECT_RATIO,
    }
    route = _route_for_prefixed_fields(
        fields,
        "图片",
        cfg,
        capability="图片",
        task_type="图生图/参考图重绘",
        default_provider=DEFAULT_IMAGE_PROVIDER,
        default_model=DEFAULT_IMAGE_MODEL,
        config_records=_stage_config_records(token),
    )
    route.params.update(params)
    execution = image_execution_params(
        route,
        size=params.get("size") or DEFAULT_IMAGE_SIZE,
        aspect_ratio=params.get("aspect_ratio") or DEFAULT_ASPECT_RATIO,
    )
    original_size = params.get("size") or DEFAULT_IMAGE_SIZE
    params.update({"size": execution["size"], "aspect_ratio": execution["aspect_ratio"]})
    route.params.update(params)
    existing_task_id = raw_existing_task_id if route.provider == "OTU" and original_size == execution["size"] else ""
    summary = {
        "record_id": record_id,
        "dry_run": dry_run,
        "route": ai_routing.build_media_request_summary(route, prompt, reference_count=1),
        "prompt_chars": len(prompt),
    }
    if dry_run:
        summary["status"] = "dry_run_ready"
        return summary
    work_dir = ensure_work_dir(record_id)
    if existing_task_id:
        refs = []
        reference_urls = []
        reference_image_paths = []
        prompt = "\n\n".join(part for part in [NINE_GRID_IMAGE_SYSTEM_PROMPT, prompt] if part).strip()
        summary["route"] = ai_routing.build_media_request_summary(route, prompt, reference_count=0)
    else:
        refs = collect_nine_grid_reference_images(
            token,
            parent_fields,
            parent_record_id,
            work_dir,
            max_count=MAX_REFERENCE_IMAGES,
            download_fn=safe_download_attachment,
        )
        reference_image_paths = [ref["path"] for ref in refs]
        reference_urls = build_reference_urls(token, refs)
        product_lock_prompt = build_product_reference_lock_prompt(refs)
        prompt = "\n\n".join(part for part in [NINE_GRID_IMAGE_SYSTEM_PROMPT, product_lock_prompt, prompt] if part).strip()
        summary["route"] = ai_routing.build_media_request_summary(route, prompt, reference_count=len(refs))
    out_path = str(work_dir / f"{record_id}_nine_grid.png")
    primary_reference_path = ""
    submitted_reference_image_paths: Optional[List[str]] = reference_image_paths
    if route.provider == "OTU" and refs:
        primary_reference_path = build_reference_contact_sheet(refs, work_dir / "reference_contact_sheet.png")
        submitted_reference_image_paths = None
        reference_urls = []

    if existing_task_id:
        safe_update_record(token, TABLE_NINE_GRID_VIDEO, record_id, filter_existing_fields(token, TABLE_NINE_GRID_VIDEO, {
            **_image_param_fields("图片", params),
            "图片任务ID": existing_task_id,
            "图片生成状态": "生成中",
            "图片错误信息": f"恢复轮询已有 OTU 宫格图片任务。task_id={existing_task_id}",
            "错误信息": "",
        }))
    else:
        safe_update_record(token, TABLE_NINE_GRID_VIDEO, record_id, filter_existing_fields(token, TABLE_NINE_GRID_VIDEO, {
            **_image_param_fields("图片", params),
            "宫格图": [],
            "九宫格图": [],
            "图片任务ID": "",
            "图片错误信息": "",
            "图片生成时间": None,
            "分镜视频": [],
            "分镜视频URL": None,
            "视频任务ID": "",
            "视频错误信息": "",
            "视频生成时间": None,
            "视频生成状态": "不触发",
            "图片生成状态": "生成中",
            "错误信息": "",
        }))
    image_result = run_image_generation(
        route,
        prompt,
        out_path,
        input_mode="image-to-image",
        image_path=primary_reference_path,
        reference_image_paths=submitted_reference_image_paths,
        metadata={
            "urls": reference_urls,
            "reference_roles": [ref["role"] for ref in refs],
            "aspectRatio": params.get("aspect_ratio") or DEFAULT_ASPECT_RATIO,
            "aspect_ratio": params.get("aspect_ratio") or DEFAULT_ASPECT_RATIO,
        },
        size=params.get("size") or DEFAULT_IMAGE_SIZE,
        aspect_ratio=params.get("aspect_ratio") or DEFAULT_ASPECT_RATIO,
        existing_task_id=existing_task_id,
        otu_submitter=submit_otu_image_task,
        otu_poller=poll_otu_image_task,
        otu_downloader=download_otu_image_result,
        on_task_submitted=lambda task_id: safe_update_record(
            token,
            TABLE_NINE_GRID_VIDEO,
            record_id,
            filter_existing_fields(token, TABLE_NINE_GRID_VIDEO, {
                "图片任务ID": task_id,
                "图片错误信息": f"已提交 {route.provider} 宫格图片任务，正在轮询。task_id={task_id}",
            }),
        ),
    )
    task_id = image_result.task_id
    submit_body = image_result.submit_body
    if task_id:
        safe_update_record(token, TABLE_NINE_GRID_VIDEO, record_id, filter_existing_fields(token, TABLE_NINE_GRID_VIDEO, {
            "图片任务ID": task_id,
            "图片错误信息": f"已提交 {route.provider} 宫格图片任务，正在轮询。task_id={task_id}",
        }))
    result = image_result.result_body
    file_token = with_retry(
        lambda: upload_image_to_feishu(token, out_path, f"{record_id}_nine_grid.png"),
        max_attempts=3,
        label="upload grid image",
    )
    safe_update_record(token, TABLE_NINE_GRID_VIDEO, record_id, filter_existing_fields(token, TABLE_NINE_GRID_VIDEO, {
        **_image_param_fields("图片", params),
        "宫格图": [{"file_token": file_token}],
        "九宫格图": [{"file_token": file_token}],
        "图片AI供应商": route.provider,
        "图片AI模型": route.model,
        "图片任务ID": task_id,
        "图片生成状态": "成功",
        "图片生成时间": int(time.time() * 1000),
        "图片错误信息": "",
        "视频生成状态": "待生成",
        "错误信息": "",
    }))
    summary.update({
        "status": "success",
        "task_id": task_id,
        "file_token": file_token,
        "output_path": out_path,
        "reference_count": len(refs),
    })
    return summary


def render_nine_grid_video(record_id: str, *, dry_run: bool = False) -> Dict[str, Any]:
    ensure_nine_grid_table()
    token = get_feishu_token()
    fields = safe_get_record(token, TABLE_NINE_GRID_VIDEO, record_id)
    fields = apply_task_default_to_record(
        token,
        TABLE_NINE_GRID_VIDEO,
        record_id,
        fields,
        app_table=TASK_TABLES["nine_grid_video"],
        stage="宫格视频生成默认",
        model_field="视频生成模型",
        size_field="视频画面尺寸",
        ratio_field="视频画面比例",
        params_field="视频AI参数JSON",
        field_filter=filter_existing_fields,
    )
    prompt = extract_text(fields.get("视频提示词")).strip()
    if not _attachment_token(_field_value(fields, "宫格图", "九宫格图")):
        raise ValueError("Board分段缺少宫格图附件")
    existing_task_id = extract_text(fields.get("视频任务ID")).strip()
    parent_record_id = extract_text(fields.get("父任务记录ID")).strip()
    if not parent_record_id:
        raise ValueError("Board分段缺少父任务记录ID")
    parent_fields = safe_get_record(token, TABLE_NINE_GRID_VIDEO, parent_record_id)
    _, cfg = get_config_record(VIDEO_STAGE_NAME, default_model="omni_flash-10s", default_api_base="https://otuapi.com", default_size=DEFAULT_VIDEO_SIZE)
    json_params = _parse_params(extract_text(fields.get("视频AI参数JSON")).strip())
    params = {
        **json_params,
        "size": extract_text(fields.get("视频画面尺寸")).strip() or json_params.get("size") or cfg.get("size") or DEFAULT_VIDEO_SIZE,
        "aspect_ratio": extract_text(fields.get("视频画面比例")).strip() or json_params.get("aspect_ratio") or cfg.get("aspect_ratio") or DEFAULT_ASPECT_RATIO,
        "seconds": json_params.get("seconds") or "10",
    }
    route = _route_for_prefixed_fields(
        fields,
        "视频",
        cfg,
        capability="视频",
        task_type="首帧图生视频",
        default_provider=DEFAULT_VIDEO_PROVIDER,
        default_model=DEFAULT_VIDEO_MODEL,
        config_records=_stage_config_records(token),
    )
    route.params.update(params)
    if not ai_model_catalog.is_reference_video_model(route.model, route.provider):
        raise ValueError(f"宫格视频只支持参考图生视频模型: {route.model}")
    if existing_task_id and not existing_video_task_matches_route(fields, route, existing_task_id):
        existing_task_id = ""
    model_name = ai_routing.parse_model_display(route.model)["model"] or route.model
    will_submit_new_task = not existing_task_id
    prompt_refs: List[Dict[str, str]] = []
    model_prompt = prompt
    if will_submit_new_task:
        product_item = first_product_reference_item(token, parent_fields)
        human_items = collect_nine_grid_video_human_reference_items(token, parent_record_id)
        prompt_refs = [{
            "role": "nine_grid",
            "name": "current Board multi-panel",
            "type": "nine_grid",
        }, {
            **product_item,
            "type": "product",
        }, *human_items]
        if route.provider == "Aitgenne" and not ai_routing.is_aitgenne_happyhorse_model(route):
            prompt_refs = prompt_refs[:_aitgenne_reference_limit(route)]
        model_prompt = build_video_model_prompt_for_route(prompt, route, prompt_refs)
    summary = {
        "record_id": record_id,
        "dry_run": dry_run,
        "route": ai_routing.build_media_request_summary(route, model_prompt, reference_count=len(prompt_refs)),
        "prompt_chars": len(model_prompt),
    }
    if existing_task_id:
        summary["existing_task_id"] = existing_task_id
    if dry_run:
        summary["status"] = "dry_run_ready"
        return summary

    work_dir = ensure_work_dir(record_id)
    output_path = str(work_dir / f"{record_id}_nine_grid_video.mp4")
    field_types = get_table_field_types(token, TABLE_NINE_GRID_VIDEO)
    task_id = existing_task_id
    task_detail = ""

    video_config = {"api_key": route.api_key, "api_base": route.api_base or DEFAULT_OTU_API_BASE, "model": model_name}
    if existing_task_id:
        task_detail = f"{video_task_route_tag(route)} task_id={task_id}"
        safe_update_record(token, TABLE_NINE_GRID_VIDEO, record_id, filter_existing_fields(token, TABLE_NINE_GRID_VIDEO, {
            "视频生成状态": "生成中",
            "视频任务ID": task_id,
            "视频错误信息": f"恢复轮询已有宫格视频任务。{task_detail}",
            "错误信息": "",
        }))
    else:
        grid_token = _attachment_token(_field_value(fields, "宫格图", "九宫格图"))
        grid_path = str(work_dir / "reference_nine_grid.png")
        safe_download_attachment(token, grid_token, grid_path)
        product_ref = collect_nine_grid_video_product_reference(
            token,
            parent_fields,
            work_dir,
            product_item=product_item,
            download_fn=safe_download_attachment,
        )
        omni_refs = [{
            "role": "nine_grid",
            "path": grid_path,
            "file_token": grid_token,
            "name": "current Board multi-panel",
        }, product_ref]
        omni_refs.extend(collect_nine_grid_video_human_references(
            token,
            parent_record_id,
            work_dir,
            items=human_items,
            download_fn=safe_download_attachment,
        ))
        submitted_refs = omni_refs
        if route.provider == "Aitgenne" and not ai_routing.is_aitgenne_happyhorse_model(route):
            submitted_refs = omni_refs[:_aitgenne_reference_limit(route)]
        if route.provider == "Aitgenne":
            urls = build_reference_urls(token, submitted_refs)
            submitted_refs = [dict(ref, url=url) for ref, url in zip(submitted_refs, urls)]
        submitted_ref_roles = _reference_roles_summary(submitted_refs)
        safe_update_record(token, TABLE_NINE_GRID_VIDEO, record_id, filter_existing_fields(token, TABLE_NINE_GRID_VIDEO, {
            "分镜视频": [],
            "分镜视频URL": None,
            "视频本地路径": "",
            "视频任务ID": "",
            "视频错误信息": "",
            "视频生成时间": None,
            "视频生成状态": "生成中",
            "错误信息": "",
        }))
        if route.provider == "OTU":
            task_id, _submit_body = submit_omni_video_task(
                video_config,
                model_prompt,
                submitted_refs,
                size=params.get("size") or DEFAULT_VIDEO_SIZE,
                aspect_ratio=params.get("aspect_ratio") or DEFAULT_ASPECT_RATIO,
            )
        else:
            task_id, _submit_body = submit_reference_video_task(
                route,
                model_prompt,
                submitted_refs,
                size=params.get("size") or DEFAULT_VIDEO_SIZE,
                aspect_ratio=params.get("aspect_ratio") or DEFAULT_ASPECT_RATIO,
                seconds=str(params.get("seconds") or "10"),
            )
        task_detail = f"{video_task_route_tag(route)} task_id={task_id} Submitted reference roles: {submitted_ref_roles}"
        safe_update_record(token, TABLE_NINE_GRID_VIDEO, record_id, filter_existing_fields(token, TABLE_NINE_GRID_VIDEO, {
            "视频生成状态": "生成中",
            "视频任务ID": task_id,
            "视频错误信息": (
                f"已提交宫格视频任务，正在轮询。{task_detail}"
            ),
        }))
    if route.provider == "OTU":
        result = poll_otu_nine_grid_video_task(video_config, task_id)
    else:
        result = poll_reference_video_task(route, task_id)
    video_url = extract_video_url(result)
    if not video_url:
        raise RuntimeError(f"宫格视频生成完成但未返回 video_url: {compact_json(result, 1200)}")
    if route.provider == "Aitgenne":
        download_video_without_env_proxy(video_url, output_path)
    else:
        download_video(video_url, output_path)
    repair_fields = {
        "视频生成状态": "生成中",
        "视频任务ID": task_id,
        "视频本地路径": output_path,
        "视频错误信息": f"视频已下载到本地，等待飞书上传附件。{task_detail}",
        "错误信息": "",
    }
    repair_fields["分镜视频URL"] = format_url_field_value(video_url, field_types.get("分镜视频URL", 0))
    safe_update_record(token, TABLE_NINE_GRID_VIDEO, record_id, filter_existing_fields(token, TABLE_NINE_GRID_VIDEO, repair_fields))
    file_token = upload_video_to_feishu(token, output_path, f"{record_id}_nine_grid_video.mp4")
    ensure_nine_grid_record_current_generation(token, record_id, "视频生成状态", "生成中", "视频任务ID", task_id)
    success_fields = {
        "视频生成模型": route.model,
        "视频生成状态": "成功",
        "分镜视频": [{"file_token": file_token, "name": Path(output_path).name}],
        "视频任务ID": task_id,
        "视频错误信息": "",
        "视频生成时间": int(time.time() * 1000),
        "错误信息": "",
    }
    success_fields["分镜视频URL"] = format_url_field_value(video_url, field_types.get("分镜视频URL", 0))
    safe_update_record(token, TABLE_NINE_GRID_VIDEO, record_id, filter_existing_fields(token, TABLE_NINE_GRID_VIDEO, success_fields))
    summary.update({"status": "success", "task_id": task_id, "video_url": video_url, "file_token": file_token, "output_path": output_path})
    return summary


def _failure_update_for_action(action: str, message: str) -> Dict[str, Any]:
    if action == "plan":
        return {"方案生成状态": "失败", "错误信息": message[:1000]}
    if action == "reference":
        return {"参考图生成状态": "失败", "参考图错误信息": message[:1000], "错误信息": message[:1000]}
    if action == "reference-approval":
        return {"参考图错误信息": message[:1000], "错误信息": message[:1000]}
    if action == "image":
        return {"图片生成状态": "失败", "图片错误信息": message[:1000], "错误信息": message[:1000]}
    if action == "video":
        return {"视频生成状态": "失败", "视频错误信息": message[:1000], "错误信息": message[:1000]}
    return {"错误信息": message[:1000]}


def main() -> int:
    parser = argparse.ArgumentParser(description="多图宫格视频生成")
    parser.add_argument("action", choices=["plan", "reference", "reference-approval", "image", "video"])
    parser.add_argument("record_id")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    try:
        if args.action == "plan":
            result = split_nine_grid_plan(args.record_id, dry_run=args.dry_run)
        elif args.action == "reference":
            result = render_reference_asset(args.record_id, dry_run=args.dry_run)
        elif args.action == "reference-approval":
            result = advance_boards_for_reference_asset(args.record_id, dry_run=args.dry_run)
        elif args.action == "image":
            result = render_nine_grid_image(args.record_id, dry_run=args.dry_run)
        else:
            result = render_nine_grid_video(args.record_id, dry_run=args.dry_run)
        print(compact_json(result))
        return 0
    except Exception as exc:
        stage = {
            "plan": "nine_grid_plan",
            "reference": "nine_grid_reference",
            "reference-approval": "nine_grid_reference_approval",
            "image": "nine_grid_image",
            "video": "nine_grid_video",
        }[args.action]
        payload = build_error_payload(exc, stage=stage)
        if not args.dry_run:
            try:
                token = get_feishu_token()
                safe_update_record(
                    token,
                    TABLE_NINE_GRID_VIDEO,
                    args.record_id,
                    filter_existing_fields(
                        token,
                        TABLE_NINE_GRID_VIDEO,
                        _failure_update_for_action(args.action, payload["message"]),
                    ),
                )
            except Exception:
                pass
        print(json.dumps(payload, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
