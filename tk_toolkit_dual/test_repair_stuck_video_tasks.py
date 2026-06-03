import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import repair_stuck_video_tasks as repair


class RepairStuckVideoTasksTests(unittest.TestCase):
    def test_run_filters_by_kind_and_record_id(self):
        nine_grid_records = [
            {"record_id": "rec_keep", "fields": {"视频生成状态": "失败", "视频错误信息": "err"}},
            {"record_id": "rec_skip", "fields": {"视频生成状态": "失败", "视频错误信息": "err"}},
        ]
        multi_role_records = [
            {"record_id": "rec_keep", "fields": {"视频生成状态": "失败", "视频错误信息": "err"}},
        ]

        with patch.object(repair, "get_feishu_token", return_value="token"), \
             patch.object(repair, "safe_list_records", side_effect=[nine_grid_records, multi_role_records]) as list_records, \
             patch.object(repair, "repair_record", side_effect=lambda token, kind, record, write: {
                 "record_id": record["record_id"],
                 "kind": kind,
                 "action": "checked",
             }):
            outputs = repair.run(write=False, kind_filter="nine_grid", record_ids=["rec_keep"])

        self.assertEqual(outputs, [{"record_id": "rec_keep", "kind": "nine_grid", "action": "checked"}])
        list_records.assert_called_once_with("token", repair.nine_grid.TABLE_NINE_GRID_VIDEO)

    def test_clear_dispatcher_state_for_record_removes_retry_and_dead_letter(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            retry_path = Path(tmpdir) / "retry.json"
            dead_path = Path(tmpdir) / "dead.json"
            retry_path.write_text(json.dumps({
                "tk_nine_grid_video.py::video::rec1": {"record_id": "rec1"},
                "tk_nine_grid_video.py::image::rec1": {"record_id": "rec1"},
                "tk_nine_grid_video.py::video::rec2": {"record_id": "rec2"},
            }), encoding="utf-8")
            dead_path.write_text(json.dumps({
                "tk_nine_grid_video.py::video::rec1": {"record_id": "rec1"},
                "tk_nine_grid_video.py::image::rec1": {"record_id": "rec1"},
                "tk_nine_grid_video.py::video::rec2": {"record_id": "rec2"},
            }), encoding="utf-8")

            with patch.object(repair, "RETRY_STATE_FILE", str(retry_path), create=True), \
                 patch.object(repair, "DEAD_LETTER_FILE", str(dead_path), create=True):
                result = repair.clear_dispatcher_state_for_record("nine_grid", "rec1", action="video", write=True)

            self.assertEqual(result["removed_retry_keys"], ["tk_nine_grid_video.py::video::rec1"])
            self.assertEqual(result["removed_dead_letter_keys"], ["tk_nine_grid_video.py::video::rec1"])
            self.assertEqual(json.loads(retry_path.read_text(encoding="utf-8")), {
                "tk_nine_grid_video.py::image::rec1": {"record_id": "rec1"},
                "tk_nine_grid_video.py::video::rec2": {"record_id": "rec2"},
            })
            self.assertEqual(json.loads(dead_path.read_text(encoding="utf-8")), {
                "tk_nine_grid_video.py::image::rec1": {"record_id": "rec1"},
                "tk_nine_grid_video.py::video::rec2": {"record_id": "rec2"},
            })

    def test_failed_record_without_artifact_resets_for_resubmit(self):
        record = {
            "record_id": "rec_failed",
            "fields": {
                "视频生成状态": "失败",
                "视频错误信息": "dispatcher兜底失败回写[RUNTIME_BUG]: upstream busy",
            },
        }

        with patch.object(repair, "has_live_process", return_value=False), \
             patch.object(repair, "filter_fields", side_effect=lambda token, kind, fields: fields), \
             patch.object(repair, "clear_dispatcher_state_for_record", return_value={
                 "removed_retry_keys": ["tk_nine_grid_video.py::video::rec_failed"],
                 "removed_dead_letter_keys": [],
             }):
            action = repair.repair_record("token", "nine_grid", record, write=False)

        self.assertEqual(action["action"], "reset_for_resubmit")
        self.assertEqual(action["payload"]["视频生成状态"], "待生成")
        self.assertEqual(action["payload"]["视频任务ID"], "")
        self.assertIn("没有可复用视频", action["payload"]["视频错误信息"])
        self.assertEqual(action["dispatcher_state_cleanup"]["removed_retry_keys"], ["tk_nine_grid_video.py::video::rec_failed"])


if __name__ == "__main__":
    unittest.main()
