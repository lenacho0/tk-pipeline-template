# UGC Workflow Code Integration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the first executable UGC workflow slice: `UGC-01` single video analysis → `UGC-02/UGC-03` script task derivation → `UGC-03` one-version script generation.

**Architecture:** Keep UGC isolated and only reference the UGC table group, fields, and states. Add UGC-specific modules under `tk_toolkit_dual/` that use the LBWU UGC table IDs and the confirmed prompt documents. Start with explicit CLI/dry-run execution, then add dispatcher automation only after manual tests pass.

**Tech Stack:** Python 3, Feishu Bitable Open API, `tk_toolkit_dual` project, Gemini-compatible LLM client, JSON_OUTPUT/MARKDOWN_OUTPUT parsing, local docs and prompt files.

---

## Non-Negotiable Rules

- Use Base token `LBWUbgRfEavAgjsXNIhcpo0Dnvb` for UGC work.
- Do not use the accidentally-created Base `Zgzqbp71zaFXgOs94l4c0nlVnef` for UGC.
- Use only UGC table names, UGC field names, and UGC status names in all new code/docs. Do not introduce non-UGC table numbers, non-UGC stage names, or non-UGC flow vocabulary.
- Product truth is always `UGC-01.关联产品 → 初始化-产品信息`.
- `UGC-02/03.关联产品` are inherited/read-only display fields, not user input.
- `JSON_OUTPUT` is the machine source of truth; do not parse Markdown for downstream fields.
- Keep changes small and verify each stage before moving on.

---

## Reference Files

- Prompt: `docs/prompts/ugc-single-video-analysis-system-prompt-v1.md`
- Prompt: `docs/prompts/ugc-script-generation-system-prompt-v1.md`
- Flow design: `docs/ugc/workflow/ugc-analysis-to-script-generation-v1.md`
- Base structure: `docs/ugc/base/ugc-base-created-LBWU-2026-04-29.md`
- Table IDs: `docs/ugc/base/ugc-base-table-ids-LBWU-2026-04-29.json`
- Field snapshot: `docs/ugc/base/ugc-base-fields-LBWU-2026-04-29.json`
- View snapshot: `docs/ugc/base/ugc-base-views-LBWU-2026-04-29.json`
- Current package: `tk_toolkit_dual/`

---

## Task 1: Add UGC Configuration Layer

**Files:**
- Create: `tk_toolkit_dual/ugc_config.py`
- Modify: `tk_toolkit_dual/config.example.json`
- Optional local-only modify: `tk_toolkit_dual/config.json`
- Test: `tk_toolkit_dual/test_ugc_config.py`

**Step 1: Write the failing test**

Create `tk_toolkit_dual/test_ugc_config.py`:

```python
from pathlib import Path

from ugc_config import load_ugc_table_ids, UGC_BASE_TOKEN


def test_load_ugc_table_ids_from_docs_snapshot():
    table_ids = load_ugc_table_ids(Path("docs/ugc/base/ugc-base-table-ids-LBWU-2026-04-29.json"))
    assert UGC_BASE_TOKEN == "LBWUbgRfEavAgjsXNIhcpo0Dnvb"
    assert table_ids["ugc_01_analysis"] == "tblSPpWWOrnOzHSq"
    assert table_ids["ugc_02_script_batch"] == "tblbLHA2DyIwZHfF"
    assert table_ids["ugc_03_script_version"] == "tblgDc6nuk6UWkLH"
```

**Step 2: Run test to verify it fails**

Run:

```bash
cd tk_toolkit_dual && python3 -m unittest test_ugc_config -v
```

Expected: FAIL because `ugc_config` does not exist.

**Step 3: Implement minimal config module**

Create `tk_toolkit_dual/ugc_config.py`:

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

UGC_BASE_TOKEN = "LBWUbgRfEavAgjsXNIhcpo0Dnvb"
TABLE_IDS_PATH = Path(__file__).resolve().parents[1] / "docs" / "ugc-base-table-ids-LBWU-2026-04-29.json"


def load_ugc_table_ids(path: Path = TABLE_IDS_PATH) -> Dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    required = [
        "ugc_01_analysis",
        "ugc_02_script_batch",
        "ugc_03_script_version",
        "ugc_04_six_grid_storyboard",
        "ugc_05_shot_images",
        "ugc_06_shot_videos",
        "ugc_07_final_concat",
    ]
    missing = [key for key in required if not data.get(key)]
    if missing:
        raise ValueError(f"Missing UGC table ids: {missing}")
    return data
