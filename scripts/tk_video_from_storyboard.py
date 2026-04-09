#!/usr/bin/env python3
"""
003表内视频生成：基于九宫格分镜图直接生成视频
用法: python3 tk_video_from_storyboard.py <record_id>
当前版本：支持 sora 与 seeddance2.0 两种视频模型
"""
import base64
import os, sys, time, requests
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *

WORK_DIR = os.path.join(WORKSPACE, 'video_from_storyboard_work')
POLL_INTERVAL = 15
MAX_POLL_TIME = 1800
SUBMIT_TIMEOUT = 90
DOWNLOAD_TIMEOUT = 120
POLL_REQUEST_TIMEOUT = 30
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


def get_attachment_tmp_download_url(token, file_token):
    resp = requests.get(
        'https://open.feishu.cn/open-apis/drive/v1/medias/batch_get_tmp_download_url',
        headers={'Authorization': f'Bearer {token}'},
        params={'file_tokens': file_token},
        timeout=30,
    )
    data = resp.json()
    if data.get('code') != 0:
        raise Exception(f"获取附件临时下载链接失败: {data.get('msg')}")

    items = (data.get('data') or {}).get('tmp_download_urls') or []
    for item in items:
        if item.get('file_token') == file_token:
            url = item.get('tmp_download_url') or ''
            if url:
                return url
    raise Exception(f'附件临时下载链接为空: {file_token}')


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


def strip_chinese_voiceover_lines(script):
    lines = []
    for line in (script or '').splitlines():
        s = line.strip()
        if s.startswith('口播（中文）') or s.startswith('口播(中文)'):
            continue
        lines.append(line)
    return '\n'.join(lines).strip()


def build_video_prompt(task_fields, prompt_template, script):
    cleaned_script = strip_chinese_voiceover_lines(script)

    existing_prompt = extract_text(task_fields.get('视频提示词', '')).strip()
    if existing_prompt:
        return strip_chinese_voiceover_lines(existing_prompt)

    if prompt_template:
        return prompt_template.replace('{script}', cleaned_script).replace('{video_duration}', extract_text(task_fields.get('视频时长', '12s')))

    return (
        "请基于这个分镜脚本生成一条专业的竖屏带货视频。"
        "所有非口播提示词、场景说明、动作说明、镜头说明统一使用中文。"
        "只有泰文口播/台词可以作为最终需要被朗读或参与音频生成的内容。"
        "不要把任何中文说明、中文翻译或中文文本当作配音台词。"
        f"脚本如下：\n{cleaned_script}"
    )


def submit_sora_task(api_base, api_key, prompt, model_name, image_path, seconds=DEFAULT_SECONDS, size=DEFAULT_SIZE):
    url = api_base.rstrip('/')
    headers = {'Authorization': api_key}
    form_data = {
        'prompt': (None, prompt),
        'model': (None, model_name),
        'seconds': (None, str(seconds)),
        'size': (None, size),
    }
    try:
        if image_path and os.path.exists(image_path):
            with open(image_path, 'rb') as img:
                form_data['image'] = (os.path.basename(image_path), img, 'image/png')
                resp = requests.post(url, headers=headers, files=form_data, timeout=SUBMIT_TIMEOUT)
        else:
            resp = requests.post(url, headers=headers, files=form_data, timeout=SUBMIT_TIMEOUT)
        resp.raise_for_status()
    except requests.exceptions.Timeout as e:
        raise Exception(f'Sora任务提交超时（{SUBMIT_TIMEOUT}秒）: {e}')
    except requests.exceptions.RequestException as e:
        raise Exception(f'Sora任务提交请求失败: {e}')

    try:
        data = resp.json()
    except Exception as e:
        body = (resp.text or '')[:500]
        raise Exception(f'Sora任务提交返回非JSON响应: HTTP {resp.status_code}, body={body}, error={e}')

    if 'id' in data:
        return data['id'], data
    raise Exception(f'Sora任务提交失败: {str(data)[:1000]}')


