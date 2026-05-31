import sys
import unittest
from pathlib import Path
from unittest.mock import patch

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

    def test_table_definition_has_clean_entry_review_generation_views(self):
        self.assertEqual(create_table.TABLE_DEFINITION["key"], "nine_grid_video")
        field_names = [field["name"] for field in create_table.NINE_GRID_VIDEO_FIELDS]
        for name in [
            "方案生成状态", "方案JSON", "审核状态", "九宫格图片提示词", "视频提示词",
            "方案AI供应商", "方案AI模型", "图片AI供应商", "图片AI模型", "视频AI供应商", "视频AI模型",
        ]:
            self.assertIn(name, field_names)
        self.assertEqual(
            create_table.TABLE_DEFINITION["views"]["01-任务入口"],
            ["任务名称", "脚本内容", "关联产品记录", "选择模特", "环境图", "方案AI模型", "方案AI参数JSON", "方案生成状态", "错误信息"],
        )
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
             patch.object(nine_grid, "get_config_record", return_value=("cfg", {"api_key": "sk", "api_base": "https://otuapi.com", "model": "gpt-image-2"})):
            result = nine_grid.render_nine_grid_image("recBoard", dry_run=True)

        self.assertEqual(result["status"], "dry_run_ready")
        self.assertEqual(result["route"]["capability"], "图片")
        self.assertEqual(result["route"]["payload"]["model"], "gpt-image-2")
        self.assertEqual(result["route"]["payload"]["size"], "1080x1920")

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
             patch.object(nine_grid, "get_config_record", return_value=("cfg", {"api_key": "sk", "api_base": "https://otuapi.com", "model": "veo_3_1-fast-fl"})):
            result = nine_grid.render_nine_grid_video("recBoard", dry_run=True)

        self.assertEqual(result["status"], "dry_run_ready")
        self.assertEqual(result["route"]["capability"], "视频")
        self.assertEqual(result["route"]["payload"]["model"], "veo_3_1-fast-fl")
        self.assertEqual(result["route"]["payload"]["seconds"], "10")


if __name__ == "__main__":
    unittest.main()
