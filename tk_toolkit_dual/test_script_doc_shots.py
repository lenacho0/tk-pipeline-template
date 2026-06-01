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


class ScriptDocShotsTests(unittest.TestCase):
    def test_default_parse_prompt_requires_environment_problem_anchors(self):
        prompt = doc_shots.DEFAULT_PARSE_PROMPT

        for required in [
            "urine stain",
            "wet patch",
            "visible problem area",
            "accident point",
            "不要删除尿渍",
        ]:
            self.assertIn(required, prompt)

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
        self.assertEqual(shot_records[0]["fields"]["视频通道"], "AIHubMix")
        self.assertEqual(shot_records[0]["fields"]["视频生成模型"], "AIHubMix / 默认（配置表）")
        self.assertEqual(shot_records[1]["fields"]["需要产品参考图"], "是")
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
        self.assertEqual([item["name"] for item in fields["视频通道"]["options"]], ["AIHubMix", "OTU"])
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

        getter.assert_called_once_with("token", "rec_script_split")
        self.assertEqual(result["status"], "dry_run_ready")
        self.assertEqual(result["record_id"], "recParent")

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
        self.assertEqual(route.api_base, "")
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

    def test_human_reference_prompt_uses_character_sheet_layout(self):
        prompt = doc_shots.build_reference_image_prompt({
            "参考类型": "human",
            "参考名称": "owner",
            "参考提示词": "Thai woman in white shirt, anxious but kind",
        })

        self.assertIn("以脚本人物描述/参考提示词为唯一角色设定锚点", prompt)
        self.assertIn("左侧(约60%宽度):三张大图横排列", prompt)
        self.assertIn("右侧(约40%宽度):2x3网格六张头部小图", prompt)
        self.assertIn("全身正视站姿", prompt)
        self.assertIn("全身90°侧视站姿", prompt)
        self.assertIn("全身后视站姿", prompt)
        self.assertIn("同一张脸同一发际线", prompt)
        self.assertNotIn("collage, or split panels", prompt)

    def test_human_reference_prompt_appends_revision_note_without_relaxing_constraints(self):
        prompt = doc_shots.build_reference_image_prompt({
            "参考类型": "human",
            "参考名称": "owner",
            "参考提示词": "Thai woman in white shirt",
            "参考图修改要求": "衣服改成浅蓝色，但不要改变年龄感",
        })

        self.assertIn("本次重生成修改要求", prompt)
        self.assertIn("衣服改成浅蓝色，但不要改变年龄感", prompt)
        self.assertIn("不能破坏同一角色、超干净白底、无文字水印、九视图人物设定图版式", prompt)

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
