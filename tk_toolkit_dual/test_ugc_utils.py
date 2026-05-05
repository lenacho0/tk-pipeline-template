import unittest

from ugc_utils import (
    extract_linked_record_ids,
    extract_text,
    parse_dual_output,
)


class UGCUtilsTest(unittest.TestCase):
    def test_extract_text_handles_feishu_text_list(self):
        self.assertEqual(extract_text([{"text": "hello"}, {"text": " world"}]), "hello world")

    def test_extract_text_prefers_feishu_url_link(self):
        value = {"link": "https://example.com/video.mp4", "text": "example video"}
        self.assertEqual(extract_text(value), "https://example.com/video.mp4")

    def test_extract_linked_record_ids_handles_feishu_link_shape(self):
        value = [{"record_ids": ["recA"]}, {"record_ids": ["recB", "recC"]}]
        self.assertEqual(extract_linked_record_ids(value), ["recA", "recB", "recC"])

    def test_parse_dual_output_extracts_json_and_markdown(self):
        raw = 'JSON_OUTPUT\n{"a": 1}\nMARKDOWN_OUTPUT\n# Report\nhello'
        parsed = parse_dual_output(raw)
        self.assertEqual(parsed.json_obj, {"a": 1})
        self.assertEqual(parsed.markdown.strip(), "# Report\nhello")

    def test_parse_dual_output_rejects_missing_json_marker(self):
        raw = '{"a": 1}\nMARKDOWN_OUTPUT\n# Report'
        with self.assertRaisesRegex(ValueError, "JSON_OUTPUT"):
            parse_dual_output(raw)

    def test_parse_dual_output_rejects_fenced_json(self):
        raw = 'JSON_OUTPUT\n```json\n{"a": 1}\n```\nMARKDOWN_OUTPUT\n# Report'
        with self.assertRaisesRegex(ValueError, "code fence"):
            parse_dual_output(raw)


if __name__ == "__main__":
    unittest.main()
