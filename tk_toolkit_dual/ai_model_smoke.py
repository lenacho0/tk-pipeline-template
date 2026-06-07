#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass
import datetime as dt
import json
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence
import zlib

import requests

import ai_model_catalog
import ai_routing
import sync_ai_model_catalog_to_feishu as governance


IMAGE_PROMPT = "Create a clean vertical product-style image with soft studio light. No text."
VIDEO_PROMPT = "A short vertical product-style shot with gentle camera movement and stable lighting."
DEFAULT_WORK_ROOT = Path(tempfile.gettempdir()) / "tk_ai_model_smoke"
DEFAULT_POLL_SECONDS = 0
POLL_INTERVAL_SECONDS = 10

SECRET_PATTERNS = [
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]+", re.I),
    re.compile(r"sk-[A-Za-z0-9._\-]+", re.I),
    re.compile(r"token=([^&\s]+)", re.I),
    re.compile(r"api[_-]?key=([^&\s]+)", re.I),
    re.compile(r"Authorization", re.I),
]


class _RuntimeConfig(Dict[str, str]):
    pass


def image_path_to_data_url(path: str) -> str:
    suffix = Path(path).suffix.lower()
    mime_type = "image/jpeg" if suffix in {".jpg", ".jpeg"} else "image/webp" if suffix == ".webp" else "image/png"
    with open(path, "rb") as image_file:
        image_b64 = base64.b64encode(image_file.read()).decode("ascii")
    return f"data:{mime_type};base64,{image_b64}"


@dataclass(frozen=True)
class SmokeProfile:
    name: str
    size: str
    aspect_ratio: str
    reference_orientation: str
    reference_count: int
    seconds: str = "8"


