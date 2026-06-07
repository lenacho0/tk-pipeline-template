import sys
import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ai_model_catalog
import tk_create_prompt_image_video_table as create_table
import tk_prompt_image_video as prompt_video
import tk_dispatcher as dispatcher


class PromptImageVideoTableTests(unittest.TestCase):
    def test_table_definition_uses_confirmed_name_models_and_views(self):
        self.assertEqual(create_table.TABLE_NAME, "008-图生视频生成表")

        fields = {field["name"]: field for field in create_table.PROMPT_IMAGE_VIDEO_FIELDS}
        self.assertEqual(fields["关联产品记录"]["type"], "link")
        self.assertEqual(fields["选择模特"]["type"], "link")
        self.assertEqual(fields["上传参考图"]["type"], "attachment")
        self.assertEqual(fields["图片AI模型"]["options"], ai_model_catalog.IMAGE_MODEL_OPTIONS)
        self.assertEqual(fields["视频AI模型"]["options"], ai_model_catalog.FIRST_LAST_VIDEO_MODEL_WITH_DEFAULT_OPTIONS)
        self.assertNotIn("图片操作", fields)
        self.assertNotIn("视频操作", fields)

        self.assertIn("01-用户入口", create_table.TABLE_DEFINITION["views"])
        self.assertIn("02-图片审核", create_table.TABLE_DEFINITION["views"])
        self.assertIn("03-视频结果", create_table.TABLE_DEFINITION["views"])
        self.assertIn("98-失败处理", create_table.TABLE_DEFINITION["views"])
        self.assertIn("99-全字段系统视图", create_table.TABLE_DEFINITION["views"])

    def test_stage_views_are_narrow_and_ordered_for_each_workflow_step(self):
        self.assertEqual(
            create_table.TABLE_DEFINITION["views"]["01-用户入口"],
            [
                "任务名称", "生图提示词", "图生视频提示词", "关联产品记录", "选择模特",
                "上传产品图", "上传模特图", "上传参考图", "图片AI模型", "图片画面尺寸", "图片画面比例",
                "图片生成状态", "图片审核状态",
                "视频AI模型", "视频时长秒", "视频画面尺寸", "视频画面比例",
                "视频生成状态",
            ],
        )
        self.assertEqual(len(create_table.TABLE_DEFINITION["views"]["01-用户入口"]), 18)
        self.assertEqual(len(create_table.TABLE_DEFINITION["views"]["02-图片审核"]), 17)
        self.assertEqual(len(create_table.TABLE_DEFINITION["views"]["03-视频结果"]), 13)
        self.assertEqual(len(create_table.TABLE_DEFINITION["views"]["98-失败处理"]), 13)
        self.assertEqual(create_table.TABLE_DEFINITION["views"]["99-全字段系统视图"], create_table.ALL_FIELD_NAMES)

        all_fields = set(create_table.ALL_FIELD_NAMES)
        for fields in create_table.TABLE_DEFINITION["views"].values():
            self.assertEqual(set(fields) - all_fields, set())
            self.assertNotIn("图片操作", fields)
            self.assertNotIn("视频操作", fields)

    def test_dispatcher_uses_generation_status_fields_as_008_triggers(self):
        watches = {watch["name"]: watch for watch in dispatcher.WATCH_LIST}
        image_watch = watches["008图生视频图片生成"]
        video_watch = watches["008图生视频视频生成"]

        self.assertEqual(image_watch["status_field"], "图片生成状态")
        self.assertEqual(image_watch["trigger_value"], "待生成")
        self.assertEqual(image_watch["running_value"], "生成中")
        self.assertEqual(image_watch["failed_value"], "失败")
        self.assertEqual(image_watch["args"], ["image"])
        self.assertNotIn("args_by_trigger_value", image_watch)

        self.assertEqual(video_watch["status_field"], "视频生成状态")
        self.assertEqual(video_watch["trigger_value"], "待生成")
        self.assertEqual(video_watch["running_value"], "生成中")
        self.assertEqual(video_watch["failed_value"], "失败")
        self.assertEqual(video_watch["args"], ["video"])
        self.assertNotIn("args_by_trigger_value", video_watch)

    def test_create_or_update_views_sets_field_names_and_verifies_visible_fields(self):
        target_fields = create_table.TABLE_DEFINITION["views"]["01-用户入口"]
        field_id_by_name = {name: f"fld_{idx}" for idx, name in enumerate(create_table.ALL_FIELD_NAMES)}
        calls = []
        current_visible_fields = list(target_fields)

        def fake_run_json(argv):
            nonlocal current_visible_fields
            calls.append(argv)
            if "+field-list" in argv:
                return {"data": {"fields": [{"name": name, "id": fid} for name, fid in field_id_by_name.items()]}}
            if "+view-list" in argv:
                return {"data": {"views": [{"name": "01-用户入口", "id": "view_user"}]}}
            if "+view-set-visible-fields" in argv:
                current_visible_fields = json.loads(argv[argv.index("--json") + 1])["visible_fields"]
                return {"ok": True}
            if "+view-get-visible-fields" in argv:
                return {"data": {"visible_fields": current_visible_fields}}
            raise AssertionError(argv)

        with patch.object(create_table, "run_json", side_effect=fake_run_json), \
             patch.object(create_table.time, "sleep"):
            result = create_table.create_or_update_views("base", "table", {"01-用户入口": target_fields})

        self.assertEqual(result, {"created": 0, "updated": 1, "rebuilt": 0})
        set_call = next(call for call in calls if "+view-set-visible-fields" in call)
        payload = json.loads(set_call[set_call.index("--json") + 1])
        self.assertEqual(payload["visible_fields"], target_fields)

    def test_create_or_update_views_applies_large_visibility_changes_gradually(self):
        target_fields = create_table.TABLE_DEFINITION["views"]["01-用户入口"]
        field_id_by_name = {name: f"fld_{idx}" for idx, name in enumerate(create_table.ALL_FIELD_NAMES)}
        current_visible_fields = list(create_table.ALL_FIELD_NAMES)
        set_payloads = []

        def fake_run_json(argv):
            nonlocal current_visible_fields
            if "+field-list" in argv:
                return {"data": {"fields": [{"name": name, "id": fid} for name, fid in field_id_by_name.items()]}}
            if "+view-list" in argv:
                return {"data": {"views": [{"name": "01-用户入口", "id": "view_user"}]}}
            if "+view-set-visible-fields" in argv:
                current_visible_fields = json.loads(argv[argv.index("--json") + 1])["visible_fields"]
                set_payloads.append(current_visible_fields)
                return {"ok": True}
            if "+view-get-visible-fields" in argv:
                return {"data": {"visible_fields": current_visible_fields}}
            raise AssertionError(argv)

        with patch.object(create_table, "run_json", side_effect=fake_run_json), \
             patch.object(create_table.time, "sleep"):
            create_table.create_or_update_views("base", "table", {"01-用户入口": target_fields})

        self.assertGreater(len(set_payloads), 1)
        self.assertEqual(set_payloads[0], target_fields[:2])
        self.assertEqual(set_payloads[-1], target_fields)

    def test_create_or_update_views_rebuilds_noop_view_when_visible_fields_stay_wrong(self):
        target_fields = create_table.TABLE_DEFINITION["views"]["01-用户入口"]
        field_id_by_name = {name: f"fld_{idx}" for idx, name in enumerate(create_table.ALL_FIELD_NAMES)}
        set_attempts = 0
        calls = []
        current_visible_fields = list(create_table.ALL_FIELD_NAMES)

        def fake_run_json(argv):
            nonlocal set_attempts, current_visible_fields
            calls.append(argv)
            if "+field-list" in argv:
                return {"data": {"fields": [{"name": name, "id": fid} for name, fid in field_id_by_name.items()]}}
            if "+view-list" in argv:
                return {"data": {"views": [{"name": "01-用户入口", "id": "view_user"}]}}
            if "+view-set-visible-fields" in argv:
                set_attempts += 1
                if set_attempts == 1:
                    raise RuntimeError("800070003 no operation produced")
                current_visible_fields = json.loads(argv[argv.index("--json") + 1])["visible_fields"]
                return {"ok": True}
            if "+view-get-visible-fields" in argv:
                if set_attempts == 1:
                    return {"data": {"visible_fields": create_table.ALL_FIELD_NAMES}}
                return {"data": {"visible_fields": current_visible_fields}}
            if "+view-delete" in argv:
                return {"ok": True}
            if "+view-create" in argv:
                return {"data": {"view": {"id": "view_user_rebuilt"}}}
            raise AssertionError(argv)

        with patch.object(create_table, "run_json", side_effect=fake_run_json), \
             patch.object(create_table.time, "sleep"):
            result = create_table.create_or_update_views("base", "table", {"01-用户入口": target_fields})

        self.assertEqual(result, {"created": 0, "updated": 1, "rebuilt": 1})
        self.assertTrue(any("+view-delete" in call for call in calls))
        self.assertTrue(any("+view-create" in call for call in calls))


