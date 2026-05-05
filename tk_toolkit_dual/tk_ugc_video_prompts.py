#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ugc_config import load_ugc_table_ids
from ugc_utils import extract_linked_record_ids, extract_text
from ugc_reroll_utils import build_candidate_fields
from tk_ugc_six_grid import get_feishu_token, get_ugc_record, create_ugc_record, update_ugc_record, json_dumps
from tk_ugc_shot_images import get_attachment_token

VIDEO_PROMPT_SYSTEM_PROMPT_PATH = Path(__file__).resolve().parents[1] / "docs" / "prompts" / "ugc-image-to-video-system-prompt-2026-05-02.md"
BASE_WORK_DIR = Path(__file__).resolve().parent / "workspace_ryan" / "ugc_video_prompt_work"

RecordGetter = Callable[[str, str, str], Dict[str, Any]]
RecordCreator = Callable[[str, str, Dict[str, Any]], str]
RecordUpdater = Callable[[str, str, str, Dict[str, Any]], Any]

DEFAULT_UGC05_RECORD_IDS = [
    "recvin7kJqxQuo",
    "recvin7Er2INZu",
    "recvin861Zu2yh",
    "recvin8p8l8dx0",
    "recvin8FNrUi0W",
    "recvin8XX3Z0Iw",
]

GLOBAL_NEGATIVE_PROMPT = (
    "face drift, identity change, outfit change, hairstyle change, body shape change, "
    "product morphing, package redesign, label change, color change, brand change, "
    "scene replacement, background drift, furniture change, pet breed change, extra limbs, "
    "extra fingers, fused fingers, floating objects, unnatural hands, distorted product, "
    "sudden new props, subtitles, captions, on-screen text, stickers, watermark, TikTok UI, "
    "comments UI, poster design, commercial studio lighting, cinematic camera movement, "
    "glossy AI look, 3D render, illustration, anime, comic style"
)


def parse_json_field(raw: Any, label: str) -> Dict[str, Any]:
    text = extract_text(raw).strip()
    if not text:
        raise ValueError(f"缺少 {label}")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"{label} 不是 JSON 对象")
    return data


def load_system_prompt(path: Path = VIDEO_PROMPT_SYSTEM_PROMPT_PATH) -> str:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"UGC-06 图生视频系统提示词为空: {path}")
    return text


def normalize_content_type(shot: Dict[str, Any], assumptions: List[str]) -> str:
    raw = str(shot.get("content_type") or "").strip().lower()
    if raw in {"dialogue", "voiceover", "silent_action"}:
        return raw
    if shot.get("dialogue") or shot.get("local_voiceover"):
        assumptions.append(f"shot {shot.get('shot_index')}: content_type 缺失，因存在 dialogue/local_voiceover，按 dialogue 处理。")
        return "dialogue"
    assumptions.append(f"shot {shot.get('shot_index')}: content_type 缺失且无口播，按 silent_action 处理。")
    return "silent_action"


def get_local_voiceover(shot: Dict[str, Any], content_type: str) -> str:
    if content_type == "dialogue":
        return str(shot.get("dialogue") or shot.get("local_voiceover") or shot.get("voiceover") or "").strip()
    if content_type == "voiceover":
        return str(shot.get("voiceover") or shot.get("narration") or shot.get("local_voiceover") or shot.get("dialogue") or "").strip()
    return ""


def get_cn_translation(shot: Dict[str, Any], content_type: str) -> str:
    if content_type == "dialogue":
        return str(shot.get("dialogue_zh") or shot.get("voiceover_cn_translation") or shot.get("narration_zh") or "").strip()
    if content_type == "voiceover":
        return str(shot.get("voiceover_zh") or shot.get("narration_zh") or shot.get("voiceover_cn_translation") or shot.get("dialogue_zh") or "").strip()
    return ""


def infer_language(text: str) -> str:
    if not text:
        return "None"
    if any("\u0e00" <= ch <= "\u0e7f" for ch in text):
        return "Thai"
    if any("\u4e00" <= ch <= "\u9fff" for ch in text):
        return "Chinese"
    return "Local"


