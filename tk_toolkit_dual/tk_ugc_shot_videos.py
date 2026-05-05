#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

from ugc_config import UGC_BASE_TOKEN, load_ugc_table_ids
from ugc_utils import extract_text
from tk_ugc_six_grid import get_feishu_token, get_ugc_record, update_ugc_record, json_dumps
from tk_ugc_shot_images import get_attachment_token

UGC_VIDEO_STAGE_NAME = "UGC-分镜视频生成"
BASE_WORK_DIR = Path(__file__).resolve().parent / "workspace_ryan" / "ugc_shot_video_work"
POLL_INTERVAL = 15
MAX_POLL_SECONDS = 1800
SUBMIT_TIMEOUT = 120
POLL_TIMEOUT = 30
DOWNLOAD_TIMEOUT = 300
DEFAULT_SIZE = "720x1280"

RecordGetter = Callable[[str, str, str], Dict[str, Any]]
RecordUpdater = Callable[[str, str, str, Dict[str, Any]], Any]
VideoSubmitter = Callable[[Dict[str, str], str, str, str], Tuple[str, Dict[str, Any]]]
VideoPoller = Callable[[Dict[str, str], str], Dict[str, Any]]
Downloader = Callable[[str, str], str]
Uploader = Callable[[str, str, str], str]


def parse_json_field(raw: Any, label: str) -> Dict[str, Any]:
    text = extract_text(raw).strip()
    if not text:
        raise ValueError(f"缺少 {label}")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"{label} 不是 JSON 对象")
    return data


def get_model_config(stage_name: str = UGC_VIDEO_STAGE_NAME) -> Tuple[str, Dict[str, str]]:
    from common import TABLE_CONFIG, safe_list_records

    token = get_feishu_token()
    for rec in safe_list_records(token, TABLE_CONFIG):
        fields = rec.get("fields", {})
        if extract_text(fields.get("环节", "")).strip() == stage_name:
            cfg = {
                "model": extract_text(fields.get("模型名称", "")).strip(),
                "api_key": extract_text(fields.get("API Key", "")).strip(),
                "api_base": extract_text(fields.get("API 代理地址", "")).strip(),
                "prompt_template": extract_text(fields.get("提示词", "")).strip(),
                "call_type": extract_text(fields.get("调用方式", "")).strip(),
            }
            if not cfg["model"]:
                raise ValueError(f"{stage_name} 缺少模型名称")
            if not cfg["api_key"]:
                raise ValueError(f"{stage_name} 缺少 API Key")
            if not cfg["api_base"]:
                raise ValueError(f"{stage_name} 缺少 API 代理地址")
            return rec.get("record_id") or rec.get("id") or "", cfg
    raise ValueError(f"找不到模型配置: {stage_name}")


def ensure_work_dir(record_id: str) -> Path:
    work_dir = BASE_WORK_DIR / record_id
    work_dir.mkdir(parents=True, exist_ok=True)
    return work_dir


def download_feishu_media(token: str, file_token: str, save_path: Path) -> Path:
    url = f"https://open.feishu.cn/open-apis/drive/v1/medias/{file_token}/download"
    resp = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=DOWNLOAD_TIMEOUT, stream=True)
    if resp.status_code != 200:
        raise RuntimeError(f"飞书附件下载失败: HTTP {resp.status_code}, file_token={file_token}")
    with save_path.open("wb") as f:
        for chunk in resp.iter_content(8192):
            if chunk:
                f.write(chunk)
    if save_path.stat().st_size < 1000:
        raise RuntimeError(f"飞书附件下载结果过小: {save_path}")
    return save_path


def resolve_reference_image(token: str, record_id: str, fields: Dict[str, Any], work_dir: Path) -> Path:
    local_path = extract_text(fields.get("高清分镜图路径")).strip()
    if local_path and Path(local_path).exists():
        return Path(local_path)
    file_token = extract_text(fields.get("高清分镜图file_token")).strip() or get_attachment_token(fields.get("高清分镜图"))
    if not file_token:
        prompt_json = parse_json_field(fields.get("图生视频提示词"), f"UGC-06 {record_id}.图生视频提示词")
        source = prompt_json.get("source_image_policy") or {}
        file_token = str(source.get("ugc05_hd_file_token") or "").strip()
        local_path = str(source.get("ugc05_hd_local_path") or "").strip()
        if local_path and Path(local_path).exists():
            return Path(local_path)
    if not file_token:
        raise ValueError(f"UGC-06 {record_id} 缺少高清分镜图 file_token/路径")
    return download_feishu_media(token, file_token, work_dir / f"{record_id}_reference.png")


