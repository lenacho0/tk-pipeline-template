import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import tk_create_shot_parent_from_003 as parent


class CreateShotParentFrom003Tests(unittest.TestCase):
    def test_build_parent_fields_writes_link_fields_as_record_id_lists(self):
        source_fields = {
            "手写脚本内容": "## 成片脚本\n...",
            "选择产品": "非泼罗尼体外驱虫",
            "关联产品": [{"record_ids": ["recProduct"], "text": "非泼罗尼体外驱虫"}],
            "选择模特": [{"record_ids": ["recModel"], "text": "金毛"}],
            "选择音色": [{"record_ids": ["recVoice"], "text": "年轻小狗声线"}],
            "口播音色ID": "voice-123",
            "视频时长": "25s",
            "分镜风格": "全写实",
        }

        fields = parent.build_parent_fields("token", "rec003", source_fields)

        self.assertEqual(fields["关联产品"], ["recProduct"])
        self.assertEqual(fields["选择模特"], ["recModel"])
        self.assertEqual(fields["选择音色"], ["recVoice"])
        self.assertNotIn("选择产品", fields)
        self.assertEqual(fields["口播音色ID"], "voice-123")

    def test_build_parent_fields_keeps_select_product_when_no_linked_product(self):
        source_fields = {
            "手写脚本内容": "script",
            "选择产品": "宠物尿味分解除臭喷雾",
            "视频时长": "15s",
        }

        fields = parent.build_parent_fields("token", "rec003", source_fields)

        self.assertEqual(fields["选择产品"], "宠物尿味分解除臭喷雾")
        self.assertNotIn("关联产品", fields)


if __name__ == "__main__":
    unittest.main()
