#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import time
from typing import Any, Dict, Iterable, List, Optional, Sequence

import requests

import ai_model_catalog
import ai_routing


CONFIG_PRESET_PREFIX = "统一AI预设"

DEFAULT_PROVIDER_BASES = {
    "AIHubMix": {
        "文本": "https://aihubmix.com/gemini",
        "图片": "https://aihubmix.com",
        "视频": "https://aihubmix.com",
    },
    "Aitgenne": {
        "文本": "https://api.aitgenne.com",
        "图片": "https://api.aitgenne.com",
        "视频": "https://api.aitgenne.com",
    },
    "OTU": {
        "图片": "https://otuapi.com",
        "视频": "https://otuapi.com",
    },
}

DEFAULT_TASK_BY_CAPABILITY = {
    "文本": "脚本生成",
    "图片": "图生图/参考图重绘",
    "视频": "首帧图生视频",
    "语音": "TTS",
}

DEFAULT_PARAMS_BY_CAPABILITY = {
    "文本": {},
    "图片": {"size": "720x1280", "aspect_ratio": "9:16"},
    "视频": {"size": "720x1280", "aspect_ratio": "9:16", "seconds": "8"},
    "语音": {},
}


@dataclass(frozen=True)
class FieldOptionUpdate:
    table_key: str
    table_id: str
    field_name: str
    options: List[Dict[str, str]]


def load_config(path: Path) -> Dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def provider_base(entry: ai_model_catalog.ModelCatalogEntry) -> str:
    return (DEFAULT_PROVIDER_BASES.get(entry.provider) or {}).get(entry.capability, "")


def default_task(entry: ai_model_catalog.ModelCatalogEntry) -> str:
    return DEFAULT_TASK_BY_CAPABILITY.get(entry.capability, entry.capability)


def default_params(entry: ai_model_catalog.ModelCatalogEntry) -> Dict[str, str]:
    params = dict(DEFAULT_PARAMS_BY_CAPABILITY.get(entry.capability, {}))
    if entry.provider == "OTU" and entry.capability == "图片":
        if entry.model.endswith("-2K"):
            params["size"] = "1080x1920"
        elif entry.model.endswith("-4K"):
            params["size"] = "1440x2560"
    return params


def default_call_type(entry: ai_model_catalog.ModelCatalogEntry) -> str:
    if entry.call_types:
        return entry.call_types[0]
    return entry.endpoint_type


def build_config_presets(entries: Optional[Sequence[ai_model_catalog.ModelCatalogEntry]] = None) -> List[Dict[str, Any]]:
    presets = []
    source_entries = entries or [
        entry for entry in ai_model_catalog.production_models()
        if entry.capability in ai_model_catalog.UNIFIED_AI_CAPABILITIES
    ]
    for entry in source_entries:
        params = default_params(entry)
        notes = [
            "统一 AI 模型 Catalog 预设；不复制密钥，真实调用复用正式环节密钥。",
            f"source={entry.source}",
        ]
        if entry.notes:
            notes.append(entry.notes)
        if entry.nine_grid_fit:
            notes.append(f"fit={entry.nine_grid_fit}")
        fields = {
            "环节": f"{CONFIG_PRESET_PREFIX}-{entry.display_name}",
            "模型名称": entry.display_name,
            "AI供应商": entry.provider,
            "AI能力类型": entry.capability,
            "AI任务类型": default_task(entry),
            "AI参数JSON": json.dumps(params, ensure_ascii=False, sort_keys=True),
            "API 代理地址": provider_base(entry),
            "调用方式": default_call_type(entry),
            "状态": "启用",
            "备注": "；".join(notes),
        }
        presets.append({"key": entry.display_name, "fields": fields})
    return presets