def build_model_prompt(fields: Dict[str, Any]) -> str:
    prompt_json = parse_json_field(fields.get("图生视频提示词"), "UGC-06.图生视频提示词")
    prompt = str(prompt_json.get("prompt_en") or prompt_json.get("prompt_cn") or "").strip()
    negative = str(prompt_json.get("negative_prompt") or "").strip()
    if not prompt:
        raise ValueError("图生视频提示词 JSON 中缺少 prompt_en/prompt_cn")
    if negative and "Negative prompt:" not in prompt:
        prompt = f"{prompt}\n\nNegative prompt: {negative}"
    return prompt


def submit_otu_video_task(config: Dict[str, str], prompt: str, image_path: str, size: str = DEFAULT_SIZE) -> Tuple[str, Dict[str, Any]]:
    api_base = config["api_base"].rstrip("/")
    url = f"{api_base}/v1/videos"
    headers = {"Authorization": f"Bearer {config['api_key']}"}
    with open(image_path, "rb") as image_file:
        files = [
            ("input_reference[]", (os.path.basename(image_path), image_file, "image/png")),
        ]
        data = {
            "model": config["model"],
            "prompt": prompt,
            "size": size,
        }
        resp = requests.post(url, headers=headers, data=data, files=files, timeout=SUBMIT_TIMEOUT)
    try:
        body = resp.json()
    except Exception:
        body = {"raw_text": resp.text[:1000]}
    if resp.status_code >= 400:
        raise RuntimeError(f"OTU 视频任务提交失败: HTTP {resp.status_code}, body={str(body)[:1000]}")
    task_id = extract_text(body.get("id") or body.get("task_id") or (body.get("data") or {}).get("id") or (body.get("data") or {}).get("task_id")).strip()
    if not task_id:
        raise RuntimeError(f"OTU 视频任务提交未返回 task_id: {str(body)[:1000]}")
    return task_id, body


def poll_otu_video_task(config: Dict[str, str], task_id: str) -> Dict[str, Any]:
    api_base = config["api_base"].rstrip("/")
    url = f"{api_base}/v1/videos/{task_id}"
    headers = {"Authorization": f"Bearer {config['api_key']}"}
    start = time.time()
    last_body: Dict[str, Any] = {}
    while time.time() - start < MAX_POLL_SECONDS:
        resp = requests.get(url, headers=headers, timeout=POLL_TIMEOUT)
        try:
            body = resp.json()
        except Exception:
            body = {"raw_text": resp.text[:1000]}
        last_body = body if isinstance(body, dict) else {"raw": body}
        if resp.status_code >= 400:
            raise RuntimeError(f"OTU 视频任务轮询失败: HTTP {resp.status_code}, body={str(last_body)[:1000]}")
        status = extract_text(
            last_body.get("status")
            or (last_body.get("data") or {}).get("status")
            or (last_body.get("result") or {}).get("status")
        ).lower()
        if status in {"completed", "succeeded", "success", "done"}:
            return last_body
        if status in {"failed", "error", "cancelled", "canceled"}:
            raise RuntimeError(f"OTU 视频生成失败: {str(last_body)[:1500]}")
        time.sleep(POLL_INTERVAL)
    raise TimeoutError(f"OTU 视频任务超时: task_id={task_id}, last={str(last_body)[:1000]}")


def iter_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from iter_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from iter_strings(item)


def extract_video_url(result: Dict[str, Any]) -> str:
    preferred_keys = ("video_url", "result_url", "download_url", "url")
    stack = [result]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for key in preferred_keys:
                val = cur.get(key)
                if isinstance(val, str) and val.startswith("http"):
                    return val
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)
    for text in iter_strings(result):
        if text.startswith("http") and (".mp4" in text or "/video/" in text or "videos-" in text):
            return text
    return ""


def download_video(video_url: str, save_path: str) -> str:
    resp = requests.get(video_url, timeout=DOWNLOAD_TIMEOUT, stream=True, allow_redirects=True)
    if resp.status_code != 200:
        raise RuntimeError(f"视频下载失败: HTTP {resp.status_code}, url={video_url[:300]}")
    with open(save_path, "wb") as f:
        for chunk in resp.iter_content(8192):
            if chunk:
                f.write(chunk)
    if os.path.getsize(save_path) < 10000:
        raise RuntimeError(f"视频下载成功但文件过小: {save_path}")
    return save_path


def upload_video_to_feishu(token: str, file_path: str, file_name: str) -> str:
    with open(file_path, "rb") as f:
        resp = requests.post(
            "https://open.feishu.cn/open-apis/drive/v1/medias/upload_all",
            headers={"Authorization": f"Bearer {token}"},
            data={
                "file_name": file_name,
                "parent_type": "bitable_file",
                "parent_node": UGC_BASE_TOKEN,
                "size": str(os.path.getsize(file_path)),
            },
            files={"file": (file_name, f, "video/mp4")},
            timeout=300,
        )
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"飞书视频上传失败: {data.get('msg') or data}")
    return data["data"]["file_token"]


