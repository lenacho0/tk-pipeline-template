#!/usr/bin/env python3
import json
import os
import sys
import time
import logging
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *
from pet_reference_downloader import download_reference_video
from pet_reference_prompt import build_pet_reference_prompt
from pet_reference_schema import parse_and_normalize_json

TABLE_PET_REFERENCE = TABLE_PET_REFERENCE_V1
PET_REFERENCE_CONFIG_RECORD_ID = CONFIG_RECORDS.get('pet_reference_analysis', '')
WORKDIR = os.path.join(WORKSPACE, 'pet_reference_downloads')


def find_config_record_by_stage(token, stage_name):
    records = safe_list_records(token, TABLE_CONFIG)
    for rec in records:
        fields = rec.get('fields', {})
        if extract_text(fields.get('环节', '')).strip() == stage_name:
            return rec
    return None


def get_pet_reference_config(token):
    if PET_REFERENCE_CONFIG_RECORD_ID:
        fields = safe_get_record(token, TABLE_CONFIG, PET_REFERENCE_CONFIG_RECORD_ID)
    else:
        rec = find_config_record_by_stage(token, '宠物拟人参考视频深拆')
        if not rec:
            raise Exception('缺少配置环节: 宠物拟人参考视频深拆')
        fields = rec.get('fields', {})
    return {
        'model': extract_text(fields.get('模型名称', '')).strip() or 'gemini-3.1-pro-preview',
        'api_key': extract_text(fields.get('API Key', '')).strip(),
        'api_base': extract_text(fields.get('API 代理地址', '')).strip(),
        'prompt': extract_text(fields.get('提示词', '')).strip(),
    }


def make_url_field(url):
    url = extract_text(url).strip()
    if not url:
        return None
    return {'link': url, 'text': url}


