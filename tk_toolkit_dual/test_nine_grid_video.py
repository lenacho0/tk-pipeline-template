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


def sample_thai_script_text():
    return """
分镜
时间
画面
说话人
说话方式
完整声纹描述
本地化口播文案 (泰语)
中文理解
S01
0.0-2.0s
中景：客人刚进门，指着地毯。特写地毯黄渍。客人夸张捂鼻倒退。
客人
嫌弃大喊
Young Thai male, loud, disgusted
客人：เฮ้ย! ทำไมพรมแกเหลืองงี้ กลิ่นฉี่หึ่งเลย!
客人：我去！你家地毯怎么黄了，还一股尿骚味！
S02
2.0-3.5s
近景：主人急满头大汗，从背后光速掏出带有黄绿标签的喷雾瓶。
主人
急促打断
Young Thai male, panicked but fast
主人：แป๊บนะ! ขอเวลา 3 วินาที!
主人：等下！给我三秒钟！
S03
3.5-5.5s
特写：对准地毯黄渍狂喷，白泡瞬间覆盖。
主人
边做边说
Young Thai male, fast
主人：สเปรย์สลายกลิ่นฉี่ จัดการคราบฝังลึกโดยเฉพาะ!
主人：尿味分解喷雾，专门对付陈年尿渍！
S04
5.5-7.5s
特写：主人拿纸巾用力一按一擦，黄渍瞬间消失，地毯变干净。
无
无口播
强烈的摩擦声和清脆的“叮”音效
（无）
纯视觉展示去黄效果。
S05
7.5-10.0s
中景：客人蹲下深吸一口气，震惊脸。小狗在旁边摇尾巴。
客人/主人
震惊/得意
Young Thai male, shocked / proud
客人：เอ๊ะ? ไม่มีกลิ่นแล้วจริงดิ?
主人：สลายกลิ่นฉี่ ไม่ทิ้งคราบเหลือง!
客人：咦？真没味了？
主人：分解尿味，不留黄印！
""".strip()


