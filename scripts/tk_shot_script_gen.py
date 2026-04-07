#!/usr/bin/env python3
"""
独立流程：逐镜头脚本生成
用法: python3 tk_shot_script_gen.py <record_id>

说明：
- 不影响现有产品脚本生成 / 九宫格分镜图流程
- 从独立的「逐镜头脚本生成表」读取任务
- 输出可读脚本 + shots_json
- 后续由逐镜头分镜图脚本拆 shot 入表并逐条出图
"""
import json, os, sys, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *
from tk_script_gen import get_product_info, get_model_info, get_reference_scripts, generate_strategy_summary
from tk_shot_storyboard import cleanup_shots_by_source, split_shots

MAX_STRATEGY_REFERENCES = 3
MAX_VISUAL_BIBLE_CHARS = 2500
MAX_STRATEGY_JSON_CHARS = 3500

DEFAULT_SHOT_PROMPT = """
你是一个短视频逐镜头脚本导演。
请基于给定产品信息、模特信息、参考爆款策略，输出一个“逐镜头脚本”。

输出格式必须严格如下：
第一行：<<<SHOTS_JSON>>>
第二部分：输出一个合法 JSON 对象，格式：
{
  "shots": [
    {
      "shot_no": 1,
      "duration": "0-3s",
      "narration": "旁白或字幕",
      "visual": "画面内容",
      "scene": "场景",
      "product_focus": "该镜头产品重点",
      "character_focus": "人物表现重点"
    }
  ]
}
第三行：<<<SCRIPT>>>
第四部分：输出完整可读版逐镜头脚本文案。

要求：
- shots 至少 5 个，最多 9 个
- 每个 shot 都要有明确画面目标
- 必须适合后续逐镜头生成分镜图
- 默认单主角叙事：整组 shot 必须是同一个主角，禁止每个镜头切换不同人物设定
- 除非脚本明确不可避免，否则不要新增清晰可辨识的配角；其他人只能作为弱化背景存在
- 除非剧情明确切场，否则保持主场景、世界观、光线和色调连续
- product_focus / character_focus / scene 都要服务于后续单镜头稳定出图，描述具体，不要抽象空话
- 不要输出任何多余解释
""".strip()


def extract_shots_payload(raw_text):
    raw_text = (raw_text or '').strip()
    if not raw_text:
        raise Exception('逐镜头脚本结果为空')

    if '<<<SHOTS_JSON>>>' in raw_text and '<<<SCRIPT>>>' in raw_text:
        payload = raw_text.split('<<<SHOTS_JSON>>>', 1)[1]
        json_part, script_part = payload.split('<<<SCRIPT>>>', 1)
        match = re.search(r'\{[\s\S]*\}', json_part)
        if not match:
            raise Exception('未找到 shots JSON')
        data = json.loads(match.group())
        return data, script_part.strip()

    match = re.search(r'\{[\s\S]*\}', raw_text)
    if not match:
        raise Exception('未找到可解析 JSON')
    data = json.loads(match.group())
    return data, raw_text


def compress_references_for_strategy(references):
    packed = []
    total = 0
    for ref in references[:MAX_STRATEGY_REFERENCES]:
        summary = ref.get('summary') or {}
        item = {
            'video_id': ref.get('视频ID', ''),
            'sales': ref.get('销量', 0),
            'play_count': ref.get('播放量', 0),
            'trigger_type': summary.get('trigger_type', ''),
            'fit_products': summary.get('fit_products', ''),
            'viral_reason': summary.get('viral_reason', ''),
            'reusable_pattern': summary.get('reusable_pattern', ''),
        }
        encoded = json.dumps(item, ensure_ascii=False)
        if total + len(encoded) > MAX_STRATEGY_JSON_CHARS:
            break
        packed.append(item)
        total += len(encoded)
    return packed


