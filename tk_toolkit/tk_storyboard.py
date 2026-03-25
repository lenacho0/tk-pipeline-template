#!/usr/bin/env python3
"""
环节4：九宫格分镜图生成
用法: python3 tk_storyboard.py <record_id>
从飞书配置表读取模型/提示词 → 下载产品图+模特图 → 生成 shot prompts → 生成九宫格图片 → 上传 → 更新状态
"""
import json, os, sys, time, base64, re, requests
from google.genai import types
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *

BASE_WORK_DIR = os.path.join(WORKSPACE, 'storyboard_work')


def ensure_task_dir(record_id):
    task_dir = os.path.join(BASE_WORK_DIR, record_id)
    os.makedirs(task_dir, exist_ok=True)
    return task_dir


def download_attachment(token, file_token, save_path):
    resp = requests.get(
        f'https://open.feishu.cn/open-apis/drive/v1/medias/{file_token}/download',
        headers={'Authorization': f'Bearer {token}'}, timeout=120, stream=True)
    if resp.status_code == 200:
        with open(save_path, 'wb') as f:
            for chunk in resp.iter_content(8192):
                f.write(chunk)
        return True
    return False


def safe_download_attachment(token, file_token, save_path):
    return with_retry(
        lambda: _download_or_raise(token, file_token, save_path),
        max_attempts=3,
        label='feishu attachment download'
    )


def _download_or_raise(token, file_token, save_path):
    ok = download_attachment(token, file_token, save_path)
    if not ok:
        raise Exception(f'附件下载失败: {file_token}')
    return True


def extract_json_block(raw_text):
    raw_text = (raw_text or '').strip()
    if not raw_text:
        raise Exception('模型返回空文本，无法提取 JSON')
    match = re.search(r'\{[\s\S]*\}', raw_text)
    if not match:
        raise Exception('Gemini 未返回有效 JSON')
    try:
        return json.loads(match.group())
    except Exception as e:
        raise Exception(f'JSON 解析失败: {e}')


def upload_image_to_feishu(token, file_path, file_name):
    with open(file_path, 'rb') as f:
        resp = requests.post(
            'https://open.feishu.cn/open-apis/drive/v1/medias/upload_all',
            headers={'Authorization': f'Bearer {token}'},
            data={
                'file_name': file_name,
                'parent_type': 'bitable_file',
                'parent_node': APP_TOKEN,
                'size': str(os.path.getsize(file_path))
            },
            files={'file': (file_name, f, 'image/png')},
            timeout=120
        )
    data = resp.json()
    if data.get('code') != 0:
        raise Exception(f"飞书上传失败: {data.get('msg')}")
    return data['data']['file_token']


def generate_shots_json(client, parts, prompt_template, style, script):
    full_prompt = prompt_template.replace('{storyboard_style}', style) + "\n\n## 脚本\n" + script
    parts_step1 = parts + [types.Part.from_text(text=full_prompt)]
    resp = with_retry(
        lambda: client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[types.Content(role='user', parts=parts_step1)],
            config=types.GenerateContentConfig(temperature=0.7)
        ),
        max_attempts=3,
        label='storyboard shots generate_content'
    )
    raw = getattr(resp, 'text', '') or ''
    shots_data = extract_json_block(raw)
    shots = shots_data.get('shots', [])
    if len(shots) < 9:
        raise Exception(f'只生成了 {len(shots)} 个分镜，需至少9个')
    return shots_data


def build_grid_prompt(shots):
    panel_lines = []
    for i, s in enumerate(shots[:9]):
        panel_lines.append(f"Panel {i+1}: {s['prompt_text']}")

    return f"""Create a single 3×3 storyboard grid image in 9:16 vertical portrait format.

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

{chr(10).join(panel_lines)}"""


def render_storyboard_image(client, model_name, parts, grid_prompt, out_path):
    parts_step2 = parts + [types.Part.from_text(text=grid_prompt)]

    for attempt in range(1, 4):
        try:
            r = client.models.generate_content(
                model=model_name,
                contents=[types.Content(role='user', parts=parts_step2)],
                config=types.GenerateContentConfig(
                    response_modalities=['image', 'text'],
                    temperature=0.2
                )
            )
            for part in r.candidates[0].content.parts:
                if hasattr(part, 'inline_data') and part.inline_data and part.inline_data.data:
                    data = part.inline_data.data
                    binary = base64.b64decode(data) if isinstance(data, str) else data
                    with open(out_path, 'wb') as f:
                        f.write(binary)
                    if os.path.getsize(out_path) < 1000:
                        raise Exception('返回了图片，但文件太小')
                    return out_path
            raise Exception('图片模型未返回图片内容')
        except Exception as e:
            if attempt >= 3:
                raise
            log_event('WARN', 'storyboard image generation retry', attempt=attempt, error=str(e)[:300])
            time.sleep(5)


