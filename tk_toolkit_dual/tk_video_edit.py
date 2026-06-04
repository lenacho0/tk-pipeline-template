#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import requests

import ai_model_catalog
from ai_routing import AiRoute, aitgenne_video_synthesis_endpoint, config_record_for_model, media_task_endpoint, parse_model_display
from common import (
    APP_TOKEN,
    TABLE_CONFIG,
    TABLE_VIDEO_EDIT,
    WORKSPACE,
    extract_text,
    feishu_headers,
    get_feishu_token,
    safe_download_attachment,
    safe_get_record,
    safe_list_records,
    safe_request,
    safe_update_record,
)


MODEL_DISPLAY_NAME = "Aitgenne / happyhorse-1.0-video-edit"
MODEL_NAME = "happyhorse-1.0-video-edit"
DEFAULT_API_BASE = "https://api.aitgenne.com/v1"
BASE_WORK_DIR = Path(WORKSPACE) / "video_edit_work"
MAX_REFERENCE_IMAGES = 5
POLL_INTERVAL_SECONDS = 8
POLL_TIMEOUT_SECONDS = 2400


def _attachment_items(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict) and item.get("file_token")]


def source_video_attachment(fields: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    items = _attachment_items(fields.get("源视频"))
    return items[0] if items else None


def reference_attachments(fields: Mapping[str, Any]) -> List[Dict[str, Any]]:
    return _attachment_items(fields.get("参考图"))[:MAX_REFERENCE_IMAGES]


def normalize_audio_setting(value: Any) -> str:
    text = extract_text(value).strip()
    if text == "自动处理音频":
        return "auto"
    return "origin"


def normalize_resolution(value: Any) -> str:
    text = extract_text(value).strip().upper()
    return text if text in {"720P", "1080P"} else "720P"


def validate_video_edit_fields(fields: Mapping[str, Any]) -> None:
    if not source_video_attachment(fields):
        raise ValueError("源视频不能为空，请上传一个飞书视频附件")
    if not extract_text(fields.get("编辑指令")).strip():
        raise ValueError("编辑指令不能为空")


def ensure_video_edit_table() -> str:
    if not TABLE_VIDEO_EDIT:
        raise ValueError("config.json 尚未配置 video_edit 表 ID，请先运行 tk_create_video_edit_table.py --update-config")
    return TABLE_VIDEO_EDIT


def _safe_filename(name: str, fallback: str) -> str:
    raw = (name or fallback).strip() or fallback
    return "".join(ch if ch.isalnum() or ch in {".", "-", "_"} else "_" for ch in raw)


def download_feishu_attachment(token: str, attachment: Mapping[str, Any], save_path: Path) -> Path:
    save_path.parent.mkdir(parents=True, exist_ok=True)
    safe_download_attachment(token, attachment["file_token"], str(save_path))
    return save_path


def download_reference_attachments(token: str, attachments: Sequence[Mapping[str, Any]], work_dir: Path) -> List[str]:
    paths: List[str] = []
    for idx, item in enumerate(attachments[:MAX_REFERENCE_IMAGES], start=1):
        name = _safe_filename(str(item.get("name") or ""), f"reference_{idx}.png")
        path = work_dir / f"reference_{idx}_{name}"
        paths.append(str(download_feishu_attachment(token, item, path)))
    return paths


def attachment_tmp_url(token: str, attachment: Mapping[str, Any]) -> str:
    file_token = extract_text(attachment.get("file_token")).strip()
    if not file_token:
        return ""
    from tk_shot_storyboard import get_tmp_download_url_for_attachment

    return get_tmp_download_url_for_attachment(token, file_token)


def _config_record_text(fields: Mapping[str, Any], *names: str) -> str:
    for name in names:
        value = extract_text(fields.get(name)).strip()
        if value:
            return value
    return ""


def ensure_video_edit_model_enabled() -> None:
    entry = ai_model_catalog.find_model("Aitgenne", "视频编辑", MODEL_NAME)
    if entry is None:
        raise ValueError(f"模型未启用: {MODEL_DISPLAY_NAME}")


def resolve_video_edit_route(token: str) -> AiRoute:
    ensure_video_edit_model_enabled()
    config_records = safe_list_records(token, TABLE_CONFIG) if TABLE_CONFIG else []
    fields = config_record_for_model(config_records, "Aitgenne", MODEL_DISPLAY_NAME)
    if fields is None:
        raise ValueError(f"未找到模型配置: {MODEL_DISPLAY_NAME}")
    api_key = _config_record_text(fields, "API Key", "api_key")
    if not api_key:
        raise ValueError(f"模型配置缺少 API Key: {MODEL_DISPLAY_NAME}")
    api_base = _config_record_text(fields, "API 代理地址", "api_base") or DEFAULT_API_BASE
    return AiRoute(
        provider="Aitgenne",
        capability="视频编辑",
        task_type="视频编辑",
        model=MODEL_DISPLAY_NAME,
        call_type="happyhorse视频编辑",
        api_base=api_base,
        api_key=api_key,
        params={},
    )


def default_video_edit_route() -> AiRoute:
    return AiRoute(
        provider="Aitgenne",
        capability="视频编辑",
        task_type="视频编辑",
        model=MODEL_DISPLAY_NAME,
        call_type="happyhorse视频编辑",
        api_base=DEFAULT_API_BASE,
        api_key="",
        params={},
    )


def _response_json(resp: requests.Response) -> Dict[str, Any]:
    try:
        data = resp.json()
    except Exception:
        data = {"raw_text": getattr(resp, "text", "")[:1000]}
    if getattr(resp, "status_code", 200) >= 400:
        raise RuntimeError(f"Aitgenne 请求失败: HTTP {resp.status_code}, body={data}")
    return data if isinstance(data, dict) else {"data": data}


def _extract_task_id(data: Mapping[str, Any]) -> str:
    candidates = [
        data.get("id"),
        data.get("task_id"),
        data.get("video_id"),
        (data.get("data") or {}).get("id") if isinstance(data.get("data"), dict) else None,
        (data.get("data") or {}).get("task_id") if isinstance(data.get("data"), dict) else None,
        (data.get("output") or {}).get("task_id") if isinstance(data.get("output"), dict) else None,
    ]
    for item in candidates:
        text = extract_text(item).strip()
        if text:
            return text
    raise RuntimeError(f"Aitgenne 未返回视频任务ID: {data}")


def submit_aitgenne_video_edit_task(
    route: AiRoute,
    prompt: str,
    source_video_path: str,
    reference_paths: Sequence[str],
    params: Mapping[str, Any],
) -> Tuple[str, Dict[str, Any]]:
    ensure_video_edit_model_enabled()
    model_name = parse_model_display(route.model)["model"] or MODEL_NAME
    source_video_url = extract_text((params or {}).get("source_video_url")).strip()
    if not source_video_url:
        raise ValueError("Aitgenne 视频编辑缺少 source_video_url")
    media = [{"type": "video", "url": source_video_url}]
    for url in (params or {}).get("reference_image_urls") or []:
        text = extract_text(url).strip()
        if text:
            media.append({"type": "reference_image", "url": text})
    payload = {
        "model": model_name,
        "input": {
            "prompt": prompt,
            "media": media,
        },
        "parameters": {
            "resolution": params.get("resolution") or "720P",
            "audio_setting": params.get("audio_setting") or "origin",
        },
    }
    extra_params = {
        key: value
        for key, value in (params or {}).items()
        if key not in {"resolution", "audio_setting", "source_video_url", "reference_image_urls"} and value is not None
    }
    payload["parameters"].update(extra_params)
    resp = requests.post(
        aitgenne_video_synthesis_endpoint(route.api_base or DEFAULT_API_BASE),
        headers={"Authorization": f"Bearer {route.api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=180,
    )
    body = _response_json(resp)
    return _extract_task_id(body), body


def _walk_values(value: Any):
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in {"url", "video_url", "result_url", "output_url", "download_url", "media_url"}:
                yield item
            yield from _walk_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_values(item)
    elif isinstance(value, str):
        yield value


def extract_video_result_url(data: Mapping[str, Any]) -> str:
    for item in _walk_values(data):
        text = extract_text(item).strip()
        if text.startswith(("http://", "https://")):
            return text
    return ""


def _extract_status(data: Mapping[str, Any]) -> str:
    candidates = [
        data.get("status"),
        (data.get("data") or {}).get("status") if isinstance(data.get("data"), dict) else None,
        (data.get("data") or {}).get("state") if isinstance(data.get("data"), dict) else None,
        (data.get("output") or {}).get("task_status") if isinstance(data.get("output"), dict) else None,
    ]
    for item in candidates:
        text = extract_text(item).strip().lower()
        if text:
            return text
    return ""


def poll_aitgenne_video_edit_task(
    route: AiRoute,
    task_id: str,
    *,
    timeout_seconds: int = POLL_TIMEOUT_SECONDS,
    interval_seconds: int = POLL_INTERVAL_SECONDS,
) -> Dict[str, Any]:
    endpoint = media_task_endpoint(route, task_id)
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        resp = requests.get(endpoint, headers={"Authorization": f"Bearer {route.api_key}"}, timeout=45)
        body = _response_json(resp)
        status = _extract_status(body)
        if status in {"failed", "failure", "error", "cancelled"}:
            raise RuntimeError(f"Aitgenne 视频编辑失败: {body}")
        if status in {"succeeded", "success", "completed", "done"} and extract_video_result_url(body):
            return body
        url = extract_video_result_url(body)
        if url and not status:
            return body
        time.sleep(interval_seconds)
    raise TimeoutError(f"Aitgenne 视频编辑轮询超时: task_id={task_id}")


def download_video(url: str, save_path: Path) -> str:
    save_path.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, timeout=300, stream=True) as resp:
        resp.raise_for_status()
        with open(save_path, "wb") as f:
            for chunk in resp.iter_content(1024 * 1024):
                if chunk:
                    f.write(chunk)
    return str(save_path)


def upload_video_to_feishu(token: str, file_path: str, file_name: str) -> str:
    from tk_shot_video import upload_video_to_feishu as _upload_video_to_feishu

    return _upload_video_to_feishu(token, file_path, file_name)


def filter_existing_fields(token: str, table_id: str, fields: Mapping[str, Any]) -> Dict[str, Any]:
    if not table_id:
        return dict(fields)
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/fields?page_size=200"
    try:
        data = safe_request("get", url, headers=feishu_headers(token), timeout=15, max_attempts=2)
        items = data.get("data", {}).get("items") or []
        names = {item.get("field_name") or item.get("name") for item in items}
        names.discard(None)
        if not names:
            return dict(fields)
        return {key: value for key, value in fields.items() if key in names}
    except Exception:
        return dict(fields)


def _update_record_fields(token: str, table_id: str, record_id: str, fields: Mapping[str, Any]) -> None:
    safe_update_record(token, table_id, record_id, filter_existing_fields(token, table_id, dict(fields)))


def run_video_edit(
    record_id: str,
    *,
    work_dir: Path = BASE_WORK_DIR,
    submitter: Callable[[AiRoute, str, str, Sequence[str], Mapping[str, Any]], Tuple[str, Dict[str, Any]]] = submit_aitgenne_video_edit_task,
    poller: Callable[[AiRoute, str], Dict[str, Any]] = poll_aitgenne_video_edit_task,
) -> Dict[str, Any]:
    table_id = ensure_video_edit_table()
    token = get_feishu_token()
    fields = safe_get_record(token, table_id, record_id)
    validate_video_edit_fields(fields)
    task_dir = Path(work_dir) / record_id
    task_dir.mkdir(parents=True, exist_ok=True)

    prompt = extract_text(fields.get("编辑指令")).strip()
    source_attachment = source_video_attachment(fields)
    assert source_attachment is not None
    source_name = _safe_filename(str(source_attachment.get("name") or ""), "source.mp4")
    source_path = download_feishu_attachment(token, source_attachment, task_dir / source_name)
    reference_paths = download_reference_attachments(token, reference_attachments(fields), task_dir)
    source_video_url = attachment_tmp_url(token, source_attachment)
    if not source_video_url:
        raise ValueError("Aitgenne 视频编辑缺少源视频临时下载 URL")
    params = {
        "resolution": normalize_resolution(fields.get("输出分辨率")),
        "audio_setting": normalize_audio_setting(fields.get("音频策略")),
        "source_video_url": source_video_url,
        "reference_image_urls": [attachment_tmp_url(token, item) for item in reference_attachments(fields)],
    }

    if submitter is submit_aitgenne_video_edit_task or poller is poll_aitgenne_video_edit_task:
        route = resolve_video_edit_route(token)
    else:
        route = default_video_edit_route()
    existing_task_id = extract_text(fields.get("视频任务ID")).strip()
    task_id = existing_task_id
    try:
        _update_record_fields(token, table_id, record_id, {"编辑状态": "生成中", "错误信息": ""})
        if not task_id:
            task_id, submit_body = submitter(route, prompt, str(source_path), reference_paths, params)
            _update_record_fields(token, table_id, record_id, {"视频任务ID": task_id, "错误信息": ""})
        else:
            submit_body = {"id": task_id, "resumed": True}

        result_body = poller(route, task_id)
        result_url = extract_video_result_url(result_body)
        if not result_url:
            raise RuntimeError(f"Aitgenne 未返回结果视频 URL: {result_body}")
        output_name = f"{record_id}_video_edit.mp4"
        output_path = download_video(result_url, task_dir / output_name)
        file_token = upload_video_to_feishu(token, output_path, output_name)
        result_attachment = [{"file_token": file_token, "name": output_name}]
        _update_record_fields(token, table_id, record_id, {
            "编辑状态": "成功",
            "结果视频": result_attachment,
            "视频任务ID": task_id,
            "错误信息": "",
        })
        return {"status": "success", "task_id": task_id, "submit": submit_body, "result_url": result_url}
    except Exception as exc:
        _update_record_fields(token, table_id, record_id, {"编辑状态": "失败", "错误信息": str(exc)[:1000]})
        raise


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="运行 HappyHorse 视频编辑任务")
    parser.add_argument("mode", nargs="?", default="edit", choices=["edit"])
    parser.add_argument("record_id")
    args = parser.parse_args(argv)

    try:
        result = run_video_edit(args.record_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
