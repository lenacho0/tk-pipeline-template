import json
import unittest
from unittest.mock import patch

import tk_ugc_script_generate as gen


SAMPLE_HANDOFF = {
    "must_preserve": ["If hook", "ordinary powder comparison"],
    "can_replace": ["pain point", "scene"],
    "hook_templates": ["If your pet..."],
    "script_skeleton": ["hook", "pain", "product", "proof", "cta"],
    "emotional_curve": "焦虑到安心",
    "pain_point_moment_template": "软便/喂食困难",
    "product_entry_rule": "痛点后自然出现",
    "proof_rule": "真实买家秀",
    "trust_rule": "生活化演示",
    "cta_rule": "软性购物车引导",
    "ugc_style_requirements": ["自然光", "手机感"],
    "avoid_in_new_scripts": ["夸大功效"],
    "new_script_directions": [{"direction_name": "痛点拉踩型"}],
}

VALID_MODEL_OUTPUT = """JSON_OUTPUT
{
  "version_task": {
    "version_id": "V01",
    "version_name": "痛点拉踩型",
    "primary_test": "pain_point_moment",
    "target_market": "泰国",
    "new_product": "猫狗通用益生菌软咀嚼片",
    "shot_count": 6,
    "ugc_style": true
  },
  "input_validation": {"ready_for_generation": true, "blocking_errors": [], "missing_optional_info": [], "product_info_confidence": "medium", "notes": ""},
  "reuse_strategy": {"must_preserve": [], "can_replace": [], "copied_mechanism": "", "changed_variables": [], "emotional_curve": "", "conversion_path": "", "ugc_style_requirements": [], "avoid_in_new_scripts": []},
  "character_card": {"description": "Thai pet owner"},
  "environment_card": {"description": "home"},
  "video_setup": {"video_style": "真实UGC", "aspect_ratio": "9:16"},
  "shots": [
    {"shot_index": 1, "content_type": "dialogue", "speaker": "主人", "speaker_visible": true, "dialogue": "สวัสดี", "dialogue_zh": "你好"},
    {"shot_index": 2, "content_type": "voiceover", "speaker": "旁白", "speaker_visible": false, "dialogue": "", "dialogue_zh": ""},
    {"shot_index": 3, "content_type": "silent_action", "speaker": "无", "speaker_visible": false, "dialogue": "", "dialogue_zh": ""},
    {"shot_index": 4, "content_type": "dialogue", "speaker": "主人", "speaker_visible": true, "dialogue": "ดี", "dialogue_zh": "好"},
    {"shot_index": 5, "content_type": "voiceover", "speaker": "旁白", "speaker_visible": false, "dialogue": "", "dialogue_zh": ""},
    {"shot_index": 6, "content_type": "dialogue", "speaker": "主人", "speaker_visible": true, "dialogue": "ลองดู", "dialogue_zh": "试试看"}
  ],
  "six_grid_summary": [
    {"grid_index": 1, "source_shot_index": 1, "content_type": "dialogue", "speaker_visible": true},
    {"grid_index": 2, "source_shot_index": 2, "content_type": "voiceover", "speaker_visible": false},
    {"grid_index": 3, "source_shot_index": 3, "content_type": "silent_action", "speaker_visible": false},
    {"grid_index": 4, "source_shot_index": 4, "content_type": "dialogue", "speaker_visible": true},
    {"grid_index": 5, "source_shot_index": 5, "content_type": "voiceover", "speaker_visible": false},
    {"grid_index": 6, "source_shot_index": 6, "content_type": "dialogue", "speaker_visible": true}
  ],
  "final_cta": {"cta_type": "soft", "cta_text": "", "cta_text_zh": "", "cta_strength": "soft"},
  "self_check": {"six_grid_ready": "通过", "content_type_ready": "通过"},
  "risk_notes": []
}
MARKDOWN_OUTPUT
# UGC脚本 V01｜痛点拉踩

## 分镜脚本
测试脚本正文
"""


