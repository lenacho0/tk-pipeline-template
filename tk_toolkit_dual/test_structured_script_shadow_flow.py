#!/usr/bin/env python3
"""
结构化脚本影子测试
test_structured_script_shadow_flow.py

输入: 旧格式脚本（纯文本，口播+画面）
输出:
  1. 结构化脚本 JSON（带 content_type: dialogue/voiceover/silent_action）
  2. 基于结构化结果生成的新版分镜提示词
  3. 基于结构化结果生成的新版视频提示词
  4. Markdown 对比报告

不对正式链路做任何修改，仅做离线影子测试。
Usage:
  python3 test_structured_script_shadow_flow.py [--sample SAMPLE_ID] [--all]
"""

import json
import os
import sys
import textwrap
import re
from datetime import datetime
from pathlib import Path

# ── paths ──────────────────────────────────────────────────────────────────────
WORKSPACE   = Path(os.environ.get("WORKSPACE", ".")).resolve()
OUT_DIR     = WORKSPACE / "structured_script_shadow_output"
OUT_DIR.mkdir(exist_ok=True)
SCRIPT_DIR  = WORKSPACE / "tk_toolkit_dual"

# ── LLM prompt for structuring ─────────────────────────────────────────────────
STRUCTURE_SCRIPT_PROMPT = textwrap.dedent("""
You are a script structuring assistant for short-form e-commerce videos (TikTok style, ~15s, 9:16 vertical).

## Your task
Given a legacy script in Thai (with optional Chinese translation), output a STRUCTURED JSON script.
Each line/section of the original script should be mapped to one or more "segment" objects.

## Segment types (content_type)
You MUST classify each segment into exactly ONE of these three types:

- **dialogue**: A character is VISIBLY SPEAKING IN THE SCENE — talking to camera, talking to another character, or addressing the viewer directly. The speaker must be identifiable (e.g., "女主人", "猫咪" as anthropomorphic, "兽医"). This triggers lip-sync / speaking expression constraints in downstream video generation.
  → Required fields: visible speaker identity, emotion/tone

- **voiceover**: Narration / voiceover that plays OVER the scene. No visible speaker. The character may be doing something unrelated to speaking. This is the default for traditional voice-over scripts.
  → Include: key message points covered by the narration

- **silent_action**: Pure visual / action scene with NO voice, no speech, no narration. Used for pacing, atmosphere, product showcase moments, or result demonstrations.
  → Include: what is visually happening

## Rules
1. **dialogue segments**: If a Thai voiceover line describes someone addressing the camera, talking to someone, or otherwise implies the speaker is present on screen → mark as dialogue. The speaker is whoever is described as the active subject in that segment.
2. **voiceover segments**: If the voiceover describes what is happening but the speaker is not visibly on screen (e.g., "天然生物酶从源头分解...") → mark as voiceover.
3. **silent_action segments**: Pure visual descriptions (e.g., product close-up, cat rolling, satisfied reaction shots) with no Thai voiceover → mark as silent_action.
4. If a story beat has BOTH visible speech AND other action, split into multiple segments.
5. Preserve ALL Thai voiceover text exactly. Do NOT translate or omit it.
6. The "shot_duration" in each segment should reflect the original timing if specified.
7. Output valid JSON only — no markdown, no explanation, no preamble.

## Output JSON schema
{
  "schema_version": "structured_script_v1",
  "source_script": "... (original script text)",
  "video_duration": "... (target duration, e.g. '15s')",
  "segments": [
    {
      "id": 1,
      "content_type": "dialogue | voiceover | silent_action",
      "thai_voiceover": "... (exact Thai text, omit if silent_action)",
      "chinese_note": "... (Chinese translation if present in original)",
      "speaker": "... (character name, required for dialogue, null otherwise)",
      "speaker_visible": true | false,
      "scene_description": "... (what's on screen)",
      "shot_duration": "... (e.g., '3s')",
      "notes": "... (e.g., 'visible speaking expression required')"
    }
  ]
}
""").strip()

