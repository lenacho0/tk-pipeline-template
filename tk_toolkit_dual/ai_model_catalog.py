#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


STATUS_ENABLED = "enabled"
STATUS_CANDIDATE = "candidate"
STATUS_DISABLED = "disabled"
STATUS_DEPRECATED = "deprecated"
STATUS_DISCARD = "discard"

PRODUCTION_STATUSES = {STATUS_ENABLED}
LOOKUP_STATUSES = {STATUS_ENABLED}
INSPECTABLE_STATUSES = {STATUS_ENABLED, STATUS_CANDIDATE}
UNIFIED_AI_CAPABILITIES = ("文本", "图片", "视频")


@dataclass(frozen=True)
class ModelCatalogEntry:
    provider: str
    capability: str
    model: str
    display_name: str
    endpoint_type: str
    status: str
    source: str
    notes: str = ""
    call_types: Tuple[str, ...] = field(default_factory=tuple)
    supports_video_input: bool = False
    supports_structured_json: bool = False
    nine_grid_fit: str = ""
    price: str = ""


def opt(name: str, hue: str = "Blue", lightness: str = "Lighter") -> Dict[str, str]:
    return {"name": name, "hue": hue, "lightness": lightness}


def display_name(provider: str, model: str) -> str:
    return f"{provider} / {model}"


def _entry(
    provider: str,
    capability: str,
    model: str,
    endpoint_type: str,
    status: str,
    source: str,
    *,
    notes: str = "",
    call_types: Sequence[str] = (),
    supports_video_input: bool = False,
    supports_structured_json: bool = False,
    nine_grid_fit: str = "",
    price: str = "",
) -> ModelCatalogEntry:
    return ModelCatalogEntry(
        provider=provider,
        capability=capability,
        model=model,
        display_name=display_name(provider, model),
        endpoint_type=endpoint_type,
        status=status,
        source=source,
        notes=notes,
        call_types=tuple(call_types),
        supports_video_input=supports_video_input,
        supports_structured_json=supports_structured_json,
        nine_grid_fit=nine_grid_fit,
        price=price,
    )


