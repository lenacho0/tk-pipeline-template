import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import tk_create_first_last_video_table as create_table
import tk_dispatcher as dispatcher
import tk_first_last_video as first_last
import tk_healthcheck as healthcheck


def parsed_payload():
    return {
        "first_frame_prompt": "A clean vertical product hero opening frame.",
        "last_frame_prompt": "The same scene after the transformation is complete.",
        "video_prompt": "Animate naturally from the first frame to the last frame.",
    }


class FirstLastVideoTableTests(unittest.TestCase):
    def test_table_definition_has_parent_child_regeneration_fields_and_views(self):
        field_names = [field["name"] for field in create_table.FIRST_LAST_VIDEO_FIELDS]

        for name in [
            "任务名称",
            "记录类型",
            "记录状态",
            "父任务记录ID",
            "批次ID",
            "当前批次ID",
            "场景编号",
            "场景标题",
            "关联产品记录",
            "产品名称",
            "产品参考图file_tokenJSON",
            "首尾帧文档",
            "首尾帧文档附件",
            "目标时长秒",
            "文档拆分状态",
            "拆分状态",
            "总场景数",
            "场景拆分操作",
            "拆分结果JSON",
            "拆分版本",
            "首帧生图提示词",
            "尾帧生图提示词",
            "首尾帧生视频提示词",
            "首帧图操作",
            "首帧图版本",
            "首帧图生成状态",
            "首帧图",
            "首帧审核状态",
            "尾帧图操作",
            "尾帧图版本",
            "尾帧图生成状态",
            "尾帧图",
            "尾帧审核状态",
            "视频操作",
            "视频版本",
            "视频生成状态",
            "首尾帧视频",
            "历史生成记录JSON",
            "首帧图画面尺寸",
            "首帧图画面比例",
            "尾帧图画面尺寸",
            "尾帧图画面比例",
            "视频画面尺寸",
            "视频画面比例",
        ]:
            self.assertIn(name, field_names)

        self.assertNotIn("首尾帧文档链接", field_names)

        self.assertEqual(create_table.TABLE_DEFINITION["key"], "first_last_video")
        self.assertIn("01-用户入口", create_table.TABLE_DEFINITION["views"])
        self.assertIn("02-场景子任务", create_table.TABLE_DEFINITION["views"])
        self.assertIn("03-首帧审核", create_table.TABLE_DEFINITION["views"])
        self.assertIn("04-尾帧审核", create_table.TABLE_DEFINITION["views"])
        self.assertIn("05-视频结果", create_table.TABLE_DEFINITION["views"])
        self.assertIn("99-排错", create_table.TABLE_DEFINITION["views"])

    def test_user_entry_view_has_single_split_control(self):
        entry_fields = create_table.TABLE_DEFINITION["views"]["01-用户入口"]

        self.assertEqual(entry_fields, [
            "任务名称",
            "关联产品记录",
            "首尾帧文档",
            "首尾帧文档附件",
            "目标时长秒",
            "拆分AI模型",
            "拆分AI参数JSON",
            "拆分状态",
            "场景拆分操作",
            "总场景数",
            "错误信息",
        ])
        for hidden_field in [
            "记录类型",
            "记录状态",
            "批量拆分状态",
            "文档拆分状态",
            "当前批次ID",
            "首帧生图提示词",
            "尾帧生图提示词",
            "首尾帧生视频提示词",
        ]:
            self.assertNotIn(hidden_field, entry_fields)

    def test_workflow_views_keep_related_regeneration_controls_without_filters(self):
        views = create_table.TABLE_DEFINITION["views"]

        self.assertEqual(list(views.keys()), [
            "01-用户入口",
            "02-场景子任务",
            "高级AI参数",
            "03-首帧审核",
            "04-尾帧审核",
            "05-视频结果",
            "99-排错",
        ])
        self.assertIn("场景拆分操作", views["01-用户入口"])
        for field_name in ["场景拆分操作", "首帧图操作", "尾帧图操作", "视频操作"]:
            self.assertIn(field_name, views["02-场景子任务"])
            self.assertIn(field_name, views["99-排错"])
        self.assertIn("视频生成模型", views["99-排错"])
        self.assertIn("视频AI模型", views["99-排错"])
        self.assertNotIn("视频AI模型", views["02-场景子任务"])
        self.assertNotIn("视频AI参数JSON", views["02-场景子任务"])
        self.assertIn("视频通道", views["02-场景子任务"])
        self.assertIn("视频生成模型", views["02-场景子任务"])
        for field_name in [
            "首帧图画面尺寸",
            "首帧图画面比例",
            "尾帧图画面尺寸",
            "尾帧图画面比例",
            "视频画面尺寸",
            "视频画面比例",
        ]:
            self.assertIn(field_name, views["02-场景子任务"])
        self.assertIn("首帧图操作", views["03-首帧审核"])
        self.assertIn("首帧图画面尺寸", views["03-首帧审核"])
        self.assertIn("首帧图画面比例", views["03-首帧审核"])
        self.assertIn("尾帧图操作", views["04-尾帧审核"])
        self.assertIn("尾帧图画面尺寸", views["04-尾帧审核"])
        self.assertIn("尾帧图画面比例", views["04-尾帧审核"])
        self.assertIn("视频操作", views["05-视频结果"])
        self.assertNotIn("视频AI模型", views["05-视频结果"])
        self.assertNotIn("视频AI参数JSON", views["05-视频结果"])
        self.assertIn("视频通道", views["05-视频结果"])
        self.assertIn("视频生成模型", views["05-视频结果"])
        self.assertIn("视频画面尺寸", views["05-视频结果"])
        self.assertIn("视频画面比例", views["05-视频结果"])
        self.assertIn("使用统一AI路由", views["高级AI参数"])
        self.assertIn("拆分AI参数JSON", views["高级AI参数"])
        self.assertIn("首帧图AI模型", views["高级AI参数"])
        self.assertNotIn("视频AI模型", views["高级AI参数"])
        self.assertNotIn("视频AI参数JSON", views["高级AI参数"])
        self.assertIn("视频通道", views["高级AI参数"])
        self.assertIn("视频生成模型", views["高级AI参数"])
        for field_name in [
            "首帧图画面尺寸",
            "首帧图画面比例",
            "尾帧图画面尺寸",
            "尾帧图画面比例",
            "视频画面尺寸",
            "视频画面比例",
        ]:
            self.assertIn(field_name, views["高级AI参数"])
        self.assertFalse(hasattr(create_table, "VIEW_FILTERS"))
        self.assertFalse(hasattr(create_table, "apply_first_last_view_filters"))

    def test_first_last_media_summary_rejects_reference_video_model(self):
        config_records = [
            {"fields": {"环节": "统一AI路由启用状态", "模型名称": "指定记录启用"}},
            {"fields": {"AI供应商": "Aitgenne", "API 代理地址": "https://api.aitgenne.com", "API Key": "sk-aitgenne"}},
        ]

        with patch.object(first_last, "safe_list_records", return_value=config_records):
            with self.assertRaisesRegex(ValueError, "首尾帧视频模型不支持参考图视频模型"):
                first_last.maybe_unified_media_summary(
                    "token",
                    {"使用统一AI路由": "是", "视频AI模型": "Aitgenne / happyhorse-1.0-i2v"},
                    {"provider": "OTU", "api_key": "sk-otu", "api_base": "https://otuapi.com", "model": "veo_3_1-fast-fl"},
                    capability="视频",
                    task_type="首帧图生视频",
                    model="veo_3_1-fast-fl",
                    slot_name="视频",
                    prompt="video prompt",
                    params={"size": "720x1280", "aspect_ratio": "9:16"},
                    reference_count=1,
                )

    def test_prune_obsolete_views_deletes_only_legacy_first_last_views(self):
        calls = []

        def fake_run_json(args):
            calls.append(args)
            if "+view-list" in args:
                return {"data": {"views": [
                    {"id": "vew_default", "name": "Grid View"},
                    {"id": "vew_entry", "name": "01-用户入口"},
                    {"id": "vew_old_first", "name": "02-首帧审核"},
                    {"id": "vew_child", "name": "02-场景子任务"},
                    {"id": "vew_old_last", "name": "03-尾帧审核"},
                    {"id": "vew_first", "name": "03-首帧审核"},
                    {"id": "vew_old_video", "name": "04-视频结果"},
                    {"id": "vew_last", "name": "04-尾帧审核"},
                    {"id": "vew_video", "name": "05-视频结果"},
                    {"id": "vew_debug", "name": "99-排错"},
                ]}}
            if "+view-delete" in args:
                return {"ok": True}
            raise AssertionError(args)

        with patch.object(create_table, "run_json", side_effect=fake_run_json):
            deleted = create_table.prune_obsolete_views("app_token", "tbl_first_last")

        self.assertEqual(deleted, ["Grid View", "02-首帧审核", "03-尾帧审核", "04-视频结果"])
        delete_view_ids = [
            args[args.index("--view-id") + 1]
            for args in calls
            if "+view-delete" in args
        ]
        self.assertEqual(delete_view_ids, ["vew_default", "vew_old_first", "vew_old_last", "vew_old_video"])
        self.assertTrue(all("--yes" in args for args in calls if "+view-delete" in args))
        self.assertNotIn("vew_entry", delete_view_ids)
        self.assertNotIn("vew_child", delete_view_ids)

    def test_migrate_renamed_fields_renames_batch_split_status_without_duplicate(self):
        calls = []

        def fake_run_json(args):
            if "+field-list" in args:
                return {"data": {"items": [{"id": "fld_old", "name": "批量拆分状态", "type": "select"}]}}
            if "+field-update" in args:
                calls.append(args)
                return {"data": {"field": {"id": "fld_old", "name": "拆分状态"}}}
            raise AssertionError(args)

        with patch.object(create_table, "run_json", side_effect=fake_run_json):
            renamed = create_table.migrate_renamed_fields("app_token", "tbl_first_last")

        self.assertEqual(renamed, ["批量拆分状态 -> 拆分状态"])
        self.assertEqual(len(calls), 1)
        update_args = calls[0]
        self.assertIn("--yes", update_args)
        self.assertEqual(update_args[update_args.index("--field-id") + 1], "fld_old")
        payload = json.loads(update_args[update_args.index("--json") + 1])
        self.assertEqual(payload["name"], "拆分状态")
        self.assertEqual(payload["type"], "select")

    def test_config_template_includes_first_last_video_table_key(self):
        template_path = Path(__file__).resolve().parent / "config.json.template"
        data = json.loads(template_path.read_text(encoding="utf-8"))

        self.assertIn("first_last_video", data["feishu"]["tables"])

    def test_create_script_prefers_configured_first_last_table_id(self):
        configured = {
            "feishu": {
                "tables": {
                    "first_last_video": "tbl_configured",
                },
            },
        }
        self.assertEqual(create_table.resolve_first_last_table_id(configured, {create_table.TABLE_NAME: "tbl_by_name"}), "tbl_configured")
        self.assertEqual(create_table.resolve_first_last_table_id({"feishu": {"tables": {}}}, {create_table.TABLE_NAME: "tbl_by_name"}), "tbl_by_name")

    def test_dispatcher_has_all_first_last_video_watches(self):
        watches = {watch["name"]: watch for watch in dispatcher.RAW_WATCH_LIST}

        expected = {
            "首尾帧批量场景拆分": ("拆分状态", "待拆分", "拆分中", ["batch-parse"]),
            "首尾帧文档拆分": ("文档拆分状态", "待拆分", "拆分中", ["parse"]),
            "首尾帧场景重新拆分": ("场景拆分操作", "重新拆分场景", "重新拆分场景", ["regenerate-split"]),
            "首尾帧首帧图重生成": ("首帧图操作", "重新生成首帧图", "重新生成首帧图", ["regenerate-first-frame"]),
            "首尾帧首帧图生成": ("首帧图生成状态", "待生成", "生成中", ["first-frame"]),
            "首尾帧首帧审核推进": ("首帧审核状态", "通过", "通过", ["advance-first-review"]),
            "首尾帧尾帧图重生成": ("尾帧图操作", "重新生成尾帧图", "重新生成尾帧图", ["regenerate-last-frame"]),
            "首尾帧尾帧图生成": ("尾帧图生成状态", "待生成", "生成中", ["last-frame"]),
            "首尾帧尾帧审核推进": ("尾帧审核状态", "通过", "通过", ["advance-last-review"]),
            "首尾帧视频重生成": ("视频操作", "重新生成首尾帧视频", "重新生成首尾帧视频", ["regenerate-video"]),
            "首尾帧视频生成": ("视频生成状态", "待生成", "生成中", ["video"]),
        }
        for name, (status_field, trigger_value, running_value, args) in expected.items():
            self.assertIn(name, watches)
            self.assertEqual(watches[name]["table"], dispatcher.TABLE_FIRST_LAST_VIDEO)
            self.assertEqual(watches[name]["status_field"], status_field)
            self.assertEqual(watches[name]["trigger_value"], trigger_value)
            self.assertEqual(watches[name]["running_value"], running_value)
            self.assertEqual(watches[name]["script"], "tk_first_last_video.py")
            self.assertEqual(watches[name]["args"], args)

        claim_fields = dispatcher.apply_claim_clear_fields({"视频生成状态": "生成中"}, watches["首尾帧视频生成"], "待生成")
        self.assertEqual(claim_fields["视频任务ID"], "")
        self.assertEqual(claim_fields["首尾帧视频"], [])
        self.assertIsNone(claim_fields["首尾帧视频URL"])
        self.assertEqual(claim_fields["首尾帧视频file_token"], "")
        self.assertEqual(claim_fields["本地视频路径"], "")
        self.assertEqual(claim_fields["视频生成原始响应JSON"], "")
        self.assertEqual(claim_fields["视频错误信息"], "")
        self.assertEqual(claim_fields["错误信息"], "")

        resume_fields = dispatcher.apply_claim_clear_fields({"视频生成状态": "生成中"}, watches["首尾帧视频生成"], "生成中")
        self.assertEqual(resume_fields, {"视频生成状态": "生成中"})
        self.assertEqual(watches["首尾帧场景重新拆分"]["required_field_values"]["记录类型"], ["", "母任务"])
        self.assertEqual(watches["首尾帧首帧图生成"]["skip_if_field_values"]["记录类型"], ["母任务"])
        self.assertEqual(watches["首尾帧首帧图生成"]["trigger_values"], ["待生成", "生成中"])
        self.assertEqual(watches["首尾帧尾帧图生成"]["trigger_values"], ["待生成", "生成中"])
        self.assertEqual(watches["首尾帧视频生成"]["trigger_values"], ["待生成", "生成中"])

        first_waiting_claim = dispatcher.apply_claim_clear_fields({"首帧图生成状态": "生成中"}, watches["首尾帧首帧图生成"], "待生成")
        self.assertEqual(first_waiting_claim["首帧图任务ID"], "")
        first_running_claim = dispatcher.apply_claim_clear_fields({"首帧图生成状态": "生成中"}, watches["首尾帧首帧图生成"], "生成中")
        self.assertNotIn("首帧图任务ID", first_running_claim)

        last_waiting_claim = dispatcher.apply_claim_clear_fields({"尾帧图生成状态": "生成中"}, watches["首尾帧尾帧图生成"], "待生成")
        self.assertEqual(last_waiting_claim["尾帧图任务ID"], "")
        last_running_claim = dispatcher.apply_claim_clear_fields({"尾帧图生成状态": "生成中"}, watches["首尾帧尾帧图生成"], "生成中")
        self.assertNotIn("尾帧图任务ID", last_running_claim)
        self.assertTrue(watches["首尾帧首帧图生成"]["skip_deprecated_records"])

    def test_dispatcher_classifies_otu_resubmit_errors_as_retryable(self):
        stderr = (
            "OTU 视频生成失败: {'id': 'task_old', 'error': {'code': 'official_generation_error', "
            "'message': '官方生成遇到错误，请重新提交'}, 'model': 'veo_3_1-fast-fl', "
            "'object': 'video', 'status': 'failed', 'progress': 100}"
        )

        payload = dispatcher.parse_subprocess_error_payload("", stderr, "tk_first_last_video.py")

        self.assertEqual(payload["error_code"], "UPSTREAM_RETRYABLE")
        self.assertTrue(payload["retryable"])
        self.assertIn("official_generation_error", payload["message"])

    def test_dispatcher_skips_deprecated_first_last_records(self):
        watch = {
            "name": "首尾帧首帧图生成",
            "skip_deprecated_records": True,
            "skip_if_field_values": {"记录类型": ["母任务"]},
        }

        self.assertFalse(dispatcher.record_matches_watch_filters(watch, {"记录状态": "已废弃", "记录类型": "场景子任务"}))
        self.assertFalse(dispatcher.record_matches_watch_filters(watch, {"记录状态": "有效", "记录类型": "母任务"}))
        self.assertTrue(dispatcher.record_matches_watch_filters(watch, {"记录状态": "有效", "记录类型": "场景子任务"}))

    def test_healthcheck_validates_first_last_video_table_and_configs(self):
        config_records = [
            {"fields": {"环节": "图片生成-OTU", "模型名称": "gpt-image-2", "API Key": "sk-img", "API 代理地址": "https://otuapi.com"}},
            {"fields": {"环节": "分镜视频生成-OTU", "模型名称": "veo_3_1-fast-fl", "API Key": "sk-video", "API 代理地址": "https://otuapi.com"}},
        ]
        with patch.object(healthcheck, "TABLE_FIRST_LAST_VIDEO", "tbl_first_last"), \
             patch.object(healthcheck, "get_feishu_token", return_value="token"), \
             patch.object(healthcheck, "get_table_field_names", return_value={
                 "记录类型",
                 "记录状态",
                 "父任务记录ID",
                 "批次ID",
                 "当前批次ID",
                 "场景编号",
                 "关联产品记录",
                 "产品名称",
                 "产品参考图file_tokenJSON",
                 "首尾帧文档附件",
                 "拆分状态",
                 "场景拆分操作",
                 "首帧图操作",
                 "尾帧图操作",
                 "视频操作",
                 "拆分版本",
                 "首帧图版本",
                 "尾帧图版本",
                 "视频版本",
             }), \
             patch.object(healthcheck, "safe_list_records", return_value=config_records):
            ok, msg = healthcheck.check_first_last_video_config()

        self.assertTrue(ok, msg)
        self.assertNotIn("文本拆分", msg)
        self.assertIn("图片生成-OTU", msg)
        self.assertIn("分镜视频生成-OTU", msg)


