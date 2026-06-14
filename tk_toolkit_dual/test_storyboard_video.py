import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import tk_auto_review
import tk_dispatcher as dispatcher
import tk_prompt_image_video as prompt_video
import tk_storyboard_video as storyboard_video
import tk_create_storyboard_video_table as create_table
import tk_model_config_center as center


def sample_storyboard_package():
    return """
# Product Storyboard Package

## Storyboard Image Prompts

```text
Storyboard 01 Image Prompt:
Create a 16:9 horizontal storyboard production board.
Time Range: 0-10s.
Shot grid follows the first conflict.
```

```text
Storyboard 02 Image Prompt:
Create a 16:9 horizontal storyboard production board.
Time Range: 10-20s.
Shot grid follows the product rescue.
```

## Storyboard Video Prompts

```text
Storyboard 01 Video Prompt:
Use the uploaded storyboard image as the visual source.
Extremely important exclusion: remove all storyboard grid borders and text.
```

```text
Storyboard 02 Video Prompt:
Use the uploaded storyboard image as the visual source.
Extremely important exclusion: remove all storyboard grid borders and text.
```
""".strip()


def sample_multiview_storyboard_package():
    return """
# Product Storyboard Package

## Storyboard Image Prompts

```text
Storyboard 01 Image Prompt:
Create a 16:9 horizontal storyboard production board.
Time Range: 0-10s.
Middle reference strip: Use three reference areas.
Thai female owner reference area: show the same woman in a worried-to-calm expression sheet, front view and face close-up.
Small dog reference area: show the same dog in worried lowered head and later calm sitting pose, then relaxed tail-wagging pose on the sofa.
Product reference area: show the uploaded product reference image as packaging guide, including front box, green ampoule blister, single green ampoule, back view, side view, and multi-pack spread.
Use three reference areas, not fixed equal cards if the layout needs adjustment.
Shot grid follows the first conflict.
```

## Storyboard Video Prompts

```text
Storyboard 01 Video Prompt:
Use the uploaded storyboard image as the visual source.
```
""".strip()


