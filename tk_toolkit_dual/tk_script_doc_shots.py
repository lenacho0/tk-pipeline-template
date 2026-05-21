#!/usr/bin/env python3
"""
脚本文档逐分镜链路：
1) 文档母记录：整篇脚本文档 -> 结构化 assets + shots
2) 参考底图记录：宠物/环境/人类角色底图
3) 分镜记录：单条分镜图/视频/音频生成
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

from google.genai import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (  # noqa: E402
    APP_TOKEN,
    CONFIG_RECORDS,
    TABLE_CONFIG,
    TABLE_PRODUCT,
    TABLE_SCRIPT_DOC_REFERENCE_ASSETS,
    TABLE_SCRIPT_DOC_SHOTS,
    TABLE_SCRIPT_DOC_TASKS,
    WORKSPACE,
    build_error_payload,
    extract_linked_record_ids,
    extract_text,
    feishu_headers,
    get_feishu_token,
    get_model_config,
    get_product_record,
    log_event,
    safe_get_record,
    safe_list_records,
    safe_request,
    safe_update_record,
    with_retry,
)
from tk_shot_script_gen import (  # noqa: E402
    build_readable_script,
    extract_json_object,
    parse_target_seconds,
)
from otu_image import (  # noqa: E402
    DEFAULT_OTU_API_BASE,
    DEFAULT_OTU_IMAGE_MODEL,
    DEFAULT_OTU_IMAGE_SIZE,
    download_otu_image_result,
    extract_otu_result_url,
    normalize_image_channel,
    normalize_image_model_choice,
    poll_otu_image_task,
    submit_otu_image_task,
)
from tk_shot_storyboard import (  # noqa: E402
    build_image_to_video_prompt,
    filter_existing_fields,
)
from tk_storyboard import safe_download_attachment, upload_image_to_feishu  # noqa: E402


ASSET_TYPES = {"pet", "environment", "human"}
YES_VALUES = {"是", "true", "yes", "1", "需要", "y"}

DEFAULT_PARSE_PROMPT = """
你是短视频脚本文档结构化拆解器。用户会给你一整篇已经写好的脚本文档。

你必须忠实解析，不要改写创意。输出严格 JSON，不要 markdown，不要解释。

你需要完成三件事：
1. 从全文中找出全局参考资产提示词：
   - pet：宠物形象参考底图提示词
   - environment：环境/背景参考底图提示词
   - human：人类角色参考底图提示词
   如果全文中有多个宠物、环境或人类角色，要分别创建多个 asset。
2. 按分镜拆成 shots。
3. 对每条 shot 判断生成分镜图时到底需要哪些参考图：
   - 只有该分镜画面里需要保持某个宠物/环境/人物一致时，才把对应 asset_id 放进 asset_ids。
   - 只有该分镜画面明确出现产品、产品包装、产品使用、产品 hero close-up，或提示词要求保持产品外观一致时，use_product_reference 才为 true。
   - 不要把所有参考图默认塞给每条分镜。

