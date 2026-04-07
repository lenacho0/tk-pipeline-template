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


def strip_non_voiceover_lines(script):
    lines = []
    for line in (script or '').splitlines():
        s = line.strip()
        if s.startswith('口播（中文）') or s.startswith('口播(中文)'):
            continue
        lines.append(line)
    return '\n'.join(lines).strip()


def generate_shots_json(client, parts, prompt_template, style, script):
    storyboard_script = strip_non_voiceover_lines(script)
    prompt_variants = [
        prompt_template.replace('{storyboard_style}', style) + "\n\n## 脚本\n" + storyboard_script,
        (
            "你是短视频电商分镜规划器。请只输出严格 JSON，不要解释，不要 markdown。"
            "必须返回 {\"shots\": [...]}，其中至少包含9个shots。"
            "每个shot至少包含 prompt_text 字段，可附带 scene / product_focus / character_focus。"
            "脚本里的泰文口播是最终视频唯一有效的口播内容；中文仅为翻译参考，不参与分镜规划。"
            f"\n\n风格：{style}\n\n脚本：\n{storyboard_script}"
        )
    ]

    last_error = None
    for idx, prompt in enumerate(prompt_variants, start=1):
        try:
            parts_step1 = parts + [types.Part.from_text(text=prompt)]
            resp = with_retry(
                lambda: client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=[types.Content(role='user', parts=parts_step1)],
                    config=types.GenerateContentConfig(temperature=0.7 if idx == 1 else 0.2)
                ),
                max_attempts=2,
                label=f'storyboard shots generate_content v{idx}'
            )
            raw = getattr(resp, 'text', '') or ''
            shots_data = extract_json_block(raw)
            shots = shots_data.get('shots', [])
            if len(shots) < 9:
                raise Exception(f'只生成了 {len(shots)} 个分镜，需至少9个')
            return shots_data
        except Exception as e:
            last_error = e
            log_event('WARN', 'storyboard shots fallback retry', variant=idx, error=str(e)[:300])
    raise last_error


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


