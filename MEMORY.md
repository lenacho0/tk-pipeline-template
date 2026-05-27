# MEMORY.md - Long-Term Memory

## Identity & Setup

- Workspace initialized under OpenClaw with Feishu direct-chat as the main session context.
- User wants important conversation content summarized into memory files rather than left ephemeral.

## Preferences

- The user values durable memory: key discussion points, decisions, and preferences should be written down when asked.
- Prefer concise, useful summaries over verbose logging.
- When pipeline stages / naming /巡检口径 change, related daily healthcheck and monitoring descriptions should be updated together so old flow names do not linger and mislead.
- For risky pipeline/prompt changes that may affect script, storyboard, or video quality, prefer a shadow-test / parallel-test approach first: validate with small-sample offline outputs before modifying the formal production chain.

## 内容链路 / UGC 新链路长期记忆

### 2026-05-03 内容链路双模式与 prompt 配置

- 正确 Base 仍为 `LBWUbgRfEavAgjsXNIhcpo0Dnvb`；飞书表组用户可见名称已从 `UGC-01~07` 升级为 `内容-01~07`，用于承载 UGC / 非UGC 双模式内容生产。table_id 不变，代码中部分 `UGC` / `6宫格` 字段名是兼容名，业务口径以“内容链路”为准。
- 内容链路 9宫格规则统一：固定 3×3 9宫格容器，active shots 数量 `N` 由脚本/分镜动态决定，范围 `1-9`，默认通常 `5-6`；第 `N+1` 到第9格是 white inactive placeholders，只用于补齐画布，不进入视频提示词或图生视频。
- 非UGC 四个核心 prompt 已由用户提供并写回配置表：`非UGC-爆款视频分析`、`非UGC-脚本生成`、`非UGC-9宫格分镜图生成`、`非UGC-视频提示词生成`。本地镜像分别为 `docs/prompts/non-ugc-animation-video-analysis-system-prompt-v1.md`、`non-ugc-animation-script-generation-system-prompt-v3-content.md`、`non-ugc-animation-nine-grid-storyboard-system-prompt-v1-content.md`、`non-ugc-animation-image-to-video-system-prompt-v1-content.md`。
- 非UGC prompt 已从旧 `ANI-*` 链路名适配为 `内容-01~07`：分析输出 `JSON_OUTPUT.script_generation_handoff`；脚本生成读取该 handoff 并输出动态 `effective_shot_count=N`；9宫格分镜生成第1-N格 active、第N+1到9格白色 inactive；视频提示词只为 N 个 active panels 生成 N 条 `video_clips`。
- 飞书配置表是运行时 prompt 真源；本地 `docs/prompts/*.md` 是版本管理/人工审阅镜像。若用户直接在飞书配置表修改 prompt，应运行 `python3 tk_toolkit_dual/sync_prompt_from_feishu.py <环节名>` 拉回本地；从本地推送到飞书用 `sync_prompt_to_feishu.py <环节名>` 先 dry-run，加 `--write` 才写回。

### 2026-04-29 UGC 新链路关键决策

- UGC 新链路使用正确 Base `LBWUbgRfEavAgjsXNIhcpo0Dnvb` 的独立 UGC 表组：`UGC-01` 到 `UGC-07`，不要接入误建 Base `Zgzqbp71zaFXgOs94l4c0nlVnef`。
- 后续所有 UGC 代码和文档只允许使用 UGC 自己的表名、状态、环节名；不要再出现其他项目/旧链路/表6/旧输入/表2/共性分析等说法，避免误导。
- 产品输入口径：用户只在 `UGC-01 视频输入与分析表` 选择一次 `关联产品`，关联到 `初始化-产品信息`；后续 `UGC-02/03` 仅系统继承/只读展示，代码以 `UGC-01.关联产品` 为产品真源。
- UGC 日常视图已分层：用户主要使用 `UGC-01.01-用户填写入口`、`UGC-01.02-分析结果审核`、`UGC-03.01-脚本审核选择` 和下游 `01-结果查看`；`99-*` 仅系统排错。
- UGC 脚本版本的 `主测试点` 由系统创建版本任务时自动填写；`standard` 只用于单脚本、handoff 不足或调试兜底，多版本不应全部使用 `standard`。

### 2026-04-30 至 2026-05-01 UGC 链路进展与当前接力点