def script_stage(shot: Dict[str, Any]) -> str:
    return str(shot.get("shot_title") or shot.get("script_stage") or shot.get("function") or "").strip()


def dynamic_goal_for_shot(shot: Dict[str, Any], content_type: str) -> str:
    stage = script_stage(shot)
    action = str(shot.get("subject_action") or shot.get("visual_action") or shot.get("visual_description") or "").strip()
    if content_type == "dialogue":
        return f"让当前静帧中的可见说话主体用自然口型完成本镜头口播，同时保持轻微真实动作。{stage}".strip()
    if content_type == "voiceover":
        return f"让画面动作与画外旁白节奏同步，只做轻微自然运动。{stage}".strip()
    return f"让当前静帧以真实 UGC 方式轻微动起来，不加入口播。{action[:80]}".strip()


def visual_motion_for_shot(shot: Dict[str, Any], content_type: str) -> str:
    action = str(shot.get("subject_action") or shot.get("visual_action") or shot.get("visual_description") or "").strip()
    pet_state = str(shot.get("pet_state") or "").strip()
    character_state = str(shot.get("character_state") or "").strip()
    parts = []
    if action:
        parts.append(action)
    if character_state:
        parts.append(f"人物表情/状态轻微变化：{character_state}")
    if pet_state:
        parts.append(f"宠物只做轻微自然反应：{pet_state}")
    if content_type == "dialogue":
        parts.append("可见说话主体自然眨眼、轻微头部动作和低幅度口型变化。")
    if not parts:
        parts.append("人物或主体保持原构图，只做轻微呼吸、眨眼、手部微调等自然动作。")
    return " ".join(parts)


def camera_motion_for_shot(shot: Dict[str, Any]) -> str:
    camera = str(shot.get("camera") or "").strip()
    if camera:
        return f"保持输入静帧的机位逻辑：{camera}。只允许轻微手持晃动和非常小幅的推近/平移，不做电影级大运镜。"
    return "保持输入静帧的机位和构图，只允许轻微手持晃动和非常小幅的推近/平移，不做电影级大运镜。"


def build_audio_plan(shot: Dict[str, Any], content_type: str, duration: int, assumptions: List[str]) -> Dict[str, Any]:
    local = get_local_voiceover(shot, content_type)
    cn = get_cn_translation(shot, content_type)
    speaker = str(shot.get("speaker") or "").strip()
    if content_type == "silent_action" or not local:
        if content_type in {"dialogue", "voiceover"} and not local:
            assumptions.append(f"shot {shot.get('shot_index')}: {content_type} 缺少本土语言口播文本，按无口播输出。")
        return {
            "has_voiceover": False,
            "language": "None",
            "delivery_type": "none",
            "speaker": speaker,
            "timeline": [],
            "subtitle_policy": "No subtitles or on-screen text. Chinese translation is for review only.",
        }
    delivery = "dialogue" if content_type == "dialogue" else "voiceover"
    return {
        "has_voiceover": True,
        "language": infer_language(local),
        "delivery_type": delivery,
        "speaker": speaker,
        "timeline": [
            {
                "start": "0.0s",
                "end": f"{duration:.1f}s",
                "text_local": local,
                "text_cn_for_review_only": cn,
            }
        ],
        "subtitle_policy": "No subtitles or on-screen text. Chinese translation is for review only.",
    }


