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
import tk_dispatcher as dispatcher


def parent_fields():
    return {
        "记录类型": "母任务",
        "任务名称": "story task",
        "脚本内容": "0-10s hook\n10-20s product demo",
        "关联产品记录": [{"record_ids": ["recProduct"], "text": "Pet odor spray"}],
        "选择模特": [{"record_ids": ["recModel"], "text": "Momo"}],
        "环境图": [{"file_token": "ft_environment"}],
    }


def multi_model_parent_fields(model_ids=None, environment_tokens=None):
    model_ids = model_ids or ["recHuman1", "recHuman2", "recPet1", "recPet2"]
    return {
        **parent_fields(),
        "选择模特": [{"record_ids": model_ids, "text": "multi models"}],
        "环境图": [{"file_token": token} for token in (environment_tokens or ["ft_environment"])],
    }


def fake_parent_lookup(token, table_id, record_id):
    if record_id == "recProduct":
        return {
            "产品名称-zh": "宠物除臭喷雾",
            "产品名称-th": "Pet odor spray TH",
            "目标用户": "Thai pet owners",
            "产品图片": [{"file_token": "ft_product"}],
        }
    if record_id == "recModel":
        return {
            "模特名称": "Momo",
            "模特照片": [{"file_token": "ft_character"}],
        }
    raise AssertionError((token, table_id, record_id))


def fake_multi_model_lookup(token, table_id, record_id):
    if record_id == "recProduct":
        return {
            "产品名称-zh": "宠物除臭喷雾",
            "目标用户": "Thai pet owners",
            "产品图片": [
                {"file_token": "ft_product_1"},
                {"file_token": "ft_product_2"},
                {"file_token": "ft_product_3"},
            ],
        }
    models = {
        "recHuman1": {"模特名称": "Thai man 1", "模特类型": "人类", "外观描述": "blue shirt", "模特照片": [{"file_token": "ft_human_1a"}, {"file_token": "ft_human_1b"}]},
        "recHuman2": {"模特名称": "Thai woman 1", "模特类型": "人类", "外观描述": "white dress", "模特照片": [{"file_token": "ft_human_2a"}, {"file_token": "ft_human_2b"}]},
        "recPet1": {"模特名称": "Orange cat", "模特类型": "宠物", "外观描述": "orange tabby", "模特照片": [{"file_token": "ft_pet_1a"}, {"file_token": "ft_pet_1b"}]},
        "recPet2": {"模特名称": "White dog", "模特类型": "宠物", "外观描述": "small white dog", "模特照片": [{"file_token": "ft_pet_2a"}, {"file_token": "ft_pet_2b"}]},
    }
    if record_id in models:
        return models[record_id]
    raise AssertionError((token, table_id, record_id))


