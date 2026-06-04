import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import audit_stale_media_tokens as audit


class AuditStaleMediaTokensTests(unittest.TestCase):
    def test_audit_records_reports_latest_attachment_mismatch(self):
        records = [
            {
                "record_id": "rec1",
                "fields": {
                    "任务名称": "任务1",
                    "关键帧图": [{"file_token": "old_attach"}, {"file_token": "new_attach"}],
                    "关键帧图file_token": "old_cache",
                },
            },
            {
                "record_id": "rec2",
                "fields": {
                    "任务名称": "任务2",
                    "关键帧图": [{"file_token": "same"}],
                    "关键帧图file_token": "same",
                },
            },
            {
                "record_id": "rec3",
                "fields": {
                    "任务名称": "任务3",
                    "关键帧图": [{"file_token": "new_without_cache"}],
                    "关键帧图file_token": "",
                },
            },
        ]

        findings = audit.audit_records(
            records,
            [("关键帧图", "关键帧图file_token")],
            table_key="001",
            table_name="001-多角色首尾帧生成表",
        )

        self.assertEqual(len(findings), 2)
        self.assertEqual(findings[0]["record_id"], "rec1")
        self.assertEqual(findings[0]["latest_attachment_token"], "new_attach")
        self.assertEqual(findings[0]["cached_token"], "old_cache")
        self.assertEqual(findings[0]["status"], "stale_cache")
        self.assertEqual(findings[1]["record_id"], "rec3")
        self.assertEqual(findings[1]["status"], "missing_cache")

    def test_selected_specs_filters_requested_tables(self):
        self.assertEqual([spec["key"] for spec in audit.selected_specs(["001"])], ["001"])


if __name__ == "__main__":
    unittest.main()
