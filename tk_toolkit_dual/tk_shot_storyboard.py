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
from pathlib import Path
from typing import List
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *
from otu_image import (
    DEFAULT_ASPECT_RATIO,
    DEFAULT_OTU_API_BASE,
    DEFAULT_OTU_IMAGE_MODEL,
    DEFAULT_OTU_IMAGE_SIZE,
    download_otu_image_result,
    extract_otu_result_url,
    normalize_image_channel,
    normalize_image_model_choice,
    poll_otu_image_task,
    submit_otu_image_task,
)
from tk_storyboard import ensure_task_dir, safe_download_attachment, upload_image_to_feishu
from tk_storyboard_style import format_style_policy_for_prompt, normalize_storyboard_style


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


def normalize_video_model_choice(value):
    raw = extract_text(value).strip().lower().replace('_', '-').replace(' ', '')
    if not raw or raw in {'待确认', 'pending', 'default'}:
        return 'veo3.1'
    if raw in {'seeddance', 'seeddance2', 'seeddance2.0', 'seed-dance', 'seed-dance-2.0', 'seedance', 'seedance2.0'}:
        return 'seeddance2.0'
    if raw in {'veo', 'veo3', 'veo3.1', 'veo-3.1'} or raw.startswith('veo-3.1') or raw.startswith('veo3.1'):
        return 'veo3.1'
    return 'veo3.1'


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


def build_shot_record_fields(source_fields, shot, *, source_record_id, idx, total_shots, product_name, source_video_id, voice_id):
    character_ids = shot.get('character_ids') if isinstance(shot.get('character_ids'), list) else []
    pet_ids = shot.get('pet_ids') if isinstance(shot.get('pet_ids'), list) else []
    must_show = shot.get('must_show') if isinstance(shot.get('must_show'), list) else []
    forbidden = shot.get('forbidden') if isinstance(shot.get('forbidden'), list) else []
    screen_text = extract_text(shot.get('screen_text', '')).strip()
    screen_text_zh = extract_text(shot.get('screen_text_zh', '')).strip()
    source_beat = extract_text(shot.get('source_beat', '')).strip()
    video_prompt_notes = extract_text(shot.get('video_prompt_notes', '')).strip()
    voiceover_text = extract_text(shot.get('voiceover_text', '')).strip()
    character_focus = extract_text(shot.get('character_focus', '')).strip()
    scene = extract_text(shot.get('scene', '')).strip()
    product_focus = extract_text(shot.get('product_focus') or shot.get('product_visibility', '')).strip()
    continuity_notes = extract_text(shot.get('continuity_notes', '')).strip()
    environment_id = extract_text(shot.get('environment_id', '')).strip()
    fields = {
        '源逐镜头脚本记录ID': source_record_id,
        '源003记录ID': extract_text(source_fields.get('源003记录ID', '')),
        '分镜序号': idx,
        '总分镜数': total_shots,
        '产品名': product_name,
        '源视频ID': source_video_id,
        '目标时长秒': shot.get('duration_sec', ''),
        '口播文本': voiceover_text,
        '口播音色ID': voice_id,
        '口播音频状态': '不触发' if voiceover_text else '成功',
        '口播音频错误信息': '',
        '角色ID': ', '.join(str(x) for x in character_ids if x),
        '宠物ID': ', '.join(str(x) for x in pet_ids if x),
        '环境ID': environment_id,
        '画面描述': shot.get('visual', ''),
        '提示词': shot.get('image_prompt', ''),
        '文本': json.dumps({
            'beat_role': shot.get('beat_role', ''),
            'visual_intensity': shot.get('visual_intensity', ''),
            'must_show': must_show,
            'forbidden': forbidden,
            'camera': shot.get('camera', ''),
            'emotion': shot.get('emotion', ''),
            'action': shot.get('action', ''),
            'screen_text': screen_text,
            'screen_text_zh': screen_text_zh,
            'source_beat': source_beat,
            'speaker': shot.get('speaker', ''),
            'speaker_visible': bool(shot.get('speaker_visible')) if 'speaker_visible' in shot else bool(voiceover_text),
            'video_prompt_notes': video_prompt_notes,
        }, ensure_ascii=False),
        '生成状态': '待生成',
    }
    if continuity_notes:
        fields['连续性要求'] = continuity_notes
    if character_focus:
        fields['人物描述'] = character_focus
    if scene:
        fields['场景描述'] = scene
    if product_focus:
        fields['产品焦点'] = product_focus
    if not voiceover_text:
        fields['口播音频时长秒'] = 0
    fields['视频提示词'] = build_image_to_video_prompt(
        shot,
        idx=idx,
        total_shots=total_shots,
        product_name=product_name,
        voiceover_text=voiceover_text,
        voice_id=voice_id,
        video_model=source_fields.get('视频生成模型', ''),
        screen_text=screen_text,
        screen_text_zh=screen_text_zh,
        video_prompt_notes=video_prompt_notes,
    )
    return fields


