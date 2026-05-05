# UGC Reroll Trigger Layer Plan

Goal: Add a safe Feishu-facing trigger layer for UGC reroll/regeneration so users can request 9-grid storyboard image rerolls and shot video rerolls from Base fields/views, while local Python performs the actual orchestration.

## Safety decisions

- Do not rely on Feishu workflow to call local Python directly; current available Base workflow actions do not expose a safe HTTP/webhook/local command action in the documented CLI schema.
- Implement Feishu-facing trigger fields as the UI/button-like entry point.
- Implement a local poller/runner script that reads pending trigger requests and calls existing `tk_ugc_reroll.py` helpers.
- Default action should create candidate records only; model calls require explicit trigger value.
- Never overwrite existing successful AI outputs.
- After processing a request, write status/result back to the source record.

## Trigger fields

### UGC-04 source records

- `重新生成请求` — select: `不触发`, `创建候选`, `创建并生成图片`, `创建生成并切分分镜图`
- `重新生成数量` — number, default interpreted as 1 if empty
- `重新生成执行状态` — select: `空闲`, `待处理`, `处理中`, `成功`, `失败`
- `重新生成执行结果JSON` — text
- `重新生成触发备注` — text

### UGC-06 source records

- `重新生成请求` — select: `不触发`, `创建候选`, `创建并生成视频`
- `重新生成数量` — number, default interpreted as 1 if empty
- `重新生成执行状态` — select: `空闲`, `待处理`, `处理中`, `成功`, `失败`
- `重新生成执行结果JSON` — text
- `重新生成触发备注` — text

## Task 1: Local trigger parser and runner

- Add `tk_toolkit_dual/tk_ugc_reroll_trigger.py`.
- Support dry-run by default.
- Support `--stage grid|video|all`, `--write`, `--limit`, `--call-models`.
- Scan source tables for `重新生成执行状态=待处理` and trigger request not `不触发`.
- For grid: source table UGC-04, read linked UGC-03 from `关联脚本版本`, execute grid reroll with source UGC-04 record ID.
- For video: source table UGC-06, execute video reroll from UGC-06 record ID.
- If request implies model call, require `--call-models`; otherwise fail the individual request with a clear safety message.
- Write `处理中` before execution and `成功`/`失败` plus result JSON after execution when `--write` is set.

## Task 2: Tests

- Add `test_ugc_reroll_trigger.py`.
- Test request parsing, count default/clamping, safety gating for model calls, grid linked UGC-03 extraction, and update payloads.

## Task 3: Feishu fields/views

- Create missing trigger fields in UGC-04 and UGC-06.
- Add trigger fields to existing candidate/source views, or create dedicated views:
  - UGC-04 `03-重新生成入口`
  - UGC-06 `03-重新生成入口`
- Do not enable real model calls during field/view setup.

## Task 4: Verification

- `python3 -m py_compile tk_ugc_reroll_trigger.py test_ugc_reroll_trigger.py`
- `python3 -m unittest test_ugc_reroll_trigger test_ugc_reroll -v`
- Dry-run scan command.

## Task 5: Handoff

- Document how user triggers from Feishu:
  1. In source record, set `重新生成数量`.
  2. Set `重新生成请求`.
  3. Set `重新生成执行状态=待处理`.
  4. Local runner processes and writes result.
