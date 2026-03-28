#!/usr/bin/env python3
"""
环节1：爆款视频抓取
用法: python3 tk_fetch.py <record_id>
从抓取配置表读取参数 → FastMoss 抓取 → 去重 → 写入数据表 → 下载无水印视频 → 上传飞书附件 → 更新状态
"""
import json, os, sys, time, requests, re
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *

DEDUP_FILE = os.path.join(WORKSPACE, 'video_dedup.json')
VIDEO_DIR = os.path.join(WORKSPACE, 'tiktok_videos')


def load_dedup():
    if os.path.exists(DEDUP_FILE):
        with open(DEDUP_FILE) as f:
            return set(json.load(f))
    return set()


def save_dedup(ids):
    with open(DEDUP_FILE, 'w') as f:
        json.dump(list(ids), f)


def time_range_to_days(text):
    return {'近1天': 1, '近3天': 3, '近7天': 7, '近15天': 15, '近30天': 30}.get(text, 7)


def fastmoss_headers(api_key):
    return {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json',
    }


def fetch_fastmoss_page(api_base, api_key, body):
    return safe_request(
        'post',
        f'{api_base}/video/v1/search',
        headers=fastmoss_headers(api_key),
        json=body,
        timeout=30,
        max_attempts=3,
        acceptable_codes=(0,)
    )