# ── Storyboard prompt builder (content_type-aware) ────────────────────────────
def build_storyboard_prompt(structured_json: str, product_info: str, model_info: str, duration: str) -> str:
    return textwrap.dedent(f"""
You are a storyboard planner for TikTok-style product videos (9:16 vertical, ~{duration}).

## Structured script (source) — follow content_type strictly
{structured_json}

## Your task
Generate exactly 9 shots (分镜) for a 3x3 storyboard grid.
For each shot, you MUST respect the content_type:
- **dialogue**: The speaker must be VISIBLE ON SCREEN, facing camera or engaging with other characters. Include facial expression and lip-sync cues in the prompt.
- **voiceover**: No visible speaker needed; focus on visual storytelling of the narration's content.
- **silent_action**: Pure visual, no voice, no speech bubbles. Can include product close-ups, pet action, result demonstration.

## Output JSON:
{{
  "shots": [
    {{
      "shot_number": "分镜 N (content_type)",
      "prompt_text": "...",
      "content_type_influenced_by": "dialogue | voiceover | silent_action",
      "speaker_visible": true | false,
      "notes": "..."
    }}
  ]
}}

## Product reference
{product_info}

## Character reference
{model_info}
""").strip()

# ── Video prompt builder (content_type-aware) ──────────────────────────────────
def build_video_prompt(structured_json: str, shots_json: str, duration: str) -> str:
    return textwrap.dedent(f"""
Based on the structured script and storyboard below, generate a video generation prompt.

## Structured script
{structured_json}

## Storyboard shots
{shots_json}

## Video prompt rules
- For **dialogue** segments: explicitly instruct the video model to show the speaker VISIBLY TALKING with correct lip-sync and facial expressions. The speaker must appear on screen.
- For **voiceover** segments: narration plays over visuals, no visible speaker required.
- For **silent_action** segments: pure visual, no audio track for these moments.
- Preserve the 9:16 vertical format.
- Target duration: {duration}.
- Maintain character identity and visual consistency.

## Output
A single video generation prompt string (in English) that will be sent to the video model.
""").strip()

