#!/usr/bin/env python3
"""
逐镜头口播音频生成

用法:
  python3 tk_shot_voiceover.py <script_doc_shot_record_id>

读取 003-3「口播文本」→ 调用 MiniMax 同步语音合成 → 上传音频附件 → 写回音频状态/时长。
"""
import json
import mimetypes
import os
import sys
import time
from urllib.parse import urlparse

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *  # noqa: F401,F403


VOICEOVER_STAGE_NAME = '语音合成-MiniMax'
DEFAULT_API_BASE = 'https://api.aitgenne.com'
DEFAULT_MODEL = 'speech-2.8-turbo'
DEFAULT_VOICE_ID = 'moss_audio_ce44fc67-7ce3-11f0-8de5-96e35d26fb85'
BASE_WORK_DIR = os.path.join(WORKSPACE, 'shot_voiceover_work')

_TABLE_FIELDS_CACHE = {}


def ensure_voiceover_dir(record_id):
    task_dir = os.path.join(BASE_WORK_DIR, record_id)
    os.makedirs(task_dir, exist_ok=True)
    return task_dir


def redact_secret(text):
    if not text:
        return ''
    text = str(text)
    for marker in ('Bearer ', 'sk-'):
        if marker in text:
            text = text.replace(marker, marker + '[REDACTED]')
    return text[:500]


def get_table_field_names(token, table_id):
    cache_key = f'{APP_TOKEN}:{table_id}'
    if cache_key in _TABLE_FIELDS_CACHE:
        return _TABLE_FIELDS_CACHE[cache_key]

    field_names = set()
    page_token = None
    while True:
        url = f'https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/fields?page_size=100'
        if page_token:
            url += f'&page_token={page_token}'
        data = safe_request('get', url, headers=feishu_headers(token), timeout=30, max_attempts=3)
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


def parse_prompt_options(raw_prompt):
    raw_prompt = (raw_prompt or '').strip()
    if not raw_prompt:
        return {}
    try:
        data = json.loads(raw_prompt)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def find_stage_config(token, stage_name=VOICEOVER_STAGE_NAME):
    for rec in safe_list_records(token, TABLE_CONFIG):
        fields = rec.get('fields', {})
        if extract_text(fields.get('环节', '')).strip() == stage_name:
            options = parse_prompt_options(extract_text(fields.get('提示词', '')))
            return {
                'record_id': rec.get('record_id'),
                'model': extract_text(fields.get('模型名称', '')).strip() or DEFAULT_MODEL,
                'api_key': extract_text(fields.get('API Key', '')).strip() or os.environ.get('MINIMAX_TTS_API_KEY', '').strip(),
                'api_base': extract_text(fields.get('API 代理地址', '')).strip() or os.environ.get('MINIMAX_TTS_API_BASE', '').strip() or DEFAULT_API_BASE,
                'options': options,
            }
    return {
        'record_id': None,
        'model': os.environ.get('MINIMAX_TTS_MODEL', DEFAULT_MODEL),
        'api_key': os.environ.get('MINIMAX_TTS_API_KEY', '').strip(),
        'api_base': os.environ.get('MINIMAX_TTS_API_BASE', DEFAULT_API_BASE).strip(),
        'options': {},
    }


def build_t2a_url(api_base):
    base = (api_base or DEFAULT_API_BASE).strip().rstrip('/')
    parsed = urlparse(base)
    path = parsed.path.rstrip('/')
    if path.endswith('/t2a_v2'):
        return base
    if path.endswith('/minimax/v1'):
        return f'{base}/t2a_v2'
    if path == '/v1':
        origin = f'{parsed.scheme}://{parsed.netloc}'
        return f'{origin}/minimax/v1/t2a_v2'
    return f'{base}/minimax/v1/t2a_v2'


