#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

from ugc_config import UGC_BASE_TOKEN, load_ugc_table_ids
from ugc_utils import extract_linked_record_ids, extract_text


PROMPT_DIR = Path(__file__).resolve().parents[1] / "docs" / "archive" / "ugc-content-chain-2026-05" / "prompts"
SCRIPT_PROMPT_PATH = PROMPT_DIR / "ugc-script-generation-system-prompt-v1.md"
NON_UGC_SCRIPT_PROMPT_PATH = PROMPT_DIR / "non-ugc-animation-script-generation-system-prompt-v3-content.md"
UGC_SCRIPT_STAGE_NAME = "UGC-脚本生成"
NON_UGC_SCRIPT_STAGE_NAME = "非UGC-脚本生成"

RecordGetter = Callable[[str, str, str], Dict[str, Any]]
RecordUpdater = Callable[[str, str, str, Dict[str, Any]], Any]
ModelCaller = Callable[[Dict[str, str], str], str]


def get_feishu_token() -> str:
    from common import get_feishu_token as _get_feishu_token

    return _get_feishu_token()


def get_ugc_record(token: str, table_id: str, record_id: str) -> Dict[str, Any]:
    from common import feishu_headers, safe_request

    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{UGC_BASE_TOKEN}/tables/{table_id}/records/{record_id}"
    data = safe_request("get", url, headers=feishu_headers(token), timeout=20, max_attempts=3)
    return data["data"]["record"]["fields"]


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


def normalize_video_type(fields: Dict[str, Any]) -> str:
    raw = extract_text(fields.get("视频类型")).strip().lower()
    if raw in {"非ugc", "non-ugc", "non_ugc", "nonugc", "非 ugc"}:
        return "非UGC"
    return "UGC"


def script_stage_for_fields(fields: Dict[str, Any]) -> str:
    return NON_UGC_SCRIPT_STAGE_NAME if normalize_video_type(fields) == "非UGC" else UGC_SCRIPT_STAGE_NAME


def script_prompt_path_for_stage(stage_name: str) -> Path:
    return NON_UGC_SCRIPT_PROMPT_PATH if stage_name == NON_UGC_SCRIPT_STAGE_NAME else SCRIPT_PROMPT_PATH


def load_system_prompt(path: Path = SCRIPT_PROMPT_PATH) -> str:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"UGC 脚本生成系统提示词为空: {path}")
    return text


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def list_to_text(value: Any) -> str:
    if isinstance(value, list):
        return "\n".join(str(v) for v in value if v not in (None, ""))
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return json_dumps(value)


def parse_json_text(raw: str, label: str) -> Dict[str, Any]:
    if not raw.strip():
        raise ValueError(f"缺少 {label}")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError(f"{label} 不是 JSON 对象")
    return data


