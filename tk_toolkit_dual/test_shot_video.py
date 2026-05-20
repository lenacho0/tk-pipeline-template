import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tk_shot_video as video


def sample_fields():
    return {
        "视频生成状态": "待生成",
        "视频提示词": "Use this shot image as the first frame. Move naturally.",
        "目标时长秒": 7,
        "分镜图": [{"file_token": "ft_image"}],
        "口播文本": "เลือกให้ถูก",
        "口播音频状态": "待生成",
    }


class ShotVideoTest(unittest.TestCase):
    def test_normalize_seconds_limits_to_veo_values(self):
        self.assertEqual(video.normalize_seconds(4), "4")
        self.assertEqual(video.normalize_seconds("6秒"), "6")
        self.assertEqual(video.normalize_seconds(7), "8")
        self.assertEqual(video.normalize_seconds(""), "8")

    def test_build_prompt_requires_video_prompt(self):
        fields = sample_fields()
        fields["视频提示词"] = ""
        with self.assertRaisesRegex(ValueError, "视频提示词"):
            video.build_model_prompt(fields)

    def test_resolve_reference_image_requires_storyboard_attachment(self):
        fields = sample_fields()
        fields["分镜图"] = []
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "分镜图"):
                video.resolve_reference_image("t", "rec1", fields, Path(tmp), download_fn=Mock())

    def test_submit_aihubmix_video_task_sends_multipart_input_reference(self):
        with tempfile.NamedTemporaryFile(suffix=".png") as img:
            img.write(b"fake image bytes")
            img.flush()
            response = Mock()
            response.status_code = 200
            response.json.return_value = {"id": "vid_123"}
            response.text = '{"id":"vid_123"}'
            with patch("tk_shot_video.requests.post", return_value=response) as post:
                task_id, body = video.submit_aihubmix_video_task(
                    {
                        "api_base": "https://aihubmix.com",
                        "api_key": "sk-test",
                        "model": "veo-3.1-fast-generate-preview",
                    },
                    "prompt text",
                    img.name,
                    "8",
                    "720p",
                    "9:16",
                )
        self.assertEqual(task_id, "vid_123")
        self.assertEqual(body["id"], "vid_123")
        args, kwargs = post.call_args
        self.assertEqual(args[0], "https://aihubmix.com/v1/videos")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer sk-test")
        self.assertEqual(kwargs["files"]["model"], (None, "veo-3.1-fast-generate-preview"))
        self.assertEqual(kwargs["files"]["prompt"], (None, "prompt text"))
        self.assertEqual(kwargs["files"]["seconds"], (None, "8"))
        self.assertEqual(kwargs["files"]["size"], (None, "720p"))
        self.assertEqual(kwargs["files"]["aspect_ratio"], (None, "9:16"))
        self.assertIn("input_reference[]", kwargs["files"])

    def test_call_native_veo_uses_image_as_first_frame_and_portrait_config(self):
        fake_client = Mock()
        fake_client.models.generate_videos.return_value = SimpleNamespace(name="operations/native_1")
        with tempfile.NamedTemporaryFile(suffix=".png") as img:
            img.write(b"fake image bytes")
            img.flush()
            operation = video.call_native_veo_first_frame_task(
                {
                    "model": "veo-3.1-fast-generate-preview",
                    "api_key": "sk-test",
                    "api_base": "https://aihubmix.com/gemini",
                },
                "prompt text",
                img.name,
                "8",
                "720p",
                "9:16",
                client=fake_client,
            )
        self.assertEqual(operation.name, "operations/native_1")
        kwargs = fake_client.models.generate_videos.call_args.kwargs
        self.assertEqual(kwargs["model"], "veo-3.1-fast-generate-preview")
        self.assertEqual(kwargs["prompt"], "prompt text")
        self.assertEqual(kwargs["image"].mime_type, "image/png")
        self.assertEqual(kwargs["image"].image_bytes, b"fake image bytes")
        self.assertEqual(kwargs["config"].aspect_ratio, "9:16")
        self.assertEqual(kwargs["config"].resolution, "720p")
        self.assertEqual(kwargs["config"].duration_seconds, 8)
        self.assertIsNone(kwargs["config"].last_frame)

    def test_extract_video_url_handles_nested_values(self):
        result = {"data": {"output": [{"result_url": "https://x.test/video.mp4"}]}}
        self.assertEqual(video.extract_video_url(result), "https://x.test/video.mp4")

    def test_success_fields_include_video_attachment_and_status(self):
        fields = video.build_success_fields(
            {"model": "veo-3.1-fast-generate-preview"},
            "vid_123",
            {"status": "completed"},
            "https://x.test/video.mp4",
            "/tmp/out.mp4",
            "ft_video",
        )
        self.assertEqual(fields["视频生成状态"], "成功")
        self.assertEqual(fields["视频任务ID"], "vid_123")
        self.assertEqual(fields["分镜视频"][0]["file_token"], "ft_video")
        self.assertEqual(fields["分镜视频file_token"], "ft_video")

    def test_run_dry_run_validates_inputs_without_submitting(self):
        with patch("tk_shot_video.get_model_config") as cfg, \
             patch("tk_shot_video.ensure_work_dir") as work, \
             patch("tk_shot_video.resolve_reference_image") as ref:
            cfg.return_value = ("cfg1", {
                "model": "veo-3.1-fast-generate-preview",
                "api_key": "sk",
                "api_base": "https://aihubmix.com",
                "aspect_ratio": "9:16",
            })
            work.return_value = Path("/tmp")
            ref.return_value = Path("/tmp/ref.png")
            result = video.run_shot_video_generation(
                "rec1",
                dry_run=True,
                token="t",
                get_record_fn=lambda token, table, rid: sample_fields(),
            )
        self.assertEqual(result["status"], "dry_run_ready")
        self.assertEqual(result["model"], "veo-3.1-fast-generate-preview")
        self.assertEqual(result["aspect_ratio"], "9:16")
        self.assertEqual(result["first_frame_image_path"], "/tmp/ref.png")

    def test_run_defaults_blank_record_model_to_native_veo(self):
        fields = sample_fields()
        fields["视频生成模型"] = ""
        with patch("tk_shot_video.get_model_config") as cfg, \
             patch("tk_shot_video.ensure_work_dir") as work, \
             patch("tk_shot_video.resolve_reference_image") as ref:
            cfg.return_value = ("cfg1", {
                "model": "veo-3.1-fast-generate-preview",
                "api_key": "sk",
                "api_base": "https://aihubmix.com/gemini",
                "size": "720p",
                "aspect_ratio": "9:16",
            })
            work.return_value = Path("/tmp")
            ref.return_value = Path("/tmp/ref.png")

            result = video.run_shot_video_generation(
                "rec1",
                dry_run=True,
                token="t",
                get_record_fn=lambda token, table, rid: fields,
            )

        self.assertEqual(result["video_provider"], "veo3.1")
        self.assertEqual(result["api_base"], "https://aihubmix.com/gemini")

    def test_seeddance_requires_generated_voiceover_audio_when_voiceover_exists(self):
        fields = sample_fields()
        fields["视频生成模型"] = "seeddance2.0"
        with patch("tk_shot_video.get_model_config") as cfg, \
             patch("tk_shot_video.ensure_work_dir") as work, \
             patch("tk_shot_video.resolve_reference_image") as ref:
            cfg.return_value = ("cfg1", {
                "model": "doubao-seedance-2-0-fast-260128",
                "api_key": "sk",
                "api_base": "https://aihubmix.com",
                "size": "720p",
                "aspect_ratio": "9:16",
            })
            work.return_value = Path("/tmp")
            ref.return_value = Path("/tmp/ref.png")
            with self.assertRaisesRegex(ValueError, "口播音频状态=成功"):
                video.run_shot_video_generation(
                    "rec1",
                    dry_run=True,
                    token="t",
                    get_record_fn=lambda token, table, rid: fields,
                )

    def test_seeddance_dry_run_allows_silent_shot_without_audio(self):
        fields = sample_fields()
        fields["视频生成模型"] = "seeddance2.0"
        fields["口播文本"] = ""
        with patch("tk_shot_video.get_model_config") as cfg, \
             patch("tk_shot_video.ensure_work_dir") as work, \
             patch("tk_shot_video.resolve_reference_image") as ref:
            cfg.return_value = ("cfg1", {
                "model": "doubao-seedance-2-0-fast-260128",
                "api_key": "sk",
                "api_base": "https://aihubmix.com",
                "size": "720p",
                "aspect_ratio": "9:16",
            })
            work.return_value = Path("/tmp")
            ref.return_value = Path("/tmp/ref.png")

            result = video.run_shot_video_generation(
                "rec1",
                dry_run=True,
                token="t",
                get_record_fn=lambda token, table, rid: fields,
            )

        self.assertEqual(result["video_provider"], "seeddance2.0")
        self.assertEqual(result["voiceover_audio_dependency"]["required"], False)
        self.assertEqual(result["first_frame_image_path"], "/tmp/ref.png")

    def test_run_generation_uses_native_first_frame_submitter(self):
        fake_client = Mock()
        operation = SimpleNamespace(name="operations/native_1", done=False)
        completed = SimpleNamespace(
            name="operations/native_1",
            done=True,
            response=SimpleNamespace(
                generated_videos=[
                    SimpleNamespace(video=SimpleNamespace(uri="https://x.test/native.mp4"))
                ]
            ),
        )

        with patch("tk_shot_video.get_model_config") as cfg, \
             patch("tk_shot_video.ensure_work_dir") as work, \
             patch("tk_shot_video.resolve_reference_image") as ref, \
             patch("tk_shot_video.filter_existing_fields", side_effect=lambda token, table, fields: fields), \
             patch("tk_shot_video.os.path.getsize", return_value=123456):
            cfg.return_value = ("cfg1", {
                "model": "veo-3.1-fast-generate-preview",
                "api_key": "sk",
                "api_base": "https://aihubmix.com/gemini",
                "size": "720p",
                "aspect_ratio": "9:16",
            })
            work.return_value = Path("/tmp")
            ref.return_value = Path("/tmp/ref.png")
            submitter = Mock(return_value=operation)
            poller = Mock(return_value=completed)
            downloader = Mock(return_value="/tmp/rec1_video.mp4")
            uploader = Mock(return_value="ft_video")
            updates = []

            result = video.run_shot_video_generation(
                "rec1",
                token="t",
                get_record_fn=lambda token, table, rid: sample_fields(),
                update_record_fn=lambda token, table, rid, fields: updates.append(fields),
                native_client_factory=lambda config: fake_client,
                native_submitter=submitter,
                native_poller=poller,
                native_downloader=downloader,
                uploader=uploader,
            )

        submitter.assert_called_once_with(
            cfg.return_value[1],
            "Use this shot image as the first frame. Move naturally.",
            "/tmp/ref.png",
            "8",
            "720p",
            "9:16",
            client=fake_client,
        )
        poller.assert_called_once_with(fake_client, operation)
        downloader.assert_called_once_with(fake_client, completed.response.generated_videos[0].video, "/tmp/rec1_video.mp4")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["task_id"], "operations/native_1")
        self.assertEqual(result["video_url"], "https://x.test/native.mp4")
        self.assertEqual(updates[-1]["视频生成状态"], "成功")


if __name__ == "__main__":
    unittest.main()
