# UGC One-Click Overwrite Reroll Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a simple one-click UGC-04 reroll flow where the user clicks one Feishu field and the system regenerates the 9-grid image directly on the same record, overwriting the old result.

**Architecture:** Keep the existing safe candidate-pool reroll as an advanced path, but add a new default overwrite path in `tk_ugc_reroll_trigger.py`. The new path scans a single checkbox/button-like field on UGC-04, calls `run_image_generation(record_id, call_image=True, write=True)` on that same record, writes status/result fields, and resets the trigger field after completion.

**Tech Stack:** Python 3, existing Feishu Base helpers, OTU image generation via `tk_ugc_six_grid.py`, unittest.

---

## UX Decision

### New default user flow

In `UGC-04 6宫格分镜表`, show only these fields in the daily view:

- `一键重生成9宫格` — checkbox or button-like field. User clicks/checks this only.
- `一键重生成状态` — system-owned status: `待处理 / 处理中 / 成功 / 失败`.
- `一键重生成结果` — system-owned short JSON/text result.
- Existing visible result fields: `6宫格生成状态`, `6宫格图片`, `6宫格图片URL`, `6宫格图片file_token`, `错误信息`.

Everything else (`重新生成数量`, `重新生成请求`, `重新生成执行状态`, candidate fields) moves to advanced/hidden views.

### Behavior

When `一键重生成9宫格=true`:

1. Trigger sets `一键重生成状态=处理中`.
2. Trigger calls `run_image_generation(source_ugc04_record_id, call_image=True, write=True)` directly.
3. The same UGC-04 record is overwritten:
   - `6宫格生成状态`
   - `6宫格图片`
   - `6宫格图片URL`
   - `6宫格图片file_token`
   - `错误信息`
4. Trigger writes `一键重生成状态=成功` and a compact result JSON.
5. Trigger resets `一键重生成9宫格=false` so the field behaves like a button.

Failure behavior:

1. `6宫格生成状态=失败` is already handled by `run_image_generation`.
2. Trigger writes `一键重生成状态=失败` and `一键重生成结果` with the error.
3. Trigger resets `一键重生成9宫格=false`.

### Explicit non-goals for v1

- Do not delete or rewrite downstream UGC-05/06/07 automatically.
- Do not remove candidate-pool mode.
- Do not require `重新生成数量` for one-click mode.
- Do not require `重新生成请求` or `重新生成执行状态` for one-click mode.

Later optional v2: add `一键重生成并覆盖分镜图` to regenerate UGC-04 and update existing linked UGC-05 records in place.

---

### Task 1: Add one-click trigger parsing and tests

**Files:**
- Modify: `tk_toolkit_dual/tk_ugc_reroll_trigger.py`
- Modify: `tk_toolkit_dual/test_ugc_reroll_trigger.py`

**Step 1: Write failing tests**

Add tests covering:

```python
def test_should_process_one_click_grid_record_when_checkbox_true(self):
    record = {
        "record_id": "rec04",
        "fields": {
            "一键重生成9宫格": True,
            "一键重生成状态": "",
        },
    }
    self.assertTrue(should_process_one_click_grid_record(record))


def test_build_one_click_result_update_resets_checkbox(self):
    update = build_one_click_result_update("成功", {"ok": True})
    self.assertEqual(update["一键重生成9宫格"], False)
    self.assertEqual(update["一键重生成状态"], "成功")
    self.assertIn('"ok": true', update["一键重生成结果"])
```

**Step 2: Run tests to verify failure**

Run:

```bash
cd /Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit_dual
python3 -m unittest test_ugc_reroll_trigger -v
```

Expected: fails because new functions do not exist.

**Step 3: Implement minimal functions**

Add constants:

```python
ONE_CLICK_GRID_FIELD = "一键重生成9宫格"
ONE_CLICK_STATUS_FIELD = "一键重生成状态"
ONE_CLICK_RESULT_FIELD = "一键重生成结果"
```

Add helpers:

```python
def checkbox_checked(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, list) and value:
        return any(checkbox_checked(v) for v in value)
    text = extract_text(value).strip().lower()
    return text in {"true", "1", "yes", "y", "是", "已勾选", "checked"}


def should_process_one_click_grid_record(record: Dict[str, Any]) -> bool:
    fields = record.get("fields") or {}
    return checkbox_checked(fields.get(ONE_CLICK_GRID_FIELD))


def build_one_click_result_update(status: str, result: Dict[str, Any]) -> Dict[str, Any]:
    return {
        ONE_CLICK_GRID_FIELD: False,
        ONE_CLICK_STATUS_FIELD: status,
        ONE_CLICK_RESULT_FIELD: json.dumps(result, ensure_ascii=False, indent=2, default=str)[:60000],
    }
```

**Step 4: Run tests**

Expected: new tests pass.

---

### Task 2: Add overwrite execution path

**Files:**
- Modify: `tk_toolkit_dual/tk_ugc_reroll_trigger.py`
- Modify: `tk_toolkit_dual/test_ugc_reroll_trigger.py`

**Step 1: Write failing test**

