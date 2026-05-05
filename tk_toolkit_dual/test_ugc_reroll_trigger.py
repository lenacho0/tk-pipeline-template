import unittest
from unittest.mock import Mock

import tk_ugc_reroll_trigger as trig


class UGCOneClickRerollTriggerTest(unittest.TestCase):
    def test_should_process_one_click_grid_record_when_checkbox_true(self):
        record = {
            "record_id": "rec04",
            "fields": {
                "一键重生成9宫格": True,
                "一键重生成状态": "",
            },
        }
        self.assertTrue(trig.should_process_one_click_grid_record(record))

    def test_checkbox_checked_supports_feishu_like_values(self):
        self.assertTrue(trig.checkbox_checked(True))
        self.assertTrue(trig.checkbox_checked([{"text": "是"}]))
        self.assertTrue(trig.checkbox_checked({"checked": True}))
        self.assertFalse(trig.checkbox_checked(False))
        self.assertFalse(trig.checkbox_checked([]))

    def test_build_one_click_result_update_resets_checkbox(self):
        payload = trig.build_one_click_result_update("成功", {"ok": True})
        self.assertEqual(payload["一键重生成9宫格"], False)
        self.assertEqual(payload["一键重生成状态"], "成功")
        self.assertIn('"ok": true', payload["一键重生成结果"])

    def test_process_one_click_grid_record_requires_call_models(self):
        with self.assertRaisesRegex(ValueError, "需要显式 --call-models"):
            trig.process_one_click_grid_record(
                {"record_id": "rec04", "fields": {"一键重生成9宫格": True}},
                write=True,
                call_models=False,
            )

    def test_process_one_click_grid_record_overwrites_same_record_and_shots(self):
        calls = []

        def fake_generate(record_id, *, call_image, write):
            calls.append(("image", record_id, call_image, write))
            return {"ugc04_record_id": record_id, "written": True, "file_token": "tok"}

        def fake_shots(record_id, *, write, overwrite_existing):
            calls.append(("shots", record_id, write, overwrite_existing))
            return {"ugc04_record_id": record_id, "updated_record_count": 6}

        result = trig.process_one_click_grid_record(
            {"record_id": "rec04", "fields": {"一键重生成9宫格": True}},
            write=True,
            call_models=True,
            image_generate_fn=fake_generate,
            shot_records_fn=fake_shots,
        )
        self.assertEqual(calls, [("image", "rec04", True, True), ("shots", "rec04", True, True)])
        self.assertEqual(result["source_record_id"], "rec04")
        self.assertEqual(result["mode"], "overwrite_current_grid_and_shots")
        self.assertEqual(result["result"]["shot_records"]["updated_record_count"], 6)

    def test_run_stage_processes_only_one_click_grid_records(self):
        records = [
            {"record_id": "rec04", "fields": {"一键重生成9宫格": True}},
            {"record_id": "old", "fields": {"重新生成执行状态": "待处理", "重新生成请求": "创建候选"}},
        ]
        updates = []
        original_process = trig.process_one_click_grid_record
        original_update = trig.update_ugc_record
        try:
            trig.process_one_click_grid_record = Mock(return_value={"status": "success", "mode": "overwrite_current_grid_and_shots"})
            trig.update_ugc_record = lambda token, table_id, record_id, fields: updates.append((record_id, fields))
            result = trig.run_stage(
                stage="grid",
                token="token",
                table_id="tbl",
                limit=5,
                write=True,
                call_models=True,
                records=records,
            )
        finally:
            trig.process_one_click_grid_record = original_process
            trig.update_ugc_record = original_update
        self.assertEqual(result["one_click_pending_count"], 1)
        self.assertEqual(len(result["processed"]), 1)
        self.assertEqual(updates[0][0], "rec04")
        self.assertEqual(updates[0][1]["一键重生成状态"], "处理中")

    def test_video_stage_is_disabled_after_legacy_fields_removed(self):
        result = trig.run_stage(
            stage="video",
            token="token",
            table_id="tbl",
            limit=5,
            write=False,
            call_models=False,
            records=[{"record_id": "rec06", "fields": {"一键重生成9宫格": True}}],
        )
        self.assertEqual(result["one_click_pending_count"], 0)
        self.assertEqual(result["processed"], [])
        self.assertIn("仅支持 UGC-04", result["skipped_reason"])


if __name__ == "__main__":
    unittest.main()
