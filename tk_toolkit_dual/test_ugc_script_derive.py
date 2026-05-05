import json
import unittest

from tk_ugc_script_derive import (
    build_derivation_payload,
    choose_test_points,
    normalize_script_count,
    run_derive,
)


class UGCScriptDeriveTest(unittest.TestCase):
    def sample_fields(self):
        analysis = {
            "input_requirements": {"new_product": "猫狗通用益生菌软咀嚼片"},
            "script_generation_handoff": {
                "single_video_pattern_summary": "黄金三段式",
                "must_preserve": ["痛点Hook", "真实买家秀"],
                "can_replace": ["达人身份", "场景"],
                "ugc_style_requirements": ["手机竖屏", "自然口播"],
                "hook_templates": ["你家狗狗也这样吗？"],
                "new_script_directions": [
                    {"direction_name": "痛点对比型", "description": "强化肠胃问题痛点"},
                    {"direction_name": "信任证明型", "description": "强化真实使用反馈"},
                ],
            },
        }
        return {
            "分析结果JSON": json.dumps(analysis, ensure_ascii=False),
            "目标脚本数量": 3,
            "关联产品": [{"record_ids": ["recProduct"], "text": "猫狗通用益生菌软咀嚼片"}],
            "目标市场": "泰国",
        }

    def test_normalize_script_count_defaults_and_bounds(self):
        self.assertEqual(normalize_script_count(""), 3)
        self.assertEqual(normalize_script_count("2"), 2)
        self.assertEqual(normalize_script_count("99"), 6)
        self.assertEqual(normalize_script_count("0"), 1)

    def test_choose_test_points_does_not_make_all_standard(self):
        handoff = json.loads(self.sample_fields()["分析结果JSON"])["script_generation_handoff"]
        points = choose_test_points(handoff, 3)
        self.assertEqual(len(points), 3)
        self.assertNotEqual([p["test_point"] for p in points], ["standard", "standard", "standard"])
        self.assertIn(points[0]["test_point"], {"pain_point_moment", "hook_angle", "trust_builder"})

    def test_build_derivation_payload_builds_batch_and_versions(self):
        payload = build_derivation_payload("recUGC01", self.sample_fields())
        self.assertEqual(payload["target_count"], 3)
        self.assertEqual(payload["batch_fields"]["来源分析记录"], ["recUGC01"])
        self.assertEqual(payload["batch_fields"]["关联产品"], ["recProduct"])
        self.assertEqual(payload["batch_fields"]["目标市场"], "泰国")
        self.assertEqual(payload["batch_fields"]["多版本规划状态"], "已规划")
        self.assertEqual(len(payload["version_fields_list"]), 3)
        self.assertTrue(all(v["脚本生成状态"] == "待生成" for v in payload["version_fields_list"]))
        self.assertTrue(all(v["是否入选"] == "待定" for v in payload["version_fields_list"]))
        self.assertEqual(payload["ugc01_update_fields"]["脚本派生状态"], "已派生")

    def test_build_derivation_payload_requires_handoff(self):
        fields = self.sample_fields()
        fields["分析结果JSON"] = json.dumps({"analysis_scope": "single_video"})
        with self.assertRaisesRegex(ValueError, "script_generation_handoff"):
            build_derivation_payload("recUGC01", fields)

    def test_run_derive_dry_run_does_not_create_or_update(self):
        created = []
        updated = []

        def get_record(_token, _table, _record):
            return self.sample_fields()

        def create_record(_token, table, fields):
            created.append((table, fields))
            return "recCreated"

        def update_record(_token, table, record_id, fields):
            updated.append((table, record_id, fields))

        result = run_derive(
            "recUGC01",
            dry_run=True,
            token="token",
            get_record_fn=get_record,
            create_record_fn=create_record,
            update_record_fn=update_record,
        )
        self.assertTrue(result["dry_run"])
        self.assertIsNone(result["created"])
        self.assertEqual(created, [])
        self.assertEqual(updated, [])

    def test_run_derive_write_creates_batch_versions_and_updates_ugc01(self):
        created = []
        updated = []

        def get_record(_token, _table, _record):
            return self.sample_fields()

        def create_record(_token, table, fields):
            record_id = f"recCreated{len(created)+1}"
            created.append((table, fields, record_id))
            return record_id

        def update_record(_token, table, record_id, fields):
            updated.append((table, record_id, fields))

        result = run_derive(
            "recUGC01",
            dry_run=False,
            token="token",
            get_record_fn=get_record,
            create_record_fn=create_record,
            update_record_fn=update_record,
        )
        self.assertFalse(result["dry_run"])
        self.assertEqual(result["created"]["ugc02_batch_record_id"], "recCreated1")
        self.assertEqual(len(result["created"]["ugc03_version_record_ids"]), 3)
        self.assertEqual(len(created), 4)
        version_creates = created[1:]
        self.assertTrue(all(item[1]["所属批次"] == ["recCreated1"] for item in version_creates))
        self.assertEqual(len(updated), 1)
        self.assertEqual(updated[0][1], "recUGC01")
        self.assertEqual(updated[0][2]["脚本派生状态"], "已派生")


if __name__ == "__main__":
    unittest.main()
