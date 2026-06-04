import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import rebind_copied_base as rebind
from tools import release_safety_check as safety


class RebindCopiedBaseTests(unittest.TestCase):
    def test_rebind_config_data_uses_table_names_and_config_stage_names(self):
        config = {
            "feishu": {
                "tables": {
                    "config": "",
                    "product": "",
                    "model_appearance": "",
                    "script_doc_tasks": "",
                    "script_doc_reference_assets": "",
                    "script_doc_shots": "",
                    "storyboard_video": "",
                    "first_last_video": "",
                    "multi_role_first_last": "",
                    "nine_grid_video": "",
                    "video_edit": "",
                    "voice_library": "",
                    "text_audio": "",
                }
            },
            "config_records": {
                "script_doc_text_split": "",
                "storyboard_text_split": "",
                "main_image_otu": "",
            },
        }
        tables_by_name = {
            "初始化-模型与API配置": "tbl_config",
            "初始化-产品信息": "tbl_product",
            "初始化-模特形象": "tbl_model",
            "003-1脚本文档-任务表": "tbl_doc_tasks",
            "003-2脚本文档-参考资产表": "tbl_doc_assets",
            "003-3脚本文档-分镜生产表": "tbl_doc_shots",
            "004-故事板图片视频生成表": "tbl_storyboard",
            "002-首尾帧视频生成表": "tbl_first_last",
            "001-多角色首尾帧生成表": "tbl_multi_role",
            "005-多图九宫格视频生成表": "tbl_nine_grid",
            "006-视频编辑任务表": "tbl_video_edit",
            "初始化-音色库": "tbl_voice",
            "初始化-口播音频生成": "tbl_text_audio",
        }
        records_by_stage = {
            "脚本文档结构化拆分-Gemini": "rec_script_split",
            "故事板图片提示词拆分-Gemini": "rec_storyboard_split",
            "图片生成-OTU": "rec_image_otu",
        }

        result = rebind.rebind_config_data(config, tables_by_name, records_by_stage)

        self.assertTrue(result["ready"])
        self.assertEqual(result["config"]["feishu"]["tables"]["config"], "tbl_config")
        self.assertEqual(result["config"]["feishu"]["tables"]["script_doc_tasks"], "tbl_doc_tasks")
        self.assertEqual(result["config"]["feishu"]["tables"]["nine_grid_video"], "tbl_nine_grid")
        self.assertEqual(result["config"]["feishu"]["tables"]["video_edit"], "tbl_video_edit")
        self.assertEqual(result["config"]["config_records"]["main_image_otu"], "rec_image_otu")
        self.assertEqual(result["missing_tables"], [])
        self.assertEqual(result["missing_config_records"], [])

    def test_rebind_config_data_reports_missing_required_items(self):
        config = {"feishu": {"tables": {"config": ""}}, "config_records": {"main_image_otu": ""}}

        result = rebind.rebind_config_data(config, {}, {})

        self.assertFalse(result["ready"])
        self.assertIn("config", result["missing_tables"])
        self.assertIn("main_image_otu", result["missing_config_records"])


class ReleaseSafetyCheckTests(unittest.TestCase):
    def test_scan_files_flags_real_configs_absolute_paths_and_media(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tk_toolkit_dual").mkdir()
            (root / "docs").mkdir()
            (root / "tk_toolkit_dual" / "config.json").write_text("{}", encoding="utf-8")
            (root / "tk_toolkit_dual" / "config.json.template").write_text("{}", encoding="utf-8")
            local_path = "/Users/" + "ryanlynn/project"
            (root / "docs" / "ops.md").write_text(f"cd {local_path}", encoding="utf-8")
            (root / "clip.mp4").write_bytes(b"video")

            violations = safety.find_violations(
                root,
                [
                    "tk_toolkit_dual/config.json",
                    "tk_toolkit_dual/config.json.template",
                    "docs/ops.md",
                    "clip.mp4",
                ],
            )

        messages = "\n".join(item.message for item in violations)
        self.assertIn("tracked real config", messages)
        self.assertIn("hard-coded local path", messages)
        self.assertIn("tracked media artifact", messages)
        self.assertNotIn("config.json.template", messages)

    def test_scan_files_allows_placeholder_templates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tk_toolkit_dual").mkdir()
            template = root / "tk_toolkit_dual" / "config.json.template"
            template.write_text(
                json.dumps({"app_" + "secret": "在飞书开放平台创建应用后获取的 App Secret"}),
                encoding="utf-8",
            )

            violations = safety.find_violations(root, ["tk_toolkit_dual/config.json.template"])

        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
