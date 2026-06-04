import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import tk_create_video_edit_table as create_table
import tk_video_edit as video_edit


class VideoEditTableTests(unittest.TestCase):
    def test_video_edit_table_keeps_only_minimal_fields_and_views(self):
        field_names = [field["name"] for field in create_table.VIDEO_EDIT_FIELDS]

        self.assertEqual(field_names, [
            "任务名称",
            "源视频",
            "编辑指令",
            "参考图",
            "输出分辨率",
            "音频策略",
            "编辑状态",
            "结果视频",
            "视频任务ID",
            "错误信息",
        ])
        self.assertEqual(set(create_table.TABLE_DEFINITION["views"]), {"01-任务入口", "02-结果查看", "99-排错"})
        self.assertNotIn("AI供应商", field_names)
        self.assertNotIn("AI模型", field_names)
        self.assertNotIn("AI参数JSON", field_names)
        self.assertNotIn("源视频URL", field_names)
        self.assertNotIn("结果视频URL", field_names)
        self.assertNotIn("本地视频路径", field_names)


class VideoEditWorkerTests(unittest.TestCase):
    def test_audio_strategy_maps_to_provider_values(self):
        self.assertEqual(video_edit.normalize_audio_setting("保留原音频"), "origin")
        self.assertEqual(video_edit.normalize_audio_setting("自动处理音频"), "auto")
        self.assertEqual(video_edit.normalize_audio_setting(""), "origin")

    def test_validate_record_requires_source_video_and_prompt(self):
        with self.assertRaisesRegex(ValueError, "源视频"):
            video_edit.validate_video_edit_fields({"编辑指令": "change the outfit"})
        with self.assertRaisesRegex(ValueError, "编辑指令"):
            video_edit.validate_video_edit_fields({"源视频": [{"file_token": "video-token"}]})

    def test_reference_attachments_are_limited_to_five(self):
        refs = [{"file_token": f"ref-{idx}"} for idx in range(7)]

        selected = video_edit.reference_attachments({"参考图": refs})

        self.assertEqual([item["file_token"] for item in selected], ["ref-0", "ref-1", "ref-2", "ref-3", "ref-4"])

    def test_resolve_video_edit_route_uses_exact_happyhorse_model_key(self):
        config_records = [
            {
                "fields": {
                    "AI供应商": "Aitgenne",
                    "模型名称": "Aitgenne / happyhorse-1.0-i2v",
                    "API 代理地址": "https://api.aitgenne.com/v1",
                    "API Key": "sk-i2v",
                }
            },
            {
                "fields": {
                    "AI供应商": "Aitgenne",
                    "模型名称": "Aitgenne / happyhorse-1.0-video-edit",
                    "API 代理地址": "https://api.aitgenne.com/v1",
                    "API Key": "sk-edit",
                }
            },
        ]

        with patch.object(video_edit, "TABLE_CONFIG", "tbl_config"), \
             patch.object(video_edit, "safe_list_records", return_value=config_records):
            route = video_edit.resolve_video_edit_route("token")

        self.assertEqual(route.api_key, "sk-edit")
        self.assertEqual(route.api_base, "https://api.aitgenne.com/v1")

    def test_resolve_video_edit_route_does_not_reuse_other_aitgenne_key(self):
        config_records = [
            {
                "fields": {
                    "AI供应商": "Aitgenne",
                    "模型名称": "Aitgenne / happyhorse-1.0-i2v",
                    "API 代理地址": "https://api.aitgenne.com/v1",
                    "API Key": "sk-i2v",
                }
            },
            {
                "fields": {
                    "AI供应商": "Aitgenne",
                    "模型名称": "Aitgenne / happyhorse-1.0-video-edit",
                    "API 代理地址": "https://api.aitgenne.com/v1",
                    "API Key": "",
                }
            },
        ]

        with patch.object(video_edit, "TABLE_CONFIG", "tbl_config"), \
             patch.object(video_edit, "safe_list_records", return_value=config_records), \
             self.assertRaisesRegex(ValueError, "模型配置缺少 API Key: Aitgenne / happyhorse-1.0-video-edit"):
            video_edit.resolve_video_edit_route("token")

    def test_submit_video_edit_uses_happyhorse_json_schema(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = Path(tmpdir) / "source.mp4"
            ref_path = Path(tmpdir) / "ref.png"
            source_path.write_bytes(b"source-video")
            ref_path.write_bytes(b"reference-image")
            route = video_edit.default_video_edit_route()
            route.api_key = "key"
            response = Mock()
            response.status_code = 200
            response.json.return_value = {"id": "task-123"}

            with patch.object(video_edit.requests, "post", return_value=response) as post:
                task_id, _ = video_edit.submit_aitgenne_video_edit_task(
                    route,
                    "replace the shirt with @Image1",
                    str(source_path),
                    [str(ref_path)],
                    {
                        "resolution": "720P",
                        "audio_setting": "origin",
                        "source_video_url": "https://x.test/source.mp4",
                        "reference_image_urls": ["https://x.test/ref.png"],
                    },
                )

        self.assertEqual(task_id, "task-123")
        self.assertEqual(post.call_args.args[0], "https://api.aitgenne.com/v1/videos")
        kwargs = post.call_args.kwargs
        self.assertNotIn("files", kwargs)
        self.assertEqual(kwargs["json"], {
            "model": "happyhorse-1.0-video-edit",
            "prompt": "replace the shirt with @Image1",
            "input": {
                "media": [
                    {"type": "video", "url": "https://x.test/source.mp4"},
                    {"type": "reference_image", "url": "https://x.test/ref.png"},
                ],
            },
            "parameters": {
                "resolution": "720P",
                "audio_setting": "origin",
            },
        })

    def test_run_video_edit_success_writes_result_attachment(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = os.path.join(tmpdir, "source.mp4")
            result_path = os.path.join(tmpdir, "result.mp4")
            Path(source_path).write_bytes(b"source-video")
            Path(result_path).write_bytes(b"result-video")
            fields = {
                "源视频": [{"file_token": "src-token", "name": "source.mp4"}],
                "编辑指令": "replace the shirt with the reference pattern",
                "参考图": [{"file_token": "ref-token", "name": "ref.png"}],
                "输出分辨率": "720P",
                "音频策略": "保留原音频",
            }
            submitter = Mock(return_value=("task-123", {"id": "task-123"}))
            poller = Mock(return_value={"data": {"status": "completed", "url": "https://example.com/result.mp4"}})

            with patch.object(video_edit, "ensure_video_edit_table"), \
                 patch.object(video_edit, "get_feishu_token", return_value="token"), \
                 patch.object(video_edit, "safe_get_record", return_value=fields), \
                 patch.object(video_edit, "safe_update_record") as update_record, \
                 patch.object(video_edit, "filter_existing_fields", side_effect=lambda token, table, payload: payload), \
                 patch.object(video_edit, "download_feishu_attachment", return_value=Path(source_path)), \
                 patch.object(video_edit, "download_reference_attachments", return_value=[]), \
                 patch.object(video_edit, "attachment_tmp_url", side_effect=["https://x.test/source.mp4", "https://x.test/ref.png"]), \
                 patch.object(video_edit, "download_video", return_value=result_path), \
                 patch.object(video_edit, "upload_video_to_feishu", return_value="result-token"):
                result = video_edit.run_video_edit("rec1", work_dir=Path(tmpdir), submitter=submitter, poller=poller)

        self.assertEqual(result["status"], "success")
        submit_args = submitter.call_args.args
        self.assertEqual(submit_args[1], "replace the shirt with the reference pattern")
        self.assertEqual(submit_args[2], source_path)
        self.assertEqual(submit_args[4]["audio_setting"], "origin")
        self.assertEqual(submit_args[4]["source_video_url"], "https://x.test/source.mp4")
        self.assertEqual(submit_args[4]["reference_image_urls"], ["https://x.test/ref.png"])
        final_payload = update_record.call_args_list[-1].args[3]
        self.assertEqual(final_payload["编辑状态"], "成功")
        self.assertEqual(final_payload["视频任务ID"], "task-123")
        self.assertEqual(final_payload["结果视频"], [{"file_token": "result-token", "name": "rec1_video_edit.mp4"}])


if __name__ == "__main__":
    unittest.main()
