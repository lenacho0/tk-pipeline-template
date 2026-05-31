import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))

import tk_create_nine_grid_video_table as create_table
import tk_bootstrap_nine_grid_video_config as bootstrap_config
import tk_nine_grid_video as nine_grid
import tk_nine_grid_video_prompt as prompts
import tk_dispatcher as dispatcher


def sample_plan_payload():
    cells = [
        {
            "cell_index": idx,
            "visual_node": f"visual node {idx}",
            "character_action": f"action {idx}",
            "product_state": f"product state {idx}",
            "environment_anchor": "same living room rug",
            "emotion": "surprised",
            "camera": "handheld close-up",
            "dialogue_or_voiceover": "",
        }
        for idx in range(1, 10)
    ]
    return {
        "task_type": "MULTI_IMAGE_NINE_GRID_PLAN",
        "script_analysis": {
            "estimated_duration_seconds": 10,
            "script_type": "产品演示型",
            "core_conflict": "pet urine stain on rug",
            "core_product_action": "spray cleaner",
            "conversion_moment": "stain disappears",
            "needs_before_during_after": True,
            "characters": ["owner"],
            "pets": ["dog"],
            "product": "odor spray",
            "environment": "living room",
        },
        "reference_manifest": {"required_references": []},
        "boards": [
            {
                "board_index": 1,
                "time_range": "0-10s",
                "narrative_task": "show stain removal",
                "start_frame": "stain visible on rug",
                "end_frame": "rug is clean",
                "handoff_anchor": "rug is clean",
                "before_during_after_coverage": {
                    "before": "stain visible",
                    "during": "spray is used",
                    "after": "stain disappears",
                },
                "cells": cells,
                "image_prompt": "Create one vertical 9:16 image containing exactly 9 panels arranged in a 3x3 grid.",
                "video_prompt": "Turn the nine-grid storyboard into one continuous vertical UGC video.",
            }
        ],
        "continuity_check": {
            "board_handoffs": [],
            "character_consistency": "same owner",
            "pet_consistency": "same dog",
            "product_consistency": "same bottle",
            "environment_consistency": "same rug",
            "reference_images_not_in_timeline": True,
            "before_during_after_complete": True,
        },
    }


