from __future__ import annotations

import argparse
import json
import mimetypes
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from ugc_config import UGC_BASE_TOKEN, load_ugc_table_ids
from ugc_utils import extract_linked_record_ids, extract_text, parse_dual_output

ROOT_DIR = Path(__file__).resolve().parents[1]
ANALYSIS_PROMPT_PATH = ROOT_DIR / "docs" / "prompts" / "ugc-single-video-analysis-system-prompt-v1.md"
LEGACY_ANALYSIS_PROMPT_PATH = ROOT_DIR / "docs" / "ugc-single-video-analysis-system-prompt-v1.md"

RecordGetter = Callable[[str, str, str], Dict[str, Any]]
RecordUpdater = Callable[[str, str, str, Dict[str, Any]], Any]
ProductTableIdGetter = Callable[[], str]
ModelConfigLoader = Callable[[str], Dict[str, str]]


@dataclass
class UGC01ValidationResult:
    ready: bool
    video_source_type: str
    linked_product_record_id: str
    target_market: str
    blocking_missing_fields: List[str]


def validate_ugc01_inputs(fields: Dict[str, Any]) -> UGC01ValidationResult:
    video_link = extract_text(fields.get("视频链接")).strip()
    has_video_file = bool(fields.get("视频文件"))
    product_ids = extract_linked_record_ids(fields.get("关联产品"))
    target_market = extract_text(fields.get("目标市场")).strip()

    blocking_missing_fields: List[str] = []
    if not video_link and not has_video_file:
        blocking_missing_fields.append("video_source")
    if not product_ids:
        blocking_missing_fields.append("linked_product")
    if not target_market:
        blocking_missing_fields.append("target_market")

    if has_video_file:
        video_source_type = "file"
    elif video_link:
        video_source_type = "link"
    else:
        video_source_type = "missing"

    return UGC01ValidationResult(
        ready=not blocking_missing_fields,
        video_source_type=video_source_type,
        linked_product_record_id=product_ids[0] if product_ids else "",
        target_market=target_market,
        blocking_missing_fields=blocking_missing_fields,
    )


def load_analysis_system_prompt(path: Path = ANALYSIS_PROMPT_PATH) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8")
    if path == ANALYSIS_PROMPT_PATH and LEGACY_ANALYSIS_PROMPT_PATH.exists():
        return LEGACY_ANALYSIS_PROMPT_PATH.read_text(encoding="utf-8")
    return path.read_text(encoding="utf-8")


def build_blocked_analysis_json(result: UGC01ValidationResult) -> Dict[str, Any]:
    return {
        "analysis_scope": "single_video",
        "video_type": "UGC",
        "input_requirements": {
            "video_source_type": result.video_source_type,
            "linked_product_record_id": result.linked_product_record_id,
            "target_market": result.target_market,
            "ready_for_formal_analysis": False,
            "blocking_missing_fields": result.blocking_missing_fields,
        },
        "confidence": {"overall": "low"},
        "error": "缺少正式分析所需输入",
    }


def build_blocked_analysis_payload(result: UGC01ValidationResult) -> Dict[str, Any]:
    json_obj = build_blocked_analysis_json(result)
    missing = "、".join(result.blocking_missing_fields) or "未知字段"
    return {
        "分析状态": "分析失败",
        "分析结果JSON": json.dumps(json_obj, ensure_ascii=False, indent=2),
        "分析摘要": f"缺少必要输入：{missing}",
    }


def build_analysis_model_prompt(system_prompt: str, prompt_payload: Dict[str, Any]) -> str:
    return "\n\n".join([
        system_prompt.strip(),
        "---",
        "以下是本次 UGC-01 单条爆款视频分析的结构化输入。",
        "请严格基于视频内容、关联产品记录和目标市场输出 JSON_OUTPUT 与 MARKDOWN_OUTPUT。",
        json.dumps(prompt_payload, ensure_ascii=False, indent=2),
    ]).strip()


def build_analysis_prompt_payload(
    fields: Dict[str, Any],
    product_fields: Optional[Dict[str, Any]] = None,
    record_id: str = "",
) -> Dict[str, Any]:
    validation = validate_ugc01_inputs(fields)
    return {
        "ugc01_record_id": record_id,
        "video_source_type": validation.video_source_type,
        "video_link": extract_text(fields.get("视频链接")).strip(),
        "has_video_file": bool(fields.get("视频文件")),
        "linked_product_record_id": validation.linked_product_record_id,
        "target_market": validation.target_market,
        "target_script_count": fields.get("目标脚本数量") or 3,
        "user_notes": extract_text(fields.get("备注")).strip(),
        "product_fields": product_fields or {},
    }


