#!/usr/bin/env python3
"""
阶段1：多版本批次规划
读取批次母任务 → 校验/补默认值 → 生成版本分配 → 预创建版本任务记录 → 更新母任务状态
不挂接旧 tkpipeline，独立项目。
"""
import json
import os
import sys
import time
import requests

# ── 内部工具函数（不依赖旧 tkpipeline common） ──────────────────────────────

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
PRODUCTS_TABLE = TABLES.get("products", "")
MODELS_TABLE = TABLES.get("models", "")
COMMON_ANALYSIS_TABLE = TABLES.get("common_analysis", "")


# ── 飞书 API ─────────────────────────────────────────────────────────────────

def get_token():
    r = requests.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": FEISHU["app_id"], "app_secret": FEISHU["app_secret"]},
        timeout=15,
    )
    data = r.json()
    if "tenant_access_token" not in data:
        raise RuntimeError(f"Feishu token failed: {data}")
    return data["tenant_access_token"]


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


def create_records(token, table_id, records):
    if not records:
        return []
    created = []
    for i in range(0, len(records), 10):
        batch = records[i : i + 10]
        r = requests.post(
            f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/records/batch_create",
            headers=hdrs(token),
            json={"records": [{"fields": rec} for rec in batch]}, timeout=30,
        )
        d = r.json()
        if d.get("code") != 0:
            raise RuntimeError(f"batch create failed: {d}")
        created.extend(d.get("data", {}).get("records", []))
    return created


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


# ── 核心逻辑 ─────────────────────────────────────────────────────────────────

DEFAULT_VARIANT_PLANS = {
    "hook_angle": [
        {"variant_id": "V1", "variant_name": "V1-hook_angle-痛点直击开场", "primary_test": "hook_angle", "direction": "痛点直击", "difference_goal": "用宠物毛发困扰直击开场，测试是否最容易抓住注意力。"},
        {"variant_id": "V2", "variant_name": "V2-hook_angle-结果前置开场", "primary_test": "hook_angle", "direction": "结果前置", "difference_goal": "用清洁后效果结果前置开场，测试是否更容易建立兴趣。"},
    ],
    "scene_entry": [
        {"variant_id": "V1", "variant_name": "V1-scene_entry-家庭日常切入", "primary_test": "scene_entry", "direction": "家庭日常切入", "difference_goal": "从家庭沙发场景切入，测试生活化场景是否更自然。"},
        {"variant_id": "V2", "variant_name": "V2-scene_entry-出门前切入", "primary_test": "scene_entry", "direction": "出门前切入", "difference_goal": "从出门前紧急清洁场景切入，测试紧迫感场景是否更有力。"},
    ],
    "trust_builder": [
        {"variant_id": "V1", "variant_name": "V1-trust_builder-个人体验", "primary_test": "trust_builder", "direction": "个人体验", "difference_goal": "用第一人称个人使用体验建立信任，测试真实感是否更强。"},
        {"variant_id": "V2", "variant_name": "V2-trust_builder-前后对比", "primary_test": "trust_builder", "direction": "前后对比", "difference_goal": "用清洁前后对比建立信任，测试证据感是否更强。"},
    ],
}


def fill_defaults(fields):
    """补足多版本控制字段默认值"""
    raw_dims = fields.get("测试维度") or []
    if isinstance(raw_dims, str):
        dims = [d.strip() for d in raw_dims.split(",") if d.strip()]
    elif isinstance(raw_dims, list):
        dims = [str(d).strip() for d in raw_dims]
    else:
        dims = []
    if "auto" in dims:
        dims = ["auto"]

    return {
        "script_generation_mode": extract_text(fields.get("脚本生成模式")) or "多版本受控派生",
        "target_variant_count": max(1, min(int(fields.get("目标版本数") or 3), 4)),
        "testing_dimensions": dims or ["auto"],
        "derivation_strategy": extract_text(fields.get("派生策略")) or "S3 系统推荐探索",
        "difference_level": extract_text(fields.get("版本差异强度")) or "标准",
        "target_duration": extract_text(fields.get("脚本总时长目标")) or "20-25s",
    }


