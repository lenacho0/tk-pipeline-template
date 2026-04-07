#!/usr/bin/env python3
"""
环节3：产品脚本生成
用法: python3 tk_script_gen.py <record_id>
从飞书配置表读取提示词 → 填充产品/模特信息 → 读取参考脚本（来自前面对爆款视频的分析结果）→ 筛选/提纯爆款策略 → Gemini 生成 → 写回 → 更新状态
"""
import json, os, sys, time, requests, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *
from pet_reference_schema import normalize_payload

MAX_REFERENCE_SCRIPTS = 5
MAX_REFERENCE_TOTAL_CHARS = 7000
HANDWRITTEN_SOURCE_VALUES = {'手写脚本', '手动填写', '手写', 'manual', 'manual_script'}
HANDWRITTEN_ORGANIZE_STAGE_NAME = '手写脚本整理提示词'
HANDWRITTEN_REWRITE_STAGE_NAME = '手写脚本改写提示词'
DEFAULT_HANDWRITTEN_ORGANIZE_PROMPT = """
你是电商短视频脚本整理助手。

任务：把用户手写脚本整理成“可直接给九宫格分镜图生成环节使用”的标准化脚本。

当前产品信息：
{product_info}

模特信息：
{model_info}

目标视频时长：
{video_duration}

用户手写脚本：
{raw_script}

要求：
1. 保留用户原意，不要改成另一条新脚本。
2. 只做轻量整理与补齐，让结构更清晰、更适合后续分镜生成。
3. 输出内容尽量包含：开场Hook、场景/痛点、产品出场、动作/演示、结果/效果、结尾CTA。
4. 如果原文里已有镜头感，请保留；如果没有，只补最少量必要的场景/动作描述。
5. 如果脚本同时包含泰文口播与中文翻译，必须明确：泰文口播是最终视频唯一可用于配音/朗读/音频生成的正式脚本；中文仅用于翻译、人工阅读与检查，绝不能用于视频生成、语音合成或最终口播。
6. 不要输出JSON，不要解释，不要加前言后记，只输出最终脚本文本。
""".strip()
DEFAULT_HANDWRITTEN_REWRITE_PROMPT = """
你是电商短视频脚本压缩改写助手。

任务：当手写脚本与目标视频时长冲突时，以目标视频时长为准，对脚本做“保真压缩改写”。

当前产品信息：
{product_info}

模特信息：
{model_info}

目标视频时长：
{video_duration}

待改写脚本：
{raw_script}

改写要求：
1. 以目标视频时长为最高优先级。
2. 最大限度保留原脚本结构、段落顺序、核心卖点、场景设定、情绪基调与CTA。
3. 优先通过压缩、合并、删减重复内容来完成时长对齐。
4. 不要另起炉灶，不要重写成另一条全新脚本。
5. 如果原文已经有明确镜头或口播结构，尽量保留。
6. 如果脚本同时包含泰文口播与中文翻译，必须明确：泰文口播是最终视频唯一可用于配音/朗读/音频生成的正式脚本；中文仅用于翻译、人工阅读与检查，绝不能用于视频生成、语音合成或最终口播。
7. 不要输出JSON，不要解释，不要加前言后记，只输出改写后的最终脚本文本。
""".strip()


def trim_text(text, limit):
    text = (text or '').strip()
    return text[:limit]


def try_update_optional_fields(token, table_id, record_id, fields):
    try:
        safe_update_record(token, table_id, record_id, fields)
        return True
    except Exception as e:
        log_event('WARN', 'optional field write skipped', record_id=record_id, error=str(e)[:300], fields=list(fields.keys()))
        return False


def get_product_info(token, product_value):
    record_id, fields = get_product_record(token, product_value)
    if not record_id or not fields:
        return None
    return {
        '产品名称-th': extract_text(fields.get('产品名称-th', '')),
        '产品规格': extract_text(fields.get('产品规格', '')),
        '核心卖点': extract_text(fields.get('核心卖点', '')),
        '使用场景': extract_text(fields.get('使用场景', '')),
        '目标用户': extract_text(fields.get('目标用户', '')),
    }