# ── 6 Sample test scripts ─────────────────────────────────────────────────────
SAMPLE_SCRIPTS = [
    # ── Sample 1: 对白主导 (Dialogue-driven) ────────────────────────────────
    {
        "id": "sample_01",
        "type": "对白主导",
        "record_id": "recvf8PySi1U91",
        "product_info": "宠物尿味分解除臭喷雾 300ml | 卖点: 天然生物酶从源头分解、多用途、快速见效",
        "model_info": "MoMo (黑白相间母暹罗猫) + 年轻泰国女子",
        "video_duration": "15s",
        "legacy_script": """---
**分镜 1（时长 3s）**
画面：明亮的室内客厅，一位年轻泰国女子双手捂住鼻子，眉头紧锁表情极度崩溃。她脚边的木地板上放着一个带有微黄水迹的布艺宠物垫。宠物垫旁边坐着一只黑白相间的母暹罗猫（MoMo），正抬头满脸无辜地看着镜头。自然光线从窗户照入。
口播（泰文）：โอ๊ย! แมวฉี่เรี่ยราด เหม็นฉุนไปทั้งบ้าน ทนไม่ไหวแล้ว!
口播（中文）：哎哟！猫咪到处乱尿，满屋子骚臭味，受不了啦！

---
**分镜 2（时长 4s）**
画面：年轻女子表情瞬间变得自信，单手举起一瓶白色的除臭喷雾。接着镜头快速剪辑展示实操：女子的手持喷雾连续喷向灰色的布艺沙发角落、米色的毛绒地毯和蓝色的宠物窝。光线明亮，动作迅速利落。
口播（泰文）：ใช้สเปรย์ขวดนี้! ฉีดโซฟา พรม ที่นอน ได้หมดเลย
口播（中文）：用这瓶喷雾！沙发、地毯、床垫全都能喷。

---
**分镜 3（时长 5s）**
画面：首先是微距特写镜头：细密均匀的水雾喷洒并渗入粗糙的纤维布料中。紧接着镜头切换：在明亮柔和的光线下，女子微笑着温柔抚摸那只黑白相间的母暹罗猫（MoMo），猫咪眯着眼睛舒适地享受抚摸，画面充满安全感。
口播（泰文）：เอนไซม์ธรรมชาติสลายกลิ่นถึงต้นตอ ไม่ใช่น้ำหอมกลบ ปลอดภัยต่อน้องแมว
口播（中文）：天然生物酶从源头分解异味，绝非香精掩盖，对猫咪超安全！

---
**分镜 4（时长 3s）**
画面：女子将脸部凑近之前喷过喷雾的灰色沙发，闭上双眼，嘴角上扬，做出 一个深深吸气、极为舒展放松的动作。那只黑白相间的母暹罗猫（MoMo）乖巧安静地趴在沙发扶手上。最后女子右手食指坚定地指向画面左下角。光线温暖明亮。
口播（泰文）：แค่ 15 นาที กลิ่นหายเกลี้ยง! รีบกดตะกร้าซ้ายล่างเลย!
口播（中文）：只需15分钟异味全消！快点左下角小黄车下单！"""
    },
    # ── Sample 2: 对白主导 (Direct CTA address) ────────────────────────────
    {
        "id": "sample_02",
        "type": "对白主导",
        "record_id": "recvf8PBDgpcIu",
        "product_info": "宠物尿味分解除臭喷雾 300ml | 卖点: 天然生物酶、多用途、对宠物安全",
        "model_info": "YOYO (白色母银渐层猫) + 年轻泰国博主",
        "video_duration": "15s",
        "legacy_script": """---
**分镜 1（时长 3s）**
画面：室内明亮客厅。博主夸张地捏着鼻子，五官扭曲，痛苦地指着沙发脚下的一小滩水迹。一只白色的母银渐层猫（YOYO）坐在水迹旁边，抬头满脸无辜地看着镜头。
口播（泰文）：เจ้านายฉี่เรี่ยราด กลิ่นเหม็นจนบ้านจะพัง! ทำไงดี?
口播（中文）：主子乱尿，臭得房子都要塌了！怎么办？

---
**分镜 2（时长 4s）**
画面：博主瞬间变脸，自信地举起一瓶300ml的宠物尿液除臭喷雾。快速跳剪：分别在布艺沙发、毛绒地毯、以及YOYO的专属猫窝上喷洒。
口播（泰文）：สเปรย์ตัวนี้ช่วยชีวิต! ฉีดได้ทุกที่ ทั้งโซฟา พรม ที่นอน ใช้งานง่ายมาก!
口播（中文）：这款喷雾来救命！沙发、地毯、窝垫哪里都能喷，超级好用！

---
**分镜 3（时长 5s）**
画面：博主将喷雾举到镜头前展示瓶身，YOYO好奇地蹭了蹭瓶子。闭眼深吸气，陶醉放松的表情。
口播（泰文）：แค่ 5 นาที กลิ่นหายเกลี้ยง! สกัดจากเอนไซม์ธรรมชาติ สลายกลิ่นที่ต้นตอ ไม่ใช่น้ำหอมกลบกลิ่น ปลอดภัยต่อน้องๆ แน่นอน
口播（中文）：短短5分钟，臭味全消失！天然酶提取，源头分解异味绝非香精掩盖，对毛孩子绝对安全。

---
**分镜 4（时长 3s）**
画面：YOYO在干净猫垫上开心打滚。博主抚摸猫咪，另一只手明确指向画面左下角。
口播（泰文）：เพื่อสุขภาพของลูกรัก หยุดใช้สารเคมี แล้วกดตะกร้าซ้ายล่างตุนเลย!
口播（中文）：为了宝贝的健康，别用化学品啦，点击左下角小黄车赶紧囤货！"""
    },
    # ── Sample 3: 混合型 ───────────────────────────────────────────────────
    {
        "id": "sample_03",
        "type": "混合型",
        "record_id": "recvf8PIXjxMUK",
        "product_info": "宠物尿味分解除臭喷雾 300ml | 卖点: 天然植物酶、发情期尿液、安全快速",
        "model_info": "YOYO (母银渐层猫) + 泰国女博主",
        "video_duration": "15s",
        "legacy_script": """---
**分镜 1（4s）**
画面：博主推开门走进房间，瞬间面部扭曲，极度夸张地捏住鼻子。镜头快速摇向沙发，YOYO正无辜坐在尿迹旁，低头舔爪子。
口播（泰文）：โอ๊ย! ทาสแมวต้องปวดหัว กลิ่นฉี่ฉุนกึกทั่วบ้านเพราะช่วงติดสัด!
口播（中文）：哎哟！猫奴太头痛了，发情期满屋子都是刺鼻的尿骚味！

---
**分镜 2（4s）**
画面：博主拿出300ml喷雾，摆手做出"打叉"拒绝手势，表情转为专业自信的科普状态。
口播（泰文）：หยุดใช้น้ำหอมกลบกลิ่น! ต้องขวดนี้ ใช้เอนไซม์พืชธรรมชาติสลายกลิ่นจากต้นตอ
口播（中文）：别再用香精掩盖了！得用这瓶，天然植物酵素从源头分解臭味。

---
**分镜 3（5s）**
画面：喷雾直接喷在手心微笑点头展示安全。接着多场景快速跳剪：沙发尿渍处、木地板角落、猫窝YOYO。
口播（泰文）：ปลอดภัยโดนผิวได้! ฉีดได้ทุกที่ โซฟา พื้นไม้ ที่นอนแมว ไม่ทำลายพื้นผิว
口播（中文）：安全到能接触皮肤！沙发、木地板、猫窝哪都能喷，不伤材质。

---
**分镜 4（4s）**
画面：博主指着手表示意等待。凑近沙发闭眼深吸气，绽放出陶醉表情，对镜头竖起大拇指。
口播（泰文）：รอแค่ 15 นาที กลิ่นฉี่หายวับไปเลย ไม่เหลือคราบ!
口播（中文）：只需等待15分钟，尿味消失得无影无踪，不留痕迹！

---
**分镜 5（5s）**
画面：YOYO在喷过喷雾的沙发上翻着白肚皮呼呼大睡。博主坐在旁边温柔抚摸YOYO毛发。
口播（泰文）：หมดห่วงเรื่องแบคทีเรียสะสม คืนบ้านที่สะอาดและปลอดภัยให้น้อง
口播（中文）：彻底告别细菌隐患，还毛孩子一个干净安全的家。

---
**分镜 6（3s）**
画面：博主单手举喷雾瓶，表情充满激情与紧迫感，手指用力指向画面左下方。YOYO乖巧坐在旁边看着镜头。
口播（泰文）：ขวดใหญ่ 300ml คุ้มมาก รีบกดตะกร้าซ้ายล่างเลยก่อนของหมด!
口播（中文）：300ml大瓶超划算，趁没抢光赶紧点左下角小黄车！"""
    },
    # ── Sample 4: 混合型 (Pet anthro) ───────────────────────────────────────
    {
        "id": "sample_04",
        "type": "混合型",
        "record_id": "recvfjuvKS85uV",
        "product_info": "宠物尿味分解除臭喷雾 300ml | 卖点: 天然酶、15分钟见效、安全",
        "model_info": "MoMo (母暹罗猫) + 女性主人",
        "video_duration": "12s",
        "legacy_script": """---
**分镜 1（3s）**
画面：明亮的客厅，MoMo坐在沙发旁，表情无辜。沙发垫上有明显水渍。女性主人的手入画，捏住鼻子，表现出嫌弃和无奈。
口播（泰文）：แมวฉี่ใส่โซฟา กลิ่นเหม็นจนปวดหัว!
口播（中文）：猫咪尿沙发，味道臭到头痛！

---
**分镜 2（4s）**
画面：特写女性的手拿白色除味喷雾（300ml），直接对着沙发水渍喷洒。细腻水雾均匀落在织物表面。MoMo在旁边好奇看着。
口播（泰文）：สเปรย์เอนไซม์ธรรมชาติขวดนี้ ฉีดปุ๊บ สลายกลิ่นฉี่ที่ต้นตอ ไม่ใช่แค่ใช้น้ำหอมกลบนะ
口播（中文）：这瓶天然生物酶喷雾，一喷从源头分解尿味，不仅是香精掩盖哦。

---
**分镜 3（3s）**
画面：同一张沙发，水渍已干透。女性凑近沙发闻了闻，露出满意微笑。MoMo蜷缩在刚才喷过喷雾的区域安心闭眼睡觉。阳光洒在沙发上，画面温馨。
口播（泰文）：รอแค่ 15 นาที กลิ่นหายเกลี้ยง ปลอดภัยต่อลูกๆ แน่นอน
口播（中文）：只需等待15分钟，异味全无，对毛孩子绝对安全。

---
**分镜 4（2s）**
画面：女性的手拿白色除味喷雾展示在镜头前，背景是熟睡的MoMo。手指指向画面左下角。景深效果，背景微模糊。
口播（泰文）：บ้านหอมสะอาด จิ้มตะกร้าเลย!
口播（中文）：家里干干净净，快点购物车！"""
    },
    # ── Sample 5: 旁白主导 (Voiceover-driven, pet anthro CGI) ───────────────
    {
        "id": "sample_05",
        "type": "旁白主导",
        "record_id": "pet_ref_analysis_01",
        "product_info": "宠物益生菌 | 卖点: 改善肠胃、化毛、增强免疫、去口臭",
        "model_info": "CGI白发医生 + CGI猫（宠物拟人视频参考）",
        "video_duration": "71s",
        "legacy_script": """---
**分镜 1（7s, Hook）**
画面：面带怒容的CGI白发医生指着镜头，质问主人为何让宠物处于如此糟糕的状况，背景是诊疗台上的猫。
口播（泰文）：[严厉质问主人为何让'孩子'处于如此糟糕的状况，制造焦虑]
口播（中文）：严厉质问主人为何让孩子处于如此糟糕的状况，制造焦虑

---
**分镜 2（7s, 痛点放大）**
画面：猫咪艰难排便，排出巨大的绿色发光粘液。
口播（泰文）：[指出排便困难的问题，批评强迫吃蔬菜的错误做法，提出需要刺激肠道的微生物]
口播（中文）：批评强迫吃蔬菜的错误做法

---
**分镜 3（7s, 痛点放大）**
画面：医生看着一滩黑色呕吐物，猫咪呕吐毛球。
口播（泰文）：[建议补充有益菌促进消化]
口播（中文）：建议补充有益菌促进消化

---
**分镜 4（7s, 痛点放大）**
画面：主人端着昂贵的猫粮，但猫咪拒绝进食。
口播（泰文）：[解释挑食是因为消化不良，需要补充消化酶]
口播（中文）：挑食是因为消化不良

---
**分镜 5（7s, 痛点放大）**
画面：猫咪面前出现蓝色能量护盾，挡住了绿色的病毒粘液。
口播（泰文）：[强调免疫系统的重要性，引出益生菌可以增强免疫力]
口播（中文）：强调免疫系统的重要性

---
**分镜 6（7s, 痛点放大）**
画面：医生吹散手中的猫毛，空气中漂浮着大量毛发。
口播（泰文）：[将掉毛和过敏问题归结于肠道免疫力低下]
口播（中文）：将掉毛和过敏问题归结于肠道免疫力低下

---
**分镜 7（7s, 痛点放大）**
画面：猫咪打哈欠，嘴里飘出一个绿色的口臭幽灵，医生捂住鼻子。
口播（泰文）：[将口臭视为肠道崩溃的信号，警告需要紧急处理]
口播（中文）：将口臭视为肠道崩溃的信号

---
**分镜 8（15s, Solution+CTA）**
画面：画面切换至真实兽医在诊所内，手持Pethealer益生菌产品展示，屏幕出现指向购物车的黄色箭头。
口播（泰文）：[总结产品可以解决上述肠道和免疫力问题，强烈推荐购买，并引导查看购物车]
口播（中文）：总结产品可以解决上述肠道和免疫力问题"""
    },
    # ── Sample 6: 静默/氛围主导 (Silent/Atmosphere-driven) ──────────────────
    {
        "id": "sample_06",
        "type": "静默/氛围主导",
        "record_id": "silent_atmosphere_01",
        "product_info": "宠物尿味分解除臭喷雾 300ml | 卖点: 快速分解、无毒、多用途",
        "model_info": "无人物/纯产品ASMR风格",
        "video_duration": "15s",
        "legacy_script": """---
**分镜 1（3s）**
画面：纯白背景，特写300ml宠物除臭喷雾瓶身，瓶身干净洁白，标签完整。光线从左上方打来，产生柔和高光。
口播（泰文）：（无声）
口播（中文）：（无声）

---
**分镜 2（3s）**
画面：特写喷雾嘴部，纤细的白色喷雾从喷嘴均匀喷出，水雾在灯光下呈现为细腻的半透明白色颗粒，在空气中缓缓扩散。
口播（泰文）：（无声）
口播（中文）：（无声）

---
**分镜 3（3s）**
画面：特写喷雾落在灰色布艺沙发表面，细腻的水雾均匀渗入布料纤维，织物纹理在微距镜头下清晰可见。
口播（泰文）：（无声）
口播（中文）：（无声）

---
**分镜 4（3s）**
画面：特写喷雾落在木地板表面，水珠在光滑的木纹上形成均匀薄层，然后快速被吸收，表面恢复干爽。
口播（泰文）：（无声）
口播（中文）：（无声）

---
**分镜 5（3s）**
画面：特写白色猫爪踩在已经喷过喷雾的干净柔软地毯上，猫爪轻轻按压，地毯纤维在按压下轻轻凹陷，随即回弹，传递出柔软干爽的触感。
口播（泰文）：（无声）
口播（中文）：（无声）"""
    },
]


