import unittest
from unittest.mock import Mock

import tk_ugc_review_trigger as trig


class UGCReviewTriggerTest(unittest.TestCase):
    def test_should_regenerate_shot_requires_action_only(self):
        self.assertTrue(trig.should_regenerate_shot({"分镜图操作": "重新生成单张分镜图"}))
        self.assertFalse(trig.should_regenerate_shot({"分镜图操作": "不触发"}))

    def test_should_enhance_requires_review_pass_and_action(self):
        self.assertTrue(trig.should_enhance({"分镜图审核状态": "通过", "分镜图操作": "确认分镜图并高清化"}))
        self.assertFalse(trig.should_enhance({"分镜图审核状态": "待确认", "分镜图操作": "确认分镜图并高清化"}))
        self.assertFalse(trig.should_enhance({"分镜图审核状态": "通过", "分镜图操作": "不触发"}))

    def test_should_reenhance_requires_hd_action(self):
        self.assertTrue(trig.should_reenhance({"高清图操作": "重新高清化"}))
        self.assertFalse(trig.should_reenhance({"高清图操作": "不触发"}))

    def test_should_generate_video_requires_hd_pass_and_action(self):
        self.assertTrue(trig.should_generate_video({"高清图审核状态": "通过", "高清图操作": "生成分镜视频"}))
        self.assertFalse(trig.should_generate_video({"高清图审核状态": "待确认", "高清图操作": "生成分镜视频"}))

    def test_regenerate_shot_requires_call_models(self):
        with self.assertRaisesRegex(ValueError, "需要显式 --call-models"):
            trig.process_regenerate_shot_record({"record_id": "rec05", "fields": {}}, write=True, call_models=False)

    def test_process_regenerate_shot_calls_single_record_regenerator(self):
        fn = Mock(return_value={"written": True})
        result = trig.process_regenerate_shot_record({"record_id": "rec05", "fields": {}}, write=True, call_models=True, regenerate_fn=fn)
        fn.assert_called_once_with("rec05", write=True)
        self.assertEqual(result["stage"], "ugc05_single_shot_regen")

    def test_enhance_requires_call_models(self):
        with self.assertRaisesRegex(ValueError, "需要显式 --call-models"):
            trig.process_enhance_record({"record_id": "rec05", "fields": {}}, write=True, call_models=False)

    def test_process_enhance_calls_single_record_enhancer(self):
        fn = Mock(return_value={"written": True})
        result = trig.process_enhance_record({"record_id": "rec05", "fields": {}}, write=True, call_models=True, enhance_fn=fn)
        fn.assert_called_once_with("rec05", write=True)
        self.assertEqual(result["stage"], "ugc05_enhance")

    def test_process_video_creates_ugc06_then_generates(self):
        create = Mock(return_value={"created_records": [{"record_id": "rec06"}]})
        video = Mock(return_value={"video": "ok"})
        result = trig.process_video_record({"record_id": "rec05", "fields": {}}, write=True, call_models=True, create_ugc06_fn=create, video_fn=video)
        create.assert_called_once_with(["rec05"], write=True)
        video.assert_called_once_with("rec06", dry_run=False)
        self.assertEqual(result["stage"], "ugc06_video")

    def test_run_review_stage_prioritizes_single_shot_regen(self):
        records = [{"record_id": "rec05", "fields": {"分镜图审核状态": "通过", "分镜图操作": "重新生成单张分镜图"}}]
        updates = []
        old_regen = trig.process_regenerate_shot_record
        old_update = trig.update_ugc_record
        try:
            trig.process_regenerate_shot_record = Mock(return_value={"status": "success", "stage": "ugc05_single_shot_regen"})
            trig.update_ugc_record = lambda token, table, rid, fields: updates.append((rid, fields))
            result = trig.run_review_stage(token="t", ugc05_table="tbl05", limit=10, write=True, call_models=True, records=records)
        finally:
            trig.process_regenerate_shot_record = old_regen
            trig.update_ugc_record = old_update
        self.assertEqual(result["pending_count"], 1)
        self.assertEqual(result["processed"][0]["stage"], "ugc05_single_shot_regen")
        self.assertEqual(updates[-1][1]["分镜图操作"], "不触发")

    def test_run_review_stage_processes_reenhance_and_resets_hd_action(self):
        records = [{"record_id": "rec05", "fields": {"高清图操作": "重新高清化"}}]
        updates = []
        old_enhance = trig.process_enhance_record
        old_update = trig.update_ugc_record
        try:
            trig.process_enhance_record = Mock(return_value={"stage": "ugc05_enhance", "status": "success"})
            trig.update_ugc_record = lambda token, table, rid, fields: updates.append((rid, fields))
            result = trig.run_review_stage(token="t", ugc05_table="tbl05", limit=10, write=True, call_models=True, records=records)
        finally:
            trig.process_enhance_record = old_enhance
            trig.update_ugc_record = old_update
        self.assertEqual(result["pending_count"], 1)
        self.assertEqual(result["processed"][0]["stage"], "ugc05_reenhance")
        self.assertEqual(updates[-1][1]["高清图操作"], "不触发")

    def test_run_review_stage_processes_pending_and_resets_action(self):
        records = [{"record_id": "rec05", "fields": {"分镜图审核状态": "通过", "分镜图操作": "确认分镜图并高清化"}}]
        updates = []
        old_process = trig.process_enhance_record
        old_update = trig.update_ugc_record
        try:
            trig.process_enhance_record = Mock(return_value={"status": "success"})
            trig.update_ugc_record = lambda token, table, rid, fields: updates.append((rid, fields))
            result = trig.run_review_stage(token="t", ugc05_table="tbl05", limit=10, write=True, call_models=True, records=records)
        finally:
            trig.process_enhance_record = old_process
            trig.update_ugc_record = old_update
        self.assertEqual(result["pending_count"], 1)
        self.assertEqual(len(result["processed"]), 1)
        self.assertEqual(updates[0][1]["分镜图执行状态"], "处理中")
        self.assertEqual(updates[-1][1]["分镜图操作"], "不触发")
        self.assertEqual(updates[-1][1]["分镜图执行状态"], "成功")


if __name__ == "__main__":
    unittest.main()
