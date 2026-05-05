#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from ugc_config import UGC_BASE_TOKEN, load_ugc_table_ids
from ugc_utils import extract_linked_record_ids, extract_text


RecordGetter = Callable[[str, str, str], Dict[str, Any]]
RecordCreator = Callable[[str, str, Dict[str, Any]], str]
RecordUpdater = Callable[[str, str, str, Dict[str, Any]], Any]

TEST_POINT_OPTIONS = [
    "hook_angle",
    "pain_point_moment",
    "scene_entry",
    "trust_builder",
    "cta_style",
    "standard",
]


def get_feishu_token() -> str:
    from common import get_feishu_token as _get_feishu_token

    return _get_feishu_token()


def get_ugc_record(token: str, table_id: str, record_id: str) -> Dict[str, Any]:
    from common import feishu_headers, safe_request

    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{UGC_BASE_TOKEN}/tables/{table_id}/records/{record_id}"
    data = safe_request("get", url, headers=feishu_headers(token), timeout=15, max_attempts=3)
    return data["data"]["record"]["fields"]


def create_ugc_record(token: str, table_id: str, fields: Dict[str, Any]) -> str:
    from common import feishu_headers, safe_request

    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{UGC_BASE_TOKEN}/tables/{table_id}/records"
    data = safe_request(
        "post",
        url,
        headers=feishu_headers(token),
        json={"fields": fields},
        timeout=30,
        max_attempts=3,
    )
    return data["data"]["record"]["record_id"]


def update_ugc_record(token: str, table_id: str, record_id: str, fields: Dict[str, Any]) -> Any:
    from common import feishu_headers, safe_request

    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{UGC_BASE_TOKEN}/tables/{table_id}/records/{record_id}"
    return safe_request(
        "put",
        url,
        headers=feishu_headers(token),
        json={"fields": fields},
        timeout=30,
        max_attempts=3,
    )


def link_records(record_ids: List[str]) -> List[str]:
    return [record_id for record_id in record_ids if record_id]


def parse_analysis_json(fields: Dict[str, Any]) -> Dict[str, Any]:
    raw = extract_text(fields.get("分析结果JSON")).strip()
    if not raw:
        raise ValueError("UGC-01 缺少分析结果JSON")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("UGC-01 分析结果JSON不是对象")
    return data


def get_handoff(analysis_json: Dict[str, Any]) -> Dict[str, Any]:
    handoff = analysis_json.get("script_generation_handoff")
    if not isinstance(handoff, dict) or not handoff:
        raise ValueError("UGC-01 分析结果JSON缺少 script_generation_handoff")
    return handoff


def normalize_script_count(value: Any, default: int = 3, minimum: int = 1, maximum: int = 6) -> int:
    text = extract_text(value).strip()
    try:
        count = int(float(text)) if text else default
    except Exception:
        count = default
    return max(minimum, min(maximum, count))


def product_name_from_analysis(analysis_json: Dict[str, Any], fields: Dict[str, Any]) -> str:
    input_requirements = analysis_json.get("input_requirements") or {}
    basic_info = analysis_json.get("basic_info") or {}
    return (
        extract_text(fields.get("用户新产品")).strip()
        or str(input_requirements.get("new_product") or "").strip()
        or str(basic_info.get("new_product") or "").strip()
    )


def list_to_lines(value: Any) -> str:
    if isinstance(value, list):
        return "\n".join(str(item) for item in value if item not in (None, ""))
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return json.dumps(value, ensure_ascii=False)


def choose_test_points(handoff: Dict[str, Any], count: int) -> List[Dict[str, str]]:
    directions = handoff.get("new_script_directions") or []
    hooks = handoff.get("hook_templates") or []
    candidates: List[Dict[str, str]] = []

    mapping = [
        ("pain_point_moment", "痛点场景强化", "强化痛点具象化与开头冲突"),
        ("trust_builder", "信任证明强化", "强化真实买家秀、效果证明与可信表达"),
        ("hook_angle", "Hook角度强化", "强化开头3秒吸引力与点击停留"),
        ("scene_entry", "场景切入强化", "强化生活化场景进入与代入感"),
        ("cta_style", "CTA风格强化", "强化结尾转化与行动引导"),
    ]

    for idx, direction in enumerate(directions):
        if not isinstance(direction, dict):
            continue
        option, fallback_name, fallback_desc = mapping[min(idx, len(mapping) - 1)]
        name = str(direction.get("direction_name") or fallback_name).strip()
        desc = str(direction.get("description") or direction.get("recommended_variation") or fallback_desc).strip()
        candidates.append({"test_point": option, "name": name, "description": desc})

    if hooks:
        candidates.append({
            "test_point": "hook_angle",
            "name": "Hook模板强化",
            "description": "围绕可复用Hook模板改写，优先提升前三秒停留。",
        })

    candidates.extend([
        {"test_point": "scene_entry", "name": "场景代入版", "description": "强化目标市场本土生活场景和真实UGC代入。"},
        {"test_point": "trust_builder", "name": "信任背书版", "description": "强化使用前后、证据镜头、真实口吻和信任建立。"},
        {"test_point": "cta_style", "name": "转化引导版", "description": "强化软性CTA和评论/购物车行动引导。"},
        {"test_point": "standard", "name": "标准复刻版", "description": "按handoff核心结构做均衡复刻。"},
    ])

    selected: List[Dict[str, str]] = []
    used_options = set()
    for candidate in candidates:
        option = candidate["test_point"]
        if option != "standard" and option in used_options:
            continue
        selected.append(candidate)
        used_options.add(option)
        if len(selected) >= count:
            return selected

    while len(selected) < count:
        selected.append({"test_point": "standard", "name": f"标准复刻版{len(selected)+1}", "description": "按handoff核心结构做均衡复刻。"})
    return selected