MODEL_CATALOG: Tuple[ModelCatalogEntry, ...] = (
    _entry(
        "AIHubMix",
        "文本",
        "gemini-3.1-pro-preview",
        "Gemini 原生 SDK",
        STATUS_ENABLED,
        "现有适配器/配置",
        call_types=("Gemini 原生 SDK",),
        supports_video_input=True,
        supports_structured_json=True,
        nine_grid_fit="适合方案/拆分/提示词生成",
    ),
    _entry(
        "Aitgenne",
        "文本",
        "gpt-5.5",
        "OpenAI兼容 chat/completions",
        STATUS_ENABLED,
        "现有适配器/配置",
        call_types=("OpenAI兼容 chat/completions",),
        supports_structured_json=True,
        nine_grid_fit="适合方案/文案生成",
    ),
    _entry(
        "Aitgenne",
        "文本",
        "gemini-3.5-flash",
        "OpenAI兼容 chat/completions",
        STATUS_ENABLED,
        "用户提供/待填模型级密钥",
        call_types=("OpenAI兼容 chat/completions",),
        supports_structured_json=True,
        nine_grid_fit="适合文本拆解/方案生成",
    ),
    _entry(
        "Aitgenne",
        "文本",
        "claude-opus-4-8",
        "OpenAI兼容 chat/completions",
        STATUS_ENABLED,
        "用户提供/待填模型级密钥",
        call_types=("OpenAI兼容 chat/completions",),
        supports_structured_json=True,
        nine_grid_fit="适合文本拆解/高质量推理",
    ),
    _entry(
        "Aitgenne",
        "文本",
        "gemini-3.1-pro-preview",
        "待验证文本接口",
        STATUS_CANDIDATE,
        "用户候选/待隐藏模型验证",
        call_types=("Gemini 原生 SDK", "Gemini 原生 inline_data"),
        supports_video_input=True,
        supports_structured_json=True,
        notes="Aitgenne /v1/models 未返回；确认可调用前不进入生产下拉。",
    ),
    _entry("AIHubMix", "文本", "gemini-2.5-flash", "Gemini 原生 SDK", STATUS_DEPRECATED, "旧配置"),
    _entry("AIHubMix", "文本", "gemini-2.5-pro-preview-05-13", "Gemini 原生 SDK", STATUS_DEPRECATED, "旧配置"),
    _entry("Aitgenne", "文本", "custom__aitgenne/gpt-5.4", "OpenAI兼容 chat/completions", STATUS_DEPRECATED, "旧配置"),
    _entry(
        "OTU",
        "图片",
        "gpt-image-2",
        "OTU /v1/videos JSON image task",
        STATUS_ENABLED,
        "OTU /v1/models + 现有适配器",
        nine_grid_fit="1K 图片主通道",
    ),
    _entry(
        "OTU",
        "图片",
        "gpt-image-2-2K",
        "OTU /v1/videos JSON image task",
        STATUS_ENABLED,
        "OTU /v1/models + 现有适配器",
        nine_grid_fit="2K 图片主通道",
    ),
    _entry(
        "OTU",
        "图片",
        "gpt-image-2-4K",
        "OTU /v1/videos JSON image task",
        STATUS_ENABLED,
        "OTU /v1/models + 现有适配器",
        nine_grid_fit="4K 图片主通道",
    ),
    _entry(
        "AIHubMix",
        "图片",
        "gpt-image-2",
        "图片生成待验证",
        STATUS_CANDIDATE,
        "AIHubMix /v1/models 待端点确认",
        notes="确认真实图片端点和参数前不进入生产下拉。",
    ),
    _entry(
        "Aitgenne",
        "图片",
        "gpt-image-2",
        "OpenAI兼容 /v1/images/generations",
        STATUS_ENABLED,
        "Aitgenne 图片端点验证/现有统一路由",
        notes="用于参考图文生图；参考图真实提交已接入。",
    ),
    _entry("OTU", "图片", "nano_banana_2", "OTU /v1/videos", STATUS_DISCARD, "用户明确不接"),
    _entry("OTU", "图片", "nano_banana_pro-1K", "OTU /v1/videos", STATUS_DISCARD, "用户明确不接"),
    _entry("OTU", "图片", "nano_banana_pro-2K", "OTU /v1/videos", STATUS_DISCARD, "用户明确不接"),
    _entry("OTU", "图片", "nano_banana_pro-4K", "OTU /v1/videos", STATUS_DISCARD, "用户明确不接"),
    _entry("OTU", "图片", "gpt-image-2-free", "OTU /v1/videos", STATUS_DISCARD, "用户明确不接"),
    _entry("OTU", "图片", "gpt-image-2-all", "OTU /v1/videos", STATUS_DISCARD, "用户明确不接"),
    _entry("OTU", "视频", "omni_flash-10s", "OTU /v1/videos multipart", STATUS_ENABLED, "OTU /v1/models", nine_grid_fit="适合单图/Omni 视频"),
    _entry("OTU", "视频", "veo_3_1", "OTU /v1/videos multipart", STATUS_ENABLED, "OTU /v1/models", nine_grid_fit="适合图生视频"),
    _entry("OTU", "视频", "veo_3_1-fast-fl", "OTU /v1/videos multipart", STATUS_ENABLED, "OTU /v1/models + 现有适配器", nine_grid_fit="首帧图生视频主通道"),
    _entry("OTU", "视频", "veo_3_1-fast-fl-hd", "OTU /v1/videos multipart", STATUS_ENABLED, "OTU /v1/models + UGC smoke", nine_grid_fit="高清首帧图生视频"),
    _entry("OTU", "视频", "veo_3_1-fl", "OTU /v1/videos multipart", STATUS_ENABLED, "OTU /v1/models", nine_grid_fit="首帧图生视频"),
    _entry("OTU", "视频", "veo_3_1-hd", "OTU /v1/videos multipart", STATUS_ENABLED, "OTU /v1/models", nine_grid_fit="高清视频"),
    _entry("OTU", "视频", "veo_3_1-hd-fl", "OTU /v1/videos multipart", STATUS_ENABLED, "OTU /v1/models", nine_grid_fit="高清首帧图生视频"),
    _entry("OTU", "视频", "veo_3_1-fast", "OTU /v1/videos multipart", STATUS_DISCARD, "本轮 OTU /v1/models 未返回"),
    _entry("OTU", "视频", "sora-2-12s", "OTU /v1/videos multipart", STATUS_DISCARD, "本轮 OTU /v1/models 未返回/用户不接 Sora"),
    _entry("AIHubMix", "视频", "veo-3.1-fast-generate-preview", "Gemini native Veo", STATUS_ENABLED, "现有适配器/smoke test", nine_grid_fit="单首帧视频"),
    _entry("AIHubMix", "视频", "seeddance2.0", "AIHubMix 视频适配器", STATUS_CANDIDATE, "现有适配器/通道待恢复", notes="Smoke 复测返回 no_valid_channel_error，当前账号/通道不可生产使用。"),
    _entry("AIHubMix", "视频", "sora-2-pro", "AIHubMix 视频", STATUS_DISCARD, "用户明确不接"),
    _entry("Aitgenne", "视频", "happyhorse-1.0-r2v", "happyhorse视频", STATUS_ENABLED, "官网模型广场/用户确认", nine_grid_fit="适合多参考图九宫格"),
    _entry("Aitgenne", "视频", "happyhorse-1.0-i2v", "happyhorse视频", STATUS_ENABLED, "官网模型广场/用户确认", nine_grid_fit="适合单张九宫格图转视频"),
    _entry("Aitgenne", "视频", "omni-flash", "视频统一格式", STATUS_ENABLED, "官网模型广场/用户确认", nine_grid_fit="适合 Omni 视频候选"),
    _entry("Aitgenne", "视频", "veo_3_1_lite_vip", "视频统一格式", STATUS_ENABLED, "用户提供/Apifox", nine_grid_fit="Aitgenne Veo 3.1 Lite VIP 图生视频"),
    _entry("Aitgenne", "视频", "veo_3_1_fast_vip", "视频统一格式", STATUS_ENABLED, "用户提供/Apifox", nine_grid_fit="Aitgenne Veo 3.1 Fast VIP 图生视频"),
    _entry("Aitgenne", "视频", "veo_3_1_vip", "视频统一格式", STATUS_ENABLED, "用户提供/Apifox", nine_grid_fit="Aitgenne Veo 3.1 VIP 图生视频"),
    _entry("Aitgenne", "视频", "veo_3_1_components_vip", "视频统一格式", STATUS_ENABLED, "用户提供/Apifox", nine_grid_fit="Aitgenne Veo 3.1 Components VIP 参考图生视频"),
    _entry("Aitgenne", "视频", "happyhorse-1.0-t2v", "happyhorse视频", STATUS_ENABLED, "官网模型广场", notes="文生视频，使用 HappyHorse alibailian 原生端点；不作为图生视频链路默认模型。"),
    _entry(
        "Aitgenne",
        "视频编辑",
        "happyhorse-1.0-video-edit",
        "happyhorse视频编辑",
        STATUS_ENABLED,
        "官网模型广场/用户确认",
        notes="006 视频编辑任务表使用 Aitgenne alibailian video-generation/video-synthesis 原生端点。",
        call_types=("happyhorse视频编辑",),
    ),
    _entry("Aitgenne", "视频", "veo-3.1-fast", "Google 音视频待验证", STATUS_CANDIDATE, "官网模型广场待确认", notes="Aitgenne /v1/models 未返回，先不进生产下拉。"),
    _entry("Aitgenne", "视频", "kling-video", "视频统一格式", STATUS_DISCARD, "用户明确不接"),
    _entry("Aitgenne", "视频", "pixverse-video", "视频统一格式", STATUS_DISCARD, "用户明确不接"),
    _entry("Aitgenne", "视频", "MiniMax-Hailuo-2.3", "视频统一格式", STATUS_DISCARD, "用户明确不接"),
    _entry("Aitgenne", "视频", "wan2.6-i2v", "视频统一格式", STATUS_DISCARD, "用户明确不接"),
    _entry("Aitgenne", "视频", "sora-2", "视频统一格式", STATUS_DISCARD, "用户明确不接"),
    _entry("Aitgenne", "语音", "speech-2.8-turbo", "MiniMax TTS", STATUS_ENABLED, "现有 TTS 适配器"),
)


