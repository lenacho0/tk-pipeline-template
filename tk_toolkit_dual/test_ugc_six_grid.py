import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import tk_ugc_six_grid as grid


def sample_script_json():
    shots = []
    grids = []
    for i in range(1, 7):
        shots.append({
            "shot_index": i,
            "scene": f"scene {i}",
            "visual_description": f"visual {i}",
            "subject_action": f"action {i}",
            "character_state": "same woman",
            "pet_state": "pet natural",
            "product_exposure_method": "natural product exposure",
            "environment_details": "Thai home",
            "camera": "handheld phone",
            "shot_size": "medium",
            "content_type": "dialogue" if i != 4 else "silent_action",
            "speaker_visible": i != 2,
            "image_generation_focus": f"focus {i}",
        })
        grids.append({
            "grid_index": i,
            "source_shot_index": i,
            "key_visual": f"key visual {i}",
            "key_character_action": f"key action {i}",
            "product_state": "product state",
            "environment_focus": "home focus",
            "content_type": shots[-1]["content_type"],
            "speaker_visible": shots[-1]["speaker_visible"],
        })
    return {
        "character_card": {"description": "Thai pet owner"},
        "environment_card": {"description": "ordinary Bangkok apartment"},
        "video_setup": {"video_style": "真实UGC", "character_continuity": "same person"},
        "optimal_shot_count": 6,
        "shots": shots,
        "six_grid_summary": grids,
    }


def sample_prompt_json():
    return grid.build_six_grid_prompt_json("rec03", sample_script_json())


