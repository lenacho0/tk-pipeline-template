import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import repair_nine_grid_reference_approvals as repair


class RepairNineGridReferenceApprovalsTests(unittest.TestCase):
    def test_dry_run_reports_candidates_without_writing(self):
        records = [
            {
                "record_id": "asset_passed",
                "fields": {
                    "记录类型": "参考资产",
                    "父任务记录ID": "parent1",
                    "参考图审核状态": "通过",
                    "参考图file_token": "ft_ref",
                },
            },
            {
                "record_id": "board_waiting",
                "fields": {
                    "记录类型": "Board分段",
                    "父任务记录ID": "parent1",
                    "图片生成状态": "不触发",
                },
            },
        ]

        with patch.object(repair.nine_grid, "safe_update_record") as update_record, \
             patch.object(repair.nine_grid, "advance_boards_after_reference_approval") as advance:
            summary = repair.repair_reference_approvals("token", records=records, write=False)

        self.assertEqual(summary["candidate_count"], 1)
        self.assertEqual(summary["parent_count"], 1)
        self.assertEqual(summary["would_mark_handled_count"], 1)
        self.assertEqual(summary["would_advance_parent_count"], 1)
        self.assertEqual(summary["actions"][0]["record_id"], "asset_passed")
        update_record.assert_not_called()
        advance.assert_not_called()

    def test_write_advances_parent_once_and_marks_passed_assets_handled(self):
        records = [
            {
                "record_id": "asset_passed",
                "fields": {
                    "记录类型": "参考资产",
                    "父任务记录ID": "parent1",
                    "参考图审核状态": "通过",
                    "参考图file_token": "ft_ref",
                },
            },
            {
                "record_id": "asset_handled",
                "fields": {
                    "记录类型": "参考资产",
                    "父任务记录ID": "parent1",
                    "参考图审核状态": "已触发下游",
                    "参考图file_token": "ft_done",
                },
            },
            {
                "record_id": "board_waiting",
                "fields": {
                    "记录类型": "Board分段",
                    "父任务记录ID": "parent1",
                    "图片生成状态": "不触发",
                },
            },
        ]
        updates = []

        with patch.object(repair.nine_grid, "TABLE_NINE_GRID_VIDEO", "tbl_nine"), \
             patch.object(repair.nine_grid, "advance_boards_after_reference_approval", return_value={"status": "advanced", "advanced_boards": 1}) as advance, \
             patch.object(repair.nine_grid, "filter_existing_fields", side_effect=lambda token, table, payload: payload), \
             patch.object(repair.nine_grid, "safe_update_record", side_effect=lambda token, table, record_id, payload: updates.append((table, record_id, payload))):
            summary = repair.repair_reference_approvals("token", records=records, write=True)

        advance.assert_called_once_with("token", "parent1")
        self.assertEqual(updates, [
            ("tbl_nine", "asset_passed", {"参考图审核状态": "已触发下游", "参考图操作": "不触发", "错误信息": ""}),
        ])
        self.assertEqual(summary["marked_handled_count"], 1)
        self.assertEqual(summary["advanced_parent_count"], 1)

    def test_missing_reference_file_is_skipped(self):
        records = [
            {
                "record_id": "asset_missing",
                "fields": {
                    "记录类型": "参考资产",
                    "父任务记录ID": "parent1",
                    "参考图审核状态": "通过",
                },
            },
        ]

        summary = repair.repair_reference_approvals("token", records=records, write=False)

        self.assertEqual(summary["candidate_count"], 1)
        self.assertEqual(summary["missing_file_count"], 1)
        self.assertEqual(summary["would_mark_handled_count"], 0)


if __name__ == "__main__":
    unittest.main()
