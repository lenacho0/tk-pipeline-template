#!/usr/bin/env python3
"""
脚本文档逐镜头分镜图生成
用法:
1) python3 tk_shot_storyboard.py render <script_doc_shot_record_id>
   - 对单条 shot 记录生成 1 张分镜图
"""
import json, os, sys, time, base64
from pathlib import Path
from typing import List
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ai_routing
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
from image_generation import config_records_for_image_slot, resolve_image_route_from_slot, run_image_generation
from tk_storyboard_style import format_style_policy_for_prompt, normalize_storyboard_style


_TABLE_FIELDS_CACHE = {}


def script_doc_unified_route_state(fields, token):
    if not ai_routing.record_wants_unified_route(fields):
        return False, False
    config_records = safe_list_records(token, TABLE_CONFIG)
    enabled = ai_routing.unified_route_enabled(fields, config_records)
    return enabled, enabled and ai_routing.unified_route_dry_run_only(config_records)


def selected_slot_model(fields, slot_name, default_model, *, route_enabled=False):
    if not route_enabled:
        return normalize_image_model_choice(default_model)
    raw = extract_text(fields.get(f'{slot_name}AI模型')).strip()
    if ' / ' in raw:
        provider, model = raw.split(' / ', 1)
        return raw if provider.strip() != 'OTU' else normalize_image_model_choice(model)
    return normalize_image_model_choice(raw or default_model)


def slot_params(fields, slot_name, *, route_enabled=False):
    data = {}
    raw = extract_text(fields.get(f'{slot_name}AI参数JSON')).strip()
    if raw:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f'{slot_name}AI参数JSON 不是合法 JSON: {exc}') from exc
        if not isinstance(data, dict):
            raise ValueError(f'{slot_name}AI参数JSON 顶层必须是对象')
    size = extract_text(fields.get(f'{slot_name}画面尺寸')).strip()
    aspect_ratio = extract_text(fields.get(f'{slot_name}画面比例')).strip()
    if size:
        data["size"] = size
    if aspect_ratio:
        data["aspect_ratio"] = aspect_ratio
    return data


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


def get_attachment_token(value):
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict) and item.get('file_token'):
                return str(item.get('file_token')).strip()
    return ''


def download_feishu_media(token, file_token, save_path):
    url = f"https://open.feishu.cn/open-apis/drive/v1/medias/{file_token}/download"
    resp = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=300, stream=True)
    if resp.status_code != 200:
        raise RuntimeError(f"飞书附件下载失败: HTTP {resp.status_code}, file_token={file_token}")
    save_path = Path(save_path)
    with save_path.open("wb") as f:
        for chunk in resp.iter_content(8192):
            if chunk:
                f.write(chunk)
    if save_path.stat().st_size < 1000:
        raise RuntimeError(f"飞书附件下载结果过小: {save_path}")
    return save_path


def normalize_video_model_choice(value):
    raw = extract_text(value).strip().lower().replace('_', '-').replace(' ', '')
    if not raw or raw in {'待确认', 'pending', 'default'}:
        return 'veo3.1'
    if raw in {'seeddance', 'seeddance2', 'seeddance2.0', 'seed-dance', 'seed-dance-2.0', 'seedance', 'seedance2.0'}:
        return 'seeddance2.0'
    if raw in {'veo', 'veo3', 'veo3.1', 'veo-3.1'} or raw.startswith('veo-3.1') or raw.startswith('veo3.1'):
        return 'veo3.1'
    return 'veo3.1'


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


def _spoken_audio_line(voiceover_text, speaker, speaker_visible, pet_speaker):
    text = extract_text(voiceover_text).strip()
    if not text:
        return "No speech. Natural ambient sound only."
    speaker_name = extract_text(speaker).strip()
    speaker_key = speaker_name.lower()
    if pet_speaker or (speaker_visible and speaker_name and speaker_key not in {'none', 'narrator'}):
        return f"The {speaker_name} says in Thai: {text}"
    return f"Thai voiceover: {text}"


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
    pet_speaker = speaker_key in {'dog', 'cat', 'pet', 'puppy', 'kitten', 'สัตว์เลี้ยง', 'หมา', 'แมว'}
    spoken_audio_line = _spoken_audio_line(voiceover_text, speaker, speaker_visible, pet_speaker)
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
                f"Veo must directly generate the final local-language spoken audio during image-to-video generation. {spoken_audio_line}. "
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
        spoken_audio_line,
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


