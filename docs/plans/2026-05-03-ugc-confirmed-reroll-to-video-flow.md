# UGC Confirmed Reroll-to-Video Flow Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Redesign UGC regeneration as a simple human-confirmed flow: regenerate 9-grid + split shots, let user approve shot images, run HD enhancement, let user approve HD shots, then generate shot videos; allow individual unsatisfactory shot images to be regenerated.

**Architecture:** Keep UGC-04 as the 9-grid parent, UGC-05 as the user-facing shot image review layer, and UGC-06 as video generation. Add minimal trigger/approval fields to UGC-05 and extend the existing local launchd poller into a small stage orchestrator. Do not auto-burn HD/video models until the user explicitly confirms.

**Tech Stack:** Python 3, Feishu Bitable API, existing UGC scripts (`tk_ugc_six_grid.py`, `tk_ugc_shot_images.py`, `tk_ugc_video_prompts.py`, `tk_ugc_shot_videos.py`), launchd polling.

---

## Desired User Flow

### Step A — Regenerate 9-grid and split into shot images

User operates in `UGC-04`:

- Field: `一键重生成9宫格`
- Behavior:
  1. Regenerate UGC-04 9-grid image.
  2. Split active panels into UGC-05 shot images.
  3. Update/overwrite existing UGC-05 shot image records where possible.
  4. Mark UGC-05 records as awaiting review.

### Step B — User reviews UGC-05 shot images

User operates in `UGC-05` daily view:

Minimal visible fields:

- `分镜序号`
- `原始裁切图片`
- `分镜图审核状态`
- `分镜图操作`
- `分镜图备注`
- `高清化状态`
- `高清分镜图`

User choices:

- If all shot images look OK: set every `分镜图审核状态=通过`, then click parent/batch trigger `确认分镜图并高清化`.
- If one shot is bad: on that UGC-05 row set `分镜图操作=重新生成单张分镜图` and optionally write `分镜图备注`.

### Step C — HD enhancement after user confirmation

Trigger only HD-enhances UGC-05 rows that:

- `分镜图审核状态=通过`
- `高清化状态` is empty / `待高清化` / `失败`

After HD success:

- `高清化状态=成功`
- `高清分镜图` and fallback fields are updated.
- Set `高清图审核状态=待确认`.

### Step D — User reviews HD shots

User operates in `UGC-05`:

- If HD image is OK: set `高清图审核状态=通过`.
- If not OK: set `高清图操作=重新高清化` or `分镜图操作=重新生成单张分镜图` depending on problem.

### Step E — Generate UGC-06 videos after HD approval

When UGC-05 row has:

- `高清图审核状态=通过`
- `高清视频操作=生成分镜视频`

System:

1. Creates or updates corresponding UGC-06 prompt record for that UGC-05.
2. Calls UGC-06 video generation.
3. Writes back UGC-06 video fields.

---

## New Fields

### UGC-04 additions / existing

Already exists:

- `一键重生成9宫格` checkbox
- `一键重生成状态` single select/text
- `一键重生成结果` text

Consider renaming later to `重生成9宫格并拆分` for clarity, but not required.

### UGC-05 additions

Create these fields:

- `分镜图审核状态` single select: `待确认 / 通过 / 不通过`
- `分镜图操作` single select: `不触发 / 重新生成单张分镜图 / 确认分镜图并高清化`
- `分镜图备注` text
- `高清图审核状态` single select: `待确认 / 通过 / 不通过`
- `高清图操作` single select: `不触发 / 重新高清化 / 生成分镜视频`
- `高清图备注` text
- `分镜图执行状态` single select/text: `待处理 / 处理中 / 成功 / 失败`
- `分镜图执行结果` text

Design note: field names are intentionally user-facing and stage-specific. No generic “candidate” terms.

---

## Implementation Tasks

### Task 1: Create UGC-05 review/action fields in Feishu

**Files:** none or one-off script/log.

Use first-class Feishu field tools or project Feishu API helper to create fields on UGC-05 table `tblW1KwMasPcXoaR`.

Fields:

```text
分镜图审核状态: single select
分镜图操作: single select
分镜图备注: text
高清图审核状态: single select
高清图操作: single select
高清图备注: text
分镜图执行状态: single select
分镜图执行结果: text
```

After creation, list fields and verify all exist.

### Task 2: Update UGC-05 split output defaults

**Files:**
- Modify: `tk_toolkit_dual/tk_ugc_shot_images.py`
- Modify: `tk_toolkit_dual/test_ugc_shot_images.py`