def safe_strategy_summary(client, model_name, references, product_info):
    try:
        light_refs = []
        for item in compress_references_for_strategy(references):
            light_refs.append({
                'record_id': item.get('video_id', ''),
                '视频ID': item.get('video_id', ''),
                '达人': '',
                '播放量': item.get('play_count', 0),
                '销量': item.get('sales', 0),
                'summary': {
                    'trigger_type': item.get('trigger_type', ''),
                    'fit_products': item.get('fit_products', ''),
                    'viral_reason': item.get('viral_reason', ''),
                    'reusable_pattern': item.get('reusable_pattern', ''),
                },
                'detailed': '',
                'score': 0,
            })
        return generate_strategy_summary(client, model_name, light_refs or references[:MAX_STRATEGY_REFERENCES], product_info)
    except Exception as e:
        log_event('WARN', 'shot script strategy fallback enabled', error=str(e)[:300])
        fallback_refs = compress_references_for_strategy(references)
        return {
            'best_fit_patterns': [x.get('reusable_pattern', '') for x in fallback_refs if x.get('reusable_pattern')][:3],
            'avoid_patterns': [],
            'common_hooks': [x.get('trigger_type', '') for x in fallback_refs if x.get('trigger_type')][:3],
            'common_scene_order': ['问题出现', '放大痛点', '产品出场', '使用过程', '效果反馈', 'CTA'],
            'selling_logic': [x.get('viral_reason', '') for x in fallback_refs if x.get('viral_reason')][:3],
            'cta_logic': '结尾明确引导下单或立即尝试',
            'tone_style': '短视频电商带货风格，节奏快，表达直接'
        }


def build_visual_bible(task_fields, product_info, model_info, strategy_summary):
    product_name = extract_text(get_task_product_value(task_fields))
    storyboard_style = extract_text(task_fields.get('分镜风格', ''))
    script_style = extract_text(task_fields.get('脚本风格', ''))
    return json.dumps({
        'product_name': product_name,
        'product_anchor': product_info,
        'character_anchor': model_info,
        'storyboard_style': storyboard_style,
        'script_style': script_style,
        'consistency_rules': [
            '所有分镜默认同一主角，不允许更换人物身份、脸型、体态、服装逻辑',
            '除非剧情强制要求，否则不要新增清晰可辨识的新配角；背景人物只能弱化存在，不能抢主体',
            '所有分镜保持统一产品外观、颜色、标签、logo、瓶型和比例',
            '所有分镜保持统一风格、灯光倾向、色调和环境世界观',
            '除非脚本明确说明，不要改变主场景类型，只做镜头切换和景别变化',
            '即使镜头节奏变化，也要保持同一条短视频内部的人物、产品、空间逻辑连续'
        ],
        'strategy_summary': strategy_summary,
    }, ensure_ascii=False, indent=2)[:MAX_VISUAL_BIBLE_CHARS]


def build_prompt(task_fields, product_info, model_info, strategy_summary, prompt_template=''):
    product_name = extract_text(task_fields.get('选择产品', ''))
    script_style = extract_text(task_fields.get('脚本风格', ''))
    storyboard_style = extract_text(task_fields.get('分镜风格', ''))
    platform = extract_text(task_fields.get('目标平台', 'TikTok'))
    duration = extract_text(task_fields.get('视频时长', '25s'))
    shot_count = extract_text(task_fields.get('镜头数量', '6'))

    style_extra = ''
    if storyboard_style == '全动画':
        style_extra = """
## 动画风格强约束
- “全动画”在本任务中明确指：Disney / Pixar 方向的 3D 商业动画风格
- 默认采用 3D 动画电影质感、立体角色、体积光、电影化布光、细腻材质、具有情绪表现力的角色表演
- 不要输出 2D动画、扁平插画、手绘卡通、平面矢量风、低幼 flash 风
- 所有镜头的 visual / scene / character_focus 都要服务于 Disney / Pixar 向 3D 动画短片质感
- 如果出现动物角色，角色应具备 Pixar 式可爱、夸张、清晰情绪表达，但仍需保持商业广告画面的干净与高级感
""".strip()

    base = (prompt_template or DEFAULT_SHOT_PROMPT).strip()

    return f"""
{base}

## 产品
产品名：{product_name}
产品信息：{json.dumps(product_info, ensure_ascii=False)}

## 模特（必须保持所有 shot 主角一致）
{model_info}

## 目标
平台：{platform}
时长：{duration}
镜头数量：{shot_count}
脚本风格：{script_style}
分镜风格：{storyboard_style}

## 爆款策略摘要
{json.dumps(strategy_summary, ensure_ascii=False, indent=2)}

{style_extra}

## 强约束（如果上方基础模板没有覆盖，请额外遵守）
1. 所有镜头默认使用同一主角，不允许每个镜头更换人物设定
2. 除非剧情必须，不要新增清晰可辨识配角；如果需要他人出现，只能作为模糊背景或陪衬
3. 所有镜头必须保持统一分镜风格：{storyboard_style}
4. 如果分镜风格=全动画，则默认理解为 Disney / Pixar 向 3D 动画风格，不允许擅自改写成 2D 动画
5. character_focus 必须体现同一主角在不同镜头中的连续性
6. scene 必须尽量围绕同一空间体系连续变化；若切场，需让切场理由非常明确
7. visual 和 scene 必须为后续单镜头出图服务，描述清晰，不要抽象空话
8. narration、visual、scene、character_focus 之间不能互相打架，不能一边写单人一边画面又变双人主戏
""".strip()