def _resolve_linked_record_id(link_val):
    if isinstance(link_val, list):
        for item in link_val:
            if isinstance(item, dict) and item.get('record_ids'):
                record_ids = item.get('record_ids') or []
                if record_ids:
                    return record_ids[0]
    return None


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


STARTING_FRAME_MARKERS = ['[Starting Frame]', 'Starting Frame:', '首帧：', '首帧:', '开始帧：', '开始帧:']
ENDING_FRAME_MARKERS = ['[Ending Frame]', 'Ending Frame:', '尾帧：', '尾帧:', '结束帧：', '结束帧:']
FRAME_BOUNDARY_MARKERS = STARTING_FRAME_MARKERS + ENDING_FRAME_MARKERS + ['[Video Prompt]', '[Restrictions]', '[Negative Prompt]']


def _extract_marked_frame_section(text, markers, stop_markers=None):
    raw = extract_text(text).strip()
    if not raw:
        return ''
    lower = raw.lower()
    start = -1
    marker_len = 0
    for marker in markers:
        idx = lower.find(marker.lower())
        if idx >= 0:
            start = idx
            marker_len = len(marker)
            break
    if start < 0:
        return ''
    section = raw[start + marker_len:].strip()
    stops = stop_markers if stop_markers is not None else FRAME_BOUNDARY_MARKERS
    section_lower = section.lower()
    end = len(section)
    for marker in stops:
        idx = section_lower.find(marker.lower())
        if idx >= 0:
            end = min(end, idx)
    return ' '.join(section[:end].strip().split())


def extract_starting_frame_section(text):
    return _extract_marked_frame_section(text, STARTING_FRAME_MARKERS)


def image_prompt_for_first_frame(fields):
    image_prompt = _clean_image_prompt_draft(fields.get('图片提示词') or fields.get('提示词', ''))
    if is_end_frame_mode_enabled(fields):
        starting = extract_starting_frame_section(image_prompt)
        if starting:
            return starting
    return image_prompt


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
    image_prompt = image_prompt_for_first_frame(shot_fields)
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
- 只生成当前分镜的单一时刻，不要 split screen，不要 before-after comparison，不要 two-panel，不要 collage
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
        if role == "product" or role.startswith("product:"):
            lines.append(f"Reference image {idx} = product reference. Keep the product packaging, shape, label, color, specification, and logo unchanged.")
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


def get_tmp_download_url_for_attachment(token: str, file_token: str) -> str:
    urls = build_reference_urls(token, [{"role": "attachment", "file_token": file_token}])
    return urls[0] if urls else ""


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