def audio_sentence_cn(audio_plan: Dict[str, Any], content_type: str, speaker_visible: bool) -> str:
    if not audio_plan.get("has_voiceover"):
        return "本镜头无口播；Veo 只生成自然环境氛围音，不生成讲话口型，不生成字幕或任何画面文字。"
    first = (audio_plan.get("timeline") or [{}])[0]
    local = first.get("text_local", "")
    if content_type == "dialogue" and speaker_visible:
        return f"0.0s 到 {first.get('end', '')}，请 Veo 在图生视频阶段直接生成最终本土语言口播音频：{local}。画面内可见说话主体自然说出该口播，并匹配自然嘴型/讲话表情；该音频就是最终成片音频，不要等待后续 TTS，不生成字幕，不生成任何画面文字。"
    if content_type == "dialogue":
        return f"0.0s 到 {first.get('end', '')}，请 Veo 在图生视频阶段直接生成最终本土语言口播音频：{local}。说话主体不可见或不强制画面内开口；该音频就是最终成片音频，不要等待后续 TTS，不生成字幕，不生成任何画面文字。"
    return f"0.0s 到 {first.get('end', '')}，请 Veo 在图生视频阶段直接生成最终本土语言画外旁白音频：{local}。画面内人物不需要张嘴；该旁白音频就是最终成片音频，不要等待后续 TTS，不生成字幕，不生成任何画面文字。"


def audio_sentence_en(audio_plan: Dict[str, Any], content_type: str, speaker_visible: bool) -> str:
    if not audio_plan.get("has_voiceover"):
        return "No speech in this shot; Veo should generate only natural ambient audio. Do not create speaking mouth movement, subtitles, or any on-screen text."
    first = (audio_plan.get("timeline") or [{}])[0]
    local = first.get("text_local", "")
    if content_type == "dialogue" and speaker_visible:
        return f"From 0.0s to {first.get('end', '')}, Veo must directly generate the final local-language spoken audio during image-to-video generation: {local}. The visible speaker naturally says this line with matching lip-sync and speaking expression. This audio is the final video audio; do not rely on later TTS, and do not create subtitles or any on-screen text."
    if content_type == "dialogue":
        return f"From 0.0s to {first.get('end', '')}, Veo must directly generate the final local-language spoken audio during image-to-video generation: {local}. The speaker is not visible or should not be forced to speak on screen. This audio is the final video audio; do not rely on later TTS, and do not create subtitles or any on-screen text."
    return f"From 0.0s to {first.get('end', '')}, Veo must directly generate the final local-language voiceover audio during image-to-video generation: {local}. The person in the frame does not need to move their mouth. This voiceover is the final video audio; do not rely on later TTS, and do not create subtitles or any on-screen text."


def build_prompt_cn(visual_motion: str, camera_motion: str, audio_plan: Dict[str, Any], content_type: str, speaker_visible: bool) -> str:
    return (
        "严格以输入图片作为唯一视觉锚点。保持输入图片中的同一位人物、同一套穿着、同一个产品、同一只宠物（如画面中存在）、同一场景、同一光线和同一构图逻辑。"
        "不要重新设计人物外貌、发型、服装、产品包装、标签、房间、家具或背景。"
        f"仅让当前静帧中已经存在的元素产生轻微自然动作：{visual_motion} "
        f"{camera_motion} "
        f"{audio_sentence_cn(audio_plan, content_type, speaker_visible)} "
        "整体保持 TikTok UGC 真实手机视频质感，普通生活空间，自然光，轻微不完美构图。"
        "禁止换脸、换衣服、换场景、换产品包装、改变产品标签、生成新人物、新宠物、字幕、贴纸、水印、TikTok UI、广告大片感或电影感运镜。"
    )


def build_prompt_en(visual_motion: str, camera_motion: str, audio_plan: Dict[str, Any], content_type: str, speaker_visible: bool) -> str:
    return (
        "Use the input image as the only visual anchor. Keep the same person, the same outfit, the same product, the same pet if present, the same room, the same lighting, and the same composition from the input image. "
        "Do not redesign the person's face, hairstyle, clothing, product packaging, label, room, furniture, or background. "
        f"Only animate the elements that already exist in the frame with subtle natural motion: {visual_motion} "
        f"{camera_motion} "
        f"{audio_sentence_en(audio_plan, content_type, speaker_visible)} "
        "Keep a realistic TikTok UGC smartphone-video look: casual framing, natural indoor light, slight imperfections, everyday home environment. "
        "No face drift, no outfit change, no scene replacement, no product morphing, no label change, no new character, no new pet, no subtitles, no stickers, no watermark, no TikTok UI, no glossy commercial look, no cinematic camera move."
    )


