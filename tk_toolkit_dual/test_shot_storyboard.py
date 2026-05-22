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

    def test_build_last_frame_prompt_uses_explicit_tail_description(self):
        prompt = storyboard.build_script_doc_last_frame_prompt(
            {"尾帧画面描述": "hero holds product at the end", "画面描述": "hero starts walking", "视频提示词": "walk forward"},
            first_frame_prompt="first frame prompt",
        )
        self.assertIn("hero holds product at the end", prompt)
        self.assertIn("final frame", prompt.lower())
        self.assertNotIn("nine-grid", prompt.lower())

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


if __name__ == "__main__":
    unittest.main()
