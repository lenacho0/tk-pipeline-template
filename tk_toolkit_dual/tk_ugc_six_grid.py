#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import requests
from PIL import Image

from ugc_config import UGC_BASE_TOKEN, load_ugc_table_ids
from ugc_reroll_utils import build_candidate_fields
from ugc_utils import extract_text

UGC_GRID_STAGE_NAME = "UGC-6宫格分镜图生成"
BASE_WORK_DIR = Path(__file__).resolve().parent / "workspace_ryan" / "ugc_grid_work"

RecordGetter = Callable[[str, str, str], Dict[str, Any]]
RecordCreator = Callable[[str, str, Dict[str, Any]], str]
RecordUpdater = Callable[[str, str, str, Dict[str, Any]], Any]
ImageCaller = Callable[[Dict[str, str], str], Dict[str, Any]]
Uploader = Callable[[str, str, str], str]


def get_feishu_token() -> str:
    from common import get_feishu_token as _get_feishu_token

    return _get_feishu_token()


def get_ugc_record(token: str, table_id: str, record_id: str) -> Dict[str, Any]:
    from common import feishu_headers, safe_request

    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{UGC_BASE_TOKEN}/tables/{table_id}/records/{record_id}"
    data = safe_request("get", url, headers=feishu_headers(token), timeout=20, max_attempts=3)
    return data["data"]["record"]["fields"]


def create_ugc_record(token: str, table_id: str, fields: Dict[str, Any]) -> str:
    from common import feishu_headers, safe_request

    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{UGC_BASE_TOKEN}/tables/{table_id}/records"
    data = safe_request("post", url, headers=feishu_headers(token), json={"fields": fields}, timeout=30, max_attempts=3)
    return data["data"]["record"]["record_id"]


def update_ugc_record(token: str, table_id: str, record_id: str, fields: Dict[str, Any]) -> Any:
    from common import feishu_headers, safe_request

    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{UGC_BASE_TOKEN}/tables/{table_id}/records/{record_id}"
    return safe_request("put", url, headers=feishu_headers(token), json={"fields": fields}, timeout=30, max_attempts=3)


def upload_image_to_feishu(token: str, file_path: str, file_name: str) -> str:
    from common import APP_TOKEN

    with open(file_path, "rb") as f:
        resp = requests.post(
            "https://open.feishu.cn/open-apis/drive/v1/medias/upload_all",
            headers={"Authorization": f"Bearer {token}"},
            data={
                "file_name": file_name,
                "parent_type": "bitable_file",
                "parent_node": APP_TOKEN,
                "size": str(os.path.getsize(file_path)),
            },
            files={"file": (file_name, f, "image/png")},
            timeout=120,
        )
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"飞书图片上传失败: {data.get('msg') or data}")
    return data["data"]["file_token"]


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def parse_json_object(raw: Any, label: str) -> Dict[str, Any]:
    text = extract_text(raw).strip()
    if not text:
        raise ValueError(f"缺少 {label}")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"{label} 不是 JSON 对象")
    return data



def effective_shot_count(script_json: Dict[str, Any]) -> int:
    raw = script_json.get("optimal_shot_count") or script_json.get("effective_shot_count") or script_json.get("shot_count")
    shots = script_json.get("shots")
    if raw is None:
        raw = len(shots) if isinstance(shots, list) else 0
    try:
        count = int(raw)
    except Exception:
        count = len(shots) if isinstance(shots, list) else 0
    if count < 1 or count > 9:
        raise ValueError("结构化脚本JSON.optimal_shot_count/effective shot count 必须在 1-9 之间")
    if not isinstance(shots, list) or len(shots) != count:
        raise ValueError(f"结构化脚本JSON.shots 必须等于有效镜头数 {count}，且范围为 1-9")
    return count


