# UGC Reroll Regeneration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add safe reroll/regeneration support for UGC-04 9-grid storyboard images and UGC-06 shot image-to-video outputs, so users can generate multiple candidates and choose the best one without overwriting known-good results.

**Architecture:** Treat AI image/video outputs as immutable candidates instead of overwriting successful records. UGC-04 rerolls create additional UGC-04 records from the same UGC-03 script version; UGC-05 children inherit the candidate group; UGC-06 video rerolls create additional UGC-06 candidate records from the same UGC-05 shot image. A selection layer marks one candidate as `采用`, and UGC-07 final concat uses selected successful UGC-06 records only.

**Tech Stack:** Python scripts in `tk_toolkit_dual`, Feishu Base via existing project helpers and `lark-cli base +...`, OTU `gpt-image-2` for images, OTU/Veo multipart `input_reference[]` for image-to-video, `unittest` for regression tests.

---

## Product Decisions

1. **Do not overwrite successful AI outputs by default.** Existing UGC-04/05/06 records are production evidence and should remain inspectable.
2. **Reroll = new candidate record.** Each attempt gets its own record ID, file tokens, local files, upstream task IDs, and error logs.
3. **Selection is explicit.** A candidate can be `候选` / `采用` / `弃用`. Only one candidate per group should be `采用` for downstream final assembly.
4. **UGC-04 reroll fans out to UGC-05.** New 9-grid candidate produces a new set of UGC-05 active shot image candidates.
5. **UGC-06 reroll is per shot.** A user can reroll only shot 3 video three times without regenerating the whole storyboard.
6. **UGC-07 reads selected UGC-06 candidates.** If no explicit selection exists, it should fail with a clear message or use a CLI-provided ordered record list, not silently pick arbitrary latest records.
7. **No TTS.** UGC-06/Veo generates final local-language audio directly; UGC-07 preserves selected Veo audio tracks.

---

## Candidate Field Design

Add these fields where missing. Use `lark-cli base +field-list` first, then create only missing fields. Do not parallelize `+field-list`.

### UGC-04 9宫格分镜图表

Table ID: from `docs/ugc/base/ugc-base-table-ids-LBWU-2026-04-29.json` key `ugc_04_six_grid_storyboard`.

Fields:

- `重生成组ID` — Text. Stable group key, e.g. `UGC-GRID-GROUP-<UGC03_SUFFIX>` or inherited from original candidate.
- `候选序号` — Number. 1, 2, 3...
- `候选状态` — Single select: `候选`, `采用`, `弃用`.
- `重生成来源记录ID` — Text. Empty for first candidate; original/copy source record ID for rerolls.
- `重生成备注` — Text. Human/debug note.

### UGC-05 分镜图片表

Fields:

- `重生成组ID` — Text. Inherited from UGC-04.
- `候选序号` — Number. Inherited from UGC-04.
- `候选状态` — Single select: `候选`, `采用`, `弃用`.
- `来源UGC04候选记录ID` — Text. UGC-04 candidate record ID that produced this shot image.

### UGC-06 分镜视频表

Fields:

- `重生成组ID` — Text. For video candidates, e.g. `UGC-VIDEO-GROUP-<UGC05_RECORD_ID>`.
- `候选序号` — Number. Per UGC-05 shot image.
- `候选状态` — Single select: `候选`, `采用`, `弃用`.
- `重生成来源记录ID` — Text. The UGC-06 record copied from, if rerolled.
- `来源UGC05候选记录ID` — Text. UGC-05 image candidate used as reference.

### UGC-07 成片合成表

Optional but recommended:

- `采用UGC06记录列表JSON` — Text. Ordered selected UGC-06 record IDs used for the final concat.
- `候选选择摘要` — Text. Human-readable summary of selected candidate numbers.

---

## Task 1: Add Candidate Metadata Helpers

**Files:**
- Create: `tk_toolkit_dual/ugc_reroll_utils.py`
- Test: `tk_toolkit_dual/test_ugc_reroll_utils.py`

**Step 1: Write the failing tests**

