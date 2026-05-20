# TK Pipeline 清理清单（2026-05-18）

本清单记录本次文档与脚本整理的边界。当前项目主线按旧 TK pipeline / dual dispatcher 多维表格项目处理。

## 当前保留

- `docs/INDEX.md`：当前文档入口。
- `docs/tk-pipeline/`：旧 TK pipeline 主线设计、上线状态、复盘和下一步计划。
- `tk_toolkit_dual/`：当前 dual dispatcher 代码、配置模板、launchd 文件、运维文档和测试。
- `tk_toolkit/`：暂保留，当前 dual launchd 仍复用其中 `.venv312` Python 运行时。
- `.env.example`、`.gitignore`：项目级示例配置和忽略规则。

## 已归档

- `docs/archive/ugc-content-chain-2026-05/`：UGC / 内容-01~07 链路文档与 prompt。
- `docs/archive/tiktok-bitable-legacy-2026-05/`：旧 TikTok Bitable / 表6 / 方向 B 文档。
- `docs/archive/implementation-plans-legacy-2026-05/`：历史 implementation plans。
- `archive/project-docs-legacy-2026-05/`：早期工程骨架、旧自动化入口和旧单实例口径文档。
- `archive/scripts-legacy-2026-05/`：根目录旧 `scripts/` 独立脚本副本。

## 可再生缓存

以下文件可再生，不进入项目主线：

- `*.log`
- `.table_cache_*`
- `.dispatcher_*`
- `.retry_state*`
- `.dead_letter*`
- `.record_state_cache*`
- `.circuit_breakers*`
- `.healthcheck_today*`
- `__pycache__/`
- `.DS_Store`
- `*.bak-disable-healthcheck-*`

## 需人工确认后再清理

以下目录可能包含真实调试素材、生成视频或图片，默认只列清单，不直接删除：

- `tk_toolkit_dual/workspace_ryan/`
- `tk_toolkit_dual/workspace_colleague/`
- `structured_script_shadow_output/`
- `storyboard_work/`
- `video_work/`
- `tiktok_videos/`

需要释放磁盘时，优先用 `trash` 做可恢复清理。