class PromptImageVideoWorkerTests(unittest.TestCase):
    def test_auto_review_triggers_video_by_status_without_operation_fields(self):
        updates = []
        fields = {"图生视频提示词": "raw video prompt"}

        with patch.object(prompt_video, "TABLE_PROMPT_IMAGE_VIDEO", "tbl_008"), \
             patch.object(prompt_video, "auto_review_enabled", return_value=True), \
             patch.object(prompt_video, "safe_update_record", side_effect=lambda token, table, rid, patch_fields: updates.append(patch_fields)), \
             patch.object(prompt_video, "filter_existing_fields", side_effect=lambda token, table, patch_fields: patch_fields):
            result = prompt_video.maybe_auto_approve_image("token", "rec008", fields, file_token="ft_image")

        self.assertEqual(result, {"status": "auto_approved", "triggered_video": True})
        self.assertEqual(updates[-1]["图片审核状态"], "通过")
        self.assertEqual(updates[-1]["视频生成状态"], "待生成")
        self.assertNotIn("图片操作", updates[-1])
        self.assertNotIn("视频操作", updates[-1])

    def test_collect_image_references_merges_sources_in_order(self):
        downloads = []

        def fake_download(token, file_token, out_path):
            downloads.append((file_token, Path(out_path).name))
            Path(out_path).write_bytes(b"img")
            return out_path

        def fake_get_record(token, table_id, record_id):
            if table_id == "tbl_product":
                return {"产品图片": [{"file_token": "ft_product"}]}
            if table_id == "tbl_model":
                return {"模特照片": [{"file_token": "ft_model"}]}
            raise AssertionError(table_id)

        fields = {
            "关联产品记录": [{"record_ids": ["recProduct"]}],
            "选择模特": [{"record_ids": ["recModel"]}],
            "上传产品图": [{"file_token": "ft_upload_product"}],
            "上传模特图": [{"file_token": "ft_upload_model"}],
            "上传参考图": [{"file_token": "ft_upload_ref"}],
        }

        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.object(prompt_video, "TABLE_PRODUCT", "tbl_product"), \
             patch.object(prompt_video, "TABLE_MODEL", "tbl_model"):
            refs = prompt_video.collect_image_references(
                "token",
                fields,
                Path(tmpdir),
                get_record_fn=fake_get_record,
                download_fn=fake_download,
            )

        self.assertEqual(
            [ref["role"] for ref in refs],
            ["product_table:1", "uploaded_product:1", "model_table:1", "uploaded_model:1", "uploaded_reference:1"],
        )
        self.assertEqual([item[0] for item in downloads], ["ft_product", "ft_upload_product", "ft_model", "ft_upload_model", "ft_upload_ref"])

    def test_collect_image_references_allows_zero_and_rejects_more_than_seven(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.assertEqual(prompt_video.collect_image_references("token", {}, Path(tmpdir)), [])

        fields = {"上传参考图": [{"file_token": f"ft_{idx}"} for idx in range(8)]}
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaisesRegex(ValueError, "参考图数量超过上限"):
                prompt_video.collect_image_references("token", fields, Path(tmpdir))

    def test_prepare_product_reference_images_crops_top_left_panel_from_product_collage(self):
        from PIL import Image, ImageDraw

        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "product_collage.png"
            img = Image.new("RGB", (800, 800), "white")
            draw = ImageDraw.Draw(img)
            draw.rectangle([0, 0, 399, 399], fill=(20, 160, 80))
            draw.rectangle([400, 0, 401, 799], fill=(230, 230, 230))
            draw.rectangle([0, 400, 799, 401], fill=(230, 230, 230))
            img.save(source)

            refs = [{"role": "product_table:1", "file_token": "ft_product", "name": "product", "path": str(source)}]
            prepared = prompt_video.prepare_product_reference_images(refs, Path(tmpdir))

            self.assertEqual(len(prepared), 1)
            self.assertNotEqual(prepared[0]["path"], str(source))
            self.assertEqual(prepared[0]["source_path"], str(source))
            with Image.open(prepared[0]["path"]) as cropped:
                self.assertEqual(cropped.size, (400, 400))

    def test_image_generation_accepts_model_config_dict_and_uses_status_only(self):
        updates = []
        fields = {
            "生图提示词": "raw image prompt",
            "图片AI模型": "OTU / gpt-image-2-2K",
            "图片画面尺寸": "1080x1920",
            "图片画面比例": "9:16",
        }

        def fake_run_image(route, prompt, out_path, **kwargs):
            Path(out_path).write_bytes(b"image")
            return Mock(
                output_path=out_path,
                task_id="task_image",
                submit_body={"id": "task_image"},
                result_body={"ok": True},
                request_summary={"reference_count": 0},
            )

        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.object(prompt_video, "ensure_table"), \
             patch.object(prompt_video, "TABLE_PROMPT_IMAGE_VIDEO", "tbl_008"), \
             patch.object(prompt_video, "safe_get_record", return_value=fields), \
             patch.object(prompt_video, "safe_update_record", side_effect=lambda token, table, rid, patch_fields: updates.append(patch_fields)), \
             patch.object(prompt_video, "filter_existing_fields", side_effect=lambda token, table, patch_fields: patch_fields), \
             patch.object(prompt_video, "collect_image_references", return_value=[]), \
             patch.object(prompt_video, "get_model_config", return_value={"model": "gpt-image-2-2K", "api_key": "key", "api_base": "https://api.test"}), \
             patch.object(prompt_video, "safe_list_records", return_value=[]), \
             patch.object(prompt_video, "resolve_image_route_from_slot", return_value=Mock(provider="OTU", model="gpt-image-2-2K", params={})), \
             patch.object(prompt_video, "run_image_generation", side_effect=fake_run_image), \
             patch.object(prompt_video, "upload_image_to_feishu", return_value="ft_image"), \
             patch.object(prompt_video, "maybe_auto_approve_image", return_value={"status": "disabled"}), \
             patch.object(prompt_video, "BASE_WORK_DIR", Path(tmpdir)):
            result = prompt_video.run_image("token", "rec008")

        self.assertEqual(result["status"], "success")
        self.assertTrue(any(update.get("图片生成状态") == "生成中" for update in updates))
        self.assertTrue(any(update.get("图片生成状态") == "成功" for update in updates))
        self.assertTrue(all("图片操作" not in update and "视频操作" not in update for update in updates))

    def test_image_generation_uses_original_image_path_for_single_otu_reference_and_locks_product(self):
        captured = {}
        fields = {
            "生图提示词": "raw image prompt",
            "图片AI模型": "OTU / gpt-image-2-2K",
            "图片画面尺寸": "1080x1920",
            "图片画面比例": "9:16",
        }
        refs = [
            {"role": "product_table:1", "file_token": "ft_product", "name": "product", "path": "/tmp/product.png"},
        ]

        def fake_run_image(route, prompt, out_path, **kwargs):
            captured["prompt"] = prompt
            captured.update(kwargs)
            Path(out_path).write_bytes(b"image")
            return Mock(
                output_path=out_path,
                task_id="task_image",
                submit_body={"id": "task_image"},
                result_body={"ok": True},
                request_summary={"reference_count": 1},
            )

        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.object(prompt_video, "ensure_table"), \
             patch.object(prompt_video, "TABLE_PROMPT_IMAGE_VIDEO", "tbl_008"), \
             patch.object(prompt_video, "safe_get_record", return_value=fields), \
             patch.object(prompt_video, "safe_update_record"), \
             patch.object(prompt_video, "filter_existing_fields", side_effect=lambda token, table, patch_fields: patch_fields), \
             patch.object(prompt_video, "collect_image_references", return_value=refs), \
             patch.object(prompt_video, "prepare_product_reference_images", return_value=[{**refs[0], "source_path": refs[0]["path"], "path": "/tmp/product_focus.png"}]), \
             patch.object(prompt_video, "describe_product_reference_images", return_value="Visible product: UootaPet FIPRONIL package, green top, yellow bottom, cartoon cats."), \
             patch.object(prompt_video, "verify_generated_product_identity", return_value={"required": True, "passed": True, "reason": "same product"}), \
             patch.object(prompt_video, "apply_prompt_image_default_to_record", side_effect=lambda token, rid, got_fields: got_fields), \
             patch.object(prompt_video, "get_model_config", return_value={"model": "gpt-image-2-2K", "api_key": "key", "api_base": "https://api.test"}), \
             patch.object(prompt_video, "safe_list_records", return_value=[]), \
             patch.object(prompt_video, "resolve_image_route_from_slot", return_value=Mock(provider="OTU", model="gpt-image-2-2K", params={})), \
             patch.object(prompt_video, "build_reference_contact_sheet") as contact_sheet, \
             patch.object(prompt_video, "run_image_generation", side_effect=fake_run_image), \
             patch.object(prompt_video, "upload_image_to_feishu", return_value="ft_image"), \
             patch.object(prompt_video, "maybe_auto_approve_image", return_value={"status": "disabled"}), \
             patch.object(prompt_video, "BASE_WORK_DIR", Path(tmpdir)):
            result = prompt_video.run_image("token", "rec008")

        self.assertEqual(result["status"], "success")
        contact_sheet.assert_not_called()
        self.assertEqual(captured["image_path"], "/tmp/product_focus.png")
        self.assertIsNone(captured["reference_image_paths"])
        self.assertEqual(captured["reference_count_override"], 1)
        self.assertIn("PRODUCT REFERENCE LOCK", captured["prompt"])
        self.assertIn("product_table:1", captured["prompt"])
        self.assertIn("UootaPet FIPRONIL", captured["prompt"])

    def test_image_generation_fails_product_identity_audit_before_uploading(self):
        updates = []
        fields = {
            "生图提示词": "raw image prompt",
            "图片AI模型": "OTU / gpt-image-2-2K",
            "图片画面尺寸": "1080x1920",
            "图片画面比例": "9:16",
        }
        refs = [
            {"role": "product_table:1", "file_token": "ft_product", "name": "product", "path": "/tmp/product.png"},
        ]

        def fake_run_image(route, prompt, out_path, **kwargs):
            Path(out_path).write_bytes(b"image")
            return Mock(
                output_path=out_path,
                task_id="task_image",
                submit_body={"id": "task_image"},
                result_body={"ok": True},
                request_summary={"reference_count": 1},
            )

        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.object(prompt_video, "ensure_table"), \
             patch.object(prompt_video, "TABLE_PROMPT_IMAGE_VIDEO", "tbl_008"), \
             patch.object(prompt_video, "safe_get_record", return_value=fields), \
             patch.object(prompt_video, "safe_update_record", side_effect=lambda token, table, rid, patch_fields: updates.append(patch_fields)), \
             patch.object(prompt_video, "filter_existing_fields", side_effect=lambda token, table, patch_fields: patch_fields), \
             patch.object(prompt_video, "collect_image_references", return_value=refs), \
             patch.object(prompt_video, "prepare_product_reference_images", return_value=refs), \
             patch.object(prompt_video, "describe_product_reference_images", return_value="Visible product: UootaPet FIPRONIL package, green top, yellow bottom, cartoon cats."), \
             patch.object(prompt_video, "verify_generated_product_identity", return_value={
                 "required": True,
                 "passed": False,
                 "reason": "brand changed to RAMICAL",
                 "missing_or_changed": ["brand/logo", "main title"],
             }), \
             patch.object(prompt_video, "apply_prompt_image_default_to_record", side_effect=lambda token, rid, got_fields: got_fields), \
             patch.object(prompt_video, "get_model_config", return_value={"model": "gpt-image-2-2K", "api_key": "key", "api_base": "https://api.test"}), \
             patch.object(prompt_video, "safe_list_records", return_value=[]), \
             patch.object(prompt_video, "resolve_image_route_from_slot", return_value=Mock(provider="OTU", model="gpt-image-2-2K", params={})), \
             patch.object(prompt_video, "run_image_generation", side_effect=fake_run_image), \
             patch.object(prompt_video, "upload_image_to_feishu", return_value="ft_image") as upload, \
             patch.object(prompt_video, "maybe_auto_approve_image", return_value={"status": "disabled"}), \
             patch.object(prompt_video, "BASE_WORK_DIR", Path(tmpdir)):
            with self.assertRaisesRegex(ValueError, "产品一致性审核失败.*RAMICAL"):
                prompt_video.run_image("token", "rec008")

        upload.assert_not_called()
        self.assertTrue(any(update.get("图片生成状态") == "失败" for update in updates))
        self.assertTrue(any("brand changed to RAMICAL" in update.get("图片错误信息", "") for update in updates))
        self.assertFalse(any(update.get("图片生成状态") == "成功" for update in updates))

    def test_image_generation_uses_contact_sheet_for_multiple_otu_references_and_locks_product(self):
        captured = {}
        fields = {
            "生图提示词": "raw image prompt",
            "图片AI模型": "OTU / gpt-image-2-2K",
            "图片画面尺寸": "1080x1920",
            "图片画面比例": "9:16",
        }
        refs = [
            {"role": "product_table:1", "file_token": "ft_product", "name": "product", "path": "/tmp/product.png"},
            {"role": "uploaded_reference:1", "file_token": "ft_ref", "name": "ref", "path": "/tmp/ref.png"},
        ]

        def fake_run_image(route, prompt, out_path, **kwargs):
            captured["prompt"] = prompt
            captured.update(kwargs)
            Path(out_path).write_bytes(b"image")
            return Mock(
                output_path=out_path,
                task_id="task_image",
                submit_body={"id": "task_image"},
                result_body={"ok": True},
                request_summary={"reference_count": 2},
            )

        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.object(prompt_video, "ensure_table"), \
             patch.object(prompt_video, "TABLE_PROMPT_IMAGE_VIDEO", "tbl_008"), \
             patch.object(prompt_video, "safe_get_record", return_value=fields), \
             patch.object(prompt_video, "safe_update_record"), \
             patch.object(prompt_video, "filter_existing_fields", side_effect=lambda token, table, patch_fields: patch_fields), \
             patch.object(prompt_video, "collect_image_references", return_value=refs), \
             patch.object(prompt_video, "apply_prompt_image_default_to_record", side_effect=lambda token, rid, got_fields: got_fields), \
             patch.object(prompt_video, "verify_generated_product_identity", return_value={"required": True, "passed": True, "reason": "same product"}), \
             patch.object(prompt_video, "get_model_config", return_value={"model": "gpt-image-2-2K", "api_key": "key", "api_base": "https://api.test"}), \
             patch.object(prompt_video, "safe_list_records", return_value=[]), \
             patch.object(prompt_video, "resolve_image_route_from_slot", return_value=Mock(provider="OTU", model="gpt-image-2-2K", params={})), \
             patch.object(prompt_video, "build_reference_contact_sheet", return_value="/tmp/contact_sheet.png") as contact_sheet, \
             patch.object(prompt_video, "run_image_generation", side_effect=fake_run_image), \
             patch.object(prompt_video, "upload_image_to_feishu", return_value="ft_image"), \
             patch.object(prompt_video, "maybe_auto_approve_image", return_value={"status": "disabled"}), \
             patch.object(prompt_video, "BASE_WORK_DIR", Path(tmpdir)):
            result = prompt_video.run_image("token", "rec008")

        self.assertEqual(result["status"], "success")
        contact_sheet.assert_called_once()
        self.assertEqual(captured["image_path"], "/tmp/contact_sheet.png")
        self.assertIsNone(captured["reference_image_paths"])
        self.assertEqual(captured["reference_count_override"], 2)
        self.assertEqual(captured["input_mode"], "image-to-image")
        self.assertIn("PRODUCT REFERENCE LOCK", captured["prompt"])
        self.assertIn("product_table:1", captured["prompt"])

    def test_image_generation_without_references_stays_text_to_image(self):
        captured = {}
        fields = {"生图提示词": "raw image prompt"}

        def fake_run_image(route, prompt, out_path, **kwargs):
            captured.update(kwargs)
            Path(out_path).write_bytes(b"image")
            return Mock(
                output_path=out_path,
                task_id="task_image",
                submit_body={"id": "task_image"},
                result_body={"ok": True},
                request_summary={"reference_count": 0},
            )

        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.object(prompt_video, "ensure_table"), \
             patch.object(prompt_video, "TABLE_PROMPT_IMAGE_VIDEO", "tbl_008"), \
             patch.object(prompt_video, "safe_get_record", return_value=fields), \
             patch.object(prompt_video, "safe_update_record"), \
             patch.object(prompt_video, "filter_existing_fields", side_effect=lambda token, table, patch_fields: patch_fields), \
             patch.object(prompt_video, "collect_image_references", return_value=[]), \
             patch.object(prompt_video, "apply_prompt_image_default_to_record", side_effect=lambda token, rid, got_fields: got_fields), \
             patch.object(prompt_video, "get_model_config", return_value={"model": "gpt-image-2", "api_key": "key", "api_base": "https://api.test"}), \
             patch.object(prompt_video, "safe_list_records", return_value=[]), \
             patch.object(prompt_video, "resolve_image_route_from_slot", return_value=Mock(provider="OTU", model="gpt-image-2", params={})), \
             patch.object(prompt_video, "build_reference_contact_sheet") as contact_sheet, \
             patch.object(prompt_video, "run_image_generation", side_effect=fake_run_image), \
             patch.object(prompt_video, "upload_image_to_feishu", return_value="ft_image"), \
             patch.object(prompt_video, "maybe_auto_approve_image", return_value={"status": "disabled"}), \
             patch.object(prompt_video, "BASE_WORK_DIR", Path(tmpdir)):
            result = prompt_video.run_image("token", "rec008")

        self.assertEqual(result["status"], "success")
        contact_sheet.assert_not_called()
        self.assertNotIn("image_path", captured)
        self.assertEqual(captured["reference_image_paths"], [])
        self.assertEqual(captured["input_mode"], "text-to-image")

    def test_image_generation_keeps_reference_paths_for_aitgenne(self):
        captured = {}
        fields = {
            "生图提示词": "raw image prompt",
            "图片AI模型": "Aitgenne / gpt-image-2",
        }
        refs = [{"role": "uploaded_reference:1", "file_token": "ft_ref", "name": "ref", "path": "/tmp/ref.png"}]

        def fake_run_image(route, prompt, out_path, **kwargs):
            captured.update(kwargs)
            Path(out_path).write_bytes(b"image")
            return Mock(
                output_path=out_path,
                task_id="",
                submit_body={"ok": True},
                result_body={"ok": True},
                request_summary={"reference_count": 1},
            )

        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.object(prompt_video, "ensure_table"), \
             patch.object(prompt_video, "TABLE_PROMPT_IMAGE_VIDEO", "tbl_008"), \
             patch.object(prompt_video, "safe_get_record", return_value=fields), \
             patch.object(prompt_video, "safe_update_record"), \
             patch.object(prompt_video, "filter_existing_fields", side_effect=lambda token, table, patch_fields: patch_fields), \
             patch.object(prompt_video, "collect_image_references", return_value=refs), \
             patch.object(prompt_video, "apply_prompt_image_default_to_record", side_effect=lambda token, rid, got_fields: got_fields), \
             patch.object(prompt_video, "get_model_config", return_value={"model": "gpt-image-2", "api_key": "key", "api_base": "https://api.test"}), \
             patch.object(prompt_video, "safe_list_records", return_value=[]), \
             patch.object(prompt_video, "resolve_image_route_from_slot", return_value=Mock(provider="Aitgenne", model="Aitgenne / gpt-image-2", params={})), \
             patch.object(prompt_video, "build_reference_contact_sheet") as contact_sheet, \
             patch.object(prompt_video, "run_image_generation", side_effect=fake_run_image), \
             patch.object(prompt_video, "upload_image_to_feishu", return_value="ft_image"), \
             patch.object(prompt_video, "maybe_auto_approve_image", return_value={"status": "disabled"}), \
             patch.object(prompt_video, "BASE_WORK_DIR", Path(tmpdir)):
            result = prompt_video.run_image("token", "rec008")

        self.assertEqual(result["status"], "success")
        contact_sheet.assert_not_called()
        self.assertNotIn("image_path", captured)
        self.assertEqual(captured["reference_image_paths"], ["/tmp/ref.png"])
        self.assertEqual(captured["input_mode"], "image-to-image")

    def test_image_generation_applies_default_model_fields_before_routing(self):
        fields = {"生图提示词": "raw image prompt", "图片AI模型": "", "图片画面尺寸": "", "图片画面比例": ""}
        defaulted_fields = {
            **fields,
            "图片AI模型": "OTU / gpt-image-2",
            "图片画面尺寸": "720x1280",
            "图片画面比例": "9:16",
        }

        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.object(prompt_video, "ensure_table"), \
             patch.object(prompt_video, "TABLE_PROMPT_IMAGE_VIDEO", "tbl_008"), \
             patch.object(prompt_video, "safe_get_record", return_value=fields), \
             patch.object(prompt_video, "safe_update_record"), \
             patch.object(prompt_video, "filter_existing_fields", side_effect=lambda token, table, patch_fields: patch_fields), \
             patch.object(prompt_video, "collect_image_references", return_value=[]), \
             patch.object(prompt_video, "apply_prompt_image_default_to_record", return_value=defaulted_fields) as defaults, \
             patch.object(prompt_video, "get_model_config", return_value={"model": "gpt-image-2", "api_key": "key", "api_base": "https://api.test"}), \
             patch.object(prompt_video, "safe_list_records", return_value=[]), \
             patch.object(prompt_video, "resolve_image_route_from_slot", return_value=Mock(provider="OTU", model="OTU / gpt-image-2", params={})) as route_resolver, \
             patch.object(prompt_video, "run_image_generation") as run_image, \
             patch.object(prompt_video, "upload_image_to_feishu", return_value="ft_image"), \
             patch.object(prompt_video, "maybe_auto_approve_image", return_value={"status": "disabled"}), \
             patch.object(prompt_video, "BASE_WORK_DIR", Path(tmpdir)):
            def fake_run_image(route, prompt, out_path, **kwargs):
                Path(out_path).write_bytes(b"image")
                return Mock(
                    output_path=out_path,
                    task_id="task_image",
                    submit_body={"id": "task_image"},
                    result_body={"ok": True},
                    request_summary={},
                )

            run_image.side_effect = fake_run_image
            result = prompt_video.run_image("token", "rec008")

        self.assertEqual(result["status"], "success")
        defaults.assert_called_once_with("token", "rec008", fields)
        self.assertIs(route_resolver.call_args.args[0], defaulted_fields)

    def test_video_generation_requires_approved_image_and_uses_only_generated_image(self):
        updates = []
        captured = {}
        fields = {
            "图生视频提示词": "raw video prompt",
            "图片审核状态": "通过",
            "生成图片": [{"file_token": "ft_image"}],
            "视频AI模型": "OTU / veo_3_1-fast-fl",
            "视频画面尺寸": "720x1280",
            "视频画面比例": "9:16",
        }

        def fake_run_video(route, prompt, image_path, out_path, **kwargs):
            captured["prompt"] = prompt
            captured["image_path"] = image_path
            Path(out_path).write_bytes(b"video")
            return prompt_video.VideoGenerationResult(
                provider="OTU",
                task_id="task_video",
                submit_body={"id": "task_video"},
                result_body={"url": "https://example.test/video.mp4"},
                output_path=out_path,
                request_summary={"reference_count": 1},
            )

        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.object(prompt_video, "TABLE_PROMPT_IMAGE_VIDEO", "tbl_008"), \
             patch.object(prompt_video, "safe_get_record", return_value=fields), \
             patch.object(prompt_video, "safe_update_record", side_effect=lambda token, table, rid, patch_fields: updates.append(patch_fields)), \
             patch.object(prompt_video, "filter_existing_fields", side_effect=lambda token, table, patch_fields: patch_fields), \
             patch.object(prompt_video, "download_feishu_attachment_raw", side_effect=lambda token, file_token, save_path: Path(save_path).write_bytes(b"image") or save_path), \
             patch.object(prompt_video, "upload_video_to_feishu", return_value="ft_video"), \
             patch.object(prompt_video, "resolve_video_route", return_value=Mock(provider="OTU", model="OTU / veo_3_1-fast-fl")), \
             patch.object(prompt_video, "run_video_generation", side_effect=fake_run_video), \
             patch.object(prompt_video, "BASE_WORK_DIR", Path(tmpdir)):
            result = prompt_video.run_video("token", "rec008")

        self.assertEqual(result["status"], "success")
        self.assertEqual(captured["prompt"], "raw video prompt")
        self.assertTrue(str(captured["image_path"]).endswith("generated_image_v1.png"))
        self.assertTrue(any(update.get("生成视频file_token") == "ft_video" for update in updates))
        self.assertTrue(all("视频操作" not in update for update in updates))

    def test_video_status_rerun_overwrites_and_increments_existing_video_version(self):
        updates = []
        fields = {
            "图生视频提示词": "raw video prompt",
            "图片审核状态": "通过",
            "生成图片": [{"file_token": "ft_image"}],
            "生成视频": [{"file_token": "ft_old_video"}],
            "视频版本": 2,
            "视频AI模型": "OTU / veo_3_1-fast-fl",
            "视频画面尺寸": "720x1280",
            "视频画面比例": "9:16",
        }

        def fake_run_video(route, prompt, image_path, out_path, **kwargs):
            Path(out_path).write_bytes(b"video")
            return prompt_video.VideoGenerationResult(
                provider="OTU",
                task_id="task_video",
                submit_body={"id": "task_video"},
                result_body={"url": "https://example.test/video.mp4"},
                output_path=out_path,
                request_summary={"reference_count": 1},
            )

        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.object(prompt_video, "TABLE_PROMPT_IMAGE_VIDEO", "tbl_008"), \
             patch.object(prompt_video, "safe_get_record", return_value=fields), \
             patch.object(prompt_video, "safe_update_record", side_effect=lambda token, table, rid, patch_fields: updates.append(patch_fields)), \
             patch.object(prompt_video, "filter_existing_fields", side_effect=lambda token, table, patch_fields: patch_fields), \
             patch.object(prompt_video, "download_feishu_attachment_raw", side_effect=lambda token, file_token, save_path: Path(save_path).write_bytes(b"image") or save_path), \
             patch.object(prompt_video, "upload_video_to_feishu", return_value="ft_video"), \
             patch.object(prompt_video, "resolve_video_route", return_value=Mock(provider="OTU", model="OTU / veo_3_1-fast-fl")), \
             patch.object(prompt_video, "run_video_generation", side_effect=fake_run_video), \
             patch.object(prompt_video, "BASE_WORK_DIR", Path(tmpdir)):
            result = prompt_video.run_video("token", "rec008")

        self.assertEqual(result["status"], "success")
        self.assertTrue(any(update.get("视频版本") == 3 for update in updates))
        self.assertTrue(all("视频操作" not in update for update in updates))

    def test_video_generation_applies_default_model_fields_before_routing(self):
        fields = {
            "图生视频提示词": "raw video prompt",
            "图片审核状态": "通过",
            "生成图片": [{"file_token": "ft_image"}],
            "视频AI模型": "",
            "视频画面尺寸": "",
            "视频画面比例": "",
        }
        defaulted_fields = {
            **fields,
            "视频AI模型": "OTU / veo_3_1-fast-fl",
            "视频画面尺寸": "720x1280",
            "视频画面比例": "9:16",
        }

        def fake_run_video(route, prompt, image_path, out_path, **kwargs):
            Path(out_path).write_bytes(b"video")
            return prompt_video.VideoGenerationResult(
                provider="OTU",
                task_id="task_video",
                submit_body={"id": "task_video"},
                result_body={"url": "https://example.test/video.mp4"},
                output_path=out_path,
                request_summary={"reference_count": 1},
            )

        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.object(prompt_video, "ensure_table"), \
             patch.object(prompt_video, "TABLE_PROMPT_IMAGE_VIDEO", "tbl_008"), \
             patch.object(prompt_video, "safe_get_record", return_value=fields), \
             patch.object(prompt_video, "safe_update_record"), \
             patch.object(prompt_video, "filter_existing_fields", side_effect=lambda token, table, patch_fields: patch_fields), \
             patch.object(prompt_video, "apply_prompt_video_default_to_record", return_value=defaulted_fields) as defaults, \
             patch.object(prompt_video, "download_feishu_attachment_raw", side_effect=lambda token, file_token, save_path: Path(save_path).write_bytes(b"image") or save_path), \
             patch.object(prompt_video, "upload_video_to_feishu", return_value="ft_video"), \
             patch.object(prompt_video, "resolve_video_route", return_value=Mock(provider="OTU", model="OTU / veo_3_1-fast-fl")) as route_resolver, \
             patch.object(prompt_video, "run_video_generation", side_effect=fake_run_video), \
             patch.object(prompt_video, "BASE_WORK_DIR", Path(tmpdir)):
            result = prompt_video.run_video("token", "rec008")

        self.assertEqual(result["status"], "success")
        defaults.assert_called_once_with("token", "rec008", fields)
        self.assertIs(route_resolver.call_args.args[0], defaulted_fields)

    def test_video_generation_rejects_unapproved_image(self):
        with patch.object(prompt_video, "TABLE_PROMPT_IMAGE_VIDEO", "tbl_008"), \
             patch.object(prompt_video, "safe_get_record", return_value={"图片审核状态": "待确认", "生成图片": [{"file_token": "ft"}]}):
            with self.assertRaisesRegex(ValueError, "图片审核状态必须为通过"):
                prompt_video.run_video("token", "rec008")


if __name__ == "__main__":
    unittest.main()