def extract_storyboard_summary(script_json: Dict[str, Any]) -> List[Dict[str, Any]]:
    shots = script_json.get("shots")
    count = effective_shot_count(script_json)
    for key in ("nine_grid_summary", "storyboard_grid_summary", "six_grid_summary"):
        value = script_json.get(key)
        if isinstance(value, list):
            if len(value) < count:
                raise ValueError(f"结构化脚本JSON.{key} 至少需要覆盖 {count} 个有效镜头")
            return [dict(item) if isinstance(item, dict) else {} for item in value[:count]]
    assert isinstance(shots, list)
    derived: List[Dict[str, Any]] = []
    for i, shot in enumerate(shots, start=1):
        derived.append({
            "grid_index": i,
            "source_shot_index": int(shot.get("shot_index") or i) if isinstance(shot, dict) else i,
            "key_visual": shot.get("image_generation_focus") or shot.get("visual_description") or shot.get("scene") or "" if isinstance(shot, dict) else "",
            "key_character_action": shot.get("subject_action") or "" if isinstance(shot, dict) else "",
            "product_state": shot.get("product_exposure_method") or shot.get("product_presence") or "" if isinstance(shot, dict) else "",
            "environment_focus": shot.get("environment_details") or "" if isinstance(shot, dict) else "",
            "content_type": shot.get("content_type") or "" if isinstance(shot, dict) else "",
            "speaker_visible": bool(shot.get("speaker_visible")) if isinstance(shot, dict) else False,
        })
    return derived


def parse_script_json(ugc03_fields: Dict[str, Any]) -> Dict[str, Any]:
    data = parse_json_object(ugc03_fields.get("结构化脚本JSON"), "UGC-03.结构化脚本JSON")
    count = effective_shot_count(data)
    data["effective_shot_count"] = count
    data["storyboard_grid_summary"] = extract_storyboard_summary(data)
    return data


def parse_grid_prompt_json(ugc04_fields: Dict[str, Any]) -> Dict[str, Any]:
    data = parse_json_object(ugc04_fields.get("6宫格提示词JSON"), "UGC-04.6宫格提示词JSON")
    panels = data.get("panels")
    if not isinstance(panels, list) or len(panels) != 9:
        raise ValueError("9宫格提示词JSON.panels 必须正好 9 个")
    active = [p for p in panels if isinstance(p, dict) and p.get("active")]
    count = int(data.get("effective_shot_count") or len(active) or 0)
    if count < 1 or count > 9:
        raise ValueError("9宫格提示词JSON.effective_shot_count 必须在 1-9 之间")
    if len(active) != count:
        raise ValueError("9宫格提示词JSON.active panels 数量必须等于 effective_shot_count")
    return data


def grid_dimensions(layout: str) -> tuple[int, int]:
    if layout == "3行x3列":
        return 3, 3
    if layout == "3行x2列":
        return 3, 2
    if layout == "2行x3列":
        return 2, 3
    raise ValueError(f"不支持的宫格布局: {layout}")


def layout_canvas_ratio(layout: str) -> str:
    if layout == "3行x3列":
        return "9:16"
    if layout == "3行x2列":
        return "3:8"
    if layout == "2行x3列":
        return "27:32"
    return "layout-dependent; each panel must remain 9:16"


def layout_en_name(layout: str) -> str:
    if layout == "3行x3列":
        return "3 columns x 3 rows"
    if layout == "3行x2列":
        return "2 columns x 3 rows"
    if layout == "2行x3列":
        return "3 columns x 2 rows"
    return layout


