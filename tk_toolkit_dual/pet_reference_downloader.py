#!/usr/bin/env python3
import hashlib
import os
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


def download_reference_video(url, workspace):
    normalized_url = _normalize_url(url)
    platform = _detect_platform(url)
    os.makedirs(workspace, exist_ok=True)
    fake_name = hashlib.md5((url or '').encode('utf-8')).hexdigest() + '.mp4'
    local_path = os.path.join(workspace, fake_name)
    return {
        'ok': False,
        'source_url': url,
        'normalized_url': normalized_url,
        'platform': platform,
        'local_path': local_path,
        'duration_sec': 0,
        'file_size_mb': 0,
        'error': 'DOWNLOAD_NOT_IMPLEMENTED_YET'
    }