def build_global_voice_anchor_text(voice_id, speaker):
    speaker_label = speaker or 'the speaking character'
    if voice_id:
        return (
            f"Global voice anchor: voice profile ID {voice_id}; "
            f"{speaker_label}; keep the same age impression, gender quality, pitch, timbre, accent, speaking speed, breathing style, and emotional baseline across all shots of the same script. "
            "Do not drift to a different voice, different accent, or different vocal texture between shots."
        )
    return (
        f"Global voice anchor: stable local-language TikTok voice; {speaker_label}; "
        "natural Thai pronunciation when Thai dialogue is present; consistent age impression, pitch, timbre, accent, speaking speed, breathing style, and emotional baseline across all shots of the same script. "
        "Do not drift to a different voice, different accent, or different vocal texture between shots."
    )


def _voice_identity_text(voice_id, speaker):
    return build_global_voice_anchor_text(voice_id, speaker)


def _voice_style_text(content_type, emotion):
    if content_type == 'silent':
        return 'No spoken performance.'
    base = 'natural short-form TikTok delivery, clear pronunciation, conversational timing'
    return f"{base}; emotional performance: {emotion}" if emotion else base


def build_image_to_video_prompt(shot, *, idx, total_shots, product_name, voiceover_text, voice_id='', video_model='', screen_text='', screen_text_zh='', video_prompt_notes=''):
    duration = shot.get('duration_sec', '')
    visual = extract_text(shot.get('visual', '')).strip()
    camera = extract_text(shot.get('camera', '')).strip()
    action = extract_text(shot.get('action', '')).strip()
    emotion = extract_text(shot.get('emotion', '')).strip()
    continuity = extract_text(shot.get('continuity_notes', '')).strip()
    speaker = extract_text(shot.get('speaker', '')).strip()
    speaker_key = speaker.lower()
    product_visibility = extract_text(shot.get('product_visibility', '')).strip()
    must_show = shot.get('must_show') if isinstance(shot.get('must_show'), list) else []
    forbidden = shot.get('forbidden') if isinstance(shot.get('forbidden'), list) else []
    speaker_visible = bool(shot.get('speaker_visible')) if 'speaker_visible' in shot else bool(voiceover_text)

    motion_parts = []
    if action:
        motion_parts.append(action)
    if video_prompt_notes:
        motion_parts.append(video_prompt_notes)
    if emotion:
        motion_parts.append(f"情绪从首帧自然延续为：{emotion}")
    if not motion_parts:
        motion_parts.append("只做轻微自然动作，保持首帧构图稳定")

    model_choice = normalize_video_model_choice(video_model)
    thai_dialogue = voiceover_text or "无口播 / no spoken dialogue"
    pet_speaker = speaker_key in {'dog', 'cat', 'pet', 'puppy', 'kitten', 'สัตว์เลี้ยง', 'หมา', 'แมว'}
    if voiceover_text:
        if pet_speaker:
            speaker_rule = f"Visible speaking subject: {speaker}. Only the pet/dog/cat may lip-sync. The owner or other characters must stay silent, mouth closed or naturally still, and only react with eyes, brows, head, hands, or body. 不要改成画外旁白。"
        elif speaker_visible and speaker and speaker_key not in {'none', 'narrator'}:
            speaker_rule = f"Visible speaking subject: {speaker}. Only this character may lip-sync; all other visible characters must not mouth the line."
        else:
            speaker_rule = "The speaker is voiceover or not visibly speaking. Do not force any visible character to lip-sync."
    else:
        speaker_rule = "No speech. No lip-sync. Use only subtle natural ambient sound if the video model creates audio."

    if model_choice == 'seeddance2.0':
        if voiceover_text:
            audio_line = (
                "使用参考音频作为最终口播内容和节奏同步依据。Use the generated/uploaded reference voiceover audio as the final spoken audio and timing reference; "
                "match mouth movement, expression, and small head motion to the reference voiceover audio. Do not create a different spoken line."
            )
        else:
            audio_line = "No voiceover audio is required. Use only natural ambient sound; do not create speech, subtitles, or on-screen text."
    else:
        if voiceover_text:
            audio_line = (
                f"Veo must directly generate the final local-language spoken audio during image-to-video generation: {voiceover_text}. "
                "This is the final video audio; do not rely on later TTS or reference voiceover audio."
            )
        else:
            audio_line = "No speech in this shot; Veo should generate only natural ambient audio. Do not create speaking mouth movement, subtitles, or on-screen text."

    if voiceover_text:
        voice_policy = f"{audio_line} {speaker_rule}"
    else:
        voice_policy = audio_line

    post_text_policy = ""
    if screen_text or screen_text_zh:
        post_text_policy = f"后期屏幕文字参考：{screen_text}（中文理解：{screen_text_zh}）。不要在视频画面里生成这些文字，交给后期叠加。"

    must_show_text = "、".join(str(x) for x in must_show if x)
    forbidden_text = "、".join(str(x) for x in forbidden if x)
    lines = [
        "Use the uploaded image as the first frame. Keep the character, product, composition, lighting, and background consistent with the first frame. Do not redesign or re-render the scene.",
        f"Action: {'; '.join(motion_parts)}. Start from the exact first-frame state; only continue 1-2 natural actions already implied by the image.",
        f"Thai dialogue: \"{thai_dialogue}\".",
        f"Voice style: {_voice_style_text('spoken' if voiceover_text else 'silent', emotion)}.",
        f"Voice identity: {_voice_identity_text(voice_id, speaker)}.",
        f"Camera: {camera or 'subtle handheld or very slight push-in; keep the first-frame composition stable; no big transition'}.",
        f"Audio: {voice_policy}",
        f"Restrictions: no subtitles, no captions, no on-screen text, no stickers, no watermark, no TikTok UI, no price bubble, no new characters, no new pets, no scene replacement, no face drift, no outfit change, no product morphing, no label change. {product_name or 'The product'} 产品包装必须保持写实; keep logo, label, color, dosage marking, box shape, and proportions unchanged. Product exposure level: {product_visibility or 'keep as shown in the first frame'}.",
        f"Continuity: {continuity or 'Do not add unrelated people, pets, props, or sudden scene changes.'}",
        f"First-frame visual understanding: {visual}",
    ]
    if must_show_text:
        lines.append(f"必须保留/强化：{must_show_text}。")
    if forbidden_text:
        lines.append(f"禁止出现：{forbidden_text}。")
    if post_text_policy:
        lines.append(post_text_policy)
    lines.append("不要生成字幕、贴纸、水印、TikTok UI、价格气泡、额外文字；不要让产品变形、标签漂移、宠物/人物身份漂移。")
    return "\n".join(lines)