class NineGridVideoTests(unittest.TestCase):
    def setUp(self):
        self._auto_review_patcher = patch.object(nine_grid, "auto_review_enabled", return_value=False)
        self._auto_review_patcher.start()

    def tearDown(self):
        self._auto_review_patcher.stop()

    def test_auto_approve_reference_asset_advances_boards_when_enabled(self):
        updates = []
        with patch.object(nine_grid, "TABLE_NINE_GRID_VIDEO", "tbl_nine"), \
             patch.object(nine_grid, "auto_review_enabled", return_value=True) as enabled, \
             patch.object(nine_grid, "advance_boards_after_reference_approval", return_value={"advanced_boards": 3}) as advance, \
             patch.object(nine_grid, "safe_update_record", side_effect=lambda token, table, rid, fields: updates.append((rid, fields))), \
             patch.object(nine_grid, "filter_existing_fields", side_effect=lambda token, table, fields: fields):
            result = nine_grid.maybe_auto_approve_reference_asset(
                "token",
                "asset_ref",
                {"父任务记录ID": "parent", "参考图操作": "不触发"},
                file_token="ft_ref",
            )

        self.assertEqual(result["status"], "auto_approved")
        enabled.assert_called_once_with("token", stage_name=nine_grid.AUTO_REVIEW_STAGE_NAME)
        self.assertIn(("asset_ref", {"参考图审核状态": "通过", "参考图操作": "不触发", "错误信息": ""}), updates)
        advance.assert_called_once_with("token", "parent")

    def test_auto_approve_reference_asset_skips_regeneration_and_missing_token(self):
        with patch.object(nine_grid, "auto_review_enabled", return_value=True), \
             patch.object(nine_grid, "safe_update_record") as updater:
            result = nine_grid.maybe_auto_approve_reference_asset(
                "token",
                "asset_ref",
                {"父任务记录ID": "parent", "参考图操作": "重新生成参考图"},
                file_token="ft_ref",
            )
        self.assertEqual(result["status"], "manual_regeneration")
        updater.assert_not_called()

        with patch.object(nine_grid, "auto_review_enabled", return_value=True), \
             patch.object(nine_grid, "safe_update_record") as updater:
            result = nine_grid.maybe_auto_approve_reference_asset(
                "token",
                "asset_ref",
                {"父任务记录ID": "parent", "参考图操作": "不触发"},
                file_token="",
            )
        self.assertEqual(result["status"], "skipped")
        updater.assert_not_called()

    def test_plan_system_prompt_requires_dynamic_environment_problem_anchors(self):
        prompt = prompts.NINE_GRID_PLAN_SYSTEM_PROMPT

        for required in [
            "根据脚本判断",
            "不能默认套用尿渍",
            "不能默认套用虫害",
            "不得编造事故点",
            "直接给图片模型使用",
        ]:
            self.assertIn(required, prompt)

    def test_prompt_constants_are_supplier_neutral_and_define_json_truth(self):
        self.assertIn("JSON", prompts.NINE_GRID_PLAN_SYSTEM_PROMPT)
        self.assertIn("MULTI_IMAGE_NINE_GRID_PLAN", prompts.NINE_GRID_PLAN_SYSTEM_PROMPT)
        self.assertIn("不要提具体供应商或模型名", prompts.NINE_GRID_IMAGE_SYSTEM_PROMPT)
        self.assertIn("不要提具体供应商或模型名", prompts.NINE_GRID_VIDEO_SYSTEM_PROMPT)
        self.assertIn("Use a colon after the speaker action", prompts.NINE_GRID_VIDEO_SYSTEM_PROMPT)
        self.assertIn("Sound effects", prompts.NINE_GRID_VIDEO_SYSTEM_PROMPT)
        self.assertIn("Ambient noise", prompts.NINE_GRID_VIDEO_SYSTEM_PROMPT)
        self.assertIn("Dialogue", prompts.NINE_GRID_VIDEO_SYSTEM_PROMPT)
        self.assertIn("do not wrap spoken lines in quotation marks", prompts.NINE_GRID_VIDEO_SYSTEM_PROMPT)
        self.assertIn("Timeline beats", prompts.NINE_GRID_PLAN_SYSTEM_PROMPT)
        self.assertIn("Dialogue/Voiceover", prompts.NINE_GRID_VIDEO_SYSTEM_PROMPT)
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

    def test_build_board_video_prompt_binds_cell_thai_dialogue_to_timeline_beat(self):
        payload = sample_plan_payload()
        board = payload["boards"][0]
        board["cells"][2]["dialogue_or_voiceover"] = "Guest says in Thai: เฮ้ย! ทำไมพรมแกเหลืองงี้"
        board.pop("video_prompt", None)

        prompt = nine_grid.build_board_video_prompt(board)

        self.assertIn("Timeline beats:", prompt)
        self.assertIn("Cell 3 / approx", prompt)
        self.assertIn("Dialogue/Voiceover: เฮ้ย! ทำไมพรมแกเหลืองงี้", prompt)
        self.assertLess(prompt.index("Cell 3 / approx"), prompt.index("Dialogue/Voiceover: เฮ้ย! ทำไมพรมแกเหลืองงี้"))
        self.assertNotIn("Guest says in Thai", prompt)
        self.assertIn("Cell 1 / approx", prompt)
        self.assertIn("Dialogue/Voiceover: No speech; natural room tone only.", prompt)
        self.assertIn("Audio constraints:", prompt)

    def test_extract_script_thai_dialogue_removes_inline_chinese_translation(self):
        script = (
            "老公烦躁抱怨young Thai male, annoyed, loud"
            "เหม็นฉี่หมาไม่ไหวแล้ว! เบาะรถพังหมด แวะจอดเลย!"
            "狗尿味受不了了！车座全毁了，快停车！"
        )

        lines = nine_grid.extract_script_thai_dialogue(script)

        self.assertEqual(lines[0]["text"], "เหม็นฉี่หมาไม่ไหวแล้ว! เบาะรถพังหมด แวะจอดเลย!")

    def test_audio_constraints_do_not_duplicate_dialogue_as_tail_list(self):
        prompt = "Thai dialogue timing: owner says 'ฉันทนกลิ่นไม่ไหวแล้ว ต้องยกให้คนอื่น!' in the opening."

        result = nine_grid.append_audio_dialogue_to_video_prompt(
            prompt,
            ["ฉันทนกลิ่นไม่ไหวแล้ว ต้องยกให้คนอื่น!"],
        )

        self.assertIn("Thai dialogue timing", result)
        self.assertIn("Audio constraints:", result)
        self.assertNotIn("- ฉันทนกลิ่นไม่ไหวแล้ว ต้องยกให้คนอื่น!", result)

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
        self.assertEqual(fields["视频AI模型"], "OTU / omni_flash-10s")
        self.assertIn("图片AI供应商", fields)
        self.assertIn("图片AI模型", fields)
        self.assertIn("视频AI供应商", fields)
        self.assertIn("视频AI模型", fields)

    def test_child_board_video_prompt_binds_original_thai_dialogue_to_timeline_beats(self):
        parent_fields = {
            "任务名称": "nine-grid task",
            "脚本内容": sample_thai_script_text(),
        }
        payload = sample_plan_payload()
        payload["boards"][0]["video_prompt"] = "Generate a 10-second scene with the guest complaining and the host cleaning."
        payload["boards"][0]["cells"][2]["dialogue_or_voiceover"] = "客人嫌弃大喊：我去！你家地毯怎么黄了，还一股尿骚味！"

        records = nine_grid.build_child_board_records(
            parent_fields,
            payload,
            parent_record_id="recParent",
            batch_id="NINEGRID-1",
        )

        prompt = records[0]["fields"]["视频提示词"]
        self.assertIn("Timeline beats:", prompt)
        self.assertIn("Cell 3 / approx", prompt)
        self.assertIn("Dialogue/Voiceover: เฮ้ย! ทำไมพรมแกเหลืองงี้ กลิ่นฉี่หึ่งเลย!", prompt)
        self.assertIn("Cell 4 / approx", prompt)
        self.assertIn("Dialogue/Voiceover: แป๊บนะ! ขอเวลา 3 วินาที!", prompt)
        self.assertIn("เฮ้ย! ทำไมพรมแกเหลืองงี้ กลิ่นฉี่หึ่งเลย!", prompt)
        self.assertIn("แป๊บนะ! ขอเวลา 3 วินาที!", prompt)
        self.assertIn("สเปรย์สลายกลิ่นฉี่ จัดการคราบฝังลึกโดยเฉพาะ!", prompt)
        self.assertIn("เอ๊ะ? ไม่มีกลิ่นแล้วจริงดิ?", prompt)
        self.assertIn("สลายกลิ่นฉี่ ไม่ทิ้งคราบเหลือง!", prompt)
        self.assertNotIn("客人：", prompt)
        self.assertNotIn("主人：", prompt)
        self.assertNotIn("我去！你家地毯怎么黄了", prompt)
        self.assertNotIn("Audio / spoken dialogue:", prompt)

    def test_child_board_video_prompt_filters_thai_dialogue_by_board_time_range(self):
        parent_fields = {
            "任务名称": "two-board task",
            "脚本内容": sample_thai_script_text(),
        }
        payload = sample_plan_payload()
        first_board = payload["boards"][0]
        first_board["time_range"] = "0-3.5s"
        first_board["video_prompt"] = "Generate board one."
        second_board = dict(first_board)
        second_board["board_index"] = 2
        second_board["time_range"] = "3.5-10s"
        second_board["video_prompt"] = "Generate board two."
        payload["boards"] = [first_board, second_board]

        records = nine_grid.build_child_board_records(
            parent_fields,
            payload,
            parent_record_id="recParent",
            batch_id="NINEGRID-1",
        )

        first_prompt = records[0]["fields"]["视频提示词"]
        second_prompt = records[1]["fields"]["视频提示词"]
        self.assertIn("Dialogue/Voiceover: เฮ้ย! ทำไมพรมแกเหลืองงี้ กลิ่นฉี่หึ่งเลย!", first_prompt)
        self.assertIn("Dialogue/Voiceover: แป๊บนะ! ขอเวลา 3 วินาที!", first_prompt)
        self.assertNotIn("สเปรย์สลายกลิ่นฉี่", first_prompt)
        self.assertIn("Dialogue/Voiceover: สเปรย์สลายกลิ่นฉี่ จัดการคราบฝังลึกโดยเฉพาะ!", second_prompt)
        self.assertIn("Dialogue/Voiceover: เอ๊ะ? ไม่มีกลิ่นแล้วจริงดิ?", second_prompt)
        self.assertNotIn("แป๊บนะ! ขอเวลา 3 วินาที!", second_prompt)

    def test_child_board_records_wait_when_reference_assets_need_review(self):
        records = nine_grid.build_child_board_records(
            {"任务名称": "nine-grid task"},
            sample_plan_payload(),
            parent_record_id="recParent",
            batch_id="NINEGRID-1",
            await_reference_assets=True,
        )

        self.assertEqual(records[0]["fields"]["图片生成状态"], "不触发")

    def test_reference_approval_does_not_advance_boards_until_all_assets_pass(self):
        records = [
            {
                "record_id": "asset1",
                "fields": {
                    "记录类型": "参考资产",
                    "父任务记录ID": "recParent",
                    "参考图": [{"file_token": "file1"}],
                    "参考图审核状态": "通过",
                },
            },
            {
                "record_id": "asset2",
                "fields": {
                    "记录类型": "参考资产",
                    "父任务记录ID": "recParent",
                    "参考图": [{"file_token": "file2"}],
                    "参考图审核状态": "待确认",
                },
            },
            {
                "record_id": "board1",
                "fields": {
                    "记录类型": "Board分段",
                    "父任务记录ID": "recParent",
                    "图片生成状态": "不触发",
                },
            },
        ]

        with patch.object(nine_grid, "TABLE_NINE_GRID_VIDEO", "tbl_nine"), \
             patch.object(nine_grid, "safe_list_records", return_value=records), \
             patch.object(nine_grid, "safe_update_record") as update_record:
            summary = nine_grid.advance_boards_after_reference_approval("token", "recParent")

        self.assertEqual(summary["advanced_boards"], 0)
        self.assertEqual(summary["status"], "waiting_for_reference_approval")
        update_record.assert_not_called()

    def test_reference_approval_advances_only_untriggered_boards(self):
        records = [
            {
                "record_id": "asset1",
                "fields": {
                    "记录类型": "参考资产",
                    "父任务记录ID": "recParent",
                    "参考图": [{"file_token": "file1"}],
                    "参考图审核状态": "通过",
                },
            },
            {
                "record_id": "board1",
                "fields": {
                    "记录类型": "Board分段",
                    "父任务记录ID": "recParent",
                    "图片生成状态": "不触发",
                },
            },
            {
                "record_id": "board2",
                "fields": {
                    "记录类型": "Board分段",
                    "父任务记录ID": "recParent",
                    "图片生成状态": "待生成",
                },
            },
            {
                "record_id": "board3",
                "fields": {
                    "记录类型": "Board分段",
                    "父任务记录ID": "recParent",
                    "图片生成状态": "失败",
                },
            },
        ]
        updates = []

        with patch.object(nine_grid, "TABLE_NINE_GRID_VIDEO", "tbl_nine"), \
             patch.object(nine_grid, "safe_list_records", return_value=records), \
             patch.object(nine_grid, "filter_existing_fields", side_effect=lambda token, table, fields: fields), \
             patch.object(nine_grid, "safe_update_record", side_effect=lambda token, table, rid, fields: updates.append((rid, fields))):
            summary = nine_grid.advance_boards_after_reference_approval("token", "recParent")

        self.assertEqual(summary["status"], "advanced")
        self.assertEqual(summary["advanced_boards"], 1)
        self.assertEqual(updates, [("board1", {"图片生成状态": "待生成", "错误信息": ""})])

    def test_table_definition_has_clean_entry_review_generation_views(self):
        self.assertEqual(create_table.TABLE_DEFINITION["key"], "nine_grid_video")
        field_names = [field["name"] for field in create_table.NINE_GRID_VIDEO_FIELDS]
        for name in [
            "方案生成状态", "方案JSON", "审核状态", "九宫格图片提示词", "视频提示词",
            "方案AI供应商", "方案AI模型", "图片AI供应商", "图片AI模型", "视频AI供应商", "视频AI模型",
            "人物/宠物默认来源", "环境图来源", "资产ID", "资产类型", "参考图来源", "参考图",
            "参考图生成状态", "参考图审核状态", "参考图操作",
            "参考图画面尺寸", "参考图画面比例",
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
        reference_view = create_table.TABLE_DEFINITION["views"]["02-参考资产确认"]
        self.assertIn("参考图画面尺寸", reference_view)
        self.assertIn("参考图画面比例", reference_view)
        video_view = create_table.TABLE_DEFINITION["views"]["04-视频生成"]
        self.assertIn("视频生成模型", video_view)
        self.assertNotIn("视频AI模型", video_view)
        self.assertNotIn("视频AI参数JSON", video_view)
        advanced_view = create_table.TABLE_DEFINITION["views"]["高级AI参数"]
        for name in ["方案AI供应商", "参考图AI供应商", "图片AI供应商"]:
            self.assertIn(name, advanced_view)
        self.assertIn("视频生成模型", advanced_view)
        self.assertNotIn("视频AI供应商", advanced_view)
        self.assertNotIn("视频AI模型", advanced_view)
        self.assertNotIn("视频AI参数JSON", advanced_view)
        for name in [
            "参考图画面尺寸",
            "参考图画面比例",
            "图片画面尺寸",
            "图片画面比例",
            "视频画面尺寸",
            "视频画面比例",
        ]:
            self.assertIn(name, advanced_view)
            self.assertIn(name, create_table.TABLE_DEFINITION["views"]["99-排错"])
        self.assertIn("视频生成模型", create_table.TABLE_DEFINITION["views"]["99-排错"])
        self.assertIn("视频AI模型", create_table.TABLE_DEFINITION["views"]["99-排错"])

    def test_nine_grid_model_options_are_split_by_capability(self):
        field_by_name = {field["name"]: field for field in create_table.NINE_GRID_VIDEO_FIELDS}
        plan_options = [item["name"] for item in field_by_name["方案AI模型"]["options"]]
        image_options = [item["name"] for item in field_by_name["图片AI模型"]["options"]]
        video_options = [item["name"] for item in field_by_name["视频AI模型"]["options"]]
        video_generation_options = [item["name"] for item in field_by_name["视频生成模型"]["options"]]

        self.assertIn("Aitgenne / gpt-5.5", plan_options)
        self.assertIn("OTU / gpt-image-2-4K", image_options)
        self.assertIn("Aitgenne / gpt-image-2", image_options)
        self.assertEqual(video_options, [
            "OTU / omni_flash-10s",
            "Aitgenne / happyhorse-1.0-r2v",
            "Aitgenne / omni-flash",
        ])
        self.assertEqual(video_generation_options, ["默认（配置表）", *video_options])
        self.assertNotIn("OTU / gpt-image-2", plan_options)
        self.assertNotIn("Aitgenne / gpt-5.5", image_options)
        self.assertNotIn("OTU / nano_banana_pro-4K", image_options)
        self.assertNotIn("Aitgenne / happyhorse-1.0-i2v", video_options)
        self.assertNotIn("OTU / veo_3_1-fast-fl", video_options)

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
        self.assertEqual(watches["多图九宫格参考图生成"]["trigger_values"], ["待生成", "生成中"])
        reference_waiting_claim = {"参考图生成状态": "生成中"}
        dispatcher.apply_claim_clear_fields(reference_waiting_claim, watches["多图九宫格参考图生成"], "待生成")
        self.assertEqual(reference_waiting_claim["参考图任务ID"], "")

        reference_running_claim = {"参考图生成状态": "生成中"}
        dispatcher.apply_claim_clear_fields(reference_running_claim, watches["多图九宫格参考图生成"], "生成中")
        self.assertNotIn("参考图任务ID", reference_running_claim)
        self.assertEqual(
            watches["多图九宫格参考图审核推进"]["required_field_values"],
            {"记录类型": ["参考资产"], "参考图审核状态": ["通过"]},
        )
        self.assertEqual(watches["多图九宫格参考图审核推进"]["failed_value"], "通过")
        self.assertEqual(
            watches["多图九宫格图片生成"]["required_field_values"],
            {"记录类型": ["Board分段"]},
        )
        self.assertEqual(watches["多图九宫格图片生成"]["trigger_values"], ["待生成", "生成中"])
        image_waiting_claim = {"图片生成状态": "生成中"}
        dispatcher.apply_claim_clear_fields(image_waiting_claim, watches["多图九宫格图片生成"], "待生成")
        self.assertEqual(image_waiting_claim["图片任务ID"], "")

        image_running_claim = {"图片生成状态": "生成中"}
        dispatcher.apply_claim_clear_fields(image_running_claim, watches["多图九宫格图片生成"], "生成中")
        self.assertNotIn("图片任务ID", image_running_claim)
        self.assertEqual(
            watches["多图九宫格视频生成"]["required_field_values"],
            {"记录类型": ["Board分段"]},
        )
        self.assertEqual(watches["多图九宫格视频生成"]["trigger_values"], ["待生成", "生成中"])
        self.assertEqual(
            watches["多图九宫格视频生成"]["claim_clear_fields_by_trigger_value"],
            {"待生成": ["视频任务ID"]},
        )

        waiting_claim = {"视频生成状态": "生成中"}
        dispatcher.apply_claim_clear_fields(waiting_claim, watches["多图九宫格视频生成"], "待生成")
        self.assertEqual(waiting_claim["视频任务ID"], "")

        running_claim = {"视频生成状态": "生成中"}
        dispatcher.apply_claim_clear_fields(running_claim, watches["多图九宫格视频生成"], "生成中")
        self.assertNotIn("视频任务ID", running_claim)

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
        self.assertEqual(wanted[2]["模型名称"], "omni_flash-10s")

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
        self.assertEqual(result["route"]["payload"]["size"], "720x1280")

    def test_render_nine_grid_image_uses_contact_sheet_for_otu_references(self):
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
             patch.object(nine_grid, "build_reference_contact_sheet", return_value="/tmp/contact.png", create=True) as contact_sheet, \
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
        contact_sheet.assert_called_once()
        self.assertEqual(kwargs["image_path"], "/tmp/contact.png")
        self.assertIsNone(kwargs["reference_image_paths"])
        self.assertEqual(kwargs["metadata"]["reference_roles"], ["product:1", "human:owner", "environment:main_room"])
        self.assertIn("PRODUCT REFERENCE LOCK", submitter.call_args.args[1])
        self.assertNotIn("exact_product_overlay_cells", result)

    def test_render_nine_grid_image_otu_2k_overrides_stale_720_size(self):
        child_fields = {
            "父任务记录ID": "recParent",
            "九宫格图片提示词": "Show the selected spray product in the nine-grid.",
            "图片AI供应商": "OTU",
            "图片AI模型": "OTU / gpt-image-2-2K",
            "图片AI参数JSON": '{"size":"720x1280","aspect_ratio":"9:16"}',
            "图片画面尺寸": "720x1280",
            "图片画面比例": "9:16",
        }
        refs = [
            {"role": "product:1", "path": "/tmp/product.png", "file_token": "ft_product", "name": "odor spray"},
        ]
        updates = []

        with patch.object(nine_grid, "ensure_nine_grid_table"), \
             patch.object(nine_grid, "TABLE_NINE_GRID_VIDEO", "tbl_nine"), \
             patch.object(nine_grid, "get_feishu_token", return_value="token"), \
             patch.object(nine_grid, "safe_get_record", side_effect=[child_fields, {"记录类型": "母任务"}]), \
             patch.object(nine_grid, "get_config_record", return_value=("cfg", {"api_key": "sk", "api_base": "https://otuapi.com", "model": "gpt-image-2"})), \
             patch.object(nine_grid, "safe_list_records", return_value=[]), \
             patch.object(nine_grid, "collect_nine_grid_reference_images", return_value=refs), \
             patch.object(nine_grid, "build_reference_urls", return_value=["https://x.test/product.png"]), \
             patch.object(nine_grid, "build_reference_contact_sheet", return_value="/tmp/contact.png", create=True), \
             patch.object(nine_grid, "submit_otu_image_task", return_value=("task_2k", {"id": "task_2k"})) as submitter, \
             patch.object(nine_grid, "poll_otu_image_task", return_value={"result_url": "https://x.test/out.png"}), \
             patch.object(nine_grid, "download_otu_image_result"), \
             patch.object(nine_grid, "upload_image_to_feishu", return_value="ft_out"), \
             patch.object(nine_grid, "safe_update_record", side_effect=lambda token, table_id, record_id, fields: updates.append(fields)), \
             patch.object(nine_grid, "filter_existing_fields", side_effect=lambda token, table_id, fields: fields):
            result = nine_grid.render_nine_grid_image("recBoard")

        self.assertEqual(result["status"], "success")
        self.assertEqual(submitter.call_args.args[0]["model"], "gpt-image-2-2K")
        self.assertEqual(submitter.call_args.kwargs["size"], "1080x1920")
        self.assertEqual(submitter.call_args.kwargs["metadata"]["size"], "1080x1920")
        self.assertTrue(any(update.get("图片画面尺寸") == "1080x1920" for update in updates))

    def test_render_nine_grid_image_resumes_existing_otu_task_without_resubmitting(self):
        child_fields = {
            "父任务记录ID": "recParent",
            "九宫格图片提示词": "Show the selected spray product in the nine-grid.",
            "图片AI供应商": "OTU",
            "图片AI模型": "OTU / gpt-image-2",
            "图片生成状态": "生成中",
            "图片任务ID": "task_existing_image",
            "图片原始响应JSON": '{"submit":{"id":"task_existing_image"}}',
        }
        updates = []

        with patch.object(nine_grid, "ensure_nine_grid_table"), \
             patch.object(nine_grid, "TABLE_NINE_GRID_VIDEO", "tbl_nine"), \
             patch.object(nine_grid, "get_feishu_token", return_value="token"), \
             patch.object(nine_grid, "safe_get_record", side_effect=[child_fields, {"记录类型": "母任务"}]), \
             patch.object(nine_grid, "get_config_record", return_value=("cfg", {"api_key": "sk", "api_base": "https://otuapi.com", "model": "gpt-image-2"})), \
             patch.object(nine_grid, "safe_list_records", return_value=[]), \
             patch.object(nine_grid, "collect_nine_grid_reference_images") as collect_refs, \
             patch.object(nine_grid, "build_reference_urls") as build_urls, \
             patch.object(nine_grid, "build_reference_contact_sheet") as contact_sheet, \
             patch.object(nine_grid, "submit_otu_image_task") as submitter, \
             patch.object(nine_grid, "poll_otu_image_task", return_value={"result_url": "https://x.test/out.png"}) as poller, \
             patch.object(nine_grid, "download_otu_image_result"), \
             patch.object(nine_grid, "upload_image_to_feishu", return_value="ft_out"), \
             patch.object(nine_grid, "safe_update_record", side_effect=lambda token, table_id, record_id, fields: updates.append(fields)), \
             patch.object(nine_grid, "filter_existing_fields", side_effect=lambda token, table_id, fields: fields):
            result = nine_grid.render_nine_grid_image("recBoard")

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["task_id"], "task_existing_image")
        submitter.assert_not_called()
        collect_refs.assert_not_called()
        build_urls.assert_not_called()
        contact_sheet.assert_not_called()
        poller.assert_called_once()
        self.assertEqual(poller.call_args.args[1], "task_existing_image")
        self.assertIn("恢复轮询已有 OTU 九宫格图片任务", updates[0]["图片错误信息"])

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
        self.assertIn("white background", fields[0]["参考提示词"])
        self.assertIn("front-facing upper-body", fields[0]["参考提示词"])
        self.assertIn("full unobstructed face visible", fields[0]["参考提示词"])
        self.assertIn("no side profile", fields[0]["参考提示词"])
        self.assertIn("no multi-view", fields[0]["参考提示词"])
        self.assertNotIn("full-body human", fields[0]["参考提示词"])
        self.assertNotIn("everyday background", fields[0]["参考提示词"])
        self.assertEqual(fields[-1]["参考图来源"], "手动上传")
        self.assertEqual(fields[-1]["参考图生成状态"], "不触发")
        self.assertIn("EMPTY ENVIRONMENT REFERENCE PLATE ONLY", fields[-1]["参考提示词"])

    def test_human_reference_asset_prompt_is_wrapped_before_rendering(self):
        prompt = nine_grid.build_reference_image_generation_prompt({
            "资产类型": "human",
            "参考提示词": "Generate the owner reference.",
        })

        self.assertIn("white background", prompt)
        self.assertIn("front-facing upper-body", prompt)
        self.assertIn("full unobstructed face visible", prompt)
        self.assertIn("no side profile", prompt)
        self.assertIn("no multi-view", prompt)
        self.assertIn("Generate the owner reference.", prompt)

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

    def test_environment_reference_prompt_is_direct_image_prompt_without_script_meta(self):
        prompt = nine_grid.build_reference_asset_prompt({
            "asset_type": "environment",
            "asset_name": "Thai family living room",
            "purpose": "lock room layout and sofa position",
        })
        lowered = prompt.lower()

        self.assertIn("Scene details:", prompt)
        self.assertNotIn("Scene details to keep:", prompt)
        for forbidden in ["source script", "script-defined", "if one exists", "when present in the script"]:
            self.assertNotIn(forbidden, lowered)

    def test_environment_reference_prompt_removes_legacy_source_script_sentence(self):
        prompt = nine_grid.sanitize_environment_reference_prompt(
            "EMPTY ENVIRONMENT REFERENCE PLATE ONLY.\n"
            "Generate one empty but lived-in local home environment reference plate for later use as a consistency reference.\n"
            "Do not add any problem mark that is not explicitly present in the source script.\n"
            "Scene details to keep:\n"
            "Thai living room with beige sofa and visible black fleas on the center cushion."
        )
        lowered = prompt.lower()

        self.assertIn("visible black fleas", prompt)
        self.assertNotIn("source script", lowered)
        self.assertNotIn("Scene details to keep:", prompt)

    def test_environment_reference_prompt_keeps_natural_light_and_dynamic_urine_ring(self):
        prompt = nine_grid.build_reference_asset_prompt({
            "asset_type": "environment",
            "asset_name": "bedroom beside white thick mattress",
            "purpose": "lock room, furniture, natural light, problem location with yellow urine ring",
        })

        self.assertIn("natural light", prompt)
        self.assertIn("yellow urine ring", prompt)
        self.assertNotIn("fleas", prompt)
        self.assertNotIn("ticks", prompt)

    def test_environment_reference_prompt_keeps_infestation_without_inventing_urine(self):
        prompt = nine_grid.build_reference_asset_prompt({
            "asset_type": "environment",
            "asset_name": "Thai family living room with beige fabric sofa",
            "purpose": "lock room, furniture, light: the center of the beige sofa cushion is covered by many visible crawling black fleas or ticks around the cat",
        })

        self.assertIn("beige sofa cushion", prompt)
        self.assertIn("black fleas or ticks", prompt)
        self.assertNotIn("urine", prompt.lower())
        self.assertNotIn("wet patch", prompt.lower())
        self.assertNotIn("urine ring", prompt.lower())

    def test_environment_reference_prompt_keeps_damage_without_inventing_urine_or_insects(self):
        prompt = nine_grid.build_reference_asset_prompt({
            "asset_type": "environment",
            "asset_name": "old hallway wall",
            "purpose": "lock hallway layout and the cracked damaged plaster patch near the door frame",
        })

        self.assertIn("cracked damaged plaster patch", prompt)
        self.assertNotIn("urine", prompt.lower())
        self.assertNotIn("fleas", prompt.lower())
        self.assertNotIn("ticks", prompt.lower())

    def test_environment_reference_prompt_does_not_invent_problem_anchor_when_absent(self):
        prompt = nine_grid.build_reference_asset_prompt({
            "asset_type": "environment",
            "asset_name": "Thai apartment living room",
            "purpose": "lock room layout, sofa position, natural window light",
        })

        lowered = prompt.lower()
        for forbidden in ["urine", "pee", "wet patch", "fleas", "ticks", "insects", "damaged spot", "dirty area"]:
            self.assertNotIn(forbidden, lowered)

    def test_environment_reference_prompt_keeps_urine_stain_without_pet_subject(self):
        prompt = nine_grid.build_reference_asset_prompt({
            "asset_type": "environment",
            "asset_name": "white mattress area",
            "purpose": "visible cat urine stain on white mattress and wet patch on bedding",
        })

        self.assertIn("urine stain", prompt)
        self.assertIn("wet patch", prompt)
        self.assertNotIn("cat urine stain", prompt)
        self.assertIn("Do not include any people, pets, product bottles", prompt)

    def test_environment_reference_prompt_filters_character_product_action(self):
        prompt = nine_grid.build_reference_asset_prompt({
            "asset_type": "environment",
            "asset_name": "living room",
            "purpose": "woman sprays product beside a dog in the living room",
        })

        self.assertNotIn("woman sprays product", prompt)
        self.assertNotIn("beside a dog", prompt)

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
                get_record_fn=lambda token, table_id, record_id: {"产品图片": [{"file_token": "old_product"}, {"file_token": "ft_product"}]},
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

    def test_render_reference_asset_otu_submits_selected_size_and_aspect_ratio(self):
        fields = {
            "记录类型": "参考资产",
            "父任务记录ID": "recParent",
            "资产类型": "human",
            "资产ID": "owner",
            "参考图来源": "AI自动生成",
            "参考提示词": "Generate the owner reference.",
            "参考图AI模型": "OTU / gpt-image-2",
            "参考图画面尺寸": "1280x720",
            "参考图画面比例": "16:9",
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
             patch.object(nine_grid, "safe_list_records", return_value=[]), \
             patch.object(nine_grid, "submit_otu_image_task", return_value=("task_1", {"id": "task_1"})) as submitter, \
             patch.object(nine_grid, "poll_otu_image_task", return_value={"result_url": "https://x.test/out.png"}), \
             patch.object(nine_grid, "download_otu_image_result"), \
             patch.object(nine_grid, "upload_image_to_feishu", return_value="ft_out"), \
             patch.object(nine_grid, "safe_update_record"), \
             patch.object(nine_grid, "filter_existing_fields", side_effect=lambda token, table_id, fields: fields):
            result = nine_grid.render_reference_asset("recAsset")

        self.assertEqual(result["status"], "success")
        self.assertEqual(submitter.call_args.kwargs["size"], "1280x720")
        self.assertEqual(submitter.call_args.kwargs["aspect_ratio"], "16:9")
        self.assertEqual(submitter.call_args.kwargs["metadata"]["aspectRatio"], "16:9")
        self.assertEqual(submitter.call_args.kwargs["metadata"]["aspect_ratio"], "16:9")

    def test_render_reference_asset_otu_2k_overrides_stale_720_size(self):
        fields = {
            "记录类型": "参考资产",
            "父任务记录ID": "recParent",
            "资产类型": "human",
            "资产ID": "owner",
            "参考图来源": "AI自动生成",
            "参考提示词": "Generate the owner reference.",
            "参考图AI模型": "OTU / gpt-image-2-2K",
            "参考图AI参数JSON": '{"size":"720x1280","aspect_ratio":"9:16"}',
            "参考图画面尺寸": "720x1280",
            "参考图画面比例": "9:16",
        }
        updates = []

        with patch.object(nine_grid, "TABLE_NINE_GRID_VIDEO", "tbl_nine"), \
             patch.object(nine_grid, "get_feishu_token", return_value="token"), \
             patch.object(nine_grid, "safe_get_record", return_value=fields), \
             patch.object(nine_grid, "get_config_record", return_value=("cfg", {
                 "provider": "OTU",
                 "api_key": "sk-otu",
                 "api_base": "https://otuapi.com",
                 "model": "gpt-image-2",
             })), \
             patch.object(nine_grid, "safe_list_records", return_value=[]), \
             patch.object(nine_grid, "submit_otu_image_task", return_value=("task_2k", {"id": "task_2k"})) as submitter, \
             patch.object(nine_grid, "poll_otu_image_task", return_value={"result_url": "https://x.test/out.png"}), \
             patch.object(nine_grid, "download_otu_image_result"), \
             patch.object(nine_grid, "upload_image_to_feishu", return_value="ft_out"), \
             patch.object(nine_grid, "safe_update_record", side_effect=lambda token, table_id, record_id, fields: updates.append(fields)), \
             patch.object(nine_grid, "filter_existing_fields", side_effect=lambda token, table_id, fields: fields):
            result = nine_grid.render_reference_asset("recAsset")

        self.assertEqual(result["status"], "success")
        self.assertEqual(submitter.call_args.args[0]["model"], "gpt-image-2-2K")
        self.assertEqual(submitter.call_args.kwargs["size"], "1080x1920")
        self.assertEqual(submitter.call_args.kwargs["metadata"]["size"], "1080x1920")
        self.assertTrue(any(update.get("参考图画面尺寸") == "1080x1920" for update in updates))

    def test_render_reference_asset_resumes_existing_otu_task_without_resubmitting(self):
        fields = {
            "记录类型": "参考资产",
            "父任务记录ID": "recParent",
            "资产类型": "human",
            "资产ID": "owner",
            "参考图来源": "AI自动生成",
            "参考提示词": "Generate the owner reference.",
            "参考图AI模型": "OTU / gpt-image-2",
            "参考图生成状态": "生成中",
            "参考图任务ID": "task_existing_ref",
            "参考图原始响应JSON": '{"submit":{"id":"task_existing_ref"}}',
        }
        updates = []

        with patch.object(nine_grid, "TABLE_NINE_GRID_VIDEO", "tbl_nine"), \
             patch.object(nine_grid, "get_feishu_token", return_value="token"), \
             patch.object(nine_grid, "safe_get_record", return_value=fields), \
             patch.object(nine_grid, "get_config_record", return_value=("cfg", {
                 "provider": "OTU",
                 "api_key": "sk-otu",
                 "api_base": "https://otuapi.com",
                 "model": "gpt-image-2",
             })), \
             patch.object(nine_grid, "safe_list_records", return_value=[]), \
             patch.object(nine_grid, "submit_otu_image_task") as submitter, \
             patch.object(nine_grid, "poll_otu_image_task", return_value={"result_url": "https://x.test/out.png"}) as poller, \
             patch.object(nine_grid, "download_otu_image_result"), \
             patch.object(nine_grid, "upload_image_to_feishu", return_value="ft_out"), \
             patch.object(nine_grid, "safe_update_record", side_effect=lambda token, table_id, record_id, fields: updates.append(fields)), \
             patch.object(nine_grid, "filter_existing_fields", side_effect=lambda token, table_id, fields: fields):
            result = nine_grid.render_reference_asset("recAsset")

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["task_id"], "task_existing_ref")
        submitter.assert_not_called()
        poller.assert_called_once()
        self.assertEqual(poller.call_args.args[1], "task_existing_ref")
        self.assertIn("恢复轮询已有 OTU 参考图任务", updates[0]["参考图错误信息"])

    def test_render_reference_asset_otu_2k_does_not_resume_stale_720_task(self):
        fields = {
            "记录类型": "参考资产",
            "父任务记录ID": "recParent",
            "资产类型": "human",
            "资产ID": "owner",
            "参考图来源": "AI自动生成",
            "参考提示词": "Generate the owner reference.",
            "参考图AI模型": "OTU / gpt-image-2-2K",
            "参考图画面尺寸": "720x1280",
            "参考图画面比例": "9:16",
            "参考图生成状态": "生成中",
            "参考图任务ID": "task_stale_720",
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
             patch.object(nine_grid, "safe_list_records", return_value=[]), \
             patch.object(nine_grid, "submit_otu_image_task", return_value=("task_2k", {"id": "task_2k"})) as submitter, \
             patch.object(nine_grid, "poll_otu_image_task", return_value={"result_url": "https://x.test/out.png"}) as poller, \
             patch.object(nine_grid, "download_otu_image_result"), \
             patch.object(nine_grid, "upload_image_to_feishu", return_value="ft_out"), \
             patch.object(nine_grid, "safe_update_record"), \
             patch.object(nine_grid, "filter_existing_fields", side_effect=lambda token, table_id, fields: fields):
            result = nine_grid.render_reference_asset("recAsset")

        self.assertEqual(result["status"], "success")
        submitter.assert_called_once()
        self.assertEqual(submitter.call_args.args[0]["model"], "gpt-image-2-2K")
        self.assertEqual(submitter.call_args.kwargs["size"], "1080x1920")
        poller.assert_called_once()
        self.assertEqual(poller.call_args.args[1], "task_2k")

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
        submitted_prompt = submitter.call_args.args[1]
        self.assertIn("pure white background", submitted_prompt)
        self.assertIn("front-facing upper-body", submitted_prompt)
        self.assertIn("full unobstructed face visible", submitted_prompt)
        self.assertIn("Generate the owner reference.", submitted_prompt)
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
        warning_path = "/Users/" + "ryanlynn/Library/Python/3.9/lib/python/site-packages/google/auth/__init__.py"
        stderr = (
            f"{warning_path}:54: "
            "FutureWarning: You are using a Python version 3.9 past its end of life.\n"
            "  warnings.warn(eol_message.format(\"3.9\"), FutureWarning)\n"
            '{"stage": "nine_grid_plan", "status": "failed_terminal", "error_code": "RUNTIME_BUG", '
            '"retryable": false, "message": "AI模型供应商不匹配: AI供应商=AIHubMix, AI模型=Aitgenne / gpt-5.5"}\n'
        )

        payload = dispatcher.parse_subprocess_error_payload("", stderr, "tk_nine_grid_video.py")

        self.assertEqual(payload["message"], "AI模型供应商不匹配: AI供应商=AIHubMix, AI模型=Aitgenne / gpt-5.5")

    def test_otu_upstream_image_retry_message_is_retryable(self):
        payload = dispatcher.parse_subprocess_error_payload(
            "",
            'OTU 图片生成失败: {"error":{"code":"upstream_error","message":"图片生成失败，请重新提交"}}',
            "tk_nine_grid_video.py",
        )

        self.assertIn(payload["error_code"], {"UPSTREAM_RATE_LIMIT", "UPSTREAM_RETRYABLE"})
        self.assertTrue(payload["retryable"])

    def test_poll_otu_nine_grid_video_task_times_out_when_queued_zero_progress_stalls(self):
        response = Mock()
        response.status_code = 200
        response.text = '{"status":"queued","progress":0}'
        response.json.return_value = {"id": "task_stuck", "status": "queued", "progress": 0}
        times = iter([0, 0, 601])

        with patch("tk_nine_grid_video.requests.get", return_value=response), \
             self.assertRaisesRegex(TimeoutError, "queued progress=0"):
            nine_grid.poll_otu_nine_grid_video_task(
                {"api_base": "https://otuapi.com", "api_key": "sk-test"},
                "task_stuck",
                queued_zero_progress_timeout_seconds=600,
                max_poll_seconds=2400,
                now_fn=lambda: next(times),
                sleep_fn=lambda seconds: None,
            )

        payload = nine_grid.build_error_payload(TimeoutError("OTU queued progress=0 timeout"), stage="nine_grid_video")
        self.assertEqual(payload["error_code"], "UPSTREAM_NETWORK")
        self.assertTrue(payload["retryable"])

    def test_poll_otu_nine_grid_video_task_times_out_from_upstream_created_at_after_restart(self):
        response = Mock()
        response.status_code = 200
        response.text = '{"status":"queued","progress":0,"created_at":0}'
        response.json.return_value = {"id": "task_old", "status": "queued", "progress": 0, "created_at": 0}
        times = iter([601, 601])

        with patch("tk_nine_grid_video.requests.get", return_value=response), \
             self.assertRaisesRegex(TimeoutError, "created_at") as caught:
            nine_grid.poll_otu_nine_grid_video_task(
                {"api_base": "https://otuapi.com", "api_key": "sk-test"},
                "task_old",
                queued_zero_progress_timeout_seconds=600,
                max_poll_seconds=2400,
                now_fn=lambda: next(times),
                sleep_fn=lambda seconds: None,
            )

        payload = nine_grid.build_error_payload(caught.exception, stage="nine_grid_video")
        self.assertEqual(payload["error_code"], "UPSTREAM_NETWORK")
        self.assertTrue(payload["retryable"])

    def test_poll_otu_nine_grid_video_task_continues_when_queued_zero_progress_is_under_threshold(self):
        queued = Mock()
        queued.status_code = 200
        queued.text = '{"status":"queued","progress":0}'
        queued.json.return_value = {"id": "task_ok", "status": "queued", "progress": 0}
        completed = Mock()
        completed.status_code = 200
        completed.text = '{"status":"completed","video_url":"https://x.test/video.mp4"}'
        completed.json.return_value = {"id": "task_ok", "status": "completed", "video_url": "https://x.test/video.mp4"}
        times = iter([0, 0, 599])

        with patch("tk_nine_grid_video.requests.get", side_effect=[queued, completed]) as get:
            result = nine_grid.poll_otu_nine_grid_video_task(
                {"api_base": "https://otuapi.com", "api_key": "sk-test"},
                "task_ok",
                queued_zero_progress_timeout_seconds=600,
                max_poll_seconds=2400,
                now_fn=lambda: next(times),
                sleep_fn=lambda seconds: None,
            )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(get.call_count, 2)

    def test_poll_otu_nine_grid_video_task_returns_completed_video(self):
        response = Mock()
        response.status_code = 200
        response.text = '{"status":"completed","video_url":"https://x.test/video.mp4"}'
        response.json.return_value = {"id": "task_done", "status": "completed", "video_url": "https://x.test/video.mp4"}

        with patch("tk_nine_grid_video.requests.get", return_value=response) as get:
            result = nine_grid.poll_otu_nine_grid_video_task(
                {"api_base": "https://otuapi.com", "api_key": "sk-test"},
                "task_done",
                now_fn=lambda: 0,
                sleep_fn=lambda seconds: None,
            )

        self.assertEqual(result["video_url"], "https://x.test/video.mp4")
        self.assertEqual(get.call_count, 1)

    def test_dispatcher_retryable_errors_stop_after_retry_limit(self):
        watch = {
            "name": "多图九宫格视频生成",
            "script": "tk_nine_grid_video.py",
            "table": "tbl_nine",
            "status_field": "视频生成状态",
            "trigger_value": "待生成",
            "trigger_values": ["待生成", "生成中"],
            "running_value": "生成中",
            "error_field": "视频错误信息",
            "max_retries": 1,
        }
        retry_counts = []
        payload = {
            "status": "failed_retryable",
            "error_code": "UPSTREAM_RATE_LIMIT",
            "retryable": True,
            "message": "Omni upstream failed",
        }

        with patch.object(dispatcher, "get_retry_count", return_value=5), \
             patch.object(dispatcher, "set_retry_count", side_effect=lambda task_key, retry_count, **kwargs: retry_counts.append(retry_count)), \
             patch.object(dispatcher, "safe_get_record", return_value={"视频生成状态": "生成中"}), \
             patch.object(dispatcher, "safe_update_record") as update_record, \
             patch.object(dispatcher, "bump_metric"):
            retried = dispatcher.maybe_retry_task("token", watch, "recBoard", "task-key", "failed", error_payload=payload)

        self.assertFalse(retried)
        self.assertEqual(retry_counts, [6])
        update_record.assert_not_called()

    def test_dispatcher_task_key_distinguishes_same_script_record_by_action(self):
        image_watch = {
            "name": "多图九宫格图片生成",
            "script": "tk_nine_grid_video.py",
            "args": ["image"],
        }
        video_watch = {
            "name": "多图九宫格视频生成",
            "script": "tk_nine_grid_video.py",
            "args": ["video"],
        }

        self.assertNotEqual(
            dispatcher.make_task_key(image_watch, "recBoard"),
            dispatcher.make_task_key(video_watch, "recBoard"),
        )

    def test_dispatcher_retry_respects_manual_stop_status(self):
        watch = {
            "name": "多图九宫格视频生成",
            "script": "tk_nine_grid_video.py",
            "table": "tbl_nine",
            "status_field": "视频生成状态",
            "trigger_value": "待生成",
            "trigger_values": ["待生成", "生成中"],
            "running_value": "生成中",
            "error_field": "视频错误信息",
            "max_retries": 1,
        }
        payload = {
            "status": "failed_retryable",
            "error_code": "UPSTREAM_RATE_LIMIT",
            "retryable": True,
            "message": "Omni upstream failed",
        }

        with patch.object(dispatcher, "get_retry_count", return_value=2), \
             patch.object(dispatcher, "set_retry_count") as set_retry_count, \
             patch.object(dispatcher, "safe_get_record", return_value={"视频生成状态": "不触发"}), \
             patch.object(dispatcher, "safe_update_record") as update_record, \
             patch.object(dispatcher, "bump_metric"):
            handled = dispatcher.maybe_retry_task("token", watch, "recBoard", "task-key", "failed", error_payload=payload)

        self.assertTrue(handled)
        set_retry_count.assert_not_called()
        update_record.assert_not_called()

    def test_dispatcher_retryable_error_retries_after_child_failed_writeback(self):
        watch = {
            "name": "多图九宫格视频生成",
            "script": "tk_nine_grid_video.py",
            "table": "tbl_nine",
            "status_field": "视频生成状态",
            "trigger_value": "待生成",
            "trigger_values": ["待生成", "生成中"],
            "running_value": "生成中",
            "failed_value": "失败",
            "error_field": "视频错误信息",
            "max_retries": 1,
        }
        updates = []
        payload = {
            "status": "failed_retryable",
            "error_code": "UPSTREAM_RATE_LIMIT",
            "retryable": True,
            "message": "Omni upstream failed",
        }

        with patch.object(dispatcher, "get_retry_count", return_value=0), \
             patch.object(dispatcher, "set_retry_count") as set_retry_count, \
             patch.object(dispatcher, "safe_get_record", return_value={"视频生成状态": "失败"}), \
             patch.object(dispatcher, "safe_update_record", side_effect=lambda token, table, rid, fields: updates.append(fields)), \
             patch.object(dispatcher, "bump_metric"):
            retried = dispatcher.maybe_retry_task("token", watch, "recBoard", "task-key", "failed", error_payload=payload)

        self.assertTrue(retried)
        set_retry_count.assert_called_once()
        self.assertEqual(updates[0]["视频生成状态"], "待生成")
        self.assertIn("自动重试中[UPSTREAM_RATE_LIMIT]", updates[0]["视频错误信息"])

    def test_dispatcher_does_not_retry_terminal_errors(self):
        watch = {
            "name": "多图九宫格视频生成",
            "script": "tk_nine_grid_video.py",
            "table": "tbl_nine",
            "status_field": "视频生成状态",
            "trigger_value": "待生成",
            "running_value": "生成中",
            "error_field": "视频错误信息",
        }
        payload = {
            "status": "failed_terminal",
            "error_code": "MODEL_CONFIG_INVALID",
            "retryable": False,
            "message": "AI模型供应商不匹配",
        }

        with patch.object(dispatcher, "set_retry_count") as set_retry_count, \
             patch.object(dispatcher, "safe_update_record") as update_record:
            retried = dispatcher.maybe_retry_task("token", watch, "recBoard", "task-key", "failed", error_payload=payload)

        self.assertFalse(retried)
        set_retry_count.assert_not_called()
        update_record.assert_not_called()

    def test_dispatcher_does_not_block_launch_when_circuit_is_open(self):
        watch = {
            "name": "测试环节",
            "script": "tk_nine_grid_video.py",
            "table": "tbl_nine",
            "status_field": "视频生成状态",
            "trigger_value": "待生成",
            "running_value": "生成中",
            "args": ["video"],
            "max_concurrency": 1,
        }
        launched = []

        with patch.object(dispatcher, "apply_stage_policy", side_effect=lambda item: item), \
             patch.object(dispatcher, "cleanup_finished_processes"), \
             patch.object(dispatcher, "is_circuit_open", return_value=True), \
             patch.object(dispatcher, "count_running_by_watch", return_value=0), \
             patch.object(dispatcher, "get_table_records_cached", return_value=[{"record_id": "recBoard", "fields": {"视频生成状态": "待生成", "任务名称": "task"}}]), \
             patch.object(dispatcher, "try_claim_task", return_value=True), \
             patch.object(dispatcher.subprocess, "Popen", side_effect=lambda *args, **kwargs: launched.append(args) or Mock(poll=lambda: None)), \
             patch.object(dispatcher, "save_running_tasks"), \
             patch.object(dispatcher, "load_running_tasks", return_value={}), \
             patch.object(dispatcher, "bump_metric"), \
             patch.object(dispatcher, "get_retry_count", return_value=0):
            dispatcher.check_and_run("token", watch)

        self.assertEqual(len(launched), 1)

    def test_dispatcher_skips_running_record_when_live_process_exists(self):
        watch = {
            "name": "测试图片生成",
            "script": "tk_nine_grid_video.py",
            "table": "tbl_nine",
            "status_field": "图片生成状态",
            "trigger_value": "待生成",
            "trigger_values": ["待生成", "生成中"],
            "running_value": "生成中",
            "args": ["image"],
            "max_concurrency": 1,
        }
        record = {"record_id": "recImage", "fields": {"图片生成状态": "生成中", "任务名称": "image task"}}

        with patch.object(dispatcher, "apply_stage_policy", side_effect=lambda item: item), \
             patch.object(dispatcher, "cleanup_finished_processes"), \
             patch.object(dispatcher, "count_running_by_watch", return_value=0), \
             patch.object(dispatcher, "get_table_records_cached", return_value=[record]), \
             patch.object(dispatcher, "load_running_tasks", return_value={}), \
             patch.object(dispatcher, "has_live_process_for_task_key", return_value=True), \
             patch.object(dispatcher.subprocess, "Popen") as popen:
            dispatcher.check_and_run("token", watch)

        popen.assert_not_called()

    def test_dispatcher_counts_persisted_live_tasks_against_concurrency(self):
        watch = {
            "name": "测试图片生成",
            "script": "tk_nine_grid_video.py",
            "table": "tbl_nine",
            "status_field": "图片生成状态",
            "trigger_value": "待生成",
            "trigger_values": ["待生成", "生成中"],
            "running_value": "生成中",
            "args": ["image"],
            "max_concurrency": 1,
        }
        running_state = {
            dispatcher.make_task_key(watch, "recLive"): {
                "script": "tk_nine_grid_video.py",
                "args": ["image"],
                "record_id": "recLive",
            },
        }
        waiting_record = {"record_id": "recWait", "fields": {"图片生成状态": "待生成", "任务名称": "waiting task"}}

        with patch.object(dispatcher, "apply_stage_policy", side_effect=lambda item: item), \
             patch.object(dispatcher, "cleanup_finished_processes"), \
             patch.object(dispatcher, "load_running_tasks", return_value=running_state), \
             patch.object(dispatcher, "has_live_process_for_task_key", return_value=True), \
             patch.object(dispatcher, "get_table_records_cached", return_value=[waiting_record]), \
             patch.object(dispatcher, "try_claim_task", return_value=True), \
             patch.object(dispatcher, "save_running_tasks"), \
             patch.object(dispatcher, "bump_metric"), \
             patch.object(dispatcher, "get_retry_count", return_value=0), \
             patch.object(dispatcher.subprocess, "Popen") as popen:
            dispatcher.check_and_run("token", watch)

        popen.assert_not_called()

    def test_dispatcher_claims_stale_running_record_when_no_live_process_exists(self):
        watch = {
            "name": "测试图片生成",
            "script": "tk_nine_grid_video.py",
            "table": "tbl_nine",
            "status_field": "图片生成状态",
            "trigger_value": "待生成",
            "trigger_values": ["待生成", "生成中"],
            "running_value": "生成中",
            "args": ["image"],
            "max_concurrency": 1,
        }
        record = {"record_id": "recImage", "fields": {"图片生成状态": "生成中", "任务名称": "image task"}}
        launched = []

        with patch.object(dispatcher, "apply_stage_policy", side_effect=lambda item: item), \
             patch.object(dispatcher, "cleanup_finished_processes"), \
             patch.object(dispatcher, "count_running_by_watch", return_value=0), \
             patch.object(dispatcher, "count_active_running_tasks", return_value=0), \
             patch.object(dispatcher, "get_table_records_cached", return_value=[record]), \
             patch.object(dispatcher, "load_running_tasks", return_value={}), \
             patch.object(dispatcher, "has_live_process_for_task_key", return_value=False), \
             patch.object(dispatcher, "should_skip_claim_by_cache", return_value=True), \
             patch.object(dispatcher, "safe_get_record", return_value=record["fields"]), \
             patch.object(dispatcher, "safe_update_record"), \
             patch.object(dispatcher, "try_claim_task", return_value=True), \
             patch.object(dispatcher.subprocess, "Popen", side_effect=lambda *args, **kwargs: launched.append(args) or Mock(poll=lambda: None)), \
             patch.object(dispatcher, "save_running_tasks"), \
             patch.object(dispatcher, "bump_metric"), \
             patch.object(dispatcher, "get_retry_count", return_value=0):
            dispatcher.check_and_run("token", watch)

        self.assertEqual(len(launched), 1)

    def test_dispatcher_does_not_treat_trigger_equal_running_as_stale(self):
        watch = {
            "name": "测试审核推进",
            "script": "tk_nine_grid_video.py",
            "table": "tbl_nine",
            "status_field": "参考图审核状态",
            "trigger_value": "通过",
            "running_value": "通过",
            "args": ["reference-approval"],
            "max_concurrency": 1,
        }
        record = {"record_id": "recAsset", "fields": {"参考图审核状态": "通过", "任务名称": "approval task"}}

        with patch.object(dispatcher, "apply_stage_policy", side_effect=lambda item: item), \
             patch.object(dispatcher, "cleanup_finished_processes"), \
             patch.object(dispatcher, "count_running_by_watch", return_value=0), \
             patch.object(dispatcher, "get_table_records_cached", return_value=[record]), \
             patch.object(dispatcher, "load_running_tasks", return_value={}), \
             patch.object(dispatcher, "has_live_process_for_task_key", return_value=False), \
             patch.object(dispatcher, "should_skip_claim_by_cache", return_value=True), \
             patch.object(dispatcher, "try_claim_task", return_value=True), \
             patch.object(dispatcher.subprocess, "Popen") as popen:
            dispatcher.check_and_run("token", watch)

        popen.assert_not_called()

    def test_dispatcher_prunes_stale_running_state(self):
        saved = []

        with patch.object(dispatcher, "running_processes", {}), \
             patch.object(dispatcher, "load_running_tasks", return_value={
                 "tk_nine_grid_video.py::stale": {"script": "tk_nine_grid_video.py"},
             }), \
             patch.object(dispatcher, "has_live_process_for_task_key", return_value=False), \
             patch.object(dispatcher, "save_running_tasks", side_effect=lambda data: saved.append(data)):
            dispatcher.prune_stale_running_state()

        self.assertEqual(saved, [{}])

    def test_dispatcher_keeps_running_state_when_os_process_is_alive(self):
        saved = []

        with patch.object(dispatcher, "running_processes", {}), \
             patch.object(dispatcher, "load_running_tasks", return_value={
                 "tk_nine_grid_video.py::active": {
                     "script": "tk_nine_grid_video.py",
                     "record_id": "active",
                 },
             }), \
             patch.object(dispatcher, "has_live_process_for_task_key", return_value=True), \
             patch.object(dispatcher, "save_running_tasks", side_effect=lambda data: saved.append(data)):
            pruned = dispatcher.prune_stale_running_state()

        self.assertEqual(pruned, 0)
        self.assertEqual(saved, [])

    def test_video_dry_run_uses_video_prefixed_route_fields(self):
        child_fields = {
            "父任务记录ID": "recParent",
            "九宫格图": [{"file_token": "ft_grid"}],
            "视频提示词": "Turn the nine-grid into one continuous video.",
            "视频AI供应商": "OTU",
            "视频AI模型": "OTU / omni_flash-10s",
            "视频生成模型": "OTU / omni_flash-10s",
            "视频AI参数JSON": '{"seconds":"10","size":"720x1280","aspect_ratio":"9:16"}',
            "视频画面尺寸": "720x1280",
            "视频画面比例": "9:16",
        }
        parent_fields = {"关联产品记录": ["recProduct"]}
        product_fields = {"产品图片": [{"file_token": "ft_product"}]}

        with patch.object(nine_grid, "TABLE_NINE_GRID_VIDEO", "tbl_nine"), \
             patch.object(nine_grid, "TABLE_PRODUCT", "tbl_product"), \
             patch.object(nine_grid, "get_feishu_token", return_value="token"), \
             patch.object(nine_grid, "safe_get_record", side_effect=[
                 child_fields,
                 parent_fields,
                 product_fields,
                 {"视频生成状态": "生成中", "视频任务ID": "task_ref"},
             ]), \
             patch.object(nine_grid, "get_config_record", return_value=("cfg", {"api_key": "sk", "api_base": "https://otuapi.com", "model": "omni_flash-10s"})), \
             patch.object(nine_grid, "safe_list_records", return_value=[]):
            result = nine_grid.render_nine_grid_video("recBoard", dry_run=True)

        self.assertEqual(result["status"], "dry_run_ready")
        self.assertEqual(result["route"]["capability"], "视频")
        self.assertEqual(result["route"]["payload"]["model"], "omni_flash-10s")
        self.assertEqual(result["route"]["payload"]["seconds"], "10")

    def test_video_dry_run_prefers_video_generation_model_over_legacy_video_ai_model(self):
        child_fields = {
            "父任务记录ID": "recParent",
            "九宫格图": [{"file_token": "ft_grid"}],
            "视频提示词": "Turn the nine-grid into one continuous video.",
            "视频AI供应商": "OTU",
            "视频AI模型": "OTU / omni_flash-10s",
            "视频生成模型": "Aitgenne / happyhorse-1.0-r2v",
            "视频AI参数JSON": '{"seconds":"10","size":"720x1280","aspect_ratio":"9:16"}',
            "视频画面尺寸": "720x1280",
            "视频画面比例": "9:16",
        }
        parent_fields = {"关联产品记录": ["recProduct"]}
        product_fields = {"产品图片": [{"file_token": "ft_product"}]}
        config_records = [{"fields": {"AI供应商": "Aitgenne", "API 代理地址": "https://api.aitgenne.com", "API Key": "sk-aitgenne"}}]

        with patch.object(nine_grid, "TABLE_NINE_GRID_VIDEO", "tbl_nine"), \
             patch.object(nine_grid, "TABLE_PRODUCT", "tbl_product"), \
             patch.object(nine_grid, "get_feishu_token", return_value="token"), \
             patch.object(nine_grid, "safe_get_record", side_effect=[
                 child_fields,
                 parent_fields,
                 product_fields,
                 {"视频生成状态": "生成中", "视频任务ID": "task_ref"},
             ]), \
             patch.object(nine_grid, "get_config_record", return_value=("cfg", {"api_key": "sk", "api_base": "https://otuapi.com", "model": "omni_flash-10s"})), \
             patch.object(nine_grid, "safe_list_records", return_value=config_records):
            result = nine_grid.render_nine_grid_video("recBoard", dry_run=True)

        self.assertEqual(result["status"], "dry_run_ready")
        self.assertEqual(result["route"]["provider"], "Aitgenne")
        self.assertEqual(result["route"]["payload"]["model"], "happyhorse-1.0-r2v")

    def test_video_dry_run_rejects_first_last_video_model_for_nine_grid(self):
        child_fields = {
            "父任务记录ID": "recParent",
            "九宫格图": [{"file_token": "ft_grid"}],
            "视频提示词": "Turn the nine-grid into one continuous video.",
            "视频AI供应商": "OTU",
            "视频AI模型": "OTU / veo_3_1-fast-fl",
            "视频画面尺寸": "720x1280",
            "视频画面比例": "9:16",
        }
        parent_fields = {"关联产品记录": ["recProduct"]}
        product_fields = {"产品图片": [{"file_token": "ft_product"}]}

        with patch.object(nine_grid, "TABLE_NINE_GRID_VIDEO", "tbl_nine"), \
             patch.object(nine_grid, "TABLE_PRODUCT", "tbl_product"), \
             patch.object(nine_grid, "get_feishu_token", return_value="token"), \
             patch.object(nine_grid, "safe_get_record", side_effect=[
                 child_fields,
                 parent_fields,
                 product_fields,
                 {"视频生成状态": "生成中", "视频任务ID": "task_ref"},
             ]), \
             patch.object(nine_grid, "get_config_record", return_value=("cfg", {"api_key": "sk", "api_base": "https://otuapi.com", "model": "omni_flash-10s"})), \
             patch.object(nine_grid, "safe_list_records", return_value=[]):
            with self.assertRaisesRegex(ValueError, "九宫格视频只支持参考图生视频模型"):
                nine_grid.render_nine_grid_video("recBoard", dry_run=True)

    def test_video_dry_run_requires_product_reference_and_reports_two_references(self):
        raw_prompt = (
            "0-7.5s，Non捏鼻后退，说 in Thai: อย่าเอาแมวมาใกล้ผม! "
            "Pear拿出驱虫滴剂并安抚猫，猫尿味和冲突内容按原文保留。"
        )
        child_fields = {
            "父任务记录ID": "recParent",
            "九宫格图": [{"file_token": "ft_grid"}],
            "视频提示词": raw_prompt,
            "视频AI供应商": "OTU",
            "视频AI模型": "OTU / omni_flash-10s",
            "视频画面尺寸": "720x1280",
            "视频画面比例": "9:16",
        }
        parent_fields = {"关联产品记录": ["recProduct"]}
        product_fields = {"产品图片": [{"file_token": "ft_product"}]}

        with patch.object(nine_grid, "TABLE_NINE_GRID_VIDEO", "tbl_nine"), \
             patch.object(nine_grid, "TABLE_PRODUCT", "tbl_product"), \
             patch.object(nine_grid, "get_feishu_token", return_value="token"), \
             patch.object(nine_grid, "safe_get_record", side_effect=[child_fields, parent_fields, product_fields]), \
             patch.object(nine_grid, "get_config_record", return_value=("cfg", {"api_key": "sk", "api_base": "https://otuapi.com", "model": "omni_flash-10s"})), \
             patch.object(nine_grid, "safe_list_records", return_value=[]):
            result = nine_grid.render_nine_grid_video("recBoard", dry_run=True)

        prompt = result["route"]["payload"]["prompt"]
        self.assertIn(prompts.NINE_GRID_VIDEO_SYSTEM_PROMPT, prompt)
        self.assertIn("Faithfully translate any Chinese visual/action directions into English", prompt)
        self.assertIn("Do not rewrite, soften, add, remove, or sanitize story details.", prompt)
        self.assertIn("Reference image 1 = current Board nine-grid storyboard", prompt)
        self.assertIn("Reference image 2 = exact product reference", prompt)
        self.assertIn(raw_prompt, prompt)
        self.assertIn("อย่าเอาแมวมาใกล้ผม!", prompt)
        self.assertIn("猫尿味", prompt)
        self.assertNotIn("continuous vertical UGC home-cleaning video", prompt)
        self.assertEqual(result["route"]["reference_count"], 2)

    def test_render_nine_grid_video_appends_approved_human_references_after_product_only(self):
        raw_prompt = "朋友捏鼻，Non says in Thai: อย่าเอาแมวมาใกล้ผม! 主人喷沙发，朋友惊喜。"
        child_fields = {
            "父任务记录ID": "recParent",
            "九宫格图": [{"file_token": "ft_grid"}],
            "视频提示词": raw_prompt,
            "视频AI供应商": "OTU",
            "视频AI模型": "OTU / omni_flash-10s",
            "视频画面尺寸": "720x1280",
            "视频画面比例": "9:16",
        }
        parent_fields = {"记录类型": "母任务", "关联产品记录": ["recProduct"]}
        product_fields = {"产品图片": [{"file_token": "ft_product"}, {"file_token": "ft_product_2"}]}
        asset_records = [
            {"record_id": "recPear", "fields": {
                "记录类型": "参考资产",
                "父任务记录ID": "recParent",
                "资产类型": "human",
                "资产ID": "pear",
                "资产名称": "Pear",
                "参考图审核状态": "通过",
                "参考图": [{"file_token": "ft_pear"}],
            }},
            {"record_id": "recCat", "fields": {
                "记录类型": "参考资产",
                "父任务记录ID": "recParent",
                "资产类型": "pet",
                "资产ID": "cat",
                "资产名称": "orange cat",
                "参考图审核状态": "通过",
                "参考图": [{"file_token": "ft_cat"}],
            }},
            {"record_id": "recRoom", "fields": {
                "记录类型": "参考资产",
                "父任务记录ID": "recParent",
                "资产类型": "environment",
                "资产ID": "bedroom",
                "资产名称": "Thai bedroom",
                "参考图审核状态": "通过",
                "参考图": [{"file_token": "ft_room"}],
            }},
            {"record_id": "recNon", "fields": {
                "记录类型": "参考资产",
                "父任务记录ID": "recParent",
                "资产类型": "human",
                "资产ID": "non",
                "资产名称": "Non",
                "参考图审核状态": "通过",
                "参考图": [{"file_token": "ft_non"}],
            }},
        ]

        with patch.object(nine_grid, "TABLE_NINE_GRID_VIDEO", "tbl_nine"), \
             patch.object(nine_grid, "TABLE_PRODUCT", "tbl_product"), \
             patch.object(nine_grid, "get_feishu_token", return_value="token"), \
             patch.object(nine_grid, "safe_get_record", side_effect=[child_fields, parent_fields, product_fields, {
                 "视频生成状态": "生成中",
                 "视频任务ID": "task_omni",
             }]), \
             patch.object(nine_grid, "get_config_record", return_value=("cfg", {"api_key": "sk", "api_base": "https://otuapi.com", "model": "omni_flash-10s"})), \
             patch.object(nine_grid, "safe_list_records", return_value=asset_records), \
             patch.object(nine_grid, "safe_download_attachment", side_effect=lambda token, file_token, path: path) as download_attachment, \
             patch.object(nine_grid, "collect_nine_grid_reference_images") as collect_all_refs, \
             patch.object(nine_grid, "submit_omni_video_task", return_value=("task_omni", {"id": "task_omni"}), create=True) as omni_submitter, \
             patch.object(nine_grid, "poll_otu_nine_grid_video_task", return_value={"video_url": "https://x.test/video.mp4"}, create=True), \
             patch.object(nine_grid, "download_video"), \
             patch.object(nine_grid, "upload_video_to_feishu", return_value="ft_video"), \
             patch.object(nine_grid, "get_table_field_types", return_value={"分镜视频URL": 15}), \
             patch.object(nine_grid, "safe_update_record"), \
             patch.object(nine_grid, "filter_existing_fields", side_effect=lambda token, table_id, fields: fields):
            result = nine_grid.render_nine_grid_video("recBoard")

        self.assertEqual(result["status"], "success")
        collect_all_refs.assert_not_called()
        self.assertEqual(
            [call.args[1] for call in download_attachment.call_args_list],
            ["ft_grid", "ft_product_2", "ft_pear", "ft_non"],
        )
        args, kwargs = omni_submitter.call_args
        self.assertEqual(args[0]["model"], "omni_flash-10s")
        self.assertIn(prompts.NINE_GRID_VIDEO_SYSTEM_PROMPT, args[1])
        self.assertIn("Faithfully translate any Chinese visual/action directions into English", args[1])
        self.assertIn("Reference image 1 = current Board nine-grid storyboard", args[1])
        self.assertIn("Reference image 2 = exact product reference", args[1])
        self.assertIn("Reference image 3 = human character reference (Pear)", args[1])
        self.assertIn("Reference image 4 = human character reference (Non)", args[1])
        self.assertNotIn("orange cat", args[1])
        self.assertNotIn("Thai bedroom", args[1])
        self.assertIn(raw_prompt, args[1])
        self.assertIn("อย่าเอาแมวมาใกล้ผม!", args[1])
        self.assertIn("捏鼻", args[1])
        self.assertNotIn("continuous vertical UGC home-cleaning video", args[1])
        self.assertEqual([ref["role"] for ref in args[2]], ["nine_grid", "product:1", "human:pear", "human:non"])
        self.assertEqual(kwargs["size"], "720x1280")
        self.assertEqual(kwargs["aspect_ratio"], "9:16")
        self.assertNotIn("seconds", kwargs)

    def test_render_nine_grid_video_submits_aitgenne_r2v_with_grid_product_and_humans(self):
        child_fields = {
            "父任务记录ID": "recParent",
            "九宫格图": [{"file_token": "ft_grid"}],
            "视频提示词": "Turn the nine-grid into one continuous video.",
            "视频AI模型": "Aitgenne / happyhorse-1.0-r2v",
            "视频画面尺寸": "720x1280",
            "视频画面比例": "9:16",
        }
        parent_fields = {"记录类型": "母任务", "关联产品记录": ["recProduct"]}
        product_fields = {"产品图片": [{"file_token": "ft_product"}]}
        asset_records = [
            {"record_id": "recPear", "fields": {
                "记录类型": "参考资产",
                "父任务记录ID": "recParent",
                "资产类型": "human",
                "资产ID": "pear",
                "资产名称": "Pear",
                "参考图审核状态": "通过",
                "参考图": [{"file_token": "ft_pear"}],
            }},
        ]
        latest_fields = {"视频生成状态": "生成中", "视频任务ID": "task_ref"}

        with patch.object(nine_grid, "TABLE_NINE_GRID_VIDEO", "tbl_nine"), \
             patch.object(nine_grid, "TABLE_PRODUCT", "tbl_product"), \
             patch.object(nine_grid, "get_feishu_token", return_value="token"), \
             patch.object(nine_grid, "safe_get_record", side_effect=[child_fields, parent_fields, product_fields, latest_fields]), \
             patch.object(nine_grid, "get_config_record", return_value=("cfg", {
                 "provider": "OTU",
                 "api_key": "sk-otu",
                 "api_base": "https://otuapi.com",
                 "model": "omni_flash-10s",
             })), \
             patch.object(nine_grid, "safe_list_records", return_value=[
                 {"fields": {"AI供应商": "Aitgenne", "API 代理地址": "https://api.aitgenne.com", "API Key": "sk-aitgenne"}},
                 *asset_records,
             ]), \
             patch.object(nine_grid, "safe_download_attachment", side_effect=lambda token, file_token, path: path), \
             patch.object(nine_grid, "build_reference_urls", side_effect=lambda token, refs: [f"https://x.test/{ref['file_token']}.png" for ref in refs]), \
             patch.object(nine_grid, "submit_reference_video_task", return_value=("task_ref", {"id": "task_ref"}), create=True) as submitter, \
             patch.object(nine_grid, "poll_reference_video_task", return_value={"video_url": "https://x.test/video.mp4"}, create=True), \
             patch.object(nine_grid, "download_video"), \
             patch.object(nine_grid, "upload_video_to_feishu", return_value="ft_video"), \
             patch.object(nine_grid, "get_table_field_types", return_value={"分镜视频URL": 15}), \
             patch.object(nine_grid, "safe_update_record"), \
             patch.object(nine_grid, "filter_existing_fields", side_effect=lambda token, table_id, fields: fields):
            result = nine_grid.render_nine_grid_video("recBoard")

        self.assertEqual(result["status"], "success")
        route, prompt, refs = submitter.call_args.args
        self.assertEqual(route.provider, "Aitgenne")
        self.assertEqual(route.model, "Aitgenne / happyhorse-1.0-r2v")
        self.assertEqual([ref["role"] for ref in refs], ["nine_grid", "product:1", "human:pear"])
        self.assertIn("Reference image 2 = exact product reference", prompt)
        self.assertEqual(submitter.call_args.kwargs["seconds"], "10")

    def test_submit_aitgenne_reference_video_uses_input_media_json_schema(self):
        route = nine_grid.ai_routing.AiRoute(
            provider="Aitgenne",
            capability="视频",
            task_type="首帧图生视频",
            model="Aitgenne / happyhorse-1.0-r2v",
            api_base="https://api.aitgenne.com/v1",
            api_key="sk-aitgenne",
        )
        refs = [
            {"role": "nine_grid", "url": "https://x.test/grid.png"},
            {"role": "product:1", "url": "https://x.test/product.png"},
        ]
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"output": {"task_id": "task_aitgenne", "task_status": "PENDING"}}
        response.text = '{"id":"task_aitgenne"}'

        with patch.object(nine_grid.requests, "post", return_value=response) as post:
            task_id, body = nine_grid.submit_reference_video_task(
                route,
                "video prompt",
                refs,
                size="720x1280",
                aspect_ratio="9:16",
                seconds="10",
            )

        self.assertEqual(task_id, "task_aitgenne")
        self.assertEqual(body["output"]["task_status"], "PENDING")
        args, kwargs = post.call_args
        self.assertEqual(args[0], "https://api.aitgenne.com/alibailian/api/v1/services/aigc/video-generation/video-synthesis")
        self.assertNotIn("files", kwargs)
        self.assertEqual(kwargs["json"], {
            "model": "happyhorse-1.0-r2v",
            "input": {
                "prompt": "video prompt",
                "media": [
                    {"type": "reference_image", "url": "https://x.test/grid.png"},
                    {"type": "reference_image", "url": "https://x.test/product.png"},
                ],
            },
            "parameters": {
                "resolution": "720P",
                "ratio": "9:16",
                "duration": 10,
            },
        })

    def test_old_aitgenne_input_media_failure_task_is_not_resumed(self):
        route = nine_grid.ai_routing.AiRoute(
            provider="Aitgenne",
            capability="视频",
            task_type="首帧图生视频",
            model="Aitgenne / happyhorse-1.0-r2v",
            api_base="https://api.aitgenne.com/v1",
            api_key="sk-aitgenne",
        )
        fields = {
            "视频错误信息": (
                "Aitgenne 参考图视频生成失败: {'error': {'code': 'InvalidParameter', "
                "'message': \"Field required: input.media & Input should be '1080P' or '720P': parameters.resolution\"}}"
            )
        }

        self.assertFalse(nine_grid.existing_video_task_matches_route(fields, route, "task_old"))

    def test_render_nine_grid_video_submits_aitgenne_omni_with_grid_and_product_only(self):
        child_fields = {
            "父任务记录ID": "recParent",
            "九宫格图": [{"file_token": "ft_grid"}],
            "视频提示词": "Turn the nine-grid into one continuous video.",
            "视频AI模型": "Aitgenne / omni-flash",
        }
        parent_fields = {"记录类型": "母任务", "关联产品记录": ["recProduct"]}
        product_fields = {"产品图片": [{"file_token": "ft_product"}]}
        asset_records = [
            {"record_id": "recPear", "fields": {
                "记录类型": "参考资产",
                "父任务记录ID": "recParent",
                "资产类型": "human",
                "资产ID": "pear",
                "资产名称": "Pear",
                "参考图审核状态": "通过",
                "参考图": [{"file_token": "ft_pear"}],
            }},
        ]
        latest_fields = {"视频生成状态": "生成中", "视频任务ID": "task_ref"}

        updates = []
        with patch.object(nine_grid, "TABLE_NINE_GRID_VIDEO", "tbl_nine"), \
             patch.object(nine_grid, "TABLE_PRODUCT", "tbl_product"), \
             patch.object(nine_grid, "get_feishu_token", return_value="token"), \
             patch.object(nine_grid, "safe_get_record", side_effect=[child_fields, parent_fields, product_fields, latest_fields]), \
             patch.object(nine_grid, "get_config_record", return_value=("cfg", {"provider": "OTU", "api_key": "sk-otu", "api_base": "https://otuapi.com", "model": "omni_flash-10s"})), \
             patch.object(nine_grid, "safe_list_records", return_value=[
                 {"fields": {"AI供应商": "Aitgenne", "API 代理地址": "https://api.aitgenne.com", "API Key": "sk-aitgenne"}},
                 *asset_records,
             ]), \
             patch.object(nine_grid, "safe_download_attachment", side_effect=lambda token, file_token, path: path), \
             patch.object(nine_grid, "build_reference_urls", side_effect=lambda token, refs: [f"https://x.test/{ref['file_token']}.png" for ref in refs]), \
             patch.object(nine_grid, "submit_reference_video_task", return_value=("task_ref", {"id": "task_ref"}), create=True) as submitter, \
             patch.object(nine_grid, "poll_reference_video_task", return_value={"video_url": "https://x.test/video.mp4"}, create=True), \
             patch.object(nine_grid, "download_video"), \
             patch.object(nine_grid, "upload_video_to_feishu", return_value="ft_video"), \
             patch.object(nine_grid, "get_table_field_types", return_value={"分镜视频URL": 15}), \
             patch.object(nine_grid, "safe_update_record", side_effect=lambda token, table_id, record_id, fields: updates.append(fields)), \
             patch.object(nine_grid, "filter_existing_fields", side_effect=lambda token, table_id, fields: fields):
            nine_grid.render_nine_grid_video("recBoard")

        route, prompt, refs = submitter.call_args.args
        self.assertEqual(route.provider, "Aitgenne")
        self.assertEqual([ref["role"] for ref in refs], ["nine_grid", "product:1"])
        self.assertIn("If the storyboard image conflicts with the product reference image, the product reference image wins", prompt)
        self.assertIn("Submitted reference roles: nine_grid,product:1", updates[-2]["视频错误信息"])

    def test_render_nine_grid_video_aitgenne_omni_dry_run_reports_submitted_reference_count(self):
        child_fields = {
            "父任务记录ID": "recParent",
            "九宫格图": [{"file_token": "ft_grid"}],
            "视频提示词": "Turn the nine-grid into one continuous video.",
            "视频AI模型": "Aitgenne / omni-flash",
        }
        parent_fields = {"记录类型": "母任务", "关联产品记录": ["recProduct"]}
        product_fields = {"产品图片": [{"file_token": "ft_product"}]}
        asset_records = [
            {"record_id": "recPear", "fields": {
                "记录类型": "参考资产",
                "父任务记录ID": "recParent",
                "资产类型": "human",
                "资产ID": "pear",
                "资产名称": "Pear",
                "参考图审核状态": "通过",
                "参考图": [{"file_token": "ft_pear"}],
            }},
        ]

        with patch.object(nine_grid, "TABLE_NINE_GRID_VIDEO", "tbl_nine"), \
             patch.object(nine_grid, "TABLE_PRODUCT", "tbl_product"), \
             patch.object(nine_grid, "get_feishu_token", return_value="token"), \
             patch.object(nine_grid, "safe_get_record", side_effect=[child_fields, parent_fields, product_fields]), \
             patch.object(nine_grid, "get_config_record", return_value=("cfg", {"provider": "OTU", "api_key": "sk-otu", "api_base": "https://otuapi.com", "model": "omni_flash-10s"})), \
             patch.object(nine_grid, "safe_list_records", return_value=[
                 {"fields": {"AI供应商": "Aitgenne", "API 代理地址": "https://api.aitgenne.com", "API Key": "sk-aitgenne"}},
                 *asset_records,
             ]):
            result = nine_grid.render_nine_grid_video("recBoard", dry_run=True)

        self.assertEqual(result["route"]["provider"], "Aitgenne")
        self.assertEqual(result["route"]["payload"]["model"], "omni-flash")
        self.assertEqual(result["route"]["reference_count"], 2)

    def test_render_nine_grid_video_resumes_existing_task_without_resubmitting(self):
        child_fields = {
            "父任务记录ID": "recParent",
            "九宫格图": [{"file_token": "ft_grid"}],
            "视频提示词": "Use the existing task.",
            "视频AI供应商": "OTU",
            "视频AI模型": "OTU / omni_flash-10s",
            "视频画面尺寸": "720x1280",
            "视频画面比例": "9:16",
            "视频生成状态": "生成中",
            "视频任务ID": "task_existing",
        }
        updates = []

        with patch.object(nine_grid, "TABLE_NINE_GRID_VIDEO", "tbl_nine"), \
             patch.object(nine_grid, "get_feishu_token", return_value="token"), \
             patch.object(nine_grid, "safe_get_record", return_value=child_fields), \
             patch.object(nine_grid, "get_config_record", return_value=("cfg", {"api_key": "sk", "api_base": "https://otuapi.com", "model": "omni_flash-10s"})), \
             patch.object(nine_grid, "safe_list_records", return_value=[]), \
             patch.object(nine_grid, "safe_download_attachment") as download_attachment, \
             patch.object(nine_grid, "collect_nine_grid_video_product_reference") as product_ref, \
             patch.object(nine_grid, "collect_nine_grid_video_human_references") as human_refs, \
             patch.object(nine_grid, "submit_omni_video_task") as submitter, \
             patch.object(nine_grid, "poll_otu_nine_grid_video_task", return_value={"status": "completed", "video_url": "https://x.test/video.mp4"}) as poller, \
             patch.object(nine_grid, "download_video") as downloader, \
             patch.object(nine_grid, "upload_video_to_feishu", return_value="ft_video") as uploader, \
             patch.object(nine_grid, "get_table_field_types", return_value={"分镜视频URL": 15}), \
             patch.object(nine_grid, "safe_update_record", side_effect=lambda token, table, rid, fields: updates.append(fields)), \
             patch.object(nine_grid, "filter_existing_fields", side_effect=lambda token, table, fields: fields):
            result = nine_grid.render_nine_grid_video("recBoard")

        submitter.assert_not_called()
        download_attachment.assert_not_called()
        product_ref.assert_not_called()
        human_refs.assert_not_called()
        poller.assert_called_once()
        self.assertEqual(poller.call_args.args[1], "task_existing")
        downloader.assert_called_once_with("https://x.test/video.mp4", result["output_path"])
        uploader.assert_called_once()
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["task_id"], "task_existing")
        self.assertEqual(updates[0]["视频任务ID"], "task_existing")
        self.assertIn("恢复轮询", updates[0]["视频错误信息"])
        self.assertEqual(updates[-1]["视频生成状态"], "成功")
        self.assertEqual(updates[-1]["分镜视频"][0]["file_token"], "ft_video")

    def test_render_nine_grid_video_preserves_url_and_local_path_before_upload_failure(self):
        child_fields = {
            "父任务记录ID": "recParent",
            "九宫格图": [{"file_token": "ft_grid"}],
            "视频提示词": "Use the existing task.",
            "视频AI供应商": "OTU",
            "视频AI模型": "OTU / omni_flash-10s",
            "视频画面尺寸": "720x1280",
            "视频画面比例": "9:16",
            "视频生成状态": "生成中",
            "视频任务ID": "task_existing",
        }
        updates = []

        with patch.object(nine_grid, "TABLE_NINE_GRID_VIDEO", "tbl_nine"), \
             patch.object(nine_grid, "get_feishu_token", return_value="token"), \
             patch.object(nine_grid, "safe_get_record", return_value=child_fields), \
             patch.object(nine_grid, "get_config_record", return_value=("cfg", {"api_key": "sk", "api_base": "https://otuapi.com", "model": "omni_flash-10s"})), \
             patch.object(nine_grid, "safe_list_records", return_value=[]), \
             patch.object(nine_grid, "poll_otu_nine_grid_video_task", return_value={"status": "completed", "video_url": "https://x.test/video.mp4"}), \
             patch.object(nine_grid, "download_video"), \
             patch.object(nine_grid, "upload_video_to_feishu", side_effect=RuntimeError("飞书视频上传失败: params error.")), \
             patch.object(nine_grid, "get_table_field_types", return_value={"分镜视频URL": 15}), \
             patch.object(nine_grid, "safe_update_record", side_effect=lambda token, table, rid, fields: updates.append(fields)), \
             patch.object(nine_grid, "filter_existing_fields", side_effect=lambda token, table, fields: fields):
            with self.assertRaisesRegex(RuntimeError, "params error"):
                nine_grid.render_nine_grid_video("recBoard")

        repair_updates = [update for update in updates if update.get("视频本地路径") and update.get("分镜视频URL")]
        self.assertTrue(repair_updates)
        self.assertEqual(repair_updates[-1]["视频任务ID"], "task_existing")
        self.assertEqual(repair_updates[-1]["视频生成状态"], "生成中")
        self.assertIn("等待飞书上传", repair_updates[-1]["视频错误信息"])

    def test_render_nine_grid_video_resubmits_when_existing_task_belongs_to_other_route(self):
        child_fields = {
            "父任务记录ID": "recParent",
            "九宫格图": [{"file_token": "ft_grid"}],
            "视频提示词": "Use the current Aitgenne model.",
            "视频AI模型": "Aitgenne / omni-flash",
            "视频画面尺寸": "720x1280",
            "视频画面比例": "9:16",
            "视频生成状态": "生成中",
            "视频任务ID": "task_old_otu",
            "视频错误信息": "已提交九宫格视频任务，正在轮询。provider=OTU model=omni_flash-10s task_id=task_old_otu",
        }
        parent_fields = {"记录类型": "母任务", "关联产品记录": ["recProduct"]}
        product_fields = {"产品图片": [{"file_token": "ft_product"}]}
        latest_fields = {"视频生成状态": "生成中", "视频任务ID": "task_new_aitgenne"}
        updates = []
        board_reads = 0

        def fake_get_record(token, table_id, record_id):
            nonlocal board_reads
            if record_id == "recBoard":
                board_reads += 1
                if board_reads > 1:
                    return latest_fields
                return child_fields
            if record_id == "recParent":
                return parent_fields
            if record_id == "recProduct":
                return product_fields
            return latest_fields

        with patch.object(nine_grid, "TABLE_NINE_GRID_VIDEO", "tbl_nine"), \
             patch.object(nine_grid, "TABLE_PRODUCT", "tbl_product"), \
             patch.object(nine_grid, "get_feishu_token", return_value="token"), \
             patch.object(nine_grid, "safe_get_record", side_effect=fake_get_record), \
             patch.object(nine_grid, "get_config_record", return_value=("cfg", {"provider": "OTU", "api_key": "sk-otu", "api_base": "https://otuapi.com", "model": "omni_flash-10s"})), \
             patch.object(nine_grid, "safe_list_records", return_value=[
                 {"fields": {"AI供应商": "Aitgenne", "API 代理地址": "https://api.aitgenne.com", "API Key": "sk-aitgenne"}},
             ]), \
             patch.object(nine_grid, "safe_download_attachment", side_effect=lambda token, file_token, path: path), \
             patch.object(nine_grid, "build_reference_urls", side_effect=lambda token, refs: [f"https://x.test/{ref['file_token']}.png" for ref in refs]), \
             patch.object(nine_grid, "submit_reference_video_task", return_value=("task_new_aitgenne", {"id": "task_new_aitgenne"}), create=True) as submitter, \
             patch.object(nine_grid, "poll_reference_video_task", return_value={"video_url": "https://x.test/video.mp4"}, create=True) as poller, \
             patch.object(nine_grid, "download_video"), \
             patch.object(nine_grid, "upload_video_to_feishu", return_value="ft_video"), \
             patch.object(nine_grid, "get_table_field_types", return_value={"分镜视频URL": 15}), \
             patch.object(nine_grid, "safe_update_record", side_effect=lambda token, table, rid, fields: updates.append(fields)), \
             patch.object(nine_grid, "filter_existing_fields", side_effect=lambda token, table, fields: fields):
            result = nine_grid.render_nine_grid_video("recBoard")

        submitter.assert_called_once()
        poller.assert_called_once()
        self.assertEqual(poller.call_args.args[1], "task_new_aitgenne")
        self.assertEqual(result["task_id"], "task_new_aitgenne")
        self.assertTrue(any(item.get("视频任务ID") == "" for item in updates))
        self.assertIn("provider=Aitgenne", updates[-2]["视频错误信息"])

    def test_render_nine_grid_video_clears_stale_local_path_before_new_submit(self):
        child_fields = {
            "父任务记录ID": "recParent",
            "九宫格图": [{"file_token": "ft_grid"}],
            "视频提示词": "Submit a fresh OTU task.",
            "视频AI供应商": "OTU",
            "视频AI模型": "OTU / omni_flash-10s",
            "视频画面尺寸": "720x1280",
            "视频画面比例": "9:16",
            "视频本地路径": "/old/video.mp4",
        }
        parent_fields = {"记录类型": "母任务", "关联产品记录": ["recProduct"]}
        product_fields = {"产品图片": [{"file_token": "ft_product"}]}
        latest_fields = {"视频生成状态": "生成中", "视频任务ID": "task_new"}
        updates = []

        with patch.object(nine_grid, "TABLE_NINE_GRID_VIDEO", "tbl_nine"), \
             patch.object(nine_grid, "TABLE_PRODUCT", "tbl_product"), \
             patch.object(nine_grid, "get_feishu_token", return_value="token"), \
             patch.object(nine_grid, "safe_get_record", side_effect=[child_fields, parent_fields, product_fields, latest_fields]), \
             patch.object(nine_grid, "get_config_record", return_value=("cfg", {
                 "provider": "OTU",
                 "api_key": "sk-otu",
                 "api_base": "https://otuapi.com",
                 "model": "omni_flash-10s",
             })), \
             patch.object(nine_grid, "safe_list_records", return_value=[]), \
             patch.object(nine_grid, "safe_download_attachment", side_effect=lambda token, file_token, path: path), \
             patch.object(nine_grid, "submit_omni_video_task", return_value=("task_new", {"id": "task_new"}), create=True), \
             patch.object(nine_grid, "poll_otu_nine_grid_video_task", return_value={"video_url": "https://x.test/video.mp4"}, create=True), \
             patch.object(nine_grid, "download_video"), \
             patch.object(nine_grid, "upload_video_to_feishu", return_value="ft_video"), \
             patch.object(nine_grid, "get_table_field_types", return_value={"分镜视频URL": 15}), \
             patch.object(nine_grid, "safe_update_record", side_effect=lambda token, table, rid, fields: updates.append(fields)), \
             patch.object(nine_grid, "filter_existing_fields", side_effect=lambda token, table, fields: fields):
            nine_grid.render_nine_grid_video("recBoard")

        reset_updates = [update for update in updates if update.get("视频生成状态") == "生成中" and update.get("视频任务ID") == ""]
        self.assertTrue(reset_updates)
        self.assertEqual(reset_updates[-1]["视频本地路径"], "")

    def test_video_dry_run_caps_human_references_at_five_after_grid_and_product(self):
        child_fields = {
            "父任务记录ID": "recParent",
            "九宫格图": [{"file_token": "ft_grid"}],
            "视频提示词": "Pear says in Thai: ใช้นี่เลย!",
            "视频AI供应商": "OTU",
            "视频AI模型": "OTU / omni_flash-10s",
        }
        parent_fields = {"关联产品记录": ["recProduct"]}
        product_fields = {"产品图片": [{"file_token": "ft_product"}]}
        asset_records = [
            {"record_id": f"recHuman{idx}", "fields": {
                "记录类型": "参考资产",
                "父任务记录ID": "recParent",
                "资产类型": "human",
                "资产ID": f"human_{idx}",
                "资产名称": f"Human {idx}",
                "参考图审核状态": "通过",
                "参考图": [{"file_token": f"ft_human_{idx}"}],
            }}
            for idx in range(1, 8)
        ]

        with patch.object(nine_grid, "TABLE_NINE_GRID_VIDEO", "tbl_nine"), \
             patch.object(nine_grid, "TABLE_PRODUCT", "tbl_product"), \
             patch.object(nine_grid, "get_feishu_token", return_value="token"), \
             patch.object(nine_grid, "safe_get_record", side_effect=[child_fields, parent_fields, product_fields]), \
             patch.object(nine_grid, "get_config_record", return_value=("cfg", {"api_key": "sk", "api_base": "https://otuapi.com", "model": "omni_flash-10s"})), \
             patch.object(nine_grid, "safe_list_records", return_value=asset_records):
            result = nine_grid.render_nine_grid_video("recBoard", dry_run=True)

        prompt = result["route"]["payload"]["prompt"]
        self.assertEqual(result["route"]["reference_count"], 7)
        self.assertIn("Reference image 7 = human character reference (Human 5)", prompt)
        self.assertNotIn("Human 6", prompt)
        self.assertNotIn("Human 7", prompt)

    def test_render_nine_grid_video_fails_when_product_image_missing(self):
        child_fields = {
            "父任务记录ID": "recParent",
            "九宫格图": [{"file_token": "ft_grid"}],
            "视频提示词": "Turn the nine-grid into one continuous video.",
            "视频AI供应商": "OTU",
            "视频AI模型": "OTU / omni_flash-10s",
        }
        parent_fields = {"关联产品记录": ["recProduct"]}
        product_fields = {"产品图片": []}

        with patch.object(nine_grid, "TABLE_NINE_GRID_VIDEO", "tbl_nine"), \
             patch.object(nine_grid, "TABLE_PRODUCT", "tbl_product"), \
             patch.object(nine_grid, "get_feishu_token", return_value="token"), \
             patch.object(nine_grid, "safe_get_record", side_effect=[child_fields, parent_fields, product_fields]), \
             patch.object(nine_grid, "get_config_record", return_value=("cfg", {"api_key": "sk", "api_base": "https://otuapi.com", "model": "omni_flash-10s"})), \
             patch.object(nine_grid, "safe_list_records", return_value=[]):
            with self.assertRaisesRegex(ValueError, "产品记录缺少产品图片"):
                nine_grid.render_nine_grid_video("recBoard", dry_run=True)

    def test_failure_update_for_video_writes_video_status_and_error(self):
        fields = nine_grid._failure_update_for_action("video", "network broke")

        self.assertEqual(fields["视频生成状态"], "失败")
        self.assertEqual(fields["视频错误信息"], "network broke")
        self.assertEqual(fields["错误信息"], "network broke")


if __name__ == "__main__":
    unittest.main()