class StoryboardVideoTests(unittest.TestCase):
    def test_prompt_instructions_keep_conflict_hook_only_on_storyboard_01(self):
        fields = dict(parent_fields(), **{"产品名称": "Pet odor spray", "目标人群": "Thai pet owners"})
        prompt = storyboard_video.build_storyboard_prompt_generation_request(fields)

        self.assertIn("Storyboard 01", prompt)
        self.assertIn("核心冲突场景", prompt)
        self.assertIn("黄金3秒/戏剧钩子", prompt)
        self.assertIn("Storyboard 02", prompt)
        self.assertIn("from Storyboard 02 onward", prompt)
        self.assertIn("must not include 核心冲突场景", prompt)
        self.assertIn("derive the Storyboard 01 core conflict scene", prompt)
        self.assertNotIn("Core conflict scene:", prompt)
        self.assertNotIn("Golden 3-second / dramatic hook:", prompt)
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
            dict(parent_fields(), **{"产品名称": "Pet odor spray", "目标人群": "Thai pet owners"}),
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
        self.assertEqual(records[0]["fields"]["关联产品记录"], parent_fields()["关联产品记录"])
        self.assertEqual(records[0]["fields"]["选择模特"], parent_fields()["选择模特"])
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
                "关联产品记录": [{"record_ids": ["recProduct"]}],
                "选择模特": [{"record_ids": ["recModel"]}],
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
                get_record_fn=fake_parent_lookup,
            )

        self.assertEqual([ref["role"] for ref in refs], ["storyboard", "product:1", "character:1", "environment:1"])
        self.assertEqual([call.args[1] for call in download.call_args_list], ["ft_story", "ft_product", "ft_character", "ft_environment"])

    def test_resolve_parent_reference_context_allows_multiple_models_and_uses_first_photo_each(self):
        context = storyboard_video.resolve_parent_reference_context(
            "token",
            multi_model_parent_fields(),
            get_record_fn=fake_multi_model_lookup,
            product_table_id="tblProduct",
            model_table_id="tblModel",
        )

        self.assertEqual(context["model_record_ids"], ["recHuman1", "recHuman2", "recPet1", "recPet2"])
        self.assertEqual(context["character_tokens"], ["ft_human_1a", "ft_human_2a", "ft_pet_1a", "ft_pet_2a"])
        self.assertEqual([character["name"] for character in context["characters"]], ["Thai man 1", "Thai woman 1", "Orange cat", "White dog"])
        self.assertEqual([character["type"] for character in context["characters"]], ["人类", "人类", "宠物", "宠物"])

        prompt = storyboard_video.build_storyboard_prompt_generation_request(
            storyboard_video.apply_parent_reference_snapshots(dict(multi_model_parent_fields()), context)
        )
        self.assertIn("Selected character references", prompt)
        self.assertIn("Thai man 1", prompt)
        self.assertIn("Orange cat", prompt)
        self.assertIn("Keep every selected human/pet character consistent", prompt)

    def test_resolve_parent_reference_context_supports_common_human_pet_combinations(self):
        cases = [
            ["recHuman1"],
            ["recHuman1", "recPet1"],
            ["recHuman1", "recHuman2", "recPet1"],
            ["recHuman1", "recHuman2", "recPet1", "recPet2"],
        ]

        for model_ids in cases:
            with self.subTest(model_ids=model_ids):
                context = storyboard_video.resolve_parent_reference_context(
                    "token",
                    multi_model_parent_fields(model_ids=model_ids),
                    get_record_fn=fake_multi_model_lookup,
                    product_table_id="tblProduct",
                    model_table_id="tblModel",
                )

                self.assertEqual(context["model_record_ids"], model_ids)
                self.assertEqual(len(context["character_tokens"]), len(model_ids))

    def test_parent_reference_priority_keeps_required_product_and_all_model_refs_before_extras(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for name in [
                "product_1.png", "product_2.png", "product_3.png",
                "human_1.png", "human_2.png", "pet_1.png", "pet_2.png",
                "environment.png",
            ]:
                (tmp_path / name).write_bytes(b"x" * 2000)
            download = Mock(side_effect=[
                tmp_path / "product_1.png",
                tmp_path / "human_1.png",
                tmp_path / "human_2.png",
                tmp_path / "pet_1.png",
                tmp_path / "pet_2.png",
                tmp_path / "product_2.png",
                tmp_path / "product_3.png",
            ])

            refs = storyboard_video.collect_parent_reference_images(
                "token",
                multi_model_parent_fields(),
                tmp_path,
                download_fn=download,
                get_record_fn=fake_multi_model_lookup,
            )

        self.assertEqual(
            [ref["role"] for ref in refs],
            ["product:1", "character:1", "character:2", "character:3", "character:4", "product:2", "product:3"],
        )
        self.assertEqual(
            [call.args[1] for call in download.call_args_list],
            ["ft_product_1", "ft_human_1a", "ft_human_2a", "ft_pet_1a", "ft_pet_2a", "ft_product_2", "ft_product_3"],
        )

    def test_omni_reference_images_reserve_one_slot_for_storyboard_and_cap_parent_refs_at_6(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for name in ["story.png", "product_1.png", "human_1.png", "human_2.png", "pet_1.png", "pet_2.png", "product_2.png"]:
                (tmp_path / name).write_bytes(b"x" * 2000)
            download = Mock(side_effect=[
                tmp_path / "story.png",
                tmp_path / "product_1.png",
                tmp_path / "human_1.png",
                tmp_path / "human_2.png",
                tmp_path / "pet_1.png",
                tmp_path / "pet_2.png",
                tmp_path / "product_2.png",
            ])

            refs = storyboard_video.collect_omni_reference_images(
                "token",
                {"故事板图": [{"file_token": "ft_story"}]},
                multi_model_parent_fields(),
                tmp_path,
                download_fn=download,
                get_record_fn=fake_multi_model_lookup,
            )

        self.assertEqual(
            [ref["role"] for ref in refs],
            ["storyboard", "product:1", "character:1", "character:2", "character:3", "character:4", "product:2"],
        )
        self.assertEqual(len(refs), 7)

    def test_parent_reference_images_fail_when_required_product_and_models_exceed_limit(self):
        with self.assertRaisesRegex(ValueError, "参考图数量超过上限"):
            storyboard_video.collect_parent_reference_images(
                "token",
                multi_model_parent_fields(model_ids=["recHuman1", "recHuman2", "recPet1", "recPet2", "recExtra1", "recExtra2", "recExtra3"]),
                Path("/tmp"),
                download_fn=Mock(),
                get_record_fn=lambda token, table_id, record_id: (
                    {"产品图片": [{"file_token": "ft_product_1"}]}
                    if record_id == "recProduct"
                    else {"模特名称": record_id, "模特照片": [{"file_token": f"ft_{record_id}"}]}
                ),
            )

    def test_build_omni_video_prompt_rejects_rendering_storyboard_board(self):
        prompt = storyboard_video.build_omni_video_prompt(
            {"故事板图片提示词": "board prompt", "视频提示词": ""},
            dict(parent_fields(), **{"产品名称": "Pet odor spray", "目标人群": "Thai pet owners"}),
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
        self.assertIn("关联产品记录", field_names)
        self.assertIn("选择模特", field_names)
        self.assertNotIn("产品名称", field_names)
        self.assertNotIn("目标人群", field_names)
        self.assertNotIn("核心冲突场景", field_names)
        self.assertNotIn("黄金3秒/戏剧钩子", field_names)
        self.assertNotIn("产品图", field_names)
        self.assertNotIn("角色图", field_names)
        self.assertNotIn("故事板图本地路径", field_names)
        self.assertNotIn("故事板图file_token", field_names)
        self.assertNotIn("故事板图片原始响应JSON", field_names)
        self.assertNotIn("视频通道", field_names)
        self.assertNotIn("视频生成模型", field_names)
        self.assertNotIn("本地视频路径", field_names)
        self.assertNotIn("分镜视频file_token", field_names)
        self.assertNotIn("视频生成原始响应JSON", field_names)
        self.assertNotIn("失败分类", field_names)
        self.assertNotIn("生成时间", field_names)
        self.assertIn("环境图", field_names)
        self.assertIn("Storyboard编号", field_names)
        self.assertIn("故事板图片生成状态", field_names)
        self.assertIn("视频生成状态", field_names)
        self.assertIn("分镜视频", field_names)
        self.assertEqual(create_table.TABLE_DEFINITION["key"], "storyboard_video")
        self.assertEqual(create_table.TABLE_DEFINITION["views"]["01-母任务入口"], [
            "任务名称", "脚本内容", "关联产品记录", "选择模特", "环境图", "拆分状态", "错误信息",
        ])
        self.assertIn("02-故事板图片", create_table.TABLE_DEFINITION["views"])
        self.assertIn("03-Omni视频", create_table.TABLE_DEFINITION["views"])

    def test_prune_obsolete_fields_deletes_by_field_id_for_special_names(self):
        calls = []

        def fake_run_json(args):
            calls.append(args)
            if "+field-list" in args:
                return {"data": {"fields": [{"name": "黄金3秒/戏剧钩子", "id": "fldHook"}]}}
            if "+field-delete" in args:
                return {"ok": True}
            raise AssertionError(args)

        with patch.object(create_table, "get_feishu_token", return_value="token"), \
             patch.object(create_table, "safe_list_records", return_value=[{"fields": {"黄金3秒/戏剧钩子": ""}}]), \
             patch.object(create_table, "run_json", side_effect=fake_run_json):
            deleted = create_table.prune_obsolete_fields("base", "tbl", field_names=["黄金3秒/戏剧钩子"])

        delete_call = [call for call in calls if "+field-delete" in call][0]
        self.assertEqual(deleted, ["黄金3秒/戏剧钩子"])
        self.assertEqual(delete_call[delete_call.index("--field-id") + 1], "fldHook")

    def test_resolve_parent_reference_context_uses_linked_product_and_model(self):
        context = storyboard_video.resolve_parent_reference_context(
            "token",
            parent_fields(),
            get_record_fn=fake_parent_lookup,
            product_table_id="tblProduct",
            model_table_id="tblModel",
        )

        self.assertEqual(context["product_record_id"], "recProduct")
        self.assertEqual(context["model_record_id"], "recModel")
        self.assertEqual(context["product_name"], "宠物除臭喷雾")
        self.assertEqual(context["target_audience"], "Thai pet owners")
        self.assertEqual(context["product_tokens"], ["ft_product"])
        self.assertEqual(context["character_tokens"], ["ft_character"])
        self.assertEqual(context["environment_tokens"], ["ft_environment"])

    def test_resolve_parent_reference_context_requires_single_product_and_at_least_one_model(self):
        with self.assertRaisesRegex(ValueError, "必须选择 1 个产品"):
            storyboard_video.resolve_parent_reference_context(
                "token",
                {"关联产品记录": [], "选择模特": [{"record_ids": ["recModel"]}]},
                get_record_fn=fake_parent_lookup,
                product_table_id="tblProduct",
                model_table_id="tblModel",
            )

        with self.assertRaisesRegex(ValueError, "必须至少选择 1 个模特"):
            storyboard_video.resolve_parent_reference_context(
                "token",
                {"关联产品记录": [{"record_ids": ["recProduct"]}], "选择模特": []},
                get_record_fn=fake_parent_lookup,
                product_table_id="tblProduct",
                model_table_id="tblModel",
            )

        with self.assertRaisesRegex(ValueError, "recMissingPhoto.*缺少模特照片"):
            storyboard_video.resolve_parent_reference_context(
                "token",
                {"关联产品记录": [{"record_ids": ["recProduct"]}], "选择模特": [{"record_ids": ["recMissingPhoto"]}]},
                get_record_fn=lambda token, table_id, record_id: (
                    {"产品图片": [{"file_token": "ft_product"}]}
                    if record_id == "recProduct"
                    else {"模特名称": "recMissingPhoto", "模特照片": []}
                ),
                product_table_id="tblProduct",
                model_table_id="tblModel",
            )

    def test_regeneration_reset_fields_clear_old_outputs(self):
        image_reset = storyboard_video.image_regeneration_reset_fields()
        self.assertEqual(image_reset["故事板图"], [])
        self.assertEqual(image_reset["故事板图片任务ID"], "")
        self.assertIsNone(image_reset["故事板图片生成时间"])
        self.assertEqual(image_reset["分镜视频"], [])
        self.assertEqual(image_reset["分镜视频URL"], "")
        self.assertEqual(image_reset["视频任务ID"], "")
        self.assertEqual(image_reset["视频生成状态"], "不触发")

        video_reset = storyboard_video.video_regeneration_reset_fields()
        self.assertEqual(video_reset["分镜视频"], [])
        self.assertEqual(video_reset["分镜视频URL"], "")
        self.assertEqual(video_reset["视频任务ID"], "")
        self.assertIsNone(video_reset["视频生成时间"])

    def test_dispatcher_claim_clear_values_supports_typed_resets(self):
        claim_fields = {"视频生成状态": "生成中"}
        dispatcher.apply_claim_clear_fields(claim_fields, {
            "claim_clear_values": {
                "分镜视频": [],
                "分镜视频URL": "",
                "视频生成时间": None,
            }
        })

        self.assertEqual(claim_fields["分镜视频"], [])
        self.assertEqual(claim_fields["分镜视频URL"], "")
        self.assertIsNone(claim_fields["视频生成时间"])

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
