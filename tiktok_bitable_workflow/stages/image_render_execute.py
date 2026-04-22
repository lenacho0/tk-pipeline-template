#!/usr/bin/env python3
"""
阶段7：真实生图执行
读取版本任务的 生图提示词JSON，逐镜头生成真实图片，上传回 分镜图附件。
首版策略：1 shot -> 1 image，先打通真实执行链，不直接做九宫格拼图。
"""
import base64
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
BASE_WORK_DIR = os.path.join(WORKSPACE, "image_render_execute")
os.makedirs(BASE_WORK_DIR, exist_ok=True)


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
        "model": "gemini-2.5-flash-image-preview",
        "api_key": "",
        "api_base": "https://api.aitgenne.com/",
        "prompt": "",
        "source": "fallback",
    }
    if not CONFIG_TABLE:
        return runtime
    for rec in list_records(token, CONFIG_TABLE):
        flds = rec.get("fields", {})
        stage = extract_text(flds.get("环节名", "")).strip() or extract_text(flds.get("环节", "")).strip()
        if not stage:
            continue
        if (
            "生图执行" in stage
            or "分镜图执行" in stage
            or "图片生成" in stage
            or "image_render_execute" in stage.lower()
        ):
            api_cfg = parse_api_config_text(flds.get("API配置", ""))
            return {
                "model": extract_text(flds.get("模型名", "")).strip() or extract_text(flds.get("模型名称", "")).strip() or api_cfg.get("model") or runtime["model"],
                "api_key": extract_text(flds.get("API Key", "")).strip() or api_cfg.get("api_key") or runtime["api_key"],
                "api_base": extract_text(flds.get("API 代理地址", "")).strip() or api_cfg.get("api_base") or runtime["api_base"],
                "prompt": extract_text(flds.get("系统提示词", "")).strip() or extract_text(flds.get("提示词", "")).strip(),
                "source": f"bitable:{rec.get('record_id')}",
            }
    return runtime


def upload_image_to_feishu(token: str, file_path: str, file_name: str) -> str:
    with open(file_path, 'rb') as f:
        resp = requests.post(
            'https://open.feishu.cn/open-apis/drive/v1/medias/upload_all',
            headers={'Authorization': f'Bearer {token}'},
            data={
                'file_name': file_name,
                'parent_type': 'bitable_file',
                'parent_node': APP_TOKEN,
                'size': str(os.path.getsize(file_path))
            },
            files={'file': (file_name, f, 'image/png')},
            timeout=120
        )
    data = resp.json()
    if data.get('code') != 0:
        raise RuntimeError(f"upload image failed: {data}")
    return data['data']['file_token']


def ensure_task_dir(record_id: str) -> str:
    task_dir = os.path.join(BASE_WORK_DIR, record_id)
    os.makedirs(task_dir, exist_ok=True)
    return task_dir


def render_image_with_gemini(api_key: str, api_base: str, model: str, prompt: str, out_path: str) -> None:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key, http_options={"base_url": api_base})
    resp = client.models.generate_content(
        model=model,
        contents=[types.Content(role='user', parts=[types.Part.from_text(text=prompt)])],
        config=types.GenerateContentConfig(response_modalities=['image', 'text'], temperature=0.2)
    )
    candidates = getattr(resp, 'candidates', []) or []
    for cand in candidates:
        content = getattr(cand, 'content', None)
        parts = getattr(content, 'parts', []) or []
        for part in parts:
            inline = getattr(part, 'inline_data', None)
            data = getattr(inline, 'data', None) if inline else None
            if data:
                binary = base64.b64decode(data) if isinstance(data, str) else data
                with open(out_path, 'wb') as f:
                    f.write(binary)
                if os.path.getsize(out_path) < 1000:
                    raise RuntimeError('rendered image too small')
                return
    raise RuntimeError('image model returned no image data')


def main(argv=None):
    argv = argv or sys.argv
    if len(argv) < 2:
        print("Usage: python3 stages/image_render_execute.py <record_id>")
        sys.exit(1)

    record_id = argv[1]
    token = get_feishu_token()
    fields = get_record(token, SCRIPT_TASKS_TABLE, record_id)
    raw = extract_text(fields.get("生图提示词JSON", "")).strip()
    if not raw:
        raise RuntimeError("缺少 生图提示词JSON")

    payload = json.loads(raw)
    shots = payload.get("shots", [])
    if not shots:
        raise RuntimeError("生图提示词JSON 中没有 shots")

    runtime = read_runtime_config(token)
    if not runtime.get("api_key"):
        raise RuntimeError("生图执行阶段缺少 API Key；请在配置表增加“生图执行”配置记录")

    task_dir = ensure_task_dir(record_id)
    update_record(token, SCRIPT_TASKS_TABLE, record_id, {
        "下游推进状态": "生图中",
        "备注": f"image_render_execute started ({runtime.get('source')})",
    })

    attachments = []
    state_items = []
    generated_files = []
    for idx, shot in enumerate(shots, start=1):
        shot_name = extract_text(shot.get("shot_number")) or f"shot_{idx}"
        prompt = extract_text(shot.get("prompt"))
        if not prompt:
            state_items.append({"shot_number": shot_name, "status": "failed", "error": "missing prompt"})
            continue
        final_prompt = f"{runtime.get('prompt','').strip()}\n\n{prompt}".strip()
        out_path = os.path.join(task_dir, f"{idx:02d}_{shot_name}.png")
        try:
            render_image_with_gemini(runtime["api_key"], runtime["api_base"], runtime["model"], final_prompt, out_path)
            file_token = upload_image_to_feishu(token, out_path, os.path.basename(out_path))
            attachments.append({"file_token": file_token})
            generated_files.append(out_path)
            state_items.append({"shot_number": shot_name, "status": "success", "file_name": os.path.basename(out_path), "local_path": out_path})
            log("INFO", "image rendered", record_id=record_id, shot=shot_name, file=out_path)
        except Exception as e:
            state_items.append({"shot_number": shot_name, "status": "failed", "error": str(e)[:300]})
            log("ERROR", "image render failed", record_id=record_id, shot=shot_name, error=str(e)[:300])

    has_failure = any(item.get("status") != "success" for item in state_items)
    status_payload = {
        "stage": "image_render_execute",
        "model": runtime.get("model"),
        "source": runtime.get("source"),
        "items": state_items,
        "generated_files": generated_files,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    writeback_error = None
    try:
        update_record(token, SCRIPT_TASKS_TABLE, record_id, {
            "分镜图附件": attachments,
            "分镜图状态JSON": json.dumps(status_payload, ensure_ascii=False, indent=2),
            "下游推进状态": "待图生视频" if not has_failure else "已终止",
            "备注": "image_render_execute success" if not has_failure else "image_render_execute partial/failed",
        })
    except Exception as e:
        writeback_error = str(e)
        status_payload["attachment_writeback_error"] = writeback_error
        update_record(token, SCRIPT_TASKS_TABLE, record_id, {
            "分镜图状态JSON": json.dumps(status_payload, ensure_ascii=False, indent=2),
            "下游推进状态": "待图生视频" if not has_failure else "已终止",
            "备注": f"image_render_execute attachment writeback failed: {str(e)[:200]}",
        })

    if has_failure:
        raise RuntimeError("部分镜头生图失败")
    if writeback_error:
        raise RuntimeError(f"生图已完成，但附件回写失败: {writeback_error}")
    log("INFO", "image_render_execute success", record_id=record_id, count=len(attachments))


if __name__ == "__main__":
    main()
