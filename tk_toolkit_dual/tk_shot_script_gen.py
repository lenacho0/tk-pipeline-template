#!/usr/bin/env python3
"""
手写脚本 → 逐镜头结构 JSON。

用法: python3 tk_shot_script_gen.py <003-2_record_id>

本脚本只处理手写脚本拆解，不读取历史爆款参考表。
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *
from tk_script_gen import get_model_info, get_product_info
from tk_shot_storyboard import cleanup_shots_by_source, filter_existing_fields, split_shots
from tk_storyboard_style import format_style_policy_for_prompt, resolve_storyboard_style_policy

MAX_VISUAL_BIBLE_CHARS = 6000

DEFAULT_HANDWRITTEN_SHOT_PROMPT = """
你是短视频逐镜头导演。你的任务是把用户输入的手写脚本，忠实拆解成可执行的逐镜头 JSON。

最高优先级：
- 用户手写脚本是唯一创意来源。
- 不要参考任何历史样本，不要引入外部套路，不要改写剧情、角色、产品使用方式、Hook 设计或口播重点。
- 只允许在不改变原意的前提下补充镜头语言、构图、动作、情绪、连续性描述和单镜头图片提示词。

必须先判断故事模式：
- single_character_continuity：同一个主角/宠物从头到尾连续出现或说话。
- multi_case_product_demo：多个主人/宠物/场景分别展示同一产品。
- product_steps_demo：同一产品按步骤演示。
- mixed：脚本里同时存在连续主角和多场景案例。

一致性规则：
- 产品永远必须一致，lock_product=true。
- 角色、宠物、环境是否一致，必须根据脚本内容判断。
- 如果脚本明确是一只小猫/一个主人从头到尾说话，所有 shots 必须复用同一 character_id / pet_id / environment_id。
- 如果脚本明确是多个用户案例，不要强行锁同一个人物、宠物或环境；只锁产品和整体风格。
- 如果前三秒是 Hook 或脚本要求强视觉冲击，第一镜必须标记 beat_role=hook、visual_intensity=high，并在 must_show/forbidden/camera/action 中强化。

Markdown 表格成片脚本规则：
- 如果用户输入是 Markdown 表格成片脚本，请优先按列解析：时间 / 画面 / 泰语口播/字幕 / 中文理解 / 爆点来源。
- 每一行时间段通常对应一个 shot；除非一行内部明确有两个连续执行阶段，否则不要随意合并或拆散。
- voiceover_text 只能放最终 TTS 要朗读的泰语口播；不得放中文理解、屏幕文字、爆点来源、解释文字或“狗狗口播：”标签。
- 表格中的“屏幕泰文”“屏幕文字”“字幕”必须放入 `screen_text`；对应中文解释放入 `screen_text_zh`，不得进入 `voiceover_text`。
- 表格中的“中文理解”只用于模型理解和人工检查，不进入 TTS，不进入图片生成文字。
- 表格中的“爆点来源”放入 `source_beat`，用于保留创意依据，不得当成画面文字生成。
- 如果原文含图生视频动作提示或镜头运动备注，放入 `video_prompt_notes`，供后续视频提示词使用；单张分镜图只吸收其静态首帧画面信息。