def load_shots_payload(fields, payload=None):
    if payload is not None:
        data = payload
    else:
        raw = extract_text(fields.get('分镜头结构JSON', ''))
        if not raw:
            raise Exception('分镜头结构JSON 为空')
        data = json.loads(raw)
    shots = data.get('shots', []) if isinstance(data, dict) else []
    if not shots:
        raise Exception('shots 为空')
    return data, shots


def split_shots(token, source_record_id, payload=None):
    if not TABLE_SHOT_SCRIPT_GEN or not TABLE_SHOT_STORYBOARD:
        raise Exception('config.json 尚未配置 shot_script_gen / shot_storyboard 表 ID')

    fields = safe_get_record(token, TABLE_SHOT_SCRIPT_GEN, source_record_id)
    data, shots = load_shots_payload(fields, payload)

    product_name = extract_text(get_task_product_value(fields))
    source_video_id = extract_text(fields.get('源视频ID', ''))
    voice_id = extract_text(fields.get('口播音色ID', '')).strip()
    records = []
    for idx, shot in enumerate(shots, start=1):
        shot_fields = build_shot_record_fields(
            fields,
            shot,
            source_record_id=source_record_id,
            idx=idx,
            total_shots=len(shots),
            product_name=product_name,
            source_video_id=source_video_id,
            voice_id=voice_id,
        )
        records.append({'fields': filter_existing_fields(token, TABLE_SHOT_STORYBOARD, shot_fields)})

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


