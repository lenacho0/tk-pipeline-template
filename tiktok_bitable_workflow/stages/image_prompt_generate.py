#!/usr/bin/env python3
"""
阶段4：生图提示词生成（第一版）
读取结构化脚本 JSON / 产品表 / 模特表 / 项目表场景信息，生成逐分镜生图提示词。
第一版只生成 JSON + Markdown，不直接调图片模型。
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
PROJECTS_TABLE = TABLES.get("projects", "")
PRODUCTS_TABLE = TABLES.get("products", "")
MODELS_TABLE = TABLES.get("models", "")


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


def extract_linked_ids(val):
    ids = []
    if isinstance(val, list):
        for item in val:
            if isinstance(item, dict) and item.get("record_ids"):
                ids.extend(item["record_ids"])
    return [i for i in ids if i]


def log(level, msg, **kwargs):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    extra = " ".join(f"{k}={repr(v)}" for k, v in kwargs.items() if v is not None)
    line = f"[{ts}] [{level}] {msg}"
    if extra:
        line += f" | {extra}"
    print(line, flush=True)


def get_project_context(token, fields):
    project_ids = extract_linked_ids(fields.get("所属项目") or fields.get("项目关联"))
    if not project_ids or not PROJECTS_TABLE:
        return {}
    try:
        pf = get_record(token, PROJECTS_TABLE, project_ids[0])
        return {
            "target_market": extract_text(pf.get("目标市场", "")) or extract_text(fields.get("目标市场", "")),
            "scene_reference_note": extract_text(pf.get("场景参考说明", "")),
        }
    except Exception:
        return {"target_market": extract_text(fields.get("目标市场", ""))}


def get_product_context(token, fields):
    product_ids = extract_linked_ids(fields.get("关联产品") or fields.get("产品关联"))
    if not product_ids or not PRODUCTS_TABLE:
        return {}
    pf = get_record(token, PRODUCTS_TABLE, product_ids[0])
    return {
        "product_name": extract_text(pf.get("产品名称-th", "")) or extract_text(pf.get("产品名称", "")),
        "product_truth": extract_text(pf.get("产品描述", "")),
        "selling_points": extract_text(pf.get("核心卖点", "")) or extract_text(pf.get("产品卖点", "")),
    }


def get_model_context(token, fields):
    model_ids = extract_linked_ids(fields.get("关联模特") or fields.get("模特关联"))
    if not model_ids or not MODELS_TABLE:
        return {}
    mf = get_record(token, MODELS_TABLE, model_ids[0])
    return {
        "model_name": extract_text(mf.get("模特名称", "")),
        "appearance": extract_text(mf.get("外观描述", "")) or extract_text(mf.get("模特描述", "")),
        "style": extract_text(mf.get("出镜风格", "")) or extract_text(mf.get("模特描述", "")),
    }


def build_prompt_items(structured, project_ctx, product_ctx, model_ctx):
    shots = structured.get("shots", [])
    items = []
    for idx, shot in enumerate(shots, start=1):
        prompt = (
            f"竖屏 TikTok 分镜，分镜 {idx}。"
            f"场景：{shot.get('visual_description','')}。"
            f"人物：{model_ctx.get('appearance','真实自然出镜人物')}。"
            f"产品：{product_ctx.get('product_name','当前产品')}，特征：{product_ctx.get('product_truth','')}。"
            f"卖点聚焦：{product_ctx.get('selling_points','')}。"
            f"市场语境：{project_ctx.get('target_market','目标市场本土化场景')}。"
            f"场景参考：{project_ctx.get('scene_reference_note','')}。"
            f"构图提示：{shot.get('prompt_text','')}。"
            f"无美颜，无滤镜，真实皮肤纹理，真实环境。no text, no watermark, no subtitle"
        )
        items.append({
            "shot_number": shot.get("shot_number", f"分镜 {idx}"),
            "brief": shot.get("visual_description", ""),
            "prompt": prompt,
        })
    return items


def render_markdown(items):
    lines = ["# 生图提示词", ""]
    for item in items:
        lines.append(f"## {item['shot_number']}")
        lines.append(f"- brief: {item['brief']}")
        lines.append(f"- prompt: {item['prompt']}")
        lines.append("")
    return "\n".join(lines).strip()


def main(argv=None):
    argv = argv or sys.argv
    if len(argv) < 2:
        print("Usage: python3 stages/image_prompt_generate.py <record_id>")
        sys.exit(1)

    record_id = argv[1]
    token = get_token()
    fields = get_record(token, SCRIPT_TASKS_TABLE, record_id)

    raw = extract_text(fields.get("结构化脚本JSON", "")).strip()
    if not raw:
        raise RuntimeError("缺少结构化脚本JSON")
    structured = json.loads(raw)

    project_ctx = get_project_context(token, fields)
    product_ctx = get_product_context(token, fields)
    model_ctx = get_model_context(token, fields)
    items = build_prompt_items(structured, project_ctx, product_ctx, model_ctx)

    update_record(token, SCRIPT_TASKS_TABLE, record_id, {
        "生图提示词JSON": json.dumps({"shots": items}, ensure_ascii=False, indent=2),
        "生图提示词Markdown": render_markdown(items)[:8000],
        "下游推进状态": "待图生视频",
    })
    log("INFO", "image_prompt_generate success", record_id=record_id, shot_count=len(items))


if __name__ == "__main__":
    main()