def call_llm(prompt: str, model: str = "gemini-2.0-flash") -> str:
    """Call the LLM via the project's standard client setup."""
    sys.path.insert(0, str(SCRIPT_DIR))
    try:
        from common import get_feishu_token, get_model_config, get_gemini_client, CONFIG_RECORDS
        # Use script_gen config record (same Gemini credentials as pet_reference)
        record_id = CONFIG_RECORDS.get("script_gen", "")
        if not record_id:
            return "<!-- LLM call failed: no script_gen config record found -->"
        token = get_feishu_token()
        config = get_model_config(token, record_id)
        api_key = (config.get("api_key") or "").strip()
        api_base = (config.get("api_base") or "https://aihubmix.com/gemini").strip()
        if not api_key:
            return "<!-- LLM call failed: empty API key in config -->"
        client = get_gemini_client(api_key, api_base)
        from google.genai import types
        response = client.models.generate_content(
            model=model,
            contents=[types.Content(role="user", parts=[types.Part.from_text(text=prompt)])],
        )
        return response.text
    except Exception as e:
        import traceback
        return f"<!-- LLM call failed: {e}\n{traceback.format_exc()} -->"


def parse_json_response(response_text: str):
    """Extract JSON from LLM response, handling markdown code blocks."""
    text = response_text.strip()
    # Remove ```json ... ``` or ``` ... ```
    match = re.search(r'```(?:json)?\n?([\s\S]*?)```', text)
    if match:
        text = match.group(1)
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError as e:
        print(f"JSON parse error: {e}")
        print(f"Raw response (first 500 chars): {response_text[:500]}")
        return None


