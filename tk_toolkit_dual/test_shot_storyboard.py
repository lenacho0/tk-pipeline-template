import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tk_shot_storyboard as storyboard


class ShotStoryboardReferenceTests(unittest.TestCase):
    def test_build_reference_urls_uses_feishu_tmp_download_urls(self):
        refs = [
            {"role": "pet:pet_hero", "file_token": "ft_pet"},
            {"role": "human:human_owner", "file_token": "ft_human"},
        ]
        response = {
            "code": 0,
            "data": {
                "tmp_download_urls": [
                    {"file_token": "ft_pet", "tmp_download_url": "https://x.test/pet.png"},
                    {"file_token": "ft_human", "tmp_download_url": "https://x.test/human.png"},
                ]
            },
        }
        with patch("tk_shot_storyboard.safe_request", return_value=response) as safe_request:
            urls = storyboard.build_reference_urls("token", refs)

        self.assertEqual(urls, ["https://x.test/pet.png", "https://x.test/human.png"])
        self.assertEqual(safe_request.call_count, 2)
        self.assertEqual(safe_request.call_args_list[0].kwargs["params"], {"file_tokens": "ft_pet"})
        self.assertEqual(safe_request.call_args_list[1].kwargs["params"], {"file_tokens": "ft_human"})

    def test_build_reference_urls_preserves_multiple_product_refs(self):
        refs = [
            {"role": "product:1", "file_token": "ft_product_1"},
            {"role": "product:2", "file_token": "ft_product_2"},
            {"role": "product:3", "file_token": "ft_product_3"},
        ]
        responses = [
            {"code": 0, "data": {"tmp_download_urls": [{"file_token": "ft_product_1", "tmp_download_url": "https://x.test/product-1.png"}]}},
            {"code": 0, "data": {"tmp_download_urls": [{"file_token": "ft_product_2", "tmp_download_url": "https://x.test/product-2.png"}]}},
            {"code": 0, "data": {"tmp_download_urls": [{"file_token": "ft_product_3", "tmp_download_url": "https://x.test/product-3.png"}]}},
        ]
        with patch("tk_shot_storyboard.safe_request", side_effect=responses):
            urls = storyboard.build_reference_urls("token", refs)

        self.assertEqual(urls, [
            "https://x.test/product-1.png",
            "https://x.test/product-2.png",
            "https://x.test/product-3.png",
        ])

    def test_build_shot_reference_prompt_note_treats_numbered_product_refs_as_product(self):
        prompt = storyboard.build_shot_reference_prompt_note([
            {"role": "product:1"},
            {"role": "product:2"},
            {"role": "pet:dog_character"},
        ])

        self.assertIn("Reference image 1 = product reference", prompt)
        self.assertIn("Reference image 2 = product reference", prompt)
        self.assertIn("packaging", prompt.lower())
        self.assertIn("label", prompt.lower())
        self.assertIn("color", prompt.lower())
        self.assertIn("specification", prompt.lower())
        self.assertIn("Reference image 3 = selected pet model reference (dog_character)", prompt)

    def test_get_tmp_download_url_for_attachment_uses_single_file_token(self):
        response = {
            "code": 0,
            "data": {
                "tmp_download_urls": [
                    {"file_token": "ft_first", "tmp_download_url": "https://x.test/first.png"},
                ]
            },
        }
        with patch("tk_shot_storyboard.safe_request", return_value=response) as safe_request:
            url = storyboard.get_tmp_download_url_for_attachment("token", "ft_first")

        self.assertEqual(url, "https://x.test/first.png")
        self.assertEqual(safe_request.call_args.kwargs["params"], {"file_tokens": "ft_first"})

    def test_build_last_frame_prompt_uses_explicit_tail_description(self):
        prompt = storyboard.build_script_doc_last_frame_prompt(
            {"尾帧画面描述": "hero holds product at the end", "画面描述": "hero starts walking", "视频提示词": "walk forward"},
            first_frame_prompt="first frame prompt",
        )
        self.assertIn("hero holds product at the end", prompt)
        self.assertIn("final frame", prompt.lower())
        self.assertNotIn("nine-grid", prompt.lower())

    def test_infer_last_frame_description_extracts_ending_frame_from_image_prompt(self):
        desc = storyboard.infer_script_doc_last_frame_description({
            "图片提示词": "[Starting Frame] stained rug\n\n[Ending Frame] same rug is clean and slightly damp."
        })
        self.assertEqual(desc, "same rug is clean and slightly damp.")

    def test_build_storyboard_success_fields_auto_triggers_last_frame_when_enabled(self):
        fields = storyboard.build_script_doc_storyboard_success_fields(
            {"首尾帧视频模式": "启用", "图片提示词": "[Starting Frame] stain [Ending Frame] clean rug"},
            file_token="ft_first",
            out_path="/tmp/shot.png",
            prompt="prompt",
        )
        self.assertEqual(fields["尾帧图生成状态"], "待生成")
        self.assertEqual(fields["尾帧画面描述"], "clean rug")

    def test_single_shot_prompt_uses_only_starting_frame_when_end_frame_enabled(self):
        prompt = storyboard._build_single_shot_prompt(
            "base prompt",
            {
                "首尾帧视频模式": "启用",
                "图片提示词": "[Starting Frame] stained sofa with product bottle\n\n[Ending Frame] sofa is clean and towel is wet",
                "画面描述": "cleaning demo",
            },
            "写实",
            "",
        )

        self.assertIn("stained sofa with product bottle", prompt)
        self.assertNotIn("sofa is clean and towel is wet", prompt)
        self.assertNotIn("[Ending Frame]", prompt)

    def test_last_frame_prompt_preserves_ending_frame_instruction_verbatim(self):
        ending = "Preserve the same Thai living room and product packaging. The pale yellow urine stain is completely gone. The cleaned area looks slightly damp. The paper towel is wet."
        prompt = storyboard.build_script_doc_last_frame_prompt(
            {
                "尾帧画面描述": ending,
                "图片提示词": "[Starting Frame] stained sofa with original product bottle\n\n[Ending Frame] sofa is clean and towel is wet",
            },
            first_frame_prompt="[Starting Frame] stained sofa with original product bottle\n\n[Ending Frame] sofa is clean and towel is wet",
        )

        lower = prompt.lower()
        self.assertIn("uploaded first-frame image", lower)
        self.assertIn("visual reference", lower)
        self.assertIn("ending frame instruction", lower)
        self.assertIn(ending, prompt)
        self.assertIn("preserve the same thai living room", lower)
        self.assertIn("pale yellow urine stain is completely gone", lower)
        self.assertIn("cleaned area looks slightly damp", lower)
        self.assertIn("paper towel is wet", lower)
        self.assertNotIn("only change", lower)
        self.assertNotIn("exact product bottle shape, label, colors, logo, text layout, position, and scale", lower)
        self.assertNotIn("stained sofa with original product bottle", prompt)
        self.assertNotIn("[Ending Frame]", prompt)

    def test_render_script_doc_last_frame_generates_and_writes_tail_frame(self):
        shot_fields = {
            "首尾帧视频模式": "启用",
            "尾帧画面描述": "end pose with product",
            "分镜图": [{"file_token": "ft_first"}],
            "画面描述": "start pose",
            "视频提示词": "move to end pose",
        }
        updates = []
        with tempfile.TemporaryDirectory() as tmp, \
             patch("tk_shot_storyboard.TABLE_SCRIPT_DOC_SHOTS", "tbl_shots"), \
             patch("tk_shot_storyboard.safe_get_record", return_value=shot_fields), \
             patch("tk_shot_storyboard.safe_update_record", side_effect=lambda token, table, rid, fields: updates.append(fields)), \
             patch("tk_shot_storyboard.filter_existing_fields", side_effect=lambda token, table, fields: fields), \
             patch("tk_shot_storyboard.ensure_task_dir", return_value=tmp), \
             patch("tk_shot_storyboard.download_feishu_media", return_value=Path(tmp) / "first.png"), \
             patch("tk_shot_storyboard.get_tmp_download_url_for_attachment", return_value="https://x.test/first-frame.png"), \
             patch("tk_shot_storyboard.get_model_config", return_value={"model": "gpt-image-2", "api_key": "sk", "api_base": "https://otuapi.com", "prompt": ""}), \
             patch("tk_shot_storyboard.submit_otu_image_task", return_value=("img_task_1", {"id": "img_task_1"})) as submitter, \
             patch("tk_shot_storyboard.poll_otu_image_task", return_value={"status": "completed", "result_url": "https://x.test/last.png"}), \
             patch("tk_shot_storyboard.download_otu_image_result") as image_downloader, \
             patch("tk_shot_storyboard.upload_image_to_feishu", return_value="ft_last"):
            image_downloader.side_effect = lambda url, path: Path(path).write_bytes(b"image bytes")
            storyboard.render_script_doc_last_frame("t", "rec1")

        self.assertEqual(updates[0]["尾帧图生成状态"], "生成中")
        self.assertEqual(updates[-1]["尾帧图生成状态"], "成功")
        self.assertEqual(updates[-1]["尾帧图file_token"], "ft_last")
        self.assertIn("尾帧图提示词", updates[-1])
        self.assertEqual(submitter.call_args.kwargs["input_mode"], "image-to-image")

    def test_render_script_doc_last_frame_uses_only_first_frame_url_as_visual_reference(self):
        shot_fields = {
            "首尾帧视频模式": "启用",
            "尾帧画面描述": "same sofa, stain removed, towel is wet",
            "分镜图": [{"file_token": "ft_first"}],
            "父文档记录ID": "parent1",
            "画面描述": "start pose",
            "视频提示词": "remove stain",
            "图片提示词": "[Starting Frame] stained sofa with exact product bottle\n\n[Ending Frame] same sofa, stain removed",
        }
        updates = []
        with tempfile.TemporaryDirectory() as tmp, \
             patch("tk_shot_storyboard.TABLE_SCRIPT_DOC_SHOTS", "tbl_shots"), \
             patch("tk_shot_storyboard.safe_get_record", return_value=shot_fields), \
             patch("tk_shot_storyboard.build_reference_urls") as build_reference_urls, \
             patch("tk_shot_storyboard.get_tmp_download_url_for_attachment", return_value="https://x.test/first-frame.png") as tmp_url_getter, \
             patch("tk_shot_storyboard.safe_update_record", side_effect=lambda token, table, rid, fields: updates.append(fields)), \
             patch("tk_shot_storyboard.filter_existing_fields", side_effect=lambda token, table, fields: fields), \
             patch("tk_shot_storyboard.ensure_task_dir", return_value=tmp), \
             patch("tk_shot_storyboard.download_feishu_media", return_value=Path(tmp) / "first.png"), \
             patch("tk_shot_storyboard.get_model_config", return_value={"model": "gpt-image-2", "api_key": "sk", "api_base": "https://otuapi.com", "prompt": ""}), \
             patch("tk_shot_storyboard.submit_otu_image_task", return_value=("img_task_1", {"id": "img_task_1"})) as submitter, \
             patch("tk_shot_storyboard.poll_otu_image_task", return_value={"status": "completed", "result_url": "https://x.test/last.png"}), \
             patch("tk_shot_storyboard.download_otu_image_result") as image_downloader, \
             patch("tk_shot_storyboard.upload_image_to_feishu", return_value="ft_last"):
            image_downloader.side_effect = lambda url, path: Path(path).write_bytes(b"image bytes")
            storyboard.render_script_doc_last_frame("t", "rec1")

        metadata = submitter.call_args.kwargs["metadata"]
        self.assertEqual(metadata["urls"], ["https://x.test/first-frame.png"])
        self.assertEqual(metadata["reference_roles"], ["first_frame"])
        tmp_url_getter.assert_called_once_with("t", "ft_first")
        build_reference_urls.assert_not_called()
        prompt = submitter.call_args.args[1]
        self.assertIn("ending frame instruction", prompt.lower())
        self.assertNotIn("product reference wins", prompt.lower())

    def test_slot_model_ignores_new_field_when_unified_route_is_disabled(self):
        model = storyboard.selected_slot_model(
            {"分镜图AI模型": "OTU / gpt-image-2-4K"},
            "分镜图",
            "gpt-image-2",
            route_enabled=False,
        )

        self.assertEqual(model, "gpt-image-2")

    def test_slot_params_reports_invalid_json_with_field_name(self):
        with self.assertRaisesRegex(ValueError, "分镜图AI参数JSON 不是合法 JSON"):
            storyboard.slot_params(
                {"分镜图AI参数JSON": "{bad json"},
                "分镜图",
                route_enabled=True,
            )

    def test_render_script_doc_last_frame_dry_run_does_not_submit_or_write(self):
        shot_fields = {
            "首尾帧视频模式": "启用",
            "尾帧画面描述": "same sofa, stain removed",
            "分镜图": [{"file_token": "ft_first"}],
            "图片提示词": "[Starting Frame] stained sofa\n\n[Ending Frame] same sofa, stain removed",
            "使用统一AI路由": "是",
            "尾帧图AI模型": "OTU / gpt-image-2-2K",
            "尾帧图AI参数JSON": '{"size": "2K", "aspect_ratio": "9:16"}',
        }
        with patch("tk_shot_storyboard.TABLE_SCRIPT_DOC_SHOTS", "tbl_shots"), \
             patch("tk_shot_storyboard.safe_get_record", return_value=shot_fields), \
             patch("tk_shot_storyboard.safe_list_records", return_value=[{
                 "fields": {"环节": "统一AI路由启用状态", "模型名称": "仅dry-run"}
             }]), \
             patch("tk_shot_storyboard.get_model_config", return_value={"model": "gpt-image-2", "api_key": "sk", "api_base": "https://otuapi.com", "prompt": ""}), \
             patch("tk_shot_storyboard.safe_update_record") as updater, \
             patch("tk_shot_storyboard.download_feishu_media") as downloader, \
             patch("tk_shot_storyboard.submit_otu_image_task") as submitter:
            result = storyboard.render_script_doc_last_frame("t", "rec1", dry_run=False)

        self.assertEqual(result["status"], "unified_ai_dry_run_ready")
        self.assertTrue(result["unified_ai_route_enabled"])
        self.assertEqual(result["model"], "gpt-image-2-2K")
        self.assertEqual(result["size"], "2K")
        updater.assert_not_called()
        downloader.assert_not_called()
        submitter.assert_not_called()

    def test_render_script_doc_shot_dry_run_does_not_submit_or_write(self):
        shot_fields = {
            "父文档记录ID": "parent1",
            "图片提示词": "clean the sofa with product visible",
            "画面描述": "cleaning demo",
            "使用统一AI路由": "是",
            "分镜图AI模型": "OTU / gpt-image-2-4K",
            "分镜图AI参数JSON": '{"size": "4K", "aspect_ratio": "9:16"}',
        }
        parent_fields = {"分镜风格": "写实", "解析结果JSON": ""}
        with patch("tk_shot_storyboard.TABLE_SCRIPT_DOC_TASKS", "tbl_tasks"), \
             patch("tk_shot_storyboard.TABLE_SCRIPT_DOC_REFERENCE_ASSETS", "tbl_assets"), \
             patch("tk_shot_storyboard.TABLE_SCRIPT_DOC_SHOTS", "tbl_shots"), \
             patch("tk_shot_storyboard.safe_get_record", side_effect=[shot_fields, parent_fields]), \
             patch("tk_shot_storyboard.safe_list_records", return_value=[{
                 "fields": {"环节": "统一AI路由启用状态", "模型名称": "仅dry-run"}
             }]), \
             patch("tk_shot_storyboard.get_model_config", return_value={"model": "gpt-image-2", "api_key": "sk", "api_base": "https://otuapi.com", "prompt": "base prompt"}), \
             patch("tk_shot_storyboard.safe_update_record") as updater, \
             patch("tk_shot_storyboard.submit_otu_image_task") as submitter:
            result = storyboard.render_script_doc_shot("t", "rec1", dry_run=True)

        self.assertEqual(result["status"], "dry_run_ready")
        self.assertTrue(result["unified_ai_route_enabled"])
        self.assertEqual(result["model"], "gpt-image-2-4K")
        self.assertEqual(result["size"], "4K")
        updater.assert_not_called()
        submitter.assert_not_called()


if __name__ == "__main__":
    unittest.main()
