import json
import tempfile
import unittest
from pathlib import Path

import tk_ugc_single_video_analyze as ugc_analyze

from tk_ugc_single_video_analyze import (
    build_analysis_model_prompt,
    build_analysis_prompt_payload,
    build_blocked_analysis_payload,
    build_local_analysis_payload,
    build_success_analysis_payload,
    is_dry_run_from_env,
    load_analysis_system_prompt,
    run_ugc01_analysis,
    should_use_inline_video_input,
    validate_ugc01_inputs,
)


class UGCAnalyzeValidationTest(unittest.TestCase):
    def test_validate_requires_video_source_product_and_market(self):
        fields = {
            "视频来源类型": "视频链接",
            "视频链接": "https://example.com/video.mp4",
            "关联产品": [{"record_ids": ["recProduct"]}],
            "目标市场": "美国",
        }
        result = validate_ugc01_inputs(fields)
        self.assertTrue(result.ready)
        self.assertEqual(result.blocking_missing_fields, [])
        self.assertEqual(result.linked_product_record_id, "recProduct")
        self.assertEqual(result.video_source_type, "link")

    def test_validate_blocks_missing_product(self):
        fields = {"视频来源类型": "视频链接", "视频链接": "https://example.com/video.mp4", "目标市场": "美国"}
        result = validate_ugc01_inputs(fields)
        self.assertFalse(result.ready)
        self.assertIn("linked_product", result.blocking_missing_fields)

    def test_validate_file_has_priority_over_link(self):
        fields = {
            "视频来源类型": "链接+文件",
            "视频链接": "https://example.com/video.mp4",
            "视频文件": [{"file_token": "fileA"}],
            "关联产品": [{"record_ids": ["recProduct"]}],
            "目标市场": "美国",
        }
        result = validate_ugc01_inputs(fields)
        self.assertEqual(result.video_source_type, "file")

    def test_validate_blocks_missing_video_source_and_market(self):
        fields = {"关联产品": [{"record_ids": ["recProduct"]}]}
        result = validate_ugc01_inputs(fields)
        self.assertFalse(result.ready)
        self.assertEqual(result.video_source_type, "missing")
        self.assertIn("video_source", result.blocking_missing_fields)
        self.assertIn("target_market", result.blocking_missing_fields)

    def test_build_blocked_analysis_payload_sets_low_confidence(self):
        result = validate_ugc01_inputs({"目标市场": "美国"})
        payload = build_blocked_analysis_payload(result)
        self.assertEqual(payload["分析状态"], "分析失败")
        self.assertIn("分析结果JSON", payload)
        json_obj = json.loads(payload["分析结果JSON"])
        self.assertFalse(json_obj["input_requirements"]["ready_for_formal_analysis"])
        self.assertEqual(json_obj["confidence"]["overall"], "low")
        self.assertIn("video_source", json_obj["input_requirements"]["blocking_missing_fields"])
        self.assertIn("linked_product", json_obj["input_requirements"]["blocking_missing_fields"])

    def test_load_analysis_system_prompt_contains_dual_output_contract(self):
        prompt = load_analysis_system_prompt()
        self.assertIn("JSON_OUTPUT", prompt)
        self.assertIn("MARKDOWN_OUTPUT", prompt)
        self.assertIn("script_generation_handoff", prompt)

    def test_build_analysis_model_prompt_includes_system_prompt_and_payload(self):
        prompt = build_analysis_model_prompt("SYSTEM", {"target_market": "美国", "product_fields": {"产品名称": "Pet Brush"}})
        self.assertIn("SYSTEM", prompt)
        self.assertIn("JSON_OUTPUT", prompt)
        self.assertIn("target_market", prompt)
        self.assertIn("Pet Brush", prompt)

    def test_build_analysis_prompt_payload_uses_ugc01_product_truth(self):
        fields = {
            "视频链接": "https://example.com/video.mp4",
            "关联产品": [{"record_ids": ["recProduct"]}],
            "目标市场": "美国",
            "目标脚本数量": 3,
        }
        payload = build_analysis_prompt_payload(fields, product_fields={"产品名称": "Pet Brush"}, record_id="recUGC01")
        self.assertEqual(payload["ugc01_record_id"], "recUGC01")
        self.assertEqual(payload["linked_product_record_id"], "recProduct")
        self.assertEqual(payload["target_market"], "美国")
        self.assertEqual(payload["target_script_count"], 3)
        self.assertEqual(payload["product_fields"], {"产品名称": "Pet Brush"})

    def test_build_success_analysis_payload_parses_dual_output(self):
        raw = '''JSON_OUTPUT
{"script_generation_handoff": {"single_video_pattern_summary": "前三秒强钩子，随后快速展示产品解决痛点。"}}
MARKDOWN_OUTPUT
# 分析报告
可复用。'''
        payload = build_success_analysis_payload(raw)
        self.assertEqual(payload["分析状态"], "分析成功")
        self.assertIn("script_generation_handoff", payload["分析结果JSON"])
        self.assertEqual(payload["分析摘要"], "前三秒强钩子，随后快速展示产品解决痛点。")
        self.assertIn("# 分析报告", payload["分析结果Markdown"])

    def test_build_local_analysis_payload_blocks_invalid_input_before_model_output(self):
        payload = build_local_analysis_payload({"目标市场": "美国"})
        self.assertEqual(payload["分析状态"], "分析失败")

    def test_build_local_analysis_payload_requires_model_output_for_ready_input(self):
        fields = {
            "视频链接": "https://example.com/video.mp4",
            "关联产品": [{"record_ids": ["recProduct"]}],
            "目标市场": "美国",
        }
        with self.assertRaisesRegex(ValueError, "模型输出"):
            build_local_analysis_payload(fields)

    def test_is_dry_run_from_env_defaults_safe(self):
        self.assertTrue(is_dry_run_from_env("1"))
        self.assertTrue(is_dry_run_from_env("true"))
        self.assertFalse(is_dry_run_from_env("0"))
        self.assertFalse(is_dry_run_from_env("false"))

    def test_should_use_inline_video_input_for_aitgenne_by_default(self):
        self.assertTrue(should_use_inline_video_input({"api_base": "https://api.aitgenne.com"}))
        self.assertFalse(should_use_inline_video_input({"api_base": "https://aihubmix.com/gemini"}))
        self.assertTrue(should_use_inline_video_input({"api_base": "https://other.example", "video_input_mode": "inline"}))
        self.assertFalse(should_use_inline_video_input({"api_base": "https://api.aitgenne.com", "video_input_mode": "file"}))

    def test_prepare_ugc_video_file_uses_local_video_path_for_smoke_tests(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4") as tmp:
            path, source = ugc_analyze.prepare_ugc_video_file(
                "fake-token",
                {"本地视频路径": tmp.name, "视频链接": "https://example.com/video.mp4"},
                "recUGC01",
            )
        self.assertEqual(path, tmp.name)
        self.assertEqual(source, "local")

    def test_call_ugc_analysis_model_uses_inline_video_for_aitgenne(self):
        import common

        calls = []
        original_prepare = ugc_analyze.prepare_ugc_video_file
        original_build_part = ugc_analyze.build_inline_video_part
        original_client = common.get_gemini_client

        class FakeModels:
            def generate_content(self, model, contents):
                calls.append((model, contents))
                return type("Resp", (), {"text": "JSON_OUTPUT\n{}\nMARKDOWN_OUTPUT\n# ok"})()

        class FakeClient:
            models = FakeModels()

        try:
            ugc_analyze.prepare_ugc_video_file = lambda token, fields, record_id: ("/tmp/fake.mp4", "file")
            ugc_analyze.build_inline_video_part = lambda video_path: "INLINE_VIDEO_PART"
            common.get_gemini_client = lambda api_key, api_base: FakeClient()
            raw = ugc_analyze.call_ugc_analysis_model(
                token="fake-token",
                fields={"视频文件": [{"file_token": "fileA"}]},
                record_id="recUGC01",
                prompt_payload={"target_market": "美国"},
                model_config={"model": "gemini-3.1-pro-preview", "api_key": "fake", "api_base": "https://api.aitgenne.com", "prompt": "SYSTEM"},
            )
        finally:
            ugc_analyze.prepare_ugc_video_file = original_prepare
            ugc_analyze.build_inline_video_part = original_build_part
            common.get_gemini_client = original_client

        self.assertIn("JSON_OUTPUT", raw)
        self.assertEqual(calls[0][0], "gemini-3.1-pro-preview")
        self.assertEqual(calls[0][1][0], "INLINE_VIDEO_PART")
        self.assertIn("target_market", calls[0][1][1])

    def test_run_ugc01_analysis_dry_run_does_not_update_record(self):
        updates = []

        def fake_get_record(token, table_id, record_id):
            return {"目标市场": "美国"}

        def fake_update_record(token, table_id, record_id, fields):
            updates.append(fields)

        result = run_ugc01_analysis(
            "recUGC01",
            dry_run=True,
            token="fake-token",
            get_record_fn=fake_get_record,
            update_record_fn=fake_update_record,
        )
        self.assertEqual(updates, [])
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["record_id"], "recUGC01")
        self.assertEqual(result["write_payload"]["分析状态"], "分析失败")

    def test_run_ugc01_analysis_write_updates_status_then_final_payload(self):
        updates = []

        def fake_get_record(token, table_id, record_id):
            return {"目标市场": "美国"}

        def fake_update_record(token, table_id, record_id, fields):
            updates.append(fields)

        result = run_ugc01_analysis(
            "recUGC01",
            dry_run=False,
            token="fake-token",
            get_record_fn=fake_get_record,
            update_record_fn=fake_update_record,
        )
        self.assertFalse(result["dry_run"])
        self.assertEqual(updates[0], {"分析状态": "分析中"})
        self.assertEqual(updates[1]["分析状态"], "分析失败")

    def test_run_ugc01_analysis_ready_dry_run_fetches_product_and_builds_prompt_payload(self):
        calls = []

        def fake_get_record(token, table_id, record_id):
            calls.append((table_id, record_id))
            if record_id == "recUGC01":
                return {
                    "视频链接": "https://example.com/video.mp4",
                    "关联产品": [{"record_ids": ["recProduct"]}],
                    "目标市场": "美国",
                    "目标脚本数量": 3,
                }
            return {"产品名称": "Pet Brush", "核心卖点": "easy clean"}

        def fake_update_record(token, table_id, record_id, fields):
            raise AssertionError("dry-run should not update")

        result = run_ugc01_analysis(
            "recUGC01",
            dry_run=True,
            token="fake-token",
            get_record_fn=fake_get_record,
            update_record_fn=fake_update_record,
            product_table_id_getter=lambda: "tblProduct",
        )
        self.assertTrue(result["model_required"])
        self.assertIsNone(result["write_payload"])
        self.assertEqual(calls[-1], ("tblProduct", "recProduct"))
        self.assertEqual(result["prompt_payload"]["product_fields"]["产品名称"], "Pet Brush")
        self.assertEqual(result["prompt_payload"]["linked_product_record_id"], "recProduct")

    def test_run_ugc01_analysis_ready_write_without_model_output_refuses_before_updates(self):
        updates = []

        def fake_get_record(token, table_id, record_id):
            if record_id == "recUGC01":
                return {
                    "视频链接": "https://example.com/video.mp4",
                    "关联产品": [{"record_ids": ["recProduct"]}],
                    "目标市场": "美国",
                }
            return {"产品名称": "Pet Brush"}

        def fake_update_record(token, table_id, record_id, fields):
            updates.append(fields)

        with self.assertRaisesRegex(ValueError, "拒绝真实写入"):
            run_ugc01_analysis(
                "recUGC01",
                dry_run=False,
                token="fake-token",
                get_record_fn=fake_get_record,
                update_record_fn=fake_update_record,
                product_table_id_getter=lambda: "tblProduct",
            )
        self.assertEqual(updates, [])

    def test_run_ugc01_analysis_call_model_builds_success_payload(self):
        updates = []
        original = ugc_analyze.call_ugc_analysis_model

        def fake_get_record(token, table_id, record_id):
            if record_id == "recUGC01":
                return {
                    "视频链接": "https://example.com/video.mp4",
                    "关联产品": [{"record_ids": ["recProduct"]}],
                    "目标市场": "美国",
                }
            return {"产品名称": "Pet Brush"}

        def fake_update_record(token, table_id, record_id, fields):
            updates.append(fields)

        def fake_call_model(**kwargs):
            self.assertEqual(kwargs["prompt_payload"]["product_fields"]["产品名称"], "Pet Brush")
            return '''JSON_OUTPUT
{"script_generation_handoff":{"single_video_pattern_summary":"模型摘要"}}
MARKDOWN_OUTPUT
# 模型报告'''

        try:
            ugc_analyze.call_ugc_analysis_model = fake_call_model
            result = run_ugc01_analysis(
                "recUGC01",
                dry_run=False,
                token="fake-token",
                get_record_fn=fake_get_record,
                update_record_fn=fake_update_record,
                product_table_id_getter=lambda: "tblProduct",
                call_model=True,
                model_config_loader=lambda token: {"model": "fake", "api_key": "fake", "api_base": "fake", "prompt": "SYSTEM"},
            )
        finally:
            ugc_analyze.call_ugc_analysis_model = original

        self.assertFalse(result["model_required"])
        self.assertTrue(result["call_model_enabled"])
        self.assertEqual(updates[0], {"分析状态": "分析中"})
        self.assertEqual(updates[1]["分析状态"], "分析成功")
        self.assertEqual(updates[1]["分析摘要"], "模型摘要")


if __name__ == "__main__":
    unittest.main()
