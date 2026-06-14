import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import repair_media_versions as repair


class RepairMediaVersionsTests(unittest.TestCase):
    def test_prompt_like_audit_uses_history_without_guessing_missing_history(self):
        records = [
            {
                "record_id": "rec_with_history",
                "fields": {
                    "图片版本": 1,
                    "视频版本": 1,
                    "历史生成记录JSON": '[{"stage":"image","version":3},{"stage":"video","version":2}]',
                },
            },
            {
                "record_id": "rec_without_history",
                "fields": {
                    "图片版本": 1,
                    "视频版本": 1,
                    "图片file_token": "ft_current",
                    "生成视频file_token": "ft_video",
                },
            },
        ]

        updates = repair.audit_prompt_like_records(records, table_label="008-图生视频生成表")

        self.assertEqual(updates, [
            {
                "table": "008-图生视频生成表",
                "record_id": "rec_with_history",
                "fields": {"图片版本": 3, "视频版本": 2},
                "reason": "history",
            }
        ])

    def test_multi_role_audit_updates_active_child_from_deprecated_same_parent_key(self):
        records = [
            {
                "record_id": "old_video",
                "fields": {
                    "记录类型": "视频片段",
                    "记录状态": "已废弃",
                    "父任务记录ID": "parent",
                    "视频片段类型": "S01",
                    "视频版本": 3,
                },
            },
            {
                "record_id": "new_video",
                "fields": {
                    "记录类型": "视频片段",
                    "记录状态": "有效",
                    "父任务记录ID": "parent",
                    "视频片段类型": "S01",
                    "视频版本": 1,
                },
            },
            {
                "record_id": "fresh_video",
                "fields": {
                    "记录类型": "视频片段",
                    "记录状态": "有效",
                    "父任务记录ID": "other_parent",
                    "视频片段类型": "S01",
                    "视频版本": 1,
                },
            },
        ]

        updates = repair.audit_multi_role_records(records)

        self.assertEqual(updates, [
            {
                "table": "001-多角色首尾帧生成表",
                "record_id": "new_video",
                "fields": {"视频版本": 4},
                "reason": "deprecated_sibling",
            }
        ])

    def test_first_last_audit_updates_active_scene_from_deprecated_same_parent_scene(self):
        records = [
            {
                "record_id": "old_scene",
                "fields": {
                    "记录类型": "场景子任务",
                    "记录状态": "已废弃",
                    "父任务记录ID": "parent",
                    "场景编号": 1,
                    "首帧图版本": 2,
                    "尾帧图版本": 4,
                    "视频版本": 6,
                },
            },
            {
                "record_id": "old_scene_without_number",
                "fields": {
                    "记录类型": "场景子任务",
                    "记录状态": "已废弃",
                    "父任务记录ID": "parent",
                    "视频版本": 99,
                },
            },
            {
                "record_id": "new_scene",
                "fields": {
                    "记录类型": "场景子任务",
                    "记录状态": "有效",
                    "父任务记录ID": "parent",
                    "场景编号": 1,
                    "首帧图版本": 1,
                    "尾帧图版本": 1,
                    "视频版本": 1,
                },
            },
            {
                "record_id": "other_parent_scene",
                "fields": {
                    "记录类型": "场景子任务",
                    "记录状态": "有效",
                    "父任务记录ID": "other_parent",
                    "场景编号": 1,
                    "视频版本": 1,
                },
            },
        ]

        updates = repair.audit_first_last_records(records)

        self.assertEqual(updates, [
            {
                "table": "002-首尾帧视频生成表",
                "record_id": "new_scene",
                "fields": {"首帧图版本": 3, "尾帧图版本": 5, "视频版本": 7},
                "reason": "deprecated_sibling",
            }
        ])


if __name__ == "__main__":
    unittest.main()