- `爆款视频分析-UGC` / Aitgenne `gemini-3.1-pro-preview` 已验证可用；真实 UGC-01 记录 `recvia7bZjgXMZ` 的 TikTok 链接下载、产品关联读取、inline 视频分析、JSON/MARKDOWN 解析、真实写回已闭环。
- UGC-01 `recvia7bZjgXMZ` 已派生 UGC-02 批次 `recvieE32pYunq` / `UGC-BATCH-20260430095506-ZjgXMZ`，并创建 3 条 UGC-03 脚本版本：`recvieE3B2omPp`、`recvieE49S7hNC`、`recvieE4zrzYnX`；第一条 `recvieE3B2omPp` 已完成脚本生成真实写回。
- 2026-05-01 已将 UGC 分镜图路线从“固定 6宫格 / 固定 6 shots”升级为“固定 3×3 9宫格容器 + 动态有效镜头数 N（1-9，默认 5-6）”；字段名暂保留 `6宫格...`，业务语义已升级。
- 已实现并验证 `tk_toolkit_dual/tk_ugc_script_generate.py`、`tk_ugc_six_grid.py`、`tk_ugc_shot_images.py`：脚本生成支持动态 N；UGC-04 固定 9宫格容器、inactive cells 本地刷白、比例校验；UGC-05 只为 active panels 建记录。
- 真实 UGC-04 `recvimPkZjza7b` 基于 UGC-03 `recvieE3B2omPp` 跑通：OTU `gpt-image-2` 返回 `941x1672`，总图和单格均接近 9:16，inactive grids `[7,8,9]` 已刷白。
- 9宫格黑框问题已修复：prompt 禁止边框/分割线，UGC-05 新增 `inset_cell_box()` 轻微内缩裁切作为兜底，避免黑线进入单张分镜图和后续视频。
- UGC-05 高清化已采用用户确认更好的方案 A：无黑边 crop 作为主构图参考、完整 9宫格作为一致性参考、精简 shot prompt 作为语义约束，通过 OTU `metadata.urls` + `gpt-image-2` 参考重绘，再本地适配为 `1080x1920`。
- 推荐下次从这 6 条新 UGC-05 高清记录继续进入 UGC-06：`recvin7kJqxQuo`、`recvin7Er2INZu`、`recvin861Zu2yh`、`recvin8p8l8dx0`、`recvin8FNrUi0W`、`recvin8XX3Z0Iw`；不要优先使用旧的 resize 分镜记录。
- UGC-06 下一步 blocker/注意点：`UGC-06 分镜视频表` 的 `高清分镜图` / `分镜视频` 附件字段此前仍可能是扫码限制；继续前先检查字段 meta。如仍受限，要么在飞书 UI 修改上传属性，要么给 UGC-06 加文本 file_token/path/url 兜底字段。
- API 口径：Aitgenne 文本链路用于 `UGC-脚本生成` / `UGC-视频提示词生成`；OTU 图片/图生图使用 JSON `POST /v1/videos` + `metadata.urls`；OTU Veo 图生视频必须使用 `multipart/form-data` + `input_reference[]` 传首帧/参考帧，不能用图片高清化的 JSON `metadata.urls`。
- 交接文档：`docs/ugc/workflow/ugc-nine-grid-dynamic-shots-handoff-2026-05-01.md`；实施计划：`docs/plans/2026-05-01-ugc-nine-grid-dynamic-shot-count.md`；prompt 审核稿：`docs/prompts/ugc-6-grid-storyboard-system-prompt-2026-04-30.md`（文件名保留旧称，内容已升级为 2026-05-01 v3）。

### 2026-05-02 UGC 单镜头视频、成片合成与 reroll 触发层

