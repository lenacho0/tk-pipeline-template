import json
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import tk_script_doc_shots as doc_shots
import tk_create_script_doc_shots_table as create_tables
import tk_dispatcher as dispatcher
import tk_model_config_center as model_config_center


class ScriptDocShotsTests(unittest.TestCase):
    def setUp(self):
        self._auto_review_patcher = patch.object(doc_shots, "auto_review_enabled", return_value=False)
        self._auto_review_patcher.start()

    def tearDown(self):
        self._auto_review_patcher.stop()

    def test_reference_approval_advances_only_shots_with_ready_assets(self):
        records = [
            {"record_id": "asset_pet", "fields": {"父文档记录ID": "parent", "资产ID": "pet_hero", "参考图审核状态": "通过", "参考图file_token": "ft_pet"}},
            {"record_id": "asset_env", "fields": {"父文档记录ID": "parent", "资产ID": "home_bg", "参考图审核状态": "待确认", "参考图file_token": "ft_env"}},
            {"record_id": "shot_pet", "fields": {"父文档记录ID": "parent", "参考资产ID列表": "pet_hero", "分镜图生成状态": "不触发"}},
            {"record_id": "shot_both", "fields": {"父文档记录ID": "parent", "参考资产ID列表": "pet_hero,home_bg", "分镜图生成状态": "不触发"}},
            {"record_id": "shot_running", "fields": {"父文档记录ID": "parent", "参考资产ID列表": "pet_hero", "分镜图生成状态": "生成中"}},
        ]
        updates = []
        with patch.object(doc_shots, "TABLE_SCRIPT_DOC_REFERENCE_ASSETS", "tbl_assets"), \
             patch.object(doc_shots, "TABLE_SCRIPT_DOC_SHOTS", "tbl_shots"), \
             patch.object(doc_shots, "safe_list_records", side_effect=[records[:2], records[2:]]), \
             patch.object(doc_shots, "safe_update_record", side_effect=lambda token, table, rid, fields: updates.append((table, rid, fields))), \
             patch.object(doc_shots, "filter_existing_fields", side_effect=lambda token, table, fields: fields):
            result = doc_shots.advance_shots_after_reference_approval("token", "parent")

        self.assertEqual(result["advanced_shots"], 1)
        self.assertIn(("tbl_shots", "shot_pet", {"分镜图生成状态": "待生成", "错误信息": ""}), updates)
        self.assertFalse(any(item[1] == "shot_both" for item in updates))

    def test_auto_approve_reference_image_updates_review_and_advances_shots(self):
        updates = []
        with patch.object(doc_shots, "TABLE_SCRIPT_DOC_REFERENCE_ASSETS", "tbl_assets"), \
             patch.object(doc_shots, "auto_review_enabled", return_value=True) as enabled, \
             patch.object(doc_shots, "advance_shots_after_reference_approval", return_value={"advanced_shots": 2}) as advance, \
             patch.object(doc_shots, "safe_update_record", side_effect=lambda token, table, rid, fields: updates.append((table, rid, fields))), \
             patch.object(doc_shots, "filter_existing_fields", side_effect=lambda token, table, fields: fields):
            result = doc_shots.maybe_auto_approve_reference_image(
                "token",
                "asset_pet",
                {"父文档记录ID": "parent"},
                file_token="ft_pet",
            )

        self.assertEqual(result["status"], "auto_approved")
        enabled.assert_called_once_with("token", stage_name=doc_shots.AUTO_REVIEW_STAGE_NAME)
        self.assertIn(("tbl_assets", "asset_pet", {"参考图审核状态": "通过", "错误信息": ""}), updates)
        advance.assert_called_once_with("token", "parent", unified=False)

    def test_unified_auto_approve_reference_image_uses_unified_switch(self):
        updates = []
        with patch.object(doc_shots, "TABLE_SCRIPT_DOC_UNIFIED", "tbl_unified"), \
             patch.object(doc_shots, "auto_review_enabled", return_value=True) as enabled, \
             patch.object(doc_shots, "advance_shots_after_reference_approval", return_value={"advanced_shots": 2}) as advance, \
             patch.object(doc_shots, "safe_update_record", side_effect=lambda token, table, rid, fields: updates.append((table, rid, fields))), \
             patch.object(doc_shots, "filter_existing_fields", side_effect=lambda token, table, fields: fields):
            result = doc_shots.maybe_auto_approve_reference_image(
                "token",
                "asset_pet",
                {"父文档记录ID": "parent"},
                file_token="ft_pet",
                unified=True,
            )

        self.assertEqual(result["status"], "auto_approved")
        enabled.assert_called_once_with("token", stage_name=doc_shots.UNIFIED_AUTO_REVIEW_STAGE_NAME)
        self.assertIn(("tbl_unified", "asset_pet", {"参考图审核状态": "通过", "错误信息": ""}), updates)
        advance.assert_called_once_with("token", "parent", unified=True)

    def test_auto_approve_reference_image_requires_switch_and_token(self):
        with patch.object(doc_shots, "auto_review_enabled", return_value=False), \
             patch.object(doc_shots, "safe_update_record") as updater:
            result = doc_shots.maybe_auto_approve_reference_image("token", "asset_pet", {"父文档记录ID": "parent"}, file_token="ft_pet")
        self.assertEqual(result["status"], "disabled")
        updater.assert_not_called()

        with patch.object(doc_shots, "auto_review_enabled", return_value=True), \
             patch.object(doc_shots, "safe_update_record") as updater:
            result = doc_shots.maybe_auto_approve_reference_image("token", "asset_pet", {"父文档记录ID": "parent"}, file_token="")
        self.assertEqual(result["status"], "skipped")
        updater.assert_not_called()

    def test_dispatcher_reclaims_stale_running_image_stages(self):
        watches = {watch["name"]: watch for watch in dispatcher.RAW_WATCH_LIST}

        for name in ["脚本文档参考底图生成", "脚本文档分镜图生成", "脚本文档尾帧图生成"]:
            self.assertEqual(watches[name]["trigger_values"], ["待生成", "生成中"])

    def test_script_doc_image_watches_clear_stale_task_state_only_for_waiting_records(self):
        watches = {watch["name"]: watch for watch in dispatcher.RAW_WATCH_LIST}

        reference_waiting = dispatcher.apply_claim_clear_fields(
            {"参考图生成状态": "生成中"},
            watches["脚本文档参考底图生成"],
            "待生成",
        )
        self.assertEqual(reference_waiting["参考图任务ID"], "")
        self.assertEqual(reference_waiting["参考图原始响应JSON"], "")
        self.assertEqual(reference_waiting["参考图file_token"], "")
        self.assertEqual(reference_waiting["参考图本地路径"], "")
        self.assertEqual(reference_waiting["错误信息"], "")
        reference_running = dispatcher.apply_claim_clear_fields(
            {"参考图生成状态": "生成中"},
            watches["脚本文档参考底图生成"],
            "生成中",
        )
        self.assertNotIn("参考图任务ID", reference_running)

        shot_waiting = dispatcher.apply_claim_clear_fields(
            {"分镜图生成状态": "生成中"},
            watches["脚本文档分镜图生成"],
            "待生成",
        )
        self.assertEqual(shot_waiting["分镜图任务ID"], "")
        self.assertEqual(shot_waiting["分镜图原始响应JSON"], "")
        self.assertEqual(shot_waiting["分镜图file_token"], "")
        self.assertEqual(shot_waiting["分镜图本地路径"], "")
        self.assertEqual(shot_waiting["错误信息"], "")
        shot_running = dispatcher.apply_claim_clear_fields(
            {"分镜图生成状态": "生成中"},
            watches["脚本文档分镜图生成"],
            "生成中",
        )
        self.assertNotIn("分镜图任务ID", shot_running)

        tail_waiting = dispatcher.apply_claim_clear_fields(
            {"尾帧图生成状态": "生成中"},
            watches["脚本文档尾帧图生成"],
            "待生成",
        )
        self.assertEqual(tail_waiting["尾帧图任务ID"], "")
        self.assertEqual(tail_waiting["尾帧图原始响应JSON"], "")
        self.assertEqual(tail_waiting["尾帧图file_token"], "")
        self.assertEqual(tail_waiting["尾帧图本地路径"], "")
        self.assertEqual(tail_waiting["错误信息"], "")
        tail_running = dispatcher.apply_claim_clear_fields(
            {"尾帧图生成状态": "生成中"},
            watches["脚本文档尾帧图生成"],
            "生成中",
        )
        self.assertNotIn("尾帧图任务ID", tail_running)

    def test_default_parse_prompt_requires_dynamic_environment_problem_anchors(self):
        prompt = doc_shots.DEFAULT_PARSE_PROMPT

        for required in [
            "根据脚本判断",
            "不能默认套用尿渍",
            "不能默认套用虫害",
            "不得编造事故点",
            "直接给图片模型使用",
        ]:
            self.assertIn(required, prompt)

    def test_environment_asset_prompt_removes_script_meta_before_storage(self):
        asset = doc_shots.normalize_asset({
            "asset_type": "environment",
            "asset_id": "living_room",
            "prompt": "Living room sofa with visible black fleas, from the source script if one exists. script-defined problem location details.",
        }, 1)
        lowered = asset["prompt"].lower()

        self.assertIn("visible black fleas", asset["prompt"])
        for forbidden in ["source script", "if one exists", "script-defined", "when present in the script"]:
            self.assertNotIn(forbidden, lowered)

    def sample_payload(self):
        return {
            "global_assets": [
                {
                    "asset_id": "pet_hero",
                    "asset_type": "pet",
                    "asset_name": "MoMo",
                    "prompt": "Pixar style white cat with blue eyes",
                    "required_for_story": True,
                },
                {
                    "asset_id": "home_bg",
                    "asset_type": "environment",
                    "asset_name": "living room",
                    "prompt": "warm Thai living room background",
                    "required_for_story": True,
                },
                {
                    "asset_id": "owner_a",
                    "asset_type": "human",
                    "asset_name": "owner",
                    "prompt": "Thai woman in white shirt",
                    "required_for_story": False,
                },
            ],
            "shots": [
                {
                    "shot_no": 1,
                    "duration_sec": 4,
                    "voiceover_text": "สวัสดี",
                    "visual": "MoMo speaks in living room, no product visible",
                    "image_prompt": "MoMo cat close-up in living room",
                    "video_prompt": "MoMo blinks and talks",
                    "pet_ids": ["pet_hero"],
                    "character_ids": ["owner_a"],
                    "environment_id": "home_bg",
                    "reference_requirements": {
                        "use_product_reference": False,
                        "asset_ids": [],
                        "reason": "cat and background must stay consistent",
                    },
                    "publish_title": "Cat hook",
                    "publish_tags": ["pet", "hook"],
                },
                {
                    "shot_no": 2,
                    "duration_sec": 4,
                    "voiceover_text": "",
                    "visual": "Product hero close-up only",
                    "image_prompt": "realistic product close-up",
                    "video_prompt": "slow push-in on product",
                    "reference_requirements": {
                        "use_product_reference": True,
                        "asset_ids": [],
                        "reason": "product packaging must match product table",
                    },
                },
            ],
        }

    def test_normalize_payload_preserves_per_shot_reference_requirements(self):
        payload = doc_shots.validate_and_normalize_payload(self.sample_payload(), target_seconds=8)

        self.assertEqual(len(payload["global_assets"]), 3)
        self.assertEqual(
            payload["shots"][0]["reference_requirements"]["asset_ids"],
            ["pet_hero", "owner_a", "home_bg"],
        )
        self.assertFalse(payload["shots"][0]["reference_requirements"]["use_product_reference"])
        self.assertTrue(payload["shots"][1]["reference_requirements"]["use_product_reference"])
        self.assertEqual(payload["shots"][1]["reference_requirements"]["asset_ids"], [])

    def test_normalize_payload_filters_product_assets_and_keeps_product_reference_flag(self):
        raw = self.sample_payload()
        raw["global_assets"].append({
            "asset_id": "product_ref",
            "asset_type": "product",
            "asset_name": "Product bottle",
            "prompt": "Use the uploaded product reference image for exact packaging.",
            "required_for_story": True,
        })
        raw["global_assets"].append({
            "asset_id": "object_product",
            "asset_type": "object",
            "asset_name": "Spray bottle product reference",
            "prompt": "Exact product bottle reference, do not redesign the packaging.",
            "required_for_story": True,
        })
        raw["shots"][1]["reference_requirements"]["asset_ids"] = ["product_ref", "object_product"]
        raw["shots"][1]["reference_requirements"]["use_product_reference"] = False
        raw["shots"][1]["image_prompt"] = "Product bottle close-up with packaging visible"

        payload = doc_shots.validate_and_normalize_payload(raw, target_seconds=8)

        asset_ids = {asset["asset_id"] for asset in payload["global_assets"]}
        self.assertNotIn("product_ref", asset_ids)
        self.assertNotIn("object_product", asset_ids)
        self.assertTrue(payload["shots"][1]["reference_requirements"]["use_product_reference"])
        self.assertEqual(payload["shots"][1]["reference_requirements"]["asset_ids"], [])

        asset_records = doc_shots.build_reference_asset_records("recParent", payload)
        self.assertNotIn("product_ref", [item["fields"]["资产ID"] for item in asset_records])

    def test_build_records_creates_asset_and_shot_rows(self):
        payload = doc_shots.validate_and_normalize_payload(self.sample_payload(), target_seconds=8)

        asset_records = doc_shots.build_reference_asset_records("recParent", payload)
        shot_records = doc_shots.build_child_shot_records(
            {"任务名称": "doc task", "关联产品记录": [{"record_ids": ["recProduct"]}], "口播音色ID": "voice-a"},
            payload,
            parent_record_id="recParent",
            batch_id="BATCH-1",
        )

        self.assertEqual(asset_records[0]["fields"]["资产ID"], "pet_hero")
        self.assertEqual(asset_records[0]["fields"]["参考图审核状态"], "待确认")
        self.assertEqual(len(shot_records), 2)
        self.assertEqual(shot_records[0]["fields"]["父文档记录ID"], "recParent")
        self.assertEqual(shot_records[0]["fields"]["参考资产ID列表"], "pet_hero,owner_a,home_bg")
        self.assertEqual(shot_records[0]["fields"]["视频通道"], "OTU")
        self.assertEqual(shot_records[0]["fields"]["视频生成模型"], "OTU / 默认（配置表）")
        with patch.object(model_config_center, "load_task_default_fields", return_value={
            "默认供应商": "OTU",
            "默认模型显示名称": "OTU / veo_3_1-fast-fl",
            "画面尺寸": "720x1280",
            "画面比例": "9:16",
        }):
            defaulted_shots = doc_shots.apply_shot_default_models("real-token", shot_records)
        self.assertEqual(defaulted_shots[0]["fields"]["视频生成模型"], "OTU / veo_3_1-fast-fl")
        self.assertEqual(shot_records[0]["fields"]["使用统一AI路由"], "是")
        self.assertEqual(shot_records[1]["fields"]["需要产品参考图"], "是")
        self.assertEqual(shot_records[1]["fields"]["使用统一AI路由"], "是")
        self.assertIn("slow push-in on product", shot_records[1]["fields"]["视频提示词"])

    def test_child_shots_inherit_media_dimensions_from_parent(self):
        payload = doc_shots.validate_and_normalize_payload(self.sample_payload(), target_seconds=8)
        shot_records = doc_shots.build_child_shot_records(
            {
                "任务名称": "doc task",
                "分镜图画面尺寸": "720x1280",
                "分镜图画面比例": "9:16",
                "尾帧图画面尺寸": "1080x1920",
                "尾帧图画面比例": "9:16",
                "视频画面尺寸": "720x1280",
                "视频画面比例": "9:16",
            },
            payload,
            parent_record_id="recParent",
            batch_id="BATCH-1",
        )

        for field_name in [
            "分镜图画面尺寸",
            "分镜图画面比例",
            "尾帧图画面尺寸",
            "尾帧图画面比例",
            "视频画面尺寸",
            "视频画面比例",
        ]:
            self.assertEqual(shot_records[0]["fields"][field_name], {
                "分镜图画面尺寸": "720x1280",
                "分镜图画面比例": "9:16",
                "尾帧图画面尺寸": "1080x1920",
                "尾帧图画面比例": "9:16",
                "视频画面尺寸": "720x1280",
                "视频画面比例": "9:16",
            }[field_name])

    def test_child_shots_inherit_video_channel_and_model_from_parent(self):
        payload = doc_shots.validate_and_normalize_payload(self.sample_payload(), target_seconds=8)
        shot_records = doc_shots.build_child_shot_records(
            {"任务名称": "doc task", "视频通道": "OTU", "视频生成模型": "veo_3_1-fast-fl"},
            payload,
            parent_record_id="recParent",
            batch_id="BATCH-1",
        )

        self.assertEqual(shot_records[0]["fields"]["视频通道"], "OTU")
        self.assertEqual(shot_records[0]["fields"]["视频生成模型"], "OTU / veo_3_1-fast-fl")

    def test_voiceover_audio_defaults_to_not_triggered_even_when_text_exists(self):
        payload = doc_shots.validate_and_normalize_payload(self.sample_payload(), target_seconds=8)

        shot_records = doc_shots.build_child_shot_records(
            {"任务名称": "doc task", "口播音色ID": "voice-a"},
            payload,
            parent_record_id="recParent",
            batch_id="BATCH-1",
        )

        self.assertEqual(shot_records[0]["fields"]["口播文本"], "สวัสดี")
        self.assertEqual(shot_records[0]["fields"]["口播音频状态"], "不触发")
        self.assertEqual(shot_records[1]["fields"]["口播音频状态"], "不触发")

    def test_shot_table_field_specs_and_daily_views_match_production_cleanup(self):
        fields = {item["name"]: item for item in create_tables.SHOT_FIELDS}
        self.assertEqual(fields["视频通道"]["type"], "select")
        self.assertEqual([item["name"] for item in fields["视频通道"]["options"]], ["OTU", "AIHubMix"])
        self.assertEqual(fields["视频生成模型"]["type"], "select")
        video_model_options = [item["name"] for item in fields["视频生成模型"]["options"]]
        self.assertEqual(video_model_options[0], "默认（配置表）")
        for option in [
            "AIHubMix / veo-3.1-fast-generate-preview",
            "OTU / veo_3_1-fast-fl",
            "OTU / veo_3_1-fast-fl-hd",
        ]:
            self.assertIn(option, video_model_options)
        self.assertNotIn("AIHubMix / seeddance2.0", video_model_options)
        self.assertEqual(fields["视频生成时间"]["type"], "datetime")
        self.assertEqual(fields["生成时间"]["type"], "datetime")
        self.assertEqual(fields["分镜图任务ID"]["type"], "text")
        self.assertEqual(fields["分镜图原始响应JSON"]["type"], "text")
        self.assertEqual(fields["尾帧图任务ID"]["type"], "text")
        self.assertEqual(fields["尾帧图原始响应JSON"]["type"], "text")

        views = next(item for item in create_tables.TABLE_DEFINITIONS if item["key"] == "script_doc_shots")["views"]
        self.assertIn("首尾帧视频模式", views["01-分镜图生成"])
        self.assertIn("尾帧画面描述", views["01-分镜图生成"])
        self.assertIn("尾帧图生成状态", views["01-分镜图生成"])
        self.assertIn("尾帧图", views["01-分镜图生成"])
        for name in ["分镜图画面尺寸", "分镜图画面比例", "尾帧图画面尺寸", "尾帧图画面比例"]:
            self.assertIn(name, views["01-分镜图生成"])
        self.assertIn("视频通道", views["03-分镜视频"])
        self.assertIn("视频生成模型", views["03-分镜视频"])
        self.assertIn("视频画面尺寸", views["03-分镜视频"])
        self.assertIn("视频画面比例", views["03-分镜视频"])
        self.assertNotIn("视频AI模型", views["03-分镜视频"])
        self.assertNotIn("视频AI参数JSON", views["03-分镜视频"])
        self.assertEqual(
            views["03-分镜视频"],
            ["任务名称", "关联任务", "分镜序号", "目标时长秒", "分镜图生成状态", "分镜图", "首尾帧视频模式", "尾帧画面描述", "尾帧图生成状态", "尾帧图", "尾帧图错误信息", "视频提示词", "视频通道", "视频生成模型", "视频画面尺寸", "视频画面比例", "视频生成状态", "分镜视频", "分镜视频URL", "视频错误信息", "视频任务ID", "本地视频路径", "分镜视频file_token", "视频生成时间"],
        )
        self.assertNotIn("发布平台", views["04-发布素材"])
        self.assertIn("发布平台", views["99-排错"])
        self.assertIn("视频生成模型", views["99-排错"])
        self.assertIn("视频AI模型", views["99-排错"])
        self.assertIn("分镜图任务ID", views["99-排错"])
        self.assertIn("分镜图原始响应JSON", views["99-排错"])
        self.assertIn("尾帧图任务ID", views["99-排错"])
        self.assertIn("尾帧图原始响应JSON", views["99-排错"])

        asset_fields = {item["name"]: item for item in create_tables.ASSET_FIELDS}
        self.assertEqual(asset_fields["参考图AI模型"]["type"], "select")
        self.assertIn("Aitgenne / gpt-image-2", [item["name"] for item in asset_fields["参考图AI模型"]["options"]])
        self.assertEqual(asset_fields["参考图画面尺寸"]["type"], "select")
        self.assertEqual(asset_fields["参考图画面比例"]["type"], "select")
        self.assertEqual(asset_fields["参考图任务ID"]["type"], "text")
        self.assertEqual(asset_fields["参考图原始响应JSON"]["type"], "text")
        asset_views = next(item for item in create_tables.TABLE_DEFINITIONS if item["key"] == "script_doc_reference_assets")["views"]
        self.assertIn("参考图AI模型", asset_views["01-参考图确认"])
        self.assertIn("参考图AI模型", asset_views["99-参考图排错"])
        self.assertIn("参考图AI参数JSON", asset_views["99-参考图排错"])
        self.assertIn("参考图任务ID", asset_views["99-参考图排错"])
        self.assertIn("参考图原始响应JSON", asset_views["99-参考图排错"])

    def test_unified_ai_route_fields_are_optional_and_visible_in_advanced_view(self):
        fields = {item["name"]: item for item in create_tables.SHOT_FIELDS}
        for name in [
            "使用统一AI路由",
            "分镜图AI模型",
            "分镜图AI参数JSON",
            "分镜图画面尺寸",
            "分镜图画面比例",
            "尾帧图AI模型",
            "尾帧图画面尺寸",
            "尾帧图画面比例",
            "视频AI模型",
            "视频AI参数JSON",
            "视频生成模型",
            "视频画面尺寸",
            "视频画面比例",
        ]:
            self.assertIn(name, fields)

        views = next(item for item in create_tables.TABLE_DEFINITIONS if item["key"] == "script_doc_shots")["views"]
        self.assertIn("高级AI参数", views)
        self.assertIn("使用统一AI路由", views["高级AI参数"])
        self.assertIn("分镜图AI参数JSON", views["高级AI参数"])
        self.assertNotIn("视频AI模型", views["高级AI参数"])
        self.assertNotIn("视频AI参数JSON", views["高级AI参数"])
        self.assertIn("视频通道", views["高级AI参数"])
        self.assertIn("视频生成模型", views["高级AI参数"])
        for name in [
            "分镜图画面尺寸",
            "分镜图画面比例",
            "尾帧图画面尺寸",
            "尾帧图画面比例",
            "视频画面尺寸",
            "视频画面比例",
        ]:
            self.assertIn(name, views["高级AI参数"])

        task_views = next(item for item in create_tables.TABLE_DEFINITIONS if item["key"] == "script_doc_tasks")["views"]
        self.assertIn("视频生成模型", task_views["高级AI参数"])
        self.assertNotIn("视频AI模型", task_views["高级AI参数"])
        self.assertNotIn("视频AI参数JSON", task_views["高级AI参数"])
        self.assertIn("视频生成模型", task_views["99-解析排错"])
        self.assertIn("视频AI模型", task_views["99-解析排错"])

    def test_split_table_records_omit_mixed_record_type_field(self):
        payload = doc_shots.validate_and_normalize_payload(self.sample_payload(), target_seconds=8)

        asset_records = doc_shots.build_reference_asset_records("recParent", payload)
        shot_records = doc_shots.build_child_shot_records(
            {"任务名称": "doc task", "关联产品记录": [{"record_ids": ["recProduct"]}], "口播音色ID": "voice-a"},
            payload,
            parent_record_id="recParent",
            batch_id="BATCH-1",
        )

        for item in asset_records + shot_records:
            self.assertNotIn("记录类型", item["fields"])
            self.assertEqual(item["fields"]["关联任务"], ["recParent"])
        self.assertEqual(asset_records[0]["fields"]["父文档记录ID"], "recParent")
        self.assertEqual(shot_records[0]["fields"]["父文档记录ID"], "recParent")
        self.assertEqual(shot_records[0]["fields"]["关联产品记录"], ["recProduct"])

    def test_unified_table_fields_omit_voiceover_audio_and_use_record_type_views(self):
        field_names = [item["name"] for item in create_tables.UNIFIED_SCRIPT_DOC_FIELDS]

        self.assertEqual(field_names[:2], ["任务名称", "记录类型"])
        self.assertIn("记录类型", field_names)
        self.assertIn("脚本文档", field_names)
        self.assertIn("脚本文档附件", field_names)
        for forbidden in [
            "记录状态",
            "旧表来源",
            "旧记录ID",
            "脚本文档标题",
            "脚本文档正文",
            "脚本文档链接",
            "产品名",
            "关联产品",
            "选择产品",
            "口播音色ID",
            "口播文本",
            "AI供应商",
            "AI能力类型",
            "AI任务类型",
            "AI模型",
            "AI参数JSON",
            "视频AI模型",
            "解析结果JSON",
            "解析后逐镜头脚本",
            "参考图file_token",
            "参考图本地路径",
            "参考图原始响应JSON",
            "分镜原文",
            "人物描述",
            "场景描述",
            "产品焦点",
            "连续性要求",
            "文本",
            "提示词",
            "参考图选择原因",
            "分镜图本地路径",
            "分镜图file_token",
            "分镜图原始响应JSON",
            "分镜图生成时间",
            "尾帧图提示词",
            "尾帧图本地路径",
            "尾帧图file_token",
            "尾帧图原始响应JSON",
            "尾帧图生成时间",
            "本地视频路径",
            "分镜视频file_token",
            "视频生成原始响应JSON",
            "视频生成时间",
            "生成时间",
            "发布平台",
            "口播音频状态",
            "口播音频",
            "口播音频时长秒",
            "口播音频路径",
            "口播音频下载链接",
            "口播音频FileToken",
            "口播音频错误信息",
        ]:
            self.assertNotIn(forbidden, field_names)

        self.assertEqual(create_tables.UNIFIED_TABLE_DEFINITION["key"], "script_doc_unified")
        views = create_tables.UNIFIED_TABLE_DEFINITION["views"]
        self.assertEqual(views["01-文档入口"]["filter"]["conditions"], [["记录类型", "is", ["文档任务"]]])
        self.assertEqual(views["01-文档入口"]["visible_fields"][:3], ["任务名称", "脚本文档", "脚本文档附件"])
        self.assertNotIn("分镜风格", views["01-文档入口"]["visible_fields"])
        for view_name in ["01-文档入口", "02-参考图确认", "03-分镜图生成", "04-分镜视频", "05-发布素材"]:
            self.assertEqual(views[view_name]["visible_fields"][0], "任务名称")
            self.assertNotIn("记录类型", views[view_name]["visible_fields"])
        self.assertEqual(views["02-参考图确认"]["filter"]["conditions"], [["记录类型", "is", ["参考资产"]]])
        for view_name in ["03-分镜图生成", "04-分镜视频", "05-发布素材"]:
            self.assertEqual(views[view_name]["filter"]["conditions"], [["记录类型", "is", ["分镜"]]])
        self.assertNotIn("04-口播音频", views)

    def test_parse_parent_record_unified_writes_only_new_unified_table(self):
        parent_fields = {
            "任务名称": "doc task",
            "脚本文档": "0-4s: hook",
            "视频时长": "8s",
            "使用统一AI路由": "是",
            "解析AI模型": "AIHubMix / gemini-3.1-pro-preview",
        }
        created_batches = []
        updates = []

        with patch.object(doc_shots, "TABLE_SCRIPT_DOC_UNIFIED", "tbl_unified"), \
             patch.object(doc_shots, "TABLE_SCRIPT_DOC_TASKS", "tbl_tasks"), \
             patch.object(doc_shots, "TABLE_SCRIPT_DOC_REFERENCE_ASSETS", "tbl_assets"), \
             patch.object(doc_shots, "TABLE_SCRIPT_DOC_SHOTS", "tbl_shots"), \
             patch.object(doc_shots, "ensure_script_doc_tables"), \
             patch.object(doc_shots, "get_feishu_token", return_value="token"), \
             patch.object(doc_shots, "safe_get_record", return_value=parent_fields) as getter, \
             patch.object(doc_shots, "safe_list_records", return_value=[
                 {"fields": {"环节": "统一AI路由启用状态", "模型名称": "指定记录启用"}},
                 {"fields": {"供应商": "AIHubMix", "API 代理地址": "https://aihubmix.com/gemini", "API Key": "sk-aihubmix"}},
             ]), \
             patch.object(doc_shots, "get_model_config", return_value={
                 "provider": "AIHubMix",
                 "model": "gemini-3.1-pro-preview",
                 "api_key": "sk-aihubmix",
                 "api_base": "https://aihubmix.com/gemini",
                 "call_type": "Gemini 原生 SDK",
                 "prompt": "CONFIGURED SCRIPT DOC PROMPT",
             }), \
             patch.object(doc_shots.ai_routing, "call_text_model", return_value=Mock(text=json.dumps(self.sample_payload()))), \
             patch.object(doc_shots, "cleanup_children", return_value=0) as cleanup, \
             patch.object(doc_shots, "create_records", side_effect=lambda token, table, records: created_batches.append((table, records)) or len(records)), \
             patch.object(doc_shots, "safe_update_record", side_effect=lambda token, table, rid, fields: updates.append((table, rid, fields))), \
             patch.object(doc_shots, "filter_existing_fields", side_effect=lambda token, table, fields: fields):
            result = doc_shots.parse_parent_record("recParent", unified=True)

        self.assertEqual(result["status"], "success")
        getter.assert_called_once_with("token", "tbl_unified", "recParent")
        cleanup.assert_any_call("token", "tbl_unified", "recParent", record_type="参考资产")
        cleanup.assert_any_call("token", "tbl_unified", "recParent", record_type="分镜")
        self.assertTrue(created_batches)
        self.assertEqual({table for table, _records in created_batches}, {"tbl_unified"})
        created_fields = [record["fields"] for _table, records in created_batches for record in records]
        self.assertIn("参考资产", {fields["记录类型"] for fields in created_fields})
        self.assertIn("分镜", {fields["记录类型"] for fields in created_fields})
        for fields in created_fields:
            self.assertNotIn("口播音频状态", fields)
            self.assertNotIn("记录状态", fields)
            self.assertEqual(fields["任务名称"], "doc task")
            self.assertNotIn("口播文本", fields)
        self.assertEqual(updates[-1][0], "tbl_unified")
        self.assertNotIn("解析结果JSON", updates[-1][2])
        self.assertNotIn("解析后逐镜头脚本", updates[-1][2])

    def test_unified_parse_can_read_script_doc_attachment(self):
        parent_fields = {
            "任务名称": "doc task",
            "脚本文档附件": [{"file_token": "ft_doc"}],
        }
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.object(doc_shots, "WORKSPACE", tmpdir), \
             patch.object(doc_shots, "safe_download_attachment", side_effect=lambda token, file_token, save_path: Path(save_path).write_text("0-4s: hook from attachment", encoding="utf-8") or True):
            text = doc_shots.read_script_document_text("token", "recParent", parent_fields, unified=True)

        self.assertEqual(text, "0-4s: hook from attachment")

    def test_parse_parent_record_uses_script_doc_text_split_config(self):
        parent_fields = {
            "任务名称": "doc task",
            "脚本文档正文": "0-4s: hook",
            "视频时长": "8s",
        }
        with patch.dict(doc_shots.CONFIG_RECORDS, {"script_doc_text_split": "rec_script_split"}, clear=True), \
             patch.object(doc_shots, "ensure_script_doc_tables"), \
             patch.object(doc_shots, "get_feishu_token", return_value="token"), \
             patch.object(doc_shots, "safe_get_record", return_value=parent_fields), \
             patch.object(doc_shots, "get_model_config", return_value={
                 "model": "gemini-3.1-pro-preview",
                 "api_key": "sk-text",
                 "api_base": "https://aihubmix.com/gemini",
                 "prompt": "CONFIGURED SCRIPT DOC PROMPT",
             }) as getter:
            result = doc_shots.parse_parent_record("recParent", dry_run=True)

        getter.assert_called_once_with("token", "stage:脚本文档结构化拆分-Gemini")
        self.assertEqual(result["status"], "dry_run_ready")
        self.assertEqual(result["record_id"], "recParent")

    def test_new_unified_dispatcher_watches_are_parallel_and_have_no_voiceover(self):
        watches = {watch["name"]: watch for watch in dispatcher.RAW_WATCH_LIST}
        old_watch = watches["脚本文档解析拆分"]
        self.assertEqual(old_watch["table"], dispatcher.TABLE_SCRIPT_DOC_TASKS)

        expected = {
            "003新表脚本文档解析拆分": ("解析状态", ["文档任务"], ["parse", "--unified"]),
            "003新表脚本文档参考底图生成": ("参考图生成状态", ["参考资产"], ["reference-image", "--unified"]),
            "003新表脚本文档分镜图生成": ("分镜图生成状态", ["分镜"], ["render", "--table", "script_doc_unified"]),
            "003新表脚本文档尾帧图生成": ("尾帧图生成状态", ["分镜"], ["last-frame", "--table", "script_doc_unified"]),
            "003新表脚本文档分镜视频生成": ("视频生成状态", ["分镜"], ["--table", "script_doc_unified"]),
        }
        for name, (status_field, record_types, args_prefix) in expected.items():
            self.assertIn(name, watches)
            watch = watches[name]
            self.assertEqual(watch["table"], dispatcher.TABLE_SCRIPT_DOC_UNIFIED)
            self.assertEqual(watch["status_field"], status_field)
            self.assertEqual(watch["required_field_values"], {"记录类型": record_types})
            self.assertEqual(watch["args"][:len(args_prefix)], args_prefix)
            self.assertTrue(watch["keep_when_table_missing"])
            clear_fields = set(watch.get("claim_clear_fields") or [])
            for clear_values in (watch.get("claim_clear_values_by_trigger_value") or {}).values():
                clear_fields.update(clear_values)
            for removed in create_tables.UNIFIED_REMOVED_FIELDS:
                self.assertNotIn(removed, clear_fields)
        self.assertNotIn("003新表脚本文档口播音频生成", watches)

    def test_model_config_center_adds_unified_script_doc_defaults_without_voiceover(self):
        defaults = {
            (spec.table_key, spec.stage, spec.source_config_stage, spec.dispatch_stage_name)
            for spec in model_config_center.RUNTIME_DEFAULT_SPECS
        }

        self.assertIn(("script_doc_unified", "脚本文档结构化拆分默认", "脚本文档结构化拆分-Gemini", "003新表脚本文档解析拆分"), defaults)
        self.assertIn(("script_doc_unified", "参考底图生成默认", "图片生成-OTU", "003新表脚本文档参考底图生成"), defaults)
        self.assertIn(("script_doc_unified", "分镜图生成默认", "图片生成-OTU", "003新表脚本文档分镜图生成"), defaults)
        self.assertIn(("script_doc_unified", "尾帧图生成默认", "图片生成-OTU", "003新表脚本文档尾帧图生成"), defaults)
        self.assertIn(("script_doc_unified", "分镜视频生成默认", "分镜视频生成-OTU", "003新表脚本文档分镜视频生成"), defaults)
        self.assertNotIn(("script_doc_unified", "口播音频生成默认", "语音合成-MiniMax", ""), defaults)
        self.assertEqual(model_config_center.TASK_TABLES["script_doc_unified"], "003-脚本文档生产表")
        unified_limits = {
            spec.dispatch_stage_name: spec.max_concurrency
            for spec in model_config_center.RUNTIME_DEFAULT_SPECS
            if spec.table_key == "script_doc_unified"
        }
        self.assertEqual(unified_limits["003新表脚本文档解析拆分"], "1")
        self.assertEqual(unified_limits["003新表脚本文档参考底图生成"], "3")
        self.assertEqual(unified_limits["003新表脚本文档分镜图生成"], "3")
        self.assertEqual(unified_limits["003新表脚本文档尾帧图生成"], "3")
        self.assertEqual(unified_limits["003新表脚本文档分镜视频生成"], "3")

    def test_generate_reference_image_routes_by_reference_model_field(self):
        fields = {
            "参考提示词": "make a clean reference",
            "参考图AI模型": "Aitgenne / gpt-image-2",
            "参考图生成状态": "待生成",
        }
        config_records = [
            {"fields": {"AI供应商": "Aitgenne", "API 代理地址": "https://api.aitgenne.com", "API Key": "sk-aitgenne"}},
        ]
        image_result = Mock()
        image_result.task_id = ""
        image_result.submit_body = {"id": "aitgenne_sync"}
        image_result.result_body = {"data": [{"b64_json": "x"}]}
        image_result.request_summary = {"provider": "Aitgenne", "model": "gpt-image-2"}
        updates = []

        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(doc_shots, "WORKSPACE", tmp), \
             patch.object(doc_shots, "TABLE_SCRIPT_DOC_REFERENCE_ASSETS", "tbl_assets"), \
             patch.object(doc_shots, "ensure_script_doc_tables"), \
             patch.object(doc_shots, "get_feishu_token", return_value="token"), \
             patch.object(doc_shots, "safe_get_record", return_value=fields), \
             patch.object(doc_shots, "safe_list_records", return_value=config_records), \
             patch.object(doc_shots, "get_model_config", return_value={
                 "provider": "OTU",
                 "api_key": "sk-otu",
                 "api_base": "https://otuapi.com",
                 "model": "gpt-image-2",
                 "size": "720x1280",
                 "aspect_ratio": "9:16",
             }), \
             patch.object(doc_shots, "run_image_generation", return_value=image_result) as runner, \
             patch.object(doc_shots, "upload_image_to_feishu", return_value="ft_image"), \
             patch.object(doc_shots, "safe_update_record", side_effect=lambda token, table, rid, patch_fields: updates.append(patch_fields)), \
             patch.object(doc_shots, "filter_existing_fields", side_effect=lambda token, table, patch_fields: patch_fields):
            result = doc_shots.generate_reference_image("recAsset")

        runner.assert_called_once()
        route = runner.call_args.args[0]
        self.assertEqual(route.provider, "Aitgenne")
        self.assertEqual(route.model, "Aitgenne / gpt-image-2")
        self.assertEqual(runner.call_args.args[1], doc_shots.build_reference_image_prompt(fields))
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["file_token"], "ft_image")
        self.assertTrue(any(update.get("参考图生成状态") == "成功" for update in updates))

    def test_parse_parent_record_unified_route_uses_prefixed_model_provider(self):
        parent_fields = {
            "任务名称": "doc task",
            "脚本文档正文": "0-4s: hook",
            "视频时长": "8s",
            "使用统一AI路由": "是",
            "解析AI模型": "Aitgenne / gpt-5.5",
        }
        config_records = [
            {"fields": {"环节": "统一AI路由启用状态", "模型名称": "指定记录启用"}},
            {"fields": {"AI供应商": "Aitgenne", "API 代理地址": "https://api.aitgenne.com", "API Key": "sk-aitgenne"}},
        ]

        with patch.dict(doc_shots.CONFIG_RECORDS, {"script_doc_text_split": "rec_script_split"}, clear=True), \
             patch.object(doc_shots, "ensure_script_doc_tables"), \
             patch.object(doc_shots, "get_feishu_token", return_value="token"), \
             patch.object(doc_shots, "safe_get_record", return_value=parent_fields), \
             patch.object(doc_shots, "safe_list_records", return_value=config_records), \
             patch.object(doc_shots, "get_model_config", return_value={
                 "provider": "AIHubMix",
                 "model": "gemini-3.1-pro-preview",
                 "api_key": "sk-aihubmix",
                 "api_base": "https://aihubmix.com/gemini",
                 "call_type": "Gemini 原生 SDK",
                 "prompt": "CONFIGURED SCRIPT DOC PROMPT",
             }):
            result = doc_shots.parse_parent_record("recParent", dry_run=True)

        route = result["unified_ai_route"]
        self.assertEqual(route["provider"], "Aitgenne")
        self.assertEqual(route["call_type"], "OpenAI兼容 chat/completions")
        self.assertEqual(route["endpoint"], "https://api.aitgenne.com/v1/chat/completions")

    def test_parse_parent_record_can_fallback_to_aihubmix_parse_model(self):
        parent_fields = {
            "任务名称": "doc task",
            "脚本文档正文": "0-4s: hook",
            "视频时长": "8s",
            "使用统一AI路由": "是",
            "解析AI模型": "AIHubMix / gemini-3.1-pro-preview",
        }
        config_records = [
            {"fields": {"环节": "统一AI路由启用状态", "模型名称": "指定记录启用"}},
            {"fields": {"供应商": "AIHubMix", "API 代理地址": "https://aihubmix.com/gemini", "API Key": "sk-aihubmix"}},
            {"fields": {"供应商": "Aitgenne", "API 代理地址": "https://api.aitgenne.com/v1", "API Key": "sk-aitgenne"}},
        ]

        with patch.dict(doc_shots.CONFIG_RECORDS, {"script_doc_text_split": "rec_script_split"}, clear=True), \
             patch.object(doc_shots, "ensure_script_doc_tables"), \
             patch.object(doc_shots, "get_feishu_token", return_value="token"), \
             patch.object(doc_shots, "safe_get_record", return_value=parent_fields), \
             patch.object(doc_shots, "safe_list_records", return_value=config_records), \
             patch.object(doc_shots, "get_model_config", return_value={
                 "provider": "Aitgenne",
                 "model": "Aitgenne / gpt-5.5",
                 "api_key": "sk-aitgenne",
                 "api_base": "https://api.aitgenne.com/v1",
                 "call_type": "OpenAI兼容 chat/completions",
                 "prompt": "CONFIGURED SCRIPT DOC PROMPT",
             }):
            result = doc_shots.parse_parent_record("recParent", dry_run=True)

        route = result["unified_ai_route"]
        self.assertEqual(route["provider"], "AIHubMix")
        self.assertEqual(route["call_type"], "Gemini 原生 SDK")
        self.assertEqual(route["endpoint"], "https://aihubmix.com/gemini")

    def test_parse_parent_record_real_unified_call_uses_prefixed_route(self):
        parent_fields = {
            "任务名称": "doc task",
            "脚本文档正文": "0-4s: hook",
            "视频时长": "8s",
            "使用统一AI路由": "是",
            "解析AI模型": "Aitgenne / gpt-5.5",
        }
        config_records = [
            {"fields": {"环节": "统一AI路由启用状态", "模型名称": "指定记录启用"}},
            {"fields": {"AI供应商": "Aitgenne", "API 代理地址": "https://api.aitgenne.com", "API Key": "sk-aitgenne"}},
        ]

        with patch.dict(doc_shots.CONFIG_RECORDS, {"script_doc_text_split": "rec_script_split"}, clear=True), \
             patch.object(doc_shots, "ensure_script_doc_tables"), \
             patch.object(doc_shots, "get_feishu_token", return_value="token"), \
             patch.object(doc_shots, "safe_get_record", return_value=parent_fields), \
             patch.object(doc_shots, "safe_list_records", return_value=config_records), \
             patch.object(doc_shots, "get_model_config", return_value={
                 "provider": "AIHubMix",
                 "model": "gemini-3.1-pro-preview",
                 "api_key": "sk-aihubmix",
                 "api_base": "https://aihubmix.com/gemini",
                 "call_type": "Gemini 原生 SDK",
                 "prompt": "CONFIGURED SCRIPT DOC PROMPT",
             }), \
             patch.object(doc_shots.ai_routing, "call_text_model", return_value=Mock(text=json.dumps(self.sample_payload()))) as call_text, \
             patch.object(doc_shots, "safe_update_record"), \
             patch.object(doc_shots, "filter_existing_fields", side_effect=lambda token, table, f: f), \
             patch.object(doc_shots, "cleanup_children", return_value=0), \
             patch.object(doc_shots, "create_records", return_value=5):
            result = doc_shots.parse_parent_record("recParent")

        route = call_text.call_args.args[0]
        self.assertEqual(result["status"], "success")
        self.assertEqual(route.provider, "Aitgenne")
        self.assertEqual(route.call_type, "OpenAI兼容 chat/completions")
        self.assertEqual(route.api_base, "https://api.aitgenne.com")
        self.assertEqual(route.api_key, "sk-aitgenne")

    def test_build_parse_prompt_uses_configured_system_prompt(self):
        prompt = doc_shots.build_parse_prompt(
            {"视频时长": "8s", "分镜风格": "写实", "产品名": "Pet Spray"},
            "0-4s: hook",
            system_prompt="CONFIGURED SCRIPT DOC PROMPT",
        )

        self.assertIn("CONFIGURED SCRIPT DOC PROMPT", prompt)
        self.assertIn("## 目标参数", prompt)
        self.assertIn("0-4s: hook", prompt)

    def test_human_reference_prompt_uses_single_front_facing_white_background_portrait(self):
        prompt = doc_shots.build_reference_image_prompt({
            "参考类型": "human",
            "参考名称": "owner",
            "参考提示词": "Thai woman in white shirt, anxious but kind",
        })

        self.assertIn("以脚本人物描述/参考提示词为唯一角色设定锚点", prompt)
        self.assertIn("单张白底半身正脸身份照", prompt)
        self.assertIn("pure white background", prompt)
        self.assertIn("front-facing upper-body", prompt)
        self.assertIn("full unobstructed face visible", prompt)
        self.assertIn("禁止侧脸", prompt)
        self.assertNotIn("全身90°侧视站姿", prompt)
        self.assertNotIn("全身后视站姿", prompt)
        self.assertNotIn("2x3网格", prompt)
        self.assertNotIn("九视图人物设定图", prompt)
        self.assertNotIn("character sheet", prompt)

    def test_human_reference_prompt_appends_revision_note_without_relaxing_constraints(self):
        prompt = doc_shots.build_reference_image_prompt({
            "参考类型": "human",
            "参考名称": "owner",
            "参考提示词": "Thai woman in white shirt",
            "参考图修改要求": "衣服改成浅蓝色，但不要改变年龄感",
        })

        self.assertIn("本次重生成修改要求", prompt)
        self.assertIn("衣服改成浅蓝色，但不要改变年龄感", prompt)
        self.assertIn("不能放松白底、正对镜头、完整露出全脸", prompt)

    def test_non_human_reference_prompt_keeps_single_image_logic(self):
        prompt = doc_shots.build_reference_image_prompt({
            "参考类型": "pet",
            "参考名称": "MoMo",
            "参考提示词": "white cat with blue eyes",
            "参考图修改要求": "fur slightly longer",
        })

        self.assertIn("Generate one clean reference image for later storyboard consistency.", prompt)
        self.assertIn("Output a single image only. No text, watermark, collage, or split panels.", prompt)
        self.assertIn("fur slightly longer", prompt)
        self.assertNotIn("2x3网格六张头部小图", prompt)

    def test_generate_reference_image_uses_configured_size_and_aspect_ratio(self):
        fields = {
            "参考类型": "human",
            "参考名称": "owner",
            "参考提示词": "Thai owner reference.",
        }

        with patch.object(doc_shots, "get_feishu_token", return_value="token"), \
             patch.object(doc_shots, "safe_get_record", return_value=fields), \
             patch.object(doc_shots, "get_model_config", return_value={
                 "api_key": "sk-otu",
                 "api_base": "https://otuapi.com",
                 "model": "gpt-image-2",
                 "size": "1280x720",
                 "aspect_ratio": "16:9",
             }), \
             patch.object(doc_shots, "safe_update_record"), \
             patch.object(doc_shots, "filter_existing_fields", side_effect=lambda token, table_id, fields: fields), \
             patch.object(doc_shots, "submit_otu_image_task", return_value=("task_1", {"id": "task_1"})) as submitter, \
             patch.object(doc_shots, "poll_otu_image_task", return_value={"result_url": "https://x.test/out.png"}), \
             patch.object(doc_shots, "download_otu_image_result"), \
             patch.object(doc_shots, "upload_image_to_feishu", return_value="ft_out"):
            result = doc_shots.generate_reference_image("recAsset")

        self.assertEqual(result["status"], "success")
        self.assertEqual(submitter.call_args.kwargs["size"], "1280x720")
        self.assertEqual(submitter.call_args.kwargs["aspect_ratio"], "16:9")
        self.assertEqual(submitter.call_args.kwargs["metadata"]["aspectRatio"], "16:9")
        self.assertEqual(submitter.call_args.kwargs["metadata"]["aspect_ratio"], "16:9")

    def test_generate_reference_image_writes_task_id_and_response_json(self):
        fields = {
            "参考类型": "pet",
            "参考名称": "cat",
            "参考提示词": "white cat reference.",
            "参考图生成状态": "待生成",
        }
        updates = []

        with patch.object(doc_shots, "get_feishu_token", return_value="token"), \
             patch.object(doc_shots, "safe_get_record", return_value=fields), \
             patch.object(doc_shots, "get_model_config", return_value={
                 "api_key": "sk-otu",
                 "api_base": "https://otuapi.com",
                 "model": "gpt-image-2",
                 "size": "720x1280",
                 "aspect_ratio": "9:16",
             }), \
             patch.object(doc_shots, "safe_update_record", side_effect=lambda token, table, rid, fields: updates.append(fields)), \
             patch.object(doc_shots, "filter_existing_fields", side_effect=lambda token, table_id, fields: fields), \
             patch.object(doc_shots, "submit_otu_image_task", return_value=("task_ref", {"id": "task_ref"})) as submitter, \
             patch.object(doc_shots, "poll_otu_image_task", return_value={"result_url": "https://x.test/out.png"}), \
             patch.object(doc_shots, "download_otu_image_result"), \
             patch.object(doc_shots, "upload_image_to_feishu", return_value="ft_out"):
            result = doc_shots.generate_reference_image("recAsset")

        self.assertEqual(result["status"], "success")
        self.assertEqual(updates[0]["参考图生成状态"], "生成中")
        self.assertEqual(updates[1]["参考图任务ID"], "task_ref")
        self.assertIn("参考图原始响应JSON", updates[1])
        self.assertEqual(updates[-1]["参考图任务ID"], "task_ref")
        self.assertIn("参考图原始响应JSON", updates[-1])
        submitter.assert_called_once()

    def test_generate_reference_image_resumes_running_task_without_resubmitting(self):
        fields = {
            "参考类型": "pet",
            "参考名称": "cat",
            "参考提示词": "white cat reference.",
            "参考图生成状态": "生成中",
            "参考图任务ID": "task_existing",
            "参考图原始响应JSON": '{"submit":{"id":"task_existing"}}',
        }
        updates = []

        with patch.object(doc_shots, "get_feishu_token", return_value="token"), \
             patch.object(doc_shots, "safe_get_record", return_value=fields), \
             patch.object(doc_shots, "get_model_config", return_value={
                 "api_key": "sk-otu",
                 "api_base": "https://otuapi.com",
                 "model": "gpt-image-2",
                 "size": "720x1280",
                 "aspect_ratio": "9:16",
             }), \
             patch.object(doc_shots, "safe_update_record", side_effect=lambda token, table, rid, fields: updates.append(fields)), \
             patch.object(doc_shots, "filter_existing_fields", side_effect=lambda token, table_id, fields: fields), \
             patch.object(doc_shots, "submit_otu_image_task") as submitter, \
             patch.object(doc_shots, "poll_otu_image_task", return_value={"result_url": "https://x.test/out.png"}) as poller, \
             patch.object(doc_shots, "download_otu_image_result"), \
             patch.object(doc_shots, "upload_image_to_feishu", return_value="ft_out"):
            result = doc_shots.generate_reference_image("recAsset")

        self.assertEqual(result["status"], "success")
        self.assertIn("恢复轮询已有 OTU 参考底图任务", updates[0]["错误信息"])
        submitter.assert_not_called()
        poller.assert_called_once()
        self.assertEqual(poller.call_args.args[1], "task_existing")

    def test_collect_reference_images_uses_only_shot_requested_assets_and_product(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            product_paths = [
                tmp_path / "product_1.png",
                tmp_path / "product_2.png",
                tmp_path / "product_3.png",
            ]
            pet_path = tmp_path / "pet.png"
            env_path = tmp_path / "env.png"
            for path in product_paths:
                path.write_bytes(b"x" * 2000)
            pet_path.write_bytes(b"x" * 2000)
            env_path.write_bytes(b"x" * 2000)
            fields = {
                "父文档记录ID": "recParent",
                "需要产品参考图": "是",
                "参考资产ID列表": "pet_hero",
            }
            parent_fields = {"关联产品": [{"record_ids": ["recProduct"]}]}
            records = [
                {
                    "record_id": "recPet",
                    "fields": {
                        "记录类型": "参考底图记录",
                        "父文档记录ID": "recParent",
                        "资产ID": "pet_hero",
                        "参考类型": "pet",
                        "参考图审核状态": "通过",
                        "参考图": [{"file_token": "ft_pet"}],
                    },
                },
                {
                    "record_id": "recEnv",
                    "fields": {
                        "记录类型": "参考底图记录",
                        "父文档记录ID": "recParent",
                        "资产ID": "home_bg",
                        "参考类型": "environment",
                        "参考图审核状态": "通过",
                        "参考图": [{"file_token": "ft_env"}],
                    },
                },
            ]
            download = Mock(side_effect=[*product_paths, pet_path])
            get_product = Mock(return_value=("recProduct", {"产品图片": [
                {"file_token": "ft_product_1"},
                {"file_token": "ft_product_2"},
                {"file_token": "ft_product_3"},
            ]}))

            refs = doc_shots.collect_reference_images_for_shot(
                "token",
                fields,
                parent_fields,
                records,
                tmp_path,
                download_fn=download,
                product_getter=get_product,
            )

            self.assertEqual([r["role"] for r in refs], ["product:1", "product:2", "product:3", "pet:pet_hero"])
            self.assertEqual(
                [call.args[1] for call in download.call_args_list],
                ["ft_product_1", "ft_product_2", "ft_product_3", "ft_pet"],
            )
            self.assertEqual(
                [call.args[2] for call in download.call_args_list[:3]],
                [
                    str(tmp_path / "reference_product_1.png"),
                    str(tmp_path / "reference_product_2.png"),
                    str(tmp_path / "reference_product_3.png"),
                ],
            )

    def test_collect_reference_images_rejects_unapproved_required_asset(self):
        with tempfile.TemporaryDirectory() as tmp:
            fields = {"父文档记录ID": "recParent", "参考资产ID列表": "pet_hero"}
            records = [
                {
                    "fields": {
                        "记录类型": "参考底图记录",
                        "父文档记录ID": "recParent",
                        "资产ID": "pet_hero",
                        "参考图审核状态": "待确认",
                    }
                }
            ]

            with self.assertRaisesRegex(ValueError, "未审核通过"):
                doc_shots.collect_reference_images_for_shot(
                    "token",
                    fields,
                    {},
                    records,
                    Path(tmp),
                    download_fn=Mock(),
                    product_getter=Mock(),
                )

    def test_collect_reference_images_uses_target_path_when_downloader_returns_bool(self):
        with tempfile.TemporaryDirectory() as tmp:
            fields = {"父文档记录ID": "recParent", "参考资产ID列表": "pet_hero"}
            records = [
                {
                    "fields": {
                        "父文档记录ID": "recParent",
                        "资产ID": "pet_hero",
                        "参考类型": "pet",
                        "参考图审核状态": "通过",
                        "参考图": [{"file_token": "ft_pet"}],
                    }
                }
            ]

            refs = doc_shots.collect_reference_images_for_shot(
                "token",
                fields,
                {},
                records,
                Path(tmp),
                download_fn=Mock(return_value=True),
                product_getter=Mock(),
            )

            self.assertEqual(refs[0]["path"], str(Path(tmp) / "reference_pet_hero.png"))


if __name__ == "__main__":
    unittest.main()