def build_panel_prompt(shot: Dict[str, Any], grid: Dict[str, Any], script_json: Dict[str, Any], *, grid_index: int, active_count: int, active: bool = True) -> Dict[str, Any]:
    if not active:
        return {
            "grid_index": grid_index,
            "source_shot_index": None,
            "active": False,
            "placeholder": True,
            "placeholder_type": "white_blank",
            "image_prompt_en": f"Panel {grid_index}: plain pure white blank placeholder cell, no subject, no product, no text, no border decoration.",
            "negative_prompt_en": "No people, no pets, no objects, no words, no icons, no texture, no shadows.",
        }
    character = script_json.get("character_card") or {}
    environment = script_json.get("environment_card") or {}
    video_setup = script_json.get("video_setup") or {}
    content_type = str(shot.get("content_type") or grid.get("content_type") or "").strip()
    speaker_visible = bool(shot.get("speaker_visible") if "speaker_visible" in shot else grid.get("speaker_visible"))
    source_index = int(grid.get("source_shot_index") or shot.get("shot_index") or grid_index)
    prompt = (
        f"Vertical UGC storyboard panel {grid_index}/9, active story shot {source_index}/{active_count}, realistic smartphone video still, 9:16 composition. "
        f"Scene: {shot.get('scene') or ''}. Visual: {shot.get('visual_description') or grid.get('key_visual') or ''}. "
        f"Main action: {shot.get('subject_action') or grid.get('key_character_action') or ''}. "
        f"Character: {shot.get('character_state') or character.get('description') or ''}. "
        f"Pet: {shot.get('pet_state') or ''}. Product: {shot.get('product_exposure_method') or grid.get('product_state') or ''}. "
        f"Environment: {shot.get('environment_details') or grid.get('environment_focus') or environment.get('description') or ''}. "
        f"Camera: {shot.get('camera') or ''}, shot size: {shot.get('shot_size') or ''}. "
        f"Style: {video_setup.get('video_style') or 'real UGC'}, natural light, ordinary home, not commercial, no text overlay, no subtitles, no logo hallucination."
    )
    negative = "No subtitles, no text stickers, no large poster words, no extra fingers, no distorted pets, no medical/clinical scene, no ecommerce product render."
    return {
        "grid_index": grid_index,
        "source_shot_index": source_index,
        "active": True,
        "placeholder": False,
        "content_type": content_type,
        "speaker_visible": speaker_visible,
        "key_visual": grid.get("key_visual") or shot.get("image_generation_focus") or shot.get("visual_description") or "",
        "key_character_action": grid.get("key_character_action") or shot.get("subject_action") or "",
        "product_state": grid.get("product_state") or shot.get("product_presence") or "",
        "environment_focus": grid.get("environment_focus") or shot.get("environment_details") or "",
        "image_prompt_en": prompt,
        "negative_prompt_en": negative,
    }


def build_six_grid_prompt_json(ugc03_record_id: str, script_json: Dict[str, Any], layout: str = "3行x3列") -> Dict[str, Any]:
    # Backward-compatible function name: business semantics are now a fixed 9-grid container.
    layout = "3行x3列"
    shots = script_json["shots"]
    grids = script_json.get("storyboard_grid_summary") or extract_storyboard_summary(script_json)
    active_count = effective_shot_count(script_json)
    panels: List[Dict[str, Any]] = []
    for idx in range(1, 10):
        if idx <= active_count:
            panels.append(build_panel_prompt(shots[idx - 1], grids[idx - 1], script_json, grid_index=idx, active_count=active_count, active=True))
        else:
            panels.append(build_panel_prompt({}, {}, script_json, grid_index=idx, active_count=active_count, active=False))
    return {
        "task_type": "UGC_9_GRID_STORYBOARD_DYNAMIC_SHOTS",
        "source_ugc03_record_id": ugc03_record_id,
        "layout": layout,
        "effective_shot_count": active_count,
        "inactive_grid_indices": [p["grid_index"] for p in panels if not p.get("active")],
        "panel_aspect_ratio": "9:16",
        "combined_canvas_aspect_ratio": "9:16",
        "layout_en": layout_en_name(layout),
        "global_style": {
            "visual_style": "realistic UGC smartphone video stills",
            "continuity": {
                "character": (script_json.get("video_setup") or {}).get("character_continuity") or (script_json.get("character_card") or {}).get("description") or "same person across all active panels",
                "product": (script_json.get("video_setup") or {}).get("product_continuity") or "same product packaging across all active panels",
                "pet": (script_json.get("video_setup") or {}).get("pet_continuity") or "same pet(s) across all active panels if present",
                "environment": (script_json.get("environment_card") or {}).get("description") or "same ordinary home environment",
            },
            "hard_constraints": [
                "Generate one combined 9-panel storyboard image on a 9:16 canvas.",
                "Each individual cell must be a vertical 9:16 video frame.",
                "Do not draw any borders, black frames, grid separator lines, gutters, panel outlines, margins, dividers, or comic-strip boxes between or around panels.",
                "Panels should touch edge-to-edge seamlessly; separation is only implied by the 3x3 layout, not by visible lines.",
                f"Only panels 1-{active_count} are active story panels; panels {active_count + 1}-9 must be plain pure white blank placeholders if any.",
                "No subtitles or text overlays inside the image.",
                "Active panels should be clear visual frames suitable for later image-to-video generation.",
                "Keep UGC realness; avoid polished advertising look.",
            ],
        },
        "panels": panels,
    }

