import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import tk_model_config_center as center


def rec(record_id, **fields):
    return {"record_id": record_id, "fields": fields}


class ModelConfigCenterTests(unittest.TestCase):
    def setUp(self):
        center._TABLE_ID_CACHE.clear()
        center._TASK_DEFAULT_CACHE.clear()

    def test_build_plan_splits_catalog_and_task_defaults(self):
        records = [
            rec("img", 环节="图片生成-OTU", 模型名称="gpt-image-2", 状态="启用", **{"API 代理地址": "https://otuapi.com", "画面尺寸": "720x1280", "画面比例": "9:16", "调用方式": "专用 API"}),
            rec("video", 环节="分镜视频生成-OTU", 模型名称="veo_3_1-fast-fl", 状态="启用", **{"API 代理地址": "https://otuapi.com", "画面尺寸": "720x1280", "画面比例": "9:16", "调用方式": "专用 API"}),
            rec("story", 环节="故事板图片提示词拆分-Gemini", 模型名称="gemini-3.1-pro-preview", 状态="启用", **{"API 代理地址": "https://aihubmix.com/gemini", "调用方式": "Gemini 原生 SDK", "提示词": "story prompt"}),
            rec("edit", 环节="统一AI预设-Aitgenne / happyhorse-1.0-video-edit", 模型名称="Aitgenne / happyhorse-1.0-video-edit", 状态="启用", **{"AI供应商": "Aitgenne", "AI能力类型": "视频编辑", "API 代理地址": "https://api.aitgenne.com/v1", "画面尺寸": "720P", "调用方式": "happyhorse视频编辑"}),
            rec("old", 环节="统一AI预设-图片-OTU-GPTImage2-1K", 模型名称="gpt-image-2", 状态="停用", **{"API 代理地址": "https://otuapi.com"}),
        ]

        plan = center.build_config_center_plan(records)

        catalog_by_display = {item["显示名称"]: item for item in plan.model_catalog_rows}
        self.assertEqual(catalog_by_display["OTU / gpt-image-2"]["接入状态"], "已适配")
        self.assertEqual(catalog_by_display["OTU / gpt-image-2"]["测试状态"], "测试通过")
        self.assertEqual(catalog_by_display["OTU / gpt-image-2"]["是否生产可用"], "是")
        self.assertEqual(catalog_by_display["OTU / veo_3_1-fast-fl"]["能力类型"], "视频")

        default_keys = {(item["应用表格"], item["环节"]) for item in plan.task_default_rows}
        self.assertIn(("002-首尾帧视频生成表", "首帧图生成默认"), default_keys)
        self.assertIn(("002-首尾帧视频生成表", "首尾帧视频生成默认"), default_keys)
        self.assertIn(("004-故事板图片视频生成表", "故事板提示词拆分默认"), default_keys)
        self.assertIn(("006-视频编辑任务表", "视频编辑默认"), default_keys)
        self.assertNotIn(("002-首尾帧视频生成表", "文档拆分默认"), default_keys)

        edit_default = next(item for item in plan.task_default_rows if item["应用表格"] == "006-视频编辑任务表")
        self.assertEqual(edit_default["默认供应商"], "Aitgenne")
        self.assertEqual(edit_default["默认模型显示名称"], "Aitgenne / happyhorse-1.0-video-edit")
        self.assertEqual(edit_default["画面尺寸"], "720P")
        self.assertIn("source_config=统一AI预设-Aitgenne / happyhorse-1.0-video-edit", edit_default["备注"])

        archived = {item["record_id"]: item["fields"] for item in plan.legacy_archive_updates}
        self.assertEqual(archived["old"]["状态"], "停用")
        self.assertIn("归档", archived["old"]["备注"])

    def test_validate_default_rows_requires_production_catalog_model(self):
        rows = [
            {"应用表格": "002-首尾帧视频生成表", "环节": "首帧图生成默认", "默认模型显示名称": "OTU / gpt-image-2"},
            {"应用表格": "002-首尾帧视频生成表", "环节": "尾帧图生成默认", "默认模型显示名称": "OTU / not-ready"},
        ]
        catalog = [
            {"显示名称": "OTU / gpt-image-2", "接入状态": "已适配", "测试状态": "测试通过", "是否生产可用": "是"},
            {"显示名称": "OTU / not-ready", "接入状态": "已适配", "测试状态": "未测试", "是否生产可用": "否"},
        ]

        errors = center.validate_task_default_rows(rows, catalog)

        self.assertEqual(errors, ["002-首尾帧视频生成表 / 尾帧图生成默认 默认模型不可生产使用: OTU / not-ready"])

    def test_default_patch_does_not_override_user_values(self):
        fields = {
            "首帧图AI模型": "OTU / gpt-image-2-2K",
            "首帧图画面尺寸": "",
            "首帧图画面比例": "",
            "首帧图AI参数JSON": "",
        }
        default = {
            "默认供应商": "OTU",
            "默认模型显示名称": "OTU / gpt-image-2",
            "画面尺寸": "720x1280",
            "画面比例": "9:16",
            "AI参数JSON": '{"size":"720x1280"}',
        }

        patch = center.default_patch_for_slot(fields, "首帧图", default)

        self.assertNotIn("首帧图AI模型", patch)
        self.assertEqual(patch["首帧图画面尺寸"], "720x1280")
        self.assertEqual(patch["首帧图画面比例"], "9:16")
        self.assertEqual(patch["首帧图AI参数JSON"], '{"size":"720x1280"}')

    def test_default_patch_supports_explicit_task_field_names(self):
        default = {
            "默认模型显示名称": "OTU / omni_flash-10s",
            "画面尺寸": "720x1280",
            "画面比例": "9:16",
            "AI参数JSON": '{"seconds":"10"}',
        }

        patch = center.default_patch_for_fields(
            {"视频AI模型": "", "Omni画面尺寸": "", "Omni画面比例": "", "视频AI参数JSON": ""},
            default,
            model_field="视频AI模型",
            size_field="Omni画面尺寸",
            ratio_field="Omni画面比例",
            params_field="视频AI参数JSON",
        )

        self.assertEqual(patch["视频AI模型"], "OTU / omni_flash-10s")
        self.assertEqual(patch["Omni画面尺寸"], "720x1280")
        self.assertEqual(patch["Omni画面比例"], "9:16")
        self.assertEqual(patch["视频AI参数JSON"], '{"seconds":"10"}')

    def test_default_patch_ignores_unmapped_prompt_field(self):
        default = {
            "默认模型显示名称": "OTU / gpt-image-2",
            "画面尺寸": "720x1280",
            "画面比例": "9:16",
            "系统提示词": "prompt should not be written without a target field",
        }

        patch = center.default_patch_for_fields(
            {"首帧图AI模型": "", "首帧图画面尺寸": "", "首帧图画面比例": ""},
            default,
            model_field="首帧图AI模型",
            size_field="首帧图画面尺寸",
            ratio_field="首帧图画面比例",
        )

        self.assertNotIn("", patch)
        self.assertEqual(patch["首帧图AI模型"], "OTU / gpt-image-2")

    def test_apply_task_default_to_record_writes_only_empty_fields(self):
        updates = []

        def update_fn(token, table_id, record_id, fields):
            updates.append(fields)

        with mock.patch.object(center, "load_task_default_fields", return_value={
            "默认模型显示名称": "OTU / gpt-image-2",
            "画面尺寸": "720x1280",
            "画面比例": "9:16",
            "AI参数JSON": "{}",
        }):
            merged = center.apply_task_default_to_record(
                "token",
                "table",
                "record",
                {"首帧图AI模型": "OTU / gpt-image-2-2K", "首帧图画面尺寸": ""},
                app_table="002-首尾帧视频生成表",
                stage="首帧图生成默认",
                model_field="首帧图AI模型",
                size_field="首帧图画面尺寸",
                update_fn=update_fn,
            )

        self.assertEqual(updates, [{"首帧图画面尺寸": "720x1280"}])
        self.assertEqual(merged["首帧图AI模型"], "OTU / gpt-image-2-2K")
        self.assertEqual(merged["首帧图画面尺寸"], "720x1280")

    def test_load_task_default_fields_uses_openapi_table_lookup(self):
        rows = [
            rec("default1", **{
                "应用表格": "002-首尾帧视频生成表",
                "环节": "首帧图生成默认",
                "默认模型显示名称": "OTU / gpt-image-2",
                "状态": "启用",
            })
        ]

        with mock.patch.object(center, "list_tables_api", return_value={center.TASK_DEFAULT_TABLE_NAME: "tbl_defaults"}), \
             mock.patch.object(center, "safe_list_records", return_value=rows):
            fields = center.load_task_default_fields("real-token", "002-首尾帧视频生成表", "首帧图生成默认")

        self.assertEqual(fields["默认模型显示名称"], "OTU / gpt-image-2")

    def test_load_task_default_fields_fails_when_missing_or_ambiguous(self):
        with mock.patch.object(center, "list_tables_api", return_value={}):
            with self.assertRaisesRegex(RuntimeError, "找不到.*初始化-任务默认模型配置"):
                center.load_task_default_fields("real-token", "002-首尾帧视频生成表", "首帧图生成默认")

        center._TABLE_ID_CACHE.clear()
        center._TASK_DEFAULT_CACHE.clear()
        duplicate_rows = [
            rec("default1", **{"应用表格": "002-首尾帧视频生成表", "环节": "首帧图生成默认", "状态": "启用"}),
            rec("default2", **{"应用表格": "002-首尾帧视频生成表", "环节": "首帧图生成默认", "状态": "启用"}),
        ]
        with mock.patch.object(center, "list_tables_api", return_value={center.TASK_DEFAULT_TABLE_NAME: "tbl_defaults"}), \
             mock.patch.object(center, "safe_list_records", return_value=duplicate_rows):
            with self.assertRaisesRegex(RuntimeError, "默认配置重复"):
                center.load_task_default_fields("real-token", "002-首尾帧视频生成表", "首帧图生成默认")

    def test_apply_task_default_to_record_fails_when_field_filter_drops_default(self):
        with mock.patch.object(center, "load_task_default_fields", return_value={
            "默认模型显示名称": "OTU / gpt-image-2",
            "画面尺寸": "720x1280",
        }):
            with self.assertRaisesRegex(RuntimeError, "默认配置字段不存在"):
                center.apply_task_default_to_record(
                    "token",
                    "table",
                    "record",
                    {"首帧图AI模型": "", "首帧图画面尺寸": ""},
                    app_table="002-首尾帧视频生成表",
                    stage="首帧图生成默认",
                    model_field="首帧图AI模型",
                    size_field="首帧图画面尺寸",
                    field_filter=lambda token, table, patch: {"首帧图AI模型": patch["首帧图AI模型"]},
                    update_fn=mock.Mock(),
                )

    def test_runtime_default_backfill_dry_run_and_write(self):
        spec = center.RuntimeDefaultBackfillSpec(
            table_key="first_last_video",
            app_table="002-首尾帧视频生成表",
            stage="首帧图生成默认",
            status_field="首帧图生成状态",
            model_field="首帧图AI模型",
            size_field="首帧图画面尺寸",
            ratio_field="首帧图画面比例",
            params_field="首帧图AI参数JSON",
        )
        records = [
            rec("needs", 任务名称="scene1", 首帧图生成状态="成功", 首帧图AI模型="", 首帧图画面尺寸="", 首帧图画面比例=""),
            rec("manual", 任务名称="scene2", 首帧图生成状态="成功", 首帧图AI模型="OTU / gpt-image-2-2K", 首帧图画面尺寸="1080x1920", 首帧图画面比例="9:16"),
            rec("idle", 任务名称="scene3", 首帧图生成状态="不触发", 首帧图AI模型="", 首帧图画面尺寸="", 首帧图画面比例=""),
        ]
        updates = []

        with mock.patch.object(center, "TABLE_IDS_BY_KEY", {"first_last_video": "tbl_first_last"}), \
             mock.patch.object(center, "load_task_default_fields", return_value={
                 "默认模型显示名称": "OTU / gpt-image-2",
                 "画面尺寸": "720x1280",
                 "画面比例": "9:16",
             }), \
             mock.patch.object(center, "list_field_names_api", return_value={"首帧图AI模型", "首帧图画面尺寸", "首帧图画面比例", "首帧图AI参数JSON"}), \
             mock.patch.object(center, "safe_list_records", return_value=records):
            dry = center.backfill_runtime_defaults("token", specs=[spec], write=False, update_fn=lambda *args: updates.append(args))
            written = center.backfill_runtime_defaults("token", specs=[spec], write=True, update_fn=lambda *args: updates.append(args))

        self.assertEqual(updates, [("token", "tbl_first_last", "needs", {
            "首帧图AI模型": "OTU / gpt-image-2",
            "首帧图画面尺寸": "720x1280",
            "首帧图画面比例": "9:16",
        })])
        self.assertEqual(dry["totals"]["would_update"], 1)
        self.assertEqual(written["totals"]["updated"], 1)
        self.assertEqual(written["stages"][0]["skipped_no_patch"], 1)

    def test_runtime_default_backfill_filters_missing_schema_fields(self):
        spec = center.RuntimeDefaultBackfillSpec(
            table_key="first_last_video",
            app_table="002-首尾帧视频生成表",
            stage="首帧图生成默认",
            status_field="首帧图生成状态",
            model_field="首帧图AI模型",
            size_field="首帧图画面尺寸",
            ratio_field="首帧图画面比例",
        )
        updates = []

        with mock.patch.object(center, "TABLE_IDS_BY_KEY", {"first_last_video": "tbl_first_last"}), \
             mock.patch.object(center, "load_task_default_fields", return_value={
                 "默认模型显示名称": "OTU / gpt-image-2",
                 "画面尺寸": "720x1280",
                 "画面比例": "9:16",
             }), \
             mock.patch.object(center, "list_field_names_api", return_value={"首帧图AI模型", "首帧图画面尺寸"}), \
             mock.patch.object(center, "safe_list_records", return_value=[
                 rec("needs", 首帧图生成状态="成功", 首帧图AI模型="", 首帧图画面尺寸="", 首帧图画面比例=""),
             ]):
            result = center.backfill_runtime_defaults("token", specs=[spec], write=True, update_fn=lambda *args: updates.append(args))

        self.assertEqual(updates, [("token", "tbl_first_last", "needs", {
            "首帧图AI模型": "OTU / gpt-image-2",
            "首帧图画面尺寸": "720x1280",
        })])
        self.assertEqual(result["stages"][0]["schema_missing_fields"], ["首帧图画面比例"])

    def test_creation_defaults_can_replace_legacy_placeholders(self):
        default = {"默认模型显示名称": "OTU / veo_3_1-fast-fl"}

        patch = center.default_patch_for_fields(
            {"视频生成模型": "默认（配置表）"},
            default,
            model_field="视频生成模型",
            placeholder_values=("默认（配置表）",),
        )

        self.assertEqual(patch, {"视频生成模型": "OTU / veo_3_1-fast-fl"})

    def test_runtime_defaults_keep_script_doc_video_and_video_edit_slots(self):
        specs = {(item.table_key, item.stage): item for item in center.RUNTIME_DEFAULT_SPECS}
        backfill = {(item.table_key, item.stage): item for item in center.RUNTIME_DEFAULT_BACKFILL_SPECS}

        script_video = specs[("script_doc_shots", "分镜视频生成默认")]
        self.assertEqual(script_video.source_config_stage, "分镜视频生成-Veo")
        self.assertEqual(script_video.slot_name, "视频")
        self.assertIn(("script_doc_shots", "分镜视频生成默认"), backfill)

        video_edit = specs[("video_edit", "视频编辑默认")]
        self.assertEqual(video_edit.source_config_stage, center.VIDEO_EDIT_SOURCE_CONFIG_STAGE)
        self.assertEqual(video_edit.slot_name, "视频编辑")
        self.assertIn(("video_edit", "视频编辑默认"), backfill)


if __name__ == "__main__":
    unittest.main()
