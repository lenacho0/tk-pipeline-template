#!/usr/bin/env python3
"""
多图九宫格方案、九宫格图片、整板视频生成。

用法:
  python3 tk_nine_grid_video.py plan <parent_record_id>
  python3 tk_nine_grid_video.py image <board_record_id>
  python3 tk_nine_grid_video.py video <board_record_id>
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (  # noqa: E402
    APP_TOKEN,
    TABLE_CONFIG,
    TABLE_NINE_GRID_VIDEO,
    WORKSPACE,
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
    normalize_image_model_choice,
    poll_otu_image_task,
    submit_otu_image_task,
)
from tk_nine_grid_video_prompt import (  # noqa: E402
    NINE_GRID_IMAGE_SYSTEM_PROMPT,
    NINE_GRID_PLAN_SYSTEM_PROMPT,
    NINE_GRID_VIDEO_SYSTEM_PROMPT,
)
from tk_shot_script_gen import extract_json_object  # noqa: E402
from tk_storyboard_video import (  # noqa: E402
    build_reference_contact_sheet,
    build_reference_urls,
    collect_parent_reference_images,
    compact_json,
    filter_existing_fields,
)
from tk_shot_video import (  # noqa: E402
    download_video,
    extract_video_url,
    format_url_field_value,
    get_table_field_types,
    poll_otu_video_task,
    submit_otu_video_task,
    upload_video_to_feishu,
)
import ai_routing  # noqa: E402


PLAN_STAGE_NAME = "多图九宫格方案生成"
IMAGE_STAGE_NAME = "多图九宫格图片生成"
VIDEO_STAGE_NAME = "多图九宫格视频生成"
DEFAULT_TEXT_PROVIDER = "AIHubMix"
DEFAULT_TEXT_MODEL = "AIHubMix / gemini-3.1-pro-preview"
DEFAULT_IMAGE_PROVIDER = "OTU"
DEFAULT_IMAGE_MODEL = "OTU / gpt-image-2"
DEFAULT_VIDEO_PROVIDER = "OTU"
DEFAULT_VIDEO_MODEL = "OTU / veo_3_1-fast-fl"
DEFAULT_IMAGE_SIZE = "720x1280"
DEFAULT_VIDEO_SIZE = "720x1280"
DEFAULT_ASPECT_RATIO = "9:16"
BASE_WORK_DIR = Path(WORKSPACE) / "nine_grid_video_work"
MAX_REFERENCE_IMAGES = 7
SECRET_FALLBACK_STAGES = {
    PLAN_STAGE_NAME: ("故事板图片提示词拆分-Gemini",),
    IMAGE_STAGE_NAME: ("图片生成-OTU", "故事板图片生成-OTU"),
    VIDEO_STAGE_NAME: ("分镜视频生成-OTU",),
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


def normalize_nine_grid_plan_payload(payload: Any) -> Dict[str, Any]:
    data = payload
    if isinstance(payload, str):
        stripped = _strip_markdown_code_block(payload)
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            data = extract_json_object(stripped)
    if not isinstance(data, dict):
        raise ValueError("九宫格方案结果必须是 JSON 对象")
    if extract_text(data.get("task_type")).strip() != "MULTI_IMAGE_NINE_GRID_PLAN":
        raise ValueError("九宫格方案 task_type 必须是 MULTI_IMAGE_NINE_GRID_PLAN")
    boards = _as_list(data.get("boards"))
    if not boards:
        raise ValueError("九宫格方案缺少 boards")
    normalized_boards = []
    for idx, board in enumerate(boards, start=1):
        if not isinstance(board, dict):
            raise ValueError(f"boards[{idx}] 必须是对象")
        cells = _as_list(board.get("cells"))
        if len(cells) != 9:
            raise ValueError(f"Board {idx} cells 必须正好 9 个")
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
        normalized_board["cells"] = normalized_cells
        normalized_board["image_prompt"] = extract_text(board.get("image_prompt")).strip() or build_board_image_prompt(normalized_board)
        normalized_board["video_prompt"] = extract_text(board.get("video_prompt")).strip() or build_board_video_prompt(normalized_board)
        normalized_boards.append(normalized_board)
    normalized = dict(data)
    normalized["boards"] = normalized_boards
    return normalized


def build_board_image_prompt(board: Dict[str, Any]) -> str:
    lines = [
        "Create one vertical 9:16 image containing exactly 9 panels arranged in a 3x3 grid.",
        "Each panel is a vertical 9:16 smartphone UGC video still.",
        "Read panels left to right, top to bottom.",
        "Use the uploaded character, pet, product, and environment reference images as strict identity anchors.",
        "Do not place reference-sheet images inside the timeline panels.",
        "No subtitles, no stickers, no watermarks, no UI, no poster text, no panel numbers.",
        "Avoid visible borders, thick black grid lines, comic panel outlines, gutters, or table-like layout.",
        "Keep the same person/pet/product/environment across all nine panels.",
    ]
    for cell in _as_list(board.get("cells")):
        lines.append(
            f"Cell {cell.get('cell_index')}: {cell.get('visual_node')}; "
            f"action: {cell.get('character_action')}; product: {cell.get('product_state')}; "
            f"environment: {cell.get('environment_anchor')}; emotion: {cell.get('emotion')}; camera: {cell.get('camera')}."
        )
    return "\n".join(lines)


def build_board_video_prompt(board: Dict[str, Any]) -> str:
    cells = "; ".join(
        f"Cell {cell.get('cell_index')} {cell.get('visual_node')}"
        for cell in _as_list(board.get("cells"))
    )
    return (
        "Use the current Board nine-grid image as a narrative sequence reference, not as a final split-screen layout. "
        "Read the nine cells left to right, top to bottom, then turn them into one continuous vertical 9:16 TikTok UGC smartphone video. "
        "Keep the same person, pet, product, room, furniture, lighting, and problem location from the uploaded references. "
        f"Action sequence: {cells}. "
        "No grid layout, no split screen, no panel borders, no subtitles, no stickers, no watermarks, no UI, no poster text."
    )


def _field_with_default(fields: Dict[str, Any], name: str, default: str) -> str:
    return extract_text(fields.get(name)).strip() or default


def _prefixed_route_fields(fields: Dict[str, Any], prefix: str, *, default_provider: str, default_model: str) -> Dict[str, str]:
    return {
        "provider": _field_with_default(fields, f"{prefix}AI供应商", default_provider),
        "model": _field_with_default(fields, f"{prefix}AI模型", default_model),
        "params": extract_text(fields.get(f"{prefix}AI参数JSON")).strip(),
    }


def _parse_params(text: str) -> Dict[str, Any]:
    if not text:
        return {}
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("AI参数JSON 顶层必须是对象")
    return parsed


def build_plan_generation_request(fields: Dict[str, Any], *, system_prompt: str = "") -> str:
    script = extract_text(fields.get("脚本内容")).strip()
    product_links = _extract_link_ids(fields.get("关联产品记录"))
    model_links = _extract_link_ids(fields.get("选择模特"))
    rules = extract_text(system_prompt).strip() or NINE_GRID_PLAN_SYSTEM_PROMPT
    return f"""
{rules}

