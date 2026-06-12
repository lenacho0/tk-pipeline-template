#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence
from urllib.parse import urlencode, urlparse

import requests
from media_specs import adapt_image_metadata, media_spec_from_values

import ai_model_catalog
from common import extract_text


ROUTE_SWITCH_STAGE = "统一AI路由启用状态"
ROUTE_MODE_OFF = "关闭"
ROUTE_MODE_DRY_RUN = "仅dry-run"
ROUTE_MODE_RECORDS = "指定记录启用"
ROUTE_MODE_ALL = "全量启用"

AI_ROUTE_SWITCH_FIELD = "使用统一AI路由"
AI_PROVIDER_FIELD = "AI供应商"
AI_CAPABILITY_FIELD = "AI能力类型"
AI_TASK_TYPE_FIELD = "AI任务类型"
AI_MODEL_FIELD = "AI模型"
AI_PARAMS_FIELD = "AI参数JSON"
TEXT_MODEL_FIELD = "文本AI模型"
AI_SLOT_MODEL_SUFFIX = "AI模型"
AI_SLOT_PARAMS_SUFFIX = "AI参数JSON"
TEXT_SLOT_LEGACY_MODEL_FIELDS = {
    "方案": ("方案AI模型",),
    "拆分": ("拆分AI模型",),
    "解析": ("解析AI模型",),
    "拆解": ("拆解AI模型",),
}

YES_VALUES = {"是", "yes", "true", "1", "启用", "开启", "使用"}
NO_VALUES = {"否", "no", "false", "0", "关闭", "不使用", ""}
PROVIDER_API_BASE_MARKERS = {
    "AIHubMix": "aihubmix",
    "Aitgenne": "aitgenne",
    "OTU": "otuapi",
}
AITGENNE_UNIFIED_VIDEO_MODELS = {
    "omni-flash",
    "veo_3_1_lite_vip",
    "veo_3_1_fast_vip",
    "veo_3_1_vip",
    "veo_3_1_components_vip",
}
AITGENNE_COMPONENTS_VIDEO_MODELS = {"veo_3_1_components_vip"}


@dataclass
class AiRoute:
    provider: str
    capability: str
    task_type: str
    model: str
    call_type: str = ""
    api_base: str = ""
    api_key: str = ""
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TextModelResult:
    text: str
    raw_response: Dict[str, Any]
    endpoint: str
    provider: str
    model: str


def _norm(value: Any) -> str:
    return extract_text(value).strip()


def _compact(value: Any) -> str:
    return _norm(value).lower().replace("_", "-").replace(" ", "")


def parse_model_display(value: Any) -> Dict[str, str]:
    raw = _norm(value)
    if " / " in raw:
        provider, model = raw.split(" / ", 1)
        return {"provider": provider.strip(), "model": model.strip()}
    return {"provider": "", "model": raw}


def route_switch_mode(config_records: Iterable[Dict[str, Any]]) -> str:
    for rec in config_records or []:
        fields = rec.get("fields") if isinstance(rec, dict) else {}
        if _norm(fields.get("环节")) != ROUTE_SWITCH_STAGE:
            continue
        status = _norm(fields.get("模型名称") or fields.get("状态") or fields.get("备注"))
        if status in {ROUTE_MODE_DRY_RUN, ROUTE_MODE_RECORDS, ROUTE_MODE_ALL}:
            return status
        return ROUTE_MODE_OFF
    return ROUTE_MODE_OFF


def record_wants_unified_route(fields: Dict[str, Any]) -> bool:
    raw = _compact(fields.get(AI_ROUTE_SWITCH_FIELD))
    if raw in YES_VALUES:
        return True
    if raw in NO_VALUES:
        return False
    return False


def unified_route_enabled(fields: Dict[str, Any], config_records: Iterable[Dict[str, Any]]) -> bool:
    mode = route_switch_mode(config_records)
    if mode == ROUTE_MODE_OFF:
        return False
    if mode == ROUTE_MODE_ALL:
        return True
    if mode in {ROUTE_MODE_DRY_RUN, ROUTE_MODE_RECORDS}:
        return record_wants_unified_route(fields)
    return False


def unified_route_dry_run_only(config_records: Iterable[Dict[str, Any]]) -> bool:
    return route_switch_mode(config_records) == ROUTE_MODE_DRY_RUN


