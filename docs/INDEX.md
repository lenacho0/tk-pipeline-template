# Workspace TK 文档索引

最后整理：2026-05-03

本目录按“当前 UGC 新链路 / 历史 TK pipeline / 旧 TikTok Bitable 方案 / 执行计划 / Prompt”重新归类。后续新增文档请优先放入对应子目录，避免根目录再次堆积。

---

## 当前重点：UGC 新链路

### `docs/ugc/base/`

UGC 正确 Base `LBWUbgRfEavAgjsXNIhcpo0Dnvb` 的表结构、字段和视图快照。

- `ugc-base-created-LBWU-2026-04-29.md`：正确 UGC Base 创建记录
- `ugc-base-fields-LBWU-2026-04-29.json`：正确 UGC Base 字段快照
- `ugc-base-table-ids-LBWU-2026-04-29.json`：正确 UGC Base 表 ID 映射
- `ugc-base-views-LBWU-2026-04-29.json`：正确 UGC Base 视图快照
- `content-base-rename-config-sync-2026-05-03.md`：UGC 表组重命名为 `内容-01~07` 后的配置表回填记录、非UGC prompt 写回状态、动态 N 口径和 prompt 同步脚本用法

注意：当前内容链路只能使用正确 Base `LBWUbgRfEavAgjsXNIhcpo0Dnvb`，不要使用误建 Base。

### `docs/ugc/workflow/`

UGC 链路设计、阶段说明和上下游衔接文档。

- `ugc-analysis-to-script-generation-v1.md`：UGC 分析结果到脚本生成的衔接设计
- `ugc-nine-grid-dynamic-shots-handoff-2026-05-01.md`：UGC 9宫格动态有效镜头数、无黑边裁切、参考重绘高清化的当前接力说明
- `ugc-one-click-reroll.md`：UGC-04 一键覆盖重生、UGC-05 审核闸门/单张重绘/高清化、UGC-06 单条视频重生的当前技术与操作口径
- `ugc-feishu-operation-manual-2026-05-03.md`：给同事使用的飞书多维表格视频生成操作手册，覆盖创建任务、审核状态、触发动作、返工入口和常见问题

---

## Prompt 文档

### `docs/prompts/`

系统提示词候选稿、正式稿和人工审核稿。

- `ugc-single-video-analysis-system-prompt-v1.md`：UGC 单条爆款视频分析 System Prompt
- `ugc-script-generation-system-prompt-v1.md`：UGC 脚本生成 System Prompt
- `ugc-6-grid-storyboard-system-prompt-2026-04-30.md`：UGC 9宫格动态分镜图生成 System Prompt（文件名保留旧称，内容已升级为 2026-05-01 v3 口径）
- `ugc-image-to-video-system-prompt-2026-05-02.md`：UGC 图生视频提示词 System Prompt
- `content-nine-grid-split-system-prompt-2026-05-03.md`：内容链路 9宫格拆分说明，UGC/非UGC 共用
- `non-ugc-animation-video-analysis-system-prompt-v1.md`：非UGC 动画爆款视频分析 System Prompt，已写回 `非UGC-爆款视频分析`
- `non-ugc-animation-script-generation-system-prompt-v3-content.md`：非UGC 动画脚本生成 System Prompt，已适配 `内容-01~03` 与动态 N
- `non-ugc-animation-nine-grid-storyboard-system-prompt-v1-content.md`：非UGC 动画 9宫格分镜图生成 System Prompt，已适配 3×3 容器 + 动态 active panels
- `non-ugc-animation-image-to-video-system-prompt-v1-content.md`：非UGC 动画图生视频提示词 System Prompt，已适配只为 N 个 active panels 生成 N 条 clips

约定：

- 当前内容链路的 Prompt 优先放这里。
- 飞书配置表是运行时真源；本地 doc 是版本管理/人工审阅镜像。
- 若直接在飞书配置表修改 prompt，应使用 `tk_toolkit_dual/sync_prompt_from_feishu.py <环节名>` 拉回本地。
- 从本地推送到飞书时先 dry-run，确认后再加 `--write`。
- 机器链路 Prompt 应优先采用 `JSON_OUTPUT + MARKDOWN_OUTPUT`，下游只消费 JSON。

---

## 执行计划

### `docs/plans/`

阶段实施计划和可执行 checklist。

