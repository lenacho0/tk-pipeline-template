# AI 模型候选清单

生成日期：2026-05-31

说明：本报告只读生成，不写飞书、不调用生成模型、不输出密钥。

## 拉取状态
- OTU: 0 models, endpoint=, error=跳过 /v1/models 拉取
- AIHubMix: 0 models, endpoint=, error=跳过 /v1/models 拉取
- Aitgenne: 0 models, endpoint=, error=跳过 /v1/models 拉取

## 候选模型

| 供应商 | 模型 ID | 展示名 | 能力类型 | 支持端点 | 价格信息 | 是否适合九宫格 | 建议状态 | 来源 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| AIHubMix | gpt-image-2 | AIHubMix / gpt-image-2 | 图片 | 图片生成待验证 | 待确认 | 待确认 | candidate | AIHubMix /v1/models 待端点确认 |
| AIHubMix | gemini-3.1-pro-preview | AIHubMix / gemini-3.1-pro-preview | 文本 | Gemini 原生 SDK | 待确认 | 适合方案/拆分/提示词生成 | enabled | 现有适配器/配置 |
| AIHubMix | seeddance2.0 | AIHubMix / seeddance2.0 | 视频 | AIHubMix 视频适配器 | 待确认 | 待确认 | candidate | 现有适配器/通道待恢复 |
| AIHubMix | veo-3.1-fast-generate-preview | AIHubMix / veo-3.1-fast-generate-preview | 视频 | Gemini native Veo | 待确认 | 单首帧视频 | enabled | 现有适配器/smoke test |
| Aitgenne | gpt-image-2 | Aitgenne / gpt-image-2 | 图片 | image-generation/openai编辑图片待验证 | 待确认 | 待确认 | candidate | Aitgenne /v1/models 元数据待端点确认 |
| Aitgenne | gemini-3.1-pro-preview | Aitgenne / gemini-3.1-pro-preview | 文本 | 待验证文本接口 | 待确认 | 待确认 | candidate | 用户候选/待隐藏模型验证 |
| Aitgenne | gpt-5.5 | Aitgenne / gpt-5.5 | 文本 | OpenAI兼容 chat/completions | 待确认 | 适合方案/文案生成 | enabled | 现有适配器/配置 |
| Aitgenne | happyhorse-1.0-t2v | Aitgenne / happyhorse-1.0-t2v | 视频 | happyhorse视频 | 待确认 | 待确认 | candidate | 官网模型广场 |
| Aitgenne | veo-3.1-fast | Aitgenne / veo-3.1-fast | 视频 | Google 音视频待验证 | 待确认 | 待确认 | candidate | 官网模型广场待确认 |
| Aitgenne | happyhorse-1.0-i2v | Aitgenne / happyhorse-1.0-i2v | 视频 | happyhorse视频 | 待确认 | 适合单张九宫格图转视频 | enabled | 官网模型广场/用户确认 |
| Aitgenne | happyhorse-1.0-r2v | Aitgenne / happyhorse-1.0-r2v | 视频 | happyhorse视频 | 待确认 | 适合多参考图九宫格 | enabled | 官网模型广场/用户确认 |
| Aitgenne | omni-flash | Aitgenne / omni-flash | 视频 | 视频统一格式 | 待确认 | 适合 Omni 视频候选 | enabled | 官网模型广场/用户确认 |
| Aitgenne | speech-2.8-turbo | Aitgenne / speech-2.8-turbo | 语音 | MiniMax TTS | 待确认 | 待确认 | enabled | 现有 TTS 适配器 |
| OTU | gpt-image-2 | OTU / gpt-image-2 | 图片 | OTU /v1/videos JSON image task | 待确认 | 1K 图片主通道 | enabled | OTU /v1/models + 现有适配器 |
| OTU | gpt-image-2-2K | OTU / gpt-image-2-2K | 图片 | OTU /v1/videos JSON image task | 待确认 | 2K 图片主通道 | enabled | OTU /v1/models + 现有适配器 |
| OTU | gpt-image-2-4K | OTU / gpt-image-2-4K | 图片 | OTU /v1/videos JSON image task | 待确认 | 4K 图片主通道 | enabled | OTU /v1/models + 现有适配器 |
| OTU | omni_flash-10s | OTU / omni_flash-10s | 视频 | OTU /v1/videos multipart | 待确认 | 适合单图/Omni 视频 | enabled | OTU /v1/models |
| OTU | veo_3_1 | OTU / veo_3_1 | 视频 | OTU /v1/videos multipart | 待确认 | 适合图生视频 | enabled | OTU /v1/models |
| OTU | veo_3_1-fast-fl | OTU / veo_3_1-fast-fl | 视频 | OTU /v1/videos multipart | 待确认 | 首帧图生视频主通道 | enabled | OTU /v1/models + 现有适配器 |
| OTU | veo_3_1-fast-fl-hd | OTU / veo_3_1-fast-fl-hd | 视频 | OTU /v1/videos multipart | 待确认 | 高清首帧图生视频 | enabled | OTU /v1/models + UGC smoke |
| OTU | veo_3_1-fl | OTU / veo_3_1-fl | 视频 | OTU /v1/videos multipart | 待确认 | 首帧图生视频 | enabled | OTU /v1/models |
| OTU | veo_3_1-hd | OTU / veo_3_1-hd | 视频 | OTU /v1/videos multipart | 待确认 | 高清视频 | enabled | OTU /v1/models |
| OTU | veo_3_1-hd-fl | OTU / veo_3_1-hd-fl | 视频 | OTU /v1/videos multipart | 待确认 | 高清首帧图生视频 | enabled | OTU /v1/models |
