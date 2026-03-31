#!/usr/bin/env python3
"""
003表内视频生成：基于九宫格分镜图直接生成视频
用法: python3 tk_video_from_storyboard.py <record_id>
当前第一版：仅接入 ryan 实例中的 sora 选择
"""
import os, sys, time, requests
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *

WORK_DIR = os.path.join(WORKSPACE, 'video_from_storyboard_work')
POLL_INTERVAL = 15
MAX_POLL_TIME = 1800
DEFAULT_SECONDS = 12
DEFAULT_SIZE = '720x1280'
STAGE_PREFIX = '九宫格生成视频-'


def ensure_work_dir():
    os.makedirs(WORK_DIR, exist_ok=True)


def get_model_config_by_stage_name(token, stage_name):
    records = safe_list_records(token, TABLE_CONFIG)
    for rec in records:
        fields = rec.get('fields', {})
        if extract_text(fields.get('环节', '')).strip() == stage_name:
            return rec['record_id'], {
                'model': extract_text(fields.get('模型名称', '')),
                'api_key': extract_text(fields.get('API Key', '')),
                'api_base': extract_text(fields.get('API 代理地址', '')),
                'prompt': extract_text(fields.get('提示词', '')),
                'call_type': extract_text(fields.get('调用方式', '')),
                'fields': fields,
            }
    return None, None


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
        label='download storyboard attachment'
    )


def _download_or_raise(token, file_token, save_path):
    ok = download_attachment(token, file_token, save_path)
    if not ok:
        raise Exception(f'附件下载失败: {file_token}')
    return True


def upload_video_to_feishu(token, file_path, file_name):
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
            files={'file': (file_name, f, 'video/mp4')},
            timeout=300
        )
    data = resp.json()
    if data.get('code') != 0:
        raise Exception(f"飞书上传失败: {data.get('msg')}")
    return data['data']['file_token']


def parse_seconds(duration_text):
    try:
        seconds = int(''.join(c for c in (duration_text or '') if c.isdigit())) if duration_text else DEFAULT_SECONDS
        if seconds not in [4, 5, 8, 10, 12, 15, 25]:
            seconds = DEFAULT_SECONDS
        return seconds
    except Exception:
        return DEFAULT_SECONDS


def build_video_prompt(task_fields, prompt_template, script):
    existing_prompt = extract_text(task_fields.get('视频提示词', '')).strip()
    if existing_prompt:
        return existing_prompt
    if prompt_template:
        return prompt_template.replace('{script}', script).replace('{video_duration}', extract_text(task_fields.get('视频时长', '12s')))
    return f"Create a professional vertical product video based on this storyboard. Script:\n{script}"


def submit_sora_task(api_base, api_key, prompt, model_name, image_path, seconds=DEFAULT_SECONDS, size=DEFAULT_SIZE):
    url = api_base.rstrip('/')
    headers = {'Authorization': api_key}
    form_data = {
        'prompt': (None, prompt),
        'model': (None, model_name),
        'seconds': (None, str(seconds)),
        'size': (None, size),
    }
    if image_path and os.path.exists(image_path):
        with open(image_path, 'rb') as img:
            form_data['image'] = (os.path.basename(image_path), img, 'image/png')
            resp = requests.post(url, headers=headers, files=form_data, timeout=120)
    else:
        resp = requests.post(url, headers=headers, files=form_data, timeout=120)

    data = resp.json()
    if 'id' in data:
        return data['id'], data
    raise Exception(f'Sora任务提交失败: {data}')


def poll_sora_task(api_base, api_key, video_id):
    url = f"{api_base.rstrip('/').rsplit('/', 2)[0]}/videos/{video_id}"
    headers = {'Authorization': api_key}
    start = time.time()
    while time.time() - start < MAX_POLL_TIME:
        resp = requests.get(url, headers=headers, timeout=30)
        data = resp.json()
        status = data.get('status', '')
        if status in ('completed', 'succeeded'):
            return data
        if status in ('failed', 'error'):
            raise Exception(f"Sora生成失败: {data.get('error', '未知错误')}")
        time.sleep(POLL_INTERVAL)
    raise Exception(f'Sora任务超时（{MAX_POLL_TIME}秒），任务ID: {video_id}')


def download_sora_video(api_base, api_key, video_id, save_path):
    url = f"{api_base.rstrip('/').rsplit('/', 2)[0]}/videos/{video_id}/content"
    headers = {'Authorization': api_key}
    resp = requests.get(url, headers=headers, stream=True, allow_redirects=True, timeout=300)
    if resp.status_code != 200:
        raise Exception(f'视频下载失败: HTTP {resp.status_code}')
    with open(save_path, 'wb') as f:
        for chunk in resp.iter_content(8192):
            f.write(chunk)
    if os.path.getsize(save_path) < 10000:
        raise Exception('视频下载成功但文件过小')
    return save_path