def build_field_option_updates(config: Dict[str, Any]) -> List[FieldOptionUpdate]:
    tables = ((config.get("feishu") or {}).get("tables") or {})
    target_specs = [
        ("nine_grid_video", "方案AI模型", ai_model_catalog.TEXT_MODEL_OPTIONS),
        ("nine_grid_video", "图片AI模型", ai_model_catalog.IMAGE_MODEL_OPTIONS),
        ("nine_grid_video", "视频AI模型", ai_model_catalog.VIDEO_AI_MODEL_OPTIONS),
        ("storyboard_video", "拆分AI模型", ai_model_catalog.TEXT_MODEL_OPTIONS),
        ("storyboard_video", "故事板图片AI模型", ai_model_catalog.IMAGE_MODEL_OPTIONS),
        ("storyboard_video", "视频AI模型", ai_model_catalog.VIDEO_AI_MODEL_OPTIONS),
        ("first_last_video", "拆分AI模型", ai_model_catalog.TEXT_MODEL_OPTIONS),
        ("first_last_video", "首帧图AI模型", ai_model_catalog.IMAGE_MODEL_OPTIONS),
        ("first_last_video", "尾帧图AI模型", ai_model_catalog.IMAGE_MODEL_OPTIONS),
        ("first_last_video", "视频AI模型", ai_model_catalog.VIDEO_AI_MODEL_OPTIONS),
        ("first_last_video", "视频生成模型", ai_model_catalog.VIDEO_MODEL_OPTIONS),
        ("script_doc_tasks", "解析AI模型", ai_model_catalog.TEXT_MODEL_OPTIONS),
        ("script_doc_tasks", "分镜图AI模型", ai_model_catalog.IMAGE_MODEL_OPTIONS),
        ("script_doc_tasks", "尾帧图AI模型", ai_model_catalog.IMAGE_MODEL_OPTIONS),
        ("script_doc_tasks", "视频AI模型", ai_model_catalog.VIDEO_AI_MODEL_OPTIONS),
        ("script_doc_shots", "分镜图AI模型", ai_model_catalog.IMAGE_MODEL_OPTIONS),
        ("script_doc_shots", "尾帧图AI模型", ai_model_catalog.IMAGE_MODEL_OPTIONS),
        ("script_doc_shots", "视频AI模型", ai_model_catalog.VIDEO_AI_MODEL_OPTIONS),
        ("script_doc_shots", "视频生成模型", ai_model_catalog.VIDEO_MODEL_OPTIONS),
        ("multi_role_first_last", "拆解AI模型", ai_model_catalog.TEXT_MODEL_OPTIONS),
        ("multi_role_first_last", "参考图AI模型", ai_model_catalog.IMAGE_MODEL_OPTIONS),
        ("multi_role_first_last", "关键帧AI模型", ai_model_catalog.IMAGE_MODEL_OPTIONS),
        ("multi_role_first_last", "视频AI模型", ai_model_catalog.VIDEO_AI_MODEL_OPTIONS),
        ("multi_role_first_last", "视频生成模型", ai_model_catalog.VIDEO_MODEL_OPTIONS),
    ]
    updates: List[FieldOptionUpdate] = []
    for table_key, field_name, options in target_specs:
        table_id = tables.get(table_key)
        if not table_id:
            continue
        updates.append(FieldOptionUpdate(
            table_key=table_key,
            table_id=table_id,
            field_name=field_name,
            options=[dict(item) for item in options],
        ))
    return updates


def build_dry_run_matrix(
    *,
    include_candidates: bool = False,
    api_key: str = "sk-redacted",
) -> List[Dict[str, Any]]:
    statuses = ai_model_catalog.INSPECTABLE_STATUSES if include_candidates else ai_model_catalog.PRODUCTION_STATUSES
    entries = [
        entry for entry in ai_model_catalog.catalog_entries(statuses)
        if entry.capability in {"图片", "视频"}
    ]
    summaries: List[Dict[str, Any]] = []
    for entry in entries:
        params = default_params(entry)
        route = ai_routing.AiRoute(
            provider=entry.provider,
            capability=entry.capability,
            task_type=default_task(entry),
            model=entry.display_name,
            call_type=default_call_type(entry),
            api_base=provider_base(entry),
            api_key=api_key,
            params=params,
        )
        reference_count = 1 if entry.capability == "图片" else 2
        if entry.status in ai_model_catalog.PRODUCTION_STATUSES:
            summary = ai_routing.build_media_request_summary(route, "dry-run prompt", reference_count=reference_count)
        else:
            summary = build_candidate_media_summary(route, "dry-run prompt", reference_count=reference_count)
        if summary.get("api_key"):
            summary["api_key"] = "[REDACTED]"
        summary["display_name"] = entry.display_name
        summary["status"] = entry.status
        summaries.append(summary)
    return summaries


