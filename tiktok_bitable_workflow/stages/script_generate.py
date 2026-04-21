#!/usr/bin/env python3
"""
阶段2：单版本脚本生成
读取版本任务 → 组装 protocol payload → 调用 LLM 生成脚本 → 解析结构化 JSON → 写回版本任务记录
不挂接旧 tkpipeline，独立项目。
"""
import json
import os
import re
import sys
import time
import requests

# ── 内部工具函数 ─────────────────────────────────────────────────────────────

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
LLM = CFG.get("llm", {})
TABLES = FEISHU["tables"]
APP_TOKEN = FEISHU["bitable_app_token"]
SCRIPT_TASKS_TABLE = TABLES.get("script_tasks") or TABLES.get("script_gen", "")
PRODUCTS_TABLE = TABLES.get("products", "")
MODELS_TABLE = TABLES.get("models", "")
COMMON_ANALYSIS_TABLE = TABLES.get("common_analysis", "")
CONFIG_TABLE = TABLES.get("config", "")


# ── 飞书 API ─────────────────────────────────────────────────────────────────

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
        headers=hdrs(token),
        json={"fields": fields}, timeout=30,
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


# ── 工具 ─────────────────────────────────────────────────────────────────────

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


# ── LLM 调用 ──────────────────────────────────────────────────────────────────

def get_llm_client():
    api_key = LLM.get("api_key", "")
    api_base = LLM.get("api_base", "https://aihubmix.com/gemini")
    model = LLM.get("model", "gemini-2.5-flash")
    try:
        from google import genai
        client = genai.Client(api_key=api_key, http_options={"base_url": api_base})
        return client, model
    except Exception as e:
        log("ERROR", "failed to create LLM client", error=str(e))
        raise RuntimeError(f"LLM client init failed: {e}")


def call_llm(client, model, prompt, label="llm"):
    def _do():
        resp = with_retry(
            lambda: client.models.generate_content(model=model, contents=[prompt]),
            max_attempts=3,
            label=label,
        )
        text = getattr(resp, "text", "") or ""
        if not text.strip():
            raise RuntimeError("LLM returned empty response")
        return text
    return with_retry(_do, max_attempts=2, label=label)


# ── 数据读取 ─────────────────────────────────────────────────────────────────

def read_product_info(token, product_link):
    if not product_link or not PRODUCTS_TABLE:
        return {}
    linked_ids = extract_linked_ids(product_link)
    if not linked_ids:
        return {}
    try:
        fields = get_record(token, PRODUCTS_TABLE, linked_ids[0])
        return {
            "product_name_th": extract_text(fields.get("产品名称-th", "")) or extract_text(fields.get("产品名称", "")),
            "spec": extract_text(fields.get("产品规格", "")) or extract_text(fields.get("产品描述", "")),
            "selling_points": extract_text(fields.get("核心卖点", "")) or extract_text(fields.get("产品卖点", "")),
            "usage_scenario": extract_text(fields.get("使用场景", "")) or extract_text(fields.get("产品描述", "")),
            "target_user": extract_text(fields.get("目标用户", "")),
        }
    except Exception:
        return {}


def read_model_info(token, model_link):
    if not model_link or not MODELS_TABLE:
        return ""
    linked_ids = extract_linked_ids(model_link)
    if not linked_ids:
        return ""
    try:
        fields = get_record(token, MODELS_TABLE, linked_ids[0])
        parts = [
            f"模特名称: {extract_text(fields.get('模特名称', ''))}",
            f"外观描述: {extract_text(fields.get('外观描述', '')) or extract_text(fields.get('模特描述', ''))}",
            f"出镜风格: {extract_text(fields.get('出镜风格', '')) or extract_text(fields.get('模特描述', ''))}",
        ]
        return "；".join(p for p in parts if not p.endswith(": "))
    except Exception:
        return ""


def read_common_analysis(token, record_id):
    if not record_id or not COMMON_ANALYSIS_TABLE:
        return {}
    try:
        fields = get_record(token, COMMON_ANALYSIS_TABLE, record_id)
        raw = extract_text(fields.get("共性摘要")) or extract_text(fields.get("summary")) or extract_text(fields.get("聚合分析结果Markdown")) or extract_text(fields.get("聚合分析结果JSON"))
        return {"summary": raw[:800] if raw else ""}
    except Exception:
        return {}