```

**Step 4: Run test to verify it passes**

Run:

```bash
cd tk_toolkit_dual && python3 -m unittest test_ugc_config -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add tk_toolkit_dual/ugc_config.py tk_toolkit_dual/test_ugc_config.py tk_toolkit_dual/config.example.json
git commit -m "feat: add UGC workflow config"
```

---

## Task 2: Add Shared UGC Parsing Utilities

**Files:**
- Create: `tk_toolkit_dual/ugc_utils.py`
- Test: `tk_toolkit_dual/test_ugc_utils.py`

**Step 1: Write tests**

Create `tk_toolkit_dual/test_ugc_utils.py`:

```python
from ugc_utils import (
    extract_text,
    extract_linked_record_ids,
    parse_dual_output,
)


def test_extract_linked_record_ids_handles_feishu_link_shape():
    value = [{"record_ids": ["recA"]}, {"record_ids": ["recB", "recC"]}]
    assert extract_linked_record_ids(value) == ["recA", "recB", "recC"]


def test_parse_dual_output_extracts_json_and_markdown():
    raw = 'JSON_OUTPUT\n{"a": 1}\nMARKDOWN_OUTPUT\n# Report\nhello'
    parsed = parse_dual_output(raw)
    assert parsed.json_obj == {"a": 1}
    assert parsed.markdown.strip() == "# Report\nhello"


def test_parse_dual_output_rejects_missing_json_marker():
    raw = '{"a": 1}\nMARKDOWN_OUTPUT\n# Report'
    try:
        parse_dual_output(raw)
    except ValueError as exc:
        assert "JSON_OUTPUT" in str(exc)
    else:
        raise AssertionError("expected ValueError")
```

**Step 2: Run tests to verify failure**

```bash
cd tk_toolkit_dual && python3 -m unittest test_ugc_utils -v
```

Expected: FAIL because module does not exist.

**Step 3: Implement utilities**

Create `tk_toolkit_dual/ugc_utils.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Dict, List


def extract_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                parts.append(str(item.get("text", "")))
            else:
                parts.append(str(item))
        return "".join(parts)
    return str(value)


def extract_linked_record_ids(value: Any) -> List[str]:
    ids: List[str] = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                record_ids = item.get("record_ids") or []
                ids.extend(str(record_id) for record_id in record_ids if record_id)
    return ids


@dataclass
class DualOutput:
    json_obj: Dict[str, Any]
    markdown: str


def parse_dual_output(raw: str) -> DualOutput:
    if "JSON_OUTPUT" not in raw:
        raise ValueError("Missing JSON_OUTPUT marker")
    if "MARKDOWN_OUTPUT" not in raw:
        raise ValueError("Missing MARKDOWN_OUTPUT marker")
    json_part = raw.split("JSON_OUTPUT", 1)[1].split("MARKDOWN_OUTPUT", 1)[0].strip()
    markdown = raw.split("MARKDOWN_OUTPUT", 1)[1].strip()
    if json_part.startswith("```"):
        raise ValueError("JSON_OUTPUT must not be wrapped in markdown code fence")
    json_obj = json.loads(json_part)
    if not isinstance(json_obj, dict):
        raise ValueError("JSON_OUTPUT must be a JSON object")
    return DualOutput(json_obj=json_obj, markdown=markdown)
```

**Step 4: Run tests**

```bash
cd tk_toolkit_dual && python3 -m unittest test_ugc_utils -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add tk_toolkit_dual/ugc_utils.py tk_toolkit_dual/test_ugc_utils.py
git commit -m "feat: add UGC output parsing utilities"
```

---

## Task 3: Implement UGC-01 Input Validation and Product Resolution

**Files:**
- Create: `tk_toolkit_dual/tk_ugc_single_video_analyze.py`
- Test: `tk_toolkit_dual/test_ugc_single_video_analyze.py`

**Step 1: Write tests**

Create `tk_toolkit_dual/test_ugc_single_video_analyze.py`:

```python
from tk_ugc_single_video_analyze import validate_ugc01_inputs


