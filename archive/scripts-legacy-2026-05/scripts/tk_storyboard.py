#!/usr/bin/env python3
"""
环节4：九宫格分镜图生成
用法: python3 tk_storyboard.py <record_id>
从飞书配置表读取模型/提示词 → 下载产品图+模特图 → 生成 shot prompts → 生成九宫格图片 → 上传 → 更新状态
"""
import json, os, sys, time, base64, re, requests
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *

STORYBOARD_CONFIG_RECORD = 'recveizDqA44fi'  # 模型配置表中分镜图生成的记录
WORK_DIR = os.path.join(WORKSPACE, 'storyboard_work')

def download_attachment(token, file_token, save_path):
    """从飞书下载附件"""
    resp = requests.get(
        f'https://open.feishu.cn/open-apis/drive/v1/medias/{file_token}/download',
        headers={'Authorization': f'Bearer {token}'}, timeout=120, stream=True)
    if resp.status_code == 200:
        with open(save_path, 'wb') as f:
            for chunk in resp.iter_content(8192): f.write(chunk)
        return True
    return False

def get_linked_record_id(field_val):
    """从关联字段提取 record_id"""
    if isinstance(field_val, list) and field_val:
        item = field_val[0]
        if isinstance(item, dict):
            return item.get('record_ids', [None])[0] if 'record_ids' in item else item.get('text', '')
        return str(item)
    return None

