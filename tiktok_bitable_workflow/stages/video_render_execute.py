#!/usr/bin/env python3
"""
阶段8：真实图生视频执行
首版：读取图生视频提示词JSON + image_render_execute 生成的本地图片，逐镜头调视频模型，
把状态写回 分镜视频状态JSON；若附件字段不可写，则至少保留本地产物路径和执行状态。
"""
import json
import os
import sys
import time
from typing import Any, Dict, List

import requests

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
CONFIG_PATH = os.environ.get("TIKTOK_BITABLE_CONFIG", os.path.join(PROJECT_DIR, "config.json"))
if not os.path.isabs(CONFIG_PATH):
    CONFIG_PATH = os.path.abspath(os.path.join(PROJECT_DIR, CONFIG_PATH))


def load_config() -> Dict[str, Any]:
    if not os.path.exists(CONFIG_PATH):
        raise FileNotFoundError(f"Missing config: {CONFIG_PATH}")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


CFG = load_config()
FEISHU = CFG["feishu"]
TABLES = FEISHU["tables"]
APP_TOKEN = FEISHU["bitable_app_token"]
CONFIG_TABLE = TABLES.get("config", "")
SCRIPT_TASKS_TABLE = TABLES.get("script_tasks") or TABLES.get("script_gen", "")
WORKSPACE = os.path.abspath(os.path.join(PROJECT_DIR, CFG.get("workspace", "./workspace")))
IMAGE_WORK_DIR = os.path.join(WORKSPACE, "image_render_execute")
VIDEO_WORK_DIR = os.path.join(WORKSPACE, "video_render_execute")
os.makedirs(VIDEO_WORK_DIR, exist_ok=True)

POLL_INTERVAL = 8
MAX_POLL_TIME = 1800
DEFAULT_SECONDS = 4
DEFAULT_SIZE = '720x1280'


def log(level: str, msg: str, **kwargs: Any) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    extra = " ".join(f"{k}={repr(v)}" for k, v in kwargs.items() if v is not None)
    line = f"[{ts}] [{level}] {msg}"
    if extra:
        line += f" | {extra}"
    print(line, flush=True)


def extract_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: List[str] = []
        for item in value:
            if isinstance(item, dict):
                parts.append(item.get("text", ""))
            else:
                parts.append(str(item))
        return "".join(parts)
    return str(value)


def get_feishu_token() -> str:
    resp = requests.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": FEISHU["app_id"], "app_secret": FEISHU["app_secret"]},
        timeout=15,
    )
    data = resp.json()
    if "tenant_access_token" not in data:
        raise RuntimeError(f"Feishu token failed: {data}")
    return data["tenant_access_token"]


def feishu_headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def get_record(token: str, table_id: str, record_id: str) -> Dict[str, Any]:
    resp = requests.get(
        f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/records/{record_id}",
        headers=feishu_headers(token), timeout=20,
    )
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"get_record failed: {data}")
    return data["data"]["record"]["fields"]


def update_record(token: str, table_id: str, record_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    resp = requests.put(
        f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/records/{record_id}",
        headers=feishu_headers(token), json={"fields": fields}, timeout=30,
    )
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"update_record failed: {data}")
    return data


def list_records(token: str, table_id: str, page_size: int = 100) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    page_token = None
    while True:
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/records?page_size={page_size}"
        if page_token:
            url += f"&page_token={page_token}"
        resp = requests.get(url, headers=feishu_headers(token), timeout=20)
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"list_records failed: {data}")
        data_block = data.get("data", {})
        items.extend(data_block.get("items", []))
        if not data_block.get("has_more"):
            break
        page_token = data_block.get("page_token")
    return items


def parse_api_config_text(raw_text: Any) -> Dict[str, str]:
    raw = extract_text(raw_text).strip()
    if not raw:
        return {}
    try:
        if raw.startswith("{"):
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    result: Dict[str, str] = {}
    for line in raw.splitlines():
        line = line.strip().strip(",")
        if not line or ":" not in line:
            continue
        k, v = line.split(":", 1)
        result[k.strip()] = v.strip().strip('"').strip("'")
    return result