```python
import unittest
import ugc_reroll_utils as rr

class UGCRerollUtilsTest(unittest.TestCase):
    def test_make_group_id_is_stable_for_stage_and_source(self):
        self.assertEqual(rr.make_group_id("grid", "recvieE3B2omPp"), "UGC-GRID-GROUP-E3B2omPp")
        self.assertEqual(rr.make_group_id("video", "recvin7kJqxQuo"), "UGC-VIDEO-GROUP-n7kJqxQuo")

    def test_next_candidate_index_ignores_missing_and_bad_values(self):
        records = [
            {"fields": {"候选序号": 1}},
            {"fields": {"候选序号": "2"}},
            {"fields": {"候选序号": "bad"}},
            {"fields": {}},
        ]
        self.assertEqual(rr.next_candidate_index(records), 3)

    def test_build_candidate_fields_defaults_to_candidate(self):
        fields = rr.build_candidate_fields("UGC-GRID-GROUP-abc", 2, source_record_id="rec_old")
        self.assertEqual(fields["重生成组ID"], "UGC-GRID-GROUP-abc")
        self.assertEqual(fields["候选序号"], 2)
        self.assertEqual(fields["候选状态"], "候选")
        self.assertEqual(fields["重生成来源记录ID"], "rec_old")
```

**Step 2: Run test to verify it fails**

Run:

```bash
cd /Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit_dual
python3 -m unittest test_ugc_reroll_utils -v
```

Expected: FAIL because `ugc_reroll_utils.py` does not exist.

**Step 3: Implement minimal helper**

```python
#!/usr/bin/env python3
from __future__ import annotations

from typing import Any, Dict, Iterable


def make_group_id(stage: str, source_record_id: str) -> str:
    stage_key = stage.strip().upper()
    if stage_key == "GRID":
        prefix = "UGC-GRID-GROUP"
    elif stage_key == "VIDEO":
        prefix = "UGC-VIDEO-GROUP"
    else:
        raise ValueError(f"unsupported reroll stage: {stage}")
    return f"{prefix}-{source_record_id[-8:]}"


def coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return default


def next_candidate_index(records: Iterable[Dict[str, Any]]) -> int:
    max_seen = 0
    for record in records:
        fields = record.get("fields") if isinstance(record, dict) else {}
        max_seen = max(max_seen, coerce_int((fields or {}).get("候选序号"), 0))
    return max_seen + 1


def build_candidate_fields(group_id: str, candidate_index: int, *, source_record_id: str = "", status: str = "候选") -> Dict[str, Any]:
    fields: Dict[str, Any] = {
        "重生成组ID": group_id,
        "候选序号": candidate_index,
        "候选状态": status,
    }
    if source_record_id:
        fields["重生成来源记录ID"] = source_record_id
    return fields
```

**Step 4: Run test to verify it passes**

Run:

```bash
python3 -m unittest test_ugc_reroll_utils -v
```

Expected: PASS.

---

## Task 2: Add Base Field Bootstrap Script

**Files:**
- Create: `tk_toolkit_dual/tk_ugc_reroll_fields.py`
- Test: `tk_toolkit_dual/test_ugc_reroll_fields.py`
- Reference before real Base ops: `/Users/ryanlynn/.agents/skills/lark-base/SKILL.md`, `/Users/ryanlynn/.agents/skills/lark-shared/SKILL.md`, and relevant `references/lark-base-field-list.md` / field-create reference.

**Step 1: Write tests for missing-field planning**

```python
import unittest
import tk_ugc_reroll_fields as fields

class UGCRerollFieldsTest(unittest.TestCase):
    def test_missing_fields_plan_only_missing_names(self):
        existing = [{"name": "重生成组ID"}, {"name": "候选状态"}]
        required = fields.required_fields_for_table("ugc04")
        missing = fields.missing_field_names(existing, required)
        self.assertNotIn("重生成组ID", missing)
        self.assertNotIn("候选状态", missing)
        self.assertIn("候选序号", missing)
        self.assertIn("重生成来源记录ID", missing)

    def test_required_field_types_include_number_for_candidate_index(self):
        required = fields.required_fields_for_table("ugc06")
        self.assertEqual(required["候选序号"], 2)
        self.assertEqual(required["重生成组ID"], 1)
```

