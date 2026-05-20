#!/usr/bin/env python3
"""
从 003 产品脚本分镜图生成表创建 003-2 逐镜头母任务。

用法: python3 tk_create_shot_parent_from_003.py <003_record_id>
触发字段: 003.逐镜头流程状态 = 待创建
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *
from tk_shot_storyboard import filter_existing_fields


def create_record(token, table_id, fields):
    data = safe_request(
        "post",
        f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/records",
        headers=feishu_headers(token),
        json={"fields": fields},
        timeout=30,
        max_attempts=3,
        acceptable_codes=(0,),
    )
    return data["data"]["record"]["record_id"]


def find_existing_parent(token, source_003_record_id):
    for rec in safe_list_records(token, TABLE_SHOT_SCRIPT_GEN):
        fields = rec.get("fields", {})
        if extract_text(fields.get("源003记录ID", "")).strip() == source_003_record_id:
            return rec.get("record_id", "")
    return ""


def resolve_voice_id(token, source_fields):
    direct = extract_text(source_fields.get("口播音色ID", "")).strip()
    if direct:
        return direct
    linked_ids = extract_linked_record_ids(source_fields.get("选择音色"))
    if not linked_ids or not TABLE_VOICE_LIBRARY:
        return ""
    voice_fields = safe_get_record(token, TABLE_VOICE_LIBRARY, linked_ids[0])
    voice_id = extract_text(voice_fields.get("Voice ID", "")).strip()
    status = extract_text(voice_fields.get("生成状态", "")).strip()
    if not voice_id:
        raise Exception("已选择音色，但音色库 Voice ID 为空，请先生成音色")
    if status and status != "成功":
        raise Exception(f"已选择音色，但音色生成状态不是成功: {status}")
    return voice_id


def linked_record_ids_or_empty(value):
    return extract_linked_record_ids(value)


def build_parent_fields(token, source_record_id, source_fields):
    raw_script = extract_text(source_fields.get("手写脚本内容", "")).strip()
    if not raw_script:
        raise Exception("003 手写脚本内容为空，无法创建逐镜头母任务")

    product_value = get_task_product_value(source_fields)
    if not extract_text(product_value).strip() and not extract_linked_record_ids(product_value):
        raise Exception("003 未选择产品或关联产品")

    task_name = f"手写逐镜头-{source_record_id[-6:]}-{time.strftime('%Y%m%d%H%M%S')}"
    product_link_ids = linked_record_ids_or_empty(source_fields.get("关联产品"))
    model_link_ids = linked_record_ids_or_empty(source_fields.get("选择模特"))
    voice_link_ids = linked_record_ids_or_empty(source_fields.get("选择音色"))
    fields = {
        "源003记录ID": source_record_id,
        "任务名称": task_name,
        "手写脚本内容": raw_script,
        "文本": raw_script,
        "脚本来源": "手写脚本",
        "视频时长": source_fields.get("视频时长", ""),
        "分镜风格": source_fields.get("分镜风格", ""),
        "口播音色ID": resolve_voice_id(token, source_fields),
        "脚本风格": "手写脚本忠实拆解",
        "参考来源": "手写脚本，无爆款参考",
        "参考样本数": 0,
        "生成状态": "待生成",
        "错误信息": "",
    }
    if product_link_ids:
        fields["关联产品"] = product_link_ids
    else:
        fields["选择产品"] = source_fields.get("选择产品", "")
    if model_link_ids:
        fields["选择模特"] = model_link_ids
    if voice_link_ids:
        fields["选择音色"] = voice_link_ids
    return fields


def main():
    if len(sys.argv) < 2:
        print("用法: python3 tk_create_shot_parent_from_003.py <003_record_id>")
        sys.exit(1)

    record_id = sys.argv[1]
    token = get_feishu_token()

    try:
        if not TABLE_SHOT_SCRIPT_GEN:
            raise Exception("config.json 尚未配置 shot_script_gen 表 ID")

        log_event("INFO", "create shot parent start", source_record_id=record_id)
        source_fields = safe_get_record(token, TABLE_SCRIPT_GEN, record_id)
        safe_update_record(token, TABLE_SCRIPT_GEN, record_id, filter_existing_fields(token, TABLE_SCRIPT_GEN, {
            "逐镜头流程状态": "创建中",
            "逐镜头流程错误信息": "",
        }))

        existing = extract_text(source_fields.get("逐镜头母任务ID", "")).strip() or find_existing_parent(token, record_id)
        if existing:
            raise Exception(f"已存在逐镜头母任务: {existing}；如需重建请先人工处理旧任务")

        parent_fields = filter_existing_fields(token, TABLE_SHOT_SCRIPT_GEN, build_parent_fields(token, record_id, source_fields))
        parent_record_id = create_record(token, TABLE_SHOT_SCRIPT_GEN, parent_fields)

        safe_update_record(token, TABLE_SCRIPT_GEN, record_id, filter_existing_fields(token, TABLE_SCRIPT_GEN, {
            "逐镜头母任务ID": parent_record_id,
            "逐镜头流程状态": "已创建",
            "逐镜头流程错误信息": "",
        }))
        log_event("INFO", "create shot parent success", source_record_id=record_id, parent_record_id=parent_record_id)
        print(f"✅ 已创建逐镜头母任务: {parent_record_id}")

    except Exception as e:
        payload = build_error_payload(e, stage="create_shot_parent")
        err = payload["message"]
        log_event("ERROR", "create shot parent failed", source_record_id=record_id, error=err, error_code=payload["error_code"])
        try:
            safe_update_record(token, TABLE_SCRIPT_GEN, record_id, filter_existing_fields(token, TABLE_SCRIPT_GEN, {
                "逐镜头流程状态": "失败",
                "逐镜头流程错误信息": err,
            }))
        except Exception:
            pass
        print(f"ERROR_CODE={payload['error_code']} RETRYABLE={str(payload['retryable']).lower()} MESSAGE={err}")
        sys.exit(1)


if __name__ == "__main__":
    main()
