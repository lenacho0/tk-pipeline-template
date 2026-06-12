import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import tk_model_config_center as center
import common
import repair_script_doc_shot_video_otu_defaults as repair_video_defaults


def rec(record_id, **fields):
    return {"record_id": record_id, "fields": fields}


class ModelConfigCenterTests(unittest.TestCase):
    def setUp(self):
        center._TABLE_ID_CACHE.clear()
        center._TASK_DEFAULT_CACHE.clear()
        center._STAGE_CONFIG_CACHE.clear()

    def test_build_plan_splits_catalog_and_task_defaults(self):
        records = [
            rec("img", 环节="图片生成-OTU", 模型名称="gpt-image-2", 状态="启用", **{"API 代理地址": "https://otuapi.com", "画面尺寸": "720x1280", "画面比例": "9:16", "调用方式": "专用 API"}),
            rec("video", 环节="分镜视频生成-OTU", 模型名称="veo_3_1-fast-fl", 状态="启用", **{"API 代理地址": "https://otuapi.com", "画面尺寸": "720x1280", "画面比例": "9:16", "调用方式": "专用 API"}),
            rec("edit", 环节="视频编辑-HappyHorse", 模型名称="Aitgenne / happyhorse-1.0-video-edit", 状态="启用", **{"AI供应商": "Aitgenne", "AI能力类型": "视频编辑", "API 代理地址": "https://api.aitgenne.com/v1", "画面尺寸": "720P", "调用方式": "happyhorse视频编辑"}),
            rec("old", 环节="统一AI预设-图片-OTU-GPTImage2-1K", 模型名称="gpt-image-2", 状态="停用", **{"API 代理地址": "https://otuapi.com"}),
        ]

        plan = center.build_config_center_plan(records)

        catalog_by_display = {item["显示名称"]: item for item in plan.model_catalog_rows}
        self.assertEqual(catalog_by_display["OTU / gpt-image-2"]["接入状态"], "已适配")
        self.assertEqual(catalog_by_display["OTU / gpt-image-2"]["测试状态"], "测试通过")
        self.assertEqual(catalog_by_display["OTU / gpt-image-2"]["是否生产可用"], "是")
        self.assertEqual(catalog_by_display["OTU / veo_3_1-fast-fl"]["能力类型"], "视频")

        default_keys = {(item["应用表格"], item["任务环节"]) for item in plan.task_default_rows}
        self.assertIn(("002-首尾帧视频生成表", "首帧图生成默认"), default_keys)
        self.assertIn(("002-首尾帧视频生成表", "首尾帧视频生成默认"), default_keys)
        self.assertIn(("008-图生视频生成表", "图片生成默认"), default_keys)
        self.assertIn(("008-图生视频生成表", "图生视频生成默认"), default_keys)
        self.assertIn(("006-视频编辑任务表", "视频编辑默认"), default_keys)
        self.assertNotIn(("002-首尾帧视频生成表", "文档拆分默认"), default_keys)

        edit_default = next(item for item in plan.task_default_rows if item["应用表格"] == "006-视频编辑任务表")
        self.assertEqual(edit_default["配置类型"], "任务默认")
        self.assertEqual(edit_default["任务环节"], "视频编辑默认")
        self.assertEqual(edit_default["环节"], center.VIDEO_EDIT_SOURCE_CONFIG_STAGE)
        self.assertEqual(edit_default["默认供应商"], "Aitgenne")
        self.assertEqual(edit_default["默认模型显示名称"], "Aitgenne / happyhorse-1.0-video-edit")
        self.assertEqual(edit_default["画面尺寸"], "720P")
        self.assertIn(f"source_config={center.VIDEO_EDIT_SOURCE_CONFIG_STAGE}", edit_default["备注"])

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
            {"视频生成模型": "", "Omni画面尺寸": "", "Omni画面比例": "", "视频AI参数JSON": ""},
            default,
            model_field="视频生成模型",
            size_field="Omni画面尺寸",
            ratio_field="Omni画面比例",
            params_field="视频AI参数JSON",
        )

        self.assertEqual(patch["视频生成模型"], "OTU / omni_flash-10s")
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

    def test_load_task_default_fields_does_not_fallback_to_legacy_table(self):
        with mock.patch.object(center, "safe_list_records", return_value=[]), \
             mock.patch.object(center, "list_tables_api") as list_tables:
            with self.assertRaisesRegex(RuntimeError, "初始化-模型与API配置.*任务默认"):
                center.load_task_default_fields("real-token", "002-首尾帧视频生成表", "首帧图生成默认")

        list_tables.assert_not_called()

    def test_load_task_default_fields_uses_single_config_table_runtime_defaults(self):
        rows = [
            rec("runtime_default", **{
                "配置类型": "任务默认",
                "应用表格": "002-首尾帧视频生成表",
                "任务环节": "首帧图生成默认",
                "环节": "图片生成-OTU",
                "模型名称": "OTU / gpt-image-2",
                "供应商": "OTU",
                "画面尺寸": "720x1280",
                "画面比例": "9:16",
                "AI参数JSON": '{"size":"720x1280"}',
                "生效来源": "线上配置",
                "状态": "启用",
            })
        ]

        with mock.patch.object(center, "safe_list_records", return_value=rows):
            fields = center.load_task_default_fields("real-token", "002-首尾帧视频生成表", "首帧图生成默认")

        self.assertEqual(fields["默认供应商"], "OTU")
        self.assertEqual(fields["默认模型显示名称"], "OTU / gpt-image-2")
        self.assertEqual(fields["画面尺寸"], "720x1280")
        self.assertEqual(fields["画面比例"], "9:16")
        self.assertEqual(fields["AI参数JSON"], '{"size":"720x1280"}')

    def test_task_default_model_name_overrides_stale_display_name(self):
        rows = [
            rec("runtime_default", **{
                "配置类型": "任务默认",
                "应用表格": "001-多角色首尾帧生成表",
                "任务环节": "视频片段生成默认",
                "供应商": "Aitgenne",
                "模型名称": "Aitgenne / veo_3_1_fast_vip",
                "显示名称": "OTU / veo_3_1-fast-fl",
                "画面尺寸": "720x1280",
                "画面比例": "9:16",
                "生效来源": "线上配置",
                "状态": "启用",
            })
        ]

        with mock.patch.object(center, "safe_list_records", return_value=rows):
            fields = center.load_task_default_fields("real-token", "001-多角色首尾帧生成表", "视频片段生成默认")

        self.assertEqual(fields["默认供应商"], "Aitgenne")
        self.assertEqual(fields["默认模型显示名称"], "Aitgenne / veo_3_1_fast_vip")

    def test_nine_grid_defaults_keep_legacy_name_aliases(self):
        rows = [
            rec("runtime_default", **{
                "配置类型": "任务默认",
                "应用表格": "005-多图九宫格视频生成表",
                "任务环节": "九宫格图片生成默认",
                "环节": "多图九宫格图片生成",
                "模型名称": "OTU / gpt-image-2",
                "供应商": "OTU",
                "画面尺寸": "720x1280",
                "画面比例": "9:16",
                "AI参数JSON": '{"size":"720x1280"}',
                "生效来源": "线上配置",
                "状态": "启用",
            }),
            rec("runtime_stage", **{
                "配置类型": "运行环节",
                "环节": "多图九宫格图片生成",
                "模型名称": "gpt-image-2",
                "供应商": "OTU",
                "API Key": "sk-image",
                "API 代理地址": "https://otuapi.com",
                "画面尺寸": "720x1280",
                "画面比例": "9:16",
                "生效来源": "线上配置",
                "状态": "启用",
            }),
        ]

        with mock.patch.object(center, "safe_list_records", return_value=rows):
            default_fields = center.load_task_default_fields(
                "real-token",
                "005-多图宫格视频生成表",
                "宫格图片生成默认",
            )
            record_id, cfg = center.load_stage_config_fields(
                "real-token",
                "多图宫格图片生成",
                default_model="gpt-image-2",
                default_api_base="https://fallback.example",
            )

        self.assertEqual(default_fields["默认模型显示名称"], "OTU / gpt-image-2")
        self.assertEqual(default_fields["画面尺寸"], "720x1280")
        self.assertEqual(record_id, "runtime_stage")
        self.assertEqual(cfg["provider"], "OTU")
        self.assertEqual(cfg["api_key"], "sk-image")

    def test_load_task_default_fields_ignores_code_default_rows(self):
        rows = [
            rec("runtime_default", **{
                "配置类型": "任务默认",
                "应用表格": "002-首尾帧视频生成表",
                "任务环节": "首帧图生成默认",
                "模型名称": "OTU / gpt-image-2",
                "生效来源": "代码默认",
                "状态": "启用",
            })
        ]

        with mock.patch.object(center, "safe_list_records", return_value=rows):
            fields = center.load_task_default_fields("real-token", "002-首尾帧视频生成表", "首帧图生成默认")

        self.assertIsNone(fields)

    def test_load_stage_config_from_single_table_by_stage(self):
        rows = [
            rec("image_stage", **{
                "配置类型": "运行环节",
                "环节": "图片生成-OTU",
                "模型名称": "OTU / gpt-image-2",
                "供应商": "OTU",
                "API Key": "sk-image",
                "API 代理地址": "https://otuapi.com",
                "调用方式": "OTU /v1/videos JSON image task",
                "画面尺寸": "720x1280",
                "画面比例": "9:16",
                "AI参数JSON": '{"size":"720x1280"}',
                "提示词": "image prompt",
                "生效来源": "线上配置",
                "状态": "启用",
            })
        ]

        with mock.patch.object(center, "safe_list_records", return_value=rows):
            record_id, cfg = center.load_stage_config_fields(
                "real-token",
                "图片生成-OTU",
                default_model="gpt-image-2",
                default_api_base="https://fallback.example",
            )

        self.assertEqual(record_id, "image_stage")
        self.assertEqual(cfg["model"], "gpt-image-2")
        self.assertEqual(cfg["provider"], "OTU")
        self.assertEqual(cfg["api_key"], "sk-image")
        self.assertEqual(cfg["api_base"], "https://otuapi.com")
        self.assertEqual(cfg["call_type"], "OTU /v1/videos JSON image task")
        self.assertEqual(cfg["size"], "720x1280")
        self.assertEqual(cfg["aspect_ratio"], "9:16")
        self.assertEqual(cfg["params"], '{"size":"720x1280"}')
        self.assertEqual(cfg["prompt"], "image prompt")

    def test_load_stage_config_uses_code_default_when_source_says_code_default(self):
        rows = [
            rec("image_stage", **{
                "配置类型": "运行环节",
                "环节": "图片生成-OTU",
                "模型名称": "OTU / gpt-image-2-4K",
                "API Key": "sk-image",
                "API 代理地址": "https://otuapi.com",
                "生效来源": "代码默认",
                "状态": "启用",
            })
        ]

        with mock.patch.object(center, "safe_list_records", return_value=rows):
            record_id, cfg = center.load_stage_config_fields(
                "real-token",
                "图片生成-OTU",
                default_model="gpt-image-2",
                default_api_base="https://fallback.example",
                default_size="720x1280",
            )

        self.assertEqual(record_id, "image_stage")
        self.assertEqual(cfg["model"], "gpt-image-2")
        self.assertEqual(cfg["api_key"], "sk-image")
        self.assertEqual(cfg["api_base"], "https://fallback.example")
        self.assertEqual(cfg["size"], "720x1280")

    def test_stage_config_cache_keeps_code_default_fallbacks_separate(self):
        rows = [
            rec("image_stage", **{
                "配置类型": "运行环节",
                "环节": "图片生成-OTU",
                "API Key": "sk-image",
                "生效来源": "代码默认",
                "状态": "启用",
            })
        ]

        with mock.patch.object(center, "safe_list_records", return_value=rows):
            _, first = center.load_stage_config_fields(
                "real-token",
                "图片生成-OTU",
                default_model="gpt-image-2",
                default_api_base="https://fallback-a.example",
                default_size="720x1280",
            )
            _, second = center.load_stage_config_fields(
                "real-token",
                "图片生成-OTU",
                default_model="veo_3_1-fast-fl",
                default_api_base="https://fallback-b.example",
                default_size="1080x1920",
            )

        self.assertEqual(first["model"], "gpt-image-2")
        self.assertEqual(first["api_base"], "https://fallback-a.example")
        self.assertEqual(first["size"], "720x1280")
        self.assertEqual(second["model"], "veo_3_1-fast-fl")
        self.assertEqual(second["api_base"], "https://fallback-b.example")
        self.assertEqual(second["size"], "1080x1920")

    def test_common_get_model_config_can_read_by_stage_name(self):
        rows = [
            rec("image_stage", **{
                "配置类型": "运行环节",
                "环节": "图片生成-OTU",
                "模型名称": "OTU / gpt-image-2",
                "供应商": "OTU",
                "API Key": "sk-image",
                "API 代理地址": "https://otuapi.com",
                "调用方式": "OTU /v1/videos JSON image task",
                "画面尺寸": "720x1280",
                "画面比例": "9:16",
                "AI参数JSON": '{"size":"720x1280"}',
                "提示词": "image prompt",
                "生效来源": "线上配置",
                "状态": "启用",
            })
        ]

        with mock.patch.object(common, "safe_list_records", return_value=rows):
            cfg = common.get_model_config("token", "stage:图片生成-OTU")

        self.assertEqual(cfg["model"], "OTU / gpt-image-2")
        self.assertEqual(cfg["provider"], "OTU")
        self.assertEqual(cfg["api_key"], "sk-image")
        self.assertEqual(cfg["api_base"], "https://otuapi.com")
        self.assertEqual(cfg["call_type"], "OTU /v1/videos JSON image task")
        self.assertEqual(cfg["size"], "720x1280")
        self.assertEqual(cfg["aspect_ratio"], "9:16")
        self.assertEqual(cfg["params"], '{"size":"720x1280"}')
        self.assertEqual(cfg["prompt"], "image prompt")

    def test_common_get_model_config_blanks_online_fields_for_code_default(self):
        rows = [
            rec("image_stage", **{
                "配置类型": "运行环节",
                "环节": "图片生成-OTU",
                "模型名称": "OTU / gpt-image-2-4K",
                "API Key": "sk-image",
                "API 代理地址": "https://otuapi.com",
                "提示词": "online prompt",
                "生效来源": "代码默认",
                "状态": "启用",
            })
        ]

        with mock.patch.object(common, "safe_list_records", return_value=rows):
            cfg = common.get_model_config("token", "stage:图片生成-OTU")

        self.assertEqual(cfg["model"], "")
        self.assertEqual(cfg["api_key"], "sk-image")
        self.assertEqual(cfg["api_base"], "")
        self.assertEqual(cfg["prompt"], "")

    def test_load_task_default_fields_fails_when_missing_or_ambiguous(self):
        with mock.patch.object(center, "safe_list_records", return_value=[]):
            with self.assertRaisesRegex(RuntimeError, "初始化-模型与API配置.*任务默认"):
                center.load_task_default_fields("real-token", "002-首尾帧视频生成表", "首帧图生成默认")

        center._TABLE_ID_CACHE.clear()
        center._TASK_DEFAULT_CACHE.clear()
        duplicate_rows = [
            rec("default1", **{"配置类型": "任务默认", "应用表格": "002-首尾帧视频生成表", "任务环节": "首帧图生成默认", "状态": "启用"}),
            rec("default2", **{"配置类型": "任务默认", "应用表格": "002-首尾帧视频生成表", "任务环节": "首帧图生成默认", "状态": "启用"}),
        ]
        with mock.patch.object(center, "safe_list_records", return_value=duplicate_rows):
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
            {"视频生成模型": "OTU / 默认（配置表）"},
            default,
            model_field="视频生成模型",
            placeholder_values=("默认（配置表）",),
        )

        self.assertEqual(patch, {"视频生成模型": "OTU / veo_3_1-fast-fl"})

    def test_video_defaults_can_fill_channel_from_default_provider(self):
        default = {
            "默认供应商": "OTU",
            "默认模型显示名称": "OTU / veo_3_1-fast-fl",
        }

        patch = center.default_patch_for_fields(
            {"视频通道": "", "视频生成模型": "默认（配置表）"},
            default,
            channel_field="视频通道",
            model_field="视频生成模型",
            placeholder_values=("默认（配置表）",),
        )

        self.assertEqual(patch, {
            "视频通道": "OTU",
            "视频生成模型": "OTU / veo_3_1-fast-fl",
        })

    def test_video_defaults_replace_legacy_otu_model_and_sync_channel(self):
        default = {
            "默认供应商": "Aitgenne",
            "默认模型显示名称": "Aitgenne / veo_3_1_fast_vip",
        }

        patch = center.default_patch_for_fields(
            {"视频通道": "OTU", "视频生成模型": "OTU / veo_3_1-fast-fl"},
            default,
            channel_field="视频通道",
            model_field="视频生成模型",
            placeholder_values=("OTU / veo_3_1-fast-fl", "默认（配置表）"),
        )

        self.assertEqual(patch, {
            "视频通道": "Aitgenne",
            "视频生成模型": "Aitgenne / veo_3_1_fast_vip",
        })

    def test_first_last_video_default_repair_only_updates_unfinished_records(self):
        records = [
            rec("success", 任务名称="done", 视频生成状态="成功", 视频任务ID="task_done", 视频通道="OTU", 视频生成模型="OTU / veo_3_1-fast-fl"),
            rec("failed_with_task", 任务名称="failed with task", 视频生成状态="失败", 视频任务ID="task_old", 视频通道="OTU", 视频生成模型="OTU / veo_3_1-fast-fl"),
            rec("failed_empty", 任务名称="failed empty", 视频生成状态="失败", 视频任务ID="", 视频通道="OTU", 视频生成模型="OTU / veo_3_1-fast-fl"),
            rec("pending", 任务名称="pending", 视频生成状态="待生成", 视频任务ID="", 视频通道="OTU", 视频生成模型="OTU / veo_3_1-fast-fl"),
        ]
        updates = []

        with mock.patch.object(center, "TABLE_IDS_BY_KEY", {"first_last_video": "tbl_first_last"}), \
             mock.patch.object(center, "load_task_default_fields", return_value={
                 "默认供应商": "Aitgenne",
                 "默认模型显示名称": "Aitgenne / veo_3_1_fast_vip",
                 "画面尺寸": "720x1280",
                 "画面比例": "9:16",
             }), \
             mock.patch.object(center, "list_field_names_api", return_value={"视频通道", "视频生成模型", "视频画面尺寸", "视频画面比例", "视频AI参数JSON"}), \
             mock.patch.object(center, "safe_list_records", return_value=records):
            result = center.backfill_runtime_defaults(
                "token",
                specs=[spec for spec in center.FIRST_LAST_VIDEO_DEFAULT_REPAIR_SPECS if spec.table_key == "first_last_video"],
                write=True,
                update_fn=lambda *args: updates.append(args),
            )

        self.assertEqual(updates, [
            ("token", "tbl_first_last", "failed_empty", {
                "视频通道": "Aitgenne",
                "视频生成模型": "Aitgenne / veo_3_1_fast_vip",
                "视频画面尺寸": "720x1280",
                "视频画面比例": "9:16",
            }),
            ("token", "tbl_first_last", "pending", {
                "视频通道": "Aitgenne",
                "视频生成模型": "Aitgenne / veo_3_1_fast_vip",
                "视频画面尺寸": "720x1280",
                "视频画面比例": "9:16",
            }),
        ])
        self.assertEqual(result["stages"][0]["skipped_status"], 1)
        self.assertEqual(result["stages"][0]["skipped_existing_task"], 1)
        self.assertEqual(result["totals"]["updated"], 2)

    def test_multi_role_video_default_repair_only_updates_video_clip_records(self):
        records = [
            rec("parent", 任务名称="parent", 记录类型="母任务", 记录状态="有效", 视频生成状态="", 视频任务ID="", 视频通道="", 视频生成模型=""),
            rec("asset", 任务名称="asset", 记录类型="参考资产", 记录状态="有效", 视频生成状态="", 视频任务ID="", 视频通道="", 视频生成模型=""),
            rec("clip", 任务名称="clip", 记录类型="视频片段", 记录状态="有效", 视频生成状态="不触发", 视频任务ID="", 视频通道="OTU", 视频生成模型="OTU / veo_3_1-fast-fl"),
        ]
        updates = []

        with mock.patch.object(center, "TABLE_IDS_BY_KEY", {"multi_role_first_last": "tbl_multi"}), \
             mock.patch.object(center, "load_task_default_fields", return_value={
                 "默认供应商": "Aitgenne",
                 "默认模型显示名称": "Aitgenne / veo_3_1_fast_vip",
                 "画面尺寸": "720x1280",
                 "画面比例": "9:16",
             }), \
             mock.patch.object(center, "list_field_names_api", return_value={"视频通道", "视频生成模型", "视频画面尺寸", "视频画面比例", "视频AI参数JSON"}), \
             mock.patch.object(center, "safe_list_records", return_value=records):
            result = center.backfill_runtime_defaults(
                "token",
                specs=[spec for spec in center.FIRST_LAST_VIDEO_DEFAULT_REPAIR_SPECS if spec.table_key == "multi_role_first_last"],
                write=True,
                update_fn=lambda *args: updates.append(args),
            )

        self.assertEqual(updates, [("token", "tbl_multi", "clip", {
            "视频通道": "Aitgenne",
            "视频生成模型": "Aitgenne / veo_3_1_fast_vip",
            "视频画面尺寸": "720x1280",
            "视频画面比例": "9:16",
        })])
        self.assertEqual(result["stages"][0]["skipped_record_type"], 2)
        self.assertEqual(result["totals"]["updated"], 1)

    def test_unified_repair_script_matches_prefixed_otu_default_placeholder(self):
        self.assertTrue(repair_video_defaults.is_candidate({
            "视频生成状态": "待生成",
            "视频通道": "OTU",
            "视频生成模型": "OTU / 默认（配置表）",
        }))
        self.assertFalse(repair_video_defaults.is_candidate({
            "视频生成状态": "",
            "视频通道": "",
            "视频生成模型": "",
        }))

    def test_unified_repair_script_covers_all_video_channel_tables(self):
        specs = {
            (item.table_key, item.default_stage, item.table_name)
            for item in repair_video_defaults.TABLE_REPAIR_SPECS
        }

        self.assertEqual(specs, {
            ("first_last_video", "首尾帧视频生成默认", "002-首尾帧视频生成表"),
            ("multi_role_first_last", "视频片段生成默认", "001-多角色首尾帧生成表"),
            ("script_doc_shots", "分镜视频生成默认", "003-3脚本文档-分镜生产表"),
        })

    def test_runtime_defaults_keep_script_doc_video_and_video_edit_slots(self):
        specs = {(item.table_key, item.stage): item for item in center.RUNTIME_DEFAULT_SPECS}
        backfill = {(item.table_key, item.stage): item for item in center.RUNTIME_DEFAULT_BACKFILL_SPECS}

        self.assertEqual(center.TASK_TABLES["prompt_image_video"], "008-图生视频生成表")
        image_default = specs[("prompt_image_video", "图片生成默认")]
        self.assertEqual(image_default.source_config_stage, "图片生成-OTU")
        self.assertEqual(image_default.slot_name, "图片")
        self.assertEqual(image_default.dispatch_stage_name, "008图生视频图片生成")
        self.assertEqual(image_default.max_concurrency, "10")
        video_default = specs[("prompt_image_video", "图生视频生成默认")]
        self.assertEqual(video_default.source_config_stage, "分镜视频生成-OTU")
        self.assertEqual(video_default.slot_name, "视频")
        self.assertEqual(video_default.dispatch_stage_name, "008图生视频视频生成")
        self.assertEqual(video_default.max_concurrency, "10")
        image_backfill = backfill[("prompt_image_video", "图片生成默认")]
        self.assertEqual(image_backfill.status_field, "图片生成状态")
        self.assertEqual(image_backfill.model_field, "图片AI模型")
        self.assertEqual(image_backfill.size_field, "图片画面尺寸")
        self.assertEqual(image_backfill.ratio_field, "图片画面比例")
        self.assertEqual(image_backfill.params_field, "图片AI参数JSON")
        video_backfill = backfill[("prompt_image_video", "图生视频生成默认")]
        self.assertEqual(video_backfill.status_field, "视频生成状态")
        self.assertEqual(video_backfill.model_field, "视频生成模型")
        self.assertEqual(video_backfill.size_field, "视频画面尺寸")
        self.assertEqual(video_backfill.ratio_field, "视频画面比例")
        self.assertEqual(video_backfill.params_field, "视频AI参数JSON")
        self.assertIn("", image_backfill.active_statuses)
        self.assertIn("失败", image_backfill.active_statuses)
        self.assertIn("", video_backfill.active_statuses)
        self.assertIn("不触发", video_backfill.active_statuses)

        script_video = specs[("script_doc_shots", "分镜视频生成默认")]
        self.assertEqual(script_video.source_config_stage, "分镜视频生成-OTU")
        self.assertEqual(script_video.slot_name, "视频")
        self.assertIn(("script_doc_shots", "分镜视频生成默认"), backfill)
        for key, stage in [
            ("multi_role_first_last", "视频片段生成默认"),
            ("first_last_video", "首尾帧视频生成默认"),
            ("script_doc_shots", "分镜视频生成默认"),
        ]:
            self.assertEqual(backfill[(key, stage)].channel_field, "视频通道")

        video_edit = specs[("video_edit", "视频编辑默认")]
        self.assertEqual(video_edit.source_config_stage, center.VIDEO_EDIT_SOURCE_CONFIG_STAGE)
        self.assertEqual(video_edit.slot_name, "视频编辑")
        self.assertIn(("video_edit", "视频编辑默认"), backfill)

    def test_prompt_image_video_default_rows_include_dispatch_concurrency(self):
        rows = center.build_task_default_rows([
            rec("img", 环节="图片生成-OTU", 模型名称="gpt-image-2-2K", 状态="启用", **{"API 代理地址": "https://otuapi.com", "画面尺寸": "1080x1920", "画面比例": "9:16"}),
            rec("vid", 环节="分镜视频生成-OTU", 模型名称="veo_3_1-fast-fl-hd", 状态="启用", **{"API 代理地址": "https://otuapi.com", "画面尺寸": "720x1280", "画面比例": "9:16"}),
        ])
        by_stage = {
            item["任务环节"]: item
            for item in rows
            if item.get("应用表格") == center.TASK_TABLES["prompt_image_video"]
        }

        self.assertEqual(by_stage["图片生成默认"]["调度环节名"], "008图生视频图片生成")
        self.assertEqual(by_stage["图片生成默认"]["环节最大并发"], 10)
        self.assertEqual(by_stage["图生视频生成默认"]["调度环节名"], "008图生视频视频生成")
        self.assertEqual(by_stage["图生视频生成默认"]["环节最大并发"], 10)

    def test_media_regeneration_concurrency_rows_cover_dispatcher_entries(self):
        rows = center.build_media_regeneration_concurrency_rows()
        by_stage = {item["调度环节名"]: item for item in rows}

        self.assertEqual(set(by_stage), {
            "多图宫格参考图重生成",
            "首尾帧首帧图重生成",
            "首尾帧尾帧图重生成",
            "首尾帧视频重生成",
            "多角色参考图重生成",
            "多角色关键帧重生成",
            "多角色视频片段重生成",
        })
        self.assertNotIn("首尾帧场景重新拆分", by_stage)
        for stage, row in by_stage.items():
            self.assertEqual(row["配置类型"], "运行环节")
            self.assertEqual(row["环节"], stage)
            self.assertEqual(row["环节最大并发"], 20)
            self.assertEqual(row["状态"], "启用")
            self.assertEqual(row["生效来源"], "线上配置")
            self.assertIn("dispatcher-only media regeneration entry", row["备注"])

    def test_run_media_regeneration_concurrency_upsert_uses_dispatch_stage_key(self):
        upserts = []

        with mock.patch.object(center, "get_feishu_token", return_value="token"), \
             mock.patch.object(center, "upsert_rows", side_effect=lambda token, base, table, rows, key_fields, dry_run: upserts.append((table, list(rows), tuple(key_fields), dry_run)) or [{"action": "dry_run_create"}]):
            result = center.run_media_regeneration_concurrency_upsert(write=False)

        self.assertEqual(result["mode"], "dry_run")
        self.assertEqual(result["media_regeneration_concurrency_records"], [{"action": "dry_run_create"}])
        self.assertEqual(len(upserts), 1)
        self.assertEqual(upserts[0][0], center.TABLE_CONFIG)
        self.assertEqual(upserts[0][2], ("配置类型", "调度环节名"))
        self.assertTrue(upserts[0][3])
        self.assertEqual(len(upserts[0][1]), 7)

    def test_storyboard_image_default_uses_horizontal_16_9_without_affecting_008(self):
        rows = center.build_task_default_rows([
            rec("img", 环节="图片生成-OTU", 模型名称="gpt-image-2-2K", 状态="启用", **{"API 代理地址": "https://otuapi.com", "画面尺寸": "720x1280", "画面比例": "9:16"}),
            rec("vid", 环节="分镜视频生成-OTU", 模型名称="veo_3_1-fast-fl", 状态="启用", **{"API 代理地址": "https://otuapi.com", "画面尺寸": "720x1280", "画面比例": "9:16"}),
            rec("omni", 环节="多图宫格视频生成", 模型名称="omni_flash-10s", 状态="启用", **{"API 代理地址": "https://otuapi.com", "画面尺寸": "720x1280", "画面比例": "9:16"}),
        ])
        by_table_stage = {
            (item["应用表格"], item["任务环节"]): item
            for item in rows
        }

        storyboard_image = by_table_stage[(center.TASK_TABLES["storyboard_video"], "图片生成默认")]
        self.assertEqual(storyboard_image["画面尺寸"], "1280x720")
        self.assertEqual(storyboard_image["画面比例"], "16:9")

        prompt_image = by_table_stage[(center.TASK_TABLES["prompt_image_video"], "图片生成默认")]
        self.assertEqual(prompt_image["画面尺寸"], "720x1280")
        self.assertEqual(prompt_image["画面比例"], "9:16")

        storyboard_video = by_table_stage[(center.TASK_TABLES["storyboard_video"], "图生视频生成默认")]
        self.assertEqual(storyboard_video["默认模型显示名称"], "OTU / omni_flash-10s")
        self.assertEqual(storyboard_video["模型名称"], "OTU / omni_flash-10s")
        self.assertEqual(storyboard_video["画面尺寸"], "720x1280")
        self.assertEqual(storyboard_video["画面比例"], "9:16")
        self.assertEqual(storyboard_video["调度环节名"], "004故事板视频生成")

        prompt_video = by_table_stage[(center.TASK_TABLES["prompt_image_video"], "图生视频生成默认")]
        self.assertEqual(prompt_video["默认模型显示名称"], "OTU / veo_3_1-fast-fl")

    def test_run_migration_writes_catalog_and_defaults_to_single_config_table(self):
        records = [
            rec("img", 环节="图片生成-OTU", 模型名称="gpt-image-2", 状态="启用", **{"API 代理地址": "https://otuapi.com", "画面尺寸": "720x1280", "画面比例": "9:16"}),
        ]
        upserts = []

        with mock.patch.object(center, "get_feishu_token", return_value="token"), \
             mock.patch.object(center, "safe_list_records", return_value=records), \
             mock.patch.object(center, "write_backup"), \
             mock.patch.object(center, "ensure_table") as ensure_table, \
             mock.patch.object(center, "ensure_views", return_value=[]), \
             mock.patch.object(center, "upsert_rows", side_effect=lambda token, base, table, rows, key_fields, dry_run: upserts.append((table, list(rows), tuple(key_fields))) or []), \
             mock.patch.object(center, "apply_legacy_archive", return_value=[]):
            result = center.run_migration(write=False)

        ensure_table.assert_not_called()
        self.assertEqual(result["config_table"]["table_id"], center.TABLE_CONFIG)
        self.assertEqual({item[0] for item in upserts}, {center.TABLE_CONFIG})
        self.assertIn(("配置类型", "显示名称"), [item[2] for item in upserts])
        self.assertIn(("配置类型", "应用表格", "任务环节"), [item[2] for item in upserts])

    def test_apply_legacy_archive_filters_missing_fields_before_write(self):
        updates = [{
            "record_id": "recLegacy",
            "fields": {"状态": "停用", "备注": "归档", "是否统一AI预设": "否"},
        }]
        calls = []

        with mock.patch.object(center, "filter_fields_for_table", return_value={"状态": "停用", "备注": "归档"}), \
             mock.patch.object(center, "safe_update_record", side_effect=lambda token, table, record_id, fields: calls.append(fields)):
            result = center.apply_legacy_archive("token", updates, dry_run=False)

        self.assertEqual(calls, [{"状态": "停用", "备注": "归档"}])
        self.assertEqual(result[0]["fields"], {"状态": "停用", "备注": "归档"})


if __name__ == "__main__":
    unittest.main()