def build_batch_id(project_id, parent_record_id):
    now = time.strftime("%Y%m%d-%H%M%S")
    proj = extract_text(project_id) or "PJ"
    return f"TBW-SCRIPT-{proj}-{now}-{parent_record_id[-6:]}"


def plan_variants(defaults):
    count = defaults["target_variant_count"]
    mode = defaults["script_generation_mode"]
    if mode == "单版本标准生成" or count == 1:
        return [{
            "variant_id": "V1",
            "variant_name": "V1-standard-标准生成",
            "primary_test": "standard",
            "secondary_test": "",
            "direction": "standard",
            "difference_goal": "标准单版本生成，不做多版本派生。",
        }]

    dims = defaults["testing_dimensions"]
    if "auto" in dims:
        dims = ["hook_angle", "scene_entry", "trust_builder"]

    pool = []
    for dim in dims:
        pool.extend(DEFAULT_VARIANT_PLANS.get(dim, []))
    if not pool:
        pool = DEFAULT_VARIANT_PLANS["hook_angle"]

    return pool[:count]


def build_locked_notes(product_info, model_info, common_summary):
    parts = [
        "锁定产品真源",
        "锁定人物真源",
        "锁定共性脚本主骨架" if common_summary else "",
        "锁定目标市场本土化语境",
        "锁定总时长区间",
    ]
    return "；".join(p for p in parts if p)


def build_variable_notes(testing_dims, variants):
    dim_map = {
        "hook_angle": "开场 hook 切入角度",
        "scene_entry": "场景切入方式",
        "trust_builder": "信任建立方式",
        "cta_style": "CTA 推动方式",
        "tone_style": "口播语气风格",
    }
    changed = ", ".join(dim_map.get(d, d) for d in testing_dims if d != "auto")
    locked = "产品核心卖点主轴 / 人物身份底色 / 目标市场 / 转化路径骨架"
    return f"允许变化：{changed or '待指定'}；锁定：{locked}"


def read_common_analysis_summary(token, record_id):
    """从共性分析表读取摘要文本"""
    if not record_id or not COMMON_ANALYSIS_TABLE:
        return ""
    try:
        fields = get_record(token, COMMON_ANALYSIS_TABLE, record_id)
        raw = extract_text(fields.get("共性摘要")) or extract_text(fields.get("summary")) or extract_text(fields.get("文本输出"))
        return raw[:600] if raw else ""
    except Exception:
        return ""


def read_product_info(token, product_link):
    """从产品表读取产品信息摘要"""
    if not product_link or not PRODUCTS_TABLE:
        return {}
    linked_ids = extract_linked_ids(product_link)
    if not linked_ids:
        return {}
    try:
        fields = get_record(token, PRODUCTS_TABLE, linked_ids[0])
        return {
            "产品名称-th": extract_text(fields.get("产品名称-th", "")),
            "产品规格": extract_text(fields.get("产品规格", "")),
            "核心卖点": extract_text(fields.get("核心卖点", "")),
            "使用场景": extract_text(fields.get("使用场景", "")),
            "目标用户": extract_text(fields.get("目标用户", "")),
        }
    except Exception:
        return {}


