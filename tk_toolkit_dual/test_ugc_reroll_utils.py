import unittest

import ugc_reroll_utils as rr


class UGCRerollUtilsTest(unittest.TestCase):
    def test_make_group_id_is_stable_for_stage_and_source(self):
        self.assertEqual(rr.make_group_id("grid", "recvieE3B2omPp"), "UGC-GRID-GROUP-E3B2omPp")
        self.assertEqual(rr.make_group_id("video", "recvin7kJqxQuo"), "UGC-VIDEO-GROUP-7kJqxQuo")

    def test_next_candidate_index_ignores_missing_and_bad_values(self):
        records = [
            {"fields": {"候选序号": 1}},
            {"fields": {"候选序号": "2"}},
            {"fields": {"候选序号": "bad"}},
            {"fields": {}},
        ]
        self.assertEqual(rr.next_candidate_index(records), 3)

    def test_build_candidate_fields_defaults_to_candidate(self):
        fields = rr.build_candidate_fields("UGC-GRID-GROUP-abc", 2, source_record_id="rec_old")
        self.assertEqual(fields["重生成组ID"], "UGC-GRID-GROUP-abc")
        self.assertEqual(fields["候选序号"], 2)
        self.assertEqual(fields["候选状态"], "候选")
        self.assertEqual(fields["重生成来源记录ID"], "rec_old")


if __name__ == "__main__":
    unittest.main()
