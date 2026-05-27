# Workspace TK 文档索引

最后整理：2026-05-28

当前一线文档只服务 ryan 主线 TK pipeline 多维表格项目。UGC / 内容-01~07、新 TikTok Bitable 表6、colleague 实例、误建 Base、早期脚本副本和实验输出均已归档，不再作为当前主线依据。

---

## 当前主线

### `docs/tk-pipeline/`

旧 TK pipeline、分镜一致性、上线状态、P0/P1 改造和经验复盘。

- `pipeline-migration-phase1.md`：不停产迁移第一阶段改造项。
- `storyboard-consistency-phase2.md`：逐镜头一致性增强工程化记录。
- `tk-2026-03-28-rollout-status.md`：2026-03-28 实际上线状态。
- `tk-dual-storyboard-plan-2026-03-25.md`：双流程分镜方案。
- `tk-editing-notes.md`：历史编辑失败说明。
- `tk-p0-implementation-2026-03-28.md`：P0 最小落地说明。
- `tk-pipeline-lessons-learned.md`：长期维护经验。
- `tk-pipeline-next-plan-2026-03-25.md`：下一步计划。
- `tk-second-round-plan-2026-03-25.md`：第二轮优化方案初版。
- `tk-second-round-plan-2026-03-28.md`：第二轮优化方案更新版。

### `tk_toolkit_dual/`

当前核心代码目录，只承载 ryan dispatcher 实例。

- `README_DUAL.md`：ryan-only 运行说明。
- `OPS_QUICK_REFERENCE.md`：当前 ryan 主线运维速查。
- `launchd_usage_dual.md`：ryan launchd 常用命令。

---

## 运维入口

### 当前服务

- `com.ryan.tk-dispatcher.ryan`

### 常用命令

```bash
launchctl print gui/$(id -u)/com.ryan.tk-dispatcher.ryan | sed -n '1,120p'
```

```bash
TK_INSTANCE=ryan TK_CONFIG_FILE=/Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit_dual/config.ryan.json /Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit/.venv312/bin/python /Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit_dual/tk_healthcheck.py
```

注意：`tk_toolkit/` 暂时保留，因为当前 dual launchd 仍复用其中的 `.venv312` Python 运行时。不要在清理文档时删除它。

---

## 历史归档

### `docs/archive/ugc-content-chain-2026-05/`

UGC / 内容-01~07 新链路文档、prompt 镜像、审核触发器说明和相关资料。该链路不属于当前旧 TK pipeline 主线。

### `docs/archive/tiktok-bitable-legacy-2026-05/`

旧 TikTok Bitable / 表6 / 方向 B 文档。保留用于追溯，不作为当前项目实施依据。

### `docs/archive/implementation-plans-legacy-2026-05/`

历史 implementation plans。这里包含 UGC reroll 候选池等已被否决或被后续方案取代的计划，只能作为历史参考。

### `docs/archive/wrong-ugc-base-2026-04-29/`

误建 UGC Base `Zgzqbp71zaFXgOs94l4c0nlVnef` 的历史记录和快照。仅作追溯，不得用于当前代码或配置。

### `archive/project-docs-legacy-2026-05/`

早期工程骨架、旧自动化入口和旧单实例口径文档，例如 `README-phase1.md`、`WORKFLOW_AUTO.md`、`tk_toolkit_dual/launchd_usage.md`。

### `archive/scripts-legacy-2026-05/`

根目录旧 `scripts/` 独立脚本副本。当前主线以 `tk_toolkit_dual/` 为准。

---

## 本地产物

以下内容是本机运行产物或缓存，不属于文档主线：

- `tk_toolkit_dual/workspace_*/`
- `structured_script_shadow_output/`
- `storyboard_work/`
- `video_work/`
- `tiktok_videos/`
- `*.log`
- `.table_cache_*`
- `.dispatcher_*`
- `.retry_state*`
- `.dead_letter*`
- `__pycache__/`
- `.DS_Store`
- `*.bak-disable-healthcheck-*`

真实视频和图片产物先不删除；需要释放磁盘时优先用 `trash` 做可恢复清理。