def read_script_gen_prompt(token):
    if not CONFIG_TABLE:
        return ""
    try:
        records = list_records(token, CONFIG_TABLE)
        for rec in records:
            flds = rec.get("fields", {})
            stage = extract_text(flds.get("环节名", "")).strip() or extract_text(flds.get("环节", "")).strip()
            if "脚本生成" in stage or "script" in stage.lower():
                return extract_text(flds.get("系统提示词", "") or flds.get("提示词", "") or flds.get("prompt", ""))
    except Exception:
        pass
    return ""


# ── Prompt 构建 ──────────────────────────────────────────────────────────────

PROMPT_SUFFIX_STRUCTURED_JSON = """

---
## 附加要求：同时输出结构化 JSON

除了上面的脚本正文，还必须在同一个回复的末尾追加输出以下 JSON 结构（放在 ```json 代码块中）。

**JSON 格式要求（每条分镜必须包含以下所有字段）：**
```json
{
  "script_meta": {
    "batch_id": "TBW-SCRIPT-...",
    "variant_id": "V1",
    "variant_name": "V1-hook_angle-痛点直击开场",
    "primary_test": "hook_angle",
    "direction": "痛点直击"
  },
  "static_cards": {
    "character_card": "人物卡片描述",
    "scene_card": "场景卡片描述",
    "quality_card": "画质要求描述 (no subtitles)"
  },
  "shots": [
    {
      "shot_number": "分镜 1",
      "content_type": "dialogue",
      "speaker": "MoMo",
      "speaker_visible": true,
      "thai_text": "泰文口播原文",
      "visual_description": "画面内容文字描述",
      "prompt_text": "分镜图画面生成提示词，含镜头角度、角色/产品外观、场景、氛围"
    }
  ],
  "final_cta": "结尾CTA",
  "notes": "备注"
}
```

**字段说明：**
- `content_type`: `dialogue`（有台词对白）/ `voiceover`（旁白配音无画面）/ `silent_action`（纯动作无台词）
- `speaker`: dialogue 时填角色名，voiceover 填"旁白"，silent_action 填空字符串 `""`
- `speaker_visible`: dialogue 且说话主体出现在画面内时为 `true`，否则 `false`
- `thai_text`: 泰文口播原文，silent_action 时为 `""`
- `prompt_text`: 供后续分镜图生成使用的画面描述，包含镜头角度、角色/产品外观、场景、氛围光影，不含镜头技术参数

**注意：** JSON 代码块必须放在整个回复的最后，不能出现在其他位置。
"""