只输出严格 JSON，不要 markdown，不要解释。JSON 顶层格式：
{
  "story_mode": "single_character_continuity | multi_case_product_demo | product_steps_demo | mixed",
  "total_duration_sec": 15,
  "visual_continuity_policy": {
    "lock_product": true,
    "lock_main_character": true,
    "lock_pet": true,
    "lock_environment": true,
    "allowed_character_variation": false,
    "allowed_environment_variation": false,
    "reason": "为什么这样判断"
  },
  "visual_entities": {
    "product": {"id": "product_1", "description": "产品外观和使用方式"},
    "characters": [{"id": "cat_hero", "role": "main_speaker", "description": "角色外观与性格"}],
    "pets": [{"id": "pet_1", "description": "宠物外观"}],
    "environments": [{"id": "living_room", "description": "环境设定"}]
  },
  "shots": [
    {
      "shot_no": 1,
      "beat_role": "hook | pain | solution | proof | cta | transition",
      "duration_sec": 3,
      "time_range": "0-3s",
      "voiceover_text": "只放最终要朗读的口播文本；无口播则为空字符串",
      "screen_text": "只放需要后期叠加的屏幕泰文；没有则为空字符串",
      "screen_text_zh": "屏幕文字中文理解；没有则为空字符串",
      "source_beat": "爆点来源或创意依据；没有则为空字符串",
      "speaker": "dog | owner | narrator | none",
      "speaker_visible": true,
      "visual": "忠实对应脚本的画面内容",
      "visual_intensity": "high | medium | low",
      "must_show": ["脚本强制要求出现的画面元素"],
      "forbidden": ["本镜头不能出现或不能被弱化成的内容"],
      "character_ids": ["cat_hero"],
      "pet_ids": ["pet_1"],
      "environment_id": "living_room",
      "product_visibility": "none | subtle | clear | hero",
      "camera": "镜头语言",
      "emotion": "情绪",
      "action": "动作",
      "continuity_notes": "本镜头和前后镜头的一致性要求",
      "video_prompt_notes": "后续图生视频动作/镜头运动备注；没有则为空字符串",
      "image_prompt": "给单张 9:16 分镜图模型使用的英文提示词；不要文字、字幕、水印"
    }
  ]
}

