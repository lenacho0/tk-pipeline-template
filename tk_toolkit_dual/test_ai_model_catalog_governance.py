import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ai_model_catalog
import sync_ai_model_catalog_to_feishu as governance


class AiModelCatalogGovernanceTests(unittest.TestCase):
    def test_config_presets_exclude_discard_and_secrets(self):
        presets = governance.build_config_presets()
        text = json.dumps(presets, ensure_ascii=False)

        self.assertNotIn("happyhorse-1.0-video-edit", text)
        self.assertNotIn("API Key", text)
        self.assertIn("OTU / gpt-image-2-4K", text)
        self.assertIn("Aitgenne / happyhorse-1.0-r2v", text)
        self.assertIn("Aitgenne / happyhorse-1.0-i2v", text)
        self.assertIn("Aitgenne / omni-flash", text)
        self.assertNotIn("speech-2.8-turbo", text)
        self.assertTrue(all(preset["fields"]["状态"] == "启用" for preset in presets))

    def test_field_option_updates_are_production_only(self):
        config = {
            "feishu": {
                "bitable_app_token": "app_token",
                "tables": {
                    "config": "tbl_config",
                    "nine_grid_video": "tbl_nine",
                    "storyboard_video": "tbl_story",
                    "first_last_video": "tbl_first_last",
                    "script_doc_tasks": "tbl_tasks",
                    "script_doc_shots": "tbl_shots",
                    "multi_role_first_last": "tbl_multi",
                },
            }
        }

        updates = governance.build_field_option_updates(config)
        by_key = {(item.table_key, item.field_name): [opt["name"] for opt in item.options] for item in updates}

        self.assertEqual(by_key[("nine_grid_video", "方案AI模型")], [entry.display_name for entry in ai_model_catalog.production_models("文本")])
        self.assertEqual(by_key[("nine_grid_video", "图片AI模型")], [entry.display_name for entry in ai_model_catalog.production_models("图片")])
        self.assertEqual(by_key[("nine_grid_video", "视频AI模型")], [entry.display_name for entry in ai_model_catalog.production_models("视频")])
        self.assertEqual(by_key[("first_last_video", "拆分AI模型")], [entry.display_name for entry in ai_model_catalog.production_models("文本")])
        self.assertEqual(by_key[("first_last_video", "首帧图AI模型")], [entry.display_name for entry in ai_model_catalog.production_models("图片")])
        self.assertEqual(by_key[("script_doc_tasks", "视频AI模型")], [entry.display_name for entry in ai_model_catalog.production_models("视频")])
        self.assertEqual(by_key[("multi_role_first_last", "关键帧AI模型")], [entry.display_name for entry in ai_model_catalog.production_models("图片")])
        self.assertIn("默认（配置表）", by_key[("first_last_video", "视频生成模型")])
        self.assertIn("Aitgenne / happyhorse-1.0-i2v", by_key[("multi_role_first_last", "视频生成模型")])

        serialized = json.dumps(updates, default=lambda obj: obj.__dict__, ensure_ascii=False)
        self.assertNotIn("happyhorse-1.0-video-edit", serialized)
        self.assertNotIn("Aitgenne / gemini-3.1-pro-preview", serialized)
        self.assertNotIn("Aitgenne / happyhorse-1.0-t2v", serialized)
        self.assertNotIn("AIHubMix / gpt-image-2", serialized)
        self.assertNotIn("OTU / nano_banana_pro-4K", serialized)
        self.assertNotIn("speech-2.8-turbo", serialized)

    def test_dry_run_matrix_redacts_secrets(self):
        summaries = governance.build_dry_run_matrix(api_key="sk-test-token")
        serialized = json.dumps(summaries, ensure_ascii=False)

        enabled_media_count = len(ai_model_catalog.production_models("图片")) + len(ai_model_catalog.production_models("视频"))
        self.assertEqual(enabled_media_count, len(summaries))
        self.assertIn("OTU / gpt-image-2", serialized)
        self.assertIn("Aitgenne / happyhorse-1.0-r2v", serialized)
        self.assertIn("endpoint", serialized)
        self.assertIn("payload_keys", serialized)
        self.assertIn("reference_count", serialized)
        self.assertNotIn("sk-test-token", serialized)
        self.assertNotIn("Authorization", serialized)
        self.assertNotIn("token", serialized.lower())

    def test_run_json_treats_lark_no_operation_as_noop_success(self):
        no_op = json.dumps({
            "ok": False,
            "error": {
                "code": 800070003,
                "message": "no operation produced",
            },
        })
        proc = SimpleNamespace(returncode=1, stdout=no_op, stderr="")

        with patch("sync_ai_model_catalog_to_feishu.subprocess.run", return_value=proc):
            result = governance.run_json(["lark-cli", "base", "+field-update"])

        self.assertTrue(result["ok"])
        self.assertTrue(result["noop"])

    def test_run_json_treats_stderr_lark_no_operation_as_noop_success(self):
        no_op = '[lark-cli] [WARN] proxy detected\n' + json.dumps({
            "ok": False,
            "error": {
                "code": 800070003,
                "message": "no operation produced",
            },
        })
        proc = SimpleNamespace(returncode=1, stdout="", stderr=no_op)

        with patch("sync_ai_model_catalog_to_feishu.subprocess.run", return_value=proc):
            result = governance.run_json(["lark-cli", "base", "+field-update"])

        self.assertTrue(result["ok"])
        self.assertTrue(result["noop"])


if __name__ == "__main__":
    unittest.main()
