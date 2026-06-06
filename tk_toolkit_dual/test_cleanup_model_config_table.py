import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cleanup_model_config_table as cleanup


def rec(record_id, **fields):
    return {"record_id": record_id, "fields": fields}


class CleanupModelConfigTableTests(unittest.TestCase):
    def test_plan_classifies_current_archive_and_runtime_records(self):
        records = [
            rec("prod_img", 环节="图片生成-OTU", 模型名称="gpt-image-2", **{"API Key": "sk-prod", "状态": "启用"}),
            rec("switch", 环节="统一AI路由启用状态", 模型名称="仅dry-run", 状态="启用"),
            rec("ng_img", 环节="多图九宫格图片生成", 模型名称="gpt-image-2", 是否统一AI预设="是", 状态="测试中"),
            rec("current", 环节="统一AI预设-OTU / gpt-image-2", 模型名称="OTU / gpt-image-2", 状态="启用"),
            rec("candidate", 环节="统一AI预设-AIHubMix / seeddance2.0", 模型名称="AIHubMix / seeddance2.0", 状态="启用"),
            rec("legacy", 环节="统一AI预设-图片-OTU-GPTImage2-1K", 模型名称="gpt-image-2", 是否统一AI预设="是", 状态="测试中", 备注="old note"),
        ]

        plan = cleanup.build_cleanup_plan(records)
        patches = {item.record_id: item.fields for item in plan.record_updates}

        self.assertEqual(plan.summary["production_config_count"], 1)
        self.assertEqual(plan.summary["route_switch_count"], 1)
        self.assertEqual(plan.summary["prompt_stage_config_count"], 1)
        self.assertEqual(plan.summary["current_catalog_preset_count"], 1)
        self.assertEqual(plan.summary["archived_preset_count"], 2)
        self.assertEqual(patches["prod_img"], {
            "是否统一AI预设": "否",
            "配置类型": "运行环节",
            "生效来源": "线上配置",
            "供应商": "OTU",
            "能力类型": "图片",
            "画面尺寸": "720x1280",
            "画面比例": "9:16",
            "备注": "运行环节配置：API/提示词/兜底源；任务记录自己的模型/参数优先。",
        })
        self.assertEqual(patches["switch"], {
            "是否统一AI预设": "否",
            "配置类型": "路由开关",
            "生效来源": "线上配置",
            "备注": "统一AI路由开关：当前模式=仅dry-run；记录级模型/参数优先；模式为“指定记录启用”时，仅对任务记录中开启“使用统一AI路由”的记录生效。",
        })
        self.assertEqual(patches["ng_img"], {
            "是否统一AI预设": "否",
            "配置类型": "运行环节",
            "生效来源": "线上配置",
            "供应商": "OTU",
            "能力类型": "图片",
            "画面尺寸": "720x1280",
            "画面比例": "9:16",
            "备注": "运行环节配置：API/提示词/兜底源；任务记录自己的模型/参数优先。",
        })
        self.assertEqual(patches["current"], {
            "是否统一AI预设": "是",
            "配置类型": "模型目录",
            "生效来源": "线上配置",
            "状态": "启用",
            "备注": "模型目录：候选模型清单，不直接触发运行。",
        })
        self.assertEqual(patches["candidate"]["状态"], "停用")
        self.assertEqual(patches["candidate"]["是否统一AI预设"], "否")
        self.assertEqual(patches["candidate"]["配置类型"], "模型目录")
        self.assertEqual(patches["candidate"]["生效来源"], "线上配置")
        self.assertIn("candidate", patches["candidate"]["备注"])
        self.assertEqual(patches["legacy"]["状态"], "停用")
        self.assertEqual(patches["legacy"]["是否统一AI预设"], "否")
        self.assertEqual(patches["legacy"]["配置类型"], "模型目录")
        self.assertEqual(patches["legacy"]["生效来源"], "线上配置")
        self.assertIn("归档", patches["legacy"]["备注"])
        self.assertIn("old note", patches["legacy"]["备注"])

    def test_plan_marks_auto_review_switch_records_for_admin_view(self):
        records = [
            rec("auto", 环节="001-多角色首尾帧生成表一键审核通过模式", 状态="停用"),
        ]

        plan = cleanup.build_cleanup_plan(records)
        patches = {item.record_id: item.fields for item in plan.record_updates}

        self.assertEqual(patches["auto"], {
            "配置类型": "自动审核",
            "生效来源": "线上配置",
            "备注": "自动审核开关：表级控制；启用后仅自动放行本表新生成成功且有附件 token 的审核闸门。",
        })

    def test_plan_preserves_existing_single_source_row_types(self):
        records = [
            rec("default", **{"配置类型": "任务默认", "应用表格": "002-首尾帧视频生成表", "任务环节": "首帧图生成默认", "环节": "图片生成-OTU", "生效来源": "线上配置", "状态": "启用"}),
            rec("catalog", **{"配置类型": "模型目录", "环节": "图片生成-OTU", "显示名称": "OTU / gpt-image-2", "状态": "启用", "生效来源": "线上配置"}),
        ]

        plan = cleanup.build_cleanup_plan(records)
        patches = {item.record_id: item.fields for item in plan.record_updates}

        self.assertEqual(patches["default"], {
            "业务环节名": "002-首尾帧视频生成表-首帧图生成",
            "调度环节名": "首尾帧首帧图生成",
            "备注": "任务默认配置：仅在任务记录未指定模型/参数时用于初始化/补默认。",
        })
        self.assertEqual(patches["catalog"], {"备注": "模型目录：候选模型清单，不直接触发运行。"})

    def test_plan_adds_clear_role_remarks_without_changing_statuses(self):
        records = [
            rec("runtime", **{"配置类型": "运行环节", "环节": "图片生成-OTU", "状态": "启用", "备注": "OTU 单张分镜图生成"}),
            rec("runtime_fixed", **{"配置类型": "运行环节", "环节": "多图九宫格视频生成", "状态": "启用", "备注": "模型固定 omni_flash-10s"}),
            rec("default", **{"配置类型": "任务默认", "应用表格": "001-多角色首尾帧生成表", "任务环节": "参考图生成默认", "状态": "启用"}),
            rec("catalog", **{"配置类型": "模型目录", "显示名称": "OTU / gpt-image-2", "状态": "启用"}),
            rec("route", **{"配置类型": "路由开关", "环节": "统一AI路由启用状态", "模型名称": "指定记录启用", "状态": "启用", "备注": "恢复关闭"}),
            rec("route_all", **{"配置类型": "路由开关", "环节": "统一AI路由启用状态", "模型名称": "全量启用", "状态": "启用", "备注": "old note"}),
            rec("auto", **{"配置类型": "自动审核", "环节": "001-多角色首尾帧生成表一键审核通过模式", "状态": "停用", "备注": "表级自动审核通过开关；启用后仅自动放行本表新生成成功且有附件 token 的审核闸门。"}),
        ]

        plan = cleanup.build_cleanup_plan(records)
        patches = {item.record_id: item.fields for item in plan.record_updates}

        self.assertIn("API/提示词/兜底源", patches["runtime"]["备注"])
        self.assertIn("任务记录自己的模型/参数优先", patches["runtime"]["备注"])
        self.assertIn("默认模型 omni_flash-10s", patches["runtime_fixed"]["备注"])
        self.assertNotIn("模型固定", patches["runtime_fixed"]["备注"])
        self.assertIn("任务记录未指定模型/参数时", patches["default"]["备注"])
        self.assertIn("候选模型清单，不直接触发运行", patches["catalog"]["备注"])
        self.assertIn("当前模式=指定记录启用", patches["route"]["备注"])
        self.assertNotIn("关闭", patches["route"]["备注"])
        self.assertIn("当前模式=全量启用", patches["route_all"]["备注"])
        self.assertIn("隐藏字段 使用统一AI路由 不再是必要条件", patches["route_all"]["备注"])
        self.assertNotIn("状态", patches["route"])
        self.assertEqual(
            patches["auto"]["备注"],
            "自动审核开关：表级控制；启用后仅自动放行本表新生成成功且有附件 token 的审核闸门。",
        )

    def test_plan_does_not_archive_task_default_with_legacy_source_stage(self):
        records = [
            rec("video_edit_default", **{
                "配置类型": "任务默认",
                "应用表格": "006-视频编辑任务表",
                "任务环节": "视频编辑默认",
                "默认槽位": "视频编辑",
                "环节": "统一AI预设-Aitgenne / happyhorse-1.0-video-edit",
                "模型名称": "Aitgenne / happyhorse-1.0-video-edit",
                "状态": "启用",
                "生效来源": "线上配置",
            }),
        ]

        plan = cleanup.build_cleanup_plan(records)

        self.assertEqual(plan.record_updates, [
            cleanup.RecordUpdate(
                record_id="video_edit_default",
                category="single_source_record",
                fields={
                    "业务环节名": "006-视频编辑任务表-视频编辑生成",
                    "调度环节名": "视频编辑生成",
                    "备注": "任务默认配置：仅在任务记录未指定模型/参数时用于初始化/补默认。",
                },
            )
        ])

    def test_backup_snapshot_redacts_secrets_and_long_prompts(self):
        snapshot = cleanup.build_backup_snapshot(
            fields=[{"field_name": "API Key"}, {"field_name": "环节"}],
            views=[{"view_name": "配置总览"}],
            records=[
                rec("prod_img", 环节="图片生成-OTU", 模型名称="gpt-image-2", **{"API Key": "sk-prod-token", "提示词": "hello" * 200}),
            ],
        )
        serialized = json.dumps(snapshot, ensure_ascii=False)

        self.assertNotIn("sk-prod-token", serialized)
        self.assertNotIn("API Key", serialized)
        self.assertEqual(snapshot["records"][0]["api_key_status"], "存在")
        self.assertEqual(snapshot["records"][0]["提示词_chars"], 1000)
        self.assertNotIn("hellohello", serialized)

    def test_view_definitions_keep_daily_views_clean(self):
        field_names = [
            "配置类型",
            "应用表格",
            "任务环节",
            "默认槽位",
            "环节",
            "模型名称",
            "显示名称",
            "供应商",
            "能力类型",
            "API 代理地址",
            "画面尺寸",
            "画面比例",
            "AI参数JSON",
            "调用方式",
            "提示词",
            "API Key",
            "生效来源",
            "测试状态",
            "是否生产可用",
            "状态",
            "备注",
        ]
        views = cleanup.build_view_definitions(field_names)

        self.assertEqual(list(views), [
            "01-运行配置-管理员",
            "02-任务默认配置",
            "03-模型目录",
            "05-自动审核开关",
            "99-排错全字段",
        ])
        self.assertIn("API Key", views["01-运行配置-管理员"]["visible_fields"])
        self.assertIn("提示词", views["01-运行配置-管理员"]["visible_fields"])
        self.assertEqual(views["03-模型目录"]["visible_fields"], cleanup.MODEL_CATALOG_VISIBLE_FIELDS)
        self.assertIn("画面尺寸", views["02-任务默认配置"]["visible_fields"])
        self.assertIn("画面比例", views["02-任务默认配置"]["visible_fields"])
        self.assertEqual(
            views["01-运行配置-管理员"]["filter"],
            {"logic": "and", "conditions": [["配置类型", "intersects", ["运行环节", "路由开关", "自动审核"]], ["状态", "intersects", ["启用", "测试中"]]]},
        )
        self.assertEqual(
            views["05-自动审核开关"]["filter"],
            {"logic": "and", "conditions": [["配置类型", "intersects", ["自动审核"]]]},
        )
        self.assertIn("状态", views["05-自动审核开关"]["visible_fields"])
        self.assertIn("API Key", views["99-排错全字段"]["visible_fields"])
        self.assertIn("提示词", views["99-排错全字段"]["visible_fields"])

    def test_config_field_specs_include_concurrency_fields(self):
        specs = {item["name"]: item for item in cleanup.CONFIG_FIELD_SPECS}

        self.assertEqual(specs["环节最大并发"]["type"], "number")
        self.assertEqual(specs["全局最大并发"]["type"], "number")
        self.assertEqual(specs["业务环节名"]["type"], "text")
        self.assertEqual(specs["调度环节名"]["type"], "text")
        self.assertEqual(specs["使用位置摘要"]["type"], "text")

    def test_admin_view_shows_concurrency_fields(self):
        views = cleanup.build_view_definitions(["配置类型", "环节", "业务环节名", "调度环节名", "使用位置摘要", "环节最大并发", "全局最大并发"])
        visible = views["01-运行配置-管理员"]["visible_fields"]

        self.assertIn("业务环节名", visible)
        self.assertIn("调度环节名", visible)
        self.assertIn("使用位置摘要", visible)
        self.assertIn("环节最大并发", visible)
        self.assertIn("全局最大并发", visible)

    def test_task_default_rows_get_business_and_dispatch_names(self):
        fields = {
            "配置类型": "任务默认",
            "应用表格": "001-多角色首尾帧生成表",
            "任务环节": "多角色解析默认",
            "环节": "多角色首尾帧解析-Gemini",
        }

        patch = cleanup.task_default_metadata_patch(fields)

        self.assertEqual(patch["业务环节名"], "001-多角色首尾帧生成表-文本分析")
        self.assertEqual(patch["调度环节名"], "多角色首尾帧解析")

    def test_runtime_rows_get_usage_summary_and_single_use_business_name(self):
        records = [
            rec("runtime", **{"配置类型": "运行环节", "环节": "多角色首尾帧解析-Gemini", "状态": "启用"}),
            rec("default", **{
                "配置类型": "任务默认",
                "应用表格": "001-多角色首尾帧生成表",
                "任务环节": "多角色解析默认",
                "环节": "多角色首尾帧解析-Gemini",
                "状态": "启用",
            }),
        ]

        plan = cleanup.build_cleanup_plan(records)
        patches = {item.record_id: item.fields for item in plan.record_updates}

        self.assertEqual(patches["runtime"]["业务环节名"], "001-多角色首尾帧生成表-文本分析")
        self.assertEqual(patches["runtime"]["调度环节名"], "多角色首尾帧解析")
        self.assertEqual(patches["runtime"]["使用位置摘要"], "001-多角色首尾帧生成表-文本分析 -> 多角色首尾帧解析")

    def test_shared_runtime_concurrency_is_copied_to_task_defaults_without_single_dispatch_name(self):
        records = [
            rec("runtime", **{"配置类型": "运行环节", "环节": "图片生成-OTU", "状态": "启用", "环节最大并发": 10}),
            rec("default1", **{
                "配置类型": "任务默认",
                "应用表格": "001-多角色首尾帧生成表",
                "任务环节": "参考图生成默认",
                "环节": "图片生成-OTU",
                "状态": "启用",
            }),
            rec("default2", **{
                "配置类型": "任务默认",
                "应用表格": "002-首尾帧视频生成表",
                "任务环节": "首帧图生成默认",
                "环节": "图片生成-OTU",
                "状态": "启用",
            }),
        ]

        plan = cleanup.build_cleanup_plan(records)
        patches = {item.record_id: item.fields for item in plan.record_updates}

        self.assertIn("001-多角色首尾帧生成表-参考图生成 -> 多角色参考图生成", patches["runtime"]["使用位置摘要"])
        self.assertIn("002-首尾帧视频生成表-首帧图生成 -> 首尾帧首帧图生成", patches["runtime"]["使用位置摘要"])
        self.assertNotIn("调度环节名", patches["runtime"])
        self.assertEqual(patches["default1"]["环节最大并发"], 10)
        self.assertEqual(patches["default2"]["环节最大并发"], 10)

    def test_blank_status_runtime_stage_is_marked_enabled(self):
        records = [
            rec("veo", 环节=cleanup.AIHUBMIX_VEO_STAGE, 模型名称="veo-3.1-fast-generate-preview", 状态=""),
        ]

        plan = cleanup.build_cleanup_plan(records)
        patches = {item.record_id: item.fields for item in plan.record_updates}

        self.assertEqual(patches["veo"]["状态"], "启用")

    def test_plan_treats_select_name_values_as_already_matching(self):
        records = [
            rec(
                "image",
                环节="图片生成-OTU",
                配置类型="运行环节",
                状态="启用",
                **{
                    "画面尺寸": [{"name": "720x1280"}],
                    "画面比例": [{"name": "9:16"}],
                    "备注": "运行环节配置：API/提示词/兜底源；任务记录自己的模型/参数优先。",
                },
            ),
        ]

        plan = cleanup.build_cleanup_plan(records)

        self.assertEqual(plan.record_updates, [])

    def test_delete_audit_only_selects_safe_stopped_legacy_presets(self):
        records = [
            rec("runtime_key", 环节="图片生成-OTU", 状态="启用", 调用方式="专用 API", **{"API 代理地址": "https://otuapi.com", "API Key": "sk-runtime"}),
            rec("safe_old", 环节="统一AI预设-图片-OTU-GPTImage2-1K", 状态="停用", 调用方式="专用 API", **{"API 代理地址": "https://otuapi.com", "API Key": "sk-old"}),
            rec("linked_old", 环节="统一AI预设-视频-AIHubMix-VeoFast-720p", 状态="停用", 调用方式="Gemini 原生 SDK", **{"API 代理地址": "https://aihubmix.com/gemini"}),
            rec("unique_key", 环节="统一AI预设-文本-Only-Key", 状态="停用", 调用方式="OpenAI", **{"API 代理地址": "https://unique.example", "API Key": "sk-unique"}),
            rec("current", 环节="统一AI预设-OTU / gpt-image-2", 状态="启用", 调用方式="专用 API", **{"API 代理地址": "https://otuapi.com"}),
        ]
        task_defaults = [
            rec("default", 备注="source_config=统一AI预设-视频-AIHubMix-VeoFast-720p; source_record_id=linked_old"),
        ]

        audit = cleanup.build_delete_audit(
            records,
            task_defaults,
            config_record_ids=set(),
            code_referenced_stages=set(),
        )

        self.assertEqual([item.record_id for item in audit.candidates], ["safe_old"])
        skipped = {item.record_id: item.reason for item in audit.skipped}
        self.assertIn("被任务默认配置引用", skipped["linked_old"])
        self.assertIn("唯一密钥来源", skipped["unique_key"])
        self.assertNotIn("sk-", json.dumps(audit.to_public_dict(), ensure_ascii=False))

    def test_delete_audit_keeps_code_referenced_or_config_id_records(self):
        records = [
            rec("code_ref", 环节="统一AI预设-文本-Legacy", 状态="停用"),
            rec("config_ref", 环节="统一AI预设-图片-Legacy", 状态="停用"),
        ]

        audit = cleanup.build_delete_audit(
            records,
            [],
            config_record_ids={"config_ref"},
            code_referenced_stages={"统一AI预设-文本-Legacy"},
        )

        skipped = {item.record_id: item.reason for item in audit.skipped}
        self.assertIn("生产代码常量引用", skipped["code_ref"])
        self.assertIn("config_records 引用", skipped["config_ref"])

    def test_cleanup_targets_do_not_delete_unified_table_fields_or_touch_legacy_tables(self):
        self.assertEqual(cleanup.MIGRATED_FIELD_NAMES, set())
        self.assertFalse(hasattr(cleanup, "MODEL_CATALOG_TABLE_ID"))
        self.assertFalse(hasattr(cleanup, "TASK_DEFAULT_TABLE_ID"))
        self.assertIn("统一AI预设", cleanup.OBSOLETE_VIEWS_BY_TABLE[cleanup.TABLE_CONFIG])
        self.assertEqual(cleanup.LEGACY_CONFIG_VIEW_RENAMES["供应商密钥-管理员"], "01-运行配置-管理员")

    def test_config_field_specs_include_media_dimensions(self):
        specs = {item["name"]: item for item in cleanup.CONFIG_FIELD_SPECS}

        self.assertEqual([item["name"] for item in specs["画面尺寸"]["options"]], [
            "1024x1024",
            "720x1280",
            "1080x1920",
            "1280x720",
            "1440x2560",
            "2K",
            "4K",
        ])
        self.assertEqual([item["name"] for item in specs["画面比例"]["options"]], ["9:16", "16:9", "1:1"])

    def test_config_field_specs_include_single_source_runtime_fields(self):
        specs = {item["name"]: item for item in cleanup.CONFIG_FIELD_SPECS}

        self.assertEqual([item["name"] for item in specs["配置类型"]["options"]], ["运行环节", "任务默认", "模型目录", "路由开关", "自动审核"])
        self.assertEqual([item["name"] for item in specs["生效来源"]["options"]], ["线上配置", "代码默认"])
        self.assertEqual([item["name"] for item in specs["测试状态"]["options"]], ["未测试", "测试通过", "测试失败", "停用"])
        self.assertEqual([item["name"] for item in specs["是否生产可用"]["options"]], ["是", "否"])
        self.assertEqual([item["name"] for item in specs["应用表格"]["options"]], cleanup.TASK_DEFAULT_APP_TABLE_OPTIONS)
        self.assertEqual([item["name"] for item in specs["默认槽位"]["options"]], ["stage", "参考图", "关键帧", "视频", "首帧图", "尾帧图", "分镜图", "图片", "口播音频", "视频编辑"])
        self.assertIn("供应商", specs)
        self.assertIn("能力类型", specs)
        self.assertIn("显示名称", specs)
        self.assertIn("任务环节", specs)

    def test_dispatcher_concurrency_control_record_is_created_when_missing(self):
        result = cleanup.ensure_dispatcher_concurrency_control_record("token", [], dry_run=True)

        self.assertEqual(result["status"], "dry_run_create")
        self.assertEqual(result["fields"]["配置类型"], "路由开关")
        self.assertEqual(result["fields"]["环节"], cleanup.DISPATCHER_CONCURRENCY_STAGE)
        self.assertEqual(result["fields"]["全局最大并发"], 0)

    def test_dispatcher_concurrency_control_record_is_not_duplicated(self):
        records = [
            rec("rec_control", **{
                "配置类型": "路由开关",
                "环节": cleanup.DISPATCHER_CONCURRENCY_STAGE,
                "状态": "启用",
                "全局最大并发": 3,
            }),
        ]

        result = cleanup.ensure_dispatcher_concurrency_control_record("token", records, dry_run=True)

        self.assertEqual(result, {"status": "exists", "record_id": "rec_control"})

    def test_view_definitions_expose_single_source_management_views(self):
        views = cleanup.build_view_definitions([
            "环节",
            "配置类型",
            "应用表格",
            "任务环节",
            "默认槽位",
            "模型名称",
            "显示名称",
            "供应商",
            "能力类型",
            "API Key",
            "API 代理地址",
            "调用方式",
            "提示词",
            "画面尺寸",
            "画面比例",
            "AI参数JSON",
            "生效来源",
            "状态",
            "备注",
        ])

        self.assertEqual(list(views), [
            "01-运行配置-管理员",
            "02-任务默认配置",
            "03-模型目录",
            "05-自动审核开关",
            "99-排错全字段",
        ])
        self.assertIn("API Key", views["01-运行配置-管理员"]["visible_fields"])
        self.assertIn("应用表格", views["02-任务默认配置"]["visible_fields"])
        self.assertIn("默认槽位", views["02-任务默认配置"]["visible_fields"])
        self.assertIn("显示名称", views["03-模型目录"]["visible_fields"])
        self.assertIn("状态", views["05-自动审核开关"]["visible_fields"])

    def test_model_catalog_visible_field_count_allows_forced_primary_field(self):
        definition = {"visible_fields": cleanup.MODEL_CATALOG_VISIBLE_FIELDS}

        self.assertFalse(cleanup.view_needs_visible_field_rebuild("03-模型目录", definition, 11))
        self.assertTrue(cleanup.view_needs_visible_field_rebuild("03-模型目录", definition, 21))
        self.assertFalse(cleanup.view_needs_visible_field_rebuild("05-自动审核开关", definition, 21))

    def test_apply_view_definitions_rebuilds_model_catalog_when_visible_fields_stay_wide(self):
        calls = []

        def fake_run_json(argv):
            calls.append(list(argv))
            if "+view-create" in argv:
                return {"data": {"view": {"id": "vew_new"}}}
            return {}

        views = {
            "03-模型目录": {
                "visible_fields": cleanup.MODEL_CATALOG_VISIBLE_FIELDS,
                "filter": {"logic": "and", "conditions": [["配置类型", "intersects", ["模型目录"]]]},
            }
        }

        with patch.object(cleanup, "get_feishu_token", return_value="token"), \
             patch.object(cleanup, "list_views", return_value=[{"view_name": "03-模型目录", "view_id": "vew_old"}]), \
             patch.object(cleanup, "view_visible_field_count", side_effect=[21, 11]), \
             patch.object(cleanup, "run_json", side_effect=fake_run_json):
            results = cleanup.apply_view_definitions("app_token", views, dry_run=False)

        self.assertEqual(results[0]["status"], "rebuilt")
        self.assertEqual(results[0]["view_id"], "vew_new")
        self.assertEqual(results[0]["visible_field_count"], 11)
        self.assertTrue(any("+view-rename" in call and "vew_old" in call for call in calls))
        self.assertTrue(any("+view-delete" in call and "vew_old" in call for call in calls))
        self.assertTrue(any("+view-create" in call for call in calls))

    def test_run_cleanup_avoids_legacy_table_writes_and_field_deletes(self):
        with patch.object(cleanup, "get_feishu_token", return_value="token"), \
             patch.object(cleanup, "list_fields", return_value=[]), \
             patch.object(cleanup, "list_views", return_value=[]), \
             patch.object(cleanup, "safe_list_records", return_value=[]), \
             patch.object(cleanup, "write_backup"), \
             patch.object(cleanup, "create_missing_config_fields", return_value=[]), \
             patch.object(cleanup, "apply_record_updates", return_value=[]), \
             patch.object(cleanup, "delete_audited_records") as delete_records, \
             patch.object(cleanup, "rename_legacy_views", return_value=[]), \
             patch.object(cleanup, "apply_view_definitions", return_value=[]), \
             patch.object(cleanup, "delete_obsolete_views", return_value=[]), \
             patch.object(cleanup, "rename_legacy_config_table") as rename_table, \
             patch.object(cleanup, "delete_migrated_fields") as delete_fields, \
             patch.object(cleanup, "ensure_unified_config_table_name", return_value={"status": "dry_run"}) as rename_unified:
            result = cleanup.run_cleanup(write=False, backup_path=Path("/tmp/cleanup.json"))

        rename_table.assert_not_called()
        rename_unified.assert_called_once()
        delete_fields.assert_not_called()
        delete_records.assert_not_called()
        self.assertEqual(result["legacy_table"]["status"], "not_touched")
        self.assertEqual(result["config_table_name"]["status"], "dry_run")
        self.assertEqual(result["migrated_fields"], [])
        self.assertEqual(result["deleted_records"], [])

    def test_run_cleanup_drops_noop_updates_after_unwritable_fields_are_filtered(self):
        records = [
            rec(
                "image",
                环节="图片生成-OTU",
                配置类型="运行环节",
                状态="启用",
                **{
                    "API Key": "sk-test",
                    "画面尺寸": "720x1280",
                    "画面比例": "9:16",
                    "备注": "运行环节配置：API/提示词/兜底源；任务记录自己的模型/参数优先。",
                },
            )
        ]
        field_names = [
            "环节",
            "配置类型",
            "状态",
            "API Key",
            "画面尺寸",
            "画面比例",
            "备注",
        ]
        fields = [{"field_name": name} for name in field_names]

        with patch.object(cleanup, "get_feishu_token", return_value="token"), \
             patch.object(cleanup, "list_fields", return_value=fields), \
             patch.object(cleanup, "list_views", return_value=[]), \
             patch.object(cleanup, "safe_list_records", return_value=records), \
             patch.object(cleanup, "write_backup"), \
             patch.object(cleanup, "create_missing_config_fields", return_value=[]), \
             patch.object(cleanup, "apply_record_updates", return_value=[]) as apply_updates, \
             patch.object(cleanup, "rename_legacy_views", return_value=[]), \
             patch.object(cleanup, "apply_view_definitions", return_value=[]), \
             patch.object(cleanup, "delete_obsolete_views", return_value=[]), \
             patch.object(cleanup, "ensure_unified_config_table_name", return_value={"status": "dry_run"}):
            cleanup.run_cleanup(write=False, backup_path=Path("/tmp/cleanup.json"))

        self.assertEqual(apply_updates.call_args.args[1], [])

    def test_ensure_view_falls_back_to_listing_after_create_without_id(self):
        existing = {}

        with patch.object(cleanup, "run_json", return_value={"data": {"view": {}}}), \
             patch.object(cleanup, "get_feishu_token", return_value="token"), \
             patch.object(cleanup, "list_views", return_value=[{"view_name": "00-生产运行配置", "view_id": "vew_created"}]):
            view_id = cleanup.ensure_view("app_token", "00-生产运行配置", existing)

        self.assertEqual(view_id, "vew_created")
        self.assertEqual(existing["00-生产运行配置"], "vew_created")


if __name__ == "__main__":
    unittest.main()
