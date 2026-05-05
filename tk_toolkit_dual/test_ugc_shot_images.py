import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

import tk_ugc_shot_images as shots


def sample_script_json():
    return {"optimal_shot_count": 6, "shots": [{"shot_index": i, "visual_description": f"visual {i}", "content_type": "voiceover"} for i in range(1, 7)]}


def sample_prompt_json():
    return {
        "task_type": "UGC_9_GRID_STORYBOARD_DYNAMIC_SHOTS",
        "layout": "3行x3列",
        "effective_shot_count": 6,
        "panels": [
            {"grid_index": i, "active": i <= 6, "placeholder": i > 6} for i in range(1, 10)
        ],
    }


class UGCShotImagesTest(unittest.TestCase):
    def test_grid_cells_3x2_reading_order(self):
        cells = shots.grid_cells(100, 300, "3行x2列")
        self.assertEqual(len(cells), 6)
        self.assertEqual(cells[0], (0, 0, 50, 100))
        self.assertEqual(cells[1], (50, 0, 100, 100))
        self.assertEqual(cells[5], (50, 200, 100, 300))

    def test_grid_cells_3x3_reading_order(self):
        cells = shots.grid_cells(900, 1600, "3行x3列")
        self.assertEqual(len(cells), 9)
        self.assertEqual(cells[0], (0, 0, 300, 533))
        self.assertEqual(cells[8], (600, 1067, 900, 1600))

    def test_crop_six_grid_outputs_six_files(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "grid.png"
            Image.new("RGB", (900, 1600), color=(255, 0, 0)).save(src)
            out = shots.crop_six_grid(src, Path(td) / "crops", "3行x3列")
            self.assertEqual(len(out), 9)
            self.assertTrue(out[0]["border_trimmed"])
            self.assertEqual(out[0]["raw_box"], [0, 0, 300, 533])
            self.assertLess(out[0]["size"][0], 300)
            self.assertLess(out[0]["size"][1], 533)
            self.assertTrue(Path(out[8]["path"]).exists())


    def test_crop_six_grid_trims_black_separator_lines(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "grid_with_lines.png"
            im = Image.new("RGB", (900, 1600), color=(240, 120, 80))
            px = im.load()
            # Draw black separator strokes on exact cell boundaries. Exact-boundary
            # cropping would preserve these pixels as black borders.
            for x in [300, 600]:
                for dx in [-1, 0, 1]:
                    for y in range(1600):
                        px[x + dx, y] = (0, 0, 0)
            for y in [533, 1067]:
                for dy in [-1, 0, 1]:
                    for x in range(900):
                        px[x, y + dy] = (0, 0, 0)
            im.save(src)
            out = shots.crop_six_grid(src, Path(td) / "crops", "3行x3列")
            # The first crop's right/bottom edges would hit separator lines without inset.
            with Image.open(out[0]["path"]) as crop:
                self.assertNotEqual(crop.getpixel((crop.width - 1, crop.height // 2)), (0, 0, 0))
                self.assertNotEqual(crop.getpixel((crop.width // 2, crop.height - 1)), (0, 0, 0))

    def test_make_vertical_916_image_preserves_aspect_on_1080x1920_canvas(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "shot.png"
            out = Path(td) / "shot_916.png"
            Image.new("RGB", (484, 541), color=(12, 34, 56)).save(src)
            info = shots.make_vertical_916_image(src, out)
            self.assertTrue(out.exists())
            self.assertEqual(info["size"], [1080, 1920])
            with Image.open(out) as im:
                self.assertEqual(im.size, (1080, 1920))
            self.assertGreater(info["fit_box"][2] - info["fit_box"][0], 0)

    def test_build_ugc05_fields_includes_links_and_fallback_fields(self):
        fields = shots.build_ugc05_fields("rec04", "rec03", {"shot_index": 1}, {"shot_index": 1, "path": "/tmp/a.png"}, file_token="ft")
        self.assertEqual(fields["关联6宫格任务"], ["rec04"])
        self.assertEqual(fields["关联脚本版本"], ["rec03"])
        self.assertEqual(fields["分镜序号"], 1)
        self.assertEqual(fields["裁切状态"], "成功")
        self.assertEqual(fields["高清化状态"], "待高清化")
        self.assertEqual(fields["原始裁切图片file_token"], "ft")
        self.assertEqual(fields["原始裁切图片"][0]["file_token"], "ft")

    def test_build_ugc05_fields_does_not_write_deleted_candidate_fields(self):
        ugc04_fields = {
            "重生成组ID": "UGC-GRID-GROUP-rec03",
            "候选序号": 2,
            "候选状态": "候选",
        }
        fields = shots.build_ugc05_fields(
            "rec04_new",
            "rec03",
            {"shot_index": 1},
            {"shot_index": 1, "path": "/tmp/shot_01.png"},
            ugc04_fields=ugc04_fields,
        )
        self.assertNotIn("重生成组ID", fields)
        self.assertNotIn("候选序号", fields)
        self.assertNotIn("候选状态", fields)
        self.assertNotIn("来源UGC04候选记录ID", fields)

    @patch("tk_ugc_shot_images.load_ugc_table_ids")
    def test_regenerate_single_ugc05_shot_updates_original_and_resets_hd(self, tables_mock):
        tables_mock.return_value = {"ugc_04_six_grid_storyboard": "tbl04", "ugc_05_shot_images": "tbl05"}
        with tempfile.TemporaryDirectory() as td:
            crop = Path(td) / "crop.png"
            grid = Path(td) / "grid.png"
            Image.new("RGB", (300, 533), color=(10, 20, 30)).save(crop)
            Image.new("RGB", (900, 1600), color=(255, 0, 0)).save(grid)
            updates = []
            old_base = shots.BASE_WORK_DIR
            shots.BASE_WORK_DIR = Path(td) / "work"
            try:
                def fake_get(token, table, rid):
                    if table == "tbl05":
                        return {
                            "关联6宫格任务": [{"record_ids": ["rec04"]}],
                            "分镜序号": 1,
                            "原始裁切图片路径": str(crop),
                        }
                    return {
                        "结构化脚本JSON": json.dumps(sample_script_json(), ensure_ascii=False),
                        "6宫格图片URL": str(grid),
                    }

                def fake_repaint(token, crop_path, grid_path, shot, crop_info, output_path, *, active_count, uploader):
                    Image.new("RGB", (1080, 1920), color=(1, 2, 3)).save(output_path)
                    return {"task_id": "task1", "final_path": str(output_path)}

                def fake_upload(token, path, name):
                    return f"ft_{name}"

                def fake_update(token, table, record_id, fields):
                    updates.append(fields)

                with patch("tk_ugc_shot_images.enhance_shot_image_with_repaint", fake_repaint):
                    result = shots.regenerate_single_ugc05_shot(
                        "rec05",
                        token="t",
                        write=True,
                        get_record_fn=fake_get,
                        update_record_fn=fake_update,
                        uploader=fake_upload,
                    )
                self.assertTrue(result["written"])
                self.assertEqual(updates[0]["分镜图审核状态"], "待确认")
                self.assertEqual(updates[0]["高清化状态"], "待高清化")
                self.assertEqual(updates[0]["高清图操作"], "不触发")
                self.assertIn("原始裁切图片", updates[0])
            finally:
                shots.BASE_WORK_DIR = old_base

    @patch("tk_ugc_shot_images.load_ugc_table_ids")
    def test_create_or_preview_dry_run_does_not_upload_or_create(self, tables_mock):
        tables_mock.return_value = {"ugc_04_six_grid_storyboard": "tbl04", "ugc_05_shot_images": "tbl05"}
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "grid.png"
            Image.new("RGB", (900, 1600), color=(255, 0, 0)).save(src)
            old_base = shots.BASE_WORK_DIR
            shots.BASE_WORK_DIR = Path(td) / "work"
            try:
                def fake_get(token, table, rid):
                    return {
                        "6宫格生成状态": "成功",
                        "布局": "3行x3列",
                        "结构化脚本JSON": json.dumps(sample_script_json(), ensure_ascii=False),
                        "6宫格提示词JSON": json.dumps(sample_prompt_json(), ensure_ascii=False),
                        "6宫格图片URL": str(src),
                        "关联脚本版本": [{"record_ids": ["rec03"]}],
                    }

                def fail_create(*args, **kwargs):
                    raise AssertionError("should not create in dry-run")

                result = shots.create_or_preview_shot_records("rec04", token="t", get_record_fn=fake_get, create_record_fn=fail_create)
                self.assertFalse(result["written"])
                self.assertEqual(result["shot_count"], 6)
                self.assertEqual(result["total_grid_cell_count"], 9)
                self.assertEqual(result["active_grid_indices"], [1, 2, 3, 4, 5, 6])
                self.assertEqual(len(result["preview_fields"]), 6)
            finally:
                shots.BASE_WORK_DIR = old_base

    def test_find_existing_ugc05_by_shot_matches_parent_and_shot_index(self):
        records = [
            {"record_id": "rec05_1", "fields": {"关联6宫格任务": [{"record_ids": ["rec04"]}], "分镜序号": 1}},
            {"record_id": "other", "fields": {"关联6宫格任务": [{"record_ids": ["other04"]}], "分镜序号": 1}},
            {"record_id": "rec05_2", "fields": {"关联6宫格任务": [{"record_ids": ["rec04"]}], "分镜序号": "2"}},
        ]
        self.assertEqual(shots.find_existing_ugc05_by_shot(records, ugc04_record_id="rec04"), {1: "rec05_1", 2: "rec05_2"})

    @patch("tk_ugc_shot_images.load_ugc_table_ids")
    def test_create_or_preview_write_uploads_and_creates_six_records(self, tables_mock):
        tables_mock.return_value = {"ugc_04_six_grid_storyboard": "tbl04", "ugc_05_shot_images": "tbl05"}
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "grid.png"
            Image.new("RGB", (900, 1600), color=(255, 0, 0)).save(src)
            created = []
            old_base = shots.BASE_WORK_DIR
            shots.BASE_WORK_DIR = Path(td) / "work"
            try:
                def fake_get(token, table, rid):
                    return {
                        "6宫格生成状态": "成功",
                        "布局": "3行x3列",
                        "结构化脚本JSON": json.dumps(sample_script_json(), ensure_ascii=False),
                        "6宫格提示词JSON": json.dumps(sample_prompt_json(), ensure_ascii=False),
                        "6宫格图片URL": str(src),
                        "关联脚本版本": [{"record_ids": ["rec03"]}],
                    }

                def fake_upload(token, path, name):
                    self.assertTrue(Path(path).exists())
                    return f"ft_{name}"

                def fake_create(token, table, fields):
                    created.append(fields)
                    return f"rec05_{len(created)}"

                result = shots.create_or_preview_shot_records("rec04", token="t", write=True, get_record_fn=fake_get, create_record_fn=fake_create, uploader=fake_upload)
                self.assertTrue(result["written"])
                self.assertEqual(len(result["created_records"]), 6)
                self.assertEqual(result["total_grid_cell_count"], 9)
                self.assertEqual(len(created), 6)
                self.assertEqual(created[0]["原始裁切图片"][0]["file_token"], "ft_shot_01.png")
            finally:
                shots.BASE_WORK_DIR = old_base

    @patch("tk_ugc_shot_images.load_ugc_table_ids")
    def test_create_or_preview_overwrite_updates_existing_records(self, tables_mock):
        tables_mock.return_value = {"ugc_04_six_grid_storyboard": "tbl04", "ugc_05_shot_images": "tbl05"}
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "grid.png"
            Image.new("RGB", (900, 1600), color=(255, 0, 0)).save(src)
            created = []
            updated = []
            old_base = shots.BASE_WORK_DIR
            shots.BASE_WORK_DIR = Path(td) / "work"
            try:
                def fake_get(token, table, rid):
                    return {
                        "6宫格生成状态": "成功",
                        "布局": "3行x3列",
                        "结构化脚本JSON": json.dumps(sample_script_json(), ensure_ascii=False),
                        "6宫格提示词JSON": json.dumps(sample_prompt_json(), ensure_ascii=False),
                        "6宫格图片URL": str(src),
                        "关联脚本版本": [{"record_ids": ["rec03"]}],
                    }

                def fake_upload(token, path, name):
                    return f"ft_{name}"

                def fake_create(token, table, fields):
                    created.append(fields)
                    return f"new_{len(created)}"

                def fake_update(token, table, record_id, fields):
                    updated.append((record_id, fields))

                existing = [
                    {"record_id": f"rec05_{i}", "fields": {"关联6宫格任务": [{"record_ids": ["rec04"]}], "分镜序号": i}}
                    for i in range(1, 7)
                ]
                result = shots.create_or_preview_shot_records(
                    "rec04",
                    token="t",
                    write=True,
                    get_record_fn=fake_get,
                    create_record_fn=fake_create,
                    update_record_fn=fake_update,
                    uploader=fake_upload,
                    overwrite_existing=True,
                    existing_records=existing,
                )
                self.assertTrue(result["written"])
                self.assertEqual(result["updated_record_count"], 6)
                self.assertEqual(result["created_record_count"], 0)
                self.assertEqual(len(updated), 6)
                self.assertEqual(len(created), 0)
                self.assertEqual(updated[0][0], "rec05_1")
                self.assertEqual(updated[0][1]["原始裁切图片"][0]["file_token"], "ft_shot_01.png")
            finally:
                shots.BASE_WORK_DIR = old_base


if __name__ == "__main__":
    unittest.main()