shots 数量建议 4-8 个；除非脚本明确需要，不要超过 8 个剧情镜头。所有 duration_sec 总和应接近目标总时长。
""".strip()


def parse_target_seconds(value):
    text = extract_text(value).strip()
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    if not match:
        return 15
    seconds = float(match.group(1))
    return int(seconds) if seconds.is_integer() else seconds


def get_handwritten_script(fields):
    for name in ("手写脚本内容", "文本", "逐镜头脚本"):
        value = extract_text(fields.get(name, "")).strip()
        if value:
            return value
    return ""


def extract_json_object(raw_text):
    raw_text = (raw_text or "").strip()
    if not raw_text:
        raise Exception("模型返回空文本，无法提取逐镜头 JSON")
    fenced = re.search(r"```json\s*([\s\S]*?)\s*```", raw_text)
    if fenced:
        raw_text = fenced.group(1).strip()
    else:
        matched = re.search(r"\{[\s\S]*\}", raw_text)
        if matched:
            raw_text = matched.group()
    try:
        return json.loads(raw_text)
    except Exception as exc:
        raise Exception(f"逐镜头 JSON 解析失败: {exc}")


def normalize_shot(shot, idx):
    normalized = dict(shot or {})
    normalized["shot_no"] = int(normalized.get("shot_no") or idx)
    normalized["duration_sec"] = float(normalized.get("duration_sec") or 0)
    normalized["voiceover_text"] = extract_text(normalized.get("voiceover_text", "")).strip()
    normalized["screen_text"] = extract_text(normalized.get("screen_text", "")).strip()
    normalized["screen_text_zh"] = extract_text(normalized.get("screen_text_zh", "")).strip()
    normalized["source_beat"] = extract_text(normalized.get("source_beat", "")).strip()
    normalized["speaker"] = extract_text(normalized.get("speaker", "")).strip()
    normalized["speaker_visible"] = bool(normalized.get("speaker_visible")) if "speaker_visible" in normalized else bool(normalized["voiceover_text"])
    normalized["visual"] = extract_text(normalized.get("visual", "")).strip()
    normalized["image_prompt"] = extract_text(normalized.get("image_prompt", "")).strip() or normalized["visual"]
    normalized["video_prompt_notes"] = extract_text(normalized.get("video_prompt_notes", "")).strip()
    normalized["must_show"] = normalized.get("must_show") if isinstance(normalized.get("must_show"), list) else []
    normalized["forbidden"] = normalized.get("forbidden") if isinstance(normalized.get("forbidden"), list) else []
    normalized["character_ids"] = normalized.get("character_ids") if isinstance(normalized.get("character_ids"), list) else []
    normalized["pet_ids"] = normalized.get("pet_ids") if isinstance(normalized.get("pet_ids"), list) else []
    normalized["environment_id"] = extract_text(normalized.get("environment_id", "")).strip()
    normalized["continuity_notes"] = extract_text(normalized.get("continuity_notes", "")).strip()
    if not normalized["visual"]:
        raise Exception(f"shot {idx} 缺少 visual")
    if normalized["duration_sec"] <= 0:
        raise Exception(f"shot {idx} 缺少有效 duration_sec")
    return normalized


def validate_and_normalize_payload(payload, target_seconds):
    if not isinstance(payload, dict):
        raise Exception("逐镜头 JSON 顶层必须是对象")
    shots = payload.get("shots")
    if not isinstance(shots, list) or not shots:
        raise Exception("逐镜头 JSON 缺少 shots")

    policy = payload.get("visual_continuity_policy")
    if not isinstance(policy, dict):
        raise Exception("逐镜头 JSON 缺少 visual_continuity_policy")
    policy["lock_product"] = True
    payload["visual_continuity_policy"] = policy

    payload["story_mode"] = extract_text(payload.get("story_mode", "")).strip() or "mixed"
    payload["total_duration_sec"] = float(payload.get("total_duration_sec") or target_seconds)
    payload["visual_entities"] = payload.get("visual_entities") if isinstance(payload.get("visual_entities"), dict) else {}
    payload["shots"] = [normalize_shot(shot, idx) for idx, shot in enumerate(shots, start=1)]
    return payload


def build_readable_script(payload):
    lines = []
    for shot in payload.get("shots", []):
        lines.append(f"分镜 {shot['shot_no']} ({shot['duration_sec']}s)")
        if shot.get("voiceover_text"):
            lines.append(f"口播：{shot['voiceover_text']}")
        lines.append(f"画面：{shot['visual']}")
        if shot.get("continuity_notes"):
            lines.append(f"连续性：{shot['continuity_notes']}")
        lines.append("")
    return "\n".join(lines).strip()


def build_visual_bible(task_fields, product_info, model_info, payload):
    style_policy = resolve_storyboard_style_policy(task_fields.get("分镜风格", ""))
    return json.dumps({
        "product_name": extract_text(get_task_product_value(task_fields)),
        "product_anchor": product_info,
        "character_anchor": model_info,
        "storyboard_style": style_policy["style"],
        "storyboard_style_policy": style_policy["rules"],
        "story_mode": payload.get("story_mode", ""),
        "visual_continuity_policy": payload.get("visual_continuity_policy", {}),
        "visual_entities": payload.get("visual_entities", {}),
        "consistency_rules": [
            "产品在所有镜头中必须保持一致。",
            "角色/宠物/环境是否一致，以 visual_continuity_policy 为准。",
            "single_character_continuity 必须复用同一角色/宠物/环境锚点。",
            "multi_case_product_demo 不要强行复用同一人物、宠物或环境。",
        ],
    }, ensure_ascii=False, indent=2)[:MAX_VISUAL_BIBLE_CHARS]


def build_prompt(task_fields, product_info, model_info, raw_script):
    target_seconds = parse_target_seconds(task_fields.get("视频时长", "15s"))
    product_name = extract_text(get_task_product_value(task_fields))
    style_policy = resolve_storyboard_style_policy(task_fields.get("分镜风格", "混合（产品写实+角色动画）"))
    storyboard_style = style_policy["style"]
    storyboard_style_block = format_style_policy_for_prompt(storyboard_style)
    return f"""
{DEFAULT_HANDWRITTEN_SHOT_PROMPT}

## 目标参数
- 目标总时长：{target_seconds}s
- 分镜风格：{storyboard_style}

{storyboard_style_block}

## 产品信息
产品名：{product_name}
{json.dumps(product_info, ensure_ascii=False, indent=2)}

## 模特/角色参考信息
{model_info or "无指定模特；如脚本内有角色，请以脚本描述为准。"}

