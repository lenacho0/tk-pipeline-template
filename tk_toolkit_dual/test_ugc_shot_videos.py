import json
import unittest
from unittest.mock import patch

import tk_ugc_shot_videos as videos


def sample_ugc06_fields(status="待生成"):
    prompt = {
        "prompt_en": "Use the input image as the only visual anchor.",
        "negative_prompt": "no subtitles",
        "source_image_policy": {
            "ugc05_hd_file_token": "ft_ref",
            "ugc05_hd_local_path": "/tmp/missing.png",
        },
    }
    return {
        "视频生成状态": status,
        "图生视频提示词": json.dumps(prompt, ensure_ascii=False),
        "高清分镜图file_token": "ft_ref",
        "高清分镜图路径": "",
    }


class UGCShotVideosTest(unittest.TestCase):
    def test_build_model_prompt_appends_negative_prompt(self):
        prompt = videos.build_model_prompt(sample_ugc06_fields())
        self.assertIn("Use the input image as the only visual anchor", prompt)
        self.assertIn("Negative prompt: no subtitles", prompt)

    def test_extract_video_url_handles_nested_result_url(self):
        result = {"data": {"output": {"result_url": "https://x.test/video/a.mp4"}}}
        self.assertEqual(videos.extract_video_url(result), "https://x.test/video/a.mp4")

    def test_run_dry_run_validates_config_prompt_and_reference(self):
        with patch("tk_ugc_shot_videos.load_ugc_table_ids") as tables, \
             patch("tk_ugc_shot_videos.get_model_config") as cfg, \
             patch("tk_ugc_shot_videos.ensure_work_dir") as work, \
             patch("tk_ugc_shot_videos.resolve_reference_image") as ref:
            tables.return_value = {"ugc_06_shot_videos": "tbl06"}
            cfg.return_value = ("cfg1", {"model": "veo_3_1-fast-fl-hd", "api_key": "sk", "api_base": "https://otuapi.com", "prompt_template": "", "call_type": "专用 API"})
            work.return_value = __import__("pathlib").Path("/tmp")
            ref.return_value = __import__("pathlib").Path("/tmp/ref.png")
            result = videos.run_ugc06_video_generation(
                "rec06",
                dry_run=True,
                token="t",
                get_record_fn=lambda token, table, rid: sample_ugc06_fields(),
            )
        self.assertEqual(result["status"], "dry_run_ready")
        self.assertEqual(result["model"], "veo_3_1-fast-fl-hd")
        self.assertEqual(result["reference_image_path"], "/tmp/ref.png")

    def test_success_fields_include_fallback_fields_and_attachment(self):
        fields = videos.build_success_fields(
            {"model": "veo_3_1-fast-fl-hd"},
            "task_1",
            {"status": "completed", "video_url": "https://x/video.mp4"},
            "https://x/video.mp4",
            "/tmp/rec06_video.mp4",
            "ft_video",
        )
        self.assertEqual(fields["视频生成状态"], "成功")
        self.assertEqual(fields["视频生成任务ID"], "task_1")
        self.assertEqual(fields["分镜视频file_token"], "ft_video")
        self.assertEqual(fields["分镜视频"][0]["file_token"], "ft_video")

    def test_successful_existing_record_refuses_repeat_generation(self):
        with patch("tk_ugc_shot_videos.load_ugc_table_ids") as tables:
            tables.return_value = {"ugc_06_shot_videos": "tbl06"}
            with self.assertRaises(ValueError):
                videos.run_ugc06_video_generation(
                    "rec06",
                    dry_run=False,
                    token="t",
                    get_record_fn=lambda token, table, rid: sample_ugc06_fields(status="成功"),
                )

    def test_successful_existing_record_allows_overwrite_dry_run(self):
        with patch("tk_ugc_shot_videos.load_ugc_table_ids") as tables, \
             patch("tk_ugc_shot_videos.get_model_config") as cfg, \
             patch("tk_ugc_shot_videos.ensure_work_dir") as work, \
             patch("tk_ugc_shot_videos.resolve_reference_image") as ref:
            tables.return_value = {"ugc_06_shot_videos": "tbl06"}
            cfg.return_value = ("cfg1", {"model": "veo_3_1-fast-fl-hd", "api_key": "sk", "api_base": "https://otuapi.com", "prompt_template": "", "call_type": "专用 API"})
            work.return_value = __import__("pathlib").Path("/tmp")
            ref.return_value = __import__("pathlib").Path("/tmp/ref.png")
            result = videos.run_ugc06_video_generation(
                "rec06",
                dry_run=True,
                token="t",
                get_record_fn=lambda token, table, rid: sample_ugc06_fields(status="成功"),
                allow_overwrite=True,
            )
        self.assertTrue(result["allow_overwrite"])
        self.assertEqual(result["status"], "dry_run_ready")


if __name__ == "__main__":
    unittest.main()
