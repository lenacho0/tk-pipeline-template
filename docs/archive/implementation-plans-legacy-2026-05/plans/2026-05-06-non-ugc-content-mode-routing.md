# Non-UGC Content Mode Routing Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let the shared 内容-01~07 pipeline route records with `视频类型=非UGC` to non-UGC prompt/config stages while preserving existing UGC behavior.

**Architecture:** Add small content-mode helpers in existing UGC modules instead of creating a parallel pipeline. The Feishu tables are shared; code should inspect `内容-01/UGC-01.视频类型`, choose the matching stage names/prompts, and keep current table IDs/field compatibility. Changes must be covered by unit tests and validated with dry-run commands before any real model calls.

**Tech Stack:** Python stdlib, existing `tk_toolkit_dual` modules, unittest, Feishu Base via existing helpers.

---

### Task 1: Add content-mode helpers for analysis/script routing

**Files:**
- Modify: `tk_toolkit_dual/tk_ugc_single_video_analyze.py`
- Modify: `tk_toolkit_dual/tk_ugc_script_generate.py`
- Test: `tk_toolkit_dual/test_ugc_single_video_analyze.py`
- Test: `tk_toolkit_dual/test_ugc_script_generate.py`

**Steps:**
1. Add constants for non-UGC prompt paths/stage names.
2. Add helper to read `视频类型` and normalize to `UGC` or `非UGC`.
3. Make analysis model config choose `爆款视频分析-UGC` for UGC and `非UGC-爆款视频分析` for non-UGC.
4. Make script model config choose `UGC-脚本生成` for UGC and `非UGC-脚本生成` for non-UGC.
5. Keep old function names for backwards compatibility.
6. Add tests proving UGC defaults remain unchanged and non-UGC selects non-UGC stages/prompts.

### Task 2: Add content-mode helpers for 9-grid storyboard routing

**Files:**
- Modify: `tk_toolkit_dual/tk_ugc_six_grid.py`
- Test: `tk_toolkit_dual/test_ugc_six_grid.py`

**Steps:**
1. Add `NON_UGC_GRID_STAGE_NAME = "非UGC-9宫格分镜图生成"`.
2. Infer content mode from `结构化脚本JSON.video_type` / `content_mode` / source UGC-01 if available.
3. Make config lookup choose non-UGC grid stage for non-UGC script JSON.
4. Keep 9宫格 field names and old compatibility constants unchanged.
5. Add tests for non-UGC config selection and UGC backwards compatibility.

### Task 3: Add content-mode helpers for video prompt routing

**Files:**
- Modify: `tk_toolkit_dual/tk_ugc_video_prompts.py`
- Test: `tk_toolkit_dual/test_ugc_video_prompts.py`

**Steps:**
1. Add non-UGC prompt path/stage constant for `非UGC-视频提示词生成`.
2. Load the non-UGC prompt when shot JSON/content mode says non-UGC.
3. Preserve UGC audio policy for UGC; for non-UGC use the non-UGC prompt text source and avoid forcing UGC realism language where inappropriate.
4. Add tests around prompt source/routing only; do not call video models.

### Task 4: Verify and dry-run

**Files:**
- No new files unless logs are saved under `workspace/ugc_smoke/`.

**Steps:**
1. Run focused unit tests:
   `cd tk_toolkit_dual && python3 -m unittest test_ugc_single_video_analyze test_ugc_script_generate test_ugc_six_grid test_ugc_video_prompts -v`
2. Run py_compile on modified modules.
3. Use Feishu field lists / record dry-runs only; do not call models until dry-run confirms stage routing.
4. Save dry-run output under `workspace/ugc_smoke/non_ugc_routing_20260506.json`.