class FirstLastVideoWorkerTests(unittest.TestCase):
    def test_normalize_parse_payload_requires_three_prompts(self):
        payload = first_last.normalize_parse_payload({
            "first_frame_prompt": "first",
            "last_frame_prompt": "last",
            "video_prompt": "video",
        })

        self.assertEqual(payload["first_frame_prompt"], "first")
        self.assertEqual(payload["last_frame_prompt"], "last")
        self.assertEqual(payload["video_prompt"], "video")

        with self.assertRaisesRegex(ValueError, "video_prompt"):
            first_last.normalize_parse_payload({
                "first_frame_prompt": "first",
                "last_frame_prompt": "last",
            })

    def test_normalize_batch_parse_payload_requires_scene_prompts(self):
        payload = first_last.normalize_batch_parse_payload({
            "scenes": [
                {
                    "scene_no": 1,
                    "title": "Opening",
                    "first_frame_prompt": "first 1",
                    "last_frame_prompt": "last 1",
                    "video_prompt": "video 1",
                },
                {
                    "scene_no": 2,
                    "scene_title": "Ending",
                    "首帧生图提示词": "first 2",
                    "尾帧生图提示词": "last 2",
                    "首尾帧生视频提示词": "video 2",
                },
            ],
        })

        self.assertEqual(len(payload["scenes"]), 2)
        self.assertEqual(payload["scenes"][0]["scene_no"], 1)
        self.assertEqual(payload["scenes"][1]["title"], "Ending")
        self.assertEqual(payload["scenes"][1]["video_prompt"], "video 2")

        with self.assertRaisesRegex(ValueError, "scene 1.*video_prompt"):
            first_last.normalize_batch_parse_payload({"scenes": [{"first_frame_prompt": "first", "last_frame_prompt": "last"}]})

    def test_parse_structured_markdown_scenes_extracts_three_prompts_per_scene(self):
        doc = """
## S01 浅瓷砖地板

### S01-1 首帧生图提示词

```text
first prompt 1
```

中文拍摄理解：ignore me

### S01-2 尾帧生图 / 编辑提示词

```text
last prompt 1
```

### S01-3 首尾帧图生视频提示词

```text
video prompt 1
```

---

## S02 木纹地板

### S02-1 首帧生图提示词

```text
first prompt 2
```

### S02-2 尾帧生图 / 编辑提示词

```text
last prompt 2
```

### S02-3 首尾帧图生视频提示词

```text
video prompt 2
```
""".strip()

        payload = first_last.parse_structured_markdown_scenes(doc)

        self.assertEqual(len(payload["scenes"]), 2)
        self.assertEqual(payload["scenes"][0]["scene_no"], 1)
        self.assertEqual(payload["scenes"][0]["title"], "浅瓷砖地板")
        self.assertEqual(payload["scenes"][0]["first_frame_prompt"], "first prompt 1")
        self.assertEqual(payload["scenes"][1]["last_frame_prompt"], "last prompt 2")
        self.assertEqual(payload["scenes"][1]["video_prompt"], "video prompt 2")

    def test_require_structured_markdown_scenes_reports_missing_section(self):
        doc = """
## S01 浅瓷砖地板

### S01-1 首帧生图提示词

```text
first prompt
```

### S01-3 首尾帧图生视频提示词

```text
video prompt
```
""".strip()

        with self.assertRaisesRegex(ValueError, "S01.*S01-2.*尾帧"):
            first_last.require_structured_markdown_scenes(doc)

    def test_read_source_document_text_uses_raw_attachment_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc_path = Path(tmp) / "source.txt"
            doc_path.write_text("short scene doc", encoding="utf-8")
            fields = {"首尾帧文档附件": [{"file_token": "doc_token"}], "拆分版本": 1}
            with patch.object(first_last, "ensure_work_dir", return_value=Path(tmp)), \
                 patch.object(first_last, "download_feishu_attachment_raw", return_value=doc_path) as raw_downloader, \
                 patch.object(first_last, "download_feishu_media") as image_downloader:
                text = first_last.read_source_document_text("token", "rec1", fields)

        self.assertEqual(text, "short scene doc")
        raw_downloader.assert_called_once()
        image_downloader.assert_not_called()

    def test_batch_parse_deprecates_old_children_and_creates_new_batch(self):
        updates = []
        created_batches = []
        parent_fields = {
            "记录类型": "母任务",
            "记录状态": "有效",
            "任务名称": "尿味分解",
            "首尾帧文档": "12 scenes doc",
            "当前批次ID": "old_batch",
            "拆分版本": 1,
            "目标时长秒": 6,
            "关联产品记录": [{"record_ids": ["recProduct"]}],
        }
        existing_records = [
            {"record_id": "old1", "fields": {"记录类型": "场景子任务", "记录状态": "有效", "父任务记录ID": "parent", "批次ID": "old_batch"}},
            {"record_id": "old2", "fields": {"记录类型": "场景子任务", "记录状态": "", "父任务记录ID": "parent", "批次ID": "old_batch"}},
            {"record_id": "other", "fields": {"记录类型": "场景子任务", "记录状态": "有效", "父任务记录ID": "elsewhere"}},
        ]
        model_output = {
            "scenes": [
                {"scene_no": 1, "title": "开场", "first_frame_prompt": "first 1", "last_frame_prompt": "last 1", "video_prompt": "video 1"},
                {"scene_no": 2, "title": "收尾", "first_frame_prompt": "first 2", "last_frame_prompt": "last 2", "video_prompt": "video 2"},
            ]
        }

        def capture_create(token, table, records):
            created_batches.append(records)
            return len(records)

        with patch.object(first_last, "TABLE_FIRST_LAST_VIDEO", "tbl_first_last"), \
             patch.object(first_last, "get_feishu_token", return_value="token"), \
             patch.object(first_last, "safe_get_record", side_effect=[
                 parent_fields,
                 {"产品名称-zh": "Pet Odor Spray", "产品图片": [{"file_token": "ft_product"}]},
             ]), \
             patch.object(first_last, "safe_list_records", return_value=existing_records), \
             patch.object(first_last, "safe_update_record", side_effect=lambda token, table, rid, fields: updates.append((rid, fields))), \
             patch.object(first_last, "filter_existing_fields", side_effect=lambda token, table, fields: fields), \
             patch.object(first_last, "create_records", side_effect=capture_create), \
             patch.object(first_last, "make_batch_id", return_value="batch_new"), \
             patch.object(first_last, "parse_structured_markdown_scenes", return_value={}) as markdown_parser:
            result = first_last.batch_parse_document("parent", raw_model_output=model_output)

        markdown_parser.assert_not_called()

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["created_records"], 2)
        deprecated = {rid: fields for rid, fields in updates if rid in {"old1", "old2"}}
        self.assertEqual(deprecated["old1"]["记录状态"], "已废弃")
        self.assertEqual(deprecated["old2"]["首帧图生成状态"], "不触发")
        created = created_batches[0]
        self.assertEqual(len(created), 2)
        self.assertEqual(created[0]["fields"]["记录类型"], "场景子任务")
        self.assertEqual(created[0]["fields"]["记录状态"], "有效")
        self.assertEqual(created[0]["fields"]["父任务记录ID"], "parent")
        self.assertEqual(created[0]["fields"]["批次ID"], "batch_new")
        self.assertEqual(created[0]["fields"]["关联产品记录"], ["recProduct"])
        self.assertEqual(created[0]["fields"]["产品名称"], "Pet Odor Spray")
        self.assertIn("ft_product", created[0]["fields"]["产品参考图file_tokenJSON"])
        self.assertEqual(created[0]["fields"]["场景编号"], 1)
        self.assertEqual(created[0]["fields"]["首帧图生成状态"], "待生成")
        self.assertEqual(created[0]["fields"]["尾帧图生成状态"], "不触发")
        self.assertEqual(created[0]["fields"]["视频生成状态"], "不触发")
        parent_final = updates[-1][1]
        self.assertEqual(parent_final["当前批次ID"], "batch_new")
        self.assertEqual(parent_final["产品名称"], "Pet Odor Spray")
        self.assertIn("ft_product", parent_final["产品参考图file_tokenJSON"])
        self.assertEqual(parent_final["总场景数"], 2)
        self.assertEqual(parent_final["拆分版本"], 2)
        self.assertEqual(parent_final["场景拆分操作"], "不触发")

    def test_batch_parse_uses_markdown_directly_without_text_model(self):
        updates = []
        created_batches = []
        parent_fields = {
            "记录类型": "母任务",
            "记录状态": "有效",
            "任务名称": "尿味分解",
            "首尾帧文档": """
## S01 浅瓷砖地板

### S01-1 首帧生图提示词

```text
first prompt exactly
```

### S01-2 尾帧生图 / 编辑提示词

```text
last prompt exactly
```

### S01-3 首尾帧图生视频提示词

```text
video prompt exactly
```
""".strip(),
            "拆分版本": 1,
            "目标时长秒": 6,
            "关联产品记录": [{"record_ids": ["recProduct"]}],
        }

        def capture_create(token, table, records):
            created_batches.append(records)
            return len(records)

        with patch.object(first_last, "TABLE_FIRST_LAST_VIDEO", "tbl_first_last"), \
             patch.object(first_last, "get_feishu_token", return_value="token"), \
             patch.object(first_last, "safe_get_record", side_effect=[
                 parent_fields,
                 {"产品名称-zh": "Pet Odor Spray", "产品图片": [{"file_token": "ft_product"}]},
             ]), \
             patch.object(first_last, "safe_list_records", return_value=[]), \
             patch.object(first_last, "safe_update_record", side_effect=lambda token, table, rid, fields: updates.append((rid, fields))), \
             patch.object(first_last, "filter_existing_fields", side_effect=lambda token, table, fields: fields), \
             patch.object(first_last, "create_records", side_effect=capture_create), \
             patch.object(first_last, "make_batch_id", return_value="batch_new"):
            result = first_last.batch_parse_document("parent")

        self.assertEqual(result["parser"], "structured_markdown")
        created = created_batches[0]
        self.assertEqual(created[0]["fields"]["首帧生图提示词"], "first prompt exactly")
        self.assertEqual(created[0]["fields"]["尾帧生图提示词"], "last prompt exactly")
        self.assertEqual(created[0]["fields"]["首尾帧生视频提示词"], "video prompt exactly")

    def test_batch_parse_rejects_unstructured_markdown_without_model_fallback(self):
        parent_fields = {
            "记录类型": "母任务",
            "记录状态": "有效",
            "任务名称": "尿味分解",
            "首尾帧文档": "自由文本，不是固定 Markdown 模板",
            "拆分版本": 1,
            "目标时长秒": 6,
            "关联产品记录": [{"record_ids": ["recProduct"]}],
        }

        with patch.object(first_last, "TABLE_FIRST_LAST_VIDEO", "tbl_first_last"), \
             patch.object(first_last, "get_feishu_token", return_value="token"), \
             patch.object(first_last, "safe_get_record", side_effect=[
                 parent_fields,
                 {"产品名称-zh": "Pet Odor Spray", "产品图片": [{"file_token": "ft_product"}]},
             ]), \
             patch.object(first_last, "safe_update_record"), \
             patch.object(first_last, "filter_existing_fields", side_effect=lambda token, table, fields: fields):
            with self.assertRaisesRegex(ValueError, "Markdown 格式不符合要求.*## S01"):
                first_last.batch_parse_document("parent")

    def test_first_frame_regeneration_clears_dependent_outputs_and_bumps_version(self):
        updates = []
        fields = {
            "记录类型": "场景子任务",
            "记录状态": "有效",
            "首帧图版本": 2,
            "首帧图file_token": "old_first",
            "尾帧图file_token": "old_last",
            "首尾帧视频file_token": "old_video",
        }
        with patch.object(first_last, "TABLE_FIRST_LAST_VIDEO", "tbl_first_last"), \
             patch.object(first_last, "get_feishu_token", return_value="token"), \
             patch.object(first_last, "safe_get_record", return_value=fields), \
             patch.object(first_last, "safe_update_record", side_effect=lambda token, table, rid, patch_fields: updates.append(patch_fields)), \
             patch.object(first_last, "filter_existing_fields", side_effect=lambda token, table, patch_fields: patch_fields):
            result = first_last.request_first_frame_regeneration("rec1")

        patch_fields = updates[-1]
        self.assertEqual(result["status"], "triggered")
        self.assertEqual(patch_fields["首帧图版本"], 3)
        self.assertEqual(patch_fields["首帧图"], [])
        self.assertEqual(patch_fields["首帧图file_token"], "")
        self.assertEqual(patch_fields["尾帧图"], [])
        self.assertEqual(patch_fields["尾帧图file_token"], "")
        self.assertEqual(patch_fields["首尾帧视频"], [])
        self.assertIsNone(patch_fields["首尾帧视频URL"])
        self.assertEqual(patch_fields["首尾帧视频file_token"], "")
        self.assertEqual(patch_fields["首帧图生成状态"], "待生成")
        self.assertEqual(patch_fields["尾帧图生成状态"], "不触发")
        self.assertEqual(patch_fields["视频生成状态"], "不触发")
        self.assertEqual(patch_fields["首帧图操作"], "不触发")

    def test_last_frame_regeneration_keeps_first_frame_and_clears_video(self):
        updates = []
        fields = {
            "记录类型": "场景子任务",
            "记录状态": "有效",
            "尾帧图版本": 4,
            "首帧图file_token": "keep_first",
            "尾帧图file_token": "old_last",
            "首尾帧视频file_token": "old_video",
        }
        with patch.object(first_last, "TABLE_FIRST_LAST_VIDEO", "tbl_first_last"), \
             patch.object(first_last, "get_feishu_token", return_value="token"), \
             patch.object(first_last, "safe_get_record", return_value=fields), \
             patch.object(first_last, "safe_update_record", side_effect=lambda token, table, rid, patch_fields: updates.append(patch_fields)), \
             patch.object(first_last, "filter_existing_fields", side_effect=lambda token, table, patch_fields: patch_fields):
            result = first_last.request_last_frame_regeneration("rec1")

        patch_fields = updates[-1]
        self.assertEqual(result["status"], "triggered")
        self.assertNotIn("首帧图file_token", patch_fields)
        self.assertEqual(patch_fields["尾帧图版本"], 5)
        self.assertEqual(patch_fields["尾帧图"], [])
        self.assertEqual(patch_fields["尾帧图file_token"], "")
        self.assertEqual(patch_fields["首尾帧视频"], [])
        self.assertIsNone(patch_fields["首尾帧视频URL"])
        self.assertEqual(patch_fields["视频生成状态"], "不触发")
        self.assertEqual(patch_fields["尾帧图生成状态"], "待生成")

    def test_video_regeneration_keeps_frames_and_clears_only_video(self):
        updates = []
        fields = {
            "记录类型": "场景子任务",
            "记录状态": "有效",
            "视频版本": 7,
            "首帧图file_token": "keep_first",
            "尾帧图file_token": "keep_last",
            "首尾帧视频file_token": "old_video",
        }
        with patch.object(first_last, "TABLE_FIRST_LAST_VIDEO", "tbl_first_last"), \
             patch.object(first_last, "get_feishu_token", return_value="token"), \
             patch.object(first_last, "safe_get_record", return_value=fields), \
             patch.object(first_last, "safe_update_record", side_effect=lambda token, table, rid, patch_fields: updates.append(patch_fields)), \
             patch.object(first_last, "filter_existing_fields", side_effect=lambda token, table, patch_fields: patch_fields):
            result = first_last.request_video_regeneration("rec1")

        patch_fields = updates[-1]
        self.assertEqual(result["status"], "triggered")
        self.assertNotIn("首帧图file_token", patch_fields)
        self.assertNotIn("尾帧图file_token", patch_fields)
        self.assertEqual(patch_fields["视频版本"], 8)
        self.assertEqual(patch_fields["首尾帧视频"], [])
        self.assertIsNone(patch_fields["首尾帧视频URL"])
        self.assertEqual(patch_fields["首尾帧视频file_token"], "")
        self.assertEqual(patch_fields["视频任务ID"], "")
        self.assertEqual(patch_fields["视频生成原始响应JSON"], "")
        self.assertEqual(patch_fields["视频错误信息"], "")
        self.assertEqual(patch_fields["错误信息"], "")
        self.assertEqual(patch_fields["视频生成状态"], "待生成")
        self.assertEqual(patch_fields["视频操作"], "不触发")

    def test_stale_guard_rejects_changed_version_or_task(self):
        with patch.object(first_last, "safe_get_record", return_value={
            "记录状态": "有效",
            "首帧图生成状态": "生成中",
            "首帧图版本": 3,
            "首帧图任务ID": "new_task",
        }):
            with self.assertRaisesRegex(RuntimeError, "首帧图版本 已变更"):
                first_last.ensure_current_generation("token", "rec1", "首帧图生成状态", "生成中", "首帧图版本", 2, "首帧图任务ID", "old_task")

        with patch.object(first_last, "safe_get_record", return_value={
            "记录状态": "有效",
            "首帧图生成状态": "生成中",
            "首帧图版本": 3,
            "首帧图任务ID": "new_task",
        }):
            with self.assertRaisesRegex(RuntimeError, "首帧图任务ID 已变更"):
                first_last.ensure_current_generation("token", "rec1", "首帧图生成状态", "生成中", "首帧图版本", 3, "首帧图任务ID", "old_task")

        with patch.object(first_last, "safe_get_record", return_value={
            "记录状态": "已废弃",
            "首帧图生成状态": "生成中",
            "首帧图版本": 3,
            "首帧图任务ID": "task",
        }):
            with self.assertRaisesRegex(RuntimeError, "记录状态已变更为 已废弃"):
                first_last.ensure_current_generation("token", "rec1", "首帧图生成状态", "生成中", "首帧图版本", 3, "首帧图任务ID", "task")

    def test_parse_document_writes_prompts_and_triggers_first_frame(self):
        updates = []
        with patch.object(first_last, "TABLE_FIRST_LAST_VIDEO", "tbl_first_last"), \
             patch.object(first_last, "get_feishu_token", return_value="token"), \
             patch.object(first_last, "safe_get_record", return_value={"首尾帧文档": "free form doc", "目标时长秒": "6"}), \
             patch.object(first_last, "safe_update_record", side_effect=lambda token, table, rid, fields: updates.append(fields)), \
             patch.object(first_last, "filter_existing_fields", side_effect=lambda token, table, fields: fields):
            result = first_last.parse_document("rec1", raw_model_output=parsed_payload())

        self.assertEqual(result["status"], "success")
        self.assertEqual(updates[-1]["文档拆分状态"], "成功")
        self.assertEqual(updates[-1]["首帧生图提示词"], parsed_payload()["first_frame_prompt"])
        self.assertEqual(updates[-1]["尾帧生图提示词"], parsed_payload()["last_frame_prompt"])
        self.assertEqual(updates[-1]["首尾帧生视频提示词"], parsed_payload()["video_prompt"])
        self.assertEqual(updates[-1]["首帧图生成状态"], "待生成")
        self.assertEqual(updates[-1]["首帧审核状态"], "待确认")
        self.assertEqual(updates[-1]["尾帧图生成状态"], "不触发")
        self.assertEqual(updates[-1]["视频生成状态"], "不触发")
        self.assertEqual(updates[-1]["记录状态"], "有效")
        self.assertEqual(updates[-1]["首帧图版本"], 1)
        self.assertEqual(updates[-1]["尾帧图版本"], 1)
        self.assertEqual(updates[-1]["视频版本"], 1)

    def test_resolve_product_reference_context_prefers_frozen_snapshot(self):
        fields = {
            "记录类型": "场景子任务",
            "关联产品记录": [{"record_ids": ["recProduct"]}],
            "产品名称": "Frozen Pet Spray",
            "产品参考图file_tokenJSON": json.dumps({
                "product_record_id": "recProduct",
                "product_name": "Frozen Pet Spray",
                "file_tokens": ["ft_frozen"],
            }),
        }

        with patch.object(first_last, "safe_get_record", side_effect=AssertionError("should not reload latest product record")):
            context = first_last.resolve_product_reference_context("token", fields, "rec1")

        self.assertEqual(context["product_record_id"], "recProduct")
        self.assertEqual(context["product_name"], "Frozen Pet Spray")
        self.assertEqual(context["product_tokens"], ["ft_frozen"])
        self.assertTrue(context["snapshot_used"])

    def test_render_first_frame_uses_product_reference_image_and_writes_review_gate(self):
        updates = []
        with tempfile.TemporaryDirectory() as tmp:
            product_path = Path(tmp) / "product.png"
            product_path.write_bytes(b"x" * 2000)
            with patch.object(first_last, "TABLE_FIRST_LAST_VIDEO", "tbl_first_last"), \
                 patch.object(first_last, "get_feishu_token", return_value="token"), \
                 patch.object(first_last, "safe_get_record", side_effect=[
                     {"记录类型": "场景子任务", "记录状态": "有效", "首帧生图提示词": "first prompt", "首帧图版本": 2, "关联产品记录": [{"record_ids": ["recProduct"]}]},
                     {"产品名称-zh": "Pet Odor Spray", "产品图片": [{"file_token": "ft_product"}]},
                     {"记录状态": "有效", "首帧图生成状态": "生成中", "首帧图版本": 2, "首帧图任务ID": "img_task_1"},
                 ]), \
                 patch.object(first_last, "safe_update_record", side_effect=lambda token, table, rid, fields: updates.append(fields)), \
                 patch.object(first_last, "filter_existing_fields", side_effect=lambda token, table, fields: fields), \
                 patch.object(first_last, "ensure_work_dir", return_value=Path(tmp)), \
                 patch.object(first_last, "download_feishu_media", return_value=product_path) as media_downloader, \
                 patch.object(first_last, "get_tmp_download_url_for_attachment", return_value="https://x.test/product.png"), \
                 patch.object(first_last, "get_stage_config", return_value=("cfg_img", {"api_key": "sk", "api_base": "https://otuapi.com", "model": "gpt-image-2", "size": "1024x1024"})), \
                 patch.object(first_last, "submit_otu_image_task", return_value=("img_task_1", {"id": "img_task_1"})) as submitter, \
                 patch.object(first_last, "poll_otu_image_task", return_value={"status": "completed", "result_url": "https://x.test/first.png"}), \
                 patch.object(first_last, "download_otu_image_result") as downloader, \
                 patch.object(first_last, "upload_image_to_feishu", return_value="ft_first"):
                result = first_last.render_first_frame("rec1")

        self.assertEqual(result["status"], "success")
        media_downloader.assert_called_once()
        self.assertEqual(media_downloader.call_args.args[1], "ft_product")
        args = submitter.call_args.args
        kwargs = submitter.call_args.kwargs
        self.assertEqual(args[1], "first prompt")
        self.assertNotIn("Reference image 1 = product reference", args[1])
        self.assertNotIn("Product identity anchor", args[1])
        self.assertEqual(kwargs["input_mode"], "image-to-image")
        self.assertEqual(kwargs["image_path"], str(product_path))
        self.assertEqual(kwargs["metadata"]["aspectRatio"], "9:16")
        self.assertEqual(kwargs["metadata"]["reference_roles"], ["product:1"])
        self.assertEqual(kwargs["metadata"]["product_record_id"], "recProduct")
        self.assertEqual(kwargs["metadata"]["urls"], ["https://x.test/product.png"])
        self.assertNotIn("pawradise", args[1])
        self.assertNotIn("Pet Lily", args[1])
        self.assertNotIn("Pet Care", args[1])
        downloader.assert_called_once()
        self.assertEqual(updates[-1]["首帧图生成状态"], "成功")
        self.assertEqual(updates[-1]["关联产品记录"], ["recProduct"])
        self.assertEqual(updates[-1]["产品名称"], "Pet Odor Spray")
        self.assertIn("ft_product", updates[-1]["产品参考图file_tokenJSON"])
        self.assertEqual(updates[-1]["首帧审核状态"], "待确认")
        self.assertEqual(updates[-1]["首帧图file_token"], "ft_first")
        self.assertEqual(updates[-1]["首帧图版本"], 2)
        self.assertIn("first_frame_v2", updates[-1]["首帧图本地路径"])

    def test_render_first_frame_resumes_existing_otu_task_without_resubmitting(self):
        updates = []
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(first_last, "TABLE_FIRST_LAST_VIDEO", "tbl_first_last"), \
                 patch.object(first_last, "get_feishu_token", return_value="token"), \
                 patch.object(first_last, "safe_get_record", side_effect=[
                     {
                         "记录类型": "场景子任务",
                         "记录状态": "有效",
                         "首帧生图提示词": "first prompt",
                         "首帧图生成状态": "生成中",
                         "首帧图版本": 2,
                         "首帧图任务ID": "img_task_existing",
                         "首帧图原始响应JSON": json.dumps({"submit": {"id": "img_task_existing"}}),
                     },
                     {"记录状态": "有效", "首帧图生成状态": "生成中", "首帧图版本": 2, "首帧图任务ID": "img_task_existing"},
                 ]), \
                 patch.object(first_last, "safe_update_record", side_effect=lambda token, table, rid, fields: updates.append(fields)), \
                 patch.object(first_last, "filter_existing_fields", side_effect=lambda token, table, fields: fields), \
                 patch.object(first_last, "ensure_work_dir", return_value=Path(tmp)), \
                 patch.object(first_last, "get_stage_config", return_value=("cfg_img", {"api_key": "sk", "api_base": "https://otuapi.com", "model": "gpt-image-2", "size": "1024x1024"})), \
                 patch.object(first_last, "submit_otu_image_task") as submitter, \
                 patch.object(first_last, "collect_product_reference_images") as collect_refs, \
                 patch.object(first_last, "reference_urls_for_refs") as reference_urls, \
                 patch.object(first_last, "poll_otu_image_task", return_value={"status": "completed", "result_url": "https://x.test/first.png"}) as poller, \
                 patch.object(first_last, "download_otu_image_result") as downloader, \
                 patch.object(first_last, "upload_image_to_feishu", return_value="ft_first"):
                result = first_last.render_first_frame("rec1")

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["task_id"], "img_task_existing")
        submitter.assert_not_called()
        collect_refs.assert_not_called()
        reference_urls.assert_not_called()
        poller.assert_called_once()
        self.assertEqual(poller.call_args.args[1], "img_task_existing")
        downloader.assert_called_once()
        self.assertEqual(updates[0]["首帧图任务ID"], "img_task_existing")
        self.assertIn("恢复轮询已有 OTU 首帧图任务", updates[0]["首帧图错误信息"])
        self.assertEqual(updates[-1]["首帧图生成状态"], "成功")
        self.assertEqual(updates[-1]["首帧图file_token"], "ft_first")

    def test_collect_product_reference_images_uses_uploaded_product_attachment_without_cropping(self):
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            product_path = work_dir / "product_reference.png"
            product_path.write_bytes(b"product-reference")

            with patch.object(first_last, "download_feishu_media", return_value=product_path):
                refs = first_last.collect_product_reference_images(
                    "token",
                    {"product_tokens": ["ft_product"]},
                    work_dir,
                )

            self.assertEqual(len(refs), 1)
            self.assertEqual(refs[0]["path"], str(product_path))
            self.assertNotIn("submit_path", refs[0])
            self.assertFalse((work_dir / "reference_product_1_identity.png").exists())

    def test_main_does_not_overwrite_record_when_stale_guard_blocks_old_task(self):
        with patch.object(sys, "argv", ["tk_first_last_video.py", "first-frame", "rec1"]), \
             patch.object(first_last, "render_first_frame", side_effect=RuntimeError("首帧图版本 已变更，停止写回，避免旧任务覆盖新结果")), \
             patch.object(first_last, "log_event"), \
             patch.object(first_last, "get_feishu_token", return_value="token"), \
             patch.object(first_last, "filter_existing_fields", side_effect=lambda token, table, fields: fields), \
             patch.object(first_last, "safe_update_record") as updater:
            exit_code = first_last.main()

        self.assertEqual(exit_code, 1)
        updater.assert_not_called()

    def test_advance_first_review_is_idempotent(self):
        updates = []
        with patch.object(first_last, "TABLE_FIRST_LAST_VIDEO", "tbl_first_last"), \
             patch.object(first_last, "get_feishu_token", return_value="token"), \
             patch.object(first_last, "safe_get_record", return_value={"首帧审核状态": "通过", "尾帧图生成状态": "不触发"}), \
             patch.object(first_last, "safe_update_record", side_effect=lambda token, table, rid, fields: updates.append(fields)), \
             patch.object(first_last, "filter_existing_fields", side_effect=lambda token, table, fields: fields):
            result = first_last.advance_first_review("rec1")

        self.assertEqual(result["status"], "triggered")
        self.assertEqual(updates[-1]["首帧审核状态"], "已触发尾帧")
        self.assertEqual(updates[-1]["尾帧图生成状态"], "待生成")

        with patch.object(first_last, "TABLE_FIRST_LAST_VIDEO", "tbl_first_last"), \
             patch.object(first_last, "get_feishu_token", return_value="token"), \
             patch.object(first_last, "safe_get_record", return_value={"首帧审核状态": "已触发尾帧", "尾帧图生成状态": "待生成"}), \
             patch.object(first_last, "safe_update_record") as updater:
            result = first_last.advance_first_review("rec1")

        self.assertEqual(result["status"], "skipped")
        updater.assert_not_called()

    def test_render_last_frame_uses_first_frame_reference(self):
        updates = []
        with tempfile.TemporaryDirectory() as tmp:
            first_path = Path(tmp) / "first.png"
            first_path.write_bytes(b"x" * 2000)
            product_path = Path(tmp) / "product.png"
            product_path.write_bytes(b"x" * 2000)
            with patch.object(first_last, "TABLE_FIRST_LAST_VIDEO", "tbl_first_last"), \
                 patch.object(first_last, "get_feishu_token", return_value="token"), \
                 patch.object(first_last, "safe_get_record", side_effect=[
                     {"记录类型": "场景子任务", "记录状态": "有效", "尾帧生图提示词": "last prompt", "首帧图": [{"file_token": "old_attachment"}], "首帧图file_token": "ft_first", "尾帧图版本": 3, "关联产品记录": [{"record_ids": ["recProduct"]}]},
                     {"产品名称-zh": "Pet Odor Spray", "产品图片": [{"file_token": "ft_product"}]},
                     {"记录状态": "有效", "尾帧图生成状态": "生成中", "尾帧图版本": 3, "尾帧图任务ID": "img_task_2"},
                 ]), \
                 patch.object(first_last, "safe_update_record", side_effect=lambda token, table, rid, fields: updates.append(fields)), \
                 patch.object(first_last, "filter_existing_fields", side_effect=lambda token, table, fields: fields), \
                 patch.object(first_last, "ensure_work_dir", return_value=Path(tmp)), \
                 patch.object(first_last, "download_feishu_media", side_effect=[first_path, product_path]) as media_downloader, \
                 patch.object(first_last, "get_tmp_download_url_for_attachment", side_effect=["https://x.test/first.png", "https://x.test/product.png"]), \
                 patch.object(first_last, "get_stage_config", return_value=("cfg_img", {"api_key": "sk", "api_base": "https://otuapi.com", "model": "gpt-image-2", "size": "1024x1024"})), \
                 patch.object(first_last, "submit_otu_image_task", return_value=("img_task_2", {"id": "img_task_2"})) as submitter, \
                 patch.object(first_last, "poll_otu_image_task", return_value={"status": "completed", "result_url": "https://x.test/last.png"}), \
                 patch.object(first_last, "download_otu_image_result"), \
                 patch.object(first_last, "upload_image_to_feishu", return_value="ft_last"):
                result = first_last.render_last_frame("rec1")

        self.assertEqual(result["status"], "success")
        self.assertEqual(media_downloader.call_count, 2)
        self.assertEqual(media_downloader.call_args_list[0].args[1], "ft_first")
        self.assertEqual(media_downloader.call_args_list[1].args[1], "ft_product")
        args = submitter.call_args.args
        kwargs = submitter.call_args.kwargs
        self.assertEqual(args[1], "last prompt")
        self.assertNotIn("Vertical 9:16 portrait frame", args[1])
        self.assertNotIn("Reference image 1 = starting frame editing base", args[1])
        self.assertNotIn("Reference image 2 = product identity reference", args[1])
        self.assertNotIn("Product identity anchor", args[1])
        self.assertNotIn("pawradise", args[1])
        self.assertNotIn("Pet Lily", args[1])
        self.assertNotIn("Pet Care", args[1])
        self.assertEqual(kwargs["input_mode"], "image-to-image")
        self.assertEqual(kwargs["image_path"], str(first_path))
        self.assertEqual(kwargs["metadata"]["urls"], ["https://x.test/first.png", "https://x.test/product.png"])
        self.assertEqual(kwargs["metadata"]["reference_roles"], ["first_frame", "product:1"])
        self.assertEqual(kwargs["metadata"]["product_record_id"], "recProduct")
        self.assertEqual(updates[-1]["尾帧图生成状态"], "成功")
        self.assertEqual(updates[-1]["关联产品记录"], ["recProduct"])
        self.assertEqual(updates[-1]["产品名称"], "Pet Odor Spray")
        self.assertIn("ft_product", updates[-1]["产品参考图file_tokenJSON"])
        raw_response = json.loads(updates[-1]["尾帧图原始响应JSON"])
        self.assertEqual(raw_response["references"]["reference_roles"], ["first_frame", "product:1"])
        self.assertEqual(raw_response["references"]["reference_file_tokens"], ["ft_first", "ft_product"])
        self.assertEqual(raw_response["references"]["reference_urls"], ["https://x.test/first.png", "https://x.test/product.png"])
        self.assertTrue(raw_response["references"]["remote_reference_urls"])
        self.assertEqual(raw_response["references"]["aspect_ratio"], "9:16")
        self.assertEqual(raw_response["references"]["size"], "1024x1024")
        self.assertEqual(updates[-1]["尾帧审核状态"], "待确认")
        self.assertEqual(updates[-1]["尾帧图file_token"], "ft_last")
        self.assertEqual(updates[-1]["尾帧图版本"], 3)

    def test_render_last_frame_resumes_existing_otu_task_without_resubmitting(self):
        updates = []
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(first_last, "TABLE_FIRST_LAST_VIDEO", "tbl_first_last"), \
                 patch.object(first_last, "get_feishu_token", return_value="token"), \
                 patch.object(first_last, "safe_get_record", side_effect=[
                     {
                         "记录类型": "场景子任务",
                         "记录状态": "有效",
                         "尾帧生图提示词": "last prompt",
                         "尾帧图生成状态": "生成中",
                         "尾帧图版本": 3,
                         "尾帧图任务ID": "img_task_existing_last",
                         "尾帧图原始响应JSON": json.dumps({"submit": {"id": "img_task_existing_last"}}),
                     },
                     {"记录状态": "有效", "尾帧图生成状态": "生成中", "尾帧图版本": 3, "尾帧图任务ID": "img_task_existing_last"},
                 ]), \
                 patch.object(first_last, "safe_update_record", side_effect=lambda token, table, rid, fields: updates.append(fields)), \
                 patch.object(first_last, "filter_existing_fields", side_effect=lambda token, table, fields: fields), \
                 patch.object(first_last, "ensure_work_dir", return_value=Path(tmp)), \
                 patch.object(first_last, "download_feishu_media") as media_downloader, \
                 patch.object(first_last, "get_stage_config", return_value=("cfg_img", {"api_key": "sk", "api_base": "https://otuapi.com", "model": "gpt-image-2", "size": "1024x1024"})), \
                 patch.object(first_last, "submit_otu_image_task") as submitter, \
                 patch.object(first_last, "collect_product_reference_images") as collect_refs, \
                 patch.object(first_last, "reference_urls_for_refs") as reference_urls, \
                 patch.object(first_last, "poll_otu_image_task", return_value={"status": "completed", "result_url": "https://x.test/last.png"}) as poller, \
                 patch.object(first_last, "download_otu_image_result"), \
                 patch.object(first_last, "upload_image_to_feishu", return_value="ft_last"):
                result = first_last.render_last_frame("rec1")

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["task_id"], "img_task_existing_last")
        submitter.assert_not_called()
        media_downloader.assert_not_called()
        collect_refs.assert_not_called()
        reference_urls.assert_not_called()
        poller.assert_called_once()
        self.assertEqual(poller.call_args.args[1], "img_task_existing_last")
        self.assertEqual(updates[0]["尾帧图任务ID"], "img_task_existing_last")
        self.assertIn("恢复轮询已有 OTU 尾帧图任务", updates[0]["尾帧图错误信息"])
        self.assertEqual(updates[-1]["尾帧图生成状态"], "成功")
        self.assertEqual(updates[-1]["尾帧图file_token"], "ft_last")

    def test_submit_first_last_video_task_uses_two_reference_frames(self):
        with tempfile.NamedTemporaryFile(suffix=".png") as first, tempfile.NamedTemporaryFile(suffix=".png") as last:
            first.write(b"first")
            first.flush()
            last.write(b"last")
            last.flush()
            response = Mock()
            response.status_code = 200
            response.json.return_value = {"id": "task_video", "status": "queued"}
            response.text = '{"id":"task_video"}'

            with patch.object(first_last.requests, "post", return_value=response) as post:
                task_id, body = first_last.submit_first_last_video_task(
                    {"api_key": "sk", "api_base": "https://otuapi.com", "model": "veo_3_1-fast-fl"},
                    "video prompt",
                    first.name,
                    last.name,
                    seconds="6",
                    size="720x1280",
                    aspect_ratio="9:16",
                )

        self.assertEqual(task_id, "task_video")
        self.assertEqual(body["status"], "queued")
        args, kwargs = post.call_args
        self.assertEqual(args[0], "https://otuapi.com/v1/videos")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer sk")
        self.assertEqual(kwargs["data"]["prompt"], "video prompt")
        self.assertEqual(kwargs["data"]["seconds"], "6")
        self.assertEqual([item[0] for item in kwargs["files"]], ["input_reference[]", "input_reference[]"])

    def test_submit_first_last_video_task_retries_transient_network_failure(self):
        with tempfile.NamedTemporaryFile(suffix=".png") as first, tempfile.NamedTemporaryFile(suffix=".png") as last:
            first.write(b"first")
            first.flush()
            last.write(b"last")
            last.flush()
            response = Mock()
            response.status_code = 200
            response.json.return_value = {"id": "task_video", "status": "queued"}
            response.text = '{"id":"task_video"}'

            with patch.object(first_last.requests, "post", side_effect=[first_last.requests.exceptions.SSLError("unexpected eof"), response]) as post, \
                 patch("common.sleep_backoff"):
                task_id, body = first_last.submit_first_last_video_task(
                    {"api_key": "sk", "api_base": "https://otuapi.com", "model": "veo_3_1-fast-fl"},
                    "video prompt",
                    first.name,
                    last.name,
                    seconds="6",
                    size="720x1280",
                    aspect_ratio="9:16",
                )

        self.assertEqual(task_id, "task_video")
        self.assertEqual(body["status"], "queued")
        self.assertEqual(post.call_count, 2)

    def test_render_video_resumes_existing_otu_task_without_resubmitting(self):
        updates = []
        fields = {
            "记录类型": "场景子任务",
            "记录状态": "有效",
            "首尾帧生视频提示词": "video prompt",
            "首帧图file_token": "ft_first",
            "尾帧图file_token": "ft_last",
            "视频生成状态": "生成中",
            "视频任务ID": "task_existing",
            "视频版本": 2,
            "目标时长秒": 6,
        }

        with patch.object(first_last, "TABLE_FIRST_LAST_VIDEO", "tbl_first_last"), \
             patch.object(first_last, "get_feishu_token", return_value="token"), \
             patch.object(first_last, "safe_get_record", return_value=fields), \
             patch.object(first_last, "get_stage_config", return_value=("rec_cfg", {
                 "api_key": "sk",
                 "api_base": "https://otuapi.com",
                 "model": "veo_3_1-fast-fl",
                 "size": "720x1280",
                 "aspect_ratio": "9:16",
             })), \
             patch.object(first_last, "get_table_field_types", return_value={"首尾帧视频URL": 1}), \
             patch.object(first_last, "submit_first_last_video_task") as submitter, \
             patch.object(first_last, "download_feishu_media") as download_media, \
             patch.object(first_last, "poll_otu_video_task", return_value={"status": "completed", "video_url": "https://x.test/video.mp4"}) as poller, \
             patch.object(first_last, "download_video", return_value="/tmp/video.mp4") as downloader, \
             patch.object(first_last, "upload_video_to_feishu", return_value="ft_video") as uploader, \
             patch.object(first_last, "safe_update_record", side_effect=lambda token, table, rid, patch_fields: updates.append(patch_fields)), \
             patch.object(first_last, "filter_existing_fields", side_effect=lambda token, table, patch_fields: patch_fields):
            result = first_last.render_video("rec1")

        submitter.assert_not_called()
        download_media.assert_not_called()
        poller.assert_called_once()
        self.assertEqual(poller.call_args.args[1], "task_existing")
        downloader.assert_called_once_with("https://x.test/video.mp4", result["output_path"])
        uploader.assert_called_once()
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["task_id"], "task_existing")
        self.assertEqual(updates[0]["视频任务ID"], "task_existing")
        self.assertIn("恢复轮询", updates[0]["视频错误信息"])
        self.assertEqual(updates[-1]["视频生成状态"], "成功")
        self.assertEqual(updates[-1]["首尾帧视频file_token"], "ft_video")

    def test_render_video_uses_record_video_generation_model_for_new_submit(self):
        updates = []
        fields = {
            "记录类型": "场景子任务",
            "记录状态": "有效",
            "首尾帧生视频提示词": "video prompt",
            "首帧图file_token": "ft_first",
            "尾帧图file_token": "ft_last",
            "视频生成状态": "待生成",
            "视频任务ID": "",
            "视频版本": 2,
            "视频生成模型": "OTU / veo_3_1-fl",
            "目标时长秒": 6,
        }

        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(first_last, "TABLE_FIRST_LAST_VIDEO", "tbl_first_last"), \
             patch.object(first_last, "get_feishu_token", return_value="token"), \
             patch.object(first_last, "safe_get_record", return_value=fields), \
             patch.object(first_last, "ensure_stage_work_dir", return_value=Path(tmp)), \
             patch.object(first_last, "get_stage_config", return_value=("rec_cfg", {
                 "api_key": "sk",
                 "api_base": "https://otuapi.com",
                 "model": "veo_3_1-fast-fl",
                 "size": "720x1280",
                 "aspect_ratio": "9:16",
             })), \
             patch.object(first_last, "get_table_field_types", return_value={"首尾帧视频URL": 1}), \
             patch.object(first_last, "submit_first_last_video_task", return_value=("task_new", {"id": "task_new"})) as submitter, \
             patch.object(first_last, "download_feishu_media", side_effect=lambda token, file_token, path: str(path)), \
             patch.object(first_last, "poll_otu_video_task", return_value={"status": "completed", "video_url": "https://x.test/video.mp4"}), \
             patch.object(first_last, "download_video", return_value="/tmp/video.mp4"), \
             patch.object(first_last, "upload_video_to_feishu", return_value="ft_video"), \
             patch.object(first_last, "ensure_current_generation"), \
             patch.object(first_last, "safe_update_record", side_effect=lambda token, table, rid, patch_fields: updates.append(patch_fields)), \
             patch.object(first_last, "filter_existing_fields", side_effect=lambda token, table, patch_fields: patch_fields):
            result = first_last.render_video("rec1")

        submitted_cfg = submitter.call_args.args[0]
        self.assertEqual(submitted_cfg["model"], "veo_3_1-fl")
        self.assertEqual(result["model"], "veo_3_1-fl")
        self.assertEqual(result["model_source"], "视频生成模型")
        self.assertTrue(any(update.get("视频生成模型") == "OTU / veo_3_1-fl" for update in updates))

    def test_render_video_uses_aihubmix_native_veo_when_generation_model_selects_aihubmix(self):
        updates = []
        fields = {
            "记录类型": "场景子任务",
            "记录状态": "有效",
            "首尾帧生视频提示词": "video prompt",
            "首帧图file_token": "ft_first",
            "尾帧图file_token": "ft_last",
            "视频生成状态": "待生成",
            "视频任务ID": "",
            "视频版本": 2,
            "视频生成模型": "AIHubMix / veo-3.1-fast-generate-preview",
            "目标时长秒": 6,
        }
        operation = Mock(name="operations/op_aihubmix")
        operation.name = "operations/op_aihubmix"
        completed = Mock()
        generated_video = Mock()

        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(first_last, "TABLE_FIRST_LAST_VIDEO", "tbl_first_last"), \
             patch.object(first_last, "get_feishu_token", return_value="token"), \
             patch.object(first_last, "safe_get_record", return_value=fields), \
             patch.object(first_last, "ensure_stage_work_dir", return_value=Path(tmp)), \
             patch.object(first_last, "get_stage_config", return_value=("rec_cfg", {
                 "api_key": "sk",
                 "api_base": "https://aihubmix.com/gemini",
                 "model": "veo-3.1-fast-generate-preview",
                 "size": "720x1280",
                 "aspect_ratio": "9:16",
             })), \
             patch.object(first_last, "get_table_field_types", return_value={"首尾帧视频URL": 1}), \
             patch.object(first_last, "get_native_veo_client", return_value="client") as client_factory, \
             patch.object(first_last, "call_native_veo_first_frame_task", return_value=operation) as native_submitter, \
             patch.object(first_last, "poll_native_veo_operation", return_value=completed) as native_poller, \
             patch.object(first_last, "extract_native_generated_video", return_value=generated_video), \
             patch.object(first_last, "native_generated_video_uri", return_value="https://x.test/native.mp4"), \
             patch.object(first_last, "download_native_veo_video", return_value="/tmp/video.mp4") as native_downloader, \
             patch.object(first_last, "submit_first_last_video_task") as otu_submitter, \
             patch.object(first_last, "poll_otu_video_task") as otu_poller, \
             patch.object(first_last, "download_feishu_media", side_effect=lambda token, file_token, path: str(path)), \
             patch.object(first_last, "upload_video_to_feishu", return_value="ft_video"), \
             patch.object(first_last, "ensure_current_generation"), \
             patch.object(first_last, "safe_update_record", side_effect=lambda token, table, rid, patch_fields: updates.append(patch_fields)), \
             patch.object(first_last, "filter_existing_fields", side_effect=lambda token, table, patch_fields: patch_fields):
            result = first_last.render_video("rec1")

        otu_submitter.assert_not_called()
        otu_poller.assert_not_called()
        client_factory.assert_called_once()
        native_submitter.assert_called_once()
        self.assertEqual(native_submitter.call_args.args[0]["model"], "veo-3.1-fast-generate-preview")
        self.assertEqual(native_submitter.call_args.args[4], "720p")
        self.assertEqual(native_submitter.call_args.kwargs["last_frame_path"], str(Path(tmp) / "rec1_video_last_frame_v2.png"))
        native_poller.assert_called_once_with("client", operation)
        native_downloader.assert_called_once_with("client", generated_video, result["output_path"])
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["task_id"], "operations/op_aihubmix")
        self.assertTrue(any(update.get("视频通道") == "AIHubMix" for update in updates))
        self.assertTrue(any(update.get("视频生成模型") == "AIHubMix / veo-3.1-fast-generate-preview" for update in updates))


if __name__ == "__main__":
    unittest.main()
