import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import repair_stuck_media_tasks as repair


class RepairStuckMediaTasksTests(unittest.TestCase):
    def test_completed_image_task_downloads_uploads_and_marks_success(self):
        spec = repair.MEDIA_SPECS["first_last_first_frame"]
        record = {
            "record_id": "rec_img",
            "fields": {
                "首帧图生成状态": "失败",
                "首帧图任务ID": "task_done",
                "首帧图错误信息": "queued timeout",
            },
        }
        updates = []

        with patch.object(repair, "has_live_process", return_value=False), \
             patch.object(repair, "query_task", return_value=({"status": "completed", "result_url": "https://x.test/out.png"}, "https://x.test/out.png")), \
             patch.object(repair, "download_media") as downloader, \
             patch.object(repair, "upload_media", return_value="ft_img") as uploader, \
             patch.object(repair, "safe_update_record", side_effect=lambda token, table, record_id, payload: updates.append((table, record_id, payload))), \
             patch.object(repair, "filter_fields", side_effect=lambda token, spec, payload: payload), \
             patch.object(repair, "clear_dispatcher_state_for_record", return_value={"removed_retry_keys": [], "removed_dead_letter_keys": []}):
            action = repair.repair_record("token", spec, record, write=True)

        downloader.assert_called_once_with("https://x.test/out.png", action["local_path"], "image")
        uploader.assert_called_once_with("token", action["local_path"], "rec_img_first_frame.png", "image")
        self.assertEqual(action["action"], "uploaded_media")
        self.assertEqual(updates[0][0], spec.table_id)
        self.assertEqual(updates[0][1], "rec_img")
        self.assertEqual(updates[0][2]["首帧图生成状态"], "成功")
        self.assertEqual(updates[0][2]["首帧图"], [{"file_token": "ft_img", "name": "rec_img_first_frame.png"}])
        self.assertEqual(updates[0][2]["首帧图file_token"], "ft_img")

    def test_queued_task_restores_running_without_resubmitting(self):
        spec = repair.MEDIA_SPECS["multi_role_reference"]
        record = {
            "record_id": "rec_ref",
            "fields": {
                "参考图生成状态": "失败",
                "参考图任务ID": "task_queue",
                "参考图错误信息": "queued progress=0 timeout",
            },
        }

        with patch.object(repair, "has_live_process", return_value=False), \
             patch.object(repair, "query_task", return_value=({"status": "queued", "progress": 0}, "")), \
             patch.object(repair, "filter_fields", side_effect=lambda token, spec, payload: payload), \
             patch.object(repair, "clear_dispatcher_state_for_record", return_value={"removed_retry_keys": ["key"], "removed_dead_letter_keys": []}):
            action = repair.repair_record("token", spec, record, write=False)

        self.assertEqual(action["action"], "restore_running")
        self.assertEqual(action["payload"]["参考图生成状态"], "生成中")
        self.assertEqual(action["payload"]["参考图任务ID"], "task_queue")
        self.assertIn("恢复轮询", action["payload"]["参考图错误信息"])
        self.assertEqual(action["dispatcher_state_cleanup"]["removed_retry_keys"], ["key"])

    def test_stale_zero_progress_task_resets_for_resubmit(self):
        spec = repair.MEDIA_SPECS["multi_role_video"]
        record = {
            "record_id": "rec_video",
            "fields": {
                "视频生成状态": "失败",
                "视频任务ID": "task_stale",
                "视频错误信息": "OTU 视频 progress=0 timeout",
            },
        }

        with patch.object(repair, "has_live_process", return_value=False), \
             patch.object(repair, "query_task", return_value=({"status": "queued", "progress": 0, "created_at": 1000}, "")), \
             patch.object(repair.time, "time", return_value=1701), \
             patch.object(repair, "filter_fields", side_effect=lambda token, spec, payload: payload), \
             patch.object(repair, "clear_dispatcher_state_for_record", return_value={"removed_retry_keys": [], "removed_dead_letter_keys": ["dead"]}):
            action = repair.repair_record("token", spec, record, write=False)

        self.assertEqual(action["action"], "reset_for_resubmit")
        self.assertEqual(action["payload"]["视频生成状态"], "待生成")
        self.assertEqual(action["payload"]["视频任务ID"], "")
        self.assertIn("progress=0 排队超时", action["payload"]["视频错误信息"])
        self.assertEqual(action["dispatcher_state_cleanup"]["removed_dead_letter_keys"], ["dead"])

    def test_existing_attachment_success_does_not_fake_local_path(self):
        spec = repair.MEDIA_SPECS["multi_role_reference"]
        record = {
            "record_id": "rec_ref",
            "fields": {
                "参考图生成状态": "失败",
                "参考图": [{"file_token": "ft_existing", "name": "existing.png"}],
                "参考图错误信息": "upload writeback failed",
            },
        }

        with patch.object(repair, "has_live_process", return_value=False), \
             patch.object(repair, "filter_fields", side_effect=lambda token, spec, payload: payload), \
             patch.object(repair, "clear_dispatcher_state_for_record", return_value={"removed_retry_keys": [], "removed_dead_letter_keys": []}):
            action = repair.repair_record("token", spec, record, write=False)

        self.assertEqual(action["action"], "mark_existing_attachment_success")
        self.assertNotIn("参考图本地路径", action["payload"])
        self.assertEqual(action["payload"]["参考图"], [{"file_token": "ft_existing", "name": "existing.png"}])

    def test_policy_blocked_marks_manual_failure(self):
        spec = repair.MEDIA_SPECS["multi_role_video"]
        record = {
            "record_id": "rec_video",
            "fields": {
                "视频生成状态": "失败",
                "视频任务ID": "task_bad",
                "视频错误信息": "timeout",
            },
        }

        with patch.object(repair, "has_live_process", return_value=False), \
             patch.object(repair, "query_task", return_value=({"status": "failed", "error": {"message": "提示词或图片中包含违规信息，请立即修改后重试"}}, "")), \
             patch.object(repair, "filter_fields", side_effect=lambda token, spec, payload: payload), \
             patch.object(repair, "clear_dispatcher_state_for_record", return_value={"removed_retry_keys": [], "removed_dead_letter_keys": []}):
            action = repair.repair_record("token", spec, record, write=False)

        self.assertEqual(action["action"], "mark_policy_blocked")
        self.assertEqual(action["payload"]["视频生成状态"], "失败")
        self.assertIn("上游判定提示词或图片违规", action["payload"]["视频错误信息"])

    def test_transient_failed_task_resets_for_resubmit(self):
        spec = repair.MEDIA_SPECS["nine_grid_video"]
        record = {
            "record_id": "rec_grid",
            "fields": {
                "视频生成状态": "失败",
                "视频任务ID": "task_busy",
                "视频错误信息": "upstream busy",
            },
        }

        with patch.object(repair, "has_live_process", return_value=False), \
             patch.object(repair, "query_task", return_value=({"status": "failed", "error": {"message": "服务内部异常，请重新发起请求"}}, "")), \
             patch.object(repair, "filter_fields", side_effect=lambda token, spec, payload: payload), \
             patch.object(repair, "clear_dispatcher_state_for_record", return_value={"removed_retry_keys": [], "removed_dead_letter_keys": ["dead"]}):
            action = repair.repair_record("token", spec, record, write=False)

        self.assertEqual(action["action"], "reset_for_resubmit")
        self.assertEqual(action["payload"]["视频生成状态"], "待生成")
        self.assertEqual(action["payload"]["视频任务ID"], "")
        self.assertIn("上游任务失败或无可下载结果", action["payload"]["视频错误信息"])
        self.assertEqual(action["dispatcher_state_cleanup"]["removed_dead_letter_keys"], ["dead"])

    def test_reset_preserves_message_when_error_field_is_common_error_field(self):
        spec = repair.MEDIA_SPECS["script_doc_reference"]

        with patch.object(repair, "filter_fields", side_effect=lambda token, spec, payload: payload), \
             patch.object(repair, "clear_dispatcher_state_for_record", return_value={"removed_retry_keys": [], "removed_dead_letter_keys": []}):
            action = repair.reset_for_resubmit("token", spec, "rec_doc", "没有可复用结果，清空旧 task 等待重新提交。", write=False)

        self.assertEqual(action["payload"]["参考图生成状态"], "待生成")
        self.assertEqual(action["payload"]["参考图任务ID"], "")
        self.assertIn("没有可复用结果", action["payload"]["错误信息"])

    def test_live_process_is_skipped(self):
        spec = repair.MEDIA_SPECS["first_last_video"]
        record = {"record_id": "rec_live", "fields": {"视频生成状态": "生成中", "视频任务ID": "task_live"}}

        with patch.object(repair, "has_live_process", return_value=True):
            action = repair.repair_record("token", spec, record, write=False)

        self.assertEqual(action["action"], "skip_live_process")

    def test_clear_dispatcher_state_for_record_removes_exact_action_key(self):
        spec = repair.MEDIA_SPECS["nine_grid_image"]
        with tempfile.TemporaryDirectory() as tmpdir:
            retry_path = Path(tmpdir) / "retry.json"
            dead_path = Path(tmpdir) / "dead.json"
            retry_path.write_text(json.dumps({
                "tk_nine_grid_video.py::image::rec1": {"record_id": "rec1"},
                "tk_nine_grid_video.py::video::rec1": {"record_id": "rec1"},
            }), encoding="utf-8")
            dead_path.write_text(json.dumps({
                "tk_nine_grid_video.py::image::rec1": {"record_id": "rec1"},
                "tk_nine_grid_video.py::video::rec1": {"record_id": "rec1"},
            }), encoding="utf-8")

            with patch.object(repair, "RETRY_STATE_FILE", retry_path), \
                 patch.object(repair, "DEAD_LETTER_FILE", dead_path):
                result = repair.clear_dispatcher_state_for_record(spec, "rec1", write=True)

            self.assertEqual(result["removed_retry_keys"], ["tk_nine_grid_video.py::image::rec1"])
            self.assertEqual(result["removed_dead_letter_keys"], ["tk_nine_grid_video.py::image::rec1"])
            self.assertEqual(json.loads(retry_path.read_text(encoding="utf-8")), {
                "tk_nine_grid_video.py::video::rec1": {"record_id": "rec1"},
            })
            self.assertEqual(json.loads(dead_path.read_text(encoding="utf-8")), {
                "tk_nine_grid_video.py::video::rec1": {"record_id": "rec1"},
            })


if __name__ == "__main__":
    unittest.main()
