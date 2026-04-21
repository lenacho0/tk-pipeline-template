#!/usr/bin/env python3
import json
import sys
from typing import Any, Dict

from common import CFG, TABLES, extract_text, get_feishu_token, get_record, log, update_record

SCRIPT_TASKS_TABLE = TABLES["script_tasks"]


def build_protocol_payload(fields: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "protocol_version": "table6_script_multivariant_v1",
        "generation_mode": "single_standard" if extract_text(fields.get("主测试点")) == "standard" else "multi_variant_controlled",
        "batch_context": {
            "batch_id": extract_text(fields.get("批次ID")),
            "project_id": extract_text(fields.get("项目ID")),
            "project_name": extract_text(fields.get("项目名称")),
            "common_analysis_record_id": extract_text(fields.get("共性分析记录ID")),
            "product_id": extract_text(fields.get("产品ID")),
            "product_name": extract_text(fields.get("产品名称")),
            "model_id": extract_text(fields.get("模特ID")),
            "model_name": extract_text(fields.get("模特名称")),
            "target_market": extract_text(fields.get("目标市场")),
            "script_generation_mode": extract_text(fields.get("脚本生成模式")),
            "target_variant_count": fields.get("目标版本数") or 1,
            "derivation_strategy": extract_text(fields.get("派生策略")),
            "testing_dimensions": fields.get("测试维度") or [],
            "difference_level": extract_text(fields.get("版本差异强度")),
            "target_duration": extract_text(fields.get("脚本总时长目标")),
        },
        "locked_elements": {
            "notes": [extract_text(fields.get("锁定项说明"))],
        },
        "variable_slots": {
            "notes": [extract_text(fields.get("变量位说明"))],
        },
        "variant_assignment": {
            "variant_id": extract_text(fields.get("版本编号")),
            "variant_name": extract_text(fields.get("版本名称")),
            "primary_test": extract_text(fields.get("主测试点")),
            "secondary_test": extract_text(fields.get("次测试点")),
            "difference_goal": extract_text(fields.get("版本差异说明")),
        },
        "output_contract": {
            "json_top_level_fields": ["script_meta", "static_cards", "structure_summary", "shots", "final_cta", "notes"]
        }
    }


def render_prompt(payload: Dict[str, Any]) -> str:
    return (
        "## 多版本派生控制协议\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
        + "\n\n## 正式脚本生成要求\n"
        + "请基于以上协议生成单个版本的 TikTok 带货脚本。当前脚本生成器骨架已建立，后续将接入正式 prompt 模板与 LLM 调用。"
    )


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python3 stages/script_generate.py <record_id>")
        sys.exit(1)

    record_id = sys.argv[1]
    token = get_feishu_token()
    fields = get_record(token, SCRIPT_TASKS_TABLE, record_id)
    role = extract_text(fields.get("记录角色"))
    if role and role != "版本任务":
        log("script generate skipped", record_id=record_id, role=role)
        return

    payload = build_protocol_payload(fields)
    prompt_preview = render_prompt(payload)
    update_record(token, SCRIPT_TASKS_TABLE, record_id, {
        "脚本生成状态": "生成中",
        "错误信息": "",
        "生成的脚本": "[占位] 独立新项目 script_generate 骨架已建立，尚未接入正式 LLM 生成。",
        "结构化脚本JSON": json.dumps({
            "script_meta": {
                "batch_id": extract_text(fields.get("批次ID")),
                "variant_id": extract_text(fields.get("版本编号")),
                "variant_name": extract_text(fields.get("版本名称")),
                "primary_test": extract_text(fields.get("主测试点")),
                "secondary_test": extract_text(fields.get("次测试点")),
            },
            "notes": ["skeleton only", prompt_preview[:1200]]
        }, ensure_ascii=False, indent=2),
        "版本差异自检结果": json.dumps({
            "same_backbone_confirmed": True,
            "structural_difference_confirmed": bool(extract_text(fields.get("主测试点"))),
            "difference_strength": "pending_real_llm",
            "notes": "当前为独立项目骨架占位输出，待接入正式模型调用。"
        }, ensure_ascii=False, indent=2),
        "脚本生成状态": "生成成功",
    })
    log("script generate skeleton success", record_id=record_id, variant=extract_text(fields.get("版本编号")))


if __name__ == "__main__":
    main()