SHOT_REVISION_NOTE_FIELDS = (
    '分镜图修改要求',
    '修改要求',
    '重生成备注',
    '备注',
)


def _extract_shot_revision_note(shot_fields):
    for field_name in SHOT_REVISION_NOTE_FIELDS:
        note = extract_text(shot_fields.get(field_name, '')).strip()
        if note:
            return note
    return ''


def _clean_image_prompt_draft(value):
    text = extract_text(value).strip()
    if not text:
        return ''
    generated_prompt_markers = (
        'Reference image 1 =',
        '## 当前任务不是生成九宫格',
        '## 单张图输出要求',
        'Use these reference images as hard identity anchors',
    )
    if any(marker in text for marker in generated_prompt_markers):
        return ''
    return text


def _build_single_shot_prompt(base_prompt, shot_fields, style, visual_bible=''):
    narration = extract_text(shot_fields.get('分镜文案', ''))
    voiceover = extract_text(shot_fields.get('口播文本', ''))
    visual = extract_text(shot_fields.get('画面描述', '')) or extract_text(shot_fields.get('分镜说明', ''))
    character = extract_text(shot_fields.get('人物描述', ''))
    scene = extract_text(shot_fields.get('场景描述', ''))
    product_focus = extract_text(shot_fields.get('产品焦点', ''))
    continuity = extract_text(shot_fields.get('连续性要求', ''))
    character_id = extract_text(shot_fields.get('角色ID', ''))
    pet_id = extract_text(shot_fields.get('宠物ID', ''))
    environment_id = extract_text(shot_fields.get('环境ID', ''))
    target_duration = extract_text(shot_fields.get('目标时长秒', ''))
    image_prompt = _clean_image_prompt_draft(shot_fields.get('图片提示词') or shot_fields.get('提示词', ''))
    shot_no = extract_text(shot_fields.get('分镜序号', ''))
    total_shots = extract_text(shot_fields.get('总分镜数', ''))
    raw_meta = extract_text(shot_fields.get('文本', '')).strip()
    meta = {}
    if raw_meta:
        try:
            parsed = json.loads(raw_meta)
            meta = parsed if isinstance(parsed, dict) else {}
        except Exception:
            meta = {}
    screen_text = extract_text(meta.get('screen_text', '')).strip()
    screen_text_zh = extract_text(meta.get('screen_text_zh', '')).strip()
    source_beat = extract_text(meta.get('source_beat', '')).strip()
    video_prompt_notes = extract_text(meta.get('video_prompt_notes', '')).strip()
    revision_note = _extract_shot_revision_note(shot_fields)

    normalized_style = normalize_storyboard_style(style)
    style_policy_block = format_style_policy_for_prompt(normalized_style)

    style_extra = ''
    if normalized_style == '全动画':
        style_extra = """
- 本任务中的“全动画”明确指 Disney / Pixar 向 3D 动画商业短片风格
- 采用 3D cinematic animated look，角色、场景、道具都应有明确体积感、材质感、电影化光影
- 不要输出 2D flat cartoon、扁平插画、手绘动画、低幼 flash 风
- 动物角色应具有 Pixar 式可爱、情绪清晰、动作夸张但高级的动画表演感
- 广告画面仍需干净、精致、明快，不能变成儿童简笔卡通
""".strip()

    base_prompt = (base_prompt or '').replace('{storyboard_style}', normalized_style).strip()

    shot_block = f"""

## 当前任务不是生成九宫格，而是只生成其中一个分镜头的单张图片。
请严格沿用上面的角色一致性、产品一致性、风格一致性规则，只输出当前这个 shot 对应的一张图。

{style_policy_block}

## 全局视觉锚点（整组一致性最高优先级）
{visual_bible}

## 当前 Shot 信息
- Shot No: {shot_no}/{total_shots}
- Target Duration: {target_duration}s
- Voiceover: {voiceover or narration}
- Narration/Subtitles: {narration}
- Visual Description: {visual}
- Image Prompt Draft: {image_prompt}
- Character Focus: {character}
- Character ID: {character_id}
- Pet ID: {pet_id}
- Scene: {scene}
- Environment ID: {environment_id}
- Product Focus: {product_focus}
- Continuity Requirement: {continuity}
- Screen Text For Post-production Only: {screen_text}
- Screen Text Chinese Meaning: {screen_text_zh}
- Source Beat: {source_beat}
- Video Prompt Notes: {video_prompt_notes}

## 本次重生成修改要求（如为空则忽略）
{revision_note or '无'}

## 单张图输出要求
- 只生成 1 张图，不要九宫格，不要 panel layout
- 画面比例 9:16 竖图
- 如果“本次重生成修改要求”非空，必须优先满足该要求；但不能破坏产品写实一致性、主角/宠物身份一致性、场景连续性和当前 shot 的故事任务
- 不要文字，不要字幕，不要贴纸，不要水印
- 不要把 Screen Text / Screen Text Chinese Meaning 生成到图片里；它们只供后期叠加字幕或人工检查
- 必须保持产品外观与参考图完全一致
- 如果提供了模特图，必须保持主角身份、长相、体态、气质一致
- 默认单主角叙事：不要凭空新增第二主角、第三主角、明确配角
- 如必须出现其他人，只能作为弱化背景、模糊路人或环境陪衬，不能形成清晰可辨识角色，不能抢主体
- 保持场景连续性：除非当前 shot 明确要求切场，否则不要突然改变空间类型、时间段、主色调、布光逻辑
- 如果提供了组参考图，必须在人物、产品、风格、环境连续性上尽量向组参考图对齐
- 风格必须严格遵守：{normalized_style}
{style_extra}
- 优先做“同一条视频里连续镜头”的感觉，而不是把每张图都做成独立海报
"""
    return (base_prompt + shot_block).strip()