def poll_sora_task(api_base, api_key, video_id, progress_cb=None):
    url = f"{api_base.rstrip('/').rsplit('/', 2)[0]}/videos/{video_id}"
    headers = {'Authorization': api_key}
    start = time.time()
    last_status = None
    last_progress_push_at = 0
    while time.time() - start < MAX_POLL_TIME:
        try:
            resp = requests.get(url, headers=headers, timeout=POLL_REQUEST_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.Timeout:
            data = {'status': 'poll_timeout'}
        except requests.exceptions.RequestException as e:
            raise Exception(f'Sora轮询请求失败: {e}')
        except Exception as e:
            raise Exception(f'Sora轮询返回异常: {e}')

        status = data.get('status', '') or 'unknown'
        elapsed = int(time.time() - start)
        if progress_cb and (status != last_status or time.time() - last_progress_push_at >= 60):
            progress_cb(status, elapsed, data)
            last_progress_push_at = time.time()
            last_status = status

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


def normalize_video_model_name(video_model):
    value = (video_model or '').strip().lower()
    aliases = {
        'seedance2.0': 'seeddance2.0',
        'seedance': 'seeddance2.0',
        'seed-dance': 'seeddance2.0',
        'seed-dance-2.0': 'seeddance2.0',
        'seeddance': 'seeddance2.0',
        'seeddance-2.0': 'seeddance2.0',
        'seeddance2': 'seeddance2.0',
        'seeddance2.0': 'seeddance2.0',
        'sora': 'sora',
    }
    return aliases.get(value, value)


def creaa_headers(api_key):
    return {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json',
        'X-Source': 'openclaw',
    }


def build_data_uri(file_path, mime_type='image/png'):
    with open(file_path, 'rb') as f:
        encoded = base64.b64encode(f.read()).decode('utf-8')
    return f'data:{mime_type};base64,{encoded}'


def resolve_seeddance_provider_model(model_name):
    """透传模型名，aihubmix 的 doubao-seedance 模型名需精确传递。"""
    return extract_text(model_name).strip() or 'doubao-seedance-2-0-fast-260128'


def submit_seeddance_task(api_base, api_key, prompt, model_name, image_path, seconds=DEFAULT_SECONDS, image_url=''):
    if not image_path or not os.path.exists(image_path):
        raise Exception('SeedDance 2.0 当前仅接 image_to_video，缺少九宫格分镜图文件')

    # aihubmix 风格：POST /v1/videos，图片作为 multipart file 上传
    url = f"{api_base.rstrip('/')}/v1/videos"
    headers = {'Authorization': f'Bearer {api_key}'}

    try:
        with open(image_path, 'rb') as f:
            image_bytes = f.read()
    except Exception as e:
        raise Exception(f'SeedDance 2.0 读取分镜图文件失败: {e}')

    try:
        resp = requests.post(
            url,
            headers=headers,
            data={
                'model': model_name,
                'prompt': prompt,
                'seconds': seconds,
                'size': DEFAULT_SIZE,
            },
            files={'image': (os.path.basename(image_path), image_bytes, 'image/png')},
            timeout=SUBMIT_TIMEOUT
        )
        resp.raise_for_status()
    except requests.exceptions.Timeout as e:
        raise Exception(f'SeedDance 2.0 任务提交超时（{SUBMIT_TIMEOUT}秒）: {e}')
    except requests.exceptions.RequestException as e:
        raise Exception(f'SeedDance 2.0 任务提交请求失败: {e}')

    try:
        data = resp.json()
    except Exception as e:
        body = (resp.text or '')[:500]
        raise Exception(f'SeedDance 2.0 提交返回非JSON响应: HTTP {resp.status_code}, body={body}, error={e}')

    task_id = extract_text(data.get('id', '') or data.get('task_id', ''))
    if task_id:
        return task_id, data

    err = extract_text(data.get('error', '') or data.get('message', ''))
    raise Exception(f'SeedDance 2.0 任务提交失败: {err or str(data)[:1000]}')


def poll_seeddance_task(api_base, api_key, task_id, progress_cb=None):
    url = f"{api_base.rstrip('/')}/v1/videos/{task_id}"
    start = time.time()
    last_status = None
    last_progress_push_at = 0
    while time.time() - start < MAX_POLL_TIME:
        try:
            resp = requests.get(url, headers={'Authorization': f'Bearer {api_key}'}, timeout=POLL_REQUEST_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.Timeout:
            data = {'status': 'poll_timeout'}
        except requests.exceptions.RequestException as e:
            raise Exception(f'SeedDance 2.0 轮询请求失败: {e}')
        except Exception as e:
            raise Exception(f'SeedDance 2.0 轮询返回异常: {e}')

        status = extract_text(data.get('status', '') or data.get('data', {}).get('status', '')).lower() or 'unknown'
        elapsed = int(time.time() - start)
        if progress_cb and (status != last_status or time.time() - last_progress_push_at >= 60):
            progress_cb(status, elapsed, data)
            last_progress_push_at = time.time()
            last_status = status

        if status in ('completed', 'succeeded', 'success', 'done'):
            return data
        if status in ('failed', 'error', 'cancelled', 'canceled'):
            err = data.get('error') or data.get('message') or data.get('data', {}).get('error') or '未知错误'
            raise Exception(f'SeedDance 2.0 生成失败: {err}')
        time.sleep(POLL_INTERVAL)
    raise Exception(f'SeedDance 2.0 任务超时（{MAX_POLL_TIME}秒），任务ID: {task_id}')


def normalize_url_candidate(value):
    if value is None:
        return ''
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ('url', 'video_url', 'result_url', 'download_url'):
            nested = value.get(key)
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
        return ''
    return str(value).strip()


def extract_seeddance_video_url(result):
    # aihubmix: completed 时 url=null，下载路径固定为 /v1/videos/{id}/content
    video_id = extract_text(result.get('id', '') or result.get('task_id', ''))
    if video_id:
        return f"https://aihubmix.com/v1/videos/{video_id}/content"
    # 兜底：从 result 里找已有 URL
    for key in ('url', 'video_url', 'result_url', 'download_url'):
        val = result.get(key)
        if val and isinstance(val, str) and val.startswith('http'):
            return val
    return ''


def download_seeddance_video(api_base, api_key, task_id, save_path):
    # aihubmix 下载：GET /v1/videos/{id}/content
    video_url = f"{api_base.rstrip('/')}/v1/videos/{task_id}/content"
    headers = {'Authorization': f'Bearer {api_key}'}
    resp = requests.get(video_url, headers=headers, stream=True, allow_redirects=True, timeout=300)
    if resp.status_code != 200:
        raise Exception(f'SeedDance 2.0 视频下载失败: HTTP {resp.status_code}')
    with open(save_path, 'wb') as f:
        for chunk in resp.iter_content(8192):
            f.write(chunk)
    if os.path.getsize(save_path) < 10000:
        raise Exception('SeedDance 2.0 视频下载成功但文件过小')
    return save_path


def main():
    if len(sys.argv) < 2:
        print('用法: python3 tk_video_from_storyboard.py <record_id>')
        sys.exit(1)
    record_id = sys.argv[1]
    ensure_work_dir()
    token = get_feishu_token()

    upstream_completed = False
    video_id = ''
    try:
        log_event('INFO', 'video-from-storyboard task start', record_id=record_id)
        task = safe_get_record(token, TABLE_SCRIPT_GEN, record_id)

        if extract_text(task.get('是否生成视频', '')).strip() != '是':
            raise Exception('未开启视频生成')

        video_model = normalize_video_model_name(extract_text(task.get('视频模型', '')).strip())
        if not video_model:
            raise Exception('未选择视频模型')
        if video_model not in ('sora', 'seeddance2.0'):
            raise Exception(f'当前仅支持 sora / seeddance2.0，当前选择: {video_model}')

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
        storyboard_tmp_url = ''
        log_event('INFO', 'video-from-storyboard download storyboard start', record_id=record_id, file_token=file_token)
        safe_download_attachment(token, file_token, storyboard_path)
        try:
            storyboard_tmp_url = get_attachment_tmp_download_url(token, file_token)
        except Exception as url_err:
            log_event('WARNING', 'video-from-storyboard get tmp url failed', record_id=record_id, file_token=file_token, error=str(url_err))
        log_event('INFO', 'video-from-storyboard download storyboard success', record_id=record_id, storyboard_path=storyboard_path, storyboard_tmp_url=storyboard_tmp_url or None)

        prompt = build_video_prompt(task, config.get('prompt', ''), script)
        safe_update_record(token, TABLE_SCRIPT_GEN, record_id, {
            '视频提示词': prompt[:10000],
        })

        seconds = parse_seconds(extract_text(task.get('视频时长', '12s')))
        model_name = config.get('model') or 'sora-2-all'
        api_base = config.get('api_base') or 'https://own-jarvis-api.com/v1/video/create'

        safe_update_record(token, TABLE_SCRIPT_GEN, record_id, {
            '视频错误信息': f'准备提交{video_model}任务（{seconds}s）...'
        })
        log_event('INFO', 'video-from-storyboard submit start', record_id=record_id, provider=video_model, stage_name=stage_name, model_name=model_name, seconds=seconds, api_base=api_base)

        if video_model == 'sora':
            video_id, _ = submit_sora_task(
                api_base=api_base,
                api_key=config['api_key'],
                prompt=prompt,
                model_name=model_name,
                image_path=storyboard_path,
                seconds=seconds,
                size=DEFAULT_SIZE,
            )
        else:
            video_id, _ = submit_seeddance_task(
                api_base=api_base,
                api_key=config['api_key'],
                prompt=prompt,
                model_name=model_name,
                image_path=storyboard_path,
                seconds=seconds,
                image_url=storyboard_tmp_url,
            )

        log_event('INFO', 'video-from-storyboard submit success', record_id=record_id, provider=video_model, video_id=video_id)
        safe_update_record(token, TABLE_SCRIPT_GEN, record_id, {
            '视频任务ID': video_id,
            '视频错误信息': f'已提交{video_model}任务，正在轮询（任务ID: {video_id}）'
        })

        def push_poll_progress(status, elapsed, raw):
            message = f'轮询中: provider={video_model}, status={status}, elapsed={elapsed}s, task_id={video_id}'
            safe_update_record(token, TABLE_SCRIPT_GEN, record_id, {
                '视频错误信息': message[:1000],
            })
            log_event('INFO', 'video-from-storyboard polling', record_id=record_id, provider=video_model, video_id=video_id, status=status, elapsed=elapsed)

        if video_model == 'sora':
            result = poll_sora_task(api_base, config['api_key'], video_id, progress_cb=push_poll_progress)
        else:
            result = poll_seeddance_task(api_base, config['api_key'], video_id, progress_cb=push_poll_progress)

        result_video_url = ''
        if video_model == 'seeddance2.0':
            result_video_url = extract_seeddance_video_url(result)
            safe_update_record(token, TABLE_SCRIPT_GEN, record_id, {
                '视频错误信息': (f'上游已完成，准备下载结果。task_id={video_id} url={result_video_url[:800]}' if result_video_url else f'上游已完成，但暂未解析到下载地址。task_id={video_id}')[:1000],
            })
            log_event('INFO', 'video-from-storyboard seeddance result resolved', record_id=record_id, provider=video_model, video_id=video_id, result_video_url=result_video_url or None)

        upstream_completed = True
        out_path = os.path.join(WORK_DIR, f'{record_id}_video.mp4')
        if video_model == 'sora':
            download_sora_video(api_base, config['api_key'], video_id, out_path)
        else:
            download_seeddance_video(api_base, config['api_key'], video_id, out_path)
        safe_update_record(token, TABLE_SCRIPT_GEN, record_id, {
            '视频错误信息': f'视频下载完成，准备上传飞书。task_id={video_id}'[:1000],
        })
        video_file_token = with_retry(
            lambda: upload_video_to_feishu(token, out_path, f'{record_id}_video.mp4'),
            max_attempts=3,
            label='upload generated video to feishu'
        )

        safe_update_record(token, TABLE_SCRIPT_GEN, record_id, {
            '生成视频': [{'file_token': video_file_token}],
            '视频生成状态': '成功',
            '视频错误信息': '',
        })
        log_event('INFO', 'video-from-storyboard task success', record_id=record_id, provider=video_model, stage_name=stage_name, cfg_record_id=cfg_record_id, video_id=video_id)
        print(f'✅ 视频生成完成: {out_path}')

    except Exception as e:
        payload = build_error_payload(e, stage='generate_video_from_storyboard')
        err = payload['message']
        if upstream_completed:
            failure_message = f"错误[UPSTREAM_COMPLETED_LOCAL_WRITEBACK_FAILED]: 上游视频已生成成功，但本地下载/飞书回写失败。task_id={video_id or 'unknown'}，详情: {err}"
            log_event('ERROR', 'video-from-storyboard task failed after upstream completion', record_id=record_id, video_id=video_id or None, error=err, error_code='UPSTREAM_COMPLETED_LOCAL_WRITEBACK_FAILED')
        else:
            failure_message = f"错误[{payload['error_code']}]: {err}"
            log_event('ERROR', 'video-from-storyboard task failed', record_id=record_id, error=err, error_code=payload['error_code'])
        try:
            safe_update_record(token, TABLE_SCRIPT_GEN, record_id, {
                '视频生成状态': '失败',
                '视频错误信息': failure_message[:1000],
            })
        except Exception as write_err:
            log_event('ERROR', 'video-from-storyboard failure writeback failed', record_id=record_id, error=str(write_err)[:500])
        print(f"ERROR_CODE={payload['error_code']} RETRYABLE={str(payload['retryable']).lower()} MESSAGE={err}")
        sys.exit(1)


if __name__ == '__main__':
    main()