def build_candidate_media_summary(route: ai_routing.AiRoute, prompt: str, *, reference_count: int = 0) -> Dict[str, Any]:
    model_name = ai_routing.parse_model_display(route.model)["model"] or route.model
    params = dict(route.params or {})
    payload: Dict[str, Any] = {"model": model_name, "prompt": prompt}
    if route.capability == "图片":
        payload["size"] = params.get("size") or "1024x1024"
        payload["metadata"] = {"aspectRatio": params.get("aspect_ratio") or "9:16"}
        if reference_count:
            payload["input_mode"] = "image-to-image"
    else:
        payload["size"] = params.get("size") or "720x1280"
        payload["seconds"] = str(params.get("seconds") or "8")
        payload["aspect_ratio"] = params.get("aspect_ratio") or "9:16"
    return ai_routing.redact_secret({
        "provider": route.provider,
        "capability": route.capability,
        "task_type": route.task_type,
        "endpoint": ai_routing.media_endpoint(route),
        "method": "POST",
        "payload_keys": sorted(payload.keys()),
        "payload": payload,
        "reference_count": int(reference_count or 0),
        "api_key": route.api_key,
    })


def render_dry_run_report(summaries: Sequence[Dict[str, Any]]) -> str:
    lines = [
        "# AI 模型 dry-run 路由摘要",
        "",
        f"- 生成时间: {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 模型数量: {len(summaries)}",
        "- 说明: 只构造请求摘要，不调用生成模型，不输出密钥。",
        "",
    ]
    for item in summaries:
        payload = item.get("payload") or {}
        lines.extend([
            f"## {item.get('display_name')}",
            "",
            f"- capability: {item.get('capability')}",
            f"- status: {item.get('status')}",
            f"- endpoint: `{item.get('endpoint')}`",
            f"- payload_keys: `{', '.join(item.get('payload_keys') or [])}`",
            f"- size: `{payload.get('size', '')}`",
            f"- aspect_ratio: `{payload.get('aspect_ratio') or (payload.get('metadata') or {}).get('aspectRatio') or ''}`",
            f"- seconds: `{payload.get('seconds', '')}`",
            f"- reference_count: `{item.get('reference_count')}`",
            "",
        ])
    return "\n".join(lines).rstrip() + "\n"


def redacted_json(data: Any) -> str:
    return json.dumps(ai_routing.redact_secret(data), ensure_ascii=False, indent=2, sort_keys=True)


def run_json(argv: Sequence[str]) -> Dict[str, Any]:
    proc = subprocess.run(argv, check=False, text=True, capture_output=True)
    output = (proc.stdout or "").strip()
    if proc.returncode != 0:
        data = _json_from_command_output(output) or _json_from_command_output(proc.stderr or "") or {}
        error = data.get("error") if isinstance(data, dict) else {}
        if isinstance(error, dict) and (error.get("code") == 800070003 or error.get("message") == "no operation produced"):
            return {"ok": True, "noop": True, "raw": data}
        raise RuntimeError(f"command failed: {' '.join(argv[:3])} ...\n{proc.stderr or proc.stdout}")
    return json.loads(output) if output else {}


def _json_from_command_output(text: str) -> Dict[str, Any]:
    text = (text or "").strip()
    if not text:
        return {}
    candidates = [text]
    brace = text.find("{")
    if brace > 0:
        candidates.append(text[brace:])
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        return data if isinstance(data, dict) else {}
    return {}


def field_name(item: Dict[str, Any]) -> str:
    return item.get("name") or item.get("field_name") or ""


def field_id(item: Dict[str, Any]) -> str:
    return item.get("id") or item.get("field_id") or ""


def list_field_items(base_token: str, table_id: str) -> List[Dict[str, Any]]:
    data = run_json([
        "lark-cli", "base", "+field-list",
        "--base-token", base_token,
        "--table-id", table_id,
        "--limit", "200",
    ])
    raw = data.get("data", {})
    return raw.get("items") or raw.get("fields") or []


def select_field_payload(name: str, options: Sequence[Dict[str, str]]) -> Dict[str, Any]:
    return {"name": name, "type": "select", "multiple": False, "options": list(options)}