def build_shot_reference_prompt_note(refs):
    if not refs:
        return "No extra reference images were uploaded."
    lines = []
    for idx, ref in enumerate(refs, start=1):
        role = ref.get("role", "reference")
        if role == "product":
            lines.append(f"Reference image {idx} = product reference. Keep the product shape, label, color, and logo unchanged.")
        elif role.startswith("pet:"):
            lines.append(f"Reference image {idx} = selected pet model reference ({role.split(':', 1)[1]}). Keep the same pet identity, breed, face, coat pattern, fur length, ear shape, and body proportions.")
        elif role.startswith("human:"):
            lines.append(f"Reference image {idx} = selected human model reference ({role.split(':', 1)[1]}). Keep the same person identity, face, hairstyle, body shape, and clothing silhouette.")
        else:
            lines.append(f"Reference image {idx} = {role}. Keep it aligned with the current shot requirement.")
    lines.append("Use these reference images as hard identity anchors, not optional inspiration.")
    return "\n".join(lines)


def build_reference_urls(token: str, refs: List[dict]) -> List[str]:
    urls = []
    for ref in refs:
        file_token = ref.get("file_token", "")
        if not file_token:
            continue
        url = "https://open.feishu.cn/open-apis/drive/v1/medias/batch_get_tmp_download_url"
        data = safe_request(
            "get",
            url,
            headers=feishu_headers(token),
            params={"file_tokens": file_token},
            timeout=60,
            max_attempts=3,
            acceptable_codes=(0,),
        )
        items = data.get("data", {}).get("tmp_download_urls") or []
        if isinstance(items, dict):
            tmp = extract_text(items.get(file_token) or items.get("tmp_download_url") or "").strip()
        elif items:
            tmp = ""
            for item in items:
                item = item or {}
                if extract_text(item.get("file_token") or "").strip() == file_token:
                    tmp = extract_text(item.get("tmp_download_url") or item.get("url") or "").strip()
                    break
            if not tmp:
                first = items[0] or {}
                tmp = extract_text(first.get("tmp_download_url") or first.get("url") or "").strip()
        else:
            tmp = ""
        if tmp:
            urls.append(tmp)
    return urls


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


