# Prompt Config Sync Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add small CLI scripts to sync prompt text between Feishu config table records and local `docs/prompts/*.md` files.

**Architecture:** Create a reusable `tk_toolkit_dual/prompt_config_sync.py` module that knows the stage-to-file mapping, fetches config records by `环节`, and supports safe from-Feishu / to-Feishu synchronization. Add two thin wrappers: `sync_prompt_from_feishu.py` and `sync_prompt_to_feishu.py`.

**Tech Stack:** Python stdlib, existing `tk_toolkit_dual/common.py` Feishu helpers, unittest.

---

### Task 1: Add reusable sync module

**Files:**
- Create: `tk_toolkit_dual/prompt_config_sync.py`

**Steps:**
1. Define `PROMPT_STAGE_FILES` mapping for UGC and nonUGC prompt stages.
2. Implement `resolve_prompt_path(stage)`.
3. Implement `find_config_record_by_stage(token, stage)`.
4. Implement `sync_from_feishu(stage, dry_run=False)`.
5. Implement `sync_to_feishu(stage, dry_run=True)`.
6. Implement `main(argv)` with `from-feishu`, `to-feishu`, and `list` commands.

### Task 2: Add wrapper scripts

**Files:**
- Create: `tk_toolkit_dual/sync_prompt_from_feishu.py`
- Create: `tk_toolkit_dual/sync_prompt_to_feishu.py`

**Steps:**
1. Each wrapper imports `prompt_config_sync.main`.
2. `sync_prompt_from_feishu.py STAGE` calls `from-feishu STAGE`.
3. `sync_prompt_to_feishu.py STAGE --write` calls `to-feishu STAGE`.

### Task 3: Add tests

**Files:**
- Create: `tk_toolkit_dual/test_prompt_config_sync.py`

**Steps:**
1. Test known stage resolves to expected path.
2. Test unknown stage raises useful error.
3. Test `--list` includes nonUGC stages.
4. Test dry-run to-feishu does not call updater.

### Task 4: Verify

Run:

```bash
python3 -m unittest tk_toolkit_dual/test_prompt_config_sync.py
python3 -m py_compile tk_toolkit_dual/prompt_config_sync.py tk_toolkit_dual/sync_prompt_from_feishu.py tk_toolkit_dual/sync_prompt_to_feishu.py
```
