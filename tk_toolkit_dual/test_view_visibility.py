import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import view_visibility


class ViewVisibilityTests(unittest.TestCase):
    def write_snapshot(self, payload):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        path = Path(tmpdir.name) / "snapshot.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def test_snapshot_overrides_defaults_and_preserves_extra_views(self):
        path = self.write_snapshot({
            "tables": {
                "tasks": {
                    "table_id": "tbl_live",
                    "views": {
                        "01-用户入口": {"visible_fields": ["任务名称", "解析状态"]},
                        "Grid View": {"visible_fields": ["任务名称"]},
                    },
                },
            },
        })

        result = view_visibility.apply_view_visibility_snapshot(
            "tbl_live",
            {"01-用户入口": ["任务名称", "解析状态", "错误信息"]},
            snapshot_path=path,
        )

        self.assertEqual(result["01-用户入口"], ["任务名称", "解析状态"])
        self.assertEqual(result["Grid View"], ["任务名称"])

    def test_snapshot_mismatch_falls_back_to_defaults(self):
        path = self.write_snapshot({
            "tables": {
                "tasks": {
                    "table_id": "tbl_other",
                    "views": {
                        "01-用户入口": {"visible_fields": ["任务名称"]},
                    },
                },
            },
        })

        defaults = {"01-用户入口": ["任务名称", "解析状态"]}
        result = view_visibility.apply_view_visibility_snapshot("tbl_live", defaults, snapshot_path=path)

        self.assertEqual(result, defaults)
        self.assertIsNot(result, defaults)

    def test_snapshot_can_override_dict_definitions_without_losing_filters(self):
        path = self.write_snapshot({
            "tables": {
                "config": {
                    "table_id": "tbl_config",
                    "views": {
                        "02-任务默认配置": {"visible_fields": ["应用表格", "状态"]},
                        "99-线上新增": {"visible_fields": ["状态"]},
                    },
                },
            },
        })

        defaults = {
            "02-任务默认配置": {
                "visible_fields": ["应用表格", "模型名称", "状态"],
                "filter": {"logic": "and", "conditions": [["配置类型", "intersects", ["任务默认"]]]},
            },
        }
        result = view_visibility.apply_view_visibility_snapshot("tbl_config", defaults, snapshot_path=path)

        self.assertEqual(result["02-任务默认配置"]["visible_fields"], ["应用表格", "状态"])
        self.assertEqual(result["02-任务默认配置"]["filter"], defaults["02-任务默认配置"]["filter"])
        self.assertEqual(result["99-线上新增"], {"visible_fields": ["状态"]})

    def test_snapshot_serialization_rejects_secret_like_values(self):
        snapshot = view_visibility.build_visibility_snapshot(
            base_token="base_token_should_not_be_saved",
            table_entries=[
                {
                    "table_key": "config",
                    "table_id": "tbl_config",
                    "views": {
                        "04-API密钥管理-管理员": {
                            "view_id": "viw_admin",
                            "visible_fields": ["环节", "API Key", "状态"],
                        }
                    },
                }
            ],
        )
        serialized = json.dumps(snapshot, ensure_ascii=False)

        self.assertNotIn("base_token_should_not_be_saved", serialized)
        self.assertIn("API Key", serialized)
        self.assertIn("tbl_config", serialized)
