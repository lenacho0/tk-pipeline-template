import json
import unittest
from unittest.mock import patch

import tk_ugc_video_prompts as video_prompts


def sample_ugc05_fields(shot_index=1, content_type="dialogue", dialogue="สวัสดี", hd=True, video_type="UGC"):
    shot = {
        "shot_index": shot_index,
        "shot_title": "Hook",
        "duration_sec": 3,
        "content_type": content_type,
        "scene": "客厅",
        "camera": "手机固定在茶几上",
        "visual_description": "主人坐在宠物碗旁边",
        "subject_action": "主人轻微抬起右手里的小袋子",
        "character_state": "皱眉、无奈",
        "pet_state": "小狗轻微转头",
        "speaker": "泰国养宠女主人",
        "speaker_visible": True,
        "dialogue": dialogue,
        "dialogue_zh": "你好",
        "video_type": video_type,
        "content_mode": "non_ugc_animation" if video_type == "非UGC" else "ugc",
    }
    fields = {
        "分镜序号": str(shot_index),
        "对应脚本片段JSON": json.dumps(shot, ensure_ascii=False),
        "高清化状态": "成功",
        "高清分镜图路径": f"/tmp/shot_{shot_index:02d}_916.png",
        "高清分镜图file_token": f"ft_{shot_index}",
        "关联脚本版本": [{"record_ids": ["rec03"]}],
        "关联9宫格任务": [{"record_ids": ["rec04"]}],
    }
    if hd:
        fields["高清分镜图"] = [{"file_token": f"ft_attach_{shot_index}", "name": f"shot_{shot_index:02d}_916.png"}]
    return fields


class UGCVideoPromptsTest(unittest.TestCase):
    def test_build_shot_video_prompt_dialogue_locks_input_image_first(self):
        assumptions = []
        item = video_prompts.build_shot_video_prompt("rec05", sample_ugc05_fields(), assumptions)
        self.assertEqual(item["content_type"], "dialogue")
        self.assertEqual(item["video_type"], "UGC")
        self.assertEqual(item["prompt_stage"], video_prompts.UGC_VIDEO_PROMPT_STAGE_NAME)
        self.assertTrue(item["audio_plan"]["has_voiceover"])
        self.assertEqual(item["audio_plan"]["language"], "Thai")
        self.assertIn("严格以输入图片作为唯一视觉锚点", item["prompt_cn"][:80])
        self.assertIn("Use the input image as the only visual anchor", item["prompt_en"][:120])
        self.assertIn("不生成字幕", item["prompt_cn"])
        self.assertIn("No face drift", item["prompt_en"])
        self.assertEqual(assumptions, [])

    def test_non_ugc_video_prompt_routes_to_non_ugc_stage_and_prompt_path(self):
        fields = sample_ugc05_fields(video_type="非UGC")
        item = video_prompts.build_shot_video_prompt("rec05", fields, [])
        self.assertEqual(item["video_type"], "非UGC")
        self.assertEqual(item["content_mode"], "non_ugc_animation")
        self.assertEqual(item["prompt_stage"], video_prompts.NON_UGC_VIDEO_PROMPT_STAGE_NAME)
        self.assertTrue(item["system_prompt_path"].endswith("non-ugc-animation-image-to-video-system-prompt-v1-content.md"))

    def test_silent_action_has_empty_audio_timeline(self):
        fields = sample_ugc05_fields(content_type="silent_action", dialogue="")
        item = video_prompts.build_shot_video_prompt("rec05", fields, [])
        self.assertFalse(item["audio_plan"]["has_voiceover"])
        self.assertEqual(item["audio_plan"]["delivery_type"], "none")
        self.assertEqual(item["audio_plan"]["timeline"], [])
        self.assertIn("无口播", item["prompt_cn"])

    def test_build_video_prompt_batch_supports_dynamic_record_count(self):
        records = {
            "recA": sample_ugc05_fields(shot_index=2, content_type="voiceover", dialogue="เสียงบรรยาย"),
            "recB": sample_ugc05_fields(shot_index=1),
        }
        with patch("tk_ugc_video_prompts.load_ugc_table_ids") as tables:
            tables.return_value = {"ugc_05_shot_images": "tbl05"}
            result = video_prompts.build_video_prompt_batch(
                ["recA", "recB"],
                token="t",
                get_record_fn=lambda token, table, rid: records[rid],
            )
        self.assertEqual(result["validation"]["status"], "ok")
        self.assertEqual(result["video_prompt_batch"]["shot_count"], 2)
        self.assertEqual(result["video_prompt_batch"]["video_type"], "UGC")
        self.assertEqual([p["shot_index"] for p in result["shot_video_prompts"]], [1, 2])

    def test_missing_hd_image_blocks_single_shot(self):
        fields = sample_ugc05_fields(hd=False)
        fields.pop("高清分镜图路径")
        fields.pop("高清分镜图file_token")
        with self.assertRaises(ValueError):
            video_prompts.build_shot_video_prompt("rec05", fields, [])

    def test_build_ugc06_fields_contains_prompt_and_links(self):
        item = video_prompts.build_shot_video_prompt("rec05", sample_ugc05_fields(), [])
        fields = video_prompts.build_ugc06_fields(item)
        self.assertEqual(fields["分镜序号"], 1)
        self.assertEqual(fields["提示词生成状态"], "成功")
        self.assertEqual(fields["视频生成状态"], "待生成")
        self.assertEqual(fields["关联分镜图片"], ["rec05"])
        self.assertIn("图生视频提示词", fields)
        self.assertEqual(fields["高清分镜图"][0]["file_token"], "ft_attach_1")

    def test_build_ugc06_fields_can_include_video_candidate_metadata(self):
        fields = video_prompts.build_ugc06_fields(
            {"ugc05_record_id": "rec05", "shot_index": 1, "prompt_en": "x"},
            candidate_group_id="UGC-VIDEO-GROUP-rec05",
            candidate_index=3,
            reroll_source_record_id="rec06_old",
        )
        self.assertEqual(fields["重生成组ID"], "UGC-VIDEO-GROUP-rec05")
        self.assertEqual(fields["候选序号"], 3)
        self.assertEqual(fields["候选状态"], "候选")
        self.assertEqual(fields["重生成来源记录ID"], "rec06_old")
        self.assertEqual(fields["来源UGC05候选记录ID"], "rec05")


if __name__ == "__main__":
    unittest.main()