def read_runtime_config(token: str) -> Dict[str, str]:
    runtime = {
        "model": "seedance-1.0-lite",
        "api_key": "",
        "api_base": "https://api.aitgenne.com/",
        "source": "fallback",
    }
    if not CONFIG_TABLE:
        return runtime

    records = list_records(token, CONFIG_TABLE)
    exact_matches = []
    fuzzy_matches = []
    for rec in records:
        flds = rec.get("fields", {})
        stage = extract_text(flds.get("环节名", "")).strip() or extract_text(flds.get("环节", "")).strip()
        if not stage:
            continue
        normalized = stage.lower().strip()
        if stage in ("图生视频", "视频生成") or normalized == "video_render_execute":
            exact_matches.append(rec)
        elif "图生视频" in stage or "视频生成" in stage or "video_render_execute" in normalized:
            fuzzy_matches.append(rec)

    picked = exact_matches[0] if exact_matches else (fuzzy_matches[0] if fuzzy_matches else None)
    if not picked:
        return runtime

    flds = picked.get("fields", {})
    api_cfg = parse_api_config_text(flds.get("API配置", ""))
    return {
        "model": extract_text(flds.get("模型名", "")).strip() or extract_text(flds.get("模型名称", "")).strip() or api_cfg.get("model") or runtime["model"],
        "api_key": extract_text(flds.get("API Key", "")).strip() or api_cfg.get("api_key") or runtime["api_key"],
        "api_base": extract_text(flds.get("API 代理地址", "")).strip() or api_cfg.get("api_base") or runtime["api_base"],
        "source": f"bitable:{picked.get('record_id')}",
    }


def ensure_video_dir(record_id: str) -> str:
    path = os.path.join(VIDEO_WORK_DIR, record_id)
    os.makedirs(path, exist_ok=True)
    return path


def find_shot_image(record_id: str, shot_number: Any) -> str:
    image_dir = os.path.join(IMAGE_WORK_DIR, record_id)
    candidates = [
        os.path.join(image_dir, f"{int(shot_number):02d}_{shot_number}.png") if str(shot_number).isdigit() else "",
        os.path.join(image_dir, f"{int(shot_number):02d}_{int(shot_number)}.png") if str(shot_number).isdigit() else "",
    ]
    for path in candidates:
        if path and os.path.exists(path):
            return path
    for name in sorted(os.listdir(image_dir)) if os.path.isdir(image_dir) else []:
        if name.startswith(f"{int(shot_number):02d}_") and name.endswith('.png'):
            return os.path.join(image_dir, name)
    raise FileNotFoundError(f"找不到镜头图片: shot={shot_number}")


def submit_img2video(api_key: str, api_base: str, model: str, image_path: str, prompt: str, duration_sec: int) -> str:
    url = api_base.rstrip('/') + '/v1/videos'
    headers = {"Authorization": f"Bearer {api_key}"}
    data = {
        "model": model,
        "prompt": prompt,
        "duration": str(duration_sec or DEFAULT_SECONDS),
        "size": DEFAULT_SIZE,
    }
    with open(image_path, 'rb') as f:
        files = {
            "image": (os.path.basename(image_path), f, "image/png")
        }
        resp = requests.post(url, headers=headers, data=data, files=files, timeout=120)
    body = resp.json()
    data_block = body.get('data') if isinstance(body, dict) else None
    if data_block is None:
        data_block = {}
    task_id = (
        body.get('id')
        or body.get('task_id')
        or data_block.get('id')
        or data_block.get('task_id')
    )
    if not task_id:
        raise RuntimeError(f"submit img2video failed: {body}")
    return task_id


def poll_video(api_key: str, api_base: str, task_id: str) -> Dict[str, Any]:
    url = api_base.rstrip('/') + f'/v1/videos/{task_id}'
    headers = {"Authorization": f"Bearer {api_key}"}
    start = time.time()
    while True:
        resp = requests.get(url, headers=headers, timeout=30)
        body = resp.json()
        data_block = body.get('data') if isinstance(body, dict) else None
        if data_block is None:
            data_block = {}
        status = (
            body.get('status')
            or data_block.get('status')
            or body.get('state')
            or ''
        ).lower()
        if status in ('succeeded', 'completed', 'success'):
            return body
        if status in ('failed', 'error', 'cancelled', 'canceled'):
            raise RuntimeError(f"video task failed: {body}")
        if time.time() - start > MAX_POLL_TIME:
            raise TimeoutError(f"video task poll timeout: {task_id}")
        time.sleep(POLL_INTERVAL)


