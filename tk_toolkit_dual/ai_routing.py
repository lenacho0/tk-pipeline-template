#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence
from urllib.parse import urlparse

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
AI_SLOT_MODEL_SUFFIX = "AI模型"
AI_SLOT_PARAMS_SUFFIX = "AI参数JSON"

YES_VALUES = {"是", "yes", "true", "1", "启用", "开启", "使用"}
NO_VALUES = {"否", "no", "false", "0", "关闭", "不使用", ""}
PROVIDER_API_BASE_MARKERS = {
    "AIHubMix": "aihubmix",
    "Aitgenne": "aitgenne",
    "OTU": "otuapi",
}


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
    for rec in config_records or []:
        fields = rec.get("fields") if isinstance(rec, dict) else {}
        if not isinstance(fields, dict):
            continue
        if config_record_matches_model(fields, provider, display_model):
            return fields
    return None


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
    explicit_model = _norm(fields.get(AI_MODEL_FIELD))
    raw_model = explicit_model or _norm(config.get("model"))
    model_bits = parse_model_display(raw_model)
    provider = model_bits["provider"] or _norm(fields.get(AI_PROVIDER_FIELD)) or _norm(config.get("provider"))
    capability = _norm(fields.get(AI_CAPABILITY_FIELD)) or _norm(config.get("capability")) or "文本"
    task_type = _norm(fields.get(AI_TASK_TYPE_FIELD)) or _norm(config.get("task_type"))
    model = raw_model
    call_type = "" if explicit_model else _norm(config.get("call_type") or config.get("调用方式"))
    if capability == "文本" and (not call_type or explicit_model):
        call_type = "Gemini 原生 SDK" if "gemini" in model.lower() else "OpenAI兼容 chat/completions"
    params: Dict[str, Any] = _config_params(config)
    params.update(_parse_params_json(fields.get(AI_PARAMS_FIELD), field_name=AI_PARAMS_FIELD))
    config_provider = _norm(config.get("provider"))
    api_base = _norm(config.get("api_base"))
    api_key = _norm(config.get("api_key"))
    provider_config_records = list(config_records or [])
    if explicit_model and (
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
    slot_model = _norm(fields.get(model_field))
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


def aitgenne_video_synthesis_endpoint(api_base: str = "") -> str:
    origin = _api_origin(api_base, "https://api.aitgenne.com")
    if origin.endswith("/alibailian/api/v1/services/aigc/video-generation/video-synthesis"):
        return origin
    return f"{origin}/alibailian/api/v1/services/aigc/video-generation/video-synthesis"


def aitgenne_task_endpoint(api_base: str, task_id: str) -> str:
    return f"{_api_origin(api_base, 'https://api.aitgenne.com')}/alibailian/api/v1/tasks/{task_id}"


def media_task_endpoint(route: AiRoute, task_id: str) -> str:
    if is_aitgenne_happyhorse_model(route):
        return aitgenne_task_endpoint(route.api_base, task_id)
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
    ]
    for item in candidates:
        text = _norm(item).lower()
        if text:
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
        else:
            payload["size"] = size
            payload["seconds"] = seconds
            payload["aspect_ratio"] = aspect_ratio
        spec = media_spec_from_values(size=size, aspect_ratio=aspect_ratio, seconds=seconds, slot_name=route.task_type, capability=route.capability)
        adapter_payload_summary = (
            {"input": "payload.input", "parameters": "payload.parameters"}
            if is_aitgenne_happyhorse_model(route)
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
