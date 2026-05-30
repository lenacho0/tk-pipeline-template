import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cleanup_generated_files as cleanup


class CleanupGeneratedFilesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.tmp.name)
        self.old_now = 1_800_000_000.0

    def tearDown(self):
        self.tmp.cleanup()

    def make_file(self, relative_path, *, age_days):
        path = self.repo_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("payload", encoding="utf-8")
        mtime = self.old_now - age_days * 24 * 60 * 60
        os.utime(path, (mtime, mtime))
        return path

    def run_cleanup(self, *, execute=True):
        return cleanup.run_cleanup(
            repo_root=self.repo_root,
            days=7,
            execute=execute,
            now=self.old_now,
            log_file=None,
            tracked_paths=set(),
        )

    def test_deletes_files_older_than_retention_in_whitelisted_dirs(self):
        old_file = self.make_file(
            "tk_toolkit_dual/workspace_ryan/storyboard_work/rec_old/shot.png",
            age_days=8,
        )

        result = self.run_cleanup()

        self.assertFalse(old_file.exists())
        self.assertEqual(result.deleted_count, 1)
        self.assertEqual(result.deleted_bytes, len("payload"))

    def test_keeps_recent_files_in_whitelisted_dirs(self):
        recent_file = self.make_file(
            "tk_toolkit_dual/workspace_ryan/shot_video_work/rec_new/video.mp4",
            age_days=2,
        )

        result = self.run_cleanup()

        self.assertTrue(recent_file.exists())
        self.assertEqual(result.deleted_count, 0)

    def test_keeps_files_outside_whitelisted_dirs(self):
        outside_file = self.make_file("docs/old_note.txt", age_days=30)

        result = self.run_cleanup()

        self.assertTrue(outside_file.exists())
        self.assertEqual(result.deleted_count, 0)

    def test_skips_symlinks_inside_whitelisted_dirs(self):
        target = self.make_file("outside_target.bin", age_days=30)
        link = self.repo_root / "tk_toolkit_dual/workspace_ryan/storyboard_work/rec/link.bin"
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(target)
        old_time = self.old_now - 30 * 24 * 60 * 60
        os.utime(link, (old_time, old_time), follow_symlinks=False)

        result = self.run_cleanup()

        self.assertTrue(link.is_symlink())
        self.assertTrue(target.exists())
        self.assertEqual(result.deleted_count, 0)

    def test_removes_empty_child_dirs_but_keeps_whitelist_root(self):
        old_file = self.make_file(
            "first_last_video_work/rec_old/video_v1/output.mp4",
            age_days=8,
        )
        whitelist_root = self.repo_root / "first_last_video_work"
        deleted_parent = old_file.parent

        result = self.run_cleanup()

        self.assertFalse(old_file.exists())
        self.assertFalse(deleted_parent.exists())
        self.assertTrue(whitelist_root.exists())
        self.assertEqual(result.deleted_count, 1)


if __name__ == "__main__":
    unittest.main()