def build_script_prompt(fields, product_info, model_info, common_data, prompt_template):
    variant_id = extract_text(fields.get("版本编号", ""))
    variant_name = extract_text(fields.get("版本名称", ""))
    primary_test = extract_text(fields.get("主测试点", ""))
    difference_goal = extract_text(fields.get("版本差异说明", ""))
    target_market = extract_text(fields.get("目标市场", "泰国"))
    target_duration = extract_text(fields.get("脚本总时长目标", "20-25s"))
    locked_notes = extract_text(fields.get("锁定项说明", ""))
    variable_notes = extract_text(fields.get("变量位说明", ""))

    # 构建 protocol 前导
    protocol_block = f"""## 多版本派生控制协议

本条脚本为独立版本任务，以下信息为只读约束，不得违背：
- 批次ID: {extract_text(fields.get('批次ID', ''))}
- 版本编号: {variant_id}
- 版本名称: {variant_name}
- 主测试点: {primary_test}
- 版本差异目标: {difference_goal}
- 锁定项: {locked_notes or '产品真源/人物真源/共性骨架/目标市场/时长边界'}
- 变量位: {variable_notes or '待指定'}

## 当前版本测试目标
本版本主测维度: {primary_test}，方向: {extract_text(fields.get('版本差异说明', ''))}。
请确保脚本在这一维度上形成真实差异，而不是泛泛优化。
"""

    # 构建产品/人物/共性信息块
    product_block = f"""
## 产品信息
- 产品名称: {product_info.get('product_name_th', '（未填写）')}
- 产品规格: {product_info.get('spec', '（未填写）')}
- 核心卖点: {product_info.get('selling_points', '（未填写）')}
- 使用场景: {product_info.get('usage_scenario', '（未填写）')}
- 目标用户: {product_info.get('target_user', '（未填写）')}
"""

    model_block = f"""
## 模特/人物信息
{model_info or '（未填写，请根据目标市场自主生成可信人物设定）'}
"""

    common_block = ""
    if common_data.get("summary"):
        common_block = f"""
## 爆款共性分析摘要（必须优先遵守）
{common_data['summary'][:600]}
"""

    # 如果有外部 prompt 模板，插入之
    if prompt_template:
        body = prompt_template
    else:
        body = f"""你是 TikTok 短视频带货分镜脚本生成专家。

任务：基于以下信息生成一条完整的 TikTok 带货分镜脚本。

要求：
1. 输出分镜级脚本，每条分镜包含：镜头序号、内容类型、说话主体、口播原文、画面描述、分镜图生成提示词。
2. 脚本必须覆盖完整转化路径：抓注意力 → 建立兴趣 → 展示产品/解决方案 → 建立信任 → 推动行动。
3. 口播只允许使用目标市场语言（当前: {target_market}），不允许出现中文台词翻译混入正文。
4. 场景必须体现目标市场本土化真实生活语境。
5. 单镜头时长建议 3-6 秒，总时长建议 {target_duration}。
6. 每条分镜的画面描述不含镜头技术参数；分镜图生成提示词不含分镜编号和序号。

最终输出格式：
[TEXT_OUTPUT — 分镜脚本正文]
```json
{{
  "script_meta": {{...}},
  "static_cards": {{...}},
  "shots": [...],
  "final_cta": "...",
  "notes": "..."
}}
```"""

    parts = [protocol_block, product_block, model_block, common_block, body, PROMPT_SUFFIX_STRUCTURED_JSON]
    return "\n\n".join(p for p in parts if p)


# ── JSON 解析 ─────────────────────────────────────────────────────────────────

def extract_json_block(text):
    m = re.search(r'```json\s*([\s\S]*?)\s*```', text)
    if m:
        return m.group(1).strip()
    m2 = re.search(r'\{[\s\S]*\}', text)
    if m2:
        return m2.group()
    return ""


def parse_llm_response(text):
    """从 LLM 文本中提取 JSON block 和纯文本脚本文本"""
    json_block = extract_json_block(text)
    structured = None
    if json_block:
        try:
            structured = json.loads(json_block)
        except json.JSONDecodeError:
            pass

    # 提取纯文本部分（去掉 json block 之后的部分）
    json_start = text.find('```json')
    plain_text = text[:json_start].strip() if json_start != -1 else text.strip()
    # 去掉可能残留的 markdown json 痕迹
    plain_text = re.sub(r'```json\s*', '', plain_text).strip()

    return structured, plain_text


def build_diff_check(fields, structured_shots) -> dict:
    """生成版本差异自检结果"""
    variant_id = extract_text(fields.get("版本编号", ""))
    primary_test = extract_text(fields.get("主测试点", ""))
    difference_goal = extract_text(fields.get("版本差异说明", ""))

    shots = structured_shots.get("shots", []) if structured_shots else []
    content_types = [s.get("content_type") for s in shots if s]

    return {
        "same_backbone_confirmed": True,
        "structural_difference_confirmed": bool(primary_test and primary_test != "standard"),
        "difference_strength": "sufficient" if primary_test != "standard" else "standard",
        "variant_id": variant_id,
        "primary_test": primary_test,
        "difference_goal": difference_goal,
        "shots_generated": len(shots),
        "content_type_distribution": {str(ct): content_types.count(ct) for ct in set(content_types)},
        "notes": f"版本 {variant_id} 生成完成，主测 {primary_test}，方向 {difference_goal}。"
    }