def _matching_catalog_entry(route: AiRoute) -> Optional[ai_model_catalog.AiModelCatalogEntry]:
    model_bits = parse_model_display(route.model)
    provider = model_bits["provider"] or route.provider
    model = model_bits["model"]
    return ai_model_catalog.find_model(provider, route.capability, model)


def validate_route(route: AiRoute) -> AiRoute:
    model_bits = parse_model_display(route.model)
    if model_bits["provider"] and model_bits["provider"] != route.provider:
        raise ValueError(f"AI模型供应商不匹配: AI供应商={route.provider}, AI模型={route.model}")
    entry = _matching_catalog_entry(route)
    if not entry:
        raise ValueError(f"AI模型不支持当前能力: provider={route.provider}, capability={route.capability}, model={route.model}")
    if route.call_type and entry.call_types and route.call_type not in entry.call_types:
        raise ValueError(f"调用方式不支持当前模型: {route.call_type}")
    return route


def _parse_params_json(raw: Any, *, field_name: str) -> Dict[str, Any]:
    params_text = _norm(raw)
    if not params_text:
        return {}
    try:
        parsed_params = json.loads(params_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field_name} 不是合法 JSON: {exc}") from exc
    if not isinstance(parsed_params, dict):
        raise ValueError(f"{field_name} 顶层必须是对象")
    return parsed_params


def _config_params(config: Dict[str, Any]) -> Dict[str, Any]:
    raw_params = config.get("params")
    if isinstance(raw_params, dict):
        return dict(raw_params)
    if raw_params:
        return _parse_params_json(raw_params, field_name="配置参数JSON")
    return _parse_params_json(config.get(AI_PARAMS_FIELD), field_name=AI_PARAMS_FIELD)


def config_record_matches_provider(fields: Dict[str, Any], provider: str) -> bool:
    provider_text = _norm(fields.get(AI_PROVIDER_FIELD) or fields.get("供应商"))
    if provider_text == provider:
        return True
    marker = PROVIDER_API_BASE_MARKERS.get(provider, "").lower()
    api_base = _norm(fields.get("API 代理地址") or fields.get("api_base")).lower()
    return bool(marker and marker in api_base)


def api_base_matches_provider(api_base: str, provider: str) -> bool:
    marker = PROVIDER_API_BASE_MARKERS.get(provider, "").lower()
    if not marker:
        return True
    return marker in _norm(api_base).lower()


def config_record_matches_model(fields: Dict[str, Any], provider: str, display_model: str) -> bool:
    requested = parse_model_display(display_model)
    requested_provider = requested["provider"] or provider
    requested_model = requested["model"] or _norm(display_model)
    if not requested_model:
        return False
    field_provider = _norm(fields.get(AI_PROVIDER_FIELD) or fields.get("供应商"))
    for field_name in ("模型名称", "默认模型", AI_MODEL_FIELD, "model"):
        raw = _norm(fields.get(field_name))
        if not raw:
            continue
        candidate = parse_model_display(raw)
        candidate_provider = candidate["provider"] or field_provider
        candidate_model = candidate["model"] or raw
        if candidate_model != requested_model:
            continue
        if requested_provider and candidate_provider and candidate_provider != requested_provider:
            continue
        return True
    return False


def config_record_for_model(
    config_records: Iterable[Dict[str, Any]],
    provider: str,
    display_model: str,
) -> Optional[Dict[str, Any]]:
    matches: List[Dict[str, Any]] = []
    for rec in config_records or []:
        fields = rec.get("fields") if isinstance(rec, dict) else {}
        if not isinstance(fields, dict):
            continue
        if config_record_matches_model(fields, provider, display_model):
            matches.append(fields)
    if not matches:
        return None
    api_config_matches = [
        fields for fields in matches
        if _norm(fields.get("配置类型")) in {"", "运行环节", "模型目录"}
    ]
    if not api_config_matches:
        return None

    def priority(fields: Dict[str, Any]) -> tuple[int, int, int]:
        active = _norm(fields.get("状态")) != "停用"
        has_key = bool(_norm(fields.get("API Key") or fields.get("api_key")))
        config_type = _norm(fields.get("配置类型"))
        is_runtime = config_type == "运行环节"
        is_catalog = config_type == "模型目录"
        if active and is_runtime and has_key:
            return (0, 0, 0)
        if active and has_key:
            return (1, 0 if is_catalog else 1, 0)
        if active and is_runtime:
            return (2, 0, 0)
        if is_runtime:
            return (3, 0, 0)
        return (4, 0 if active else 1, 0 if has_key else 1)

    return min(api_config_matches, key=priority)