def main():
    if len(sys.argv) < 2:
        print("用法: python3 tk_storyboard.py <record_id>")
        sys.exit(1)
    record_id = sys.argv[1]
    task_dir = ensure_task_dir(record_id)
    token = get_feishu_token()

    try:
        log_event('INFO', 'storyboard task start', record_id=record_id)
        config = get_model_config(token, CONFIG_RECORDS['storyboard'])
        model_name = config['model']
        api_key = config['api_key']
        api_base = config['api_base']
        prompt_template = config['prompt']

        if not model_name or not api_key:
            raise Exception('飞书配置表缺少模型名称或API Key')

        task = safe_get_record(token, TABLE_SCRIPT_GEN, record_id)
        script = extract_text(task.get('生成的脚本', ''))
        style = extract_text(task.get('分镜风格', '混合'))
        if not script:
            raise Exception('任务无脚本内容')

        safe_update_record(token, TABLE_SCRIPT_GEN, record_id, {'分镜图状态': '生成中'})

        product_name = extract_text(task.get('选择产品', ''))
        product_record_id = PRODUCT_MAP.get(product_name)

        product_path = os.path.join(task_dir, 'product.png')
        if product_record_id and not (os.path.exists(product_path) and os.path.getsize(product_path) > 10000):
            prod_fields = safe_get_record(token, TABLE_PRODUCT, product_record_id)
            attachments = prod_fields.get('产品图片', [])
            if attachments and isinstance(attachments, list):
                file_token = attachments[0].get('file_token', '')
                if file_token:
                    safe_download_attachment(token, file_token, product_path)

        model_path = os.path.join(task_dir, 'model.png')
        model_link = task.get('选择模特')
        if model_link:
            model_record_id = None
            if isinstance(model_link, list) and model_link:
                for item in model_link:
                    if isinstance(item, dict) and 'record_ids' in item:
                        record_ids = item['record_ids']
                        if record_ids:
                            model_record_id = record_ids[0]
                            break
            if model_record_id and not (os.path.exists(model_path) and os.path.getsize(model_path) > 10000):
                model_fields = safe_get_record(token, TABLE_MODEL, model_record_id)
                attachments = model_fields.get('模特照片', [])
                if attachments and isinstance(attachments, list):
                    file_token = attachments[0].get('file_token', '')
                    if file_token:
                        safe_download_attachment(token, file_token, model_path)

        if not os.path.exists(product_path) or os.path.getsize(product_path) < 1000:
            raise Exception('产品图片缺失')

        from google import genai
        client = genai.Client(api_key=api_key, http_options={'base_url': api_base})

        product_file = with_retry(lambda: client.files.upload(file=product_path), max_attempts=3, label='upload product image')
        parts = [types.Part.from_uri(file_uri=product_file.uri, mime_type='image/png')]
        model_file = None

        if os.path.exists(model_path) and os.path.getsize(model_path) > 1000:
            model_file = with_retry(lambda: client.files.upload(file=model_path), max_attempts=3, label='upload model image')
            parts.append(types.Part.from_uri(file_uri=model_file.uri, mime_type='image/png'))

        shots_data = generate_shots_json(client, parts, prompt_template, style, script)
        shots = shots_data.get('shots', [])
        grid_prompt = build_grid_prompt(shots)

        out_path = os.path.join(task_dir, f'{record_id}_storyboard.png')
        render_storyboard_image(client, model_name, parts, grid_prompt, out_path)

        prompts_json = json.dumps(shots_data, ensure_ascii=False, indent=2)
        file_token = with_retry(
            lambda: upload_image_to_feishu(token, out_path, f'{record_id}_storyboard.png'),
            max_attempts=3,
            label='upload storyboard image to feishu'
        )

        safe_update_record(token, TABLE_SCRIPT_GEN, record_id, {
            '分镜图': [{'file_token': file_token}],
            '分镜图提示词': prompts_json,
            '图片生成提示词': grid_prompt,
            '分镜图状态': '成功',
        })
        log_event('INFO', 'storyboard task success', record_id=record_id, shots=len(shots))
        print(f'✅ 分镜图生成完成: {out_path}')

    except Exception as e:
        err = str(e)[:500]
        log_event('ERROR', 'storyboard task failed', record_id=record_id, error=err)
        try:
            safe_update_record(token, TABLE_SCRIPT_GEN, record_id, {
                '分镜图状态': '失败',
                '分镜图提示词': f'错误: {err}'
            })
        except Exception as write_err:
            log_event('ERROR', 'storyboard failure writeback failed', record_id=record_id, error=str(write_err)[:500])
        print(f'❌ {e}')
        sys.exit(1)


if __name__ == '__main__':
    main()