def render_script_doc_shot(token, record_id, *, dry_run=False):
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

    config = get_model_config(token, CONFIG_RECORDS['main_image_otu'])
    config_prompt = config.get('prompt', '') or (
        "你是TikTok电商分镜图片生成专家。请根据以下信息生成一张高质量单图分镜图。\n\n"
        "## 输出要求\n"
        "- 只生成1张图片，不是九宫格，不是panel layout\n"
        "- 画面比例9:16竖图\n"
        "- 不要文字/字幕/贴纸/水印\n"
    )

    route_enabled, route_dry_run_only = script_doc_unified_route_state(shot_fields, token)
    model_choice = selected_slot_model(shot_fields, '分镜图', config['model'] or DEFAULT_OTU_IMAGE_MODEL, route_enabled=route_enabled)
    image_params = slot_params(shot_fields, '分镜图', route_enabled=route_enabled)
    config_records = config_records_for_image_slot(shot_fields, '分镜图', lambda: safe_list_records(token, TABLE_CONFIG))
    route = resolve_image_route_from_slot(
        shot_fields,
        '分镜图',
        config,
        task_type='分镜图生成',
        params={'size': image_params.get('size') or DEFAULT_OTU_IMAGE_SIZE, 'aspect_ratio': image_params.get('aspect_ratio') or '9:16'},
        config_records=config_records,
    )
    prompt = _build_single_shot_prompt(config_prompt, shot_fields, style, visual_bible)
    summary = {
        'record_id': record_id,
        'dry_run': dry_run,
        'model': model_choice,
        'size': image_params.get('size') or DEFAULT_OTU_IMAGE_SIZE,
        'aspect_ratio': image_params.get('aspect_ratio') or '9:16',
        'prompt_chars': len(prompt),
        'unified_ai_route_enabled': route_enabled,
    }
    if dry_run:
        summary['status'] = 'dry_run_ready'
        return summary
    if route_dry_run_only:
        summary['status'] = 'unified_ai_dry_run_ready'
        return summary

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

    api_key = config['api_key']
    api_base = config['api_base'] or DEFAULT_OTU_API_BASE
    if not api_key:
        raise Exception('飞书配置表缺少 API Key')
    prompt = f"{build_shot_reference_prompt_note(refs)}\n\n{prompt}".strip()
    out_path = os.path.join(task_dir, f'{record_id}_shot.png')
    ref_paths = [ref.get('path') for ref in refs if ref.get('path')]
    reference_urls = build_reference_urls(token, refs)
    image_result = run_image_generation(
        route,
        prompt,
        out_path,
        input_mode='image-to-image' if ref_paths else 'text-to-image',
        image_path=ref_paths[0] if ref_paths else '',
        metadata={'urls': reference_urls, 'reference_roles': [ref.get('role', 'reference') for ref in refs], 'aspectRatio': image_params.get('aspect_ratio') or '9:16'},
        size=image_params.get('size') or DEFAULT_OTU_IMAGE_SIZE,
        aspect_ratio=image_params.get('aspect_ratio') or '9:16',
        otu_submitter=submit_otu_image_task,
        otu_poller=poll_otu_image_task,
        otu_downloader=download_otu_image_result,
    )
    submit_task_id = image_result.task_id
    submit_body = image_result.submit_body
    result = image_result.result_body

    file_token = with_retry(
        lambda: upload_image_to_feishu(token, out_path, f'{record_id}_shot.png'),
        max_attempts=3,
        label='upload script doc shot image to feishu'
    )

    success_fields = build_script_doc_storyboard_success_fields(
        shot_fields,
        file_token=file_token,
        out_path=out_path,
        prompt=prompt,
    )
    safe_update_record(token, TABLE_SCRIPT_DOC_SHOTS, record_id, filter_existing_fields(token, TABLE_SCRIPT_DOC_SHOTS, success_fields))
    log_event('INFO', 'script doc shot storyboard render success', record_id=record_id, reference_count=len(refs))
    print(f'✅ 脚本文档单张分镜图生成完成: {record_id}')


def is_end_frame_mode_enabled(fields):
    raw = extract_text(fields.get('首尾帧视频模式')).strip().lower().replace(' ', '')
    return raw in {'启用', '是', 'yes', 'true', '1', 'enabled', 'enable'}


def extract_ending_frame_section(text):
    return _extract_marked_frame_section(text, ENDING_FRAME_MARKERS)


def infer_script_doc_last_frame_description(fields):
    explicit_tail = extract_text(fields.get('尾帧画面描述')).strip()
    if explicit_tail:
        return explicit_tail
    for field_name in ('图片提示词', '提示词', '结构化分镜JSON'):
        candidate = extract_ending_frame_section(fields.get(field_name))
        if candidate:
            return candidate
    raw_json = extract_text(fields.get('结构化分镜JSON')).strip()
    if raw_json:
        try:
            parsed = json.loads(raw_json)
        except Exception:
            parsed = {}
        if isinstance(parsed, dict):
            for key in ('image_prompt', 'video_prompt', 'continuity_notes'):
                candidate = extract_ending_frame_section(parsed.get(key))
                if candidate:
                    return candidate
            continuity = extract_text(parsed.get('continuity_notes')).strip()
            if continuity:
                return continuity
    return ''