def exact_model_runtime_config(
    config_records: Iterable[Dict[str, Any]],
    provider: str,
    display_model: str,
    *,
    require_api_key: bool = True,
) -> Dict[str, str]:
    fields = config_record_for_model(config_records, provider, display_model)
    if not fields:
        raise ValueError(f"模型配置缺失或停用: {display_model}")
    cfg = {
        "model": _norm(fields.get("模型名称") or fields.get("默认模型") or fields.get(AI_MODEL_FIELD) or fields.get("model")) or display_model,
        "provider": _norm(fields.get(AI_PROVIDER_FIELD) or fields.get("供应商")) or provider,
        "api_key": _norm(fields.get("API Key") or fields.get("api_key")),
        "api_base": _norm(fields.get("API 代理地址") or fields.get("api_base")),
        "call_type": _norm(fields.get("调用方式") or fields.get("call_type")),
        "params": _norm(fields.get(AI_PARAMS_FIELD) or fields.get("AI参数JSON") or fields.get("params")),
    }
    if require_api_key and not cfg["api_key"]:
        raise ValueError(f"模型配置缺少 API Key: {display_model}")
    return cfg


def api_key_for_provider(config_records: Iterable[Dict[str, Any]], provider: str) -> str:
    for rec in config_records or []:
        fields = rec.get("fields") if isinstance(rec, dict) else {}
        if not isinstance(fields, dict):
            continue
        if not config_record_matches_provider(fields, provider):
            continue
        api_key = _norm(fields.get("API Key") or fields.get("api_key"))
        if api_key:
            return api_key
    return ""


def api_base_for_provider(config_records: Iterable[Dict[str, Any]], provider: str) -> str:
    for rec in config_records or []:
        fields = rec.get("fields") if isinstance(rec, dict) else {}
        if not isinstance(fields, dict):
            continue
        if not config_record_matches_provider(fields, provider):
            continue
        api_base = _norm(fields.get("API 代理地址") or fields.get("api_base"))
        if api_base:
            return api_base
    return ""


def route_from_record(
    fields: Dict[str, Any],
    config: Optional[Dict[str, str]] = None,
    *,
    config_records: Optional[Iterable[Dict[str, Any]]] = None,
) -> AiRoute:
    config = config or {}
    capability = _norm(fields.get(AI_CAPABILITY_FIELD)) or _norm(config.get("capability")) or "文本"
    explicit_model = _norm(fields.get(AI_MODEL_FIELD))
    if capability == "文本" and not explicit_model:
        explicit_model = _norm(fields.get(TEXT_MODEL_FIELD))
    raw_model = explicit_model or _norm(config.get("model"))
    model_bits = parse_model_display(raw_model)
    provider = model_bits["provider"] or _norm(fields.get(AI_PROVIDER_FIELD)) or _norm(config.get("provider"))
    task_type = _norm(fields.get(AI_TASK_TYPE_FIELD)) or _norm(config.get("task_type"))
    model = raw_model
    call_type = "" if explicit_model else _norm(config.get("call_type") or config.get("调用方式"))
    if capability == "文本" and (not call_type or explicit_model):
        catalog_entry = ai_model_catalog.find_model(provider, capability, parse_model_display(model)["model"] or model)
        if catalog_entry and catalog_entry.call_types:
            call_type = catalog_entry.call_types[0]
        else:
            call_type = "Gemini 原生 SDK" if "gemini" in model.lower() and provider == "AIHubMix" else "OpenAI兼容 chat/completions"
    params: Dict[str, Any] = _config_params(config)
    params.update(_parse_params_json(fields.get(AI_PARAMS_FIELD), field_name=AI_PARAMS_FIELD))
    config_provider = _norm(config.get("provider"))
    api_base = _norm(config.get("api_base"))
    api_key = _norm(config.get("api_key"))
    provider_config_records = list(config_records or [])
    exact_model_config_preferred = explicit_model and provider == "Aitgenne" and capability in {"文本", "视频"}
    exact_fields = config_record_for_model(provider_config_records, provider, explicit_model) if exact_model_config_preferred else None
    if exact_fields:
        api_base = _norm(exact_fields.get("API 代理地址") or exact_fields.get("api_base")) or api_base
        api_key = _norm(exact_fields.get("API Key") or exact_fields.get("api_key"))
    elif exact_model_config_preferred and capability == "视频" and not config_record_matches_model({"模型名称": config.get("model"), "供应商": config_provider}, provider, explicit_model):
        api_key = ""
    elif explicit_model and (
        (config_provider and config_provider != provider)
        or (api_base and not api_base_matches_provider(api_base, provider))
    ):
        api_base = ""
        api_key = ""
        api_base = api_base_for_provider(provider_config_records, provider)
        api_key = api_key_for_provider(provider_config_records, provider)
    elif explicit_model and not api_key:
        api_key = api_key_for_provider(provider_config_records, provider)
    if explicit_model and not api_base:
        api_base = api_base_for_provider(provider_config_records, provider)
    return validate_route(AiRoute(
        provider=provider,
        capability=capability,
        task_type=task_type,
        model=model,
        call_type=call_type,
        api_base=api_base,
        api_key=api_key,
        params=params,
    ))