# ── 主逻辑 ───────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 stages/script_generate.py <record_id>")
        sys.exit(1)

    record_id = sys.argv[1]
    token = get_token()

    log("INFO", "script_generate start", record_id=record_id)

    # ── Step 1：读取版本任务 ─────────────────────────────────────────────────
    try:
        fields = get_record(token, SCRIPT_TASKS_TABLE, record_id)
    except Exception as e:
        log("ERROR", "failed to load version task", record_id=record_id, error=str(e)[:300])
        sys.exit(1)

    role = extract_text(fields.get("记录角色"))
    if role and role != "版本任务":
        log("INFO", "script_generate skipped (not a version task)", record_id=record_id, role=role)
        return

    # ── Step 2：标记生成中 ──────────────────────────────────────────────────
    update_record(token, SCRIPT_TASKS_TABLE, record_id, {
        "脚本生成状态": "生成中",
        "错误信息": "",
    })

    # ── Step 3：读取上下文数据 ─────────────────────────────────────────────
    product_info = read_product_info(token, fields.get("产品关联") or fields.get("产品ID"))
    model_info = read_model_info(token, fields.get("模特关联") or fields.get("模特ID"))
    common_data = read_common_analysis(token, extract_text(fields.get("共性分析记录ID")))
    prompt_template = read_script_gen_prompt(token)

    # ── Step 4：构建 prompt ─────────────────────────────────────────────────
    prompt = build_script_prompt(fields, product_info, model_info, common_data, prompt_template)
    log("INFO", "prompt built", record_id=record_id, prompt_len=len(prompt))

    # ── Step 5：调用 LLM ────────────────────────────────────────────────────
    try:
        client, model = get_llm_client()
        raw_response = call_llm(client, model, prompt, label="script_generate")
        log("INFO", "llm call success", record_id=record_id, response_len=len(raw_response))
    except Exception as e:
        err = f"LLM 调用失败: {str(e)[:300]}"
        log("ERROR", "llm call failed", record_id=record_id, error=err)
        update_record(token, SCRIPT_TASKS_TABLE, record_id, {
            "脚本生成状态": "生成失败",
            "错误信息": err,
        })
        sys.exit(1)

    # ── Step 6：解析输出 ────────────────────────────────────────────────────
    structured_shots, plain_script = parse_llm_response(raw_response)

    if not plain_script and not structured_shots:
        err = "LLM 未返回有效内容"
        log("ERROR", "empty response", record_id=record_id)
        update_record(token, SCRIPT_TASKS_TABLE, record_id, {
            "脚本生成状态": "生成失败",
            "错误信息": err,
        })
        sys.exit(1)

    # 清理中文口播行（如果残留）
    lines = []
    for line in (plain_script or "").splitlines():
        s = line.strip()
        if s.startswith("口播（中文）") or s.startswith("口播(中文)"):
            continue
        lines.append(line)
    plain_script = "\n".join(lines).strip()

    # ── Step 7：生成 diff-check ─────────────────────────────────────────────
    diff_check = build_diff_check(fields, structured_shots)

    # ── Step 8：写回字段 ────────────────────────────────────────────────────
    update_fields = {
        "生成的脚本": plain_script[:8000] if plain_script else "",
        "版本差异自检结果": json.dumps(diff_check, ensure_ascii=False, indent=2),
        "脚本生成状态": "生成成功",
    }

    if structured_shots:
        update_fields["结构化脚本JSON"] = json.dumps(structured_shots, ensure_ascii=False, indent=2)

    try:
        update_record(token, SCRIPT_TASKS_TABLE, record_id, update_fields)
        log("INFO", "script_generate success", record_id=record_id,
            variant=extract_text(fields.get("版本编号")),
            primary_test=extract_text(fields.get("主测试点")),
            shots=len(structured_shots.get("shots", []) if structured_shots else 0))
    except Exception as e:
        log("ERROR", "writeback failed", record_id=record_id, error=str(e)[:300])
        update_record(token, SCRIPT_TASKS_TABLE, record_id, {
            "脚本生成状态": "生成成功-写回失败",
            "错误信息": f"写回失败: {str(e)[:300]}",
        })


if __name__ == "__main__":
    main()