def generate_comparison_report(
    sample: dict,
    structured: dict,
    storyboard_result: str,
    video_prompt: str,
) -> str:
    """Generate a markdown comparison report."""
    duration = structured.get("video_duration", sample.get("video_duration", "?"))

    dialogue_segs = [s for s in structured.get("segments", []) if s.get("content_type") == "dialogue"]
    voiceover_segs = [s for s in structured.get("segments", []) if s.get("content_type") == "voiceover"]
    silent_segs = [s for s in structured.get("segments", []) if s.get("content_type") == "silent_action"]

    # Parse storyboard JSON if possible
    sb_data = None
    try:
        sb_data = json.loads(storyboard_result)
    except (json.JSONDecodeError, TypeError):
        pass

    # Dialogue speaker summary
    speakers = set(s.get("speaker", "?") for s in dialogue_segs if s.get("speaker"))

    # Legacy script line count (approximate)
    legacy_lines = len([l for l in sample["legacy_script"].split("\n") if l.strip()])

    report = f"""# 结构化脚本影子测试报告

**样本 ID**: `{sample['id']}`
**类型**: {sample['type']}
**Record ID**: `{sample['record_id']}`
**产品**: {sample['product_info']}
**目标时长**: {duration}
**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

---

## 原始脚本 vs 结构化脚本

### Legacy 格式
- 纯文本口播 + 画面描述
- 无 `content_type` 语义区分
- **下游视频生成默认全部按旁白（voiceover）处理，无法区分说话主体是否出镜**

### 结构化脚本格式
- 每个片段标注 `content_type: dialogue | voiceover | silent_action`
- `dialogue` → 触发可见说话主体约束（口型/表情/出镜）
- `voiceover` → 画外旁白（无出镜要求）
- `silent_action` → 纯视觉片段（无配音）

---

## Segment 分布

| content_type | 数量 | 说明 |
|---|---|---|
| **dialogue** | {len(dialogue_segs)} | 可见说话主体，需口型约束 |
| **voiceover** | {len(voiceover_segs)} | 画外旁白，无出镜要求 |
| **silent_action** | {len(silent_segs)} | 纯视觉，无配音 |

"""
    if speakers:
        report += f"**可见说话主体**: {', '.join(sorted(speakers))}\n\n"
    else:
        report += "**可见说话主体**: 无（所有片段均为 voiceover 或 silent_action）\n\n"

    report += "### Segment 明细\n\n"
    for seg in structured.get("segments", []):
        ct = seg.get("content_type", "?")
        speaker = seg.get("speaker") or ("N/A" if ct != "dialogue" else "?")
        report += """**分镜 {seg.get('id','?')}** | `{ct}` | {seg.get('shot_duration','')}
- speaker: {speaker}
- thai_voiceover: 「{seg.get('thai_voiceover', '(silent)')[:60]}...」
- scene: {seg.get('scene_description','')[:80]}...
"""

    report += "\n---\n\n## 新版分镜提示词（content_type-aware）\n\n"
    if sb_data:
        report += f"```json\n{json.dumps(sb_data, ensure_ascii=False, indent=2)}\n```\n"
    else:
        report += f"```\n{str(storyboard_result)[:2000]}\n```\n"

    report += "\n---\n\n## 新版视频提示词（content_type-aware）\n\n"
    report += f"```\n{video_prompt[:4000]}\n```\n"

    # Key differences analysis
    report += """
---

## 关键差异分析

### 1. dialogue vs voiceover 的处理差异

**Legacy 处理方式**:
所有 Thai 口播全部被送入 TTS 生成配音 → 视频生成时默认按旁白处理 → **画面内不会主动生成说话人物**

**结构化脚本处理方式**:
"""
    if dialogue_segs:
        report += """`dialogue` 片段 ({len(dialogue_segs)} 条):
- 分镜 prompt 会明确要求「可见说话主体出镜、面对镜头、配合口型」
- 视频 prompt 会明确要求「show speaker visibly talking with correct lip-sync」

`voiceover` 片段 ({len(voiceover_segs)} 条):
- 视频 prompt 说明「narration plays over visuals, no visible speaker required」
- 下游不会尝试生成口型/表情约束

"""
    else:
        report += "本样本无 dialogue 片段（全为 voiceover 或 silent_action）\n"

    if silent_segs:
        report += """`silent_action` 片段 ({len(silent_segs)} 条):
- 纯视觉片段，分镜和视频 prompt 均不触发配音/TTS 环节
- 可用于产品特写、氛围镜头、结果展示等

"""

    report += """### 2. 预期效果

| 维度 | Legacy | 结构化脚本 |
|---|---|---|
| 对白主导片段 | 画面无说话人物，默认旁白 | 画面内有可见说话主体，口型/表情自然 |
| 旁白主导片段 | 不变 | 不变 |
| 静默动作片段 | 不变 | 明确无配音，不触发 TTS |
| speaker 可追溯性 | 不可追溯 | 每条 dialogue 明确标注 speaker |

### 3. 潜在风险
- dialogue 误判（把 voiceover 标成 dialogue）：会导致视频尝试生成口型但内容不符
- silent_action 漏标：会导致下游尝试给纯视觉片段加配音，破坏节奏
- 建议：人工审核环节重点检查 content_type 标注准确性

"""
    return report


