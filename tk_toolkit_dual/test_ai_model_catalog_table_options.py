import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import tk_create_first_last_video_table as first_last_table
import tk_create_multi_role_first_last_table as multi_role_table
import tk_create_nine_grid_video_table as nine_grid_table
import tk_create_prompt_image_video_table as prompt_image_video_table
import tk_create_script_doc_shots_table as script_doc_tables


def field_options(fields, field_name):
    by_name = {field["name"]: field for field in fields}
    return [item["name"] for item in by_name[field_name]["options"]]


class AiModelCatalogTableOptionsTests(unittest.TestCase):
    def test_script_doc_video_model_options_come_from_catalog(self):
        options = field_options(script_doc_tables.SHOT_FIELDS, "视频生成模型")
        task_options = field_options(script_doc_tables.TASK_FIELDS, "视频生成模型")

        self.assertIn("OTU / veo_3_1-fast-fl-hd", options)
        self.assertIn("Aitgenne / happyhorse-1.0-i2v", options)
        self.assertEqual(task_options, options)
        self.assertIn("AIHubMix / veo-3.1-fast-generate-preview", options)
        self.assertNotIn("OTU / omni_flash-10s", options)
        self.assertNotIn("Aitgenne / happyhorse-1.0-r2v", options)
        self.assertNotIn("Aitgenne / happyhorse-1.0-video-edit", options)
        self.assertNotIn("AIHubMix / seeddance2.0", options)
        self.assertNotIn("AIHubMix / sora-2-pro", options)

    def test_first_last_video_model_options_come_from_catalog(self):
        options = field_options(first_last_table.FIRST_LAST_VIDEO_FIELDS, "视频AI模型")

        self.assertIn("OTU / veo_3_1-fast-fl-hd", options)
        self.assertIn("AIHubMix / veo-3.1-fast-generate-preview", options)
        self.assertIn("Aitgenne / happyhorse-1.0-i2v", options)
        self.assertNotIn("Aitgenne / happyhorse-1.0-video-edit", options)
        self.assertNotIn("OTU / omni_flash-10s", options)
        self.assertNotIn("OTU / sora-2-12s", options)
        image_options = field_options(first_last_table.FIRST_LAST_VIDEO_FIELDS, "首帧图AI模型")
        self.assertIn("OTU / gpt-image-2-4K", image_options)
        self.assertIn("Aitgenne / gpt-image-2", image_options)
        self.assertNotIn("AIHubMix / gpt-image-2", image_options)

    def test_prompt_image_video_model_options_include_omni_without_changing_first_last(self):
        prompt_options = field_options(prompt_image_video_table.PROMPT_IMAGE_VIDEO_FIELDS, "视频AI模型")
        first_last_options = field_options(first_last_table.FIRST_LAST_VIDEO_FIELDS, "视频AI模型")

        self.assertIn("OTU / omni_flash-10s", prompt_options)
        self.assertIn("OTU / veo_3_1-fast-fl-hd", prompt_options)
        self.assertIn("Aitgenne / happyhorse-1.0-i2v", prompt_options)
        self.assertNotIn("OTU / omni_flash-10s", first_last_options)

    def test_multi_role_ai_and_video_model_options_come_from_catalog(self):
        ai_options = field_options(multi_role_table.MULTI_ROLE_FIRST_LAST_FIELDS, "AI模型")
        video_options = field_options(multi_role_table.MULTI_ROLE_FIRST_LAST_FIELDS, "视频生成模型")
        slot_video_options = field_options(multi_role_table.MULTI_ROLE_FIRST_LAST_FIELDS, "视频AI模型")

        self.assertIn("Aitgenne / gpt-5.5", ai_options)
        self.assertIn("OTU / gpt-image-2-4K", ai_options)
        self.assertIn("Aitgenne / gpt-image-2", ai_options)
        self.assertIn("OTU / veo_3_1-fast-fl-hd", video_options)
        self.assertIn("OTU / veo_3_1-fast-fl-hd", slot_video_options)
        self.assertIn("Aitgenne / happyhorse-1.0-i2v", video_options)
        self.assertNotIn("Aitgenne / happyhorse-1.0-r2v", video_options)
        self.assertNotIn("Aitgenne / happyhorse-1.0-video-edit", video_options)
        self.assertNotIn("OTU / omni_flash-10s", slot_video_options)
        self.assertNotIn("Aitgenne / gemini-3.1-pro-preview", ai_options)
        self.assertNotIn("OTU / nano_banana_pro-4K", ai_options)

    def test_reference_video_tables_use_reference_video_model_options(self):
        nine_grid_options = field_options(nine_grid_table.NINE_GRID_VIDEO_FIELDS, "视频AI模型")
        nine_grid_generation_options = field_options(nine_grid_table.NINE_GRID_VIDEO_FIELDS, "视频生成模型")

        self.assertEqual(nine_grid_options, [
            "OTU / omni_flash-10s",
            "Aitgenne / happyhorse-1.0-r2v",
            "Aitgenne / omni-flash",
        ])
        self.assertEqual(nine_grid_generation_options, ["默认（配置表）", *nine_grid_options])
        self.assertNotIn("Aitgenne / happyhorse-1.0-i2v", nine_grid_options)
        self.assertNotIn("Aitgenne / happyhorse-1.0-video-edit", nine_grid_options)
        self.assertNotIn("OTU / veo_3_1-fast-fl", nine_grid_options)


if __name__ == "__main__":
    unittest.main()