When building UGC-05 fields after splitting:

```python
fields.update({
    "分镜图审核状态": "待确认",
    "分镜图操作": "不触发",
    "高清图审核状态": "",
    "高清图操作": "不触发",
    "分镜图执行状态": "",
    "分镜图执行结果": "",
})
```

When HD enhancement succeeds:

```python
update_fields.update({
    "高清图审核状态": "待确认",
    "高清图操作": "不触发",
})
```

Tests:

- New split records get `分镜图审核状态=待确认`.
- HD success sets `高清图审核状态=待确认`.

### Task 3: Add UGC-05 stage trigger poller helpers

**Files:**
- Create: `tk_toolkit_dual/tk_ugc_review_trigger.py`
- Create: `tk_toolkit_dual/test_ugc_review_trigger.py`

Responsibilities:

- List UGC-05 records.
- Detect pending actions:
  - `分镜图操作=确认分镜图并高清化`
  - `分镜图操作=重新生成单张分镜图`
  - `高清图操作=重新高清化`
  - `高清图操作=生成分镜视频`
- Safety gates:
  - HD enhancement requires explicit `--call-models`.
  - Video generation requires explicit `--call-models`.
  - Single-shot regeneration requires explicit `--call-models`.

For v1, implement only:

- `确认分镜图并高清化`
- `高清图操作=生成分镜视频`

Leave single-shot reroll as planned-but-blocked unless a safe implementation exists.

### Task 4: Implement HD enhancement trigger

**Files:**
- Modify/create: `tk_toolkit_dual/tk_ugc_review_trigger.py`
- Modify: tests

Behavior for one UGC-05 row:

If:

```text
分镜图审核状态=通过
分镜图操作=确认分镜图并高清化
```

Then:

1. Set `分镜图执行状态=处理中`.
2. Run a new helper in `tk_ugc_shot_images.py` to HD-enhance exactly this existing UGC-05 record.
3. Set `高清化状态=成功`, `高清图审核状态=待确认`.
4. Reset `分镜图操作=不触发`.
5. Set `分镜图执行状态=成功`.

If failure:

- `分镜图执行状态=失败`
- `分镜图执行结果` contains error
- operation resets to `不触发` or remains? Recommendation: reset to avoid repeated model calls; user can reselect.

### Task 5: Implement video generation trigger

**Files:**
- Modify: `tk_toolkit_dual/tk_ugc_review_trigger.py`
- Modify: tests

If:

```text
高清图审核状态=通过
高清图操作=生成分镜视频
```

Then:

1. Create or update UGC-06 prompt record for this UGC-05.
2. Run UGC-06 video generation for that UGC-06 record.
3. Reset `高清图操作=不触发`.
4. Set `分镜图执行状态=成功/失败` and result JSON.

Implementation hint:

- Reuse `create_or_preview_ugc06_records([ugc05_record_id], write=True)`.
- Then call `run_ugc06_video_generation(ugc06_record_id, dry_run=False)`.
- Need idempotency: if there is already a UGC-06 linked to this UGC-05, prefer updating/reusing it rather than creating duplicates. If this is too large, v1 can create a new UGC-06 and record id in result JSON.

### Task 6: Launchd integration

**Files:**
- Modify: `run_ugc_one_click_reroll.sh` or create `run_ugc_review_trigger.sh`
- Modify/create plist if separate.

Recommendation:

- Keep `com.ryan.ugc-one-click-reroll` for UGC-04 only.
- Add separate `com.ryan.ugc-review-trigger` every 60 seconds for UGC-05 review actions.

Reason: clearer logs and easier stop/start if video model costs need control.

### Task 7: Views

Create/update UGC-05 views:

- `01-分镜图确认`
- `02-高清图确认`
- `03-分镜视频生成入口`

Do not expose internal JSON/path fields in daily views unless needed.

### Task 8: Single-shot image reroll design

This is harder than whole-grid reroll because current image source is the 9-grid container. Options:

1. Regenerate whole 9-grid and replace only one UGC-05 crop — easy but may change style unexpectedly.
2. Use OTU image edit/reference repaint from the bad crop + full grid + shot prompt — better; output one 1080x1920 shot image directly.
3. Regenerate 9-grid but crop only selected panel and update only that UGC-05.

Recommendation: implement option 2 after HD/video gating is stable.

---

## Current Clarification

Do not auto-run HD/video immediately after splitting. User explicitly wants confirmation gates:

- split shots OK -> HD
- HD OK -> video
- single bad shot can be regenerated

Therefore launchd must only process explicit action fields, not status alone.