def slot_model_field(slot_name: str) -> str:
    return f"{slot_name}{AI_SLOT_MODEL_SUFFIX}"


def slot_params_field(slot_name: str) -> str:
    return f"{slot_name}{AI_SLOT_PARAMS_SUFFIX}"


def text_slot_model_value(fields: Dict[str, Any], slot_name: str) -> str:
    unified = _norm(fields.get(TEXT_MODEL_FIELD))
    if unified:
        return unified
    legacy_names = (*TEXT_SLOT_LEGACY_MODEL_FIELDS.get(slot_name, ()), slot_model_field(slot_name))
    for name in legacy_names:
        value = _norm(fields.get(name))
        if value:
            return value
    return ""


def route_from_slot(
    fields: Dict[str, Any],
    slot_name: str,
    config: Optional[Dict[str, Any]] = None,
    *,
    capability: str,
    task_type: str,
    config_records: Optional[Iterable[Dict[str, Any]]] = None,
) -> AiRoute:
    """Build a route from a task-specific model slot, falling back to legacy fields."""
    config = dict(config or {})
    config["capability"] = capability
    config["task_type"] = task_type
    model_field = slot_model_field(slot_name)
    params_field = slot_params_field(slot_name)
    slot_model = text_slot_model_value(fields, slot_name) if capability == "文本" else _norm(fields.get(model_field))
    slot_params = fields.get(params_field)
    legacy_model = _norm(fields.get(AI_MODEL_FIELD))
    legacy_params = fields.get(AI_PARAMS_FIELD)
    route_fields: Dict[str, Any] = {
        AI_CAPABILITY_FIELD: capability,
        AI_TASK_TYPE_FIELD: task_type,
    }
    if slot_model:
        route_fields[AI_MODEL_FIELD] = slot_model
        route_fields[AI_PARAMS_FIELD] = slot_params
    else:
        route_fields[AI_PROVIDER_FIELD] = fields.get(AI_PROVIDER_FIELD)
        route_fields[AI_MODEL_FIELD] = legacy_model
        route_fields[AI_PARAMS_FIELD] = legacy_params
    return route_from_record(route_fields, config, config_records=config_records)


def redact_secret(value: Any) -> Any:
    if isinstance(value, dict):
        redacted = {}
        for k, v in value.items():
            if any(marker in str(k).lower() for marker in ("api_key", "apikey", "secret", "token", "authorization")):
                redacted[k] = "[REDACTED]" if v else v
            else:
                redacted[k] = redact_secret(v)
        return redacted
    if isinstance(value, list):
        return [redact_secret(v) for v in value]
    if isinstance(value, str):
        text = value
        for marker in ("Bearer ", "sk-"):
            if marker in text:
                text = text.replace(marker, marker + "[REDACTED]")
        return text
    return value