def get_handoff_from_analysis(ugc01_fields: Dict[str, Any], ugc02_fields: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    # Prefer UGC-01 JSON source of truth. UGC-02 handoff is inherited display/cache only.
    analysis_json = parse_json_text(extract_text(ugc01_fields.get("分析结果JSON")), "UGC-01.分析结果JSON")
    handoff = analysis_json.get("script_generation_handoff")
    if not isinstance(handoff, dict) or not handoff:
        raise ValueError("UGC-01.分析结果JSON 缺少 script_generation_handoff")
    return handoff


def extract_single_link(value: Any) -> str:
    ids = extract_linked_record_ids(value)
    return ids[0] if ids else ""


def build_product_info(product_fields: Dict[str, Any]) -> Dict[str, Any]:
    keys = [
        "产品名称-zh",
        "产品",
        "产品名称-th",
        "产品规格",
        "核心卖点",
        "使用场景",
        "目标用户",
        "产品价格",
        "产品图片",
    ]
    info: Dict[str, Any] = {}
    for key in keys:
        value = product_fields.get(key)
        if key == "产品图片":
            info[key] = value or []
        else:
            info[key] = extract_text(value).strip()
    return info


def find_config_record_id(token: str, stage_name: str) -> str:
    from common import TABLE_CONFIG, feishu_headers, safe_request

    all_items: List[Dict[str, Any]] = []
    page_token = None
    while True:
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{UGC_BASE_TOKEN}/tables/{TABLE_CONFIG}/records?page_size=100"
        if page_token:
            url += f"&page_token={page_token}"
        data = safe_request("get", url, headers=feishu_headers(token), timeout=20, max_attempts=3)
        all_items.extend(data.get("data", {}).get("items", []))
        if not data.get("data", {}).get("has_more"):
            break
        page_token = data.get("data", {}).get("page_token")
    for item in all_items:
        fields = item.get("fields", {})
        if extract_text(fields.get("环节")).strip() == stage_name:
            return item.get("record_id", "")
    return ""


def get_script_model_config(token: str, stage_name: str = UGC_SCRIPT_STAGE_NAME) -> Dict[str, str]:
    env_key = "NON_UGC_SCRIPT_CONFIG_RECORD_ID" if stage_name == NON_UGC_SCRIPT_STAGE_NAME else "UGC_SCRIPT_CONFIG_RECORD_ID"
    rid = os.environ.get(env_key) or find_config_record_id(token, stage_name)
    if not rid:
        raise ValueError(f"未找到模型配置记录: {stage_name}")
    fields = get_ugc_record(token, __import__("common").TABLE_CONFIG, rid)
    return {
        "record_id": rid,
        "stage": extract_text(fields.get("环节")).strip(),
        "model": extract_text(fields.get("模型名称")).strip(),
        "api_key": extract_text(fields.get("API Key")).strip(),
        "api_base": extract_text(fields.get("API 代理地址")).strip().rstrip("/"),
        "prompt": extract_text(fields.get("提示词")).strip() or load_system_prompt(script_prompt_path_for_stage(stage_name)),
        "method": extract_text(fields.get("调用方式")).strip(),
    }


def build_generation_context(
    ugc03_record_id: str,
    ugc03_fields: Dict[str, Any],
    ugc02_fields: Dict[str, Any],
    ugc01_fields: Dict[str, Any],
    product_record_id: str,
    product_fields: Dict[str, Any],
) -> Dict[str, Any]:
    handoff = get_handoff_from_analysis(ugc01_fields, ugc02_fields)
    target_market = (
        extract_text(ugc03_fields.get("目标市场")).strip()
        or extract_text(ugc02_fields.get("目标市场")).strip()
        or extract_text(ugc01_fields.get("目标市场")).strip()
    )
    if not target_market:
        raise ValueError("缺少目标市场")
    if not product_record_id:
        raise ValueError("缺少关联产品")

    product_info = build_product_info(product_fields)
    product_name = (
        extract_text(ugc03_fields.get("用户新产品")).strip()
        or extract_text(ugc02_fields.get("用户新产品")).strip()
        or extract_text(ugc01_fields.get("用户新产品")).strip()
        or product_info.get("产品名称-zh")
        or product_info.get("产品")
    )

    version_task = {
        "ugc03_record_id": ugc03_record_id,
        "version_id": extract_text(ugc03_fields.get("版本ID")).strip(),
        "version_name": extract_text(ugc03_fields.get("版本名称")).strip(),
        "primary_test": extract_text(ugc03_fields.get("主测试点")).strip(),
        "variant_difference": extract_text(ugc03_fields.get("版本差异说明")).strip(),
        "locked_items": extract_text(ugc03_fields.get("锁定项说明")).strip(),
        "variable_items": extract_text(ugc03_fields.get("变量位说明")).strip(),
        "target_market": target_market,
        "target_language": "按目标市场自动本土化；若目标市场为泰国，则使用自然泰语口播",
        "linked_product_record_id": product_record_id,
        "new_product": product_name,
        "duration_target": "约40-48秒；单个分镜视频默认约8秒",
        "shot_count_policy": "动态选择 1-9 个有效镜头；默认优先 5-6 个，除非爆款结构强依赖更多阶段，否则不要超过 6 个",
        "preferred_shot_count_range": "5-6",
        "min_shot_count": 1,
        "max_shot_count": 9,
        "ugc_style": True,
    }

    return {
        "version_task": version_task,
        "product_source_of_truth": {
            "table": "初始化-产品信息",
            "record_id": product_record_id,
            "product_info": product_info,
        },
        "source_records": {
            "ugc01_record_id": extract_single_link(ugc03_fields.get("来源分析记录")),
            "ugc02_record_id": extract_single_link(ugc03_fields.get("所属批次")),
            "ugc03_record_id": ugc03_record_id,
        },
        "script_generation_handoff": handoff,
        "replicable_factors": parse_json_text(extract_text(ugc01_fields.get("分析结果JSON")), "UGC-01.分析结果JSON").get("replicable_factors", {}),
        "ugc_authenticity": parse_json_text(extract_text(ugc01_fields.get("分析结果JSON")), "UGC-01.分析结果JSON").get("ugc_authenticity", {}),
        "risk_and_optimization": parse_json_text(extract_text(ugc01_fields.get("分析结果JSON")), "UGC-01.分析结果JSON").get("risk_and_optimization", {}),
        "hard_requirements": [
            "每次只生成当前 UGC-03 版本的一条脚本，不要批量输出多个版本。",
            "必须优先消费 script_generation_handoff，不要从 Markdown 反推字段。",
            "新脚本只销售 UGC-01.关联产品 指向的产品，不要销售原爆款视频产品。",
            "shots 必须为 1-9 个，并给出 optimal_shot_count/effective_shot_count；默认优先 5-6 个，除非爆款结构强依赖更多阶段，否则不要超过 6 个。",
            "storyboard_grid_summary 或 six_grid_summary 至少覆盖所有有效 shots；后续 UGC-04 会固定使用 9宫格容器，超出有效镜头数的格子为空白占位。",
            "每个 shot 必须包含 content_type、speaker、speaker_visible；dialogue 时 speaker_visible=true。",
            "避免医疗化、绝对化、夸大功效表达；产品信息不足时保守表达并写入 risk_notes。",
        ],
    }


def build_prompt(system_prompt: str, context: Dict[str, Any]) -> str:
    return (
        system_prompt
        + "\n\n---\n\n"
        + "# 当前脚本生成任务上下文\n\n"
        + "请严格基于以下 JSON 上下文生成 1 条 UGC 脚本。最终输出只能包含 JSON_OUTPUT 和 MARKDOWN_OUTPUT。\n\n"
        + "```json\n"
        + json_dumps(context)
        + "\n```\n"
    )


def call_openai_compatible_chat(config: Dict[str, str], prompt: str) -> str:
    api_key = config.get("api_key", "").strip()
    api_base = config.get("api_base", "").strip().rstrip("/")
    model = config.get("model", "").strip()
    if not api_key or not api_base or not model:
        raise ValueError("UGC 脚本生成模型配置缺少 model/api_base/api_key")
    payload = {
        "model": model,
        "messages": [
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.7,
    }
    url = api_base + "/v1/chat/completions"
    r = requests.post(
        url,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=240,
    )
    if r.status_code != 200:
        raise RuntimeError(f"模型调用失败 HTTP {r.status_code}: {r.text[:1000]}")
    data = r.json()
    try:
        text = data["choices"][0]["message"]["content"]
    except Exception as exc:
        raise RuntimeError(f"模型返回结构异常: {str(data)[:1000]}") from exc
    if not str(text).strip():
        raise RuntimeError("模型返回空文本")
    return str(text)


def strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    return stripped.strip()


def parse_model_output(text: str) -> Dict[str, Any]:
    raw = text.strip()
    if "JSON_OUTPUT" not in raw or "MARKDOWN_OUTPUT" not in raw:
        raise ValueError("模型输出缺少 JSON_OUTPUT 或 MARKDOWN_OUTPUT 标记")
    json_part = raw.split("JSON_OUTPUT", 1)[1].split("MARKDOWN_OUTPUT", 1)[0].strip()
    markdown_part = raw.split("MARKDOWN_OUTPUT", 1)[1].strip()
    json_part = strip_code_fence(json_part)
    try:
        script_json = json.loads(json_part)
    except Exception as exc:
        raise ValueError(f"JSON_OUTPUT 不是合法 JSON: {exc}") from exc
    if not isinstance(script_json, dict):
        raise ValueError("JSON_OUTPUT 不是对象")
    validate_script_json(script_json)
    if not markdown_part:
        raise ValueError("MARKDOWN_OUTPUT 为空")
    return {"script_json": script_json, "markdown": markdown_part, "raw": raw}



def validate_script_json(script_json: Dict[str, Any]) -> None:
    shots = script_json.get("shots")
    if not isinstance(shots, list):
        raise ValueError("结构化脚本JSON.shots 必须是数组")
    raw_count = script_json.get("effective_shot_count") or script_json.get("optimal_shot_count") or script_json.get("shot_count") or len(shots)
    try:
        count = int(raw_count)
    except Exception as exc:
        raise ValueError("结构化脚本JSON.effective_shot_count/optimal_shot_count 必须是数字") from exc
    if count < 1 or count > 9:
        raise ValueError("结构化脚本JSON 有效镜头数必须在 1-9 之间")
    if len(shots) != count:
        raise ValueError(f"结构化脚本JSON.shots 数量必须等于有效镜头数 {count}")
    grid = script_json.get("storyboard_grid_summary") or script_json.get("nine_grid_summary") or script_json.get("six_grid_summary")
    if not isinstance(grid, list) or len(grid) < count:
        raise ValueError("结构化脚本JSON.storyboard_grid_summary/six_grid_summary 至少需要覆盖所有有效 shots")
    script_json["effective_shot_count"] = count
    script_json["storyboard_grid_summary"] = grid[:count]
    for idx, shot in enumerate(shots, 1):
        if not isinstance(shot, dict):
            raise ValueError(f"shot {idx} 不是对象")
        for key in ["content_type", "speaker", "speaker_visible"]:
            if key not in shot:
                raise ValueError(f"shot {idx} 缺少 {key}")
        if shot.get("content_type") == "dialogue" and shot.get("speaker_visible") is not True:
            raise ValueError(f"shot {idx} dialogue 必须 speaker_visible=true")

def summarize_script(script_json: Dict[str, Any]) -> str:
    vt = script_json.get("version_task") or {}
    setup = script_json.get("video_setup") or {}
    cta = script_json.get("final_cta") or {}
    return "｜".join(
        str(x)
        for x in [
            vt.get("version_name") or vt.get("version_id") or "UGC脚本",
            vt.get("primary_test") or "",
            setup.get("video_style") or "",
            cta.get("cta_type") or "",
        ]
        if x
    )[:500]


def build_write_fields(parsed: Dict[str, Any]) -> Dict[str, Any]:
    script_json = parsed["script_json"]
    return {
        "脚本生成状态": "生成成功",
        "生成的脚本": parsed["markdown"],
        "结构化脚本JSON": json_dumps(script_json),
        "下游推进状态": "待6宫格分镜",
        "错误信息": "",
    }


def build_error_fields(error: Exception) -> Dict[str, Any]:
    return {
        "脚本生成状态": "生成失败",
        "错误信息": str(error)[:1000],
    }


def run_generate(
    ugc03_record_id: str,
    *,
    call_model: bool = False,
    write: bool = False,
    token: Optional[str] = None,
    raw_model_output: Optional[str] = None,
    raw_output_save: Optional[str] = None,
    get_record_fn: RecordGetter = get_ugc_record,
    update_record_fn: RecordUpdater = update_ugc_record,
    model_caller: ModelCaller = call_openai_compatible_chat,
) -> Dict[str, Any]:
    if write and not (call_model or raw_model_output):
        raise ValueError("--write 必须配合 --call-model 或 --raw-output-file，避免写入空结果")

    token = token or get_feishu_token()
    table_ids = load_ugc_table_ids()
    ugc01_table = table_ids["ugc_01_analysis"]
    ugc02_table = table_ids["ugc_02_script_batch"]
    ugc03_table = table_ids["ugc_03_script_version"]
    product_table = __import__("common").TABLE_PRODUCT

    ugc03 = get_record_fn(token, ugc03_table, ugc03_record_id)
    ugc02_id = extract_single_link(ugc03.get("所属批次"))
    ugc01_id = extract_single_link(ugc03.get("来源分析记录"))
    product_id = extract_single_link(ugc03.get("关联产品"))
    if not ugc02_id:
        raise ValueError("UGC-03 缺少 所属批次")
    if not ugc01_id:
        raise ValueError("UGC-03 缺少 来源分析记录")
    if not product_id:
        raise ValueError("UGC-03 缺少 关联产品")

    ugc02 = get_record_fn(token, ugc02_table, ugc02_id)
    ugc01 = get_record_fn(token, ugc01_table, ugc01_id)
    product = get_record_fn(token, product_table, product_id)
    context = build_generation_context(ugc03_record_id, ugc03, ugc02, ugc01, product_id, product)
    stage_name = script_stage_for_fields(ugc01)
    model_config = get_script_model_config(token, stage_name)
    system_prompt = model_config.get("prompt") or load_system_prompt()
    prompt = build_prompt(system_prompt, context)

    result: Dict[str, Any] = {
        "ugc03_record_id": ugc03_record_id,
        "dry_run": not write,
        "call_model": call_model,
        "tables": {"ugc01": ugc01_table, "ugc02": ugc02_table, "ugc03": ugc03_table, "product": product_table},
        "source_records": {"ugc01": ugc01_id, "ugc02": ugc02_id, "product": product_id},
        "model_config": {k: ("***" if k == "api_key" and v else v) for k, v in model_config.items()},
        "context": context,
        "prompt_preview": prompt[:3000],
        "prompt_chars": len(prompt),
    }

    if not call_model and not raw_model_output:
        return result

    try:
        output = raw_model_output if raw_model_output is not None else model_caller(model_config, prompt)
        if raw_output_save:
            Path(raw_output_save).write_text(output, encoding="utf-8")
            result["raw_output_saved_to"] = raw_output_save
        parsed = parse_model_output(output)
        write_fields = build_write_fields(parsed)
        result.update({
            "model_output_chars": len(output),
            "script_summary": summarize_script(parsed["script_json"]),
            "parsed": {"script_json": parsed["script_json"], "markdown_chars": len(parsed["markdown"])},
            "write_fields": write_fields,
        })
        if write:
            update_record_fn(token, ugc03_table, ugc03_record_id, write_fields)
            result["written"] = True
        else:
            result["written"] = False
    except Exception as exc:
        result["error"] = str(exc)
        if write:
            update_record_fn(token, ugc03_table, ugc03_record_id, build_error_fields(exc))
            result["written_error"] = True
        raise
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="UGC-03 单条脚本生成。默认只 dry-run 构建上下文，不调用模型、不写表。")
    parser.add_argument("record_id", help="UGC-03 record_id")
    parser.add_argument("--call-model", action="store_true", help="真实调用模型生成脚本")
    parser.add_argument("--write", action="store_true", help="将模型结果写回 UGC-03；必须配合 --call-model 或 --raw-output-file")
    parser.add_argument("--raw-output-file", help="使用已有模型输出文件解析/写回，避免重复调用模型")
    parser.add_argument("--raw-output-save", help="调用模型后将原始输出保存到该文件，便于后续无重复调用写回")
    parser.add_argument("--output-file", help="保存完整运行结果 JSON 到本地文件")
    args = parser.parse_args()

    raw_output = None
    if args.raw_output_file:
        raw_output = Path(args.raw_output_file).read_text(encoding="utf-8")
    result = run_generate(
        args.record_id,
        call_model=args.call_model,
        write=args.write,
        raw_model_output=raw_output,
        raw_output_save=args.raw_output_save,
    )
    text = json_dumps(result)
    print(text)
    if args.output_file:
        Path(args.output_file).write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