def test_validate_requires_video_source_product_and_market():
    fields = {
        "视频来源类型": "视频链接",
        "视频链接": "https://example.com/video.mp4",
        "关联产品": [{"record_ids": ["recProduct"]}],
        "目标市场": "美国",
    }
    result = validate_ugc01_inputs(fields)
    assert result.ready is True
    assert result.blocking_missing_fields == []
    assert result.linked_product_record_id == "recProduct"


def test_validate_blocks_missing_product():
    fields = {"视频来源类型": "视频链接", "视频链接": "https://example.com/video.mp4", "目标市场": "美国"}
    result = validate_ugc01_inputs(fields)
    assert result.ready is False
    assert "linked_product" in result.blocking_missing_fields


def test_validate_file_has_priority_over_link():
    fields = {
        "视频来源类型": "链接+文件",
        "视频链接": "https://example.com/video.mp4",
        "视频文件": [{"file_token": "fileA"}],
        "关联产品": [{"record_ids": ["recProduct"]}],
        "目标市场": "美国",
    }
    result = validate_ugc01_inputs(fields)
    assert result.video_source_type == "file"
```

**Step 2: Run test to verify failure**

```bash
cd tk_toolkit_dual && python3 -m unittest test_ugc_single_video_analyze -v
```

Expected: FAIL because module/function does not exist.

**Step 3: Implement validation model**

In `tk_toolkit_dual/tk_ugc_single_video_analyze.py`, implement:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from ugc_utils import extract_text, extract_linked_record_ids


@dataclass
class UGC01ValidationResult:
    ready: bool
    video_source_type: str
    linked_product_record_id: str
    target_market: str
    blocking_missing_fields: List[str]


def validate_ugc01_inputs(fields: Dict[str, Any]) -> UGC01ValidationResult:
    video_link = extract_text(fields.get("视频链接")).strip()
    has_video_file = bool(fields.get("视频文件"))
    product_ids = extract_linked_record_ids(fields.get("关联产品"))
    target_market = extract_text(fields.get("目标市场")).strip()

    missing: List[str] = []
    if not video_link and not has_video_file:
        missing.append("video_source")
    if not product_ids:
        missing.append("linked_product")
    if not target_market:
        missing.append("target_market")

    if has_video_file:
        video_source_type = "file"
    elif video_link:
        video_source_type = "link"
    else:
        video_source_type = "missing"

    return UGC01ValidationResult(
        ready=not missing,
        video_source_type=video_source_type,
        linked_product_record_id=product_ids[0] if product_ids else "",
        target_market=target_market,
        blocking_missing_fields=missing,
    )
```

**Step 4: Run tests**

```bash
cd tk_toolkit_dual && python3 -m unittest test_ugc_single_video_analyze -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add tk_toolkit_dual/tk_ugc_single_video_analyze.py tk_toolkit_dual/test_ugc_single_video_analyze.py
git commit -m "feat: validate UGC analysis inputs"
```

---

## Task 4: Implement UGC-01 Single Video Analysis CLI Skeleton

**Files:**
- Modify: `tk_toolkit_dual/tk_ugc_single_video_analyze.py`
- Test: `tk_toolkit_dual/test_ugc_single_video_analyze.py`

**Step 1: Add tests for status payloads**

Extend `tk_toolkit_dual/test_ugc_single_video_analyze.py`:

```python
from tk_ugc_single_video_analyze import build_blocked_analysis_payload


def test_build_blocked_analysis_payload_sets_low_confidence():
    result = validate_ugc01_inputs({"目标市场": "美国"})
    payload = build_blocked_analysis_payload(result)
    assert payload["分析状态"] == "分析失败"
    assert "分析结果JSON" in payload
    assert '"ready_for_formal_analysis": false' in payload["分析结果JSON"]
    assert '"overall": "low"' in payload["分析结果JSON"]
```

**Step 2: Run test to verify failure**

```bash
cd tk_toolkit_dual && python3 -m unittest test_ugc_single_video_analyze -v
```

Expected: FAIL because `build_blocked_analysis_payload` does not exist.

**Step 3: Implement payload builder and CLI shell**

Add functions:

```python
import json
import sys


def build_blocked_analysis_payload(result: UGC01ValidationResult) -> Dict[str, Any]:
    json_obj = {
        "analysis_scope": "single_video",
        "video_type": "UGC",
        "input_requirements": {
            "video_source_type": result.video_source_type,
            "linked_product_record_id": result.linked_product_record_id,
            "target_market": result.target_market,
            "ready_for_formal_analysis": False,
            "blocking_missing_fields": result.blocking_missing_fields,
        },
        "confidence": {"overall": "low"},
        "error": "缺少正式分析所需输入",
    }
    return {
        "分析状态": "分析失败",
        "分析结果JSON": json.dumps(json_obj, ensure_ascii=False, indent=2),
        "分析摘要": "缺少必要输入：" + "、".join(result.blocking_missing_fields),
    }


def main(argv=None):
    argv = argv or sys.argv
    if len(argv) < 2:
        raise SystemExit("Usage: python -m tk_ugc_single_video_analyze <UGC01_RECORD_ID>")
    record_id = argv[1]
    # Later tasks will wire Feishu read/write and LLM call.
    print(f"UGC single video analyze skeleton ready: {record_id}")
```

**Step 4: Run tests**

```bash
cd tk_toolkit_dual && python3 -m unittest test_ugc_single_video_analyze -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add tk_toolkit_dual/tk_ugc_single_video_analyze.py tk_toolkit_dual/test_ugc_single_video_analyze.py
git commit -m "feat: add UGC analysis blocked payload"
```

---

## Task 5: Wire Feishu Read/Write for UGC-01 Analysis

**Files:**
- Modify: `tk_toolkit_dual/tk_ugc_single_video_analyze.py`
- Modify: `tk_toolkit_dual/common.py` if reusable helpers are needed
- Test: manual dry-run against one test UGC-01 record

**Step 1: Implement Feishu wiring**

Use existing helpers from `tk_toolkit_dual/common.py` where possible:

- `get_feishu_token`
- `get_record`
- `update_record`

Implementation flow:

1. Get token.
2. Read `UGC-01` record from `ugc_01_analysis` table.
3. Set `分析状态 = 分析中`.
4. Validate required inputs.
5. If invalid, write blocked payload and stop.
6. If valid, continue to Task 6 LLM call.

**Step 2: Add safe dry-run option**

Support environment variable:

```bash
UGC_DRY_RUN=1
```

When set, print intended updates but do not write Feishu.

**Step 3: Run dry-run**

```bash
UGC_DRY_RUN=1 python3 -m tk_ugc_single_video_analyze <record_id>
```

Expected:

- Logs show record read.
- Logs show validation result.
- No Feishu update is made.

**Step 4: Run blocked real-write test on an intentionally incomplete test row**

```bash
python3 -m tk_ugc_single_video_analyze <incomplete_record_id>
```

Expected:

- `分析状态 = 分析失败`.
- `分析结果JSON.input_requirements.ready_for_formal_analysis = false`.
- `confidence.overall = low`.

**Step 5: Commit**

```bash
git add tk_toolkit_dual/tk_ugc_single_video_analyze.py tk_toolkit_dual/common.py
git commit -m "feat: wire UGC analysis Feishu record updates"
```

---

## Task 6: Implement Prompt Loading and LLM Dual Output Parsing for UGC-01

**Files:**
- Modify: `tk_toolkit_dual/tk_ugc_single_video_analyze.py`
- Test: `tk_toolkit_dual/test_ugc_single_video_analyze.py`

**Step 1: Add prompt loading test**

```python
from tk_ugc_single_video_analyze import load_analysis_system_prompt


def test_load_analysis_system_prompt_contains_dual_output_contract():
    prompt = load_analysis_system_prompt()
    assert "JSON_OUTPUT" in prompt
    assert "MARKDOWN_OUTPUT" in prompt
    assert "script_generation_handoff" in prompt
```

**Step 2: Implement prompt loader**

```python
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
ANALYSIS_PROMPT_PATH = ROOT_DIR / "docs" / "ugc-single-video-analysis-system-prompt-v1.md"


def load_analysis_system_prompt(path: Path = ANALYSIS_PROMPT_PATH) -> str:
    return path.read_text(encoding="utf-8")
```

**Step 3: Build model input block**

The prompt payload must include:

- video source type
- video link or file marker
- linked product record id
- product record fields from `初始化-产品信息`
- target market
- UGC-01 record id

Do not ask the user for product fields again.