- `2026-03-27-media-bulk-downloader.md`
- `2026-04-29-ugc-workflow-code-integration.md`
- `2026-04-30-ugc-accelerated-next-steps.md`
- `2026-05-01-ugc-nine-grid-dynamic-shot-count.md`
- `2026-05-02-ugc-reroll-regeneration.md`（历史方案：候选池，已被 2026-05-03 简化方案取代，仅作追溯）
- `2026-05-02-ugc-reroll-trigger-layer.md`（历史方案：候选池字段触发，已被一键覆盖/审核闸门取代）
- `2026-05-03-ugc-one-click-overwrite-reroll.md`
- `2026-05-03-ugc-confirmed-reroll-to-video-flow.md`
- `2026-05-03-prompt-config-sync.md`：飞书配置表 prompt 与本地 `docs/prompts/*.md` 同步脚本实施计划

---

## TK Pipeline 历史/运维/经验文档

### `docs/tk-pipeline/`

旧 TK pipeline、dual dispatcher、分镜一致性、上线状态、P0/P1 改造和经验复盘。

- `pipeline-migration-phase1.md`
- `storyboard-consistency-phase2.md`
- `tk-2026-03-28-rollout-status.md`
- `tk-dual-storyboard-plan-2026-03-25.md`
- `tk-editing-notes.md`
- `tk-p0-implementation-2026-03-28.md`
- `tk-pipeline-lessons-learned.md`
- `tk-pipeline-next-plan-2026-03-25.md`
- `tk-second-round-plan-2026-03-25.md`
- `tk-second-round-plan-2026-03-28.md`

---

## 旧 TikTok Bitable / 表6 / 方向B 文档

### `docs/tiktok-bitable-legacy/`

旧 TikTok Bitable 方案、表6 多版本脚本设计、方向 B 收口记录。此类文档保留用于参考，但不要直接作为 UGC 新链路依据。

- `tiktok-bitable-current-status-2026-04-21.md`
- `tiktok-bitable-direction-b-closure-plan.md`
- `tiktok-bitable-direction-b-final-closure.md`
- `tiktok-bitable-final-prompts-full.md`
- `tiktok-bitable-final-prompts-production.md`
- `tiktok-bitable-final-prompts.md`
- `tiktok-bitable-independent-project-boundary.md`
- `tiktok-bitable-table6-code-integration-plan.md`
- `tiktok-bitable-table6-field-spec.md`
- `tiktok-bitable-table6-implementation-todo.md`
- `tiktok-bitable-table6-multivariant-design.md`
- `tiktok-bitable-table6-prompt-input-protocol.md`
- `tiktok-bitable-workflow-prompts.md`

---

## 归档

### `docs/archive/wrong-ugc-base-2026-04-29/`

误建 UGC Base `Zgzqbp71zaFXgOs94l4c0nlVnef` 的历史记录和快照。仅作追溯，不得用于当前 UGC 代码和配置。

- `ugc-base-created-2026-04-29.md`
- `ugc-base-fields-2026-04-29.json`
- `ugc-base-table-ids-2026-04-29.json`

---

## 当前 UGC 运维/触发器说明

这些文件在 `tk_toolkit_dual/` 下，面向本机后台轮询器运维：

- `ugc_one_click_reroll_launchd.md`：UGC-04 一键重生成 9宫格触发器 `com.ryan.ugc-one-click-reroll`
- `ugc_review_trigger_launchd.md`：UGC-05 分镜图/高清图审核推进触发器 `com.ryan.ugc-review-trigger`
- `ugc_video_review_trigger_launchd.md`：UGC-06 分镜视频审核/单条重生触发器 `com.ryan.ugc-video-review-trigger`

---

## 后续维护约定

1. 新的执行计划放 `docs/plans/`。
2. 新的系统提示词放 `docs/prompts/`。
3. 当前 UGC 新链路文档放 `docs/ugc/`。
4. 当前 UGC 日常操作口径优先以 `docs/ugc/workflow/ugc-feishu-operation-manual-2026-05-03.md` 和 `docs/ugc/workflow/ugc-one-click-reroll.md` 为准。
5. 旧 pipeline 参考资料放 `docs/tk-pipeline/`。
6. 旧 TikTok Bitable / 表6 文档放 `docs/tiktok-bitable-legacy/`。
7. 误建、废弃但需要保留追溯的材料放 `docs/archive/`。