def build_script_doc_storyboard_success_fields(shot_fields, *, file_token, out_path, prompt):
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
    if is_end_frame_mode_enabled(shot_fields):
        tail_description = infer_script_doc_last_frame_description(shot_fields)
        if tail_description and not extract_text(shot_fields.get('尾帧画面描述')).strip():
            success_fields['尾帧画面描述'] = tail_description[:10000]
        tail_status = extract_text(shot_fields.get('尾帧图生成状态')).strip()
        if tail_status not in {'成功', '生成中'}:
            success_fields['尾帧图生成状态'] = '待生成'
            success_fields['尾帧图错误信息'] = ''
    return success_fields


def build_script_doc_last_frame_prompt(fields, first_frame_prompt=''):
    explicit_tail = infer_script_doc_last_frame_description(fields)
    target = extract_text(explicit_tail).strip() or (
        "Infer the final moment of the shot from the action prompt. "
        "Show the natural end state after the described motion is completed."
    )
    parts = [
        "Edit the uploaded first-frame image according to the following Ending Frame instruction.",
        "Use the uploaded first-frame image as the visual reference.",
        "Follow the Ending Frame instruction exactly.",
        "",
        "Ending Frame instruction:",
        target,
        "",
        "Output one single 9:16 final frame image, not a split-screen or before-after comparison.",
    ]
    return "\n".join(parts)


def render_script_doc_last_frame(token, record_id, *, dry_run=False):
    if not TABLE_SCRIPT_DOC_SHOTS:
        raise Exception('config.json 尚未配置 script_doc_shots 表 ID')

    fields = safe_get_record(token, TABLE_SCRIPT_DOC_SHOTS, record_id)
    if not is_end_frame_mode_enabled(fields):
        raise Exception('首尾帧视频模式未启用，拒绝生成尾帧图')
    first_frame_token = get_attachment_token(fields.get('分镜图'))
    if not first_frame_token:
        raise Exception('缺少分镜图附件，无法生成尾帧图')

    config = get_model_config(token, CONFIG_RECORDS['main_image_otu'])
    route_enabled, route_dry_run_only = script_doc_unified_route_state(fields, token)
    model_name = selected_slot_model(fields, '尾帧图', config['model'] or DEFAULT_OTU_IMAGE_MODEL, route_enabled=route_enabled)
    image_params = slot_params(fields, '尾帧图', route_enabled=route_enabled)
    config_records = config_records_for_image_slot(fields, '尾帧图', lambda: safe_list_records(token, TABLE_CONFIG))
    route = resolve_image_route_from_slot(
        fields,
        '尾帧图',
        config,
        task_type='尾帧图生成',
        params={'size': image_params.get('size') or DEFAULT_OTU_IMAGE_SIZE, 'aspect_ratio': image_params.get('aspect_ratio') or '9:16'},
        config_records=config_records,
    )
    prompt = build_script_doc_last_frame_prompt(
        fields,
        extract_text(fields.get('图片提示词') or fields.get('提示词')).strip(),
    )
    summary = {
        'record_id': record_id,
        'dry_run': dry_run,
        'model': model_name,
        'size': image_params.get('size') or DEFAULT_OTU_IMAGE_SIZE,
        'aspect_ratio': image_params.get('aspect_ratio') or '9:16',
        'prompt_chars': len(prompt),
        'first_frame_file_token_present': bool(first_frame_token),
        'unified_ai_route_enabled': route_enabled,
    }
    if dry_run:
        summary['status'] = 'dry_run_ready'
        return summary
    if route_dry_run_only:
        summary['status'] = 'unified_ai_dry_run_ready'
        return summary

    safe_update_record(token, TABLE_SCRIPT_DOC_SHOTS, record_id, filter_existing_fields(token, TABLE_SCRIPT_DOC_SHOTS, {
        '尾帧图生成状态': '生成中',
        '尾帧图错误信息': '',
    }))

    task_dir = ensure_task_dir(record_id)
    first_frame_path = download_feishu_media(token, first_frame_token, Path(task_dir) / f'{record_id}_first_frame.png')
    first_frame_tmp_url = get_tmp_download_url_for_attachment(token, first_frame_token)
    api_key = config['api_key']
    api_base = config['api_base'] or DEFAULT_OTU_API_BASE
    if not api_key:
        raise Exception('飞书配置表缺少 API Key')
    out_path = os.path.join(task_dir, f'{record_id}_last_frame.png')
    image_result = run_image_generation(
        route,
        prompt,
        out_path,
        input_mode='image-to-image',
        image_path=str(first_frame_path),
        metadata={'urls': [first_frame_tmp_url] if first_frame_tmp_url else [], 'reference_roles': ['first_frame'], 'aspectRatio': image_params.get('aspect_ratio') or '9:16'},
        size=image_params.get('size') or DEFAULT_OTU_IMAGE_SIZE,
        aspect_ratio=image_params.get('aspect_ratio') or '9:16',
        otu_submitter=submit_otu_image_task,
        otu_poller=poll_otu_image_task,
        otu_downloader=download_otu_image_result,
    )
    submit_task_id = image_result.task_id
    submit_body = image_result.submit_body
    result = image_result.result_body

    file_token = with_retry(
        lambda: upload_image_to_feishu(token, out_path, f'{record_id}_last_frame.png'),
        max_attempts=3,
        label='upload script doc last frame image to feishu'
    )
    safe_update_record(token, TABLE_SCRIPT_DOC_SHOTS, record_id, filter_existing_fields(token, TABLE_SCRIPT_DOC_SHOTS, {
        '尾帧图': [{'file_token': file_token}],
        '尾帧图file_token': file_token,
        '尾帧图本地路径': out_path,
        '尾帧图提示词': prompt[:10000],
        '尾帧图生成状态': '成功',
        '尾帧图生成时间': int(time.time() * 1000),
        '尾帧图错误信息': '',
        '错误信息': '',
    }))
    log_event('INFO', 'script doc last frame render success', record_id=record_id)
    print(f'✅ 脚本文档尾帧图生成完成: {record_id}')