class UGCGenerateTest(unittest.TestCase):
    def setUp(self):
        self.table_ids = {
            "ugc_01_analysis": "tbl01",
            "ugc_02_script_batch": "tbl02",
            "ugc_03_script_version": "tbl03",
            "ugc_04_six_grid_storyboard": "tbl04",
            "ugc_05_shot_images": "tbl05",
            "ugc_06_shot_videos": "tbl06",
            "ugc_07_final_concat": "tbl07",
        }
        self.ugc03 = {
            "版本ID": "V01",
            "版本名称": "痛点拉踩型",
            "主测试点": "pain_point_moment",
            "版本差异说明": "强化软便痛点",
            "锁定项说明": "If hook",
            "变量位说明": "替换为软咀嚼片",
            "用户新产品": "猫狗通用益生菌软咀嚼片",
            "目标市场": "泰国",
            "所属批次": [{"record_ids": ["rec02"]}],
            "来源分析记录": [{"record_ids": ["rec01"]}],
            "关联产品": [{"record_ids": ["recProduct"]}],
        }
        self.ugc02 = {"目标市场": "泰国", "用户新产品": "猫狗通用益生菌软咀嚼片"}
        self.ugc01 = {
            "目标市场": "泰国",
            "视频类型": "UGC",
            "分析结果JSON": json.dumps({
                "script_generation_handoff": SAMPLE_HANDOFF,
                "replicable_factors": {"copy_level": "B"},
                "ugc_authenticity": {"phone_feeling": true if False else True},
                "risk_and_optimization": {"risk": "health claim"},
            }, ensure_ascii=False),
        }
        self.product = {
            "产品名称-zh": "猫狗通用益生菌软咀嚼片",
            "产品": "益生菌软咀嚼片",
            "产品名称-th": "โปรไบโอติกสำหรับหมาแมว",
            "产品规格": "软咀嚼片",
            "核心卖点": "好喂，适口性好",
            "使用场景": "日常肠胃护理",
            "目标用户": "猫狗主人",
            "产品价格": "",
        }

    def fake_get(self, token, table_id, record_id):
        if table_id == "tbl03":
            return self.ugc03
        if table_id == "tbl02":
            return self.ugc02
        if table_id == "tbl01":
            return self.ugc01
        if table_id == "tblProduct":
            return self.product
        raise AssertionError((table_id, record_id))

    def test_parse_model_output_validates_dynamic_shots(self):
        parsed = gen.parse_model_output(VALID_MODEL_OUTPUT)
        self.assertEqual(len(parsed["script_json"]["shots"]), 6)
        self.assertIn("测试脚本正文", parsed["markdown"])


    def test_parse_model_output_accepts_five_dynamic_shots(self):
        data = json.loads(VALID_MODEL_OUTPUT.split("JSON_OUTPUT", 1)[1].split("MARKDOWN_OUTPUT", 1)[0].strip())
        data["effective_shot_count"] = 5
        data["version_task"]["shot_count"] = 5
        data["shots"] = data["shots"][:5]
        data["six_grid_summary"] = data["six_grid_summary"][:5]
        text = "JSON_OUTPUT\n" + json.dumps(data, ensure_ascii=False) + "\nMARKDOWN_OUTPUT\n# ok"
        parsed = gen.parse_model_output(text)
        self.assertEqual(parsed["script_json"]["effective_shot_count"], 5)
        self.assertEqual(len(parsed["script_json"]["shots"]), 5)
        self.assertEqual(len(parsed["script_json"]["storyboard_grid_summary"]), 5)

    def test_parse_model_output_rejects_missing_markers(self):
        with self.assertRaises(ValueError):
            gen.parse_model_output('{"shots": []}')

    def test_non_ugc_script_stage_and_prompt_path(self):
        self.assertEqual(gen.script_stage_for_fields({"视频类型": "非UGC"}), gen.NON_UGC_SCRIPT_STAGE_NAME)
        self.assertEqual(gen.script_prompt_path_for_stage(gen.NON_UGC_SCRIPT_STAGE_NAME).name, "non-ugc-animation-script-generation-system-prompt-v3-content.md")
        self.assertEqual(gen.script_stage_for_fields({}), gen.UGC_SCRIPT_STAGE_NAME)

    @patch("tk_ugc_script_generate.load_ugc_table_ids")
    @patch("tk_ugc_script_generate.get_script_model_config")
    @patch("tk_ugc_script_generate.load_system_prompt")
    def test_dry_run_builds_context_without_model_or_write(self, prompt_mock, cfg_mock, tables_mock):
        tables_mock.return_value = self.table_ids
        prompt_mock.return_value = "SYSTEM"
        cfg_mock.return_value = {"record_id": "cfg", "model": "gpt-5.5", "api_key": "k", "api_base": "https://api", "prompt": "", "method": "chat"}
        with patch("common.TABLE_PRODUCT", "tblProduct", create=True):
            result = gen.run_generate("rec03", token="t", get_record_fn=self.fake_get)
        self.assertFalse(result["call_model"])
        self.assertIn("script_generation_handoff", result["context"])
        self.assertIn("SYSTEM", result["prompt_preview"])

    @patch("tk_ugc_script_generate.load_ugc_table_ids")
    @patch("tk_ugc_script_generate.get_script_model_config")
    @patch("tk_ugc_script_generate.load_system_prompt")
    def test_raw_output_write_updates_record(self, prompt_mock, cfg_mock, tables_mock):
        tables_mock.return_value = self.table_ids
        prompt_mock.return_value = "SYSTEM"
        cfg_mock.return_value = {"record_id": "cfg", "model": "gpt-5.5", "api_key": "k", "api_base": "https://api", "prompt": "", "method": "chat"}
        updates = []

        def fake_update(token, table_id, record_id, fields):
            updates.append((table_id, record_id, fields))

        with patch("common.TABLE_PRODUCT", "tblProduct", create=True):
            result = gen.run_generate("rec03", token="t", write=True, raw_model_output=VALID_MODEL_OUTPUT, get_record_fn=self.fake_get, update_record_fn=fake_update)
        self.assertTrue(result["written"])
        self.assertEqual(updates[0][0], "tbl03")
        self.assertEqual(updates[0][2]["脚本生成状态"], "生成成功")
        self.assertEqual(updates[0][2]["下游推进状态"], "待6宫格分镜")


if __name__ == "__main__":
    unittest.main()
