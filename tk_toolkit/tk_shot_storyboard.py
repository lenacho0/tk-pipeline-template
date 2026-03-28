#!/usr/bin/env python3
"""
独立流程：逐镜头分镜图生成
用法:
1) python3 tk_shot_storyboard.py split <shot_script_record_id>
   - 将逐镜头脚本生成表中的 shots_json 拆分写入逐镜头分镜图表
2) python3 tk_shot_storyboard.py render <shot_storyboard_record_id>
   - 对单条 shot 记录生成 1 张分镜图
"""
import json, os, sys, time, base64
from google.genai import types
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *
from tk_storyboard import ensure_task_dir, safe_download_attachment, upload_image_to_feishu


_TABLE_FIELDS_CACHE = {}


def get_table_field_names(token, table_id):
    cache_key = f"{APP_TOKEN}:{table_id}"
    if cache_key in _TABLE_FIELDS_CACHE:
        return _TABLE_FIELDS_CACHE[cache_key]
    field_names = set()
    page_token = None
    while True:
        url = f'https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/fields?page_size=100'
        if page_token:
            url += f'&page_token={page_token}'
        data = safe_request('get', url, headers=feishu_headers(token), timeout=30, max_attempts=3, acceptable_codes=(0,))
        for item in data.get('data', {}).get('items', []):
            name = item.get('field_name')
            if name:
                field_names.add(name)
        if not data.get('data', {}).get('has_more'):
            break
        page_token = data.get('data', {}).get('page_token')
    _TABLE_FIELDS_CACHE[cache_key] = field_names
    return field_names


def filter_existing_fields(token, table_id, fields):
    existing = get_table_field_names(token, table_id)
    return {k: v for k, v in fields.items() if k in existing}


def cleanup_shots_by_source(token, source_record_id):
    items = safe_list_records(token, TABLE_SHOT_STORYBOARD)
    to_delete = []
    for rec in items:
        fields = rec.get('fields', {})
        if extract_text(fields.get('源逐镜头脚本记录ID', '')) == source_record_id:
            to_delete.append(rec['record_id'])

    deleted = 0
    for rid in to_delete:
        safe_request(
            'delete',
            f'https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_SHOT_STORYBOARD}/records/{rid}',
            headers=feishu_headers(token),
            timeout=30,
            max_attempts=3,
            acceptable_codes=(0,)
        )
        deleted += 1
    return deleted


def split_shots(token, source_record_id):
    if not TABLE_SHOT_SCRIPT_GEN or not TABLE_SHOT_STORYBOARD:
        raise Exception('config.json 尚未配置 shot_script_gen / shot_storyboard 表 ID')

    fields = safe_get_record(token, TABLE_SHOT_SCRIPT_GEN, source_record_id)
    raw = extract_text(fields.get('分镜头结构JSON', ''))
    if not raw:
        raise Exception('分镜头结构JSON 为空')
    data = json.loads(raw)
    shots = data.get('shots', [])
    if not shots:
        raise Exception('shots 为空')

    product_name = extract_text(get_task_product_value(fields))
    source_video_id = extract_text(fields.get('源视频ID', ''))
    records = []
    for idx, shot in enumerate(shots, start=1):
        records.append({'fields': {
            '源逐镜头脚本记录ID': source_record_id,
            '分镜序号': idx,
            '总分镜数': len(shots),
            '产品名': product_name,
            '源视频ID': source_video_id,
            '分镜文案': shot.get('narration', ''),
            '分镜说明': shot.get('visual', ''),
            '画面描述': shot.get('visual', ''),
            '人物描述': shot.get('character_focus', ''),
            '场景描述': shot.get('scene', ''),
            '产品焦点': shot.get('product_focus', ''),
            '提示词': '',
            '生成状态': '待生成',
        }})

    created = 0
    for i in range(0, len(records), 10):
        batch = records[i:i+10]
        safe_request(
            'post',
            f'https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_SHOT_STORYBOARD}/records/batch_create',
            headers=feishu_headers(token),
            json={'records': batch},
            timeout=30,
            max_attempts=3,
            acceptable_codes=(0,)
        )
        created += len(batch)
    safe_update_record(token, TABLE_SHOT_SCRIPT_GEN, source_record_id, {'生成状态': '已拆分'})
    log_event('INFO', 'shot storyboard split success', record_id=source_record_id, created=created)
    print(f'✅ 已拆分 {created} 条 shot 记录')


