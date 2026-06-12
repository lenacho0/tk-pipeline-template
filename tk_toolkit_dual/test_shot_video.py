import os
import base64
import importlib.util
import sys
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tk_shot_video as video

_dispatcher_spec = importlib.util.spec_from_file_location(
    "tk_dispatcher",
    Path(__file__).with_name("tk_dispatcher.py"),
)
dispatcher = importlib.util.module_from_spec(_dispatcher_spec)
assert _dispatcher_spec and _dispatcher_spec.loader
_dispatcher_spec.loader.exec_module(dispatcher)


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
    def test_dispatcher_stage_policy_prefers_watch_name_then_script_config(self):
        watch = {
            "name": "首尾帧首帧图生成",
            "script": "tk_first_last_video.py",
            "max_concurrency": 1,
            "max_retries": 1,
            "timeout": 1200,
        }
        with patch.object(dispatcher, "STAGE_CFG", {
            "tk_first_last_video.py": {"max_concurrency": 4, "timeout": 2400},
            "首尾帧首帧图生成": {"max_concurrency": 2},
        }):
            applied = dispatcher.apply_stage_policy(watch)

        self.assertEqual(applied["max_concurrency"], 2)
        self.assertEqual(applied["timeout"], 2400)

    def test_dispatcher_stage_policy_keeps_script_level_config_compatible(self):
        watch = {
            "name": "脚本文档分镜视频生成",
            "script": "tk_shot_video.py",
            "max_concurrency": 1,
            "max_retries": 1,
            "timeout": 1200,
        }
        with patch.object(dispatcher, "STAGE_CFG", {
            "tk_shot_video.py": {"max_concurrency": 2, "timeout": 2400},
        }):
            applied = dispatcher.apply_stage_policy(watch)

        self.assertEqual(applied["max_concurrency"], 2)
        self.assertEqual(applied["timeout"], 2400)

    def test_dispatcher_global_concurrency_limit_blocks_new_launches(self):
        class RunningProcess:
            def poll(self):
                return None

        dispatcher.running_processes = {
            f"other::{idx}": {
                "process": RunningProcess(),
                "watch": {"name": f"其它环节{idx}"},
            }
            for idx in range(6)
        }
        watch = {
            "name": "脚本文档分镜视频生成",
            "table": "tbl1",
            "status_field": "视频生成状态",
            "trigger_value": "待生成",
            "running_value": "生成中",
            "max_concurrency": 2,
            "script": "tk_shot_video.py",
            "args": [],
        }
        record = {"record_id": "rec1", "fields": {"视频生成状态": "待生成", "任务名称": "任务1"}}

        with patch.object(dispatcher, "GLOBAL_MAX_CONCURRENCY", 6, create=True), \
             patch.object(dispatcher, "cleanup_finished_processes"), \
             patch.object(dispatcher, "is_circuit_open", return_value=False), \
             patch.object(dispatcher, "get_table_records_cached", return_value=[record]), \
             patch.object(dispatcher, "load_running_tasks", return_value={}), \
             patch.object(dispatcher, "should_skip_claim_by_cache", return_value=False), \
             patch.object(dispatcher, "try_claim_task", return_value=True), \
             patch.object(dispatcher.subprocess, "Popen") as popen:
            dispatcher.check_and_run("token", watch)

        popen.assert_not_called()

    def test_dispatcher_counts_running_tasks_by_watch_not_script(self):
        dispatcher.running_processes = {
            "tk_shot_video.py::a": {"watch": {"script": "tk_shot_video.py", "name": "脚本文档分镜视频生成"}},
            "tk_shot_video.py::b": {"watch": {"script": "tk_shot_video.py", "name": "逐镜头分镜视频生成"}},
        }
        self.assertEqual(dispatcher.count_running_by_watch("脚本文档分镜视频生成"), 1)
        self.assertEqual(dispatcher.count_running_by_watch("逐镜头分镜视频生成"), 1)

    def test_dispatcher_clears_claim_fields_when_triggering_rerun(self):
        watch = {
            "table": "tbl1",
            "status_field": "视频生成状态",
            "trigger_value": "待生成",
            "running_value": "生成中",
            "claim_clear_fields": ["视频任务ID", "视频生成原始响应JSON"],
        }
        updates = []

        with patch.object(dispatcher, "safe_get_record", return_value={"视频生成状态": "待生成"}), \
             patch.object(dispatcher, "safe_update_record", side_effect=lambda token, table, rid, fields: updates.append(fields)), \
             patch.object(dispatcher, "update_record_state_cache"):
            self.assertTrue(dispatcher.try_claim_task("t", watch, "rec1"))

        self.assertEqual(updates[0], {
            "视频生成状态": "生成中",
            "视频任务ID": "",
            "视频生成原始响应JSON": "",
        })

    def test_dispatcher_clears_claim_fields_only_for_matching_trigger_value(self):
        watch = {
            "table": "tbl1",
            "status_field": "视频生成状态",
            "trigger_value": "待生成",
            "running_value": "生成中",
            "claim_clear_fields_by_trigger_value": {
                "待生成": ["视频任务ID", "视频片段file_token"],
            },
        }
        updates = []

        with patch.object(dispatcher, "safe_get_record", return_value={"视频生成状态": "待生成"}), \
             patch.object(dispatcher, "safe_update_record", side_effect=lambda token, table, rid, fields: updates.append(fields)), \
             patch.object(dispatcher, "update_record_state_cache"):
            self.assertTrue(dispatcher.try_claim_task("t", watch, "rec1"))

        self.assertEqual(updates[0], {
            "视频生成状态": "生成中",
            "视频任务ID": "",
            "视频片段file_token": "",
        })

        updates.clear()
        with patch.object(dispatcher, "safe_get_record", return_value={"视频生成状态": "生成中"}), \
             patch.object(dispatcher, "safe_update_record", side_effect=lambda token, table, rid, fields: updates.append(fields)), \
             patch.object(dispatcher, "update_record_state_cache"):
            self.assertTrue(dispatcher.try_claim_task("t", {**watch, "trigger_values": ["待生成", "生成中"]}, "rec1"))

        self.assertEqual(updates[0], {"视频生成状态": "生成中"})

    def test_dispatcher_has_script_doc_last_frame_watch(self):
        watch = next(item for item in dispatcher.WATCH_LIST if item["name"] == "脚本文档尾帧图生成")
        self.assertEqual(watch["table"], dispatcher.TABLE_SCRIPT_DOC_SHOTS)
        self.assertEqual(watch["status_field"], "尾帧图生成状态")
        self.assertEqual(watch["script"], "tk_shot_storyboard.py")
        self.assertEqual(watch["args"], ["last-frame", "--table", "script_doc"])

    def test_normalize_seconds_limits_to_veo_values(self):
        self.assertEqual(video.normalize_seconds(4), "4")
        self.assertEqual(video.normalize_seconds("6秒"), "6")
        self.assertEqual(video.normalize_seconds(7), "8")
        self.assertEqual(video.normalize_seconds(""), "8")

    def test_upload_video_to_feishu_uses_multipart_for_large_files(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4") as tmp:
            tmp.write(b"abcdef")
            tmp.flush()

            prepare = Mock()
            prepare.status_code = 200
            prepare.json.return_value = {"code": 0, "data": {"upload_id": "up_1", "block_size": 2, "block_num": 3}}
            part = Mock()
            part.status_code = 200
            part.json.return_value = {"code": 0, "data": {}}
            finish = Mock()
            finish.status_code = 200
            finish.json.return_value = {"code": 0, "data": {"file_token": "file_token"}}

            with patch("tk_shot_video.FEISHU_UPLOAD_ALL_LIMIT_BYTES", 3), \
                 patch("tk_shot_video.APP_TOKEN", "app_token"), \
                 patch("tk_shot_video.requests.post", side_effect=[prepare, part, part, part, finish]) as post:
                file_token = video.upload_video_to_feishu("tenant_token", tmp.name, "clip.mp4")

        self.assertEqual(file_token, "file_token")
        urls = [call.args[0] for call in post.call_args_list]
        self.assertEqual(urls, [
            "https://open.feishu.cn/open-apis/drive/v1/medias/upload_prepare",
            "https://open.feishu.cn/open-apis/drive/v1/medias/upload_part",
            "https://open.feishu.cn/open-apis/drive/v1/medias/upload_part",
            "https://open.feishu.cn/open-apis/drive/v1/medias/upload_part",
            "https://open.feishu.cn/open-apis/drive/v1/medias/upload_finish",
        ])
        first_part = post.call_args_list[1].kwargs
        self.assertEqual(first_part["data"]["seq"], "0")
        self.assertEqual(first_part["data"]["size"], "2")
        self.assertEqual(first_part["data"]["checksum"], str(video.zlib.adler32(b"ab") & 0xFFFFFFFF))
        self.assertEqual(post.call_args_list[-1].kwargs["json"], {"upload_id": "up_1", "block_num": 3})

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

    def test_resolve_reference_image_uses_latest_storyboard_attachment(self):
        fields = sample_fields()
        fields["分镜图"] = [{"file_token": "old_shot"}, {"file_token": "new_shot"}]
        download = Mock(return_value=Path("/tmp/shot.png"))

        with tempfile.TemporaryDirectory() as tmp:
            result = video.resolve_reference_image("t", "rec1", fields, Path(tmp), download_fn=download)

        self.assertEqual(result, Path("/tmp/shot.png"))
        self.assertEqual(download.call_args.args[1], "new_shot")

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

    def test_poll_otu_video_task_retries_transient_ssl_failure(self):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"status": "completed", "video_url": "https://x.test/video.mp4"}
        response.text = '{"status":"completed"}'

        with patch.object(video.requests, "get", side_effect=[video.requests.exceptions.SSLError("unexpected eof"), response]) as getter, \
             patch("common.sleep_backoff"):
            result = video.poll_otu_video_task({"api_key": "sk", "api_base": "https://otuapi.com"}, "task_1")

        self.assertEqual(result["status"], "completed")
        self.assertEqual(getter.call_count, 2)

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

    def test_call_native_veo_uses_optional_last_frame(self):
        fake_client = Mock()
        fake_client.models.generate_videos.return_value = SimpleNamespace(name="operations/native_1")
        with tempfile.NamedTemporaryFile(suffix=".png") as first, tempfile.NamedTemporaryFile(suffix=".png") as last:
            first.write(b"first frame bytes")
            first.flush()
            last.write(b"last frame bytes")
            last.flush()
            video.call_native_veo_first_frame_task(
                {
                    "model": "veo-3.1-fast-generate-preview",
                    "api_key": "sk-test",
                    "api_base": "https://aihubmix.com/gemini",
                },
                "prompt text",
                first.name,
                "8",
                "720p",
                "9:16",
                last_frame_path=last.name,
                client=fake_client,
            )
        kwargs = fake_client.models.generate_videos.call_args.kwargs
        self.assertEqual(kwargs["image"].image_bytes, b"first frame bytes")
        self.assertEqual(kwargs["config"].last_frame.image_bytes, b"last frame bytes")
        self.assertEqual(kwargs["config"].last_frame.mime_type, "image/png")

    def test_submit_otu_video_task_sends_first_and_last_reference_images(self):
        with tempfile.NamedTemporaryFile(suffix=".png") as first, tempfile.NamedTemporaryFile(suffix=".png") as last:
            first.write(b"first")
            first.flush()
            last.write(b"last")
            last.flush()
            response = Mock()
            response.status_code = 200
            response.json.return_value = {"id": "otu_task_1"}
            response.text = '{"id":"otu_task_1"}'
            with patch("tk_shot_video.requests.post", return_value=response) as post:
                task_id, _ = video.submit_otu_video_task(
                    {"api_base": "https://otuapi.com", "api_key": "sk-test", "model": "veo_3_1-fast-fl"},
                    "prompt text",
                    first.name,
                    "8",
                    "720x1280",
                    "9:16",
                    last_frame_path=last.name,
                )
        self.assertEqual(task_id, "otu_task_1")
        files = post.call_args.kwargs["files"]
        reference_files = [item for item in files if item[0] == "input_reference[]"]
        self.assertEqual(len(reference_files), 2)
        self.assertEqual(reference_files[0][1][0], os.path.basename(first.name))
        self.assertEqual(reference_files[1][1][0], os.path.basename(last.name))

    def test_resolve_last_frame_image_requires_success_when_enabled(self):
        fields = sample_fields()
        fields["首尾帧视频模式"] = "启用"
        fields["尾帧图生成状态"] = "待生成"
        fields["尾帧图"] = [{"file_token": "ft_last"}]
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "尾帧图生成状态=成功"):
                video.resolve_last_frame_image("t", "rec1", fields, Path(tmp), download_fn=Mock())

    def test_resolve_last_frame_image_uses_latest_tail_attachment(self):
        fields = sample_fields()
        fields["首尾帧视频模式"] = "启用"
        fields["尾帧图生成状态"] = "成功"
        fields["尾帧图"] = [{"file_token": "old_tail"}, {"file_token": "new_tail"}]
        download = Mock(return_value=Path("/tmp/tail.png"))

        with tempfile.TemporaryDirectory() as tmp:
            result = video.resolve_last_frame_image("t", "rec1", fields, Path(tmp), download_fn=download)

        self.assertEqual(result, Path("/tmp/tail.png"))
        self.assertEqual(download.call_args.args[1], "new_tail")

    def test_run_dry_run_includes_last_frame_when_end_frame_mode_enabled(self):
        fields = sample_fields()
        fields["首尾帧视频模式"] = "启用"
        fields["尾帧图生成状态"] = "成功"
        fields["尾帧图"] = [{"file_token": "ft_last"}]
        with patch("tk_shot_video.get_model_config") as cfg, \
             patch("tk_shot_video.ensure_work_dir") as work, \
             patch("tk_shot_video.resolve_reference_image") as ref, \
             patch("tk_shot_video.resolve_last_frame_image") as last_ref:
            cfg.return_value = ("cfg1", {
                "model": "veo-3.1-fast-generate-preview",
                "api_key": "sk",
                "api_base": "https://aihubmix.com/gemini",
                "size": "720x1280",
                "aspect_ratio": "9:16",
            })
            work.return_value = Path("/tmp")
            ref.return_value = Path("/tmp/ref.png")
            last_ref.return_value = Path("/tmp/last.png")
            result = video.run_shot_video_generation(
                "rec1",
                dry_run=True,
                token="t",
                get_record_fn=lambda token, table, rid: fields,
            )
        self.assertEqual(result["end_frame_mode"], True)
        self.assertEqual(result["last_frame_image_path"], "/tmp/last.png")

    def test_extract_and_download_native_inline_video_response(self):
        video_bytes = b"0" * 12000
        generated = video.extract_native_generated_video({
            "done": True,
            "response": {
                "videos": [{
                    "bytesBase64Encoded": base64.b64encode(video_bytes).decode("ascii"),
                    "mimeType": "video/mp4",
                }]
            },
        })
        self.assertIn("bytesBase64Encoded", generated)
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            video.download_native_veo_video(Mock(), generated, tmp_path)
            with open(tmp_path, "rb") as f:
                self.assertEqual(f.read(), video_bytes)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def test_download_native_accepts_google_video_bytes_key(self):
        video_bytes = b"2" * 12000
        generated = {
            "uri": "https://x.test/maybe-stale-file:download",
            "videoBytes": base64.b64encode(video_bytes).decode("ascii"),
        }
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            video.download_native_veo_video(Mock(), generated, tmp_path)
            with open(tmp_path, "rb") as f:
                self.assertEqual(f.read(), video_bytes)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def test_poll_native_operation_fetches_raw_when_sdk_drops_response(self):
        operation = SimpleNamespace(name="operations/native_1", done=False)
        completed_without_response = SimpleNamespace(
            name="projects/p/locations/global/publishers/google/models/veo/operations/native_1",
            done=True,
            error=None,
            response=None,
        )
        raw_operation = {"done": True, "response": {"videos": [{"bytesBase64Encoded": "AA=="}]}}
        fake_client = Mock()
        fake_client.operations.get.return_value = completed_without_response
        fake_client.operations._get_videos_operation.return_value = raw_operation
        with patch("tk_shot_video.POLL_INTERVAL", 0):
            result = video.poll_native_veo_operation(fake_client, operation)
        self.assertEqual(result, raw_operation)
        fake_client.operations._get_videos_operation.assert_called_once_with(operation_name="operations/native_1")

    def test_poll_native_operation_fetches_raw_when_sdk_get_404s(self):
        operation = SimpleNamespace(name="operations/native_1", done=False)
        raw_operation = {"done": True, "response": {"videos": [{"bytesBase64Encoded": "AA=="}]}}
        fake_client = Mock()
        fake_client.operations.get.side_effect = Exception("404 Not Found")
        fake_client.operations._get_videos_operation.return_value = raw_operation
        with patch("tk_shot_video.POLL_INTERVAL", 0):
            result = video.poll_native_veo_operation(fake_client, operation)
        self.assertEqual(result, raw_operation)
        fake_client.operations._get_videos_operation.assert_called_once_with(operation_name="operations/native_1")

    def test_extract_video_url_handles_nested_values(self):
        result = {"data": {"output": [{"result_url": "https://x.test/video.mp4"}]}}
        self.assertEqual(video.extract_video_url(result), "https://x.test/video.mp4")

    def test_download_video_retries_transient_ssl_failure(self):
        first_error = video.requests.exceptions.SSLError("unexpected eof")
        response = Mock()
        response.status_code = 200
        response.iter_content.return_value = [b"x" * 12000]

        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(video.requests, "get", side_effect=[first_error, response]) as getter, \
             patch.object(video, "assert_playable_video_file"), \
             patch("common.sleep_backoff"):
            out_path = os.path.join(tmp, "out.mp4")
            result = video.download_video("https://x.test/video.mp4", out_path)
            output_size = os.path.getsize(result)

        self.assertEqual(result, out_path)
        self.assertEqual(getter.call_count, 2)
        self.assertEqual(getter.call_args.kwargs["timeout"], video.DOWNLOAD_REQUEST_TIMEOUT)
        self.assertGreater(output_size, 10000)

    def test_download_video_retries_invalid_mp4_probe(self):
        invalid_response = Mock()
        invalid_response.status_code = 200
        invalid_response.iter_content.return_value = [b"x" * 12000]
        valid_response = Mock()
        valid_response.status_code = 200
        valid_response.iter_content.return_value = [b"y" * 12000]
        bad_probe = SimpleNamespace(returncode=1, stderr="moov atom not found", stdout="")
        good_probe = SimpleNamespace(returncode=0, stderr="", stdout='{"streams":[{"codec_type":"video"}]}')

        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(video.requests, "get", side_effect=[invalid_response, valid_response]) as getter, \
             patch.object(video.shutil, "which", return_value="/usr/bin/ffprobe"), \
             patch.object(video.subprocess, "run", side_effect=[bad_probe, good_probe]) as probe, \
             patch("common.sleep_backoff"):
            out_path = os.path.join(tmp, "out.mp4")
            result = video.download_video("https://x.test/video.mp4", out_path)

        self.assertEqual(result, out_path)
        self.assertEqual(getter.call_count, 2)
        self.assertEqual(probe.call_count, 2)

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
        self.assertEqual(fields["分镜视频URL"], "https://x.test/video.mp4")

    def test_success_fields_write_url_object_for_url_field(self):
        fields = video.build_success_fields(
            {"model": "veo-3.1-fast-generate-preview"},
            "vid_123",
            {"status": "completed"},
            "https://x.test/video.mp4",
            "/tmp/out.mp4",
            "ft_video",
            field_types={"分镜视频URL": 15},
        )
        self.assertEqual(fields["分镜视频URL"], {"link": "https://x.test/video.mp4", "text": "https://x.test/video.mp4"})

    def test_success_fields_omit_blank_video_url_text_field(self):
        fields = video.build_success_fields(
            {"model": "veo-3.1-fast-generate-preview"},
            "vid_123",
            {"status": "completed"},
            "",
            "/tmp/out.mp4",
            "ft_video",
        )
        self.assertNotIn("分镜视频URL", fields)

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

    def test_run_uses_source_script_and_shot_number_for_video_filename(self):
        fields = sample_fields()
        fields["源逐镜头脚本记录ID"] = "recScript123"
        fields["分镜序号"] = "3"
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
                "size": "720x1280",
                "aspect_ratio": "9:16",
            })
            work.return_value = Path("/tmp")
            ref.return_value = Path("/tmp/ref.png")
            downloader = Mock(return_value="/tmp/recScript123_shot03_video.mp4")
            uploader = Mock(return_value="ft_video")

            result = video.run_shot_video_generation(
                "rec1",
                token="t",
                get_record_fn=lambda token, table, rid: fields,
                update_record_fn=Mock(),
                native_client_factory=lambda config: fake_client,
                native_submitter=Mock(return_value=operation),
                native_poller=Mock(return_value=completed),
                native_downloader=downloader,
                uploader=uploader,
            )

        expected_path = "/tmp/recScript123_shot03_video.mp4"
        downloader.assert_called_once_with(fake_client, completed.response.generated_videos[0].video, expected_path)
        uploader.assert_called_once_with("t", expected_path, "recScript123_shot03_video.mp4")
        self.assertEqual(result["output_path"], expected_path)

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
        self.assertEqual(result["video_channel"], "AIHubMix")
        self.assertEqual(result["api_base"], "https://aihubmix.com/gemini")

    def test_run_otu_channel_uses_otu_submit_poll_download(self):
        fields = sample_fields()
        fields["视频通道"] = "OTU"
        fields["视频生成模型"] = "OTU / veo_3_1-fast-fl"
        submitter = Mock(return_value=("otu_task_1", {"id": "otu_task_1"}))
        poller = Mock(return_value={"status": "completed", "data": {"result_url": "https://x.test/otu.mp4"}})
        downloader = Mock(return_value="/tmp/rec1_video.mp4")
        uploader = Mock(return_value="ft_video")
        updates = []

        with patch("tk_shot_video.get_model_config") as cfg, \
             patch("tk_shot_video.ensure_work_dir") as work, \
             patch("tk_shot_video.resolve_reference_image") as ref, \
             patch("tk_shot_video.filter_existing_fields", side_effect=lambda token, table, fields: fields), \
             patch("tk_shot_video.os.path.getsize", return_value=123456):
            cfg.return_value = ("cfg_otu", {
                "model": "veo_3_1-fast-fl",
                "api_key": "sk",
                "api_base": "https://otuapi.com",
                "size": "720x1280",
                "aspect_ratio": "9:16",
            })
            work.return_value = Path("/tmp")
            ref.return_value = Path("/tmp/ref.png")

            result = video.run_shot_video_generation(
                "rec1",
                token="t",
                get_record_fn=lambda token, table, rid: fields,
                update_record_fn=lambda token, table, rid, patch_fields: updates.append(patch_fields),
                native_submitter=Mock(),
                otu_submitter=submitter,
                otu_poller=poller,
                otu_downloader=downloader,
                uploader=uploader,
            )

        cfg.assert_called_once_with(video.OTU_STAGE_NAME)
        submitter.assert_called_once()
        submitted_config = submitter.call_args.args[0]
        self.assertEqual(submitted_config["model"], "veo_3_1-fast-fl")
        self.assertEqual(submitted_config["api_base"], "https://otuapi.com")
        poller.assert_called_once_with(submitted_config, "otu_task_1")
        downloader.assert_called_once_with("https://x.test/otu.mp4", "/tmp/rec1_video.mp4")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["video_channel"], "OTU")
        self.assertEqual(result["model"], "veo_3_1-fast-fl")
        self.assertEqual(updates[-1]["视频通道"], "OTU")
        self.assertEqual(updates[-1]["视频生成模型"], "OTU / veo_3_1-fast-fl")

    def test_prefixed_default_otu_model_uses_otu_stage_when_channel_blank(self):
        fields = sample_fields()
        fields["视频通道"] = ""
        fields["视频生成模型"] = "OTU / 默认（配置表）"

        with patch("tk_shot_video.get_model_config") as cfg, \
             patch("tk_shot_video.ensure_work_dir") as work, \
             patch("tk_shot_video.resolve_reference_image") as ref:
            cfg.return_value = ("cfg_otu", {
                "model": "veo_3_1-fast-fl",
                "api_key": "sk",
                "api_base": "https://otuapi.com",
                "size": "720x1280",
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

        cfg.assert_called_once_with(video.OTU_STAGE_NAME)
        self.assertEqual(result["video_channel"], "OTU")
        self.assertEqual(result["model"], "veo_3_1-fast-fl")

    def test_run_aihubmix_channel_rejects_otu_model_prefix(self):
        fields = sample_fields()
        fields["视频通道"] = "AIHubMix"
        fields["视频生成模型"] = "OTU / veo_3_1-fast-fl"
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
            with self.assertRaisesRegex(ValueError, "不能选择 OTU 模型"):
                video.run_shot_video_generation(
                    "rec1",
                    dry_run=True,
                    token="t",
                    get_record_fn=lambda token, table, rid: fields,
                )

    def test_legacy_video_ai_model_is_ignored_when_video_generation_model_is_empty(self):
        fields = sample_fields()
        fields["视频通道"] = "AIHubMix"
        fields["视频生成模型"] = ""
        fields["视频AI模型"] = "AIHubMix / veo-3.1-fast-generate-preview"
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

        self.assertFalse(result["unified_ai_route_enabled"])
        self.assertEqual(result["video_channel"], "AIHubMix")
        self.assertEqual(result["model"], "veo-3.1-fast-generate-preview")
        self.assertEqual(result["model_source"], "配置表")

    def test_video_generation_model_is_blocked_by_global_dry_run_switch(self):
        fields = sample_fields()
        fields["使用统一AI路由"] = "是"
        fields["视频通道"] = "OTU"
        fields["视频生成模型"] = "OTU / veo_3_1-fast-fl"
        submitter = Mock()
        with patch("tk_shot_video.safe_list_records", return_value=[{
                "fields": {"环节": "统一AI路由启用状态", "模型名称": "仅dry-run"}
             }]), \
             patch("tk_shot_video.get_model_config") as cfg, \
             patch("tk_shot_video.ensure_work_dir") as work, \
             patch("tk_shot_video.resolve_reference_image") as ref:
            cfg.return_value = ("cfg_otu", {
                "model": "veo_3_1-fast-fl",
                "api_key": "sk",
                "api_base": "https://otuapi.com",
                "size": "720x1280",
                "aspect_ratio": "9:16",
            })
            work.return_value = Path("/tmp")
            ref.return_value = Path("/tmp/ref.png")

            result = video.run_shot_video_generation(
                "rec1",
                token="t",
                get_record_fn=lambda token, table, rid: fields,
                otu_submitter=submitter,
            )

        self.assertTrue(result["unified_ai_route_enabled"])
        self.assertEqual(result["status"], "unified_ai_dry_run_ready")
        self.assertEqual(result["video_channel"], "OTU")
        self.assertEqual(result["model"], "veo_3_1-fast-fl")
        submitter.assert_not_called()

    def test_script_doc_rejects_reference_video_model_for_first_last_mode(self):
        fields = sample_fields()
        fields["使用统一AI路由"] = "是"
        fields["视频生成模型"] = "Aitgenne / happyhorse-1.0-r2v"
        with patch("tk_shot_video.safe_list_records", return_value=[
                {"fields": {"环节": "统一AI路由启用状态", "模型名称": "指定记录启用"}},
                {"fields": {"AI供应商": "Aitgenne", "API 代理地址": "https://api.aitgenne.com", "API Key": "sk-aitgenne"}},
             ]), \
             patch("tk_shot_video.get_model_config") as cfg, \
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
            with self.assertRaisesRegex(ValueError, "首尾帧视频模型不支持参考图视频模型"):
                video.run_shot_video_generation(
                    "rec1",
                    dry_run=True,
                    token="t",
                    get_record_fn=lambda token, table, rid: fields,
                )

    def test_run_defaults_chinese_default_record_model_to_native_veo(self):
        for model_value in ("默认（配置表）", "默认", "待确认"):
            with self.subTest(model_value=model_value):
                fields = sample_fields()
                fields["视频生成模型"] = model_value
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
                        get_record_fn=lambda token, table, rid, fields=fields: fields,
                    )

                self.assertEqual(result["video_provider"], "veo3.1")

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

    def test_end_frame_mode_rejects_seeddance_provider(self):
        fields = sample_fields()
        fields["首尾帧视频模式"] = "启用"
        fields["尾帧图生成状态"] = "成功"
        fields["尾帧图"] = [{"file_token": "ft_last"}]
        fields["视频生成模型"] = "seeddance2.0"
        fields["口播文本"] = ""
        with patch("tk_shot_video.get_model_config") as cfg, \
             patch("tk_shot_video.ensure_work_dir") as work, \
             patch("tk_shot_video.resolve_reference_image") as ref, \
             patch("tk_shot_video.resolve_last_frame_image") as last_ref:
            cfg.return_value = ("cfg1", {
                "model": "doubao-seedance-2-0-fast-260128",
                "api_key": "sk",
                "api_base": "https://aihubmix.com",
                "size": "720p",
                "aspect_ratio": "9:16",
            })
            work.return_value = Path("/tmp")
            ref.return_value = Path("/tmp/ref.png")
            last_ref.return_value = Path("/tmp/last.png")
            with self.assertRaisesRegex(ValueError, "首尾帧视频模式仅支持 Veo"):
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

    def test_seeddance_generation_rebuilds_stale_veo_prompt_and_writes_it_back(self):
        fields = sample_fields()
        fields.update({
            "视频生成模型": "seeddance2.0",
            "视频提示词": "Veo must directly generate the final local-language spoken audio.",
            "口播音频状态": "成功",
            "口播音频路径": "/tmp/audio.mp3",
            "画面描述": "狗狗坐在产品旁边抬爪",
            "产品名": "Uootapet",
            "口播音色ID": "voice-a",
            "文本": '{"speaker":"dog","speaker_visible":true,"action":"dog raises paw","video_prompt_notes":"tail wag"}',
        })
        submitter = Mock(return_value=("seed_task_1", {"id": "seed_task_1"}))
        poller = Mock(return_value={"status": "completed", "result_url": "https://x.test/seed.mp4"})
        downloader = Mock(return_value="/tmp/rec1_video.mp4")
        uploader = Mock(return_value="ft_video")
        updates = []
        with patch("tk_shot_video.get_model_config") as cfg, \
             patch("tk_shot_video.ensure_work_dir") as work, \
             patch("tk_shot_video.resolve_reference_image") as ref, \
             patch("tk_shot_video.filter_existing_fields", side_effect=lambda token, table, fields: fields), \
             patch("tk_shot_video.os.path.getsize", return_value=123456):
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
                token="t",
                get_record_fn=lambda token, table, rid: fields,
                update_record_fn=lambda token, table, rid, patch_fields: updates.append(patch_fields),
                seeddance_submitter=submitter,
                seeddance_poller=poller,
                seeddance_downloader=downloader,
                uploader=uploader,
            )

        submitted_prompt = submitter.call_args.args[1]
        self.assertIn("使用参考音频作为最终口播内容", submitted_prompt)
        self.assertIn("reference voiceover audio", submitted_prompt)
        self.assertNotIn("Veo must directly generate", submitted_prompt)
        self.assertTrue(any("视频提示词" in item and "使用参考音频作为最终口播内容" in item["视频提示词"] for item in updates))
        self.assertEqual(result["status"], "success")

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
                "size": "720x1280",
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
            last_frame_path=None,
            client=fake_client,
        )
        poller.assert_called_once_with(fake_client, operation)
        downloader.assert_called_once_with(fake_client, completed.response.generated_videos[0].video, "/tmp/rec1_video.mp4")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["task_id"], "operations/native_1")
        self.assertEqual(result["video_url"], "https://x.test/native.mp4")
        self.assertEqual(updates[-1]["视频生成状态"], "成功")

    def test_script_doc_video_generation_writes_select_provider_not_model_name(self):
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
        fields = sample_fields()
        fields["视频生成模型"] = "默认（配置表）"

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
            updates = []

            video.run_shot_video_generation(
                "rec1",
                table="script_doc",
                token="t",
                get_record_fn=lambda token, table, rid: fields,
                update_record_fn=lambda token, table, rid, patch_fields: updates.append(patch_fields),
                native_client_factory=lambda config: fake_client,
                native_submitter=Mock(return_value=operation),
                native_poller=Mock(return_value=completed),
                native_downloader=Mock(return_value="/tmp/rec1_video.mp4"),
                uploader=Mock(return_value="ft_video"),
            )

        model_writes = [item["视频生成模型"] for item in updates if "视频生成模型" in item]
        self.assertTrue(model_writes)
        self.assertTrue(all(item == "AIHubMix / veo-3.1-fast-generate-preview" for item in model_writes))

    def test_native_generation_refetches_raw_operation_when_sdk_video_uri_404s(self):
        fake_client = Mock()
        operation = SimpleNamespace(name="operations/native_1", done=False)
        completed = SimpleNamespace(
            name="projects/p/locations/global/publishers/google/models/veo/operations/native_1",
            done=True,
            response=SimpleNamespace(
                generated_videos=[
                    SimpleNamespace(video=SimpleNamespace(uri="https://x.test/stale.mp4"))
                ]
            ),
        )
        raw_operation = {
            "name": "operations/native_1",
            "done": True,
            "response": {
                "videos": [{
                    "videoBytes": base64.b64encode(b"3" * 12000).decode("ascii"),
                    "mimeType": "video/mp4",
                }]
            },
        }
        fake_client.operations._get_videos_operation.return_value = raw_operation

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
            downloader = Mock(side_effect=[Exception("404 Not Found. {'message': '404 page not found'}"), "/tmp/rec1_video.mp4"])
            uploader = Mock(return_value="ft_video")

            result = video.run_shot_video_generation(
                "rec1",
                token="t",
                get_record_fn=lambda token, table, rid: sample_fields(),
                update_record_fn=Mock(),
                native_client_factory=lambda config: fake_client,
                native_submitter=Mock(return_value=operation),
                native_poller=Mock(return_value=completed),
                native_downloader=downloader,
                uploader=uploader,
            )

        self.assertEqual(downloader.call_count, 2)
        self.assertEqual(downloader.call_args_list[1].args[1]["videoBytes"], raw_operation["response"]["videos"][0]["videoBytes"])
        fake_client.operations._get_videos_operation.assert_called_once_with(operation_name="operations/native_1")
        self.assertEqual(result["status"], "success")

    def test_run_generation_reuses_existing_native_task_id(self):
        fields = sample_fields()
        fields["视频生成状态"] = "生成中"
        fields["视频任务ID"] = "operations/existing_1"
        fake_client = Mock()
        completed = {
            "name": "operations/existing_1",
            "done": True,
            "response": {
                "videos": [{
                    "bytesBase64Encoded": base64.b64encode(b"1" * 12000).decode("ascii"),
                    "mimeType": "video/mp4",
                }]
            },
        }

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
            submitter = Mock()
            poller = Mock(return_value=completed)
            downloader = Mock(return_value="/tmp/rec1_video.mp4")
            uploader = Mock(return_value="ft_video")

            result = video.run_shot_video_generation(
                "rec1",
                token="t",
                get_record_fn=lambda token, table, rid: fields,
                update_record_fn=Mock(),
                native_client_factory=lambda config: fake_client,
                native_submitter=submitter,
                native_poller=poller,
                native_downloader=downloader,
                uploader=uploader,
            )

        submitter.assert_not_called()
        self.assertEqual(poller.call_args.args[1].name, "operations/existing_1")
        self.assertEqual(result["task_id"], "operations/existing_1")
        self.assertEqual(result["status"], "success")

    def test_run_generation_resubmits_when_pending_even_with_existing_native_task_id(self):
        fields = sample_fields()
        fields["视频生成状态"] = "待生成"
        fields["视频任务ID"] = "operations/old_1"
        fake_client = Mock()
        operation = SimpleNamespace(name="operations/native_2", done=False)
        completed = {
            "name": "operations/native_2",
            "done": True,
            "response": {
                "videos": [{
                    "bytesBase64Encoded": base64.b64encode(b"5" * 12000).decode("ascii"),
                    "mimeType": "video/mp4",
                }]
            },
        }
        updates = []

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

            result = video.run_shot_video_generation(
                "rec1",
                token="t",
                get_record_fn=lambda token, table, rid: fields,
                update_record_fn=lambda token, table, rid, patch_fields: updates.append(patch_fields),
                native_client_factory=lambda config: fake_client,
                native_submitter=submitter,
                native_poller=Mock(return_value=completed),
                native_downloader=Mock(return_value="/tmp/rec1_video.mp4"),
                uploader=Mock(return_value="ft_video"),
            )

        submitter.assert_called_once()
        self.assertTrue(any(item.get("视频任务ID") == "" for item in updates))
        self.assertEqual(result["task_id"], "operations/native_2")
        self.assertEqual(result["status"], "success")

    def test_run_otu_resubmits_when_pending_even_with_existing_task_id(self):
        fields = sample_fields()
        fields["视频生成状态"] = "待生成"
        fields["视频通道"] = "OTU"
        fields["视频生成模型"] = "OTU / veo_3_1-fast-fl"
        fields["视频任务ID"] = "task_old_otu"
        submitter = Mock(return_value=("task_new_otu", {"id": "task_new_otu"}))
        poller = Mock(return_value={"status": "completed", "data": {"result_url": "https://x.test/new-otu.mp4"}})
        downloader = Mock(return_value="/tmp/rec1_video.mp4")
        uploader = Mock(return_value="ft_video")
        updates = []

        with patch("tk_shot_video.get_model_config") as cfg, \
             patch("tk_shot_video.ensure_work_dir") as work, \
             patch("tk_shot_video.resolve_reference_image") as ref, \
             patch("tk_shot_video.filter_existing_fields", side_effect=lambda token, table, fields: fields), \
             patch("tk_shot_video.os.path.getsize", return_value=123456):
            cfg.return_value = ("cfg_otu", {
                "model": "veo_3_1-fast-fl",
                "api_key": "sk",
                "api_base": "https://otuapi.com",
                "size": "720x1280",
                "aspect_ratio": "9:16",
            })
            work.return_value = Path("/tmp")
            ref.return_value = Path("/tmp/ref.png")

            result = video.run_shot_video_generation(
                "rec1",
                token="t",
                get_record_fn=lambda token, table, rid: fields,
                update_record_fn=lambda token, table, rid, patch_fields: updates.append(patch_fields),
                native_submitter=Mock(),
                otu_submitter=submitter,
                otu_poller=poller,
                otu_downloader=downloader,
                uploader=uploader,
            )

        submitter.assert_called_once()
        poller.assert_called_once_with(submitter.call_args.args[0], "task_new_otu")
        self.assertTrue(any(item.get("视频任务ID") == "" for item in updates))
        self.assertEqual(result["task_id"], "task_new_otu")
        self.assertEqual(result["video_url"], "https://x.test/new-otu.mp4")

    def test_run_generation_ignores_legacy_non_native_task_id(self):
        fields = sample_fields()
        fields["视频任务ID"] = "task_legacy_1"
        fake_client = Mock()
        operation = SimpleNamespace(name="operations/native_2", done=False)
        completed = {
            "name": "operations/native_2",
            "done": True,
            "response": {
                "videos": [{
                    "bytesBase64Encoded": base64.b64encode(b"4" * 12000).decode("ascii"),
                    "mimeType": "video/mp4",
                }]
            },
        }
        updates = []

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

            result = video.run_shot_video_generation(
                "rec1",
                token="t",
                get_record_fn=lambda token, table, rid: fields,
                update_record_fn=lambda token, table, rid, patch_fields: updates.append(patch_fields),
                native_client_factory=lambda config: fake_client,
                native_submitter=submitter,
                native_poller=Mock(return_value=completed),
                native_downloader=Mock(return_value="/tmp/rec1_video.mp4"),
                uploader=Mock(return_value="ft_video"),
            )

        submitter.assert_called_once()
        self.assertTrue(any(item.get("视频任务ID") == "" for item in updates))
        self.assertEqual(result["task_id"], "operations/native_2")
        self.assertEqual(result["status"], "success")


if __name__ == "__main__":
    unittest.main()