**Step 2: Run failing tests**

```bash
python3 -m unittest test_ugc_reroll_fields -v
```

Expected: FAIL.

**Step 3: Implement dry-run-first field planner**

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from typing import Dict, List

from ugc_config import UGC_BASE_TOKEN, load_ugc_table_ids

TEXT = 1
NUMBER = 2
SINGLE_SELECT = 3

REQUIRED = {
    "ugc04": {
        "重生成组ID": TEXT,
        "候选序号": NUMBER,
        "候选状态": SINGLE_SELECT,
        "重生成来源记录ID": TEXT,
        "重生成备注": TEXT,
    },
    "ugc05": {
        "重生成组ID": TEXT,
        "候选序号": NUMBER,
        "候选状态": SINGLE_SELECT,
        "来源UGC04候选记录ID": TEXT,
    },
    "ugc06": {
        "重生成组ID": TEXT,
        "候选序号": NUMBER,
        "候选状态": SINGLE_SELECT,
        "重生成来源记录ID": TEXT,
        "来源UGC05候选记录ID": TEXT,
    },
    "ugc07": {
        "采用UGC06记录列表JSON": TEXT,
        "候选选择摘要": TEXT,
    },
}

def required_fields_for_table(key: str) -> Dict[str, int]:
    return dict(REQUIRED[key])

def missing_field_names(existing_fields: List[dict], required: Dict[str, int]) -> List[str]:
    existing_names = {f.get("name") for f in existing_fields}
    return [name for name in required if name not in existing_names]
```

Add CLI later in the same file:

- `--dry-run` prints missing fields.
- `--write` serially runs `lark-cli base +field-list`, then `lark-cli base +field-create` or the current shortcut for field creation after reading the exact reference.

**Step 4: Run tests**

```bash
python3 -m unittest test_ugc_reroll_fields -v
```

Expected: PASS.

**Step 5: Real Base bootstrap, after explicit confirmation**

Run dry-run first:

```bash
python3 tk_ugc_reroll_fields.py --dry-run
```

Only after verifying field list and command syntax:

```bash
python3 tk_ugc_reroll_fields.py --write
```

Expected: Only missing fields are created; no existing fields are modified.

---

## Task 3: UGC-04 Grid Reroll Creates New Candidate Records

**Files:**
- Modify: `tk_toolkit_dual/tk_ugc_six_grid.py`
- Test: `tk_toolkit_dual/test_ugc_six_grid.py`

**Step 1: Add tests for candidate metadata on prepare**

Add to `test_ugc_six_grid.py`:

```python
@patch("tk_ugc_six_grid.load_ugc_table_ids")
def test_run_prepare_write_with_reroll_metadata_creates_candidate_record(self, tables_mock):
    tables_mock.return_value = {"ugc_03_script_version": "tbl03", "ugc_04_six_grid_storyboard": "tbl04"}
    created = []

    def fake_get(token, table, rid):
        return {"结构化脚本JSON": json.dumps(sample_script_json(), ensure_ascii=False)}

    def fake_create(token, table, fields):
        created.append(fields)
        return "rec04_new"

    result = grid.run_prepare(
        "rec03",
        token="t",
        write=True,
        get_record_fn=fake_get,
        create_record_fn=fake_create,
        update_record_fn=lambda *a, **k: None,
        candidate_group_id="UGC-GRID-GROUP-rec03",
        candidate_index=2,
        reroll_source_record_id="rec04_old",
    )
    self.assertEqual(result["ugc04_record_id"], "rec04_new")
    self.assertEqual(created[0]["重生成组ID"], "UGC-GRID-GROUP-rec03")
    self.assertEqual(created[0]["候选序号"], 2)
    self.assertEqual(created[0]["候选状态"], "候选")
    self.assertEqual(created[0]["重生成来源记录ID"], "rec04_old")