def main():
    if len(sys.argv) < 2:
        print('用法: python3 tk_video_from_storyboard.py <record_id>')
        sys.exit(1)
    record_id = sys.argv[1]
    ensure_work_dir()
    token = get_feishu_token()

    try:
        log_event('INFO', 'video-from-storyboard task start', record_id=record_id)
        task = safe_get_record(token, TABLE_SCRIPT_GEN, record_id)

        if extract_text(task.get('是否生成视频', '')).strip() != '是':
            raise Exception('未开启视频生成')

        video_model = extract_text(task.get('视频模型', '')).strip().lower()
        if not video_model:
            raise Exception('未选择视频模型')
        if video_model != 'sora':
            raise Exception(f'第一版仅支持 sora，当前选择: {video_model}')

        stage_name = f'{STAGE_PREFIX}{video_model}'
        cfg_record_id, config = get_model_config_by_stage_name(token, stage_name)
        if not config:
            raise Exception(f'找不到视频模型配置: {stage_name}')

        if not config.get('api_key'):
            raise Exception(f'视频模型配置缺少 API Key: {stage_name}')

        script = extract_text(task.get('生成的脚本', '')).strip()
        if not script:
            raise Exception('无脚本内容')

        attachments = task.get('分镜图', [])
        if not attachments or not isinstance(attachments, list):
            raise Exception('无分镜图附件')
        file_token = attachments[0].get('file_token', '')
        if not file_token:
            raise Exception('分镜图附件缺少 file_token')

        safe_update_record(token, TABLE_SCRIPT_GEN, record_id, {
            '视频生成状态': '生成中',
            '视频错误信息': '',
        })

        storyboard_path = os.path.join(WORK_DIR, f'{record_id}_storyboard.png')
        safe_download_attachment(token, file_token, storyboard_path)

        prompt = build_video_prompt(task, config.get('prompt', ''), script)
        safe_update_record(token, TABLE_SCRIPT_GEN, record_id, {
            '视频提示词': prompt[:10000],
        })

        seconds = parse_seconds(extract_text(task.get('视频时长', '12s')))
        model_name = config.get('model') or 'sora-2-all'
        api_base = config.get('api_base') or 'https://own-jarvis-api.com/v1/video/create'

        video_id, _ = submit_sora_task(
            api_base=api_base,
            api_key=config['api_key'],
            prompt=prompt,
            model_name=model_name,
            image_path=storyboard_path,
            seconds=seconds,
            size=DEFAULT_SIZE,
        )
        safe_update_record(token, TABLE_SCRIPT_GEN, record_id, {
            '视频任务ID': video_id,
        })

        poll_sora_task(api_base, config['api_key'], video_id)

        out_path = os.path.join(WORK_DIR, f'{record_id}_video.mp4')
        download_sora_video(api_base, config['api_key'], video_id, out_path)
        video_file_token = with_retry(
            lambda: upload_video_to_feishu(token, out_path, f'{record_id}_video.mp4'),
            max_attempts=3,
            label='upload generated video to feishu'
        )

        safe_update_record(token, TABLE_SCRIPT_GEN, record_id, {
            '生成视频': [{'file_token': video_file_token}],
            '视频生成状态': '成功',
        })
        log_event('INFO', 'video-from-storyboard task success', record_id=record_id, stage_name=stage_name, cfg_record_id=cfg_record_id, video_id=video_id)
        print(f'✅ 视频生成完成: {out_path}')

    except Exception as e:
        payload = build_error_payload(e, stage='generate_video_from_storyboard')
        err = payload['message']
        log_event('ERROR', 'video-from-storyboard task failed', record_id=record_id, error=err, error_code=payload['error_code'])
        try:
            safe_update_record(token, TABLE_SCRIPT_GEN, record_id, {
                '视频生成状态': '失败',
                '视频错误信息': f"错误[{payload['error_code']}]: {err}",
            })
        except Exception as write_err:
            log_event('ERROR', 'video-from-storyboard failure writeback failed', record_id=record_id, error=str(write_err)[:500])
        print(f"ERROR_CODE={payload['error_code']} RETRYABLE={str(payload['retryable']).lower()} MESSAGE={err}")
        sys.exit(1)


if __name__ == '__main__':
    main()
