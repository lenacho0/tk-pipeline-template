# 全局 AI 模型接入与表格选项治理计划

日期：2026-05-30
适用范围：TK 爆款视频生产链路中的文本、图片、视频模型选择与路由治理。

## 1. 背景与目标

当前多图九宫格视频生成表已经暴露出一个全局问题：模型下拉选项来自旧的通用 `AI_MODEL_OPTIONS`，没有按供应商、能力类型、真实 API 支持情况拆分，导致：

- 图片字段里只出现少量旧选项，且混入文本/视频模型。
- 视频字段没有完整体现 OTU、AIHubMix、Aitgenne 的可用视频模型。
- 不同表格各自维护模型选项，后续会持续漂移。
- 有些模型接口能查到，有些只在官网模型广场展示，不能只依赖单一来源。

目标是建立一套全局可复用的模型 catalog 和路由规则，供以下表格统一使用：

- 多图九宫格视频生成表
- 001-故事板图片视频生成表
- 002-首尾帧视频生成表
- 003-3脚本文档-分镜生产表
- 001-多角色首尾帧生成表
- 后续所有需要文本/图片/视频 AI 路由的生产表

## 2. 已确认的接口事实

已只读拉取过以下接口，没有写表、没有改代码：

- `OTU /v1/models`：可拉通，返回 17 个模型。
- `AIHubMix /v1/models`：可拉通，返回 229 个模型。
- `Aitgenne /v1/models`：可拉通，返回 453 个模型。

重要纠偏：

- Aitgenne `/v1/models` 本次没有返回 `veo` 相关模型。
- 但 Aitgenne 官网模型广场 / pricing 页面显示 Google 音视频分类下支持 VEO 系列和 `omni-flash`。
- 因此 Aitgenne 模型 catalog 不能只以 `/v1/models` 为唯一真源；需要同时抓取官网模型广场 / pricing 页面，确认真实模型 ID、标签、价格、能力类型和 API 调用方式。

## 3. 全局模型 Catalog 设计

新增一个全局模型 catalog，所有表格建表脚本、修表脚本、worker 路由逻辑都从这里取模型选项。

每个模型记录至少包含：

- `provider`：`OTU` / `AIHubMix` / `Aitgenne`
- `capability`：`文本` / `图片` / `视频` / `语音`
- `model`：真实提交给 API 的模型 ID
- `display_name`：飞书表格下拉展示名，例如 `OTU / gpt-image-2-2K`
- `endpoint_type`：接口类型，例如 `openai`、`happyhorse视频`、`image-generation`
- `status`：`enabled` / `candidate` / `disabled` / `deprecated`
- `source`：`/v1/models`、官网模型广场、手动验证、现有适配器
- `notes`：能力说明、限制、是否已 smoke test

生产表格下拉只展示：

- `status = enabled`
- 已有真实适配器，或已完成 smoke test 的模型

接口查到但未验证真实提交参数的模型只进入 `candidate`，不进入生产下拉。

## 4. 文本模型范围

保留：

- `AIHubMix / gemini-3.1-pro-preview`
- `Aitgenne / gpt-5.5`

待确认：

- `Aitgenne / gemini-3.1-pro-preview`

说明：

- 用户希望 Aitgenne 保留 `GPT5.5` 和 `Gemini 3.1 PRO preview`。
- 但本次 Aitgenne `/v1/models` 没有返回 `gemini-3.1-pro-preview`。
- 新线程需要验证它是否是隐藏可调用模型；确认前不要默认写入 `enabled`。

不保留旧文本模型：

- `gemini-2.5-flash`
- `gemini-2.5-pro-preview-05-13`
- `custom__aitgenne/gpt-5.4`
- 其他旧模型

## 5. 图片模型范围

用户明确要求：图片只接 GPT-image2 系列，不接 NanoBanana。

保留：

- `OTU / gpt-image-2`
- `OTU / gpt-image-2-2K`
- `OTU / gpt-image-2-4K`
- `AIHubMix / gpt-image-2`
- `Aitgenne / gpt-image-2`

不接：

- `nano_banana_2`
- `nano_banana_pro-1K`
- `nano_banana_pro-2K`
- `nano_banana_pro-4K`
- `gpt-image-2-free`
- `gpt-image-2-all`
- 其他泛图片模型

图片分辨率规则：

- OTU 不使用单独的“分辨率档位”做二次映射，直接选择最终模型：
  - `OTU / gpt-image-2` = 1K
  - `OTU / gpt-image-2-2K` = 2K
  - `OTU / gpt-image-2-4K` = 4K