def redact_secret(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            ("[REDACTED]" if any(marker in str(k).lower() for marker in ("authorization", "api_key", "apikey", "token", "secret")) else k): redact_secret(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact_secret(item) for item in value]
    if isinstance(value, str):
        text = value
        for pattern in SECRET_PATTERNS:
            text = pattern.sub("[REDACTED]", text)
        return text
    return value


def enabled_media_entries() -> List[ai_model_catalog.ModelCatalogEntry]:
    return [
        entry for entry in ai_model_catalog.production_models()
        if entry.capability in {"图片", "视频"}
    ]


def build_smoke_queue(
    *,
    all_enabled_media: bool = False,
    model_names: Optional[Sequence[str]] = None,
) -> List[ai_model_catalog.ModelCatalogEntry]:
    if all_enabled_media:
        if model_names:
            raise ValueError("--all-enabled-media 与 --model 不能同时使用")
        return enabled_media_entries()
    if not model_names:
        raise ValueError("必须指定 --all-enabled-media 或至少一个 --model")
    queue: List[ai_model_catalog.ModelCatalogEntry] = []
    for name in model_names:
        bits = ai_routing.parse_model_display(name)
        provider = bits["provider"]
        model = bits["model"] or name
        matches = [
            entry for entry in ai_model_catalog.catalog_entries()
            if entry.provider == provider and entry.model == model
        ]
        entry = matches[0] if matches else None
        if not entry or entry.status != ai_model_catalog.STATUS_ENABLED or entry.capability not in {"图片", "视频"}:
            raise ValueError(f"不允许真实 smoke: {name}")
        queue.append(entry)
    return queue


def reference_count_for_entry(entry: ai_model_catalog.ModelCatalogEntry) -> int:
    return smoke_profile_for_entry(entry).reference_count


def smoke_profile_for_entry(entry: ai_model_catalog.ModelCatalogEntry) -> SmokeProfile:
    if entry.capability == "图片":
        params = governance.default_params(entry)
        return SmokeProfile(
            name="vertical_i2i",
            size=params.get("size") or "720x1280",
            aspect_ratio=params.get("aspect_ratio") or "9:16",
            reference_orientation="vertical",
            reference_count=1,
            seconds="",
        )
    if entry.provider == "OTU" and entry.model in {"veo_3_1", "veo_3_1-hd"}:
        return SmokeProfile("landscape_i2v", "1280x720", "16:9", "landscape", 1)
    if entry.model == "happyhorse-1.0-t2v":
        return SmokeProfile("text_to_video", "720x1280", "9:16", "vertical", 0)
    if entry.model == "happyhorse-1.0-r2v":
        return SmokeProfile("multi_reference", "720x1280", "9:16", "vertical", 2)
    return SmokeProfile("vertical_i2v", "720x1280", "9:16", "vertical", 1)


def make_route(entry: ai_model_catalog.ModelCatalogEntry, runtime_config: Optional[Dict[str, str]] = None) -> ai_routing.AiRoute:
    runtime_config = runtime_config or {}
    profile = smoke_profile_for_entry(entry)
    return ai_routing.AiRoute(
        provider=entry.provider,
        capability=entry.capability,
        task_type=governance.default_task(entry),
        model=entry.display_name,
        call_type=governance.default_call_type(entry),
        api_base=runtime_config.get("api_base") or governance.provider_base(entry),
        api_key=runtime_config.get("api_key") or "sk-redacted",
        params={"size": profile.size, "aspect_ratio": profile.aspect_ratio, "seconds": profile.seconds},
    )


def smoke_dry_run_summary(entry: ai_model_catalog.ModelCatalogEntry) -> Dict[str, Any]:
    route = make_route(entry)
    return ai_routing.build_media_request_summary(
        route,
        IMAGE_PROMPT if entry.capability == "图片" else VIDEO_PROMPT,
        reference_count=reference_count_for_entry(entry),
    )


def classify_error(exc: BaseException) -> str:
    text = str(exc).lower()
    if "缺少" in str(exc) or "config" in text or "api key" in text:
        return "config_missing"
    if "http 400" in text or "parameter" in text or "参数" in str(exc):
        return "parameter_error"
    if "http 401" in text or "http 403" in text or "unauthorized" in text:
        return "config_missing"
    if "http" in text or "endpoint" in text or "not found" in text:
        return "endpoint_error"
    if "timeout" in text or "超时" in str(exc):
        return "timeout"
    if "failed" in text or "失败" in str(exc):
        return "upstream_task_failed"
    if "empty" in text or "空" in str(exc):
        return "model_empty_output"
    return "unknown_error"


def png_bytes(width: int = 512, height: int = 512, color: Sequence[int] = (74, 144, 226)) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        import struct
        import zlib as _zlib

        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", _zlib.crc32(kind + data) & 0xFFFFFFFF)

    import struct

    row = bytes([0]) + bytes(color[:3]) * width
    raw = b"".join(row for _ in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")


def ensure_reference_images(work_root: Path) -> List[str]:
    work_root.mkdir(parents=True, exist_ok=True)
    paths = []
    specs = [
        ("vertical", 512, 896, (74, 144, 226)),
        ("vertical", 512, 896, (90, 190, 120)),
        ("landscape", 896, 512, (210, 150, 70)),
    ]
    for index, (orientation, width, height, color) in enumerate(specs, start=1):
        path = work_root / f"smoke-reference-{orientation}-{index}.png"
        if not path.exists():
            path.write_bytes(png_bytes(width=width, height=height, color=color))
        paths.append(str(path))
    return paths


def select_reference_paths(reference_paths: Sequence[str], profile: SmokeProfile) -> List[str]:
    selected = [path for path in reference_paths if f"reference-{profile.reference_orientation}-" in Path(path).name]
    if len(selected) < profile.reference_count:
        selected = list(reference_paths)
    return selected[:profile.reference_count]


def extract_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(item.get("text", "") if isinstance(item, dict) else str(item) for item in value)
    return str(value) if value else ""


def extract_task_id(body: Dict[str, Any]) -> str:
    return ai_routing.extract_video_task_id(body)


def extract_result_url(body: Dict[str, Any]) -> str:
    data = body.get("data") if isinstance(body.get("data"), dict) else {}
    result = body.get("result") if isinstance(body.get("result"), dict) else {}
    candidates = [
        body.get("video_url"),
        body.get("result_url"),
        body.get("url"),
        body.get("download_url"),
        data.get("video_url"),
        data.get("result_url"),
        data.get("url"),
        data.get("download_url"),
        result.get("video_url"),
        result.get("result_url"),
        result.get("url"),
        result.get("download_url"),
    ]
    for key in ("result_urls", "urls", "videos"):
        value = body.get(key) or data.get(key) or result.get(key)
        if isinstance(value, list) and value:
            first = value[0]
            if isinstance(first, str):
                candidates.append(first)
            elif isinstance(first, dict):
                candidates.extend([first.get("url"), first.get("video_url"), first.get("download_url")])
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.startswith("http"):
            return candidate
    return ""


def video_status(body: Dict[str, Any]) -> str:
    return ai_routing.extract_video_status(body)


def videos_endpoint(api_base: str) -> str:
    base = api_base.rstrip("/")
    if base.endswith("/v1/videos"):
        return base
    if base.endswith("/v1"):
        return f"{base}/videos"
    return f"{base}/v1/videos"


def parse_reference_urls(raw: Any) -> List[str]:
    if isinstance(raw, list):
        values = raw
    else:
        text = extract_text(raw).strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                parsed = json.loads(text)
                values = parsed if isinstance(parsed, list) else []
            except json.JSONDecodeError:
                values = []
        else:
            values = re.split(r"[\n,]+", text)
    return [extract_text(value).strip() for value in values if extract_text(value).strip().startswith("http")]


def happyhorse_smoke_reference_urls(runtime_config: Dict[str, str], selected_refs: Sequence[str], required_count: int) -> List[str]:
    urls = parse_reference_urls(runtime_config.get("happyhorse_reference_urls"))
    urls.extend(path for path in selected_refs if extract_text(path).strip().startswith("http"))
    deduped = list(dict.fromkeys(urls))
    if len(deduped) < required_count:
        raise ValueError("HappyHorse smoke 需要公网参考图 URL，请设置 HAPPYHORSE_SMOKE_REFERENCE_URLS")
    return deduped[:required_count]


def submit_smoke_task(
    entry: ai_model_catalog.ModelCatalogEntry,
    runtime_config: Dict[str, str],
    reference_paths: Sequence[str],
    *,
    post: Callable[..., Any] = requests.post,
) -> Dict[str, Any]:
    if not runtime_config.get("api_key"):
        raise ValueError(f"{entry.provider} 缺少 API Key")
    route = make_route(entry, runtime_config)
    endpoint = ai_routing.media_endpoint(route)
    profile = smoke_profile_for_entry(entry)
    selected_refs = select_reference_paths(reference_paths, profile)
    if entry.capability == "图片":
        image_path = selected_refs[0]
        payload = {
            "model": entry.model,
            "prompt": IMAGE_PROMPT,
            "metadata": {
                "aspectRatio": profile.aspect_ratio,
                "aspect_ratio": profile.aspect_ratio,
                "urls": [image_path_to_data_url(image_path)],
            },
            "input_mode": "image-to-image",
            "size": profile.size,
        }
        resp = post(endpoint, headers={"Authorization": f"Bearer {runtime_config['api_key']}", "Content-Type": "application/json"}, json=payload, timeout=180)
        payload_keys = sorted(payload.keys())
    else:
        data = {
            "model": entry.model,
            "prompt": VIDEO_PROMPT,
            "seconds": profile.seconds,
            "size": profile.size,
            "aspect_ratio": profile.aspect_ratio,
        }
        opened = []
        try:
            if entry.provider == "Aitgenne" and entry.model.startswith("happyhorse-1.0-"):
                reference_urls = happyhorse_smoke_reference_urls(runtime_config, selected_refs, profile.reference_count)
                payload = ai_routing.build_happyhorse_video_payload(
                    route,
                    VIDEO_PROMPT,
                    reference_urls,
                    size=profile.size,
                    aspect_ratio=profile.aspect_ratio,
                    seconds=profile.seconds,
                )
                resp = post(
                    endpoint,
                    headers={"Authorization": f"Bearer {runtime_config['api_key']}", "Content-Type": "application/json"},
                    json=payload,
                    timeout=180,
                )
                data = payload
            elif entry.provider == "AIHubMix" and entry.model == "seeddance2.0":
                image_file = open(selected_refs[0], "rb")
                opened.append(image_file)
                files: Any = {"image": (Path(selected_refs[0]).name, image_file, "image/png")}
                resp = post(endpoint, headers={"Authorization": f"Bearer {runtime_config['api_key']}"}, data=data, files=files, timeout=180)
            elif entry.provider == "AIHubMix":
                image_file = open(selected_refs[0], "rb")
                opened.append(image_file)
                files = {
                    "prompt": (None, data["prompt"]),
                    "model": (None, data["model"]),
                    "size": (None, data["size"]),
                    "aspect_ratio": (None, data["aspect_ratio"]),
                    "seconds": (None, data["seconds"]),
                    "input_reference[]": (Path(selected_refs[0]).name, image_file, "image/png"),
                }
                resp = post(endpoint, headers={"Authorization": f"Bearer {runtime_config['api_key']}"}, files=files, timeout=180)
            else:
                files = []
                for path in selected_refs:
                    image_file = open(path, "rb")
                    opened.append(image_file)
                    files.append(("input_reference[]", (Path(path).name, image_file, "image/png")))
                resp = post(endpoint, headers={"Authorization": f"Bearer {runtime_config['api_key']}"}, data=data, files=files, timeout=180)
        finally:
            for handle in opened:
                handle.close()
        payload_keys = sorted(data.keys())
    try:
        body = resp.json()
    except Exception:
        body = {"raw_text": getattr(resp, "text", "")[:1000]}
    if getattr(resp, "status_code", 200) >= 400:
        raise RuntimeError(f"HTTP {getattr(resp, 'status_code', '')}: {redact_secret(body)}")
    task_id = extract_task_id(body)
    result_url = extract_result_url(body)
    if not task_id and not result_url:
        raise RuntimeError(f"提交未返回任务 ID 或结果 URL: {redact_secret(body)}")
    return {
        "task_id": task_id,
        "result_url": result_url,
        "response_status": video_status(body) or "submitted",
        "payload_keys": payload_keys,
        "raw_response": redact_secret(body),
    }


def poll_smoke_task(
    entry: ai_model_catalog.ModelCatalogEntry,
    runtime_config: Dict[str, str],
    task_id: str,
    *,
    poll_seconds: int,
    get: Callable[..., Any] = requests.get,
) -> Dict[str, Any]:
    if not task_id or poll_seconds <= 0:
        return {}
    route = make_route(entry, runtime_config)
    endpoint = ai_routing.media_task_endpoint(route, task_id)
    deadline = time.time() + poll_seconds
    last_body: Dict[str, Any] = {}
    while time.time() < deadline:
        resp = get(endpoint, headers={"Authorization": f"Bearer {runtime_config['api_key']}"}, timeout=45)
        try:
            body = resp.json()
        except Exception:
            body = {"raw_text": getattr(resp, "text", "")[:1000]}
        last_body = body if isinstance(body, dict) else {"raw": body}
        if getattr(resp, "status_code", 200) >= 400:
            raise RuntimeError(f"HTTP {getattr(resp, 'status_code', '')}: {redact_secret(last_body)}")
        status = video_status(last_body)
        result_url = extract_result_url(last_body)
        if status in {"completed", "succeeded", "success", "done"} or result_url:
            return {"response_status": status or "completed", "result_url": result_url, "poll_response": redact_secret(last_body)}
        if status in {"failed", "error", "cancelled", "canceled"}:
            raise RuntimeError(f"上游任务失败: {redact_secret(last_body)}")
        time.sleep(POLL_INTERVAL_SECONDS)
    raise TimeoutError(f"轮询超时: task_id={task_id}, last={redact_secret(last_body)}")


def load_config(path: Path) -> Dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def feishu_headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def get_feishu_token(config: Dict[str, Any]) -> str:
    feishu = config["feishu"]
    resp = requests.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": feishu["app_id"], "app_secret": feishu["app_secret"]},
        timeout=10,
    )
    data = resp.json()
    token = data.get("tenant_access_token")
    if not token:
        raise RuntimeError(f"获取飞书 token 失败: {redact_secret(data)}")
    return token


def list_config_records(config: Dict[str, Any], token: str) -> List[Dict[str, Any]]:
    app_token = config["feishu"]["bitable_app_token"]
    table_id = config["feishu"]["tables"]["config"]
    records = []
    page_token = ""
    while True:
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records?page_size=100"
        if page_token:
            url += f"&page_token={page_token}"
        resp = requests.get(url, headers=feishu_headers(token), timeout=30)
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"读取配置表失败: {redact_secret(data)}")
        records.extend((data.get("data") or {}).get("items") or [])
        if not (data.get("data") or {}).get("has_more"):
            return records
        page_token = (data.get("data") or {}).get("page_token") or ""