def write_field_options(base_token: str, update: FieldOptionUpdate, field_item: Dict[str, Any]) -> None:
    fid = field_id(field_item)
    if not fid:
        raise RuntimeError(f"字段缺少 field_id: table={update.table_key}, field={update.field_name}")
    argv = [
        "lark-cli", "base", "+field-update",
        "--base-token", base_token,
        "--table-id", update.table_id,
        "--field-id", fid,
        "--json", json.dumps(select_field_payload(update.field_name, update.options), ensure_ascii=False),
        "--yes",
    ]
    for attempt in range(5):
        try:
            run_json(argv)
            return
        except RuntimeError as exc:
            if "800004135" not in str(exc) or attempt == 4:
                raise
            time.sleep(2 + attempt * 2)


def create_select_field(base_token: str, update: FieldOptionUpdate) -> None:
    run_json([
        "lark-cli", "base", "+field-create",
        "--base-token", base_token,
        "--table-id", update.table_id,
        "--json", json.dumps(select_field_payload(update.field_name, update.options), ensure_ascii=False),
    ])


def backup_target_fields(base_token: str, updates: Sequence[FieldOptionUpdate]) -> List[Dict[str, Any]]:
    by_table: Dict[str, List[FieldOptionUpdate]] = {}
    for update in updates:
        by_table.setdefault(update.table_id, []).append(update)
    backups = []
    for table_id, table_updates in by_table.items():
        items = list_field_items(base_token, table_id)
        wanted = {item.field_name for item in table_updates}
        backups.append({
            "table_key": table_updates[0].table_key,
            "table_id": table_id,
            "fields": [item for item in items if field_name(item) in wanted],
        })
    return backups


def apply_field_option_updates(base_token: str, updates: Sequence[FieldOptionUpdate], *, dry_run: bool) -> List[Dict[str, Any]]:
    results = []
    by_table: Dict[str, List[FieldOptionUpdate]] = {}
    for update in updates:
        by_table.setdefault(update.table_id, []).append(update)
    for table_id, table_updates in by_table.items():
        items = list_field_items(base_token, table_id)
        by_name = {field_name(item): item for item in items}
        for update in table_updates:
            existing = by_name.get(update.field_name)
            if not existing:
                status = "would_create_field" if dry_run else "created_field"
                if not dry_run:
                    create_select_field(base_token, update)
            else:
                status = "dry_run" if dry_run else "updated"
                if not dry_run:
                    write_field_options(base_token, update, existing)
            results.append({
                "table_key": update.table_key,
                "table_id": update.table_id,
                "field_name": update.field_name,
                "option_count": len(update.options),
                "status": status,
            })
    return results


def feishu_headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def request_json(method: str, url: str, token: str, **kwargs: Any) -> Dict[str, Any]:
    resp = requests.request(method, url, headers=feishu_headers(token), timeout=30, **kwargs)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"Feishu API error code={data.get('code')} msg={data.get('msg')}")
    return data


def get_feishu_token(config: Dict[str, Any]) -> str:
    feishu = config["feishu"]
    resp = requests.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": feishu["app_id"], "app_secret": feishu["app_secret"]},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    token = data.get("tenant_access_token")
    if not token:
        raise RuntimeError(f"获取飞书 token 失败: {ai_routing.redact_secret(data)}")
    return token


def list_records(token: str, app_token: str, table_id: str, page_size: int = 100) -> List[Dict[str, Any]]:
    records = []
    page_token = ""
    while True:
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records?page_size={page_size}"
        if page_token:
            url += f"&page_token={page_token}"
        data = request_json("get", url, token)
        records.extend((data.get("data") or {}).get("items") or [])
        if not (data.get("data") or {}).get("has_more"):
            return records
        page_token = (data.get("data") or {}).get("page_token") or ""


def list_api_fields(token: str, app_token: str, table_id: str) -> List[Dict[str, Any]]:
    fields = []
    page_token = ""
    while True:
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields?page_size=100"
        if page_token:
            url += f"&page_token={page_token}"
        data = request_json("get", url, token)
        fields.extend((data.get("data") or {}).get("items") or [])
        if not (data.get("data") or {}).get("has_more"):
            return fields
        page_token = (data.get("data") or {}).get("page_token") or ""


def existing_field_names(token: str, app_token: str, table_id: str) -> set[str]:
    return {field_name(item) for item in list_api_fields(token, app_token, table_id)}


def filter_existing_fields(fields: Dict[str, Any], allowed_names: Iterable[str]) -> Dict[str, Any]:
    allowed = set(allowed_names)
    return {name: value for name, value in fields.items() if name in allowed}


