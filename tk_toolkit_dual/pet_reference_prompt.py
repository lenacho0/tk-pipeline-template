#!/usr/bin/env python3
import json

def build_pet_reference_prompt(source_url='', normalized_url='', duration_sec=0, file_size_mb=0):
    return f'''你是一个专门分析「宠物拟人视角带货视频」的结构化视频分析器。
你的任务不是写观后感，也不是总结成普通文案，而是从视频中提取可复用的宠物拟人叙事机制、转化策略、内容结构和可迁移模板，并且严格输出 JSON。

请分析输入视频，判断它是否属于“宠物拟人视角带货视频”，并输出一个结构化 JSON，供后续脚本生成系统直接消费。

重要原则：
1. 宠物拟人是一种叙事视角，不是一种固定风格；不要把“宠物拟人”简单等同于“萌宠”。
2. 如果视频开头有虫害、病灶、脏污、血腥、恶心、恐吓等强刺激画面，也要正常分析其转化机制。
3. 缺失信息允许为空，不要编造。
4. 最终输出必须是单个合法 JSON 对象，不要输出 markdown、不要使用代码块。

固定元信息（若视频本身无法提供，请沿用以下值）：
- source_url: {source_url}
- normalized_url: {normalized_url}
- video_duration_sec: {duration_sec}
- file_size_mb: {file_size_mb}
- analysis_model: gemini-3.1-pro-preview

输出 JSON Schema（必须遵守）：
{{
  "schema_version": "pet_reference_v1",
  "analysis_status": "success",
  "meta": {{
    "source_url": "",
    "normalized_url": "",
    "platform": "",
    "analysis_model": "gemini-3.1-pro-preview",
    "analyzed_at": "",
    "video_duration_sec": 0,
    "file_size_mb": 0
  }},
  "pet_anthro": {{
    "is_pet_anthro": true,
    "confidence": 0,
    "pet_type": "",
    "narrative_subject": "",
    "anthro_intensity": "",
    "role_summary": "",
    "pet_anthro_mechanism": ""
  }},
  "conversion": {{
    "core_strategy": "",
    "hook_type": "",
    "visual_intensity": "",
    "sensitive_visual_types": [],
    "product_integration_method": "",
    "cta_summary": ""
  }},
  "content": {{
    "summary": "",
    "opening_hook_analysis": "",
    "timeline_breakdown": [],
    "voiceover_structure": "",
    "rhythm_analysis": "",
    "selling_points_flow": "",
    "closed_loop_analysis": ""
  }},
  "reuse": {{
    "reusable_structure_template": "",
    "reusable_opening_template": "",
    "reusable_role_template": "",
    "reusable_cta_template": "",
    "fit_products": [],
    "unfit_products": [],
    "avoid_copying_notes": ""
  }}
}}

枚举要求：
- platform: TikTok | Douyin | Instagram | YouTube Shorts | Xiaohongshu | Unknown
- pet_type: cat | dog | multiple_pets | other | unknown
- narrative_subject: pet_first_person | owner_speaks_for_pet | pet_owner_dialogue | third_person_observation | mixed | unknown
- anthro_intensity: low | medium | high | unknown
- core_strategy: cute_seed | fear_appeal | anxiety_warning | pain_point_amplification | before_after_comparison | emotional_resonance | professional_education | urgent_reminder | case_testimony | product_recommendation | comedic_contrast | social_showoff | mixed | unknown
- hook_type: shock | disgust_impact | pain_complaint | comedic_contrast | suspense | warm_emotion | result_first | problem_exposure | expert_warning | question_hook | unknown
- visual_intensity: low | medium | high | unknown
- sensitive_visual_types: parasites | skin_issue | ear_dirt | oral_dirt | blood_wound | vomit_or_excretion | other | none
- product_integration_method: pet_expresses_need | owner_solves_problem | before_after_demonstration | risk_problem_driven | pet_recommendation | natural_scene_integration | professional_endorsement | mixed | unknown

timeline_breakdown 中每段格式：
{{
  "start_sec": 0,
  "end_sec": 0,
  "purpose": "",
  "visuals": "",
  "voiceover": ""
}}

只输出 JSON。'''


def build_pet_reference_translation_prompt(json_payload):
    """把英文结构化 JSON 翻译成中文保持结构版，供人工阅读。"""
    return f'''你是一个专业的电商视频分析翻译助手。你的任务是把一份英文结构化 JSON 的所有字段值翻译成中文，同时严格保持原始 JSON 的结构、key、层级和枚举值不变。

翻译原则：
1. 只翻译 value，不改变任何 key
2. 保持 JSON 结构完全一致（嵌套对象、数组全部保留）
3. 枚举类 value（如 hook_type、core_strategy、pet_type、narrative_subject 等）翻译成对应的中文自然语言表达，不要保留英文原文
4. 非枚举的自由文本也翻译成通顺中文
5. timeline_breakdown 数组中每个对象的每个字段都翻译
6. 不要省略任何字段，不要增删任何 key
7. 最终输出必须是一个合法的单个 JSON 对象，不要加 markdown 代码块、不要解释、不要前言后记

待翻译的 JSON：
{json.dumps(json_payload, ensure_ascii=False)}

输出翻译后的 JSON（只输出 JSON，不要其他任何内容）：'''