def main():
    if len(sys.argv) < 2:
        print("用法: python3 tk_storyboard.py <record_id>")
        sys.exit(1)
    record_id = sys.argv[1]
    os.makedirs(WORK_DIR, exist_ok=True)
    token = get_feishu_token()

    try:
        # ---- 1. 读取配置（全部从飞书） ----
        config = get_model_config(token, STORYBOARD_CONFIG_RECORD)
        model_name = config['model']
        api_key = config['api_key']
        api_base = config['api_base']
        prompt_template = config['prompt']

        if not model_name or not api_key:
            raise Exception('飞书配置表缺少模型名称或API Key')

        # ---- 2. 读取任务信息 ----
        task = get_record(token, TABLE_SCRIPT_GEN, record_id)
        script = extract_text(task.get('生成的脚本', ''))
        style = extract_text(task.get('分镜风格', '混合'))
        if not script:
            raise Exception('任务无脚本内容')

        update_record(token, TABLE_SCRIPT_GEN, record_id, {'分镜图状态': '生成中'})

        # ---- 3. 下载产品图 ----
        product_name = extract_text(task.get('选择产品', ''))
        product_record_id = {
            "宠物尿味分解除臭喷雾": "recveikpqWjEiB",
            "宠物皮肤护理喷雾": "recveikpqWDayE",
        }.get(product_name)

        product_path = os.path.join(WORK_DIR, 'product.png')
        if product_record_id:
            prod_fields = get_record(token, TABLE_PRODUCT, product_record_id)
            attachments = prod_fields.get('产品图片', [])
            if attachments and isinstance(attachments, list):
                ft = attachments[0].get('file_token', '')
                if ft:
                    download_attachment(token, ft, product_path)

        # ---- 4. 下载模特图 ----
        model_path = os.path.join(WORK_DIR, 'model.png')
        model_link = task.get('选择模特')
        if model_link:
            # 关联字段结构
            model_record_id = None
            if isinstance(model_link, list) and model_link:
                for item in model_link:
                    if isinstance(item, dict) and 'record_ids' in item:
                        rids = item['record_ids']
                        if rids: model_record_id = rids[0]
            if model_record_id:
                model_fields = get_record(token, TABLE_MODEL, model_record_id)
                attachments = model_fields.get('模特照片', [])
                if attachments and isinstance(attachments, list):
                    ft = attachments[0].get('file_token', '')
                    if ft:
                        download_attachment(token, ft, model_path)

        # 检查素材
        if not os.path.exists(product_path) or os.path.getsize(product_path) < 1000:
            raise Exception('产品图片缺失')

        # ---- 5. Gemini 客户端 ----
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=api_key, http_options={'base_url': api_base})

        # 上传图片
        pf = client.files.upload(file=product_path)
        parts = [types.Part.from_uri(file_uri=pf.uri, mime_type='image/png')]

        if os.path.exists(model_path) and os.path.getsize(model_path) > 1000:
            mf = client.files.upload(file=model_path)
            parts.append(types.Part.from_uri(file_uri=mf.uri, mime_type='image/png'))

        # ---- 6. 生成 shot prompts ----
        full_prompt = prompt_template.replace('{storyboard_style}', style) + "\n\n## 脚本\n" + script
        parts_step1 = parts + [types.Part.from_text(text=full_prompt)]

        resp = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[types.Content(role='user', parts=parts_step1)],
            config=types.GenerateContentConfig(temperature=0.7))

        raw = resp.text
        jm = re.search(r'\{[\s\S]*\}', raw)
        if not jm:
            raise Exception('Gemini 未返回有效 JSON')
        shots_data = json.loads(jm.group())
        shots = shots_data.get('shots', [])
        if len(shots) < 9:
            raise Exception(f'只生成了 {len(shots)} 个分镜，需要9个')

        # ---- 7. 构建 grid prompt ----
        pl = []
        for i, s in enumerate(shots[:9]):
            pl.append(f"Panel {i+1}: {s['prompt_text']}")

        grid_prompt = f"""Create a single 3×3 storyboard grid image in 9:16 vertical portrait format.

REFERENCE IMAGES (attached):
- Image 1 = Product reference photo. The product in EVERY panel MUST be an EXACT visual copy of this reference — same bottle shape, same color, same label text, same logo, same nozzle design. Do NOT invent or alter the product appearance.
- Image 2 = Character reference photo. The character in every panel must match this reference exactly.

CRITICAL: The product is the most important element. Copy its appearance pixel-perfectly from Image 1. If unsure about any detail, refer back to Image 1.

LAYOUT REQUIREMENTS:
- Single image containing exactly 9 panels arranged in a 3×3 grid (3 columns × 3 rows)
- Overall image aspect ratio: 9:16 (vertical portrait, taller than wide)
- Each individual panel aspect ratio: 9:16 (vertical portrait)
- Thin white borders separating all panels
- NO panel numbers, NO text labels, NO numbering on any panel

PANEL DESCRIPTIONS:

{chr(10).join(pl)}"""

        # ---- 8. 生成九宫格图片 ----
        parts_step2 = parts + [types.Part.from_text(text=grid_prompt)]
        image_found = False
        out_path = os.path.join(WORK_DIR, f'{record_id}_storyboard.png')

        for attempt in range(1, 4):
            try:
                r = client.models.generate_content(
                    model=model_name,  # 从飞书配置表读取！
                    contents=[types.Content(role='user', parts=parts_step2)],
                    config=types.GenerateContentConfig(
                        response_modalities=['image', 'text'], temperature=0.2))
                for part in r.candidates[0].content.parts:
                    if hasattr(part, 'inline_data') and part.inline_data and part.inline_data.data:
                        d = part.inline_data.data
                        b = base64.b64decode(d) if isinstance(d, str) else d
                        with open(out_path, 'wb') as f: f.write(b)
                        image_found = True
                        break
                if image_found: break
            except Exception as e:
                if attempt == 3: raise
                time.sleep(5)

        if not image_found:
            raise Exception('图片模型未返回图片（3次重试均失败）')

        # ---- 9. 上传到飞书 ----
        prompts_json = json.dumps(shots_data, ensure_ascii=False, indent=2)

        with open(out_path, 'rb') as f:
            r4 = requests.post('https://open.feishu.cn/open-apis/drive/v1/medias/upload_all',
                headers={'Authorization': f'Bearer {token}'},
                data={'file_name': f'{record_id}_storyboard.png', 'parent_type': 'bitable_file',
                      'parent_node': APP_TOKEN, 'size': str(os.path.getsize(out_path))},
                files={'file': (f'{record_id}_storyboard.png', f, 'image/png')})

        if r4.json().get('code') == 0:
            ft = r4.json()['data']['file_token']
            update_record(token, TABLE_SCRIPT_GEN, record_id, {
                '分镜图': [{'file_token': ft}],
                '分镜图提示词': prompts_json,
                '图片生成提示词': grid_prompt,
                '分镜图状态': '成功',
            })
        else:
            # 附件上传失败，但图片已生成
            update_record(token, TABLE_SCRIPT_GEN, record_id, {
                '分镜图提示词': prompts_json,
                '图片生成提示词': grid_prompt,
                '分镜图状态': '成功（附件上传失败）',
            })

        print(f'✅ 分镜图生成完成: {out_path}')

    except Exception as e:
        try: update_record(token, TABLE_SCRIPT_GEN, record_id, {
            '分镜图状态': '失败', '分镜图提示词': f'错误: {str(e)[:500]}'})
        except: pass
        print(f'❌ {e}')
        sys.exit(1)

if __name__ == '__main__':
    main()
