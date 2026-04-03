#!/usr/bin/env python3
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEDIA_TOOL_ROOT = ROOT / 'tools' / 'media_bulk_downloader'
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.media_bulk_downloader.config import load_config
from tools.media_bulk_downloader.downloader import download_media
from tools.media_bulk_downloader.io_utils import detect_platform, normalize_url
from tools.media_bulk_downloader.models import InputItem
from tools.media_bulk_downloader.provider import MediaProviderClient


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
    normalized_url = normalize_url(url)
    platform = detect_platform(normalized_url)
    output_root = Path(workspace)
    output_root.mkdir(parents=True, exist_ok=True)
    env_file = ROOT / '.env'

    try:
        config = load_config(env_file)
        client = MediaProviderClient(config)
        item = InputItem(
            source_url=url,
            normalized_url=normalized_url,
            platform=platform,
            row_number=1,
            source_label='pet_reference_v1',
        )
        media = client.resolve(item)
        result = download_media(config, item, media, output_root, skip_existing=True)
        if result.status not in ('success', 'skipped') or not result.file_path:
            return {
                'ok': False,
                'source_url': url,
                'normalized_url': normalized_url,
                'platform': platform.title() if platform != 'unknown' else 'Unknown',
                'local_path': '',
                'duration_sec': 0,
                'file_size_mb': 0,
                'error': result.error or 'MEDIA_BULK_DOWNLOAD_FAILED'
            }
        local_path = str(result.file_path)
        duration_sec, file_size_mb = _probe_video(local_path)
        display_platform = platform.title() if platform != 'unknown' else 'Unknown'
        if display_platform == 'Tiktok':
            display_platform = 'TikTok'
        return {
            'ok': True,
            'source_url': url,
            'normalized_url': normalized_url,
            'platform': display_platform,
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
            'platform': platform.title() if platform != 'unknown' else 'Unknown',
            'local_path': '',
            'duration_sec': 0,
            'file_size_mb': 0,
            'error': f'MEDIA_BULK_EXCEPTION: {str(e)[:500]}'
        }
