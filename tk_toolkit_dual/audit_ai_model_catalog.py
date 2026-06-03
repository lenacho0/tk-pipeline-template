#!/usr/bin/env python3
"""只读审计供应商模型接口并生成候选模型报告。"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ai_model_catalog  # noqa: E402


PROVIDERS = {
    "OTU": {
        "base_url": "https://otuapi.com",
        "api_key_env": "OTU_API_KEY",
    },
    "AIHubMix": {
        "base_url": "https://aihubmix.com",
        "api_key_env": "AIHUBMIX_API_KEY",
    },
    "Aitgenne": {
        "base_url": "https://api.aitgenne.com",
        "api_key_env": "AITGENNE_API_KEY",
    },
}

AITGENNE_PRICING_SEEDS = [
    {
        "provider": "Aitgenne",
        "model": "veo-3.1-fast",
        "display_name": "Aitgenne / veo-3.1-fast",
        "capability": "视频",
        "endpoint_type": "Google 音视频待验证",
        "price": "待人工确认",
        "source": "官网模型广场/人工录入",
    },
    {
        "provider": "Aitgenne",
        "model": "omni-flash",
        "display_name": "Aitgenne / omni-flash",
        "capability": "视频",
        "endpoint_type": "视频统一格式",
        "price": "待人工确认",
        "source": "官网模型广场/人工录入",
    },
    {
        "provider": "Aitgenne",
        "model": "happyhorse-1.0-r2v",
        "display_name": "Aitgenne / happyhorse-1.0-r2v",
        "capability": "视频",
        "endpoint_type": "happyhorse视频",
        "price": "待人工确认",
        "source": "官网模型广场/人工录入",
    },
    {
        "provider": "Aitgenne",
        "model": "happyhorse-1.0-i2v",
        "display_name": "Aitgenne / happyhorse-1.0-i2v",
        "capability": "视频",
        "endpoint_type": "happyhorse视频",
        "price": "待人工确认",
        "source": "官网模型广场/人工录入",
    },
]

SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]+"),
    re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]+", re.I),
    re.compile(r"token=([^&\s]+)", re.I),
    re.compile(r"api[_-]?key=([^&\s]+)", re.I),
]
VISIBLE_REPORT_STATUSES = {"enabled", "candidate"}


def redact_secret(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: redact_secret(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_secret(item) for item in value]
    if not isinstance(value, str):
        return value
    redacted = value
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub(lambda match: match.group(0).split("=")[0] + "=[REDACTED]" if "=" in match.group(0) else "[REDACTED]", redacted)
    redacted = re.sub(r"\bInvalid token\b", "Invalid credential", redacted, flags=re.I)
    return redacted


def models_endpoint(base_url: str) -> str:
    base = (base_url or "").strip().rstrip("/")
    if base.endswith("/v1/models"):
        return base
    if base.endswith("/v1"):
        return f"{base}/models"
    return f"{base}/v1/models"


def parse_model_ids(payload: Dict[str, Any]) -> List[str]:
    data = payload.get("data")
    if isinstance(data, dict):
        data = data.get("items") or data.get("models") or []
    if not isinstance(data, list):
        data = payload.get("models") if isinstance(payload.get("models"), list) else []
    models = []
    for item in data:
        if isinstance(item, str):
            models.append(item)
        elif isinstance(item, dict):
            model_id = item.get("id") or item.get("model") or item.get("name")
            if model_id:
                models.append(str(model_id))
    return sorted(set(models))


def fetch_provider_models(
    provider: str,
    *,
    api_key: str = "",
    base_url: str = "",
    get: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
    info = PROVIDERS[provider]
    url = models_endpoint(base_url or info["base_url"])
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    sender = get or requests.get
    try:
        response = sender(url, headers=headers, timeout=60)
        data = response.json()
        if getattr(response, "status_code", 200) >= 400:
            return {"models": [], "error": f"HTTP {response.status_code}: {redact_secret(data)}", "endpoint": url}
        return {"models": parse_model_ids(data), "error": "", "endpoint": url}
    except Exception as exc:
        return {"models": [], "error": redact_secret(str(exc)), "endpoint": url}


def infer_capability(model: str) -> str:
    key = model.lower()
    if any(marker in key for marker in ("image", "banana")):
        return "图片"
    if any(marker in key for marker in ("veo", "video", "sora", "seedance", "happyhorse", "omni", "kling", "pixverse", "wan", "hailuo")):
        return "视频"
    if any(marker in key for marker in ("speech", "tts", "audio")):
        return "语音"
    return "文本"


def catalog_status(provider: str, capability: str, model: str) -> str:
    entry = ai_model_catalog.find_model(provider, capability, model, include_candidate=True)
    if entry:
        return entry.status
    for item in ai_model_catalog.catalog_entries():
        if item.provider == provider and item.model == model:
            return item.status
    lowered = model.lower()
    if any(marker in lowered for marker in ("banana", "sora", "kling", "pixverse", "wan", "hailuo")):
        return "discard"
    return "candidate"


def row_for_model(provider: str, model: str, *, source: str, price: str = "") -> Dict[str, str]:
    capability = infer_capability(model)
    entry = ai_model_catalog.find_model(provider, capability, model, include_candidate=True)
    if not entry:
        entry = next((item for item in ai_model_catalog.catalog_entries() if item.provider == provider and item.model == model), None)
    return {
        "供应商": provider,
        "模型 ID": model,
        "展示名": entry.display_name if entry else f"{provider} / {model}",
        "能力类型": entry.capability if entry else capability,
        "支持端点": entry.endpoint_type if entry else "待确认",
        "价格信息": price or (entry.price if entry else "待确认"),
        "是否适合九宫格": entry.nine_grid_fit if entry and entry.nine_grid_fit else "待确认",
        "建议状态": catalog_status(provider, capability, model),
        "来源": source,
    }


def build_candidate_rows(api_results: Dict[str, Dict[str, Any]], pricing_models: Iterable[Dict[str, str]]) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    seen = set()
    for entry in ai_model_catalog.catalog_entries():
        if entry.status not in VISIBLE_REPORT_STATUSES:
            seen.add((entry.provider, entry.model))
            continue
        if entry.capability not in ai_model_catalog.UNIFIED_AI_CAPABILITIES:
            seen.add((entry.provider, entry.model))
            continue
        rows.append({
            "供应商": entry.provider,
            "模型 ID": entry.model,
            "展示名": entry.display_name,
            "能力类型": entry.capability,
            "支持端点": entry.endpoint_type,
            "价格信息": entry.price or "待确认",
            "是否适合九宫格": entry.nine_grid_fit or "待确认",
            "建议状态": entry.status,
            "来源": entry.source,
        })
        seen.add((entry.provider, entry.model))
    for provider, result in api_results.items():
        for model in result.get("models") or []:
            if (provider, model) in seen:
                continue
            row = row_for_model(provider, model, source="/v1/models")
            seen.add((row["供应商"], row["模型 ID"]))
            if row["建议状态"] not in VISIBLE_REPORT_STATUSES:
                continue
            rows.append(row)
    for item in pricing_models:
        provider = item.get("provider") or "Aitgenne"
        model = item.get("model") or ""
        if not model or (provider, model) in seen:
            continue
        row = row_for_model(provider, model, source=item.get("source") or "官网模型广场", price=item.get("price") or "")
        row["展示名"] = item.get("display_name") or row["展示名"]
        row["支持端点"] = item.get("endpoint_type") or row["支持端点"]
        if row["建议状态"] not in VISIBLE_REPORT_STATUSES:
            continue
        rows.append(row)
    rows.sort(key=lambda row: (row["供应商"], row["能力类型"], row["建议状态"], row["模型 ID"]))
    return rows


def markdown_table(rows: List[Dict[str, str]]) -> str:
    headers = ["供应商", "模型 ID", "展示名", "能力类型", "支持端点", "价格信息", "是否适合九宫格", "建议状态", "来源"]
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(header, "")).replace("|", "\\|") for header in headers) + " |")
    return "\n".join(lines)


def write_candidate_report(
    api_results: Dict[str, Dict[str, Any]],
    pricing_models: Iterable[Dict[str, str]],
    *,
    output_path: Path,
) -> str:
    rows = build_candidate_rows(api_results, pricing_models)
    report = [
        "# AI 模型候选清单",
        "",
        f"生成日期：{date.today().isoformat()}",
        "",
        "说明：本报告只读生成，不写飞书、不调用生成模型、不输出密钥。",
        "",
        "## 拉取状态",
    ]
    for provider, result in api_results.items():
        error = redact_secret(result.get("error") or "")
        count = len(result.get("models") or [])
        endpoint = result.get("endpoint") or ""
        report.append(f"- {provider}: {count} models, endpoint={endpoint}, error={error or '无'}")
    report.extend(["", "## 候选模型", "", markdown_table(rows), ""])
    text = "\n".join(report)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text, encoding="utf-8")
    return text


def collect_api_results() -> Dict[str, Dict[str, Any]]:
    results = {}
    for provider, info in PROVIDERS.items():
        api_key = os.environ.get(info["api_key_env"], "").strip()
        base_url = os.environ.get(f"{provider.upper()}_API_BASE", "").strip() or info["base_url"]
        results[provider] = fetch_provider_models(provider, api_key=api_key, base_url=base_url)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="只读生成全局 AI 模型候选报告")
    parser.add_argument("--output", default=f"docs/tk-pipeline/ai-model-catalog-candidates-{date.today().isoformat()}.md")
    parser.add_argument("--no-fetch", action="store_true", help="只使用本地 catalog 和人工录入模型，不访问供应商接口")
    args = parser.parse_args()

    if args.no_fetch:
        api_results = {provider: {"models": [], "error": "跳过 /v1/models 拉取", "endpoint": ""} for provider in PROVIDERS}
    else:
        api_results = collect_api_results()
    write_candidate_report(api_results, AITGENNE_PRICING_SEEDS, output_path=Path(args.output))
    print(json.dumps({"output": args.output, "providers": list(api_results)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