def build_dry_run_summary(route: AiRoute, prompt: str) -> Dict[str, Any]:
    model_bits = parse_model_display(route.model)
    model_name = model_bits["model"] or route.model
    endpoint = text_endpoint(route)
    return redact_secret({
        "provider": route.provider,
        "capability": route.capability,
        "task_type": route.task_type,
        "model": model_name,
        "call_type": route.call_type,
        "endpoint": endpoint,
        "prompt_chars": len(prompt or ""),
        "api_key": route.api_key,
    })


def text_endpoint(route: AiRoute) -> str:
    base = (route.api_base or "").strip().rstrip("/")
    if "gemini" in route.call_type.lower():
        return base or "https://aihubmix.com/gemini"
    if not base:
        base = "https://api.aitgenne.com"
    parsed = urlparse(base)
    path = parsed.path.rstrip("/")
    if path.endswith("/chat/completions"):
        return base
    if path.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


def _default_gemini_client_factory(api_key: str, api_base: str) -> Any:
    from google import genai

    return genai.Client(api_key=api_key, http_options={"base_url": api_base})


def _extract_openai_text(data: Dict[str, Any]) -> str:
    choices = data.get("choices") if isinstance(data, dict) else []
    if choices and isinstance(choices[0], dict):
        message = choices[0].get("message") or {}
        if isinstance(message, dict):
            return _norm(message.get("content"))
        return _norm(choices[0].get("text"))
    return _norm(data.get("text") if isinstance(data, dict) else "")


