#!/usr/bin/env python3
"""
单视频补救工具：按 video_id 补下载无水印视频，并回填到数据表记录的「无水印视频」附件字段。
用法: python3 tk_repair_video.py <video_id>
"""
import os, sys, re, requests
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *

VIDEO_DIR = os.path.join(WORKSPACE, 'tiktok_videos')


def ensure_video_dir():
    os.makedirs(VIDEO_DIR, exist_ok=True)


def find_data_record_by_video_id(token, video_id):
    records = safe_list_records(token, TABLE_DATA)
    for rec in records:
        fields = rec.get('fields', {})
        if extract_text(fields.get('视频ID', '')) == video_id:
            return rec
    return None


def candidate_urls(video_id, existing_url=''):
    urls = []
    if existing_url:
        urls.append(existing_url)
        m = re.search(r'(\d{10,})', existing_url)
        if m:
            video_id = m.group(1)
    for u in [
        f'https://www.tiktok.com/@user/video/{video_id}',
        f'https://www.tiktok.com/video/{video_id}',
        f'https://m.tiktok.com/v/{video_id}.html',
    ]:
        if u not in urls:
            urls.append(u)
    return urls


def download_video(video_id, existing_url=''):
    ensure_video_dir()
    path = os.path.join(VIDEO_DIR, f'{video_id}.mp4')
    if os.path.exists(path) and os.path.getsize(path) > 1000:
        return path, True

    last_error = None
    for source_url in candidate_urls(video_id, existing_url):
        try:
            def _download():
                resp = requests.get('https://www.tikwm.com/api/', params={'url': source_url}, timeout=30)
                data = resp.json()
                play_url = data.get('data', {}).get('play') or data.get('data', {}).get('hdplay')
                if data.get('code') != 0 or not play_url:
                    raise Exception(f"tikwm API异常: {data.get('msg', 'unknown')}")
                dl = requests.get(play_url, timeout=120, stream=True)
                if dl.status_code != 200:
                    raise Exception(f'视频下载失败 HTTP {dl.status_code}')
                with open(path, 'wb') as f:
                    for chunk in dl.iter_content(8192):
                        f.write(chunk)
                if os.path.getsize(path) <= 1000:
                    raise Exception('下载文件太小')
                return path

            return with_retry(_download, max_attempts=2, label=f'repair download via {source_url}'), False
        except Exception as e:
            last_error = e
            log_event('WARN', 'repair download fallback failed', video_id=video_id, source_url=source_url, error=str(e)[:200])
            if os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass
    raise last_error or Exception('视频补下载失败')


def upload_feishu_attachment(token, file_path, file_name):
    def _upload():
        file_size = os.path.getsize(file_path)
        with open(file_path, 'rb') as f:
            resp = requests.post(
                'https://open.feishu.cn/open-apis/drive/v1/medias/upload_all',
                headers={'Authorization': f'Bearer {token}'},
                data={
                    'file_name': file_name,
                    'parent_type': 'bitable_file',
                    'parent_node': APP_TOKEN,
                    'size': str(file_size),
                },
                files={'file': (file_name, f, 'video/mp4')},
                timeout=120
            )
        data = resp.json()
        if data.get('code') != 0:
            raise Exception(f"上传失败: {data.get('msg')}")
        return data['data']['file_token']
    return with_retry(_upload, max_attempts=3, label='repair upload video attachment')


def main():
    if len(sys.argv) < 2:
        print('用法: python3 tk_repair_video.py <video_id>')
        sys.exit(1)
    video_id = sys.argv[1]
    token = get_feishu_token()

    rec = find_data_record_by_video_id(token, video_id)
    if not rec:
        raise Exception(f'数据表中找不到视频ID: {video_id}')

    fields = rec.get('fields', {})
    existing_url = ''
    raw_url = fields.get('视频链接')
    if isinstance(raw_url, dict):
        existing_url = raw_url.get('link', '')
    elif isinstance(raw_url, str):
        existing_url = raw_url

    path, existed = download_video(video_id, existing_url)
    file_token = upload_feishu_attachment(token, path, f'{video_id}.mp4')
    safe_update_record(token, TABLE_DATA, rec['record_id'], {
        '无水印视频': [{'file_token': file_token, 'name': f'{video_id}.mp4'}]
    })
    log_event('INFO', 'repair video success', video_id=video_id, record_id=rec['record_id'], existed=existed, path=path)
    print(f'✅ repair success: {video_id} -> {rec["record_id"]}')


if __name__ == '__main__':
    main()