def main():
    if len(sys.argv) < 2:
        print('用法: python3 tk_shot_script_gen.py <record_id>')
        sys.exit(1)
    record_id = sys.argv[1]
    token = get_feishu_token()

    if not TABLE_SHOT_SCRIPT_GEN:
        raise Exception('当前配置文件尚未配置 shot_script_gen 表 ID')

    try:
        log_event('INFO', 'shot script task start', record_id=record_id)
        config = get_model_config(token, CONFIG_RECORDS['shot_script_gen'])
        model_name = config['model'] or 'gemini-2.5-flash'
        api_key = config['api_key']
        api_base = config['api_base'] or 'https://aihubmix.com/gemini'

        fields = safe_get_record(token, TABLE_SHOT_SCRIPT_GEN, record_id)
        product_value = get_task_product_value(fields)
        product_name = extract_text(product_value)
        if not product_name and not extract_linked_record_ids(product_value):
            raise Exception('未选择产品')

        product_info = get_product_info(token, product_value)
        if not product_info:
            raise Exception(f'找不到产品: {product_name or product_value}')

        model_info = get_model_info(token, fields)
        safe_update_record(token, TABLE_SHOT_SCRIPT_GEN, record_id, {'生成状态': '生成中'})

        references = get_reference_scripts(token, product_info)
        if not references:
            raise Exception('没有可用的爆款视频分析结果，无法生成逐镜头脚本')
        if not api_key:
            raise Exception('飞书配置表缺少 API Key')

        from google import genai
        client = genai.Client(api_key=api_key, http_options={'base_url': api_base})
        strategy_summary = safe_strategy_summary(client, model_name, references, product_info)
        prompt_template = config.get('prompt', '') or DEFAULT_SHOT_PROMPT
        prompt = build_prompt(fields, product_info, model_info, strategy_summary, prompt_template)

        response = with_retry(
            lambda: client.models.generate_content(model=model_name, contents=[prompt]),
            max_attempts=3,
            label='gemini shot script generate_content'
        )
        raw_text = getattr(response, 'text', '') or ''
        shots_data, readable_script = extract_shots_payload(raw_text)
        shots = shots_data.get('shots', [])
        if not isinstance(shots, list) or not shots:
            raise Exception('shots 为空')

        visual_bible = build_visual_bible(fields, product_info, model_info, strategy_summary)
        safe_update_record(token, TABLE_SHOT_SCRIPT_GEN, record_id, {
            '逐镜头脚本': readable_script[:10000],
            '分镜头结构JSON': json.dumps(shots_data, ensure_ascii=False, indent=2)[:10000],
            '总镜头数': len(shots),
            '参考来源': '自动从002爆款视频脚本分析筛选',
            '参考分析记录IDs': ', '.join([r['record_id'] for r in references[:5]])[:10000],
            '参考视频ID列表': ', '.join([r['视频ID'] for r in references[:5] if r.get('视频ID')])[:10000],
            '参考样本数': len(references[:5]),
            '参考策略摘要': json.dumps(strategy_summary, ensure_ascii=False, indent=2)[:10000],
            '全局视觉锚点': visual_bible,
            '生成状态': '成功',
        })

        deleted = cleanup_shots_by_source(token, record_id)
        log_event('INFO', 'old shot records cleaned', record_id=record_id, deleted=deleted)
        split_shots(token, record_id)

        log_event('INFO', 'shot script task success', record_id=record_id, shot_count=len(shots), split_rebuilt=True)
        print(f'✅ 逐镜头脚本生成完成并已重建shot记录 ({len(shots)}个镜头)')

    except Exception as e:
        payload = build_error_payload(e, stage='generate_shot_script')
        err = payload['message']
        log_event('ERROR', 'shot script task failed', record_id=record_id, error=err, error_code=payload['error_code'], retryable=payload['retryable'])
        try:
            safe_update_record(token, TABLE_SHOT_SCRIPT_GEN, record_id, {
                '生成状态': '失败',
                '逐镜头脚本': f"错误[{payload['error_code']}]: {err}"
            })
        except Exception:
            pass
        print(f"ERROR_CODE={payload['error_code']} RETRYABLE={str(payload['retryable']).lower()} MESSAGE={err}")
        sys.exit(1)


if __name__ == '__main__':
    main()
