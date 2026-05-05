#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import requests
from PIL import Image, ImageFilter

from ugc_config import UGC_BASE_TOKEN, load_ugc_table_ids
from ugc_utils import extract_linked_record_ids, extract_text, first_present
from tk_ugc_six_grid import (
    GRID_IMAGE_FIELD,
    GRID_IMAGE_TOKEN_FIELD,
    GRID_IMAGE_URL_FIELD,
    GRID_STATUS_FIELD,
    LEGACY_GRID_IMAGE_FIELD,
    LEGACY_GRID_IMAGE_TOKEN_FIELD,
    LEGACY_GRID_IMAGE_URL_FIELD,
    LEGACY_GRID_STATUS_FIELD,
    call_otu_image_generation,
    create_ugc_record,
    find_config_record_id,
    get_feishu_token,
    get_ugc_record,
    json_dumps,
    parse_grid_prompt_json,
    parse_json_object,
    update_ugc_record,
    upload_image_to_feishu,
)

LINKED_GRID_FIELD = "关联9宫格任务"
LEGACY_LINKED_GRID_FIELD = "关联6宫格任务"

BASE_WORK_DIR = Path(__file__).resolve().parent / "workspace_ryan" / "ugc_shot_image_work"
ENHANCE_STAGE_NAME = "UGC-分镜图片高清化"

RecordGetter = Callable[[str, str, str], Dict[str, Any]]
RecordCreator = Callable[[str, str, Dict[str, Any]], str]
RecordUpdater = Callable[[str, str, str, Dict[str, Any]], Any]
Uploader = Callable[[str, str, str], str]


def get_attachment_token(value: Any) -> str:
    if isinstance(value, list) and value:
        first = value[0]
        if isinstance(first, dict):
            return str(first.get("file_token") or "")
    return ""


def download_feishu_media(token: str, file_token: str, save_path: Path) -> None:
    from common import feishu_headers

    url = f"https://open.feishu.cn/open-apis/drive/v1/medias/{file_token}/download"
    resp = requests.get(url, headers=feishu_headers(token), timeout=180, stream=True)
    resp.raise_for_status()
    save_path.parent.mkdir(parents=True, exist_ok=True)
    with open(save_path, "wb") as f:
        for chunk in resp.iter_content(8192):
            if chunk:
                f.write(chunk)
    if save_path.stat().st_size < 1024:
        raise RuntimeError(f"下载9宫格图片过小，疑似失败: {save_path.stat().st_size} bytes")


def resolve_six_grid_image_path(token: str, ugc04_record_id: str, fields: Dict[str, Any], *, downloader: Callable[[str, str, Path], None] = download_feishu_media) -> Path:
    work_dir = BASE_WORK_DIR / ugc04_record_id
    local_hint = extract_text(first_present(fields, [GRID_IMAGE_URL_FIELD, LEGACY_GRID_IMAGE_URL_FIELD])).strip()
    if local_hint and local_hint.startswith("/"):
        p = Path(local_hint)
        if p.exists() and p.stat().st_size >= 1024:
            return p
    attachment_token = get_attachment_token(first_present(fields, [GRID_IMAGE_FIELD, LEGACY_GRID_IMAGE_FIELD])) or extract_text(first_present(fields, [GRID_IMAGE_TOKEN_FIELD, LEGACY_GRID_IMAGE_TOKEN_FIELD])).strip()
    if attachment_token:
        p = work_dir / f"{ugc04_record_id}_six_grid.png"
        downloader(token, attachment_token, p)
        return p
    raise ValueError("UGC-04 缺少可用的9宫格图片附件/file_token/本地路径")



def grid_dimensions(layout: str) -> Tuple[int, int]:
    if layout == "3行x3列":
        return 3, 3
    if layout == "3行x2列":
        return 3, 2
    if layout == "2行x3列":
        return 2, 3
    raise ValueError(f"不支持的宫格布局: {layout}")


