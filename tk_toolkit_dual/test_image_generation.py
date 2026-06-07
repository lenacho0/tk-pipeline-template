import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ai_routing
import image_generation


class ImageGenerationTests(unittest.TestCase):
    def test_run_image_generation_adapts_otu_metadata_from_media_spec(self):
        submitter = Mock(return_value=("task_1", {"id": "task_1"}))
        poller = Mock(return_value={"result_url": "https://x.test/out.png"})
        downloader = Mock()
        route = ai_routing.AiRoute(
            provider="OTU",
            capability="图片",
            task_type="图生图/参考图重绘",
            model="OTU / gpt-image-2",
            call_type="OTU /v1/videos",
            api_base="https://otuapi.com",
            api_key="sk-test",
            params={"size": "1280x720", "aspect_ratio": "16:9"},
        )

        result = image_generation.run_image_generation(
            route,
            "Render from reference.",
            "/tmp/out.png",
            input_mode="image-to-image",
            metadata={"reference_roles": ["product:1"]},
            size="1280x720",
            aspect_ratio="16:9",
            otu_submitter=submitter,
            otu_poller=poller,
            otu_downloader=downloader,
        )

        self.assertEqual(result.provider, "OTU")
        self.assertEqual(result.request_summary["size"], "1280x720")
        self.assertEqual(result.request_summary["aspect_ratio"], "16:9")
        self.assertEqual(result.request_summary["adapter_payload_summary"]["aspect_ratio"], "payload.metadata.aspectRatio")
        self.assertEqual(submitter.call_args.kwargs["size"], "1280x720")
        self.assertEqual(submitter.call_args.kwargs["aspect_ratio"], "16:9")
        self.assertEqual(submitter.call_args.kwargs["metadata"]["aspectRatio"], "16:9")
        self.assertEqual(submitter.call_args.kwargs["metadata"]["aspect_ratio"], "16:9")
        self.assertEqual(submitter.call_args.kwargs["metadata"]["size"], "1280x720")
        self.assertEqual(submitter.call_args.kwargs["metadata"]["reference_roles"], ["product:1"])

    def test_run_image_generation_uses_otu_2k_model_size_over_stale_record_size(self):
        submitter = Mock(return_value=("task_2k", {"id": "task_2k"}))
        poller = Mock(return_value={"result_url": "https://x.test/out.png"})
        downloader = Mock()
        route = ai_routing.AiRoute(
            provider="OTU",
            capability="图片",
            task_type="文生图",
            model="OTU / gpt-image-2-2K",
            call_type="OTU /v1/videos",
            api_base="https://otuapi.com",
            api_key="sk-test",
            params={"size": "720x1280", "aspect_ratio": "9:16"},
        )

        result = image_generation.run_image_generation(
            route,
            "Render a reference image.",
            "/tmp/out.png",
            input_mode="text-to-image",
            metadata={"reference_roles": []},
            size="720x1280",
            aspect_ratio="9:16",
            otu_submitter=submitter,
            otu_poller=poller,
            otu_downloader=downloader,
        )

        self.assertEqual(result.request_summary["model"], "gpt-image-2-2K")
        self.assertEqual(result.request_summary["size"], "1080x1920")
        self.assertEqual(result.request_summary["aspect_ratio"], "9:16")
        self.assertEqual(submitter.call_args.args[0]["model"], "gpt-image-2-2K")
        self.assertEqual(submitter.call_args.kwargs["size"], "1080x1920")
        self.assertEqual(submitter.call_args.kwargs["aspect_ratio"], "9:16")
        self.assertEqual(submitter.call_args.kwargs["metadata"]["size"], "1080x1920")

    def test_run_image_generation_uses_reference_count_override_for_contact_sheet(self):
        submitter = Mock(return_value=("task_contact", {"id": "task_contact"}))
        poller = Mock(return_value={"result_url": "https://x.test/out.png"})
        downloader = Mock()
        route = ai_routing.AiRoute(
            provider="OTU",
            capability="图片",
            task_type="图生图/参考图重绘",
            model="OTU / gpt-image-2",
            call_type="OTU /v1/videos",
            api_base="https://otuapi.com",
            api_key="sk-test",
            params={"size": "720x1280", "aspect_ratio": "9:16"},
        )

        result = image_generation.run_image_generation(
            route,
            "Render from a contact sheet.",
            "/tmp/out.png",
            input_mode="image-to-image",
            image_path="/tmp/reference_contact_sheet.png",
            reference_image_paths=None,
            reference_count_override=3,
            metadata={"reference_roles": ["product_table:1", "model_table:1", "uploaded_reference:1"]},
            size="720x1280",
            aspect_ratio="9:16",
            otu_submitter=submitter,
            otu_poller=poller,
            otu_downloader=downloader,
        )

        self.assertEqual(result.request_summary["reference_count"], 3)
        self.assertEqual(submitter.call_args.kwargs["image_path"], "/tmp/reference_contact_sheet.png")
        self.assertIsNone(submitter.call_args.kwargs["reference_image_paths"])

    def test_run_image_generation_reports_otu_submitted_reference_cap(self):
        submitter = Mock(return_value=("task_refs", {"id": "task_refs"}))
        poller = Mock(return_value={"result_url": "https://x.test/out.png"})
        downloader = Mock()
        route = ai_routing.AiRoute(
            provider="OTU",
            capability="图片",
            task_type="图生图/参考图重绘",
            model="OTU / gpt-image-2",
            call_type="OTU /v1/videos",
            api_base="https://otuapi.com",
            api_key="sk-test",
            params={"size": "720x1280", "aspect_ratio": "9:16"},
        )

        result = image_generation.run_image_generation(
            route,
            "Render from many references.",
            "/tmp/out.png",
            input_mode="image-to-image",
            image_path="/tmp/primary.png",
            reference_image_paths=[f"/tmp/ref_{idx}.png" for idx in range(6)],
            reference_count_override=7,
            metadata={"reference_roles": ["primary", "product_table:1", "model_table:1", "uploaded_reference:1"]},
            size="720x1280",
            aspect_ratio="9:16",
            otu_submitter=submitter,
            otu_poller=poller,
            otu_downloader=downloader,
        )

        self.assertEqual(result.request_summary["reference_count"], 7)
        self.assertEqual(result.request_summary["submitted_reference_count"], 5)
        self.assertEqual(result.request_summary["dropped_reference_count"], 2)

    def test_run_image_generation_uses_aitgenne_image_to_image(self):
        submitter = Mock(return_value={"data": [{"url": "https://x.test/out.png"}]})
        saver = Mock()
        route = ai_routing.AiRoute(
            provider="Aitgenne",
            capability="图片",
            task_type="图生图/参考图重绘",
            model="Aitgenne / gpt-image-2",
            call_type="OpenAI兼容 /v1/images/generations",
            api_base="https://api.aitgenne.com",
            api_key="sk-test",
            params={"size": "720x1280", "aspect_ratio": "9:16"},
        )
        with tempfile.TemporaryDirectory() as tmp:
            ref_path = Path(tmp) / "ref.png"
            ref_path.write_bytes(b"ref")
            out_path = Path(tmp) / "out.png"

            result = image_generation.run_image_generation(
                route,
                "Render from reference.",
                str(out_path),
                input_mode="image-to-image",
                image_path=str(ref_path),
                metadata={"reference_roles": ["product:1"]},
                size="720x1280",
                aspect_ratio="9:16",
                aitgenne_submitter=submitter,
                aitgenne_saver=saver,
            )

        self.assertEqual(result.provider, "Aitgenne")
        self.assertEqual(result.task_id, "")
        self.assertEqual(result.request_summary["size"], "720x1280")
        self.assertEqual(result.request_summary["aspect_ratio"], "9:16")
        self.assertEqual(submitter.call_args.args[0]["model"], "gpt-image-2")
        self.assertEqual(submitter.call_args.args[1], "Render from reference.")
        self.assertEqual(submitter.call_args.kwargs["input_mode"], "image-to-image")
        self.assertEqual(submitter.call_args.kwargs["image_path"], str(ref_path))
        self.assertEqual(submitter.call_args.kwargs["metadata"]["reference_roles"], ["product:1"])
        self.assertEqual(submitter.call_args.kwargs["metadata"]["aspectRatio"], "9:16")
        self.assertEqual(submitter.call_args.kwargs["metadata"]["aspect_ratio"], "9:16")
        self.assertEqual(submitter.call_args.kwargs["metadata"]["size"], "720x1280")
        saver.assert_called_once()

    def test_run_image_generation_retries_aitgenne_rate_limit_before_saving(self):
        submitter = Mock(side_effect=[
            RuntimeError("Aitgenne 图片编辑提交失败: HTTP 429, body={'error': {'message': '当前分组上游负载已饱和，请稍后再试'}}"),
            RuntimeError("Aitgenne 图片编辑提交失败: HTTP 429, body={'error': {'message': '当前分组上游负载已饱和，请稍后再试'}}"),
            {"data": [{"url": "https://x.test/out.png"}]},
        ])
        saver = Mock()
        route = ai_routing.AiRoute(
            provider="Aitgenne",
            capability="图片",
            task_type="图生图/参考图重绘",
            model="Aitgenne / gpt-image-2",
            call_type="OpenAI兼容 /v1/images/generations",
            api_base="https://api.aitgenne.com",
            api_key="sk-test",
            params={"size": "720x1280", "aspect_ratio": "9:16"},
        )

        with tempfile.TemporaryDirectory() as tmp, patch("time.sleep") as sleep:
            out_path = Path(tmp) / "out.png"
            result = image_generation.run_image_generation(
                route,
                "Render from references.",
                str(out_path),
                input_mode="image-to-image",
                reference_image_paths=[str(Path(tmp) / "ref.png")],
                metadata={"reference_roles": ["product:1"]},
                size="720x1280",
                aspect_ratio="9:16",
                aitgenne_submitter=submitter,
                aitgenne_saver=saver,
            )

        self.assertEqual(result.provider, "Aitgenne")
        self.assertEqual(result.result_body, {"data": [{"url": "https://x.test/out.png"}]})
        self.assertEqual(submitter.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [8, 16])
        saver.assert_called_once_with({"data": [{"url": "https://x.test/out.png"}]}, str(out_path))


if __name__ == "__main__":
    unittest.main()
