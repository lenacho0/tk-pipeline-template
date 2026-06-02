#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Any, Callable, Dict, Iterable, List, Optional

import requests

import ai_routing
from aitgenne_image import (
    DEFAULT_AITGENNE_API_BASE,
    save_aitgenne_image_result,
    submit_aitgenne_image_generation,
)
from media_specs import adapt_image_metadata
from otu_image import (
    DEFAULT_OTU_API_BASE,
    DEFAULT_OTU_IMAGE_MODEL,
    DEFAULT_OTU_IMAGE_SIZE,
    download_otu_image_result,
    extract_otu_result_url,
    normalize_image_model_choice,
    poll_otu_image_task,
    submit_otu_image_task,
)


AITGENNE_SUBMIT_RETRY_DELAYS_SECONDS = [8, 16]
AITGENNE_RETRYABLE_ERROR_MARKERS = (
    "http 429",
    "rate limit",
    "too many requests",
    "负载已饱和",
    "稍后再试",
    "network",
    "网络",
    "timeout",
    "timed out",
    "ssl",
    "connection",
)


@dataclass
class ImageGenerationResult:
    provider: str
    task_id: str
    submit_body: Dict[str, Any]
    result_body: Dict[str, Any]
    output_path: str
    request_summary: Dict[str, Any] = field(default_factory=dict)


def _request_summary(
    *,
    provider: str,
    model: str,
    size: str,
    aspect_ratio: str,
    input_mode: str,
    reference_count: int,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "provider": provider,
        "model": model,
        "size": size,
        "aspect_ratio": aspect_ratio,
        "input_mode": input_mode,
        "reference_count": int(reference_count or 0),
        "metadata_keys": sorted((metadata or {}).keys()),
        "adapter_payload_summary": {
            "size": "payload.size",
            "aspect_ratio": "payload.metadata.aspectRatio",
            "aspect_ratio_alias": "payload.metadata.aspect_ratio",
        },
        "ignored_fields": [],
    }


def resolve_image_route_from_slot(
    fields: Dict[str, Any],
    slot_name: str,
    cfg: Dict[str, Any],
    *,
    task_type: str,
    params: Optional[Dict[str, Any]] = None,
    config_records: Optional[Iterable[Dict[str, Any]]] = None,
) -> ai_routing.AiRoute:
    provider = cfg.get("provider") or "OTU"
    model = cfg.get("model") or DEFAULT_OTU_IMAGE_MODEL
    if " / " not in str(model):
        model = f"{provider} / {model}"
    route = ai_routing.route_from_slot(
        fields,
        slot_name,
        {
            **cfg,
            "provider": provider,
            "capability": "图片",
            "task_type": task_type,
            "model": model,
            "params": params or {},
        },
        capability="图片",
        task_type=task_type,
        config_records=config_records,
    )
    route.params.update(params or {})
    return route


def config_records_for_image_slot(
    fields: Dict[str, Any],
    slot_name: str,
    loader: Callable[[], Iterable[Dict[str, Any]]],
) -> Iterable[Dict[str, Any]]:
    raw = str(fields.get(ai_routing.slot_model_field(slot_name)) or "").strip()
    provider = raw.split(" / ", 1)[0].strip() if " / " in raw else ""
    if provider and provider != "OTU":
        return loader()
    if ai_routing.record_wants_unified_route(fields):
        return loader()
    return []


def image_model_name(route: ai_routing.AiRoute) -> str:
    raw = ai_routing.parse_model_display(route.model)["model"] or route.model
    return normalize_image_model_choice(raw) if route.provider == "OTU" else raw


def _is_retryable_aitgenne_submit_error(exc: Exception) -> bool:
    if isinstance(exc, requests.RequestException):
        return True
    message = str(exc).lower()
    return any(marker in message for marker in AITGENNE_RETRYABLE_ERROR_MARKERS)


def _submit_aitgenne_image_with_retry(
    submitter: Callable[..., Any],
    config: Dict[str, str],
    prompt: str,
    **kwargs: Any,
) -> Dict[str, Any]:
    for delay in [*AITGENNE_SUBMIT_RETRY_DELAYS_SECONDS, None]:
        try:
            return submitter(config, prompt, **kwargs)
        except Exception as exc:
            if delay is None or not _is_retryable_aitgenne_submit_error(exc):
                raise
            time.sleep(delay)
    raise RuntimeError("Aitgenne 图片提交重试状态异常")