def grid_cells(width: int, height: int, layout: str) -> List[Tuple[int, int, int, int]]:
    rows, cols = grid_dimensions(layout)
    cells: List[Tuple[int, int, int, int]] = []
    for r in range(rows):
        for c in range(cols):
            left = round(c * width / cols)
            right = round((c + 1) * width / cols)
            top = round(r * height / rows)
            bottom = round((r + 1) * height / rows)
            cells.append((left, top, right, bottom))
    return cells


def active_panel_indices_from_prompt(prompt_json: Dict[str, Any], shot_count: int) -> List[int]:
    panels = prompt_json.get("panels") if isinstance(prompt_json, dict) else None
    if isinstance(panels, list):
        active = [int(p.get("grid_index")) for p in panels if isinstance(p, dict) and p.get("active")]
        if active:
            return active
    return list(range(1, shot_count + 1))

def inset_cell_box(box: Tuple[int, int, int, int], *, inset_ratio: float = 0.012, min_inset_px: int = 2) -> Tuple[int, int, int, int]:
    """Shrink a grid cell box inward to remove model-generated grid lines/borders.

    9-grid storyboard models often draw visible black separators even when told not
    to. Cropping exactly at cell boundaries preserves those separators as black
    frames around downstream shot images. This inset is deliberately tiny
    (~1.2% per side, at least 2px) so content remains intact while border pixels
    are discarded before UGC-06 video generation.
    """
    left, top, right, bottom = box
    w = max(0, right - left)
    h = max(0, bottom - top)
    inset_x = max(min_inset_px, round(w * inset_ratio))
    inset_y = max(min_inset_px, round(h * inset_ratio))
    if w <= inset_x * 2 + 2 or h <= inset_y * 2 + 2:
        return box
    return (left + inset_x, top + inset_y, right - inset_x, bottom - inset_y)


