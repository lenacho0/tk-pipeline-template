import unittest
from unittest.mock import Mock

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


if __name__ == "__main__":
    unittest.main()