def main():
    if len(sys.argv) < 2:
        print('用法: python3 tk_pet_reference_analyze.py <record_id>')
        sys.exit(1)
    if not TABLE_PET_REFERENCE:
        raise Exception('当前配置文件未配置 pet_reference_v1 table')

    record_id = sys.argv[1]
    token = get_feishu_token()
    fields = safe_get_record(token, TABLE_PET_REFERENCE, record_id)
    title = extract_text(fields.get('标题', '')) or extract_text(fields.get('任务标题', '')) or extract_text(fields.get('文本', ''))
    video_url = extract_text(fields.get('视频链接', '')).strip()
    if not video_url:
        raise Exception('视频链接为空')

    safe_update_record(token, TABLE_PET_REFERENCE, record_id, {
        'record_id': record_id,
        '下载状态': '下载中',
        '深度拆解状态': '待拆解',
        '下载错误信息': '',
        '深度拆解错误信息': ''
    })

    dl = download_reference_video(video_url, WORKDIR)
    if not dl.get('ok'):
        payload = {
            'record_id': record_id,
            '下载状态': '下载失败',
            '下载错误信息': extract_text(dl.get('error', '下载失败'))[:1000],
            '平台': dl.get('platform', 'Unknown')
        }
        normalized_url_field = make_url_field(dl.get('normalized_url', ''))
        if normalized_url_field:
            payload['标准化链接'] = normalized_url_field
        safe_update_record(token, TABLE_PET_REFERENCE, record_id, payload)
        payload = build_error_payload(dl.get('error', '下载失败'), stage='pet_reference_download')
        print(f"ERROR_CODE={payload['error_code']} RETRYABLE={str(payload['retryable']).lower()} MESSAGE={payload['message']}")
        sys.exit(1)

    payload = {
        'record_id': record_id,
        '下载状态': '下载成功',
        '深度拆解状态': '拆解中',
        '平台': dl.get('platform', 'Unknown'),
        '视频时长(秒)': dl.get('duration_sec', 0),
        '文件大小(MB)': dl.get('file_size_mb', 0),
        '下载错误信息': ''
    }
    normalized_url_field = make_url_field(dl.get('normalized_url', ''))
    if normalized_url_field:
        payload['标准化链接'] = normalized_url_field
    safe_update_record(token, TABLE_PET_REFERENCE, record_id, payload)

    cfg = get_pet_reference_config(token)
    if not cfg.get('api_key'):
        raise Exception('宠物拟人参考视频深拆缺少 API Key')

    from google import genai
    client = genai.Client(api_key=cfg['api_key'], http_options={'base_url': cfg.get('api_base') or 'https://aihubmix.com/gemini'})
    prompt = cfg.get('prompt') or build_pet_reference_prompt(
        source_url=video_url,
        normalized_url=dl.get('normalized_url', ''),
        duration_sec=dl.get('duration_sec', 0),
        file_size_mb=dl.get('file_size_mb', 0),
    )

    uploaded = with_retry(
        lambda: client.files.upload(file=dl['local_path']),
        max_attempts=3,
        label='gemini pet reference upload'
    )
    waited = 0
    while getattr(getattr(uploaded, 'state', None), 'name', '') == 'PROCESSING' and waited < 180:
        time.sleep(3)
        waited += 3
        uploaded = with_retry(
            lambda: client.files.get(name=uploaded.name),
            max_attempts=3,
            label='gemini pet reference upload poll'
        )
    if getattr(getattr(uploaded, 'state', None), 'name', '') != 'ACTIVE':
        raise Exception(f"视频文件上传后未激活: {getattr(getattr(uploaded, 'state', None), 'name', 'UNKNOWN')}")

    response = with_retry(
        lambda: client.models.generate_content(model=cfg['model'], contents=[uploaded, prompt, f'视频标题: {title}', f'视频链接: {video_url}']),
        max_attempts=3,
        label='gemini pet reference analyze'
    )
    text = getattr(response, 'text', '') or ''
    if not text.strip():
        raise Exception('Gemini 未返回分析结果')

    start = text.find('{')
    end = text.rfind('}')
    if start < 0 or end <= start:
        raise Exception('Gemini 未返回有效 JSON')
    payload = parse_and_normalize_json(text[start:end+1])
    payload['meta']['source_url'] = video_url
    payload['meta']['normalized_url'] = dl.get('normalized_url', '')
    payload['meta']['platform'] = dl.get('platform', 'Unknown')
    payload['meta']['analysis_model'] = cfg['model']
    payload['meta']['analyzed_at'] = datetime.now().astimezone().isoformat(timespec='seconds')
    payload['meta']['video_duration_sec'] = dl.get('duration_sec', 0)
    payload['meta']['file_size_mb'] = dl.get('file_size_mb', 0)

    safe_update_record(token, TABLE_PET_REFERENCE, record_id, {
        'record_id': record_id,
        '深度拆解状态': '拆解成功',
        '深度拆解错误信息': '',
        '分析模型': cfg['model'],
        '分析时间': int(datetime.now().timestamp() * 1000),
        '完整JSON分析结果': json.dumps(payload, ensure_ascii=False)
    })

    # ---- 中文翻译：保持 JSON 结构，值翻成中文，供人工阅读 ----
    try:
        from pet_reference_prompt import build_pet_reference_translation_prompt
        trans_prompt = build_pet_reference_translation_prompt(payload)
        trans_response = with_retry(
            lambda: client.models.generate_content(model=cfg['model'], contents=[trans_prompt]),
            max_attempts=3,
            label='gemini pet reference translate'
        )
        trans_text = getattr(trans_response, 'text', '') or ''
        if trans_text.strip():
            trans_start = trans_text.find('{')
            trans_end = trans_text.rfind('}')
            if trans_start >= 0 and trans_end > trans_start:
                translated_json = json.loads(trans_text[trans_start:trans_end+1])
                safe_update_record(token, TABLE_PET_REFERENCE, record_id, {
                    '完整JSON分析结果-中文翻译': json.dumps(translated_json, ensure_ascii=False, indent=2)
                })
            else:
                log_event('WARNING', 'translation response not valid JSON, skipping translation writeback',
                          record_id=record_id)
        else:
            log_event('WARNING', 'translation returned empty, skipping translation writeback',
                      record_id=record_id)
    except Exception as trans_err:
        log_event('WARNING', 'translation step failed, continuing without translation writeback',
                  record_id=record_id, error=str(trans_err)[:500])

    print(f'✅ 宠物拟人参考视频分析完成: {record_id}')


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        payload = build_error_payload(e, stage='pet_reference_analyze')
        try:
            token = get_feishu_token()
            if len(sys.argv) >= 2 and TABLE_PET_REFERENCE:
                safe_update_record(token, TABLE_PET_REFERENCE, sys.argv[1], {
                    'record_id': sys.argv[1],
                    '深度拆解状态': '拆解失败',
                    '深度拆解错误信息': payload['message'][:1000]
                })
        except Exception:
            pass
        print(f"ERROR_CODE={payload['error_code']} RETRYABLE={str(payload['retryable']).lower()} MESSAGE={payload['message']}")
        sys.exit(1)