```python
def test_process_one_click_grid_record_overwrites_same_record(self):
    calls = []

    def fake_generate(record_id, *, call_image, write):
        calls.append((record_id, call_image, write))
        return {"ugc04_record_id": record_id, "written": True, "file_token": "tok"}

    result = process_one_click_grid_record(
        {"record_id": "rec04", "fields": {"一键重生成9宫格": True}},
        write=True,
        call_models=True,
        image_generate_fn=fake_generate,
    )

    self.assertEqual(calls, [("rec04", True, True)])
    self.assertEqual(result["source_record_id"], "rec04")
    self.assertEqual(result["mode"], "overwrite_current_grid")
```

**Step 2: Implement function**

In `tk_ugc_reroll_trigger.py` import:

```python
from tk_ugc_six_grid import get_feishu_token, update_ugc_record, run_image_generation
```

Add:

```python
def process_one_click_grid_record(
    record: Dict[str, Any],
    *,
    write: bool,
    call_models: bool,
    image_generate_fn: Callable[..., Dict[str, Any]] = run_image_generation,
) -> Dict[str, Any]:
    if not call_models:
        raise ValueError("一键重生成9宫格会触发真实图片模型调用，需要显式 --call-models")
    record_id = record.get("record_id") or ""
    result = image_generate_fn(record_id, call_image=True, write=write)
    return {
        "stage": "grid",
        "mode": "overwrite_current_grid",
        "source_record_id": record_id,
        "status": "success",
        "result": result,
    }
```

**Step 3: Run tests**

Expected: all trigger tests pass.

---

### Task 3: Integrate one-click scan into `run_stage`

**Files:**
- Modify: `tk_toolkit_dual/tk_ugc_reroll_trigger.py`
- Modify: `tk_toolkit_dual/test_ugc_reroll_trigger.py`

**Step 1: Write failing tests**

Add a test where `run_stage(stage="grid", records=[one_click_record])` processes one-click records even when old reroll fields are empty.

Expected result:

```python
self.assertEqual(result["one_click_pending_count"], 1)
self.assertEqual(result["pending_count"], 0)
```

**Step 2: Implement integration**

In `run_stage`, for `stage == "grid"`:

1. Build `one_click_pending = [record for record in records_list if should_process_one_click_grid_record(record)]`.
2. Process those first.
3. If `write`, set source record `一键重生成状态=处理中`.
4. On success, write `build_one_click_result_update(STATUS_SUCCESS, processed)`.
5. On failure, write `build_one_click_result_update(STATUS_FAILED, failure)`.
6. Then process old candidate-pool pending as before.
7. Include `one_click_pending_count` in returned JSON.

Important: avoid double-processing the same record in old mode if it also has old fields pending. One-click mode wins.

**Step 3: Run tests**

```bash
python3 -m unittest test_ugc_reroll_trigger -v
```

Expected: pass.

---

### Task 4: Add Feishu field bootstrap script or command note

**Files:**
- Modify: `tk_toolkit_dual/tk_ugc_reroll_fields.py` or add one-off documented command
- Optional modify: `docs/ugc/workflow/...`

**Fields to add to UGC-04 (`tblkCASP9y1yZ1Sa`):**

- `一键重生成9宫格` — checkbox
- `一键重生成状态` — single select or text
- `一键重生成结果` — long text

Implementation choice:

- If field creation helper already exists in `tk_ugc_reroll_fields.py`, extend it.
- Otherwise add the three fields manually with `lark-cli base +field-create` or first-class Feishu bitable field tool.

**View recommendation:**

Create/rename a simple daily view:

- `01-一键重生成`

Visible fields only:

- primary task/name field
- `6宫格图片`
- `6宫格生成状态`
- `一键重生成9宫格`
- `一键重生成状态`
- `错误信息`

Old view `03-重新生成入口` becomes advanced or can be hidden later.

---

### Task 5: Smoke test on a safe UGC-04 record

**Files:**
- None unless bug found.

**Step 1: Dry-run field scan**

Set `一键重生成9宫格=true` manually on one known record, e.g. `recvivTIelFiyE` or another testable UGC-04 record.

Run:

```bash
python3 tk_ugc_reroll_trigger.py --stage grid --limit 5
```

Expected:

- `one_click_pending_count=1`
- fails/previews with model-call safety if not using `--call-models`, or indicates would process.

**Step 2: Real run**

Run:

```bash
python3 tk_ugc_reroll_trigger.py --stage grid --limit 5 --write --call-models
```

Expected:

- Same UGC-04 record image fields are overwritten.
- `一键重生成9宫格=false` after completion.
- `一键重生成状态=成功`.
- `6宫格生成状态=成功`.

**Step 3: Confirm no candidate record created**

Check UGC-04 candidate pool count/group result or inspect returned JSON. Expected: no `created_record_ids` for one-click overwrite path.

---

### Task 6: Final docs/user instructions

**Files:**
- Create or modify: `docs/ugc/workflow/ugc-one-click-reroll.md`
- Update: `memory/YYYY-MM-DD.md`

User-facing instructions:

```markdown
日常重生成 9宫格：

1. 打开 UGC-04 的「01-一键重生成」视图。
2. 找到要重生的记录。
3. 勾选「一键重生成9宫格」。
4. 等「一键重生成状态」变成「成功」。

不用填数量、请求、执行状态。系统会直接覆盖当前记录的旧 9宫格图片。
```

---

## Rollback Plan

- Code rollback: revert changes to `tk_ugc_reroll_trigger.py`.
- Feishu rollback: hide or delete `一键重生成9宫格 / 一键重生成状态 / 一键重生成结果` fields.
- Existing candidate-pool reroll remains untouched.
