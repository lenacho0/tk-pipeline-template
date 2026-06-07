# Dispatcher Concurrency Config Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Feishu-table controlled dispatcher concurrency so users can set per-stage and global concurrency from `初始化-模型与API配置`.

**Architecture:** Keep the existing dispatcher slot logic and add a small Feishu-backed policy loader in `tk_dispatcher.py`. The loader converts config-table fields into the same `max_concurrency` and global limit values the dispatcher already understands. Table field/view governance stays in `cleanup_model_config_table.py`.

**Tech Stack:** Python 3 standard library, existing Feishu helpers in `common.py`, `unittest`, `unittest.mock`, existing lark-cli based table governance scripts.

---

## File Structure

- Modify: `tk_toolkit_dual/tk_dispatcher.py`
  - Add Feishu concurrency policy loading, caching, parsing, and precedence.
  - Update `apply_stage_policy()` to apply Feishu stage overrides after local `STAGE_CFG`.
  - Update global slot calculation to use dynamic policy instead of only module-level `GLOBAL_MAX_CONCURRENCY`.
- Modify: `tk_toolkit_dual/cleanup_model_config_table.py`
  - Add field specs for `环节最大并发` and `全局最大并发`.
  - Add the fields to `01-运行配置-管理员`.
- Modify: `tk_toolkit_dual/config.json.template`
  - Document that local dispatcher concurrency is fallback and Feishu table overrides it.
- Modify: `tk_toolkit_dual/test_dispatcher.py`
  - Add focused tests for policy parsing, precedence, pause semantics, and global limit.
- Modify: `tk_toolkit_dual/test_cleanup_model_config_table.py`
  - Assert new fields exist in specs and admin view.
- Modify: `docs/tk-pipeline/tk-pipeline-lessons-learned.md`
  - Add short operational note for future maintenance.

---

### Task 1: Add Dispatcher Policy Parser Tests

**Files:**
- Modify: `tk_toolkit_dual/test_dispatcher.py`

- [ ] **Step 1: Write tests for integer parsing**

Add tests near other dispatcher policy tests:

```python
def test_parse_concurrency_cell_handles_blank_default_and_zero_pause(self):
    self.assertIsNone(dispatcher.parse_concurrency_cell(""))
    self.assertIsNone(dispatcher.parse_concurrency_cell(None))
    self.assertEqual(dispatcher.parse_concurrency_cell("0"), 0)
    self.assertEqual(dispatcher.parse_concurrency_cell("3"), 3)


def test_parse_concurrency_cell_rejects_invalid_values(self):
    self.assertIsNone(dispatcher.parse_concurrency_cell("-1"))
    self.assertIsNone(dispatcher.parse_concurrency_cell("1.5"))
    self.assertIsNone(dispatcher.parse_concurrency_cell("fast"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd tk_toolkit_dual && python3 -m unittest test_dispatcher.DispatcherRecoveryTests.test_parse_concurrency_cell_handles_blank_default_and_zero_pause test_dispatcher.DispatcherRecoveryTests.test_parse_concurrency_cell_rejects_invalid_values -v
```

Expected: FAIL because `parse_concurrency_cell` does not exist.

### Task 2: Implement Concurrency Cell Parser

**Files:**
- Modify: `tk_toolkit_dual/tk_dispatcher.py`

- [ ] **Step 1: Add parser function**

Add after `apply_stage_policy()` helper area or before it:

```python
def parse_concurrency_cell(value):
    text_value = extract_text(value).strip()
    if not text_value:
        return None
    if not text_value.isdigit():
        log.warning(f"忽略无效并发配置: {text_value!r}")
        return None
    return int(text_value)
```

- [ ] **Step 2: Run parser tests**

Run:

```bash
cd tk_toolkit_dual && python3 -m unittest test_dispatcher.DispatcherRecoveryTests.test_parse_concurrency_cell_handles_blank_default_and_zero_pause test_dispatcher.DispatcherRecoveryTests.test_parse_concurrency_cell_rejects_invalid_values -v
```

Expected: PASS.

### Task 3: Add Feishu Policy Loading Tests

**Files:**
- Modify: `tk_toolkit_dual/test_dispatcher.py`

- [ ] **Step 1: Add tests for policy loading**

Add tests:

```python
def test_load_feishu_concurrency_policy_reads_stage_and_global_limits(self):
    records = [
        {
            "record_id": "rec_stage",
            "fields": {
                "配置类型": "运行环节",
                "环节": "多角色视频片段生成",
                "状态": "启用",
                "生效来源": "线上配置",
                "环节最大并发": "0",
            },
        },
        {
            "record_id": "rec_global",
            "fields": {
                "配置类型": "路由开关",
                "环节": "Dispatcher并发控制",
                "状态": "启用",
                "全局最大并发": "5",
            },
        },
    ]

    with patch.object(dispatcher, "safe_list_records", return_value=records):
        policy = dispatcher.load_feishu_concurrency_policy("token", force=True)

    self.assertEqual(policy["stage_policies"], {"多角色视频片段生成": {"max_concurrency": 0}})
    self.assertEqual(policy["global_max_concurrency"], 5)


def test_load_feishu_concurrency_policy_ignores_blank_and_disabled_rows(self):
    records = [
        {
            "record_id": "rec_blank",
            "fields": {
                "配置类型": "运行环节",
                "环节": "多角色视频片段生成",
                "状态": "启用",
                "环节最大并发": "",
            },
        },
        {
            "record_id": "rec_disabled",
            "fields": {
                "配置类型": "运行环节",
                "环节": "多图九宫格视频生成",
                "状态": "停用",
                "环节最大并发": "9",
            },
        },
    ]

    with patch.object(dispatcher, "safe_list_records", return_value=records):
        policy = dispatcher.load_feishu_concurrency_policy("token", force=True)

    self.assertEqual(policy["stage_policies"], {})
    self.assertIsNone(policy["global_max_concurrency"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd tk_toolkit_dual && python3 -m unittest test_dispatcher.DispatcherRecoveryTests.test_load_feishu_concurrency_policy_reads_stage_and_global_limits test_dispatcher.DispatcherRecoveryTests.test_load_feishu_concurrency_policy_ignores_blank_and_disabled_rows -v
```

Expected: FAIL because `load_feishu_concurrency_policy` does not exist.

### Task 4: Implement Feishu Policy Loader

**Files:**
- Modify: `tk_toolkit_dual/tk_dispatcher.py`

- [ ] **Step 1: Add constants and cache**

Add near dispatcher constants:

```python
CONCURRENCY_CONTROL_STAGE = 'Dispatcher并发控制'
CONCURRENCY_POLICY_TTL_SECONDS = int(DISPATCHER_CFG.get('concurrency_policy_ttl_seconds', 60) or 60)
_CONCURRENCY_POLICY_CACHE = {
    'loaded_at': 0,
    'policy': {'stage_policies': {}, 'global_max_concurrency': None},
}
```

- [ ] **Step 2: Add row helpers and loader**

Add before `apply_stage_policy()`:

```python
def _config_cell_matches(fields, field_name, expected):
    return extract_text(fields.get(field_name, '')).strip() == expected


def _config_status_is_active(fields):
    return extract_text(fields.get('状态', '')).strip() != '停用'


def load_feishu_concurrency_policy(token, *, force=False):
    now = time.time()
    cached = _CONCURRENCY_POLICY_CACHE.get('policy') or {'stage_policies': {}, 'global_max_concurrency': None}
    loaded_at = float(_CONCURRENCY_POLICY_CACHE.get('loaded_at') or 0)
    if not force and loaded_at and now - loaded_at < CONCURRENCY_POLICY_TTL_SECONDS:
        return cached

    try:
        records = safe_list_records(token, TABLE_CONFIG)
    except Exception as exc:
        log.warning(f"读取飞书并发配置失败，沿用缓存/本地默认: {exc}")
        return cached

    stage_candidates = {}
    global_limit = None

    for record in records:
        fields = record.get('fields') or {}
        if not _config_status_is_active(fields):
            continue
        config_type = extract_text(fields.get('配置类型', '')).strip()
        stage = extract_text(fields.get('环节', '')).strip()
        if config_type == '运行环节':
            limit = parse_concurrency_cell(fields.get('环节最大并发'))
            if limit is None or not stage:
                continue
            stage_candidates.setdefault(stage, []).append((fields, limit))
        elif config_type == '路由开关' and stage == CONCURRENCY_CONTROL_STAGE:
            parsed_global = parse_concurrency_cell(fields.get('全局最大并发'))
            if parsed_global is not None:
                global_limit = parsed_global

    stage_policies = {}
    for stage, candidates in stage_candidates.items():
        online = [
            item for item in candidates
            if extract_text(item[0].get('生效来源', '')).strip() in ('', '线上配置')
        ]
        selected = online or candidates
        if len(selected) != 1:
            log.warning(f"忽略重复并发配置: stage={stage} count={len(selected)}")
            continue
        stage_policies[stage] = {'max_concurrency': selected[0][1]}

    policy = {'stage_policies': stage_policies, 'global_max_concurrency': global_limit}
    _CONCURRENCY_POLICY_CACHE['loaded_at'] = now
    _CONCURRENCY_POLICY_CACHE['policy'] = policy
    return policy
```

- [ ] **Step 3: Run policy loader tests**