def build_shot_video_prompt(ugc05_record_id: str, fields05: Dict[str, Any], assumptions: List[str]) -> Dict[str, Any]:
    shot = parse_json_field(fields05.get("对应脚本片段JSON"), f"UGC-05 {ugc05_record_id}.对应脚本片段JSON")
    ugc03_ids = extract_linked_record_ids(fields05.get("关联脚本版本"))
    ugc04_ids = extract_linked_record_ids(fields05.get("关联6宫格任务"))
    shot_index = int(float(extract_text(fields05.get("分镜序号") or shot.get("shot_index") or 0)))
    if shot_index < 1 or shot_index > 9:
        raise ValueError(f"UGC-05 {ugc05_record_id}.分镜序号 必须在 1-9 之间")
    hd_token = get_attachment_token(fields05.get("高清分镜图")) or extract_text(fields05.get("高清分镜图file_token")).strip()
    hd_path = extract_text(fields05.get("高清分镜图路径")).strip()
    if not hd_token and not hd_path:
        raise ValueError(f"UGC-05 {ugc05_record_id} 缺少高清分镜图附件/file_token/路径")
    content_type = normalize_content_type(shot, assumptions)
    duration = int(float(shot.get("duration_sec") or 4))
    duration = min(5, max(2, duration))
    speaker_visible = bool(shot.get("speaker_visible"))
    audio_plan = build_audio_plan(shot, content_type, duration, assumptions)
    visual_motion = visual_motion_for_shot(shot, content_type)
    camera_motion = camera_motion_for_shot(shot)
    prompt_cn = build_prompt_cn(visual_motion, camera_motion, audio_plan, content_type, speaker_visible)
    prompt_en = build_prompt_en(visual_motion, camera_motion, audio_plan, content_type, speaker_visible)
    return {
        "ugc05_record_id": ugc05_record_id,
        "ugc03_record_id": ugc03_ids[0] if ugc03_ids else "",
        "ugc04_record_id": ugc04_ids[0] if ugc04_ids else "",
        "shot_index": shot_index,
        "panel_index": shot_index,
        "script_stage": script_stage(shot),
        "content_type": content_type,
        "dynamic_goal": dynamic_goal_for_shot(shot, content_type),
        "duration_seconds": f"{duration}",
        "source_image_policy": {
            "source_image_role": "single-shot first-frame reference",
            "visual_lock": "Use the input image as the only visual anchor. Keep the same person, outfit, product, pet if present, room, lighting, and composition.",
            "ugc05_hd_file_token": hd_token,
            "ugc05_hd_local_path": hd_path,
        },
        "audio_generation_policy": "Veo must generate the final local-language spoken audio directly during UGC-06 image-to-video generation. UGC-07 only preserves/concatenates the Veo audio tracks; no separate TTS stage is used.",
        "audio_plan": audio_plan,
        "visual_motion": visual_motion,
        "camera_motion": camera_motion,
        "consistency_requirements": "保持输入图片中的同一人物、同一穿着、同一产品、同一宠物（如有）、同一场景、同一光线和同一构图；不得重绘或替换。",
        "ugc_realism_requirements": "真实 TikTok UGC 手机视频质感；轻微手持晃动、自然室内光、普通生活空间、不完美构图；不要棚拍、广告大片或电影感。",
        "prompt_cn": prompt_cn,
        "prompt_en": prompt_en,
        "negative_prompt": GLOBAL_NEGATIVE_PROMPT,
        "recommended_params": {
            "duration_seconds": duration,
            "aspect_ratio": "9:16",
            "motion_strength": "low",
            "camera_motion_strength": "low",
            "reference_image_required": True,
        },
    }


