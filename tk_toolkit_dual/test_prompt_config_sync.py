from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prompt_config_sync as sync


class PromptConfigSyncTests(unittest.TestCase):
    def test_resolve_known_stage(self):
        path = sync.resolve_prompt_path("非UGC-脚本生成")
        self.assertEqual(path.name, "non-ugc-animation-script-generation-system-prompt-v3-content.md")

    def test_resolve_unknown_stage_raises_useful_error(self):
        with self.assertRaisesRegex(ValueError, "未知提示词环节"):
            sync.resolve_prompt_path("不存在的环节")

    def test_list_includes_non_ugc_stages(self):
        listed = sync.list_stages()
        self.assertIn("非UGC-爆款视频分析", listed)
        self.assertIn("非UGC-视频提示词生成", listed)

    def test_sync_to_feishu_dry_run_does_not_call_updater(self):
        with tempfile.TemporaryDirectory() as td:
            prompt_path = Path(td) / "prompt.md"
            prompt_path.write_text("local prompt", encoding="utf-8")
            record = {"record_id": "rec1", "fields": {"环节": "测试环节", "提示词": "remote prompt"}}
            with patch.object(sync, "resolve_prompt_path", return_value=prompt_path), \
                 patch.object(sync, "read_remote_prompt", return_value=("rec1", "remote prompt")):
                calls = []
                result = sync.sync_to_feishu(
                    "测试环节",
                    dry_run=True,
                    token_getter=lambda: "token",
                    updater=lambda token, rid, prompt: calls.append((token, rid, prompt)),
                )
            self.assertTrue(result.changed)
            self.assertEqual(result.message, "would update Feishu config")
            self.assertEqual(calls, [])

    def test_sync_from_feishu_writes_local_file(self):
        with tempfile.TemporaryDirectory() as td:
            prompt_path = Path(td) / "prompt.md"
            with patch.object(sync, "resolve_prompt_path", return_value=prompt_path), \
                 patch.object(sync, "read_remote_prompt", return_value=("rec1", "remote prompt")):
                result = sync.sync_from_feishu("测试环节", token_getter=lambda: "token")
            self.assertTrue(result.changed)
            self.assertEqual(prompt_path.read_text(encoding="utf-8"), "remote prompt")


if __name__ == "__main__":
    unittest.main()