## 用户手写脚本（唯一创意来源）
{raw_script}
""".strip()


def main():
    if len(sys.argv) < 2:
        print("用法: python3 tk_shot_script_gen.py <record_id>")
        sys.exit(1)
    record_id = sys.argv[1]
    token = get_feishu_token()

    if not TABLE_SHOT_SCRIPT_GEN:
        raise Exception("config.json 尚未配置 shot_script_gen 表 ID")

    try:
        log_event("INFO", "handwritten shot script task start", record_id=record_id)
        config = get_model_config(token, CONFIG_RECORDS["shot_script_gen"])
        model_name = config["model"] or "gemini-2.5-flash"
        api_key = config["api_key"]
        api_base = config["api_base"] or "https://aihubmix.com/gemini"
        if not api_key:
            raise Exception("飞书配置表缺少 API Key")

        fields = safe_get_record(token, TABLE_SHOT_SCRIPT_GEN, record_id)
        raw_script = get_handwritten_script(fields)
        if not raw_script:
            raise Exception("逐镜头母任务缺少手写脚本内容")

        product_value = get_task_product_value(fields)
        product_name = extract_text(product_value)
        if not product_name and not extract_linked_record_ids(product_value):
            raise Exception("未选择产品")

        product_info = get_product_info(token, product_value)
        if not product_info:
            raise Exception(f"找不到产品: {product_name or product_value}")

        model_info = get_model_info(token, fields)
        target_seconds = parse_target_seconds(fields.get("视频时长", "15s"))
        safe_update_record(token, TABLE_SHOT_SCRIPT_GEN, record_id, {"生成状态": "生成中"})

        from google import genai
        client = genai.Client(api_key=api_key, http_options={"base_url": api_base})
        prompt = build_prompt(fields, product_info, model_info, raw_script)
        response = with_retry(
            lambda: client.models.generate_content(model=model_name, contents=[prompt]),
            max_attempts=3,
            label="gemini handwritten shot json generate_content",
        )
        payload = validate_and_normalize_payload(extract_json_object(getattr(response, "text", "") or ""), target_seconds)
        readable_script = build_readable_script(payload)
        visual_bible = build_visual_bible(fields, product_info, model_info, payload)

        update_fields = {
            "逐镜头脚本": readable_script[:10000],
            "分镜头结构JSON": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))[:10000],
            "总镜头数": len(payload.get("shots", [])),
            "参考来源": "手写脚本，无爆款参考",
            "参考分析记录IDs": "",
            "参考视频ID列表": "",
            "参考样本数": 0,
            "参考策略摘要": "",
            "全局视觉锚点": visual_bible,
            "故事模式": payload.get("story_mode", ""),
            "视觉连续性策略JSON": json.dumps(payload.get("visual_continuity_policy", {}), ensure_ascii=False, indent=2)[:10000],
            "生成状态": "成功",
        }
        safe_update_record(
            token,
            TABLE_SHOT_SCRIPT_GEN,
            record_id,
            filter_existing_fields(token, TABLE_SHOT_SCRIPT_GEN, update_fields),
        )

        deleted = cleanup_shots_by_source(token, record_id)
        log_event("INFO", "old shot records cleaned", record_id=record_id, deleted=deleted)
        split_shots(token, record_id, payload)

        log_event("INFO", "handwritten shot script task success", record_id=record_id, shot_count=len(payload.get("shots", [])))
        print(f"✅ 手写脚本逐镜头 JSON 生成完成并已重建 shot 记录 ({len(payload.get('shots', []))}个镜头)")

    except Exception as e:
        payload = build_error_payload(e, stage="generate_handwritten_shot_json")
        err = payload["message"]
        log_event("ERROR", "handwritten shot script task failed", record_id=record_id, error=err, error_code=payload["error_code"], retryable=payload["retryable"])
        try:
            safe_update_record(token, TABLE_SHOT_SCRIPT_GEN, record_id, filter_existing_fields(token, TABLE_SHOT_SCRIPT_GEN, {
                "生成状态": "失败",
                "逐镜头脚本": f"错误[{payload['error_code']}]: {err}",
                "错误信息": err,
            }))
        except Exception:
            pass
        print(f"ERROR_CODE={payload['error_code']} RETRYABLE={str(payload['retryable']).lower()} MESSAGE={err}")
        sys.exit(1)


if __name__ == "__main__":
    main()
