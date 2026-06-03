import unittest
from unittest.mock import Mock
from unittest.mock import patch

import repair_multi_role_video_prompts as repair


class RepairMultiRoleVideoPromptsTests(unittest.TestCase):
    def test_repair_prompt_translates_chinese_action_and_preserves_thai(self):
        model = Mock(return_value="Action: The owner sprays foam onto the sofa urine stain.\nDialogue: The owner says in Thai: ไม่ต้องตกใจ")

        result = repair.repair_prompt_text(
            "Action: 主人对准沙发尿渍喷泡沫。\nThe owner says in Thai: ไม่ต้องตกใจ",
            translate_fn=model,
        )

        self.assertEqual(
            result,
            "Action: The owner sprays foam onto the sofa urine stain.\nDialogue: The owner says in Thai: ไม่ต้องตกใจ",
        )
        self.assertFalse(repair.has_cjk_text(result))
        self.assertIn("ไม่ต้องตกใจ", result)
        self.assertIn("preserve Thai dialogue exactly", model.call_args.args[0])

    def test_repair_prompt_keeps_english_prompt_without_calling_model(self):
        model = Mock()

        result = repair.repair_prompt_text(
            "Action: The owner sprays foam onto the sofa stain. The owner says in Thai: ไม่ต้องตกใจ",
            translate_fn=model,
        )

        self.assertEqual(
            result,
            "Action: The owner sprays foam onto the sofa stain. The owner says in Thai: ไม่ต้องตกใจ",
        )
        model.assert_not_called()

    def test_collect_candidates_skips_running_records_by_default(self):
        records = [
            {
                "record_id": "rec_running",
                "fields": {
                    "记录类型": "视频片段",
                    "父任务记录ID": "parent1",
                    "视频片段类型": "S01",
                    "视频生成状态": "生成中",
                    "视频提示词": "Action: 主人喷泡沫。",
                },
            },
            {
                "record_id": "rec_waiting",
                "fields": {
                    "记录类型": "视频片段",
                    "父任务记录ID": "parent2",
                    "视频片段类型": "S02",
                    "视频生成状态": "待生成",
                    "视频提示词": "Action: 租客擦地毯。 The tenant says in Thai: ขอเวลาแค่ 1 นาที",
                },
            },
            {
                "record_id": "rec_english",
                "fields": {
                    "记录类型": "视频片段",
                    "父任务记录ID": "parent3",
                    "视频片段类型": "S01",
                    "视频生成状态": "成功",
                    "视频提示词": "Action: The renter wipes the carpet.",
                },
            },
        ]

        candidates, skipped = repair.collect_repair_candidates(records)

        self.assertEqual([item.record_id for item in candidates], ["rec_waiting"])
        self.assertEqual([item.record_id for item in skipped], ["rec_running"])

    def test_collect_candidates_filters_record_ids_and_policy_safe_english_prompts(self):
        records = [
            {
                "record_id": "rec_target",
                "fields": {
                    "记录类型": "视频片段",
                    "父任务记录ID": "parent1",
                    "视频片段类型": "S02",
                    "视频生成状态": "失败",
                    "视频提示词": "Action: The stain disappears completely. The owner says in Thai: ไม่ต้องตกใจ",
                },
            },
            {
                "record_id": "rec_other",
                "fields": {
                    "记录类型": "视频片段",
                    "父任务记录ID": "parent2",
                    "视频片段类型": "S01",
                    "视频生成状态": "失败",
                    "视频提示词": "Action: 主人喷泡沫。",
                },
            },
        ]

        candidates, skipped = repair.collect_repair_candidates(
            records,
            record_ids={"rec_target"},
            policy_safe_regenerate=True,
        )

        self.assertEqual([item.record_id for item in candidates], ["rec_target"])
        self.assertEqual(skipped, [])

    def test_policy_safe_regenerate_rewrites_english_prompt_and_keeps_thai(self):
        model = Mock(return_value="Action: The treated mattress looks cleaner and slightly damp.\nThe owner says in Thai: ไม่ต้องตกใจ")

        result = repair.repair_prompt_text(
            "Action: The urine stain disappears completely. The owner says in Thai: ไม่ต้องตกใจ. Buy one bottle now.",
            translate_fn=model,
            policy_safe_regenerate=True,
            clip_type="S02",
        )

        self.assertEqual(
            result,
            "Action: The treated mattress looks cleaner and slightly damp.\nThe owner says in Thai: ไม่ต้องตกใจ",
        )
        self.assertFalse(repair.has_cjk_text(result))
        self.assertIn("ไม่ต้องตกใจ", result)
        self.assertIn("avoid shopping CTA", model.call_args.args[0])
        self.assertIn("S02 result", model.call_args.args[0])

    def test_run_repair_writes_prompt_and_resets_for_rerun(self):
        records = [
            {
                "record_id": "rec_target",
                "fields": {
                    "记录类型": "视频片段",
                    "父任务记录ID": "parent1",
                    "视频片段类型": "S02",
                    "视频生成状态": "失败",
                    "视频提示词": "Action: The stain disappears completely. The owner says in Thai: ไม่ต้องตกใจ.",
                    "视频任务ID": "task_old",
                },
            },
            {
                "record_id": "rec_other",
                "fields": {
                    "记录类型": "视频片段",
                    "父任务记录ID": "parent2",
                    "视频片段类型": "S01",
                    "视频生成状态": "失败",
                    "视频提示词": "Action: 主人喷泡沫。",
                },
            },
        ]
        updates = []
        repaired_prompt = "Action: The treated sofa area looks cleaner and slightly damp.\nThe owner says in Thai: ไม่ต้องตกใจ"

        with patch.object(repair, "TABLE_MULTI_ROLE_FIRST_LAST", "tbl_multi"), \
             patch.object(repair, "get_feishu_token", return_value="token"), \
             patch.object(repair, "safe_list_records", return_value=records), \
             patch.object(repair, "_translation_route", return_value=object()), \
             patch.object(repair, "_make_translate_fn", return_value=Mock(return_value=repaired_prompt)), \
             patch.object(repair, "safe_update_record", side_effect=lambda token, table, rid, fields: updates.append((rid, fields))), \
             patch.object(repair, "filter_existing_fields", side_effect=lambda token, table, fields: fields):
            result = repair.run_repair(
                write=True,
                record_ids=["rec_target"],
                policy_safe_regenerate=True,
                reset_for_rerun=True,
            )

        self.assertEqual(result["candidate_count"], 1)
        self.assertEqual(result["repaired_records"][0]["record_id"], "rec_target")
        self.assertEqual(len(updates), 1)
        record_id, payload = updates[0]
        self.assertEqual(record_id, "rec_target")
        self.assertEqual(payload["视频提示词"], repaired_prompt)
        self.assertEqual(payload["视频生成状态"], "待生成")
        self.assertEqual(payload["视频操作"], "不触发")
        self.assertEqual(payload["视频任务ID"], "")
        self.assertEqual(payload["视频本地路径"], "")
        self.assertEqual(payload["视频错误信息"], "")
        self.assertEqual(payload["错误信息"], "")
        self.assertEqual(payload["视频原始响应JSON"], "")


if __name__ == "__main__":
    unittest.main()