PROVIDER_HUES = {
    "AIHubMix": "Blue",
    "Aitgenne": "Purple",
    "OTU": "Green",
}


def _norm(value: str) -> str:
    return (value or "").strip().lower().replace("_", "-").replace(" ", "")


def catalog_entries(statuses: Optional[Iterable[str]] = None) -> List[ModelCatalogEntry]:
    allowed = set(statuses) if statuses else None
    return [entry for entry in MODEL_CATALOG if allowed is None or entry.status in allowed]


def models_for_capability(capability: str, statuses: Optional[Iterable[str]] = None) -> List[ModelCatalogEntry]:
    allowed_statuses = set(statuses or PRODUCTION_STATUSES)
    return [
        entry for entry in MODEL_CATALOG
        if entry.capability == capability and entry.status in allowed_statuses
    ]


def production_models(capability: Optional[str] = None) -> List[ModelCatalogEntry]:
    entries = catalog_entries(PRODUCTION_STATUSES)
    if capability:
        entries = [entry for entry in entries if entry.capability == capability]
    return entries


def find_model(provider: str, capability: str, model: str, *, include_candidate: bool = False) -> Optional[ModelCatalogEntry]:
    statuses = INSPECTABLE_STATUSES if include_candidate else LOOKUP_STATUSES
    provider_norm = _norm(provider)
    capability_norm = _norm(capability)
    model_norm = _norm(model)
    for entry in MODEL_CATALOG:
        if entry.status not in statuses:
            continue
        if _norm(entry.provider) != provider_norm:
            continue
        if _norm(entry.capability) != capability_norm:
            continue
        if _norm(entry.model) == model_norm or _norm(entry.display_name) == model_norm:
            return entry
    return None