**Step 4: Call LLM and parse output**

Use `parse_dual_output()` from Task 2.

Write back:

- `分析状态 = 分析成功`
- `分析结果JSON = json.dumps(parsed.json_obj, ensure_ascii=False, indent=2)`
- `分析结果Markdown = parsed.markdown`
- `分析摘要 = parsed.json_obj["script_generation_handoff"]["single_video_pattern_summary"]` if available, else a short fallback summary.

**Step 5: Run tests**

```bash
cd tk_toolkit_dual && python3 -m unittest test_ugc_single_video_analyze test_ugc_utils -v
```

Expected: PASS.

**Step 6: Manual dry-run with mock output**

Add environment option:

```bash
UGC_MOCK_LLM_OUTPUT=/path/to/mock_dual_output.txt
```

Run:

```bash
UGC_DRY_RUN=1 UGC_MOCK_LLM_OUTPUT=fixtures/ugc_analysis_mock_output.txt python3 -m tk_ugc_single_video_analyze <record_id>
```

Expected: parsed JSON/Markdown printed; no write.

**Step 7: Commit**

```bash
git add tk_toolkit_dual/tk_ugc_single_video_analyze.py tk_toolkit_dual/test_ugc_single_video_analyze.py
git commit -m "feat: parse UGC analysis dual output"
```

---

## Task 7: Write UGC Analysis Prompt into Runtime Config Table

**Files:**
- Create: `scripts/sync_ugc_prompts_to_base.py`
- Modify: `docs/ugc/base/ugc-base-created-LBWU-2026-04-29.md`
- Test: manual read-back from Base config table

**Step 1: Identify config table and required fields**

Use `lark-cli base +table-list` and `+field-list` on Base `LBWU...` to identify the configuration table and prompt field names.

**Step 2: Create sync script**

The script should write:

- 环节: `UGC-单视频爆款分析`
- 提示词: content of `docs/prompts/ugc-single-video-analysis-system-prompt-v1.md`
- 环节: `UGC-脚本生成`
- 提示词: content of `docs/prompts/ugc-script-generation-system-prompt-v1.md`

Do not overwrite unrelated config rows.

**Step 3: Run sync script**

```bash
python3 scripts/sync_ugc_prompts_to_base.py
```

Expected:

- Existing rows updated or rows created.
- Script prints record ids.

**Step 4: Read back records**

Use `lark-cli base +record-list` or first-class Feishu tools to confirm prompt field is non-empty.

**Step 5: Commit**

```bash
git add scripts/sync_ugc_prompts_to_base.py docs/ugc/base/ugc-base-created-LBWU-2026-04-29.md
git commit -m "feat: sync UGC prompts to Base config"
```

---

## Task 8: Implement UGC-01 → UGC-02/UGC-03 Script Batch Derivation

**Files:**
- Create: `tk_toolkit_dual/tk_ugc_script_batch_create.py`
- Test: `tk_toolkit_dual/test_ugc_script_batch_create.py`

**Step 1: Write tests for version plan allocation**

```python
from tk_ugc_script_batch_create import choose_test_points


def test_choose_test_points_for_one_script_uses_standard():
    assert choose_test_points(1) == ["standard"]


def test_choose_test_points_for_three_scripts_uses_default_pool():
    assert choose_test_points(3) == ["hook_angle", "scene_entry", "trust_builder"]


def test_choose_test_points_for_four_scripts_adds_cta():
    assert choose_test_points(4) == ["hook_angle", "scene_entry", "trust_builder", "cta_style"]
```

**Step 2: Run test to fail**

```bash
cd tk_toolkit_dual && python3 -m unittest test_ugc_script_batch_create -v
```

Expected: FAIL because module does not exist.

**Step 3: Implement allocation**

```python
DEFAULT_POINTS = ["hook_angle", "scene_entry", "trust_builder", "cta_style"]


def choose_test_points(count: int):
    if count <= 0:
        raise ValueError("目标脚本数量必须大于 0")
    if count == 1:
        return ["standard"]
    pool = DEFAULT_POINTS[:]
    while len(pool) < count:
        pool.append("pain_point_moment")
    return pool[:count]
```

**Step 4: Implement Feishu derivation**

Flow:

