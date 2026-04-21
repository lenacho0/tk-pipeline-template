import json
import os
import time
from typing import Any, Dict, List, Optional

import requests

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.environ.get("TIKTOK_BITABLE_CONFIG", os.path.join(SCRIPT_DIR, "config.json"))
if not os.path.isabs(CONFIG_PATH):
    CONFIG_PATH = os.path.abspath(os.path.join(SCRIPT_DIR, CONFIG_PATH))


def load_config() -> Dict[str, Any]:
    if not os.path.exists(CONFIG_PATH):
        raise FileNotFoundError(
            f"Missing config file: {CONFIG_PATH}\n"
            f"Copy config.example.json to config.json first."
        )
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


CFG = load_config()
FEISHU = CFG["feishu"]
TABLES = FEISHU["tables"]
APP_TOKEN = FEISHU["bitable_app_token"]
WORKSPACE = os.path.abspath(os.path.join(SCRIPT_DIR, CFG.get("workspace", "./workspace")))
os.makedirs(WORKSPACE, exist_ok=True)


def log(message: str, **kwargs: Any) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    extra = " ".join(f"{k}={repr(v)}" for k, v in kwargs.items() if v is not None)
    line = f"[{ts}] {message}"
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
        raise RuntimeError(f"Failed to get Feishu token: {data}")
    return data["tenant_access_token"]


def feishu_headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def get_record(token: str, table_id: str, record_id: str) -> Dict[str, Any]:
    resp = requests.get(
        f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/records/{record_id}",
        headers=feishu_headers(token),
        timeout=20,
    )
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"get_record failed: {data}")
    return data["data"]["record"]["fields"]


def update_record(token: str, table_id: str, record_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    resp = requests.put(
        f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/records/{record_id}",
        headers=feishu_headers(token),
        json={"fields": fields},
        timeout=30,
    )
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"update_record failed: {data}")
    return data


def create_records(token: str, table_id: str, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not records:
        return []
    created: List[Dict[str, Any]] = []
    for i in range(0, len(records), 10):
        batch = records[i:i + 10]
        resp = requests.post(
            f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/records/batch_create",
            headers=feishu_headers(token),
            json={"records": [{"fields": r} for r in batch]},
            timeout=30,
        )
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"create_records failed: {data}")
        created.extend(data.get("data", {}).get("records", []))
    return created


def list_records(token: str, table_id: str, page_size: int = 100) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    page_token: Optional[str] = None
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
