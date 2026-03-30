#!/usr/bin/env python3
"""
环节3：产品脚本生成
用法: python3 tk_script_gen.py <record_id>
从飞书配置表读取提示词 → 填充产品/模特信息 → 读取参考脚本（来自前面对爆款视频的分析结果）→ 筛选/提纯爆款策略 → Gemini 生成 → 写回 → 更新状态
"""
import json, os, sys, time, requests, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *

MAX_REFERENCE_SCRIPTS = 5
MAX_REFERENCE_TOTAL_CHARS = 7000


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
"""
    return base + tail


def main():
    if len(sys.argv) < 2:
        print("用法: python3 tk_script_gen.py <record_id>")
        sys.exit(1)
    record_id = sys.argv[1]
    token = get_feishu_token()

    try:
        log_event('INFO', 'script generation task start', record_id=record_id)
        config = get_model_config(token, CONFIG_RECORDS['script_gen'])
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

        references = get_reference_scripts(token, product_info)
        if not references:
            raise Exception('没有可用的爆款视频分析结果，无法生成产品脚本')

        if not api_key:
            raise Exception('飞书配置表缺少 API Key')

        from google import genai
        client = genai.Client(api_key=api_key, http_options={'base_url': api_base})

        strategy_summary = generate_strategy_summary(client, model_name, references, product_info)
        prompt = build_script_generation_prompt(
            prompt_template, product_info, model_info, video_duration, strategy_summary, references
        )

        response = with_retry(
            lambda: client.models.generate_content(model=model_name, contents=[prompt]),
            max_attempts=3,
            label='gemini script generate_content'
        )
        result = getattr(response, 'text', '') or ''
        if not result.strip():
            raise Exception('Gemini 返回空脚本')

        current_fields = safe_get_record(token, TABLE_SCRIPT_GEN, record_id)
        storyboard_status = extract_text(current_fields.get('分镜图状态', '')).strip()
        update_fields = {
            '生成的脚本': result[:10000],
            '生成状态': '成功',
            'record_id': record_id,
        }
        if storyboard_status not in ('生成中', '待执行'):
            update_fields['分镜图状态'] = '待执行'
        safe_update_record(token, TABLE_SCRIPT_GEN, record_id, update_fields)

        log_event(
            'INFO', 'script generation task success',
            record_id=record_id,
            result_len=len(result),
            reference_count=len(references),
            selected_refs=[r['record_id'] for r in references[:5]]
        )
        print(f'✅ 脚本生成完成 ({len(result)}字)')

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