1. Read `UGC-01` source record.
2. Validate:
   - `分析状态 = 分析成功`
   - `脚本派生状态 = 待派生`
   - `关联产品` exists
   - `目标市场` exists
   - `目标脚本数量` exists
   - `分析结果JSON.script_generation_handoff` exists
3. Create one `UGC-02` record.
4. Create N `UGC-03` records.
5. Copy `UGC-01.关联产品` into `UGC-02/03.关联产品`.
6. Set `UGC-03.主测试点` using `choose_test_points()`.
7. Write back `UGC-01.脚本批次ID` and `脚本派生状态 = 已派生`.

**Step 5: Dry-run**

```bash
UGC_DRY_RUN=1 python3 -m tk_ugc_script_batch_create <ugc01_record_id>
```

Expected: prints one batch payload and N version payloads.

**Step 6: Real-write on one test record**

```bash
python3 -m tk_ugc_script_batch_create <ugc01_record_id>
```

Expected:

- One `UGC-02` batch created.
- N `UGC-03` records created.
- `主测试点` is populated on every version.
- No user product selection required in UGC-02/03.

**Step 7: Commit**

```bash
git add tk_toolkit_dual/tk_ugc_script_batch_create.py tk_toolkit_dual/test_ugc_script_batch_create.py
git commit -m "feat: derive UGC script batch and versions"
```

---

## Task 9: Implement UGC-03 One-Version Script Generation

**Files:**
- Create: `tk_toolkit_dual/tk_ugc_script_generate.py`
- Test: `tk_toolkit_dual/test_ugc_script_generate.py`

**Step 1: Write tests for prompt input assembly**

```python
from tk_ugc_script_generate import build_script_prompt_payload


def test_build_script_prompt_payload_prefers_ugc01_product_truth():
    payload = build_script_prompt_payload(
        ugc01_fields={"关联产品": [{"record_ids": ["recProduct"]}], "目标市场": "美国"},
        ugc03_fields={"主测试点": "hook_angle", "版本ID": "V1"},
        handoff={"must_preserve": ["真实感"], "can_replace": ["场景"]},
        product_fields={"产品名称": "Pet Brush"},
    )
    assert payload["linked_product_record_id"] == "recProduct"
    assert payload["target_market"] == "美国"
    assert payload["main_test_point"] == "hook_angle"
```

**Step 2: Run test to fail**

```bash
cd tk_toolkit_dual && python3 -m unittest test_ugc_script_generate -v
```

Expected: FAIL because module does not exist.

**Step 3: Implement payload builder**

The builder must include:

- `UGC-03` version fields
- `UGC-01` source fields
- product fields read from `初始化-产品信息`
- `script_generation_handoff`
- target market
- main test point

**Step 4: Load prompt**

Use `docs/prompts/ugc-script-generation-system-prompt-v1.md`.

**Step 5: Call LLM and parse dual output**

Use `parse_dual_output()`.

Validate generated JSON:

- `shots` length = 6
- `six_grid_summary` length = 6
- each shot has `content_type`
- if `content_type=dialogue`, `speaker_visible=true`

Write back:

- `脚本生成状态 = 生成成功`
- `结构化脚本JSON`
- `生成的脚本`

On failure:

- `脚本生成状态 = 生成失败`
- `错误信息`

**Step 6: Dry-run with mock LLM output**

```bash
UGC_DRY_RUN=1 UGC_MOCK_LLM_OUTPUT=fixtures/ugc_script_mock_output.txt python3 -m tk_ugc_script_generate <ugc03_record_id>
```

Expected: validates and prints writeback payload.

**Step 7: Commit**

```bash
git add tk_toolkit_dual/tk_ugc_script_generate.py tk_toolkit_dual/test_ugc_script_generate.py
git commit -m "feat: generate UGC script versions"
```

---

## Task 10: Add UGC Dispatcher Integration After Manual Success

**Files:**
- Modify: `tk_toolkit_dual/dispatcher.py`
- Test: manual dry-run / short polling run

**Step 1: Add UGC stage map entries**

Add:

```python
"ugc_single_video_analyze": "stages.ugc_single_video_analyze",
"ugc_script_batch_create": "stages.ugc_script_batch_create",
"ugc_script_generate": "stages.ugc_script_generate",
```

**Step 2: Add UGC table IDs**

Use `ugc_config.load_ugc_table_ids()`.

