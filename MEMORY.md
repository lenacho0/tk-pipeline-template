# MEMORY.md - Long-Term Memory

## Identity & Setup

- Workspace initialized under OpenClaw with Feishu direct-chat as the main session context.
- User wants important conversation content summarized into memory files rather than left ephemeral.

## Preferences

- The user values durable memory: key discussion points, decisions, and preferences should be written down when asked.
- Prefer concise, useful summaries over verbose logging.
- When pipeline stages / naming /巡检口径 change, related daily healthcheck and monitoring descriptions should be updated together so old flow names do not linger and mislead.

## Ongoing Project Memory

- 2026-03-28: TK pipeline 第二轮优化已从方案阶段进入真实落地阶段。
- 已完成 dispatcher 第一轮硬化、扫描减负第一刀、runtime log 独立化，以及多个关键脚本的标准错误输出协议统一。
- 后续默认沿“低风险收口 → 小批量真实验证 → 再推进更正式批量能力/状态机/批次语义”路线继续推进。
- 2026-03-30: colleague 新双表流程已完成真实链路贯通验证，并在运行时层面完成切换：旧单表 dispatcher `com.ryan.tk-dispatcher` 已停用，正式常驻实例收口为 dual 的 `com.ryan.tk-dispatcher.ryan` 与 `com.ryan.tk-dispatcher.colleague`。
- 2026-03-30: 双表流程两类关键问题已明确并修复到可运行状态：其一，`tk_analyze.py` 在 colleague 线上因 4 并发 + 900 秒超时导致批量超时，已调整为 1 并发 + 2400 秒；其二，`003-2` 不触发的根因不是表/字段错误，而是 dual colleague dispatcher 未正确接管、旧实例混跑造成状态污染。
- 2026-04-01: `003视频生成` / `seeddance2.0` 再次定位到真实运行根因：Creaa 返回里已有 `result_url`，但 `tk_toolkit_dual/tk_video_from_storyboard.py` 的 `extract_seeddance_video_url(result)` 早前未兼容 `result_url`，从而误报“未返回可下载视频地址”。现已补上 `result_url` / `download_url` / `data.*` / `output.*` / `result_urls` 兼容，并提交 `5b7892f Harden SeedDance video result parsing`。
- 2026-04-01: 为避免再次把“上游已成功生成视频”和“本地下载/飞书回写失败”混成同一种失败，`tk_toolkit_dual/tk_video_from_storyboard.py` 已新增 `upstream_completed` 语义分支；若上游成功后半段再失败，飞书会明确写成 `错误[UPSTREAM_COMPLETED_LOCAL_WRITEBACK_FAILED] ...`。提交：`860ee84 Differentiate upstream success from writeback failure`。
- 2026-04-01: `003视频生成` 重新触发问题与 dispatcher watch 配置无关；`status_field: '视频生成状态'` 配置本身正确。实际受 table cache 与 `/Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit_dual/.circuit_breakers.ryan.json` 熔断冷却共同影响。
- 2026-04-01: 用户明确要求双语脚本里“泰文口播 = 最终视频唯一配音稿；中文 = 仅供翻译/阅读检查，不得进入视频生成或TTS”。该约束已补入 `tk_toolkit_dual/tk_script_gen.py`，commit: `16dd5fd Clarify Thai-only voiceover in script prompts`。
- 2026-04-01: `分镜图生成` 新暴露出同类双语输入问题：`tk_toolkit_dual/tk_storyboard.py` 原先会把双语脚本原样送入分镜规划，`recvfvYTrwsHpA` 连续 3 次报 `MODEL_EMPTY_OUTPUT`。现已改为在 storyboard prompt 前自动剔除 `口播（中文）` 行，仅保留泰文口播，commit: `9633168 Ignore Chinese translation in storyboard prompts`。
- 2026-04-01: 配置表里 `九宫格生成视频-seeddance2.0` 的 `提示词` 一度为空；已按当前运行中的最新版本与 `九宫格生成视频-sora` / `九宫格生成视频-grok` 对齐，确保视频任务继续保持“执行时优先从配置表读取提示词”的逻辑。
- 2026-04-02: 用户明确要求每日巡检与监控口径同步跟进最新功能命名。已将 `tk_toolkit_dual/tk_dispatcher.py` 中旧 `003视频生成` 监控名称改为 `九宫格生成视频`（commit: `bd97d4c`），并在 `tk_toolkit_dual/tk_healthcheck.py` 新增 `九宫格生成视频` 专项检查：校验 `九宫格生成视频-grok` / `-sora` / `-seeddance2.0` 三条配置的 `模型名称`、`API Key`、`API 代理地址`、`提示词` 是否完整，同时对“名称含 `视频生成` 但不属于 `九宫格生成视频-*`”的旧配置残留直接报异常（commit: `46acfeb`）。
