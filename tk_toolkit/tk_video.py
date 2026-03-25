#!/usr/bin/env python3
"""
环节5：视频制作（Sora 图生视频）
用法: python3 tk_video.py <record_id>
从飞书配置表读取 Sora API 配置 → 下载分镜图 → 提交 Sora 图生视频任务 → 轮询等待 → 下载视频 → 上传飞书 → 更新状态
"""
import json, os, sys, time, requests
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *

WORK_DIR = os.path.join(WORKSPACE, 'video_work')

POLL_INTERVAL = 15
MAX_POLL_TIME = 600
DEFAULT_SECONDS = 12
DEFAULT_SIZE = '720x1280'


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


def get_linked_script_record(token, task_fields):
    link = task_fields.get('关联脚本')
    if not link:
        return None, None
    if isinstance(link, list):
        for item in link:
            if isinstance(item, dict) and 'record_ids' in item:
                rids = item['record_ids']
                if rids:
                    rid = rids[0]
                    fields = get_record(token, TABLE_SCRIPT_GEN, rid)
                    return rid, fields
    return None, None


def submit_sora_task(api_base, api_key, prompt, model_name='sora-2-pro', image_path=None, seconds=DEFAULT_SECONDS, size=DEFAULT_SIZE):
    url = f'{api_base}/videos'
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
    raise Exception(f'Sora 任务提交失败: {data}')


def poll_sora_task(api_base, api_key, video_id):
    url = f'{api_base}/videos/{video_id}'
    headers = {'Authorization': api_key}
    start = time.time()

    while time.time() - start < MAX_POLL_TIME:
        resp = requests.get(url, headers=headers, timeout=30)
        data = resp.json()
        status = data.get('status', '')
        progress = data.get('progress', 0)
        print(f'  状态: {status}, 进度: {progress}%')

        if status == 'completed' or status == 'succeeded':
            return data
        elif status == 'failed' or status == 'error':
            error = data.get('error', '未知错误')
            raise Exception(f'Sora 生成失败: {error}')

        time.sleep(POLL_INTERVAL)

    raise Exception(f'Sora 任务超时（{MAX_POLL_TIME}秒），任务ID: {video_id}')


def download_sora_video(api_base, api_key, video_id, save_path):
    url = f'{api_base}/videos/{video_id}/content'
    headers = {'Authorization': api_key}

    resp = requests.get(url, headers=headers, stream=True, allow_redirects=True, timeout=300)
    if resp.status_code == 200:
        with open(save_path, 'wb') as f:
            for chunk in resp.iter_content(8192):
                f.write(chunk)
        file_size = os.path.getsize(save_path)
        if file_size > 10000:
            return True
        else:
            print(f'  ⚠️ 下载文件过小 ({file_size} bytes)')
            return False
    else:
        print(f'  ⚠️ 下载失败: HTTP {resp.status_code}')
        return False