Run:

```bash
cd tk_toolkit_dual && python3 -m unittest test_dispatcher.DispatcherRecoveryTests.test_load_feishu_concurrency_policy_reads_stage_and_global_limits test_dispatcher.DispatcherRecoveryTests.test_load_feishu_concurrency_policy_ignores_blank_and_disabled_rows -v
```

Expected: PASS.

### Task 5: Apply Stage Overrides From Feishu

**Files:**
- Modify: `tk_toolkit_dual/test_dispatcher.py`
- Modify: `tk_toolkit_dual/tk_dispatcher.py`

- [ ] **Step 1: Add precedence test**

Add test:

```python
def test_apply_stage_policy_prefers_feishu_concurrency_over_local_config(self):
    watch = {
        "name": "多角色视频片段生成",
        "script": "tk_multi_role_first_last.py",
        "args": ["video"],
        "max_concurrency": 1,
        "timeout": 2400,
    }

    with patch.object(dispatcher, "STAGE_CFG", {"多角色视频片段生成": {"max_concurrency": 2}}), \
         patch.object(dispatcher, "get_current_concurrency_policy", return_value={
             "stage_policies": {"多角色视频片段生成": {"max_concurrency": 0}},
             "global_max_concurrency": None,
         }):
        applied = dispatcher.apply_stage_policy(watch)

    self.assertEqual(applied["max_concurrency"], 0)
```

- [ ] **Step 2: Add helper and patch `apply_stage_policy()`**

Add:

```python
def get_current_concurrency_policy():
    return _CONCURRENCY_POLICY_CACHE.get('policy') or {'stage_policies': {}, 'global_max_concurrency': None}
```

Then update the end of `apply_stage_policy()`:

```python
    feishu_stage_policy = (get_current_concurrency_policy().get('stage_policies') or {}).get(watch.get('name'))
    if feishu_stage_policy:
        for key in ('max_concurrency',):
            if key in feishu_stage_policy:
                merged[key] = feishu_stage_policy[key]
    return merged
```

- [ ] **Step 3: Run precedence test**

Run:

```bash
cd tk_toolkit_dual && python3 -m unittest test_dispatcher.DispatcherRecoveryTests.test_apply_stage_policy_prefers_feishu_concurrency_over_local_config -v
```

Expected: PASS.

### Task 6: Apply Dynamic Global Limit In Dispatcher Loop

**Files:**
- Modify: `tk_toolkit_dual/test_dispatcher.py`
- Modify: `tk_toolkit_dual/tk_dispatcher.py`

- [ ] **Step 1: Add global limit test**

Add test:

```python
def test_check_and_run_uses_feishu_global_concurrency_limit(self):
    watch = {
        "name": "测试图片生成",
        "script": "tk_nine_grid_video.py",
        "table": "tbl_nine",
        "status_field": "图片生成状态",
        "trigger_value": "待生成",
        "running_value": "生成中",
        "args": ["image"],
        "max_concurrency": 3,
    }
    record = {"record_id": "recWait", "fields": {"图片生成状态": "待生成", "任务名称": "waiting task"}}

    with patch.object(dispatcher, "load_feishu_concurrency_policy", return_value={
             "stage_policies": {},
             "global_max_concurrency": 1,
         }), \
         patch.object(dispatcher, "cleanup_finished_processes"), \
         patch.object(dispatcher, "load_running_tasks", return_value={}), \
         patch.object(dispatcher, "count_running_by_watch", return_value=0), \
         patch.object(dispatcher, "count_active_running_tasks", return_value=1), \
         patch.object(dispatcher, "get_table_records_cached", return_value=[record]), \
         patch.object(dispatcher.subprocess, "Popen") as popen:
        dispatcher.check_and_run("token", watch)

    popen.assert_not_called()
```

- [ ] **Step 2: Add global policy helper**

Add:

```python
def current_global_max_concurrency(policy):
    configured = policy.get('global_max_concurrency')
    if configured is None:
        return GLOBAL_MAX_CONCURRENCY
    return int(configured)
```

- [ ] **Step 3: Load policy at start of `check_and_run()`**

Change the beginning of `check_and_run()` to:

```python
def check_and_run(token, watch):
    policy = load_feishu_concurrency_policy(token)
    watch = apply_stage_policy(watch)
    cleanup_finished_processes(token)
    running_state = load_running_tasks()
    current_running = count_running_by_watch(watch['name']) + count_live_persisted_by_watch(watch, running_state)
    available_slots = max(0, watch.get('max_concurrency', 1) - current_running)
    global_limit = current_global_max_concurrency(policy)
    if global_limit > 0:
        global_slots = max(0, global_limit - count_active_running_tasks())
        available_slots = min(available_slots, global_slots)
    if available_slots <= 0:
        return
```