- AIHubMix / Aitgenne 如果只有 `gpt-image-2` 一个模型，则通过 `图片画面尺寸` 或 `图片AI参数JSON` 传分辨率/尺寸参数。
- 不建议新增独立 `图片分辨率档位` 作为生产真源，避免与 `图片AI模型` 冲突。

## 6. 视频模型范围

### 6.1 OTU 视频模型

保留 `/v1/models` 已返回的 OTU 视频模型：

- `OTU / omni_flash-10s`
- `OTU / veo_3_1`
- `OTU / veo_3_1-fast-fl`
- `OTU / veo_3_1-fast-fl-hd`
- `OTU / veo_3_1-fl`
- `OTU / veo_3_1-hd`
- `OTU / veo_3_1-hd-fl`

不接：

- `OTU / veo_3_1-fast`
- `OTU / sora-2-12s`

原因：本次 OTU `/v1/models` 没有返回这两个模型。

### 6.2 AIHubMix 视频模型

保留：

- `AIHubMix / veo-3.1-fast-generate-preview`
- `AIHubMix / seeddance2.0`

不接：

- `AIHubMix / sora-2-pro`

原因：用户明确要求不接。

说明：

- AIHubMix `/v1/models` 本次没有返回 `veo / seeddance / sora` 视频模型。
- 但现有代码和配置已经有 `veo-3.1-fast-generate-preview`、`seeddance2.0` 相关适配经验。
- 新线程需要以现有适配器和 smoke test 为准，不要只看 `/v1/models`。

### 6.3 Aitgenne 视频模型

已确认保留：

- `Aitgenne / happyhorse-1.0-r2v`
- `Aitgenne / happyhorse-1.0-i2v`
- `Aitgenne / omni-flash`

HappyHorse 说明：

- `happyhorse-1.0-r2v`：参考生视频，描述支持最多 9 张参考图，最适合多图九宫格。
- `happyhorse-1.0-i2v`：图生视频，适合单张九宫格图转视频。
- `happyhorse-1.0-t2v`：文生视频，不适合当前九宫格主链路。
- `happyhorse-1.0-video-edit`：视频编辑，不适合生成主链路。

不接：

- `Aitgenne / kling-video`
- `Aitgenne / pixverse-video`
- `Aitgenne / MiniMax-Hailuo-2.3`
- `Aitgenne / wan2.6-i2v`
- `Aitgenne / sora-2`

原因：用户明确要求不接。

Aitgenne VEO 待确认：

- 用户在官网模型广场看到 Aitgenne 支持 Google VEO 系列和 `omni-flash`。
- `/v1/models` 未返回 VEO，因此新线程需要先抓取官网模型广场 / pricing 页面里的 Google 音视频模型。
- 先不要写表；先列出真实模型 ID、展示名、标签、价格和能力，再让用户筛选 2-4 个适合九宫格的 VEO 模型。

## 7. 推荐表格字段

所有需要 AI 路由的表统一使用能力分层字段。

文本/方案：

- `方案AI供应商`
- `方案AI模型`
- `方案AI参数JSON`

图片：

- `图片AI供应商`
- `图片AI模型`
- `图片画面比例`
- `图片画面尺寸`
- `图片AI参数JSON`

视频：

- `视频AI供应商`
- `视频AI模型`
- `视频时长秒`
- `视频画面比例`
- `视频画面尺寸`
- `视频AI参数JSON`

字段原则：

- `图片AI模型` 必须是最终可提交模型，不要让 OTU 通过另一个分辨率字段再隐式换模型。
- `视频AI模型` 只放经过筛选的生产候选，不把供应商返回的全部模型塞进下拉。
- `AI参数JSON` 只作为高级覆盖项，不作为普通用户必须填写字段。

## 8. 路由与适配器改造

新增全局模型路由层：

- `provider + capability + model` 唯一定位模型。
- 根据模型选择对应 adapter。
- 所有 adapter 输出统一 dry-run 摘要：
  - endpoint
  - method
  - payload keys
  - reference image count
  - seconds / size / aspect ratio
  - 是否真实提交

图片适配：

- OTU：复用 `/v1/videos` JSON 图像任务路径；gpt-image-2 图片参考图统一放在 `metadata.urls`，本地图片转完整 Data URL，不再使用顶层 `image_base64`。OTU 视频接口的 multipart 参考图另算。
- AIHubMix：需要确认 `gpt-image-2` 的实际图片生成端点和参数，不能只凭 `/v1/models` 进入生产。
- Aitgenne：`gpt-image-2` 文生图使用 JSON `POST /v1/images/generations`；带参考图时使用 multipart `POST /v1/images/edits`，重复字段名为 `image`，不提交内部 `metadata` / `input_mode`。

