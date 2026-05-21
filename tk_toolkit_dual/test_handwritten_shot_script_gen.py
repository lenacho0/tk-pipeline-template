import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import tk_shot_script_gen as shot_gen
import tk_shot_storyboard as shot_storyboard


class HandwrittenShotScriptGenTests(unittest.TestCase):
    def test_validate_single_character_policy_keeps_one_character(self):
        payload = {
            "story_mode": "single_character_continuity",
            "total_duration_sec": 15,
            "visual_continuity_policy": {
                "lock_product": True,
                "lock_main_character": True,
                "lock_pet": True,
                "lock_environment": True,
            },
            "visual_entities": {},
            "shots": [
                {
                    "shot_no": 1,
                    "duration_sec": 3,
                    "voiceover_text": "thai line",
                    "visual": "小猫冲到镜头前",
                    "character_ids": ["cat_hero"],
                    "pet_ids": ["cat_hero"],
                    "environment_id": "living_room",
                    "image_prompt": "close-up cat hero",
                },
                {
                    "shot_no": 2,
                    "duration_sec": 3,
                    "voiceover_text": "thai line 2",
                    "visual": "同一只小猫继续说话",
                    "character_ids": ["cat_hero"],
                    "pet_ids": ["cat_hero"],
                    "environment_id": "living_room",
                    "image_prompt": "same cat hero speaking",
                },
            ],
        }
        result = shot_gen.validate_and_normalize_payload(payload, 15)
        ids = {tuple(item["character_ids"]) for item in result["shots"]}
        self.assertEqual(ids, {("cat_hero",)})
        self.assertTrue(result["visual_continuity_policy"]["lock_product"])

    def test_validate_multi_case_allows_different_characters(self):
        payload = {
            "story_mode": "multi_case_product_demo",
            "visual_continuity_policy": {
                "lock_product": True,
                "lock_main_character": False,
                "allowed_character_variation": True,
                "allowed_environment_variation": True,
            },
            "shots": [
                {
                    "shot_no": 1,
                    "duration_sec": 2,
                    "voiceover_text": "line 1",
                    "visual": "主人A使用产品",
                    "character_ids": ["owner_a"],
                    "environment_id": "home_a",
                    "image_prompt": "owner a uses product",
                },
                {
                    "shot_no": 2,
                    "duration_sec": 2,
                    "voiceover_text": "line 2",
                    "visual": "主人B在另一个场景使用同一产品",
                    "character_ids": ["owner_b"],
                    "environment_id": "home_b",
                    "image_prompt": "owner b uses same product",
                },
            ],
        }
        result = shot_gen.validate_and_normalize_payload(payload, 15)
        ids = [item["character_ids"][0] for item in result["shots"]]
        self.assertEqual(ids, ["owner_a", "owner_b"])
        self.assertFalse(result["visual_continuity_policy"]["lock_main_character"])

    def test_source_no_longer_imports_boom_reference_helpers(self):
        source = Path(shot_gen.__file__).read_text(encoding="utf-8")
        self.assertNotIn("get_reference_scripts", source)
        self.assertNotIn("generate_strategy_summary", source)
        self.assertNotIn("002爆款", source)

    def test_extract_json_object_accepts_fenced_json(self):
        payload = {"visual_continuity_policy": {"lock_product": True}, "shots": []}
        self.assertEqual(shot_gen.extract_json_object("```json\n" + json.dumps(payload) + "\n```"), payload)

    def test_storyboard_style_policy_normalizes_known_styles(self):
        realistic = shot_gen.resolve_storyboard_style_policy("真实拍摄")
        mixed = shot_gen.resolve_storyboard_style_policy("混合（产品写实+角色动画）")
        animated = shot_gen.resolve_storyboard_style_policy("全动画")

        self.assertEqual(realistic["style"], "全写实")
        self.assertEqual(mixed["style"], "混合（产品写实+角色动画）")
        self.assertEqual(animated["style"], "全动画")
        self.assertIn("产品包装始终严格写实", animated["prompt_rules"])
        self.assertIn("泰国真实 UGC", realistic["prompt_rules"])

    def test_build_prompt_includes_style_policy_without_changing_script(self):
        prompt = shot_gen.build_prompt(
            {"视频时长": "28s", "分镜风格": "全动画", "关联产品": "Uootapet"},
            {"产品名称-th": "Uootapet", "产品规格": "1.34 ml"},
            "",
            "狗狗口播：สวัสดี",
        )

        self.assertIn("## 分镜风格策略", prompt)
        self.assertIn("标准化风格：全动画", prompt)
        self.assertIn("不得让风格改变剧情、口播、产品使用方式", prompt)
        self.assertIn("狗狗口播：สวัสดี", prompt)

    def test_build_prompt_includes_markdown_finished_script_contract(self):
        prompt = shot_gen.build_prompt(
            {"视频时长": "28s", "分镜风格": "全写实", "关联产品": "Uootapet"},
            {"产品名称-th": "Uootapet"},
            "",
            "| 时间 | 画面 | 泰语口播/字幕 | 中文理解 | 爆点来源 |\n| 0-3s | 狗狗抓痒 | 狗狗口播：`ไทย` | 中文 | 视频2 |",
        )

        self.assertIn("Markdown 表格成片脚本", prompt)
        self.assertIn("时间 / 画面 / 泰语口播/字幕 / 中文理解 / 爆点来源", prompt)
        self.assertIn("voiceover_text 只能放最终 TTS 要朗读的泰语口播", prompt)
        self.assertIn("screen_text", prompt)
        self.assertIn("source_beat", prompt)

    def test_normalize_shot_preserves_screen_text_and_video_notes(self):
        result = shot_gen.normalize_shot(
            {
                "duration_sec": 4,
                "voiceover_text": "สวัสดี",
                "screen_text": "Uootapet มี 3 สูตร",
                "screen_text_zh": "Uootapet 有 3 个规格",
                "source_beat": "视频 2：三规格 CTA",
                "video_prompt_notes": "tail wag, product boxes remain stable",
                "visual": "干净狗抬爪推荐三规格产品",
            },
            1,
        )

        self.assertEqual(result["screen_text"], "Uootapet มี 3 สูตร")
        self.assertEqual(result["screen_text_zh"], "Uootapet 有 3 个规格")
        self.assertEqual(result["source_beat"], "视频 2：三规格 CTA")
        self.assertEqual(result["video_prompt_notes"], "tail wag, product boxes remain stable")
        self.assertNotIn("Uootapet 有 3 个规格", result["voiceover_text"])

    def test_build_shot_record_fields_packs_screen_text_metadata(self):
        fields = shot_storyboard.build_shot_record_fields(
            {"源003记录ID": "rec003", "口播音色ID": "voice-a"},
            {
                "duration_sec": 4,
                "voiceover_text": "เลือกให้ถูก",
                "screen_text": "Uootapet มี 3 สูตร",
                "screen_text_zh": "Uootapet 有 3 个规格",
                "source_beat": "视频 2：三规格 CTA",
                "video_prompt_notes": "tail wag and raise paw",
                "visual": "干净狗抬爪推荐",
                "image_prompt": "clean dog with products",
            },
            source_record_id="rec-parent",
            idx=7,
            total_shots=7,
            product_name="Uootapet",
            source_video_id="",
            voice_id="voice-a",
        )

        self.assertEqual(fields["口播文本"], "เลือกให้ถูก")
        self.assertEqual(fields["口播音频状态"], "不触发")
        self.assertNotIn("分镜文案", fields)
        self.assertNotIn("分镜说明", fields)
        self.assertNotIn("口播音频时长秒", fields)
        self.assertIn("视频提示词", fields)
        self.assertIn("tail wag and raise paw", fields["视频提示词"])
        self.assertIn("不要生成字幕", fields["视频提示词"])
        self.assertIn("产品包装必须保持写实", fields["视频提示词"])
        self.assertIn("Veo must directly generate the final local-language spoken audio", fields["视频提示词"])
        self.assertNotIn("图生视频提示词｜", fields["视频提示词"])
        meta = json.loads(fields["文本"])
        self.assertEqual(meta["screen_text"], "Uootapet มี 3 สูตร")
        self.assertEqual(meta["screen_text_zh"], "Uootapet 有 3 个规格")
        self.assertEqual(meta["source_beat"], "视频 2：三规格 CTA")
        self.assertEqual(meta["video_prompt_notes"], "tail wag and raise paw")

    def test_veo_image_to_video_prompt_generates_final_audio_directly(self):
        prompt = shot_storyboard.build_image_to_video_prompt(
            {
                "duration_sec": 4,
                "voiceover_text": "เลือกให้ถูก",
                "speaker": "dog",
                "speaker_visible": True,
                "action": "dog raises paw",
                "camera": "slow push in",
                "emotion": "cute and confident",
            },
            idx=1,
            total_shots=3,
            product_name="Uootapet",
            voiceover_text="เลือกให้ถูก",
            voice_id="voice-a",
            video_model="veo3.1",
        )

        self.assertIn("Use the uploaded image as the first frame.", prompt)
        self.assertIn("Thai dialogue:", prompt)
        self.assertIn("Voice style:", prompt)
        self.assertIn("Voice identity:", prompt)
        self.assertIn("Global voice anchor:", prompt)
        self.assertIn("voice profile ID voice-a", prompt)
        self.assertIn("Veo must directly generate the final local-language spoken audio", prompt)
        self.assertNotIn("使用参考音频作为最终口播内容", prompt)

    def test_seeddance_image_to_video_prompt_uses_generated_voiceover_audio(self):
        prompt = shot_storyboard.build_image_to_video_prompt(
            {
                "duration_sec": 4,
                "voiceover_text": "เลือกให้ถูก",
                "speaker": "dog",
                "speaker_visible": True,
                "action": "dog raises paw",
            },
            idx=1,
            total_shots=3,
            product_name="Uootapet",
            voiceover_text="เลือกให้ถูก",
            voice_id="voice-a",
            video_model="seeddance2.0",
        )

        self.assertIn("Use the uploaded image as the first frame.", prompt)
        self.assertIn("Thai dialogue:", prompt)
        self.assertIn("使用参考音频作为最终口播内容", prompt)
        self.assertIn("reference voiceover audio", prompt)
        self.assertIn("Global voice anchor:", prompt)
        self.assertIn("产品包装必须保持写实", prompt)
        self.assertIn("no subtitles", prompt)

    def test_build_shot_record_fields_sets_zero_audio_duration_without_voiceover(self):
        fields = shot_storyboard.build_shot_record_fields(
            {"源003记录ID": "rec003"},
            {
                "duration_sec": 4,
                "voiceover_text": "",
                "visual": "无口播产品定帧",
                "image_prompt": "product still",
            },
            source_record_id="rec-parent",
            idx=1,
            total_shots=1,
            product_name="Uootapet",
            source_video_id="",
            voice_id="",
        )

        self.assertEqual(fields["口播音频状态"], "成功")
        self.assertEqual(fields["口播音频时长秒"], 0)

    def test_build_shot_record_fields_omits_id_duplicates_from_optional_descriptions(self):
        fields = shot_storyboard.build_shot_record_fields(
            {"源003记录ID": "rec003"},
            {
                "duration_sec": 4,
                "voiceover_text": "สวัสดี",
                "visual": "同一只狗看镜头",
                "image_prompt": "same dog looks at camera",
                "character_ids": ["dog_hero"],
                "pet_ids": ["dog_hero"],
                "environment_id": "thai_front_door",
            },
            source_record_id="rec-parent",
            idx=1,
            total_shots=1,
            product_name="Uootapet",
            source_video_id="",
            voice_id="voice-a",
        )

        self.assertEqual(fields["角色ID"], "dog_hero")
        self.assertEqual(fields["宠物ID"], "dog_hero")
        self.assertEqual(fields["环境ID"], "thai_front_door")
        self.assertNotIn("人物描述", fields)
        self.assertNotIn("场景描述", fields)

    def test_image_to_video_prompt_keeps_pet_speaker_visible_even_if_model_marks_invisible(self):
        prompt = shot_storyboard.build_image_to_video_prompt(
            {
                "duration_sec": 3,
                "voiceover_text": "คันมากเลยงับ",
                "visual": "镜头压低贴近地面，虫子往狗身边爬",
                "speaker": "dog",
                "speaker_visible": False,
                "action": "狗抬爪抓脖子",
            },
            idx=2,
            total_shots=7,
            product_name="Uootapet",
            voiceover_text="คันมากเลยงับ",
        )

        self.assertIn("Visible speaking subject: dog", prompt)
        self.assertIn("Veo must directly generate the final local-language spoken audio", prompt)
        self.assertIn("不要改成画外旁白", prompt)
        self.assertNotIn("画外口播", prompt)
        self.assertNotIn("图生视频提示词｜", prompt)

    def test_load_shots_payload_prefers_full_memory_payload_over_truncated_field(self):
        fields = {
            "分镜头结构JSON": '{"shots":[{"visual":"truncated',
        }
        payload = {
            "shots": [
                {
                    "duration_sec": 3,
                    "voiceover_text": "ไทย",
                    "visual": "完整内存 payload",
                    "image_prompt": "full payload image prompt",
                }
            ]
        }

        data, shots = shot_storyboard.load_shots_payload(fields, payload)

        self.assertIs(data, payload)
        self.assertEqual(shots[0]["visual"], "完整内存 payload")

    def test_single_shot_prompt_includes_normalized_style_policy(self):
        prompt = shot_storyboard._build_single_shot_prompt(
            "BASE {storyboard_style}",
            {
                "分镜序号": 1,
                "总分镜数": 3,
                "口播文本": "สวัสดี",
                "画面描述": "狗狗看镜头说话",
                "提示词": "dog speaking to camera",
            },
            "混合",
            visual_bible='{"storyboard_style": "混合"}',
        )

        self.assertIn("标准化风格：混合（产品写实+角色动画）", prompt)
        self.assertIn("产品包装始终严格写实", prompt)
        self.assertIn("主人不露完整脸、不 lip-sync", prompt)
        self.assertIn("BASE 混合（产品写实+角色动画）", prompt)

    def test_single_shot_prompt_falls_back_to_legacy_duplicate_fields(self):
        prompt = shot_storyboard._build_single_shot_prompt(
            "BASE",
            {
                "分镜序号": 1,
                "总分镜数": 1,
                "分镜文案": "legacy narration",
                "分镜说明": "legacy visual",
            },
            "全写实",
        )

        self.assertIn("Voiceover: legacy narration", prompt)
        self.assertIn("Visual Description: legacy visual", prompt)
        self.assertIn("本次重生成修改要求", prompt)
        self.assertIn("无", prompt)

    def test_single_shot_prompt_includes_revision_note_for_regeneration(self):
        prompt = shot_storyboard._build_single_shot_prompt(
            "BASE",
            {
                "分镜序号": 2,
                "总分镜数": 5,
                "画面描述": "主人拿着产品坐在浴室地垫旁",
                "分镜图修改要求": "改成平视近景，产品包装正面对镜头，人物表情更自然，背景仍然是浴室。",
            },
            "混合",
        )

        self.assertIn("本次重生成修改要求", prompt)
        self.assertIn("改成平视近景", prompt)
        self.assertIn("产品包装正面对镜头", prompt)
        self.assertIn("必须优先满足该要求", prompt)
        self.assertIn("不能破坏产品写实一致性", prompt)

    def test_single_shot_prompt_keeps_screen_text_as_post_production_only(self):
        prompt = shot_storyboard._build_single_shot_prompt(
            "BASE",
            {
                "分镜序号": 7,
                "总分镜数": 7,
                "口播文本": "เลือกให้ถูก",
                "画面描述": "干净狗坐在三规格产品旁边",
                "文本": json.dumps({
                    "screen_text": "Uootapet มี 3 สูตร",
                    "screen_text_zh": "Uootapet 有 3 个规格",
                    "source_beat": "视频 2：三规格 CTA",
                    "video_prompt_notes": "dog raises paw, tail wag",
                }, ensure_ascii=False),
            },
            "全写实",
        )

        self.assertIn("Screen Text For Post-production Only: Uootapet มี 3 สูตร", prompt)
        self.assertIn("Source Beat: 视频 2：三规格 CTA", prompt)
        self.assertIn("Video Prompt Notes: dog raises paw, tail wag", prompt)
        self.assertIn("不要把 Screen Text", prompt)

    def test_single_shot_prompt_does_not_reuse_previous_full_prompt_as_draft(self):
        prompt = shot_storyboard._build_single_shot_prompt(
            "BASE",
            {
                "分镜序号": 3,
                "总分镜数": 5,
                "画面描述": "主人拿出喷雾，狗狗在旁边",
                "提示词": "Reference image 1 = product reference.\nReference image 2 = selected pet model reference.\n\n## 当前任务不是生成九宫格\nold full prompt",
            },
            "全写实",
        )

        self.assertIn("Image Prompt Draft: ", prompt)
        self.assertNotIn("old full prompt", prompt)

    def test_build_shot_reference_prompt_note_marks_pet_as_hard_anchor(self):
        note = shot_storyboard.build_shot_reference_prompt_note([
            {"role": "product"},
            {"role": "pet:pet_hero"},
            {"role": "human:owner"},
        ])

        self.assertIn("Reference image 2 = selected pet model reference (pet_hero)", note)
        self.assertIn("hard identity anchors", note)


if __name__ == "__main__":
    unittest.main()