def extract_analysis_summary(json_obj: Dict[str, Any]) -> str:
    handoff = json_obj.get("script_generation_handoff")
    if isinstance(handoff, dict):
        for key in ("single_video_pattern_summary", "pattern_summary", "summary"):
            value = handoff.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    for key in ("analysis_summary", "summary"):
        value = json_obj.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "UGC 单视频分析已完成，分析结果已写入 JSON 与 Markdown。"


def build_success_analysis_payload(raw_model_output: str) -> Dict[str, Any]:
    parsed = parse_dual_output(raw_model_output)
    return {
        "分析状态": "分析成功",
        "分析结果JSON": json.dumps(parsed.json_obj, ensure_ascii=False, indent=2),
        "分析结果Markdown": parsed.markdown,
        "分析摘要": extract_analysis_summary(parsed.json_obj),
    }


def build_local_analysis_payload(
    fields: Dict[str, Any],
    raw_model_output: Optional[str] = None,
) -> Dict[str, Any]:
    validation = validate_ugc01_inputs(fields)
    if not validation.ready:
        return build_blocked_analysis_payload(validation)
    if raw_model_output is None:
        raise ValueError("UGC-01 输入已满足分析条件，但当前未提供模型输出。")
    return build_success_analysis_payload(raw_model_output)


def is_dry_run_from_env(value: Optional[str] = None) -> bool:
    raw = os.environ.get("UGC_DRY_RUN", "1") if value is None else value
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def get_ugc01_table_id() -> str:
    return load_ugc_table_ids()["ugc_01_analysis"]


def get_feishu_token() -> str:
    from common import get_feishu_token as _get_feishu_token

    return _get_feishu_token()


def get_ugc_record(token: str, table_id: str, record_id: str) -> Dict[str, Any]:
    from common import feishu_headers, safe_request

    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{UGC_BASE_TOKEN}/tables/{table_id}/records/{record_id}"
    data = safe_request("get", url, headers=feishu_headers(token), timeout=15, max_attempts=3)
    return data["data"]["record"]["fields"]


def get_product_table_id() -> str:
    from common import TABLE_PRODUCT

    return TABLE_PRODUCT


def find_ugc_analysis_config_record_id(token: str) -> str:
    from common import TABLE_CONFIG, safe_list_records

    records = safe_list_records(token, TABLE_CONFIG)
    for record in records:
        fields = record.get("fields", {})
        stage_values = fields.get("环节") or []
        if isinstance(stage_values, list) and "爆款视频分析-UGC" in stage_values:
            return record.get("record_id", "")
        if extract_text(stage_values).strip() == "爆款视频分析-UGC":
            return record.get("record_id", "")
    return ""


def get_ugc_analysis_model_config(token: str) -> Dict[str, str]:
    from common import CONFIG_RECORDS, get_model_config

    record_id = (
        os.environ.get("UGC_ANALYSIS_CONFIG_RECORD_ID")
        or CONFIG_RECORDS.get("ugc_single_video_analysis")
        or find_ugc_analysis_config_record_id(token)
        or CONFIG_RECORDS.get("analysis")
    )
    if not record_id:
        raise ValueError("缺少 UGC 分析模型配置 record_id；请配置爆款视频分析-UGC配置记录或 UGC_ANALYSIS_CONFIG_RECORD_ID。")
    config = get_model_config(token, record_id)
    return {
        "model": (config.get("model") or "gemini-2.5-flash").strip(),
        "api_key": (config.get("api_key") or "").strip(),
        "api_base": (config.get("api_base") or "https://aihubmix.com/gemini").strip(),
        "prompt": (config.get("prompt") or "").strip(),
    }


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


def extract_first_file_token(value: Any) -> str:
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict) and item.get("file_token"):
                return str(item.get("file_token") or "")
    return ""


