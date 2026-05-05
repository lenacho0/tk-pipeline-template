# UGC Accelerated Next Steps Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Accelerate UGC workflow from the completed `UGC-01` analysis writeback to script generation and first downstream handoff.

**Architecture:** Keep the main path narrow: `UGC-01 分析成功` → derive `UGC-02` batch and `UGC-03` script version records → generate scripts for selected `UGC-03` records → only then add dispatcher automation. Downstream image/video work should prepare interfaces in parallel but not block the script path.

**Tech Stack:** Python 3, Feishu Bitable Open API, `tk_toolkit_dual`, Gemini-compatible model client, UGC table group in Base `LBWUbgRfEavAgjsXNIhcpo0Dnvb`, JSON_OUTPUT/MARKDOWN_OUTPUT protocol.

---

## Current Verified State

- `UGC-01` real record `recvia7bZjgXMZ` has been analyzed and written back successfully.
- Aitgenne `gemini-3.1-pro-preview` works for UGC inline video analysis.
- URL field parsing bug for Feishu `{link,text}` has been fixed and covered by unit test.
- Current test gate: `python3 -m unittest test_ugc_config test_ugc_utils test_ugc_single_video_analyze -v` passes 27 tests.

---

## Acceleration Principle

1. Do not build dispatcher first. Manual CLI first, then dispatcher.
2. Do not start full image/video pipeline before scripts are generated.
3. Use existing successful `UGC-01` record as the golden integration sample.
4. Every new stage must support dry-run and explicit write.
5. Use JSON output as source of truth; never parse Markdown for downstream fields.

---

## Phase A: UGC-01 → UGC-02/UGC-03 Derivation

**Target:** From one analyzed UGC-01 record, create one script batch in `UGC-02` and N script version records in `UGC-03`.

**Files:**
- Create: `tk_toolkit_dual/tk_ugc_script_derive.py`
- Modify: `tk_toolkit_dual/ugc_config.py` if helper accessors are missing
- Test: `tk_toolkit_dual/test_ugc_script_derive.py`

**Behavior:**
- Input: `UGC-01 record_id`
- Read `分析结果JSON`
- Validate `script_generation_handoff` exists
- Read `目标脚本数量`, default to 3 if missing/invalid
- Create one `UGC-02` batch record with:
  - linked UGC-01
  - inherited linked product
  - target market
  - target script count
  - status fields initialized
- Create N `UGC-03` version records with differentiated `主测试点`:
  - first from `new_script_directions[0].direction_name` if available
  - second from `new_script_directions[1].direction_name` if available
  - remaining from `hook_templates` / `script_skeleton` derived labels
  - use `standard` only as fallback
- Update `UGC-01.脚本派生状态` to `已派生` only on explicit write success.

**Validation:**
```bash
cd tk_toolkit_dual
python3 -m unittest test_ugc_script_derive -v
python3 tk_ugc_script_derive.py recvia7bZjgXMZ --dry-run
python3 tk_ugc_script_derive.py recvia7bZjgXMZ --write
```

---

## Phase B: UGC-03 Single Script Generation

**Target:** Generate one script for one `UGC-03` version record using `docs/prompts/ugc-script-generation-system-prompt-v1.md`.

**Files:**
- Create: `tk_toolkit_dual/tk_ugc_script_generate.py`
- Test: `tk_toolkit_dual/test_ugc_script_generate.py`

**Behavior:**
- Input: `UGC-03 record_id`
- Read linked `UGC-02` and linked `UGC-01`
- Read UGC-01 `分析结果JSON.script_generation_handoff`
- Read inherited product and target market
- Build script-generation prompt payload
- Call model only with `--call-model`
- Parse `JSON_OUTPUT + MARKDOWN_OUTPUT`
- Write back to `UGC-03` only with `--write`
- Fields should include script JSON, script Markdown/body, summary, status, error message if any.

**Validation:**
```bash
cd tk_toolkit_dual
python3 -m unittest test_ugc_script_generate -v
python3 tk_ugc_script_generate.py <ugc03_record_id> --call-model
python3 tk_ugc_script_generate.py <ugc03_record_id> --call-model --write
```

---

## Phase C: Batch Generate All UGC-03 Versions

**Target:** Generate all pending script versions under one UGC-02 batch.

**Files:**
- Modify: `tk_toolkit_dual/tk_ugc_script_generate.py`
- Test: extend `tk_toolkit_dual/test_ugc_script_generate.py`

**Behavior:**
- Add `--batch-record-id <UGC-02 record_id>`
- Find linked/pending `UGC-03` records
- Generate sequentially, not parallel, to avoid model/API rate bursts
- Continue-on-error option only after first stable run

**Validation:**
```bash
python3 tk_ugc_script_generate.py --batch-record-id <ugc02_record_id> --call-model --write
```

---

## Phase D: Dispatcher Automation

**Target:** Only after manual Phase A/B/C pass, wire automation into dispatcher.

**Files:**
- Modify: `tk_toolkit_dual/tk_dispatcher.py`
- Test: add focused tests or dry-run simulation if practical

**Triggers:**
- UGC-01 `分析状态=分析成功` and `脚本派生状态=待派生` → run derive
- UGC-03 `脚本生成状态=待生成` → run script generation

**Validation:**
- Run dispatcher in dry/manual mode first.
- Confirm it does not touch unrelated TK pipeline stages.

---

## Phase E: Downstream Preparation, Not Main Blocker

**Target:** Prepare but do not block on 6-grid/storyboard/video.

**Work:**
- Map UGC script JSON fields to `UGC-04 6宫格分镜表` requirements.
- Confirm whether existing six-grid prompt can be adapted or needs a UGC-specific prompt.
- Do not generate images/videos until at least one UGC-03 script is approved.

---

## Immediate Recommended Execution Order

1. Implement Phase A now.
2. Run Phase A dry-run on `recvia7bZjgXMZ`.
3. If dry-run looks right, write UGC-02/03 records.
4. Implement Phase B immediately after.
5. Generate only one UGC-03 script first.
6. If quality acceptable, batch generate remaining scripts.
7. Add dispatcher automation last.

---
