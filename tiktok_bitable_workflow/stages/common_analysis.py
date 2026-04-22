#!/usr/bin/env python3
"""
阶段1：共性分析
读取共性分析任务 → 聚合单视频分析结果 → 调用 LLM → 写回 JSON / Markdown / 摘要。
"""
import json
import os
import re
import sys
import time
import requests

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
CONFIG_PATH = os.environ.get(
    "TIKTOK_BITABLE_CONFIG",
    os.path.join(PROJECT_DIR, "config.json")
)
if not os.path.isabs(CONFIG_PATH):
    CONFIG_PATH = os.path.abspath(os.path.join(PROJECT_DIR, CONFIG_PATH))


def load_config():
    if not os.path.exists(CONFIG_PATH):
        raise FileNotFoundError(f"Missing config: {CONFIG_PATH}")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


CFG = load_config()
FEISHU = CFG["feishu"]
LLM = CFG.get("llm", {})
TABLES = FEISHU["tables"]
APP_TOKEN = FEISHU["bitable_app_token"]
MATERIALS_TABLE = TABLES.get("materials", "tblQgQA587nzXgfX")
COMMON_ANALYSIS_TABLE = TABLES.get("common_analysis", "tblLg3rwyn2KyrtT")
CONFIG_TABLE = TABLES.get("config", "")
FALLBACK_NOTE_PREFIX = "common_analysis fallback"


def build_fallback_note(reason):
    return f"{FALLBACK_NOTE_PREFIX}: {reason}"[:500]


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


def sleep_backoff(attempt, base=1.5, cap=20):
    import random
    delay = min(cap, base * (2 ** max(0, attempt - 1)))
    delay += random.uniform(0, 0.5)
    time.sleep(delay)


def with_retry(fn, max_attempts=3, label="op"):
    last_err = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except Exception as e:
            last_err = e
            if attempt < max_attempts:
                log("WARN", f"{label} failed, retry", attempt=attempt, error=str(e)[:300])
                sleep_backoff(attempt)
            else:
                log("ERROR", f"{label} failed after {max_attempts} attempts", error=str(e)[:300])
    raise last_err


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


def parse_api_config_text(raw_text):
    raw = extract_text(raw_text).strip()
    if not raw:
        return {}
    try:
        if raw.startswith("{"):
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    result = {}
    for line in raw.splitlines():
        line = line.strip().strip(",")
        if not line or ":" not in line:
            continue
        k, v = line.split(":", 1)
        result[k.strip()] = v.strip().strip('"').strip("'")
    return result


def read_llm_runtime_config(token):
    runtime = {
        "provider": LLM.get("provider", "gemini-compatible"),
        "model": LLM.get("model", "gemini-2.5-flash"),
        "api_key": LLM.get("api_key", ""),
        "api_base": LLM.get("api_base", "https://aihubmix.com/gemini"),
        "source": "config.json",
    }
    if not CONFIG_TABLE:
        return runtime
    try:
        records = list_records(token, CONFIG_TABLE)
        for rec in records:
            flds = rec.get("fields", {})
            stage = extract_text(flds.get("环节名", "")).strip() or extract_text(flds.get("环节", "")).strip()
            if not stage or ("共性分析" not in stage and "common" not in stage.lower()):
                continue
            api_cfg = parse_api_config_text(flds.get("API配置", ""))
            return {
                "provider": extract_text(flds.get("provider", "")).strip() or api_cfg.get("provider") or runtime.get("provider"),
                "model": extract_text(flds.get("模型名", "")).strip() or extract_text(flds.get("模型名称", "")).strip() or api_cfg.get("model") or runtime.get("model"),
                "api_key": extract_text(flds.get("API Key", "")).strip() or api_cfg.get("api_key") or runtime.get("api_key"),
                "api_base": extract_text(flds.get("API 代理地址", "")).strip() or api_cfg.get("api_base") or runtime.get("api_base"),
                "prompt_template": extract_text(flds.get("系统提示词", "")).strip(),
                "source": f"bitable:{rec.get('record_id')}",
            }
    except Exception as e:
        log("WARN", "failed to read runtime config from bitable, fallback to config.json", error=str(e)[:300])
    return runtime


def classify_runtime_mode(runtime_cfg):
    return "formal_llm" if bool((runtime_cfg or {}).get("api_key")) else "fallback_only"


def get_llm_client(runtime_cfg=None):
    runtime_cfg = runtime_cfg or {}
    api_key = runtime_cfg.get("api_key") or LLM.get("api_key", "")
    api_base = runtime_cfg.get("api_base") or LLM.get("api_base", "https://aihubmix.com/gemini")
    model = runtime_cfg.get("model") or LLM.get("model", "gemini-2.5-flash")
    from google import genai
    client = genai.Client(api_key=api_key, http_options={"base_url": api_base})
    return client, model


def load_material_summaries(token, linked_ids):
    materials = []
    for rid in linked_ids:
        fields = get_record(token, MATERIALS_TABLE, rid)
        materials.append({
            "record_id": rid,
            "素材名称": extract_text(fields.get("素材名称", "")),
            "原始链接": extract_text(fields.get("原始链接", "")),
            "单视频分析结果JSON": extract_text(fields.get("单视频分析结果JSON", "")),
            "单视频分析结果Markdown": extract_text(fields.get("单视频分析结果Markdown", "")),
        })
    return materials


