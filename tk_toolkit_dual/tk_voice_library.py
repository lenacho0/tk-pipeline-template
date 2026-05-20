#!/usr/bin/env python3
"""
MiniMax 音色库生成

用法:
  python3 tk_voice_library.py <voice_library_record_id>

支持三种生成方式：
- 上传音频复刻：参考音频 -> files/upload -> voice_clone -> Voice ID
- 文本描述生成：音色描述 + 试听文本 -> voice_design -> Voice ID
- 手动填写Voice ID：仅校验字段并标记成功
"""
import mimetypes
import os
import re
import sys
import time
from urllib.parse import urlparse

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *  # noqa: F401,F403
from tk_shot_voiceover import (
    decode_audio_response,
    find_stage_config,
    filter_existing_fields,
    normalize_audio_length_seconds,
    redact_secret,
    upload_audio_to_feishu,
)


BASE_WORK_DIR = os.path.join(WORKSPACE, 'voice_library_work')
DEFAULT_PREVIEW_TEXT = 'สวัสดีค่ะ วันนี้เราจะมาแนะนำสินค้าที่ช่วยให้ชีวิตง่ายขึ้น'


def ensure_voice_dir(record_id):
    task_dir = os.path.join(BASE_WORK_DIR, record_id)
    os.makedirs(task_dir, exist_ok=True)
    return task_dir


def build_minimax_endpoint(api_base, endpoint):
    base = (api_base or 'https://api.aitgenne.com').strip().rstrip('/')
    endpoint = endpoint.strip().lstrip('/')
    parsed = urlparse(base)
    path = parsed.path.rstrip('/')
    if path.endswith('/minimax/v1'):
        return f'{base}/{endpoint}'
    if path == '/v1':
        return f'{parsed.scheme}://{parsed.netloc}/minimax/v1/{endpoint}'
    return f'{base}/minimax/v1/{endpoint}'


def generate_clone_voice_id(record_id):
    suffix = re.sub(r'[^A-Za-z0-9_-]+', '_', str(record_id or 'record')).strip('_') or 'record'
    return f'tkvoice_{suffix}_{int(time.time())}'


def check_base_resp(data, label):
    base_resp = data.get('base_resp') if isinstance(data, dict) else {}
    if isinstance(base_resp, dict) and int(base_resp.get('status_code', 0) or 0) != 0:
        raise Exception(f"{label}失败: {base_resp.get('status_msg', '')}")


def parse_voice_design_response(data):
    check_base_resp(data, 'Voice Design')
    voice_id = str(data.get('voice_id') or '').strip()
    if not voice_id:
        raise Exception('Voice Design 未返回 voice_id')
    trial_audio = str(data.get('trial_audio') or '').strip()
    audio_bytes = bytes.fromhex(trial_audio) if trial_audio else b''
    return voice_id, audio_bytes


def parse_minimax_json_response(resp, label):
    try:
        return resp.json()
    except ValueError as e:
        content_type = ''
        try:
            content_type = resp.headers.get('content-type', '')
        except Exception:
            pass
        body_preview = redact_secret((getattr(resp, 'text', '') or '')[:300])
        raise Exception(
            f"{label} returned non-JSON HTTP {getattr(resp, 'status_code', 'unknown')}: "
            f"content-type={content_type or 'unknown'} body={body_preview or '<empty>'}"
        ) from e


def build_upload_clone_endpoints(api_base):
    primary = build_minimax_endpoint(api_base, 'files/upload')
    candidates = [primary]
    if primary.endswith('/files/upload'):
        candidates.append(primary[:-len('/upload')])
    return list(dict.fromkeys(candidates))


def upload_clone_audio(file_path, config):
    if not config.get('api_key'):
        raise Exception('MiniMax语音合成配置缺少 API Key')
    mime_type = mimetypes.guess_type(file_path)[0] or 'audio/mpeg'
    last_error = None
    for url in build_upload_clone_endpoints(config.get('api_base')):
        try:
            with open(file_path, 'rb') as f:
                resp = requests.post(
                    url,
                    headers={'Authorization': f"Bearer {config['api_key']}"},
                    data={'purpose': 'voice_clone'},
                    files={'file': (os.path.basename(file_path), f, mime_type)},
                    timeout=180,
                )
            data = parse_minimax_json_response(resp, 'MiniMax upload')
            if resp.status_code >= 400:
                raise Exception(f"MiniMax upload HTTP {resp.status_code}: {redact_secret(data)}")
            check_base_resp(data, '上传复刻音频')
            file_id = (data.get('file') or {}).get('file_id')
            if not file_id:
                raise Exception('上传复刻音频未返回 file_id')
            return file_id
        except Exception as e:
            last_error = e
            log_event('WARN', 'MiniMax upload endpoint failed', endpoint=url, error=redact_secret(str(e))[:500])
    raise last_error


