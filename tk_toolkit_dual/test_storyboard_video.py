import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import tk_storyboard_video as storyboard_video
import tk_create_storyboard_video_table as create_table
import tk_bootstrap_storyboard_video_config as bootstrap_config
import tk_dispatcher as dispatcher


def parent_fields():
    return {
        "记录类型": "母任务",
        "任务名称": "story task",
        "脚本内容": "0-10s hook\n10-20s product demo",
        "关联产品记录": [{"record_ids": ["recProduct"], "text": "Pet odor spray"}],
        "选择模特": [{"record_ids": ["recModel"], "text": "Momo"}],
        "环境图": [{"file_token": "ft_environment"}],
    }


def multi_model_parent_fields(model_ids=None, environment_tokens=None):
    model_ids = model_ids or ["recHuman1", "recHuman2", "recPet1", "recPet2"]
    return {
        **parent_fields(),
        "选择模特": [{"record_ids": model_ids, "text": "multi models"}],
        "环境图": [{"file_token": token} for token in (environment_tokens or ["ft_environment"])],
    }


def fake_parent_lookup(token, table_id, record_id):
    if record_id == "recProduct":
        return {
            "产品名称-zh": "宠物除臭喷雾",
            "产品名称-th": "Pet odor spray TH",
            "目标用户": "Thai pet owners",
            "产品图片": [{"file_token": "ft_product"}],
        }
    if record_id == "recModel":
        return {
            "模特名称": "Momo",
            "模特照片": [{"file_token": "ft_character"}],
        }
    raise AssertionError((token, table_id, record_id))


def fake_multi_model_lookup(token, table_id, record_id):
    if record_id == "recProduct":
        return {
            "产品名称-zh": "宠物除臭喷雾",
            "目标用户": "Thai pet owners",
            "产品图片": [
                {"file_token": "ft_product_1"},
                {"file_token": "ft_product_2"},
                {"file_token": "ft_product_3"},
            ],
        }
    models = {
        "recHuman1": {"模特名称": "Thai man 1", "模特类型": "人类", "外观描述": "blue shirt", "模特照片": [{"file_token": "ft_human_1a"}, {"file_token": "ft_human_1b"}]},
        "recHuman2": {"模特名称": "Thai woman 1", "模特类型": "人类", "外观描述": "white dress", "模特照片": [{"file_token": "ft_human_2a"}, {"file_token": "ft_human_2b"}]},
        "recPet1": {"模特名称": "Orange cat", "模特类型": "宠物", "外观描述": "orange tabby", "模特照片": [{"file_token": "ft_pet_1a"}, {"file_token": "ft_pet_1b"}]},
        "recPet2": {"模特名称": "White dog", "模特类型": "宠物", "外观描述": "small white dog", "模特照片": [{"file_token": "ft_pet_2a"}, {"file_token": "ft_pet_2b"}]},
    }
    if record_id in models:
        return models[record_id]
    raise AssertionError((token, table_id, record_id))


def complete_storyboard_prompt(storyboard_no=1, *, include_hook=True) -> str:
    top_fields = "Storyboard 编号, Time Range, 产品名称, 目标人群"
    if include_hook:
        top_fields += ", 核心冲突场景, 黄金3秒/戏剧钩子"
    start = (storyboard_no - 1) * 10
    end = storyboard_no * 10
    return f"""
【强制垫图指令】：接下来的所有画面生成，必须100%严格参考我随附上传的【人物照片】、【宠物照片】、【产品照片】和【环境参考】。绝对禁止 AI 自行发散捏造人物长相、宠物外观、服装、产品外观和场景环境，产品绝不可变形脱相，场景绝不可随镜头更换！

第一区块（顶部表头，横向占满全宽）：短视频带货分镜制作。顶部表头字段：{top_fields}。
Time Range: {start}-{end}s.

第二区块（中部素材区）：根据脚本角色放置人物参考区、宠物参考区、产品参考区、固定环境参考区。每个参考区展示正面、面部/局部特写、服装或外观特征、产品正面和其它角度；固定环境参考区展示同一个主要场景、主要家具、背景锚点、问题发生位置和光线氛围。

第三区块（核心分镜区，横向占满全宽）：Storyboard {storyboard_no:02d}：微剧情分镜（{start}-{end}s）。下方根据脚本实际镜头数量划分镜头网格，不固定为5个镜头。
每个镜头网格内部从上到下严格包含：
顶部栏：镜头编号及名称。
画面区：带货分镜配图，严格按照脚本剧情顺序排布，场景需符合目标国家/地区【泰国】的真实生活环境与家居风格，所有镜头必须发生在同一个固定场景中，并保留固定环境参考区的背景锚点。
底部表格：时间轴、景别、运镜（强调快推和主观视角）、画面内容（强调动作交互，绝不可省略此项）、情绪（从抓狂到极度惊喜的巨大反转）、日常口语化对白。
""".strip()