def option_for_model(entry: ModelCatalogEntry) -> Dict[str, str]:
    return opt(entry.display_name, PROVIDER_HUES.get(entry.provider, "Blue"))


def production_model_options(capability: Optional[str] = None) -> List[Dict[str, str]]:
    return [option_for_model(entry) for entry in production_models(capability)]


def unified_ai_model_options() -> List[Dict[str, str]]:
    return [
        option_for_model(entry)
        for entry in production_models()
        if entry.capability in UNIFIED_AI_CAPABILITIES
    ]


def select_options_for_capability(capability: str) -> List[Dict[str, str]]:
    return production_model_options(capability)


REFERENCE_VIDEO_MODEL_NAMES = (
    "OTU / omni_flash-10s",
    "Aitgenne / happyhorse-1.0-r2v",
    "Aitgenne / omni-flash",
    "Aitgenne / veo_3_1_lite_vip",
    "Aitgenne / veo_3_1_fast_vip",
    "Aitgenne / veo_3_1_vip",
    "Aitgenne / veo_3_1_components_vip",
)

FIRST_LAST_VIDEO_MODEL_NAMES = (
    "AIHubMix / veo-3.1-fast-generate-preview",
    "OTU / veo_3_1-fast-fl",
    "OTU / veo_3_1-fast-fl-hd",
    "OTU / veo_3_1-fl",
    "OTU / veo_3_1-hd-fl",
    "Aitgenne / happyhorse-1.0-i2v",
    "Aitgenne / veo_3_1_lite_vip",
    "Aitgenne / veo_3_1_fast_vip",
    "Aitgenne / veo_3_1_vip",
)

PROMPT_IMAGE_VIDEO_MODEL_NAMES = (
    *FIRST_LAST_VIDEO_MODEL_NAMES,
    "OTU / omni_flash-10s",
    "Aitgenne / veo_3_1_components_vip",
)

STORYBOARD_VIDEO_MODEL_NAMES = (
    *FIRST_LAST_VIDEO_MODEL_NAMES,
    "OTU / omni_flash-10s",
)