def upsert_config_presets(
    token: str,
    app_token: str,
    table_id: str,
    presets: Sequence[Dict[str, Any]],
    *,
    dry_run: bool,
) -> List[Dict[str, Any]]:
    allowed_names = existing_field_names(token, app_token, table_id)
    records = list_records(token, app_token, table_id)
    by_stage = {
        ai_routing._norm((record.get("fields") or {}).get("环节")): record
        for record in records
    }
    results = []
    for preset in presets:
        desired = filter_existing_fields(preset["fields"], allowed_names)
        stage = ai_routing._norm(desired.get("环节"))
        existing = by_stage.get(stage)
        action = "update" if existing else "create"
        if not dry_run:
            if existing:
                url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/{existing['record_id']}"
                request_json("put", url, token, json={"fields": desired})
            else:
                url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
                request_json("post", url, token, json={"fields": desired})
        results.append({
            "stage": stage,
            "model": preset["key"],
            "action": "dry_run_" + action if dry_run else action,
            "field_count": len(desired),
        })
    return results


def read_back_field_options(base_token: str, updates: Sequence[FieldOptionUpdate]) -> List[Dict[str, Any]]:
    results = []
    by_table: Dict[str, List[FieldOptionUpdate]] = {}
    for update in updates:
        by_table.setdefault(update.table_id, []).append(update)
    for table_id, table_updates in by_table.items():
        items = list_field_items(base_token, table_id)
        by_name = {field_name(item): item for item in items}
        for update in table_updates:
            item = by_name.get(update.field_name) or {}
            options = item.get("options") or ((item.get("property") or {}).get("options")) or []
            names = [opt.get("name") for opt in options if isinstance(opt, dict)]
            expected = [opt["name"] for opt in update.options]
            results.append({
                "table_key": update.table_key,
                "field_name": update.field_name,
                "matches": names == expected,
                "option_count": len(names),
            })
    return results


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> None:
    today = dt.date.today().isoformat()
    parser = argparse.ArgumentParser(description="Sync enabled AI model catalog options to Feishu without touching business records")
    parser.add_argument("--config", default=str(Path(__file__).resolve().parent / "config.json"))
    parser.add_argument("--write", action="store_true", help="Apply Feishu config preset and field option updates")
    parser.add_argument("--skip-config-presets", action="store_true")
    parser.add_argument("--skip-field-options", action="store_true")
    parser.add_argument("--include-candidates-in-dry-run", action="store_true")
    parser.add_argument("--backup-output", default=f"docs/tk-pipeline/ai-model-field-backup-{today}.json")
    parser.add_argument("--dry-run-report", default=f"docs/tk-pipeline/ai-model-catalog-dry-run-{today}.md")
    args = parser.parse_args()

    config = load_config(Path(args.config))
    app_token = config["feishu"]["bitable_app_token"]
    base_token = app_token
    tables = config["feishu"]["tables"]
    updates = build_field_option_updates(config)
    presets = build_config_presets()
    summaries = build_dry_run_matrix(include_candidates=args.include_candidates_in_dry_run)

    write_text(Path(args.dry_run_report), render_dry_run_report(summaries))

    output: Dict[str, Any] = {
        "mode": "write" if args.write else "dry_run",
        "config_preset_count": 0 if args.skip_config_presets else len(presets),
        "field_update_count": 0 if args.skip_field_options else len(updates),
        "dry_run_report": args.dry_run_report,
    }

    if not args.skip_config_presets or not args.skip_field_options:
        token = get_feishu_token(config)
    else:
        token = ""

    if args.write and not args.skip_field_options:
        backup = backup_target_fields(base_token, updates)
        backup_payload = {"generated_at": dt.datetime.now().isoformat(timespec="seconds"), "tables": backup}
        write_text(Path(args.backup_output), redacted_json(backup_payload) + "\n")
        output["backup_output"] = args.backup_output

    if not args.skip_config_presets:
        config_table_id = tables.get("config", "")
        if config_table_id:
            output["config_presets"] = upsert_config_presets(
                token,
                app_token,
                config_table_id,
                presets,
                dry_run=not args.write,
            )

    if not args.skip_field_options:
        output["field_options"] = apply_field_option_updates(base_token, updates, dry_run=not args.write)
        if args.write:
            output["field_read_back"] = read_back_field_options(base_token, updates)

    print(redacted_json(output))


if __name__ == "__main__":
    main()