def build_ugc04_fields(ugc03_record_id: str, script_json: Dict[str, Any], layout: str = "3行x3列") -> Dict[str, Any]:
    prompt_json = build_six_grid_prompt_json(ugc03_record_id, script_json, layout=layout)
    task_id = f"UGC-GRID-{datetime.now().strftime('%Y%m%d%H%M%S')}-{ugc03_record_id[-6:]}"
    return {
        "分镜任务ID": task_id,
        "关联脚本版本": [ugc03_record_id],
        "结构化脚本JSON": json_dumps(script_json),
        "6宫格提示词JSON": json_dumps(prompt_json),
        "6宫格生成状态": "待生成",
        "布局": "3行x3列",
        "错误信息": "",
    }


def find_config_record_id(token: str, stage_name: str) -> str:
    from common import TABLE_CONFIG, feishu_headers, safe_request

    all_items: List[Dict[str, Any]] = []
    page_token = None
    while True:
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{UGC_BASE_TOKEN}/tables/{TABLE_CONFIG}/records?page_size=100"
        if page_token:
            url += f"&page_token={page_token}"
        data = safe_request("get", url, headers=feishu_headers(token), timeout=20, max_attempts=3)
        all_items.extend(data.get("data", {}).get("items", []))
        if not data.get("data", {}).get("has_more"):
            break
        page_token = data.get("data", {}).get("page_token")
    for item in all_items:
        fields = item.get("fields", {})
        if extract_text(fields.get("环节")).strip() == stage_name:
            return item.get("record_id", "")
    return ""


def get_grid_model_config(token: str) -> Dict[str, str]:
    from common import TABLE_CONFIG

    rid = os.environ.get("UGC_GRID_CONFIG_RECORD_ID") or find_config_record_id(token, UGC_GRID_STAGE_NAME)
    if not rid:
        raise ValueError(f"未找到模型配置记录: {UGC_GRID_STAGE_NAME}")
    fields = get_ugc_record(token, TABLE_CONFIG, rid)
    return {
        "record_id": rid,
        "stage": extract_text(fields.get("环节")).strip(),
        "model": extract_text(fields.get("模型名称")).strip(),
        "api_key": extract_text(fields.get("API Key")).strip(),
        "api_base": extract_text(fields.get("API 代理地址")).strip().rstrip("/"),
        "prompt": extract_text(fields.get("提示词")).strip(),
        "method": extract_text(fields.get("调用方式")).strip(),
    }



def build_combined_image_prompt(prompt_json: Dict[str, Any]) -> str:
    layout = prompt_json.get("layout") or "3行x3列"
    global_style = prompt_json.get("global_style") or {}
    continuity = global_style.get("continuity") or {}
    hard_constraints = global_style.get("hard_constraints") or []
    panels = prompt_json.get("panels") or []
    canvas_ratio = prompt_json.get("combined_canvas_aspect_ratio") or layout_canvas_ratio(layout)
    layout_en = prompt_json.get("layout_en") or layout_en_name(layout)
    active_count = int(prompt_json.get("effective_shot_count") or len([p for p in panels if p.get("active")]) or 0)
    inactive = prompt_json.get("inactive_grid_indices") or [p.get("grid_index") for p in panels if not p.get("active")]
    lines = [
        "Create one single combined 9-panel UGC storyboard image.",
        f"Overall canvas: {canvas_ratio} ({layout_en}); this 3x3 grid naturally keeps every cell at 9:16.",
        "Each individual cell must be a vertical 9:16 smartphone video frame, so later cropping produces separate 9:16 images without distortion.",
        f"Layout: {layout}, nine edge-to-edge cells arranged in reading order 1 to 9; do not use visible separator lines.",
        f"Active story panels: 1-{active_count}. Inactive placeholder panels: {inactive or 'none'}.",
        "Inactive placeholder panels must be plain pure white blank cells. They must not contain people, pets, products, icons, shadows, textures, captions, or any visual content.",
        f"Global visual style for active panels: {global_style.get('visual_style') or 'realistic smartphone UGC stills'}.",
        "Continuity requirements for active panels:",
        f"- Character: {continuity.get('character') or 'same person across all active panels'}",
        f"- Product: {continuity.get('product') or 'same product packaging across all active panels'}",
        f"- Pet: {continuity.get('pet') or 'same pet if present'}",
        f"- Environment: {continuity.get('environment') or 'same ordinary home environment'}",
        "Hard constraints:",
    ]
    lines.extend(f"- {item}" for item in hard_constraints)
    lines.append("- Absolutely no subtitles, no captions, no text overlays, no labels, no UI, no watermarks.")
    lines.append("- Absolutely no borders, black frames, panel outlines, grid lines, separator lines, gutters, margins, comic-strip boxes, or divider strokes anywhere in the combined image.")
    lines.append("- Active panels must extend fully to their cell edges with normal image content; inactive panels must be pure white edge-to-edge.")
    lines.append("Panel details:")
    for panel in panels:
        status = "ACTIVE" if panel.get("active") else "INACTIVE WHITE PLACEHOLDER"
        lines.append(f"Panel {panel.get('grid_index')} [{status}]: {panel.get('image_prompt_en')}")
        if panel.get("negative_prompt_en"):
            lines.append(f"Avoid in panel {panel.get('grid_index')}: {panel.get('negative_prompt_en')}")
    return "\n".join(lines)

