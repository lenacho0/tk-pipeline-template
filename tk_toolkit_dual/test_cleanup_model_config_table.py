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
        })
        self.assertEqual(patches["switch"], {"是否统一AI预设": "否", "配置类型": "路由开关", "生效来源": "线上配置"})
        self.assertEqual(patches["ng_img"], {
            "是否统一AI预设": "否",
            "配置类型": "运行环节",
            "生效来源": "线上配置",
            "供应商": "OTU",
            "能力类型": "图片",
            "画面尺寸": "720x1280",
            "画面比例": "9:16",
        })
        self.assertEqual(patches["current"], {"是否统一AI预设": "是", "配置类型": "模型目录", "生效来源": "线上配置", "状态": "启用"})
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

        self.assertEqual(patches["auto"], {"配置类型": "自动审核", "生效来源": "线上配置"})

    def test_plan_preserves_existing_single_source_row_types(self):
        records = [
            rec("default", **{"配置类型": "任务默认", "应用表格": "002-首尾帧视频生成表", "任务环节": "首帧图生成默认", "环节": "图片生成-OTU", "生效来源": "线上配置", "状态": "启用"}),
            rec("catalog", **{"配置类型": "模型目录", "环节": "图片生成-OTU", "显示名称": "OTU / gpt-image-2", "状态": "启用", "生效来源": "线上配置"}),
        ]

        plan = cleanup.build_cleanup_plan(records)

        self.assertEqual(plan.record_updates, [])

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

        self.assertEqual(plan.record_updates, [])

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
            "04-提示词配置",
            "90-归档旧配置",
            "99-排错全字段",
        ])
        self.assertIn("API Key", views["01-运行配置-管理员"]["visible_fields"])
        self.assertIn("提示词", views["01-运行配置-管理员"]["visible_fields"])
        self.assertIn("画面尺寸", views["02-任务默认配置"]["visible_fields"])
        self.assertIn("画面比例", views["02-任务默认配置"]["visible_fields"])
        self.assertEqual(
            views["01-运行配置-管理员"]["filter"],
            {"logic": "and", "conditions": [["配置类型", "intersects", ["运行环节", "路由开关", "自动审核"]], ["状态", "intersects", ["启用", "测试中"]]]},
        )
        self.assertIn("API Key", views["99-排错全字段"]["visible_fields"])
        self.assertIn("提示词", views["99-排错全字段"]["visible_fields"])

    def test_blank_status_runtime_stage_is_marked_enabled(self):
        records = [
            rec("veo", 环节=cleanup.AIHUBMIX_VEO_STAGE, 模型名称="veo-3.1-fast-generate-preview", 状态=""),
        ]

        plan = cleanup.build_cleanup_plan(records)
        patches = {item.record_id: item.fields for item in plan.record_updates}

        self.assertEqual(patches["veo"]["状态"], "启用")

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
        self.assertEqual([item["name"] for item in specs["默认槽位"]["options"]], ["stage", "参考图", "关键帧", "视频", "首帧图", "尾帧图", "分镜图", "故事板图片", "图片", "口播音频", "视频编辑"])
        self.assertIn("供应商", specs)
        self.assertIn("能力类型", specs)
        self.assertIn("显示名称", specs)
        self.assertIn("任务环节", specs)

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
            "04-提示词配置",
            "90-归档旧配置",
            "99-排错全字段",
        ])
        self.assertIn("API Key", views["01-运行配置-管理员"]["visible_fields"])
        self.assertIn("应用表格", views["02-任务默认配置"]["visible_fields"])
        self.assertIn("默认槽位", views["02-任务默认配置"]["visible_fields"])
        self.assertIn("显示名称", views["03-模型目录"]["visible_fields"])
        self.assertIn("提示词", views["04-提示词配置"]["visible_fields"])

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