def prepare_ugc_video_file(token: str, fields: Dict[str, Any], record_id: str) -> Tuple[str, str]:
    from common import WORKSPACE, with_retry
    from tk_analyze import download_feishu_media, download_from_video_link

    local_video_path = extract_text(fields.get("本地视频路径")).strip()
    if local_video_path:
        path = Path(local_video_path).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"本地视频路径不存在: {path}")
        return str(path), "local"

    video_dir = Path(WORKSPACE) / "ugc_videos"
    video_dir.mkdir(parents=True, exist_ok=True)
    video_path = video_dir / f"{record_id}.mp4"

    file_token = extract_first_file_token(fields.get("视频文件"))
    if file_token:
        path = with_retry(
            lambda: download_feishu_media(token, file_token, str(video_path)),
            max_attempts=3,
            label="download UGC video from feishu attachment",
        )
        return path, "file"

    video_link = extract_text(fields.get("视频链接")).strip()
    if video_link:
        path = with_retry(
            lambda: download_from_video_link(video_link, str(video_path)),
            max_attempts=2,
            label="download UGC video from link",
        )
        return path, "link"

    raise ValueError("缺少可下载的视频来源")


def should_use_inline_video_input(model_config: Dict[str, str]) -> bool:
    """Whether to pass video as inline bytes instead of Gemini Files upload.

    Aitgenne currently supports Gemini generateContent but its files.upload path
    does not return the upload URL expected by google-genai, so UGC uses inline
    video input for that proxy. The mode can be forced with UGC_VIDEO_INPUT_MODE:
    inline/base64 or file/files/upload.
    """
    mode = (os.environ.get("UGC_VIDEO_INPUT_MODE") or model_config.get("video_input_mode") or "").strip().lower()
    if mode in {"inline", "base64", "inline_data"}:
        return True
    if mode in {"file", "files", "upload", "file_upload"}:
        return False
    api_base = (model_config.get("api_base") or "").lower()
    return "aitgenne.com" in api_base


def build_inline_video_part(video_path: str) -> Any:
    from google.genai import types

    path = Path(video_path)
    mime_type = mimetypes.guess_type(path.name)[0] or "video/mp4"
    return types.Part.from_bytes(data=path.read_bytes(), mime_type=mime_type)


def call_ugc_analysis_model(
    token: str,
    fields: Dict[str, Any],
    record_id: str,
    prompt_payload: Dict[str, Any],
    model_config: Dict[str, str],
) -> str:
    from common import get_gemini_client, with_retry

    api_key = (model_config.get("api_key") or "").strip()
    if not api_key:
        raise ValueError("UGC 分析模型配置缺少 API Key")

    model_name = (model_config.get("model") or "gemini-2.5-flash").strip()
    api_base = (model_config.get("api_base") or "https://aihubmix.com/gemini").strip()
    system_prompt = (model_config.get("prompt") or "").strip() or load_analysis_system_prompt()
    prompt_text = build_analysis_model_prompt(system_prompt, prompt_payload)

    video_path, _source = prepare_ugc_video_file(token, fields, record_id)
    client = get_gemini_client(api_key, api_base)

    if should_use_inline_video_input(model_config):
        video_part = build_inline_video_part(video_path)
        response = with_retry(
            lambda: client.models.generate_content(model=model_name, contents=[video_part, prompt_text]),
            max_attempts=3,
            label="gemini UGC single video analyze generate_content inline video",
        )
        result = getattr(response, "text", "") or ""
        if not result.strip():
            raise ValueError("UGC 分析模型返回空结果")
        return result

    from tk_analyze import upload_and_wait_active

    uploaded = upload_and_wait_active(client, video_path, max_wait=180)
    try:
        response = with_retry(
            lambda: client.models.generate_content(model=model_name, contents=[uploaded, prompt_text]),
            max_attempts=3,
            label="gemini UGC single video analyze generate_content uploaded file",
        )
        result = getattr(response, "text", "") or ""
        if not result.strip():
            raise ValueError("UGC 分析模型返回空结果")
        return result
    finally:
        try:
            with_retry(lambda: client.files.delete(name=uploaded.name), max_attempts=2, label="gemini UGC uploaded video cleanup")
        except Exception:
            pass


