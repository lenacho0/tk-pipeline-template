import unittest

import tk_ugc_reroll_fields as fields


class UGCOneClickFieldsTest(unittest.TestCase):
    def test_required_fields_are_one_click_only(self):
        required = fields.required_fields_for_table("ugc04")
        self.assertEqual(required["一键重生成9宫格"], 7)
        self.assertEqual(required["一键重生成状态"], 3)
        self.assertEqual(required["一键重生成结果"], 1)
        self.assertNotIn("重生成组ID", required)
        self.assertEqual(fields.required_fields_for_table("ugc05"), {})

    def test_missing_field_names_accepts_field_name_or_name(self):
        existing = [{"field_name": "一键重生成9宫格"}, {"name": "一键重生成状态"}]
        missing = fields.missing_field_names(existing, fields.required_fields_for_table("ugc04"))
        self.assertEqual(missing, ["一键重生成结果"])


if __name__ == "__main__":
    unittest.main()