def fetch_fastmoss(api_base, api_key, keyword, days, region, min_sold, min_play, target_count, known_ids=None, sort_by='按销售量', is_ecom='仅带货视频'):
    now = int(time.time())
    min_time = now - days * 86400
    all_videos = []
    known_ids = known_ids or set()

    region_code_map = {
        '泰国': 'TH', '美国': 'US', '印尼': 'ID', '越南': 'VN',
        '马来西亚': 'MY', '菲律宾': 'PH', '日本': 'JP', '英国': 'GB',
        '墨西哥': 'MX', '西班牙': 'ES', '法国': 'FR', '巴西': 'BR',
        '全部地区': None, '不限': None, '': None
    }

    region_codes = region_code_map.get(region)
    if region and region not in region_code_map:
        region_codes = region

    ecommerce_filter = is_ecom != '不限'
    orderby_map = {
        '按播放量': 'play_count',
        '按点赞量': 'digg_count',
        '按互动率': 'interact_rate',
        '按粉丝数': 'follower_count',
        '按发布时间': 'create_time',
    }
    api_orderby = orderby_map.get(sort_by, 'play_count')
    need_client_sort = sort_by == '按销售量'

    if target_count <= 10:
        max_pages = 3
    elif target_count <= 30:
        max_pages = 5
    else:
        max_pages = min(max(target_count // 20 + 2, 3), 10)

    estimated_needed = max(target_count * 2, target_count)

    for page in range(1, max_pages + 1):
        body = {
            'keywords': keyword,
            'filter': {
                'publish_time_range': {'min': min_time, 'max': now},
            },
            'orderby': api_orderby,
            'page': page,
            'pagesize': 100,
        }
        if ecommerce_filter:
            body['filter']['is_ecommerce_creator'] = True
        if region_codes:
            body['filter']['region'] = [region_codes]
        if min_play > 0:
            body['filter']['play_count_range'] = {'min': min_play}

        data = fetch_fastmoss_page(api_base, api_key, body)
        items = data.get('data', {}).get('list', [])
        if not items:
            break

        all_videos.extend(items)

        filtered = [
            v for v in all_videos
            if (v.get('sold_count', 0) or 0) >= min_sold and (v.get('play_count', 0) or 0) >= min_play
        ]
        if need_client_sort:
            filtered.sort(key=lambda x: x.get('sold_count', 0) or 0, reverse=True)

        new_count = 0
        for v in filtered:
            vid = str(v.get('video_id', ''))
            if vid and vid not in known_ids:
                new_count += 1
                if new_count >= target_count:
                    break

        log_event('INFO', 'fastmoss page fetched', page=page, item_count=len(items), accumulated=len(all_videos), filtered=len(filtered), new_candidates=new_count, target_count=target_count)

        if new_count >= target_count:
            log_event('INFO', 'fastmoss stop early', page=page, new_candidates=new_count, target_count=target_count)
            break

        if len(filtered) >= estimated_needed and page >= 2:
            log_event('INFO', 'fastmoss stop by estimated sufficiency', page=page, filtered=len(filtered), estimated_needed=estimated_needed)
            break

        time.sleep(0.5)

    filtered = [
        v for v in all_videos
        if (v.get('sold_count', 0) or 0) >= min_sold and (v.get('play_count', 0) or 0) >= min_play
    ]

    if need_client_sort:
        filtered.sort(key=lambda x: x.get('sold_count', 0) or 0, reverse=True)

    return filtered


def classify_download_error(err):
    msg = str(err or '')
    if 'Url parsing is failed' in msg:
        return 'source_unparseable'
    if 'HTTP 4' in msg or 'HTTP 5' in msg:
        return 'download_http_error'
    if '下载文件太小' in msg:
        return 'download_file_too_small'
    return 'download_failed'


def download_video(video_id):
    os.makedirs(VIDEO_DIR, exist_ok=True)
    path = os.path.join(VIDEO_DIR, f'{video_id}.mp4')
    if os.path.exists(path) and os.path.getsize(path) > 1000:
        return path, True, 'cached', ''

    candidate_urls = [
        f'https://www.tiktok.com/@user/video/{video_id}',
        f'https://www.tiktok.com/video/{video_id}',
        f'https://m.tiktok.com/v/{video_id}.html',
    ]

    def _download_from_url(source_url):
        resp = requests.get(
            'https://www.tikwm.com/api/',
            params={'url': source_url},
            timeout=30
        )
        data = resp.json()
        if data.get('code') != 0 or not data.get('data', {}).get('play'):
            raise Exception(f"tikwm API异常: {data.get('msg', 'unknown')}")

        dl = requests.get(data['data']['play'], timeout=120, stream=True)
        if dl.status_code != 200:
            raise Exception(f'视频下载失败 HTTP {dl.status_code}')

        with open(path, 'wb') as f:
            for chunk in dl.iter_content(8192):
                f.write(chunk)

        if os.path.getsize(path) <= 1000:
            raise Exception('下载文件太小')
        return path

    last_error = None
    for source_url in candidate_urls:
        try:
            return with_retry(lambda url=source_url: (_download_from_url(url), False)[0], max_attempts=2, label=f'download tiktok video via {source_url}'), False, 'downloaded', ''
        except Exception as e:
            last_error = e
            error_code = classify_download_error(e)
            log_event('WARN', 'download fallback failed', video_id=video_id, source_url=source_url, error_code=error_code, error=str(e)[:200])
            if os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass

    error_code = classify_download_error(last_error)
    log_event('WARN', 'all download fallbacks failed', video_id=video_id, error_code=error_code, error=str(last_error)[:300] if last_error else 'unknown')
    return None, False, error_code, str(last_error)[:300] if last_error else ''


def pick_video_link(video):
    candidates = [
        video.get('share_url'),
        video.get('video_url'),
        video.get('url'),
        video.get('aweme_url'),
    ]

    author_id = (video.get('creator') or {}).get('unique_id', '')
    video_id = str(video.get('video_id', '') or '')
    if video_id:
        candidates.extend([
            f'https://www.tiktok.com/@{author_id}/video/{video_id}' if author_id else '',
            f'https://www.tiktok.com/video/{video_id}',
            f'https://m.tiktok.com/v/{video_id}.html',
        ])

    for candidate in candidates:
        if isinstance(candidate, str) and re.match(r'^https?://', candidate.strip()):
            return candidate.strip()
    return ''


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

    return with_retry(_upload, max_attempts=3, label='upload video attachment')


def insert_to_data_table(token, videos, task_name):
    records = []
    for v in videos:
        creator = v.get('creator', {})
        products = v.get('product_info', [])
        product = products[0] if products else {}

        fields = {
            '来源任务': task_name,
            '视频ID': str(v.get('video_id', '')),
            '视频描述': (v.get('desc', '') or '')[:500],
            '地区': v.get('region', ''),
            '发布时间': v.get('create_date', ''),
            '时长(秒)': v.get('duration', 0),
            '播放量': v.get('play_count', 0),
            '点赞数': v.get('digg_count', 0),
            '评论数': v.get('comment_count', 0),
            '分享数': v.get('share_count', 0),
            '收藏数': v.get('forward_count', 0),
            '互动率(%)': v.get('interact_rate', 0),
            '是否广告': '是' if v.get('is_ad') == 1 else '否',
            '销售量': v.get('sold_count', 0),
            '销售额': v.get('sale_amount', 0),
            '达人昵称': creator.get('nickname', ''),
            '达人ID': creator.get('unique_id', ''),
            '达人分类': creator.get('category_name', ''),
            '粉丝数': creator.get('follower_count', 0),
        }

        if product:
            fields['商品名称'] = product.get('title', '')
            fields['商品价格'] = product.get('price', '')
            fields['商品销量'] = product.get('sold_count', 0)
            fields['商品销售额'] = product.get('sale_amount', 0)
            fields['商品分类'] = product.get('category_name', '')

        video_link = pick_video_link(v)
        if video_link:
            fields['视频链接'] = {'link': video_link}

        records.append({'fields': fields})

    id_map = {}
    inserted = 0
    for i in range(0, len(records), 10):
        batch = records[i:i + 10]
        result = safe_request(
            'post',
            f'https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_DATA}/records/batch_create',
            headers=feishu_headers(token),
            json={'records': batch},
            timeout=30,
            max_attempts=3,
            acceptable_codes=(0,)
        )
        for rec in result['data']['records']:
            vid = rec['fields'].get('视频ID', '')
            if vid:
                id_map[vid] = rec['record_id']
        inserted += len(result['data']['records'])
        time.sleep(0.3)
    return inserted, id_map


def main():
    if len(sys.argv) < 2:
        print("用法: python3 tk_fetch.py <record_id>")
        sys.exit(1)
    record_id = sys.argv[1]
    token = get_feishu_token()

    try:
        log_event('INFO', 'fetch task start', record_id=record_id)
        api_cfg = get_fetch_api_config(token)
        fields = safe_get_record(token, TABLE_FETCH_CONFIG, record_id)
        task_name = extract_text(fields.get('任务名称', '未命名'))
        limit = int(fields.get('抓取数量', 50) or 50)
        days = time_range_to_days(extract_text(fields.get('时间范围', '近7天')))
        keyword = extract_text(fields.get('关键词', ''))
        min_sold = int(fields.get('最低销量', 0) or 0)
        min_play = int(fields.get('最低播放量', 0) or 0)
        region = extract_text(fields.get('地区', ''))
        sort_by = extract_text(fields.get('排序方式', '按销售量'))
        is_ecom = extract_text(fields.get('是否带货', '仅带货视频'))

        log_event('INFO', 'fetch task config loaded', task_name=task_name, keyword=keyword, region=region, days=days, limit=limit, api_base=api_cfg['api_base'])
        safe_update_record(token, TABLE_FETCH_CONFIG, record_id, {'执行状态': '抓取中'})
        known_ids = load_dedup()

        videos = fetch_fastmoss(api_cfg['api_base'], api_cfg['api_key'], keyword, days, region, min_sold, min_play, limit, known_ids, sort_by, is_ecom)
        log_event('INFO', 'fastmoss fetch completed', task_name=task_name, returned=len(videos))

        new_videos = []
        dup_count = 0
        for v in videos:
            vid = str(v.get('video_id', ''))
            if vid in known_ids:
                dup_count += 1
            else:
                new_videos.append(v)
                if len(new_videos) >= limit:
                    break

        if not new_videos:
            safe_update_record(token, TABLE_FETCH_CONFIG, record_id, {
                '执行状态': '成功',
                '新增视频数': 0,
                '重复跳过数': dup_count,
                '执行时间': datetime.now().strftime('%Y-%m-%d %H:%M'),
                '抓取结果': f'无新视频。API返回{len(videos)}条，全部已存在。'
            })
            print(f'⚠️ 无新视频（API返回{len(videos)}条，{dup_count}条重复）')
            return

        inserted, id_map = insert_to_data_table(token, new_videos, task_name)
        log_event('INFO', 'new videos inserted', inserted=inserted)

        downloaded = 0
        for v in new_videos:
            vid = str(v.get('video_id', ''))
            print(f'  下载视频 {vid}...', end=' ', flush=True)
            path, existed, download_status, download_error = download_video(vid)
            if path:
                if not existed:
                    downloaded += 1
                try:
                    file_token = upload_feishu_attachment(token, path, f'{vid}.mp4')
                    if vid in id_map:
                        safe_update_record(token, TABLE_DATA, id_map[vid], {
                            '无水印视频': [{'file_token': file_token, 'name': f'{vid}.mp4'}]
                        })
                        print('✅ 已上传')
                    else:
                        print('✅ 已上传(未找到记录)')
                except Exception as upload_err:
                    print(f'✅ 下载成功(上传失败: {str(upload_err)[:120]})')
                    log_event('WARN', 'video upload failed after download', video_id=vid, error_code='feishu_upload_failed', error=str(upload_err)[:300])
            else:
                print(f'❌ 下载失败({download_status})')
                log_event('WARN', 'video download failed', video_id=vid, error_code=download_status, error=download_error)
            known_ids.add(vid)
            time.sleep(0.5)

        save_dedup(known_ids)

        summary = f'新增{len(new_videos)}条，写入{inserted}条，下载{downloaded}个视频'
        safe_update_record(token, TABLE_FETCH_CONFIG, record_id, {
            '执行状态': '成功',
            '新增视频数': len(new_videos),
            '重复跳过数': dup_count,
            '执行时间': datetime.now().strftime('%Y-%m-%d %H:%M'),
            '抓取结果': summary
        })
        log_event('INFO', 'fetch task success', record_id=record_id, summary=summary)
        print(f'✅ {summary}')

    except Exception as e:
        payload = build_error_payload(e, stage='fetch_trending')
        err = payload['message']
        log_event('ERROR', 'fetch task failed', record_id=record_id, error=err, error_code=payload['error_code'], retryable=payload['retryable'])
        try:
            safe_update_record(token, TABLE_FETCH_CONFIG, record_id, {
                '执行状态': '失败',
                '抓取结果': f"错误[{payload['error_code']}]: {err}",
                '执行时间': datetime.now().strftime('%Y-%m-%d %H:%M')
            })
        except Exception as write_err:
            log_event('ERROR', 'fetch failure writeback failed', record_id=record_id, error=str(write_err)[:500])
        print(f"ERROR_CODE={payload['error_code']} RETRYABLE={str(payload['retryable']).lower()} MESSAGE={err}")
        sys.exit(1)


if __name__ == '__main__':
    main()
