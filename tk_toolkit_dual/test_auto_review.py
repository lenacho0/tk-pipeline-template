import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import tk_auto_review as auto_review


class AutoReviewTests(unittest.TestCase):
    def test_auto_review_switch_defaults_off_when_missing_disabled_or_global_enabled(self):
        stage_name = auto_review.TABLE_AUTO_REVIEW_STAGE_NAMES["multi_role_first_last"]
        self.assertFalse(auto_review.auto_review_enabled("token", stage_name=stage_name, config_records=[]))
        self.assertFalse(auto_review.auto_review_enabled("token", stage_name=stage_name, config_records=[
            {"fields": {"环节": stage_name, "状态": "停用"}},
        ]))
        self.assertFalse(auto_review.auto_review_enabled("token", stage_name=stage_name, config_records=[
            {"fields": {"环节": auto_review.LEGACY_GLOBAL_AUTO_REVIEW_STAGE_NAME, "状态": "启用"}},
        ]))

    def test_auto_review_switch_enabled_by_table_config_record(self):
        stage_name = auto_review.TABLE_AUTO_REVIEW_STAGE_NAMES["nine_grid_video"]
        self.assertTrue(auto_review.auto_review_enabled("token", stage_name=stage_name, config_records=[
            {"fields": {"环节": stage_name, "状态": "启用"}},
        ]))

    def test_generated_result_gate_requires_token_and_keeps_regeneration_manual(self):
        self.assertFalse(auto_review.generated_result_can_auto_review(
            {"参考图版本": 1},
            attachment_field="参考图",
            token_field="参考图file_token",
            version_field="参考图版本",
            first_version_only=True,
        ))
        self.assertTrue(auto_review.generated_result_can_auto_review(
            {"参考图版本": 1, "参考图file_token": "ft_ref"},
            attachment_field="参考图",
            token_field="参考图file_token",
            version_field="参考图版本",
            first_version_only=True,
        ))
        self.assertFalse(auto_review.generated_result_can_auto_review(
            {"参考图版本": 2, "参考图file_token": "ft_ref"},
            attachment_field="参考图",
            token_field="参考图file_token",
            version_field="参考图版本",
            first_version_only=True,
        ))
        self.assertFalse(auto_review.generated_result_can_auto_review(
            {"参考图file_token": "ft_ref", "参考图操作": "重新生成参考图"},
            attachment_field="参考图",
            token_field="参考图file_token",
            operation_field="参考图操作",
            regeneration_values={"重新生成参考图"},
        ))

    def test_table_switch_records_are_created_disabled_when_missing(self):
        created = []
        with patch.object(auto_review, "TABLE_CONFIG", "tbl_config"), \
             patch.object(auto_review, "safe_list_records", return_value=[]), \
             patch.object(auto_review, "safe_request", side_effect=lambda *args, **kwargs: created.append(kwargs["json"]) or {"data": {"record": {"record_id": "recSwitch"}}}):
            result = auto_review.ensure_table_auto_review_switch_records("token", write=True)

        self.assertEqual(result["status"], "created")
        self.assertEqual(len(created), len(auto_review.TABLE_AUTO_REVIEW_STAGE_NAMES))
        self.assertEqual(
            {payload["fields"]["环节"] for payload in created},
            set(auto_review.TABLE_AUTO_REVIEW_STAGE_NAMES.values()),
        )
        self.assertIn(auto_review.TABLE_AUTO_REVIEW_STAGE_NAMES["storyboard_video"], {payload["fields"]["环节"] for payload in created})
        self.assertEqual({payload["fields"]["状态"] for payload in created}, {"停用"})
        self.assertEqual({payload["fields"]["配置类型"] for payload in created}, {"自动审核"})

    def test_sync_switch_records_deletes_legacy_and_duplicates_then_creates_missing(self):
        created = []
        deleted = []
        records = [
            {"record_id": "recLegacy", "fields": {"环节": auto_review.LEGACY_GLOBAL_AUTO_REVIEW_STAGE_NAME, "状态": "启用"}},
            {"record_id": "rec001", "fields": {"环节": auto_review.TABLE_AUTO_REVIEW_STAGE_NAMES["multi_role_first_last"], "状态": "启用"}},
            {"record_id": "rec001Dup", "fields": {"环节": auto_review.TABLE_AUTO_REVIEW_STAGE_NAMES["multi_role_first_last"], "状态": "停用"}},
        ]

        def fake_request(method, url, **kwargs):
            if method == "delete":
                deleted.append(url.rsplit("/", 1)[-1])
                return {"code": 0}
            created.append(kwargs["json"])
            return {"data": {"record": {"record_id": f"recNew{len(created)}"}}}

        with patch.object(auto_review, "TABLE_CONFIG", "tbl_config"), \
             patch.object(auto_review, "safe_list_records", return_value=records), \
             patch.object(auto_review, "safe_request", side_effect=fake_request):
            result = auto_review.sync_table_auto_review_switch_records("token", write=True)

        self.assertEqual(result["status"], "synced")
        self.assertEqual(set(deleted), {"recLegacy", "rec001Dup"})
        self.assertEqual(len(created), len(auto_review.TABLE_AUTO_REVIEW_STAGE_NAMES) - 1)
        self.assertIn(auto_review.TABLE_AUTO_REVIEW_STAGE_NAMES["first_last_video"], {payload["fields"]["环节"] for payload in created})
        self.assertIn(auto_review.TABLE_AUTO_REVIEW_STAGE_NAMES["storyboard_video"], {payload["fields"]["环节"] for payload in created})
        self.assertEqual({payload["fields"]["状态"] for payload in created}, {"停用"})
        self.assertEqual({payload["fields"]["配置类型"] for payload in created}, {"自动审核"})

    def test_ensure_switch_record_creates_missing_config(self):
        created = []
        with patch.object(auto_review, "TABLE_CONFIG", "tbl_config"), \
             patch.object(auto_review, "safe_list_records", return_value=[]), \
             patch.object(auto_review, "safe_request", side_effect=lambda *args, **kwargs: created.append(kwargs["json"]) or {"data": {"record": {"record_id": "recSwitch"}}}):
            result = auto_review.ensure_auto_review_switch_record("token", write=True)

        self.assertEqual(result["status"], "created")
        self.assertEqual(len(created), len(auto_review.TABLE_AUTO_REVIEW_STAGE_NAMES))
        self.assertIn("004-故事板视频生成表一键审核通过模式", {payload["fields"]["环节"] for payload in created})
        self.assertIn("008-图生视频生成表一键审核通过模式", {payload["fields"]["环节"] for payload in created})
        self.assertIn("003-脚本文档生产表一键审核通过模式", {payload["fields"]["环节"] for payload in created})


if __name__ == "__main__":
    unittest.main()