JSON 顶层格式：
{
  "global_assets": [
    {
      "asset_id": "pet_hero",
      "asset_type": "pet | environment | human",
      "asset_name": "资产名称",
      "prompt": "用于生成该参考底图的完整提示词",
      "required_for_story": true
    }
  ],
  "shots": [
    {
      "shot_no": 1,
      "duration_sec": 4,
      "time_range": "0-4s",
      "voiceover_text": "最终要生成音频的口播；无口播则为空",
      "screen_text": "后期叠加文字；没有则为空",
      "screen_text_zh": "屏幕文字中文理解；没有则为空",
      "speaker": "说话主体；没有则为空",
      "speaker_visible": true,
      "visual": "画面描述",
      "character_ids": ["human_or_pet_asset_id"],
      "pet_ids": ["pet_asset_id"],
      "environment_id": "environment_asset_id",
      "product_visibility": "none | subtle | clear | hero",
      "camera": "镜头语言",
      "emotion": "情绪",
      "action": "动作",
      "continuity_notes": "连续性要求",
      "image_prompt": "单张分镜图生成提示词",
      "video_prompt": "图生视频提示词；没有则根据 shot 信息生成",
      "publish_title": "发布视频标题；没有则为空",
      "publish_tags": ["标签"],
      "publish_caption": "发布文案；没有则为空",
      "reference_requirements": {
        "use_product_reference": false,
        "asset_ids": ["pet_hero", "home_bg"],
        "reason": "为什么该分镜只需要这些参考图"
      }
    }
  ]
}
""".strip()


def _as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _csv(items: Iterable[Any]) -> str:
    return ",".join(str(item).strip() for item in items if str(item).strip())


def _link_record_ids(value: Any) -> List[str]:
    ids = extract_linked_record_ids(value)
    if ids:
        return ids
    if isinstance(value, str) and value.strip().startswith("rec"):
        return [value.strip()]
    return []


def _yes(value: Any) -> bool:
    return extract_text(value).strip().lower() in YES_VALUES


def _unique_id(raw: Any, fallback: str) -> str:
    text = extract_text(raw).strip()
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"[^0-9A-Za-z_\-]+", "", text)
    return text or fallback


def normalize_asset(asset: Dict[str, Any], idx: int) -> Dict[str, Any]:
    asset_type = extract_text(asset.get("asset_type") or asset.get("type")).strip().lower()
    if asset_type not in ASSET_TYPES:
        raise ValueError(f"global_assets[{idx}] asset_type 无效: {asset_type}")
    asset_id = _unique_id(asset.get("asset_id") or asset.get("id"), f"{asset_type}_{idx}")
    prompt = extract_text(asset.get("prompt") or asset.get("reference_prompt")).strip()
    if not prompt:
        raise ValueError(f"global_assets[{idx}] 缺少 prompt")
    return {
        "asset_id": asset_id,
        "asset_type": asset_type,
        "asset_name": extract_text(asset.get("asset_name") or asset.get("name")).strip() or asset_id,
        "prompt": prompt,
        "required_for_story": bool(asset.get("required_for_story", True)),
    }


def normalize_reference_requirements(raw: Any) -> Dict[str, Any]:
    data = raw if isinstance(raw, dict) else {}
    asset_ids = []
    for item in _as_list(data.get("asset_ids")):
        asset_id = extract_text(item).strip()
        if asset_id and asset_id not in asset_ids:
            asset_ids.append(asset_id)
    return {
        "use_product_reference": bool(data.get("use_product_reference")),
        "asset_ids": asset_ids,
        "reason": extract_text(data.get("reason")).strip(),
    }


def _union_reference_asset_ids(*groups: Iterable[Any]) -> List[str]:
    asset_ids: List[str] = []
    for group in groups:
        for item in group or []:
            asset_id = extract_text(item).strip()
            if asset_id and asset_id not in asset_ids:
                asset_ids.append(asset_id)
    return asset_ids


def normalize_shot(shot: Dict[str, Any], idx: int) -> Dict[str, Any]:
    normalized = dict(shot or {})
    normalized["shot_no"] = int(normalized.get("shot_no") or normalized.get("shot_number") or idx)
    normalized["duration_sec"] = float(normalized.get("duration_sec") or 0)
    normalized["time_range"] = extract_text(normalized.get("time_range")).strip()
    normalized["voiceover_text"] = extract_text(normalized.get("voiceover_text") or normalized.get("thai_text")).strip()
    normalized["screen_text"] = extract_text(normalized.get("screen_text")).strip()
    normalized["screen_text_zh"] = extract_text(normalized.get("screen_text_zh")).strip()
    normalized["speaker"] = extract_text(normalized.get("speaker")).strip()
    normalized["speaker_visible"] = bool(normalized.get("speaker_visible")) if "speaker_visible" in normalized else bool(normalized["voiceover_text"])
    normalized["visual"] = extract_text(normalized.get("visual") or normalized.get("visual_description")).strip()
    normalized["character_ids"] = [extract_text(x).strip() for x in _as_list(normalized.get("character_ids")) if extract_text(x).strip()]
    normalized["pet_ids"] = [extract_text(x).strip() for x in _as_list(normalized.get("pet_ids")) if extract_text(x).strip()]
    normalized["environment_id"] = extract_text(normalized.get("environment_id")).strip()
    normalized["product_visibility"] = extract_text(normalized.get("product_visibility")).strip() or "none"
    normalized["camera"] = extract_text(normalized.get("camera")).strip()
    normalized["emotion"] = extract_text(normalized.get("emotion")).strip()
    normalized["action"] = extract_text(normalized.get("action")).strip()
    normalized["continuity_notes"] = extract_text(normalized.get("continuity_notes")).strip()
    normalized["image_prompt"] = extract_text(normalized.get("image_prompt") or normalized.get("prompt_text")).strip() or normalized["visual"]
    normalized["video_prompt"] = extract_text(normalized.get("video_prompt")).strip()
    normalized["publish_title"] = extract_text(normalized.get("publish_title")).strip()
    normalized["publish_tags"] = [extract_text(x).strip() for x in _as_list(normalized.get("publish_tags")) if extract_text(x).strip()]
    normalized["publish_caption"] = extract_text(normalized.get("publish_caption")).strip()
    normalized["reference_requirements"] = normalize_reference_requirements(normalized.get("reference_requirements"))
    if not normalized["visual"]:
        raise ValueError(f"shot {idx} 缺少 visual")
    if normalized["duration_sec"] <= 0:
        raise ValueError(f"shot {idx} 缺少有效 duration_sec")
    return normalized


def validate_and_normalize_payload(payload: Dict[str, Any], target_seconds: float) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("脚本文档解析 JSON 顶层必须是对象")
    assets = [normalize_asset(asset, idx) for idx, asset in enumerate(_as_list(payload.get("global_assets")), start=1)]
    shots = [normalize_shot(shot, idx) for idx, shot in enumerate(_as_list(payload.get("shots")), start=1)]
    if not shots:
        raise ValueError("脚本文档解析 JSON 缺少 shots")
    known_assets = {asset["asset_id"] for asset in assets}
    for shot in shots:
        required_asset_ids = _union_reference_asset_ids(
            shot["reference_requirements"]["asset_ids"],
            shot.get("pet_ids", []),
            shot.get("character_ids", []),
            [shot.get("environment_id", "")] if shot.get("environment_id") else [],
        )
        shot["reference_requirements"]["asset_ids"] = required_asset_ids
        missing = [asset_id for asset_id in required_asset_ids if asset_id not in known_assets]
        if missing:
            raise ValueError(f"shot {shot['shot_no']} 引用了不存在的参考资产: {','.join(missing)}")
    return {
        "total_duration_sec": float(payload.get("total_duration_sec") or target_seconds),
        "global_assets": assets,
        "shots": shots,
    }


def build_reference_asset_records(parent_record_id: str, payload: Dict[str, Any]) -> List[Dict[str, Dict[str, Any]]]:
    records = []
    for asset in payload.get("global_assets", []):
        records.append({
            "fields": {
                "关联任务": [parent_record_id],
                "父文档记录ID": parent_record_id,
                "资产ID": asset["asset_id"],
                "参考类型": asset["asset_type"],
                "参考名称": asset["asset_name"],
                "参考提示词": asset["prompt"],
                "参考图生成状态": "待生成",
                "参考图审核状态": "待确认",
                "错误信息": "",
            }
        })
    return records


def _build_video_prompt_for_doc_shot(shot: Dict[str, Any], parent_fields: Dict[str, Any]) -> str:
    if shot.get("video_prompt"):
        return shot["video_prompt"]
    return build_image_to_video_prompt(
        shot,
        idx=shot["shot_no"],
        total_shots=0,
        product_name=extract_text(parent_fields.get("产品名") or parent_fields.get("选择产品") or parent_fields.get("关联产品记录") or parent_fields.get("关联产品")).strip(),
        voiceover_text=shot.get("voiceover_text", ""),
        voice_id=extract_text(parent_fields.get("口播音色ID")).strip(),
        video_model=extract_text(parent_fields.get("视频生成模型")).strip(),
        screen_text=shot.get("screen_text", ""),
        screen_text_zh=shot.get("screen_text_zh", ""),
        video_prompt_notes=extract_text(shot.get("video_prompt_notes")).strip(),
    )


def _prefixed_video_model_value(channel: str, model: str) -> str:
    raw_channel = extract_text(channel).strip() or "AIHubMix"
    raw_model = extract_text(model).strip() or "默认（配置表）"
    if " / " in raw_model:
        return raw_model
    return f"{raw_channel} / {raw_model}"


def build_child_shot_records(
    parent_fields: Dict[str, Any],
    payload: Dict[str, Any],
    *,
    parent_record_id: str,
    batch_id: str,
) -> List[Dict[str, Dict[str, Any]]]:
    total = len(payload.get("shots", []))
    records = []
    for shot in payload.get("shots", []):
        refs = shot["reference_requirements"]
        required_asset_ids = _union_reference_asset_ids(
            refs.get("asset_ids", []),
            shot.get("pet_ids", []),
            shot.get("character_ids", []),
            [shot.get("environment_id", "")] if shot.get("environment_id") else [],
        )
        refs = dict(refs)
        refs["asset_ids"] = required_asset_ids
        meta = {
            "speaker": shot.get("speaker", ""),
            "speaker_visible": shot.get("speaker_visible", False),
            "screen_text": shot.get("screen_text", ""),
            "screen_text_zh": shot.get("screen_text_zh", ""),
            "camera": shot.get("camera", ""),
            "emotion": shot.get("emotion", ""),
            "action": shot.get("action", ""),
            "reference_requirements": refs,
        }
        fields = {
            "关联任务": [parent_record_id],
            "父文档记录ID": parent_record_id,
            "批次ID": batch_id,
            "分镜序号": shot["shot_no"],
            "总分镜数": total,
            "分镜原文": shot.get("visual", ""),
            "口播文本": shot.get("voiceover_text", ""),
            "口播音色ID": extract_text(parent_fields.get("口播音色ID")).strip(),
            "口播音频状态": "不触发",
            "目标时长秒": shot.get("duration_sec", ""),
            "画面描述": shot.get("visual", ""),
            "人物描述": _csv(shot.get("character_ids", [])),
            "场景描述": shot.get("environment_id", ""),
            "产品焦点": shot.get("product_visibility", ""),
            "连续性要求": shot.get("continuity_notes", ""),
            "结构化分镜JSON": json.dumps(shot, ensure_ascii=False, separators=(",", ":"))[:10000],
            "文本": json.dumps(meta, ensure_ascii=False, separators=(",", ":"))[:10000],
            "图片提示词": shot.get("image_prompt", ""),
            "提示词": shot.get("image_prompt", ""),
            "视频提示词": _build_video_prompt_for_doc_shot(shot, parent_fields),
            "需要产品参考图": "是" if refs["use_product_reference"] else "否",
            "参考资产ID列表": _csv(refs["asset_ids"]),
            "参考图选择原因": refs.get("reason", ""),
            "分镜图生成状态": "不触发",
            "视频通道": extract_text(parent_fields.get("视频通道")).strip() or "AIHubMix",
            "视频生成模型": _prefixed_video_model_value(
                extract_text(parent_fields.get("视频通道")).strip() or "AIHubMix",
                extract_text(parent_fields.get("视频生成模型")).strip() or "默认（配置表）",
            ),
            "视频生成状态": "不触发",
            "发布视频标题": shot.get("publish_title", ""),
            "发布视频标签": _csv(shot.get("publish_tags", [])),
            "发布文案": shot.get("publish_caption", ""),
            "发布状态": "未发布",
            "错误信息": "",
        }
        if parent_fields.get("关联产品记录"):
            product_ids = _link_record_ids(parent_fields.get("关联产品记录"))
            if product_ids:
                fields["关联产品记录"] = product_ids
        if parent_fields.get("关联产品"):
            fields["关联产品"] = parent_fields.get("关联产品")
        records.append({"fields": fields})
    return records


def _extract_attachment_token(value: Any) -> str:
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict) and item.get("file_token"):
                return str(item["file_token"]).strip()
    return ""


def _downloaded_path(downloaded: Any, fallback: Path) -> str:
    if isinstance(downloaded, (str, os.PathLike)):
        return str(downloaded)
    return str(fallback)


def _asset_ids_from_fields(fields: Dict[str, Any]) -> List[str]:
    raw = extract_text(fields.get("参考资产ID列表")).strip()
    return [item.strip() for item in raw.split(",") if item.strip()]


def collect_reference_images_for_shot(
    token: str,
    shot_fields: Dict[str, Any],
    parent_fields: Dict[str, Any],
    asset_records: List[Dict[str, Any]],
    task_dir: Path,
    *,
    download_fn: Callable[[str, str, str], Any] = safe_download_attachment,
    product_getter: Callable[[str, Any], Tuple[Optional[str], Optional[Dict[str, Any]]]] = get_product_record,
) -> List[Dict[str, str]]:
    task_dir.mkdir(parents=True, exist_ok=True)
    refs: List[Dict[str, str]] = []

    if _yes(shot_fields.get("需要产品参考图")):
        product_value = (
            parent_fields.get("关联产品记录")
            or parent_fields.get("关联产品")
            or parent_fields.get("选择产品")
            or shot_fields.get("关联产品记录")
            or shot_fields.get("关联产品")
        )
        _, product_fields = product_getter(token, product_value)
        product_token = _extract_attachment_token((product_fields or {}).get("产品图片"))
        if not product_token:
            raise ValueError("该分镜需要产品参考图，但产品表缺少 产品图片")
        product_path = task_dir / "reference_product.png"
        downloaded = download_fn(token, product_token, str(product_path))
        refs.append({"role": "product", "path": _downloaded_path(downloaded, product_path), "file_token": product_token})

    requested_ids = _asset_ids_from_fields(shot_fields)
    if not requested_ids:
        return refs
    by_asset_id = {}
    for rec in asset_records:
        fields = rec.get("fields", {})
        if extract_text(fields.get("父文档记录ID")) != extract_text(shot_fields.get("父文档记录ID")):
            continue
        asset_id = extract_text(fields.get("资产ID")).strip()
        if asset_id:
            by_asset_id[asset_id] = fields

    for asset_id in requested_ids:
        asset = by_asset_id.get(asset_id)
        if not asset:
            raise ValueError(f"分镜需要参考资产 {asset_id}，但未找到对应参考底图记录")
        if extract_text(asset.get("参考图审核状态")).strip() != "通过":
            raise ValueError(f"分镜需要参考资产 {asset_id}，但参考图未审核通过")
        file_token = _extract_attachment_token(asset.get("参考图"))
        if not file_token:
            raise ValueError(f"分镜需要参考资产 {asset_id}，但参考图附件缺失")
        asset_type = extract_text(asset.get("参考类型")).strip() or "asset"
        local_path = task_dir / f"reference_{asset_id}.png"
        downloaded = download_fn(token, file_token, str(local_path))
        refs.append({"role": f"{asset_type}:{asset_id}", "path": _downloaded_path(downloaded, local_path), "file_token": file_token})
    return refs


def ensure_script_doc_tables(*, need_tasks: bool = False, need_assets: bool = False, need_shots: bool = False) -> None:
    missing = []
    if need_tasks and not TABLE_SCRIPT_DOC_TASKS:
        missing.append("script_doc_tasks")
    if need_assets and not TABLE_SCRIPT_DOC_REFERENCE_ASSETS:
        missing.append("script_doc_reference_assets")
    if need_shots and not TABLE_SCRIPT_DOC_SHOTS:
        missing.append("script_doc_shots")
    if missing:
        raise RuntimeError(f"config.json 尚未配置脚本文档拆分表: {', '.join(missing)}")


def build_reference_prompt_note(refs: List[Dict[str, str]]) -> str:
    if not refs:
        return "本分镜没有上传额外参考图；只按当前分镜提示词生成。"
    lines = []
    for idx, ref in enumerate(refs, start=1):
        lines.append(f"Reference image {idx} = {ref['role']}. Only use it if it matches the current shot requirement.")
    return "\n".join(lines)


def build_parse_prompt(parent_fields: Dict[str, Any], raw_script: str) -> str:
    target_seconds = extract_text(parent_fields.get("视频时长") or "15s")
    style = extract_text(parent_fields.get("分镜风格") or "混合（产品写实+角色动画）")
    product = extract_text(parent_fields.get("产品名") or parent_fields.get("关联产品记录") or parent_fields.get("关联产品") or parent_fields.get("选择产品"))
    return f"""
{DEFAULT_PARSE_PROMPT}

