import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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

    def test_default_parse_prompt_constrains_human_reference_images_to_front_facing_ugc(self):
        prompt = multi_role.DEFAULT_PARSE_PROMPT

        for phrase in [
            "single person",
            "front-facing",
            "full face visible",
            "no side profile",
            "one angle",
            "no multi-view",
            "UGC smartphone",
            "natural skin texture",
            "not studio",
        ]:
            self.assertIn(phrase, prompt)

    def test_default_parse_prompt_preserves_environment_problem_anchor(self):
        prompt = multi_role.DEFAULT_PARSE_PROMPT

        for phrase in [
            "urine stain",
            "pee stain",
            "visible problem area",
            "accident point",
            "不要删除尿渍",
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
        self.assertIn("视频操作", views["04-视频片段结果"])
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
        self.assertIn("视频AI模型", views["高级AI参数"])
        self.assertIn("视频AI参数JSON", views["高级AI参数"])
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
        self.assertEqual(views["99-全字段系统视图"], [field["name"] for field in create_table.MULTI_ROLE_FIRST_LAST_FIELDS])

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
             patch.object(multi_role, "deprecate_existing_children", return_value=0), \
             patch.object(multi_role, "create_records", return_value=8):
            result = multi_role.parse_task("recParent")

        route = call_text.call_args.args[0]
        self.assertEqual(result["status"], "success")
        self.assertEqual(route.provider, "Aitgenne")
        self.assertEqual(route.call_type, "OpenAI兼容 chat/completions")
        self.assertEqual(route.api_base, "")
        self.assertEqual(route.api_key, "sk-aitgenne")

    def test_multi_role_media_summary_rejects_reference_video_model(self):
        config_records = [
            {"fields": {"环节": "统一AI路由启用状态", "模型名称": "指定记录启用"}},
            {"fields": {"AI供应商": "Aitgenne", "API 代理地址": "https://api.aitgenne.com", "API Key": "sk-aitgenne"}},
        ]

        with patch.object(multi_role, "safe_list_records", return_value=config_records):
            with self.assertRaisesRegex(ValueError, "首尾帧视频模型不支持参考图视频模型"):
                multi_role.maybe_unified_media_summary(
                    "token",
                    {"使用统一AI路由": "是", "视频AI模型": "Aitgenne / happyhorse-1.0-r2v"},
                    {"provider": "OTU", "api_key": "sk-otu", "api_base": "https://otuapi.com", "model": "veo_3_1-fast-fl"},
                    capability="视频",
                    task_type="首尾帧图生视频",
                    model="veo_3_1-fast-fl",
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

    def test_video_dependencies_accept_already_advanced_keyframes(self):
        records = [
            {"record_id": "kf_first", "fields": {"记录类型": "关键帧", "父任务记录ID": "parent", "关键帧类型": "S01_FIRST", "关键帧审核状态": "已触发下游", "关键帧图file_token": "ft_first"}},
        ]
        result = multi_role._find_keyframe_for_clip(records, "parent", "S01_FIRST")
        self.assertEqual(result["file_token"], "ft_first")

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
             patch.object(multi_role, "safe_list_records", return_value=[]), \
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

    def test_video_clip_resumes_existing_task_id(self):
        fields = {
            "记录类型": "视频片段",
            "记录状态": "有效",
            "视频提示词": "animate between frames",
            "视频版本": 2,
            "视频任务ID": "task_existing",
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
             patch.object(multi_role, "safe_list_records", return_value=records), \
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
             patch.object(multi_role, "safe_list_records", return_value=records), \
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

    def test_regeneration_resets_current_output_and_increments_version(self):
        updates = []
        with patch.object(multi_role, "TABLE_MULTI_ROLE_FIRST_LAST", "tbl_multi"), \
             patch.object(multi_role, "get_feishu_token", return_value="token"), \
             patch.object(multi_role, "safe_get_record", return_value={"记录类型": "关键帧", "记录状态": "有效", "关键帧版本": 2}), \
             patch.object(multi_role, "safe_update_record", side_effect=lambda token, table, rid, fields: updates.append(fields)), \
             patch.object(multi_role, "filter_existing_fields", side_effect=lambda token, table, fields: fields):
            result = multi_role.request_keyframe_regeneration("rec_keyframe")
        self.assertEqual(result["version"], 3)
        self.assertEqual(updates[0]["关键帧版本"], 3)
        self.assertEqual(updates[0]["关键帧生成状态"], "待生成")
        self.assertEqual(updates[0]["关键帧图"], [])
        self.assertEqual(updates[0]["关键帧任务ID"], "")

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
             patch.object(multi_role, "safe_list_records", return_value=records), \
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
             patch.object(multi_role, "safe_list_records", return_value=records), \
             patch.object(multi_role, "safe_update_record", side_effect=lambda token, table, rid, fields: updates.append((rid, fields))), \
             patch.object(multi_role, "filter_existing_fields", side_effect=lambda token, table, fields: fields):
            result = multi_role.advance_keyframe_review("kf_shared")
        self.assertEqual(result["triggered_keyframes"], 1)
        self.assertEqual(result["triggered_videos"], 1)
        self.assertIn(("kf_tail", {"关键帧生成状态": "待生成", "关键帧错误信息": "", "错误信息": ""}), updates)
        self.assertIn(("clip_s01", {"视频生成状态": "待生成", "视频错误信息": "", "错误信息": ""}), updates)
        self.assertIn(("kf_shared", {"关键帧审核状态": "已触发下游"}), updates)

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
        self.assertEqual(watches["多角色视频片段生成"]["required_field_values"], {"记录类型": ["视频片段"]})
        self.assertEqual(watches["多角色视频片段生成"]["trigger_values"], ["待生成", "生成中"])
        self.assertEqual(watches["多角色视频片段生成"]["max_concurrency"], 2)
        self.assertEqual(
            watches["多角色视频片段生成"]["claim_clear_fields_by_trigger_value"]["待生成"],
            [
                "视频任务ID",
                "视频片段",
                "视频片段URL",
                "视频片段file_token",
                "视频本地路径",
                "视频原始响应JSON",
                "视频错误信息",
            ],
        )

    def test_video_plan_uses_shared_keyframe_for_both_clips(self):
        payload = multi_role.normalize_plan_payload(sample_plan(role_count=3))
        clips = {clip["clip_type"]: clip for clip in payload["videos"]}
        self.assertEqual(clips["S01"]["first_keyframe_type"], "S01_FIRST")
        self.assertEqual(clips["S01"]["last_keyframe_type"], "S01_TAIL_SHARED_S02_FIRST")
        self.assertEqual(clips["S02"]["first_keyframe_type"], "S01_TAIL_SHARED_S02_FIRST")
        self.assertEqual(clips["S02"]["last_keyframe_type"], "S02_TAIL")


if __name__ == "__main__":
    unittest.main()