class StoryboardVideoTests(unittest.TestCase):
    def test_prompt_instructions_keep_conflict_hook_only_on_storyboard_01(self):
        fields = dict(parent_fields(), **{"产品名称": "Pet odor spray", "目标人群": "Thai pet owners"})
        prompt = storyboard_video.build_storyboard_prompt_generation_request(fields)

        self.assertIn("Storyboard 01", prompt)
        self.assertIn("核心冲突场景", prompt)
        self.assertIn("黄金3秒/戏剧钩子", prompt)
        self.assertIn("Storyboard 02", prompt)
        self.assertIn("从 Storyboard 02 开始", prompt)
        self.assertIn("不得再出现“核心冲突场景”", prompt)
        self.assertNotIn("Core conflict scene:", prompt)
        self.assertNotIn("Golden 3-second / dramatic hook:", prompt)
        self.assertIn("英文", prompt)
        self.assertIn("泰文", prompt)
        self.assertIn("固定环境参考区", prompt)
        self.assertIn("环境参考", prompt)
        self.assertIn("所有镜头必须发生在同一个固定场景中", prompt)
        self.assertIn("参考图优先于脚本文字外观", prompt)
        self.assertIn("不得根据脚本自行改写人物服装", prompt)
        self.assertIn("不得根据脚本自行改写产品瓶型", prompt)

    def test_prompt_generation_request_uses_configured_system_prompt(self):
        fields = dict(parent_fields(), **{"产品名称": "Pet odor spray", "目标人群": "Thai pet owners"})
        prompt = storyboard_video.build_storyboard_prompt_generation_request(
            fields,
            system_prompt="CONFIGURED STORYBOARD SYSTEM PROMPT",
        )

        self.assertIn("CONFIGURED STORYBOARD SYSTEM PROMPT", prompt)
        self.assertNotIn("Return strict JSON only", prompt)
        self.assertNotIn("JSON schema", prompt)
        self.assertIn("自动化预检硬性要求", prompt)
        self.assertIn("画面内容", prompt)
        self.assertIn("日常口语化对白", prompt)
        self.assertIn("【完整脚本内容】", prompt)

    def test_text_generation_config_uses_dedicated_storyboard_split_record(self):
        with patch.dict(storyboard_video.CONFIG_RECORDS, {"storyboard_text_split": "rec_story_split"}, clear=True), \
             patch.object(storyboard_video, "get_model_config", return_value={
            "model": "gemini-3.1-pro-preview",
            "api_key": "sk-text",
            "api_base": "https://aihubmix.com/gemini",
            "prompt": "configured split prompt",
        }) as getter:
            cfg = storyboard_video.get_text_generation_config("token")

        getter.assert_called_once_with("token", "rec_story_split")
        self.assertEqual(cfg["model"], "gemini-3.1-pro-preview")
        self.assertEqual(cfg["api_key"], "sk-text")
        self.assertEqual(cfg["api_base"], "https://aihubmix.com/gemini")
        self.assertEqual(cfg["prompt"], "configured split prompt")
        self.assertEqual(cfg["prompt_record_id"], "rec_story_split")

    def test_text_generation_config_falls_back_when_split_prompt_empty(self):
        with patch.dict(storyboard_video.CONFIG_RECORDS, {"storyboard_text_split": "rec_story_split"}, clear=True), \
             patch.object(storyboard_video, "get_model_config", return_value={
            "model": "gemini-3.1-pro-preview",
            "api_key": "sk-text",
            "api_base": "https://aihubmix.com/gemini",
            "prompt": "",
        }):
            cfg = storyboard_video.get_text_generation_config("token")

        self.assertEqual(cfg["prompt"], storyboard_video.STORYBOARD_PROMPT_RULES)
        self.assertEqual(cfg["prompt_record_id"], "")

    def test_split_storyboards_unified_route_uses_prefixed_model_provider(self):
        fields = dict(parent_fields(), **{
            "使用统一AI路由": "是",
            "拆分AI模型": "Aitgenne / gpt-5.5",
        })
        config_records = [
            {"fields": {"环节": "统一AI路由启用状态", "模型名称": "指定记录启用"}},
            {"fields": {"AI供应商": "Aitgenne", "API 代理地址": "https://api.aitgenne.com", "API Key": "sk-aitgenne"}},
        ]

        with patch.object(storyboard_video, "get_feishu_token", return_value="token"), \
             patch.object(storyboard_video, "safe_get_record", return_value=fields), \
             patch.object(storyboard_video, "resolve_parent_reference_context", return_value={}), \
             patch.object(storyboard_video, "apply_parent_reference_snapshots", side_effect=lambda f, ctx: f), \
             patch.object(storyboard_video, "get_text_generation_config", return_value={
                 "provider": "AIHubMix",
                 "model": "gemini-3.1-pro-preview",
                 "api_key": "sk-aihubmix",
                 "api_base": "https://aihubmix.com/gemini",
                 "call_type": "Gemini 原生 SDK",
                 "prompt": "configured split prompt",
             }), \
             patch.object(storyboard_video, "safe_list_records", return_value=config_records):
            result = storyboard_video.split_storyboards("recParent", dry_run=True)

        route = result["unified_ai_route"]
        self.assertEqual(route["provider"], "Aitgenne")
        self.assertEqual(route["call_type"], "OpenAI兼容 chat/completions")
        self.assertEqual(route["endpoint"], "https://api.aitgenne.com/v1/chat/completions")

    def test_split_storyboards_real_unified_call_uses_prefixed_route(self):
        fields = dict(parent_fields(), **{
            "使用统一AI路由": "是",
            "拆分AI模型": "Aitgenne / gpt-5.5",
        })
        config_records = [
            {"fields": {"环节": "统一AI路由启用状态", "模型名称": "指定记录启用"}},
            {"fields": {"AI供应商": "Aitgenne", "API 代理地址": "https://api.aitgenne.com", "API Key": "sk-aitgenne"}},
        ]
        payload = {
            "storyboards": [
                {
                    "storyboard_no": 1,
                    "time_range": "0-10s",
                    "image_prompt": complete_storyboard_prompt(1),
                    "video_prompt": "Animate as one clean vertical video.",
                }
            ]
        }

        with patch.object(storyboard_video, "get_feishu_token", return_value="token"), \
             patch.object(storyboard_video, "safe_get_record", return_value=fields), \
             patch.object(storyboard_video, "resolve_parent_reference_context", return_value={}), \
             patch.object(storyboard_video, "apply_parent_reference_snapshots", side_effect=lambda f, ctx: f), \
             patch.object(storyboard_video, "get_text_generation_config", return_value={
                 "provider": "AIHubMix",
                 "model": "gemini-3.1-pro-preview",
                 "api_key": "sk-aihubmix",
                 "api_base": "https://aihubmix.com/gemini",
                 "call_type": "Gemini 原生 SDK",
                 "prompt": "configured split prompt",
             }), \
             patch.object(storyboard_video, "safe_list_records", return_value=config_records), \
             patch.object(storyboard_video.ai_routing, "call_text_model", return_value=Mock(text=json.dumps(payload))) as call_text, \
             patch.object(storyboard_video, "safe_update_record"), \
             patch.object(storyboard_video, "filter_existing_fields", side_effect=lambda token, table, f: f), \
             patch.object(storyboard_video, "cleanup_child_storyboards", return_value=0), \
             patch.object(storyboard_video, "create_records", return_value=1):
            result = storyboard_video.split_storyboards("recParent")

        route = call_text.call_args.args[0]
        self.assertEqual(result["status"], "success")
        self.assertEqual(route.provider, "Aitgenne")
        self.assertEqual(route.call_type, "OpenAI兼容 chat/completions")
        self.assertEqual(route.api_base, "")
        self.assertEqual(route.api_key, "sk-aitgenne")

    def test_storyboard_media_summary_uses_prefixed_video_provider(self):
        config_records = [
            {"fields": {"环节": "统一AI路由启用状态", "模型名称": "指定记录启用"}},
            {"fields": {"AI供应商": "Aitgenne", "API 代理地址": "https://api.aitgenne.com", "API Key": "sk-aitgenne"}},
        ]

        with patch.object(storyboard_video, "safe_list_records", return_value=config_records):
            summary = storyboard_video.maybe_unified_media_summary(
                "token",
                {"使用统一AI路由": "是", "视频AI模型": "Aitgenne / happyhorse-1.0-i2v"},
                {"provider": "OTU", "api_key": "sk-otu", "api_base": "https://otuapi.com", "model": "omni_flash-10s"},
                capability="视频",
                task_type="首帧图生视频",
                model="omni_flash-10s",
                slot_name="视频",
                prompt="video prompt",
                params={"size": "720x1280", "aspect_ratio": "9:16"},
                reference_count=1,
            )

        self.assertEqual(summary["provider"], "Aitgenne")
        self.assertEqual(summary["endpoint"], "https://api.aitgenne.com/v1/videos")
        self.assertEqual(summary["api_key"], "[REDACTED]")

    def test_normalize_storyboard_payload_requires_final_image_prompt_and_adds_numbers(self):
        payload = storyboard_video.normalize_storyboard_payload({
            "storyboards": [
                {
                    "storyboard_no": 1,
                    "time_range": "0-10s",
                    "image_prompt": complete_storyboard_prompt(1),
                    "video_prompt": "Animate the real scene from storyboard 01.",
                },
                {
                    "time_range": "10-20s",
                    "image_prompt": complete_storyboard_prompt(2, include_hook=False),
                },
            ]
        })

        self.assertEqual(payload["storyboards"][0]["storyboard_no"], 1)
        self.assertIn("中部素材区", payload["storyboards"][0]["image_prompt"])
        self.assertEqual(payload["storyboards"][1]["storyboard_no"], 2)
        self.assertEqual(payload["storyboards"][1]["video_prompt"], "")

    def test_normalize_storyboard_payload_validates_material_zone_and_storyboard_02_header_fields(self):
        with self.assertRaisesRegex(ValueError, "Storyboard 01.*素材区"):
            storyboard_video.normalize_storyboard_payload({
                "storyboards": [{
                    "storyboard_no": 1,
                    "time_range": "0-10s",
                    "image_prompt": complete_storyboard_prompt(1)
                    .replace(
                        "第二区块（中部素材区）：根据脚本角色放置人物参考区、宠物参考区、产品参考区、固定环境参考区。每个参考区展示正面、面部/局部特写、服装或外观特征、产品正面和其它角度；固定环境参考区展示同一个主要场景、主要家具、背景锚点、问题发生位置和光线氛围。",
                        "第二区块：根据脚本角色放置素材。"
                    )
                    .replace("人物参考区", "人物素材")
                    .replace("宠物参考区", "宠物素材")
                    .replace("产品参考区", "产品素材")
                    .replace("参考区", "素材"),
                }]
            })

        with self.assertRaisesRegex(ValueError, "Storyboard 02.*核心冲突场景"):
            storyboard_video.normalize_storyboard_payload({
                "storyboards": [
                    {
                        "storyboard_no": 1,
                        "time_range": "0-10s",
                        "image_prompt": complete_storyboard_prompt(1),
                    },
                    {
                        "storyboard_no": 2,
                        "time_range": "10-20s",
                        "image_prompt": complete_storyboard_prompt(2, include_hook=False) + "\n核心冲突场景: should not appear.",
                    },
                ]
            })

    def test_normalize_storyboard_payload_accepts_english_final_prompt_markers(self):
        payload = storyboard_video.normalize_storyboard_payload({
            "storyboards": [
                {
                    "storyboard_no": 1,
                    "time_range": "0-10s",
                    "image_prompt": (
                        "【强制垫图指令】：strictly use uploaded people, pet, product photos, and environment reference. "
                        "Complete 16:9 storyboard production board. Top header table includes "
                        "Core conflict scene: pet odor disaster and Golden 3-second dramatic hook: "
                        "owner panic. Middle material/reference section includes one human character "
                        "reference area, one pet reference area, one product reference area, and one fixed environment reference area. "
                        "Core storyboard section contains micro-drama storyboard grid cells. Each shot grid "
                        "includes a top bar with shot number and name, an image area with commerce storyboard "
                        "illustration in a realistic Thailand home with the same fixed scene and background anchors, and a bottom table with Timeline, Shot size, "
                        "Camera movement, Visual content, Emotion, and colloquial dialogue."
                    ),
                },
                {
                    "storyboard_no": 2,
                    "time_range": "10-20s",
                    "image_prompt": (
                        "【强制垫图指令】：strictly use uploaded people, pet, product photos, and environment reference. "
                        "Complete 16:9 storyboard production board. Top header table includes only "
                        "Storyboard number, Time Range, Product name, and Target audience. "
                        "Middle material/reference section includes character reference area and "
                        "product reference area plus fixed environment reference area. Core storyboard section contains micro-drama storyboard "
                        "grid cells. Each shot grid includes a top bar with shot number and name, an image "
                        "area with commerce storyboard illustration in a realistic Thailand home with the same fixed scene and background anchors, and a "
                        "bottom table with Timeline, Shot size, Camera movement, Visual content, Emotion, "
                        "and colloquial dialogue."
                    ),
                },
            ]
        })

        self.assertEqual(payload["storyboards"][0]["storyboard_no"], 1)
        self.assertIn("Core conflict scene", payload["storyboards"][0]["image_prompt"])

    def test_normalize_storyboard_payload_rejects_storyboard_02_english_header_fields(self):
        with self.assertRaisesRegex(ValueError, "Storyboard 02.*Core conflict scene"):
            storyboard_video.normalize_storyboard_payload({
                "storyboards": [
                    {
                        "storyboard_no": 1,
                        "time_range": "0-10s",
                        "image_prompt": complete_storyboard_prompt(1),
                    },
                    {
                        "storyboard_no": 2,
                        "time_range": "10-20s",
                        "image_prompt": complete_storyboard_prompt(2, include_hook=False) + "\nTop header table includes Core conflict scene: should not appear.",
                    },
                ]
            })

    def test_normalize_storyboard_payload_parses_markdown_code_block_prompts(self):
        raw = f"""```text
Storyboard 01 Prompt:

{complete_storyboard_prompt(1)}

Storyboard 02 Prompt:

{complete_storyboard_prompt(2, include_hook=False)}
```"""

        payload = storyboard_video.normalize_storyboard_payload(raw)

        self.assertEqual([item["storyboard_no"] for item in payload["storyboards"]], [1, 2])
        self.assertEqual(payload["storyboards"][0]["time_range"], "0-10s")
        self.assertEqual(payload["storyboards"][1]["time_range"], "10-20s")
        self.assertEqual(payload["storyboards"][0]["image_prompt"], complete_storyboard_prompt(1))
        self.assertEqual(payload["storyboards"][1]["video_prompt"], "")

    def test_normalize_storyboard_payload_requires_complete_core_grid_fields(self):
        with self.assertRaisesRegex(ValueError, "强制垫图指令"):
            storyboard_video.normalize_storyboard_payload({
                "storyboards": [{
                    "storyboard_no": 1,
                    "time_range": "0-10s",
                    "image_prompt": complete_storyboard_prompt(1).replace("【强制垫图指令】", "【垫图】"),
                }]
            })

        with self.assertRaisesRegex(ValueError, "核心分镜区"):
            storyboard_video.normalize_storyboard_payload({
                "storyboards": [{
                    "storyboard_no": 1,
                    "time_range": "0-10s",
                    "image_prompt": complete_storyboard_prompt(1)
                    .replace("第三区块（核心分镜区，横向占满全宽）", "第三区块")
                    .replace("微剧情分镜", "剧情分解")
                    .replace("镜头网格", "镜头列表"),
                }]
            })

        with self.assertRaisesRegex(ValueError, "画面内容"):
            storyboard_video.normalize_storyboard_payload({
                "storyboards": [{
                    "storyboard_no": 1,
                    "time_range": "0-10s",
                    "image_prompt": complete_storyboard_prompt(1).replace("画面内容", "动作说明"),
                }]
            })

    def test_child_records_are_same_table_segments_and_trigger_image_only_first(self):
        payload = storyboard_video.normalize_storyboard_payload({
            "storyboards": [
                {
                    "storyboard_no": 1,
                    "time_range": "0-10s",
                    "image_prompt": complete_storyboard_prompt(1),
                    "video_prompt": "Video one",
                },
                {
                    "storyboard_no": 2,
                    "time_range": "10-20s",
                    "image_prompt": complete_storyboard_prompt(2, include_hook=False),
                    "video_prompt": "Video two",
                },
            ]
        })

        records = storyboard_video.build_child_storyboard_records(
            dict(parent_fields(), **{"产品名称": "Pet odor spray", "目标人群": "Thai pet owners"}),
            payload,
            parent_record_id="recParent",
            batch_id="SB-1",
        )

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["fields"]["记录类型"], "Storyboard分段")
        self.assertEqual(records[0]["fields"]["父任务记录ID"], "recParent")
        self.assertEqual(records[0]["fields"]["Storyboard编号"], 1)
        self.assertEqual(records[0]["fields"]["Time Range"], "0-10s")
        self.assertEqual(records[0]["fields"]["故事板图片生成状态"], "待生成")
        self.assertEqual(records[0]["fields"]["视频生成状态"], "不触发")
        self.assertEqual(records[0]["fields"]["关联产品记录"], ["recProduct"])
        self.assertEqual(records[0]["fields"]["选择模特"], ["recModel"])
        self.assertEqual(records[0]["fields"]["故事板图片提示词"], complete_storyboard_prompt(1))
        self.assertEqual(records[0]["fields"]["故事板图片模型"], "gpt-image-2")
        self.assertEqual(records[0]["fields"]["故事板图片画面尺寸"], "1280x720")
        self.assertEqual(records[0]["fields"]["故事板图片画面比例"], "16:9")
        self.assertEqual(records[0]["fields"]["Omni模型"], "omni_flash-10s")
        self.assertEqual(records[0]["fields"]["Omni画面尺寸"], "720x1280")
        self.assertEqual(records[0]["fields"]["Omni画面比例"], "9:16")
        self.assertEqual(records[1]["fields"]["故事板图片提示词"], complete_storyboard_prompt(2, include_hook=False))
        self.assertEqual(records[1]["fields"]["故事板图片模型"], "gpt-image-2")
        self.assertEqual(records[1]["fields"]["故事板图片画面尺寸"], "1280x720")
        self.assertEqual(records[1]["fields"]["故事板图片画面比例"], "16:9")
        self.assertEqual(records[1]["fields"]["Omni模型"], "omni_flash-10s")
        self.assertEqual(records[1]["fields"]["Omni画面尺寸"], "720x1280")
        self.assertEqual(records[1]["fields"]["Omni画面比例"], "9:16")

    def test_split_storyboards_requires_environment_image_before_calling_model(self):
        fields = dict(parent_fields())
        fields["环境图"] = []

        with patch.object(storyboard_video, "get_feishu_token", return_value="token"), \
             patch.object(storyboard_video, "safe_get_record", return_value=fields), \
             patch.object(storyboard_video, "get_text_generation_config") as get_config:
            with self.assertRaisesRegex(ValueError, "环境图必须上传"):
                storyboard_video.split_storyboards("recParent")

        get_config.assert_not_called()

    def test_collect_reference_images_uses_storyboard_then_product_character_environment_and_caps_at_7(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for name in ["story.png", "product.png", "character.png", "environment.png"]:
                (tmp_path / name).write_bytes(b"x" * 2000)

            child = {
                "故事板图": [{"file_token": "ft_story"}],
                "父任务记录ID": "recParent",
            }
            parent = {
                "关联产品记录": [{"record_ids": ["recProduct"]}],
                "选择模特": [{"record_ids": ["recModel"]}],
                "环境图": [{"file_token": "ft_environment"}],
            }
            download = Mock(side_effect=[
                tmp_path / "story.png",
                tmp_path / "product.png",
                tmp_path / "character.png",
                tmp_path / "environment.png",
            ])

            refs = storyboard_video.collect_omni_reference_images(
                "token",
                child,
                parent,
                tmp_path,
                download_fn=download,
                get_record_fn=fake_parent_lookup,
            )

        self.assertEqual([ref["role"] for ref in refs], ["storyboard", "product:1", "character:1", "environment:1"])
        self.assertEqual([call.args[1] for call in download.call_args_list], ["ft_story", "ft_product", "ft_character", "ft_environment"])

    def test_resolve_parent_reference_context_allows_multiple_models_and_uses_first_photo_each(self):
        context = storyboard_video.resolve_parent_reference_context(
            "token",
            multi_model_parent_fields(),
            get_record_fn=fake_multi_model_lookup,
            product_table_id="tblProduct",
            model_table_id="tblModel",
        )

        self.assertEqual(context["model_record_ids"], ["recHuman1", "recHuman2", "recPet1", "recPet2"])
        self.assertEqual(context["character_tokens"], ["ft_human_1a", "ft_human_2a", "ft_pet_1a", "ft_pet_2a"])
        self.assertEqual([character["name"] for character in context["characters"]], ["Thai man 1", "Thai woman 1", "Orange cat", "White dog"])
        self.assertEqual([character["type"] for character in context["characters"]], ["人类", "人类", "宠物", "宠物"])
        self.assertEqual(context["environment_tokens"], ["ft_environment"])

        prompt = storyboard_video.build_storyboard_prompt_generation_request(
            storyboard_video.apply_parent_reference_snapshots(dict(multi_model_parent_fields()), context)
        )
        self.assertIn("【已选择人物/宠物参考】", prompt)
        self.assertIn("Thai man 1", prompt)
        self.assertIn("Orange cat", prompt)
        self.assertIn("Keep every selected human/pet character consistent", prompt)

    def test_resolve_parent_reference_context_supports_common_human_pet_combinations(self):
        cases = [
            ["recHuman1"],
            ["recHuman1", "recPet1"],
            ["recHuman1", "recHuman2", "recPet1"],
            ["recHuman1", "recHuman2", "recPet1", "recPet2"],
        ]

        for model_ids in cases:
            with self.subTest(model_ids=model_ids):
                context = storyboard_video.resolve_parent_reference_context(
                    "token",
                    multi_model_parent_fields(model_ids=model_ids),
                    get_record_fn=fake_multi_model_lookup,
                    product_table_id="tblProduct",
                    model_table_id="tblModel",
                )

                self.assertEqual(context["model_record_ids"], model_ids)
                self.assertEqual(len(context["character_tokens"]), len(model_ids))

    def test_parent_reference_priority_keeps_required_product_and_all_model_refs_before_extras(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for name in [
                "product_1.png", "product_2.png", "product_3.png",
                "human_1.png", "human_2.png", "pet_1.png", "pet_2.png",
                "environment.png",
            ]:
                (tmp_path / name).write_bytes(b"x" * 2000)
            download = Mock(side_effect=[
                tmp_path / "product_1.png",
                tmp_path / "human_1.png",
                tmp_path / "human_2.png",
                tmp_path / "pet_1.png",
                tmp_path / "pet_2.png",
                tmp_path / "environment.png",
                tmp_path / "product_2.png",
            ])

            refs = storyboard_video.collect_parent_reference_images(
                "token",
                multi_model_parent_fields(),
                tmp_path,
                download_fn=download,
                get_record_fn=fake_multi_model_lookup,
            )

        self.assertEqual(
            [ref["role"] for ref in refs],
            ["product:1", "character:1", "character:2", "character:3", "character:4", "environment:1", "product:2"],
        )
        self.assertEqual(
            [call.args[1] for call in download.call_args_list],
            ["ft_product_1", "ft_human_1a", "ft_human_2a", "ft_pet_1a", "ft_pet_2a", "ft_environment", "ft_product_2"],
        )

    def test_omni_reference_images_reserve_one_slot_for_storyboard_and_cap_parent_refs_at_6(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for name in ["story.png", "product_1.png", "human_1.png", "human_2.png", "pet_1.png", "pet_2.png", "product_2.png"]:
                (tmp_path / name).write_bytes(b"x" * 2000)
            download = Mock(side_effect=[
                tmp_path / "story.png",
                tmp_path / "product_1.png",
                tmp_path / "human_1.png",
                tmp_path / "human_2.png",
                tmp_path / "pet_1.png",
                tmp_path / "pet_2.png",
                tmp_path / "product_2.png",
            ])

            refs = storyboard_video.collect_omni_reference_images(
                "token",
                {"故事板图": [{"file_token": "ft_story"}]},
                multi_model_parent_fields(),
                tmp_path,
                download_fn=download,
                get_record_fn=fake_multi_model_lookup,
            )

        self.assertEqual(
            [ref["role"] for ref in refs],
            ["storyboard", "product:1", "character:1", "character:2", "character:3", "character:4", "environment:1"],
        )
        self.assertEqual(len(refs), 7)

    def test_parent_reference_images_fail_when_required_product_and_models_exceed_limit(self):
        with self.assertRaisesRegex(ValueError, "参考图数量超过上限"):
            storyboard_video.collect_parent_reference_images(
                "token",
                multi_model_parent_fields(model_ids=["recHuman1", "recHuman2", "recPet1", "recPet2", "recExtra1", "recExtra2", "recExtra3"]),
                Path("/tmp"),
                download_fn=Mock(),
                get_record_fn=lambda token, table_id, record_id: (
                    {"产品图片": [{"file_token": "ft_product_1"}]}
                    if record_id == "recProduct"
                    else {"模特名称": record_id, "模特照片": [{"file_token": f"ft_{record_id}"}]}
                ),
            )

    def test_parent_reference_images_require_environment_image(self):
        fields = dict(parent_fields())
        fields["环境图"] = []

        with self.assertRaisesRegex(ValueError, "环境图必须上传"):
            storyboard_video.collect_parent_reference_images(
                "token",
                fields,
                Path("/tmp"),
                download_fn=Mock(),
                get_record_fn=fake_parent_lookup,
            )

    def test_render_storyboard_image_requires_parent_environment_before_otu_submit(self):
        child_fields = {
            "父任务记录ID": "recParent",
            "故事板图片提示词": complete_storyboard_prompt(1),
        }
        parent = dict(parent_fields())
        parent["环境图"] = []

        def fake_safe_get_record(token, table_id, record_id):
            if record_id == "recChild":
                return child_fields
            if record_id == "recParent":
                return parent
            raise AssertionError(record_id)

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(storyboard_video, "get_feishu_token", return_value="token"), \
                 patch.object(storyboard_video, "safe_get_record", side_effect=fake_safe_get_record), \
                 patch.object(storyboard_video, "ensure_work_dir", return_value=Path(tmp)), \
                 patch.object(storyboard_video, "submit_otu_image_task") as submitter:
                with self.assertRaisesRegex(ValueError, "环境图必须上传"):
                    storyboard_video.render_storyboard_image("recChild")

        submitter.assert_not_called()

    def test_build_image_reference_note_marks_environment_as_required_anchor(self):
        note = storyboard_video.build_image_reference_note([
            {"role": "product:1", "name": "Pet spray"},
            {"role": "character:1", "name": "Thai model"},
            {"role": "environment:1", "name": "Living room"},
        ])

        self.assertIn("environment reference", note)
        self.assertIn("fixed location", note)
        self.assertIn("background anchors", note)
        self.assertIn("Ignore any conflicting text", note)
        self.assertIn("Pet spray", note)
        self.assertIn("Thai model", note)

    def test_reference_contact_sheet_contains_all_references_as_primary_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            refs = []
            for idx, role in enumerate(["product:1", "character:1", "character:2", "environment:1"], start=1):
                path = tmp_path / f"ref_{idx}.png"
                path.write_bytes(b"not-real-image")
                refs.append({"role": role, "path": str(path)})
            out_path = tmp_path / "contact.png"

            with patch.object(storyboard_video, "_render_reference_contact_sheet") as renderer:
                result = storyboard_video.build_reference_contact_sheet(refs, out_path)

        self.assertEqual(result, str(out_path))
        renderer.assert_called_once_with(refs, out_path)

    def test_render_storyboard_image_uses_record_parameters(self):
        updates = []
        child_fields = {
            "父任务记录ID": "recParent",
            "故事板图片提示词": complete_storyboard_prompt(1),
            "故事板图片模型": "gpt-image-2-2K",
            "故事板图片画面尺寸": "1280x720",
            "故事板图片画面比例": "16:9",
        }

        def fake_safe_get_record(token, table_id, record_id):
            if record_id == "recChild":
                return child_fields
            if record_id == "recParent":
                return parent_fields()
            raise AssertionError(record_id)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            product = tmp_path / "product.png"
            character = tmp_path / "character.png"
            environment = tmp_path / "environment.png"
            for path in (product, character, environment):
                path.write_bytes(b"image")

            with patch.object(storyboard_video, "get_feishu_token", return_value="token"), \
                 patch.object(storyboard_video, "TABLE_STORYBOARD_VIDEO", "tbl_storyboard"), \
                 patch.object(storyboard_video, "safe_get_record", side_effect=fake_safe_get_record), \
                 patch.object(storyboard_video, "ensure_work_dir", return_value=tmp_path), \
                 patch.object(storyboard_video, "collect_parent_reference_images", return_value=[
                     {"role": "product:1", "path": str(product)},
                     {"role": "character:1", "path": str(character)},
                     {"role": "environment:1", "path": str(environment)},
                 ]), \
                 patch.object(storyboard_video, "build_reference_urls", return_value=["https://ref/product.png", "https://ref/character.png", "https://ref/environment.png"]), \
                 patch.object(storyboard_video, "get_stage_config", return_value=("cfg_image", {"api_key": "sk", "api_base": "https://otuapi.com", "model": "wrong", "size": "wrong"})), \
                 patch.object(storyboard_video, "safe_update_record", side_effect=lambda token, table, record_id, fields: updates.append(fields)), \
                 patch.object(storyboard_video, "filter_existing_fields", side_effect=lambda token, table, fields: fields), \
                 patch.object(storyboard_video, "build_reference_contact_sheet", return_value=str(tmp_path / "contact.png")) as contact_sheet, \
                 patch.object(storyboard_video, "submit_otu_image_task", return_value=("task_1", {"id": "task_1"})) as submitter, \
                 patch.object(storyboard_video, "poll_otu_image_task", return_value={"status": "completed", "result_url": "https://x.test/storyboard.png"}), \
                 patch.object(storyboard_video, "download_otu_image_result"), \
                 patch.object(storyboard_video, "upload_image_to_feishu", return_value="ft_story"), \
                 patch.object(storyboard_video, "ensure_record_current_generation"):
                result = storyboard_video.render_storyboard_image("recChild")

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["model"], "gpt-image-2-2K")
        self.assertEqual(result["size"], "1280x720")
        self.assertEqual(result["aspect_ratio"], "16:9")
        submitter.assert_called_once()
        self.assertEqual(submitter.call_args.args[0]["model"], "gpt-image-2-2K")
        self.assertEqual(submitter.call_args.kwargs["size"], "1280x720")
        self.assertEqual(submitter.call_args.kwargs["image_path"], str(tmp_path / "contact.png"))
        self.assertEqual(submitter.call_args.kwargs["metadata"]["aspectRatio"], "16:9")
        self.assertIn("environment:1", submitter.call_args.kwargs["metadata"]["reference_roles"])
        contact_sheet.assert_called_once()
        submitted_prompt = submitter.call_args.args[1]
        self.assertIn("reference images override the storyboard text", submitted_prompt)
        self.assertIn("Ignore any conflicting text", submitted_prompt)

    def test_render_storyboard_image_falls_back_to_specific_defaults_for_old_records(self):
        child_fields = {
            "父任务记录ID": "recParent",
            "故事板图片提示词": complete_storyboard_prompt(1),
            "故事板图片模型": "",
            "故事板图片画面尺寸": "",
            "故事板图片画面比例": "",
        }

        def fake_safe_get_record(token, table_id, record_id):
            if record_id == "recChild":
                return child_fields
            if record_id == "recParent":
                return parent_fields()
            raise AssertionError(record_id)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ref = tmp_path / "ref.png"
            ref.write_bytes(b"image")
            with patch.object(storyboard_video, "get_feishu_token", return_value="token"), \
                 patch.object(storyboard_video, "TABLE_STORYBOARD_VIDEO", "tbl_storyboard"), \
                 patch.object(storyboard_video, "safe_get_record", side_effect=fake_safe_get_record), \
                 patch.object(storyboard_video, "ensure_work_dir", return_value=tmp_path), \
                 patch.object(storyboard_video, "collect_parent_reference_images", return_value=[{"role": "environment:1", "path": str(ref)}]), \
                 patch.object(storyboard_video, "build_reference_urls", return_value=["https://ref/environment.png"]), \
                 patch.object(storyboard_video, "get_stage_config", return_value=("cfg_image", {"api_key": "sk", "api_base": "https://otuapi.com", "model": "wrong", "size": "wrong"})), \
                 patch.object(storyboard_video, "safe_update_record"), \
                 patch.object(storyboard_video, "filter_existing_fields", side_effect=lambda token, table, fields: fields), \
                 patch.object(storyboard_video, "build_reference_contact_sheet", return_value=str(tmp_path / "contact.png")), \
                 patch.object(storyboard_video, "submit_otu_image_task", return_value=("task_1", {"id": "task_1"})) as submitter, \
                 patch.object(storyboard_video, "poll_otu_image_task", return_value={"status": "completed", "result_url": "https://x.test/storyboard.png"}), \
                 patch.object(storyboard_video, "download_otu_image_result"), \
                 patch.object(storyboard_video, "upload_image_to_feishu", return_value="ft_story"), \
                 patch.object(storyboard_video, "ensure_record_current_generation"):
                storyboard_video.render_storyboard_image("recChild")

        self.assertEqual(submitter.call_args.args[0]["model"], "gpt-image-2")
        self.assertEqual(submitter.call_args.kwargs["size"], "1280x720")
        self.assertEqual(submitter.call_args.kwargs["metadata"]["aspectRatio"], "16:9")

    def test_build_omni_video_prompt_rejects_rendering_storyboard_board(self):
        prompt = storyboard_video.build_omni_video_prompt(
            {"故事板图片提示词": "board prompt", "视频提示词": ""},
            dict(parent_fields(), **{"产品名称": "Pet odor spray", "目标人群": "Thai pet owners"}),
        )

        self.assertIn("智能识别并彻底抹除原图中的所有网格边框", prompt)
        self.assertIn("最终只输出纯净、无边框、无文字的真实视频画面", prompt)
        self.assertIn("保持人物面孔、服装和产品外观 100% 一致", prompt)
        self.assertNotIn("Product: Pet odor spray", prompt)
        self.assertNotIn("Storyboard image prompt / visual understanding:", prompt)
        self.assertNotIn("Additional video direction:", prompt)
        self.assertNotIn("【参考图顺序】", prompt)

    def test_build_omni_video_prompt_uses_markdown_configured_prompt(self):
        prompt = storyboard_video.build_omni_video_prompt(
            {"故事板图片提示词": "board prompt", "视频提示词": "extra video direction"},
            dict(parent_fields(), **{"产品名称": "Pet odor spray", "目标人群": "Thai pet owners"}),
            system_prompt="""```markdown
Omni Video Prompt:

根据上传图片的核心人物形象、服装、场景及核心产品细节。
极度重要（排他指令）：去除所有 UI 元素。
```""",
        )

        self.assertIn("根据上传图片的核心人物形象", prompt)
        self.assertIn("去除所有 UI 元素", prompt)
        self.assertNotIn("```", prompt)
        self.assertNotIn("Omni Video Prompt:", prompt)
        self.assertNotIn("extra video direction", prompt)
        self.assertNotIn("board prompt", prompt)

    def test_submit_omni_video_task_uses_multipart_with_size_and_aspect_ratio_without_seconds(self):
        with tempfile.NamedTemporaryFile(suffix=".png") as story, tempfile.NamedTemporaryFile(suffix=".png") as product:
            story.write(b"story")
            story.flush()
            product.write(b"product")
            product.flush()
            response = Mock()
            response.status_code = 200
            response.json.return_value = {"id": "task_omni", "status": "queued"}
            response.text = '{"id":"task_omni"}'

            with patch("tk_storyboard_video.requests.post", return_value=response) as post:
                task_id, body = storyboard_video.submit_omni_video_task(
                    {"api_base": "https://otuapi.com", "api_key": "sk-test", "model": "omni_flash-10s"},
                    "prompt text",
                    [{"role": "storyboard", "path": story.name}, {"role": "product:1", "path": product.name}],
                    size="720x1280",
                    aspect_ratio="9:16",
                )

        self.assertEqual(task_id, "task_omni")
        self.assertEqual(body["status"], "queued")
        args, kwargs = post.call_args
        self.assertEqual(args[0], "https://otuapi.com/v1/videos")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer sk-test")
        self.assertEqual(kwargs["data"], {
            "model": "omni_flash-10s",
            "prompt": "prompt text",
            "size": "720x1280",
            "aspect_ratio": "9:16",
        })
        form_fields = kwargs["files"]
        self.assertNotIn("seconds", kwargs["data"])
        self.assertEqual([item[0] for item in form_fields], ["input_reference[]", "input_reference[]"])

    def test_render_omni_video_uses_record_parameters_and_writes_prompt(self):
        updates = []
        child_fields = {
            "父任务记录ID": "recParent",
            "故事板图": [{"file_token": "ft_story"}],
            "Omni模型": "omni_flash-10s",
            "Omni画面尺寸": "1280x720",
            "Omni画面比例": "16:9",
        }

        def fake_safe_get_record(token, table_id, record_id):
            if record_id == "recChild":
                return child_fields
            if record_id == "recParent":
                return parent_fields()
            raise AssertionError(record_id)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            story = tmp_path / "story.png"
            story.write_bytes(b"story")
            with patch.object(storyboard_video, "get_feishu_token", return_value="token"), \
                 patch.object(storyboard_video, "TABLE_STORYBOARD_VIDEO", "tbl_storyboard"), \
                 patch.object(storyboard_video, "safe_get_record", side_effect=fake_safe_get_record), \
                 patch.object(storyboard_video, "parent_fields_with_reference_snapshots", side_effect=lambda token, fields: fields), \
                 patch.object(storyboard_video, "ensure_work_dir", return_value=tmp_path), \
                 patch.object(storyboard_video, "collect_omni_reference_images", return_value=[{"role": "storyboard", "path": str(story)}]), \
                 patch.object(storyboard_video, "get_stage_config", return_value=("cfg_video", {"api_key": "sk", "api_base": "https://otuapi.com", "prompt": "Omni Video Prompt:\nCONFIG PROMPT"})), \
                 patch.object(storyboard_video, "get_table_field_types", return_value={"分镜视频URL": 0}), \
                 patch.object(storyboard_video, "safe_update_record", side_effect=lambda token, table, record_id, fields: updates.append(fields)), \
                 patch.object(storyboard_video, "filter_existing_fields", side_effect=lambda token, table, fields: fields), \
                 patch.object(storyboard_video, "submit_omni_video_task", return_value=("task_1", {"id": "task_1"})) as submitter, \
                 patch.object(storyboard_video, "poll_omni_video_task", return_value={"status": "completed", "video_url": "https://x.test/video.mp4"}), \
                 patch.object(storyboard_video, "download_video"), \
                 patch.object(storyboard_video, "upload_video_to_feishu", return_value="ft_video"), \
                 patch.object(storyboard_video, "ensure_record_current_generation"):
                result = storyboard_video.render_omni_video("recChild")

        self.assertEqual(result["status"], "success")
        submitter.assert_called_once()
        self.assertEqual(submitter.call_args.args[0]["model"], "omni_flash-10s")
        self.assertEqual(submitter.call_args.kwargs["size"], "1280x720")
        self.assertEqual(submitter.call_args.kwargs["aspect_ratio"], "16:9")
        prompt_updates = [item["视频提示词"] for item in updates if "视频提示词" in item]
        self.assertEqual(prompt_updates, ["CONFIG PROMPT"])

    def test_render_omni_video_falls_back_to_specific_defaults_for_old_records(self):
        child_fields = {
            "父任务记录ID": "recParent",
            "故事板图": [{"file_token": "ft_story"}],
            "Omni模型": "",
            "Omni画面尺寸": "",
            "Omni画面比例": "",
        }

        def fake_safe_get_record(token, table_id, record_id):
            if record_id == "recChild":
                return child_fields
            if record_id == "recParent":
                return parent_fields()
            raise AssertionError(record_id)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            story = tmp_path / "story.png"
            story.write_bytes(b"story")
            with patch.object(storyboard_video, "get_feishu_token", return_value="token"), \
                 patch.object(storyboard_video, "TABLE_STORYBOARD_VIDEO", "tbl_storyboard"), \
                 patch.object(storyboard_video, "safe_get_record", side_effect=fake_safe_get_record), \
                 patch.object(storyboard_video, "parent_fields_with_reference_snapshots", side_effect=lambda token, fields: fields), \
                 patch.object(storyboard_video, "ensure_work_dir", return_value=tmp_path), \
                 patch.object(storyboard_video, "collect_omni_reference_images", return_value=[{"role": "storyboard", "path": str(story)}]), \
                 patch.object(storyboard_video, "get_stage_config", return_value=("cfg_video", {"api_key": "sk", "api_base": "https://otuapi.com", "model": "wrong", "size": "wrong", "prompt": "Omni Video Prompt:\nCONFIG PROMPT"})), \
                 patch.object(storyboard_video, "get_table_field_types", return_value={"分镜视频URL": 0}), \
                 patch.object(storyboard_video, "safe_update_record"), \
                 patch.object(storyboard_video, "filter_existing_fields", side_effect=lambda token, table, fields: fields), \
                 patch.object(storyboard_video, "submit_omni_video_task", return_value=("task_1", {"id": "task_1"})) as submitter, \
                 patch.object(storyboard_video, "poll_omni_video_task", return_value={"status": "completed", "video_url": "https://x.test/video.mp4"}), \
                 patch.object(storyboard_video, "download_video"), \
                 patch.object(storyboard_video, "upload_video_to_feishu", return_value="ft_video"), \
                 patch.object(storyboard_video, "ensure_record_current_generation"):
                storyboard_video.render_omni_video("recChild")

        self.assertEqual(submitter.call_args.args[0]["model"], "omni_flash-10s")
        self.assertEqual(submitter.call_args.kwargs["size"], "720x1280")
        self.assertEqual(submitter.call_args.kwargs["aspect_ratio"], "9:16")

    def test_table_definition_has_single_mixed_parent_child_table(self):
        field_names = [field["name"] for field in create_table.STORYBOARD_VIDEO_FIELDS]
        self.assertIn("记录类型", field_names)
        self.assertIn("脚本内容", field_names)
        self.assertIn("关联产品记录", field_names)
        self.assertIn("选择模特", field_names)
        self.assertNotIn("产品名称", field_names)
        self.assertNotIn("目标人群", field_names)
        self.assertNotIn("核心冲突场景", field_names)
        self.assertNotIn("黄金3秒/戏剧钩子", field_names)
        self.assertNotIn("产品图", field_names)
        self.assertNotIn("角色图", field_names)
        self.assertNotIn("故事板图本地路径", field_names)
        self.assertNotIn("故事板图file_token", field_names)
        self.assertNotIn("故事板图片原始响应JSON", field_names)
        self.assertNotIn("视频通道", field_names)
        self.assertNotIn("视频生成模型", field_names)
        self.assertNotIn("本地视频路径", field_names)
        self.assertNotIn("分镜视频file_token", field_names)
        self.assertNotIn("视频生成原始响应JSON", field_names)
        self.assertNotIn("失败分类", field_names)
        self.assertNotIn("生成时间", field_names)
        self.assertIn("环境图", field_names)
        self.assertIn("Storyboard编号", field_names)
        self.assertIn("故事板图片生成状态", field_names)
        self.assertIn("视频生成状态", field_names)
        self.assertIn("分镜视频", field_names)
        field_by_name = {field["name"]: field for field in create_table.STORYBOARD_VIDEO_FIELDS}
        self.assertEqual([opt["name"] for opt in field_by_name["故事板图片模型"]["options"]], ["gpt-image-2", "gpt-image-2-2K", "gpt-image-2-4K"])
        self.assertEqual([opt["name"] for opt in field_by_name["故事板图片画面尺寸"]["options"]], ["1280x720", "720x1280", "1024x1024"])
        self.assertEqual([opt["name"] for opt in field_by_name["故事板图片画面比例"]["options"]], ["16:9", "9:16", "1:1"])
        self.assertEqual([opt["name"] for opt in field_by_name["Omni模型"]["options"]], ["omni_flash-10s"])
        self.assertEqual([opt["name"] for opt in field_by_name["Omni画面尺寸"]["options"]], ["720x1280", "1280x720"])
        self.assertEqual([opt["name"] for opt in field_by_name["Omni画面比例"]["options"]], ["9:16", "16:9"])
        image_view = create_table.TABLE_DEFINITION["views"]["02-故事板图片"]
        self.assertIn("故事板图片模型", image_view)
        self.assertIn("故事板图片画面尺寸", image_view)
        self.assertIn("故事板图片画面比例", image_view)
        self.assertLess(image_view.index("故事板图片提示词"), image_view.index("故事板图片模型"))
        self.assertLess(image_view.index("故事板图片画面比例"), image_view.index("故事板图片生成状态"))
        omni_view = create_table.TABLE_DEFINITION["views"]["03-Omni视频"]
        self.assertIn("Omni模型", omni_view)
        self.assertIn("Omni画面尺寸", omni_view)
        self.assertIn("Omni画面比例", omni_view)
        self.assertLess(omni_view.index("视频提示词"), omni_view.index("Omni模型"))
        self.assertLess(omni_view.index("Omni画面比例"), omni_view.index("视频生成状态"))
        self.assertEqual(create_table.TABLE_DEFINITION["key"], "storyboard_video")
        self.assertEqual(create_table.TABLE_DEFINITION["views"]["01-母任务入口"], [
            "任务名称", "脚本内容", "关联产品记录", "选择模特", "环境图", "拆分AI模型", "拆分AI参数JSON", "拆分状态", "错误信息",
        ])
        self.assertIn("02-故事板图片", create_table.TABLE_DEFINITION["views"])
        self.assertIn("03-Omni视频", create_table.TABLE_DEFINITION["views"])
        self.assertEqual(create_table.VIEW_FILTERS["01-母任务入口"], {
            "logic": "and",
            "conditions": [["记录类型", "intersects", ["母任务"]]],
        })
        self.assertEqual(create_table.VIEW_FILTERS["02-故事板图片"], {
            "logic": "and",
            "conditions": [["记录类型", "intersects", ["Storyboard分段"]]],
        })
        self.assertEqual(create_table.VIEW_FILTERS["03-Omni视频"], {
            "logic": "and",
            "conditions": [["记录类型", "intersects", ["Storyboard分段"]]],
        })

    def test_prune_obsolete_fields_deletes_by_field_id_for_special_names(self):
        calls = []

        def fake_run_json(args):
            calls.append(args)
            if "+field-list" in args:
                return {"data": {"fields": [{"name": "黄金3秒/戏剧钩子", "id": "fldHook"}]}}
            if "+field-delete" in args:
                return {"ok": True}
            raise AssertionError(args)

        with patch.object(create_table, "get_feishu_token", return_value="token"), \
             patch.object(create_table, "safe_list_records", return_value=[{"fields": {"黄金3秒/戏剧钩子": ""}}]), \
             patch.object(create_table, "run_json", side_effect=fake_run_json):
            deleted = create_table.prune_obsolete_fields("base", "tbl", field_names=["黄金3秒/戏剧钩子"])

        delete_call = [call for call in calls if "+field-delete" in call][0]
        self.assertEqual(deleted, ["黄金3秒/戏剧钩子"])
        self.assertEqual(delete_call[delete_call.index("--field-id") + 1], "fldHook")

    def test_backfill_storyboard_omni_defaults_only_updates_empty_segment_fields(self):
        updates = []
        records = [
            {
                "record_id": "rec_empty",
                "fields": {
                    "记录类型": "Storyboard分段",
                    "Omni模型": "",
                    "Omni画面尺寸": "",
                    "Omni画面比例": "",
                },
            },
            {
                "record_id": "rec_custom",
                "fields": {
                    "记录类型": "Storyboard分段",
                    "Omni模型": "omni_flash-10s",
                    "Omni画面尺寸": "1280x720",
                    "Omni画面比例": "16:9",
                },
            },
            {
                "record_id": "rec_parent",
                "fields": {
                    "记录类型": "母任务",
                    "Omni模型": "",
                    "Omni画面尺寸": "",
                    "Omni画面比例": "",
                },
            },
        ]

        with patch.object(create_table, "safe_list_records", return_value=records), \
             patch.object(create_table, "safe_update_record", side_effect=lambda token, table_id, record_id, fields: updates.append((record_id, fields))):
            updated = create_table.backfill_storyboard_omni_defaults("token", "tbl_storyboard")

        self.assertEqual(updated, 1)
        self.assertEqual(updates, [(
            "rec_empty",
            {
                "Omni模型": "omni_flash-10s",
                "Omni画面尺寸": "720x1280",
                "Omni画面比例": "9:16",
            },
        )])

    def test_backfill_storyboard_image_defaults_only_updates_empty_segment_fields(self):
        updates = []
        records = [
            {
                "record_id": "rec_empty",
                "fields": {
                    "记录类型": "Storyboard分段",
                    "故事板图片模型": "",
                    "故事板图片画面尺寸": "",
                    "故事板图片画面比例": "",
                },
            },
            {
                "record_id": "rec_custom",
                "fields": {
                    "记录类型": "Storyboard分段",
                    "故事板图片模型": "gpt-image-2-2K",
                    "故事板图片画面尺寸": "720x1280",
                    "故事板图片画面比例": "9:16",
                },
            },
            {
                "record_id": "rec_parent",
                "fields": {
                    "记录类型": "母任务",
                    "故事板图片模型": "",
                    "故事板图片画面尺寸": "",
                    "故事板图片画面比例": "",
                },
            },
        ]

        with patch.object(create_table, "safe_list_records", return_value=records), \
             patch.object(create_table, "safe_update_record", side_effect=lambda token, table_id, record_id, fields: updates.append((record_id, fields))):
            updated = create_table.backfill_storyboard_image_defaults("token", "tbl_storyboard")

        self.assertEqual(updated, 1)
        self.assertEqual(updates, [(
            "rec_empty",
            {
                "故事板图片模型": "gpt-image-2",
                "故事板图片画面尺寸": "1280x720",
                "故事板图片画面比例": "16:9",
            },
        )])

    def test_backfill_storyboard_record_types_repairs_mixed_parent_child_rows(self):
        updates = []
        records = [
            {
                "record_id": "rec_child_marked_parent",
                "fields": {
                    "记录类型": "母任务",
                    "父任务记录ID": "recParent",
                    "故事板图片提示词": "prompt",
                },
            },
            {
                "record_id": "rec_empty_parent_type",
                "fields": {
                    "记录类型": "",
                    "父任务记录ID": "",
                    "脚本内容": "script",
                    "关联产品记录": [{"record_ids": ["recProduct"]}],
                },
            },
            {
                "record_id": "rec_blank",
                "fields": {
                    "记录类型": "",
                    "父任务记录ID": "",
                    "脚本内容": "",
                },
            },
            {
                "record_id": "rec_good_child",
                "fields": {
                    "记录类型": "Storyboard分段",
                    "父任务记录ID": "recParent",
                },
            },
        ]

        with patch.object(create_table, "safe_list_records", return_value=records), \
             patch.object(create_table, "safe_update_record", side_effect=lambda token, table_id, record_id, fields: updates.append((record_id, fields))):
            updated = create_table.backfill_storyboard_record_types("token", "tbl_storyboard")

        self.assertEqual(updated, 2)
        self.assertEqual(updates, [
            ("rec_child_marked_parent", {"记录类型": "Storyboard分段"}),
            ("rec_empty_parent_type", {"记录类型": "母任务"}),
        ])

    def test_backfill_storyboard_parent_task_names_only_updates_empty_parents(self):
        updates = []
        records = [
            {"record_id": "recParent123456", "fields": {"记录类型": "母任务", "任务名称": ""}},
            {"record_id": "recNamed", "fields": {"记录类型": "母任务", "任务名称": "已有名称"}},
            {"record_id": "recChild", "fields": {"记录类型": "Storyboard分段", "任务名称": ""}},
        ]

        with patch.object(create_table, "safe_list_records", return_value=records), \
             patch.object(create_table, "safe_update_record", side_effect=lambda token, table_id, record_id, fields: updates.append((record_id, fields))):
            updated = create_table.backfill_storyboard_parent_task_names("token", "tbl_storyboard")

        self.assertEqual(updated, 1)
        self.assertEqual(updates, [("recParent123456", {"任务名称": "故事板任务-123456"})])

    def test_storyboard_dispatcher_filters_by_record_type(self):
        storyboard_watches = {
            watch["name"]: watch
            for watch in dispatcher.RAW_WATCH_LIST
            if watch.get("name") in {"故事板提示词拆分", "故事板图片生成", "故事板Omni视频生成"}
        }

        self.assertEqual(storyboard_watches["故事板提示词拆分"]["required_field_values"], {"记录类型": ["母任务"]})
        self.assertEqual(storyboard_watches["故事板图片生成"]["required_field_values"], {"记录类型": ["Storyboard分段"]})
        self.assertEqual(storyboard_watches["故事板Omni视频生成"]["required_field_values"], {"记录类型": ["Storyboard分段"]})

    def test_resolve_storyboard_table_id_prefers_configured_existing_table_id(self):
        table_id, created = create_table.resolve_storyboard_table_id(
            {"feishu": {"tables": {"storyboard_video": "tbl_existing"}}},
            "base",
            {"Other Table": "tbl_other"},
            create_table_fn=Mock(side_effect=AssertionError("should not create table")),
            fields=[],
        )

        self.assertEqual(table_id, "tbl_existing")
        self.assertFalse(created)

    def test_resolve_parent_reference_context_uses_linked_product_and_model(self):
        context = storyboard_video.resolve_parent_reference_context(
            "token",
            parent_fields(),
            get_record_fn=fake_parent_lookup,
            product_table_id="tblProduct",
            model_table_id="tblModel",
        )

        self.assertEqual(context["product_record_id"], "recProduct")
        self.assertEqual(context["model_record_id"], "recModel")
        self.assertEqual(context["product_name"], "宠物除臭喷雾")
        self.assertEqual(context["target_audience"], "Thai pet owners")
        self.assertEqual(context["product_tokens"], ["ft_product"])
        self.assertEqual(context["character_tokens"], ["ft_character"])
        self.assertEqual(context["environment_tokens"], ["ft_environment"])

    def test_resolve_parent_reference_context_requires_single_product_and_at_least_one_model(self):
        with self.assertRaisesRegex(ValueError, "必须选择 1 个产品"):
            storyboard_video.resolve_parent_reference_context(
                "token",
                {"关联产品记录": [], "选择模特": [{"record_ids": ["recModel"]}]},
                get_record_fn=fake_parent_lookup,
                product_table_id="tblProduct",
                model_table_id="tblModel",
            )

        with self.assertRaisesRegex(ValueError, "必须至少选择 1 个模特"):
            storyboard_video.resolve_parent_reference_context(
                "token",
                {"关联产品记录": [{"record_ids": ["recProduct"]}], "选择模特": []},
                get_record_fn=fake_parent_lookup,
                product_table_id="tblProduct",
                model_table_id="tblModel",
            )

        with self.assertRaisesRegex(ValueError, "recMissingPhoto.*缺少模特照片"):
            storyboard_video.resolve_parent_reference_context(
                "token",
                {
                    "关联产品记录": [{"record_ids": ["recProduct"]}],
                    "选择模特": [{"record_ids": ["recMissingPhoto"]}],
                    "环境图": [{"file_token": "ft_environment"}],
                },
                get_record_fn=lambda token, table_id, record_id: (
                    {"产品图片": [{"file_token": "ft_product"}]}
                    if record_id == "recProduct"
                    else {"模特名称": "recMissingPhoto", "模特照片": []}
                ),
                product_table_id="tblProduct",
                model_table_id="tblModel",
            )

    def test_regeneration_reset_fields_clear_old_outputs(self):
        image_reset = storyboard_video.image_regeneration_reset_fields()
        self.assertEqual(image_reset["故事板图"], [])
        self.assertEqual(image_reset["故事板图片任务ID"], "")
        self.assertIsNone(image_reset["故事板图片生成时间"])
        self.assertEqual(image_reset["分镜视频"], [])
        self.assertIsNone(image_reset["分镜视频URL"])
        self.assertEqual(image_reset["视频任务ID"], "")
        self.assertEqual(image_reset["视频生成状态"], "不触发")

        video_reset = storyboard_video.video_regeneration_reset_fields()
        self.assertEqual(video_reset["分镜视频"], [])
        self.assertIsNone(video_reset["分镜视频URL"])
        self.assertEqual(video_reset["视频任务ID"], "")
        self.assertIsNone(video_reset["视频生成时间"])

    def test_dispatcher_claim_clear_values_supports_typed_resets(self):
        claim_fields = {"视频生成状态": "生成中"}
        dispatcher.apply_claim_clear_fields(claim_fields, {
            "claim_clear_values": {
                "分镜视频": [],
                "分镜视频URL": None,
                "视频生成时间": None,
            }
        })

        self.assertEqual(claim_fields["分镜视频"], [])
        self.assertIsNone(claim_fields["分镜视频URL"])
        self.assertIsNone(claim_fields["视频生成时间"])

    def test_storyboard_dispatcher_clears_url_fields_with_null(self):
        storyboard_watches = {
            watch["name"]: watch
            for watch in dispatcher.RAW_WATCH_LIST
            if watch.get("name") in {"故事板图片生成", "故事板Omni视频生成"}
        }

        self.assertIsNone(storyboard_watches["故事板图片生成"]["claim_clear_values"]["分镜视频URL"])
        self.assertIsNone(storyboard_watches["故事板Omni视频生成"]["claim_clear_values"]["分镜视频URL"])

    def test_bootstrap_config_creates_only_missing_storyboard_stages(self):
        created = []
        with patch.object(bootstrap_config, "get_feishu_token", return_value="token"), \
             patch.object(bootstrap_config, "safe_list_records", return_value=[
                 {"record_id": "rec_image", "fields": {"环节": "故事板图片生成-OTU"}}
             ]), \
             patch.object(bootstrap_config, "config_field_names", return_value={"环节", "模型名称", "API Key", "API 代理地址", "调用方式", "状态", "备注", "提示词"}), \
             patch.dict(os.environ, {"STORYBOARD_VIDEO_OTU_API_KEY": "sk-test", "STORYBOARD_TEXT_SPLIT_API_KEY": "sk-text"}, clear=False), \
             patch.object(bootstrap_config, "create_config_record", side_effect=lambda token, fields, existing_fields: created.append(fields) or "rec_new"), \
             patch("tk_bootstrap_storyboard_video_config.print") as printer:
            bootstrap_config.main()

        self.assertEqual([item["环节"] for item in created], ["故事板图片提示词拆分-Gemini", "故事板视频生成-Omni"])
        self.assertIn("强制视觉网格排版", created[0]["提示词"])
        self.assertIn("固定环境参考区", created[0]["提示词"])
        self.assertIn("环境参考", created[0]["提示词"])
        self.assertIn("所有镜头必须发生在同一个固定场景中", created[0]["提示词"])
        self.assertIn("第二区块", created[0]["提示词"])
        self.assertIn("素材区", created[0]["提示词"])
        self.assertIn("每个镜头网格内部", created[0]["提示词"])
        self.assertIn("底部表格", created[0]["提示词"])
        self.assertIn("纯净代码块", created[0]["提示词"])
        self.assertIn("Storyboard 01 Prompt:", created[0]["提示词"])
        self.assertNotIn("JSON schema", created[0]["提示词"])
        self.assertEqual(created[0]["模型名称"], "gemini-3.1-pro-preview")
        self.assertEqual(created[0]["API 代理地址"], "https://aihubmix.com/gemini")
        self.assertEqual(created[0]["API Key"], "sk-text")
        self.assertEqual(created[1]["模型名称"], "omni_flash-10s")
        self.assertEqual(created[1]["API 代理地址"], "https://otuapi.com")
        self.assertEqual(created[1]["画面尺寸"], "720x1280")
        self.assertEqual(created[1]["画面比例"], "9:16")
        self.assertIn("根据上传图片的核心人物形象", created[1]["提示词"])
        self.assertIn("极度重要（排他指令）", created[1]["提示词"])
        self.assertIn("纯净、无边框、无文字", created[1]["提示词"])
        printed = printer.call_args.args[0]
        self.assertIn("故事板视频生成-Omni", printed)
        self.assertNotIn("sk-test", printed)
        self.assertNotIn("sk-text", printed)

    def test_bootstrap_split_prompt_requires_own_text_key_not_otu_key(self):
        created = []
        with patch.object(bootstrap_config, "get_feishu_token", return_value="token"), \
             patch.object(bootstrap_config, "safe_list_records", return_value=[
                 {"record_id": "rec_image", "fields": {"环节": "故事板图片生成-OTU"}},
                 {"record_id": "rec_video", "fields": {"环节": "故事板视频生成-Omni"}},
             ]), \
             patch.object(bootstrap_config, "config_field_names", return_value={"环节", "模型名称", "API Key", "API 代理地址", "调用方式", "状态", "备注", "提示词"}), \
             patch.dict(os.environ, {}, clear=True), \
             patch.object(bootstrap_config, "create_config_record", side_effect=lambda token, fields, existing_fields: created.append(fields) or "rec_new"):
            bootstrap_config.main()

        self.assertEqual(created, [])


if __name__ == "__main__":
    unittest.main()
