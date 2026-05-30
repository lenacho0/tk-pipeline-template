#!/usr/bin/env python3
"""
TK 任务调度器 —— 轮询飞书多维表格，发现「待执行」任务后自动执行对应脚本
零 token 消耗，纯 Python 运行

用法: python3 tk_dispatcher.py
后台运行: nohup python3 tk_dispatcher.py >> dispatcher.log 2>&1 &
"""
import json, os, sys, time, subprocess, logging
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
log = logging.getLogger('dispatcher')

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
POLL_INTERVAL = 30  # 秒
HEALTHCHECK_HOUR = 8  # 每天早上8点巡检
HEALTHCHECK_DONE_FILE = os.path.join(SCRIPTS_DIR, '.healthcheck_today')

# 各表的轮询配置：表ID、状态字段名、触发值、对应脚本、环节名
WATCH_LIST = [
    {
        'name': '爆款抓取',
        'table': TABLE_FETCH_CONFIG,
        'status_field': '执行状态',
        'trigger_value': '待执行',
        'script': 'tk_fetch.py',
    },
    {
        'name': '脚本分析',
        'table': TABLE_ANALYSIS,
        'status_field': '分析状态',
        'trigger_value': '待分析',
        'script': 'tk_analyze.py',
    },
    {
        'name': '产品脚本生成',
        'table': TABLE_SCRIPT_GEN,
        'status_field': '生成状态',
        'trigger_value': '待生成',
        'script': 'tk_script_gen.py',
    },
    {
        'name': '分镜图生成',
        'table': TABLE_SCRIPT_GEN,
        'status_field': '分镜图状态',
        'trigger_value': '待执行',
        'script': 'tk_storyboard.py',
    },
    {
        'name': '视频制作',
        'table': TABLE_VIDEO,
        'status_field': '制作状态',
        'trigger_value': '待执行',
        'script': 'tk_video.py',
    },
]

def check_and_run(token, watch):
    """检查一张表，执行所有待执行的任务"""
    try:
        records = list_records(token, watch['table'])
    except Exception as e:
        log.error(f"[{watch['name']}] 读取表失败: {e}")
        return

    for rec in records:
        record_id = rec['record_id']
        fields = rec.get('fields', {})
        status = extract_text(fields.get(watch['status_field'], ''))

        if status != watch['trigger_value']:
            continue

        # 找到待执行任务
        task_id = extract_text(fields.get('任务ID', '')) or extract_text(fields.get('任务名称', '')) or record_id
        log.info(f"[{watch['name']}] 发现任务: {task_id} ({record_id})")

        # 执行脚本
        script_path = os.path.join(SCRIPTS_DIR, watch['script'])
        try:
            # 视频制作需要更长超时（Sora 生成 + 下载）
            task_timeout = 900 if watch['script'] == 'tk_video.py' else 600
            result = subprocess.run(
                [sys.executable, script_path, record_id],
                capture_output=True, text=True, timeout=task_timeout,
                cwd=SCRIPTS_DIR
            )
            if result.returncode == 0:
                log.info(f"[{watch['name']}] ✅ {task_id} 完成")
            else:
                log.error(f"[{watch['name']}] ❌ {task_id} 失败: {result.stderr[-300:]}")
            if result.stdout.strip():
                log.info(f"  stdout: {result.stdout.strip()[-200:]}")
        except subprocess.TimeoutExpired:
            log.error(f"[{watch['name']}] ⏰ {task_id} 超时(10分钟)")
            try:
                update_record(token, watch['table'], record_id, {
                    watch['status_field']: '失败',
                })
            except: pass
        except Exception as e:
            log.error(f"[{watch['name']}] 执行异常: {e}")

def check_video_sync(token):
    """检查视频制作表是否有「待同步」记录，有就执行同步脚本"""
    try:
        records = list_records(token, TABLE_VIDEO)
    except Exception as e:
        log.error(f"[视频同步] 读取表失败: {e}")
        return

    for rec in records:
        fields = rec.get('fields', {})
        sync_status = extract_text(fields.get('同步状态', ''))
        if sync_status == '待同步':
            record_id = rec['record_id']
            log.info(f"[视频同步] 检测到同步触发: {record_id}")

            # 先把同步状态改为「同步中」
            try:
                update_record(token, TABLE_VIDEO, record_id, {'同步状态': '同步中'})
            except: pass

            # 执行同步脚本
            script_path = os.path.join(SCRIPTS_DIR, 'tk_sync_video.py')
            try:
                result = subprocess.run(
                    [sys.executable, script_path],
                    capture_output=True, text=True, timeout=120,
                    cwd=SCRIPTS_DIR
                )
                if result.returncode == 0:
                    log.info(f"[视频同步] ✅ 同步完成")
                else:
                    log.error(f"[视频同步] ❌ 同步失败: {result.stderr[-300:]}")
                if result.stdout.strip():
                    log.info(f"  stdout: {result.stdout.strip()[-300:]}")
            except Exception as e:
                log.error(f"[视频同步] 执行异常: {e}")

            # 更新同步状态为「已完成」
            try:
                update_record(token, TABLE_VIDEO, record_id, {'同步状态': '已完成'})
            except: pass

            break  # 一次只处理一个同步触发


def check_daily_health():
    """每天早上8点执行一次健康巡检"""
    now = datetime.now()
    if now.hour != HEALTHCHECK_HOUR:
        return
    # 检查今天是否已经巡检过
    if os.path.exists(HEALTHCHECK_DONE_FILE):
        with open(HEALTHCHECK_DONE_FILE) as f:
            done_date = f.read().strip()
        if done_date == now.strftime('%Y-%m-%d'):
            return
    # 执行巡检
    log.info("🔍 开始每日健康巡检...")
    try:
        result = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS_DIR, 'tk_healthcheck.py')],
            capture_output=True, text=True, timeout=120,
            cwd=SCRIPTS_DIR
        )
        if result.stdout.strip():
            for line in result.stdout.strip().split('\n'):
                log.info(f"  [巡检] {line}")
        if result.returncode != 0 and result.stderr.strip():
            log.error(f"  [巡检] 错误: {result.stderr.strip()[-200:]}")
        # 标记今天已完成
        with open(HEALTHCHECK_DONE_FILE, 'w') as f:
            f.write(now.strftime('%Y-%m-%d'))
    except Exception as e:
        log.error(f"[巡检] 执行异常: {e}")


def main():
    log.info("🚀 TK 任务调度器启动")
    log.info(f"   轮询间隔: {POLL_INTERVAL}秒")
    log.info(f"   监控环节: {', '.join(w['name'] for w in WATCH_LIST)}")

    token = get_feishu_token()
    token_time = time.time()

    while True:
        # 刷新 token（每20分钟）
        if time.time() - token_time > 1200:
            try:
                token = get_feishu_token()
                token_time = time.time()
            except Exception as e:
                log.error(f"刷新 token 失败: {e}")
                time.sleep(POLL_INTERVAL)
                continue

        # 检查视频同步触发
        check_video_sync(token)

        # 每日健康巡检（早上8点）
        check_daily_health()

        # 轮询每张表
        for watch in WATCH_LIST:
            check_and_run(token, watch)

        time.sleep(POLL_INTERVAL)

if __name__ == '__main__':
    main()