class StoryboardVideoTests(unittest.TestCase):
    def test_table_definition_uses_004_name_record_types_and_reused_008_fields(self):
        self.assertEqual(create_table.TABLE_NAME, "004-故事板视频生成表")
        fields = {field["name"]: field for field in create_table.STORYBOARD_VIDEO_FIELDS}

        self.assertEqual(fields["记录类型"]["type"], "select")
        self.assertEqual([item["name"] for item in fields["记录类型"]["options"]], ["母任务", "Storyboard分段"])
        self.assertEqual(fields["故事板Markdown附件"]["type"], "attachment")
        self.assertEqual(fields["关联产品记录"]["type"], "link")
        self.assertEqual(fields["生成图片"]["type"], "attachment")
        self.assertEqual(fields["生成视频"]["type"], "attachment")
        self.assertIn("生图提示词", fields)
        self.assertIn("图生视频提示词", fields)

        self.assertIn("01-任务入口", create_table.TABLE_DEFINITION["views"])
        self.assertIn("02-故事板图片审核", create_table.TABLE_DEFINITION["views"])
        self.assertIn("03-故事板视频结果", create_table.TABLE_DEFINITION["views"])
        self.assertIn("98-失败处理", create_table.TABLE_DEFINITION["views"])
        self.assertIn("99-全字段系统视图", create_table.TABLE_DEFINITION["views"])
        self.assertEqual(create_table.VIEW_FILTERS["01-任务入口"]["conditions"], [["记录类型", "intersects", ["母任务"]]])
        self.assertEqual(create_table.VIEW_FILTERS["02-故事板图片审核"]["conditions"], [["记录类型", "intersects", ["Storyboard分段"]]])

    def test_parse_storyboard_package_pairs_image_and_video_prompts_by_number(self):
        payload = storyboard_video.parse_storyboard_markdown_package(sample_storyboard_package())

        self.assertEqual(payload["total_storyboards"], 2)
        self.assertEqual(payload["storyboards"][0]["storyboard_number"], 1)
        self.assertEqual(payload["storyboards"][0]["time_range"], "0-10s")
        self.assertIn("Storyboard 01 Image Prompt", payload["storyboards"][0]["image_prompt"])
        self.assertIn("Storyboard 01 Video Prompt", payload["storyboards"][0]["video_prompt"])
        self.assertEqual(payload["storyboards"][1]["storyboard_title"], "Storyboard 02")

    def test_child_storyboards_inherit_next_versions_from_previous_children(self):
        payload = storyboard_video.parse_storyboard_markdown_package(sample_storyboard_package())
        old_records = [
            {"record_id": "old_1", "fields": {"记录类型": "Storyboard分段", "父任务记录ID": "parent", "Storyboard编号": 1, "图片版本": 5, "视频版本": 2}},
            {"record_id": "old_2", "fields": {"记录类型": "Storyboard分段", "父任务记录ID": "parent", "Storyboard编号": 2, "图片版本": 1, "视频版本": 4}},
        ]

        version_seeds = storyboard_video.collect_storyboard_version_seeds(old_records, "parent")
        records = storyboard_video.build_child_storyboard_records(
            {"任务名称": "Story"},
            payload,
            parent_record_id="parent",
            batch_id="batch2",
            version_seeds=version_seeds,
        )

        by_number = {item["fields"]["Storyboard编号"]: item["fields"] for item in records}
        self.assertEqual(by_number[1]["图片版本"], 6)
        self.assertEqual(by_number[1]["视频版本"], 3)
        self.assertEqual(by_number[2]["图片版本"], 2)
        self.assertEqual(by_number[2]["视频版本"], 5)

    def test_image_prompt_normalizer_removes_old_multiview_reference_board_language(self):
        payload = storyboard_video.parse_storyboard_markdown_package(sample_multiview_storyboard_package())
        image_prompt = payload["storyboards"][0]["image_prompt"]
        lowered = image_prompt.lower()

        self.assertIn("Storyboard 01 Image Prompt", image_prompt)
        self.assertIn("Shot grid follows the first conflict", image_prompt)
        self.assertIn("low-information reference strip", lowered)
        self.assertIn("single front package anchor", lowered)
        for forbidden in [
            "expression sheet",
            "front view and face close-up",
            "worried-to-calm",
            "worried lowered head",
            "calm sitting pose",
            "tail-wagging pose",
            "back view",
            "side view",
            "multi-pack spread",
            "use three reference areas",
            "one key use-form cue",
        ]:
            self.assertNotIn(forbidden, lowered)

    def test_parse_storyboard_package_rejects_unpaired_prompts(self):
        markdown = """
## Storyboard Image Prompts
```text
Storyboard 01 Image Prompt:
image only
```
## Storyboard Video Prompts
```text
Storyboard 02 Video Prompt:
video only
```
"""
        with self.assertRaisesRegex(ValueError, "提示词不成对"):
            storyboard_video.parse_storyboard_markdown_package(markdown)

    def test_document_input_prefers_pasted_body_over_attachment(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source = storyboard_video.resolve_storyboard_document_input(
                "token",
                {
                    "故事板文档正文": "pasted markdown",
                    "故事板Markdown附件": [{"file_token": "ft_md", "name": "storyboard.md"}],
                },
                Path(tmpdir),
                download_fn=Mock(side_effect=AssertionError("attachment should be ignored")),
            )

        self.assertEqual(source["source"], "正文")
        self.assertEqual(source["markdown"], "pasted markdown")
        self.assertTrue(source["attachment_ignored"])

    def test_document_input_reads_markdown_attachment_when_body_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            def fake_download(token, file_token, save_path):
                Path(save_path).write_text("attachment markdown", encoding="utf-8")
                return save_path

            source = storyboard_video.resolve_storyboard_document_input(
                "token",
                {"故事板Markdown附件": [{"file_token": "ft_md", "name": "storyboard.md"}]},
                Path(tmpdir),
                download_fn=fake_download,
            )

        self.assertEqual(source["source"], "附件")
        self.assertEqual(source["markdown"], "attachment markdown")

    def test_document_input_rejects_missing_or_non_text_attachment(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaisesRegex(ValueError, "缺少故事板文档输入"):
                storyboard_video.resolve_storyboard_document_input("token", {}, Path(tmpdir))

            with self.assertRaisesRegex(ValueError, "仅支持"):
                storyboard_video.resolve_storyboard_document_input(
                    "token",
                    {"故事板Markdown附件": [{"file_token": "ft_pdf", "name": "storyboard.pdf"}]},
                    Path(tmpdir),
                )

    def test_dispatcher_has_004_parse_image_and_video_watches(self):
        watches = {watch["name"]: watch for watch in dispatcher.WATCH_LIST}
        parse_watch = watches["004故事板文档解析"]
        image_watch = watches["004故事板图片生成"]
        video_watch = watches["004故事板视频生成"]

        self.assertEqual(parse_watch["status_field"], "解析状态")
        self.assertEqual(parse_watch["args"], ["parse"])
        self.assertEqual(parse_watch["required_field_values"], {"记录类型": ["母任务"]})
        self.assertEqual(image_watch["status_field"], "图片生成状态")
        self.assertEqual(image_watch["args"], ["image"])
        self.assertEqual(image_watch["required_field_values"], {"记录类型": ["Storyboard分段"]})
        self.assertEqual(video_watch["status_field"], "视频生成状态")
        self.assertEqual(video_watch["args"], ["video"])
        self.assertEqual(video_watch["required_field_values"], {"记录类型": ["Storyboard分段"]})

    def test_prompt_worker_can_auto_approve_against_storyboard_table_switch(self):
        updates = []
        fields = {"图生视频提示词": "video prompt"}
        with patch.object(prompt_video, "TABLE_STORYBOARD_VIDEO", "tbl_004"), \
             patch.object(prompt_video, "safe_update_record", side_effect=lambda token, table, rid, patch_fields: updates.append((table, patch_fields))), \
             patch.object(prompt_video, "filter_existing_fields", side_effect=lambda token, table, patch_fields: patch_fields), \
             patch.object(prompt_video, "auto_review_enabled", return_value=True) as enabled:
            result = prompt_video.maybe_auto_approve_image(
                "token",
                "rec004",
                fields,
                file_token="ft_image",
                table_key="storyboard_video",
            )

        self.assertEqual(result["status"], "auto_approved")
        enabled.assert_called_once_with("token", stage_name=tk_auto_review.TABLE_AUTO_REVIEW_STAGE_NAMES["storyboard_video"])
        self.assertEqual(updates, [("tbl_004", {"图片审核状态": "通过", "错误信息": "", "视频生成状态": "待生成"})])

    def test_prompt_worker_defaults_to_008_table_key_for_existing_callers(self):
        updates = []
        with patch.object(prompt_video, "TABLE_PROMPT_IMAGE_VIDEO", "tbl_008"), \
             patch.object(prompt_video, "safe_update_record", side_effect=lambda token, table, rid, patch_fields: updates.append((table, patch_fields))), \
             patch.object(prompt_video, "filter_existing_fields", side_effect=lambda token, table, patch_fields: patch_fields), \
             patch.object(prompt_video, "auto_review_enabled", return_value=True) as enabled:
            prompt_video.maybe_auto_approve_image("token", "rec008", {"图生视频提示词": ""}, file_token="ft_image")

        enabled.assert_called_once_with("token", stage_name=tk_auto_review.TABLE_AUTO_REVIEW_STAGE_NAMES["prompt_image_video"])
        self.assertEqual(updates[0][0], "tbl_008")
        self.assertNotIn("视频生成状态", updates[0][1])

    def test_model_config_center_registers_storyboard_video_defaults(self):
        self.assertEqual(center.TASK_TABLES["storyboard_video"], "004-故事板视频生成表")
        default_keys = {(spec.table_key, spec.stage, spec.dispatch_stage_name) for spec in center.RUNTIME_DEFAULT_SPECS}
        self.assertIn(("storyboard_video", "图片生成默认", "004故事板图片生成"), default_keys)
        self.assertIn(("storyboard_video", "图生视频生成默认", "004故事板视频生成"), default_keys)

    def test_parse_parent_creates_storyboard_child_records(self):
        created_records = []
        updates = []
        fields = {
            "任务名称": "story task",
            "记录类型": "母任务",
            "故事板文档正文": sample_storyboard_package(),
            "关联产品记录": ["recProduct"],
            "上传产品图": [{"file_token": "ft_upload"}],
        }

        with patch.object(storyboard_video, "TABLE_STORYBOARD_VIDEO", "tbl_004"), \
             patch.object(storyboard_video, "safe_get_record", return_value=fields), \
             patch.object(storyboard_video, "safe_update_record", side_effect=lambda token, table, rid, patch_fields: updates.append(patch_fields)), \
             patch.object(storyboard_video, "safe_list_records", return_value=[]), \
             patch.object(storyboard_video, "filter_existing_fields", side_effect=lambda token, table, patch_fields: patch_fields), \
             patch.object(storyboard_video, "create_records", side_effect=lambda token, table, records: created_records.extend(records) or len(records)), \
             patch.object(storyboard_video, "cleanup_child_storyboards", return_value=0), \
             patch.object(storyboard_video, "apply_storyboard_default_models", side_effect=lambda token, records: records):
            result = storyboard_video.parse_parent_record("recParent", token="token")

        self.assertEqual(result["status"], "success")
        self.assertEqual(len(created_records), 2)
        first_fields = created_records[0]["fields"]
        self.assertEqual(first_fields["记录类型"], "Storyboard分段")
        self.assertEqual(first_fields["父任务记录ID"], "recParent")
        self.assertEqual(first_fields["Storyboard编号"], 1)
        self.assertEqual(first_fields["关联产品记录"], ["recProduct"])
        self.assertEqual(first_fields["上传产品图"], [{"file_token": "ft_upload"}])
        self.assertEqual(first_fields["图片生成状态"], "待生成")
        self.assertEqual(first_fields["视频生成状态"], "不触发")
        self.assertTrue(any(update.get("解析状态") == "成功" for update in updates))

    def test_parse_parent_creates_child_records_with_sanitized_image_prompts(self):
        created_records = []
        fields = {
            "任务名称": "story task",
            "记录类型": "母任务",
            "故事板文档正文": sample_multiview_storyboard_package(),
        }

        with patch.object(storyboard_video, "TABLE_STORYBOARD_VIDEO", "tbl_004"), \
             patch.object(storyboard_video, "safe_get_record", return_value=fields), \
             patch.object(storyboard_video, "safe_update_record"), \
             patch.object(storyboard_video, "safe_list_records", return_value=[]), \
             patch.object(storyboard_video, "filter_existing_fields", side_effect=lambda token, table, patch_fields: patch_fields), \
             patch.object(storyboard_video, "create_records", side_effect=lambda token, table, records: created_records.extend(records) or len(records)), \
             patch.object(storyboard_video, "cleanup_child_storyboards", return_value=0), \
             patch.object(storyboard_video, "apply_storyboard_default_models", side_effect=lambda token, records: records):
            storyboard_video.parse_parent_record("recParent", token="token")

        image_prompt = created_records[0]["fields"]["生图提示词"].lower()
        self.assertIn("low-information reference strip", image_prompt)
        self.assertNotIn("expression sheet", image_prompt)
        self.assertNotIn("multi-pack spread", image_prompt)

    def test_child_records_normalize_read_link_fields_before_create(self):
        payload = storyboard_video.parse_storyboard_markdown_package(sample_storyboard_package())
        records = storyboard_video.build_child_storyboard_records(
            {
                "任务名称": "story task",
                "关联产品记录": [{"id": "recProduct"}],
                "选择模特": [{"record_ids": ["recModel"]}],
                "上传产品图": [{"file_token": "ft_upload"}],
            },
            payload,
            parent_record_id="recParent",
            batch_id="batch",
        )

        first_fields = records[0]["fields"]
        self.assertEqual(first_fields["关联产品记录"], ["recProduct"])
        self.assertEqual(first_fields["选择模特"], ["recModel"])
        self.assertEqual(first_fields["上传产品图"], [{"file_token": "ft_upload"}])


if __name__ == "__main__":
    unittest.main()
