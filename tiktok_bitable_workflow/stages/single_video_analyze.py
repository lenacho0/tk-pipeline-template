#!/usr/bin/env python3
"""
阶段0：单视频分析
读取视频素材记录 → 调用 LLM 分析 → 写回 JSON / Markdown。
独立新项目，不挂接旧 tkpipeline。
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
CONFIG_TABLE = TABLES.get("config", "")
FALLBACK_NOTE_PREFIX = "single_video_analyze fallback"


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
            if not stage or ("单视频分析" not in stage and "single" not in stage.lower()):
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


def build_analysis_prompt(fields, runtime_cfg):
    prompt_template = runtime_cfg.get("prompt_template") or "你是一位短视频分析师，请输出 JSON_OUTPUT 和 MARKDOWN_OUTPUT。"
    source_platform = extract_text(fields.get("来源平台", ""))
    material_name = extract_text(fields.get("素材名称", ""))
    raw_link = extract_text(fields.get("原始链接", ""))
    attachment = fields.get("视频附件") or []
    attachment_urls = []
    if isinstance(attachment, list):
        for item in attachment:
            if isinstance(item, dict):
                url = item.get("url") or item.get("tmp_url") or item.get("file_token") or ""
                if url:
                    attachment_urls.append(str(url))
    blocks = [
        prompt_template,
        "",
        "【素材信息】",
        f"素材名称: {material_name}",
        f"来源平台: {source_platform}",
        f"原始链接: {raw_link}",
        f"视频附件: {'; '.join(attachment_urls) if attachment_urls else '无'}",
        "",
        "请严格按配置要求输出：JSON_OUTPUT → MARKDOWN_OUTPUT。",
    ]
    return "\n".join(blocks)


def extract_json_and_markdown(text):
    text = text.strip()
    json_text = ""
    markdown_text = text
    m = re.search(r"JSON_OUTPUT\s*(\{.*?\})\s*MARKDOWN_OUTPUT\s*(.*)$", text, re.S)
    if m:
        json_text = m.group(1).strip()
        markdown_text = m.group(2).strip()
        return json_text, markdown_text
    m = re.search(r"(\{.*\})", text, re.S)
    if m:
        candidate = m.group(1).strip()
        try:
            json.loads(candidate)
            json_text = candidate
            markdown_text = text.replace(candidate, "").strip() or text
            return json_text, markdown_text
        except Exception:
            pass
    return "", markdown_text


def build_fallback_payload(fields):
    material_name = extract_text(fields.get("素材名称", "")) or "未命名素材"
    raw_link = extract_text(fields.get("原始链接", ""))
    payload = {
        "title": material_name,
        "basic_info": {"source_platform": extract_text(fields.get("来源平台", "")), "url": raw_link},
        "video_overview": {"summary": "当前未能进入正式模型，先生成联调兜底分析结果。"},
        "distribution_engine": {},
        "conversion_engine": {},
        "script_breakdown": [],
        "comment_prediction": [],
        "copy_decision": {"status": "fallback_only"},
        "one_sentence_summary": "fallback 联调分析结果，仅用于链路验证。",
    }
    md = f"# {material_name}\n\n- 原始链接: {raw_link or '无'}\n- 说明: 当前使用 fallback 联调分析结果，仅用于链路验证。"
    return json.dumps(payload, ensure_ascii=False), md


def main(argv=None):
    argv = argv or sys.argv
    if len(argv) < 2:
        print("Usage: python3 single_video_analyze.py <material_record_id>")
        sys.exit(1)
    record_id = argv[1]
    token = get_token()
    log("INFO", "single_video_analyze start", record_id=record_id)
    update_record(token, MATERIALS_TABLE, record_id, {"单视频分析状态": "分析中", "备注": "single_video_analyze started"})
    try:
        fields = get_record(token, MATERIALS_TABLE, record_id)
        runtime_cfg = read_llm_runtime_config(token)
        runtime_mode = classify_runtime_mode(runtime_cfg)
        log("INFO", "runtime config resolved", record_id=record_id, runtime_mode=runtime_mode, source=runtime_cfg.get("source"), model=runtime_cfg.get("model"), has_api_key=bool(runtime_cfg.get("api_key")))
        prompt = build_analysis_prompt(fields, runtime_cfg)
        if runtime_mode != "formal_llm":
            json_text, md_text = build_fallback_payload(fields)
            note = build_fallback_note("missing api_key or api_base")
        else:
            client, model = get_llm_client(runtime_cfg)
            resp = with_retry(lambda: client.models.generate_content(model=model, contents=[prompt]), max_attempts=2, label="single_video_analyze")
            text = getattr(resp, "text", "") or ""
            if not text.strip():
                raise RuntimeError("LLM returned empty response")
            json_text, md_text = extract_json_and_markdown(text)
            if not json_text:
                raise RuntimeError("missing JSON_OUTPUT in model response")
            note = "single_video_analyze success (formal_llm)"
        update_record(token, MATERIALS_TABLE, record_id, {
            "单视频分析结果JSON": json_text,
            "单视频分析结果Markdown": md_text,
            "单视频分析状态": "已完成",
            "备注": note,
        })
        log("INFO", "single_video_analyze success", record_id=record_id, runtime_mode=runtime_mode)
    except Exception as e:
        err = str(e)[:500]
        update_record(token, MATERIALS_TABLE, record_id, {"单视频分析状态": "失败", "备注": err})
        log("ERROR", "single_video_analyze failed", record_id=record_id, error=err)
        raise


if __name__ == "__main__":
    main()