def normalize_audio_length_seconds(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    if number <= 0:
        return 0
    return round(number / 1000, 3) if number > 60 else round(number, 3)


def build_minimax_payload(text, config):
    options = config.get('options') or {}
    voice_setting = dict(options.get('voice_setting') or {})
    if not voice_setting.get('voice_id'):
        voice_setting['voice_id'] = options.get('voice_id') or os.environ.get('MINIMAX_TTS_VOICE_ID') or DEFAULT_VOICE_ID

    for key in ('speed', 'vol', 'pitch', 'emotion'):
        if key in options and key not in voice_setting:
            voice_setting[key] = options[key]

    audio_setting = {
        'sample_rate': int(options.get('sample_rate', 32000)),
        'bitrate': int(options.get('bitrate', 128000)),
        'format': options.get('format', 'mp3'),
        'channel': int(options.get('channel', 1)),
    }
    if isinstance(options.get('audio_setting'), dict):
        audio_setting.update(options['audio_setting'])

    payload = {
        'model': config.get('model') or DEFAULT_MODEL,
        'text': text,
        'voice_setting': voice_setting,
        'audio_setting': audio_setting,
    }
    language_boost = options.get('language_boost', 'Thai')
    if language_boost:
        payload['language_boost'] = language_boost
    if options.get('subtitle_enable') is not None:
        payload['subtitle_enable'] = bool(options.get('subtitle_enable'))
    return payload


def apply_record_voice_options(config, record_fields):
    merged = dict(config)
    options = dict(config.get('options') or {})
    record_voice_id = extract_text(record_fields.get('口播音色ID', '')).strip()
    if record_voice_id:
        options['voice_id'] = record_voice_id
    merged['options'] = options
    return merged


def decode_audio_response(data):
    base_resp = data.get('base_resp') if isinstance(data, dict) else {}
    if isinstance(base_resp, dict) and int(base_resp.get('status_code', 0) or 0) != 0:
        raise Exception(f"MiniMax返回失败: {base_resp.get('status_msg', '')}")

    audio_value = ((data.get('data') or {}).get('audio') or data.get('audio') or '').strip()
    if not audio_value:
        raise Exception('MiniMax 未返回音频内容')

    if audio_value.startswith('http://') or audio_value.startswith('https://'):
        resp = requests.get(audio_value, timeout=120)
        resp.raise_for_status()
        return resp.content

    try:
        return bytes.fromhex(audio_value)
    except ValueError as exc:
        raise Exception(f'MiniMax 音频 hex 解码失败: {exc}') from exc


def synthesize_voiceover(text, config):
    if not config.get('api_key'):
        raise Exception('语音合成-MiniMax 配置缺少 API Key')
    url = build_t2a_url(config.get('api_base'))
    payload = build_minimax_payload(text, config)
    headers = {
        'Authorization': f"Bearer {config['api_key']}",
        'Content-Type': 'application/json',
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=180)
    try:
        data = resp.json()
    except Exception as exc:
        raise Exception(f'MiniMax 响应不是 JSON: HTTP {resp.status_code}') from exc
    if resp.status_code >= 400:
        raise Exception(f"MiniMax HTTP {resp.status_code}: {redact_secret(data)}")

    audio_bytes = decode_audio_response(data)
    extra = data.get('extra_info') or {}
    return {
        'audio_bytes': audio_bytes,
        'duration_sec': normalize_audio_length_seconds(extra.get('audio_length')),
        'format': extra.get('audio_format') or (payload.get('audio_setting') or {}).get('format') or 'mp3',
        'trace_id': data.get('trace_id', ''),
    }


def upload_audio_to_feishu(token, file_path, file_name):
    mime_type = mimetypes.guess_type(file_name)[0] or 'audio/mpeg'
    with open(file_path, 'rb') as f:
        resp = requests.post(
            'https://open.feishu.cn/open-apis/drive/v1/medias/upload_all',
            headers={'Authorization': f'Bearer {token}'},
            data={
                'file_name': file_name,
                'parent_type': 'bitable_file',
                'parent_node': APP_TOKEN,
                'size': str(os.path.getsize(file_path)),
            },
            files={'file': (file_name, f, mime_type)},
            timeout=180,
        )
    data = resp.json()
    if data.get('code') != 0:
        raise Exception(f"飞书上传音频失败: {data.get('msg')}")
    return data['data']['file_token']


def resolve_voiceover_table(table='script_doc'):
    if table in ('script_doc', 'script_doc_shots', TABLE_SCRIPT_DOC_SHOTS):
        if not TABLE_SCRIPT_DOC_SHOTS:
            raise Exception('config.json 尚未配置 script_doc_shots 表 ID')
        return TABLE_SCRIPT_DOC_SHOTS
    raise Exception('不再支持旧 shot_storyboard 表，请使用 script_doc')


def generate_voiceover(token, record_id, table='script_doc'):
    table_id = resolve_voiceover_table(table)
    fields = safe_get_record(token, table_id, record_id)
    voiceover_text = extract_text(fields.get('口播文本', '')).strip()
    if not voiceover_text:
        success_fields = {
            '口播音频状态': '成功',
            '口播音频时长秒': 0,
            '口播音频错误信息': '',
        }
        safe_update_record(token, table_id, record_id, filter_existing_fields(token, table_id, success_fields))
        log_event('INFO', 'shot voiceover skipped empty text', record_id=record_id)
        return

    safe_update_record(
        token,
        table_id,
        record_id,
        filter_existing_fields(token, table_id, {'口播音频状态': '生成中', '口播音频错误信息': ''}),
    )

    config = apply_record_voice_options(find_stage_config(token), fields)
    result = with_retry(lambda: synthesize_voiceover(voiceover_text, config), max_attempts=2, label='minimax tts')
    audio_bytes = result['audio_bytes']
    if len(audio_bytes) < 1000:
        raise Exception('MiniMax 返回音频过小')

    task_dir = ensure_voiceover_dir(record_id)
    ext = str(result.get('format') or 'mp3').lower().lstrip('.')
    out_path = os.path.join(task_dir, f'{record_id}_voiceover.{ext}')
    with open(out_path, 'wb') as f:
        f.write(audio_bytes)

    file_token = with_retry(
        lambda: upload_audio_to_feishu(token, out_path, os.path.basename(out_path)),
        max_attempts=3,
        label='upload voiceover audio to feishu',
    )
    success_fields = {
        '口播音频路径': out_path,
        '口播音频时长秒': result.get('duration_sec') or 0,
        '口播音频状态': '成功',
        '口播音频错误信息': '',
        '口播音频FileToken': file_token,
        '生成时间': int(time.time() * 1000),
    }
    safe_update_record(token, table_id, record_id, filter_existing_fields(token, table_id, success_fields))
    try:
        safe_update_record(
            token,
            table_id,
            record_id,
            filter_existing_fields(token, table_id, {'口播音频': [{'file_token': file_token}]}),
            max_attempts=1,
        )
    except Exception as e:
        safe_update_record(token, table_id, record_id, filter_existing_fields(token, table_id, {
            '口播音频错误信息': f'口播音频附件写回失败，但本地音频已生成: {redact_secret(str(e))[:300]}',
        }))
    log_event('INFO', 'shot voiceover success', record_id=record_id, duration_sec=result.get('duration_sec'), trace_id=result.get('trace_id'))
    print(f'✅ 口播音频生成完成: {record_id}')


def classify_voiceover_error(err):
    payload = build_error_payload(err, stage='generate_voiceover')
    mapping = {
        'CONFIG_INVALID': '配置错误',
        'INPUT_MISSING': '输入缺失',
        'UPLOAD_FAILED': '上传飞书失败',
        'WRITEBACK_FAILED': '写回失败',
        'UPSTREAM_NETWORK': '上游网络异常',
        'UPSTREAM_RATE_LIMIT': '上游限流',
        'RUNTIME_BUG': '运行时bug',
    }
    return mapping.get(payload['error_code'], '运行时bug')


def main():
    import argparse
    parser = argparse.ArgumentParser(description='逐镜头口播音频生成')
    parser.add_argument('record_id')
    parser.add_argument('--table', default='script_doc', choices=['script_doc'])
    args = parser.parse_args()
    record_id = args.record_id
    token = get_feishu_token()
    table_id = None
    try:
        table_id = resolve_voiceover_table(args.table)
        generate_voiceover(token, record_id, table=args.table)
    except Exception as e:
        payload = build_error_payload(e, stage='generate_voiceover')
        err = redact_secret(payload['message'])
        log_event('ERROR', 'shot voiceover task failed', record_id=record_id, error=err, error_code=payload['error_code'], retryable=payload['retryable'])
        try:
            fail_fields = {
                '口播音频状态': '失败',
                '口播音频错误信息': err,
                '失败分类': classify_voiceover_error(e),
            }
            target_table = table_id or TABLE_SCRIPT_DOC_SHOTS
            safe_update_record(token, target_table, record_id, filter_existing_fields(token, target_table, fail_fields))
        except Exception:
            pass
        print(f"ERROR_CODE={payload['error_code']} RETRYABLE={str(payload['retryable']).lower()} MESSAGE={err}")
        sys.exit(1)


if __name__ == '__main__':
    main()