【本次任务上下文】
- Product record ids: {", ".join(product_links) or "none"}
- Character / pet model record ids: {", ".join(model_links) or "none"}
- Environment image count: {len(_as_list(fields.get("环境图")))}

【完整脚本内容】
{script}
""".strip()


def build_plan_review_markdown(payload: Dict[str, Any]) -> str:
    lines = ["# 多图九宫格方案审核稿"]
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


def build_child_board_records(
    parent_fields: Dict[str, Any],
    payload: Dict[str, Any],
    *,
    parent_record_id: str,
    batch_id: str,
) -> List[Dict[str, Dict[str, Any]]]:
    records = []
    boards = payload.get("boards") or []
    total = len(boards)
    task_name = extract_text(parent_fields.get("任务名称")).strip() or f"九宫格任务-{parent_record_id[-6:]}"
    for board in boards:
        no = int(board.get("board_index") or len(records) + 1)
        fields = {
            "记录类型": "Board分段",
            "任务名称": f"{task_name}-Board{no:02d}",
            "父任务记录ID": parent_record_id,
            "批次ID": batch_id,
            "关联产品记录": _extract_link_ids(parent_fields.get("关联产品记录")),
            "选择模特": _extract_link_ids(parent_fields.get("选择模特")),
            "总Board数": total,
            "Board编号": no,
            "Time Range": extract_text(board.get("time_range")).strip(),
            "叙事任务": extract_text(board.get("narrative_task")).strip(),
            "起始画面": extract_text(board.get("start_frame")).strip(),
            "结束画面": extract_text(board.get("end_frame")).strip(),
            "衔接锚点": extract_text(board.get("handoff_anchor")).strip(),
            "九格摘要JSON": compact_json(board.get("cells") or [], 10000),
            "审核状态": "待确认",
            "九宫格图片提示词": extract_text(board.get("image_prompt")).strip(),
            "图片AI供应商": _field_with_default(parent_fields, "图片AI供应商", DEFAULT_IMAGE_PROVIDER),
            "图片AI模型": _field_with_default(parent_fields, "图片AI模型", DEFAULT_IMAGE_MODEL),
            "图片AI参数JSON": extract_text(parent_fields.get("图片AI参数JSON")).strip(),
            "图片画面尺寸": DEFAULT_IMAGE_SIZE,
            "图片画面比例": DEFAULT_ASPECT_RATIO,
            "图片生成状态": "待生成",
            "视频提示词": extract_text(board.get("video_prompt")).strip(),
            "视频AI供应商": _field_with_default(parent_fields, "视频AI供应商", DEFAULT_VIDEO_PROVIDER),
            "视频AI模型": _field_with_default(parent_fields, "视频AI模型", DEFAULT_VIDEO_MODEL),
            "视频AI参数JSON": extract_text(parent_fields.get("视频AI参数JSON")).strip(),
            "视频画面尺寸": DEFAULT_VIDEO_SIZE,
            "视频画面比例": DEFAULT_ASPECT_RATIO,
            "视频生成状态": "不触发",
            "错误信息": "",
        }
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
    for rec in records:
        fields = rec.get("fields") or {}
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
        return rec.get("record_id") or rec.get("id") or "", cfg
    return "", {
        "model": default_model,
        "api_key": "",
        "api_base": default_api_base,
        "size": default_size,
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
) -> ai_routing.AiRoute:
    route_fields = _prefixed_route_fields(fields, prefix, default_provider=default_provider, default_model=default_model)
    route = ai_routing.AiRoute(
        provider=route_fields["provider"],
        capability=capability,
        task_type=task_type,
        model=route_fields["model"],
        api_base=extract_text(cfg.get("api_base")).strip(),
        api_key=extract_text(cfg.get("api_key")).strip(),
        params=_parse_params(route_fields["params"]),
    )
    return ai_routing.validate_route(route)


def split_nine_grid_plan(record_id: str, *, dry_run: bool = False, raw_model_output: Any = None) -> Dict[str, Any]:
    ensure_nine_grid_table()
    token = get_feishu_token()
    fields = safe_get_record(token, TABLE_NINE_GRID_VIDEO, record_id)
    script = extract_text(fields.get("脚本内容")).strip()
    if not script:
        raise ValueError("脚本内容为空")
    _, cfg = get_config_record(PLAN_STAGE_NAME, default_model="gemini-3.1-pro-preview", default_api_base="https://aihubmix.com/gemini")
    prompt = build_plan_generation_request(fields, system_prompt=cfg.get("prompt") or NINE_GRID_PLAN_SYSTEM_PROMPT)
    route = _route_for_prefixed_fields(
        fields,
        "方案",
        cfg,
        capability="文本",
        task_type="多图九宫格方案生成",
        default_provider=DEFAULT_TEXT_PROVIDER,
        default_model=DEFAULT_TEXT_MODEL,
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

    config_records = _stage_config_records(token)
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
    payload = normalize_nine_grid_plan_payload(raw_model_output)
    batch_id = f"NINEGRID-{time.strftime('%Y%m%d%H%M%S')}-{record_id[-6:]}"
    child_records = build_child_board_records(fields, payload, parent_record_id=record_id, batch_id=batch_id)
    deleted = cleanup_child_boards(token, record_id)
    create_records(token, TABLE_NINE_GRID_VIDEO, [
        {"fields": filter_existing_fields(token, TABLE_NINE_GRID_VIDEO, item["fields"])}
        for item in child_records
    ])
    safe_update_record(token, TABLE_NINE_GRID_VIDEO, record_id, filter_existing_fields(token, TABLE_NINE_GRID_VIDEO, {
        "记录类型": "母任务",
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
        "deleted_children": deleted,
        "board_count": len(child_records),
    })
    return summary


def _attachment_token(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    for item in value:
        if isinstance(item, dict) and item.get("file_token"):
            return item["file_token"]
    return ""


def render_nine_grid_image(record_id: str, *, dry_run: bool = False) -> Dict[str, Any]:
    ensure_nine_grid_table()
    token = get_feishu_token()
    fields = safe_get_record(token, TABLE_NINE_GRID_VIDEO, record_id)
    parent_record_id = extract_text(fields.get("父任务记录ID")).strip()
    if not parent_record_id:
        raise ValueError("Board分段缺少父任务记录ID")
    parent_fields = safe_get_record(token, TABLE_NINE_GRID_VIDEO, parent_record_id)
    prompt = extract_text(fields.get("九宫格图片提示词")).strip()
    if not prompt:
        raise ValueError("九宫格图片提示词为空")
    _, cfg = get_config_record(IMAGE_STAGE_NAME, default_model="gpt-image-2", default_api_base="https://otuapi.com", default_size=DEFAULT_IMAGE_SIZE)
    params = {
        "size": _field_with_default(fields, "图片画面尺寸", DEFAULT_IMAGE_SIZE),
        "aspect_ratio": _field_with_default(fields, "图片画面比例", DEFAULT_ASPECT_RATIO),
    }
    params.update(_parse_params(extract_text(fields.get("图片AI参数JSON")).strip()))
    route = _route_for_prefixed_fields(
        fields,
        "图片",
        cfg,
        capability="图片",
        task_type="图生图/参考图重绘",
        default_provider=DEFAULT_IMAGE_PROVIDER,
        default_model=DEFAULT_IMAGE_MODEL,
    )
    route.params.update(params)
    summary = {
        "record_id": record_id,
        "dry_run": dry_run,
        "route": ai_routing.build_media_request_summary(route, prompt, reference_count=1),
        "prompt_chars": len(prompt),
    }
    if dry_run:
        summary["status"] = "dry_run_ready"
        return summary
    if route.provider != "OTU":
        raise NotImplementedError(f"当前仅 OTU 图片真实提交已接入；{route.provider} 请先使用 --dry-run 校验路由")

    work_dir = ensure_work_dir(record_id)
    refs = collect_parent_reference_images(
        token,
        parent_fields,
        work_dir,
        max_count=MAX_REFERENCE_IMAGES,
        download_fn=safe_download_attachment,
    )
    reference_urls = build_reference_urls(token, refs)
    contact_sheet = build_reference_contact_sheet(refs, work_dir / "reference_contact_sheet.png")
    prompt = f"{NINE_GRID_IMAGE_SYSTEM_PROMPT}\n\n{prompt}".strip()
    model_name = normalize_image_model_choice(ai_routing.parse_model_display(route.model)["model"] or route.model)
    out_path = str(work_dir / f"{record_id}_nine_grid.png")

    safe_update_record(token, TABLE_NINE_GRID_VIDEO, record_id, filter_existing_fields(token, TABLE_NINE_GRID_VIDEO, {
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
    task_id, submit_body = submit_otu_image_task(
        {"api_key": route.api_key, "api_base": route.api_base or DEFAULT_OTU_API_BASE, "model": model_name},
        prompt,
        input_mode="image-to-image",
        image_path=contact_sheet,
        metadata={
            "urls": reference_urls,
            "reference_roles": [ref["role"] for ref in refs],
            "aspectRatio": params.get("aspect_ratio") or DEFAULT_ASPECT_RATIO,
            "aspect_ratio": params.get("aspect_ratio") or DEFAULT_ASPECT_RATIO,
        },
        size=params.get("size") or DEFAULT_IMAGE_SIZE,
    )
    if task_id:
        safe_update_record(token, TABLE_NINE_GRID_VIDEO, record_id, filter_existing_fields(token, TABLE_NINE_GRID_VIDEO, {
            "图片任务ID": task_id,
            "图片错误信息": f"已提交九宫格图片任务，正在轮询。task_id={task_id}",
        }))
    result = submit_body if not task_id else poll_otu_image_task(
        {"api_key": route.api_key, "api_base": route.api_base or DEFAULT_OTU_API_BASE, "model": model_name},
        task_id,
    )
    result_url = extract_otu_result_url(result) or extract_otu_result_url(submit_body)
    if not result_url:
        raise RuntimeError("九宫格图片任务完成但未返回图片地址")
    download_otu_image_result(result_url, out_path)
    file_token = with_retry(
        lambda: upload_image_to_feishu(token, out_path, f"{record_id}_nine_grid.png"),
        max_attempts=3,
        label="upload nine grid image",
    )
    safe_update_record(token, TABLE_NINE_GRID_VIDEO, record_id, filter_existing_fields(token, TABLE_NINE_GRID_VIDEO, {
        "九宫格图": [{"file_token": file_token}],
        "图片任务ID": task_id,
        "图片生成状态": "成功",
        "图片生成时间": int(time.time() * 1000),
        "图片错误信息": "",
        "视频生成状态": "待生成",
        "错误信息": "",
    }))
    summary.update({"status": "success", "file_token": file_token, "output_path": out_path, "reference_count": len(refs)})
    return summary


def render_nine_grid_video(record_id: str, *, dry_run: bool = False) -> Dict[str, Any]:
    ensure_nine_grid_table()
    token = get_feishu_token()
    fields = safe_get_record(token, TABLE_NINE_GRID_VIDEO, record_id)
    prompt = extract_text(fields.get("视频提示词")).strip() or NINE_GRID_VIDEO_SYSTEM_PROMPT
    if not _attachment_token(fields.get("九宫格图")):
        raise ValueError("Board分段缺少九宫格图附件")
    _, cfg = get_config_record(VIDEO_STAGE_NAME, default_model="veo_3_1-fast-fl", default_api_base="https://otuapi.com", default_size=DEFAULT_VIDEO_SIZE)
    params = {
        "size": _field_with_default(fields, "视频画面尺寸", DEFAULT_VIDEO_SIZE),
        "aspect_ratio": _field_with_default(fields, "视频画面比例", DEFAULT_ASPECT_RATIO),
        "seconds": "10",
    }
    params.update(_parse_params(extract_text(fields.get("视频AI参数JSON")).strip()))
    route = _route_for_prefixed_fields(
        fields,
        "视频",
        cfg,
        capability="视频",
        task_type="首帧图生视频",
        default_provider=DEFAULT_VIDEO_PROVIDER,
        default_model=DEFAULT_VIDEO_MODEL,
    )
    route.params.update(params)
    summary = {
        "record_id": record_id,
        "dry_run": dry_run,
        "route": ai_routing.build_media_request_summary(route, prompt, reference_count=1),
        "prompt_chars": len(prompt),
    }
    if dry_run:
        summary["status"] = "dry_run_ready"
        return summary
    if route.provider != "OTU":
        raise NotImplementedError(f"当前仅 OTU 视频真实提交已接入；{route.provider} 请先使用 --dry-run 校验路由")

    work_dir = ensure_work_dir(record_id)
    grid_token = _attachment_token(fields.get("九宫格图"))
    grid_path = str(work_dir / "reference_nine_grid.png")
    safe_download_attachment(token, grid_token, grid_path)
    model_name = ai_routing.parse_model_display(route.model)["model"] or route.model
    output_path = str(work_dir / f"{record_id}_nine_grid_video.mp4")
    field_types = get_table_field_types(token, TABLE_NINE_GRID_VIDEO)

    safe_update_record(token, TABLE_NINE_GRID_VIDEO, record_id, filter_existing_fields(token, TABLE_NINE_GRID_VIDEO, {
        "分镜视频": [],
        "分镜视频URL": None,
        "视频任务ID": "",
        "视频错误信息": "",
        "视频生成时间": None,
        "视频生成状态": "生成中",
        "错误信息": "",
    }))
    task_id, _submit_body = submit_otu_video_task(
        {"api_key": route.api_key, "api_base": route.api_base or DEFAULT_OTU_API_BASE, "model": model_name},
        f"{NINE_GRID_VIDEO_SYSTEM_PROMPT}\n\n{prompt}".strip(),
        grid_path,
        str(params.get("seconds") or "10"),
        size=params.get("size") or DEFAULT_VIDEO_SIZE,
        aspect_ratio=params.get("aspect_ratio") or DEFAULT_ASPECT_RATIO,
    )
    safe_update_record(token, TABLE_NINE_GRID_VIDEO, record_id, filter_existing_fields(token, TABLE_NINE_GRID_VIDEO, {
        "视频任务ID": task_id,
        "视频错误信息": f"已提交九宫格视频任务，正在轮询。task_id={task_id}",
    }))
    result = poll_otu_video_task(
        {"api_key": route.api_key, "api_base": route.api_base or DEFAULT_OTU_API_BASE, "model": model_name},
        task_id,
    )
    video_url = extract_video_url(result)
    if not video_url:
        raise RuntimeError(f"九宫格视频生成完成但未返回 video_url: {compact_json(result, 1200)}")
    download_video(video_url, output_path)
    file_token = upload_video_to_feishu(token, output_path, f"{record_id}_nine_grid_video.mp4")
    success_fields = {
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


def main() -> int:
    parser = argparse.ArgumentParser(description="多图九宫格视频生成")
    parser.add_argument("action", choices=["plan", "image", "video"])
    parser.add_argument("record_id")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    try:
        if args.action == "plan":
            result = split_nine_grid_plan(args.record_id, dry_run=args.dry_run)
        elif args.action == "image":
            result = render_nine_grid_image(args.record_id, dry_run=args.dry_run)
        else:
            result = render_nine_grid_video(args.record_id, dry_run=args.dry_run)
        print(compact_json(result))
        return 0
    except Exception as exc:
        stage = {"plan": "nine_grid_plan", "image": "nine_grid_image", "video": "nine_grid_video"}[args.action]
        payload = build_error_payload(exc, stage=stage)
        print(json.dumps(payload, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