- UGC-06 图生视频提示词链路已落地：新增 `tk_toolkit_dual/tk_ugc_video_prompts.py` / `test_ugc_video_prompts.py`，基于 UGC-05 高清分镜图生成结构化 `video_prompt_batch` 与 `shot_video_prompts`，默认 dry-run，不调用视频模型；提示词系统稿为 `docs/prompts/ugc-image-to-video-system-prompt-2026-05-02.md`，并已同步写入配置表 `recvieU4If1fMD`。
- 已从 6 条 UGC-05 高清记录创建 6 条 UGC-06 提示词记录：`recviqdQNUCITK`、`recviqdRegrc0I`、`recviqdRCF7vB4`、`recviqdS12ne1Y`、`recviqdSrQPN6A`、`recviqdSPPUiSG`；后续真实视频均基于这批记录推进。
- UGC-06 首条真实图生视频 smoke test 已成功：`recviqdQNUCITK` 使用配置 `recvieU5aB4Yxw` / `UGC-分镜视频生成` / `veo_3_1-fast-fl-hd` / `https://otuapi.com/`，按 `multipart/form-data` + `input_reference[]` 调 OTU/Veo，生成任务 `task_LINxMa5dIlPomFPxZVFPDpAQWVK99NDi`，本地视频 `/Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit_dual/workspace_ryan/ugc_shot_video_work/recviqdQNUCITK/recviqdQNUCITK_video.mp4`，飞书 file_token `LST2bzIAFoX4PqxbTmYcdbyanre`。
- 首条 UGC-07 成片合成已跑通并随后修正音频口径：最初 `tk_ugc_final_concat.py` 使用 `-an` 导致无声；用户纠正后确认 6 条 UGC-06 Veo 片段均自带 AAC 音轨。现已改为保留 Veo 原始音轨、无 TTS、无替换音轨；带音频成片记录 `recvirbcn7OHwH` / 任务 `UGC-FINAL-20260502132203-NUCITK` / 飞书附件 `RxY2bdSnHoy7zlxhK9vczT8pngd` / 上传文件 `UGC-FINAL-20260502132203-NUCITK_with_audio_feishu.mp4`。
- UGC-07 口径必须保持：UGC-06/Veo 直接生成最终本土语言口播音频；UGC-07 只保留并拼接 Veo 原始音轨，不做 TTS；源片段缺音频时最多补静音 AAC 轨用于 concat 一致性，不得生成或替代口播。
- 2026-05-02 曾落地过 reroll/regeneration 候选池方案，但该方案已在 2026-05-03 被用户明确否定为过于复杂；相关候选池字段/视图已从飞书 Base 删除，日常链路不得再使用 `重生成组ID`、`候选序号`、`候选状态`、`重新生成请求/数量`、`02-*候选池`、`03-重新生成入口` 等旧入口。
- `lark-cli` 已由 `1.0.16` 升级到 `1.0.23`，路径 `/Users/ryanlynn/.nvm/versions/node/v24.14.0/bin/lark-cli`；但当前 shell 直接调用 `lark-cli` 可能仍显示未配置，应优先使用项目内 Feishu API 工具/脚本或确认 CLI 配置后再用。

### 2026-05-03 UGC 审核闸门、一键覆盖重生与同事操作手册

- UGC 返工入口已改为“简单字段入口 + 本地 launchd 轮询触发器”：UGC-04 `一键重生成9宫格` 覆盖重生当前 9宫格并同步刷新 UGC-05；UGC-05 负责单张分镜图审核、单张重绘、高清化、重新高清化和触发分镜视频；UGC-06 负责单条分镜视频审核与单条视频覆盖重生。
- 当前日常确认链路：UGC-04 生成/重生 9宫格 → 自动拆分 UGC-05 → 用户在 UGC-05 `01-分镜图确认` 审核；满意则 `分镜图审核状态=通过` + `分镜图操作=确认分镜图并高清化`，不满意则 `分镜图操作=重新生成单张分镜图`；高清图在 `02-高清图确认` 审核，满意则 `高清图操作=生成分镜视频`，不满意则 `高清图操作=重新高清化`；UGC-06 视频不满意则 `分镜视频操作=重新生成分镜视频`。
- 已补齐 UGC-05/UGC-06 审核字段和单选选项：审核状态统一 `待确认/通过/不通过`；操作字段统一从 `不触发` 进入明确动作；执行状态统一 `待处理/处理中/成功/失败`。不要让用户手填自由文本状态。
- 已安装三个本地 launchd 触发器：`com.ryan.ugc-one-click-reroll`（UGC-04，每 60 秒）、`com.ryan.ugc-review-trigger`（UGC-05，每 60 秒）、`com.ryan.ugc-video-review-trigger`（UGC-06，每 60 秒）。真实模型调用仍由脚本中的 `--call-models` 安全闸门控制，只有明确动作字段命中才会烧模型。
- UGC-06 视频覆盖重生必须走 `tk_ugc_video_review_trigger.py`，该路径会调用 `run_ugc06_video_generation(..., allow_overwrite=True)`；底层 `run_ugc06_video_generation()` 默认仍拒绝对成功记录重复生成，防止误烧视频模型。
- UGC-07 仍不自动重跑：所有 UGC-06 分镜视频人工确认后，再手动/明确触发成片合成；成片合成继续保留 Veo 原始音轨，不做 TTS、不替换口播。
- 给同事的主操作手册：`docs/ugc/workflow/ugc-feishu-operation-manual-2026-05-03.md`；一键覆盖与审核触发说明：`docs/ugc/workflow/ugc-one-click-reroll.md`；launchd 说明：`tk_toolkit_dual/ugc_one_click_reroll_launchd.md`、`tk_toolkit_dual/ugc_review_trigger_launchd.md`、`tk_toolkit_dual/ugc_video_review_trigger_launchd.md`。

