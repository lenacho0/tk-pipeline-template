import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import tk_create_first_last_video_table as first_last_table
import ai_model_catalog
import tk_create_multi_role_first_last_table as multi_role_table
import tk_create_nine_grid_video_table as nine_grid_table
import tk_create_prompt_image_video_table as prompt_image_video_table
import tk_create_script_doc_shots_table as script_doc_tables
import tk_create_storyboard_video_table as storyboard_table


def field_options(fields, field_name):
    by_name = {field["name"]: field for field in fields}
    return [item["name"] for item in by_name[field_name]["options"]]


class AiModelCatalogTableOptionsTests(unittest.TestCase):
    def test_text_model_fields_use_unified_name(self):
        expected = [entry.display_name for entry in ai_model_catalog.production_models("文本")]
        table_fields = [
            (first_last_table.FIRST_LAST_VIDEO_FIELDS, "拆分AI模型"),
            (multi_role_table.MULTI_ROLE_FIRST_LAST_FIELDS, "拆解AI模型"),
            (nine_grid_table.NINE_GRID_VIDEO_FIELDS, "方案AI模型"),
            (script_doc_tables.TASK_FIELDS, "解析AI模型"),
            (script_doc_tables.UNIFIED_TABLE_DEFINITION["fields"], "解析AI模型"),
        ]

        for fields, old_name in table_fields:
            self.assertEqual(field_options(fields, "文本AI模型"), expected)
            with self.assertRaises(KeyError):
                field_options(fields, old_name)

    def test_script_doc_video_model_options_come_from_catalog(self):
        options = field_options(script_doc_tables.SHOT_FIELDS, "视频生成模型")
        task_options = field_options(script_doc_tables.TASK_FIELDS, "视频生成模型")

        self.assertIn("OTU / veo_3_1-fast-fl-hd", options)
        self.assertIn("Aitgenne / happyhorse-1.0-i2v", options)
        self.assertIn("Aitgenne / veo_3_1_lite_vip", options)
        self.assertIn("Aitgenne / veo_3_1_fast_vip", options)
        self.assertIn("Aitgenne / veo_3_1_vip", options)
        self.assertEqual(task_options, options)
        self.assertIn("AIHubMix / veo-3.1-fast-generate-preview", options)
        self.assertNotIn("OTU / omni_flash-10s", options)
        self.assertNotIn("Aitgenne / happyhorse-1.0-r2v", options)
        self.assertNotIn("Aitgenne / veo_3_1_components_vip", options)
        self.assertNotIn("Aitgenne / happyhorse-1.0-video-edit", options)
        self.assertNotIn("AIHubMix / seeddance2.0", options)
        self.assertNotIn("AIHubMix / sora-2-pro", options)

    def test_first_last_video_model_options_come_from_catalog(self):
        options = field_options(first_last_table.FIRST_LAST_VIDEO_FIELDS, "视频生成模型")

        self.assertIn("OTU / veo_3_1-fast-fl-hd", options)
        self.assertIn("AIHubMix / veo-3.1-fast-generate-preview", options)
        self.assertIn("Aitgenne / happyhorse-1.0-i2v", options)
        self.assertIn("Aitgenne / veo_3_1_lite_vip", options)
        self.assertIn("Aitgenne / veo_3_1_fast_vip", options)
        self.assertIn("Aitgenne / veo_3_1_vip", options)
        self.assertNotIn("Aitgenne / veo_3_1_components_vip", options)
        self.assertNotIn("Aitgenne / happyhorse-1.0-video-edit", options)
        self.assertNotIn("OTU / omni_flash-10s", options)
        self.assertNotIn("OTU / sora-2-12s", options)
        image_options = field_options(first_last_table.FIRST_LAST_VIDEO_FIELDS, "首帧图AI模型")
        self.assertIn("OTU / gpt-image-2-4K", image_options)
        self.assertIn("Aitgenne / gpt-image-2", image_options)
        self.assertNotIn("AIHubMix / gpt-image-2", image_options)

    def test_prompt_image_video_model_options_include_omni_without_changing_first_last(self):
        prompt_options = field_options(prompt_image_video_table.PROMPT_IMAGE_VIDEO_FIELDS, "视频生成模型")
        first_last_options = field_options(first_last_table.FIRST_LAST_VIDEO_FIELDS, "视频生成模型")

        self.assertIn("OTU / omni_flash-10s", prompt_options)
        self.assertIn("OTU / veo_3_1-fast-fl-hd", prompt_options)
        self.assertIn("Aitgenne / happyhorse-1.0-i2v", prompt_options)
        self.assertIn("Aitgenne / veo_3_1_lite_vip", prompt_options)
        self.assertIn("Aitgenne / veo_3_1_fast_vip", prompt_options)
        self.assertIn("Aitgenne / veo_3_1_vip", prompt_options)
        self.assertIn("Aitgenne / veo_3_1_components_vip", prompt_options)
        self.assertNotIn("OTU / omni_flash-10s", first_last_options)

    def test_storyboard_video_options_include_regular_vip_but_not_components(self):
        storyboard_options = field_options(storyboard_table.STORYBOARD_VIDEO_FIELDS, "视频生成模型")

        self.assertIn("OTU / omni_flash-10s", storyboard_options)
        self.assertIn("Aitgenne / veo_3_1_lite_vip", storyboard_options)
        self.assertIn("Aitgenne / veo_3_1_fast_vip", storyboard_options)
        self.assertIn("Aitgenne / veo_3_1_vip", storyboard_options)
        self.assertNotIn("Aitgenne / veo_3_1_components_vip", storyboard_options)

    def test_multi_role_ai_and_video_model_options_come_from_catalog(self):
        video_options = field_options(multi_role_table.MULTI_ROLE_FIRST_LAST_FIELDS, "视频生成模型")

        self.assertIn("OTU / veo_3_1-fast-fl-hd", video_options)
        self.assertIn("Aitgenne / happyhorse-1.0-i2v", video_options)
        self.assertIn("Aitgenne / veo_3_1_lite_vip", video_options)
        self.assertIn("Aitgenne / veo_3_1_fast_vip", video_options)
        self.assertIn("Aitgenne / veo_3_1_vip", video_options)
        self.assertNotIn("Aitgenne / happyhorse-1.0-r2v", video_options)
        self.assertNotIn("Aitgenne / veo_3_1_components_vip", video_options)
        self.assertNotIn("Aitgenne / happyhorse-1.0-video-edit", video_options)

    def test_reference_video_tables_use_reference_video_model_options(self):
        nine_grid_generation_options = field_options(nine_grid_table.NINE_GRID_VIDEO_FIELDS, "视频生成模型")

        self.assertEqual(nine_grid_generation_options, ["默认（配置表）",
            "OTU / omni_flash-10s",
            "Aitgenne / happyhorse-1.0-r2v",
            "Aitgenne / omni-flash",
            "Aitgenne / veo_3_1_lite_vip",
            "Aitgenne / veo_3_1_fast_vip",
            "Aitgenne / veo_3_1_vip",
            "Aitgenne / veo_3_1_components_vip",
        ])
        self.assertNotIn("Aitgenne / happyhorse-1.0-i2v", nine_grid_generation_options)
        self.assertNotIn("Aitgenne / happyhorse-1.0-video-edit", nine_grid_generation_options)
        self.assertNotIn("OTU / veo_3_1-fast-fl", nine_grid_generation_options)

    def test_nine_grid_image_dimension_options_include_landscape(self):
        for size_field in ("参考图画面尺寸", "图片画面尺寸"):
            self.assertIn("1280x720", field_options(nine_grid_table.NINE_GRID_VIDEO_FIELDS, size_field))
        for ratio_field in ("参考图画面比例", "图片画面比例"):
            self.assertIn("16:9", field_options(nine_grid_table.NINE_GRID_VIDEO_FIELDS, ratio_field))

        self.assertIn("1280x720", field_options(nine_grid_table.NINE_GRID_VIDEO_FIELDS, "视频画面尺寸"))
        self.assertIn("16:9", field_options(nine_grid_table.NINE_GRID_VIDEO_FIELDS, "视频画面比例"))


if __name__ == "__main__":
    unittest.main()