## 目标参数
- 目标总时长：{target_seconds}
- 分镜风格：{style}
- 关联产品：{product or "见产品表关联记录"}

## 脚本文档正文
{raw_script}
""".strip()


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


def cleanup_children(token: str, table_id: str, parent_record_id: str) -> int:
    deleted = 0
    for rec in safe_list_records(token, table_id):
        fields = rec.get("fields", {})
        if extract_text(fields.get("父文档记录ID")) != parent_record_id:
            continue
        safe_request(
            "delete",
            f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/records/{rec['record_id']}",
            headers=feishu_headers(token),
            timeout=30,
            max_attempts=3,
            acceptable_codes=(0,),
        )
        deleted += 1
    return deleted


def parse_parent_record(record_id: str, *, dry_run: bool = False) -> Dict[str, Any]:
    ensure_script_doc_tables(need_tasks=True, need_assets=True, need_shots=True)
    token = get_feishu_token()
    fields = safe_get_record(token, TABLE_SCRIPT_DOC_TASKS, record_id)
    raw_script = extract_text(fields.get("脚本文档正文")).strip()
    if not raw_script:
        raise ValueError("脚本文档正文为空")
    target_seconds = parse_target_seconds(fields.get("视频时长", "15s"))
    cfg = get_model_config(token, CONFIG_RECORDS.get("shot_script_gen"))
    model_name = cfg["model"] or "gemini-2.5-flash"
    api_key = cfg["api_key"]
    api_base = cfg["api_base"] or "https://aihubmix.com/gemini"
    if not api_key:
        raise ValueError("逐镜头脚本生成配置缺少 API Key")
    prompt = build_parse_prompt(fields, raw_script)

    summary = {"record_id": record_id, "dry_run": dry_run, "prompt_chars": len(prompt)}
    if dry_run:
        summary["status"] = "dry_run_ready"
        return summary

    safe_update_record(token, TABLE_SCRIPT_DOC_TASKS, record_id, filter_existing_fields(token, TABLE_SCRIPT_DOC_TASKS, {
        "解析状态": "解析中",
        "解析错误信息": "",
    }))
    from google import genai
    client = genai.Client(api_key=api_key, http_options={"base_url": api_base})
    response = with_retry(
        lambda: client.models.generate_content(model=model_name, contents=[prompt]),
        max_attempts=3,
        label="gemini script doc shots parse",
    )
    payload = validate_and_normalize_payload(extract_json_object(getattr(response, "text", "") or ""), target_seconds)
    readable_script = build_readable_script({"shots": payload["shots"]})
    batch_id = f"SCRIPTDOC-{time.strftime('%Y%m%d%H%M%S')}-{record_id[-6:]}"
    asset_records = build_reference_asset_records(record_id, payload)
    shot_records = build_child_shot_records(fields, payload, parent_record_id=record_id, batch_id=batch_id)

    deleted = (
        cleanup_children(token, TABLE_SCRIPT_DOC_REFERENCE_ASSETS, record_id)
        + cleanup_children(token, TABLE_SCRIPT_DOC_SHOTS, record_id)
    )
    create_records(token, TABLE_SCRIPT_DOC_REFERENCE_ASSETS, [
        {"fields": filter_existing_fields(token, TABLE_SCRIPT_DOC_REFERENCE_ASSETS, item["fields"])}
        for item in asset_records
    ])
    create_records(token, TABLE_SCRIPT_DOC_SHOTS, [
        {"fields": filter_existing_fields(token, TABLE_SCRIPT_DOC_SHOTS, item["fields"])}
        for item in shot_records
    ])
    safe_update_record(token, TABLE_SCRIPT_DOC_TASKS, record_id, filter_existing_fields(token, TABLE_SCRIPT_DOC_TASKS, {
        "解析状态": "成功",
        "解析结果JSON": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))[:10000],
        "解析后逐镜头脚本": readable_script[:10000],
        "总分镜数": len(payload["shots"]),
        "批次ID": batch_id,
        "解析错误信息": "",
    }))
    summary.update({
        "status": "success",
        "batch_id": batch_id,
        "deleted_children": deleted,
        "asset_count": len(asset_records),
        "shot_count": len(shot_records),
    })
    return summary


def generate_reference_image(record_id: str, *, dry_run: bool = False) -> Dict[str, Any]:
    ensure_script_doc_tables(need_assets=True)
    token = get_feishu_token()
    fields = safe_get_record(token, TABLE_SCRIPT_DOC_REFERENCE_ASSETS, record_id)
    prompt = extract_text(fields.get("参考提示词")).strip()
    if not prompt:
        raise ValueError("参考提示词为空")
    cfg = get_model_config(token, CONFIG_RECORDS.get("shot_storyboard"))
    model_name = normalize_image_model_choice(cfg["model"] or DEFAULT_OTU_IMAGE_MODEL)
    api_key = cfg["api_key"]
    api_base = cfg["api_base"] or DEFAULT_OTU_API_BASE
    if not api_key:
        raise ValueError("分镜图生成配置缺少 API Key")
    summary = {"record_id": record_id, "dry_run": dry_run, "prompt_chars": len(prompt), "model": model_name}
    if dry_run:
        summary["status"] = "dry_run_ready"
        return summary

    safe_update_record(token, TABLE_SCRIPT_DOC_REFERENCE_ASSETS, record_id, filter_existing_fields(token, TABLE_SCRIPT_DOC_REFERENCE_ASSETS, {
        "参考图生成状态": "生成中",
        "错误信息": "",
    }))
    full_prompt = f"""
