#!/usr/bin/env python3
"""
环节1：爆款视频抓取
用法: python3 tk_fetch.py <record_id>
从抓取配置表读取参数 → FastMoss 抓取 → 去重 → 写入数据表 → 下载无水印视频 → 上传飞书附件 → 更新状态
"""
import json, os, sys, time, requests
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *

FASTMOSS_TOKEN = 'fkhrujriavzpolvanncdmszthtpirpxz'
FASTMOSS_BASE = 'https://openapi.fastmoss.com'
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
    return {'近1天':1,'近3天':3,'近7天':7,'近15天':15,'近30天':30}.get(text, 7)

def fetch_fastmoss(keyword, days, region, min_sold, min_play, limit, sort_by='按销售量', is_ecom='仅带货视频'):
    """POST 请求 FastMoss v1 search API，返回完整数据（含商品信息）"""
    now = int(time.time())
    min_time = now - days * 86400
    all_videos = []
    headers = {
        'Authorization': f'Bearer {FASTMOSS_TOKEN}',
        'Content-Type': 'application/json',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    }

    region_code_map = {'泰国': 'TH', '美国': 'US', '印尼': 'ID', '越南': 'VN',
                       '马来西亚': 'MY', '菲律宾': 'PH', '日本': 'JP', '英国': 'GB',
                       '墨西哥': 'MX', '西班牙': 'ES', '法国': 'FR', '巴西': 'BR',
                       '全部地区': None, '不限': None, '': None}

    region_codes = region_code_map.get(region)
    if region and region not in region_code_map:
        # 直接作为代码使用（如用户输入了 TH、US 等）
        region_codes = region

    # 是否带货过滤
    ecommerce_filter = is_ecom != '不限'  # 默认「仅带货视频」或「仅非带货视频」都加过滤

    # 排序方式映射到 API orderby
    orderby_map = {
        '按播放量': 'play_count',
        '按点赞量': 'digg_count',
        '按评论数': 'comment_count',
        '按分享数': 'share_count',
        '按互动率': 'interact_rate',
        '按粉丝数': 'follower_count',
        '按发布时间': 'create_time',
        '按销量': 'sold_count',
        '按销售量': 'sold_count',
    }
    api_orderby = orderby_map.get(sort_by, 'play_count')
    need_client_sort = False

    for page in range(1, max(limit // 100 + 3, 6)):
        body = {
            'keywords': keyword,
            'filter': {
                'publish_time_range': {'min': min_time, 'max': now},
            },
            'orderby': api_orderby,
            'page': page,
            'pagesize': 100,
        }
        # 带货过滤（服务端）
        if ecommerce_filter:
            body['filter']['is_ecommerce_creator'] = True
        # 地区过滤
        if region_codes:
            body['filter']['region'] = [region_codes]
        # 最低播放量
        if min_play > 0:
            body['filter']['play_count_range'] = {'min': min_play}

        try:
            resp = requests.post(f'{FASTMOSS_BASE}/video/v1/search',
                json=body, headers=headers, timeout=30)
            data = resp.json()
            if data.get('code') != 0 and data.get('code') != 200:
                print(f'  API 错误: code={data.get("code")}, msg={data.get("message")}')
                break
            items = data.get('data', {}).get('list', []) or data.get('data', {}).get('video_list', [])
            if not items: break
            all_videos.extend(items)
            time.sleep(0.5)
        except Exception as e:
            print(f'  请求异常: {e}')
            break

    # 过滤最低销量
    filtered = [v for v in all_videos if (v.get('sold_count', 0) or 0) >= min_sold and (v.get('play_count', 0) or 0) >= min_play]

    # 客户端带货过滤
    if is_ecom == '仅带货视频':
        filtered = [v for v in filtered if v.get('is_ecommerce') == 1]
    elif is_ecom == '仅非带货视频':
        filtered = [v for v in filtered if v.get('is_ecommerce') == 0]

    return filtered

def download_video(video_id):
    os.makedirs(VIDEO_DIR, exist_ok=True)
    path = os.path.join(VIDEO_DIR, f'{video_id}.mp4')
    if os.path.exists(path) and os.path.getsize(path) > 1000:
        return path, True
    try:
        resp = requests.get('https://www.tikwm.com/api/',
            params={'url': f'https://www.tiktok.com/@user/video/{video_id}'}, timeout=30)
        data = resp.json()
        if data.get('code') == 0 and data.get('data', {}).get('play'):
            dl = requests.get(data['data']['play'], timeout=120, stream=True)
            if dl.status_code == 200:
                with open(path, 'wb') as f:
                    for chunk in dl.iter_content(8192): f.write(chunk)
                if os.path.getsize(path) > 1000: return path, False
    except: pass
    return None, False

def upload_feishu_attachment(token, file_path, file_name):
    """上传文件到飞书 bitable，返回 file_token"""
    try:
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
                timeout=120)
        data = resp.json()
        if data.get('code') == 0:
            return data['data']['file_token']
        else:
            print(f'  上传失败: {data.get("msg")}')
    except Exception as e:
        print(f'  上传异常: {e}')
    return None

def insert_to_data_table(token, videos, task_name):
    """写入飞书数据表，返回 {video_id: record_id} 映射"""
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
            '收藏数': v.get('forward_count', 0),  # forward_count = 收藏数
            '互动率(%)': v.get('interact_rate', 0),
            '是否广告': '是' if v.get('is_ad') == 1 else '否',
            '销售量': v.get('sold_count', 0),
            '销售额': v.get('sale_amount', 0),
            '达人昵称': creator.get('nickname', ''),
            '达人ID': creator.get('unique_id', ''),
            '达人分类': creator.get('category_name', ''),
            '粉丝数': creator.get('follower_count', 0),
        }

        # 商品信息
        if product:
            fields['商品名称'] = product.get('title', '')
            fields['商品价格'] = product.get('price', '')
            fields['商品销量'] = product.get('sold_count', 0)
            fields['商品销售额'] = product.get('sale_amount', 0)
            fields['商品分类'] = product.get('category_name', '')

        # URL 字段
        if v.get('video_url'):
            fields['视频链接'] = {'link': v['video_url'], 'text': 'TikTok'}

        records.append({'fields': fields})

    # 批量写入，记录 video_id → record_id 映射
    id_map = {}  # video_id → record_id
    inserted = 0
    for i in range(0, len(records), 10):
        batch = records[i:i+10]
        resp = requests.post(
            f'https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_DATA}/records/batch_create',
            headers=feishu_headers(token), json={'records': batch}, timeout=30)
        result = resp.json()
        if result.get('code') == 0:
            for rec in result['data']['records']:
                vid = rec['fields'].get('视频ID', '')
                if vid:
                    id_map[vid] = rec['record_id']
            inserted += len(result['data']['records'])
        else:
            print(f'  写入失败: {result.get("msg")}')
        time.sleep(0.3)
    return inserted, id_map

