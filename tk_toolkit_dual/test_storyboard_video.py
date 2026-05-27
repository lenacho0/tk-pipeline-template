import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import tk_storyboard_video as storyboard_video
import tk_create_storyboard_video_table as create_table
import tk_bootstrap_storyboard_video_config as bootstrap_config


def parent_fields():
    return {
        "记录类型": "母任务",
        "任务名称": "story task",
        "脚本内容": "0-10s hook\n10-20s product demo",
        "产品名称": "Pet odor spray",
        "目标人群": "Thai pet owners",
        "核心冲突场景": "cat urine smell in the house",
        "黄金3秒/戏剧钩子": "The cat confesses the smell problem",
        "产品图": [{"file_token": "ft_product"}],
        "角色图": [{"file_token": "ft_character"}],
        "环境图": [{"file_token": "ft_environment"}],
    }


class StoryboardVideoTests(unittest.TestCase):
    def test_prompt_instructions_keep_conflict_hook_only_on_storyboard_01(self):
        prompt = storyboard_video.build_storyboard_prompt_generation_request(parent_fields())

        self.assertIn("Storyboard 01", prompt)
        self.assertIn("核心冲突场景", prompt)
        self.assertIn("黄金3秒/戏剧钩子", prompt)
        self.assertIn("Storyboard 02", prompt)
        self.assertIn("from Storyboard 02 onward", prompt)
        self.assertIn("must not include 核心冲突场景", prompt)
        self.assertIn("English", prompt)
        self.assertIn("Thai", prompt)

    def test_normalize_storyboard_payload_requires_prompt_and_adds_numbers(self):
        payload = storyboard_video.normalize_storyboard_payload({
            "storyboards": [
                {
                    "storyboard_no": 1,
                    "time_range": "0-10s",
                    "image_prompt": "Create a 16:9 storyboard board for hook.",
                    "video_prompt": "Animate the real scene from storyboard 01.",
                },
                {
                    "time_range": "10-20s",
                    "image_prompt": "Create a 16:9 storyboard board for demo.",
                },
            ]
        })

        self.assertEqual(payload["storyboards"][0]["storyboard_no"], 1)
        self.assertEqual(payload["storyboards"][1]["storyboard_no"], 2)
        self.assertEqual(payload["storyboards"][1]["video_prompt"], "")

    def test_child_records_are_same_table_segments_and_trigger_image_only_first(self):
        payload = storyboard_video.normalize_storyboard_payload({
            "storyboards": [
                {
                    "storyboard_no": 1,
                    "time_range": "0-10s",
                    "image_prompt": "Prompt one",
                    "video_prompt": "Video one",
                },
                {
                    "storyboard_no": 2,
                    "time_range": "10-20s",
                    "image_prompt": "Prompt two",
                    "video_prompt": "Video two",
                },
            ]
        })

        records = storyboard_video.build_child_storyboard_records(
            parent_fields(),
            payload,
            parent_record_id="recParent",
            batch_id="SB-1",
        )

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["fields"]["记录类型"], "Storyboard分段")
        self.assertEqual(records[0]["fields"]["父任务记录ID"], "recParent")
        self.assertEqual(records[0]["fields"]["Storyboard编号"], 1)
        self.assertEqual(records[0]["fields"]["Time Range"], "0-10s")
        self.assertEqual(records[0]["fields"]["故事板图片生成状态"], "待生成")
        self.assertEqual(records[0]["fields"]["视频生成状态"], "不触发")
        self.assertEqual(records[1]["fields"]["故事板图片提示词"], "Prompt two")

    def test_collect_reference_images_uses_storyboard_then_product_character_environment_and_caps_at_7(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for name in ["story.png", "product.png", "character.png", "environment.png"]:
                (tmp_path / name).write_bytes(b"x" * 2000)

            child = {
                "故事板图": [{"file_token": "ft_story"}],
                "父任务记录ID": "recParent",
            }
            parent = {
                "产品图": [{"file_token": "ft_product"}],
                "角色图": [{"file_token": "ft_character"}],
                "环境图": [{"file_token": "ft_environment"}],
            }
            download = Mock(side_effect=[
                tmp_path / "story.png",
                tmp_path / "product.png",
                tmp_path / "character.png",
                tmp_path / "environment.png",
            ])

            refs = storyboard_video.collect_omni_reference_images(
                "token",
                child,
                parent,
                tmp_path,
                download_fn=download,
            )

        self.assertEqual([ref["role"] for ref in refs], ["storyboard", "product:1", "character:1", "environment:1"])
        self.assertEqual([call.args[1] for call in download.call_args_list], ["ft_story", "ft_product", "ft_character", "ft_environment"])

    def test_build_omni_video_prompt_rejects_rendering_storyboard_board(self):
        prompt = storyboard_video.build_omni_video_prompt(
            {"故事板图片提示词": "board prompt", "视频提示词": ""},
            parent_fields(),
        )

        self.assertIn("Do not render the storyboard board", prompt)
        self.assertIn("Do not show grid lines", prompt)
        self.assertIn("product", prompt.lower())
        self.assertIn("character", prompt.lower())

    def test_submit_omni_video_task_uses_multipart_without_seconds(self):
        with tempfile.NamedTemporaryFile(suffix=".png") as story, tempfile.NamedTemporaryFile(suffix=".png") as product:
            story.write(b"story")
            story.flush()
            product.write(b"product")
            product.flush()
            response = Mock()
            response.status_code = 200
            response.json.return_value = {"id": "task_omni", "status": "queued"}
            response.text = '{"id":"task_omni"}'

            with patch("tk_storyboard_video.requests.post", return_value=response) as post:
                task_id, body = storyboard_video.submit_omni_video_task(
                    {"api_base": "https://otuapi.com", "api_key": "sk-test", "model": "omni_flash-10s"},
                    "prompt text",
                    [{"role": "storyboard", "path": story.name}, {"role": "product:1", "path": product.name}],
                    size="1280x720",
                )

        self.assertEqual(task_id, "task_omni")
        self.assertEqual(body["status"], "queued")
        args, kwargs = post.call_args
        self.assertEqual(args[0], "https://otuapi.com/v1/videos")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer sk-test")
        form_fields = kwargs["files"]
        self.assertEqual(form_fields[0], ("model", (None, "omni_flash-10s")))
        self.assertEqual(form_fields[1], ("prompt", (None, "prompt text")))
        self.assertEqual(form_fields[2], ("size", (None, "1280x720")))
        self.assertNotIn("seconds", [item[0] for item in form_fields])
        self.assertEqual([item[0] for item in form_fields if item[0] == "input_reference[]"], ["input_reference[]", "input_reference[]"])

    def test_table_definition_has_single_mixed_parent_child_table(self):
        field_names = [field["name"] for field in create_table.STORYBOARD_VIDEO_FIELDS]
        self.assertIn("记录类型", field_names)
        self.assertIn("脚本内容", field_names)
        self.assertIn("产品图", field_names)
        self.assertIn("角色图", field_names)
        self.assertIn("环境图", field_names)
        self.assertIn("Storyboard编号", field_names)
        self.assertIn("故事板图片生成状态", field_names)
        self.assertIn("视频生成状态", field_names)
        self.assertIn("分镜视频", field_names)
        self.assertEqual(create_table.TABLE_DEFINITION["key"], "storyboard_video")
        self.assertIn("01-母任务入口", create_table.TABLE_DEFINITION["views"])
        self.assertIn("02-故事板图片", create_table.TABLE_DEFINITION["views"])
        self.assertIn("03-Omni视频", create_table.TABLE_DEFINITION["views"])

    def test_bootstrap_config_creates_only_missing_storyboard_stages(self):
        created = []
        with patch.object(bootstrap_config, "get_feishu_token", return_value="token"), \
             patch.object(bootstrap_config, "safe_list_records", return_value=[
                 {"record_id": "rec_image", "fields": {"环节": "故事板图片生成-OTU"}}
             ]), \
             patch.object(bootstrap_config, "config_field_names", return_value={"环节", "模型名称", "API Key", "API 代理地址", "调用方式", "状态", "备注"}), \
             patch.dict(os.environ, {"STORYBOARD_VIDEO_OTU_API_KEY": "sk-test"}, clear=False), \
             patch.object(bootstrap_config, "create_config_record", side_effect=lambda token, fields, existing_fields: created.append(fields) or "rec_new"), \
             patch("tk_bootstrap_storyboard_video_config.print") as printer:
            bootstrap_config.main()

        self.assertEqual(len(created), 1)
        self.assertEqual(created[0]["环节"], "故事板视频生成-Omni")
        self.assertEqual(created[0]["模型名称"], "omni_flash-10s")
        self.assertEqual(created[0]["API 代理地址"], "https://otuapi.com")
        printed = printer.call_args.args[0]
        self.assertIn("故事板视频生成-Omni", printed)
        self.assertNotIn("sk-test", printed)


if __name__ == "__main__":
    unittest.main()
