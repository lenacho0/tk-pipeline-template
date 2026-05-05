import unittest
from unittest.mock import patch

import tk_ugc_reroll as reroll


class UGCRerollOrchestratorTest(unittest.TestCase):
    def test_plan_grid_reroll_builds_candidate_count(self):
        plan = reroll.plan_grid_reroll("recvieE3B2omPp", count=3, source_record_id="rec04_old", existing_candidates=[])
        self.assertEqual(len(plan["candidates"]), 3)
        self.assertEqual(plan["candidates"][0]["candidate_index"], 1)
        self.assertEqual(plan["candidates"][0]["candidate_group_id"], "UGC-GRID-GROUP-E3B2omPp")
        self.assertEqual(plan["candidates"][0]["reroll_source_record_id"], "rec04_old")

    def test_plan_video_reroll_uses_ugc05_group(self):
        plan = reroll.plan_video_reroll("rec05abc123", count=2, source_record_id="rec06_old", existing_candidates=[])
        self.assertEqual(len(plan["candidates"]), 2)
        self.assertEqual(plan["candidates"][0]["candidate_group_id"], "UGC-VIDEO-GROUP-05abc123")
        self.assertEqual(plan["candidates"][1]["candidate_index"], 2)

    def test_plan_video_reroll_from_ugc06_source_resolves_linked_ugc05(self):
        with patch("tk_ugc_reroll.load_ugc_table_ids") as tables:
            tables.return_value = {"ugc_06_shot_videos": "tbl06"}
            plan = reroll.plan_video_reroll_from_ugc06(
                "rec06_old",
                count=2,
                token="t",
                get_record_fn=lambda token, table, rid: {"关联分镜图片": [{"record_ids": ["rec05abc123"]}]},
            )
        self.assertEqual(plan["ugc05_record_id"], "rec05abc123")
        self.assertEqual(plan["source_record_id"], "rec06_old")
        self.assertEqual(plan["candidates"][0]["candidate_group_id"], "UGC-VIDEO-GROUP-05abc123")

    def test_execute_video_plan_creates_new_ugc06_candidates_without_calling_model(self):
        created = []
        plan = reroll.plan_video_reroll("rec05abc123", count=2, source_record_id="rec06_old", existing_candidates=[])
        with patch("tk_ugc_reroll.create_or_preview_ugc06_records") as create_prompts:
            create_prompts.side_effect = lambda ids, **kwargs: created.append((ids, kwargs)) or {"created_records": [{"record_id": "rec06_new"}], "written": kwargs.get("write")}
            result = reroll.execute_video_plan(plan, write=True, call_video=False)
        self.assertEqual(len(created), 2)
        self.assertEqual(created[0][0], ["rec05abc123"])
        self.assertEqual(created[0][1]["candidate_group_id"], "UGC-VIDEO-GROUP-05abc123")
        self.assertEqual(created[0][1]["candidate_index"], 1)
        self.assertEqual(created[0][1]["reroll_source_record_id"], "rec06_old")
        self.assertEqual(result["created_record_ids"], ["rec06_new", "rec06_new"])

    def test_select_candidate_marks_one_adopted_and_others_discarded(self):
        updates = []
        records = [
            {"record_id": "rec_a", "fields": {"重生成组ID": "group1", "候选状态": "候选", "视频生成状态": "成功"}},
            {"record_id": "rec_b", "fields": {"重生成组ID": "group1", "候选状态": "候选", "视频生成状态": "成功"}},
        ]
        reroll.apply_selection(
            table_id="tbl",
            group_id="group1",
            selected_record_id="rec_b",
            records=records,
            token="t",
            update_record_fn=lambda token, table, rid, fields: updates.append((rid, fields)),
        )
        self.assertEqual(updates, [
            ("rec_a", {"候选状态": "弃用"}),
            ("rec_b", {"候选状态": "采用"}),
        ])

    def test_select_candidate_refuses_non_success_by_default(self):
        records = [{"record_id": "rec_a", "fields": {"重生成组ID": "group1", "候选状态": "候选", "视频生成状态": "失败"}}]
        with self.assertRaises(ValueError):
            reroll.apply_selection(
                table_id="tbl",
                group_id="group1",
                selected_record_id="rec_a",
                records=records,
                token="t",
                update_record_fn=lambda *args: None,
            )


if __name__ == "__main__":
    unittest.main()