def clone_voice(file_id, voice_id, preview_text, config):
    if not config.get('api_key'):
        raise Exception('MiniMax语音合成配置缺少 API Key')
    url = build_minimax_endpoint(config.get('api_base'), 'voice_clone')
    options = config.get('options') or {}
    payload = {
        'file_id': int(file_id),
        'voice_id': voice_id,
        'need_noise_reduction': bool(options.get('need_noise_reduction', False)),
        'need_volume_normalization': bool(options.get('need_volume_normalization', False)),
    }
    if preview_text:
        payload.update({
            'text': preview_text,
            'model': config.get('model') or 'speech-2.8-turbo',
            'language_boost': options.get('language_boost', 'Thai'),
        })
    resp = requests.post(
        url,
        headers={'Authorization': f"Bearer {config['api_key']}", 'Content-Type': 'application/json'},
        json=payload,
        timeout=180,
    )
    data = parse_minimax_json_response(resp, 'MiniMax clone')
    if resp.status_code >= 400:
        raise Exception(f"MiniMax clone HTTP {resp.status_code}: {redact_secret(data)}")
    check_base_resp(data, 'Voice Clone')
    return str(data.get('demo_audio') or '').strip()


def design_voice(prompt, preview_text, config):
    if not config.get('api_key'):
        raise Exception('MiniMax语音合成配置缺少 API Key')
    if not prompt:
        raise Exception('音色描述为空')
    if not preview_text:
        raise Exception('试听文本为空')
    url = build_minimax_endpoint(config.get('api_base'), 'voice_design')
    resp = requests.post(
        url,
        headers={'Authorization': f"Bearer {config['api_key']}", 'Content-Type': 'application/json'},
        json={'prompt': prompt, 'preview_text': preview_text},
        timeout=180,
    )
    data = parse_minimax_json_response(resp, 'MiniMax design')
    if resp.status_code >= 400:
        raise Exception(f"MiniMax design HTTP {resp.status_code}: {redact_secret(data)}")
    return parse_voice_design_response(data)


def download_feishu_media(token, file_token, save_path):
    resp = requests.get(
        f'https://open.feishu.cn/open-apis/drive/v1/medias/{file_token}/download',
        headers={'Authorization': f'Bearer {token}'},
        timeout=180,
        stream=True,
    )
    if resp.status_code != 200:
        raise Exception(f'飞书附件下载失败: HTTP {resp.status_code}')
    with open(save_path, 'wb') as f:
        for chunk in resp.iter_content(8192):
            if chunk:
                f.write(chunk)
    return save_path


def download_url_to_file(url, save_path):
    resp = requests.get(url, timeout=180, stream=True)
    resp.raise_for_status()
    with open(save_path, 'wb') as f:
        for chunk in resp.iter_content(8192):
            if chunk:
                f.write(chunk)
    return save_path


def attachment_file_token(value):
    if isinstance(value, list) and value:
        first = value[0]
        if isinstance(first, dict):
            return first.get('file_token') or ''
    return ''


def build_reference_audio_path(task_dir, record_id, attachment_value):
    ext = ''
    if isinstance(attachment_value, list) and attachment_value:
        first = attachment_value[0]
        if isinstance(first, dict):
            name = os.path.basename(str(first.get('name') or ''))
            candidate_ext = os.path.splitext(name)[1].lower()
            if candidate_ext in ('.mp3', '.m4a', '.wav'):
                ext = candidate_ext
    return os.path.join(task_dir, f'{record_id}_reference_audio{ext}')