def _resolve_linked_record_id(link_val):
    if isinstance(link_val, list):
        for item in link_val:
            if isinstance(item, dict) and item.get('record_ids'):
                record_ids = item.get('record_ids') or []
                if record_ids:
                    return record_ids[0]
    return None


def _download_product_and_model(token, source_fields, task_dir):
    product_value = get_task_product_value(source_fields)
    product_record_id = get_product_record_id(token, product_value)
    product_path = os.path.join(task_dir, 'product.png')
    if product_record_id:
        prod_fields = safe_get_record(token, TABLE_PRODUCT, product_record_id)
        attachments = prod_fields.get('产品图片', [])
        if attachments and isinstance(attachments, list):
            file_token = attachments[0].get('file_token', '')
            if file_token:
                safe_download_attachment(token, file_token, product_path)

    model_path = os.path.join(task_dir, 'model.png')
    model_record_id = _resolve_linked_record_id(source_fields.get('选择模特'))
    if model_record_id:
        model_fields = safe_get_record(token, TABLE_MODEL, model_record_id)
        attachments = model_fields.get('模特照片', [])
        if attachments and isinstance(attachments, list):
            file_token = attachments[0].get('file_token', '')
            if file_token:
                safe_download_attachment(token, file_token, model_path)

    return product_path, model_path


def _find_group_anchor_image(token, source_record_id, current_record_id):
    items = safe_list_records(token, TABLE_SHOT_STORYBOARD)
    candidates = []
    for rec in items:
        if rec['record_id'] == current_record_id:
            continue
        f = rec.get('fields', {})
        if extract_text(f.get('源逐镜头脚本记录ID', '')) != source_record_id:
            continue
        if extract_text(f.get('生成状态', '')) != '成功':
            continue
        shot_no = int(float(extract_text(f.get('分镜序号', '0')) or 0))
        attachments = f.get('分镜图', [])
        if attachments and isinstance(attachments, list):
            file_token = attachments[0].get('file_token', '')
            if file_token:
                candidates.append((shot_no, file_token))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    return candidates[0][1]


def _build_single_shot_prompt(base_prompt, shot_fields, style, visual_bible=''):
    narration = extract_text(shot_fields.get('分镜文案', ''))
    visual = extract_text(shot_fields.get('画面描述', ''))
    character = extract_text(shot_fields.get('人物描述', ''))
    scene = extract_text(shot_fields.get('场景描述', ''))
    product_focus = extract_text(shot_fields.get('产品焦点', ''))
    shot_no = extract_text(shot_fields.get('分镜序号', ''))
    total_shots = extract_text(shot_fields.get('总分镜数', ''))

    style_extra = ''
    if style == '全动画':
        style_extra = """
- 本任务中的“全动画”明确指 Disney / Pixar 向 3D 动画商业短片风格
- 采用 3D cinematic animated look，角色、场景、道具都应有明确体积感、材质感、电影化光影
- 不要输出 2D flat cartoon、扁平插画、手绘动画、低幼 flash 风
- 动物角色应具有 Pixar 式可爱、情绪清晰、动作夸张但高级的动画表演感
- 广告画面仍需干净、精致、明快，不能变成儿童简笔卡通
""".strip()

    base_prompt = (base_prompt or '').replace('{storyboard_style}', style).strip()

    shot_block = f"""

## 当前任务不是生成九宫格，而是只生成其中一个分镜头的单张图片。
请严格沿用上面的角色一致性、产品一致性、风格一致性规则，只输出当前这个 shot 对应的一张图。

## 全局视觉锚点（整组一致性最高优先级）
{visual_bible}

## 当前 Shot 信息
- Shot No: {shot_no}/{total_shots}
- Narration/Subtitles: {narration}
- Visual Description: {visual}
- Character Focus: {character}
- Scene: {scene}
- Product Focus: {product_focus}

## 单张图输出要求
- 只生成 1 张图，不要九宫格，不要 panel layout
- 画面比例 9:16 竖图
- 不要文字，不要字幕，不要贴纸，不要水印
- 必须保持产品外观与参考图完全一致
- 如果提供了模特图，必须保持主角身份、长相、体态、气质一致
- 默认单主角叙事：不要凭空新增第二主角、第三主角、明确配角
- 如必须出现其他人，只能作为弱化背景、模糊路人或环境陪衬，不能形成清晰可辨识角色，不能抢主体
- 保持场景连续性：除非当前 shot 明确要求切场，否则不要突然改变空间类型、时间段、主色调、布光逻辑
- 如果提供了组参考图，必须在人物、产品、风格、环境连续性上尽量向组参考图对齐
- 风格必须严格遵守：{style}
{style_extra}
- 优先做“同一条视频里连续镜头”的感觉，而不是把每张图都做成独立海报
"""
    return (base_prompt + shot_block).strip()


