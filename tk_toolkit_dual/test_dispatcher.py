import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common
import tk_dispatcher as dispatcher


class DispatcherRecoveryTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
