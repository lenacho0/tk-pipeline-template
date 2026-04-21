#!/usr/bin/env python3
import sys
import time
from typing import Any, Dict, List

from common import CFG, TABLES, create_records, extract_text, get_feishu_token, get_record, log, update_record

SCRIPT_TASKS_TABLE = TABLES["script_tasks"]


DEFAULT_TEST_DIRECTIONS = {
    "hook_angle": ["痛点直击", "结果前置", "认知冲突"],
    "scene_entry": ["家庭日常切入", "出门前切入", "任务处理中切入"],
    "trust_builder": ["个人体验", "可见细节证据", "前后对比"],
}


def _now_suffix() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def fill_defaults(fields: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "脚本生成模式": extract_text(fields.get("脚本生成模式")) or "多版本受控派生",
        "目标版本数": int(fields.get("目标版本数") or 3),
        "测试维度": fields.get("测试维度") or ["auto"],
        "派生策略": extract_text(fields.get("派生策略")) or "S3 系统推荐探索",
        "版本差异强度": extract_text(fields.get("版本差异强度")) or "标准",
        "脚本总时长目标": extract_text(fields.get("脚本总时长目标")) or "20-25s",
    }


def build_batch_id(fields: Dict[str, Any], parent_record_id: str) -> str:
    project_id = extract_text(fields.get("项目ID")) or "PROJECT"
    return f"TBW-SCRIPT-{project_id}-{_now_suffix()}-{parent_record_id[-4:]}"


def plan_variants(parent_fields: Dict[str, Any], defaults: Dict[str, Any]) -> List[Dict[str, str]]:
    count = max(1, min(int(defaults["目标版本数"]), 4))
    mode = defaults["脚本生成模式"]
    if mode == "单版本标准生成" or count == 1:
        return [{
            "variant_id": "V1",
            "variant_name": "V1-standard-标准生成",
            "primary_test": "standard",
            "secondary_test": "",
            "direction": "standard",
            "difference_goal": "标准单版本生成，不做多版本派生。",
        }]

    return [
        {
            "variant_id": "V1",
            "variant_name": "V1-hook_angle-痛点直击开场",
            "primary_test": "hook_angle",
            "secondary_test": "",
            "direction": "痛点直击",
            "difference_goal": "用痛点直击开场，测试是否最容易抓住注意力。",
        },
        {
            "variant_id": "V2",
            "variant_name": "V2-hook_angle-结果前置开场",
            "primary_test": "hook_angle",
            "secondary_test": "",
            "direction": "结果前置",
            "difference_goal": "用结果前置开场，测试是否更容易建立兴趣。",
        },
        {
            "variant_id": "V3",
            "variant_name": "V3-scene_entry-家庭日常切入",
            "primary_test": "scene_entry",
            "secondary_test": "",
            "direction": "家庭日常切入",
            "difference_goal": "用家庭日常切入，测试场景代入是否更自然。",
        },
    ][:count]


def build_child_record(parent_record_id: str, parent_fields: Dict[str, Any], defaults: Dict[str, Any], batch_id: str, variant: Dict[str, str]) -> Dict[str, Any]:
    passthrough_keys = [
        "项目ID", "项目名称", "共性分析记录ID", "产品ID", "产品名称",
        "模特ID", "模特名称", "目标市场", "场景参考图", "场景参考说明",
    ]
    child: Dict[str, Any] = {k: parent_fields.get(k) for k in passthrough_keys if k in parent_fields}
    child.update({
        "记录角色": "版本任务",
        "父任务ID": parent_record_id,
        "批次ID": batch_id,
        "脚本生成模式": defaults["脚本生成模式"],
        "目标版本数": defaults["目标版本数"],
        "测试维度": defaults["测试维度"],
        "派生策略": defaults["派生策略"],
        "版本差异强度": defaults["版本差异强度"],
        "脚本总时长目标": defaults["脚本总时长目标"],
        "版本编号": variant["variant_id"],
        "版本名称": variant["variant_name"],
        "主测试点": variant["primary_test"],
        "次测试点": variant["secondary_test"],
        "版本差异说明": variant["difference_goal"],
        "锁定项说明": "锁定产品真源 / 人物真源 / 共性骨架 / 目标市场 / 总时长边界",
        "变量位说明": "允许变化：hook_angle / scene_entry / trust_builder（按当前版本任务分配）",
        "共性骨架摘要": extract_text(parent_fields.get("共性骨架摘要")) or "待后续接入共性分析摘要生成",
        "脚本生成状态": "待生成",
        "下游推进状态": "未推进",
        "是否入选": "待定",
        "多版本规划状态": "已跳过",
    })
    return child


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python3 stages/variant_plan.py <record_id>")
        sys.exit(1)

    record_id = sys.argv[1]
    token = get_feishu_token()
    parent_fields = get_record(token, SCRIPT_TASKS_TABLE, record_id)
    role = extract_text(parent_fields.get("记录角色"))
    if role and role != "批次母任务":
        log("variant planner skipped", record_id=record_id, role=role)
        return

    update_record(token, SCRIPT_TASKS_TABLE, record_id, {"多版本规划状态": "规划中"})
    defaults = fill_defaults(parent_fields)
    batch_id = build_batch_id(parent_fields, record_id)
    variants = plan_variants(parent_fields, defaults)
    child_records = [build_child_record(record_id, parent_fields, defaults, batch_id, v) for v in variants]
    created = create_records(token, SCRIPT_TASKS_TABLE, child_records)
    update_record(token, SCRIPT_TASKS_TABLE, record_id, {
        "记录角色": "批次母任务",
        "批次ID": batch_id,
        "多版本规划状态": "已拆分",
        "错误信息": "",
    })
    log("variant planner success", record_id=record_id, batch_id=batch_id, created=len(created))


if __name__ == "__main__":
    main()