def _render_single_image(client, model_name, parts, prompt, out_path):
    parts_step = parts + [types.Part.from_text(text=prompt)]
    for attempt in range(1, 4):
        try:
            r = client.models.generate_content(
                model=model_name,
                contents=[types.Content(role='user', parts=parts_step)],
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
                        raise Exception('返回图片过小')
                    return out_path
            raise Exception('图像模型未返回图片内容')
        except Exception as e:
            if attempt >= 3:
                raise
            log_event('WARN', 'single shot image generation retry', attempt=attempt, error=str(e)[:300])
            time.sleep(5)


def classify_render_error(err):
    payload = build_error_payload(err, stage='generate_shot_image')
    mapping = {
        'CONFIG_INVALID': '配置错误',
        'INPUT_MISSING': '素材缺失',
        'MODEL_EMPTY_OUTPUT': '模型返回空',
        'UPLOAD_FAILED': '上传飞书失败',
        'WRITEBACK_FAILED': '写回失败',
        'PROMPT_BUILD_FAILED': 'prompt构造错误',
        'RUNTIME_BUG': '运行时bug',
        'UPSTREAM_NETWORK': '上游网络异常',
        'UPSTREAM_RATE_LIMIT': '上游限流',
        'MODEL_SCHEMA_INVALID': '模型结构异常',
    }
    return mapping.get(payload['error_code'], '运行时bug')


def render_shot(token, record_id):
    if not TABLE_SHOT_SCRIPT_GEN or not TABLE_SHOT_STORYBOARD:
        raise Exception('config.json 尚未配置 shot_script_gen / shot_storyboard 表 ID')

    shot_fields = safe_get_record(token, TABLE_SHOT_STORYBOARD, record_id)
    source_record_id = extract_text(shot_fields.get('源逐镜头脚本记录ID', ''))
    if not source_record_id:
        raise Exception('缺少源逐镜头脚本记录ID')

    source_fields = safe_get_record(token, TABLE_SHOT_SCRIPT_GEN, source_record_id)
    style = extract_text(source_fields.get('分镜风格', '混合（产品写实+角色动画）'))
    visual_bible = extract_text(source_fields.get('全局视觉锚点', ''))

    config = get_model_config(token, CONFIG_RECORDS['shot_storyboard'])
    config_prompt = config.get('prompt', '') or (
        "你是TikTok电商分镜图片生成专家。请根据以下信息生成一张高质量单图分镜图。\n\n"
        "## 风格规则\n"
        "产品必须始终严格写实锚定。角色与环境可与产品风格匹配或独立。\n"
        "## 产品一致性（最高优先级）\n"
        "产品在任何情况下都必须保持严格写实外观：颜色/形状/logo/材质/大小必须与参考图完全一致，"
        "不允许将产品动画化、卡通化、插画化。\n"
        "## 输出要求\n"
        "- 只生成1张图片，不是九宫格，不是panel layout\n"
        "- 画面比例9:16竖图\n"
        "- 不要文字/字幕/贴纸/水印\n"
        "- 必须保持产品写实锚定\n"
        "- 必须保持角色身份一致性\n"
        "- 如果提供了组参考图，必须在人物/产品/风格/色调上与组参考图对齐\n"
    )

    safe_update_record(token, TABLE_SHOT_STORYBOARD, record_id, {'生成状态': '生成中'})

    task_dir = ensure_task_dir(record_id)
    product_path, model_path = _download_product_and_model(token, source_fields, task_dir)
    if not os.path.exists(product_path) or os.path.getsize(product_path) < 1000:
        raise Exception('产品图片缺失')
    model_name = config['model'] or 'gemini-3.1-flash-image-preview'
    api_key = config['api_key']
    api_base = config['api_base'] or 'https://aihubmix.com/gemini'
    if not api_key:
        raise Exception('飞书配置表缺少 API Key')

    from google import genai
    client = genai.Client(api_key=api_key, http_options={'base_url': api_base})

    product_file = with_retry(lambda: client.files.upload(file=product_path), max_attempts=3, label='upload product image')
    parts = [types.Part.from_uri(file_uri=product_file.uri, mime_type='image/png')]
    if os.path.exists(model_path) and os.path.getsize(model_path) > 1000:
        model_file = with_retry(lambda: client.files.upload(file=model_path), max_attempts=3, label='upload model image')
        parts.append(types.Part.from_uri(file_uri=model_file.uri, mime_type='image/png'))

    anchor_file_token = _find_group_anchor_image(token, source_record_id, record_id)
    if anchor_file_token:
        anchor_path = os.path.join(task_dir, 'anchor.png')
        safe_download_attachment(token, anchor_file_token, anchor_path)
        if os.path.exists(anchor_path) and os.path.getsize(anchor_path) > 1000:
            anchor_file = with_retry(lambda: client.files.upload(file=anchor_path), max_attempts=3, label='upload anchor image')
            parts.append(types.Part.from_uri(file_uri=anchor_file.uri, mime_type='image/png'))

    prompt = _build_single_shot_prompt(config_prompt, shot_fields, style, visual_bible)
    out_path = os.path.join(task_dir, f'{record_id}_shot.png')
    _render_single_image(client, model_name, parts, prompt, out_path)

    file_token = with_retry(
        lambda: upload_image_to_feishu(token, out_path, f'{record_id}_shot.png'),
        max_attempts=3,
        label='upload single shot image to feishu'
    )

    success_fields = {
        '分镜图': [{'file_token': file_token}],
        '提示词': prompt[:10000],
        '生成状态': '成功',
        '生成时间': int(time.time() * 1000),
        '错误信息': '',
        '失败分类': '',
    }
    safe_update_record(
        token,
        TABLE_SHOT_STORYBOARD,
        record_id,
        filter_existing_fields(token, TABLE_SHOT_STORYBOARD, success_fields)
    )
    log_event('INFO', 'shot storyboard render success', record_id=record_id)
    print(f'✅ 单张分镜图生成完成: {record_id}')


def main():
    if len(sys.argv) < 3:
        print('用法: python3 tk_shot_storyboard.py <split|render> <record_id>')
        sys.exit(1)
    action = sys.argv[1]
    record_id = sys.argv[2]
    token = get_feishu_token()

    try:
        if action == 'split':
            split_shots(token, record_id)
        elif action == 'render':
            render_shot(token, record_id)
        else:
            raise Exception(f'未知 action: {action}')
    except Exception as e:
        payload = build_error_payload(e, stage='generate_shot_image' if action == 'render' else action)
        err = payload['message']
        log_event('ERROR', 'shot storyboard task failed', action=action, record_id=record_id, error=err, error_code=payload['error_code'], retryable=payload['retryable'])
        if action == 'render':
            fail_fields = {
                '生成状态': '失败',
                '错误信息': err,
                '失败分类': classify_render_error(e),
            }
            try:
                safe_update_record(
                    token,
                    TABLE_SHOT_STORYBOARD,
                    record_id,
                    filter_existing_fields(token, TABLE_SHOT_STORYBOARD, fail_fields)
                )
            except Exception:
                pass
        print(f"ERROR_CODE={payload['error_code']} RETRYABLE={str(payload['retryable']).lower()} MESSAGE={err}")
        sys.exit(1)


if __name__ == '__main__':
    main()