def env_key_name(provider: str) -> str:
    return provider.upper().replace("HUBMIX", "HUBMIX").replace(" ", "") + "_API_KEY"


def config_record_matches_provider(fields: Dict[str, Any], provider: str) -> bool:
    provider_text = extract_text(fields.get("AI供应商")).strip()
    if provider_text == provider:
        return True
    base = extract_text(fields.get("API 代理地址")).lower()
    markers = {
        "OTU": "otuapi",
        "AIHubMix": "aihubmix",
        "Aitgenne": "aitgenne",
    }
    return markers.get(provider, "").lower() in base


def resolve_runtime_config(
    entry: ai_model_catalog.ModelCatalogEntry,
    *,
    local_config: Optional[Dict[str, Any]] = None,
    records: Optional[Sequence[Dict[str, Any]]] = None,
    env: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    env = env if env is not None else os.environ
    api_key = env.get(env_key_name(entry.provider), "").strip()
    if not api_key and records:
        for record in records:
            fields = record.get("fields") or {}
            candidate = extract_text(fields.get("API Key")).strip()
            if candidate and config_record_matches_provider(fields, entry.provider):
                api_key = candidate
                break
    return {
        "api_key": api_key,
        "api_base": governance.provider_base(entry),
        "model": entry.model,
        "happyhorse_reference_urls": env.get("HAPPYHORSE_SMOKE_REFERENCE_URLS", "").strip(),
    }


def smoke_result_template(entry: ai_model_catalog.ModelCatalogEntry) -> Dict[str, Any]:
    summary = smoke_dry_run_summary(entry)
    payload = summary.get("payload") or {}
    profile = smoke_profile_for_entry(entry)
    return {
        "display_name": entry.display_name,
        "profile": profile.name,
        "status": "pending",
        "capability": entry.capability,
        "endpoint": summary.get("endpoint", ""),
        "payload_keys": summary.get("payload_keys", []),
        "size": payload.get("size", ""),
        "aspect_ratio": payload.get("aspect_ratio") or (payload.get("metadata") or {}).get("aspectRatio") or "",
        "seconds": payload.get("seconds", ""),
        "reference_count": reference_count_for_entry(entry),
        "task_id": "",
        "result_url": "",
        "response_status": "",
        "error_type": "",
        "error": "",
    }


def run_smoke(
    entries: Sequence[ai_model_catalog.ModelCatalogEntry],
    *,
    execute: bool,
    local_config: Optional[Dict[str, Any]] = None,
    records: Optional[Sequence[Dict[str, Any]]] = None,
    work_root: Path = DEFAULT_WORK_ROOT,
    poll_seconds: int = DEFAULT_POLL_SECONDS,
) -> List[Dict[str, Any]]:
    reference_paths = ensure_reference_images(work_root)
    results = []
    for entry in entries:
        result = smoke_result_template(entry)
        if not execute:
            result["status"] = "dry_run_ready"
            results.append(result)
            continue
        runtime_config = resolve_runtime_config(entry, local_config=local_config, records=records)
        try:
            submit_result = submit_smoke_task(entry, runtime_config, reference_paths)
            result.update({k: v for k, v in submit_result.items() if k != "raw_response"})
            if poll_seconds > 0:
                poll_result = poll_smoke_task(entry, runtime_config, submit_result.get("task_id", ""), poll_seconds=poll_seconds)
                if poll_result:
                    result.update({k: v for k, v in poll_result.items() if k != "poll_response"})
            result["status"] = "ok"
        except Exception as exc:
            result["status"] = "failed"
            result["error_type"] = classify_error(exc)
            result["error"] = extract_text(redact_secret(str(exc)))[:1200]
        results.append(redact_secret(result))
    return results


def render_smoke_report(results: Sequence[Dict[str, Any]]) -> str:
    redacted = redact_secret(list(results))
    ok_count = sum(1 for item in redacted if item.get("status") == "ok")
    failed_count = sum(1 for item in redacted if item.get("status") == "failed")
    lines = [
        "# AI 模型全量媒体 Smoke Test 结果",
        "",
        f"- 生成时间: {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 模型数量: {len(redacted)}",
        f"- ok: {ok_count}",
        f"- failed: {failed_count}",
        "- 说明: 报告已脱敏；不写业务记录，不触发 dispatcher。",
        "",
    ]
    for item in redacted:
        lines.extend([
            f"## {item.get('display_name')}",
            "",
            f"- status: `{item.get('status', '')}`",
            f"- profile: `{item.get('profile', '')}`",
            f"- capability: `{item.get('capability', '')}`",
            f"- endpoint: `{item.get('endpoint', '')}`",
            f"- payload_keys: `{', '.join(item.get('payload_keys') or [])}`",
            f"- size: `{item.get('size', '')}`",
            f"- aspect_ratio: `{item.get('aspect_ratio', '')}`",
            f"- seconds: `{item.get('seconds', '')}`",
            f"- reference_count: `{item.get('reference_count', '')}`",
            f"- response_status: `{item.get('response_status', '')}`",
            f"- task_id: `{item.get('task_id', '')}`",
            f"- result_url: `{item.get('result_url', '')}`",
            f"- error_type: `{item.get('error_type', '')}`",
            f"- error: `{item.get('error', '')}`",
            "",
        ])
    return "\n".join(lines).rstrip() + "\n"


def should_downgrade_seeddance(result: Dict[str, Any]) -> bool:
    return (
        result.get("display_name") == "AIHubMix / seeddance2.0"
        and result.get("status") == "failed"
        and "no_valid_channel_error" in extract_text(result.get("error")).lower()
    )


def write_report(path: Path, results: Sequence[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_smoke_report(results), encoding="utf-8")


def main() -> None:
    today = dt.date.today().isoformat()
    parser = argparse.ArgumentParser(description="Smoke test enabled image/video AI models from the global catalog")
    parser.add_argument("--config", default=str(Path(__file__).resolve().parent / "config.json"))
    parser.add_argument("--all-enabled-media", action="store_true")
    parser.add_argument("--model", action="append", default=[])
    parser.add_argument("--execute", action="store_true", help="Actually submit provider smoke tasks")
    parser.add_argument("--poll-seconds", type=int, default=DEFAULT_POLL_SECONDS)
    parser.add_argument("--report-output", default=f"docs/tk-pipeline/ai-model-smoke-results-{today}.md")
    parser.add_argument("--work-root", default=str(DEFAULT_WORK_ROOT))
    args = parser.parse_args()

    entries = build_smoke_queue(all_enabled_media=args.all_enabled_media, model_names=args.model)
    local_config = load_config(Path(args.config))
    records: Optional[List[Dict[str, Any]]] = None
    if args.execute:
        token = get_feishu_token(local_config)
        records = list_config_records(local_config, token)
    results = run_smoke(
        entries,
        execute=args.execute,
        local_config=local_config,
        records=records,
        work_root=Path(args.work_root),
        poll_seconds=max(0, args.poll_seconds),
    )
    write_report(Path(args.report_output), results)
    summary = {
        "mode": "execute" if args.execute else "dry_run",
        "model_count": len(entries),
        "ok": sum(1 for item in results if item.get("status") == "ok"),
        "failed": sum(1 for item in results if item.get("status") == "failed"),
        "report_output": args.report_output,
    }
    print(json.dumps(redact_secret(summary), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
