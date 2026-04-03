#!/usr/bin/env python3
import hashlib
import json
import os
import shutil
import subprocess
from urllib.parse import urlparse


def _detect_platform(url):
    u = (url or '').lower()
    if 'tiktok.com' in u:
        return 'TikTok'
    if 'douyin.com' in u:
        return 'Douyin'
    if 'instagram.com' in u:
        return 'Instagram'
    if 'youtube.com/shorts' in u or 'youtu.be/' in u:
        return 'YouTube Shorts'
    if 'xiaohongshu.com' in u or 'xhslink.com' in u:
        return 'Xiaohongshu'
    return 'Unknown'


def _normalize_url(url):
    try:
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    except Exception:
        return url


def _yt_dlp_bin():
    return shutil.which('yt-dlp') or os.path.expanduser('~/Library/Python/3.9/bin/yt-dlp')


def _ffprobe_bin():
    return shutil.which('ffprobe')


def _probe_video(local_path):
    ffprobe = _ffprobe_bin()
    if not ffprobe or not os.path.exists(local_path):
        return 0, round(os.path.getsize(local_path) / 1024 / 1024, 2) if os.path.exists(local_path) else 0
    result = subprocess.run(
        [ffprobe, '-v', 'error', '-show_entries', 'format=duration,size', '-of', 'json', local_path],
        capture_output=True, text=True, timeout=20
    )
    if result.returncode != 0:
        return 0, round(os.path.getsize(local_path) / 1024 / 1024, 2)
    data = json.loads(result.stdout or '{}')
    fmt = data.get('format', {})
    duration = float(fmt.get('duration') or 0)
    size_mb = round((float(fmt.get('size') or 0) / 1024 / 1024), 2)
    return round(duration, 2), size_mb


def download_reference_video(url, workspace):
    normalized_url = _normalize_url(url)
    platform = _detect_platform(url)
    os.makedirs(workspace, exist_ok=True)
    fake_name = hashlib.md5((url or '').encode('utf-8')).hexdigest() + '.mp4'
    local_path = os.path.join(workspace, fake_name)

    yt_dlp = _yt_dlp_bin()
    if not yt_dlp or not os.path.exists(yt_dlp):
        return {
            'ok': False,
            'source_url': url,
            'normalized_url': normalized_url,
            'platform': platform,
            'local_path': local_path,
            'duration_sec': 0,
            'file_size_mb': 0,
            'error': 'YT_DLP_NOT_FOUND'
        }

    cmd = [yt_dlp, '--no-playlist', '--format', 'mp4/best', '--output', local_path, url]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=240)
        if result.returncode != 0:
            err = ((result.stderr or '') + '\n' + (result.stdout or '')).strip()[:500]
            return {
                'ok': False,
                'source_url': url,
                'normalized_url': normalized_url,
                'platform': platform,
                'local_path': local_path,
                'duration_sec': 0,
                'file_size_mb': 0,
                'error': f'YT_DLP_FAILED: {err}'
            }
        if not os.path.exists(local_path) or os.path.getsize(local_path) < 1000:
            return {
                'ok': False,
                'source_url': url,
                'normalized_url': normalized_url,
                'platform': platform,
                'local_path': local_path,
                'duration_sec': 0,
                'file_size_mb': 0,
                'error': 'DOWNLOADED_FILE_INVALID'
            }
        duration_sec, file_size_mb = _probe_video(local_path)
        return {
            'ok': True,
            'source_url': url,
            'normalized_url': normalized_url,
            'platform': platform,
            'local_path': local_path,
            'duration_sec': duration_sec,
            'file_size_mb': file_size_mb,
            'error': ''
        }
    except Exception as e:
        return {
            'ok': False,
            'source_url': url,
            'normalized_url': normalized_url,
            'platform': platform,
            'local_path': local_path,
            'duration_sec': 0,
            'file_size_mb': 0,
            'error': f'DOWNLOAD_EXCEPTION: {str(e)[:500]}'
        }