def build_child_record(parent_record_id, parent_fields, defaults, batch_id, variant, locked, variable, common_summary):
    """构建一个版本任务子记录的字段字典"""
    passthrough = [
        "项目ID", "项目名称", "共性分析记录ID",
        "产品ID", "产品名称", "产品关联",
        "模特ID", "模特名称", "模特关联",
        "目标市场", "场景参考图", "场景参考说明",
        "目标时长", "视频时长",
    ]
    child = {}
    for key in passthrough:
        val = parent_fields.get(key)
        if val is not None:
            child[key] = val

    child.update({
        "记录角色": "版本任务",
        "父任务ID": parent_record_id,
        "批次ID": batch_id,
        "脚本生成模式": defaults["script_generation_mode"],
        "目标版本数": defaults["target_variant_count"],
        "测试维度": defaults["testing_dimensions"],
        "派生策略": defaults["derivation_strategy"],
        "版本差异强度": defaults["版本差异强度"],
        "脚本总时长目标": defaults["target_duration"],
        "版本编号": variant["variant_id"],
        "版本名称": variant["variant_name"],
        "主测试点": variant["primary_test"],
        "次测试点": variant.get("secondary_test", ""),
        "版本差异说明": variant["difference_goal"],
        "锁定项说明": locked,
        "变量位说明": variable,
        "共性骨架摘要": common_summary or "（待从共性分析表读取）",
        "脚本生成状态": "待生成",
        "下游推进状态": "未推进",
        "是否入选": "待定",
        "多版本规划状态": "已跳过",
        "生成模式": "多版本受控派生",
        "变异策略": defaults["derivation_strategy"],
    })
    return child


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 stages/variant_plan.py <record_id>")
        sys.exit(1)

    record_id = sys.argv[1]
    token = get_token()

    # ── Step 1：读取母任务 ───────────────────────────────────────────────────
    log("INFO", "variant_plan start", record_id=record_id)
    try:
        parent = get_record(token, SCRIPT_TASKS_TABLE, record_id)
    except Exception as e:
        log("ERROR", "failed to load parent task", record_id=record_id, error=str(e)[:300])
        sys.exit(1)

    role = extract_text(parent.get("记录角色"))
    if role and role != "批次母任务":
        log("INFO", "variant_plan skipped (not a parent task)", record_id=record_id, role=role)
        return

    # ── Step 2：写入规划中状态 ───────────────────────────────────────────────
    update_record(token, SCRIPT_TASKS_TABLE, record_id, {"多版本规划状态": "规划中"})

    # ── Step 3：读取产品/共性分析辅助信息 ───────────────────────────────────
    common_summary = read_common_analysis_summary(token, extract_text(parent.get("共性分析记录ID")) or (extract_linked_ids(parent.get("关联共性分析"))[0] if extract_linked_ids(parent.get("关联共性分析")) else ""))
    product_info = read_product_info(token, parent.get("关联产品") or parent.get("产品关联") or parent.get("产品ID"))

    # ── Step 4：补默认值 & 生成批次ID ────────────────────────────────────────
    defaults = fill_defaults(parent)
    batch_id = build_batch_id(parent.get("项目ID"), record_id)
    log("INFO", "batch_id generated", batch_id=batch_id, defaults=repr(defaults))

    # ── Step 5：版本规划 ─────────────────────────────────────────────────────
    variants = plan_variants(defaults)
    locked = build_locked_notes(product_info, {}, common_summary)
    variable = build_variable_notes(defaults["testing_dimensions"], variants)
    log("INFO", "variants planned", count=len(variants), variants=[v["variant_id"] for v in variants])

    # ── Step 6：构建子记录列表 ───────────────────────────────────────────────
    child_fields_list = [
        build_child_record(record_id, parent, defaults, batch_id, v, locked, variable, common_summary)
        for v in variants
    ]

    # ── Step 7：批量创建版本任务记录 ────────────────────────────────────────
    try:
        created = create_records(token, SCRIPT_TASKS_TABLE, child_fields_list)
        log("INFO", "child records created", count=len(created))
    except Exception as e:
        log("ERROR", "failed to create child records", record_id=record_id, error=str(e)[:300])
        update_record(token, SCRIPT_TASKS_TABLE, record_id, {
            "多版本规划状态": "规划失败",
            "错误信息": f"创建子记录失败: {str(e)[:300]}",
        })
        sys.exit(1)

    # ── Step 8：更新母任务状态 ───────────────────────────────────────────────
    update_record(token, SCRIPT_TASKS_TABLE, record_id, {
        "记录角色": "批次母任务",
        "批次ID": batch_id,
        "多版本规划状态": "已拆分",
        "错误信息": "",
    })

    log("INFO", "variant_plan success", record_id=record_id, batch_id=batch_id, children=len(created))


if __name__ == "__main__":
    main()