def build_video_prompt_batch(
    ugc05_record_ids: List[str],
    *,
    token: Optional[str] = None,
    get_record_fn: RecordGetter = get_ugc_record,
) -> Dict[str, Any]:
    if not ugc05_record_ids:
        return {
            "validation": {"status": "blocked", "missing_required_inputs": ["ugc05_record_ids"], "warnings": []},
            "video_prompt_batch": {
                "task": "UGC-06 image-to-video prompt generation",
                "shot_count": 0,
                "source_stage": "UGC-05 enhanced shot images",
                "visual_anchor_policy": "Each UGC-05 enhanced shot image is the only visual anchor for its video prompt.",
                "global_negative_prompt": GLOBAL_NEGATIVE_PROMPT,
                "assumptions": [],
            },
            "shot_video_prompts": [],
        }
    token = token or get_feishu_token()
    table_ids = load_ugc_table_ids()
    ugc05_table = table_ids["ugc_05_shot_images"]
    warnings: List[str] = []
    assumptions: List[str] = []
    prompts: List[Dict[str, Any]] = []
    ugc03_ids: List[str] = []
    ugc04_ids: List[str] = []
    for rid in ugc05_record_ids:
        fields = get_record_fn(token, ugc05_table, rid)
        status = extract_text(fields.get("高清化状态")).strip()
        if status and status != "成功":
            warnings.append(f"UGC-05 {rid}.高清化状态={status}，建议确认后再进 UGC-06。")
        ugc03_ids.extend(extract_linked_record_ids(fields.get("关联脚本版本")))
        ugc04_ids.extend(extract_linked_record_ids(fields.get("关联6宫格任务")))
        prompts.append(build_shot_video_prompt(rid, fields, assumptions))
    prompts.sort(key=lambda item: item["shot_index"])
    return {
        "validation": {"status": "ok", "missing_required_inputs": [], "warnings": warnings},
        "video_prompt_batch": {
            "task": "UGC-06 image-to-video prompt generation",
            "shot_count": len(prompts),
            "source_stage": "UGC-05 enhanced shot images",
            "visual_anchor_policy": "Each UGC-05 enhanced shot image is the only visual anchor for its video prompt.",
            "source_ugc03_record_ids": sorted(set(ugc03_ids)),
            "source_ugc04_record_ids": sorted(set(ugc04_ids)),
            "system_prompt_path": str(VIDEO_PROMPT_SYSTEM_PROMPT_PATH),
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "global_negative_prompt": GLOBAL_NEGATIVE_PROMPT,
            "assumptions": assumptions,
        },
        "shot_video_prompts": prompts,
    }


def build_ugc06_fields(
    prompt_item: Dict[str, Any],
    *,
    candidate_group_id: str = "",
    candidate_index: int = 0,
    reroll_source_record_id: str = "",
) -> Dict[str, Any]:
    shot_index = int(prompt_item["shot_index"])
    ugc05_record_id = prompt_item["ugc05_record_id"]
    source = prompt_item.get("source_image_policy") or {}
    file_token = str(source.get("ugc05_hd_file_token") or "")
    local_path = str(source.get("ugc05_hd_local_path") or "")
    fields: Dict[str, Any] = {
        "分镜视频ID": f"UGC-VIDEO-{datetime.now().strftime('%Y%m%d%H%M%S')}-{ugc05_record_id[-6:]}-{shot_index:02d}",
        "分镜序号": shot_index,
        "对应脚本片段JSON": json_dumps({
            "ugc05_record_id": ugc05_record_id,
            "shot_index": shot_index,
            "script_stage": prompt_item.get("script_stage", ""),
            "content_type": prompt_item.get("content_type", ""),
            "audio_plan": prompt_item.get("audio_plan", {}),
            "visual_motion": prompt_item.get("visual_motion", ""),
            "camera_motion": prompt_item.get("camera_motion", ""),
        }),
        "图生视频提示词": json_dumps(prompt_item),
        "提示词生成状态": "成功",
        "视频生成模型": "待确认",
        "视频生成状态": "待生成",
        "本地视频路径": "",
        "错误信息": "UGC-06 提示词已 dry-run 生成；尚未调用图生视频模型。",
        "关联分镜图片": [ugc05_record_id],
        "关联脚本版本": [prompt_item.get("ugc03_record_id")] if prompt_item.get("ugc03_record_id") else [],
        "高清分镜图file_token": file_token,
        "高清分镜图路径": local_path,
        "分镜视频file_token": "",
        "分镜视频URL": "",
        "视频生成任务ID": "",
        "视频生成原始响应JSON": "",
    }
    if file_token:
        fields["高清分镜图"] = [{"file_token": file_token, "name": Path(local_path).name or f"shot_{shot_index:02d}_916.png"}]
    if candidate_group_id and candidate_index:
        fields.update(build_candidate_fields(candidate_group_id, candidate_index, source_record_id=reroll_source_record_id))
        fields["来源UGC05候选记录ID"] = ugc05_record_id
    return fields