def build_prompt(task_fields, materials, runtime_cfg):
    prompt_template = runtime_cfg.get("prompt_template") or "你是一位短视频爆款共性分析师，请输出 JSON_OUTPUT、MARKDOWN_OUTPUT、SUMMARY_OUTPUT。"
    task_name = extract_text(task_fields.get("分析任务名称", "")) or "共性分析任务"
    chunks = [prompt_template, "", f"【任务名称】{task_name}", "", "【输入素材分析结果】"]
    for idx, item in enumerate(materials, start=1):
        chunks.extend([
            f"### 素材{idx}",
            f"record_id: {item['record_id']}",
            f"素材名称: {item['素材名称']}",
            f"原始链接: {item['原始链接']}",
            f"JSON: {item['单视频分析结果JSON']}",
            f"Markdown: {item['单视频分析结果Markdown']}",
            "",
        ])
    chunks.append("请严格输出：JSON_OUTPUT → MARKDOWN_OUTPUT → SUMMARY_OUTPUT。")
    return "\n".join(chunks)


def extract_outputs(text):
    text = (text or "").strip()

    patterns = [
        re.search(r"JSON_OUTPUT\s*(\{.*?\})\s*MARKDOWN_OUTPUT\s*(.*?)\s*SUMMARY_OUTPUT\s*(.*)$", text, re.S),
        re.search(r"JSON_OUTPUT\s*(\{.*?\})\s*TEXT_OUTPUT\s*(.*)$", text, re.S),
        re.search(r"^(\{.*?\})\s*TEXT_OUTPUT\s*(.*)$", text, re.S),
        re.search(r"JSON_OUTPUT\s*(\{.*\})\s*$", text, re.S),
        re.search(r"^(\{.*\})\s*$", text, re.S),
    ]
    for m in patterns:
        if not m:
            continue
        json_text = m.group(1).strip()
        body_text = m.group(2).strip() if len(m.groups()) >= 2 else ""
        summary = m.group(3).strip() if len(m.groups()) >= 3 else ""
        if not summary:
            try:
                payload = json.loads(json_text)
                summary = extract_text(payload.get("summary")) or extract_text(payload.get("one_sentence_summary"))
            except Exception:
                pass
        return json_text, body_text, summary

    return "", text, ""


def build_fallback_outputs(materials):
    summary = f"共分析 {len(materials)} 条素材，当前为 fallback 联调结果。"
    payload = {
        "material_count": len(materials),
        "common_patterns": [],
        "winning_hooks": [],
        "fallback": True,
        "summary": summary,
    }
    md = "# 共性分析（fallback）\n\n" + summary
    return json.dumps(payload, ensure_ascii=False), md, summary


def main(argv=None):
    argv = argv or sys.argv
    if len(argv) < 2:
        print("Usage: python3 common_analysis.py <common_analysis_record_id>")
        sys.exit(1)
    record_id = argv[1]
    token = get_token()
    log("INFO", "common_analysis start", record_id=record_id)
    update_record(token, COMMON_ANALYSIS_TABLE, record_id, {"分析状态": "执行中", "备注": "common_analysis started"})
    try:
        task_fields = get_record(token, COMMON_ANALYSIS_TABLE, record_id)
        linked_ids = extract_linked_ids(task_fields.get("关联视频素材"))
        if not linked_ids:
            raise RuntimeError("关联视频素材为空")
        materials = load_material_summaries(token, linked_ids)
        runtime_cfg = read_llm_runtime_config(token)
        runtime_mode = classify_runtime_mode(runtime_cfg)
        log("INFO", "runtime config resolved", record_id=record_id, runtime_mode=runtime_mode, source=runtime_cfg.get("source"), model=runtime_cfg.get("model"), has_api_key=bool(runtime_cfg.get("api_key")))
        if runtime_mode != "formal_llm":
            json_text, md_text, summary = build_fallback_outputs(materials)
            note = build_fallback_note("missing api_key or api_base")
        else:
            prompt = build_prompt(task_fields, materials, runtime_cfg)
            client, model = get_llm_client(runtime_cfg)
            resp = with_retry(lambda: client.models.generate_content(model=model, contents=[prompt]), max_attempts=2, label="common_analysis")
            text = getattr(resp, "text", "") or ""
            if not text.strip():
                raise RuntimeError("LLM returned empty response")
            log("INFO", "llm raw response preview", record_id=record_id, preview=text[:1200])
            json_text, md_text, summary = extract_outputs(text)
            if not json_text:
                raise RuntimeError("missing JSON_OUTPUT in model response")
            note = "common_analysis success (formal_llm)"
        update_record(token, COMMON_ANALYSIS_TABLE, record_id, {
            "聚合分析结果JSON": json_text,
            "聚合分析结果Markdown": md_text,
            "共性摘要": summary,
            "分析状态": "已完成",
            "备注": note,
        })
        log("INFO", "common_analysis success", record_id=record_id, runtime_mode=runtime_mode, material_count=len(materials))
    except Exception as e:
        err = str(e)[:500]
        update_record(token, COMMON_ANALYSIS_TABLE, record_id, {"分析状态": "失败", "备注": err})
        log("ERROR", "common_analysis failed", record_id=record_id, error=err)
        raise


if __name__ == "__main__":
    main()
