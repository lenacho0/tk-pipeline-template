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
        self.assertEqual(patches["prod_img"], {"是否统一AI预设": "否"})
        self.assertEqual(patches["switch"], {"是否统一AI预设": "否"})
        self.assertEqual(patches["ng_img"], {"是否统一AI预设": "否"})
        self.assertEqual(patches["current"], {"是否统一AI预设": "是", "状态": "启用"})
        self.assertEqual(patches["candidate"]["状态"], "停用")
        self.assertEqual(patches["candidate"]["是否统一AI预设"], "否")
        self.assertIn("candidate", patches["candidate"]["备注"])
        self.assertEqual(patches["legacy"]["状态"], "停用")
        self.assertEqual(patches["legacy"]["是否统一AI预设"], "否")
        self.assertIn("归档", patches["legacy"]["备注"])
        self.assertIn("old note", patches["legacy"]["备注"])

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
        self.assertEqual(snapshot["records"][0]["has_api_key"], True)
        self.assertEqual(snapshot["records"][0]["提示词_chars"], 1000)
        self.assertNotIn("hellohello", serialized)

    def test_view_definitions_keep_daily_views_clean(self):
        field_names = [
            "环节",
            "是否统一AI预设",
            "应用表格",
            "AI供应商",
            "AI能力类型",
            "AI任务类型",
            "模型名称",
            "API 代理地址",
            "AI参数JSON",
            "调用方式",
            "提示词",
            "API Key",
            "状态",
            "备注",
        ]
        views = cleanup.build_view_definitions(field_names)

        self.assertEqual(list(views), [
            "00-生产运行配置",
            "01-统一AI Catalog",
            "02-链路提示词配置",
            "90-归档-旧预设",
            "99-全字段排错",
        ])
        self.assertNotIn("API Key", views["00-生产运行配置"]["visible_fields"])
        self.assertNotIn("提示词", views["00-生产运行配置"]["visible_fields"])
        self.assertEqual(
            views["01-统一AI Catalog"]["filter"],
            {"logic": "and", "conditions": [["是否统一AI预设", "intersects", ["是"]], ["状态", "intersects", ["启用"]]]},
        )
        self.assertIn("API Key", views["99-全字段排错"]["visible_fields"])
        self.assertIn("提示词", views["99-全字段排错"]["visible_fields"])

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