## TK Pipeline / 历史链路记忆

- 2026-05-28: `001-故事板图片视频生成表` 的提示词口径已被用户明确收紧：故事板图片最终 prompt 与 Omni 视频最终 prompt 都以配置表系统提示词/模型直出内容为真源，代码不得再擅自追加产品、时间段、参考图顺序、故事板上下文、额外视频方向或任何“补强规则”。若需要改提示词内容，必须先向用户确认，再改 `初始化-模型与API配置` 的对应 `提示词`。当前 Omni 视频 prompt 只做 Markdown 外壳解析，剥离代码块和 `Omni Video Prompt:` 标题后原文提交 API。
- 2026-05-21: 003-3 与脚本文档分镜视频新增 OTU 视频通道。正式链路已改成 `视频通道` 决定平台、`视频生成模型` 决定具体模型：`AIHubMix` 继续走原有 AihubMix/Gemini/SeedDance 路径，`OTU` 走独立 `/v1/videos` submit/poll/download。脚本文档分镜生成与三表 schema 已补 `视频通道` 字段；OTU 配置记录已写入飞书配置表，模型为 `veo_3_1-fast-fl`。线上旧 `视频生成模型` select 字段通过 OpenAPI 更新受限，代码已兼容 OTU 模型值，UI 如需完整选项同步，可能需要在飞书页面手动补一次。
- 2026-05-20: 003-3 逐镜头分镜视频生成已从 AIHubMix `/v1/videos` multipart `input_reference[]` 参考图路径修正为 Gemini native Veo 首帧路径。正式 worker `tk_toolkit_dual/tk_shot_video.py` 现在通过 Google GenAI SDK 调 `client.models.generate_videos(image=types.Image(...), config=GenerateVideosConfig(resolution="720p", aspect_ratio="9:16"))`，只把 003-3 `分镜图` 作为首帧，不传尾帧，不传 `referenceImages`；`/v1/videos` 旧路径实测会产出横屏 `1280x720`，不得再作为 003-3 首帧模式正式路径。配置表记录 `recvk4lsU0TGGD` 的代理地址已改为 `https://aihubmix.com/gemini`，模型为 `veo-3.1-fast-generate-preview`。smoke test 记录 `recvk2MLFnjq1K` 已成功生成竖屏视频，本地路径 `/Users/ryanlynn/.openclaw/workspace-tk/shot_video_work/recvk2MLFnjq1K/recvk2MLFnjq1K_video.mp4`，飞书 file_token `UJAVbECCRoUE4UxUtEtc1YC7nNc`，`ffprobe` 为 `720x1280`、`4.000000s`。
- 2026-05-20: 脚本文档逐分镜链路已从 78 字段单表拆成三表：`脚本文档-任务表` `tblBC37ktQBHPLep`、`脚本文档-参考资产表` `tblFg33rvB7eCyzr`、`脚本文档-分镜生产表` `tbldPJLJhczlGzSt`。配置 keys 为 `script_doc_tasks`、`script_doc_reference_assets`、`script_doc_shots`，其中 `script_doc_shots` 指分镜生产表。正式逻辑：解析从任务表读取，参考资产/分镜分别写入独立表；分镜图生成从任务表取父任务和产品关联，从参考资产表取已审核底图；dispatcher 5 个脚本文档 watch 已按表拆分并重启 ryan 实例。
- 2026-05-20: 脚本文档三表链路真实 smoke test 已跑通。任务 `recvk8uUo5tb4o` 解析出 2 个参考资产与 2 条分镜；分镜 1 `需要产品参考图=否`、分镜图 reference_count=2；分镜 2 `需要产品参考图=是`、分镜图 reference_count=3、口播与 Veo 视频成功。视频本地 `/Users/ryanlynn/.openclaw/workspace-tk/shot_video_work/recvk8vXL2JSsU/recvk8vXL2JSsU_video.mp4`，file_token `C3UGbM8Olox6UTxBoSlctsnon04`，`ffprobe` 为 `720x1280`、`4.000000s`。本轮顺手修复：参考图下载函数返回布尔 `True` 时的路径处理，以及 URL 字段裸字符串写回导致的 `URLFieldConvFail`。
- 2026-03-28: TK pipeline 第二轮优化已从方案阶段进入真实落地阶段。
- 已完成 dispatcher 第一轮硬化、扫描减负第一刀、runtime log 独立化,以及多个关键脚本的标准错误输出协议统一。
- 后续默认沿"低风险收口 → 小批量真实验证 → 再推进更正式批量能力/状态机/批次语义"路线继续推进。
- 2026-03-30: colleague 新双表流程已完成真实链路贯通验证,并在运行时层面完成切换:旧单表 dispatcher `com.ryan.tk-dispatcher` 已停用,正式常驻实例收口为 dual 的 `com.ryan.tk-dispatcher.ryan` 与 `com.ryan.tk-dispatcher.colleague`。
- 2026-03-30: 双表流程两类关键问题已明确并修复到可运行状态:其一,`tk_analyze.py` 在 colleague 线上因 4 并发 + 900 秒超时导致批量超时,已调整为 1 并发 + 2400 秒;其二,`003-2` 不触发的根因不是表/字段错误,而是 dual colleague dispatcher 未正确接管、旧实例混跑造成状态污染。
- 2026-04-01: `003视频生成` / `seeddance2.0` 再次定位到真实运行根因:Creaa 返回里已有 `result_url`,但 `tk_toolkit_dual/tk_video_from_storyboard.py` 的 `extract_seeddance_video_url(result)` 早前未兼容 `result_url`,从而误报"未返回可下载视频地址"。现已补上 `result_url` / `download_url` / `data.*` / `output.*` / `result_urls` 兼容,并提交 `5b7892f Harden SeedDance video result parsing`。
- 2026-04-01: 为避免再次把"上游已成功生成视频"和"本地下载/飞书回写失败"混成同一种失败,`tk_toolkit_dual/tk_video_from_storyboard.py` 已新增 `upstream_completed` 语义分支;若上游成功后半段再失败,飞书会明确写成 `错误[UPSTREAM_COMPLETED_LOCAL_WRITEBACK_FAILED] ...`。提交:`860ee84 Differentiate upstream success from writeback failure`。
- 2026-04-01: `003视频生成` 重新触发问题与 dispatcher watch 配置无关;`status_field: '视频生成状态'` 配置本身正确。实际受 table cache 与 `/Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit_dual/.circuit_breakers.ryan.json` 熔断冷却共同影响。
- 2026-04-01: 用户明确要求双语脚本里"泰文口播 = 最终视频唯一配音稿;中文 = 仅供翻译/阅读检查,不得进入视频生成或TTS"。该约束已补入 `tk_toolkit_dual/tk_script_gen.py`,commit: `16dd5fd Clarify Thai-only voiceover in script prompts`。
- 2026-04-01: `分镜图生成` 新暴露出同类双语输入问题:`tk_toolkit_dual/tk_storyboard.py` 原先会把双语脚本原样送入分镜规划,`recvfvYTrwsHpA` 连续 3 次报 `MODEL_EMPTY_OUTPUT`。现已改为在 storyboard prompt 前自动剔除 `口播(中文)` 行,仅保留泰文口播,commit: `9633168 Ignore Chinese translation in storyboard prompts`。
- 2026-04-01: 配置表里 `九宫格生成视频-seeddance2.0` 的 `提示词` 一度为空;已按当前运行中的最新版本与 `九宫格生成视频-sora` / `九宫格生成视频-grok` 对齐,确保视频任务继续保持"执行时优先从配置表读取提示词"的逻辑。
- 2026-04-02: 用户明确要求每日巡检与监控口径同步跟进最新功能命名。已将 `tk_toolkit_dual/tk_dispatcher.py` 中旧 `003视频生成` 监控名称改为 `九宫格生成视频`(commit: `bd97d4c`),并在 `tk_toolkit_dual/tk_healthcheck.py` 新增 `九宫格生成视频` 专项检查:校验 `九宫格生成视频-grok` / `-sora` / `-seeddance2.0` 三条配置的 `模型名称`、`API Key`、`API 代理地址`、`提示词` 是否完整,同时对"名称含 `视频生成` 但不属于 `九宫格生成视频-*`"的旧配置残留直接报异常(commit: `46acfeb`)。
- 2026-04-02: 用户要求将 ryan 本轮更新完整同步到 colleague。已补齐 colleague 配置表中的 `九宫格生成视频-grok` / `-sora` / `-seeddance2.0` 三条视频环节，删除旧 `视频制作`，补齐 003 产品脚本分镜图生成表中的视频相关字段并保持字段类型与 ryan 一致；随后执行全量对齐审计，确认 colleague 在关键运行配置、关键表结构、关键环节配置层面已与 ryan 对齐。需注意：该"对齐"指运行/结构层面，不代表历史业务记录逐条一致。
- 2026-04-03: 宠物拟人参考视频深拆链路新增 `完整JSON分析结果-中文翻译` 字段后,联调中暴露出"主流程成功但翻译静默失败"的问题;根因不是飞书字段或 dispatcher 触发本身,而是两处翻译链路代码缺失 `json` 依赖:一处在 `tk_toolkit_dual/tk_pet_reference_analyze.py`,另一处在 `tk_toolkit_dual/pet_reference_prompt.py` 的 `build_pet_reference_translation_prompt`。补齐后重新触发,中文翻译 JSON 已可正常写回。
- 2026-04-03: 用户进一步指出脚本生成链路存在更上游的语义缺口:当前脚本(含手写整理/改写、默认生成、宠物拟人参考生成)未明确标注"谁在说 / 是否需要画面内说话 / 是否旁白 / 是否静默动作镜头",导致后续分镜与视频生成默认退化成画外音旁白,难以实现宠物或人类在画面中开口说话。对此已达成方向性方案:不要全局强制 `speaker`,而是引入统一的结构化脚本片段类型 `content_type`,固定区分 `dialogue` / `voiceover` / `silent_action`;只有 `dialogue` 才要求明确说话主体并在下游触发可见说话主体与口型/讲话表情约束。
- 2026-04-03: 用户明确要求先做"结构化脚本影子测试",而不是直接改正式链路。测试方案为:单独做独立脚本(建议名 `tk_toolkit_dual/test_structured_script_shadow_flow.py`),输入已有脚本,输出结构化脚本 JSON、基于结构化结果生成的分镜提示词、基于结构化结果生成的视频提示词与 markdown 报告;首轮先准备 6 条样本(对白主导 2、混合型 2、旁白主导 1、静默/氛围主导 1),先人工审结果,再只挑 3 条去试跑真实分镜/视频,确认方向正确后再考虑正式代码接入。
- 2026-04-07: 将 `宠物拟人参考视频深拆` 的视频分析提示词（build_pet_reference_prompt 的内容，约 2913 字）写入配置表记录 `recvfwvrAMAa0K`（环节=宠物拟人参考视频深拆，提示词字段）。此前该字段为空，导致运行时代码 fallback 到脚本内 hardcoded prompt。
- 2026-04-07: 结构化脚本影子测试验证：生成 grid prompt 时不能用简化模板，必须用配置表完整 prompt 约束体系（CL1-CL5）；`content_type` 分类（dialogue/voiceover/silent_action）有效。
- 2026-04-07: `tk_script_gen.py` / `tk_storyboard.py` 已完成 `content_type` 结构化改造；宠物拟人路径 `speaker_visible=true` 强制开口说话修复（commit `d152edf`）；双实例 ryan/colleague 共用同一套代码。
- 2026-04-08: colleague 脚本表 `tblmunPoOWHcAr7i` 曾缺少 `结构化脚本JSON`、`参考视频记录ID`、`脚本生成模式` 三个字段；手动补齐后对齐 ryan 的 31 字段。
- 2026-04-08: aihubmix `doubao-seedance-2-0-fast-260128` 接入代码改动已完成但平台存在 bug：提交瞬间参数正确，aihubmix 内部轮询时被覆盖为默认值（5s、1920×1080、prompt 空），实际视频内容与提交参数无关；建议用 grok 或 sora（own-jarvis-api.com）作为主视频模型。