def run_sample(sample: dict) -> dict:
    """Run the full shadow pipeline for one sample."""
    sample_id = sample["id"]
    print(f"\n{'='*60}")
    print(f"Processing: {sample_id} ({sample['type']})")
    print(f"{'='*60}")

    legacy_script = sample["legacy_script"]
    product_info = sample["product_info"]
    model_info = sample["model_info"]
    duration = sample["video_duration"]

    # ── Step 1: Structure the legacy script ────────────────────────────────
    print(f"[{sample_id}] Step 1: Calling LLM to structure script...")
    struct_prompt = f"""{STRUCTURE_SCRIPT_PROMPT}

## Product info
{product_info}

## Character/model info
{model_info}

## Target video duration
{duration}

## Legacy script to structure
{legacy_script}
"""
    struct_response = call_llm(struct_prompt)
    print(f"[{sample_id}] Structure response: {struct_response[:200]}...")

    structured = parse_json_response(struct_response)
    if structured is None:
        print(f"[{sample_id}] ❌ FAILED to parse structured JSON")
        return {
            "sample_id": sample_id,
            "status": "failed",
            "error": "Failed to parse structured JSON",
            "raw_response": struct_response,
        }

    # ── Step 2: Generate content_type-aware storyboard prompt ──────────────
    print(f"[{sample_id}] Step 2: Generating content_type-aware storyboard...")
    struct_json_str = json.dumps(structured, ensure_ascii=False, indent=2)
    sb_prompt = build_storyboard_prompt(struct_json_str, product_info, model_info, duration)
    sb_response = call_llm(sb_prompt)
    print(f"[{sample_id}] Storyboard response: {sb_response[:200]}...")

    # Parse storyboard
    shots_data = None
    try:
        shots_data = parse_json_response(sb_response)
    except Exception as e:
        print(f"[{sample_id}] Storyboard JSON parse failed: {e}")

    # ── Step 3: Generate content_type-aware video prompt ─────────────────
    print(f"[{sample_id}] Step 3: Generating content_type-aware video prompt...")
    shots_json_str = json.dumps(shots_data, ensure_ascii=False, indent=2) if shots_data else str(sb_response)
    vid_prompt = build_video_prompt(struct_json_str, shots_json_str, duration)
    vid_response = call_llm(vid_prompt)
    print(f"[{sample_id}] Video prompt response: {vid_response[:200]}...")

    # ── Step 4: Generate comparison report ────────────────────────────────
    report = generate_comparison_report(sample, structured, sb_response, vid_response)

    # ── Step 5: Write outputs ──────────────────────────────────────────────
    out_base = OUT_DIR / sample_id
    out_base.mkdir(exist_ok=True)

    with open(out_base / "structured_script.json", "w", encoding="utf-8") as f:
        json.dump(structured, f, ensure_ascii=False, indent=2)

    with open(out_base / "storyboard_shots.json", "w", encoding="utf-8") as f:
        if shots_data:
            json.dump(shots_data, f, ensure_ascii=False, indent=2)
        else:
            f.write(sb_response)

    with open(out_base / "video_prompt.txt", "w", encoding="utf-8") as f:
        f.write(vid_response)

    with open(out_base / "report.md", "w", encoding="utf-8") as f:
        f.write(report)

    print(f"[{sample_id}] ✅ Outputs written to {out_base}/")
    print(f"  - structured_script.json")
    print(f"  - storyboard_shots.json")
    print(f"  - video_prompt.txt")
    print(f"  - report.md")

    return {
        "sample_id": sample_id,
        "status": "success",
        "structured": structured,
        "storyboard": shots_data,
        "video_prompt": vid_response,
        "report": report,
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="结构化脚本影子测试")
    parser.add_argument("--sample", default=None, help="Run only this sample ID (e.g. sample_01)")
    parser.add_argument("--all", action="store_true", help="Run all 6 samples")
    parser.add_argument("--model", default="gemini-2.5-pro-preview-05-13", help="Model to use")
    args = parser.parse_args()

    samples_to_run = []
    if args.sample:
        matched = [s for s in SAMPLE_SCRIPTS if s["id"] == args.sample]
        if not matched:
            print(f"Unknown sample: {args.sample}")
            print(f"Available: {[s['id'] for s in SAMPLE_SCRIPTS]}")
            sys.exit(1)
        samples_to_run = matched
    elif args.all:
        samples_to_run = SAMPLE_SCRIPTS
    else:
        # Default: run first 3 samples (one of each type) for quick check
        print("No --sample or --all specified. Running first 3 samples as quick check.")
        samples_to_run = [s for s in SAMPLE_SCRIPTS if s["id"] in ("sample_01", "sample_03", "sample_06")]

    results = []
    for sample in samples_to_run:
        result = run_sample(sample)
        results.append(result)

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    for r in results:
        status_icon = "✅" if r["status"] == "success" else "❌"
        print(f"  {status_icon} {r['sample_id']}: {r['status']}")

    # Write overall summary report
    summary = f"# 结构化脚本影子测试 — 总报告\n\n"
    summary += f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    summary += f"## 样本运行结果\n\n"
    summary += f"| 样本 | 类型 | 状态 |\n"
    summary += f"|---|---|---|\n"
    type_map = {s["id"]: s["type"] for s in SAMPLE_SCRIPTS}
    for r in results:
        t = type_map.get(r["sample_id"], "?")
        summary += f"| {r['sample_id']} | {t} | {'✅ 成功' if r['status']=='success' else '❌ 失败'} |\n"

    summary += "\n## 下一步\n\n"
    summary += "1. 人工审查每个样本的 `report.md`，确认 content_type 标注是否符合预期\n"
    summary += "2. 特别关注：dialogue 片段的 speaker 是否正确、是否真的需要画面内说话\n"
    summary += "3. 确认无误后，挑 3 条样本（建议 sample_01, sample_03, sample_06）试跑真实分镜/视频\n"
    summary += "4. 验证视频输出中 dialogue 片段是否真的生成了可见说话主体\n"

    with open(OUT_DIR / "SUMMARY.md", "w", encoding="utf-8") as f:
        f.write(summary)
    print(f"\nSummary written to {OUT_DIR / 'SUMMARY.md'}")


if __name__ == "__main__":
    main()