def extract_otu_result_url(data: Dict[str, Any]) -> str:
    candidates = [
        data.get("video_url"),
        data.get("result_url"),
        data.get("url"),
        data.get("download_url"),
    ]
    nested = data.get("data") if isinstance(data.get("data"), dict) else {}
    candidates.extend([nested.get("video_url"), nested.get("result_url"), nested.get("url"), nested.get("download_url")])
    for key in ("result_urls", "urls"):
        value = data.get(key) or nested.get(key)
        if isinstance(value, list) and value:
            candidates.append(value[0])
    for value in candidates:
        if isinstance(value, str) and value.startswith("http"):
            return value
    return ""


def call_otu_image_generation(config: Dict[str, str], prompt: str, *, metadata: Optional[Dict[str, Any]] = None, timeout_sec: int = 900, poll_interval: int = 10) -> Dict[str, Any]:
    api_key = config.get("api_key", "").strip()
    api_base = config.get("api_base", "").strip().rstrip("/")
    model = config.get("model", "").strip()
    if not api_key or not api_base or not model:
        raise ValueError("UGC 6宫格图片模型配置缺少 model/api_base/api_key")

    submit_metadata = {
        "aspectRatio": "9:16",
        "panelAspectRatio": "9:16",
        "urls": [],
    }
    if metadata:
        submit_metadata.update(metadata)
    submit_payload = {
        "model": model,
        "prompt": prompt,
        "metadata": submit_metadata,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    submit = requests.post(f"{api_base}/v1/videos", headers=headers, json=submit_payload, timeout=180)
    submit_text = submit.text[:3000]
    try:
        submit_data = submit.json()
    except Exception:
        submit_data = {"raw": submit_text}
    if submit.status_code >= 400:
        raise RuntimeError(f"OTU 6宫格图片任务提交失败 status={submit.status_code} body={submit_text[:500]}")
    task_id = submit_data.get("id") or submit_data.get("task_id") or (submit_data.get("data") or {}).get("id")
    if not task_id:
        # Some image-compatible routes may return the final URL synchronously.
        url = extract_otu_result_url(submit_data)
        if url:
            return {"task_id": "", "status": "completed", "result_url": url, "submit_response": submit_data, "poll_response": submit_data}
        raise RuntimeError(f"OTU 6宫格图片任务未返回 task id: {submit_text[:500]}")

    deadline = time.time() + timeout_sec
    last_data: Dict[str, Any] = {}
    while time.time() < deadline:
        poll = requests.get(f"{api_base}/v1/videos/{task_id}", headers={"Authorization": f"Bearer {api_key}"}, timeout=60)
        poll_text = poll.text[:3000]
        try:
            last_data = poll.json()
        except Exception:
            last_data = {"raw": poll_text}
        if poll.status_code >= 400:
            raise RuntimeError(f"OTU 6宫格图片任务查询失败 status={poll.status_code} body={poll_text[:500]}")
        status = str(last_data.get("status") or (last_data.get("data") or {}).get("status") or "").lower()
        result_url = extract_otu_result_url(last_data)
        if status in {"completed", "succeeded", "success"} or result_url:
            if not result_url:
                raise RuntimeError(f"OTU 6宫格图片任务完成但未返回图片地址: {json_dumps(last_data)[:500]}")
            return {"task_id": task_id, "status": status or "completed", "result_url": result_url, "submit_response": submit_data, "poll_response": last_data}
        if status in {"failed", "error", "cancelled", "canceled"}:
            raise RuntimeError(f"OTU 6宫格图片任务失败: {json_dumps(last_data)[:800]}")
        time.sleep(poll_interval)
    raise TimeoutError(f"OTU 6宫格图片任务超时（{timeout_sec}秒），任务ID: {task_id}，最后状态: {json_dumps(last_data)[:500]}")




def expected_panel_ratio(layout: str) -> float:
    return 9 / 16



def validate_six_grid_image_ratio(image_path: Path, layout: str, *, tolerance: float = 0.03) -> Dict[str, Any]:
    rows, cols = grid_dimensions(layout)
    with Image.open(image_path) as im:
        width, height = im.size
    panel_w = width / cols
    panel_h = height / rows
    panel_ratio = panel_w / panel_h
    expected = expected_panel_ratio(layout)
    total_ratio = width / height
    expected_total = cols * 9 / (rows * 16)
    delta = abs(panel_ratio - expected)
    total_delta = abs(total_ratio - expected_total)
    return {
        "image_size": [width, height],
        "layout": layout,
        "rows": rows,
        "cols": cols,
        "panel_size_estimate": [panel_w, panel_h],
        "panel_ratio": panel_ratio,
        "expected_panel_ratio": expected,
        "total_ratio": total_ratio,
        "expected_total_ratio": expected_total,
        "delta": delta,
        "total_delta": total_delta,
        "tolerance": tolerance,
        "ok": delta <= tolerance and total_delta <= tolerance,
    }


def grid_cells_for_image(width: int, height: int, layout: str) -> List[tuple[int, int, int, int]]:
    rows, cols = grid_dimensions(layout)
    cells: List[tuple[int, int, int, int]] = []
    for r in range(rows):
        for c in range(cols):
            left = round(c * width / cols)
            right = round((c + 1) * width / cols)
            top = round(r * height / rows)
            bottom = round((r + 1) * height / rows)
            cells.append((left, top, right, bottom))
    return cells


def force_inactive_cells_white(image_path: Path, prompt_json: Dict[str, Any], layout: str) -> Dict[str, Any]:
    inactive = [int(p.get("grid_index")) for p in (prompt_json.get("panels") or []) if isinstance(p, dict) and not p.get("active")]
    if not inactive:
        return {"inactive_grid_indices": [], "modified": False}
    with Image.open(image_path) as im:
        canvas = im.convert("RGB")
        cells = grid_cells_for_image(canvas.width, canvas.height, layout)
        for idx in inactive:
            if 1 <= idx <= len(cells):
                white = Image.new("RGB", (cells[idx - 1][2] - cells[idx - 1][0], cells[idx - 1][3] - cells[idx - 1][1]), (255, 255, 255))
                canvas.paste(white, (cells[idx - 1][0], cells[idx - 1][1]))
        canvas.save(image_path)
    return {"inactive_grid_indices": inactive, "modified": True}

def download_file(url: str, save_path: Path) -> None:
    r = requests.get(url, timeout=180, stream=True)
    r.raise_for_status()
    save_path.parent.mkdir(parents=True, exist_ok=True)
    with open(save_path, "wb") as f:
        for chunk in r.iter_content(8192):
            if chunk:
                f.write(chunk)
    if save_path.stat().st_size < 1024:
        raise RuntimeError(f"下载图片过小，疑似失败: {save_path.stat().st_size} bytes")


def run_prepare(
    ugc03_record_id: str,
    *,
    write: bool = False,
    token: Optional[str] = None,
    layout: str = "3行x3列",
    get_record_fn: RecordGetter = get_ugc_record,
    create_record_fn: RecordCreator = create_ugc_record,
    update_record_fn: RecordUpdater = update_ugc_record,
    candidate_group_id: str = "",
    candidate_index: int = 0,
    reroll_source_record_id: str = "",
) -> Dict[str, Any]:
    token = token or get_feishu_token()
    table_ids = load_ugc_table_ids()
    ugc03_table = table_ids["ugc_03_script_version"]
    ugc04_table = table_ids["ugc_04_six_grid_storyboard"]
    ugc03_fields = get_record_fn(token, ugc03_table, ugc03_record_id)
    script_json = parse_script_json(ugc03_fields)
    ugc04_fields = build_ugc04_fields(ugc03_record_id, script_json, layout=layout)
    if candidate_group_id and candidate_index:
        ugc04_fields.update(build_candidate_fields(candidate_group_id, candidate_index, source_record_id=reroll_source_record_id))
        ugc04_fields["重生成备注"] = f"UGC-04 reroll candidate {candidate_index}; source={reroll_source_record_id or 'initial'}"
    result = {
        "ugc03_record_id": ugc03_record_id,
        "dry_run": not write,
        "tables": {"ugc03": ugc03_table, "ugc04": ugc04_table},
        "ugc04_fields": ugc04_fields,
        "panel_count": len(json.loads(ugc04_fields["6宫格提示词JSON"])["panels"]),
    }
    if write:
        ugc04_record_id = create_record_fn(token, ugc04_table, ugc04_fields)
        update_record_fn(token, ugc03_table, ugc03_record_id, {"下游推进状态": "分镜中"})
        result["written"] = True
        result["ugc04_record_id"] = ugc04_record_id
    else:
        result["written"] = False
    return result


def run_image_generation(
    ugc04_record_id: str,
    *,
    call_image: bool = False,
    write: bool = False,
    token: Optional[str] = None,
    get_record_fn: RecordGetter = get_ugc_record,
    update_record_fn: RecordUpdater = update_ugc_record,
    image_caller: ImageCaller = call_otu_image_generation,
    uploader: Uploader = upload_image_to_feishu,
) -> Dict[str, Any]:
    token = token or get_feishu_token()
    table_ids = load_ugc_table_ids()
    ugc04_table = table_ids["ugc_04_six_grid_storyboard"]
    fields = get_record_fn(token, ugc04_table, ugc04_record_id)
    prompt_json = parse_grid_prompt_json(fields)
    layout = prompt_json.get("layout") or extract_text(fields.get("布局")).strip() or "3行x3列"
    prompt = build_combined_image_prompt(prompt_json)
    canvas_ratio = prompt_json.get("combined_canvas_aspect_ratio") or layout_canvas_ratio(layout)
    image_metadata = {"aspectRatio": canvas_ratio, "panelAspectRatio": "9:16", "urls": []}
    config = get_grid_model_config(token)
    result: Dict[str, Any] = {
        "ugc04_record_id": ugc04_record_id,
        "dry_run": not call_image,
        "write": write,
        "config": {"record_id": config.get("record_id"), "stage": config.get("stage"), "model": config.get("model"), "api_base": config.get("api_base"), "method": config.get("method")},
        "prompt_chars": len(prompt),
        "panel_count": len(prompt_json.get("panels") or []),
        "image_metadata": image_metadata,
    }
    if not call_image:
        result["image_prompt"] = prompt
        result["written"] = False
        return result

    if write:
        update_record_fn(token, ugc04_table, ugc04_record_id, {"6宫格生成状态": "生成中", "错误信息": ""})
    try:
        try:
            image_result = image_caller(config, prompt, metadata=image_metadata)
        except TypeError:
            image_result = image_caller(config, prompt)
        result.update({
            "task_id": image_result.get("task_id"),
            "status": image_result.get("status"),
            "result_url": image_result.get("result_url"),
        })
        task_dir = BASE_WORK_DIR / ugc04_record_id
        image_path = task_dir / f"{ugc04_record_id}_six_grid.png"
        download_file(str(image_result["result_url"]), image_path)
        white_fill = force_inactive_cells_white(image_path, prompt_json, layout)
        result["white_fill"] = white_fill
        result["local_image_path"] = str(image_path)
        result["local_image_bytes"] = image_path.stat().st_size
        ratio_check = validate_six_grid_image_ratio(image_path, layout)
        result["ratio_check"] = ratio_check
        if not ratio_check["ok"]:
            raise ValueError(
                "9宫格容器图片比例校验失败："
                f"image_size={ratio_check['image_size']} layout={layout} "
                f"panel_ratio={ratio_check['panel_ratio']:.4f}, expected={ratio_check['expected_panel_ratio']:.4f}. "
                "裁切后单格不会是 9:16。"
            )
        if write:
            file_token = uploader(token, str(image_path), image_path.name)
            result["file_token"] = file_token
            try:
                update_record_fn(token, ugc04_table, ugc04_record_id, {
                    "6宫格生成状态": "成功",
                    "6宫格图片": [{"file_token": file_token, "name": image_path.name}],
                    "6宫格图片URL": str(image_result.get("result_url") or image_path),
                    "6宫格图片file_token": file_token,
                    "错误信息": "",
                })
                result["attachment_written"] = True
            except Exception as attach_exc:
                # Some Feishu attachment fields may be configured as scan-only
                # (UploadAttachNotAllowed). Preserve the generated asset through
                # machine-readable fallback fields instead of losing the run.
                update_record_fn(token, ugc04_table, ugc04_record_id, {
                    "6宫格生成状态": "成功",
                    "6宫格图片URL": str(image_result.get("result_url") or image_path),
                    "6宫格图片file_token": file_token,
                    "错误信息": f"附件字段6宫格图片未写入：{str(attach_exc)[:300]}；真实图片已生成，URL/file_token已写入文本字段。",
                })
                result["attachment_written"] = False
                result["attachment_write_error"] = str(attach_exc)[:500]
            result["written"] = True
        else:
            result["written"] = False
        return result
    except Exception as exc:
        if write:
            update_record_fn(token, ugc04_table, ugc04_record_id, {"6宫格生成状态": "失败", "错误信息": str(exc)[:500]})
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="UGC-04 9宫格容器分镜任务准备/出图。默认 dry-run，不创建记录、不调用模型。")
    sub = parser.add_subparsers(dest="command")

    prepare = sub.add_parser("prepare", help="从 UGC-03 创建/预览 UGC-04 任务")
    prepare.add_argument("record_id", help="UGC-03 record_id")
    prepare.add_argument("--write", action="store_true", help="创建 UGC-04 任务记录并推进 UGC-03 下游状态")
    prepare.add_argument("--layout", default="3行x3列", choices=["3行x3列"], help="9宫格容器布局")
    prepare.add_argument("--candidate-group-id", default="", help="重生成候选组 ID；用于创建新的 UGC-04 候选记录")
    prepare.add_argument("--candidate-index", type=int, default=0, help="重生成候选序号")
    prepare.add_argument("--reroll-source-record-id", default="", help="本次重生成来源 UGC-04 record_id")
    prepare.add_argument("--output-file", help="保存运行结果 JSON")

    image = sub.add_parser("image", help="对 UGC-04 任务生成/预览 6宫格图片")
    image.add_argument("record_id", help="UGC-04 record_id")
    image.add_argument("--call-image", action="store_true", help="真实调用 OTU 生成 9宫格容器图片")
    image.add_argument("--write", action="store_true", help="写回 UGC-04 状态和图片附件；需配合 --call-image")
    image.add_argument("--output-file", help="保存运行结果 JSON")

    # Backward compatible: `python tk_ugc_six_grid.py <UGC-03> --write` means prepare.
    parser.add_argument("legacy_record_id", nargs="?", help=argparse.SUPPRESS)
    parser.add_argument("--write", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--layout", default="3行x3列", choices=["3行x3列"], help=argparse.SUPPRESS)
    parser.add_argument("--output-file", help=argparse.SUPPRESS)

    args = parser.parse_args()
    if args.command == "prepare":
        result = run_prepare(
            args.record_id,
            write=args.write,
            layout=args.layout,
            candidate_group_id=args.candidate_group_id,
            candidate_index=args.candidate_index,
            reroll_source_record_id=args.reroll_source_record_id,
        )
        output_file = args.output_file
    elif args.command == "image":
        if args.write and not args.call_image:
            raise SystemExit("--write 必须配合 --call-image，避免空写回")
        result = run_image_generation(args.record_id, call_image=args.call_image, write=args.write)
        output_file = args.output_file
    elif args.legacy_record_id:
        result = run_prepare(args.legacy_record_id, write=args.write, layout=args.layout)
        output_file = args.output_file
    else:
        parser.print_help()
        return 2

    text = json_dumps(result)
    print(text)
    if output_file:
        Path(output_file).write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