def render_shot(token, record_id, table='script_doc', *, dry_run=False):
    if table in ('script_doc', 'script_doc_shots', TABLE_SCRIPT_DOC_SHOTS):
        return render_script_doc_shot(token, record_id, dry_run=dry_run)

    raise Exception('不再支持旧 shot_storyboard 表，请使用 script_doc')


def main():
    import argparse
    parser = argparse.ArgumentParser(description='逐镜头分镜图生成')
    parser.add_argument('action', choices=['render', 'last-frame'])
    parser.add_argument('record_id')
    parser.add_argument('--table', default='script_doc', choices=['script_doc'])
    parser.add_argument('--dry-run', action='store_true', help='只验证输入和配置，不提交图片任务')
    args = parser.parse_args()
    action = args.action
    record_id = args.record_id
    token = get_feishu_token()

    try:
        if action == 'render':
            result = render_shot(token, record_id, table=args.table, dry_run=args.dry_run)
        elif action == 'last-frame':
            if args.table != 'script_doc':
                raise Exception('last-frame 仅支持 --table script_doc')
            result = render_script_doc_last_frame(token, record_id, dry_run=args.dry_run)
        else:
            raise Exception(f'未知 action: {action}')
        if isinstance(result, dict):
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    except Exception as e:
        payload = build_error_payload(e, stage='generate_last_frame_image' if action == 'last-frame' else ('generate_shot_image' if action == 'render' else action))
        err = payload['message']
        log_event('ERROR', 'shot storyboard task failed', action=action, record_id=record_id, error=err, error_code=payload['error_code'], retryable=payload['retryable'])
        if args.dry_run:
            pass
        elif action == 'last-frame':
            fail_fields = {
                '尾帧图生成状态': '失败',
                '尾帧图错误信息': err,
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
        elif action == 'render' and args.table == 'script_doc':
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
                '分镜图生成状态': '失败',
                '分镜图错误信息': err,
                '失败分类': classify_render_error(e),
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
        print(f"ERROR_CODE={payload['error_code']} RETRYABLE={str(payload['retryable']).lower()} MESSAGE={err}")
        sys.exit(1)


if __name__ == '__main__':
    main()