def build_batch_id(ugc01_record_id: str) -> str:
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"UGC-BATCH-{ts}-{ugc01_record_id[-6:]}"


def build_version_id(batch_id: str, index: int) -> str:
    return f"{batch_id}-V{index:02d}"


def build_derivation_payload(ugc01_record_id: str, ugc01_fields: Dict[str, Any]) -> Dict[str, Any]:
    analysis_json = parse_analysis_json(ugc01_fields)
    handoff = get_handoff(analysis_json)
    target_count = normalize_script_count(ugc01_fields.get("目标脚本数量"))
    linked_products = extract_linked_record_ids(ugc01_fields.get("关联产品"))
    if not linked_products:
        raise ValueError("UGC-01 缺少关联产品")
    target_market = extract_text(ugc01_fields.get("目标市场")).strip()
    if not target_market:
        raise ValueError("UGC-01 缺少目标市场")

    batch_id = build_batch_id(ugc01_record_id)
    product_name = product_name_from_analysis(analysis_json, ugc01_fields)
    selected_points = choose_test_points(handoff, target_count)

    batch_fields = {
        "批次ID": batch_id,
        "来源分析记录": link_records([ugc01_record_id]),
        "关联产品": link_records(linked_products[:1]),
        "用户新产品": product_name,
        "目标市场": target_market,
        "目标脚本数量": target_count,
        "分析handoff JSON": json.dumps(handoff, ensure_ascii=False, indent=2),
        "必须保留": list_to_lines(handoff.get("must_preserve")),
        "可替换项": list_to_lines(handoff.get("can_replace")),
        "UGC风格要求": list_to_lines(handoff.get("ugc_style_requirements")),
        "多版本规划状态": "已规划",
        "版本任务数量": target_count,
        "备注": f"由UGC-01 {ugc01_record_id} 自动派生；dry-run确认后写入。",
    }

    version_fields_list = []
    for idx, point in enumerate(selected_points, start=1):
        version_id = build_version_id(batch_id, idx)
        version_fields_list.append({
            "版本ID": version_id,
            "版本名称": f"{idx:02d}-{point['name']}",
            "主测试点": point["test_point"],
            "版本差异说明": point["description"],
            "锁定项说明": list_to_lines(handoff.get("must_preserve")),
            "变量位说明": list_to_lines(handoff.get("can_replace")),
            "用户新产品": product_name,
            "目标市场": target_market,
            "脚本生成状态": "待生成",
            "是否入选": "待定",
            "下游推进状态": "未推进",
            "来源分析记录": link_records([ugc01_record_id]),
            "关联产品": link_records(linked_products[:1]),
        })

    return {
        "ugc01_record_id": ugc01_record_id,
        "batch_id": batch_id,
        "target_count": target_count,
        "batch_fields": batch_fields,
        "version_fields_list": version_fields_list,
        "ugc01_update_fields": {
            "脚本派生状态": "已派生",
            "脚本批次ID": batch_id,
        },
    }


def run_derive(
    ugc01_record_id: str,
    *,
    dry_run: bool = True,
    token: Optional[str] = None,
    get_record_fn: RecordGetter = get_ugc_record,
    create_record_fn: RecordCreator = create_ugc_record,
    update_record_fn: RecordUpdater = update_ugc_record,
) -> Dict[str, Any]:
    token = token or get_feishu_token()
    table_ids = load_ugc_table_ids()
    ugc01_table = table_ids["ugc_01_analysis"]
    ugc02_table = table_ids["ugc_02_script_batch"]
    ugc03_table = table_ids["ugc_03_script_version"]

    ugc01_fields = get_record_fn(token, ugc01_table, ugc01_record_id)
    payload = build_derivation_payload(ugc01_record_id, ugc01_fields)

    if dry_run:
        return {
            "dry_run": True,
            "ugc01_record_id": ugc01_record_id,
            "tables": {"ugc01": ugc01_table, "ugc02": ugc02_table, "ugc03": ugc03_table},
            **payload,
            "created": None,
        }

    batch_record_id = create_record_fn(token, ugc02_table, payload["batch_fields"])
    created_versions: List[str] = []
    for version_fields in payload["version_fields_list"]:
        fields = dict(version_fields)
        fields["所属批次"] = link_records([batch_record_id])
        created_versions.append(create_record_fn(token, ugc03_table, fields))
    update_record_fn(token, ugc01_table, ugc01_record_id, payload["ugc01_update_fields"])

    return {
        "dry_run": False,
        "ugc01_record_id": ugc01_record_id,
        "tables": {"ugc01": ugc01_table, "ugc02": ugc02_table, "ugc03": ugc03_table},
        **payload,
        "created": {
            "ugc02_batch_record_id": batch_record_id,
            "ugc03_version_record_ids": created_versions,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="UGC-01 分析结果派生 UGC-02/UGC-03 脚本任务。默认 dry-run。")
    parser.add_argument("record_id", help="UGC-01 record_id")
    parser.add_argument("--write", action="store_true", help="真实创建 UGC-02/UGC-03 并更新 UGC-01。默认 dry-run。")
    parser.add_argument("--dry-run", action="store_true", help="显式 dry-run，不写入。")
    args = parser.parse_args()

    result = run_derive(args.record_id, dry_run=not args.write)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