class UGCSixGridTest(unittest.TestCase):
    def test_parse_script_json_requires_six_shots(self):
        fields = {"结构化脚本JSON": json.dumps(sample_script_json(), ensure_ascii=False)}
        data = grid.parse_script_json(fields)
        self.assertEqual(len(data["shots"]), 6)
        bad = sample_script_json()
        bad["shots"] = bad["shots"][:5]
        with self.assertRaises(ValueError):
            grid.parse_script_json({"结构化脚本JSON": json.dumps(bad, ensure_ascii=False)})

    def test_build_six_grid_prompt_json_has_six_panels_and_no_text_constraint(self):
        prompt = sample_prompt_json()
        self.assertEqual(len(prompt["panels"]), 9)
        self.assertEqual(prompt["panels"][0]["grid_index"], 1)
        self.assertIn("No subtitles", prompt["panels"][0]["negative_prompt_en"])
        self.assertIn("No subtitles", " ".join(prompt["global_style"]["hard_constraints"]))
        self.assertEqual(prompt["panel_aspect_ratio"], "9:16")
        self.assertEqual(prompt["combined_canvas_aspect_ratio"], "9:16")
        self.assertNotIn("aspect_ratio", prompt)
        self.assertEqual(prompt["effective_shot_count"], 6)
        self.assertFalse(prompt["panels"][6]["active"])
        self.assertEqual(prompt["video_type"], "UGC")

    def test_non_ugc_prompt_json_routes_to_non_ugc_grid_stage(self):
        script = sample_script_json()
        script["video_type"] = "非UGC"
        script["content_mode"] = "non_ugc_animation"
        prompt = grid.build_six_grid_prompt_json("rec03", script)
        self.assertEqual(prompt["video_type"], "非UGC")
        self.assertEqual(prompt["content_mode"], "non_ugc_animation")
        self.assertEqual(grid.grid_stage_for_prompt_json(prompt), grid.NON_UGC_GRID_STAGE_NAME)
        self.assertEqual(grid.grid_stage_for_prompt_json(sample_prompt_json()), grid.UGC_GRID_STAGE_NAME)

    def test_build_combined_image_prompt_contains_all_panels(self):
        prompt = grid.build_combined_image_prompt(sample_prompt_json())
        self.assertIn("9-panel", prompt)
        self.assertIn("Overall canvas: 9:16", prompt)
        self.assertIn("Inactive placeholder panels", prompt)
        self.assertIn("Each individual cell must be a vertical 9:16", prompt)
        self.assertIn("Panel 1", prompt)
        self.assertIn("Panel 9", prompt)
        self.assertIn("Absolutely no subtitles", prompt)


    def test_validate_six_grid_image_ratio_accepts_9x16_canvas_for_3x3(self):
        with tempfile.TemporaryDirectory() as td:
            img = Path(td) / "grid.png"
            from PIL import Image
            Image.new("RGB", (900, 1600), color=(255, 255, 255)).save(img)
            check = grid.validate_six_grid_image_ratio(img, "3行x3列")
            self.assertTrue(check["ok"])
            self.assertAlmostEqual(check["panel_ratio"], 9 / 16)

    def test_validate_six_grid_image_ratio_rejects_square_panels(self):
        with tempfile.TemporaryDirectory() as td:
            img = Path(td) / "grid.png"
            from PIL import Image
            Image.new("RGB", (1024, 1536), color=(255, 255, 255)).save(img)
            check = grid.validate_six_grid_image_ratio(img, "3行x3列")
            self.assertFalse(check["ok"])

    def test_extract_otu_result_url_handles_common_shapes(self):
        self.assertEqual(grid.extract_otu_result_url({"video_url": "https://x/a.png"}), "https://x/a.png")
        self.assertEqual(grid.extract_otu_result_url({"data": {"result_url": "https://x/b.png"}}), "https://x/b.png")
        self.assertEqual(grid.extract_otu_result_url({"result_urls": ["https://x/c.png"]}), "https://x/c.png")

    @patch("tk_ugc_six_grid.load_ugc_table_ids")
    def test_run_prepare_dry_run_does_not_write(self, tables_mock):
        tables_mock.return_value = {"ugc_03_script_version": "tbl03", "ugc_04_six_grid_storyboard": "tbl04"}

        def fake_get(token, table, rid):
            return {"结构化脚本JSON": json.dumps(sample_script_json(), ensure_ascii=False)}

        result = grid.run_prepare("rec03", token="t", get_record_fn=fake_get)
        self.assertFalse(result["written"])
        self.assertEqual(result["panel_count"], 9)
        self.assertEqual(result["ugc04_fields"]["9宫格生成状态"], "待生成")

    @patch("tk_ugc_six_grid.load_ugc_table_ids")
    def test_run_prepare_write_creates_record_and_updates_ugc03(self, tables_mock):
        tables_mock.return_value = {"ugc_03_script_version": "tbl03", "ugc_04_six_grid_storyboard": "tbl04"}
        created = []
        updated = []

        def fake_get(token, table, rid):
            return {"结构化脚本JSON": json.dumps(sample_script_json(), ensure_ascii=False)}

        def fake_create(token, table, fields):
            created.append((table, fields))
            return "rec04"

        def fake_update(token, table, rid, fields):
            updated.append((table, rid, fields))

        result = grid.run_prepare("rec03", token="t", write=True, get_record_fn=fake_get, create_record_fn=fake_create, update_record_fn=fake_update)
        self.assertTrue(result["written"])
        self.assertEqual(result["ugc04_record_id"], "rec04")
        self.assertEqual(created[0][0], "tbl04")
        self.assertEqual(updated[0][2], {"下游推进状态": "分镜中"})

    @patch("tk_ugc_six_grid.load_ugc_table_ids")
    def test_run_prepare_write_with_reroll_metadata_creates_candidate_record(self, tables_mock):
        tables_mock.return_value = {"ugc_03_script_version": "tbl03", "ugc_04_six_grid_storyboard": "tbl04"}
        created = []

        def fake_get(token, table, rid):
            return {"结构化脚本JSON": json.dumps(sample_script_json(), ensure_ascii=False)}

        def fake_create(token, table, fields):
            created.append(fields)
            return "rec04_new"

        result = grid.run_prepare(
            "rec03",
            token="t",
            write=True,
            get_record_fn=fake_get,
            create_record_fn=fake_create,
            update_record_fn=lambda *a, **k: None,
            candidate_group_id="UGC-GRID-GROUP-rec03",
            candidate_index=2,
            reroll_source_record_id="rec04_old",
        )
        self.assertEqual(result["ugc04_record_id"], "rec04_new")
        self.assertEqual(created[0]["重生成组ID"], "UGC-GRID-GROUP-rec03")
        self.assertEqual(created[0]["候选序号"], 2)
        self.assertEqual(created[0]["候选状态"], "候选")
        self.assertEqual(created[0]["重生成来源记录ID"], "rec04_old")
        self.assertIn("reroll candidate 2", created[0]["重生成备注"])

    @patch("tk_ugc_six_grid.get_grid_model_config")
    @patch("tk_ugc_six_grid.load_ugc_table_ids")
    def test_run_image_generation_dry_run_does_not_call_image(self, tables_mock, cfg_mock):
        tables_mock.return_value = {"ugc_04_six_grid_storyboard": "tbl04"}
        cfg_mock.return_value = {"record_id": "cfg", "stage": grid.UGC_GRID_STAGE_NAME, "model": "gpt-image-2", "api_base": "https://otuapi.com", "method": "专用 API", "api_key": "k"}

        def fake_get(token, table, rid):
            return {"9宫格提示词JSON": json.dumps(sample_prompt_json(), ensure_ascii=False)}

        def fail_call(config, prompt):
            raise AssertionError("should not call image in dry-run")

        result = grid.run_image_generation("rec04", token="t", get_record_fn=fake_get, image_caller=fail_call)
        self.assertTrue(result["dry_run"])
        self.assertFalse(result["written"])
        self.assertEqual(result["panel_count"], 9)
        self.assertEqual(result["image_metadata"]["aspectRatio"], "9:16")
        self.assertEqual(result["image_metadata"]["panelAspectRatio"], "9:16")
        self.assertIn("Panel 9", result["image_prompt"])

    @patch("tk_ugc_six_grid.get_grid_model_config")
    @patch("tk_ugc_six_grid.load_ugc_table_ids")
    def test_run_image_generation_write_uploads_and_updates(self, tables_mock, cfg_mock):
        tables_mock.return_value = {"ugc_04_six_grid_storyboard": "tbl04"}
        cfg_mock.return_value = {"record_id": "cfg", "stage": grid.UGC_GRID_STAGE_NAME, "model": "gpt-image-2", "api_base": "https://otuapi.com", "method": "专用 API", "api_key": "k"}
        updated = []
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "source.png"
            from PIL import Image
            Image.new("RGB", (900, 1600), color=(255, 255, 255)).save(source)
            old_base = grid.BASE_WORK_DIR
            grid.BASE_WORK_DIR = Path(td) / "work"
            try:
                def fake_get(token, table, rid):
                    return {"9宫格提示词JSON": json.dumps(sample_prompt_json(), ensure_ascii=False)}

                def fake_update(token, table, rid, fields):
                    updated.append(fields)

                def fake_call(config, prompt):
                    return {"task_id": "task1", "status": "completed", "result_url": "https://example.com/image.png"}

                def fake_download(url, save_path):
                    Path(save_path).parent.mkdir(parents=True, exist_ok=True)
                    Path(save_path).write_bytes(source.read_bytes())

                def fake_upload(token, path, name):
                    self.assertTrue(Path(path).exists())
                    return "file_token_1"

                with patch("tk_ugc_six_grid.download_file", fake_download):
                    result = grid.run_image_generation("rec04", token="t", call_image=True, write=True, get_record_fn=fake_get, update_record_fn=fake_update, image_caller=fake_call, uploader=fake_upload)
                self.assertTrue(result["written"])
                self.assertTrue(result["attachment_written"])
                self.assertEqual(result["file_token"], "file_token_1")
                self.assertEqual(updated[0]["9宫格生成状态"], "生成中")
                self.assertEqual(updated[-1]["9宫格生成状态"], "成功")
                self.assertEqual(updated[-1]["9宫格图片"][0]["file_token"], "file_token_1")
            finally:
                grid.BASE_WORK_DIR = old_base

    @patch("tk_ugc_six_grid.get_grid_model_config")
    @patch("tk_ugc_six_grid.load_ugc_table_ids")
    def test_run_image_generation_write_falls_back_when_attachment_rejected(self, tables_mock, cfg_mock):
        tables_mock.return_value = {"ugc_04_six_grid_storyboard": "tbl04"}
        cfg_mock.return_value = {"record_id": "cfg", "stage": grid.UGC_GRID_STAGE_NAME, "model": "gpt-image-2", "api_base": "https://otuapi.com", "method": "专用 API", "api_key": "k"}
        updated = []
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "source.png"
            from PIL import Image
            Image.new("RGB", (900, 1600), color=(255, 255, 255)).save(source)
            old_base = grid.BASE_WORK_DIR
            grid.BASE_WORK_DIR = Path(td) / "work"
            try:
                def fake_get(token, table, rid):
                    return {"9宫格提示词JSON": json.dumps(sample_prompt_json(), ensure_ascii=False)}

                def fake_update(token, table, rid, fields):
                    updated.append(fields)
                    if "9宫格图片" in fields:
                        raise RuntimeError("UploadAttachNotAllowed")

                def fake_call(config, prompt):
                    return {"task_id": "task1", "status": "completed", "result_url": "https://example.com/image.png"}

                def fake_download(url, save_path):
                    Path(save_path).parent.mkdir(parents=True, exist_ok=True)
                    Path(save_path).write_bytes(source.read_bytes())

                def fake_upload(token, path, name):
                    return "file_token_1"

                with patch("tk_ugc_six_grid.download_file", fake_download):
                    result = grid.run_image_generation("rec04", token="t", call_image=True, write=True, get_record_fn=fake_get, update_record_fn=fake_update, image_caller=fake_call, uploader=fake_upload)
                self.assertTrue(result["written"])
                self.assertFalse(result["attachment_written"])
                self.assertIn("UploadAttachNotAllowed", result["attachment_write_error"])
                self.assertEqual(updated[-1]["9宫格生成状态"], "成功")
                self.assertEqual(updated[-1]["9宫格图片file_token"], "file_token_1")
                self.assertIn("9宫格图片URL", updated[-1])
            finally:
                grid.BASE_WORK_DIR = old_base

    @patch("tk_ugc_six_grid.get_grid_model_config")
    @patch("tk_ugc_six_grid.load_ugc_table_ids")
    def test_run_image_generation_rejects_bad_ratio_and_marks_failed(self, tables_mock, cfg_mock):
        tables_mock.return_value = {"ugc_04_six_grid_storyboard": "tbl04"}
        cfg_mock.return_value = {"record_id": "cfg", "stage": grid.UGC_GRID_STAGE_NAME, "model": "gpt-image-2", "api_base": "https://otuapi.com", "method": "专用 API", "api_key": "k"}
        updated = []
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "bad_ratio.png"
            from PIL import Image
            Image.new("RGB", (1024, 1536), color=(255, 255, 255)).save(source)
            old_base = grid.BASE_WORK_DIR
            grid.BASE_WORK_DIR = Path(td) / "work"
            try:
                def fake_get(token, table, rid):
                    return {"9宫格提示词JSON": json.dumps(sample_prompt_json(), ensure_ascii=False)}

                def fake_update(token, table, rid, fields):
                    updated.append(fields)

                def fake_call(config, prompt, metadata=None):
                    return {"task_id": "task1", "status": "completed", "result_url": "https://example.com/image.png"}

                def fake_download(url, save_path):
                    Path(save_path).parent.mkdir(parents=True, exist_ok=True)
                    Path(save_path).write_bytes(source.read_bytes())

                with patch("tk_ugc_six_grid.download_file", fake_download):
                    with self.assertRaises(ValueError):
                        grid.run_image_generation("rec04", token="t", call_image=True, write=True, get_record_fn=fake_get, update_record_fn=fake_update, image_caller=fake_call)
                self.assertEqual(updated[0]["9宫格生成状态"], "生成中")
                self.assertEqual(updated[-1]["9宫格生成状态"], "失败")
                self.assertIn("比例校验失败", updated[-1]["错误信息"])
            finally:
                grid.BASE_WORK_DIR = old_base



if __name__ == "__main__":
    unittest.main()
