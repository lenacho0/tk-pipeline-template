#!/usr/bin/env python3
"""
视频制作同步脚本：扫描「产品脚本生成」表中分镜图已完成的记录，
自动在「视频制作」表创建对应记录（带分镜图+脚本），并设为「待执行」

用法: python3 tk_sync_video.py
"""
import json, os, sys, time, requests
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *


def main():
    token = get_feishu_token()

    script_records = list_records(token, TABLE_SCRIPT_GEN)
    ready_scripts = []
    for rec in script_records:
        rid = rec['record_id']
        f = rec.get('fields', {})
        sb_status = extract_text(f.get('分镜图状态', ''))
        if '成功' in sb_status and f.get('分镜图') and f.get('生成的脚本'):
            ready_scripts.append({
                'record_id': rid,
                'task_id': extract_text(f.get('任务ID', '')),
                'product': extract_text(f.get('选择产品', '')),
                'script': extract_text(f.get('生成的脚本', '')),
                'storyboard': f.get('分镜图', []),
                'duration': extract_text(f.get('视频时长', '25s')),
            })

    if not ready_scripts:
        print('没有分镜图已完成的记录，跳过')
        return

    print(f'找到 {len(ready_scripts)} 条分镜图已完成的记录')

    video_records = list_records(token, TABLE_VIDEO)
    existing_script_ids = set()
    for rec in video_records:
        f = rec.get('fields', {})
        link = f.get('关联脚本', [])
        if isinstance(link, list):
            for item in link:
                if isinstance(item, dict) and 'record_ids' in item:
                    for rid in item['record_ids']:
                        existing_script_ids.add(rid)

    created = 0
    for s in ready_scripts:
        if s['record_id'] in existing_script_ids:
            continue

        fields = {
            '关联脚本': [s['record_id']],
            '来源任务ID': s['task_id'],
            '选择产品': s['product'],
            '生成的脚本': s['script'][:10000],
            '分镜图': s['storyboard'],
            '视频时长': s['duration'],
            '制作状态': '待执行',
        }

        resp = requests.post(
            f'https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_VIDEO}/records',
            headers=feishu_headers(token),
            json={'fields': fields},
            timeout=30
        )
        data = resp.json()
        if data.get('code') == 0:
            new_rid = data['data']['record']['record_id']
            print(f'✅ 创建视频任务: {s["product"]} ({new_rid})')
            created += 1
        else:
            print(f'❌ 创建失败 [{s["product"]}]: {data.get("msg")}')

    if created == 0:
        print('所有分镜图记录已有对应视频任务，无需同步')
    else:
        print(f'✅ 共创建 {created} 条视频任务，调度器将自动执行')


if __name__ == '__main__':
    main()
