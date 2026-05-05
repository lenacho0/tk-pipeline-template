# UGC Nine Grid Dynamic Shot Count Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace fixed 6-panel storyboard generation with a fixed 3x3 nine-grid canvas that uses only the script's effective shot count N (1-9), fills inactive cells white, and only sends active cells downstream.

**Architecture:** Keep UGC-04 as a single combined storyboard image for visual consistency, but change it from a 6-grid layout to a 9-grid container. Script JSON may contain 1-9 shots; UGC-04 always renders 9 cells on a 9:16 canvas, with cells beyond `effective_shot_count` treated as inactive placeholders. UGC-05 crops all grid cells but only creates records for active cells, so UGC-06 video count remains N.

**Tech Stack:** Python 3, PIL/Pillow, Feishu Bitable APIs, existing `tk_toolkit_dual` CLI scripts and unittest suite.

---

### Task 1: Generalize UGC-04 prompt parsing from fixed 6 to dynamic 1-9 shots

**Files:**
- Modify: `tk_toolkit_dual/tk_ugc_six_grid.py`
- Test: `tk_toolkit_dual/test_ugc_six_grid.py`

**Steps:**
1. Add helpers `effective_shot_count(script_json)`, `extract_storyboard_summary(script_json)`, and `build_nine_grid_panels(...)`.
2. Update `parse_script_json()` to accept 1-9 shots and prefer `nine_grid_summary`, then `six_grid_summary`, then derive summaries from `shots`.
3. Update `parse_grid_prompt_json()` to accept exactly 9 `panels`, with active/inactive flags.
4. Update tests so sample scripts can contain 6 active shots but prompt JSON has 9 panels.

### Task 2: Change UGC-04 prompt JSON and image prompt to fixed 9-grid container

**Files:**
- Modify: `tk_toolkit_dual/tk_ugc_six_grid.py`
- Test: `tk_toolkit_dual/test_ugc_six_grid.py`

**Steps:**
1. Update task type to `UGC_9_GRID_STORYBOARD_DYNAMIC_SHOTS`.
2. Use layout `3行x3列`, `combined_canvas_aspect_ratio=9:16`, `panel_aspect_ratio=9:16`.
3. For panels beyond active count, emit `active=false`, `placeholder=true`, and prompt text requiring plain white blank cell.
4. Update combined prompt to ask for one 9-panel storyboard image, reading order 1-9, with active panels only for 1-N and white placeholders for N+1..9.

### Task 3: Add image post-processing and ratio validation for 9-grid

**Files:**
- Modify: `tk_toolkit_dual/tk_ugc_six_grid.py`
- Test: `tk_toolkit_dual/test_ugc_six_grid.py`

**Steps:**
1. Generalize grid dimension helpers for `3行x3列`.
2. Update ratio validator to confirm a 3x3 image has total 9:16 and each panel 9:16.
3. Add `force_inactive_cells_white(image_path, panels, layout)` to overwrite inactive cells with white after download.
4. Ensure validation runs after white-fill post-processing.

### Task 4: Update UGC-05 cropping to only use active cells

**Files:**
- Modify: `tk_toolkit_dual/tk_ugc_shot_images.py`
- Test: `tk_toolkit_dual/test_ugc_shot_images.py`

**Steps:**
1. Generalize `grid_cells()` and crop function for `3行x3列`.
2. Add active panel extraction from `UGC-04.6宫格提示词JSON`.
3. Crop 9 cells for inspection but only build/upload/create records for active panels.
4. Preserve fallback attachment behavior.

### Task 5: Run gates and document current status

**Files:**
- Modify: `memory/2026-05-01.md`

**Steps:**
1. Run `python3 -m py_compile tk_ugc_six_grid.py tk_ugc_shot_images.py test_ugc_six_grid.py test_ugc_shot_images.py`.
2. Run UGC unit tests.
3. Record the implementation state and any remaining blocker in daily memory.
