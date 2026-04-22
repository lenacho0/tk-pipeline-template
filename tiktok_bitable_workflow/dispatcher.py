#!/usr/bin/env python3
"""
TikTok Bitable Workflow — 独立调度器
轮询脚本任务表，按状态分发到对应阶段。
"""
import json
import os
import sys
import time
import requests

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.environ.get(
    "TIKTOK_BITABLE_CONFIG",
    os.path.join(SCRIPT_DIR, "config.json")
)
if not os.path.isabs(CONFIG_PATH):
    CONFIG_PATH = os.path.abspath(os.path.join(SCRIPT_DIR, CONFIG_PATH))


def load_config():
    if not os.path.exists(CONFIG_PATH):
        raise FileNotFoundError(f"Missing config: {CONFIG_PATH}")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


CFG = load_config()
FEISHU = CFG["feishu"]
TABLES = FEISHU["tables"]
APP_TOKEN = FEISHU["bitable_app_token"]
SCRIPT_TASKS_TABLE = TABLES.get("script_tasks") or TABLES.get("script_gen", "")
MATERIALS_TABLE = TABLES.get("materials", "tblQgQA587nzXgfX")
COMMON_ANALYSIS_TABLE = TABLES.get("common_analysis", "tblLg3rwyn2KyrtT")
POLL_SECONDS = CFG.get("dispatcher", {}).get("poll_seconds", 20)


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


def extract_text(val):
    if val is None:
        return ""
    if isinstance(val, str):
        return val
    if isinstance(val, list):
        parts = []
        for item in val:
            if isinstance(item, dict):
                parts.append(item.get("text", ""))
            else:
                parts.append(str(item))
        return "".join(parts)
    return str(val)


def list_records(token, table_id, page_size=100):
    items = []
    page_token = None
    while True:
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/records?page_size={page_size}"
        if page_token:
            url += f"&page_token={page_token}"
        r = requests.get(url, headers=hdrs(token), timeout=20)
        d = r.json()
        if d.get("code") != 0:
            raise RuntimeError(f"list_records failed: {d}")
        items.extend(d["data"].get("items", []))
        if not d["data"].get("has_more"):
            break
        page_token = d["data"].get("page_token")
    return items


def log(msg, **kwargs):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    extra = " ".join(f"{k}={repr(v)}" for k, v in kwargs.items() if v is not None)
    line = f"[{ts}] {msg}"
    if extra:
        line += f" | {extra}"
    print(line, flush=True)


# ── 阶段分发映射 ─────────────────────────────────────────────────────────────

STAGE_SCRIPTS = {
    "single_video_analyze": "stages.single_video_analyze",
    "common_analysis": "stages.common_analysis",
    "variant_plan": "stages.variant_plan",
    "script_generate": "stages.script_generate",
    "storyboard_generate": "stages.storyboard_generate",
    "image_prompt_generate": "stages.image_prompt_generate",
    "video_prompt_generate": "stages.video_prompt_generate",
    "image_render_execute": "stages.image_render_execute",
}

STAGE_STATUS_MAP = {
    # status_field -> (trigger_value, stage_script_key)
    "多版本规划状态": {"待规划": "variant_plan"},
    "脚本生成状态": {"待生成": "script_generate"},
}


def dispatch_stage(stage_key, record_id):
    script_module = STAGE_SCRIPTS.get(stage_key)
    if not script_module:
        log("WARN", "unknown stage key", stage_key=stage_key)
        return False
    try:
        import importlib
        mod = importlib.import_module(script_module)
        mod.main([None, record_id])
        return True
    except Exception as e:
        log("ERROR", f"stage {stage_key} failed for record {record_id}", error=str(e)[:300])
        return False


def run_dispatch_loop():
    token = get_token()
    log("dispatcher started", poll_seconds=POLL_SECONDS)

    while True:
        try:
            token = get_token()
            material_records = list_records(token, MATERIALS_TABLE)
            for rec in material_records:
                fields = rec.get("fields", {})
                record_id = rec.get("record_id", "")
                analyze_status = extract_text(fields.get("单视频分析状态", ""))
                if analyze_status == "待分析":
                    log("INFO", "dispatching single_video_analyze", record_id=record_id)
                    dispatch_stage("single_video_analyze", record_id)
                    continue

            common_records = list_records(token, COMMON_ANALYSIS_TABLE)
            for rec in common_records:
                fields = rec.get("fields", {})
                record_id = rec.get("record_id", "")
                analyze_status = extract_text(fields.get("分析状态", ""))
                if analyze_status == "待执行":
                    log("INFO", "dispatching common_analysis", record_id=record_id)
                    dispatch_stage("common_analysis", record_id)
                    continue

            records = list_records(token, SCRIPT_TASKS_TABLE)

            for rec in records:
                fields = rec.get("fields", {})
                record_id = rec.get("record_id", "")

                # 检查 variant_plan
                plan_status = extract_text(fields.get("多版本规划状态", ""))
                if plan_status == "待规划":
                    role = extract_text(fields.get("记录角色", ""))
                    if not role or role == "批次母任务":
                        log("INFO", "dispatching variant_plan", record_id=record_id)
                        dispatch_stage("variant_plan", record_id)
                        continue

                # 检查 script_generate
                gen_status = extract_text(fields.get("脚本生成状态", ""))
                if gen_status == "待生成":
                    role = extract_text(fields.get("记录角色", ""))
                    if role == "版本任务":
                        log("INFO", "dispatching script_generate", record_id=record_id)
                        dispatch_stage("script_generate", record_id)
                        continue

                # 检查 storyboard_generate
                downstream_status = extract_text(fields.get("下游推进状态", ""))
                if downstream_status == "待分镜":
                    role = extract_text(fields.get("记录角色", ""))
                    selected = extract_text(fields.get("是否入选", ""))
                    if role == "版本任务" and (not selected or selected == "入选"):
                        log("INFO", "dispatching storyboard_generate", record_id=record_id)
                        dispatch_stage("storyboard_generate", record_id)
                        continue

                if downstream_status == "待生图":
                    role = extract_text(fields.get("记录角色", ""))
                    selected = extract_text(fields.get("是否入选", ""))
                    if role == "版本任务" and (not selected or selected == "入选"):
                        if extract_text(fields.get("生图提示词JSON", "")).strip():
                            log("INFO", "dispatching image_render_execute", record_id=record_id)
                            dispatch_stage("image_render_execute", record_id)
                        else:
                            log("INFO", "dispatching image_prompt_generate", record_id=record_id)
                            dispatch_stage("image_prompt_generate", record_id)
                        continue

                if downstream_status == "待图生视频":
                    role = extract_text(fields.get("记录角色", ""))
                    selected = extract_text(fields.get("是否入选", ""))
                    if role == "版本任务" and (not selected or selected == "入选"):
                        log("INFO", "dispatching video_prompt_generate", record_id=record_id)
                        dispatch_stage("video_prompt_generate", record_id)
                        continue

        except Exception as e:
            log("ERROR", "dispatch loop error", error=str(e)[:300])

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    run_dispatch_loop()