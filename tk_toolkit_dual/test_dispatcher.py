import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common
import tk_dispatcher as dispatcher


class DispatcherRecoveryTests(unittest.TestCase):
    def setUp(self):
        dispatcher.running_processes = {}
        dispatcher._CONCURRENCY_POLICY_CACHE = {
            "loaded_at": 0,
            "policy": {"stage_policies": {}, "global_max_concurrency": None},
        }

    def test_parse_concurrency_cell_handles_blank_default_and_zero_pause(self):
        self.assertIsNone(dispatcher.parse_concurrency_cell(""))
        self.assertIsNone(dispatcher.parse_concurrency_cell(None))
        self.assertEqual(dispatcher.parse_concurrency_cell("0"), 0)
        self.assertEqual(dispatcher.parse_concurrency_cell("3"), 3)

    def test_parse_concurrency_cell_rejects_invalid_values(self):
        self.assertIsNone(dispatcher.parse_concurrency_cell("-1"))
        self.assertIsNone(dispatcher.parse_concurrency_cell("1.5"))
        self.assertIsNone(dispatcher.parse_concurrency_cell("fast"))

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

    def test_load_feishu_concurrency_policy_reads_table_limits(self):
        records = [
            {
                "record_id": "rec_table",
                "fields": {
                    "配置类型": "路由开关",
                    "环节": "Dispatcher表格并发",
                    "应用表格": "005-多图宫格视频生成表",
                    "状态": "启用",
                    "生效来源": "线上配置",
                    "表格最大并发": "18",
                },
            },
        ]

        with patch.object(dispatcher, "safe_list_records", return_value=records):
            policy = dispatcher.load_feishu_concurrency_policy("token", force=True)

        self.assertEqual(policy["table_policies"], {
            dispatcher.TABLE_NINE_GRID_VIDEO: {"max_concurrency": 18}
        })

    def test_table_max_concurrency_prefers_feishu_policy(self):
        watch = {"table": dispatcher.TABLE_NINE_GRID_VIDEO, "table_max_concurrency": 2}

        with patch.object(dispatcher, "TABLE_KEY", dispatcher.TABLE_NINE_GRID_VIDEO), \
             patch.object(dispatcher, "get_current_concurrency_policy", return_value={
                 "table_policies": {dispatcher.TABLE_NINE_GRID_VIDEO: {"max_concurrency": 18}},
             }):
            self.assertEqual(dispatcher.table_max_concurrency_for_watch(watch), 18)

    def test_load_feishu_concurrency_policy_prefers_dispatch_stage_name(self):
        records = [
            {
                "record_id": "rec_default",
                "fields": {
                    "配置类型": "任务默认",
                    "环节": "图片生成-OTU",
                    "调度环节名": "多角色参考图生成",
                    "状态": "启用",
                    "生效来源": "线上配置",
                    "环节最大并发": "7",
                },
            },
        ]

        with patch.object(dispatcher, "safe_list_records", return_value=records):
            policy = dispatcher.load_feishu_concurrency_policy("token", force=True)

        self.assertEqual(policy["stage_policies"], {"多角色参考图生成": {"max_concurrency": 7}})
        self.assertEqual(policy["source_rows"][0]["matched_stage"], "多角色参考图生成")
        self.assertEqual(policy["source_rows"][0]["环节"], "图片生成-OTU")

    def test_load_feishu_concurrency_policy_keeps_legacy_stage_fallback(self):
        records = [
            {
                "record_id": "rec_stage",
                "fields": {
                    "配置类型": "运行环节",
                    "环节": "多图九宫格视频生成",
                    "状态": "启用",
                    "环节最大并发": "4",
                },
            },
        ]

        with patch.object(dispatcher, "safe_list_records", return_value=records):
            policy = dispatcher.load_feishu_concurrency_policy("token", force=True)

        self.assertEqual(policy["stage_policies"], {"多图九宫格视频生成": {"max_concurrency": 4}})

    def test_load_feishu_concurrency_policy_prefers_task_default_over_runtime_duplicate(self):
        records = [
            {
                "record_id": "rec_runtime",
                "fields": {
                    "配置类型": "运行环节",
                    "环节": "多角色首尾帧解析-Gemini",
                    "调度环节名": "多角色首尾帧解析",
                    "状态": "启用",
                    "环节最大并发": "5",
                },
            },
            {
                "record_id": "rec_default",
                "fields": {
                    "配置类型": "任务默认",
                    "环节": "多角色首尾帧解析-Gemini",
                    "调度环节名": "多角色首尾帧解析",
                    "状态": "启用",
                    "环节最大并发": "8",
                },
            },
        ]

        with patch.object(dispatcher, "safe_list_records", return_value=records):
            policy = dispatcher.load_feishu_concurrency_policy("token", force=True)

        self.assertEqual(policy["stage_policies"], {"多角色首尾帧解析": {"max_concurrency": 8}})
        self.assertEqual(policy["source_rows"][0]["record_id"], "rec_default")

    def test_dispatcher_policy_diagnostics_reports_unmatched_rows(self):
        policy = {
            "source_rows": [
                {"record_id": "rec1", "matched_stage": "多角色参考图生成"},
                {"record_id": "rec2", "matched_stage": "图片生成-OTU"},
            ],
        }
        watches = [{"name": "多角色参考图生成"}]

        diagnostics = dispatcher.concurrency_policy_diagnostics(policy, watches)

        self.assertEqual(diagnostics["unmatched_rows"], [{"record_id": "rec2", "matched_stage": "图片生成-OTU"}])

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

    def test_load_feishu_concurrency_policy_skips_fake_token_without_force(self):
        with patch.object(dispatcher, "safe_list_records", return_value=[]) as list_records:
            policy = dispatcher.load_feishu_concurrency_policy("token")

        list_records.assert_not_called()
        self.assertEqual(policy, {"stage_policies": {}, "global_max_concurrency": None})

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

    def test_media_regeneration_watches_are_polled_first_without_duplicates(self):
        ordered = dispatcher.ordered_watch_list()
        ordered_names = [watch["name"] for watch in ordered]

        self.assertEqual(ordered_names[:len(dispatcher.MEDIA_REGENERATION_WATCH_NAMES)], dispatcher.MEDIA_REGENERATION_WATCH_NAMES)
        self.assertEqual(len(ordered_names), len(set(ordered_names)))
        self.assertEqual(set(ordered_names), {watch["name"] for watch in dispatcher.WATCH_LIST})

    def test_ordered_watch_list_rotates_normal_watches_after_priority_group(self):
        watches = [
            {"name": "多角色视频片段重生成"},
            {"name": "普通A"},
            {"name": "普通B"},
            {"name": "普通C"},
        ]

        ordered = dispatcher.ordered_watch_list(watches, normal_rotation_offset=1)

        self.assertEqual([watch["name"] for watch in ordered], [
            "多角色视频片段重生成",
            "普通B",
            "普通C",
            "普通A",
        ])

    def test_background_status_watches_reclaim_running_states(self):
        missing = []
        explicit_status_fields = {"拆分状态", "文档拆分状态"}
        for watch in dispatcher.RAW_WATCH_LIST:
            status_field = watch.get("status_field") or ""
            if not watch.get("table") or not watch.get("script"):
                continue
            if not status_field.endswith("状态") and status_field not in explicit_status_fields:
                continue
            running_value = watch.get("running_value")
            trigger_value = watch.get("trigger_value")
            if not running_value or running_value == trigger_value:
                continue
            trigger_values = watch.get("trigger_values") or [trigger_value]
            if running_value not in trigger_values:
                missing.append({
                    "name": watch.get("name"),
                    "status_field": status_field,
                    "running_value": running_value,
                    "trigger_values": trigger_values,
                })

        self.assertEqual(missing, [])

    def test_group_watches_by_table_groups_only_table_watches(self):
        watches = [
            {"name": "A1", "table": "tblA"},
            {"name": "A2", "table": "tblA"},
            {"name": "B1", "table": "tblB"},
            {"name": "NoTable"},
        ]

        grouped = dispatcher.group_watches_by_table(watches)

        self.assertEqual(set(grouped), {"tblA", "tblB"})
        self.assertEqual([watch["name"] for watch in grouped["tblA"]], ["A1", "A2"])
        self.assertEqual([watch["name"] for watch in grouped["tblB"]], ["B1"])

    def test_filter_watches_by_table_key_keeps_only_that_table(self):
        watches = [
            {"name": "A1", "table": "tblA"},
            {"name": "A2", "table": "tblA"},
            {"name": "B1", "table": "tblB"},
        ]

        scoped = dispatcher.filter_watches_by_table_key(watches, "tblA")

        self.assertEqual([watch["name"] for watch in scoped], ["A1", "A2"])

    def test_scoped_runtime_file_uses_table_suffix_only_in_table_mode(self):
        self.assertEqual(
            dispatcher.scoped_runtime_file(".running_tasks", "ryan", None),
            str(Path(dispatcher.SCRIPTS_DIR) / ".running_tasks.ryan.json"),
        )
        self.assertEqual(
            dispatcher.scoped_runtime_file(".running_tasks", "ryan", "tblA"),
            str(Path(dispatcher.SCRIPTS_DIR) / ".running_tasks.ryan.tblA.json"),
        )

    def test_make_task_key_includes_table_and_status_for_new_scoped_keys(self):
        watch = {
            "table": "tblA",
            "status_field": "视频生成状态",
            "script": "worker.py",
            "args": ["video"],
        }

        self.assertEqual(
            dispatcher.make_task_key(watch, "rec1"),
            "tblA::视频生成状态::worker.py::video::rec1",
        )

    def test_build_watch_candidate_filter_queries_status_and_record_type(self):
        watch = {
            "status_field": "参考图生成状态",
            "trigger_value": "待生成",
            "trigger_values": ["待生成", "生成中"],
            "failed_value": "失败",
            "required_field_values": {"记录类型": ["参考资产"]},
            "skip_deprecated_records": True,
        }

        payload = dispatcher.build_watch_candidate_filter(watch)

        self.assertEqual(payload, {
            "logic": "and",
            "conditions": [
                ["参考图生成状态", "intersects", ["待生成", "生成中", "失败"]],
                ["记录类型", "intersects", ["参考资产"]],
            ],
        })

    def test_build_watch_candidate_filter_does_not_treat_noop_status_as_retryable_failure(self):
        watch = {
            "status_field": "参考图操作",
            "trigger_value": "重新生成参考图",
            "failed_value": "不触发",
            "required_field_values": {"记录类型": ["参考资产"]},
        }

        payload = dispatcher.build_watch_candidate_filter(watch)

        self.assertEqual(payload, {
            "logic": "and",
            "conditions": [
                ["参考图操作", "intersects", ["重新生成参考图"]],
                ["记录类型", "intersects", ["参考资产"]],
            ],
        })

    def test_build_watch_candidate_filter_does_not_push_required_blank_values(self):
        watch = {
            "status_field": "场景拆分操作",
            "trigger_value": "重新拆分场景",
            "failed_value": "不触发",
            "required_field_values": {"记录类型": ["", "母任务"]},
        }

        payload = dispatcher.build_watch_candidate_filter(watch)

        self.assertEqual(payload, {
            "logic": "and",
            "conditions": [
                ["场景拆分操作", "intersects", ["重新拆分场景"]],
            ],
        })

    def test_get_watch_candidate_records_prefers_cloud_filter_over_full_table_scan(self):
        watch = {
            "name": "测试参考图生成",
            "table": "tblA",
            "status_field": "参考图生成状态",
            "trigger_value": "待生成",
            "trigger_values": ["待生成", "生成中"],
            "failed_value": "失败",
            "required_field_values": {"记录类型": ["参考资产"]},
        }
        expected = [{"record_id": "rec1", "fields": {"参考图生成状态": "待生成"}}]

        with patch.object(dispatcher, "base_v3_filter_records", return_value=expected) as filtered, \
             patch.object(dispatcher, "get_table_records_cached") as full_scan:
            records = dispatcher.get_watch_candidate_records_cached("token", watch, force=True)

        self.assertEqual(records, expected)
        filtered.assert_called_once()
        full_scan.assert_not_called()

    def test_check_and_run_table_scope_ignores_global_concurrency_limit(self):
        watch = {
            "name": "测试图片生成",
            "script": "worker.py",
            "table": "tblA",
            "status_field": "图片生成状态",
            "trigger_value": "待生成",
            "running_value": "生成中",
            "args": ["image"],
            "max_concurrency": 3,
        }
        record = {"record_id": "recWait", "fields": {"图片生成状态": "待生成", "任务名称": "waiting task"}}

        with patch.object(dispatcher, "TABLE_KEY", "tblA"), \
             patch.object(dispatcher, "load_feishu_concurrency_policy", return_value={
                 "stage_policies": {},
                 "global_max_concurrency": 1,
             }), \
             patch.object(dispatcher, "cleanup_finished_processes"), \
             patch.object(dispatcher, "load_running_tasks", return_value={}), \
             patch.object(dispatcher, "count_running_by_watch", return_value=0), \
             patch.object(dispatcher, "count_active_running_tasks", return_value=1), \
             patch.object(dispatcher, "count_running_by_table", return_value=0), \
             patch.object(dispatcher, "count_live_persisted_by_table", return_value=0), \
             patch.object(dispatcher, "get_watch_candidate_records_cached", return_value=[record]), \
             patch.object(dispatcher, "try_claim_task", return_value=True), \
             patch.object(dispatcher, "save_running_tasks"), \
             patch.object(dispatcher, "bump_metric"), \
             patch.object(dispatcher.subprocess, "Popen") as popen:
            dispatcher.check_and_run("token", watch)

        popen.assert_called_once()

    def test_check_and_run_table_scope_respects_table_concurrency_limit(self):
        watch = {
            "name": "测试图片生成",
            "script": "worker.py",
            "table": "tblA",
            "status_field": "图片生成状态",
            "trigger_value": "待生成",
            "running_value": "生成中",
            "args": ["image"],
            "max_concurrency": 3,
            "table_max_concurrency": 2,
        }
        record = {"record_id": "recWait", "fields": {"图片生成状态": "待生成", "任务名称": "waiting task"}}

        with patch.object(dispatcher, "TABLE_KEY", "tblA"), \
             patch.object(dispatcher, "load_feishu_concurrency_policy", return_value={
                 "stage_policies": {},
                 "global_max_concurrency": None,
             }), \
             patch.object(dispatcher, "cleanup_finished_processes"), \
             patch.object(dispatcher, "load_running_tasks", return_value={}), \
             patch.object(dispatcher, "count_running_by_watch", return_value=0), \
             patch.object(dispatcher, "count_live_persisted_by_watch", return_value=0), \
             patch.object(dispatcher, "count_running_by_table", return_value=2), \
             patch.object(dispatcher, "count_live_persisted_by_table", return_value=0), \
             patch.object(dispatcher, "get_watch_candidate_records_cached", return_value=[record]), \
             patch.object(dispatcher.subprocess, "Popen") as popen:
            dispatcher.check_and_run("token", watch)

        popen.assert_not_called()

    def test_check_and_run_table_scope_zero_table_limit_pauses_table(self):
        watch = {
            "name": "测试图片生成",
            "script": "worker.py",
            "table": "tblA",
            "status_field": "图片生成状态",
            "trigger_value": "待生成",
            "running_value": "生成中",
            "args": ["image"],
            "max_concurrency": 3,
            "table_max_concurrency": 0,
        }
        record = {"record_id": "recWait", "fields": {"图片生成状态": "待生成", "任务名称": "waiting task"}}

        with patch.object(dispatcher, "TABLE_KEY", "tblA"), \
             patch.object(dispatcher, "load_feishu_concurrency_policy", return_value={
                 "stage_policies": {},
                 "global_max_concurrency": None,
             }), \
             patch.object(dispatcher, "cleanup_finished_processes"), \
             patch.object(dispatcher, "load_running_tasks", return_value={}), \
             patch.object(dispatcher, "count_running_by_watch", return_value=0), \
             patch.object(dispatcher, "count_live_persisted_by_watch", return_value=0), \
             patch.object(dispatcher, "count_running_by_table", return_value=0), \
             patch.object(dispatcher, "count_live_persisted_by_table", return_value=0), \
             patch.object(dispatcher, "get_watch_candidate_records_cached", return_value=[record]), \
             patch.object(dispatcher.subprocess, "Popen") as popen:
            dispatcher.check_and_run("token", watch)

        popen.assert_not_called()

    def test_effective_concurrency_report_shows_policy_override(self):
        watch = {
            "name": "多角色关键帧重生成",
            "script": "tk_multi_role_first_last.py",
            "args": ["regenerate-keyframe"],
            "max_concurrency": 2,
        }
        policy = {"stage_policies": {"多角色关键帧重生成": {"max_concurrency": 20}}}

        rows = dispatcher.effective_concurrency_report(policy, [watch])

        self.assertEqual(rows, [{
            "watch_name": "多角色关键帧重生成",
            "local_default": 2,
            "applied_max_concurrency": 20,
            "policy_source": "feishu",
        }])

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
             patch.object(dispatcher, "get_watch_candidate_records_cached", return_value=[record]), \
             patch.object(dispatcher.subprocess, "Popen") as popen:
            dispatcher.check_and_run("token", watch)

        popen.assert_not_called()

    def test_failed_retryable_candidate_is_requeued_without_launching_same_cycle(self):
        watch = {
            "name": "测试参考图生成",
            "script": "worker.py",
            "table": "tblA",
            "status_field": "参考图生成状态",
            "trigger_value": "待生成",
            "running_value": "生成中",
            "failed_value": "失败",
            "error_field": "参考图错误信息",
            "args": ["image"],
            "max_concurrency": 5,
            "max_retries": 2,
        }
        record = {
            "record_id": "recFailed",
            "fields": {
                "参考图生成状态": "失败",
                "参考图错误信息": "dispatcher兜底失败回写[UPSTREAM_NETWORK]: read timed out",
                "任务名称": "failed task",
            },
        }
        updates = []

        with patch.object(dispatcher, "load_feishu_concurrency_policy", return_value={
                 "stage_policies": {},
                 "global_max_concurrency": None,
             }), \
             patch.object(dispatcher, "cleanup_finished_processes"), \
             patch.object(dispatcher, "load_running_tasks", return_value={}), \
             patch.object(dispatcher, "count_running_by_watch", return_value=0), \
             patch.object(dispatcher, "count_active_running_tasks", return_value=0), \
             patch.object(dispatcher, "get_watch_candidate_records_cached", return_value=[record]), \
             patch.object(dispatcher, "get_retry_count", return_value=0), \
             patch.object(dispatcher, "set_retry_count") as set_retry_count, \
             patch.object(dispatcher, "safe_update_record", side_effect=lambda token, table, record_id, fields: updates.append(fields)), \
             patch.object(dispatcher, "clear_dead_letter") as clear_dead_letter, \
             patch.object(dispatcher, "bump_metric"), \
             patch.object(dispatcher.subprocess, "Popen") as popen:
            dispatcher.check_and_run("token", watch)

        popen.assert_not_called()
        set_retry_count.assert_called_once()
        clear_dead_letter.assert_called_once()
        self.assertEqual(updates[-1]["参考图生成状态"], "待生成")
        self.assertIn("失败队列重新排队", updates[-1]["参考图错误信息"])

    def test_failed_terminal_candidate_is_left_for_manual_review(self):
        watch = {
            "name": "测试参考图生成",
            "script": "worker.py",
            "table": "tblA",
            "status_field": "参考图生成状态",
            "trigger_value": "待生成",
            "running_value": "生成中",
            "failed_value": "失败",
            "error_field": "参考图错误信息",
            "args": ["image"],
            "max_concurrency": 5,
            "max_retries": 2,
        }
        record = {
            "record_id": "recFailed",
            "fields": {
                "参考图生成状态": "失败",
                "参考图错误信息": "dispatcher兜底失败回写[CONFIG_INVALID]: model missing",
                "任务名称": "failed task",
            },
        }

        with patch.object(dispatcher, "load_feishu_concurrency_policy", return_value={
                 "stage_policies": {},
                 "global_max_concurrency": None,
             }), \
             patch.object(dispatcher, "cleanup_finished_processes"), \
             patch.object(dispatcher, "load_running_tasks", return_value={}), \
             patch.object(dispatcher, "count_running_by_watch", return_value=0), \
             patch.object(dispatcher, "count_active_running_tasks", return_value=0), \
             patch.object(dispatcher, "get_watch_candidate_records_cached", return_value=[record]), \
             patch.object(dispatcher, "safe_update_record") as update_record, \
             patch.object(dispatcher.subprocess, "Popen") as popen:
            dispatcher.check_and_run("token", watch)

        popen.assert_not_called()
        update_record.assert_not_called()

    def test_claim_payload_skips_attachment_fields_when_clearing_outputs(self):
        claim_fields = {
            "视频生成状态": "生成中",
            "视频片段": [],
            "分镜视频": [],
            "九宫格图": [],
            "视频任务ID": "",
        }

        with patch.object(dispatcher, "get_table_field_kinds", return_value={
            "视频片段": 17,
            "分镜视频": 17,
            "九宫格图": 17,
        }):
            sanitized = dispatcher.sanitize_claim_fields_for_update("token", "tbl_test", claim_fields)

        self.assertEqual(sanitized, {
            "视频生成状态": "生成中",
            "视频任务ID": "",
        })

    def test_claim_payload_uses_known_attachment_names_when_field_metadata_is_unavailable(self):
        claim_fields = {
            "视频生成状态": "生成中",
            "视频片段": [],
            "首尾帧视频": [],
            "分镜视频": [],
            "九宫格图": [],
            "参考图": [],
            "关键帧图": [],
            "视频片段URL": None,
            "视频任务ID": "",
        }

        with patch.object(dispatcher, "get_table_field_kinds", side_effect=RuntimeError("field meta timeout")):
            sanitized = dispatcher.sanitize_claim_fields_for_update("token", "tbl_test", claim_fields)

        self.assertEqual(sanitized, {
            "视频生成状态": "生成中",
            "视频片段URL": None,
            "视频任务ID": "",
        })

    def test_policy_blocked_error_is_terminal_and_not_retried(self):
        payload = common.build_error_payload(
            "OTU 视频生成失败: {'error': {'message': '提示词或图片中包含违规信息，请立即修改后重试（1）'}}",
            stage="multi_role_first_last_video",
        )

        self.assertEqual(payload["error_code"], "UPSTREAM_POLICY_BLOCKED")
        self.assertFalse(payload["retryable"])
        self.assertEqual(payload["status"], "failed_terminal")

    def test_english_unsafe_error_is_terminal_policy_block(self):
        payload = common.build_error_payload(
            "OTU 视频生成失败: {'error': {'message': 'The generated video appears to be unsafe. Try modifying the prompts or the seeds.'}}",
            stage="multi_role_first_last_video",
        )

        self.assertEqual(payload["error_code"], "UPSTREAM_POLICY_BLOCKED")
        self.assertFalse(payload["retryable"])
        self.assertEqual(payload["status"], "failed_terminal")

    def test_aitgenne_upstream_saturation_500_is_retryable(self):
        payload = common.build_error_payload(
            "Aitgenne 参考图视频任务提交失败: HTTP 500, body={'code': 'do_request_failed', "
            "'message': '当前分组上游负载已饱和，请稍后再试', 'data': None}",
            stage="nine_grid_video",
        )

        self.assertEqual(payload["error_code"], "UPSTREAM_RATE_LIMIT")
        self.assertTrue(payload["retryable"])
        self.assertEqual(payload["status"], "failed_retryable")

    def test_upstream_no_available_channel_without_503_is_terminal_config_error(self):
        payload = common.build_error_payload(
            "OTU 图片任务提交失败: HTTP 400, body={'code': 'fail_to_fetch_task', "
            "'message': '{\"error\":{\"code\":\"model_not_found\",\"message\":\"No available channel for model gpt-image-2 under group default\"}}'}",
            stage="image_generation",
        )

        self.assertEqual(payload["error_code"], "CONFIG_INVALID")
        self.assertFalse(payload["retryable"])
        self.assertEqual(payload["status"], "failed_terminal")

    def test_upstream_no_available_channel_503_is_retryable(self):
        payload = common.build_error_payload(
            "Omni 视频任务提交失败: HTTP 503, body={'error': {'code': 'model_not_found', "
            "'message': 'No available channel for model omni_flash-10s under group default (distributor)', "
            "'type': 'new_api_error'}}",
            stage="storyboard_video",
        )

        self.assertEqual(payload["error_code"], "UPSTREAM_RATE_LIMIT")
        self.assertTrue(payload["retryable"])
        self.assertEqual(payload["status"], "failed_retryable")

    def test_feishu_records_400_is_retryable_transient_api_error(self):
        payload = common.build_error_payload(
            "400 Client Error: Bad Request for url: https://open.feishu.cn/open-apis/bitable/v1/"
            "apps/LBWUbgRfEavAgjsXNIhcpo0Dnvb/tables/tblObiMzCDn9ilFQ/records?page_size=100",
            stage="multi_role_first_last_video",
        )

        self.assertEqual(payload["error_code"], "FEISHU_API_TRANSIENT")
        self.assertTrue(payload["retryable"])
        self.assertEqual(payload["status"], "failed_retryable")

    def test_feishu_1254002_fail_is_retryable_transient_api_error(self):
        payload = common.build_error_payload(
            "API返回异常 code=1254002 msg=Fail",
            stage="dispatcher_table_scan",
        )

        self.assertEqual(payload["error_code"], "FEISHU_API_TRANSIENT")
        self.assertTrue(payload["retryable"])
        self.assertEqual(payload["status"], "failed_retryable")

    def test_otu_in_progress_timeout_is_retryable_upstream_network(self):
        payload = common.build_error_payload(
            "OTU 视频任务超时: task_id=task_123, last={'id': 'task_123', "
            "'model': 'veo_3_1-fl', 'object': 'video', 'status': 'in_progress', 'progress': 0}",
            stage="multi_role_first_last_video",
        )

        self.assertEqual(payload["error_code"], "UPSTREAM_NETWORK")
        self.assertTrue(payload["retryable"])
        self.assertEqual(payload["status"], "failed_retryable")

    def test_dispatcher_timeout_reason_includes_watch_record_and_elapsed_seconds(self):
        reason = dispatcher.format_timeout_reason(
            {"name": "多角色视频片段生成", "timeout": 2400},
            "rec_timeout",
            elapsed=2412.7,
        )

        self.assertIn("多角色视频片段生成", reason)
        self.assertIn("rec_timeout", reason)
        self.assertIn("elapsed=2412s", reason)
        self.assertIn("timeout=2400s", reason)
        payload = common.build_error_payload(reason, stage="tk_dispatcher")
        self.assertEqual(payload["error_code"], "UPSTREAM_NETWORK")
        self.assertTrue(payload["retryable"])

    def test_dispatcher_normalization_does_not_make_policy_block_retryable(self):
        payload = dispatcher.normalize_dispatcher_error_payload({
            "stage": "multi_role_first_last_video",
            "status": "failed_terminal",
            "error_code": "UPSTREAM_POLICY_BLOCKED",
            "retryable": False,
            "message": "提示词或图片中包含违规信息，请立即修改后重试（1）",
        })

        self.assertEqual(payload["error_code"], "UPSTREAM_POLICY_BLOCKED")
        self.assertFalse(payload["retryable"])

    def test_multi_role_video_retry_resubmits_new_task_instead_of_locking_failed(self):
        watch = {
            "name": "多角色视频片段生成",
            "script": "tk_multi_role_first_last.py",
            "args": ["video"],
            "table": "tbl_multi",
            "status_field": "视频生成状态",
            "trigger_value": "待生成",
            "trigger_values": ["待生成", "生成中"],
            "running_value": "生成中",
            "failed_value": "失败",
            "error_field": "视频错误信息",
            "resubmit_on_retryable_failure": True,
        }
        updates = []
        payload = common.build_error_payload(
            "OTU 视频 progress=0 timeout，自 created_at 已超过 600s: task_id=task_old",
            stage="multi_role_first_last_video",
        )

        with patch.object(dispatcher, "get_retry_count", return_value=99), \
             patch.object(dispatcher, "set_retry_count") as set_retry_count, \
             patch.object(dispatcher, "safe_get_record", return_value={"视频生成状态": "生成中"}), \
             patch.object(dispatcher, "safe_update_record", side_effect=lambda token, table, record_id, fields: updates.append(fields)), \
             patch.object(dispatcher, "clear_retry_count") as clear_retry_count, \
             patch.object(dispatcher, "clear_dead_letter") as clear_dead_letter, \
             patch.object(dispatcher, "bump_metric"):
            retried = dispatcher.maybe_retry_task("token", watch, "rec_clip", "tk_multi_role_first_last.py::video::rec_clip", "timeout", error_payload=payload)

        self.assertTrue(retried)
        set_retry_count.assert_not_called()
        clear_retry_count.assert_called_once_with("tk_multi_role_first_last.py::video::rec_clip")
        clear_dead_letter.assert_called_once_with("tk_multi_role_first_last.py::video::rec_clip")
        self.assertEqual(updates[-1]["视频生成状态"], "待生成")
        self.assertEqual(updates[-1]["视频任务ID"], "")
        self.assertEqual(updates[-1]["视频原始响应JSON"], "")
        self.assertIn("重新提交新任务", updates[-1]["视频错误信息"])

    def test_parse_subprocess_error_payload_accepts_wrapped_error_payload(self):
        stderr = (
            'Traceback before structured payload\n'
            '{"error": {"stage": "tk_prompt_image_video.py image", '
            '"status": "failed_terminal", "error_code": "PROMPT_BUILD_FAILED", '
            '"retryable": false, "message": "OTU 图片任务提交失败: HTTP 400, body={\\"error\\":\\"bad size\\"}"}}\n'
            'Traceback after structured payload\n'
        )

        payload = dispatcher.parse_subprocess_error_payload("", stderr, "tk_prompt_image_video.py")

        self.assertEqual(payload["stage"], "tk_prompt_image_video.py image")
        self.assertEqual(payload["error_code"], "PROMPT_BUILD_FAILED")
        self.assertFalse(payload["retryable"])
        self.assertIn("HTTP 400", payload["message"])
        self.assertIn("bad size", payload["message"])

    def test_nine_grid_image_claim_clears_stale_task_state_for_waiting_records(self):
        watch = next(w for w in dispatcher.WATCH_LIST if w["name"] == "多图宫格图片生成")
        claim_fields = {watch["status_field"]: watch["running_value"]}

        dispatcher.apply_claim_clear_fields(claim_fields, watch, trigger_value="待生成")

        self.assertEqual(claim_fields["图片生成状态"], "生成中")
        self.assertEqual(claim_fields["图片任务ID"], "")
        self.assertEqual(claim_fields["图片错误信息"], "")
        self.assertIsNone(claim_fields["图片生成时间"])
        self.assertEqual(claim_fields["视频任务ID"], "")
        self.assertEqual(claim_fields["视频错误信息"], "")
        self.assertIsNone(claim_fields["视频生成时间"])
        self.assertEqual(claim_fields["视频生成状态"], "不触发")

    def test_prompt_image_claim_increments_existing_image_version_before_clearing(self):
        watch = next(w for w in dispatcher.WATCH_LIST if w["name"] == "008图生视频图片生成")
        updates = []
        latest = {
            "图片生成状态": "待生成",
            "图片版本": 2,
            "图片file_token": "ft_old",
            "图片任务ID": "task_old",
        }

        with patch.object(dispatcher, "safe_get_record", return_value=latest), \
             patch.object(dispatcher, "safe_update_record", side_effect=lambda token, table, record_id, fields: updates.append(fields)), \
             patch.object(dispatcher, "update_record_state_cache"), \
             patch.object(dispatcher, "get_table_field_kinds", return_value={"生成图片": "attachment"}):
            self.assertTrue(dispatcher.try_claim_task("token", watch, "rec1"))

        self.assertEqual(updates[0]["图片生成状态"], "生成中")
        self.assertEqual(updates[0]["图片版本"], 3)
        self.assertEqual(updates[0]["图片file_token"], "")
        self.assertEqual(updates[0]["图片任务ID"], "")

    def test_prompt_image_claim_does_not_double_increment_prepared_regeneration(self):
        watch = next(w for w in dispatcher.WATCH_LIST if w["name"] == "008图生视频图片生成")
        updates = []
        latest = {
            "图片生成状态": "待生成",
            "图片版本": 3,
            "图片file_token": "",
            "图片任务ID": "",
        }

        with patch.object(dispatcher, "safe_get_record", return_value=latest), \
             patch.object(dispatcher, "safe_update_record", side_effect=lambda token, table, record_id, fields: updates.append(fields)), \
             patch.object(dispatcher, "update_record_state_cache"), \
             patch.object(dispatcher, "get_table_field_kinds", return_value={"生成图片": "attachment"}):
            self.assertTrue(dispatcher.try_claim_task("token", watch, "rec1"))

        self.assertNotIn("图片版本", updates[0])

    def test_multi_role_video_claim_increments_existing_video_version_before_clearing(self):
        watch = next(w for w in dispatcher.WATCH_LIST if w["name"] == "多角色视频片段生成")
        updates = []
        latest = {
            "记录类型": "视频片段",
            "视频生成状态": "待生成",
            "视频版本": 4,
            "视频片段file_token": "ft_old",
            "视频任务ID": "task_old",
        }

        with patch.object(dispatcher, "safe_get_record", return_value=latest), \
             patch.object(dispatcher, "safe_update_record", side_effect=lambda token, table, record_id, fields: updates.append(fields)), \
             patch.object(dispatcher, "update_record_state_cache"), \
             patch.object(dispatcher, "get_table_field_kinds", return_value={"视频片段": "attachment", "视频片段URL": "text"}):
            self.assertTrue(dispatcher.try_claim_task("token", watch, "rec1"))

        self.assertEqual(updates[0]["视频生成状态"], "生成中")
        self.assertEqual(updates[0]["视频版本"], 5)
        self.assertEqual(updates[0]["视频片段file_token"], "")
        self.assertEqual(updates[0]["视频任务ID"], "")

    def test_media_video_claim_clears_outputs_only_for_waiting_regeneration(self):
        expectations = {
            "多图宫格视频生成": ["分镜视频", "分镜视频URL", "视频任务ID", "视频错误信息", "视频生成时间"],
            "脚本文档分镜视频生成": ["分镜视频", "分镜视频URL", "视频任务ID", "视频生成原始响应JSON", "视频错误信息", "视频生成时间"],
            "003新表脚本文档分镜视频生成": ["分镜视频", "分镜视频URL", "视频任务ID", "视频错误信息"],
        }

        for watch_name, cleared_fields in expectations.items():
            with self.subTest(watch_name=watch_name):
                watch = next(w for w in dispatcher.WATCH_LIST if w["name"] == watch_name)
                waiting_claim = {watch["status_field"]: watch["running_value"]}
                running_claim = {watch["status_field"]: watch["running_value"]}

                dispatcher.apply_claim_clear_fields(waiting_claim, watch, trigger_value="待生成")
                dispatcher.apply_claim_clear_fields(running_claim, watch, trigger_value="生成中")

                for field_name in cleared_fields:
                    self.assertIn(field_name, waiting_claim)
                    self.assertNotIn(field_name, running_claim)

    def test_video_edit_watch_claim_clears_stale_result_state(self):
        watch = next(w for w in dispatcher.WATCH_LIST if w["name"] == "视频编辑生成")
        claim_fields = {watch["status_field"]: watch["running_value"]}

        dispatcher.apply_claim_clear_fields(claim_fields, watch, trigger_value="待生成")

        self.assertEqual(watch["script"], "tk_video_edit.py")
        self.assertEqual(watch["args"], ["edit"])
        self.assertEqual(claim_fields["编辑状态"], "生成中")
        self.assertEqual(claim_fields["结果视频"], [])
        self.assertEqual(claim_fields["视频任务ID"], "")
        self.assertEqual(claim_fields["错误信息"], "")

    def test_clear_retry_count_for_manual_waiting_requeue(self):
        watch = {
            "trigger_value": "待生成",
            "error_field": "视频错误信息",
        }

        with patch.object(dispatcher, "clear_retry_count") as clear_retry_count, \
             patch.object(dispatcher, "clear_dead_letter") as clear_dead_letter:
            dispatcher.clear_retry_count_for_manual_requeue(
                watch,
                "task-key",
                "待生成",
                {"视频错误信息": "用户重新提交，清空失败状态"},
            )

        clear_retry_count.assert_called_once_with("task-key")
        clear_dead_letter.assert_called_once_with("task-key")

    def test_clear_retry_count_for_manual_waiting_requeue_keeps_auto_retry_count(self):
        watch = {
            "trigger_value": "待生成",
            "error_field": "视频错误信息",
        }

        with patch.object(dispatcher, "clear_retry_count") as clear_retry_count, \
             patch.object(dispatcher, "clear_dead_letter") as clear_dead_letter:
            dispatcher.clear_retry_count_for_manual_requeue(
                watch,
                "task-key",
                "待生成",
                {"视频错误信息": "自动重试中[UPSTREAM_NETWORK] 第 1 次失败，将继续重试"},
            )

        clear_retry_count.assert_not_called()
        clear_dead_letter.assert_not_called()

    def test_clear_retry_count_for_manual_waiting_requeue_keeps_dispatcher_failure_count(self):
        watch = {
            "trigger_value": "待解析",
            "error_field": "解析错误信息",
        }

        with patch.object(dispatcher, "clear_retry_count") as clear_retry_count, \
             patch.object(dispatcher, "clear_dead_letter") as clear_dead_letter:
            cleared = dispatcher.clear_retry_count_for_manual_requeue(
                watch,
                "task-key",
                "待解析",
                {"解析错误信息": "dispatcher兜底失败回写[UPSTREAM_NETWORK]: Read timed out"},
            )

        self.assertFalse(cleared)
        clear_retry_count.assert_not_called()
        clear_dead_letter.assert_not_called()

    def test_clear_retry_count_for_manual_waiting_requeue_keeps_auto_resubmit_count(self):
        watch = {
            "trigger_value": "待生成",
            "error_field": "视频错误信息",
        }

        with patch.object(dispatcher, "clear_retry_count") as clear_retry_count, \
             patch.object(dispatcher, "clear_dead_letter") as clear_dead_letter:
            cleared = dispatcher.clear_retry_count_for_manual_requeue(
                watch,
                "task-key",
                "待生成",
                {"视频错误信息": "自动重新提交新任务[UPSTREAM_NETWORK]: 等待 dispatcher 提交新任务"},
            )

        self.assertFalse(cleared)
        clear_retry_count.assert_not_called()
        clear_dead_letter.assert_not_called()

    def test_clear_retry_count_for_manual_waiting_requeue_clears_empty_error(self):
        watch = {
            "trigger_value": "待解析",
            "error_field": "解析错误信息",
        }

        with patch.object(dispatcher, "clear_retry_count") as clear_retry_count, \
             patch.object(dispatcher, "clear_dead_letter") as clear_dead_letter:
            cleared = dispatcher.clear_retry_count_for_manual_requeue(
                watch,
                "task-key",
                "待解析",
                {"解析错误信息": ""},
            )

        self.assertTrue(cleared)
        clear_retry_count.assert_called_once_with("task-key")
        clear_dead_letter.assert_called_once_with("task-key")

    def test_mark_task_failed_writes_failed_status_after_retry_limit(self):
        watch = {
            "name": "003新表脚本文档解析拆分",
            "script": "tk_script_doc_shots.py",
            "args": ["parse", "--unified"],
            "table": "tbl_unified",
            "status_field": "解析状态",
            "trigger_value": "待解析",
            "running_value": "解析中",
            "failed_value": "失败",
            "error_field": "解析错误信息",
            "max_retries": 1,
        }
        payload = {
            "status": "failed_retryable",
            "error_code": "UPSTREAM_NETWORK",
            "retryable": True,
            "message": "Read timed out",
        }
        updates = []

        with patch.object(dispatcher, "append_last_error"), \
             patch.object(dispatcher, "safe_get_record", return_value={"解析状态": "待解析"}), \
             patch.object(dispatcher, "get_retry_count", return_value=1), \
             patch.object(dispatcher, "set_retry_count") as set_retry_count, \
             patch.object(dispatcher, "safe_update_record", side_effect=lambda token, table, record_id, fields: updates.append(fields)), \
             patch.object(dispatcher, "register_dead_letter") as register_dead_letter, \
             patch.object(dispatcher, "bump_metric"):
            dispatcher.mark_task_failed(
                "token",
                watch,
                "rec_doc",
                "tk_script_doc_shots.py::parse --unified::rec_doc",
                reason="timeout",
                error_payload=payload,
            )

        set_retry_count.assert_called_once()
        self.assertEqual(updates[-1]["解析状态"], "失败")
        self.assertIn("dispatcher兜底失败回写[UPSTREAM_NETWORK]", updates[-1]["解析错误信息"])
        register_dead_letter.assert_called_once()

    def test_unified_script_doc_video_watch_reclaims_running_records(self):
        watch = next(w for w in dispatcher.WATCH_LIST if w["name"] == "003新表脚本文档分镜视频生成")

        self.assertEqual(watch["trigger_values"], ["待生成", "生成中"])

    def test_unified_script_doc_video_claim_clears_task_id_for_waiting_records(self):
        watch = next(w for w in dispatcher.WATCH_LIST if w["name"] == "003新表脚本文档分镜视频生成")
        claim_fields = {watch["status_field"]: watch["running_value"]}

        dispatcher.apply_claim_clear_fields(claim_fields, watch, trigger_value="待生成")

        self.assertEqual(claim_fields["视频生成状态"], "生成中")
        self.assertEqual(claim_fields["视频任务ID"], "")

    def test_unified_script_doc_video_claim_keeps_task_id_when_reclaiming_running_records(self):
        watch = next(w for w in dispatcher.WATCH_LIST if w["name"] == "003新表脚本文档分镜视频生成")
        claim_fields = {watch["status_field"]: watch["running_value"]}

        dispatcher.apply_claim_clear_fields(claim_fields, watch, trigger_value="生成中")

        self.assertEqual(claim_fields["视频生成状态"], "生成中")
        self.assertNotIn("视频任务ID", claim_fields)


if __name__ == "__main__":
    unittest.main()
