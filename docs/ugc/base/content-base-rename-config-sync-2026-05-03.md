# 内容链路表重命名与配置表回填记录（2026-05-03）

## Base

- Base token: `LBWUbgRfEavAgjsXNIhcpo0Dnvb`
- 原 UGC 表组已在飞书多维表格内重命名为“内容-xx”，用于承载 UGC / 非UGC 双模式内容生产链路。

## 表名变更

| table_id | 原表名 | 新表名 |
|---|---|---|
| `tblSPpWWOrnOzHSq` | `UGC-01 视频输入与分析表` | `内容-01 视频输入与分析表` |
| `tblbLHA2DyIwZHfF` | `UGC-02 脚本批次表` | `内容-02 脚本批次表` |
| `tblgDc6nuk6UWkLH` | `UGC-03 脚本版本表` | `内容-03 脚本版本表` |
| `tblkCASP9y1yZ1Sa` | `UGC-04 6宫格分镜表` | `内容-04 9宫格分镜表` |
| `tblW1KwMasPcXoaR` | `UGC-05 分镜图片表` | `内容-05 分镜图片表` |
| `tblP2WaylYun3Box` | `UGC-06 分镜视频表` | `内容-06 分镜视频表` |
| `tblwabgzemqbezVW` | `UGC-07 成片合成表` | `内容-07 成片合成表` |

> 代码中的 table_id 和部分函数/字段兼容名暂未整体重命名；运行仍依赖稳定 table_id。后续做代码双模式改造时再逐步把用户可见文案从 UGC 迁移到“内容”。

## 配置表处理

配置表：`初始化-模型与API配置` / `tblPUVFtpjogYOGn`

### 已回填 UGC/内容共用提示词

- `UGC-脚本生成`：从 `docs/prompts/ugc-script-generation-system-prompt-v1.md` 回填。
- `UGC-6宫格分镜图生成`：从 `docs/prompts/ugc-6-grid-storyboard-system-prompt-2026-04-30.md` 回填；业务语义为 3×3 9宫格动态有效镜头数。
- `UGC-分镜图片高清化`：从当前生产代码 `build_enhance_prompt()` 口径回填；UGC 与非UGC共用。
- `UGC-视频提示词生成`：从 `docs/prompts/ugc-image-to-video-system-prompt-2026-05-02.md` 回填。

### 新增 / 更新配置记录

- `UGC-9宫格分镜图拆分`：新增；提示词沉淀在 `docs/prompts/content-nine-grid-split-system-prompt-2026-05-03.md`。本环节只做本地裁切/上传/写表，不调用模型；UGC 与非UGC共用。
- `非UGC-爆款视频分析`：已写入用户提供并适配后的正式 prompt；本地镜像为 `docs/prompts/non-ugc-animation-video-analysis-system-prompt-v1.md`。关键输出为 `JSON_OUTPUT.script_generation_handoff`，供后续脚本生成读取。
- `非UGC-脚本生成`：已写入用户提供并适配后的正式 prompt；本地镜像为 `docs/prompts/non-ugc-animation-script-generation-system-prompt-v3-content.md`。已从 `ANI-*` 改为 `内容-01~03`，镜头数为动态 N（1-9，默认优先 5-6）。
- `非UGC-9宫格分镜图生成`：已写入用户提供并适配后的正式 prompt；本地镜像为 `docs/prompts/non-ugc-animation-nine-grid-storyboard-system-prompt-v1-content.md`。业务语义为固定 3×3 9宫格容器 + 第1-N格 active panels + 第 N+1 到第9格 white inactive placeholders。
- `非UGC-视频提示词生成`：已写入用户提供并适配后的正式 prompt；本地镜像为 `docs/prompts/non-ugc-animation-image-to-video-system-prompt-v1-content.md`。只为 N 个 active panels 生成 N 条 `video_clips`，inactive placeholders 不进入视频。
- `非UGC-分镜视频生成`：新增记录，继承 UGC 分镜视频生成模型/API 配置；实际单镜头 prompt 来自上一环节。

## 当前口径

- UGC / 非UGC 分流环节：爆款视频分析、脚本生成、9宫格分镜图生成、视频提示词生成、分镜视频生成。
- 共用环节：9宫格拆分、分镜图片高清化、成片合成。
- UGC 与非UGC 的 9宫格下游保持同一动态 N 规则：容器固定 9 格，active shots 数量 N 由脚本/分镜决定，N 范围 `1-9`，默认通常 `5-6`；inactive white placeholders 只用于补齐画布，不进入视频提示词或图生视频。
- 飞书配置表是运行时真源；本地 `docs/prompts/*.md` 是版本管理/人工审阅镜像。若直接在飞书配置表修改 prompt，需用同步脚本拉回本地，避免后续本地旧稿覆盖线上。

## Prompt 同步脚本

为避免“飞书配置表已改、本地 Markdown 未同步”或“本地旧稿误覆盖飞书”的问题，已新增同步工具：

```bash
# 列出支持的环节与本地文件映射
python3 tk_toolkit_dual/prompt_config_sync.py list

# 从飞书配置表拉取到本地；先 dry-run，再确认覆盖
python3 tk_toolkit_dual/sync_prompt_from_feishu.py 非UGC-视频提示词生成 --dry-run
python3 tk_toolkit_dual/sync_prompt_from_feishu.py 非UGC-视频提示词生成

# 从本地推送到飞书；默认 dry-run，加 --write 才写回
python3 tk_toolkit_dual/sync_prompt_to_feishu.py 非UGC-视频提示词生成
python3 tk_toolkit_dual/sync_prompt_to_feishu.py 非UGC-视频提示词生成 --write
```

同步脚本会保留提示词原文，包括末尾换行；不要手工 `.strip()` prompt 内容。