def create_or_preview_ugc06_records(
    ugc05_record_ids: List[str],
    *,
    write: bool = False,
    token: Optional[str] = None,
    get_record_fn: RecordGetter = get_ugc_record,
    create_record_fn: RecordCreator = create_ugc_record,
    candidate_group_id: str = "",
    candidate_index: int = 0,
    reroll_source_record_id: str = "",
) -> Dict[str, Any]:
    batch = build_video_prompt_batch(ugc05_record_ids, token=token, get_record_fn=get_record_fn)
    preview_fields = [
        build_ugc06_fields(
            item,
            candidate_group_id=candidate_group_id,
            candidate_index=candidate_index,
            reroll_source_record_id=reroll_source_record_id,
        )
        for item in batch.get("shot_video_prompts", [])
    ]
    result: Dict[str, Any] = {
        "dry_run": not write,
        "batch": batch,
        "preview_fields": preview_fields,
        "created_records": [],
        "written": False,
    }
    if not write:
        return result
    token = token or get_feishu_token()
    table_ids = load_ugc_table_ids()
    ugc06_table = table_ids["ugc_06_shot_videos"]
    created: List[Dict[str, Any]] = []
    for fields in preview_fields:
        try:
            record_id = create_record_fn(token, ugc06_table, fields)
            attachment_written = bool(fields.get("高清分镜图"))
        except Exception as exc:
            fallback = dict(fields)
            fallback.pop("高清分镜图", None)
            fallback["错误信息"] = f"UGC-06 高清分镜图附件未写入：{str(exc)[:300]}；提示词已写入，后续可用 UGC-05 file_token/路径兜底。"
            record_id = create_record_fn(token, ugc06_table, fallback)
            attachment_written = False
        created.append({
            "record_id": record_id,
            "shot_index": fields.get("分镜序号"),
            "ugc05_record_id": (fields.get("关联分镜图片") or [""])[0],
            "attachment_written": attachment_written,
        })
    result["created_records"] = created
    result["written"] = True
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="UGC-06 分镜图生视频提示词生成。默认 dry-run，不写飞书、不调用视频模型。")
    parser.add_argument("record_ids", nargs="*", help="UGC-05 record_id 列表；为空时使用当前推荐的 6 条高清记录")
    parser.add_argument("--write", action="store_true", help="创建 UGC-06 记录并写入提示词；不调用图生视频模型")
    parser.add_argument("--video-candidate-group-id", default="", help="UGC-06 视频重生成候选组 ID")
    parser.add_argument("--video-candidate-index", type=int, default=0, help="UGC-06 视频重生成候选序号")
    parser.add_argument("--reroll-source-ugc06-record-id", default="", help="本次视频重生成来源 UGC-06 record_id")
    parser.add_argument("--output-file", help="保存运行结果 JSON")
    args = parser.parse_args()
    record_ids = args.record_ids or DEFAULT_UGC05_RECORD_IDS
    result = create_or_preview_ugc06_records(
        record_ids,
        write=args.write,
        candidate_group_id=args.video_candidate_group_id,
        candidate_index=args.video_candidate_index,
        reroll_source_record_id=args.reroll_source_ugc06_record_id,
    )
    text = json_dumps(result)
    print(text)
    if args.output_file:
        Path(args.output_file).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_file).write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