def _upload_reference_image_parts(client, refs):
    from google.genai import types

    parts = []
    for ref in refs:
        path = ref.get('path', '')
        if not path or not os.path.exists(path) or os.path.getsize(path) < 1000:
            raise Exception(f"参考图文件无效: {ref.get('role', '')}")
        uploaded = with_retry(
            lambda p=path: client.files.upload(file=p),
            max_attempts=3,
            label=f"upload reference image {ref.get('role', '')}",
        )
        parts.append(types.Part.from_uri(file_uri=uploaded.uri, mime_type='image/png'))
    return parts


def render_script_doc_shot(token, record_id):
    if not TABLE_SCRIPT_DOC_TASKS or not TABLE_SCRIPT_DOC_REFERENCE_ASSETS or not TABLE_SCRIPT_DOC_SHOTS:
        raise Exception('config.json 尚未配置脚本文档拆分表 ID')

    from tk_script_doc_shots import (
        build_reference_prompt_note,
        collect_reference_images_for_shot,
    )

    shot_fields = safe_get_record(token, TABLE_SCRIPT_DOC_SHOTS, record_id)
    parent_record_id = extract_text(shot_fields.get('父文档记录ID', '')).strip()
    if not parent_record_id:
        raise Exception('缺少父文档记录ID')

    parent_fields = safe_get_record(token, TABLE_SCRIPT_DOC_TASKS, parent_record_id)
    style = extract_text(parent_fields.get('分镜风格', '混合（产品写实+角色动画）'))
    visual_bible = extract_text(parent_fields.get('解析结果JSON', ''))

    config = get_model_config(token, CONFIG_RECORDS['shot_storyboard'])
    config_prompt = config.get('prompt', '') or (
        "你是TikTok电商分镜图片生成专家。请根据以下信息生成一张高质量单图分镜图。\n\n"
        "## 输出要求\n"
        "- 只生成1张图片，不是九宫格，不是panel layout\n"
        "- 画面比例9:16竖图\n"
        "- 不要文字/字幕/贴纸/水印\n"
    )

    safe_update_record(token, TABLE_SCRIPT_DOC_SHOTS, record_id, filter_existing_fields(token, TABLE_SCRIPT_DOC_SHOTS, {
        '分镜图生成状态': '生成中',
        '分镜图错误信息': '',
    }))

    task_dir = ensure_task_dir(record_id)
    refs = collect_reference_images_for_shot(
        token,
        shot_fields,
        parent_fields,
        safe_list_records(token, TABLE_SCRIPT_DOC_REFERENCE_ASSETS),
        Path(task_dir),
    )

    model_choice = normalize_image_model_choice(config['model'] or DEFAULT_OTU_IMAGE_MODEL)
    api_key = config['api_key']
    api_base = config['api_base'] or DEFAULT_OTU_API_BASE
    if not api_key:
        raise Exception('飞书配置表缺少 API Key')
    prompt = _build_single_shot_prompt(config_prompt, shot_fields, style, visual_bible)
    prompt = f"{build_shot_reference_prompt_note(refs)}\n\n{prompt}".strip()
    out_path = os.path.join(task_dir, f'{record_id}_shot.png')
    ref_paths = [ref.get('path') for ref in refs if ref.get('path')]
    reference_urls = build_reference_urls(token, refs)
    submit_task_id, submit_body = submit_otu_image_task(
        {
            'api_key': api_key,
            'api_base': api_base,
            'model': model_choice,
        },
        prompt,
        input_mode='image-to-image' if ref_paths else 'text-to-image',
        image_path=ref_paths[0] if ref_paths else '',
        metadata={'urls': reference_urls, 'reference_roles': [ref.get('role', 'reference') for ref in refs], 'aspectRatio': '9:16'},
        size=DEFAULT_OTU_IMAGE_SIZE,
    )
    result = submit_body if not submit_task_id else poll_otu_image_task({
        'api_key': api_key,
        'api_base': api_base,
        'model': model_choice,
    }, submit_task_id)
    result_url = extract_otu_result_url(result) or extract_otu_result_url(submit_body)
    if not result_url:
        raise Exception('OTU 图像任务完成但未返回图片地址')
    download_otu_image_result(result_url, out_path)

    file_token = with_retry(
        lambda: upload_image_to_feishu(token, out_path, f'{record_id}_shot.png'),
        max_attempts=3,
        label='upload script doc shot image to feishu'
    )

    success_fields = {
        '分镜图': [{'file_token': file_token}],
        '分镜图file_token': file_token,
        '分镜图本地路径': out_path,
        '提示词': prompt[:10000],
        '分镜图生成状态': '成功',
        '分镜图生成时间': int(time.time() * 1000),
        '分镜图错误信息': '',
        '错误信息': '',
    }
    safe_update_record(token, TABLE_SCRIPT_DOC_SHOTS, record_id, filter_existing_fields(token, TABLE_SCRIPT_DOC_SHOTS, success_fields))
    log_event('INFO', 'script doc shot storyboard render success', record_id=record_id, reference_count=len(refs))
    print(f'✅ 脚本文档单张分镜图生成完成: {record_id}')