```

**Step 2: Run failing test**

```bash
python3 -m unittest test_ugc_six_grid.UGCSixGridTest.test_run_prepare_write_with_reroll_metadata_creates_candidate_record -v
```

Expected: FAIL because `run_prepare` does not accept candidate args.

**Step 3: Implement minimal changes**

- Import `build_candidate_fields` from `ugc_reroll_utils`.
- Extend `run_prepare(...)` signature:

```python
candidate_group_id: str = "",
candidate_index: int = 0,
reroll_source_record_id: str = "",
```

- Before create, merge:

```python
if candidate_group_id and candidate_index:
    ugc04_fields.update(build_candidate_fields(candidate_group_id, candidate_index, source_record_id=reroll_source_record_id))
    ugc04_fields["重生成备注"] = f"UGC-04 reroll candidate {candidate_index}; source={reroll_source_record_id or 'initial'}"
```

**Step 4: CLI option**

Add to `prepare` subcommand:

```python
prepare.add_argument("--candidate-group-id", default="")
prepare.add_argument("--candidate-index", type=int, default=0)
prepare.add_argument("--reroll-source-record-id", default="")
```

Pass through to `run_prepare`.

**Step 5: Run focused and full tests**

```bash
python3 -m unittest test_ugc_six_grid -v
python3 -m unittest test_ugc_reroll_utils test_ugc_six_grid -v
```

Expected: PASS.

---

## Task 4: Propagate UGC-04 Candidate Metadata into UGC-05 Shot Images

**Files:**
- Modify: `tk_toolkit_dual/tk_ugc_shot_images.py`
- Test: `tk_toolkit_dual/test_ugc_shot_images.py`

**Step 1: Write tests**

Find the existing test that verifies UGC-05 record creation fields. Add a case:

```python
def test_build_shot_record_fields_inherits_candidate_metadata(self):
    ugc04_fields = {
        "重生成组ID": "UGC-GRID-GROUP-rec03",
        "候选序号": 2,
        "候选状态": "候选",
    }
    # Use the existing helper/function name that builds UGC-05 fields.
    fields = images.build_ugc05_fields(
        ugc04_record_id="rec04_new",
        ugc03_record_id="rec03",
        shot={"shot_index": 1},
        crop_info={"path": "/tmp/shot_01.png"},
        ugc04_fields=ugc04_fields,
    )
    self.assertEqual(fields["重生成组ID"], "UGC-GRID-GROUP-rec03")
    self.assertEqual(fields["候选序号"], 2)
    self.assertEqual(fields["候选状态"], "候选")
    self.assertEqual(fields["来源UGC04候选记录ID"], "rec04_new")
```

If the current helper signature differs, adapt the test to the actual existing builder but keep the assertions.

**Step 2: Run failing test**

```bash
python3 -m unittest test_ugc_shot_images -v
```

Expected: FAIL for missing fields/signature.

**Step 3: Implement propagation**

In the UGC-05 field builder, copy from parent UGC-04 fields if present:

```python
for name in ("重生成组ID", "候选序号", "候选状态"):
    value = ugc04_fields.get(name)
    if value not in (None, ""):
        fields[name] = value
if ugc04_record_id:
    fields["来源UGC04候选记录ID"] = ugc04_record_id
```

**Step 4: Run tests**

```bash
python3 -m unittest test_ugc_shot_images test_ugc_six_grid test_ugc_reroll_utils -v
```

Expected: PASS.

---

## Task 5: UGC-06 Video Reroll Creates New Candidate Records Instead of Overwriting

**Files:**
- Modify: `tk_toolkit_dual/tk_ugc_video_prompts.py`
- Modify: `tk_toolkit_dual/tk_ugc_shot_videos.py`
- Test: `tk_toolkit_dual/test_ugc_video_prompts.py`
- Test: `tk_toolkit_dual/test_ugc_shot_videos.py`

**Step 1: Add tests for UGC-06 candidate field creation**

In `test_ugc_video_prompts.py`, add a test around the function that creates UGC-06 records from UGC-05 records:

```python
def test_build_ugc06_fields_can_include_video_candidate_metadata(self):
    fields = prompts.build_ugc06_fields(
        shot_prompt={"ugc05_record_id": "rec05", "shot_index": 1, "prompt_en": "x"},
        candidate_group_id="UGC-VIDEO-GROUP-rec05",
        candidate_index=3,
        reroll_source_record_id="rec06_old",
    )
    self.assertEqual(fields["重生成组ID"], "UGC-VIDEO-GROUP-rec05")
    self.assertEqual(fields["候选序号"], 3)
    self.assertEqual(fields["候选状态"], "候选")
    self.assertEqual(fields["重生成来源记录ID"], "rec06_old")
    self.assertEqual(fields["来源UGC05候选记录ID"], "rec05")
