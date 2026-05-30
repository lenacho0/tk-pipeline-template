#!/usr/bin/env python3
"""
环节3：产品脚本生成
用法: python3 tk_script_gen.py <record_id>
从飞书配置表读取提示词 → 填充产品/模特信息 → 读取参考脚本 → Gemini 生成 → 写回 → 更新状态
"""
import json, os, sys, time, requests
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *

SCRIPT_GEN_CONFIG_RECORD = 'recveizDqAB9Xo'  # 模型配置表中产品脚本生成的记录

PRODUCT_MAP = {
    "宠物尿味分解除臭喷雾": "recveikpqWjEiB",
    "宠物皮肤护理喷雾": "recveikpqWDayE",
}

def get_product_info(token, product_name):
    record_id = PRODUCT_MAP.get(product_name)
    if not record_id: return None
    fields = get_record(token, TABLE_PRODUCT, record_id)
    return {
        '产品名称-th': extract_text(fields.get('产品名称-th', '')),
        '产品规格': extract_text(fields.get('产品规格', '')),
        '核心卖点': extract_text(fields.get('核心卖点', '')),
        '使用场景': extract_text(fields.get('使用场景', '')),
        '目标用户': extract_text(fields.get('目标用户', '')),
    }

def get_model_info(token, task_fields):
    """读取关联的模特信息"""
    model_link = task_fields.get('选择模特')
    if not model_link:
        return ''
    model_infos = []
    if isinstance(model_link, list):
        for item in model_link:
            if isinstance(item, dict) and 'record_ids' in item:
                for rid in item['record_ids']:
                    try:
                        mf = get_record(token, TABLE_MODEL, rid)
                        info = f"- 名称: {extract_text(mf.get('模特名称',''))}"
                        info += f", 类型: {extract_text(mf.get('模特类型',''))}"
                        info += f", 品种: {extract_text(mf.get('品种',''))}"
                        info += f", 毛色/肤色: {extract_text(mf.get('毛色/肤色',''))}"
                        info += f", 性别: {extract_text(mf.get('性别',''))}"
                        info += f", 外观描述: {extract_text(mf.get('外观描述',''))}"
                        model_infos.append(info)
                    except: pass
    return '\n'.join(model_infos) if model_infos else '无指定模特'

def get_reference_scripts(token):
    records = list_records(token, TABLE_ANALYSIS)
    scripts = []
    for rec in records:
        f = rec.get('fields', {})
        status = extract_text(f.get('分析状态', ''))
        if '成功' in status or '已完成' in status:
            script = extract_text(f.get('脚本结构', ''))
            if script:
                scripts.append({
                    '视频ID': extract_text(f.get('视频ID', '')),
                    '达人': extract_text(f.get('达人昵称', '')),
                    '播放量': f.get('播放量', 0),
                    '销售量': f.get('销售量', 0),
                    '视频描述': extract_text(f.get('视频描述', ''))[:200],
                    '脚本分析': script[:3000],
                })
    return sorted(scripts, key=lambda x: x.get('销售量', 0) or 0, reverse=True)

def main():
    if len(sys.argv) < 2:
        print("用法: python3 tk_script_gen.py <record_id>")
        sys.exit(1)
    record_id = sys.argv[1]
    token = get_feishu_token()

    try:
        # ---- 1. 读取配置（提示词、模型）从飞书 ----
        config = get_model_config(token, SCRIPT_GEN_CONFIG_RECORD)
        model_name = config['model'] or 'gemini-2.5-flash'
        api_key = config['api_key']
        api_base = config['api_base']
        prompt_template = config['prompt']

        if not prompt_template:
            raise Exception('飞书配置表无产品脚本生成提示词')

        # ---- 2. 读取任务信息 ----
        fields = get_record(token, TABLE_SCRIPT_GEN, record_id)
        product_name = extract_text(fields.get('选择产品', ''))
        video_duration = extract_text(fields.get('视频时长', '25s'))
        if not product_name:
            raise Exception('未选择产品')

        # 填充产品信息
        product_info = get_product_info(token, product_name)
        if not product_info:
            raise Exception(f'找不到产品: {product_name}')

        # 读取模特信息
        model_info = get_model_info(token, fields)

        update_record(token, TABLE_SCRIPT_GEN, record_id, {
            **{k: v for k, v in product_info.items()},
            '生成状态': '生成中',
        })

        # ---- 3. 读取参考脚本 ----
        scripts = get_reference_scripts(token)
        top_scripts = scripts[:10]

        product_text = '\n'.join(f'- **{k}**: {v}' for k, v in product_info.items())
        ref_text = ''
        for i, s in enumerate(top_scripts):
            ref_text += f"\n### 参考视频 {i+1}: {s['达人']} (播放:{s['播放量']}, 销售:{s['销售量']})\n"
            ref_text += f"描述: {s['视频描述']}\n"
            ref_text += f"脚本分析: {s['脚本分析'][:2000]}\n"

        # ---- 4. 填充提示词模板 ----
        prompt = prompt_template.replace('{product_info}', product_text)
        prompt = prompt.replace('{model_info}', model_info)
        prompt = prompt.replace('{video_duration}', video_duration)
        prompt = prompt.replace('{reference_scripts}', ref_text[:15000])

        # ---- 5. Gemini 调用（模型从飞书配置读取）----
        if not api_key:
            cfg = load_openclaw_config()
            for pk, pv in cfg.get('models', {}).get('providers', {}).items():
                if 'aihubmix' in pv.get('baseUrl', ''):
                    api_key = pv['apiKey']
                    api_base = api_base or pv['baseUrl']
                    break
        if not api_key:
            raise Exception('找不到 API Key')

        client = get_gemini_client(api_key, api_base or 'https://aihubmix.com/gemini')

        response = client.models.generate_content(model=model_name, contents=[prompt])
        result = response.text

        # 保存脚本到本地文件（防丢失）+ 写入飞书（内容写到字段，不是占位符）
        script_text = result[:10000]
        script_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'generated_scripts')
        os.makedirs(script_dir, exist_ok=True)
        script_file = os.path.join(script_dir, f'{record_id}_script.txt')
        with open(script_file, 'w', encoding='utf-8') as f:
            f.write(script_text)
        # 分两步写：先写状态（轻量），再写脚本内容（较重），降低单次写入数据量
        update_record(token, TABLE_SCRIPT_GEN, record_id, {'生成状态': '成功'})
        update_record(token, TABLE_SCRIPT_GEN, record_id, {
            '生成的脚本': script_text,  # 写实际内容，不是占位符
            '参考视频数': len(top_scripts),
        })
        print(f'✅ 脚本生成完成 ({len(result)}字)，已保存到 {script_file}')

    except Exception as e:
        try: update_record(token, TABLE_SCRIPT_GEN, record_id, {
            '生成状态': '失败', '生成的脚本': f'错误: {str(e)[:500]}'})
        except: pass
        print(f'❌ {e}')
        sys.exit(1)

if __name__ == '__main__':
    main()
