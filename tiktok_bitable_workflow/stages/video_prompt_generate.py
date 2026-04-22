#!/usr/bin/env python3
"""
阶段5：图生视频提示词生成（第一版）
读取结构化脚本 JSON + 生图提示词 JSON，生成逐分镜图生视频提示词。
第一版只生成 JSON + Markdown，不直接调视频模型。
"""
import json
import os
import sys
import time
import requests

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
CONFIG_PATH = os.environ.get("TIKTOK_BITABLE_CONFIG", os.path.join(PROJECT_DIR, "config.json"))
if not os.path.isabs(CONFIG_PATH):
    CONFIG_PATH = os.path.abspath(os.path.join(PROJECT_DIR, CONFIG_PATH))


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


CFG = load_config()
FEISHU = CFG["feishu"]
TABLES = FEISHU["tables"]
APP_TOKEN = FEISHU["bitable_app_token"]
SCRIPT_TASKS_TABLE = TABLES.get("script_tasks") or TABLES.get("script_gen", "")


def get_token():
    r = requests.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": FEISHU["app_id"], "app_secret": FEISHU["app_secret"]},
        timeout=15,
    )
    d = r.json()
    if "tenant_access_token" not in d:
        raise RuntimeError(f"Feishu token failed: {d}")
    return d["tenant_access_token"]


def hdrs(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def get_record(token, table_id, record_id):
    r = requests.get(
        f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/records/{record_id}",
        headers=hdrs(token), timeout=20,
    )
    d = r.json()
    if d.get("code") != 0:
        raise RuntimeError(f"get_record failed: {d}")
    return d["data"]["record"]["fields"]


def update_record(token, table_id, record_id, fields):
    r = requests.put(
        f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/records/{record_id}",
        headers=hdrs(token), json={"fields": fields}, timeout=30,
    )
    d = r.json()
    if d.get("code") != 0:
        raise RuntimeError(f"update_record failed: {d}")
    return d


def extract_text(val):
    if val is None:
        return ""
    if isinstance(val, str):
        return val
    if isinstance(val, list):
        return "".join(item.get("text", "") if isinstance(item, dict) else str(item) for item in val)
    return str(val)


def log(level, msg, **kwargs):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    extra = " ".join(f"{k}={repr(v)}" for k, v in kwargs.items() if v is not None)
    line = f"[{ts}] [{level}] {msg}"
    if extra:
        line += f" | {extra}"
    print(line, flush=True)


def build_video_prompt_items(structured, image_prompt_json):
    shots = structured.get("shots", [])
    image_items = (image_prompt_json or {}).get("shots", [])
    items = []
    voice_profile = "Warm, natural, conversational TikTok delivery, youthful energy, clean recording, no background noise."

    for idx, shot in enumerate(shots, start=1):
        image_prompt = ""
        if idx - 1 < len(image_items):
            image_prompt = image_items[idx - 1].get("prompt", "")

        content_type = shot.get("content_type", "dialogue")
        thai_text = shot.get("thai_text", "")
        speaker = shot.get("speaker", "")

        if content_type == "silent_action":
            voice_block = ""
            audio_notes = "No spoken dialogue. Keep only natural environment movement feeling."
        elif content_type == "voiceover":
            voice_block = f"画外音: {thai_text}。"
            audio_notes = f"Use unified voice profile: {voice_profile}"
        else:
            voice_block = f"{speaker}: {thai_text}。"
            audio_notes = f"Visible on-screen speaking subject. Use unified voice profile: {voice_profile}"

        video_prompt = (
            f"Use the confirmed storyboard image as the only visual reference. "
            f"Current shot: {shot.get('visual_description','')}。"
            f"Motion should be short, clear, natural, TikTok-friendly. "
            f"Keep one main action per shot. "
            f"Image prompt basis: {image_prompt}。"
            f"Voice: {voice_block} {audio_notes} no text, no subtitles, no watermarks"
        ).strip()

        items.append({
            "shot_number": shot.get("shot_number", f"分镜 {idx}"),
            "brief": shot.get("visual_description", ""),
            "duration_sec": 4,
            "video_prompt": video_prompt,
            "voice_block": voice_block,
            "audio_notes": audio_notes,
        })

    return {"voice_profile": voice_profile, "shots": items}


def render_markdown(payload):
    lines = ["# 图生视频提示词", "", f"统一音色: {payload.get('voice_profile','')}", ""]
    for item in payload.get("shots", []):
        lines.append(f"## {item['shot_number']}")
        lines.append(f"- brief: {item['brief']}")
        lines.append(f"- duration_sec: {item['duration_sec']}")
        lines.append(f"- video_prompt: {item['video_prompt']}")
        lines.append(f"- voice_block: {item['voice_block']}")
        lines.append(f"- audio_notes: {item['audio_notes']}")
        lines.append("")
    return "\n".join(lines).strip()


def main(argv=None):
    argv = argv or sys.argv
    if len(argv) < 2:
        print("Usage: python3 stages/video_prompt_generate.py <record_id>")
        sys.exit(1)

    record_id = argv[1]
    token = get_token()
    fields = get_record(token, SCRIPT_TASKS_TABLE, record_id)

    raw_structured = extract_text(fields.get("结构化脚本JSON", "")).strip()
    raw_image_prompt = extract_text(fields.get("生图提示词JSON", "")).strip()
    if not raw_structured:
        raise RuntimeError("缺少结构化脚本JSON")
    if not raw_image_prompt:
        raise RuntimeError("缺少生图提示词JSON")

    structured = json.loads(raw_structured)
    image_prompt_json = json.loads(raw_image_prompt)
    payload = build_video_prompt_items(structured, image_prompt_json)

    update_record(token, SCRIPT_TASKS_TABLE, record_id, {
        "图生视频提示词JSON": json.dumps(payload, ensure_ascii=False, indent=2),
        "图生视频提示词Markdown": render_markdown(payload)[:8000],
        "下游推进状态": "待图生视频",
    })
    log("INFO", "video_prompt_generate success", record_id=record_id, shot_count=len(payload.get('shots', [])))


if __name__ == "__main__":
    main()
