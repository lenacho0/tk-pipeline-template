import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import tk_create_first_last_video_table as first_last_table
import tk_create_multi_role_first_last_table as multi_role_table
import tk_create_script_doc_shots_table as script_doc_tables


def field_options(fields, field_name):
    by_name = {field["name"]: field for field in fields}
    return [item["name"] for item in by_name[field_name]["options"]]


class AiModelCatalogTableOptionsTests(unittest.TestCase):
    def test_script_doc_video_model_options_come_from_catalog(self):
        options = field_options(script_doc_tables.SHOT_FIELDS, "视频生成模型")

        self.assertIn("OTU / veo_3_1-fast-fl-hd", options)
        self.assertIn("AIHubMix / veo-3.1-fast-generate-preview", options)
        self.assertNotIn("AIHubMix / sora-2-pro", options)

    def test_first_last_video_model_options_come_from_catalog(self):
        options = field_options(first_last_table.FIRST_LAST_VIDEO_FIELDS, "视频生成模型")

        self.assertIn("OTU / veo_3_1-fast-fl-hd", options)
        self.assertIn("Aitgenne / happyhorse-1.0-i2v", options)
        self.assertNotIn("OTU / sora-2-12s", options)

    def test_multi_role_ai_and_video_model_options_come_from_catalog(self):
        ai_options = field_options(multi_role_table.MULTI_ROLE_FIRST_LAST_FIELDS, "AI模型")
        video_options = field_options(multi_role_table.MULTI_ROLE_FIRST_LAST_FIELDS, "视频生成模型")

        self.assertIn("Aitgenne / gpt-5.5", ai_options)
        self.assertIn("OTU / gpt-image-2-4K", ai_options)
        self.assertIn("OTU / veo_3_1-fast-fl-hd", video_options)
        self.assertNotIn("Aitgenne / gemini-3.1-pro-preview", ai_options)
        self.assertNotIn("OTU / nano_banana_pro-4K", ai_options)


if __name__ == "__main__":
    unittest.main()
