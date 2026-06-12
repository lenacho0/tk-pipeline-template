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
        self.assertIn("Aitgenne / happyhorse-1.0-t2v", text)
        self.assertIn("Aitgenne / happyhorse-1.0-r2v", text)
        self.assertIn("Aitgenne / happyhorse-1.0-i2v", text)
        self.assertIn("Aitgenne / omni-flash", text)
        self.assertIn("Aitgenne / veo_3_1_lite_vip", text)
        self.assertIn("Aitgenne / veo_3_1_fast_vip", text)
        self.assertIn("Aitgenne / veo_3_1_vip", text)
        self.assertIn("Aitgenne / veo_3_1_components_vip", text)
        self.assertNotIn("speech-2.8-turbo", text)
        self.assertTrue(all(preset["fields"]["状态"] == "启用" for preset in presets))
        aitgenne_video = next(
            preset for preset in presets
            if preset["key"] == "Aitgenne / veo_3_1_fast_vip"
        )
        self.assertEqual(aitgenne_video["fields"]["环节"], "Aitgenne Fast VIP图生视频生成")
        self.assertEqual(aitgenne_video["fields"]["配置类型"], "运行环节")
        self.assertEqual(aitgenne_video["fields"]["供应商"], "Aitgenne")
        self.assertEqual(aitgenne_video["fields"]["能力类型"], "视频")
        self.assertNotIn("AI供应商", aitgenne_video["fields"])
        self.assertNotIn("AI能力类型", aitgenne_video["fields"])
        self.assertNotIn("统一AI预设", aitgenne_video["fields"]["环节"])

    def test_aitgenne_text_key_models_are_runtime_stages(self):
        presets = {preset["key"]: preset for preset in governance.build_config_presets()}
        expected = {
            "Aitgenne / gemini-3.5-flash": "Aitgenne Gemini 3.5 Flash文本拆解",
            "Aitgenne / claude-opus-4-8": "Aitgenne Claude Opus 4.8文本拆解",
        }

        for model, stage in expected.items():
            fields = presets[model]["fields"]
            self.assertEqual(fields["配置类型"], "运行环节")
            self.assertEqual(fields["环节"], stage)
            self.assertEqual(fields["模型名称"], model)
            self.assertEqual(fields["供应商"], "Aitgenne")
            self.assertEqual(fields["能力类型"], "文本")
            self.assertEqual(fields["API 代理地址"], "https://api.aitgenne.com/v1")
            self.assertEqual(fields["调用方式"], "OpenAI兼容 chat/completions")
            self.assertEqual(fields["状态"], "启用")
            self.assertNotIn("统一AI预设", fields["环节"])

    def test_runtime_stage_upsert_migrates_same_model_legacy_preset(self):
        preset = next(
            item for item in governance.build_config_presets()
            if item["key"] == "Aitgenne / gemini-3.5-flash"
        )
        allowed_fields = set(preset["fields"])
        legacy_record = {
            "record_id": "rec_old",
            "fields": {
                "环节": "统一AI预设-Aitgenne / gemini-3.5-flash",
                "配置类型": "模型目录",
                "模型名称": "Aitgenne / gemini-3.5-flash",
            },
        }
        calls = []

        def fake_request_json(method, url, token, **kwargs):
            calls.append((method, url, kwargs))
            return {"code": 0, "data": {}}

        with patch("sync_ai_model_catalog_to_feishu.existing_field_names", return_value=allowed_fields), \
                patch("sync_ai_model_catalog_to_feishu.list_records", return_value=[legacy_record]), \
                patch("sync_ai_model_catalog_to_feishu.request_json", side_effect=fake_request_json):
            results = governance.upsert_config_presets(
                "tenant-token",
                "app-token",
                "tbl-config",
                [preset],
                dry_run=False,
            )

        self.assertEqual(results[0]["action"], "update")
        self.assertEqual(results[0]["record_id"], "rec_old")
        self.assertEqual(len(calls), 1)
        method, url, kwargs = calls[0]
        self.assertEqual(method, "put")
        self.assertTrue(url.endswith("/records/rec_old"))
        fields = kwargs["json"]["fields"]
        self.assertEqual(fields["配置类型"], "运行环节")
        self.assertEqual(fields["环节"], "Aitgenne Gemini 3.5 Flash文本拆解")
        self.assertEqual(fields["模型名称"], "Aitgenne / gemini-3.5-flash")

    def test_field_option_updates_are_production_only(self):
        config = {
            "feishu": {
                "bitable_app_token": "app_token",
                "tables": {
                    "config": "tbl_config",
                    "nine_grid_video": "tbl_nine",
                    "first_last_video": "tbl_first_last",
                    "script_doc_tasks": "tbl_script_tasks",
                    "script_doc_unified": "tbl_script_unified",
                    "storyboard_video": "tbl_storyboard",
                    "prompt_image_video": "tbl_prompt_image",
                    "multi_role_first_last": "tbl_multi",
                },
            }
        }

        updates = governance.build_field_option_updates(config)
        by_key = {(item.table_key, item.field_name): [opt["name"] for opt in item.options] for item in updates}

        text_options = [entry.display_name for entry in ai_model_catalog.production_models("文本")]
        self.assertEqual(by_key[("nine_grid_video", "文本AI模型")], text_options)
        self.assertEqual(by_key[("nine_grid_video", "参考图AI模型")], [entry.display_name for entry in ai_model_catalog.production_models("图片")])
        self.assertEqual(by_key[("nine_grid_video", "图片AI模型")], [entry.display_name for entry in ai_model_catalog.production_models("图片")])
        self.assertEqual(by_key[("nine_grid_video", "视频生成模型")], [opt["name"] for opt in ai_model_catalog.REFERENCE_VIDEO_MODEL_WITH_DEFAULT_OPTIONS])
        self.assertEqual(by_key[("first_last_video", "文本AI模型")], text_options)
        self.assertEqual(by_key[("script_doc_tasks", "文本AI模型")], text_options)
        self.assertEqual(by_key[("script_doc_unified", "文本AI模型")], text_options)
        self.assertEqual(by_key[("multi_role_first_last", "文本AI模型")], text_options)
        self.assertEqual(by_key[("first_last_video", "首帧图AI模型")], [entry.display_name for entry in ai_model_catalog.production_models("图片")])
        self.assertEqual(by_key[("first_last_video", "视频生成模型")], [opt["name"] for opt in ai_model_catalog.FIRST_LAST_VIDEO_MODEL_WITH_DEFAULT_OPTIONS])
        self.assertEqual(by_key[("first_last_video", "视频通道")], ["OTU", "AIHubMix", "Aitgenne"])
        self.assertNotIn(("nine_grid_video", "视频AI模型"), by_key)
        self.assertNotIn(("nine_grid_video", "方案AI模型"), by_key)
        self.assertNotIn(("first_last_video", "视频AI模型"), by_key)
        self.assertNotIn(("first_last_video", "拆分AI模型"), by_key)
        self.assertNotIn(("script_doc_tasks", "解析AI模型"), by_key)
        self.assertNotIn(("script_doc_unified", "解析AI模型"), by_key)
        self.assertNotIn(("multi_role_first_last", "拆解AI模型"), by_key)
        self.assertNotIn(("script_doc_tasks", "视频AI模型"), by_key)
        self.assertNotIn(("script_doc_shots", "视频AI模型"), by_key)
        self.assertEqual(by_key[("script_doc_unified", "视频生成模型")], [opt["name"] for opt in ai_model_catalog.FIRST_LAST_VIDEO_MODEL_WITH_DEFAULT_OPTIONS])
        self.assertEqual(by_key[("storyboard_video", "视频生成模型")], [opt["name"] for opt in ai_model_catalog.STORYBOARD_VIDEO_MODEL_WITH_DEFAULT_OPTIONS])
        self.assertEqual(by_key[("prompt_image_video", "视频生成模型")], [opt["name"] for opt in ai_model_catalog.PROMPT_IMAGE_VIDEO_MODEL_WITH_DEFAULT_OPTIONS])
        self.assertEqual(by_key[("multi_role_first_last", "关键帧AI模型")], [entry.display_name for entry in ai_model_catalog.production_models("图片")])
        self.assertEqual(by_key[("multi_role_first_last", "视频生成模型")], [opt["name"] for opt in ai_model_catalog.FIRST_LAST_VIDEO_MODEL_WITH_DEFAULT_OPTIONS])
        self.assertEqual(by_key[("multi_role_first_last", "视频通道")], ["OTU", "AIHubMix", "Aitgenne"])
        self.assertNotIn(("multi_role_first_last", "视频AI模型"), by_key)
        self.assertIn("Aitgenne / happyhorse-1.0-i2v", by_key[("multi_role_first_last", "视频生成模型")])
        self.assertIn("Aitgenne / veo_3_1_fast_vip", by_key[("multi_role_first_last", "视频生成模型")])
        self.assertIn("Aitgenne / veo_3_1_components_vip", by_key[("nine_grid_video", "视频生成模型")])
        self.assertIn("Aitgenne / veo_3_1_components_vip", by_key[("prompt_image_video", "视频生成模型")])
        self.assertNotIn("Aitgenne / veo_3_1_components_vip", by_key[("first_last_video", "视频生成模型")])
        self.assertNotIn("Aitgenne / veo_3_1_components_vip", by_key[("storyboard_video", "视频生成模型")])
        self.assertNotIn("OTU / veo_3_1-fl", by_key[("nine_grid_video", "视频生成模型")])

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
        self.assertIn("Aitgenne / veo_3_1_components_vip", serialized)
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