def crop_six_grid(image_path: Path, output_dir: Path, layout: str, *, trim_borders: bool = True) -> List[Dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    with Image.open(image_path) as im:
        width, height = im.size
        cells = grid_cells(width, height, layout)
        outputs: List[Dict[str, Any]] = []
        for idx, raw_box in enumerate(cells, start=1):
            box = inset_cell_box(raw_box) if trim_borders else raw_box
            crop = im.crop(box)
            out = output_dir / f"shot_{idx:02d}.png"
            crop.save(out)
            outputs.append({
                "shot_index": idx,
                "path": str(out),
                "bytes": out.stat().st_size,
                "box": list(box),
                "raw_box": list(raw_box),
                "border_trimmed": bool(trim_borders and box != raw_box),
                "size": list(crop.size),
            })
        return outputs



def extract_shots(script_json: Dict[str, Any]) -> List[Dict[str, Any]]:
    shots = script_json.get("shots")
    count = script_json.get("effective_shot_count") or script_json.get("optimal_shot_count") or script_json.get("shot_count")
    if count is None and isinstance(shots, list):
        count = len(shots)
    try:
        count_int = int(count)
    except Exception:
        count_int = 0
    if count_int < 1 or count_int > 9:
        raise ValueError("结构化脚本JSON 有效镜头数必须在 1-9 之间")
    if not isinstance(shots, list) or len(shots) != count_int:
        raise ValueError(f"结构化脚本JSON.shots 必须等于有效镜头数 {count_int}")
    return shots

def make_vertical_916_image(source_path: Path, output_path: Path, *, size: Tuple[int, int] = (1080, 1920)) -> Dict[str, Any]:
    """Create a 9:16 vertical frame from a cropped panel without distorting the source.

    The source crop is fitted into the canvas. A blurred cover-fill version of the
    same image is used as background so downstream image-to-video has a vertical
    first frame while preserving the generated storyboard content.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source_path) as im:
        src = im.convert("RGB")
        canvas_w, canvas_h = size
        bg_scale = max(canvas_w / src.width, canvas_h / src.height)
        bg_size = (max(1, round(src.width * bg_scale)), max(1, round(src.height * bg_scale)))
        bg = src.resize(bg_size, Image.LANCZOS)
        bg_left = (bg.width - canvas_w) // 2
        bg_top = (bg.height - canvas_h) // 2
        bg = bg.crop((bg_left, bg_top, bg_left + canvas_w, bg_top + canvas_h)).filter(ImageFilter.GaussianBlur(radius=28))
        overlay = Image.new("RGB", size, (0, 0, 0))
        overlay.paste(bg)
        fit_scale = min(canvas_w / src.width, canvas_h / src.height)
        fit_size = (max(1, round(src.width * fit_scale)), max(1, round(src.height * fit_scale)))
        fg = src.resize(fit_size, Image.LANCZOS)
        left = (canvas_w - fg.width) // 2
        top = (canvas_h - fg.height) // 2
        overlay.paste(fg, (left, top))
        overlay.save(output_path, quality=95)
        return {
            "path": str(output_path),
            "bytes": output_path.stat().st_size,
            "size": [canvas_w, canvas_h],
            "source_size": [src.width, src.height],
            "fit_box": [left, top, left + fg.width, top + fg.height],
        }




def get_tmp_download_url(token: str, file_token: str) -> str:
    from common import feishu_headers

    url = f"https://open.feishu.cn/open-apis/drive/v1/medias/batch_get_tmp_download_url?file_tokens={file_token}"
    resp = requests.get(url, headers=feishu_headers(token), timeout=60)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"飞书临时下载 URL 获取失败: {data}")
    items = data.get("data", {}).get("tmp_download_urls") or []
    if isinstance(items, dict):
        tmp = items.get(file_token) or items.get("tmp_download_url") or ""
    elif items:
        tmp = items[0].get("tmp_download_url") or items[0].get("url") or ""
    else:
        tmp = ""
    if not tmp:
        raise RuntimeError("飞书临时下载 URL 为空")
    return tmp


def get_enhance_model_config(token: str) -> Dict[str, str]:
    from common import TABLE_CONFIG

    rid = find_config_record_id(token, ENHANCE_STAGE_NAME)
    if not rid:
        raise ValueError(f"未找到模型配置记录: {ENHANCE_STAGE_NAME}")
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


def build_enhance_prompt(shot: Dict[str, Any], crop_info: Dict[str, Any], active_count: int) -> str:
    shot_index = int(crop_info["shot_index"])
    compact = {
        "shot_index": shot.get("shot_index") or shot_index,
        "content_type": shot.get("content_type") or "",
        "scene": shot.get("scene") or "",
        "visual_description": shot.get("visual_description") or shot.get("image_generation_focus") or "",
        "subject_action": shot.get("subject_action") or "",
        "product_exposure_method": shot.get("product_exposure_method") or shot.get("product_presence") or "",
        "environment_details": shot.get("environment_details") or "",
        "speaker_visible": shot.get("speaker_visible"),
    }
    return (
        "Enhance/redraw this exact UGC storyboard panel into a sharp 1080x1920 vertical first frame.\n"
        "Reference image 1 is the cropped panel and is the PRIMARY composition reference.\n"
        "Reference image 2 is the full 3x3 9-grid storyboard and is the continuity reference.\n"
        f"This is active story panel {shot_index}/{active_count}. Keep the same person, pet, product, room, camera angle, pose, and story moment.\n"
        "Do not create a new scene. Do not change the identity, product packaging, pet breed/color, room layout, camera angle, or action.\n"
        "Do not add borders, black frames, grid lines, separator lines, captions, text, UI, watermarks, poster design, or adjacent panels.\n"
        "Improve clarity, facial/detail sharpness, product/pet detail, natural lighting, and realistic smartphone UGC texture.\n"
        "Preserve the original composition as much as possible; only cleanly redraw/upscale the panel.\n"
        "Compact semantic constraints for disambiguation only, not for inventing new content:\n"
        + json.dumps(compact, ensure_ascii=False)
    )


def download_url(url: str, save_path: Path) -> None:
    resp = requests.get(url, timeout=180)
    resp.raise_for_status()
    save_path.parent.mkdir(parents=True, exist_ok=True)
    save_path.write_bytes(resp.content)
    if save_path.stat().st_size < 1024:
        raise RuntimeError(f"下载高清重绘图片过小，疑似失败: {save_path.stat().st_size} bytes")


def enhance_shot_image_with_repaint(
    token: str,
    crop_path: Path,
    grid_image_path: Path,
    shot: Dict[str, Any],
    crop_info: Dict[str, Any],
    output_path: Path,
    *,
    active_count: int,
    config: Optional[Dict[str, str]] = None,
    uploader: Uploader = upload_image_to_feishu,
) -> Dict[str, Any]:
    config = config or get_enhance_model_config(token)
    crop_ref_token = uploader(token, str(crop_path), crop_path.name)
    grid_ref_token = uploader(token, str(grid_image_path), grid_image_path.name)
    crop_url = get_tmp_download_url(token, crop_ref_token)
    grid_url = get_tmp_download_url(token, grid_ref_token)
    prompt = build_enhance_prompt(shot, crop_info, active_count)
    result = call_otu_image_generation(
        config,
        prompt,
        metadata={
            "aspectRatio": "9:16",
            "panelAspectRatio": "9:16",
            "outputFormat": "png",
            "urls": [crop_url, grid_url],
        },
        timeout_sec=900,
        poll_interval=10,
    )
    repaint_url = result.get("result_url") or ""
    repaint_path = output_path.with_name(output_path.stem + "_repaint.png")
    download_url(repaint_url, repaint_path)
    fit_info = make_vertical_916_image(repaint_path, output_path)
    with Image.open(repaint_path) as im:
        repaint_size = list(im.size)
    return {
        "method": "otu_reference_repaint",
        "config_record_id": config.get("record_id"),
        "model": config.get("model"),
        "task_id": result.get("task_id"),
        "result_url": repaint_url,
        "reference_file_tokens": {"crop": crop_ref_token, "grid": grid_ref_token},
        "repaint_path": str(repaint_path),
        "repaint_size": repaint_size,
        "final_path": str(output_path),
        "final_info": fit_info,
    }


def build_ugc05_fields(
    ugc04_record_id: str,
    ugc03_record_id: str,
    shot: Dict[str, Any],
    crop_info: Dict[str, Any],
    file_token: str = "",
    ugc04_fields: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    shot_index = int(crop_info["shot_index"])
    fields: Dict[str, Any] = {
        "分镜图片ID": f"UGC-SHOT-{datetime.now().strftime('%Y%m%d%H%M%S')}-{ugc04_record_id[-6:]}-{shot_index:02d}",
        LINKED_GRID_FIELD: [ugc04_record_id],
        "关联脚本版本": [ugc03_record_id] if ugc03_record_id else [],
        "分镜序号": shot_index,
        "对应脚本片段JSON": json_dumps(shot),
        "裁切状态": "成功",
        "高清化状态": "待高清化",
        "原始裁切图片路径": crop_info["path"],
        "原始裁切图片file_token": file_token,
        "错误信息": "",
        "分镜图审核状态": "待确认",
        "分镜图操作": "不触发",
        "高清图审核状态": "",
        "高清图操作": "不触发",
        "分镜图执行状态": "",
        "分镜图执行结果": "",
    }
    if file_token:
        fields["原始裁切图片"] = [{"file_token": file_token, "name": Path(crop_info["path"]).name}]
    return fields


def linked_to_ugc04(fields: Dict[str, Any], ugc04_record_id: str) -> bool:
    return ugc04_record_id in extract_linked_record_ids(first_present(fields, [LINKED_GRID_FIELD, LEGACY_LINKED_GRID_FIELD]))


def shot_index_value(fields: Dict[str, Any]) -> int:
    raw = fields.get("分镜序号")
    if isinstance(raw, list) and raw:
        raw = raw[0]
    if isinstance(raw, dict):
        raw = raw.get("text") or raw.get("value") or raw.get("name")
    try:
        return int(float(raw))
    except Exception:
        return 0


def find_existing_ugc05_by_shot(
    records: Iterable[Dict[str, Any]],
    *,
    ugc04_record_id: str,
) -> Dict[int, str]:
    by_shot: Dict[int, str] = {}
    for record in records:
        fields = record.get("fields") or {}
        if not linked_to_ugc04(fields, ugc04_record_id):
            continue
        idx = shot_index_value(fields)
        record_id = record.get("record_id") or ""
        if idx and record_id and idx not in by_shot:
            by_shot[idx] = record_id
    return by_shot


def list_ugc05_records(token: str, table_id: str) -> List[Dict[str, Any]]:
    from tk_ugc_reroll import list_ugc_records

    return list_ugc_records(token, table_id, page_size=500)


def load_ugc05_context(
    ugc05_record_id: str,
    *,
    token: str,
    get_record_fn: RecordGetter = get_ugc_record,
    downloader: Callable[[str, str, Path], None] = download_feishu_media,
) -> Dict[str, Any]:
    table_ids = load_ugc_table_ids()
    ugc04_table = table_ids["ugc_04_six_grid_storyboard"]
    ugc05_table = table_ids["ugc_05_shot_images"]
    fields05 = get_record_fn(token, ugc05_table, ugc05_record_id)
    ugc04_ids = extract_linked_record_ids(first_present(fields05, [LINKED_GRID_FIELD, LEGACY_LINKED_GRID_FIELD]))
    if len(ugc04_ids) != 1:
        raise ValueError(f"UGC-05 {ugc05_record_id} 必须且只能关联 1 条 UGC-04，actual={ugc04_ids}")
    ugc04_record_id = ugc04_ids[0]
    fields04 = get_record_fn(token, ugc04_table, ugc04_record_id)
    script_json = parse_json_object(fields04.get("结构化脚本JSON"), "UGC-04.结构化脚本JSON")
    shots = extract_shots(script_json)
    shot_index = shot_index_value(fields05)
    if shot_index < 1 or shot_index > len(shots):
        raise ValueError(f"UGC-05 {ugc05_record_id}.分镜序号无效: {shot_index}")
    crop_path_text = extract_text(fields05.get("原始裁切图片路径")).strip()
    if crop_path_text and Path(crop_path_text).exists():
        crop_path = Path(crop_path_text)
    else:
        token_text = extract_text(fields05.get("原始裁切图片file_token")).strip() or get_attachment_token(fields05.get("原始裁切图片"))
        if not token_text:
            raise ValueError(f"UGC-05 {ugc05_record_id} 缺少原始裁切图片路径/file_token")
        crop_path = BASE_WORK_DIR / ugc04_record_id / "crops" / f"shot_{shot_index:02d}.png"
        downloader(token, token_text, crop_path)
    grid_path = resolve_six_grid_image_path(token, ugc04_record_id, fields04, downloader=downloader)
    return {
        "table_ids": table_ids,
        "ugc04_record_id": ugc04_record_id,
        "fields04": fields04,
        "fields05": fields05,
        "script_json": script_json,
        "shots": shots,
        "shot_index": shot_index,
        "crop_path": crop_path,
        "grid_path": grid_path,
        "crop_info": {"shot_index": shot_index, "path": str(crop_path)},
    }


def enhance_existing_ugc05_record(
    ugc05_record_id: str,
    *,
    write: bool = False,
    token: Optional[str] = None,
    get_record_fn: RecordGetter = get_ugc_record,
    update_record_fn: RecordUpdater = update_ugc_record,
    uploader: Uploader = upload_image_to_feishu,
    downloader: Callable[[str, str, Path], None] = download_feishu_media,
) -> Dict[str, Any]:
    token = token or get_feishu_token()
    table_ids = load_ugc_table_ids()
    ugc05_table = table_ids["ugc_05_shot_images"]
    ctx = load_ugc05_context(ugc05_record_id, token=token, get_record_fn=get_record_fn, downloader=downloader)
    ugc04_record_id = ctx["ugc04_record_id"]
    shots = ctx["shots"]
    shot_index = ctx["shot_index"]
    crop_path = ctx["crop_path"]
    grid_path = ctx["grid_path"]
    crop_info = ctx["crop_info"]
    output_path = BASE_WORK_DIR / ugc04_record_id / "enhanced_repaint_916" / f"shot_{shot_index:02d}_916.png"
    result: Dict[str, Any] = {
        "ugc05_record_id": ugc05_record_id,
        "ugc04_record_id": ugc04_record_id,
        "shot_index": shot_index,
        "dry_run": not write,
        "crop_path": str(crop_path),
        "grid_path": str(grid_path),
    }
    if not write:
        result["prompt"] = build_enhance_prompt(shots[shot_index - 1], crop_info, len(shots))
        return result
    enhance_info = enhance_shot_image_with_repaint(
        token,
        crop_path,
        grid_path,
        shots[shot_index - 1],
        crop_info,
        output_path,
        active_count=len(shots),
        uploader=uploader,
    )
    enhanced_token = uploader(token, str(output_path), output_path.name)
    update_record_fn(token, ugc05_table, ugc05_record_id, {
        "高清分镜图": [{"file_token": enhanced_token, "name": output_path.name}],
        "高清分镜图路径": str(output_path),
        "高清分镜图file_token": enhanced_token,
        "高清化状态": "成功",
        "高清图审核状态": "待确认",
        "高清图操作": "不触发",
        "错误信息": "高清图由 OTU 参考重绘生成：crop 为主构图参考，9宫格为一致性参考；已适配为 1080x1920。",
    })
    result.update(enhance_info)
    result["file_token"] = enhanced_token
    result["written"] = True
    return result


def regenerate_single_ugc05_shot(
    ugc05_record_id: str,
    *,
    write: bool = False,
    token: Optional[str] = None,
    get_record_fn: RecordGetter = get_ugc_record,
    update_record_fn: RecordUpdater = update_ugc_record,
    uploader: Uploader = upload_image_to_feishu,
    downloader: Callable[[str, str, Path], None] = download_feishu_media,
) -> Dict[str, Any]:
    token = token or get_feishu_token()
    table_ids = load_ugc_table_ids()
    ugc05_table = table_ids["ugc_05_shot_images"]
    ctx = load_ugc05_context(ugc05_record_id, token=token, get_record_fn=get_record_fn, downloader=downloader)
    ugc04_record_id = ctx["ugc04_record_id"]
    shots = ctx["shots"]
    shot_index = ctx["shot_index"]
    crop_path = ctx["crop_path"]
    grid_path = ctx["grid_path"]
    crop_info = ctx["crop_info"]
    output_path = BASE_WORK_DIR / ugc04_record_id / "single_shot_regen" / f"shot_{shot_index:02d}_regen.png"
    result: Dict[str, Any] = {
        "ugc05_record_id": ugc05_record_id,
        "ugc04_record_id": ugc04_record_id,
        "shot_index": shot_index,
        "dry_run": not write,
        "crop_path": str(crop_path),
        "grid_path": str(grid_path),
    }
    if not write:
        result["prompt"] = build_enhance_prompt(shots[shot_index - 1], crop_info, len(shots))
        return result
    output_path.parent.mkdir(parents=True, exist_ok=True)
    repaint_info = enhance_shot_image_with_repaint(
        token,
        crop_path,
        grid_path,
        shots[shot_index - 1],
        crop_info,
        output_path,
        active_count=len(shots),
        uploader=uploader,
    )
    file_token = uploader(token, str(output_path), output_path.name)
    update_record_fn(token, ugc05_table, ugc05_record_id, {
        "原始裁切图片": [{"file_token": file_token, "name": output_path.name}],
        "原始裁切图片路径": str(output_path),
        "原始裁切图片file_token": file_token,
        "裁切状态": "成功",
        "分镜图审核状态": "待确认",
        "分镜图操作": "不触发",
        "高清化状态": "待高清化",
        "高清图审核状态": "",
        "高清图操作": "不触发",
        "高清分镜图路径": "",
        "高清分镜图file_token": "",
        "错误信息": "单张分镜图由 OTU 参考重绘生成：以原裁切图为主构图参考，9宫格为一致性参考；请重新审核分镜图。",
    })
    result.update(repaint_info)
    result["file_token"] = file_token
    result["written"] = True
    return result


def create_or_preview_shot_records(
    ugc04_record_id: str,
    *,
    write: bool = False,
    token: Optional[str] = None,
    get_record_fn: RecordGetter = get_ugc_record,
    create_record_fn: RecordCreator = create_ugc_record,
    update_record_fn: RecordUpdater = update_ugc_record,
    uploader: Uploader = upload_image_to_feishu,
    downloader: Callable[[str, str, Path], None] = download_feishu_media,
    enhance: bool = False,
    overwrite_existing: bool = False,
    existing_records: Optional[Iterable[Dict[str, Any]]] = None,
    list_records_fn: Callable[[str, str], List[Dict[str, Any]]] = list_ugc05_records,
) -> Dict[str, Any]:
    token = token or get_feishu_token()
    table_ids = load_ugc_table_ids()
    ugc04_table = table_ids["ugc_04_six_grid_storyboard"]
    ugc05_table = table_ids["ugc_05_shot_images"]
    fields04 = get_record_fn(token, ugc04_table, ugc04_record_id)
    if extract_text(first_present(fields04, [GRID_STATUS_FIELD, LEGACY_GRID_STATUS_FIELD])).strip() != "成功":
        raise ValueError("UGC-04.9宫格生成状态 必须为 成功 才能进入 UGC-05")
    layout = extract_text(fields04.get("布局")).strip() or "3行x3列"
    script_json = parse_json_object(fields04.get("结构化脚本JSON"), "UGC-04.结构化脚本JSON")
    shots = extract_shots(script_json)
    prompt_json: Dict[str, Any] = {}
    try:
        prompt_json = parse_grid_prompt_json(fields04)
    except Exception:
        prompt_json = {}
    active_indices = active_panel_indices_from_prompt(prompt_json, len(shots))
    ugc03_ids = extract_linked_record_ids(fields04.get("关联脚本版本"))
    ugc03_record_id = ugc03_ids[0] if ugc03_ids else ""
    image_path = resolve_six_grid_image_path(token, ugc04_record_id, fields04, downloader=downloader)
    crop_dir = BASE_WORK_DIR / ugc04_record_id / "crops"
    crops = crop_six_grid(image_path, crop_dir, layout)
    active_crops = [crops[idx - 1] for idx in active_indices if 1 <= idx <= len(crops)]
    if len(active_crops) != len(shots):
        raise ValueError(f"有效裁切图数量 {len(active_crops)} 与脚本镜头数 {len(shots)} 不一致")

    result: Dict[str, Any] = {
        "ugc04_record_id": ugc04_record_id,
        "ugc03_record_id": ugc03_record_id,
        "dry_run": not write,
        "layout": layout,
        "source_image_path": str(image_path),
        "shot_count": len(active_crops),
        "total_grid_cell_count": len(crops),
        "active_grid_indices": active_indices,
        "crops": active_crops,
        "all_crops": crops,
        "created_records": [],
        "enhanced_records": [],
        "written": False,
    }
    if not write:
        result["preview_fields"] = [build_ugc05_fields(ugc04_record_id, ugc03_record_id, shots[i], active_crops[i], ugc04_fields=fields04) for i in range(len(shots))]
        return result

    created: List[Dict[str, Any]] = []
    enhanced: List[Dict[str, Any]] = []
    existing_by_shot: Dict[int, str] = {}
    if overwrite_existing:
        records_for_match = list(existing_records) if existing_records is not None else list_records_fn(token, ugc05_table)
        existing_by_shot = find_existing_ugc05_by_shot(records_for_match, ugc04_record_id=ugc04_record_id)
    enhance_config = get_enhance_model_config(token) if enhance else None
    enhance_dir = BASE_WORK_DIR / ugc04_record_id / "enhanced_repaint_916"
    for i, crop in enumerate(active_crops):
        file_token = uploader(token, crop["path"], Path(crop["path"]).name)
        record_fields = build_ugc05_fields(ugc04_record_id, ugc03_record_id, shots[i], crop, file_token=file_token, ugc04_fields=fields04)
        existing_record_id = existing_by_shot.get(int(crop["shot_index"])) if overwrite_existing else ""
        operation = "updated" if existing_record_id else "created"
        try:
            if existing_record_id:
                update_record_fn(token, ugc05_table, existing_record_id, record_fields)
                record_id = existing_record_id
            else:
                record_id = create_record_fn(token, ugc05_table, record_fields)
            attachment_written = True
        except Exception as exc:
            fallback_fields = dict(record_fields)
            fallback_fields.pop("原始裁切图片", None)
            fallback_fields["错误信息"] = f"原始裁切图片附件未写入：{str(exc)[:300]}；裁切图片已上传，file_token/路径已写入文本字段。"
            if existing_record_id:
                update_record_fn(token, ugc05_table, existing_record_id, fallback_fields)
                record_id = existing_record_id
            else:
                record_id = create_record_fn(token, ugc05_table, fallback_fields)
            attachment_written = False
        item = {"record_id": record_id, "shot_index": crop["shot_index"], "file_token": file_token, "attachment_written": attachment_written, "operation": operation}
        if enhance:
            try:
                enhanced_path = enhance_dir / f"shot_{int(crop['shot_index']):02d}_916.png"
                enhance_info = enhance_shot_image_with_repaint(
                    token,
                    Path(crop["path"]),
                    image_path,
                    shots[i],
                    crop,
                    enhanced_path,
                    active_count=len(active_crops),
                    config=enhance_config,
                    uploader=uploader,
                )
                enhanced_token = uploader(token, str(enhanced_path), enhanced_path.name)
                update_fields = {
                    "高清分镜图": [{"file_token": enhanced_token, "name": enhanced_path.name}],
                    "高清分镜图路径": str(enhanced_path),
                    "高清分镜图file_token": enhanced_token,
                    "高清化状态": "成功",
                    "高清图审核状态": "待确认",
                    "高清图操作": "不触发",
                    "错误信息": "高清图由 OTU 参考重绘生成：crop 为主构图参考，9宫格为一致性参考；已适配为 1080x1920。",
                }
                update_record_fn(token, ugc05_table, record_id, update_fields)
                enhance_info["file_token"] = enhanced_token
                enhance_info["record_id"] = record_id
                enhanced.append(enhance_info)
                item["enhanced"] = True
            except Exception as exc:
                update_record_fn(token, ugc05_table, record_id, {
                    "高清化状态": "失败",
                    "错误信息": f"OTU 参考重绘高清化失败：{str(exc)[:500]}",
                })
                item["enhanced"] = False
                item["enhance_error"] = str(exc)[:500]
        created.append(item)
    result["created_records"] = created
    result["enhanced_records"] = enhanced
    result["overwrite_existing"] = overwrite_existing
    result["updated_record_count"] = sum(1 for item in created if item.get("operation") == "updated")
    result["created_record_count"] = sum(1 for item in created if item.get("operation") == "created")
    result["written"] = True
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="UGC-05 分镜图片裁切任务。默认 dry-run，只裁切本地图片，不写飞书。")
    parser.add_argument("record_id", help="UGC-04 record_id")
    parser.add_argument("--write", action="store_true", help="创建 UGC-05 分镜图片记录并上传裁切图")
    parser.add_argument("--enhance", action="store_true", help="写入后调用 OTU 参考重绘生成高清分镜图")
    parser.add_argument("--output-file", help="保存运行结果 JSON")
    args = parser.parse_args()
    result = create_or_preview_shot_records(args.record_id, write=args.write, enhance=args.enhance)
    text = json_dumps(result)
    print(text)
    if args.output_file:
        Path(args.output_file).write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
