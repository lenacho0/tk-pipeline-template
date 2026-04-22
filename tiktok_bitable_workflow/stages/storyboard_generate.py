#!/usr/bin/env python3
"""
阶段3：分镜生成（第一版）
读取版本任务的结构化脚本JSON → 优先直接拆 shots → 回写分镜列表 Markdown / 分镜图状态JSON。
第一版先不做真实图片生成，只把 storyboard 结构跑通。
"""
import json, os, sys, time, requests

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
    r = requests.post("https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal", json={"app_id": FEISHU["app_id"], "app_secret": FEISHU["app_secret"]}, timeout=15)
    d = r.json()
    if "tenant_access_token" not in d:
        raise RuntimeError(f"Feishu token failed: {d}")
    return d["tenant_access_token"]

def hdrs(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

def get_record(token, table_id, record_id):
    r = requests.get(f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/records/{record_id}", headers=hdrs(token), timeout=20)
    d = r.json()
    if d.get("code") != 0:
        raise RuntimeError(f"get_record failed: {d}")
    return d["data"]["record"]["fields"]

def update_record(token, table_id, record_id, fields):
    r = requests.put(f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/records/{record_id}", headers=hdrs(token), json={"fields": fields}, timeout=30)
    d = r.json()
    if d.get("code") != 0:
        raise RuntimeError(f"update_record failed: {d}")
    return d

def extract_text(val):
    if val is None: return ""
    if isinstance(val, str): return val
    if isinstance(val, list):
        return "".join(item.get("text", "") if isinstance(item, dict) else str(item) for item in val)
    return str(val)

def log(level, msg, **kwargs):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    extra = " ".join(f"{k}={repr(v)}" for k, v in kwargs.items() if v is not None)
    line = f"[{ts}] [{level}] {msg}"
    if extra: line += f" | {extra}"
    print(line, flush=True)

def render_markdown(shots):
    lines = ["# 分镜列表", ""]
    for idx, shot in enumerate(shots, start=1):
        lines.append(f"## 分镜 {idx}")
        lines.append(f"- 类型：{shot.get('content_type','')}")
        lines.append(f"- 说话主体：{shot.get('speaker','')}")
        lines.append(f"- 泰文口播：{shot.get('thai_text','')}")
        lines.append(f"- 画面描述：{shot.get('visual_description','')}")
        lines.append(f"- Prompt：{shot.get('prompt_text','')}")
        lines.append("")
    return "\n".join(lines).strip()

def main(argv=None):
    argv = argv or sys.argv
    if len(argv) < 2:
        print("Usage: python3 stages/storyboard_generate.py <record_id>")
        sys.exit(1)
    record_id = argv[1]
    token = get_token()
    fields = get_record(token, SCRIPT_TASKS_TABLE, record_id)
    raw = extract_text(fields.get("结构化脚本JSON", "")).strip()
    if not raw:
        raise RuntimeError("缺少结构化脚本JSON")
    data = json.loads(raw)
    shots = data.get("shots", [])
    markdown = render_markdown(shots)
    state = {"source": "structured_script_json", "shot_count": len(shots), "generated_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    update_record(token, SCRIPT_TASKS_TABLE, record_id, {"分镜列表Markdown": markdown[:8000], "分镜图状态JSON": json.dumps(state, ensure_ascii=False, indent=2), "下游推进状态": "待生图"})
    log("INFO", "storyboard_generate success", record_id=record_id, shots=len(shots))

if __name__ == "__main__":
    main()