def compact_json(value: Any, max_chars: int = 20000) -> str:
    text = json_dumps(value)
    if len(text) <= max_chars:
        return text
    return text[:max_chars - 200] + "\n...TRUNCATED..."


def build_success_fields(config: Dict[str, str], task_id: str, result: Dict[str, Any], video_url: str, local_path: str, file_token: str) -> Dict[str, Any]:
    return {
        "视频生成模型": config["model"],
        "视频生成状态": "成功",
        "分镜视频": [{"file_token": file_token, "name": Path(local_path).name}],
        "本地视频路径": local_path,
        "分镜视频file_token": file_token,
        "分镜视频URL": video_url,
        "视频生成任务ID": task_id,
        "视频生成原始响应JSON": compact_json(result),
        "错误信息": "",
        "分镜视频审核状态": "待确认",
        "分镜视频操作": "不触发",
        "分镜视频执行状态": "成功",
    }


def run_ugc06_video_generation(
    record_id: str,
    *,
    dry_run: bool = False,
    token: Optional[str] = None,
    get_record_fn: RecordGetter = get_ugc_record,
    update_record_fn: RecordUpdater = update_ugc_record,
    submitter: VideoSubmitter = submit_otu_video_task,
    poller: VideoPoller = poll_otu_video_task,
    downloader: Downloader = download_video,
    uploader: Uploader = upload_video_to_feishu,
    allow_overwrite: bool = False,
) -> Dict[str, Any]:
    token = token or get_feishu_token()
    table_ids = load_ugc_table_ids()
    table_id = table_ids["ugc_06_shot_videos"]
    fields = get_record_fn(token, table_id, record_id)
    status = extract_text(fields.get("视频生成状态")).strip()
    if status == "成功" and not dry_run and not allow_overwrite:
        raise ValueError(f"UGC-06 {record_id} 已成功，拒绝重复生成；如需重生请使用审核入口 allow_overwrite")
    cfg_record_id, config = get_model_config()
    work_dir = ensure_work_dir(record_id)
    image_path = resolve_reference_image(token, record_id, fields, work_dir)
    prompt = build_model_prompt(fields)
    output_path = str(work_dir / f"{record_id}_video.mp4")
    summary: Dict[str, Any] = {
        "record_id": record_id,
        "dry_run": dry_run,
        "config_record_id": cfg_record_id,
        "model": config["model"],
        "api_base": config["api_base"],
        "reference_image_path": str(image_path),
        "prompt_chars": len(prompt),
        "output_path": output_path,
        "allow_overwrite": allow_overwrite,
    }
    if dry_run:
        summary["status"] = "dry_run_ready"
        return summary

    task_id = ""
    try:
        update_record_fn(token, table_id, record_id, {
            "视频生成模型": config["model"],
            "视频生成状态": "生成中",
            "分镜视频执行状态": "处理中",
            "错误信息": "准备提交 UGC-06 图生视频任务...",
        })
        task_id, submit_result = submitter(config, prompt, str(image_path), DEFAULT_SIZE)
        update_record_fn(token, table_id, record_id, {
            "视频生成任务ID": task_id,
            "视频生成原始响应JSON": compact_json({"submit": submit_result}),
            "错误信息": f"已提交 UGC-06 图生视频任务，正在轮询。task_id={task_id}",
        })
        result = poller(config, task_id)
        video_url = extract_video_url(result)
        if not video_url:
            raise RuntimeError(f"上游已完成但未解析到视频 URL: {str(result)[:1500]}")
        downloader(video_url, output_path)
        video_file_token = uploader(token, output_path, f"{record_id}_video.mp4")
        success_fields = build_success_fields(config, task_id, result, video_url, output_path, video_file_token)
        update_record_fn(token, table_id, record_id, success_fields)
        summary.update({
            "status": "success",
            "task_id": task_id,
            "video_url": video_url,
            "video_file_token": video_file_token,
            "output_size": os.path.getsize(output_path),
        })
        return summary
    except Exception as exc:
        error_message = f"UGC-06 视频生成失败: {exc}"
        try:
            update_record_fn(token, table_id, record_id, {
                "视频生成状态": "失败",
                "视频生成任务ID": task_id,
                "错误信息": error_message[:1000],
            })
        except Exception:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="UGC-06 单镜头图生视频生成。建议先用 --dry-run，再真实跑单条 smoke test。")
    parser.add_argument("record_id", help="UGC-06 record_id")
    parser.add_argument("--dry-run", action="store_true", help="只验证输入和配置，不提交视频任务")
    parser.add_argument("--output-file", help="保存运行摘要 JSON")
    args = parser.parse_args()
    result = run_ugc06_video_generation(args.record_id, dry_run=args.dry_run)
    text = json_dumps(result)
    print(text)
    if args.output_file:
        Path(args.output_file).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_file).write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