def run_ugc01_analysis(
    record_id: str,
    *,
    dry_run: bool = True,
    raw_model_output: Optional[str] = None,
    token: Optional[str] = None,
    get_record_fn: RecordGetter = get_ugc_record,
    update_record_fn: RecordUpdater = update_ugc_record,
    product_table_id_getter: ProductTableIdGetter = get_product_table_id,
    call_model: bool = False,
    model_config_loader: ModelConfigLoader = get_ugc_analysis_model_config,
) -> Dict[str, Any]:
    if not record_id:
        raise ValueError("record_id is required")

    token = token or get_feishu_token()
    table_id = get_ugc01_table_id()
    fields = get_record_fn(token, table_id, record_id)
    validation = validate_ugc01_inputs(fields)

    product_fields: Dict[str, Any] = {}
    prompt_payload: Optional[Dict[str, Any]] = None
    if validation.ready:
        product_table_id = product_table_id_getter()
        product_fields = get_record_fn(token, product_table_id, validation.linked_product_record_id)
        prompt_payload = build_analysis_prompt_payload(
            fields,
            product_fields=product_fields,
            record_id=record_id,
        )
        if raw_model_output is None and call_model:
            raw_model_output = call_ugc_analysis_model(
                token=token,
                fields=fields,
                record_id=record_id,
                prompt_payload=prompt_payload,
                model_config=model_config_loader(token),
            )

        if raw_model_output is None:
            if not dry_run:
                raise ValueError("UGC-01 输入已满足分析条件，但当前未提供模型输出，拒绝真实写入。")
            return {
                "dry_run": dry_run,
                "record_id": record_id,
                "table_id": table_id,
                "validation": {
                    "ready": validation.ready,
                    "video_source_type": validation.video_source_type,
                    "linked_product_record_id": validation.linked_product_record_id,
                    "target_market": validation.target_market,
                    "blocking_missing_fields": validation.blocking_missing_fields,
                },
                "prompt_payload": prompt_payload,
                "model_required": True,
                "call_model_enabled": call_model,
                "would_set_in_progress": {"分析状态": "分析中"},
                "write_payload": None,
            }

    status_payload = {"分析状态": "分析中"}
    if not dry_run:
        update_record_fn(token, table_id, record_id, status_payload)

    final_payload = build_local_analysis_payload(fields, raw_model_output=raw_model_output)
    if not dry_run:
        update_record_fn(token, table_id, record_id, final_payload)

    return {
        "dry_run": dry_run,
        "record_id": record_id,
        "table_id": table_id,
        "validation": {
            "ready": validation.ready,
            "video_source_type": validation.video_source_type,
            "linked_product_record_id": validation.linked_product_record_id,
            "target_market": validation.target_market,
            "blocking_missing_fields": validation.blocking_missing_fields,
        },
        "prompt_payload": prompt_payload,
        "model_required": False,
        "call_model_enabled": call_model,
        "would_set_in_progress": status_payload,
        "write_payload": final_payload,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="UGC-01 单视频分析。默认 dry-run，不写飞书。")
    parser.add_argument("record_id", nargs="?", help="UGC-01 record_id。")
    parser.add_argument("--fields-json", help="本地测试用：UGC-01 fields JSON 文件路径。")
    parser.add_argument("--mock-output", help="本地测试用：模型 JSON_OUTPUT/MARKDOWN_OUTPUT mock 文件路径。")
    parser.add_argument("--print-prompt", action="store_true", help="打印分析 system prompt，用于人工检查。")
    parser.add_argument("--write", action="store_true", help="真实写回飞书。默认 dry-run；也可用 UGC_DRY_RUN=0。")
    parser.add_argument("--call-model", action="store_true", help="无 --mock-output 且输入 ready 时调用真实 Gemini/LLM。")
    args = parser.parse_args(argv)

    if args.print_prompt:
        print(load_analysis_system_prompt())
        return 0

    raw_model_output = None
    if args.mock_output:
        raw_model_output = Path(args.mock_output).read_text(encoding="utf-8")

    if args.fields_json:
        fields = json.loads(Path(args.fields_json).read_text(encoding="utf-8"))
        if raw_model_output is None and args.call_model:
            validation = validate_ugc01_inputs(fields)
            if not validation.ready:
                payload = build_blocked_analysis_payload(validation)
                print(json.dumps(payload, ensure_ascii=False, indent=2))
                return 0
            token = get_feishu_token()
            prompt_payload = build_analysis_prompt_payload(
                fields,
                product_fields=fields.get("产品字段") or fields.get("product_fields") or {},
                record_id=args.record_id or "local-fields-json",
            )
            raw_model_output = call_ugc_analysis_model(
                token=token,
                fields=fields,
                record_id=args.record_id or "local-fields-json",
                prompt_payload=prompt_payload,
                model_config=get_ugc_analysis_model_config(token),
            )
        payload = build_local_analysis_payload(fields, raw_model_output=raw_model_output)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if not args.record_id:
        parser.error("需要提供 record_id；或使用 --fields-json 进行本地测试。")

    dry_run = False if args.write else is_dry_run_from_env()
    result = run_ugc01_analysis(args.record_id, dry_run=dry_run, raw_model_output=raw_model_output, call_model=args.call_model)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