- [ ] **Step 4: Run global limit test**

Run:

```bash
cd tk_toolkit_dual && python3 -m unittest test_dispatcher.DispatcherRecoveryTests.test_check_and_run_uses_feishu_global_concurrency_limit -v
```

Expected: PASS.

### Task 7: Add Config Table Field/View Tests

**Files:**
- Modify: `tk_toolkit_dual/test_cleanup_model_config_table.py`
- Modify: `tk_toolkit_dual/cleanup_model_config_table.py`

- [ ] **Step 1: Add tests**

Add:

```python
def test_config_field_specs_include_concurrency_fields(self):
    names = {item["name"] for item in cleanup.CONFIG_FIELD_SPECS}
    self.assertIn("环节最大并发", names)
    self.assertIn("全局最大并发", names)


def test_admin_view_shows_concurrency_fields(self):
    views = cleanup.build_view_definitions(["配置类型", "环节", "环节最大并发", "全局最大并发"])
    visible = views["01-运行配置-管理员"]["visible_fields"]
    self.assertIn("环节最大并发", visible)
    self.assertIn("全局最大并发", visible)
```

- [ ] **Step 2: Add field specs and view fields**

In `CONFIG_FIELD_SPECS`, add:

```python
    {
        "name": "环节最大并发",
        "type": "number",
    },
    {
        "name": "全局最大并发",
        "type": "number",
    },
```

In `build_view_definitions()`, add both fields to `01-运行配置-管理员.visible_fields` after `生效来源`.

- [ ] **Step 3: Run config table tests**

Run:

```bash
cd tk_toolkit_dual && python3 -m unittest test_cleanup_model_config_table -v
```

Expected: PASS.

### Task 8: Update Template And Ops Notes

**Files:**
- Modify: `tk_toolkit_dual/config.json.template`
- Modify: `docs/tk-pipeline/tk-pipeline-lessons-learned.md`

- [ ] **Step 1: Update `config.json.template` dispatcher block**

Add a note field under `dispatcher`:

```json
"concurrency_policy_ttl_seconds": 60,
"_concurrency_note": "本地 dispatcher 并发是兜底；初始化-模型与API配置 中的 环节最大并发/全局最大并发 优先。环节最大并发=0 表示暂停该环节，空值表示使用默认。"
```

- [ ] **Step 2: Add lessons learned note**

Append:

```markdown
## 29. Dispatcher 并发配置以飞书表为日常入口

2026-06-05 起，dispatcher 并发控制应优先通过 `初始化-模型与API配置` 管理：运行环节记录用 `环节最大并发` 控制单环节并发，`Dispatcher并发控制` 路由开关记录用 `全局最大并发` 控制总并发。`环节最大并发=0` 表示暂停该环节，空值表示沿用本地默认；不要为了临时调并发再直接改 `tk_dispatcher.py`。
```

- [ ] **Step 3: Validate JSON template**

Run:

```bash
cd tk_toolkit_dual && python3 -m json.tool config.json.template >/tmp/tk_config_template_check.json
```

Expected: command exits 0.

### Task 9: Run Focused Verification

**Files:**
- No file edits.

- [ ] **Step 1: Run dispatcher tests**

Run:

```bash
cd tk_toolkit_dual && python3 -m unittest test_dispatcher test_shot_video -v
```

Expected: PASS.

- [ ] **Step 2: Run model config governance tests**

Run:

```bash
cd tk_toolkit_dual && python3 -m unittest test_cleanup_model_config_table -v
```

Expected: PASS.

- [ ] **Step 3: Dry-run config table cleanup**

Run:

```bash
cd tk_toolkit_dual && python3 cleanup_model_config_table.py --dry-run
```

Expected: prints a dry-run plan and does not write to Feishu.

### Task 10: Optional Real Table Migration

**Files:**
- No local code edits.

- [ ] **Step 1: Create fields and update views after tests pass**

Run:

```bash
cd tk_toolkit_dual && python3 cleanup_model_config_table.py --write
```

Expected: `初始化-模型与API配置` contains `环节最大并发` and `全局最大并发`; `01-运行配置-管理员` displays both.

- [ ] **Step 2: Add or update global control row**

In Feishu table:

```text
配置类型: 路由开关
环节: Dispatcher并发控制
状态: 启用
全局最大并发: 0
备注: 0/空值表示不启用全局限制；大于 0 表示所有 dispatcher 任务合计最大并发。
```

- [ ] **Step 3: Smoke test pause semantics**

Set one low-risk stage `环节最大并发=0`, wait one dispatcher poll interval, and verify no new task for that stage is claimed. Then clear the field to restore default behavior.

