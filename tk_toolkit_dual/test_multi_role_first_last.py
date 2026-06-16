import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import tk_create_multi_role_first_last_table as create_table
import tk_dispatcher as dispatcher
import tk_multi_role_first_last as multi_role


def sample_plan(role_count=3):
    roles = [
        {
            "role_id": f"role_{idx}",
            "role_name": f"Role {idx}",
            "story_function": "rescuer" if idx == 2 else "witness",
            "visual_description": f"visual {idx}",
            "needs_reference_image": True,
        }
        for idx in range(1, role_count + 1)
    ]
    return {
        "roles": roles,
        "conflict_mechanism": {
            "discoverer_role_id": "role_1",
            "rescuer_role_id": "role_2",
            "troublemaker_role_id": "role_3",
            "accident_source": "stain on sofa",
        },
        "assets": [
            {
                "asset_id": role["role_id"],
                "asset_type": "human",
                "asset_name": role["role_name"],
                "prompt": role["visual_description"],
                "source_role_ids": [role["role_id"]],
            }
            for role in roles
        ] + [
            {
                "asset_id": "living_room",
                "asset_type": "environment",
                "asset_name": "Living room",
                "prompt": "same sofa corner",
            }
        ],
        "keyframes": [
            {
                "keyframe_type": "S01_FIRST",
                "title": "accident discovered",
                "prompt": "Role 1 sees the stain. No product visible.",
                "reference_requirements": {
                    "use_product_reference": False,
                    "asset_ids": ["role_1", "living_room"],
                    "depends_on_keyframe_type": "",
                    "reason": "Only Role 1 and the room are visible.",
                },
            },
            {
                "keyframe_type": "S01_TAIL_SHARED_S02_FIRST",
                "title": "rescuer arrives",
                "prompt": "Role 2 crouches with product near source.",
                "reference_requirements": {
                    "use_product_reference": True,
                    "asset_ids": ["role_1", "role_2", "living_room"],
                    "depends_on_keyframe_type": "S01_FIRST",
                    "reason": "Role 2 and product enter; preserve first frame continuity.",
                },
            },
            {
                "keyframe_type": "S02_TAIL",
                "title": "result",
                "prompt": "Clean result with all visible roles.",
                "reference_requirements": {
                    "use_product_reference": True,
                    "asset_ids": [role["role_id"] for role in roles] + ["living_room"],
                    "depends_on_keyframe_type": "S01_TAIL_SHARED_S02_FIRST",
                    "reason": "Final result shows the full group and product.",
                },
            },
        ],
        "videos": [
            {
                "clip_type": "S01",
                "title": "accident beat",
                "first_keyframe_type": "S01_FIRST",
                "last_keyframe_type": "S01_TAIL_SHARED_S02_FIRST",
                "prompt": "Move from discovery to rescue entry.",
                "duration_sec": 8,
            },
            {
                "clip_type": "S02",
                "title": "resolution beat",
                "first_keyframe_type": "S01_TAIL_SHARED_S02_FIRST",
                "last_keyframe_type": "S02_TAIL",
                "prompt": "Use product and reveal clean result.",
                "duration_sec": 8,
            },
        ],
    }