def main():
    if len(sys.argv) < 2:
        print("用法: python3 tk_fetch.py <record_id>")
        sys.exit(1)
    record_id = sys.argv[1]
    token = get_feishu_token()
    try:
        fields = get_record(token, TABLE_FETCH_CONFIG, record_id)
        task_name = extract_text(fields.get('任务名称', '未命名'))
        limit = int(fields.get('抓取数量', 50) or 50)
        days = time_range_to_days(extract_text(fields.get('时间范围', '近7天')))
        keyword = extract_text(fields.get('关键词', ''))
        min_sold = int(fields.get('最低销量', 0) or 0)
        min_play = int(fields.get('最低播放量', 0) or 0)
        region = extract_text(fields.get('地区', ''))
        sort_by = extract_text(fields.get('排序方式', '按销售量'))
        is_ecom = extract_text(fields.get('是否带货', '仅带货视频'))

        print(f'📋 任务: {task_name} | 关键词:{keyword} | 地区:{region} | {days}天 | 限{limit}条 | 排序:{sort_by} | {is_ecom}')
        update_record(token, TABLE_FETCH_CONFIG, record_id, {'执行状态': '抓取中'})
        known_ids = load_dedup()

        videos = fetch_fastmoss(keyword, days, region, min_sold, min_play, limit * 3, sort_by, is_ecom)
        print(f'  API返回 {len(videos)} 条视频')

        # API 已经按配置排序，无需再排
        new_videos, dup_count = [], 0
        for v in videos:
            vid = str(v.get('video_id', ''))
            if vid in known_ids: dup_count += 1
            else:
                new_videos.append(v)
                if len(new_videos) >= limit: break

        if not new_videos:
            update_record(token, TABLE_FETCH_CONFIG, record_id, {
                '执行状态': '成功', '新增视频数': 0, '重复跳过数': dup_count,
                '执行时间': datetime.now().strftime('%Y-%m-%d %H:%M'),
                '抓取结果': f'无新视频。API返回{len(videos)}条，全部已存在。'})
            print(f'⚠️ 无新视频（API返回{len(videos)}条，{dup_count}条重复）')
            return

        # 写入飞书数据表
        inserted, id_map = insert_to_data_table(token, new_videos, task_name)
        print(f'  写入飞书 {inserted} 条')

        # 下载视频 + 上传飞书附件
        downloaded = 0
        for v in new_videos:
            vid = str(v.get('video_id', ''))
            print(f'  下载视频 {vid}...', end=' ', flush=True)
            path, existed = download_video(vid)
            if path:
                if not existed:
                    downloaded += 1
                # 上传到飞书附件字段
                file_token = upload_feishu_attachment(token, path, f'{vid}.mp4')
                if file_token and vid in id_map:
                    try:
                        update_record(token, TABLE_DATA, id_map[vid], {
                            '无水印视频': [{'file_token': file_token, 'name': f'{vid}.mp4'}]
                        })
                        print(f'✅ 已上传')
                    except Exception as e:
                        print(f'✅ 下载成功(写入附件失败: {e})')
                elif file_token:
                    print(f'✅ 已上传(未找到记录)')
                else:
                    print(f'✅ 下载成功(上传失败)')
            else:
                print(f'❌ 下载失败')
            known_ids.add(vid)
            time.sleep(0.5)
        save_dedup(known_ids)

        summary = f'新增{len(new_videos)}条，写入{inserted}条，下载{downloaded}个视频'
        update_record(token, TABLE_FETCH_CONFIG, record_id, {
            '执行状态': '成功', '新增视频数': len(new_videos), '重复跳过数': dup_count,
            '执行时间': datetime.now().strftime('%Y-%m-%d %H:%M'), '抓取结果': summary})
        print(f'✅ {summary}')

    except Exception as e:
        import traceback
        traceback.print_exc()
        try: update_record(token, TABLE_FETCH_CONFIG, record_id, {
            '执行状态': '失败', '抓取结果': str(e)[:500],
            '执行时间': datetime.now().strftime('%Y-%m-%d %H:%M')})
        except: pass
        print(f'❌ {e}')
        sys.exit(1)

if __name__ == '__main__':
    main()
