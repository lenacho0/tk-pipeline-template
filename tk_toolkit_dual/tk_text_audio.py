#!/usr/bin/env python3
"""
独立文案转音频

用法:
  python3 tk_text_audio.py <text_audio_record_id>

读取「初始化-口播音频生成」里的文案和音色，调用 MiniMax 语音合成，上传音频附件。
"""
import os
import re
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *  # noqa: F401,F403
from tk_shot_voiceover import (
    apply_record_voice_options,
    filter_existing_fields,
    find_stage_config,
    redact_secret,
    synthesize_voiceover,
    upload_audio_to_feishu,
)


BASE_WORK_DIR = os.path.join(WORKSPACE, 'text_audio_work')


def ensure_text_audio_dir(record_id):
    task_dir = os.path.join(BASE_WORK_DIR, record_id)
    os.makedirs(task_dir, exist_ok=True)
    return task_dir


def build_audio_filename(record_id, title, ext):
    ext = str(ext or 'mp3').lower().lstrip('.') or 'mp3'
    safe_title = re.sub(r'[\\/:*?"<>|\r\n\t]+', '_', extract_text(title).strip())
    safe_title = re.sub(r'\s+', ' ', safe_title)
    safe_title = re.sub(r'\s*_\s*', '_', safe_title)
    safe_title = re.sub(r'_+', '_', safe_title).strip(' ._')
    name = safe_title or f'{record_id}_text_audio'
    return f'{name[:120]}.{ext}'


def resolve_linked_voice_id(token, fields):
    linked_ids = extract_linked_record_ids(fields.get('选择音色'))
    if not linked_ids:
        return ''

    voice_fields = safe_get_record(token, TABLE_VOICE_LIBRARY, linked_ids[0])
    voice_id = extract_text(voice_fields.get('Voice ID', '')).strip()
    if not voice_id:
        raise Exception('已选择音色，但音色库 Voice ID 为空，请先生成音色')

    status = extract_text(voice_fields.get('生成状态', '')).strip()
    if status and status != '成功':
        raise Exception(f'已选择音色，但音色生成状态不是成功: {status}')
    return voice_id


def apply_text_audio_voice_options(token, config, fields):
    merged = apply_record_voice_options(config, {'口播音色ID': extract_text(fields.get('音色ID', '')).strip()})
    options = dict(merged.get('options') or {})
    linked_voice_id = resolve_linked_voice_id(token, fields)
    if linked_voice_id:
        options['voice_id'] = linked_voice_id
        merged['options'] = options
    return merged


def get_tmp_download_url(token, file_token):
    if not file_token:
        return ''
    resp = requests.get(
        f'https://open.feishu.cn/open-apis/drive/v1/medias/batch_get_tmp_download_url?file_tokens={file_token}',
        headers={'Authorization': f'Bearer {token}'},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get('code') != 0:
        raise Exception(f"获取音频下载链接失败: {data.get('msg')}")
    items = (data.get('data') or {}).get('tmp_download_urls') or []
    return (items[0] or {}).get('tmp_download_url', '') if items else ''


def generate_text_audio(token, record_id):
    if not TABLE_TEXT_AUDIO:
        raise Exception('config.json 尚未配置 text_audio 表 ID')

    fields = safe_get_record(token, TABLE_TEXT_AUDIO, record_id)
    text = extract_text(fields.get('文案', '')).strip()
    if not text:
        raise Exception('文案为空')

    safe_update_record(
        token,
        TABLE_TEXT_AUDIO,
        record_id,
        filter_existing_fields(token, TABLE_TEXT_AUDIO, {'生成状态': '生成中', '错误信息': ''}),
    )

    config = apply_text_audio_voice_options(token, find_stage_config(token), fields)
    result = with_retry(lambda: synthesize_voiceover(text, config), max_attempts=2, label='minimax text audio')
    audio_bytes = result['audio_bytes']
    if len(audio_bytes) < 1000:
        raise Exception('MiniMax 返回音频过小')

    task_dir = ensure_text_audio_dir(record_id)
    ext = str(result.get('format') or 'mp3').lower().lstrip('.')
    file_name = build_audio_filename(record_id, fields.get('文案标题', ''), ext)
    out_path = os.path.join(task_dir, file_name)
    with open(out_path, 'wb') as f:
        f.write(audio_bytes)

    file_token = with_retry(
        lambda: upload_audio_to_feishu(token, out_path, file_name),
        max_attempts=3,
        label='upload text audio to feishu',
    )
    success_fields = {
        '音频路径': out_path,
        '音频时长秒': result.get('duration_sec') or 0,
        '生成状态': '成功',
        '错误信息': '',
        '生成时间': int(time.time() * 1000),
        '音频FileToken': file_token,
    }
    try:
        success_fields['音频下载链接'] = get_tmp_download_url(token, file_token)
    except Exception as e:
        success_fields['错误信息'] = f'音频已生成，但下载链接获取失败: {redact_secret(str(e))[:300]}'
    safe_update_record(token, TABLE_TEXT_AUDIO, record_id, filter_existing_fields(token, TABLE_TEXT_AUDIO, success_fields))
    try:
        safe_update_record(
            token,
            TABLE_TEXT_AUDIO,
            record_id,
            filter_existing_fields(token, TABLE_TEXT_AUDIO, {'生成音频': [{'file_token': file_token}]}),
            max_attempts=1,
        )
    except Exception as e:
        message = '附件字段受限，已写入音频下载链接' if success_fields.get('音频下载链接') else f'音频附件写回失败，但本地音频已生成: {redact_secret(str(e))[:300]}'
        safe_update_record(token, TABLE_TEXT_AUDIO, record_id, filter_existing_fields(token, TABLE_TEXT_AUDIO, {
            '错误信息': message,
        }))
    log_event('INFO', 'text audio success', record_id=record_id, duration_sec=result.get('duration_sec'), trace_id=result.get('trace_id'))
    print(f'✅ 文案音频生成完成: {record_id}')


def classify_text_audio_error(err):
    payload = build_error_payload(err, stage='generate_text_audio')
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
    if len(sys.argv) < 2:
        print('用法: python3 tk_text_audio.py <text_audio_record_id>')
        sys.exit(1)

    record_id = sys.argv[1]
    token = get_feishu_token()
    try:
        generate_text_audio(token, record_id)
    except Exception as e:
        payload = build_error_payload(e, stage='generate_text_audio')
        err = redact_secret(payload['message'])
        log_event('ERROR', 'text audio task failed', record_id=record_id, error=err, error_code=payload['error_code'], retryable=payload['retryable'])
        try:
            fail_fields = {
                '生成状态': '失败',
                '错误信息': err,
                '失败分类': classify_text_audio_error(e),
            }
            safe_update_record(token, TABLE_TEXT_AUDIO, record_id, filter_existing_fields(token, TABLE_TEXT_AUDIO, fail_fields))
        except Exception:
            pass
        print(f"ERROR_CODE={payload['error_code']} RETRYABLE={str(payload['retryable']).lower()} MESSAGE={err}")
        sys.exit(1)


if __name__ == '__main__':
    main()
