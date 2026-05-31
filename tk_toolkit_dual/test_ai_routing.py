import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ai_routing
import ai_model_catalog
from common import extract_text


class UnifiedAiRoutingTests(unittest.TestCase):
    def test_extract_text_handles_empty_link_display_text(self):
        self.assertEqual(extract_text([{"record_ids": ["rec1"], "text": None}]), "")

    def test_route_switch_keeps_legacy_path_by_default(self):
        self.assertFalse(ai_routing.unified_route_enabled({}, []))
        self.assertFalse(ai_routing.unified_route_enabled({"使用统一AI路由": "是"}, []))

    def test_route_switch_allows_explicit_record_when_configured(self):
        records = [{"fields": {"环节": "统一AI路由启用状态", "状态": "指定记录启用"}}]

        self.assertTrue(ai_routing.unified_route_enabled({"使用统一AI路由": "是"}, records))
        self.assertFalse(ai_routing.unified_route_enabled({"使用统一AI路由": "否"}, records))

    def test_route_switch_prefers_model_name_mode_over_status(self):
        records = [{"fields": {"环节": "统一AI路由启用状态", "状态": "启用", "模型名称": "仅dry-run"}}]

        self.assertEqual(ai_routing.route_switch_mode(records), "仅dry-run")
        self.assertTrue(ai_routing.unified_route_enabled({"使用统一AI路由": "是"}, records))

    def test_validate_model_rejects_wrong_provider_or_capability(self):
        route = ai_routing.AiRoute(
            provider="Aitgenne",
            capability="文本",
            task_type="脚本解析拆分",
            model="OTU / gpt-image-2",
        )

        with self.assertRaisesRegex(ValueError, "供应商不匹配"):
            ai_routing.validate_route(route)

    def test_validate_model_rejects_candidate_catalog_entries(self):
        route = ai_routing.AiRoute(
            provider="Aitgenne",
            capability="文本",
            task_type="脚本生成",
            model="Aitgenne / gemini-3.1-pro-preview",
        )

        with self.assertRaisesRegex(ValueError, "AI模型不支持当前能力"):
            ai_routing.validate_route(route)

        self.assertEqual(
            ai_model_catalog.find_model("Aitgenne", "文本", "gemini-3.1-pro-preview", include_candidate=True).status,
            "candidate",
        )

    def test_route_from_record_infers_openai_compatible_for_aitgenne_gpt(self):
        route = ai_routing.route_from_record(
            {
                "AI能力类型": "文本",
                "AI任务类型": "脚本生成",
                "AI模型": "Aitgenne / gpt-5.5",
            },
            {
                "api_key": "sk-text",
                "api_base": "https://api.aitgenne.com",
            },
        )

        self.assertEqual(route.provider, "Aitgenne")
        self.assertEqual(route.call_type, "OpenAI兼容 chat/completions")

    def test_explicit_record_model_overrides_legacy_gemini_config_shape(self):
        route = ai_routing.route_from_record(
            {
                "AI供应商": "Aitgenne",
                "AI能力类型": "文本",
                "AI任务类型": "脚本解析拆分",
                "AI模型": "Aitgenne / gpt-5.5",
                "AI参数JSON": '{"temperature":0.1}',
            },
            {
                "provider": "AIHubMix",
                "model": "gemini-3.1-pro-preview",
                "call_type": "Gemini 原生 SDK",
                "api_key": "sk-legacy",
                "api_base": "https://aihubmix.com/gemini",
            },
        )

        self.assertEqual(route.provider, "Aitgenne")
        self.assertEqual(route.call_type, "OpenAI兼容 chat/completions")
        self.assertEqual(route.api_base, "")
        self.assertEqual(route.api_key, "")
        self.assertEqual(route.params["temperature"], 0.1)
        summary = ai_routing.build_dry_run_summary(route, "hello")
        self.assertEqual(summary["endpoint"], "https://api.aitgenne.com/v1/chat/completions")
        self.assertEqual(summary["api_key"], "")

    def test_prefixed_model_provider_overrides_stale_provider_field(self):
        route = ai_routing.route_from_record(
            {
                "AI供应商": "AIHubMix",
                "AI能力类型": "文本",
                "AI任务类型": "多图九宫格方案生成",
                "AI模型": "Aitgenne / gpt-5.5",
            },
            {
                "provider": "AIHubMix",
                "model": "AIHubMix / gemini-3.1-pro-preview",
                "call_type": "Gemini 原生 SDK",
                "api_key": "sk-aihubmix",
                "api_base": "https://aihubmix.com/gemini",
            },
            config_records=[
                {"fields": {"AI供应商": "AIHubMix", "API 代理地址": "https://aihubmix.com/gemini", "API Key": "sk-aihubmix"}},
                {"fields": {"AI供应商": "Aitgenne", "API 代理地址": "https://api.aitgenne.com", "API Key": "sk-aitgenne"}},
            ],
        )

        self.assertEqual(route.provider, "Aitgenne")
        self.assertEqual(route.call_type, "OpenAI兼容 chat/completions")
        self.assertEqual(route.api_base, "")
        self.assertEqual(route.api_key, "sk-aitgenne")
        self.assertEqual(ai_routing.build_dry_run_summary(route, "hello")["endpoint"], "https://api.aitgenne.com/v1/chat/completions")

    def test_provider_switch_does_not_reuse_wrong_provider_key(self):
        route = ai_routing.route_from_record(
            {
                "AI能力类型": "文本",
                "AI任务类型": "多图九宫格方案生成",
                "AI模型": "Aitgenne / gpt-5.5",
            },
            {
                "provider": "AIHubMix",
                "model": "AIHubMix / gemini-3.1-pro-preview",
                "call_type": "Gemini 原生 SDK",
                "api_key": "sk-aihubmix",
                "api_base": "https://aihubmix.com/gemini",
            },
            config_records=[
                {"fields": {"AI供应商": "AIHubMix", "API 代理地址": "https://aihubmix.com/gemini", "API Key": "sk-aihubmix"}},
            ],
        )

        self.assertEqual(route.provider, "Aitgenne")
        self.assertEqual(route.api_key, "")
        with self.assertRaisesRegex(ValueError, "缺少 API Key"):
            ai_routing.call_text_model(route, "hello", post=Mock())

    def test_route_from_slot_uses_task_model_and_params_over_defaults(self):
        route = ai_routing.route_from_slot(
            {
                "生图AI模型": "OTU / gpt-image-2-2K",
                "生图AI参数JSON": '{"size":"1080x1920"}',
            },
            "生图",
            {
                "provider": "OTU",
                "model": "OTU / gpt-image-2",
                "api_key": "sk-image",
                "api_base": "https://otuapi.com",
                "params": {"size": "720x1280", "aspect_ratio": "9:16"},
            },
            capability="图片",
            task_type="首帧图生图",
        )

        self.assertEqual(route.provider, "OTU")
        self.assertEqual(route.model, "OTU / gpt-image-2-2K")
        self.assertEqual(route.capability, "图片")
        self.assertEqual(route.task_type, "首帧图生图")
        self.assertEqual(route.params["size"], "1080x1920")
        self.assertEqual(route.params["aspect_ratio"], "9:16")

    def test_route_from_slot_falls_back_to_legacy_ai_model(self):
        route = ai_routing.route_from_slot(
            {
                "AI模型": "Aitgenne / gpt-5.5",
                "AI参数JSON": '{"temperature":0.2}',
            },
            "拆分",
            {"api_key": "sk-text", "api_base": "https://api.aitgenne.com"},
            capability="文本",
            task_type="脚本解析拆分",
        )

        self.assertEqual(route.provider, "Aitgenne")
        self.assertEqual(route.model, "Aitgenne / gpt-5.5")
        self.assertEqual(route.params["temperature"], 0.2)

    def test_text_openai_compatible_call_redacts_key_from_summary(self):
        response = Mock(status_code=200)
        response.json.return_value = {"choices": [{"message": {"content": "OK JSON"}}]}
        response.text = '{"choices":[]}'

        route = ai_routing.AiRoute(
            provider="Aitgenne",
            capability="文本",
            task_type="脚本生成",
            model="Aitgenne / gpt-5.5",
            call_type="OpenAI兼容 chat/completions",
            api_base="https://api.aitgenne.com",
            api_key="sk-secret-value",
        )

        with patch.object(ai_routing.requests, "post", return_value=response) as post:
            result = ai_routing.call_text_model(route, "hello")

        self.assertEqual(result.text, "OK JSON")
        self.assertEqual(post.call_args.args[0], "https://api.aitgenne.com/v1/chat/completions")
        self.assertEqual(post.call_args.kwargs["json"]["model"], "gpt-5.5")
        summary = ai_routing.build_dry_run_summary(route, "hello")
        self.assertNotIn("sk-secret-value", str(summary))

    def test_text_gemini_native_call_uses_generate_content(self):
        client = Mock()
        client.models.generate_content.return_value = Mock(text="{}")
        route = ai_routing.AiRoute(
            provider="AIHubMix",
            capability="文本",
            task_type="脚本解析拆分",
            model="AIHubMix / gemini-3.1-pro-preview",
            call_type="Gemini 原生 SDK",
            api_base="https://aihubmix.com/gemini",
            api_key="sk-text",
        )

        result = ai_routing.call_text_model(route, "parse this", gemini_client_factory=Mock(return_value=client))

        self.assertEqual(result.text, "{}")
        client.models.generate_content.assert_called_once_with(model="gemini-3.1-pro-preview", contents=["parse this"])

    def test_otu_image_request_summary_uses_videos_endpoint(self):
        route = ai_routing.AiRoute(
            provider="OTU",
            capability="图片",
            task_type="图生图/参考图重绘",
            model="OTU / gpt-image-2",
            api_base="https://otuapi.com",
            api_key="sk-img",
            params={"size": "1024x1024", "aspect_ratio": "9:16"},
        )

        summary = ai_routing.build_media_request_summary(route, "image prompt", reference_count=2)

        self.assertEqual(summary["endpoint"], "https://otuapi.com/v1/videos")
        self.assertEqual(summary["payload"]["model"], "gpt-image-2")
        self.assertEqual(summary["payload"]["size"], "1024x1024")
        self.assertEqual(summary["payload"]["metadata"]["aspectRatio"], "9:16")
        self.assertNotIn("sk-img", str(summary))

    def test_aihubmix_video_request_summary_uses_videos_endpoint(self):
        route = ai_routing.AiRoute(
            provider="AIHubMix",
            capability="视频",
            task_type="首帧图生视频",
            model="AIHubMix / veo-3.1-fast-generate-preview",
            api_base="https://aihubmix.com",
            api_key="sk-video",
            params={"size": "720p", "seconds": "8", "aspect_ratio": "9:16"},
        )

        summary = ai_routing.build_media_request_summary(route, "video prompt", reference_count=1)

        self.assertEqual(summary["endpoint"], "https://aihubmix.com/v1/videos")
        self.assertEqual(summary["payload"]["model"], "veo-3.1-fast-generate-preview")
        self.assertEqual(summary["payload"]["seconds"], "8")
        self.assertEqual(summary["reference_count"], 1)


if __name__ == "__main__":
    unittest.main()
