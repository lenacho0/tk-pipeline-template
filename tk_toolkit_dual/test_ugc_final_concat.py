import unittest

import tk_ugc_final_concat as concat


class UGCFinalConcatSelectionTest(unittest.TestCase):
    def test_resolve_selected_videos_requires_one_adopted_per_shot(self):
        records = [
            {"record_id": "rec1a", "fields": {"分镜序号": 1, "候选状态": "采用", "视频生成状态": "成功"}},
            {"record_id": "rec1b", "fields": {"分镜序号": 1, "候选状态": "弃用", "视频生成状态": "成功"}},
            {"record_id": "rec2a", "fields": {"分镜序号": 2, "候选状态": "采用", "视频生成状态": "成功"}},
        ]
        selected = concat.resolve_selected_ugc06_records(records, expected_shot_count=2)
        self.assertEqual(selected, ["rec1a", "rec2a"])

    def test_resolve_selected_videos_fails_on_missing_selection(self):
        with self.assertRaises(ValueError):
            concat.resolve_selected_ugc06_records([
                {"record_id": "rec1", "fields": {"分镜序号": 1, "候选状态": "候选", "视频生成状态": "成功"}},
            ], expected_shot_count=1)

    def test_resolve_selected_videos_fails_on_duplicate_selection(self):
        with self.assertRaises(ValueError):
            concat.resolve_selected_ugc06_records([
                {"record_id": "rec1a", "fields": {"分镜序号": 1, "候选状态": "采用", "视频生成状态": "成功"}},
                {"record_id": "rec1b", "fields": {"分镜序号": 1, "候选状态": "采用", "视频生成状态": "成功"}},
            ], expected_shot_count=1)

    def test_create_from_selected_resolves_ids_before_concat(self):
        calls = []
        records = [
            {"record_id": "rec1", "fields": {"分镜序号": 1, "候选状态": "采用", "视频生成状态": "成功"}},
            {"record_id": "rec2", "fields": {"分镜序号": 2, "候选状态": "采用", "视频生成状态": "成功"}},
        ]
        result = concat.create_or_run_final_concat_from_selected(
            expected_shot_count=2,
            records=records,
            write=False,
            runner=lambda ids, **kwargs: calls.append((ids, kwargs)) or {"record_ids": ids, "dry_run": True},
        )
        self.assertEqual(calls[0][0], ["rec1", "rec2"])
        self.assertEqual(result["selected_ugc06_record_ids"], ["rec1", "rec2"])


if __name__ == "__main__":
    unittest.main()