# ── content_type-aware grid prompt (uses formal CL constraints from config table) ──
def build_structured_grid_prompt(shots, style="混合"):
    """
    Builds a grid prompt from structured shots (with content_type, speaker_visible, etc.).
    Injects the full CL constraint suite from the config table:
      CL1: style separation (product always photorealistic)
      CL2: product consistency (highest priority)
      CL3: character consistency
      CL4: no text/subtitles
      CL5: shot diversity
    And respects content_type (dialogue→visible speaker, silent_action→no speaker, voiceover→no speaker).
    """
    style_suffix_map = {
        "混合": (
            ", Strictly Photorealistic model for all product descriptions, "
            "AND strictly Disney/Pixar animation style render for all character and environment descriptions, "
            "3D render, soft volumetric lighting, no text overlay."
        ),
        "全写实": (
            ", all elements strictly photorealistic, lifestyle photography style, "
            "no animation, no cartoon rendering."
        ),
        "全动画": (
            ", 3D Disney/Pixar style for all characters and environments, "
            "product remains strictly Photorealistic, Pixar movie still."
        ),
    }
    style_suffix = style_suffix_map.get(style, style_suffix_map["混合"])

    panel_lines = []
    for i, s in enumerate(shots[:9]):
        prompt_text = s.get("prompt_text", "")
        content_type = s.get("content_type_influenced_by", "")
        speaker_visible = s.get("speaker_visible", False)

        # Inject content_type awareness into prompt suffix
        type_constraint = ""
        if content_type == "dialogue" and speaker_visible:
            type_constraint = (
                " INSTRUCTION: This panel depicts a character SPEAKING DIALOGUE. "
                "The character must have a visible speaking expression (mouth slightly open, engaged). "
                "The speaking character must appear IN THE FRAME, not as a voice-over. "
            )
        elif content_type == "voiceover":
            type_constraint = (
                " INSTRUCTION: This panel is a VOICE-OVER narration. "
                "No character speaking to camera — the speaker is heard but not shown speaking. "
            )
        elif content_type == "silent_action":
            type_constraint = (
                " INSTRUCTION: This panel is SILENT ACTION / atmosphere. "
                "No dialogue, no speaking — pure visual storytelling. "
            )

        panel_lines.append(f"Panel {i+1}: {prompt_text}{type_constraint}{style_suffix}")

    grid_intro = """Create a single 3×3 storyboard grid image in 9:16 vertical portrait format.

REFERENCE IMAGES (attached):
- Image 1 = Product reference photo. The product in EVERY panel MUST be an EXACT visual copy of this reference — same bottle shape, same color, same label text, same logo, same nozzle design. Do NOT invent or alter the product appearance. This is the highest priority.
- Image 2 = Character reference photo. The character in every panel must match this reference exactly — same appearance, same features.

CRITICAL CONSTRAINTS (MUST FOLLOW):
- CL2 (Product Consistency — HIGHEST PRIORITY): The product in EVERY single panel must be pixel-perfect identical to Image 1. Same bottle shape, color, label, logo, nozzle. NEVER deviate.
- CL3 (Character Consistency): The character in every panel must exactly match Image 2. Same face, fur color, build, features.
- CL4 (No Text): Every panel prompt already ends with "no text, no subtitles, no stickers, no watermark, no timecode". Do NOT add any text.
- Shot 9 (CTA): MUST be a close-up of the product on a pure white background — no character, no background, no shadows, professional studio product photography.
- Style suffix is already embedded in each panel prompt — follow it exactly.

LAYOUT REQUIREMENTS:
- Single image containing exactly 9 panels arranged in a 3×3 grid (3 columns × 3 rows)
- Overall image aspect ratio: 9:16 (vertical portrait, taller than wide)
- Each individual panel aspect ratio: 9:16 (vertical portrait)
- Thin white borders separating all panels
- NO panel numbers, NO text labels, NO numbering on any panel

PANEL DESCRIPTIONS (follow each panel's style suffix exactly):

"""

    return grid_intro + "\n".join(panel_lines)


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

        product_value = get_task_product_value(task)
        product_record_id = get_product_record_id(token, product_value)

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

        # ── Step 1: Try structured shots JSON from script_gen output ──────────────
        raw_structured = task.get('结构化脚本JSON', '')
        structured_shots = None
        if raw_structured:
            try:
                parsed = json.loads(raw_structured)
                shots = parsed.get('shots', [])
                # Validate: must have prompt_text and content_type fields
                if shots and all(s.get('prompt_text') for s in shots[:9]):
                    structured_shots = shots[:9]
                    log_event('INFO', 'using structured shots from script_gen', record_id=record_id, shot_count=len(structured_shots))
                    print(f'  使用结构化脚本shots (共{len(structured_shots)}条)')
                else:
                    log_event('WARN', 'structured shots JSON invalid or missing prompt_text', record_id=record_id)
            except (json.JSONDecodeError, Exception) as e:
                log_event('WARN', 'structured shots JSON parse failed, falling back to LLM generation', record_id=record_id, error=str(e)[:300])

        # ── Step 2: Fallback — LLM generate shots from plain script ──────────────
        if not structured_shots:
            print(f'  无结构化JSON，使用LLM生成shots...')
            shots_data = generate_shots_json(client, parts, prompt_template, style, script)
            structured_shots = shots_data.get('shots', [])

        shots = structured_shots[:9]
        # ── Step 3: Build grid prompt — structured or plain ───────────────────────
        has_content_type = any(s.get('content_type_influenced_by') for s in shots)
        if has_content_type:
            grid_prompt = build_structured_grid_prompt(shots, style=style)
            print(f'  使用结构化grid_prompt (含content_type约束)')
        else:
            grid_prompt = build_grid_prompt(shots)
            print(f'  使用普通grid_prompt (fallback)')

        out_path = os.path.join(task_dir, f'{record_id}_storyboard.png')
        render_storyboard_image(client, model_name, parts, grid_prompt, out_path)

        # Always write back shots used (structured or LLM-generated)
        shots_data_for_writeback = {'shots': shots}
        prompts_json = json.dumps(shots_data_for_writeback, ensure_ascii=False, indent=2)
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
        payload = build_error_payload(e, stage='generate_storyboard_grid')
        err = payload['message']
        log_event('ERROR', 'storyboard task failed', record_id=record_id, error=err, error_code=payload['error_code'], retryable=payload['retryable'])
        try:
            safe_update_record(token, TABLE_SCRIPT_GEN, record_id, {
                '分镜图状态': '失败',
                '分镜图提示词': f"错误[{payload['error_code']}]: {err}"
            })
        except Exception as write_err:
            log_event('ERROR', 'storyboard failure writeback failed', record_id=record_id, error=str(write_err)[:500])
        print(f"ERROR_CODE={payload['error_code']} RETRYABLE={str(payload['retryable']).lower()} MESSAGE={err}")
        sys.exit(1)


if __name__ == '__main__':
    main()