def run_voice_library_record(token, record_id):
    if not TABLE_VOICE_LIBRARY:
        raise Exception('config.json 尚未配置 voice_library 表 ID')
    fields = safe_get_record(token, TABLE_VOICE_LIBRARY, record_id)
    method = extract_text(fields.get('生成方式', '')).strip()
    current_voice_id = extract_text(fields.get('Voice ID', '')).strip()
    preview_text = extract_text(fields.get('试听文本', '')).strip() or DEFAULT_PREVIEW_TEXT

    safe_update_record(token, TABLE_VOICE_LIBRARY, record_id, filter_existing_fields(token, TABLE_VOICE_LIBRARY, {
        '生成状态': '生成中',
        '错误信息': '',
    }))

    config = find_stage_config(token)
    updates = {'生成状态': '成功', '错误信息': ''}
    attachment_updates = {}
    task_dir = ensure_voice_dir(record_id)

    if method == '手动填写Voice ID':
        if not current_voice_id:
            raise Exception('手动填写Voice ID 模式下 Voice ID 为空')
        updates['Voice ID'] = current_voice_id

    elif method == '文本描述生成':
        prompt = extract_text(fields.get('音色描述', '')).strip()
        voice_id, audio_bytes = with_retry(lambda: design_voice(prompt, preview_text, config), max_attempts=2, label='voice design')
        updates['Voice ID'] = voice_id
        if audio_bytes:
            out_path = os.path.join(task_dir, f'{record_id}_voice_design_preview.mp3')
            with open(out_path, 'wb') as f:
                f.write(audio_bytes)
            updates['试听音频路径'] = out_path
            try:
                file_token = upload_audio_to_feishu(token, out_path, os.path.basename(out_path))
                attachment_updates['试听音频'] = [{'file_token': file_token}]
            except Exception as e:
                updates['错误信息'] = f'试听音频上传失败，但 Voice ID 已生成: {redact_secret(str(e))[:300]}'

    elif method == '上传音频复刻':
        file_token = attachment_file_token(fields.get('参考音频'))
        if not file_token:
            raise Exception('参考音频为空')
        ref_path = build_reference_audio_path(task_dir, record_id, fields.get('参考音频'))
        download_feishu_media(token, file_token, ref_path)
        voice_id = current_voice_id or generate_clone_voice_id(record_id)
        file_id = with_retry(lambda: upload_clone_audio(ref_path, config), max_attempts=2, label='upload clone audio')
        demo_url = with_retry(lambda: clone_voice(file_id, voice_id, preview_text, config), max_attempts=2, label='voice clone')
        updates['Voice ID'] = voice_id
        updates['MiniMax File ID'] = str(file_id)
        if demo_url:
            demo_path = os.path.join(task_dir, f'{record_id}_voice_clone_preview.mp3')
            download_url_to_file(demo_url, demo_path)
            updates['试听音频路径'] = demo_path
            try:
                preview_token = upload_audio_to_feishu(token, demo_path, os.path.basename(demo_path))
                attachment_updates['试听音频'] = [{'file_token': preview_token}]
            except Exception as e:
                updates['错误信息'] = f'试听音频上传失败，但 Voice ID 已生成: {redact_secret(str(e))[:300]}'
    else:
        raise Exception(f'未知生成方式: {method}')

    safe_update_record(token, TABLE_VOICE_LIBRARY, record_id, filter_existing_fields(token, TABLE_VOICE_LIBRARY, updates))
    if attachment_updates:
        try:
            safe_update_record(token, TABLE_VOICE_LIBRARY, record_id, filter_existing_fields(token, TABLE_VOICE_LIBRARY, attachment_updates), max_attempts=1)
        except Exception as e:
            safe_update_record(token, TABLE_VOICE_LIBRARY, record_id, filter_existing_fields(token, TABLE_VOICE_LIBRARY, {
                '错误信息': f'试听音频附件写回失败，但 Voice ID 已生成: {redact_secret(str(e))[:300]}',
            }))
    log_event('INFO', 'voice library generation success', record_id=record_id, method=method, voice_id=updates.get('Voice ID'))
    print(f"✅ 音色生成完成: {updates.get('Voice ID', current_voice_id)}")


def main():
    if len(sys.argv) < 2:
        print('用法: python3 tk_voice_library.py <voice_library_record_id>')
        sys.exit(1)
    record_id = sys.argv[1]
    token = get_feishu_token()
    try:
        run_voice_library_record(token, record_id)
    except Exception as e:
        payload = build_error_payload(e, stage='generate_voice_id')
        err = redact_secret(payload['message'])
        log_event('ERROR', 'voice library generation failed', record_id=record_id, error=err, error_code=payload['error_code'])
        try:
            safe_update_record(token, TABLE_VOICE_LIBRARY, record_id, filter_existing_fields(token, TABLE_VOICE_LIBRARY, {
                '生成状态': '失败',
                '错误信息': err,
            }))
        except Exception:
            pass
        print(f"ERROR_CODE={payload['error_code']} RETRYABLE={str(payload['retryable']).lower()} MESSAGE={err}")
        sys.exit(1)


if __name__ == '__main__':
    main()