def get_model_info(token, task_fields):
    model_link = task_fields.get('选择模特')
    if not model_link:
        return ''
    model_infos = []
    if isinstance(model_link, list):
        for item in model_link:
            if isinstance(item, dict) and 'record_ids' in item:
                for rid in item['record_ids']:
                    try:
                        mf = safe_get_record(token, TABLE_MODEL, rid)
                        info = f"- 名称: {extract_text(mf.get('模特名称',''))}"
                        info += f", 类型: {extract_text(mf.get('模特类型',''))}"
                        info += f", 品种: {extract_text(mf.get('品种',''))}"
                        info += f", 毛色/肤色: {extract_text(mf.get('毛色/肤色',''))}"
                        info += f", 性别: {extract_text(mf.get('性别',''))}"
                        info += f", 外观描述: {extract_text(mf.get('外观描述',''))}"
                        model_infos.append(info)
                    except Exception:
                        pass
    return '\n'.join(model_infos) if model_infos else '无指定模特'


def parse_analysis_record(text):
    text = (text or '').strip()
    summary = None
    detailed = text
    if text.startswith('【结构化摘要】'):
        match = re.search(r'\{[\s\S]*?\}', text)
        if match:
            try:
                summary = json.loads(match.group())
                tail = text[match.end():].strip()
                if tail.startswith('【详细分析】'):
                    tail = tail[len('【详细分析】'):].strip()
                detailed = tail
            except Exception:
                summary = None
    return summary, detailed


