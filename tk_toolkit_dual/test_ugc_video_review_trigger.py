import unittest
from unittest.mock import Mock

import tk_ugc_video_review_trigger as trig


class UGCVideoReviewTriggerTest(unittest.TestCase):
    def test_should_regenerate_video_accepts_actions(self):
        self.assertTrue(trig.should_regenerate_video({"分镜视频操作": "重新生成分镜视频"}))
        self.assertTrue(trig.should_regenerate_video({"分镜视频操作": "生成分镜视频"}))
        self.assertFalse(trig.should_regenerate_video({"分镜视频操作": "不触发"}))

    def test_process_video_regen_requires_call_models(self):
        with self.assertRaisesRegex(ValueError, "需要显式 --call-models"):
            trig.process_video_regen_record({"record_id": "rec06", "fields": {}}, write=True, call_models=False)

    def test_process_video_regen_allows_overwrite(self):
        fn = Mock(return_value={"status": "success"})
        result = trig.process_video_regen_record({"record_id": "rec06", "fields": {}}, write=True, call_models=True, video_fn=fn)
        fn.assert_called_once_with("rec06", dry_run=False, allow_overwrite=True)
        self.assertEqual(result["stage"], "ugc06_video_regen")

    def test_run_video_review_stage_resets_action(self):
        records = [{"record_id": "rec06", "fields": {"分镜视频操作": "重新生成分镜视频"}}]
        updates = []
        old_process = trig.process_video_regen_record
        old_update = trig.update_ugc_record
        try:
            trig.process_video_regen_record = Mock(return_value={"status": "success"})
            trig.update_ugc_record = lambda token, table, rid, fields: updates.append((rid, fields))
            result = trig.run_video_review_stage(token="t", ugc06_table="tbl06", limit=5, write=True, call_models=True, records=records)
        finally:
            trig.process_video_regen_record = old_process
            trig.update_ugc_record = old_update
        self.assertEqual(result["pending_count"], 1)
        self.assertEqual(updates[0][1]["分镜视频执行状态"], "处理中")
        self.assertEqual(updates[-1][1]["分镜视频操作"], "不触发")
        self.assertEqual(updates[-1][1]["分镜视频执行状态"], "成功")


if __name__ == "__main__":
    unittest.main()