Generate one clean reference image for later storyboard consistency.
Asset type: {extract_text(fields.get('参考类型'))}
Asset name: {extract_text(fields.get('参考名称'))}
Prompt: {prompt}

Output a single image only. No text, watermark, collage, or split panels.
""".strip()
    work_dir = Path(WORKSPACE) / "script_doc_reference_work" / record_id
    work_dir.mkdir(parents=True, exist_ok=True)
    out_path = work_dir / f"{record_id}_reference.png"
    submit_task_id, submit_body = submit_otu_image_task(
        {"api_key": api_key, "api_base": api_base, "model": model_name},
        full_prompt,
        input_mode="text-to-image",
        metadata={"urls": []},
        size=DEFAULT_OTU_IMAGE_SIZE,
    )
    result = submit_body if not submit_task_id else poll_otu_image_task({"api_key": api_key, "api_base": api_base, "model": model_name}, submit_task_id)
    result_url = extract_otu_result_url(result) or extract_otu_result_url(submit_body)
    if not result_url:
        raise RuntimeError("OTU 参考图任务完成但未返回图片地址")
    download_otu_image_result(result_url, str(out_path))
    file_token = upload_image_to_feishu(token, str(out_path), out_path.name)
    safe_update_record(token, TABLE_SCRIPT_DOC_REFERENCE_ASSETS, record_id, filter_existing_fields(token, TABLE_SCRIPT_DOC_REFERENCE_ASSETS, {
        "参考图": [{"file_token": file_token}],
        "参考图file_token": file_token,
        "参考图本地路径": str(out_path),
        "参考图生成状态": "成功",
        "参考图审核状态": "待确认",
        "错误信息": "",
    }))
    summary.update({"status": "success", "file_token": file_token, "output_path": str(out_path)})
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="脚本文档逐分镜解析/参考底图生成")
    sub = parser.add_subparsers(dest="command", required=True)
    parse_cmd = sub.add_parser("parse", help="解析文档母记录并创建参考底图/分镜记录")
    parse_cmd.add_argument("record_id")
    parse_cmd.add_argument("--dry-run", action="store_true")
    ref_cmd = sub.add_parser("reference-image", help="生成一条参考底图记录")
    ref_cmd.add_argument("record_id")
    ref_cmd.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "parse":
            result = parse_parent_record(args.record_id, dry_run=args.dry_run)
        else:
            result = generate_reference_image(args.record_id, dry_run=args.dry_run)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        payload = build_error_payload(exc, stage=f"script_doc_shots_{args.command}")
        log_event("ERROR", "script doc shots task failed", command=args.command, error=payload["message"], error_code=payload["error_code"])
        try:
            token = get_feishu_token()
            if args.command == "parse":
                safe_update_record(token, TABLE_SCRIPT_DOC_TASKS, args.record_id, filter_existing_fields(token, TABLE_SCRIPT_DOC_TASKS, {
                    "解析状态": "失败",
                    "解析错误信息": payload["message"],
                }))
            else:
                safe_update_record(token, TABLE_SCRIPT_DOC_REFERENCE_ASSETS, args.record_id, filter_existing_fields(token, TABLE_SCRIPT_DOC_REFERENCE_ASSETS, {
                    "参考图生成状态": "失败",
                    "错误信息": payload["message"],
                }))
        except Exception:
            pass
        print(f"ERROR_CODE={payload['error_code']} RETRYABLE={str(payload['retryable']).lower()} MESSAGE={payload['message']}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