class NineGridVideoTests(unittest.TestCase):
    def test_prompt_constants_are_supplier_neutral_and_define_json_truth(self):
        self.assertIn("JSON", prompts.NINE_GRID_PLAN_SYSTEM_PROMPT)
        self.assertIn("MULTI_IMAGE_NINE_GRID_PLAN", prompts.NINE_GRID_PLAN_SYSTEM_PROMPT)
        self.assertIn("不要提具体供应商或模型名", prompts.NINE_GRID_IMAGE_SYSTEM_PROMPT)
        self.assertIn("不要提具体供应商或模型名", prompts.NINE_GRID_VIDEO_SYSTEM_PROMPT)
        self.assertNotIn("OTU", prompts.NINE_GRID_IMAGE_SYSTEM_PROMPT)
        self.assertNotIn("Omni", prompts.NINE_GRID_VIDEO_SYSTEM_PROMPT)

    def test_normalize_plan_payload_requires_exactly_nine_cells(self):
        payload = sample_plan_payload()
        payload["boards"][0]["cells"] = payload["boards"][0]["cells"][:8]

        with self.assertRaisesRegex(ValueError, "必须正好 9 个"):
            nine_grid.normalize_nine_grid_plan_payload(payload)

    def test_normalize_plan_payload_keeps_json_execution_fields(self):
        normalized = nine_grid.normalize_nine_grid_plan_payload(sample_plan_payload())

        self.assertEqual(normalized["task_type"], "MULTI_IMAGE_NINE_GRID_PLAN")
        self.assertEqual(len(normalized["boards"]), 1)
        self.assertEqual(len(normalized["boards"][0]["cells"]), 9)
        self.assertEqual(normalized["boards"][0]["board_index"], 1)

    def test_build_child_board_records_uses_record_ids_and_supplier_neutral_fields(self):
        parent_fields = {
            "任务名称": "nine-grid task",
            "关联产品记录": [{"record_ids": ["recProduct"], "text": "product"}],
            "选择模特": [{"record_ids": ["recModel"], "text": "model"}],
        }
        records = nine_grid.build_child_board_records(
            parent_fields,
            sample_plan_payload(),
            parent_record_id="recParent",
            batch_id="NINEGRID-1",
        )

        self.assertEqual(len(records), 1)
        fields = records[0]["fields"]
        self.assertEqual(fields["记录类型"], "Board分段")
        self.assertEqual(fields["关联产品记录"], ["recProduct"])
        self.assertEqual(fields["选择模特"], ["recModel"])
        self.assertEqual(fields["图片生成状态"], "待生成")
        self.assertEqual(fields["视频生成状态"], "不触发")
        self.assertIn("图片AI供应商", fields)
        self.assertIn("图片AI模型", fields)
        self.assertIn("视频AI供应商", fields)
        self.assertIn("视频AI模型", fields)

    def test_child_board_records_wait_when_reference_assets_need_review(self):
        records = nine_grid.build_child_board_records(
            {"任务名称": "nine-grid task"},
            sample_plan_payload(),
            parent_record_id="recParent",
            batch_id="NINEGRID-1",
            await_reference_assets=True,
        )

        self.assertEqual(records[0]["fields"]["图片生成状态"], "不触发")

    def test_table_definition_has_clean_entry_review_generation_views(self):
        self.assertEqual(create_table.TABLE_DEFINITION["key"], "nine_grid_video")
        field_names = [field["name"] for field in create_table.NINE_GRID_VIDEO_FIELDS]
        for name in [
            "方案生成状态", "方案JSON", "审核状态", "九宫格图片提示词", "视频提示词",
            "方案AI供应商", "方案AI模型", "图片AI供应商", "图片AI模型", "视频AI供应商", "视频AI模型",
            "人物/宠物默认来源", "环境图来源", "资产ID", "资产类型", "参考图来源", "参考图",
            "参考图生成状态", "参考图审核状态", "参考图操作",
        ]:
            self.assertIn(name, field_names)
        record_types = [item["name"] for item in {field["name"]: field for field in create_table.NINE_GRID_VIDEO_FIELDS}["记录类型"]["options"]]
        self.assertEqual(record_types, ["母任务", "参考资产", "Board分段"])
        environment_sources = [item["name"] for item in {field["name"]: field for field in create_table.NINE_GRID_VIDEO_FIELDS}["环境图来源"]["options"]]
        self.assertEqual(environment_sources, ["AI自动生成", "手动上传"])
        self.assertEqual(
            create_table.TABLE_DEFINITION["views"]["01-任务入口"],
            [
                "任务名称", "脚本内容", "关联产品记录", "人物/宠物默认来源", "环境图来源",
                "方案AI模型", "方案AI参数JSON", "方案生成状态", "错误信息",
            ],
        )
        self.assertIn("02-参考资产确认", create_table.TABLE_DEFINITION["views"])
        self.assertIn("02-方案审核", create_table.TABLE_DEFINITION["views"])
        self.assertIn("03-九宫格生成", create_table.TABLE_DEFINITION["views"])
        self.assertIn("04-视频生成", create_table.TABLE_DEFINITION["views"])

    def test_nine_grid_model_options_are_split_by_capability(self):
        field_by_name = {field["name"]: field for field in create_table.NINE_GRID_VIDEO_FIELDS}
        plan_options = [item["name"] for item in field_by_name["方案AI模型"]["options"]]
        image_options = [item["name"] for item in field_by_name["图片AI模型"]["options"]]
        video_options = [item["name"] for item in field_by_name["视频AI模型"]["options"]]

        self.assertIn("Aitgenne / gpt-5.5", plan_options)
        self.assertIn("OTU / gpt-image-2-4K", image_options)
        self.assertIn("Aitgenne / gpt-image-2", image_options)
        self.assertIn("Aitgenne / happyhorse-1.0-r2v", video_options)
        self.assertNotIn("OTU / gpt-image-2", plan_options)
        self.assertNotIn("Aitgenne / gpt-5.5", image_options)
        self.assertNotIn("OTU / nano_banana_pro-4K", image_options)
        self.assertNotIn("AIHubMix / sora-2-pro", video_options)

    def test_dispatcher_registers_nine_grid_watches_by_record_type(self):
        watches = {
            watch["name"]: watch
            for watch in dispatcher.RAW_WATCH_LIST
            if watch["name"].startswith("多图九宫格")
        }

        self.assertEqual(
            watches["多图九宫格方案生成"]["required_field_values"],
            {"记录类型": ["母任务"]},
        )
        self.assertEqual(
            watches["多图九宫格参考图生成"]["required_field_values"],
            {"记录类型": ["参考资产"]},
        )
        self.assertEqual(
            watches["多图九宫格图片生成"]["required_field_values"],
            {"记录类型": ["Board分段"]},
        )
        self.assertEqual(
            watches["多图九宫格视频生成"]["required_field_values"],
            {"记录类型": ["Board分段"]},
        )

    def test_bootstrap_config_records_are_supplier_neutral_and_do_not_require_api_keys(self):
        wanted = bootstrap_config.build_wanted_config_records()
        stages = [item["环节"] for item in wanted]

        self.assertEqual(stages, ["多图九宫格方案生成", "多图九宫格图片生成", "多图九宫格视频生成"])
        for item in wanted:
            self.assertEqual(item.get("是否统一AI预设"), "是")
            self.assertEqual(item.get("API Key", ""), "")
        self.assertIn("MULTI_IMAGE_NINE_GRID_PLAN", wanted[0]["提示词"])
        self.assertIn("不要提具体供应商或模型名", wanted[1]["提示词"])
        self.assertIn("不要提具体供应商或模型名", wanted[2]["提示词"])

    def test_nine_grid_config_reuses_production_secret_when_preset_has_no_key(self):
        records = [
            {
                "record_id": "recPreset",
                "fields": {
                    "环节": "多图九宫格图片生成",
                    "模型名称": "gpt-image-2",
                    "API 代理地址": "https://otuapi.com",
                    "API Key": "",
                    "提示词": "preset prompt",
                },
            },
            {
                "record_id": "recProduction",
                "fields": {
                    "环节": "图片生成-OTU",
                    "模型名称": "gpt-image-2",
                    "API 代理地址": "https://otuapi.com",
                    "API Key": "prod-key",
                    "提示词": "production prompt",
                },
            },
        ]

        with patch.object(nine_grid, "get_feishu_token", return_value="token"), \
             patch.object(nine_grid, "safe_list_records", return_value=records):
            record_id, cfg = nine_grid.get_config_record(
                nine_grid.IMAGE_STAGE_NAME,
                default_model="gpt-image-2",
                default_api_base="https://otuapi.com",
            )

        self.assertEqual(record_id, "recPreset")
        self.assertEqual(cfg["model"], "gpt-image-2")
        self.assertEqual(cfg["api_base"], "https://otuapi.com")
        self.assertEqual(cfg["api_key"], "prod-key")
        self.assertEqual(cfg["prompt"], "preset prompt")

    def test_image_dry_run_uses_image_prefixed_route_fields(self):
        child_fields = {
            "父任务记录ID": "recParent",
            "九宫格图片提示词": "Create a 3x3 vertical nine-grid image.",
            "图片AI供应商": "OTU",
            "图片AI模型": "OTU / gpt-image-2",
            "图片AI参数JSON": '{"size":"1080x1920","aspect_ratio":"9:16"}',
            "图片画面尺寸": "720x1280",
            "图片画面比例": "9:16",
        }

        with patch.object(nine_grid, "TABLE_NINE_GRID_VIDEO", "tbl_nine"), \
             patch.object(nine_grid, "get_feishu_token", return_value="token"), \
             patch.object(nine_grid, "safe_get_record", side_effect=[child_fields, {"记录类型": "母任务"}]), \
             patch.object(nine_grid, "get_config_record", return_value=("cfg", {"api_key": "sk", "api_base": "https://otuapi.com", "model": "gpt-image-2"})), \
             patch.object(nine_grid, "safe_list_records", return_value=[]):
            result = nine_grid.render_nine_grid_image("recBoard", dry_run=True)

        self.assertEqual(result["status"], "dry_run_ready")
        self.assertEqual(result["route"]["capability"], "图片")
        self.assertEqual(result["route"]["payload"]["model"], "gpt-image-2")
        self.assertEqual(result["route"]["payload"]["size"], "1080x1920")

    def test_render_nine_grid_image_submits_independent_reference_images(self):
        child_fields = {
            "父任务记录ID": "recParent",
            "九宫格图片提示词": "Show the selected spray product in the nine-grid.",
            "图片AI供应商": "OTU",
            "图片AI模型": "OTU / gpt-image-2",
            "图片画面尺寸": "720x1280",
            "图片画面比例": "9:16",
        }
        refs = [
            {"role": "product:1", "path": "/tmp/product.png", "file_token": "ft_product", "name": "odor spray"},
            {"role": "human:owner", "path": "/tmp/owner.png", "file_token": "ft_owner", "name": "owner"},
            {"role": "environment:main_room", "path": "/tmp/env.png", "file_token": "ft_env", "name": "room"},
        ]

        with patch.object(nine_grid, "ensure_nine_grid_table"), \
             patch.object(nine_grid, "TABLE_NINE_GRID_VIDEO", "tbl_nine"), \
             patch.object(nine_grid, "get_feishu_token", return_value="token"), \
             patch.object(nine_grid, "safe_get_record", side_effect=[child_fields, {"记录类型": "母任务"}]), \
             patch.object(nine_grid, "get_config_record", return_value=("cfg", {"api_key": "sk", "api_base": "https://otuapi.com", "model": "gpt-image-2"})), \
             patch.object(nine_grid, "safe_list_records", return_value=[]), \
             patch.object(nine_grid, "collect_nine_grid_reference_images", return_value=refs), \
             patch.object(nine_grid, "build_reference_urls", return_value=["https://x.test/product.png", "https://x.test/owner.png", "https://x.test/env.png"]), \
             patch.object(nine_grid, "build_nine_grid_reference_contact_sheet", side_effect=AssertionError("contact sheet should not be used"), create=True), \
             patch.object(nine_grid, "submit_otu_image_task", return_value=("task_1", {"id": "task_1"})) as submitter, \
             patch.object(nine_grid, "poll_otu_image_task", return_value={"result_url": "https://x.test/out.png"}), \
             patch.object(nine_grid, "download_otu_image_result"), \
             patch.object(nine_grid, "apply_exact_product_overlays", side_effect=AssertionError("local product overlay should not be used"), create=True), \
             patch.object(nine_grid, "upload_image_to_feishu", return_value="ft_out"), \
             patch.object(nine_grid, "safe_update_record"), \
             patch.object(nine_grid, "filter_existing_fields", side_effect=lambda token, table_id, fields: fields):
            result = nine_grid.render_nine_grid_image("recBoard")

        self.assertEqual(result["status"], "success")
        kwargs = submitter.call_args.kwargs
        self.assertNotIn("image_path", kwargs)
        self.assertEqual(kwargs["reference_image_paths"], ["/tmp/product.png", "/tmp/owner.png", "/tmp/env.png"])
        self.assertEqual(kwargs["metadata"]["reference_roles"], ["product:1", "human:owner", "environment:main_room"])
        self.assertIn("PRODUCT REFERENCE LOCK", submitter.call_args.args[1])
        self.assertNotIn("exact_product_overlay_cells", result)

    def test_build_reference_asset_records_creates_separate_humans_pet_and_environment(self):
        payload = sample_plan_payload()
        payload["reference_manifest"] = {
            "required_references": [
                {"role": "character", "name": "owner", "purpose": "lock face and outfit"},
                {"role": "human", "name": "landlord", "purpose": "lock second person"},
                {"role": "pet", "name": "golden dog", "purpose": "lock breed and fur"},
                {"role": "product", "name": "odor spray", "purpose": "product comes from product table"},
                {"role": "environment", "name": "living room", "purpose": "lock room layout"},
            ]
        }
        parent_fields = {
            "人物/宠物默认来源": "AI自动生成",
            "环境图来源": "手动上传",
            "参考图AI供应商": "OTU",
            "参考图AI模型": "OTU / gpt-image-2",
            "参考图AI参数JSON": '{"size":"1080x1920"}',
        }

        records = nine_grid.build_reference_asset_records(parent_fields, payload, parent_record_id="recParent", batch_id="batch1")
        fields = [item["fields"] for item in records]

        self.assertEqual([item["资产类型"] for item in fields], ["human", "human", "pet", "environment"])
        self.assertEqual([item["资产ID"] for item in fields], ["owner", "landlord", "golden_dog", "living_room"])
        self.assertEqual(fields[0]["参考图来源"], "AI自动生成")
        self.assertEqual(fields[0]["参考图生成状态"], "待生成")
        self.assertEqual(fields[-1]["参考图来源"], "手动上传")
        self.assertEqual(fields[-1]["参考图生成状态"], "不触发")
        self.assertIn("EMPTY ENVIRONMENT REFERENCE PLATE ONLY", fields[-1]["参考提示词"])

    def test_reference_manifest_product_only_falls_back_to_script_assets(self):
        payload = sample_plan_payload()
        payload["script_analysis"]["characters"] = ["owner", "roommate"]
        payload["script_analysis"]["pets"] = ["brown dog"]
        payload["script_analysis"]["environment"] = "Thai living room with sofa and coffee table"
        payload["reference_manifest"] = {
            "required_references": [
                {"role": "product", "name": "odor spray", "purpose": "use product table image"},
            ]
        }

        records = nine_grid.build_reference_asset_records(
            {"人物/宠物默认来源": "AI自动生成", "环境图来源": "AI自动生成"},
            payload,
            parent_record_id="recParent",
            batch_id="batch1",
        )
        fields = [item["fields"] for item in records]

        self.assertEqual([item["资产类型"] for item in fields], ["human", "human", "pet", "environment"])
        self.assertEqual([item["资产ID"] for item in fields], ["owner", "roommate", "brown_dog", "thai_living_room_with_sofa_and_coffee_table"])
        self.assertTrue(all(item["参考图生成状态"] == "待生成" for item in fields))

    def test_environment_reference_prompt_is_empty_scene_only(self):
        prompt = nine_grid.build_reference_asset_prompt({
            "asset_type": "environment",
            "asset_name": "living room",
            "purpose": "woman sprays product beside a dog in the living room",
        })

        self.assertIn("EMPTY ENVIRONMENT REFERENCE PLATE ONLY", prompt)
        self.assertIn("Do not include any people, pets, product bottles", prompt)
        self.assertNotIn("woman sprays product", prompt)

    def test_human_reference_prompt_requires_ordinary_ugc_realism(self):
        prompt = nine_grid.build_reference_asset_prompt({
            "asset_type": "human",
            "asset_name": "young Thai owner",
            "purpose": "lock face and outfit",
        })

        self.assertIn("ordinary non-professional local person", prompt)
        self.assertIn("not a studio model", prompt)
        self.assertIn("visible natural skin texture", prompt)
        self.assertIn("minor blemishes", prompt)
        self.assertIn("phone snapshot", prompt)

    def test_environment_reference_prompt_requires_lived_in_local_clutter(self):
        prompt = nine_grid.build_reference_asset_prompt({
            "asset_type": "environment",
            "asset_name": "Thai apartment living room",
            "purpose": "lock room layout and sofa position",
        })

        self.assertIn("lived-in local home", prompt)
        self.assertIn("everyday household clutter", prompt)
        self.assertIn("wear marks", prompt)
        self.assertIn("localized details", prompt)
        self.assertIn("Do not include any people, pets, product bottles", prompt)

    def test_collect_reference_images_uses_only_approved_parent_assets_and_product(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            product_path = tmp_path / "product.png"
            owner_path = tmp_path / "owner.png"
            env_path = tmp_path / "env.png"
            for path in (product_path, owner_path, env_path):
                path.write_bytes(b"x" * 2000)
            parent_fields = {"关联产品记录": [{"record_ids": ["recProduct"]}]}
            records = [
                {"record_id": "assetOwner", "fields": {
                    "记录类型": "参考资产",
                    "父任务记录ID": "recParent",
                    "资产ID": "owner",
                    "资产类型": "human",
                    "参考图审核状态": "通过",
                    "参考图": [{"file_token": "ft_owner"}],
                }},
                {"record_id": "assetDog", "fields": {
                    "记录类型": "参考资产",
                    "父任务记录ID": "recParent",
                    "资产ID": "dog_1",
                    "资产类型": "pet",
                    "参考图审核状态": "待确认",
                    "参考图": [{"file_token": "ft_dog"}],
                }},
                {"record_id": "assetEnv", "fields": {
                    "记录类型": "参考资产",
                    "父任务记录ID": "recParent",
                    "资产ID": "main_room",
                    "资产类型": "environment",
                    "参考图审核状态": "通过",
                    "参考图file_token": "ft_env",
                }},
            ]
            download = Mock(side_effect=[product_path, owner_path, env_path])

            refs = nine_grid.collect_nine_grid_reference_images(
                "token",
                parent_fields,
                "recParent",
                tmp_path,
                records=records,
                download_fn=download,
                get_record_fn=lambda token, table_id, record_id: {"产品图片": [{"file_token": "ft_product"}]},
            )

        self.assertEqual([ref["role"] for ref in refs], ["product:1", "human:owner", "environment:main_room"])
        self.assertEqual([call.args[1] for call in download.call_args_list], ["ft_product", "ft_owner", "ft_env"])

    def test_render_reference_asset_dry_run_reports_text_to_image_route(self):
        fields = {
            "记录类型": "参考资产",
            "父任务记录ID": "recParent",
            "资产类型": "human",
            "资产ID": "owner",
            "参考图来源": "AI自动生成",
            "参考提示词": "Generate the owner reference.",
            "参考图AI模型": "OTU / gpt-image-2",
        }

        with patch.object(nine_grid, "TABLE_NINE_GRID_VIDEO", "tbl_nine"), \
             patch.object(nine_grid, "get_feishu_token", return_value="token"), \
             patch.object(nine_grid, "safe_get_record", return_value=fields), \
             patch.object(nine_grid, "get_config_record", return_value=("cfg", {"api_key": "sk", "api_base": "https://otuapi.com", "model": "gpt-image-2"})), \
             patch.object(nine_grid, "safe_list_records", return_value=[]):
            result = nine_grid.render_reference_asset("recAsset", dry_run=True)

        self.assertEqual(result["status"], "dry_run_ready")
        self.assertEqual(result["route"]["capability"], "图片")
        self.assertEqual(result["route"]["payload"]["model"], "gpt-image-2")

    def test_render_reference_asset_submits_aitgenne_image_generation(self):
        fields = {
            "记录类型": "参考资产",
            "父任务记录ID": "recParent",
            "资产类型": "human",
            "资产ID": "owner",
            "参考图来源": "AI自动生成",
            "参考提示词": "Generate the owner reference.",
            "参考图AI供应商": "Aitgenne",
            "参考图AI模型": "Aitgenne / gpt-image-2",
            "参考图AI参数JSON": '{"size":"720x1280","aspect_ratio":"9:16"}',
        }

        with patch.object(nine_grid, "TABLE_NINE_GRID_VIDEO", "tbl_nine"), \
             patch.object(nine_grid, "get_feishu_token", return_value="token"), \
             patch.object(nine_grid, "safe_get_record", return_value=fields), \
             patch.object(nine_grid, "get_config_record", return_value=("cfg", {
                 "provider": "OTU",
                 "api_key": "sk-otu",
                 "api_base": "https://otuapi.com",
                 "model": "gpt-image-2",
             })), \
             patch.object(nine_grid, "safe_list_records", return_value=[
                 {"fields": {"AI供应商": "Aitgenne", "API 代理地址": "https://api.aitgenne.com", "API Key": "sk-aitgenne"}}
             ]), \
             patch.object(nine_grid, "submit_aitgenne_image_generation", return_value={"data": [{"url": "https://x.test/out.png"}]}) as submitter, \
             patch.object(nine_grid, "save_aitgenne_image_result") as saver, \
             patch.object(nine_grid, "upload_image_to_feishu", return_value="ft_out"), \
             patch.object(nine_grid, "safe_update_record"), \
             patch.object(nine_grid, "filter_existing_fields", side_effect=lambda token, table_id, fields: fields):
            result = nine_grid.render_reference_asset("recAsset")

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["file_token"], "ft_out")
        self.assertEqual(submitter.call_args.args[0]["api_key"], "sk-aitgenne")
        self.assertEqual(submitter.call_args.args[0]["api_base"], "https://api.aitgenne.com")
        self.assertEqual(submitter.call_args.args[0]["model"], "gpt-image-2")
        self.assertEqual(submitter.call_args.args[1], "Generate the owner reference.")
        self.assertEqual(submitter.call_args.kwargs["size"], "720x1280")
        saver.assert_called_once()

    def test_plan_dry_run_infers_provider_from_prefixed_model(self):
        parent_fields = {
            "记录类型": "母任务",
            "脚本内容": "A short nine-grid script.",
            "方案AI模型": "Aitgenne / gpt-5.5",
        }

        with patch.object(nine_grid, "TABLE_NINE_GRID_VIDEO", "tbl_nine"), \
             patch.object(nine_grid, "get_feishu_token", return_value="token"), \
             patch.object(nine_grid, "safe_get_record", return_value=parent_fields), \
             patch.object(nine_grid, "get_config_record", return_value=("cfg", {
                 "provider": "AIHubMix",
                 "api_key": "sk-aihubmix",
                 "api_base": "https://aihubmix.com/gemini",
                 "model": "gemini-3.1-pro-preview",
                 "call_type": "Gemini 原生 SDK",
             })), \
             patch.object(nine_grid, "safe_list_records", return_value=[
                 {"fields": {"AI供应商": "Aitgenne", "API 代理地址": "https://api.aitgenne.com", "API Key": "sk-aitgenne"}}
             ]):
            result = nine_grid.split_nine_grid_plan("recParent", dry_run=True)

        self.assertEqual(result["status"], "dry_run_ready")
        self.assertEqual(result["route"]["provider"], "Aitgenne")
        self.assertEqual(result["route"]["model"], "gpt-5.5")
        self.assertEqual(result["route"]["call_type"], "OpenAI兼容 chat/completions")
        self.assertEqual(result["route"]["endpoint"], "https://api.aitgenne.com/v1/chat/completions")

    def test_dispatcher_parses_json_error_after_warning_lines(self):
        stderr = (
            "/Users/ryanlynn/Library/Python/3.9/lib/python/site-packages/google/auth/__init__.py:54: "
            "FutureWarning: You are using a Python version 3.9 past its end of life.\n"
            "  warnings.warn(eol_message.format(\"3.9\"), FutureWarning)\n"
            '{"stage": "nine_grid_plan", "status": "failed_terminal", "error_code": "RUNTIME_BUG", '
            '"retryable": false, "message": "AI模型供应商不匹配: AI供应商=AIHubMix, AI模型=Aitgenne / gpt-5.5"}\n'
        )

        payload = dispatcher.parse_subprocess_error_payload("", stderr, "tk_nine_grid_video.py")

        self.assertEqual(payload["message"], "AI模型供应商不匹配: AI供应商=AIHubMix, AI模型=Aitgenne / gpt-5.5")

    def test_video_dry_run_uses_video_prefixed_route_fields(self):
        child_fields = {
            "父任务记录ID": "recParent",
            "九宫格图": [{"file_token": "ft_grid"}],
            "视频提示词": "Turn the nine-grid into one continuous video.",
            "视频AI供应商": "OTU",
            "视频AI模型": "OTU / veo_3_1-fast-fl",
            "视频AI参数JSON": '{"seconds":"10","size":"720x1280","aspect_ratio":"9:16"}',
            "视频画面尺寸": "720x1280",
            "视频画面比例": "9:16",
        }

        with patch.object(nine_grid, "TABLE_NINE_GRID_VIDEO", "tbl_nine"), \
             patch.object(nine_grid, "get_feishu_token", return_value="token"), \
             patch.object(nine_grid, "safe_get_record", return_value=child_fields), \
             patch.object(nine_grid, "get_config_record", return_value=("cfg", {"api_key": "sk", "api_base": "https://otuapi.com", "model": "veo_3_1-fast-fl"})), \
             patch.object(nine_grid, "safe_list_records", return_value=[]):
            result = nine_grid.render_nine_grid_video("recBoard", dry_run=True)

        self.assertEqual(result["status"], "dry_run_ready")
        self.assertEqual(result["route"]["capability"], "视频")
        self.assertEqual(result["route"]["payload"]["model"], "veo_3_1-fast-fl")
        self.assertEqual(result["route"]["payload"]["seconds"], "10")


if __name__ == "__main__":
    unittest.main()
