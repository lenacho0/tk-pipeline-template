import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common
import tk_dispatcher as dispatcher


class DispatcherRecoveryTests(unittest.TestCase):
    def setUp(self):
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

    def test_aitgenne_upstream_saturation_500_is_retryable(self):
        payload = common.build_error_payload(
            "Aitgenne 参考图视频任务提交失败: HTTP 500, body={'code': 'do_request_failed', "
            "'message': '当前分组上游负载已饱和，请稍后再试', 'data': None}",
            stage="nine_grid_video",
        )

        self.assertEqual(payload["error_code"], "UPSTREAM_RATE_LIMIT")
        self.assertTrue(payload["retryable"])
        self.assertEqual(payload["status"], "failed_retryable")

    def test_upstream_no_available_channel_is_terminal_config_error(self):
        payload = common.build_error_payload(
            "OTU 图片任务提交失败: HTTP 503, body={'code': 'fail_to_fetch_task', "
            "'message': '{\"error\":{\"code\":\"model_not_found\",\"message\":\"No available channel for model gpt-image-2 under group default\"}}'}",
            stage="image_generation",
        )

        self.assertEqual(payload["error_code"], "CONFIG_INVALID")
        self.assertFalse(payload["retryable"])
        self.assertEqual(payload["status"], "failed_terminal")

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
        watch = next(w for w in dispatcher.WATCH_LIST if w["name"] == "多图九宫格图片生成")
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


if __name__ == "__main__":
    unittest.main()
