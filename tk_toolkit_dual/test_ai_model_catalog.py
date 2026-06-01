import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ai_model_catalog


class AiModelCatalogTests(unittest.TestCase):
    def test_enabled_options_are_filtered_by_capability(self):
        text_options = ai_model_catalog.select_options_for_capability("文本")
        image_options = ai_model_catalog.select_options_for_capability("图片")
        video_options = ai_model_catalog.select_options_for_capability("视频")

        self.assertIn("AIHubMix / gemini-3.1-pro-preview", [item["name"] for item in text_options])
        self.assertIn("OTU / gpt-image-2-4K", [item["name"] for item in image_options])
        self.assertIn("OTU / veo_3_1-fast-fl-hd", [item["name"] for item in video_options])
        self.assertNotIn("OTU / gpt-image-2", [item["name"] for item in text_options])
        self.assertNotIn("Aitgenne / gpt-5.5", [item["name"] for item in image_options])

    def test_candidate_and_discarded_models_are_not_production_options(self):
        all_option_names = [item["name"] for item in ai_model_catalog.production_model_options()]

        self.assertNotIn("Aitgenne / gemini-3.1-pro-preview", all_option_names)
        self.assertNotIn("Aitgenne / veo-3.1-fast", all_option_names)
        self.assertNotIn("OTU / nano_banana_pro-4K", all_option_names)
        self.assertNotIn("AIHubMix / sora-2-pro", all_option_names)
        self.assertNotIn("Aitgenne / kling-video", all_option_names)

    def test_lookup_requires_enabled_catalog_entry_by_default(self):
        enabled = ai_model_catalog.find_model("OTU", "图片", "gpt-image-2-2K")
        candidate = ai_model_catalog.find_model("Aitgenne", "文本", "gemini-3.1-pro-preview")

        self.assertEqual(enabled.display_name, "OTU / gpt-image-2-2K")
        self.assertIsNone(candidate)
        self.assertEqual(
            ai_model_catalog.find_model("Aitgenne", "文本", "gemini-3.1-pro-preview", include_candidate=True).status,
            "candidate",
        )

    def test_otu_image_resolution_is_encoded_in_model_id(self):
        models = [item.model for item in ai_model_catalog.models_for_capability("图片")]

        self.assertIn("gpt-image-2", models)
        self.assertIn("gpt-image-2-2K", models)
        self.assertIn("gpt-image-2-4K", models)

    def test_video_model_options_are_split_by_generation_mode(self):
        reference_names = [item["name"] for item in ai_model_catalog.REFERENCE_VIDEO_MODEL_OPTIONS]
        first_last_names = [item["name"] for item in ai_model_catalog.FIRST_LAST_VIDEO_MODEL_OPTIONS]
        first_last_with_default = [item["name"] for item in ai_model_catalog.FIRST_LAST_VIDEO_MODEL_WITH_DEFAULT_OPTIONS]

        self.assertEqual(reference_names, [
            "OTU / omni_flash-10s",
            "Aitgenne / happyhorse-1.0-r2v",
            "Aitgenne / omni-flash",
        ])
        self.assertEqual(first_last_names, [
            "AIHubMix / veo-3.1-fast-generate-preview",
            "OTU / veo_3_1-fast-fl",
            "OTU / veo_3_1-fast-fl-hd",
            "OTU / veo_3_1-fl",
            "OTU / veo_3_1-hd-fl",
        ])
        self.assertNotIn("Aitgenne / happyhorse-1.0-i2v", reference_names)
        self.assertNotIn("Aitgenne / happyhorse-1.0-r2v", first_last_names)
        self.assertEqual(first_last_with_default[0], "默认（配置表）")


if __name__ == "__main__":
    unittest.main()