def score_reference(product_info, summary, fields):
    score = 0
    sales = int(fields.get('销量', 0) or 0)
    play = int(fields.get('播放量', 0) or 0)
    score += min(sales // 10, 50)
    score += min(play // 10000, 20)

    product_text = ' '.join([product_info.get('核心卖点', ''), product_info.get('使用场景', ''), product_info.get('目标用户', '')])
    if summary:
        fit_products = summary.get('fit_products', '') or ''
        viral_reason = summary.get('viral_reason', '') or ''
        trigger_type = summary.get('trigger_type', '') or ''
        for kw in ['除臭', '护理', '喷雾', '宠物', '异味', '清洁', '场景']:
            if kw in fit_products or kw in viral_reason:
                score += 8
            if kw in product_text and kw in fit_products:
                score += 10
        if any(k in trigger_type for k in ['痛点直出', '效果对比', '场景带入']):
            score += 12
    return score


def get_reference_scripts(token, product_info):
    records = safe_list_records(token, TABLE_ANALYSIS)
    candidates = []
    for rec in records:
        f = rec.get('fields', {})
        status = extract_text(f.get('分析状态', ''))
        if '成功' not in status and '已完成' not in status:
            continue
        script = extract_text(f.get('脚本结构', ''))
        if not script:
            continue
        summary, detailed = parse_analysis_record(script)
        score = score_reference(product_info, summary, f)
        candidates.append({
            'record_id': rec['record_id'],
            '视频ID': extract_text(f.get('视频ID', '')),
            '达人': extract_text(f.get('达人昵称', '')),
            '播放量': f.get('播放量', 0),
            '销量': f.get('销量', 0),
            '视频描述': trim_text(extract_text(f.get('视频描述', '')), 180),
            'summary': summary,
            'detailed': trim_text(detailed, 1200),
            'score': score,
        })

    candidates.sort(key=lambda x: (x['score'], x['销量'] or 0, x['播放量'] or 0), reverse=True)

    selected = []
    used_triggers = set()
    for item in candidates:
        trigger = ''
        if item['summary']:
            trigger = (item['summary'].get('trigger_type', '') or '').strip()
        if trigger and trigger not in used_triggers:
            selected.append(item)
            used_triggers.add(trigger)
        elif len(selected) < 2:
            selected.append(item)
        if len(selected) >= MAX_REFERENCE_SCRIPTS:
            break

    if len(selected) < min(3, len(candidates)):
        for item in candidates:
            if item in selected:
                continue
            selected.append(item)
            if len(selected) >= min(MAX_REFERENCE_SCRIPTS, len(candidates)):
                break

    return selected


def build_strategy_prompt(references, product_info):
    ref_blocks = []
    total = 0
    for i, ref in enumerate(references):
        if ref['summary']:
            block = f"\n## 参考{i+1}\n{json.dumps(ref['summary'], ensure_ascii=False, indent=2)}\n"
        else:
            block = f"\n## 参考{i+1}\n达人:{ref['达人']} 播放:{ref['播放量']} 销量:{ref['销量']}\n描述:{ref['视频描述']}\n详细分析:{ref['detailed']}\n"
        if total + len(block) > MAX_REFERENCE_TOTAL_CHARS:
            break
        ref_blocks.append(block)
        total += len(block)

    product_text = json.dumps(product_info, ensure_ascii=False, indent=2)
    return f"""
你是一个爆款带货视频策略提炼师。
请基于以下多个爆款视频分析摘要，提炼出“适合当前产品”的爆款底层逻辑。

当前产品信息：
{product_text}

参考分析：
{''.join(ref_blocks)}

请只输出 JSON：
{{
  "best_fit_patterns": ["最适合当前产品的表达套路1", "套路2", "套路3"],
  "avoid_patterns": ["不适合当前产品的套路1", "套路2"],
  "common_hooks": ["高适配 hook 1", "hook 2", "hook 3"],
  "common_scene_order": ["问题出现", "放大痛点", "产品出场", "使用过程", "效果反馈", "CTA"],
  "selling_logic": ["为什么这些套路对当前产品有效1", "原因2", "原因3"],
  "cta_logic": "最适合这个产品的 CTA 方式",
  "tone_style": "建议语气风格"
}}
""".strip()


def generate_strategy_summary(client, model_name, references, product_info):
    prompt = build_strategy_prompt(references, product_info)
    response = with_retry(
        lambda: client.models.generate_content(model=model_name, contents=[prompt]),
        max_attempts=3,
        label='gemini strategy summarize'
    )
    text = getattr(response, 'text', '') or ''
    match = re.search(r'\{[\s\S]*\}', text)
    if not match:
        raise Exception('策略提纯未返回有效 JSON')
    return json.loads(match.group())


def build_script_generation_prompt(prompt_template, product_info, model_info, video_duration, strategy_summary, references):
    product_text = '\n'.join(f'- **{k}**: {v}' for k, v in product_info.items())
    strategy_text = json.dumps(strategy_summary, ensure_ascii=False, indent=2)
    reference_lines = []
    for i, ref in enumerate(references[:5]):
        reference_lines.append(f"参考{i+1}: 达人={ref['达人']} 播放={ref['播放量']} 销量={ref['销量']} trigger={ref['summary'].get('trigger_type','') if ref['summary'] else ''}")
    ref_text = '\n'.join(reference_lines)

    base = prompt_template
    base = base.replace('{product_info}', product_text)
    base = base.replace('{model_info}', model_info)
    base = base.replace('{video_duration}', video_duration)
    if '{reference_scripts}' in base:
        base = base.replace('{reference_scripts}', ref_text)

    tail = f"""

## 爆款策略摘要（必须优先遵守）
{strategy_text}

## 已选参考样本（仅作来源说明，不要照抄）
{ref_text}

要求：
1. 不要直接拼贴参考视频原文案
2. 必须优先借鉴“底层表达逻辑”，而不是表层台词
3. 必须适配当前产品卖点、目标用户、使用场景
4. 输出一条可执行的带货脚本
5. 脚本要明确：Hook、痛点推进、产品出场、效果证明、CTA
6. 最终输出脚本中，口播部分只允许保留泰文口播；不要输出 `口播（中文）`、`口播(中文)`、中文台词翻译、双语对照口播，也不要把中文台词混入任何最终脚本正文。
7. 中文如果需要，仅允许作为模型内部理解，不允许出现在最终输出给下游的视频脚本文本中。
8. 输出结果必须是“可直接给分镜图生成和视频生成使用”的单语终稿，默认语言为泰语口播。
{STRUCTURED_OUTPUT_PROMPT_SUFFIX}
"""
    return base + tail + STRUCTURED_OUTPUT_PROMPT_SUFFIX


def get_pet_reference_payload(token, reference_record_id):
    if not reference_record_id:
        return None
    fields = safe_get_record(token, TABLE_PET_REFERENCE_V1, reference_record_id)
    if not fields.get('是否可用于脚本生成'):
        raise Exception('参考视频未勾选为可用于脚本生成')
    raw = extract_text(fields.get('完整JSON分析结果', '')).strip()
    if not raw:
        raise Exception('参考视频缺少完整JSON分析结果')
    return normalize_payload(json.loads(raw))


def build_pet_reference_script_prompt(prompt_template, product_info, model_info, video_duration, reference_payload):
    product_text = '\n'.join(f'- **{k}**: {v}' for k, v in product_info.items())
    ref_text = json.dumps(reference_payload, ensure_ascii=False, indent=2)
    base = prompt_template
    base = base.replace('{product_info}', product_text)
    base = base.replace('{model_info}', model_info)
    base = base.replace('{video_duration}', video_duration)
    if '{reference_scripts}' in base:
        base = base.replace('{reference_scripts}', '使用宠物拟人参考JSON，不使用旧爆款脚本文本参考')
    tail = f"""

## 宠物拟人参考视频结构化分析（必须优先遵守）
{ref_text}

要求：
1. 你参考的是这条视频的叙事视角、转化策略、Hook机制、卖点推进顺序和可复用模板，不是照抄原视频台词。
2. 必须围绕当前产品重新写原创脚本。
3. 如果参考视频策略与当前产品不完全匹配，可以保留其有效机制并重构中段表达。
4. 必须保持宠物拟人视角成立；宠物拟人不等于必须萌系，可根据参考JSON中的策略走恐吓/焦虑/问题暴露/对比/温情等路线。
5. 最终输出脚本中，口播部分只允许保留泰文口播；不要输出 `口播（中文）`、`口播(中文)`、中文台词翻译、双语对照口播，也不要把中文台词混入任何最终脚本正文。
6. 中文如果需要，仅允许作为模型内部理解，不允许出现在最终输出给下游的视频脚本文本中。
7. 输出结果必须是可直接给分镜图生成和视频生成使用的单语终稿，默认语言为泰语口播。
"""
    return base + tail


def get_script_source(fields):
    return extract_text(fields.get('脚本来源', '')).strip()


def get_handwritten_script(fields):
    return extract_text(fields.get('手写脚本内容', '')).strip()


def is_handwritten_mode(fields):
    return get_script_source(fields) in HANDWRITTEN_SOURCE_VALUES


def fill_prompt_template(template, product_info, model_info, video_duration, raw_script):
    product_text = '\n'.join(f'- {k}: {v}' for k, v in product_info.items() if v) or '无'
    prompt = template
    prompt = prompt.replace('{product_info}', product_text)
    prompt = prompt.replace('{model_info}', model_info or '无指定模特')
    prompt = prompt.replace('{video_duration}', video_duration or '25s')
    prompt = prompt.replace('{raw_script}', raw_script)
    return prompt


def find_config_record_by_stage(token, stage_name):
    records = safe_list_records(token, TABLE_CONFIG)
    for rec in records:
        fields = rec.get('fields', {})
        if extract_text(fields.get('环节', '')).strip() == stage_name:
            return rec
    return None


def get_prompt_record_fields(token, stage_name, fallback_record_fields=None):
    rec = find_config_record_by_stage(token, stage_name)
    if rec and rec.get('fields'):
        return rec.get('fields', {}), f'stage_record:{stage_name}'
    return fallback_record_fields or {}, f'fallback_script_gen_record:{stage_name}'


def get_handwritten_organize_prompt(token, fallback_record_fields):
    fields, source = get_prompt_record_fields(token, HANDWRITTEN_ORGANIZE_STAGE_NAME, fallback_record_fields)
    value = extract_text(fields.get('提示词', '')).strip() or extract_text(fields.get('手写脚本整理提示词', '')).strip()
    prompt = value or DEFAULT_HANDWRITTEN_ORGANIZE_PROMPT
    # Remove the "不要输出JSON" line since we now require structured JSON output
    lines = [l for l in prompt.splitlines() if '不要输出JSON' not in l and '不要输出 json' not in l.lower()]
    prompt = '\n'.join(lines).strip()
    return prompt + '\n' + STRUCTURED_OUTPUT_PROMPT_SUFFIX, source


def get_handwritten_rewrite_prompt(token, fallback_record_fields):
    fields, source = get_prompt_record_fields(token, HANDWRITTEN_REWRITE_STAGE_NAME, fallback_record_fields)
    value = extract_text(fields.get('提示词', '')).strip() or extract_text(fields.get('手写脚本改写提示词', '')).strip()
    prompt = value or DEFAULT_HANDWRITTEN_REWRITE_PROMPT
    lines = [l for l in prompt.splitlines() if '不要输出JSON' not in l and '不要输出 json' not in l.lower()]
    prompt = '\n'.join(lines).strip()
    return prompt + '\n' + STRUCTURED_OUTPUT_PROMPT_SUFFIX, source


def contains_duration_conflict(raw_script, video_duration):
    script = (raw_script or '').lower()
    target = (video_duration or '').lower().strip()
    if not script or not target:
        return False
    normalized_target = target.replace('秒', 's').replace(' ', '')
    duration_tokens = set(re.findall(r'\b\d+\s*s\b|\d+秒', script))
    if not duration_tokens:
        return False
    return normalized_target not in {token.replace(' ', '') for token in duration_tokens}


def strip_chinese_voiceover_lines(script):
    lines = []
    for line in (script or '').splitlines():
        s = line.strip()
        if s.startswith('口播（中文）') or s.startswith('口播(中文)'):
            continue
        lines.append(line)
    return '\n'.join(lines).strip()


def run_text_prompt(client, model_name, prompt, label):
    response = with_retry(
        lambda: client.models.generate_content(model=model_name, contents=[prompt]),
        max_attempts=3,
        label=label
    )
    result = getattr(response, 'text', '') or ''
    if not result.strip():
        raise Exception('Gemini 返回空脚本')
    return result


# ── Structured script output ────────────────────────────────────────────────

STRUCTURED_OUTPUT_PROMPT_SUFFIX = """

---
## 附加要求：同时输出结构化 JSON

除了上面的脚本正文，还必须在同一个回复的末尾追加输出以下 JSON 结构（放在 ```json 代码块中）。

**JSON 格式要求（每条分镜必须包含以下所有字段）：**
```json
{
  "shots": [
    {
      "shot_number": "分镜 1",
      "content_type": "dialogue",
      "speaker": "MoMo",
      "speaker_visible": true,
      "thai_text": "口播泰文原文",
      "visual_description": "画面描述",
      "prompt_text": "Close-up, Disney/Pixar animated MoMo with slightly open mouth, speaking..."
    },
    ...共 9 条...
  ]
}
```

**字段说明：**
- `shot_number`: 分镜序号（分镜 1 ~ 分镜 9）
- `content_type`: `dialogue`（有台词对白）/ `voiceover`（旁白配音无画面）/ `silent_action`（纯动作无台词）
- `speaker`: 谁在说。dialogue 时填角色名（MoMo/模特名），voiceover 填"旁白"，silent_action 填空字符串 `""`
- `speaker_visible`: 是否要在画面内看到说话主体。dialogue 且 speaker 出现在画面时为 `true`，voiceover/silent_action 恒为 `false`
- `thai_text`: 泰文口播原文（silent_action 时为 `""`）
- `visual_description`: 画面内容文字描述（不含镜头技术参数）
- `prompt_text`: 该分镜的画面生成提示词，供后续分镜图生成使用。请包含：镜头角度、角色/产品外观、场景、氛围光影。

**content_type 判断规则：**
- 有具体台词 + 说话主体在画面内 → `dialogue`（speaker_visible=true）
- 有具体台词但说话主体不在画面内 → `voiceover`（speaker_visible=false）
- 无台词，纯动作/产品/氛围展示 → `silent_action`（speaker_visible=false）

**注意：** JSON 代码块必须放在整个回复的最后，不能出现在其他位置。
"""


def extract_json_block(text):
    """Extract JSON from ```json ... ``` block."""
    text = text or ''
    m = re.search(r'```json\s*([\s\S]*?)\s*```', text)
    if m:
        return m.group(1).strip()
    m2 = re.search(r'\{[\s\S]*\}', text)
    if m2:
        return m2.group()
    return text.strip()


def parse_structured_shots(text):
    """
    Extract structured shots JSON from a Gemini response.
    Returns (structured_shots_dict, plain_text_without_json).
    """
    raw_json = extract_json_block(text)
    try:
        parsed = json.loads(raw_json)
        shots = parsed.get('shots', [])
        if shots:
            # Build plain text: everything before the first ```json block
            json_start = text.find('```json')
            plain_text = text[:json_start].strip() if json_start != -1 else text.strip()
            return parsed, plain_text
    except (json.JSONDecodeError, Exception):
        pass
    # Fallback: no valid JSON found, return original text as plain
    return None, text


def main():
    if len(sys.argv) < 2:
        print("用法: python3 tk_script_gen.py <record_id>")
        sys.exit(1)
    record_id = sys.argv[1]
    token = get_feishu_token()

    try:
        log_event('INFO', 'script generation task start', record_id=record_id)
        config = get_model_config(token, CONFIG_RECORDS['script_gen'])
        script_gen_config_fields = safe_get_record(token, TABLE_CONFIG, CONFIG_RECORDS['script_gen'])
        model_name = config['model'] or 'gemini-2.5-flash'
        api_key = config['api_key']
        api_base = config['api_base'] or 'https://aihubmix.com/gemini'
        prompt_template = config['prompt']

        if not prompt_template:
            raise Exception('飞书配置表无产品脚本生成提示词')

        fields = safe_get_record(token, TABLE_SCRIPT_GEN, record_id)
        product_value = get_task_product_value(fields)
        product_name = extract_text(product_value)
        video_duration = extract_text(fields.get('视频时长', '25s'))
        if not product_name and not extract_linked_record_ids(product_value):
            raise Exception('未选择产品')

        product_info = get_product_info(token, product_value)
        if not product_info:
            raise Exception(f'找不到产品: {product_name or product_value}（请检查产品信息表是否存在该产品，或选择产品字段是否已关联到产品信息表）')

        model_info = get_model_info(token, fields)

        safe_update_record(token, TABLE_SCRIPT_GEN, record_id, {
            '生成状态': '生成中',
            'record_id': record_id,
        })
        try_update_optional_fields(token, TABLE_SCRIPT_GEN, record_id, {**{k: v for k, v in product_info.items()}})

        if not api_key:
            raise Exception('飞书配置表缺少 API Key')

        from google import genai
        client = genai.Client(api_key=api_key, http_options={'base_url': api_base})

        if is_handwritten_mode(fields):
            raw_script = get_handwritten_script(fields)
            if not raw_script:
                raise Exception('脚本来源为手写脚本，但手写脚本内容为空')

            organize_template, organize_source = get_handwritten_organize_prompt(token, script_gen_config_fields)
            organize_prompt = fill_prompt_template(
                organize_template,
                product_info, model_info, video_duration, raw_script
            )
            raw_response = run_text_prompt(client, model_name, organize_prompt, 'gemini handwritten script organize')
            structured_shots, raw_response = parse_structured_shots(raw_response)

            rewrite_used = False
            rewrite_source = None
            if contains_duration_conflict(raw_script, video_duration):
                rewrite_template, rewrite_source = get_handwritten_rewrite_prompt(token, script_gen_config_fields)
                rewrite_prompt = fill_prompt_template(
                    rewrite_template,
                    product_info, model_info, video_duration, raw_response
                )
                raw_response = run_text_prompt(client, model_name, rewrite_prompt, 'gemini handwritten script rewrite')
                structured_shots, raw_response = parse_structured_shots(raw_response)
                rewrite_used = True

            references = []
            log_event(
                'INFO', 'handwritten script path used',
                record_id=record_id,
                organize_source=organize_source,
                rewrite_source=rewrite_source,
                rewrite_used=rewrite_used,
                video_duration=video_duration
            )
        else:
            generation_mode = extract_text(fields.get('脚本生成模式', '')).strip()
            pet_reference_record_id = extract_text(fields.get('参考视频记录ID', '')).strip()
            if generation_mode == '宠物拟人参考生成' and pet_reference_record_id:
                reference_payload = get_pet_reference_payload(token, pet_reference_record_id)
                prompt = build_pet_reference_script_prompt(
                    prompt_template, product_info, model_info, video_duration, reference_payload
                )
                response = with_retry(
                    lambda: client.models.generate_content(model=model_name, contents=[prompt]),
                    max_attempts=3,
                    label='gemini pet reference script generate_content'
                )
                raw_response = getattr(response, 'text', '') or ''
                if not raw_response.strip():
                    raise Exception('Gemini 返回空脚本')
                structured_shots, raw_response = parse_structured_shots(raw_response)
                references = []
            else:
                references = get_reference_scripts(token, product_info)
                if not references:
                    raise Exception('没有可用的爆款视频分析结果，无法生成产品脚本')

                strategy_summary = generate_strategy_summary(client, model_name, references, product_info)
                prompt = build_script_generation_prompt(
                    prompt_template, product_info, model_info, video_duration, strategy_summary, references
                )

                response = with_retry(
                    lambda: client.models.generate_content(model=model_name, contents=[prompt]),
                    max_attempts=3,
                    label='gemini script generate_content'
                )
                raw_response = getattr(response, 'text', '') or ''
                if not raw_response.strip():
                    raise Exception('Gemini 返回空脚本')
                structured_shots, raw_response = parse_structured_shots(raw_response)

        # Strip Chinese voiceover annotations from plain text (JSON block already extracted)
        plain_script = strip_chinese_voiceover_lines(raw_response)

        current_fields = safe_get_record(token, TABLE_SCRIPT_GEN, record_id)
        storyboard_status = extract_text(current_fields.get('分镜图状态', '')).strip()
        update_fields = {
            '生成的脚本': plain_script[:10000],
            '生成状态': '成功',
            'record_id': record_id,
        }
        if structured_shots:
            update_fields['结构化脚本JSON'] = json.dumps(structured_shots, ensure_ascii=False, indent=2)
        if storyboard_status not in ('生成中', '待执行'):
            update_fields['分镜图状态'] = '待执行'
        safe_update_record(token, TABLE_SCRIPT_GEN, record_id, update_fields)

        log_event(
            'INFO', 'script generation task success',
            record_id=record_id,
            result_len=len(plain_script),
            has_structured_shots=bool(structured_shots),
            reference_count=len(references),
            selected_refs=[r['record_id'] for r in references[:5]]
        )
        print(f'✅ 脚本生成完成 ({len(plain_script)}字)' + (' [含结构化JSON]' if structured_shots else ''))

    except Exception as e:
        payload = build_error_payload(e, stage='generate_product_script')
        err = payload['message']
        log_event('ERROR', 'script generation task failed', record_id=record_id, error=err, error_code=payload['error_code'], retryable=payload['retryable'])
        try:
            safe_update_record(token, TABLE_SCRIPT_GEN, record_id, {
                '生成状态': '失败',
                '生成的脚本': f"错误[{payload['error_code']}]: {err}"
            })
        except Exception as write_err:
            log_event('ERROR', 'script generation failure writeback failed', record_id=record_id, error=str(write_err)[:500])
        print(f"ERROR_CODE={payload['error_code']} RETRYABLE={str(payload['retryable']).lower()} MESSAGE={err}")
        sys.exit(1)


if __name__ == '__main__':
    main()