def call_text_model(
    route: AiRoute,
    prompt: str,
    *,
    gemini_client_factory: Optional[Callable[[str, str], Any]] = None,
    post: Optional[Callable[..., Any]] = None,
) -> TextModelResult:
    validate_route(route)
    if route.capability != "文本":
        raise ValueError(f"call_text_model 只支持文本能力，当前={route.capability}")
    if not route.api_key:
        raise ValueError(f"{route.provider} / {route.model} 缺少 API Key")
    model_name = parse_model_display(route.model)["model"] or route.model
    endpoint = text_endpoint(route)
    if "gemini" in route.call_type.lower():
        factory = gemini_client_factory or _default_gemini_client_factory
        client = factory(route.api_key, endpoint)
        response = client.models.generate_content(model=model_name, contents=[prompt])
        text = getattr(response, "text", "") or ""
        return TextModelResult(text=text, raw_response={"text": text}, endpoint=endpoint, provider=route.provider, model=model_name)

    payload = {"model": model_name, "messages": [{"role": "user", "content": prompt}]}
    payload.update(route.params or {})
    sender = post or requests.post
    resp = sender(
        endpoint,
        headers={"Authorization": f"Bearer {route.api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=180,
    )
    try:
        data = resp.json()
    except Exception:
        data = {"raw_text": getattr(resp, "text", "")[:1000]}
    if getattr(resp, "status_code", 200) >= 400:
        raise RuntimeError(f"文本模型调用失败: HTTP {resp.status_code}, body={redact_secret(data)}")
    return TextModelResult(
        text=_extract_openai_text(data),
        raw_response=data,
        endpoint=endpoint,
        provider=route.provider,
        model=model_name,
    )


def _videos_endpoint(api_base: str, default_base: str) -> str:
    base = (api_base or default_base).strip().rstrip("/")
    if base.endswith("/v1/videos"):
        return base
    if base.endswith("/v1"):
        return f"{base}/videos"
    return f"{base}/v1/videos"


def _images_endpoint(api_base: str, default_base: str, *, edit: bool = False) -> str:
    base = (api_base or default_base).strip().rstrip("/")
    suffix = "edits" if edit else "generations"
    for known_suffix in ("/v1/images/generations", "/v1/images/edits"):
        if base.endswith(known_suffix):
            return base[: -len(known_suffix)] + f"/v1/images/{suffix}"
    if base.endswith("/v1"):
        return f"{base}/images/{suffix}"
    return f"{base}/v1/images/{suffix}"


def _api_origin(api_base: str, default_base: str) -> str:
    base = (api_base or default_base).strip().rstrip("/")
    if base.endswith("/v1"):
        return base[:-3]
    return base


def is_aitgenne_happyhorse_model(route: AiRoute) -> bool:
    model_name = parse_model_display(route.model)["model"] or route.model
    return route.provider == "Aitgenne" and model_name.startswith("happyhorse-1.0-")


def is_aitgenne_unified_video_model(route: AiRoute) -> bool:
    model_name = parse_model_display(route.model)["model"] or route.model
    return route.provider == "Aitgenne" and route.capability == "视频" and model_name in AITGENNE_UNIFIED_VIDEO_MODELS


def is_aitgenne_unified_components_model(route: AiRoute) -> bool:
    model_name = parse_model_display(route.model)["model"] or route.model
    return is_aitgenne_unified_video_model(route) and model_name in AITGENNE_COMPONENTS_VIDEO_MODELS


def aitgenne_video_synthesis_endpoint(api_base: str = "") -> str:
    origin = _api_origin(api_base, "https://api.aitgenne.com")
    if origin.endswith("/alibailian/api/v1/services/aigc/video-generation/video-synthesis"):
        return origin
    return f"{origin}/alibailian/api/v1/services/aigc/video-generation/video-synthesis"


def aitgenne_task_endpoint(api_base: str, task_id: str) -> str:
    return f"{_api_origin(api_base, 'https://api.aitgenne.com')}/alibailian/api/v1/tasks/{task_id}"


def aitgenne_video_create_endpoint(api_base: str = "") -> str:
    return f"{_api_origin(api_base, 'https://api.aitgenne.com')}/v1/video/create"


def aitgenne_video_query_endpoint(api_base: str = "", task_id: str = "") -> str:
    base = f"{_api_origin(api_base, 'https://api.aitgenne.com')}/v1/video/query"
    if not task_id:
        return base
    return f"{base}?{urlencode({'id': task_id})}"


def media_task_endpoint(route: AiRoute, task_id: str) -> str:
    if is_aitgenne_happyhorse_model(route):
        return aitgenne_task_endpoint(route.api_base, task_id)
    if is_aitgenne_unified_video_model(route):
        return aitgenne_video_query_endpoint(route.api_base, task_id)
    return f"{media_endpoint(route).rstrip('/')}/{task_id}"


def _duration_value(value: Any, default: str = "5") -> int:
    text = _norm(value) or default
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return int(default)


def _happyhorse_resolution(size: Any) -> str:
    text = _norm(size).upper()
    if text in {"1080P", "1080"} or "1080" in text or "1920" in text:
        return "1080P"
    return "720P"


def _happyhorse_media(model_name: str, reference_urls: Sequence[str]) -> List[Dict[str, str]]:
    urls = [_norm(url) for url in reference_urls if _norm(url)]
    if model_name == "happyhorse-1.0-t2v":
        return []
    if model_name == "happyhorse-1.0-i2v":
        if not urls:
            raise ValueError("happyhorse-1.0-i2v 需要 1 张首帧图 URL")
        return [{"type": "first_frame", "url": urls[0]}]
    if model_name == "happyhorse-1.0-r2v":
        if not urls:
            raise ValueError("happyhorse-1.0-r2v 需要至少 1 张参考图 URL")
        return [{"type": "reference_image", "url": url} for url in urls]
    return [{"type": "reference_image", "url": url} for url in urls]


def build_happyhorse_video_payload(
    route: AiRoute,
    prompt: str,
    reference_urls: Sequence[str],
    *,
    size: Any = "",
    aspect_ratio: Any = "",
    seconds: Any = "",
    extra_parameters: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    model_name = parse_model_display(route.model)["model"] or route.model
    if not model_name.startswith("happyhorse-1.0-"):
        raise ValueError(f"非 HappyHorse 模型不能使用 HappyHorse payload: {model_name}")
    input_body: Dict[str, Any] = {"prompt": prompt}
    media = _happyhorse_media(model_name, reference_urls)
    if media:
        input_body["media"] = media
    parameters: Dict[str, Any] = {
        "resolution": _happyhorse_resolution(size),
    }
    if model_name in {"happyhorse-1.0-r2v", "happyhorse-1.0-t2v"}:
        parameters["ratio"] = _norm(aspect_ratio) or "9:16"
    if model_name != "happyhorse-1.0-video-edit":
        parameters["duration"] = _duration_value(seconds, "5")
    for key, value in (extra_parameters or {}).items():
        if value is not None:
            parameters[key] = value
    return {
        "model": model_name,
        "input": input_body,
        "parameters": parameters,
    }


def build_aitgenne_unified_video_payload(
    route: AiRoute,
    prompt: str,
    reference_urls: Sequence[str],
    *,
    aspect_ratio: Any = "",
) -> Dict[str, Any]:
    model_name = parse_model_display(route.model)["model"] or route.model
    urls = [_norm(url) for url in reference_urls if _norm(url)]
    if not urls:
        raise ValueError(f"{route.model} 需要至少 1 张参考图 URL")
    params = dict(route.params or {})
    ratio = _norm(aspect_ratio) or _norm(params.get("aspect_ratio") or params.get("画面比例")) or "9:16"
    return {
        "model": model_name,
        "prompt": prompt,
        "images": urls,
        "enhance_prompt": bool(params.get("enhance_prompt", True)),
        "enable_upsample": bool(params.get("enable_upsample", True)),
        "aspect_ratio": ratio,
    }


def extract_video_task_id(data: Mapping[str, Any]) -> str:
    candidates = [
        data.get("id"),
        data.get("task_id"),
        data.get("video_id"),
        (data.get("data") or {}).get("id") if isinstance(data.get("data"), dict) else None,
        (data.get("data") or {}).get("task_id") if isinstance(data.get("data"), dict) else None,
        (data.get("output") or {}).get("task_id") if isinstance(data.get("output"), dict) else None,
    ]
    for item in candidates:
        text = _norm(item)
        if text:
            return text
    return ""


def extract_video_status(data: Mapping[str, Any]) -> str:
    candidates = [
        data.get("status"),
        (data.get("data") or {}).get("status") if isinstance(data.get("data"), dict) else None,
        (data.get("data") or {}).get("state") if isinstance(data.get("data"), dict) else None,
        (data.get("result") or {}).get("status") if isinstance(data.get("result"), dict) else None,
        (data.get("output") or {}).get("task_status") if isinstance(data.get("output"), dict) else None,
        (data.get("detail") or {}).get("status") if isinstance(data.get("detail"), dict) else None,
    ]
    for item in candidates:
        text = _norm(item).lower()
        if text:
            return text
    return ""


def extract_video_result_url(data: Mapping[str, Any]) -> str:
    containers: List[Mapping[str, Any]] = [data]
    for key in ("detail", "data", "result", "output"):
        nested = data.get(key) if isinstance(data.get(key), Mapping) else {}
        if nested:
            containers.append(nested)
    candidates: List[Any] = []
    for item in containers:
        candidates.extend([
            item.get("upsample_video_url"),
            item.get("video_url"),
            item.get("result_url"),
            item.get("download_url"),
            item.get("url"),
        ])
    for list_key in ("result_urls", "urls", "videos"):
        for item in containers:
            value = item.get(list_key)
            if isinstance(value, list) and value:
                first = value[0]
                if isinstance(first, str):
                    candidates.append(first)
                elif isinstance(first, Mapping):
                    candidates.extend([
                        first.get("upsample_video_url"),
                        first.get("video_url"),
                        first.get("result_url"),
                        first.get("download_url"),
                        first.get("url"),
                    ])
    for value in candidates:
        text = _norm(value)
        if text.startswith("http"):
            return text
    return ""


def media_endpoint(route: AiRoute) -> str:
    provider = route.provider
    capability = route.capability
    model_name = parse_model_display(route.model)["model"] or route.model
    if provider == "OTU":
        if capability == "图片" and model_name == "image2":
            return ((route.api_base or "https://otuapi.com").rstrip("/") + "/v1/images/generations")
        return _videos_endpoint(route.api_base, "https://otuapi.com")
    if provider == "AIHubMix":
        if capability == "图片":
            base = (route.api_base or "https://aihubmix.com").strip().rstrip("/")
            if base.endswith("/v1"):
                base = base[:-3]
            return f"{base}/v1/models/{model_name}/predictions"
        return _videos_endpoint(route.api_base, "https://aihubmix.com")
    if provider == "Aitgenne":
        if capability == "视频":
            if model_name.startswith("happyhorse-1.0-"):
                return aitgenne_video_synthesis_endpoint(route.api_base)
            if is_aitgenne_unified_video_model(route):
                return aitgenne_video_create_endpoint(route.api_base)
            return _videos_endpoint(route.api_base, "https://api.aitgenne.com")
        if capability == "图片":
            return _images_endpoint(route.api_base, "https://api.aitgenne.com")
    raise ValueError(f"不支持的媒体路由: provider={provider}, capability={capability}")


def build_media_request_summary(route: AiRoute, prompt: str, *, reference_count: int = 0) -> Dict[str, Any]:
    validate_route(route)
    if route.capability not in {"图片", "视频"}:
        raise ValueError(f"build_media_request_summary 只支持图片/视频能力，当前={route.capability}")
    model_name = parse_model_display(route.model)["model"] or route.model
    params = dict(route.params or {})
    payload: Dict[str, Any] = {
        "model": model_name,
        "prompt": prompt,
    }
    if route.capability == "图片":
        size = params.get("size") or params.get("画面尺寸") or "1024x1024"
        aspect_ratio = params.get("aspect_ratio") or params.get("画面比例") or "9:16"
        if route.provider == "Aitgenne":
            payload["n"] = int(params.get("n") or 1)
            payload["size"] = size
            for key in ("quality", "format"):
                if params.get(key) not in (None, ""):
                    payload[key] = params.get(key)
            if reference_count:
                payload["image"] = ["<reference_file>"] * int(reference_count or 0)
            endpoint = (
                _images_endpoint(route.api_base, "https://api.aitgenne.com", edit=True)
                if reference_count
                else media_endpoint(route)
            )
            adapter_payload_summary = {
                "size": "payload.size",
                "n": "payload.n",
            }
            if reference_count:
                adapter_payload_summary["image"] = "multipart field image repeated"
        else:
            payload["size"] = size
            payload["metadata"] = adapt_image_metadata(size=size, aspect_ratio=aspect_ratio)
            if reference_count:
                payload["input_mode"] = "image-to-image"
                if str(route.provider or "").strip().upper() == "OTU":
                    payload["metadata"]["urls"] = ["<reference_url>"] * min(int(reference_count or 0), 5)
            endpoint = media_endpoint(route)
            adapter_payload_summary = {
                "size": "payload.size",
                "aspect_ratio": "payload.metadata.aspectRatio",
                "aspect_ratio_alias": "payload.metadata.aspect_ratio",
            }
        spec = media_spec_from_values(size=size, aspect_ratio=aspect_ratio, slot_name=route.task_type, capability=route.capability)
    else:
        size = params.get("size") or params.get("画面尺寸") or "720x1280"
        seconds = str(params.get("seconds") or params.get("视频时长") or "8")
        aspect_ratio = params.get("aspect_ratio") or params.get("画面比例") or "9:16"
        if is_aitgenne_happyhorse_model(route):
            payload = build_happyhorse_video_payload(
                route,
                prompt,
                ["<reference_url>"] * int(reference_count or 0),
                size=size,
                aspect_ratio=aspect_ratio,
                seconds=seconds,
            )
        elif is_aitgenne_unified_video_model(route):
            payload = build_aitgenne_unified_video_payload(
                route,
                prompt,
                ["<reference_url>"] * int(reference_count or 0),
                aspect_ratio=aspect_ratio,
            )
        else:
            payload["size"] = size
            payload["seconds"] = seconds
            payload["aspect_ratio"] = aspect_ratio
        spec = media_spec_from_values(size=size, aspect_ratio=aspect_ratio, seconds=seconds, slot_name=route.task_type, capability=route.capability)
        adapter_payload_summary = (
            {"input": "payload.input", "parameters": "payload.parameters"}
            if is_aitgenne_happyhorse_model(route)
            else {"images": "payload.images", "aspect_ratio": "payload.aspect_ratio"}
            if is_aitgenne_unified_video_model(route)
            else {
                "size": "payload.size",
                "aspect_ratio": "payload.aspect_ratio",
                "seconds": "payload.seconds",
            }
        )
        endpoint = media_endpoint(route)
    return redact_secret({
        "provider": route.provider,
        "capability": route.capability,
        "task_type": route.task_type,
        "endpoint": endpoint,
        "method": "POST",
        "content_type": "multipart/form-data" if route.provider == "Aitgenne" and route.capability == "图片" and reference_count else "application/json",
        "payload_keys": sorted(payload.keys()),
        "payload": payload,
        "media_spec": spec.summary(),
        "adapter_payload_summary": adapter_payload_summary,
        "ignored_fields": [],
        "reference_count": int(reference_count or 0),
        "api_key": route.api_key,
    })