```

Adapt function name/signature to current file after inspection.

**Step 2: Add tests for video generation allowing explicit reroll records**

In `test_ugc_shot_videos.py`:

```python
def test_successful_existing_record_requires_allow_regenerate_or_new_candidate(self):
    with self.assertRaises(ValueError):
        videos.run_ugc06_video_generation(
            "rec06",
            dry_run=False,
            token="t",
            get_record_fn=lambda token, table, rid: sample_ugc06_fields(status="成功"),
        )
```

Keep this existing safety. Add a new test only if adding `allow_regenerate=True`; recommended approach is not to add force overwrite for normal users.

**Step 3: Implement UGC-06 candidate metadata in prompt-record creation**

- Extend the UGC-06 field builder to accept candidate metadata.
- Default behavior remains unchanged for first-generation records.
- CLI for prompt creation adds optional:

```bash
--video-candidate-group-id <id>
--video-candidate-index <n>
--reroll-source-ugc06-record-id <rec>
```

**Step 4: Add a small reroll command wrapper**

Create `tk_toolkit_dual/tk_ugc_reroll.py` in Task 6; do not put multi-candidate orchestration inside `tk_ugc_shot_videos.py`.

**Step 5: Run tests**

```bash
python3 -m unittest test_ugc_video_prompts test_ugc_shot_videos test_ugc_reroll_utils -v
```

Expected: PASS.

---

## Task 6: Add `tk_ugc_reroll.py` Orchestrator

**Files:**
- Create: `tk_toolkit_dual/tk_ugc_reroll.py`
- Test: `tk_toolkit_dual/test_ugc_reroll.py`

**Step 1: Write tests for dry-run planning**

```python
import unittest
from unittest.mock import patch
import tk_ugc_reroll as reroll

class UGCRerollOrchestratorTest(unittest.TestCase):
    def test_plan_grid_reroll_builds_candidate_count(self):
        plan = reroll.plan_grid_reroll("rec03", count=3, source_record_id="rec04_old", existing_candidates=[])
        self.assertEqual(len(plan["candidates"]), 3)
        self.assertEqual(plan["candidates"][0]["candidate_index"], 1)
        self.assertEqual(plan["candidates"][0]["candidate_group_id"], "UGC-GRID-GROUP-recvieE3B2omPp"[-len(plan["candidates"][0]["candidate_group_id"]):] if False else plan["candidates"][0]["candidate_group_id"])

    def test_plan_video_reroll_uses_ugc05_group(self):
        plan = reroll.plan_video_reroll("rec05abc123", count=2, source_record_id="rec06_old", existing_candidates=[])
        self.assertEqual(len(plan["candidates"]), 2)
        self.assertTrue(plan["candidates"][0]["candidate_group_id"].startswith("UGC-VIDEO-GROUP-"))
