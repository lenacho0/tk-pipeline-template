# MEMORY.md - Long-Term Memory

## Identity & Setup

- Workspace initialized under OpenClaw with Feishu direct-chat as the main session context.
- User wants important conversation content summarized into memory files rather than left ephemeral.

## Preferences

- The user values durable memory: key discussion points, decisions, and preferences should be written down when asked.
- Prefer concise, useful summaries over verbose logging.

## Ongoing Project Memory

- 2026-03-28: TK pipeline 第二轮优化已从方案阶段进入真实落地阶段。
- 已完成 dispatcher 第一轮硬化、扫描减负第一刀、runtime log 独立化，以及多个关键脚本的标准错误输出协议统一。
- 后续默认沿“低风险收口 → 小批量真实验证 → 再推进更正式批量能力/状态机/批次语义”路线继续推进。
- 2026-03-30: colleague 新双表流程已完成真实链路贯通验证，并在运行时层面完成切换：旧单表 dispatcher `com.ryan.tk-dispatcher` 已停用，正式常驻实例收口为 dual 的 `com.ryan.tk-dispatcher.ryan` 与 `com.ryan.tk-dispatcher.colleague`。
- 2026-03-30: 双表流程两类关键问题已明确并修复到可运行状态：其一，`tk_analyze.py` 在 colleague 线上因 4 并发 + 900 秒超时导致批量超时，已调整为 1 并发 + 2400 秒；其二，`003-2` 不触发的根因不是表/字段错误，而是 dual colleague dispatcher 未正确接管、旧实例混跑造成状态污染。