def extract_video_url(body: Dict[str, Any], api_key: str, api_base: str, task_id: str) -> str:
    candidates = [
        body.get('result_url'),
        body.get('download_url'),
        body.get('url'),
        (body.get('data') or {}).get('result_url') if isinstance(body, dict) else None,
        (body.get('data') or {}).get('download_url') if isinstance(body, dict) else None,
        (body.get('data') or {}).get('url') if isinstance(body, dict) else None,
        body.get('output', {}).get('url') if isinstance(body.get('output'), dict) else None,
    ]
    for item in candidates:
        if item:
            return item
    return api_base.rstrip('/') + f'/v1/videos/{task_id}/content?download=1'


def download_video(api_key: str, video_url: str, out_path: str) -> None:
    headers = {"Authorization": f"Bearer {api_key}"}
    resp = requests.get(video_url, headers=headers, timeout=180, stream=True)
    if resp.status_code != 200:
        raise RuntimeError(f"download video failed: {resp.status_code} {resp.text[:300]}")
    with open(out_path, 'wb') as f:
        for chunk in resp.iter_content(1024 * 1024):
            if chunk:
                f.write(chunk)
    if os.path.getsize(out_path) < 1000:
        raise RuntimeError("downloaded video too small")


def main(argv=None):
    argv = argv or sys.argv
    if len(argv) < 2:
        print("Usage: python3 stages/video_render_execute.py <record_id>")
        sys.exit(1)

    record_id = argv[1]
    token = get_feishu_token()
    fields = get_record(token, SCRIPT_TASKS_TABLE, record_id)
    raw = extract_text(fields.get("图生视频提示词JSON", "")).strip()
    if not raw:
        raise RuntimeError("缺少 图生视频提示词JSON")

    payload = json.loads(raw)
    shots = payload.get("shots", [])
    if not shots:
        raise RuntimeError("图生视频提示词JSON 中没有 shots")

    runtime = read_runtime_config(token)
    if not runtime.get("api_key"):
        raise RuntimeError("图生视频执行阶段缺少 API Key；请在配置表增加“图生视频/视频生成”配置记录")

    task_dir = ensure_video_dir(record_id)
    update_record(token, SCRIPT_TASKS_TABLE, record_id, {
        "下游推进状态": "图生视频中",
        "备注": f"video_render_execute started ({runtime.get('source')})",
    })

    items = []
    generated_files = []
    for idx, shot in enumerate(shots, start=1):
        shot_number = shot.get("shot_number", idx)
        prompt = extract_text(shot.get("video_prompt"))
        duration_sec = int(shot.get("duration_sec") or DEFAULT_SECONDS)
        if not prompt:
            items.append({"shot_number": shot_number, "status": "failed", "error": "missing video_prompt"})
            continue
        try:
            image_path = find_shot_image(record_id, shot_number)
            task_id = submit_img2video(runtime["api_key"], runtime["api_base"], runtime["model"], image_path, prompt, duration_sec)
            result = poll_video(runtime["api_key"], runtime["api_base"], task_id)
            video_url = extract_video_url(result, runtime["api_key"], runtime["api_base"], task_id)
            out_path = os.path.join(task_dir, f"{idx:02d}_{shot_number}.mp4")
            download_video(runtime["api_key"], video_url, out_path)
            generated_files.append(out_path)
            items.append({
                "shot_number": shot_number,
                "status": "success",
                "task_id": task_id,
                "local_path": out_path,
                "image_path": image_path,
            })
            log("INFO", "video rendered", record_id=record_id, shot=shot_number, file=out_path)
        except Exception as e:
            items.append({"shot_number": shot_number, "status": "failed", "error": str(e)[:1000]})
            log("ERROR", "video render failed", record_id=record_id, shot=shot_number, error=str(e)[:800])

    has_failure = any(item.get("status") != "success" for item in items)
    update_record(token, SCRIPT_TASKS_TABLE, record_id, {
        "分镜视频状态JSON": json.dumps({
            "stage": "video_render_execute",
            "model": runtime.get("model"),
            "source": runtime.get("source"),
            "generated_files": generated_files,
            "items": items,
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }, ensure_ascii=False, indent=2),
        "下游推进状态": "已完成" if not has_failure else "已终止",
        "备注": "video_render_execute success" if not has_failure else "video_render_execute partial/failed",
    })

    if has_failure:
        raise RuntimeError("部分镜头图生视频失败")
    log("INFO", "video_render_execute success", record_id=record_id, count=len(generated_files))


if __name__ == "__main__":
    main()