VIDEO_EDIT_MODEL_NAMES = (
    "Aitgenne / happyhorse-1.0-video-edit",
)


def _options_for_display_names(names: Sequence[str], capability: str = "视频") -> List[Dict[str, str]]:
    by_name = {entry.display_name: entry for entry in production_models(capability)}
    options: List[Dict[str, str]] = []
    for name in names:
        entry = by_name.get(name)
        if not entry:
            raise ValueError(f"生产{capability}模型不存在或未启用: {name}")
        options.append(option_for_model(entry))
    return options


def _display_name_for_value(value: str, provider: str = "") -> str:
    value = (value or "").strip()
    bits = value.split(" / ", 1)
    if len(bits) == 2:
        return value
    model = value
    return display_name(provider, model) if provider and model else model


def is_reference_video_model(value: str, provider: str = "") -> bool:
    return _display_name_for_value(value, provider) in REFERENCE_VIDEO_MODEL_NAMES


def is_first_last_video_model(value: str, provider: str = "") -> bool:
    name = _display_name_for_value(value, provider)
    return not name or name in {"默认（配置表）", "默认", "待确认"} or name in FIRST_LAST_VIDEO_MODEL_NAMES


AI_PROVIDER_OPTIONS = [opt("AIHubMix"), opt("Aitgenne", "Purple"), opt("OTU", "Green")]
AI_CAPABILITY_OPTIONS = [opt("文本"), opt("图片", "Green"), opt("视频", "Blue"), opt("视频编辑", "Purple"), opt("语音", "Purple")]
AI_TASK_TYPE_OPTIONS = [
    opt("脚本解析拆分"),
    opt("多角色首尾帧解析"),
    opt("视频分析"),
    opt("脚本生成"),
    opt("视频提示词生成"),
    opt("文生图", "Green"),
    opt("图生图/参考图重绘", "Green"),
    opt("首帧图生视频", "Blue"),
    opt("首尾帧视频", "Blue"),
    opt("TTS", "Purple"),
]
AI_MODEL_OPTIONS = unified_ai_model_options()
TEXT_MODEL_OPTIONS = select_options_for_capability("文本")
IMAGE_MODEL_OPTIONS = select_options_for_capability("图片")
VIDEO_AI_MODEL_OPTIONS = select_options_for_capability("视频")
REFERENCE_VIDEO_MODEL_OPTIONS = _options_for_display_names(REFERENCE_VIDEO_MODEL_NAMES)
FIRST_LAST_VIDEO_MODEL_OPTIONS = _options_for_display_names(FIRST_LAST_VIDEO_MODEL_NAMES)
PROMPT_IMAGE_VIDEO_MODEL_OPTIONS = _options_for_display_names(PROMPT_IMAGE_VIDEO_MODEL_NAMES)
STORYBOARD_VIDEO_MODEL_OPTIONS = _options_for_display_names(STORYBOARD_VIDEO_MODEL_NAMES)
VIDEO_EDIT_MODEL_OPTIONS = _options_for_display_names(VIDEO_EDIT_MODEL_NAMES, "视频编辑")
VOICE_MODEL_OPTIONS = select_options_for_capability("语音")
VIDEO_MODEL_OPTIONS = [opt("默认（配置表）", "Gray"), *VIDEO_AI_MODEL_OPTIONS]
REFERENCE_VIDEO_MODEL_WITH_DEFAULT_OPTIONS = [opt("默认（配置表）", "Gray"), *REFERENCE_VIDEO_MODEL_OPTIONS]
FIRST_LAST_VIDEO_MODEL_WITH_DEFAULT_OPTIONS = [opt("默认（配置表）", "Gray"), *FIRST_LAST_VIDEO_MODEL_OPTIONS]
PROMPT_IMAGE_VIDEO_MODEL_WITH_DEFAULT_OPTIONS = [opt("默认（配置表）", "Gray"), *PROMPT_IMAGE_VIDEO_MODEL_OPTIONS]
STORYBOARD_VIDEO_MODEL_WITH_DEFAULT_OPTIONS = [opt("默认（配置表）", "Gray"), *STORYBOARD_VIDEO_MODEL_OPTIONS]