def render_shot(token, record_id, table='shot_storyboard'):
    if table in ('script_doc', 'script_doc_shots', TABLE_SCRIPT_DOC_SHOTS):
        return render_script_doc_shot(token, record_id)

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
    model_name = config['model'] or DEFAULT_OTU_IMAGE_MODEL
    api_key = config['api_key']
    api_base = config['api_base'] or 'https://otuapi.com'
    if not api_key:
        raise Exception('飞书配置表缺少 API Key')

    prompt = _build_single_shot_prompt(config_prompt, shot_fields, style, visual_bible)
    prompt = f"{build_shot_reference_prompt_note([{'role': 'product'}])}\n\n{prompt}".strip()
    out_path = os.path.join(task_dir, f'{record_id}_shot.png')
    submit_task_id, submit_body = submit_otu_image_task(
        {'api_key': api_key, 'api_base': api_base, 'model': model_name},
        prompt,
        input_mode='image-to-image',
        image_path=product_path,
        metadata={'urls': [product_path], 'aspectRatio': '9:16'},
        size=DEFAULT_OTU_IMAGE_SIZE,
    )
    result = submit_body if not submit_task_id else poll_otu_image_task({'api_key': api_key, 'api_base': api_base, 'model': model_name}, submit_task_id)
    result_url = extract_otu_result_url(result) or extract_otu_result_url(submit_body)
    if not result_url:
        raise Exception('OTU 图像任务完成但未返回图片地址')
    download_otu_image_result(result_url, out_path)

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
    import argparse
    parser = argparse.ArgumentParser(description='逐镜头分镜图生成')
    parser.add_argument('action', choices=['split', 'render'])
    parser.add_argument('record_id')
    parser.add_argument('--table', default='shot_storyboard', choices=['shot_storyboard', 'script_doc'])
    args = parser.parse_args()
    action = args.action
    record_id = args.record_id
    token = get_feishu_token()

    try:
        if action == 'split':
            split_shots(token, record_id)
        elif action == 'render':
            render_shot(token, record_id, table=args.table)
        else:
            raise Exception(f'未知 action: {action}')
    except Exception as e:
        payload = build_error_payload(e, stage='generate_shot_image' if action == 'render' else action)
        err = payload['message']
        log_event('ERROR', 'shot storyboard task failed', action=action, record_id=record_id, error=err, error_code=payload['error_code'], retryable=payload['retryable'])
        if action == 'render' and args.table == 'script_doc':
            fail_fields = {
                '分镜图生成状态': '失败',
                '分镜图错误信息': err,
                '错误信息': err,
            }
            try:
                safe_update_record(
                    token,
                    TABLE_SCRIPT_DOC_SHOTS,
                    record_id,
                    filter_existing_fields(token, TABLE_SCRIPT_DOC_SHOTS, fail_fields)
                )
            except Exception:
                pass
        elif action == 'render':
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