class MultiRoleFirstLastTests(unittest.TestCase):
    def setUp(self):
        self._auto_review_patcher = patch.object(multi_role, "auto_review_enabled", return_value=False)
        self._auto_review_patcher.start()

    def tearDown(self):
        self._auto_review_patcher.stop()

    def test_auto_advance_reference_review_triggers_keyframes_for_first_version(self):
        updates = []
        with patch.object(multi_role, "TABLE_MULTI_ROLE_FIRST_LAST", "tbl_multi"), \
             patch.object(multi_role, "auto_review_enabled", return_value=True) as enabled, \
             patch.object(multi_role, "advance_reference_review", return_value={"status": "advanced"}) as advance, \
             patch.object(multi_role, "safe_update_record", side_effect=lambda token, table, rid, fields: updates.append((rid, fields))), \
             patch.object(multi_role, "filter_existing_fields", side_effect=lambda token, table, fields: fields):
            result = multi_role.maybe_auto_advance_reference_review(
                "token",
                "asset_rec",
                {"参考图版本": 1},
                file_token="ft_ref",
            )

        self.assertEqual(result["status"], "auto_approved")
        enabled.assert_called_once_with("token", stage_name=multi_role.AUTO_REVIEW_STAGE_NAME)
        self.assertIn(("asset_rec", {"参考图审核状态": "通过", "错误信息": ""}), updates)
        advance.assert_called_once_with("asset_rec")

    def test_auto_advance_reference_review_skips_regeneration_version(self):
        with patch.object(multi_role, "auto_review_enabled", return_value=True), \
             patch.object(multi_role, "safe_update_record") as updater, \
             patch.object(multi_role, "advance_reference_review") as advance:
            result = multi_role.maybe_auto_advance_reference_review(
                "token",
                "asset_rec",
                {"参考图版本": 2},
                file_token="ft_ref",
            )

        self.assertEqual(result["status"], "manual_regeneration")
        updater.assert_not_called()
        advance.assert_not_called()

    def test_auto_advance_keyframe_review_triggers_downstream_for_first_version(self):
        updates = []
        with patch.object(multi_role, "TABLE_MULTI_ROLE_FIRST_LAST", "tbl_multi"), \
             patch.object(multi_role, "auto_review_enabled", return_value=True) as enabled, \
             patch.object(multi_role, "advance_keyframe_review", return_value={"status": "advanced"}) as advance, \
             patch.object(multi_role, "safe_update_record", side_effect=lambda token, table, rid, fields: updates.append((rid, fields))), \
             patch.object(multi_role, "filter_existing_fields", side_effect=lambda token, table, fields: fields):
            result = multi_role.maybe_auto_advance_keyframe_review(
                "token",
                "keyframe_rec",
                {"关键帧版本": 1},
                file_token="ft_keyframe",
            )

        self.assertEqual(result["status"], "auto_approved")
        enabled.assert_called_once_with("token", stage_name=multi_role.AUTO_REVIEW_STAGE_NAME)
        self.assertIn(("keyframe_rec", {"关键帧审核状态": "通过", "错误信息": ""}), updates)
        advance.assert_called_once_with("keyframe_rec")

    def test_auto_advance_keyframe_review_skips_regeneration_version(self):
        with patch.object(multi_role, "auto_review_enabled", return_value=True), \
             patch.object(multi_role, "safe_update_record") as updater, \
             patch.object(multi_role, "advance_keyframe_review") as advance:
            result = multi_role.maybe_auto_advance_keyframe_review(
                "token",
                "keyframe_rec",
                {"关键帧版本": 2},
                file_token="ft_keyframe",
            )

        self.assertEqual(result["status"], "manual_regeneration")
        updater.assert_not_called()
        advance.assert_not_called()

    def test_auto_advance_keyframe_review_reapproves_regeneration_when_history_allows(self):
        updates = []
        history = json.dumps([{
            "stage": "keyframe_image",
            "previous_keyframe_review_status": "已触发下游",
            "auto_reapprove_after_regen": True,
        }])
        with patch.object(multi_role, "TABLE_MULTI_ROLE_FIRST_LAST", "tbl_multi"), \
             patch.object(multi_role, "auto_review_enabled", return_value=True) as enabled, \
             patch.object(multi_role, "advance_keyframe_review", return_value={"status": "advanced"}) as advance, \
             patch.object(multi_role, "safe_update_record", side_effect=lambda token, table, rid, fields: updates.append((rid, fields))), \
             patch.object(multi_role, "filter_existing_fields", side_effect=lambda token, table, fields: fields):
            result = multi_role.maybe_auto_advance_keyframe_review(
                "token",
                "keyframe_rec",
                {"关键帧版本": 2, "历史生成记录JSON": history},
                file_token="ft_keyframe",
            )

        self.assertEqual(result["status"], "auto_reapproved")
        enabled.assert_called_once_with("token", stage_name=multi_role.AUTO_REVIEW_STAGE_NAME)
        self.assertIn(("keyframe_rec", {"关键帧审核状态": "通过", "错误信息": ""}), updates)
        advance.assert_called_once_with("keyframe_rec")

    def test_list_multi_role_records_for_parent_filters_parent_and_deprecated_records(self):
        response = {
            "data": {
                "fields": ["任务名称", "记录类型", "父任务记录ID", "记录状态", "关键帧类型"],
                "record_id_list": ["asset_keep", "asset_other", "asset_deprecated"],
                "data": [
                    ["asset keep", ["参考资产"], "parent_a", ["有效"], None],
                    ["asset other", ["参考资产"], "parent_b", ["有效"], None],
                    ["asset deprecated", ["参考资产"], "parent_a", ["已废弃"], None],
                ],
                "has_more": False,
            }
        }

        with patch.object(multi_role, "safe_request", return_value=response) as request:
            records = multi_role.list_multi_role_records_for_parent("token", "parent_a")

        self.assertEqual([rec["record_id"] for rec in records], ["asset_keep"])
        self.assertEqual(records[0]["fields"]["任务名称"], "asset keep")
        self.assertEqual(records[0]["fields"]["父任务记录ID"], "parent_a")
        self.assertEqual(records[0]["fields"]["记录类型"], ["参考资产"])
        request.assert_called_once()

    def test_parse_prompt_requires_english_video_prompts_and_preserves_thai(self):
        prompt = multi_role.build_parse_prompt(
            {"产品名称": "uootapet", "目标时长秒": 8},
            "动作：主人对准沙发尿渍喷洒。台词：ไม่ต้องตกใจ",
        )

        self.assertIn("translate Chinese visual/action directions into English", prompt)
        self.assertIn("preserve Thai dialogue exactly", prompt)
        self.assertIn("videos[].prompt must not contain Chinese or CJK text", prompt)
        self.assertIn("ไม่ต้องตกใจ", prompt)

    def test_table_definition_contains_independent_record_types_and_regen_fields(self):
        field_names = [field["name"] for field in create_table.MULTI_ROLE_FIRST_LAST_FIELDS]
        for name in [
            "记录类型",
            "输入脚本",
            "资产ID",
            "参考图操作",
            "参考图版本",
            "关键帧类型",
            "需要产品参考图",
            "参考资产ID列表",
            "依赖关键帧类型",
            "参考图清单JSON",
            "原始请求JSON",
            "关键帧操作",
            "关键帧版本",
            "视频片段类型",
            "视频操作",
            "视频版本",
            "参考图画面尺寸",
            "参考图画面比例",
            "关键帧画面尺寸",
            "关键帧画面比例",
            "视频画面尺寸",
            "视频画面比例",
        ]:
            self.assertIn(name, field_names)
        record_type_options = next(field for field in create_table.MULTI_ROLE_FIRST_LAST_FIELDS if field["name"] == "记录类型")["options"]
        self.assertEqual([item["name"] for item in record_type_options], ["母任务", "参考资产", "关键帧", "视频片段"])
        self.assertEqual(create_table.TABLE_DEFINITION["key"], "multi_role_first_last")

    def test_default_parse_prompt_constrains_human_reference_images_to_front_facing_white_background(self):
        prompt = multi_role.DEFAULT_PARSE_PROMPT

        for phrase in [
            "single person",
            "front-facing",
            "front-facing upper-body",
            "full unobstructed face visible",
            "pure white background",
            "no side profile",
            "one angle",
            "no multi-view",
            "no contact sheet",
            "UGC smartphone",
            "natural skin texture",
            "not studio",
        ]:
            self.assertIn(phrase, prompt)

    def test_human_reference_image_prompt_is_wrapped_before_rendering(self):
        prompt = multi_role.build_reference_image_generation_prompt({
            "参考类型": "human",
            "参考提示词": "Thai renter, worried expression, blue shirt",
        })

        for phrase in [
            "pure white background",
            "front-facing upper-body",
            "full unobstructed face visible",
            "no side profile",
            "no multi-view",
            "no contact sheet",
        ]:
            self.assertIn(phrase, prompt)
        self.assertIn("Thai renter, worried expression, blue shirt", prompt)

    def test_default_parse_prompt_requires_dynamic_environment_problem_anchor(self):
        prompt = multi_role.DEFAULT_PARSE_PROMPT

        for phrase in [
            "根据脚本判断",
            "不能默认套用尿渍",
            "不能默认套用虫害",
            "不得编造事故点",
            "直接给图片模型使用",
        ]:
            self.assertIn(phrase, prompt)

    def test_multi_role_views_are_split_by_workflow_stage(self):
        views = create_table.TABLE_DEFINITION["views"]

        self.assertEqual(list(views.keys()), [
            "01-母任务入口",
            "02-参考图确认",
            "03-关键帧审核",
            "04-视频片段结果",
            "90-有效记录总览",
            "98-失败处理",
            "高级AI参数",
            "99-排错",
            "99-全字段系统视图",
            "00-已废弃记录",
        ])
        self.assertNotIn("01-用户入口", views)
        self.assertNotIn("04-视频结果", views)
        self.assertNotIn("记录类型", views["01-母任务入口"])
        self.assertIn("记录类型", views["90-有效记录总览"])
        for field_name in ["参考图操作", "关键帧操作", "视频操作"]:
            for view_name, visible_fields in views.items():
                if view_name in {"99-排错", "99-全字段系统视图"}:
                    continue
                self.assertNotIn(field_name, visible_fields)
            self.assertIn(field_name, views["99-排错"])
        for name in ["参考图画面尺寸", "参考图画面比例"]:
            self.assertIn(name, views["02-参考图确认"])
        for name in ["关键帧画面尺寸", "关键帧画面比例"]:
            self.assertIn(name, views["03-关键帧审核"])
        for name in ["视频画面尺寸", "视频画面比例"]:
            self.assertIn(name, views["04-视频片段结果"])
        self.assertNotIn("视频AI模型", views["04-视频片段结果"])
        self.assertNotIn("视频AI参数JSON", views["04-视频片段结果"])
        self.assertLess(views["04-视频片段结果"].index("视频版本"), views["04-视频片段结果"].index("视频通道"))
        self.assertLess(views["04-视频片段结果"].index("视频生成模型"), views["04-视频片段结果"].index("视频生成状态"))
        self.assertNotIn("视频AI模型", views["高级AI参数"])
        self.assertNotIn("视频AI参数JSON", views["高级AI参数"])
        for name in [
            "参考图画面尺寸",
            "参考图画面比例",
            "关键帧画面尺寸",
            "关键帧画面比例",
            "视频画面尺寸",
            "视频画面比例",
        ]:
            self.assertIn(name, views["高级AI参数"])
        self.assertIn("视频通道", views["高级AI参数"])
        self.assertIn("视频生成模型", views["高级AI参数"])
        self.assertIn("视频任务ID", views["98-失败处理"])
        self.assertIn("历史生成记录JSON", views["99-排错"])
        self.assertIn("视频生成模型", views["99-排错"])
        self.assertNotIn("视频AI模型", views["99-排错"])
        self.assertIn("视频AI参数JSON", views["99-排错"])
        self.assertEqual(views["99-全字段系统视图"], [field["name"] for field in create_table.MULTI_ROLE_FIRST_LAST_FIELDS])

    def test_video_channel_options_include_aitgenne(self):
        self.assertEqual([item["name"] for item in create_table.VIDEO_CHANNEL_OPTIONS], ["OTU", "AIHubMix", "Aitgenne"])
        self.assertEqual(multi_role.video_channel_for_provider("Aitgenne"), "Aitgenne")

    def test_multi_role_view_filters_match_record_types(self):
        filters = create_table.VIEW_FILTERS

        self.assertEqual(filters["01-母任务入口"]["conditions"], [
            ["记录类型", "intersects", ["母任务"]],
            ["记录状态", "intersects", ["有效"]],
        ])
        self.assertEqual(filters["02-参考图确认"]["conditions"][0], ["记录类型", "intersects", ["参考资产"]])
        self.assertEqual(filters["03-关键帧审核"]["conditions"][0], ["记录类型", "intersects", ["关键帧"]])
        self.assertEqual(filters["04-视频片段结果"]["conditions"][0], ["记录类型", "intersects", ["视频片段"]])
        self.assertEqual(filters["00-已废弃记录"]["conditions"], [["记录状态", "intersects", ["已废弃"]]])
        self.assertEqual(filters["99-排错"], {"conditions": []})

    def test_apply_view_filters_submits_all_known_filter_configs(self):
        view_ids = {name: f"viw_{idx}" for idx, name in enumerate(create_table.VIEW_FILTERS, start=1)}

        with patch.object(create_table, "list_views", return_value=view_ids), \
             patch.object(create_table, "run_json", return_value={}) as run_json:
            result = create_table.apply_view_filters("base", "tbl")

        self.assertEqual(result, {"applied": len(create_table.VIEW_FILTERS), "skipped": 0})
        submitted = [call.args[0] for call in run_json.call_args_list]
        self.assertEqual(len(submitted), len(create_table.VIEW_FILTERS))
        self.assertTrue(all("+view-set-filter" in args for args in submitted))

    def test_apply_view_filters_retries_feishu_rate_limit(self):
        first_view_name = next(iter(create_table.VIEW_FILTERS))

        with patch.object(create_table, "VIEW_FILTERS", {first_view_name: create_table.VIEW_FILTERS[first_view_name]}), \
             patch.object(create_table, "list_views", return_value={first_view_name: "viw_1"}), \
             patch.object(create_table, "time") as fake_time, \
             patch.object(create_table, "run_json", side_effect=[RuntimeError("800004135 limited"), {}]) as run_json:
            result = create_table.apply_view_filters("base", "tbl")

        self.assertEqual(result, {"applied": 1, "skipped": 0})
        self.assertEqual(run_json.call_count, 2)
        fake_time.sleep.assert_called_once_with(2)

    def test_image_parameters_prefer_record_fields_over_json_and_config(self):
        cfg = {"size": "1024x1024", "aspect_ratio": "1:1", "params": '{"size":"1280x720","aspect_ratio":"16:9"}'}

        result = multi_role.resolve_media_dimensions(
            {"参考图画面尺寸": "720x1280", "参考图画面比例": "9:16", "参考图AI参数JSON": '{"size":"1080x1920","aspect_ratio":"9:16"}'},
            "参考图",
            cfg,
            default_size="1024x1024",
            default_aspect_ratio="1:1",
        )

        self.assertEqual(result, {"size": "720x1280", "aspect_ratio": "9:16"})

    def test_normalize_plan_supports_dynamic_role_counts_and_per_frame_references(self):
        payload = multi_role.normalize_plan_payload(sample_plan(role_count=5))
        self.assertEqual(len(payload["roles"]), 5)
        first_refs = payload["keyframes"][0]["reference_requirements"]
        shared_refs = payload["keyframes"][1]["reference_requirements"]
        tail_refs = payload["keyframes"][2]["reference_requirements"]
        self.assertFalse(first_refs["use_product_reference"])
        self.assertEqual(first_refs["asset_ids"], ["role_1", "living_room"])
        self.assertTrue(shared_refs["use_product_reference"])
        self.assertEqual(shared_refs["depends_on_keyframe_type"], "S01_FIRST")
        self.assertIn("role_5", tail_refs["asset_ids"])

    def test_normalize_plan_forces_product_reference_when_keyframe_shows_product(self):
        plan = sample_plan()
        plan["keyframes"][0]["prompt"] = "Role 1 holds the branded spray bottle next to the stained sofa."
        plan["keyframes"][0]["reference_requirements"]["use_product_reference"] = False
        plan["keyframes"][0]["reference_requirements"]["reason"] = "The product bottle is visible in the first hook frame."

        payload = multi_role.normalize_plan_payload(plan)

        first_refs = payload["keyframes"][0]["reference_requirements"]
        self.assertTrue(first_refs["use_product_reference"])

    def test_normalize_plan_enforces_keyframe_dependency_chain(self):
        plan = sample_plan()
        plan["keyframes"][1]["reference_requirements"]["depends_on_keyframe_type"] = ""
        plan["keyframes"][2]["reference_requirements"]["depends_on_keyframe_type"] = ""

        payload = multi_role.normalize_plan_payload(plan)

        deps = {
            frame["keyframe_type"]: frame["reference_requirements"]["depends_on_keyframe_type"]
            for frame in payload["keyframes"]
        }
        self.assertEqual(deps["S01_FIRST"], "")
        self.assertEqual(deps["S01_TAIL_SHARED_S02_FIRST"], "S01_FIRST")
        self.assertEqual(deps["S02_TAIL"], "S01_TAIL_SHARED_S02_FIRST")

    def test_parse_task_unified_route_uses_prefixed_model_provider(self):
        fields = {
            "记录类型": "母任务",
            "输入脚本": "0-8s multi role hook",
            "使用统一AI路由": "是",
            "拆解AI模型": "Aitgenne / gpt-5.5",
        }
        config_records = [
            {"fields": {"环节": "统一AI路由启用状态", "模型名称": "指定记录启用"}},
            {"fields": {"AI供应商": "Aitgenne", "API 代理地址": "https://api.aitgenne.com", "API Key": "sk-aitgenne"}},
        ]

        with patch.object(multi_role, "ensure_multi_role_table"), \
             patch.object(multi_role, "get_feishu_token", return_value="token"), \
             patch.object(multi_role, "safe_get_record", return_value=fields), \
             patch.object(multi_role, "safe_list_records", return_value=config_records), \
             patch.object(multi_role, "get_stage_config", return_value=("cfg", {
                 "provider": "AIHubMix",
                 "model": "gemini-3.1-pro-preview",
                 "api_key": "sk-aihubmix",
                 "api_base": "https://aihubmix.com/gemini",
                 "call_type": "Gemini 原生 SDK",
                 "prompt": "configured parse prompt",
             })):
            result = multi_role.parse_task("recParent", dry_run=True)

        route = result["unified_ai_route"]
        self.assertEqual(route["provider"], "Aitgenne")
        self.assertEqual(route["call_type"], "OpenAI兼容 chat/completions")
        self.assertEqual(route["endpoint"], "https://api.aitgenne.com/v1/chat/completions")

    def test_parse_task_real_unified_call_uses_prefixed_route(self):
        fields = {
            "记录类型": "母任务",
            "输入脚本": "0-8s multi role hook",
            "使用统一AI路由": "是",
            "拆解AI模型": "Aitgenne / gpt-5.5",
        }
        config_records = [
            {"fields": {"环节": "统一AI路由启用状态", "模型名称": "指定记录启用"}},
            {"fields": {"AI供应商": "Aitgenne", "API 代理地址": "https://api.aitgenne.com", "API Key": "sk-aitgenne"}},
        ]

        with patch.object(multi_role, "ensure_multi_role_table"), \
             patch.object(multi_role, "get_feishu_token", return_value="token"), \
             patch.object(multi_role, "safe_get_record", return_value=fields), \
             patch.object(multi_role, "safe_list_records", return_value=config_records), \
             patch.object(multi_role, "get_stage_config", return_value=("cfg", {
                 "provider": "AIHubMix",
                 "model": "gemini-3.1-pro-preview",
                 "api_key": "sk-aihubmix",
                 "api_base": "https://aihubmix.com/gemini",
                 "call_type": "Gemini 原生 SDK",
                 "prompt": "configured parse prompt",
             })), \
             patch.object(multi_role.ai_routing, "call_text_model", return_value=type("Result", (), {"text": json.dumps(sample_plan())})()) as call_text, \
             patch.object(multi_role, "safe_update_record"), \
             patch.object(multi_role, "filter_existing_fields", side_effect=lambda token, table, f: f), \
             patch.object(multi_role, "list_multi_role_records_for_parent", return_value=[]), \
             patch.object(multi_role, "deprecate_existing_children", return_value=0), \
             patch.object(multi_role, "create_records", return_value=8):
            result = multi_role.parse_task("recParent")

        route = call_text.call_args.args[0]
        self.assertEqual(result["status"], "success")
        self.assertEqual(route.provider, "Aitgenne")
        self.assertEqual(route.call_type, "OpenAI兼容 chat/completions")
        self.assertEqual(route.api_base, "https://api.aitgenne.com")
        self.assertEqual(route.api_key, "sk-aitgenne")

    def test_parse_task_reports_gemini_prompt_block_instead_of_empty_text(self):
        fields = {
            "记录类型": "母任务",
            "输入脚本": "0-8s multi role hook",
        }
        response = SimpleNamespace(
            text="",
            prompt_feedback=SimpleNamespace(
                block_reason="PROHIBITED_CONTENT",
                block_reason_message="The prompt is blocked due to prohibited contents",
            ),
        )
        model = Mock()
        model.generate_content.return_value = response
        client = SimpleNamespace(models=model)

        with patch.object(multi_role, "ensure_multi_role_table"), \
             patch.object(multi_role, "get_feishu_token", return_value="token"), \
             patch.object(multi_role, "safe_get_record", return_value=fields), \
             patch.object(multi_role, "safe_list_records", return_value=[]), \
             patch.object(multi_role, "get_stage_config", return_value=("cfg", {
                 "model": "gemini-3.1-pro-preview",
                 "api_key": "sk-aihubmix",
                 "api_base": "https://aihubmix.com/gemini",
                 "prompt": "configured parse prompt",
             })), \
             patch.object(multi_role.genai, "Client", return_value=client), \
             patch.object(multi_role, "safe_update_record"), \
             patch.object(multi_role, "filter_existing_fields", side_effect=lambda token, table, f: f), \
             self.assertRaisesRegex(RuntimeError, "PROHIBITED_CONTENT"):
            multi_role.parse_task("recParent")

    def test_multi_role_media_summary_rejects_reference_video_model(self):
        config_records = [
            {"fields": {"环节": "统一AI路由启用状态", "模型名称": "指定记录启用"}},
            {"fields": {"AI供应商": "Aitgenne", "API 代理地址": "https://api.aitgenne.com", "API Key": "sk-aitgenne"}},
        ]

        with patch.object(multi_role, "safe_list_records", return_value=config_records):
            with self.assertRaisesRegex(ValueError, "首尾帧视频模型不支持参考图视频模型"):
                multi_role.maybe_unified_media_summary(
                    "token",
                    {"使用统一AI路由": "是", "视频生成模型": "Aitgenne / happyhorse-1.0-r2v"},
                    {"provider": "OTU", "api_key": "sk-otu", "api_base": "https://otuapi.com", "model": "veo_3_1-fast-fl"},
                    capability="视频",
                    task_type="首尾帧图生视频",
                    model="Aitgenne / happyhorse-1.0-r2v",
                    slot_name="视频",
                    prompt="video prompt",
                    params={"size": "720x1280", "aspect_ratio": "9:16"},
                    reference_count=2,
                )

    def test_build_child_records_creates_assets_keyframes_and_video_clips(self):
        records = multi_role.build_child_records("parent", {"任务名称": "Hook", "目标时长秒": 8}, sample_plan(role_count=4), batch_id="batch1")
        by_type = {}
        for item in records:
            by_type.setdefault(item["fields"]["记录类型"], []).append(item["fields"])
        self.assertEqual(len(by_type["参考资产"]), 5)
        self.assertEqual(len(by_type["关键帧"]), 3)
        self.assertEqual(len(by_type["视频片段"]), 2)
        role_asset = next(row for row in by_type["参考资产"] if row["资产ID"] == "role_1")
        self.assertEqual(role_asset["参考提示词"], "visual 1")
        first = next(row for row in by_type["关键帧"] if row["关键帧类型"] == "S01_FIRST")
        self.assertEqual(first["需要产品参考图"], "否")
        self.assertEqual(first["参考资产ID列表"], "role_1,living_room")
        self.assertEqual(first["关键帧生成状态"], "不触发")
        shared = next(row for row in by_type["关键帧"] if row["关键帧类型"] == "S01_TAIL_SHARED_S02_FIRST")
        self.assertEqual(shared["需要产品参考图"], "是")
        self.assertEqual(shared["依赖关键帧类型"], "S01_FIRST")
        for item in records:
            self.assertEqual(item["fields"]["使用统一AI路由"], "是")

    def test_video_clip_defaults_fill_video_channel(self):
        records = [{"fields": {
            "记录类型": multi_role.VIDEO_RECORD_TYPE,
            "视频通道": "AIHubMix",
            "视频生成模型": f"OTU / {multi_role.DEFAULT_OTU_MODEL}",
        }}]

        with patch.object(multi_role, "apply_task_default_to_fields", side_effect=lambda token, fields, **kwargs: dict(fields)) as apply_default:
            multi_role.apply_child_default_models("token", records)

        video_call = next(
            call for call in apply_default.call_args_list
            if call.kwargs.get("stage") == "视频片段生成默认"
        )
        self.assertEqual(video_call.kwargs["channel_field"], "视频通道")

    def test_normalize_plan_filters_product_asset_and_keeps_product_reference_flag(self):
        payload = sample_plan(role_count=3)
        payload["assets"].append({
            "asset_id": "product_ref",
            "asset_type": "object",
            "asset_name": "Pet deodorizer product reference image",
            "prompt": "Use the uploaded product reference image for the exact spray bottle packaging.",
            "source_role_ids": [],
        })
        payload["keyframes"][1]["reference_requirements"]["asset_ids"].append("product_ref")
        payload["keyframes"][1]["reference_requirements"]["use_product_reference"] = False
        payload["keyframes"][1]["reference_requirements"]["reason"] = "The product bottle is visible."
        payload["keyframes"][2]["reference_requirements"]["asset_ids"].append("product_ref")

        normalized = multi_role.normalize_plan_payload(payload)

        self.assertNotIn("product_ref", {asset["asset_id"] for asset in normalized["assets"]})
        shared_refs = normalized["keyframes"][1]["reference_requirements"]
        tail_refs = normalized["keyframes"][2]["reference_requirements"]
        self.assertTrue(shared_refs["use_product_reference"])
        self.assertTrue(tail_refs["use_product_reference"])
        self.assertNotIn("product_ref", shared_refs["asset_ids"])
        self.assertNotIn("product_ref", tail_refs["asset_ids"])

        records = multi_role.build_child_records("parent", {"任务名称": "Hook", "目标时长秒": 8}, normalized, batch_id="batch1")
        asset_ids = [
            item["fields"]["资产ID"]
            for item in records
            if item["fields"]["记录类型"] == "参考资产"
        ]
        self.assertNotIn("product_ref", asset_ids)
        shared = next(item["fields"] for item in records if item["fields"].get("关键帧类型") == "S01_TAIL_SHARED_S02_FIRST")
        self.assertEqual(shared["需要产品参考图"], "是")
        self.assertNotIn("product_ref", shared["参考资产ID列表"])

    def test_normalize_plan_filters_non_product_object_asset_without_product_reference(self):
        payload = sample_plan(role_count=3)
        payload["assets"].append({
            "asset_id": "white_cloth",
            "asset_type": "object",
            "asset_name": "White cleaning cloth prop",
            "prompt": "A plain white cloth prop used for wiping, isolated on a neutral background.",
            "source_role_ids": [],
        })
        payload["keyframes"][0]["reference_requirements"]["asset_ids"].append("white_cloth")
        payload["keyframes"][0]["reference_requirements"]["use_product_reference"] = False
        payload["keyframes"][0]["reference_requirements"]["reason"] = "The white cloth is a simple prop described in the keyframe prompt."

        normalized = multi_role.normalize_plan_payload(payload)

        self.assertNotIn("white_cloth", {asset["asset_id"] for asset in normalized["assets"]})
        first_refs = normalized["keyframes"][0]["reference_requirements"]
        self.assertFalse(first_refs["use_product_reference"])
        self.assertNotIn("white_cloth", first_refs["asset_ids"])

        records = multi_role.build_child_records("parent", {"任务名称": "Hook", "目标时长秒": 8}, normalized, batch_id="batch1")
        first = next(item["fields"] for item in records if item["fields"].get("关键帧类型") == "S01_FIRST")
        self.assertEqual(first["需要产品参考图"], "否")
        self.assertNotIn("white_cloth", first["参考资产ID列表"])

    def test_environment_asset_prompt_removes_character_product_and_pet_positives(self):
        payload = sample_plan(role_count=4)
        payload["assets"][-1]["prompt"] = "\n".join([
            "Vertical 9:16 Bangkok rental living room with beige sofa and rug.",
            "Keep the space open enough for a young Thai woman, landlord, roommate, small dog, and spray bottle. Use natural colors, no cinematic color grading.",
            "Restrictions: no people, no pets, no product bottle.",
        ])
        normalized = multi_role.normalize_plan_payload(payload)
        env_prompt = next(asset["prompt"] for asset in normalized["assets"] if asset["asset_type"] == "environment")
        self.assertIn("EMPTY ENVIRONMENT REFERENCE PLATE ONLY", env_prompt)
        self.assertIn("Bangkok rental living room", env_prompt)
        self.assertNotIn("young Thai woman", env_prompt)
        self.assertNotIn("landlord", env_prompt)
        self.assertNotIn("small dog", env_prompt)
        self.assertNotIn("spray bottle", env_prompt)
        self.assertIn("no people", env_prompt)
        self.assertEqual(multi_role.sanitize_environment_prompt(env_prompt).count("EMPTY ENVIRONMENT REFERENCE PLATE ONLY"), 1)
        duplicated = f"{env_prompt}\nScene details to keep:\nEMPTY ENVIRONMENT REFERENCE PLATE ONLY."
        self.assertEqual(multi_role.sanitize_environment_prompt(duplicated).count("EMPTY ENVIRONMENT REFERENCE PLATE ONLY"), 1)

    def test_environment_asset_prompt_is_direct_image_prompt_without_script_meta(self):
        payload = sample_plan(role_count=4)
        payload["assets"][-1]["prompt"] = "\n".join([
            "Vertical 9:16 Bangkok rental living room with beige sofa and rug.",
            "No people, no pets, no product bottle.",
        ])
        normalized = multi_role.normalize_plan_payload(payload)
        env_prompt = next(asset["prompt"] for asset in normalized["assets"] if asset["asset_type"] == "environment")
        lowered = env_prompt.lower()

        self.assertIn("Scene details:", env_prompt)
        self.assertNotIn("Scene details to keep:", env_prompt)
        for forbidden in ["source script", "script-defined", "if one exists", "when present in the script"]:
            self.assertNotIn(forbidden, lowered)

    def test_environment_asset_prompt_preserves_problem_anchor_without_pet_subject(self):
        payload = sample_plan(role_count=4)
        payload["assets"][-1]["prompt"] = "\n".join([
            "Vertical 9:16 Bangkok rental living room with beige sofa and rug.",
            "A cat urine stain on the left sofa corner, visible wet patch on gray fabric.",
            "No people, no pets, no product bottle.",
        ])
        normalized = multi_role.normalize_plan_payload(payload)
        env_prompt = next(asset["prompt"] for asset in normalized["assets"] if asset["asset_type"] == "environment")

        self.assertIn("urine stain", env_prompt)
        self.assertIn("left sofa corner", env_prompt)
        self.assertIn("visible wet patch", env_prompt)
        self.assertNotIn("cat urine", env_prompt)
        self.assertNotRegex(env_prompt.lower(), r"\bcat\b")

    def test_child_records_inherit_next_versions_from_previous_children(self):
        payload = sample_plan(role_count=3)
        normalized = multi_role.normalize_plan_payload(payload)
        old_records = [
            {"record_id": "old_asset", "fields": {"记录类型": "参考资产", "父任务记录ID": "parent", "资产ID": "role_1", "参考图版本": 2}},
            {"record_id": "old_keyframe", "fields": {"记录类型": "关键帧", "父任务记录ID": "parent", "关键帧类型": "S01_FIRST", "关键帧版本": 4}},
            {"record_id": "old_video", "fields": {"记录类型": "视频片段", "父任务记录ID": "parent", "视频片段类型": "S02", "视频版本": 3}},
        ]

        version_seeds = multi_role.collect_child_version_seeds(old_records, "parent")
        records = multi_role.build_child_records(
            "parent",
            {"任务名称": "Hook", "目标时长秒": 8},
            normalized,
            batch_id="batch2",
            version_seeds=version_seeds,
        )

        by_asset = {item["fields"].get("资产ID"): item["fields"] for item in records if item["fields"].get("记录类型") == "参考资产"}
        by_keyframe = {item["fields"].get("关键帧类型"): item["fields"] for item in records if item["fields"].get("记录类型") == "关键帧"}
        by_video = {item["fields"].get("视频片段类型"): item["fields"] for item in records if item["fields"].get("记录类型") == "视频片段"}

        self.assertEqual(by_asset["role_1"]["参考图版本"], 3)
        self.assertEqual(by_keyframe["S01_FIRST"]["关键帧版本"], 5)
        self.assertEqual(by_video["S02"]["视频版本"], 4)
        self.assertEqual(by_video["S01"]["视频版本"], 1)

    def test_keyframe_reference_collection_requires_urls_for_non_primary_references(self):
        fields = {
            "记录类型": "关键帧",
            "关键帧类型": "S01_TAIL_SHARED_S02_FIRST",
            "父任务记录ID": "parent",
            "需要产品参考图": "是",
            "参考资产ID列表": "role_1,living_room",
            "依赖关键帧类型": "S01_FIRST",
        }
        parent_fields = {"关联产品记录": [{"record_ids": ["recProduct"]}]}
        all_records = [
            {"record_id": "kf_first", "fields": {"记录类型": "关键帧", "父任务记录ID": "parent", "关键帧类型": "S01_FIRST", "关键帧审核状态": "已触发下游", "关键帧图file_token": "ft_first"}},
            {"record_id": "asset_role", "fields": {"记录类型": "参考资产", "父任务记录ID": "parent", "资产ID": "role_1", "参考类型": "human", "参考图审核状态": "已触发下游", "参考图file_token": "ft_role"}},
            {"record_id": "asset_env", "fields": {"记录类型": "参考资产", "父任务记录ID": "parent", "资产ID": "living_room", "参考类型": "environment", "参考图审核状态": "已触发下游", "参考图file_token": "ft_env"}},
        ]

        with tempfile.TemporaryDirectory() as tmp:
            refs = multi_role.collect_keyframe_references(
                "token",
                fields,
                parent_fields,
                all_records,
                Path(tmp),
                product_getter=lambda token, value: ("recProduct", {"产品图片": [{"file_token": "ft_product"}]}),
                download_fn=lambda token, file_token, save_path: Path(save_path),
                url_getter=lambda token, file_token: f"https://tmp.test/{file_token}.png",
            )

        roles = [item["role"] for item in refs]
        self.assertEqual(roles, ["base_keyframe:S01_FIRST", "product:1", "human:role_1", "environment:living_room"])
        self.assertEqual([item["url"] for item in refs], [
            "https://tmp.test/ft_first.png",
            "https://tmp.test/ft_product.png",
            "https://tmp.test/ft_role.png",
            "https://tmp.test/ft_env.png",
        ])

    def test_keyframe_reference_collection_prefers_latest_attachment_over_cached_token(self):
        fields = {
            "记录类型": "关键帧",
            "关键帧类型": "S01_TAIL_SHARED_S02_FIRST",
            "父任务记录ID": "parent",
            "需要产品参考图": "否",
            "参考资产ID列表": "role_1",
            "依赖关键帧类型": "S01_FIRST",
        }
        all_records = [
            {"record_id": "kf_first", "fields": {
                "记录类型": "关键帧",
                "父任务记录ID": "parent",
                "关键帧类型": "S01_FIRST",
                "关键帧审核状态": "已触发下游",
                "关键帧图file_token": "old_keyframe",
                "关键帧图": [{"file_token": "older_keyframe"}, {"file_token": "new_keyframe"}],
            }},
            {"record_id": "asset_role", "fields": {
                "记录类型": "参考资产",
                "父任务记录ID": "parent",
                "资产ID": "role_1",
                "参考类型": "human",
                "参考图审核状态": "已触发下游",
                "参考图file_token": "old_role",
                "参考图": [{"file_token": "older_role"}, {"file_token": "new_role"}],
            }},
        ]

        downloaded_tokens = []
        with tempfile.TemporaryDirectory() as tmp:
            refs = multi_role.collect_keyframe_references(
                "token",
                fields,
                {},
                all_records,
                Path(tmp),
                download_fn=lambda token, file_token, save_path: downloaded_tokens.append(file_token) or Path(save_path),
                url_getter=lambda token, file_token: f"https://tmp.test/{file_token}.png",
            )

        self.assertEqual([item["file_token"] for item in refs], ["new_keyframe", "new_role"])
        self.assertEqual(downloaded_tokens, ["new_keyframe", "new_role"])

    def test_video_dependencies_accept_already_advanced_keyframes(self):
        records = [
            {"record_id": "kf_first", "fields": {"记录类型": "关键帧", "父任务记录ID": "parent", "关键帧类型": "S01_FIRST", "关键帧审核状态": "已触发下游", "关键帧图file_token": "ft_first"}},
        ]
        result = multi_role._find_keyframe_for_clip(records, "parent", "S01_FIRST")
        self.assertEqual(result["file_token"], "ft_first")

    def test_video_dependencies_prefer_latest_keyframe_attachment(self):
        records = [
            {"record_id": "kf_first", "fields": {
                "记录类型": "关键帧",
                "父任务记录ID": "parent",
                "关键帧类型": "S01_FIRST",
                "关键帧审核状态": "已触发下游",
                "关键帧图file_token": "old_first",
                "关键帧图": [{"file_token": "older_first"}, {"file_token": "new_first"}],
            }},
        ]
        result = multi_role._find_keyframe_for_clip(records, "parent", "S01_FIRST")
        self.assertEqual(result["file_token"], "new_first")

    def test_video_clip_waits_when_keyframe_dependency_is_not_ready(self):
        fields = {
            "记录类型": "视频片段",
            "记录状态": "有效",
            "视频提示词": "animate between frames",
            "视频版本": 3,
            "父任务记录ID": "parent",
            "首关键帧类型": "S01_TAIL_SHARED_S02_FIRST",
            "尾关键帧类型": "S02_TAIL",
        }
        records = [
            {"record_id": "kf_shared", "fields": {
                "记录类型": "关键帧",
                "记录状态": "有效",
                "父任务记录ID": "parent",
                "关键帧类型": "S01_TAIL_SHARED_S02_FIRST",
                "关键帧审核状态": "已触发下游",
                "关键帧图file_token": "ft_shared",
            }},
            {"record_id": "kf_tail", "fields": {
                "记录类型": "关键帧",
                "记录状态": "有效",
                "父任务记录ID": "parent",
                "关键帧类型": "S02_TAIL",
                "关键帧审核状态": "待确认",
                "关键帧图file_token": "",
            }},
        ]
        updates = []
        with patch.object(multi_role, "TABLE_MULTI_ROLE_FIRST_LAST", "tbl_multi"), \
             patch.object(multi_role, "get_feishu_token", return_value="token"), \
             patch.object(multi_role, "safe_get_record", return_value=fields), \
             patch.object(multi_role, "apply_task_default_to_record", return_value=fields), \
             patch.object(multi_role, "list_multi_role_records_for_parent", return_value=records), \
             patch.object(multi_role, "get_stage_config", side_effect=AssertionError("should wait before model config")), \
             patch.object(multi_role, "safe_update_record", side_effect=lambda token, table, rid, update: updates.append(update)), \
             patch.object(multi_role, "filter_existing_fields", side_effect=lambda token, table, update: update):
            result = multi_role.render_video_clip("clip_rec")

        self.assertEqual(result["status"], "waiting_dependency")
        self.assertEqual(updates[0]["视频生成状态"], "不触发")
        self.assertIn("等待视频依赖关键帧通过后自动触发", updates[0]["视频错误信息"])

    def test_keyframe_reference_collection_fails_when_reference_url_missing(self):
        fields = {"记录类型": "关键帧", "父任务记录ID": "parent", "需要产品参考图": "是", "参考资产ID列表": ""}
        parent_fields = {"关联产品记录": [{"record_ids": ["recProduct"]}]}
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "参考图 URL"):
                multi_role.collect_keyframe_references(
                    "token",
                    fields,
                    parent_fields,
                    [],
                    Path(tmp),
                    product_getter=lambda token, value: ("recProduct", {"产品图片": [{"file_token": "ft_product"}]}),
                    download_fn=lambda token, file_token, save_path: Path(save_path),
                    url_getter=lambda token, file_token: "",
                )

    def test_reference_image_resumes_existing_task_id(self):
        fields = {
            "记录类型": "参考资产",
            "记录状态": "有效",
            "参考提示词": "make a renter reference",
            "参考图版本": 1,
            "参考图任务ID": "task_existing",
        }
        updates = []
        with patch.object(multi_role, "TABLE_MULTI_ROLE_FIRST_LAST", "tbl_multi"), \
             patch.object(multi_role, "get_feishu_token", return_value="token"), \
             patch.object(multi_role, "safe_get_record", return_value=fields), \
             patch.object(multi_role, "get_stage_config", return_value=("cfg", {"api_base": "https://otuapi.com", "api_key": "key"})), \
             patch.object(multi_role, "submit_otu_image_task") as submit, \
             patch.object(multi_role, "poll_otu_image_task", return_value={"url": "https://example.com/out.png"}) as poll, \
             patch.object(multi_role, "extract_otu_result_url", return_value="https://example.com/out.png"), \
             patch.object(multi_role, "download_otu_image_result"), \
             patch.object(multi_role, "upload_image_to_feishu", return_value="file_token"), \
             patch.object(multi_role, "safe_update_record", side_effect=lambda token, table, rid, fields: updates.append(fields)), \
             patch.object(multi_role, "filter_existing_fields", side_effect=lambda token, table, fields: fields):
            result = multi_role.render_reference_image("asset_rec")
        submit.assert_not_called()
        poll.assert_called_once()
        self.assertEqual(result["task_id"], "task_existing")
        self.assertTrue(any(update.get("参考图生成状态") == "成功" for update in updates))

    def test_reference_image_rejects_object_asset_type(self):
        fields = {
            "记录类型": "参考资产",
            "记录状态": "有效",
            "参考类型": "object",
            "参考提示词": "Use the uploaded product reference image for exact packaging.",
            "参考图版本": 1,
        }
        with patch.object(multi_role, "TABLE_MULTI_ROLE_FIRST_LAST", "tbl_multi"), \
             patch.object(multi_role, "get_feishu_token", return_value="token"), \
             patch.object(multi_role, "safe_get_record", return_value=fields), \
             patch.object(multi_role, "apply_task_default_to_record", return_value=fields), \
             patch.object(multi_role, "submit_otu_image_task") as submit:
            with self.assertRaisesRegex(ValueError, "参考类型不支持"):
                multi_role.render_reference_image("asset_rec")
        submit.assert_not_called()

    def test_keyframe_image_resumes_existing_task_id(self):
        fields = {
            "记录类型": "关键帧",
            "记录状态": "有效",
            "关键帧提示词": "make the keyframe",
            "关键帧版本": 1,
            "关键帧任务ID": "task_existing",
            "父任务记录ID": "parent",
        }
        refs = [{"role": "human:role_1", "url": "https://tmp.test/role.png", "path": "/tmp/role.png", "file_token": "ft_role"}]
        updates = []
        with patch.object(multi_role, "TABLE_MULTI_ROLE_FIRST_LAST", "tbl_multi"), \
             patch.object(multi_role, "get_feishu_token", return_value="token"), \
             patch.object(multi_role, "safe_get_record", side_effect=[fields, {}]), \
             patch.object(multi_role, "list_multi_role_records_for_parent", return_value=[]), \
             patch.object(multi_role, "collect_keyframe_references", return_value=refs), \
             patch.object(multi_role, "get_stage_config", return_value=("cfg", {"api_base": "https://otuapi.com", "api_key": "key"})), \
             patch.object(multi_role, "submit_otu_image_task") as submit, \
             patch.object(multi_role, "poll_otu_image_task", return_value={"url": "https://example.com/out.png"}) as poll, \
             patch.object(multi_role, "extract_otu_result_url", return_value="https://example.com/out.png"), \
             patch.object(multi_role, "download_otu_image_result"), \
             patch.object(multi_role, "upload_image_to_feishu", return_value="file_token"), \
             patch.object(multi_role, "safe_update_record", side_effect=lambda token, table, rid, update: updates.append(update)), \
             patch.object(multi_role, "filter_existing_fields", side_effect=lambda token, table, update: update):
            result = multi_role.render_keyframe_image("keyframe_rec")
        submit.assert_not_called()
        poll.assert_called_once()
        self.assertEqual(result["task_id"], "task_existing")
        self.assertTrue(any(update.get("关键帧生成状态") == "成功" for update in updates))

    def test_keyframe_image_passes_non_primary_references_to_image_generation(self):
        fields = {
            "记录类型": "关键帧",
            "记录状态": "有效",
            "关键帧提示词": "show the product rescue moment",
            "关键帧版本": 1,
            "父任务记录ID": "parent",
            "关键帧AI模型": "Aitgenne / gpt-image-2",
        }
        refs = [
            {"role": "product:1", "url": "https://tmp.test/product.png", "path": "/tmp/product.png", "file_token": "ft_product", "primary": False},
            {"role": "human:role_1", "url": "https://tmp.test/role.png", "path": "/tmp/role.png", "file_token": "ft_role", "primary": False},
        ]
        image_result = SimpleNamespace(
            task_id="",
            submit_body={"ok": True},
            result_body={"ok": True},
            request_summary={"reference_count": 2},
        )
        with patch.object(multi_role, "TABLE_MULTI_ROLE_FIRST_LAST", "tbl_multi"), \
             patch.object(multi_role, "ensure_multi_role_table"), \
             patch.object(multi_role, "get_feishu_token", return_value="token"), \
             patch.object(multi_role, "safe_get_record", side_effect=[fields, {}]), \
             patch.object(multi_role, "safe_list_records", return_value=[]), \
             patch.object(multi_role, "list_multi_role_records_for_parent", return_value=[]), \
             patch.object(multi_role, "collect_keyframe_references", return_value=refs), \
             patch.object(multi_role, "get_stage_config", return_value=("cfg", {"api_base": "https://api.aitgenne.com", "api_key": "key", "model": "gpt-image-2"})), \
             patch.object(multi_role, "maybe_unified_media_summary", return_value=None), \
             patch.object(multi_role, "run_image_generation", return_value=image_result) as run_image, \
             patch.object(multi_role, "upload_image_to_feishu", return_value="file_token"), \
             patch.object(multi_role, "safe_update_record"), \
             patch.object(multi_role, "filter_existing_fields", side_effect=lambda token, table, update: update):
            multi_role.render_keyframe_image("keyframe_rec")

        kwargs = run_image.call_args.kwargs
        self.assertEqual(kwargs["input_mode"], "image-to-image")
        self.assertEqual(kwargs["image_path"], "")
        self.assertEqual(kwargs["reference_image_paths"], ["/tmp/product.png", "/tmp/role.png"])

    def test_keyframe_image_aitgenne_dependent_frame_sends_only_product_references(self):
        fields = {
            "记录类型": "关键帧",
            "记录状态": "有效",
            "关键帧提示词": "continue from first frame with product",
            "关键帧版本": 1,
            "父任务记录ID": "parent",
            "关键帧AI模型": "Aitgenne / gpt-image-2",
        }
        refs = [
            {"role": "base_keyframe:S01_FIRST", "url": "https://tmp.test/base.png", "path": "/tmp/base.png", "file_token": "ft_base", "primary": True},
            {"role": "product:1", "url": "https://tmp.test/product.png", "path": "/tmp/product.png", "file_token": "ft_product", "primary": False},
            {"role": "environment:room", "url": "https://tmp.test/room.png", "path": "/tmp/room.png", "file_token": "ft_room", "primary": False},
        ]
        image_result = SimpleNamespace(
            task_id="",
            submit_body={"ok": True},
            result_body={"ok": True},
            request_summary={"reference_count": 3},
        )
        with patch.object(multi_role, "TABLE_MULTI_ROLE_FIRST_LAST", "tbl_multi"), \
             patch.object(multi_role, "ensure_multi_role_table"), \
             patch.object(multi_role, "get_feishu_token", return_value="token"), \
             patch.object(multi_role, "safe_get_record", side_effect=[fields, {}]), \
             patch.object(multi_role, "safe_list_records", return_value=[]), \
             patch.object(multi_role, "list_multi_role_records_for_parent", return_value=[]), \
             patch.object(multi_role, "collect_keyframe_references", return_value=refs), \
             patch.object(multi_role, "get_stage_config", return_value=("cfg", {"api_base": "https://api.aitgenne.com", "api_key": "key", "model": "gpt-image-2"})), \
             patch.object(multi_role, "maybe_unified_media_summary", return_value=None), \
             patch.object(multi_role, "run_image_generation", return_value=image_result) as run_image, \
             patch.object(multi_role, "upload_image_to_feishu", return_value="file_token"), \
             patch.object(multi_role, "safe_update_record"), \
             patch.object(multi_role, "filter_existing_fields", side_effect=lambda token, table, update: update):
            multi_role.render_keyframe_image("keyframe_rec")

        kwargs = run_image.call_args.kwargs
        self.assertEqual(kwargs["input_mode"], "image-to-image")
        self.assertEqual(kwargs["image_path"], "/tmp/base.png")
        self.assertEqual(kwargs["reference_image_paths"], ["/tmp/product.png"])
        self.assertIn("previous keyframe image as the only source of truth", run_image.call_args.args[1])

    def test_keyframe_image_non_aitgenne_dependent_frame_keeps_other_references(self):
        fields = {
            "记录类型": "关键帧",
            "记录状态": "有效",
            "关键帧提示词": "continue from first frame with product",
            "关键帧版本": 1,
            "父任务记录ID": "parent",
            "关键帧AI模型": "OTU / gpt-image-2",
        }
        refs = [
            {"role": "base_keyframe:S01_FIRST", "url": "https://tmp.test/base.png", "path": "/tmp/base.png", "file_token": "ft_base", "primary": True},
            {"role": "product:1", "url": "https://tmp.test/product.png", "path": "/tmp/product.png", "file_token": "ft_product", "primary": False},
            {"role": "environment:room", "url": "https://tmp.test/room.png", "path": "/tmp/room.png", "file_token": "ft_room", "primary": False},
        ]
        image_result = SimpleNamespace(
            task_id="task_otu",
            submit_body={"ok": True},
            result_body={"ok": True},
            request_summary={"reference_count": 3},
        )
        with patch.object(multi_role, "TABLE_MULTI_ROLE_FIRST_LAST", "tbl_multi"), \
             patch.object(multi_role, "ensure_multi_role_table"), \
             patch.object(multi_role, "get_feishu_token", return_value="token"), \
             patch.object(multi_role, "safe_get_record", side_effect=[fields, {}]), \
             patch.object(multi_role, "list_multi_role_records_for_parent", return_value=[]), \
             patch.object(multi_role, "collect_keyframe_references", return_value=refs), \
             patch.object(multi_role, "get_stage_config", return_value=("cfg", {"api_base": "https://otuapi.com", "api_key": "key", "model": "gpt-image-2"})), \
             patch.object(multi_role, "maybe_unified_media_summary", return_value=None), \
             patch.object(multi_role, "run_image_generation", return_value=image_result) as run_image, \
             patch.object(multi_role, "upload_image_to_feishu", return_value="file_token"), \
             patch.object(multi_role, "safe_update_record"), \
             patch.object(multi_role, "filter_existing_fields", side_effect=lambda token, table, update: update):
            multi_role.render_keyframe_image("keyframe_rec")

        kwargs = run_image.call_args.kwargs
        self.assertEqual(kwargs["input_mode"], "image-to-image")
        self.assertEqual(kwargs["image_path"], "/tmp/base.png")
        self.assertEqual(kwargs["reference_image_paths"], ["/tmp/product.png", "/tmp/room.png"])

    def test_video_clip_resumes_existing_task_id(self):
        fields = {
            "记录类型": "视频片段",
            "记录状态": "有效",
            "视频提示词": "animate between frames",
            "视频版本": 2,
            "视频任务ID": "task_existing",
            "视频生成状态": "生成中",
            "父任务记录ID": "parent",
            "首关键帧类型": "S01_FIRST",
            "尾关键帧类型": "S02_TAIL",
            "目标时长秒": 5,
        }
        records = [
            {
                "record_id": "kf_first",
                "fields": {
                    "记录类型": "关键帧",
                    "记录状态": "有效",
                    "父任务记录ID": "parent",
                    "关键帧类型": "S01_FIRST",
                    "关键帧审核状态": "通过",
                    "关键帧图file_token": "ft_first",
                },
            },
            {
                "record_id": "kf_tail",
                "fields": {
                    "记录类型": "关键帧",
                    "记录状态": "有效",
                    "父任务记录ID": "parent",
                    "关键帧类型": "S02_TAIL",
                    "关键帧审核状态": "通过",
                    "关键帧图file_token": "ft_tail",
                },
            },
        ]
        updates = []
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(multi_role, "TABLE_MULTI_ROLE_FIRST_LAST", "tbl_multi"), \
             patch.object(multi_role, "get_feishu_token", return_value="token"), \
             patch.object(multi_role, "safe_get_record", return_value=fields), \
             patch.object(multi_role, "list_multi_role_records_for_parent", return_value=records), \
             patch.object(multi_role, "ensure_stage_work_dir", return_value=Path(tmp)), \
             patch.object(multi_role, "get_stage_config", return_value=("cfg", {"api_base": "https://otuapi.com", "api_key": "key", "model": "veo_3_1-fast-fl"})), \
             patch.object(multi_role, "get_table_field_types", return_value={}), \
             patch.object(multi_role, "submit_otu_video_task") as submit, \
             patch.object(multi_role, "download_feishu_media") as download_ref, \
             patch.object(multi_role, "poll_otu_video_task", return_value={"url": "https://example.com/out.mp4"}) as poll, \
             patch.object(multi_role, "extract_video_url", return_value="https://example.com/out.mp4"), \
             patch.object(multi_role, "download_video"), \
             patch.object(multi_role, "upload_video_to_feishu", return_value="file_token"), \
             patch.object(multi_role, "safe_update_record", side_effect=lambda token, table, rid, update: updates.append(update)), \
             patch.object(multi_role, "filter_existing_fields", side_effect=lambda token, table, update: update):
            result = multi_role.render_video_clip("clip_rec")
        submit.assert_not_called()
        download_ref.assert_not_called()
        poll.assert_called_once()
        self.assertEqual(result["task_id"], "task_existing")
        self.assertEqual(updates[0]["视频任务ID"], "task_existing")
        self.assertIn("恢复轮询已有 OTU 视频任务", updates[0]["视频错误信息"])
        self.assertTrue(any(update.get("视频生成状态") == "成功" for update in updates))

    def test_video_clip_resubmits_stale_task_id_when_not_running(self):
        fields = {
            "记录类型": "视频片段",
            "记录状态": "有效",
            "视频提示词": "animate between frames",
            "视频版本": 3,
            "视频任务ID": "task_stale",
            "视频生成状态": "待生成",
            "父任务记录ID": "parent",
            "首关键帧类型": "S01_FIRST",
            "尾关键帧类型": "S02_TAIL",
            "目标时长秒": 5,
        }
        records = [
            {
                "record_id": "kf_first",
                "fields": {
                    "记录类型": "关键帧",
                    "记录状态": "有效",
                    "父任务记录ID": "parent",
                    "关键帧类型": "S01_FIRST",
                    "关键帧审核状态": "通过",
                    "关键帧图file_token": "ft_first",
                },
            },
            {
                "record_id": "kf_tail",
                "fields": {
                    "记录类型": "关键帧",
                    "记录状态": "有效",
                    "父任务记录ID": "parent",
                    "关键帧类型": "S02_TAIL",
                    "关键帧审核状态": "通过",
                    "关键帧图file_token": "ft_tail",
                },
            },
        ]
        updates = []
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(multi_role, "TABLE_MULTI_ROLE_FIRST_LAST", "tbl_multi"), \
             patch.object(multi_role, "get_feishu_token", return_value="token"), \
             patch.object(multi_role, "safe_get_record", return_value=fields), \
             patch.object(multi_role, "list_multi_role_records_for_parent", return_value=records), \
             patch.object(multi_role, "ensure_stage_work_dir", return_value=Path(tmp)), \
             patch.object(multi_role, "get_stage_config", return_value=("cfg", {"api_base": "https://otuapi.com", "api_key": "key", "model": "veo_3_1-fast-fl"})), \
             patch.object(multi_role, "get_table_field_types", return_value={}), \
             patch.object(multi_role, "submit_otu_video_task", return_value=("task_new", {"id": "task_new"})) as submit, \
             patch.object(multi_role, "download_feishu_media", side_effect=lambda token, file_token, path: str(path)), \
             patch.object(multi_role, "poll_otu_video_task", return_value={"url": "https://example.com/out.mp4"}) as poll, \
             patch.object(multi_role, "extract_video_url", return_value="https://example.com/out.mp4"), \
             patch.object(multi_role, "download_video"), \
             patch.object(multi_role, "upload_video_to_feishu", return_value="file_token"), \
             patch.object(multi_role, "safe_update_record", side_effect=lambda token, table, rid, update: updates.append(update)), \
             patch.object(multi_role, "filter_existing_fields", side_effect=lambda token, table, update: update):
            result = multi_role.render_video_clip("clip_rec")

        submit.assert_called_once()
        poll.assert_called_once_with({"api_base": "https://otuapi.com", "api_key": "key", "model": "veo_3_1-fast-fl"}, "task_new")
        self.assertEqual(result["task_id"], "task_new")
        self.assertTrue(any(update.get("视频任务ID") == "" for update in updates))
        self.assertTrue(any(
            update.get("视频任务ID") == "task_new" and update.get("视频生成状态") == "生成中"
            for update in updates
        ))
        self.assertFalse(any(update.get("视频错误信息", "").startswith("恢复轮询已有") for update in updates))

    def test_video_clip_downloads_completed_task_content_when_result_has_no_url(self):
        fields = {
            "记录类型": "视频片段",
            "记录状态": "有效",
            "视频提示词": "animate between frames",
            "视频版本": 1,
            "视频任务ID": "task_done",
            "视频生成状态": "生成中",
            "视频生成模型": "OTU / veo_3_1-fast-fl",
            "父任务记录ID": "parent",
            "首关键帧类型": "S01_FIRST",
            "尾关键帧类型": "S02_TAIL",
            "目标时长秒": 5,
        }
        records = [
            {
                "record_id": "kf_first",
                "fields": {
                    "记录类型": "关键帧",
                    "记录状态": "有效",
                    "父任务记录ID": "parent",
                    "关键帧类型": "S01_FIRST",
                    "关键帧审核状态": "通过",
                    "关键帧图file_token": "ft_first",
                },
            },
            {
                "record_id": "kf_tail",
                "fields": {
                    "记录类型": "关键帧",
                    "记录状态": "有效",
                    "父任务记录ID": "parent",
                    "关键帧类型": "S02_TAIL",
                    "关键帧审核状态": "通过",
                    "关键帧图file_token": "ft_tail",
                },
            },
        ]
        updates = []
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(multi_role, "TABLE_MULTI_ROLE_FIRST_LAST", "tbl_multi"), \
             patch.object(multi_role, "get_feishu_token", return_value="token"), \
             patch.object(multi_role, "safe_get_record", return_value=fields), \
             patch.object(multi_role, "list_multi_role_records_for_parent", return_value=records), \
             patch.object(multi_role, "ensure_stage_work_dir", return_value=Path(tmp)), \
             patch.object(multi_role, "get_stage_config", return_value=("cfg", {"api_base": "https://otuapi.com", "api_key": "key", "model": "veo_3_1-fast-fl"})), \
             patch.object(multi_role, "get_table_field_types", return_value={"视频片段URL": 15}), \
             patch.object(multi_role, "poll_otu_video_task", return_value={"id": "task_done", "status": "completed"}), \
             patch.object(multi_role, "download_video") as downloader, \
             patch.object(multi_role, "upload_video_to_feishu", return_value="file_token"), \
             patch.object(multi_role, "safe_update_record", side_effect=lambda token, table, rid, update: updates.append(update)), \
             patch.object(multi_role, "filter_existing_fields", side_effect=lambda token, table, update: update):
            result = multi_role.render_video_clip("clip_rec")

        downloader.assert_called_once()
        self.assertEqual(downloader.call_args.args[0], "https://otuapi.com/v1/videos/task_done/content")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["video_url"], "https://otuapi.com/v1/videos/task_done/content")
        self.assertTrue(any(update.get("视频生成状态") == "成功" for update in updates))

    def test_video_clip_uses_record_video_generation_model_for_new_submit(self):
        fields = {
            "记录类型": "视频片段",
            "记录状态": "有效",
            "视频提示词": "animate between frames",
            "视频版本": 2,
            "视频任务ID": "",
            "视频生成模型": "OTU / veo_3_1-fl",
            "父任务记录ID": "parent",
            "首关键帧类型": "S01_FIRST",
            "尾关键帧类型": "S02_TAIL",
            "目标时长秒": 5,
        }
        records = [
            {
                "record_id": "kf_first",
                "fields": {
                    "记录类型": "关键帧",
                    "记录状态": "有效",
                    "父任务记录ID": "parent",
                    "关键帧类型": "S01_FIRST",
                    "关键帧审核状态": "通过",
                    "关键帧图file_token": "ft_first",
                },
            },
            {
                "record_id": "kf_tail",
                "fields": {
                    "记录类型": "关键帧",
                    "记录状态": "有效",
                    "父任务记录ID": "parent",
                    "关键帧类型": "S02_TAIL",
                    "关键帧审核状态": "通过",
                    "关键帧图file_token": "ft_tail",
                },
            },
        ]
        updates = []
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(multi_role, "TABLE_MULTI_ROLE_FIRST_LAST", "tbl_multi"), \
             patch.object(multi_role, "get_feishu_token", return_value="token"), \
             patch.object(multi_role, "safe_get_record", return_value=fields), \
             patch.object(multi_role, "list_multi_role_records_for_parent", return_value=records), \
             patch.object(multi_role, "ensure_stage_work_dir", return_value=Path(tmp)), \
             patch.object(multi_role, "get_stage_config", return_value=("cfg", {"api_base": "https://otuapi.com", "api_key": "key", "model": "veo_3_1-fast-fl"})), \
             patch.object(multi_role, "get_table_field_types", return_value={}), \
             patch.object(multi_role, "submit_otu_video_task", return_value=("task_new", {"id": "task_new"})) as submit, \
             patch.object(multi_role, "download_feishu_media", side_effect=lambda token, file_token, path: str(path)), \
             patch.object(multi_role, "poll_otu_video_task", return_value={"url": "https://example.com/out.mp4"}), \
             patch.object(multi_role, "extract_video_url", return_value="https://example.com/out.mp4"), \
             patch.object(multi_role, "download_video"), \
             patch.object(multi_role, "upload_video_to_feishu", return_value="file_token"), \
             patch.object(multi_role, "safe_update_record", side_effect=lambda token, table, rid, update: updates.append(update)), \
             patch.object(multi_role, "filter_existing_fields", side_effect=lambda token, table, update: update):
            result = multi_role.render_video_clip("clip_rec")

        submitted_cfg = submit.call_args.args[0]
        self.assertEqual(submitted_cfg["model"], "veo_3_1-fl")
        self.assertEqual(result["model"], "veo_3_1-fl")
        self.assertEqual(result["model_source"], "视频生成模型")
        self.assertTrue(any(update.get("视频生成模型") == "OTU / veo_3_1-fl" for update in updates))
        self.assertTrue(any(update.get("视频操作") == "不触发" for update in updates))

    def test_poll_otu_video_task_times_out_when_zero_progress_stalls_from_created_at(self):
        response = Mock()
        response.status_code = 200
        response.text = '{"status":"in_progress","progress":0,"created_at":0}'
        response.json.return_value = {"id": "task_stuck", "status": "in_progress", "progress": 0, "created_at": 0}
        times = iter([601, 601])

        with patch("tk_shot_video.requests.get", return_value=response), \
             self.assertRaisesRegex(TimeoutError, "progress=0") as caught:
            multi_role.poll_otu_video_task(
                {"api_base": "https://otuapi.com", "api_key": "sk-test"},
                "task_stuck",
                queued_zero_progress_timeout_seconds=600,
                max_poll_seconds=2400,
                now_fn=lambda: next(times),
                sleep_fn=lambda seconds: None,
            )

        payload = multi_role.build_error_payload(caught.exception, stage="tk_multi_role_first_last.py")
        self.assertEqual(payload["error_code"], "UPSTREAM_NETWORK")
        self.assertTrue(payload["retryable"])

    def test_poll_otu_video_task_total_timeout_is_retryable_upstream_network(self):
        response = Mock()
        response.status_code = 200
        response.text = '{"status":"in_progress","progress":30}'
        response.json.return_value = {"id": "task_slow", "status": "in_progress", "progress": 30}
        times = iter([0, 2401])

        with patch("tk_shot_video.requests.get", return_value=response), \
             self.assertRaisesRegex(TimeoutError, "任务超时") as caught:
            multi_role.poll_otu_video_task(
                {"api_base": "https://otuapi.com", "api_key": "sk-test"},
                "task_slow",
                max_poll_seconds=2400,
                now_fn=lambda: next(times),
                sleep_fn=lambda seconds: None,
            )

        payload = multi_role.build_error_payload(caught.exception, stage="tk_multi_role_first_last.py")
        self.assertEqual(payload["error_code"], "UPSTREAM_NETWORK")
        self.assertTrue(payload["retryable"])

    def test_poll_otu_video_task_returns_completed_body_for_content_download_fallback(self):
        response = Mock()
        response.status_code = 200
        response.text = '{"status":"completed"}'
        response.json.return_value = {"id": "task_done", "status": "completed"}
        times = iter([0, 0])

        with patch("tk_shot_video.requests.get", return_value=response):
            result = multi_role.poll_otu_video_task(
                {"api_base": "https://otuapi.com", "api_key": "sk-test"},
                "task_done",
                now_fn=lambda: next(times),
                sleep_fn=lambda seconds: None,
            )

        self.assertEqual(result["status"], "completed")

    def test_video_clip_uses_aitgenne_reference_video_for_happyhorse_model(self):
        fields = {
            "记录类型": "视频片段",
            "记录状态": "有效",
            "视频提示词": "animate between frames",
            "视频版本": 2,
            "视频任务ID": "",
            "视频生成模型": "Aitgenne / happyhorse-1.0-i2v",
            "父任务记录ID": "parent",
            "首关键帧类型": "S01_FIRST",
            "尾关键帧类型": "S02_TAIL",
            "目标时长秒": 5,
        }
        records = [
            {
                "record_id": "kf_first",
                "fields": {
                    "记录类型": "关键帧",
                    "记录状态": "有效",
                    "父任务记录ID": "parent",
                    "关键帧类型": "S01_FIRST",
                    "关键帧审核状态": "通过",
                    "关键帧图file_token": "ft_first",
                },
            },
            {
                "record_id": "kf_tail",
                "fields": {
                    "记录类型": "关键帧",
                    "记录状态": "有效",
                    "父任务记录ID": "parent",
                    "关键帧类型": "S02_TAIL",
                    "关键帧审核状态": "通过",
                    "关键帧图file_token": "ft_tail",
                },
            },
        ]
        route = multi_role.ai_routing.AiRoute(
            provider="Aitgenne",
            capability="视频",
            task_type="首尾帧视频",
            model="Aitgenne / happyhorse-1.0-i2v",
            api_base="https://api.aitgenne.com/v1",
            api_key="sk-aitgenne",
        )
        updates = []
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(multi_role, "TABLE_MULTI_ROLE_FIRST_LAST", "tbl_multi"), \
             patch.object(multi_role, "get_feishu_token", return_value="token"), \
             patch.object(multi_role, "safe_get_record", return_value=fields), \
             patch.object(multi_role, "list_multi_role_records_for_parent", return_value=records), \
             patch.object(multi_role, "ensure_stage_work_dir", return_value=Path(tmp)), \
             patch.object(multi_role, "get_stage_config", return_value=("cfg", {"api_base": "https://otuapi.com", "api_key": "key", "model": "veo_3_1-fast-fl"})), \
             patch.object(multi_role, "reference_video_route_for_model", return_value=route), \
             patch.object(multi_role, "get_table_field_types", return_value={}), \
             patch.object(multi_role, "submit_reference_video_task", return_value=("task_aitgenne", {"id": "task_aitgenne"})) as submit, \
             patch.object(multi_role, "poll_reference_video_task", return_value={"status": "completed", "video_url": "https://example.com/aitgenne.mp4"}) as poll, \
             patch.object(multi_role, "submit_otu_video_task") as otu_submitter, \
             patch.object(multi_role, "get_native_veo_client") as native_client_factory, \
             patch.object(multi_role, "call_native_veo_first_frame_task") as native_submitter, \
             patch.object(multi_role, "download_feishu_media", side_effect=lambda token, file_token, path: str(path)), \
             patch.object(multi_role, "get_tmp_download_url_for_attachment", side_effect=lambda token, file_token: f"https://x.test/{file_token}.png"), \
             patch.object(multi_role, "download_video"), \
             patch.object(multi_role, "upload_video_to_feishu", return_value="file_token"), \
             patch.object(multi_role, "safe_update_record", side_effect=lambda token, table, rid, update: updates.append(update)), \
             patch.object(multi_role, "filter_existing_fields", side_effect=lambda token, table, update: update):
            result = multi_role.render_video_clip("clip_rec")

        otu_submitter.assert_not_called()
        native_client_factory.assert_not_called()
        native_submitter.assert_not_called()
        submit.assert_called_once()
        self.assertEqual(submit.call_args.args[2], str(Path(tmp) / "clip_rec_S01_FIRST.png"))
        self.assertEqual(submit.call_args.args[3], str(Path(tmp) / "clip_rec_S02_TAIL.png"))
        self.assertEqual(submit.call_args.kwargs["reference_urls"], ["https://x.test/ft_first.png", "https://x.test/ft_tail.png"])
        poll.assert_called_once_with(route, "task_aitgenne")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["task_id"], "task_aitgenne")
        self.assertTrue(any(update.get("视频通道") == "Aitgenne" for update in updates))
        self.assertTrue(any("provider=Aitgenne model=happyhorse-1.0-i2v" in update.get("视频错误信息", "") for update in updates))

    def test_submit_aitgenne_reference_video_uses_input_media_json_schema(self):
        route = multi_role.ai_routing.AiRoute(
            provider="Aitgenne",
            capability="视频",
            task_type="首尾帧视频",
            model="Aitgenne / happyhorse-1.0-i2v",
            api_base="https://api.aitgenne.com/v1",
            api_key="sk-aitgenne",
        )
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"output": {"task_id": "task_aitgenne", "task_status": "PENDING"}}
        response.text = '{"id":"task_aitgenne"}'

        with tempfile.NamedTemporaryFile(suffix=".png") as first, tempfile.NamedTemporaryFile(suffix=".png") as last, \
             patch.object(multi_role.requests, "post", return_value=response) as post:
            task_id, body = multi_role.submit_reference_video_task(
                route,
                "video prompt",
                first.name,
                last.name,
                seconds="5",
                size="1080x1920",
                aspect_ratio="9:16",
                reference_urls=["https://x.test/first.png", "https://x.test/last.png"],
            )

        self.assertEqual(task_id, "task_aitgenne")
        self.assertEqual(body["output"]["task_status"], "PENDING")
        args, kwargs = post.call_args
        self.assertEqual(args[0], "https://api.aitgenne.com/alibailian/api/v1/services/aigc/video-generation/video-synthesis")
        self.assertNotIn("files", kwargs)
        self.assertEqual(kwargs["json"], {
            "model": "happyhorse-1.0-i2v",
            "input": {
                "prompt": "video prompt",
                "media": [
                    {"type": "first_frame", "url": "https://x.test/first.png"},
                ],
            },
            "parameters": {
                "resolution": "1080P",
                "duration": 5,
            },
        })

    def test_old_aitgenne_input_media_failure_task_is_not_resumed(self):
        fields = {
            "视频错误信息": (
                "Aitgenne 多角色视频生成失败: {'error': {'code': 'InvalidParameter', "
                "'message': \"Field required: input.media & Input should be '1080P' or '720P': parameters.resolution\"}}"
            )
        }

        self.assertFalse(multi_role.existing_video_task_matches_channel(
            fields,
            "Aitgenne",
            "Aitgenne / happyhorse-1.0-i2v",
            "task_old",
        ))

    def test_happyhorse_route_uses_exact_model_api_key(self):
        config_records = [
            {
                "fields": {
                    "AI供应商": "Aitgenne",
                    "模型名称": "Aitgenne / gpt-image-2",
                    "API 代理地址": "https://api.aitgenne.com/v1",
                    "API Key": "sk-image",
                }
            },
            {
                "fields": {
                    "AI供应商": "Aitgenne",
                    "模型名称": "Aitgenne / happyhorse-1.0-i2v",
                    "API 代理地址": "https://api.aitgenne.com/v1",
                    "API Key": "sk-happyhorse",
                }
            },
        ]

        with patch.object(multi_role, "TABLE_CONFIG", "tbl_config"), \
             patch.object(multi_role, "safe_list_records", return_value=config_records):
            route = multi_role.reference_video_route_for_model(
                "token",
                "Aitgenne",
                "Aitgenne / happyhorse-1.0-i2v",
                task_type="首尾帧视频",
                params={"size": "720x1280"},
            )

        self.assertEqual(route.api_key, "sk-happyhorse")
        self.assertEqual(route.api_base, "https://api.aitgenne.com/v1")

    def test_happyhorse_route_does_not_reuse_other_aitgenne_key(self):
        config_records = [
            {
                "fields": {
                    "AI供应商": "Aitgenne",
                    "模型名称": "Aitgenne / gpt-image-2",
                    "API 代理地址": "https://api.aitgenne.com/v1",
                    "API Key": "sk-image",
                }
            },
            {
                "fields": {
                    "AI供应商": "Aitgenne",
                    "模型名称": "Aitgenne / happyhorse-1.0-i2v",
                    "API 代理地址": "https://api.aitgenne.com/v1",
                    "API Key": "",
                }
            },
        ]

        with patch.object(multi_role, "TABLE_CONFIG", "tbl_config"), \
             patch.object(multi_role, "safe_list_records", return_value=config_records), \
             self.assertRaisesRegex(ValueError, "模型配置缺少 API Key: Aitgenne / happyhorse-1.0-i2v"):
            multi_role.reference_video_route_for_model(
                "token",
                "Aitgenne",
                "Aitgenne / happyhorse-1.0-i2v",
                task_type="首尾帧视频",
                params={},
            )

    def test_video_clip_uses_aihubmix_native_veo_when_generation_model_selects_aihubmix(self):
        fields = {
            "记录类型": "视频片段",
            "记录状态": "有效",
            "视频提示词": "animate between frames",
            "视频版本": 2,
            "视频任务ID": "",
            "视频生成模型": "AIHubMix / veo-3.1-fast-generate-preview",
            "父任务记录ID": "parent",
            "首关键帧类型": "S01_FIRST",
            "尾关键帧类型": "S02_TAIL",
            "目标时长秒": 5,
        }
        records = [
            {
                "record_id": "kf_first",
                "fields": {
                    "记录类型": "关键帧",
                    "记录状态": "有效",
                    "父任务记录ID": "parent",
                    "关键帧类型": "S01_FIRST",
                    "关键帧审核状态": "通过",
                    "关键帧图file_token": "ft_first",
                },
            },
            {
                "record_id": "kf_tail",
                "fields": {
                    "记录类型": "关键帧",
                    "记录状态": "有效",
                    "父任务记录ID": "parent",
                    "关键帧类型": "S02_TAIL",
                    "关键帧审核状态": "通过",
                    "关键帧图file_token": "ft_tail",
                },
            },
        ]
        operation = Mock()
        operation.name = "operations/op_multi_aihubmix"
        completed = Mock()
        generated_video = Mock()
        updates = []
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(multi_role, "TABLE_MULTI_ROLE_FIRST_LAST", "tbl_multi"), \
             patch.object(multi_role, "get_feishu_token", return_value="token"), \
             patch.object(multi_role, "safe_get_record", return_value=fields), \
             patch.object(multi_role, "list_multi_role_records_for_parent", return_value=records), \
             patch.object(multi_role, "ensure_stage_work_dir", return_value=Path(tmp)), \
             patch.object(multi_role, "get_stage_config", return_value=("cfg", {"api_base": "https://aihubmix.com/gemini", "api_key": "key", "model": "veo-3.1-fast-generate-preview"})), \
             patch.object(multi_role, "get_table_field_types", return_value={}), \
             patch.object(multi_role, "get_native_veo_client", return_value="client") as client_factory, \
             patch.object(multi_role, "call_native_veo_first_frame_task", return_value=operation) as native_submitter, \
             patch.object(multi_role, "poll_native_veo_operation", return_value=completed) as native_poller, \
             patch.object(multi_role, "extract_native_generated_video", return_value=generated_video), \
             patch.object(multi_role, "native_generated_video_uri", return_value="https://example.com/native.mp4"), \
             patch.object(multi_role, "download_native_veo_video", return_value="/tmp/video.mp4") as native_downloader, \
             patch.object(multi_role, "submit_otu_video_task") as otu_submitter, \
             patch.object(multi_role, "poll_otu_video_task") as otu_poller, \
             patch.object(multi_role, "download_feishu_media", side_effect=lambda token, file_token, path: str(path)), \
             patch.object(multi_role, "upload_video_to_feishu", return_value="file_token"), \
             patch.object(multi_role, "safe_update_record", side_effect=lambda token, table, rid, update: updates.append(update)), \
             patch.object(multi_role, "filter_existing_fields", side_effect=lambda token, table, update: update):
            result = multi_role.render_video_clip("clip_rec")

        otu_submitter.assert_not_called()
        otu_poller.assert_not_called()
        client_factory.assert_called_once()
        native_submitter.assert_called_once()
        self.assertEqual(native_submitter.call_args.args[0]["model"], "veo-3.1-fast-generate-preview")
        self.assertEqual(native_submitter.call_args.args[4], "720p")
        self.assertEqual(native_submitter.call_args.kwargs["last_frame_path"], str(Path(tmp) / "clip_rec_S02_TAIL.png"))
        native_poller.assert_called_once_with("client", operation)
        native_downloader.assert_called_once_with("client", generated_video, result["output_path"])
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["task_id"], "operations/op_multi_aihubmix")
        self.assertTrue(any(update.get("视频通道") == "AIHubMix" for update in updates))
        self.assertTrue(any(update.get("视频生成模型") == "AIHubMix / veo-3.1-fast-generate-preview" for update in updates))
        self.assertTrue(any(update.get("视频操作") == "不触发" for update in updates))

    def test_video_clip_preserves_url_and_local_path_before_upload_failure(self):
        fields = {
            "记录类型": "视频片段",
            "记录状态": "有效",
            "视频提示词": "animate between frames",
            "视频版本": 1,
            "视频任务ID": "task_existing",
            "视频生成状态": "生成中",
            "视频生成模型": "OTU / veo_3_1-fast-fl",
            "父任务记录ID": "parent",
            "首关键帧类型": "S01_FIRST",
            "尾关键帧类型": "S02_TAIL",
            "目标时长秒": 5,
        }
        records = [
            {
                "record_id": "kf_first",
                "fields": {
                    "记录类型": "关键帧",
                    "记录状态": "有效",
                    "父任务记录ID": "parent",
                    "关键帧类型": "S01_FIRST",
                    "关键帧审核状态": "通过",
                    "关键帧图file_token": "ft_first",
                },
            },
            {
                "record_id": "kf_tail",
                "fields": {
                    "记录类型": "关键帧",
                    "记录状态": "有效",
                    "父任务记录ID": "parent",
                    "关键帧类型": "S02_TAIL",
                    "关键帧审核状态": "通过",
                    "关键帧图file_token": "ft_tail",
                },
            },
        ]
        updates = []
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(multi_role, "TABLE_MULTI_ROLE_FIRST_LAST", "tbl_multi"), \
             patch.object(multi_role, "get_feishu_token", return_value="token"), \
             patch.object(multi_role, "safe_get_record", return_value=fields), \
             patch.object(multi_role, "list_multi_role_records_for_parent", return_value=records), \
             patch.object(multi_role, "ensure_stage_work_dir", return_value=Path(tmp)), \
             patch.object(multi_role, "get_stage_config", return_value=("cfg", {"api_base": "https://otuapi.com", "api_key": "key", "model": "veo_3_1-fast-fl"})), \
             patch.object(multi_role, "get_table_field_types", return_value={"视频片段URL": 15}), \
             patch.object(multi_role, "poll_otu_video_task", return_value={"url": "https://example.com/out.mp4"}), \
             patch.object(multi_role, "extract_video_url", return_value="https://example.com/out.mp4"), \
             patch.object(multi_role, "download_video"), \
             patch.object(multi_role, "upload_video_to_feishu", side_effect=RuntimeError("飞书视频上传失败: params error.")), \
             patch.object(multi_role, "safe_update_record", side_effect=lambda token, table, rid, update: updates.append(update)), \
             patch.object(multi_role, "filter_existing_fields", side_effect=lambda token, table, update: update):
            with self.assertRaisesRegex(RuntimeError, "params error"):
                multi_role.render_video_clip("clip_rec")

        repair_updates = [update for update in updates if update.get("视频本地路径") and update.get("视频片段URL")]
        self.assertTrue(repair_updates)
        self.assertEqual(repair_updates[-1]["视频任务ID"], "task_existing")
        self.assertEqual(repair_updates[-1]["视频生成状态"], "生成中")
        self.assertIn("等待飞书上传", repair_updates[-1]["视频错误信息"])

    def test_video_clip_skips_writeback_when_current_task_id_changed(self):
        fields = {
            "记录类型": "视频片段",
            "记录状态": "有效",
            "视频提示词": "animate between frames",
            "视频版本": 3,
            "视频任务ID": "task_old",
            "视频生成状态": "生成中",
            "视频生成模型": "OTU / veo_3_1-fast-fl",
            "父任务记录ID": "parent",
            "首关键帧类型": "S01_FIRST",
            "尾关键帧类型": "S02_TAIL",
            "目标时长秒": 5,
        }
        records = [
            {
                "record_id": "kf_first",
                "fields": {
                    "记录类型": "关键帧",
                    "记录状态": "有效",
                    "父任务记录ID": "parent",
                    "关键帧类型": "S01_FIRST",
                    "关键帧审核状态": "通过",
                    "关键帧图file_token": "ft_first",
                },
            },
            {
                "record_id": "kf_tail",
                "fields": {
                    "记录类型": "关键帧",
                    "记录状态": "有效",
                    "父任务记录ID": "parent",
                    "关键帧类型": "S02_TAIL",
                    "关键帧审核状态": "通过",
                    "关键帧图file_token": "ft_tail",
                },
            },
        ]
        updates = []
        latest_after_download = {**fields, "视频版本": 4, "视频任务ID": "task_new"}
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(multi_role, "TABLE_MULTI_ROLE_FIRST_LAST", "tbl_multi"), \
             patch.object(multi_role, "get_feishu_token", return_value="token"), \
             patch.object(multi_role, "safe_get_record", side_effect=[fields, latest_after_download]), \
             patch.object(multi_role, "list_multi_role_records_for_parent", return_value=records), \
             patch.object(multi_role, "ensure_stage_work_dir", return_value=Path(tmp)), \
             patch.object(multi_role, "get_stage_config", return_value=("cfg", {"api_base": "https://otuapi.com", "api_key": "key", "model": "veo_3_1-fast-fl"})), \
             patch.object(multi_role, "get_table_field_types", return_value={"视频片段URL": 15}), \
             patch.object(multi_role, "poll_otu_video_task", return_value={"url": "https://example.com/out.mp4"}), \
             patch.object(multi_role, "extract_video_url", return_value="https://example.com/out.mp4"), \
             patch.object(multi_role, "download_video"), \
             patch.object(multi_role, "upload_video_to_feishu") as uploader, \
             patch.object(multi_role, "safe_update_record", side_effect=lambda token, table, rid, update: updates.append(update)), \
             patch.object(multi_role, "filter_existing_fields", side_effect=lambda token, table, update: update):
            result = multi_role.render_video_clip("clip_rec")

        uploader.assert_not_called()
        self.assertEqual(result["status"], "stale_writeback_skipped")
        self.assertEqual(result["current_task_id"], "task_new")
        self.assertFalse(any(update.get("视频生成状态") == "成功" for update in updates))

    def test_regeneration_resets_current_output_and_increments_version(self):
        updates = []
        with patch.object(multi_role, "TABLE_MULTI_ROLE_FIRST_LAST", "tbl_multi"), \
             patch.object(multi_role, "get_feishu_token", return_value="token"), \
             patch.object(multi_role, "safe_get_record", return_value={"记录类型": "关键帧", "记录状态": "有效", "关键帧版本": 2, "关键帧审核状态": "已触发下游"}), \
             patch.object(multi_role, "list_multi_role_records_for_parent", return_value=[]), \
             patch.object(multi_role, "safe_update_record", side_effect=lambda token, table, rid, fields: updates.append(fields)), \
             patch.object(multi_role, "filter_existing_fields", side_effect=lambda token, table, fields: fields):
            result = multi_role.request_keyframe_regeneration("rec_keyframe")
        self.assertEqual(result["version"], 3)
        self.assertEqual(updates[0]["关键帧版本"], 3)
        self.assertEqual(updates[0]["关键帧生成状态"], "待生成")
        self.assertEqual(updates[0]["关键帧图"], [])
        self.assertEqual(updates[0]["关键帧任务ID"], "")
        history = json.loads(updates[0]["历史生成记录JSON"])
        self.assertEqual(history[-1]["previous_keyframe_review_status"], "已触发下游")
        self.assertTrue(history[-1]["auto_reapprove_after_regen"])

    def test_keyframe_regeneration_waits_when_dependency_is_regenerating(self):
        fields = {
            "记录类型": "关键帧",
            "记录状态": "有效",
            "父任务记录ID": "parent",
            "关键帧类型": "S02_TAIL",
            "依赖关键帧类型": "S01_TAIL_SHARED_S02_FIRST",
            "关键帧版本": 1,
            "关键帧审核状态": "已触发下游",
        }
        records = [
            {"record_id": "kf_shared", "fields": {
                "记录类型": "关键帧",
                "记录状态": "有效",
                "父任务记录ID": "parent",
                "关键帧类型": "S01_TAIL_SHARED_S02_FIRST",
                "关键帧审核状态": "待确认",
                "关键帧操作": "重新生成关键帧图",
                "关键帧图file_token": "",
            }},
        ]
        updates = []
        with patch.object(multi_role, "TABLE_MULTI_ROLE_FIRST_LAST", "tbl_multi"), \
             patch.object(multi_role, "get_feishu_token", return_value="token"), \
             patch.object(multi_role, "safe_get_record", return_value=fields), \
             patch.object(multi_role, "list_multi_role_records_for_parent", return_value=records), \
             patch.object(multi_role, "safe_update_record", side_effect=lambda token, table, rid, update: updates.append(update)), \
             patch.object(multi_role, "filter_existing_fields", side_effect=lambda token, table, update: update):
            result = multi_role.request_keyframe_regeneration("kf_tail")

        self.assertEqual(result["status"], "waiting_dependency")
        self.assertEqual(updates[0]["关键帧生成状态"], "不触发")
        self.assertIn("等待依赖关键帧通过后自动触发", updates[0]["关键帧错误信息"])

    def test_keyframe_image_waits_when_dependency_is_not_ready(self):
        fields = {
            "记录类型": "关键帧",
            "记录状态": "有效",
            "关键帧提示词": "continue scene",
            "关键帧版本": 2,
            "父任务记录ID": "parent",
            "依赖关键帧类型": "S01_TAIL_SHARED_S02_FIRST",
            "参考资产ID列表": "",
        }
        records = [
            {"record_id": "kf_shared", "fields": {
                "记录类型": "关键帧",
                "记录状态": "有效",
                "父任务记录ID": "parent",
                "关键帧类型": "S01_TAIL_SHARED_S02_FIRST",
                "关键帧审核状态": "待确认",
                "关键帧图file_token": "",
            }},
        ]
        updates = []
        with patch.object(multi_role, "TABLE_MULTI_ROLE_FIRST_LAST", "tbl_multi"), \
             patch.object(multi_role, "get_feishu_token", return_value="token"), \
             patch.object(multi_role, "safe_get_record", side_effect=[fields, {}]), \
             patch.object(multi_role, "apply_task_default_to_record", return_value=fields), \
             patch.object(multi_role, "list_multi_role_records_for_parent", return_value=records), \
             patch.object(multi_role, "collect_keyframe_references") as collect_refs, \
             patch.object(multi_role, "get_stage_config", return_value=("cfg", {"api_base": "https://otuapi.com", "api_key": "key"})), \
             patch.object(multi_role, "run_image_generation", side_effect=AssertionError("should wait before generation")), \
             patch.object(multi_role, "safe_update_record", side_effect=lambda token, table, rid, update: updates.append(update)), \
             patch.object(multi_role, "filter_existing_fields", side_effect=lambda token, table, update: update):
            result = multi_role.render_keyframe_image("kf_tail")

        self.assertEqual(result["status"], "waiting_dependency")
        self.assertEqual(updates[0]["关键帧生成状态"], "不触发")
        self.assertIn("等待依赖关键帧通过后自动触发", updates[0]["关键帧错误信息"])
        collect_refs.assert_not_called()

    def test_video_regeneration_waits_when_keyframe_dependency_is_not_ready(self):
        fields = {
            "记录类型": "视频片段",
            "记录状态": "有效",
            "父任务记录ID": "parent",
            "首关键帧类型": "S01_TAIL_SHARED_S02_FIRST",
            "尾关键帧类型": "S02_TAIL",
            "视频版本": 2,
        }
        records = [
            {"record_id": "kf_shared", "fields": {
                "记录类型": "关键帧",
                "记录状态": "有效",
                "父任务记录ID": "parent",
                "关键帧类型": "S01_TAIL_SHARED_S02_FIRST",
                "关键帧审核状态": "已触发下游",
                "关键帧图file_token": "ft_shared",
            }},
            {"record_id": "kf_tail", "fields": {
                "记录类型": "关键帧",
                "记录状态": "有效",
                "父任务记录ID": "parent",
                "关键帧类型": "S02_TAIL",
                "关键帧审核状态": "待确认",
                "关键帧图file_token": "",
            }},
        ]
        updates = []
        with patch.object(multi_role, "TABLE_MULTI_ROLE_FIRST_LAST", "tbl_multi"), \
             patch.object(multi_role, "get_feishu_token", return_value="token"), \
             patch.object(multi_role, "safe_get_record", return_value=fields), \
             patch.object(multi_role, "list_multi_role_records_for_parent", return_value=records), \
             patch.object(multi_role, "safe_update_record", side_effect=lambda token, table, rid, update: updates.append(update)), \
             patch.object(multi_role, "filter_existing_fields", side_effect=lambda token, table, update: update):
            result = multi_role.request_video_regeneration("clip_rec")

        self.assertEqual(result["status"], "waiting_dependency")
        self.assertEqual(updates[0]["视频生成状态"], "不触发")
        self.assertIn("等待视频依赖关键帧通过后自动触发", updates[0]["视频错误信息"])

    def test_reference_review_advances_ready_keyframes(self):
        records = [
            {"record_id": "asset_role", "fields": {"记录类型": "参考资产", "父任务记录ID": "parent", "资产ID": "role_1", "参考图审核状态": "通过", "参考图file_token": "ft_role"}},
            {"record_id": "asset_env", "fields": {"记录类型": "参考资产", "父任务记录ID": "parent", "资产ID": "living_room", "参考图审核状态": "通过", "参考图file_token": "ft_env"}},
            {"record_id": "kf_first", "fields": {"记录类型": "关键帧", "父任务记录ID": "parent", "关键帧类型": "S01_FIRST", "参考资产ID列表": "role_1,living_room", "依赖关键帧类型": "", "关键帧生成状态": "不触发"}},
        ]
        updates = []
        with patch.object(multi_role, "TABLE_MULTI_ROLE_FIRST_LAST", "tbl_multi"), \
             patch.object(multi_role, "get_feishu_token", return_value="token"), \
             patch.object(multi_role, "safe_get_record", return_value=records[0]["fields"]), \
             patch.object(multi_role, "list_multi_role_records_for_parent", return_value=records), \
             patch.object(multi_role, "safe_update_record", side_effect=lambda token, table, rid, fields: updates.append((rid, fields))), \
             patch.object(multi_role, "filter_existing_fields", side_effect=lambda token, table, fields: fields):
            result = multi_role.advance_reference_review("asset_role")
        self.assertEqual(result["triggered_keyframes"], 1)
        self.assertIn(("kf_first", {"关键帧生成状态": "待生成", "关键帧错误信息": "", "错误信息": ""}), updates)
        self.assertIn(("asset_role", {"参考图审核状态": "已触发下游"}), updates)

    def test_keyframe_review_advances_dependent_keyframes_and_ready_videos(self):
        records = [
            {"record_id": "kf_first", "fields": {"记录类型": "关键帧", "父任务记录ID": "parent", "关键帧类型": "S01_FIRST", "关键帧审核状态": "通过", "关键帧图file_token": "ft_first"}},
            {"record_id": "kf_shared", "fields": {"记录类型": "关键帧", "父任务记录ID": "parent", "关键帧类型": "S01_TAIL_SHARED_S02_FIRST", "关键帧审核状态": "通过", "关键帧图file_token": "ft_shared"}},
            {"record_id": "kf_tail", "fields": {"记录类型": "关键帧", "父任务记录ID": "parent", "关键帧类型": "S02_TAIL", "依赖关键帧类型": "S01_TAIL_SHARED_S02_FIRST", "参考资产ID列表": "", "关键帧生成状态": "不触发"}},
            {"record_id": "clip_s01", "fields": {"记录类型": "视频片段", "父任务记录ID": "parent", "视频片段类型": "S01", "首关键帧类型": "S01_FIRST", "尾关键帧类型": "S01_TAIL_SHARED_S02_FIRST", "视频生成状态": "不触发"}},
        ]
        updates = []
        with patch.object(multi_role, "TABLE_MULTI_ROLE_FIRST_LAST", "tbl_multi"), \
             patch.object(multi_role, "get_feishu_token", return_value="token"), \
             patch.object(multi_role, "safe_get_record", return_value=records[1]["fields"]), \
             patch.object(multi_role, "list_multi_role_records_for_parent", return_value=records), \
             patch.object(multi_role, "safe_update_record", side_effect=lambda token, table, rid, fields: updates.append((rid, fields))), \
             patch.object(multi_role, "filter_existing_fields", side_effect=lambda token, table, fields: fields):
            result = multi_role.advance_keyframe_review("kf_shared")
        self.assertEqual(result["triggered_keyframes"], 1)
        self.assertEqual(result["triggered_videos"], 1)
        self.assertIn(("kf_tail", {"关键帧生成状态": "待生成", "关键帧错误信息": "", "错误信息": ""}), updates)
        self.assertIn(("clip_s01", {"视频生成状态": "待生成", "视频错误信息": "", "错误信息": ""}), updates)
        self.assertIn(("kf_shared", {"关键帧审核状态": "已触发下游"}), updates)

    def test_advance_ready_videos_repairs_stuck_clip_after_keyframes_are_approved(self):
        records = [
            {"record_id": "kf_first", "fields": {"记录类型": "关键帧", "父任务记录ID": "parent", "关键帧类型": "S01_FIRST", "关键帧审核状态": "通过", "关键帧图file_token": "ft_first"}},
            {"record_id": "kf_shared", "fields": {"记录类型": "关键帧", "父任务记录ID": "parent", "关键帧类型": "S01_TAIL_SHARED_S02_FIRST", "关键帧审核状态": "已触发下游", "关键帧图file_token": "ft_shared"}},
            {"record_id": "kf_tail", "fields": {"记录类型": "关键帧", "父任务记录ID": "parent", "关键帧类型": "S02_TAIL", "关键帧审核状态": "通过", "关键帧图file_token": "ft_tail"}},
            {"record_id": "clip_s01", "fields": {"记录类型": "视频片段", "父任务记录ID": "parent", "视频片段类型": "S01", "首关键帧类型": "S01_FIRST", "尾关键帧类型": "S01_TAIL_SHARED_S02_FIRST", "视频生成状态": "生成中"}},
            {"record_id": "clip_s02", "fields": {"记录类型": "视频片段", "父任务记录ID": "parent", "视频片段类型": "S02", "首关键帧类型": "S01_TAIL_SHARED_S02_FIRST", "尾关键帧类型": "S02_TAIL", "视频生成状态": "不触发"}},
        ]
        updates = []
        with patch.object(multi_role, "TABLE_MULTI_ROLE_FIRST_LAST", "tbl_multi"), \
             patch.object(multi_role, "get_feishu_token", return_value="token"), \
             patch.object(multi_role, "safe_get_record", return_value=records[2]["fields"]), \
             patch.object(multi_role, "list_multi_role_records_for_parent", return_value=records), \
             patch.object(multi_role, "safe_update_record", side_effect=lambda token, table, rid, fields: updates.append((rid, fields))), \
             patch.object(multi_role, "filter_existing_fields", side_effect=lambda token, table, fields: fields):
            result = multi_role.advance_ready_videos("kf_tail")

        self.assertEqual(result["parent_record_id"], "parent")
        self.assertEqual(result["triggered_videos"], 1)
        self.assertIn(("clip_s02", {"视频生成状态": "待生成", "视频错误信息": "", "错误信息": ""}), updates)
        self.assertNotIn(("clip_s01", {"视频生成状态": "待生成", "视频错误信息": "", "错误信息": ""}), updates)

    def test_dispatcher_has_multi_role_watches(self):
        watches = {watch["name"]: watch for watch in dispatcher.RAW_WATCH_LIST}
        self.assertEqual(watches["多角色首尾帧解析"]["script"], "tk_multi_role_first_last.py")
        self.assertEqual(watches["多角色首尾帧解析"]["required_field_values"], {"记录类型": ["", "母任务"]})
        self.assertEqual(watches["多角色首尾帧解析"]["claim_clear_values"]["记录类型"], "母任务")
        self.assertEqual(watches["多角色首尾帧解析"]["claim_clear_values"]["记录状态"], "有效")
        self.assertEqual(watches["多角色参考图审核推进"]["args"], ["advance-reference-review"])
        self.assertEqual(watches["多角色关键帧审核推进"]["args"], ["advance-keyframe-review"])
        self.assertEqual(watches["多角色参考图生成"]["required_field_values"], {"记录类型": ["参考资产"]})
        self.assertEqual(watches["多角色关键帧生成"]["required_field_values"], {"记录类型": ["关键帧"]})
        self.assertEqual(watches["多角色参考图生成"]["trigger_values"], ["待生成", "生成中"])
        self.assertEqual(watches["多角色关键帧生成"]["trigger_values"], ["待生成", "生成中"])
        self.assertEqual(watches["多角色视频片段生成"]["required_field_values"], {"记录类型": ["视频片段"]})
        self.assertEqual(watches["多角色视频片段生成"]["trigger_values"], ["待生成", "生成中"])
        self.assertEqual(watches["多角色视频片段生成"]["max_concurrency"], 2)
        reference_waiting_claim = dispatcher.apply_claim_clear_fields({"参考图生成状态": "生成中"}, watches["多角色参考图生成"], "待生成")
        self.assertEqual(reference_waiting_claim["参考图任务ID"], "")
        reference_running_claim = dispatcher.apply_claim_clear_fields({"参考图生成状态": "生成中"}, watches["多角色参考图生成"], "生成中")
        self.assertNotIn("参考图任务ID", reference_running_claim)

        keyframe_waiting_claim = dispatcher.apply_claim_clear_fields({"关键帧生成状态": "生成中"}, watches["多角色关键帧生成"], "待生成")
        self.assertEqual(keyframe_waiting_claim["关键帧任务ID"], "")
        keyframe_running_claim = dispatcher.apply_claim_clear_fields({"关键帧生成状态": "生成中"}, watches["多角色关键帧生成"], "生成中")
        self.assertNotIn("关键帧任务ID", keyframe_running_claim)
        self.assertEqual(
            watches["多角色视频片段生成"]["claim_clear_fields_by_trigger_value"]["待生成"],
            [
                "视频任务ID",
                "视频片段file_token",
                "视频本地路径",
                "视频原始响应JSON",
                "视频错误信息",
                "错误信息",
            ],
        )
        self.assertEqual(
            watches["多角色视频片段生成"]["claim_clear_values_by_trigger_value"]["待生成"],
            {
                "视频片段URL": None,
            },
        )

    def test_dispatcher_claim_filters_attachment_resets_before_update(self):
        watch = {
            "name": "多角色视频片段生成",
            "table": "tblMulti",
            "status_field": "视频生成状态",
            "trigger_value": "待生成",
            "running_value": "生成中",
            "required_field_values": {"记录类型": ["视频片段"]},
            "claim_clear_fields_by_trigger_value": {
                "待生成": ["视频任务ID", "视频片段file_token"],
            },
            "claim_clear_values_by_trigger_value": {
                "待生成": {
                    "视频片段": [],
                    "视频片段URL": None,
                },
            },
        }
        updates = []
        latest = {"记录类型": "视频片段", "视频生成状态": "待生成"}

        with patch.object(dispatcher, "safe_get_record", return_value=latest), \
             patch.object(dispatcher, "safe_update_record", side_effect=lambda token, table, record_id, fields: updates.append(fields)), \
             patch.object(dispatcher, "update_record_state_cache"), \
             patch.object(dispatcher, "get_table_field_kinds", return_value={"视频片段": "attachment", "视频片段URL": "text"}):
            self.assertTrue(dispatcher.try_claim_task("token", watch, "rec1"))

        self.assertEqual(updates[0], {
            "视频生成状态": "生成中",
            "视频任务ID": "",
            "视频片段file_token": "",
            "视频片段URL": None,
        })

    def test_video_plan_uses_shared_keyframe_for_both_clips(self):
        payload = multi_role.normalize_plan_payload(sample_plan(role_count=3))
        clips = {clip["clip_type"]: clip for clip in payload["videos"]}
        self.assertEqual(clips["S01"]["first_keyframe_type"], "S01_FIRST")
        self.assertEqual(clips["S01"]["last_keyframe_type"], "S01_TAIL_SHARED_S02_FIRST")
        self.assertEqual(clips["S02"]["first_keyframe_type"], "S01_TAIL_SHARED_S02_FIRST")
        self.assertEqual(clips["S02"]["last_keyframe_type"], "S02_TAIL")


if __name__ == "__main__":
    unittest.main()