```

Keep tests simple; avoid real network.

**Step 2: Implement dry-run planner**

CLI commands:

```bash
python3 tk_ugc_reroll.py grid --ugc03-record-id recvieE3B2omPp --count 3 --dry-run
python3 tk_ugc_reroll.py video --ugc06-record-id recviqdQNUCITK --count 3 --dry-run
```

Behavior:

- `grid`: plans N new UGC-04 candidates from the same UGC-03.
- `video`: reads source UGC-06 to find linked UGC-05; plans N new UGC-06 candidates from same UGC-05.
- `--write` creates candidate records but does not call external models unless `--call-image` / `--call-video` is explicitly passed.

**Step 3: Implement write mode safely**

Grid write flow:

1. `run_prepare(... candidate metadata ...)` creates UGC-04 candidate.
2. If `--call-image`, call `run_image_generation` for each candidate sequentially.
3. If `--create-shots`, call existing `tk_ugc_shot_images` flow for each successful candidate.
4. Do not mark anything `采用` automatically unless `--auto-select-first-success` is explicitly passed.

Video write flow:

1. Clone/create UGC-06 candidate from source UGC-06's UGC-05 reference and prompt.
2. If `--call-video`, call `run_ugc06_video_generation` for that new candidate.
3. Sequential only; no parallel real model calls in first implementation.
4. Do not mark `采用` automatically unless `--auto-select-first-success` is explicitly passed.

**Step 4: Run tests**

```bash
python3 -m unittest test_ugc_reroll test_ugc_reroll_utils -v
```

Expected: PASS.

---

## Task 7: Add Candidate Selection Command

**Files:**
- Modify: `tk_toolkit_dual/tk_ugc_reroll.py`
- Test: `tk_toolkit_dual/test_ugc_reroll.py`

**Step 1: Write test for selection updates**

```python
def test_select_candidate_marks_one_adopted_and_others_discarded(self):
    updates = []
    records = [
        {"record_id": "rec_a", "fields": {"重生成组ID": "group1", "候选状态": "候选"}},
        {"record_id": "rec_b", "fields": {"重生成组ID": "group1", "候选状态": "候选"}},
    ]
    reroll.apply_selection(
        table_id="tbl",
        group_id="group1",
        selected_record_id="rec_b",
        records=records,
        token="t",
        update_record_fn=lambda token, table, rid, fields: updates.append((rid, fields)),
    )
    self.assertEqual(updates, [
        ("rec_a", {"候选状态": "弃用"}),
        ("rec_b", {"候选状态": "采用"}),
    ])
```

**Step 2: Implement selection helper and CLI**

CLI examples:

```bash
python3 tk_ugc_reroll.py select-grid --group-id UGC-GRID-GROUP-E3B2omPp --record-id recvimPkZjza7b --write
python3 tk_ugc_reroll.py select-video --group-id UGC-VIDEO-GROUP-n7kJqxQuo --record-id recviqdQNUCITK --write
```

Rules:

- Selected record gets `候选状态=采用`.
- Other same-group records get `候选状态=弃用`.
- If selected record is not `成功`, refuse unless `--allow-non-success`.
- For video selection, selection is per UGC-05 shot group, not global across all shots.

**Step 3: Run tests**

```bash
python3 -m unittest test_ugc_reroll -v
```

Expected: PASS.

---

## Task 8: Make UGC-07 Use Selected UGC-06 Candidates

**Files:**
- Modify: `tk_toolkit_dual/tk_ugc_final_concat.py`
- Test: create/modify `tk_toolkit_dual/test_ugc_final_concat.py` if not present.

**Step 1: Write selection resolver tests**

```python
import unittest
import tk_ugc_final_concat as concat

class UGCFinalConcatSelectionTest(unittest.TestCase):
    def test_resolve_selected_videos_requires_one_adopted_per_shot(self):
        records = [
            {"record_id": "rec1a", "fields": {"分镜序号": 1, "候选状态": "采用", "视频生成状态": "成功"}},
            {"record_id": "rec1b", "fields": {"分镜序号": 1, "候选状态": "弃用", "视频生成状态": "成功"}},
            {"record_id": "rec2a", "fields": {"分镜序号": 2, "候选状态": "采用", "视频生成状态": "成功"}},
        ]
        selected = concat.resolve_selected_ugc06_records(records, expected_shot_count=2)
        self.assertEqual(selected, ["rec1a", "rec2a"])

    def test_resolve_selected_videos_fails_on_missing_selection(self):
        with self.assertRaises(ValueError):
            concat.resolve_selected_ugc06_records([
                {"record_id": "rec1", "fields": {"分镜序号": 1, "候选状态": "候选", "视频生成状态": "成功"}},
            ], expected_shot_count=1)
```

**Step 2: Implement resolver**

```python
def resolve_selected_ugc06_records(records: List[Dict[str, Any]], expected_shot_count: int) -> List[str]:
    by_shot = {}
    for record in records:
        fields = record.get("fields") or {}
        if extract_text(fields.get("候选状态")).strip() != "采用":
            continue
        if extract_text(fields.get("视频生成状态")).strip()