视频适配：

- OTU：复用现有 `/v1/videos` multipart，字段包括 `model`、`prompt`、`seconds`、`size`、`aspect_ratio`、`input_reference[]`。
- AIHubMix：复用现有 `veo` 和 `seeddance2.0` 适配器。
- Aitgenne：按 `supported_endpoint_types` 和官网模型广场接口拆适配器：
  - `happyhorse视频`
  - `视频统一格式`
  - 后续如确认 VEO，再新增 VEO 对应适配器

## 9. 表格迁移顺序

第一步：全局模型源治理

- 新增全局 catalog。
- 新增模型审计脚本，只读拉取 OTU / AIHubMix / Aitgenne 模型。
- 增加官网模型广场抓取逻辑，尤其是 Aitgenne Google 音视频页。
- 生成候选模型报告，先给用户确认。

第二步：配置表治理

- 更新 `初始化-模型与API配置` 中统一 AI 预设记录。
- 增加或规范模型状态：`enabled / candidate / disabled / deprecated`。
- 不复制、不输出任何 API Key。

第三步：九宫格表迁移

- 修正 `多图九宫格视频生成表` 的：
  - `方案AI模型`
  - `图片AI模型`
  - `视频AI模型`
- OTU 图片 1K/2K/4K 直接显示为不同模型选项。
- 视频模型只放已筛选列表。

第四步：其他表逐步迁移

- `001-故事板图片视频生成表`
- `002-首尾帧视频生成表`
- `003-3脚本文档-分镜生产表`
- `001-多角色首尾帧生成表`

迁移原则：

- 先同步字段选项。
- 不改变现有默认执行路径。
- 每张表迁移前备份字段结构。
- 迁移后确认已有记录不被覆盖。

## 10. 验证计划

只读审计：

- 拉取 OTU `/v1/models`。
- 拉取 AIHubMix `/v1/models`。
- 拉取 Aitgenne `/v1/models`。
- 抓取 Aitgenne 官网模型广场 / pricing 页面。
- 输出模型候选报告。

Dry-run：

- 每个 enabled 图片模型输出最终 endpoint 和 payload。
- 每个 enabled 视频模型输出最终 endpoint 和 payload。
- 确认参考图数量、尺寸、比例、时长等参数正确。

Smoke test：

- 图片：每家供应商至少 1 条最小任务。
- 视频：每家供应商先测 1-2 个代表模型。
- HappyHorse 优先测试：
  - `happyhorse-1.0-r2v`
  - `happyhorse-1.0-i2v`
- Aitgenne VEO 模型先只做接口确认和 dry-run，用户确认后再真实调用。

回归测试：

- 确认旧表默认路径不被破坏。
- 确认九宫格方案、生图、生视频三段路由正确。
- 确认字段下拉不出现禁用模型。
- 确认 API Key 不进入日志、代码、文档或聊天输出。

## 11. 关键注意事项

- 不要把供应商返回的全部模型直接写入飞书下拉。
- 不要把 `/v1/models` 当成 Aitgenne 的唯一真源，因为官网模型广场显示了额外的 VEO / Omni 模型。
- 不要开放未验证真实提交参数的模型。
- 不要让 OTU 图片同时受 `图片AI模型` 和 `图片分辨率档位` 两个字段控制。
- 不要接用户明确排除的模型：
  - `Aitgenne / kling-video`
  - `Aitgenne / pixverse-video`
  - `Aitgenne / MiniMax-Hailuo-2.3`
  - `Aitgenne / wan2.6-i2v`
  - `Aitgenne / sora-2`
  - `AIHubMix / sora-2-pro`
- 先做全局 catalog，再更新九宫格；不要继续在单表里硬编码模型列表。

## 12. 给新线程的首个任务建议

请新线程先执行下面这件事，不要直接写表：

1. 读取本计划。
2. 只读抓取 OTU、AIHubMix、Aitgenne `/v1/models`。
3. 抓取 Aitgenne 官网模型广场 / pricing 页面，重点是 Google 音视频分类。
4. 输出一份“可接入模型候选清单”，字段包括：
   - 供应商
   - 模型 ID
   - 展示名
   - 能力类型
   - 支持端点
   - 价格信息
   - 是否适合九宫格
   - 建议状态：`enabled` / `candidate` / `discard`
5. 等用户确认候选清单后，再进入代码和飞书表格更新。
