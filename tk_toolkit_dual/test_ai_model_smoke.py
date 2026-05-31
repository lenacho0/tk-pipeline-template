import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ai_model_smoke


class AiModelSmokeTests(unittest.TestCase):
    def test_all_enabled_media_queue_contains_every_image_and_video_model(self):
        queue = ai_model_smoke.build_smoke_queue(all_enabled_media=True)
        names = [entry.display_name for entry in queue]

        self.assertEqual(14, len(names))
        self.assertEqual([
            "OTU / gpt-image-2",
            "OTU / gpt-image-2-2K",
            "OTU / gpt-image-2-4K",
        ], names[:3])
        self.assertIn("OTU / omni_flash-10s", names)
        self.assertIn("OTU / veo_3_1-hd-fl", names)
        self.assertIn("AIHubMix / veo-3.1-fast-generate-preview", names)
        self.assertNotIn("AIHubMix / seeddance2.0", names)
        self.assertIn("Aitgenne / happyhorse-1.0-i2v", names)
        self.assertIn("Aitgenne / happyhorse-1.0-r2v", names)
        self.assertIn("Aitgenne / omni-flash", names)

    def test_smoke_queue_excludes_non_enabled_media_models(self):
        queue_text = json.dumps([entry.display_name for entry in ai_model_smoke.build_smoke_queue(all_enabled_media=True)], ensure_ascii=False)

        self.assertNotIn("Aitgenne / happyhorse-1.0-video-edit", queue_text)
        self.assertNotIn("Aitgenne / happyhorse-1.0-t2v", queue_text)
        self.assertNotIn("Aitgenne / veo-3.1-fast", queue_text)
        self.assertNotIn("AIHubMix / gpt-image-2", queue_text)
        self.assertNotIn("AIHubMix / seeddance2.0", queue_text)
        self.assertNotIn("AIHubMix / sora-2-pro", queue_text)

    def test_explicit_smoke_rejects_candidate_and_discard_models(self):
        with self.assertRaisesRegex(ValueError, "不允许真实 smoke"):
            ai_model_smoke.build_smoke_queue(model_names=["Aitgenne / happyhorse-1.0-video-edit"])

        with self.assertRaisesRegex(ValueError, "不允许真实 smoke"):
            ai_model_smoke.build_smoke_queue(model_names=["Aitgenne / happyhorse-1.0-t2v"])

        with self.assertRaisesRegex(ValueError, "不允许真实 smoke"):
            ai_model_smoke.build_smoke_queue(model_names=["AIHubMix / seeddance2.0"])

    def test_report_redacts_sensitive_values(self):
        report = ai_model_smoke.render_smoke_report([
            {
                "display_name": "OTU / gpt-image-2",
                "status": "failed",
                "capability": "图片",
                "endpoint": "https://otuapi.com/v1/videos",
                "payload_keys": ["model", "prompt"],
                "size": "720x1280",
                "aspect_ratio": "9:16",
                "seconds": "",
                "reference_count": 1,
                "task_id": "",
                "result_url": "",
                "error_type": "endpoint_error",
                "error": "HTTP 401 Authorization: Bearer sk-secret token=abc",
            }
        ])

        self.assertIn("OTU / gpt-image-2", report)
        self.assertIn("[REDACTED]", report)
        self.assertNotIn("sk-secret", report)
        self.assertNotIn("token=abc", report)
        self.assertNotIn("Authorization", report)
        self.assertNotIn("Bearer", report)

    def test_non_fl_otu_veo_profiles_use_landscape_reference_mode(self):
        profiles = {
            entry.display_name: ai_model_smoke.smoke_profile_for_entry(entry)
            for entry in ai_model_smoke.build_smoke_queue(model_names=["OTU / veo_3_1", "OTU / veo_3_1-hd"])
        }

        for profile in profiles.values():
            self.assertEqual("landscape_i2v", profile.name)
            self.assertEqual("1280x720", profile.size)
            self.assertEqual("16:9", profile.aspect_ratio)
            self.assertEqual("landscape", profile.reference_orientation)
            self.assertEqual(1, profile.reference_count)

    def test_fl_otu_veo_profiles_keep_vertical_reference_mode(self):
        profiles = {
            entry.display_name: ai_model_smoke.smoke_profile_for_entry(entry)
            for entry in ai_model_smoke.build_smoke_queue(model_names=[
                "OTU / veo_3_1-fast-fl",
                "OTU / veo_3_1-fl",
                "OTU / veo_3_1-hd-fl",
            ])
        }

        for profile in profiles.values():
            self.assertEqual("vertical_i2v", profile.name)
            self.assertEqual("720x1280", profile.size)
            self.assertEqual("9:16", profile.aspect_ratio)
            self.assertEqual("vertical", profile.reference_orientation)

    def test_report_includes_smoke_profile_name(self):
        report = ai_model_smoke.render_smoke_report([
            {
                "display_name": "OTU / veo_3_1",
                "profile": "landscape_i2v",
                "status": "ok",
                "capability": "视频",
                "endpoint": "https://otuapi.com/v1/videos",
                "payload_keys": ["model", "prompt"],
                "size": "1280x720",
                "aspect_ratio": "16:9",
                "seconds": "8",
                "reference_count": 1,
                "task_id": "task_1",
                "result_url": "",
                "error_type": "",
                "error": "",
            }
        ])

        self.assertIn("profile: `landscape_i2v`", report)

    def test_seeddance_no_valid_channel_error_marks_candidate_downgrade(self):
        result = {
            "display_name": "AIHubMix / seeddance2.0",
            "status": "failed",
            "error": "HTTP 500: no_valid_channel_error",
        }

        self.assertTrue(ai_model_smoke.should_downgrade_seeddance(result))

    def test_submit_smoke_task_uses_landscape_profile_for_non_fl_otu_veo(self):
        entry = ai_model_smoke.build_smoke_queue(model_names=["OTU / veo_3_1"])[0]
        reference_paths = ai_model_smoke.ensure_reference_images(Path("/tmp/tk_ai_model_smoke_test_profiles"))
        captured = {}

        def fake_post(url, **kwargs):
            captured["url"] = url
            captured["data"] = kwargs.get("data")
            return SimpleNamespace(status_code=200, json=lambda: {"task_id": "task_landscape", "status": "queued"})

        result = ai_model_smoke.submit_smoke_task(
            entry,
            {"api_key": "sk-test", "api_base": "https://otuapi.com", "model": "veo_3_1"},
            reference_paths,
            post=fake_post,
        )

        self.assertEqual("task_landscape", result["task_id"])
        self.assertEqual("1280x720", captured["data"]["size"])
        self.assertEqual("16:9", captured["data"]["aspect_ratio"])


if __name__ == "__main__":
    unittest.main()