def main():
    if len(sys.argv) < 2:
        print("用法: python3 tk_video.py <record_id>")
        sys.exit(1)
    record_id = sys.argv[1]
    os.makedirs(WORK_DIR, exist_ok=True)
    token = get_feishu_token()

    try:
        config = get_model_config(token, CONFIG_RECORDS['video'])
        api_key = config['api_key']
        api_base = config['api_base']
        prompt_template = config['prompt']
        model_name = config['model'] or 'sora-2-pro'

        if not api_key:
            raise Exception('飞书配置表缺少 Sora API Key')
        if not api_base:
            api_base = 'https://own-jarvis-api.com/v1'

        task = get_record(token, TABLE_VIDEO, record_id)
        update_record(token, TABLE_VIDEO, record_id, {'制作状态': '生成中'})

        script_rid, script_fields = get_linked_script_record(token, task)

        script = extract_text(task.get('生成的脚本', ''))
        if not script and script_fields:
            script = extract_text(script_fields.get('生成的脚本', ''))
        if not script:
            raise Exception('无脚本内容')

        duration_text = extract_text(task.get('视频时长', ''))
        try:
            seconds = int(''.join(c for c in duration_text if c.isdigit())) if duration_text else DEFAULT_SECONDS
            if seconds not in [4, 5, 8, 10, 12]:
                seconds = DEFAULT_SECONDS
        except:
            seconds = DEFAULT_SECONDS

        # 下载分镜图
        storyboard_path = os.path.join(WORK_DIR, f'{record_id}_storyboard.png')
        attachments = task.get('分镜图', [])
        if not attachments and script_fields:
            attachments = script_fields.get('分镜图', [])
        if attachments and isinstance(attachments, list):
            ft = attachments[0].get('file_token', '')
            if ft:
                print(f'下载分镜图: {ft}')
                download_attachment(token, ft, storyboard_path)

        has_image = os.path.exists(storyboard_path) and os.path.getsize(storyboard_path) > 10000

        # Prompt（优先读飞书表格）
        existing_prompt = extract_text(task.get('视频提示词', ''))
        if existing_prompt.strip():
            prompt = existing_prompt
            print('使用飞书表格中已有的视频提示词')
        else:
            if prompt_template:
                prompt = prompt_template.replace('{script}', script)
            else:
                prompt = f"Create a professional TikTok product commercial video based on this storyboard. Script:\n{script}"
            try:
                update_record(token, TABLE_VIDEO, record_id, {'视频提示词': prompt[:10000]})
                print('视频提示词已写入飞书表格')
            except Exception as e:
                print(f'⚠️ 写入提示词失败: {e}')

        # 提交 Sora
        print(f'提交 Sora 任务... (时长: {seconds}s, 图片: {"有" if has_image else "无"})')
        video_id, submit_data = submit_sora_task(
            api_base, api_key, prompt,
            model_name=model_name,
            image_path=storyboard_path if has_image else None,
            seconds=seconds,
            size=DEFAULT_SIZE
        )
        print(f'任务已提交: {video_id}')
        update_record(token, TABLE_VIDEO, record_id, {'视频任务ID': video_id})

        print('等待视频生成...')
        result = poll_sora_task(api_base, api_key, video_id)

        video_path = os.path.join(WORK_DIR, f'{record_id}_video.mp4')
        print('下载视频...')
        if not download_sora_video(api_base, api_key, video_id, video_path):
            raise Exception('视频下载失败')

        video_size = os.path.getsize(video_path)
        print(f'视频已下载: {video_path} ({video_size / 1024 / 1024:.1f} MB)')

        print('上传到飞书...')
        with open(video_path, 'rb') as f:
            r = requests.post(
                'https://open.feishu.cn/open-apis/drive/v1/medias/upload_all',
                headers={'Authorization': f'Bearer {token}'},
                data={
                    'file_name': f'{record_id}_video.mp4',
                    'parent_type': 'bitable_file',
                    'parent_node': APP_TOKEN,
                    'size': str(video_size),
                },
                files={'file': (f'{record_id}_video.mp4', f, 'video/mp4')},
                timeout=300
            )

        upload_data = r.json()
        if upload_data.get('code') == 0:
            ft = upload_data['data']['file_token']
            update_record(token, TABLE_VIDEO, record_id, {
                '最终视频': [{'file_token': ft}],
                '制作状态': '成功',
            })
            print(f'✅ 视频制作完成！')
        else:
            update_record(token, TABLE_VIDEO, record_id, {
                '制作状态': '成功（上传失败）',
                '错误信息': f'飞书上传失败: {upload_data.get("msg", "")}',
            })
            print(f'⚠️ 视频已生成但飞书上传失败: {upload_data.get("msg")}')

    except Exception as e:
        try:
            update_record(token, TABLE_VIDEO, record_id, {
                '制作状态': '失败',
                '错误信息': str(e)[:500],
            })
        except:
            pass
        print(f'❌ {e}')
        sys.exit(1)


if __name__ == '__main__':
    main()