def run_image_generation(
    route: ai_routing.AiRoute,
    prompt: str,
    out_path: str,
    *,
    input_mode: str,
    image_path: str = "",
    image_url: str = "",
    reference_image_paths: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    size: str = DEFAULT_OTU_IMAGE_SIZE,
    aspect_ratio: str = "9:16",
    existing_task_id: str = "",
    otu_submitter: Callable[..., Any] = submit_otu_image_task,
    otu_poller: Callable[..., Any] = poll_otu_image_task,
    otu_downloader: Callable[..., Any] = download_otu_image_result,
    aitgenne_submitter: Callable[..., Any] = submit_aitgenne_image_generation,
    aitgenne_saver: Callable[..., Any] = save_aitgenne_image_result,
    on_task_submitted: Optional[Callable[[str], None]] = None,
) -> ImageGenerationResult:
    if not route.api_key:
        raise ValueError(f"{route.provider} / {route.model} 缺少 API Key")
    model_name = image_model_name(route)
    if route.provider == "OTU":
        cfg = {"api_key": route.api_key, "api_base": route.api_base or DEFAULT_OTU_API_BASE, "model": model_name}
        request_summary: Dict[str, Any]
        if existing_task_id:
            task_id = existing_task_id
            submit_body: Dict[str, Any] = {"existing_task_id": task_id, "resumed": True}
            request_summary = _request_summary(
                provider=route.provider,
                model=model_name,
                size=size,
                aspect_ratio=aspect_ratio,
                input_mode=input_mode,
                reference_count=len(reference_image_paths or []),
                metadata=metadata,
            )
            request_summary["existing_task_id"] = task_id
        else:
            effective_metadata = adapt_image_metadata(metadata, size=size, aspect_ratio=aspect_ratio)
            request_summary = _request_summary(
                provider=route.provider,
                model=model_name,
                size=size,
                aspect_ratio=aspect_ratio,
                input_mode=input_mode,
                reference_count=len(reference_image_paths or []),
                metadata=effective_metadata,
            )
            submit_kwargs: Dict[str, Any] = {
                "input_mode": input_mode,
                "reference_image_paths": reference_image_paths,
                "metadata": effective_metadata,
                "size": size,
                "aspect_ratio": aspect_ratio,
            }
            if image_path:
                submit_kwargs["image_path"] = image_path
            if image_url:
                submit_kwargs["image_url"] = image_url
            task_id, submit_body = otu_submitter(
                cfg,
                prompt,
                **submit_kwargs,
            )
            if task_id and on_task_submitted:
                on_task_submitted(task_id)
        result = submit_body if not task_id else otu_poller(cfg, task_id)
        result_url = extract_otu_result_url(result) or extract_otu_result_url(submit_body)
        if not result_url:
            raise RuntimeError("OTU 图片任务完成但未返回图片地址")
        otu_downloader(result_url, out_path)
        return ImageGenerationResult(route.provider, task_id, submit_body, result, out_path, request_summary)
    if route.provider == "Aitgenne":
        effective_metadata = adapt_image_metadata(metadata, size=size, aspect_ratio=aspect_ratio)
        request_summary = _request_summary(
            provider=route.provider,
            model=model_name,
            size=size,
            aspect_ratio=aspect_ratio,
            input_mode=input_mode,
            reference_count=len(reference_image_paths or []),
            metadata=effective_metadata,
        )
        body = _submit_aitgenne_image_with_retry(
            aitgenne_submitter,
            {"api_key": route.api_key, "api_base": route.api_base or DEFAULT_AITGENNE_API_BASE, "model": model_name},
            prompt,
            input_mode=input_mode,
            image_path=image_path,
            image_url=image_url,
            reference_image_paths=reference_image_paths,
            metadata=effective_metadata,
            size=size,
            aspect_ratio=aspect_ratio,
        )
        aitgenne_saver(body, out_path)
        return ImageGenerationResult(route.provider, "", body, body, out_path, request_summary)
    raise NotImplementedError(f"当前图片生成暂不支持供应商：{route.provider}")
