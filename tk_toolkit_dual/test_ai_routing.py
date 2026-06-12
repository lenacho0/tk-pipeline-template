import os
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ai_routing
import ai_model_catalog
import common
from common import extract_text


class UnifiedAiRoutingTests(unittest.TestCase):
    def test_aitgenne_request_disables_environment_proxy(self):
        class FakeSession:
            instances = []

            def __init__(self):
                self.trust_env = True
                self.request_args = None
                FakeSession.instances.append(self)

            def request(self, *args, **kwargs):
                self.request_args = (args, kwargs)
                response = Mock()
                response.status_code = 200
                return response

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def close(self):
                pass

        with patch.dict(os.environ, {
            "HTTPS_PROXY": "http://127.0.0.1:10808",
            "HTTP_PROXY": "http://127.0.0.1:10808",
            "ALL_PROXY": "socks5://127.0.0.1:10808",
        }), patch.object(common.requests, "Session", FakeSession):
            response = common.aitgenne_request("GET", "https://api.aitgenne.com/v1/video/query?id=task_1", timeout=45)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(FakeSession.instances), 1)
        session = FakeSession.instances[0]
        self.assertFalse(session.trust_env)
        self.assertEqual(session.request_args[0][0], "GET")

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

    def test_route_switch_all_mode_ignores_hidden_record_field(self):
        records = [{"fields": {"环节": "统一AI路由启用状态", "状态": "启用", "模型名称": "全量启用"}}]

        self.assertTrue(ai_routing.unified_route_enabled({}, records))
        self.assertTrue(ai_routing.unified_route_enabled({"使用统一AI路由": ""}, records))
        self.assertTrue(ai_routing.unified_route_enabled({"使用统一AI路由": "否"}, records))

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
        self.assertEqual(route.api_base, "https://api.aitgenne.com")
        self.assertEqual(route.api_key, "sk-aitgenne")
        self.assertEqual(ai_routing.build_dry_run_summary(route, "hello")["endpoint"], "https://api.aitgenne.com/v1/chat/completions")

    def test_unified_text_model_field_uses_exact_aitgenne_key(self):
        route = ai_routing.route_from_slot(
            {
                "AI供应商": "AIHubMix",
                "文本AI模型": "Aitgenne / gemini-3.5-flash",
            },
            "拆解",
            {
                "provider": "AIHubMix",
                "model": "AIHubMix / gemini-3.1-pro-preview",
                "call_type": "Gemini 原生 SDK",
                "api_key": "sk-aihubmix",
                "api_base": "https://aihubmix.com/gemini",
            },
            capability="文本",
            task_type="多角色首尾帧解析",
            config_records=[
                {"fields": {"供应商": "Aitgenne", "模型名称": "Aitgenne / claude-opus-4-8", "API 代理地址": "https://api.aitgenne.com/v1", "API Key": "sk-claude"}},
                {"fields": {"供应商": "Aitgenne", "模型名称": "Aitgenne / gemini-3.5-flash", "API 代理地址": "https://api.aitgenne.com/v1", "API Key": "sk-flash"}},
                {"fields": {"供应商": "Aitgenne", "API 代理地址": "https://api.aitgenne.com/v1", "API Key": "sk-generic"}},
            ],
        )

        self.assertEqual(route.provider, "Aitgenne")
        self.assertEqual(route.model, "Aitgenne / gemini-3.5-flash")
        self.assertEqual(route.call_type, "OpenAI兼容 chat/completions")
        self.assertEqual(route.api_key, "sk-flash")
        self.assertEqual(route.api_base, "https://api.aitgenne.com/v1")

    def test_explicit_model_refreshes_stale_api_base_even_when_config_provider_matches(self):
        route = ai_routing.route_from_record(
            {
                "AI能力类型": "文本",
                "AI任务类型": "脚本解析拆分",
                "AI模型": "AIHubMix / gemini-3.1-pro-preview",
            },
            {
                "provider": "AIHubMix",
                "model": "Aitgenne / gpt-5.5",
                "call_type": "OpenAI兼容 chat/completions",
                "api_key": "sk-aitgenne",
                "api_base": "https://api.aitgenne.com/v1",
            },
            config_records=[
                {"fields": {"供应商": "AIHubMix", "API 代理地址": "https://aihubmix.com/gemini", "API Key": "sk-aihubmix"}},
                {"fields": {"供应商": "Aitgenne", "API 代理地址": "https://api.aitgenne.com/v1", "API Key": "sk-aitgenne"}},
            ],
        )

        self.assertEqual(route.provider, "AIHubMix")
        self.assertEqual(route.call_type, "Gemini 原生 SDK")
        self.assertEqual(route.api_base, "https://aihubmix.com/gemini")
        self.assertEqual(route.api_key, "sk-aihubmix")
        self.assertEqual(ai_routing.build_dry_run_summary(route, "hello")["endpoint"], "https://aihubmix.com/gemini")

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

    def test_explicit_same_provider_catalog_model_reuses_provider_key(self):
        route = ai_routing.route_from_record(
            {
                "AI能力类型": "视频",
                "AI任务类型": "首帧图生视频",
                "AI模型": "OTU / veo_3_1-fast-fl-hd",
            },
            {
                "provider": "OTU",
                "model": "veo_3_1-fast-fl-hd",
                "api_key": "",
                "api_base": "",
            },
            config_records=[
                {"fields": {
                    "配置类型": "运行环节",
                    "供应商": "OTU",
                    "环节": "分镜视频生成-OTU",
                    "API 代理地址": "https://otuapi.com",
                    "API Key": "sk-otu",
                }},
            ],
        )

        self.assertEqual(route.provider, "OTU")
        self.assertEqual(route.model, "OTU / veo_3_1-fast-fl-hd")
        self.assertEqual(route.api_key, "sk-otu")
        self.assertEqual(route.api_base, "https://otuapi.com")

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
        self.assertEqual(summary["payload"]["metadata"]["aspect_ratio"], "9:16")
        self.assertEqual(summary["payload"]["metadata"]["size"], "1024x1024")
        self.assertEqual(summary["payload"]["metadata"]["urls"], ["<reference_url>", "<reference_url>"])
        self.assertEqual(summary["media_spec"]["size"], "1024x1024")
        self.assertEqual(summary["media_spec"]["aspect_ratio"], "9:16")
        self.assertEqual(summary["adapter_payload_summary"]["size"], "payload.size")
        self.assertEqual(summary["adapter_payload_summary"]["aspect_ratio"], "payload.metadata.aspectRatio")
        self.assertEqual(summary["ignored_fields"], [])
        self.assertNotIn("sk-img", str(summary))

    def test_aitgenne_image_request_summary_uses_openai_image_schema(self):
        route = ai_routing.AiRoute(
            provider="Aitgenne",
            capability="图片",
            task_type="文生图",
            model="Aitgenne / gpt-image-2",
            api_base="https://api.aitgenne.com/v1",
            api_key="sk-img",
            params={"size": "1024x1536", "aspect_ratio": "9:16", "quality": "high", "format": "webp"},
        )

        summary = ai_routing.build_media_request_summary(route, "image prompt", reference_count=0)

        self.assertEqual(summary["endpoint"], "https://api.aitgenne.com/v1/images/generations")
        self.assertEqual(summary["payload"], {
            "model": "gpt-image-2",
            "prompt": "image prompt",
            "n": 1,
            "size": "1024x1536",
            "quality": "high",
            "format": "webp",
        })
        self.assertEqual(summary["adapter_payload_summary"]["size"], "payload.size")
        self.assertEqual(summary["adapter_payload_summary"]["n"], "payload.n")
        self.assertNotIn("metadata", summary["payload"])
        self.assertNotIn("input_mode", summary["payload"])
        self.assertNotIn("sk-img", str(summary))

    def test_aitgenne_image_reference_summary_uses_edits_multipart_schema(self):
        route = ai_routing.AiRoute(
            provider="Aitgenne",
            capability="图片",
            task_type="图生图/参考图重绘",
            model="Aitgenne / gpt-image-2",
            api_base="https://api.aitgenne.com/v1",
            api_key="sk-img",
            params={"size": "1024x1536", "aspect_ratio": "9:16"},
        )

        summary = ai_routing.build_media_request_summary(route, "image prompt", reference_count=2)

        self.assertEqual(summary["endpoint"], "https://api.aitgenne.com/v1/images/edits")
        self.assertEqual(summary["content_type"], "multipart/form-data")
        self.assertEqual(summary["payload"], {
            "model": "gpt-image-2",
            "prompt": "image prompt",
            "n": 1,
            "size": "1024x1536",
            "image": ["<reference_file>", "<reference_file>"],
        })
        self.assertEqual(summary["adapter_payload_summary"]["image"], "multipart field image repeated")
        self.assertNotIn("metadata", summary["payload"])
        self.assertNotIn("input_mode", summary["payload"])

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
        self.assertEqual(summary["media_spec"]["size"], "720p")
        self.assertEqual(summary["media_spec"]["aspect_ratio"], "9:16")
        self.assertEqual(summary["media_spec"]["seconds"], "8")

    def test_aitgenne_happyhorse_media_endpoint_uses_alibailian_video_synthesis(self):
        route = ai_routing.AiRoute(
            provider="Aitgenne",
            capability="视频",
            task_type="参考图生视频",
            model="Aitgenne / happyhorse-1.0-r2v",
            api_base="https://api.aitgenne.com/v1",
            api_key="sk-video",
            params={"size": "720x1280", "seconds": "5", "aspect_ratio": "9:16"},
        )

        summary = ai_routing.build_media_request_summary(route, "video prompt", reference_count=2)

        self.assertEqual(
            ai_routing.media_endpoint(route),
            "https://api.aitgenne.com/alibailian/api/v1/services/aigc/video-generation/video-synthesis",
        )
        self.assertEqual(
            ai_routing.media_task_endpoint(route, "task-123"),
            "https://api.aitgenne.com/alibailian/api/v1/tasks/task-123",
        )
        self.assertEqual(summary["endpoint"], "https://api.aitgenne.com/alibailian/api/v1/services/aigc/video-generation/video-synthesis")
        self.assertEqual(summary["payload"], {
            "model": "happyhorse-1.0-r2v",
            "input": {
                "prompt": "video prompt",
                "media": [
                    {"type": "reference_image", "url": "<reference_url>"},
                    {"type": "reference_image", "url": "<reference_url>"},
                ],
            },
            "parameters": {"resolution": "720P", "ratio": "9:16", "duration": 5},
        })
        self.assertEqual(summary["adapter_payload_summary"]["input"], "payload.input")
        self.assertEqual(summary["adapter_payload_summary"]["parameters"], "payload.parameters")
        self.assertEqual(summary["reference_count"], 2)

    def test_aitgenne_unified_video_models_use_create_query_and_images_schema(self):
        for model in (
            "Aitgenne / veo_3_1_lite_vip",
            "Aitgenne / veo_3_1_fast_vip",
            "Aitgenne / veo_3_1_vip",
            "Aitgenne / veo_3_1_components_vip",
        ):
            with self.subTest(model=model):
                route = ai_routing.AiRoute(
                    provider="Aitgenne",
                    capability="视频",
                    task_type="参考图生视频",
                    model=model,
                    api_base="https://api.aitgenne.com/v1",
                    api_key="sk-video",
                    params={"aspect_ratio": "9:16", "enhance_prompt": True, "enable_upsample": True},
                )

                summary = ai_routing.build_media_request_summary(route, "video prompt", reference_count=3)

                self.assertEqual(ai_routing.media_endpoint(route), "https://api.aitgenne.com/v1/video/create")
                self.assertEqual(
                    ai_routing.media_task_endpoint(route, "job:123"),
                    "https://api.aitgenne.com/v1/video/query?id=job%3A123",
                )
                self.assertEqual(summary["endpoint"], "https://api.aitgenne.com/v1/video/create")
                self.assertEqual(summary["payload"], {
                    "model": ai_routing.parse_model_display(model)["model"],
                    "prompt": "video prompt",
                    "images": ["<reference_url>", "<reference_url>", "<reference_url>"],
                    "enhance_prompt": True,
                    "enable_upsample": True,
                    "aspect_ratio": "9:16",
                })
                self.assertEqual(summary["adapter_payload_summary"]["images"], "payload.images")
                self.assertNotIn("sk-video", str(summary))

    def test_aitgenne_unified_video_payload_uses_explicit_reference_urls(self):
        route = ai_routing.AiRoute(
            provider="Aitgenne",
            capability="视频",
            task_type="参考图生视频",
            model="Aitgenne / veo_3_1_components_vip",
            api_base="https://api.aitgenne.com/v1",
            api_key="sk-components",
        )

        payload = ai_routing.build_aitgenne_unified_video_payload(
            route,
            "video prompt",
            ["https://x.test/a.png", "https://x.test/b.png"],
            aspect_ratio="16:9",
        )

        self.assertEqual(payload, {
            "model": "veo_3_1_components_vip",
            "prompt": "video prompt",
            "images": ["https://x.test/a.png", "https://x.test/b.png"],
            "enhance_prompt": True,
            "enable_upsample": True,
            "aspect_ratio": "16:9",
        })

    def test_aitgenne_unified_video_extracts_detail_status_and_upsample_url(self):
        body = {
            "detail": {
                "status": "completed",
                "video_url": "https://x.test/plain.mp4",
                "upsample_video_url": "https://x.test/up.mp4",
            }
        }

        self.assertEqual(ai_routing.extract_video_status(body), "completed")
        self.assertEqual(ai_routing.extract_video_result_url(body), "https://x.test/up.mp4")

    def test_aitgenne_unified_video_exact_key_helper_does_not_fallback_to_provider_key(self):
        records = [
            {"fields": {
                "AI供应商": "Aitgenne",
                "模型名称": "Aitgenne / veo_3_1_lite_vip",
                "API 代理地址": "https://api.aitgenne.com/v1",
                "API Key": "sk-lite",
            }},
            {"fields": {
                "AI供应商": "Aitgenne",
                "模型名称": "Aitgenne / veo_3_1_fast_vip",
                "API 代理地址": "https://api.aitgenne.com/v1",
                "API Key": "",
            }},
            {"fields": {
                "AI供应商": "Aitgenne",
                "API 代理地址": "https://api.aitgenne.com/v1",
                "API Key": "sk-provider",
            }},
        ]

        lite = ai_routing.exact_model_runtime_config(records, "Aitgenne", "Aitgenne / veo_3_1_lite_vip")
        self.assertEqual(lite["api_key"], "sk-lite")
        with self.assertRaisesRegex(ValueError, "模型配置缺少 API Key: Aitgenne / veo_3_1_fast_vip"):
            ai_routing.exact_model_runtime_config(records, "Aitgenne", "Aitgenne / veo_3_1_fast_vip")

    def test_exact_model_config_prefers_callable_runtime_over_task_default(self):
        records = [
            {"fields": {
                "配置类型": "任务默认",
                "应用表格": "002-首尾帧视频生成表",
                "任务环节": "首尾帧视频生成默认",
                "供应商": "Aitgenne",
                "模型名称": "Aitgenne / veo_3_1_fast_vip",
                "API Key": "",
            }},
            {"fields": {
                "配置类型": "运行环节",
                "环节": "Aitgenne Fast VIP图生视频生成",
                "供应商": "Aitgenne",
                "模型名称": "Aitgenne / veo_3_1_fast_vip",
                "API 代理地址": "https://api.aitgenne.com/v1",
                "API Key": "sk-fast",
                "状态": "启用",
            }},
        ]

        cfg = ai_routing.exact_model_runtime_config(records, "Aitgenne", "Aitgenne / veo_3_1_fast_vip")

        self.assertEqual(cfg["api_key"], "sk-fast")
        self.assertEqual(cfg["api_base"], "https://api.aitgenne.com/v1")

    def test_exact_model_config_prefers_keyed_runtime_record_over_task_default(self):
        records = [
            {"fields": {
                "环节": "分镜视频生成-OTU",
                "配置类型": "任务默认",
                "供应商": "Aitgenne",
                "能力类型": "视频",
                "模型名称": "Aitgenne / veo_3_1_fast_vip",
                "API 代理地址": "",
                "API Key": "",
                "状态": "启用",
            }},
            {"fields": {
                "环节": "Aitgenne Fast VIP图生视频生成",
                "配置类型": "运行环节",
                "供应商": "Aitgenne",
                "能力类型": "视频",
                "模型名称": "Aitgenne / veo_3_1_fast_vip",
                "API 代理地址": "https://api.aitgenne.com/v1",
                "API Key": "sk-fast",
                "状态": "启用",
            }},
        ]

        fields = ai_routing.config_record_for_model(records, "Aitgenne", "Aitgenne / veo_3_1_fast_vip")
        self.assertEqual(fields["环节"], "Aitgenne Fast VIP图生视频生成")
        self.assertEqual(fields["配置类型"], "运行环节")

        cfg = ai_routing.exact_model_runtime_config(records, "Aitgenne", "Aitgenne / veo_3_1_fast_vip")
        self.assertEqual(cfg["api_key"], "sk-fast")
        self.assertEqual(cfg["api_base"], "https://api.aitgenne.com/v1")


if __name__ == "__main__":
    unittest.main()