**Step 3: Add status scans**

Scan:

- `UGC-01.分析状态 = 待分析` → `ugc_single_video_analyze`
- `UGC-01.脚本派生状态 = 待派生` → `ugc_script_batch_create`
- `UGC-03.脚本生成状态 = 待生成` → `ugc_script_generate`

**Step 4: Protect against duplicate processing**

Before dispatch:

- set relevant status to `分析中` / `派生中` / `生成中` inside the stage function as soon as it starts.
- stage function should be idempotent where possible.

**Step 5: Manual short run**

Run dispatcher for a bounded local test:

```bash
UGC_DISPATCH_ONCE=1 python3 tk_dispatcher.py
```

Expected: processes at most one eligible record per stage and exits.

**Step 6: Commit**

```bash
git add tk_toolkit_dual/dispatcher.py
git commit -m "feat: add UGC dispatcher routes"
```

---

## Task 11: End-to-End Smoke Test

**Files:**
- Create: `docs/ugc-smoke-test-LBWU-2026-04-29.md`

**Step 1: Create one controlled UGC-01 test row**

Use `UGC-01.01-用户填写入口` view:

- `任务名称`: `UGC smoke test YYYY-MM-DD HH:mm`
- video link or test file
- `关联产品`
- `目标市场`
- `目标脚本数量 = 3`
- `分析状态 = 待分析`

**Step 2: Run analysis**

```bash
python3 -m tk_ugc_single_video_analyze <ugc01_record_id>
```

Expected:

- `分析状态 = 分析成功`
- `分析结果JSON` contains `script_generation_handoff`
- `分析结果Markdown` non-empty

**Step 3: Run script batch derivation**

Set `脚本派生状态 = 待派生`, then run:

```bash
python3 -m tk_ugc_script_batch_create <ugc01_record_id>
```

Expected:

- one `UGC-02` created
- three `UGC-03` created
- main test points populated

**Step 4: Run script generation for one UGC-03**

```bash
python3 -m tk_ugc_script_generate <ugc03_record_id>
```

Expected:

- `脚本生成状态 = 生成成功`
- `结构化脚本JSON` contains 6 shots
- `生成的脚本` readable

**Step 5: Document results**

Create `docs/ugc-smoke-test-LBWU-2026-04-29.md` with:

- record ids
- screenshots or copied statuses
- failures encountered
- prompt quality notes
- go/no-go decision for dispatcher automation

**Step 6: Commit**

```bash
git add docs/ugc-smoke-test-LBWU-2026-04-29.md
git commit -m "test: document UGC smoke test"
```

---

## Task 12: Only After Script Chain Is Stable — Plan UGC-04 to UGC-07

Do not implement image/video stages until Tasks 1-11 pass.

Next plan should cover:

- `UGC-04` 6-grid prompt generation and image rendering.
- `UGC-05` 6-grid crop to six individual shot images.
- `UGC-05` image upscaling.
- `UGC-06` shot-level image-to-video prompt generation.
- `UGC-06` video generation with the confirmed provider/API.
- `UGC-07` FFmpeg concat list generation and final video composition.
- End-to-end result views and error recovery.

Before writing that plan, confirm:

1. 6-grid layout: `3行x2列` or `2行x3列`.
2. Image generation provider/model.
3. Veo 3.1 API/代理接口形态.
4. Final video aspect ratio and duration constraints.

---

## Recommended Execution Order

1. Task 1-2: foundation utilities.
2. Task 3-6: `UGC-01` analysis runnable by CLI.
3. Task 7: sync prompts into Base config.
4. Task 8-9: script batch derivation and script generation.
5. Task 11: one real smoke test.
6. Task 10: dispatcher automation only after the smoke test is stable.
7. Task 12: write a separate plan for image/video stages.

---

## Completion Criteria for This Plan

This plan is complete when:

- One `UGC-01` record can be analyzed successfully.
- The analysis writes valid `JSON_OUTPUT` and `MARKDOWN_OUTPUT` back to Base.
- One analyzed record can create one `UGC-02` batch and N `UGC-03` version tasks.
- Each `UGC-03` record has a non-empty `主测试点`.
- At least one `UGC-03` record can generate a valid script with exactly 6 shots and 6 `six_grid_summary` items.
- The smoke test doc records exact record IDs and status results.
