#!/usr/bin/env python3
"""
TK 任务调度器 —— 轮询飞书多维表格，发现「待执行」任务后自动执行对应脚本
增强版：增加本地并发控制、避免同一任务重复启动、子进程异步轮询回收、最小任务级自动重试、运行统计

用法: python3 tk_dispatcher.py
后台运行: nohup python3 tk_dispatcher.py >> dispatcher.log 2>&1 &
"""
import json, os, sys, time, subprocess, logging
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
log = logging.getLogger('dispatcher')

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
POLL_INTERVAL = 30
HEALTHCHECK_HOUR = 8
HEALTHCHECK_DONE_FILE = os.path.join(SCRIPTS_DIR, '.healthcheck_today')
RUNNING_TASKS_FILE = os.path.join(SCRIPTS_DIR, '.running_tasks.json')
RETRY_STATE_FILE = os.path.join(SCRIPTS_DIR, '.retry_state.json')
METRICS_FILE = os.path.join(SCRIPTS_DIR, '.dispatcher_metrics.json')

WATCH_LIST = [
    {
        'name': '爆款抓取',
        'table': TABLE_FETCH_CONFIG,
        'status_field': '执行状态',
        'trigger_value': '待执行',
        'running_value': '抓取中',
        'script': 'tk_fetch.py',
        'args': [],
        'timeout': 900,
        'max_concurrency': 1,
        'max_retries': 2,
    },
    {
        'name': '脚本分析',
        'table': TABLE_ANALYSIS,
        'status_field': '分析状态',
        'trigger_value': '待分析',
        'running_value': '分析中',
        'script': 'tk_analyze.py',
        'args': [],
        'timeout': 900,
        'max_concurrency': 2,
        'max_retries': 2,
    },
    {
        'name': '产品脚本生成',
        'table': TABLE_SCRIPT_GEN,
        'status_field': '生成状态',
        'trigger_value': '待生成',
        'running_value': '生成中',
        'script': 'tk_script_gen.py',
        'args': [],
        'timeout': 600,
        'max_concurrency': 2,
        'max_retries': 2,
    },
    {
        'name': '分镜图生成',
        'table': TABLE_SCRIPT_GEN,
        'status_field': '分镜图状态',
        'trigger_value': '待执行',
        'running_value': '生成中',
        'script': 'tk_storyboard.py',
        'args': [],
        'timeout': 1200,
        'max_concurrency': 2,
        'max_retries': 2,
    },
    {
        'name': '逐镜头脚本生成',
        'table': TABLE_SHOT_SCRIPT_GEN,
        'status_field': '生成状态',
        'trigger_value': '待生成',
        'running_value': '生成中',
        'script': 'tk_shot_script_gen.py',
        'args': [],
        'timeout': 900,
        'max_concurrency': 2,
        'max_retries': 2,
    },
    {
        'name': '逐镜头图片生成',
        'table': TABLE_SHOT_STORYBOARD,
        'status_field': '生成状态',
        'trigger_value': '待生成',
        'running_value': '生成中',
        'script': 'tk_shot_storyboard.py',
        'args': ['render'],
        'timeout': 1200,
        'max_concurrency': 2,
        'max_retries': 2,
    },
    {
        'name': '视频制作',
        'table': TABLE_VIDEO,
        'status_field': '制作状态',
        'trigger_value': '待执行',
        'running_value': '制作中',
        'script': 'tk_video.py',
        'args': [],
        'timeout': 1800,
        'max_concurrency': 1,
        'max_retries': 1,
    },
]

running_processes = {}


def load_json_file(path):
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_json_file(path, data):
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.warning(f'保存状态文件失败 {path}: {e}')


def load_running_tasks():
    return load_json_file(RUNNING_TASKS_FILE)


def save_running_tasks(data):
    save_json_file(RUNNING_TASKS_FILE, data)


def load_retry_state():
    return load_json_file(RETRY_STATE_FILE)


def save_retry_state(data):
    save_json_file(RETRY_STATE_FILE, data)


def today_str():
    return datetime.now().strftime('%Y-%m-%d')


def load_metrics():
    data = load_json_file(METRICS_FILE)
    if data.get('date') != today_str():
        data = {
            'date': today_str(),
            'launched': {},
            'success': {},
            'failed': {},
            'retried': {},
            'timeouts': {},
            'last_errors': []
        }
    return data


def save_metrics(data):
    save_json_file(METRICS_FILE, data)


def bump_metric(section, watch_name, amount=1):
    metrics = load_metrics()
    metrics.setdefault(section, {})
    metrics[section][watch_name] = int(metrics[section].get(watch_name, 0) or 0) + amount
    save_metrics(metrics)


def append_last_error(watch_name, record_id, reason):
    metrics = load_metrics()
    metrics.setdefault('last_errors', [])
    metrics['last_errors'].append({
        'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'watch': watch_name,
        'record_id': record_id,
        'reason': str(reason)[:300],
    })
    metrics['last_errors'] = metrics['last_errors'][-50:]
    save_metrics(metrics)


def log_metrics_snapshot():
    metrics = load_metrics()
    log.info(f"📊 今日运行统计 launched={metrics.get('launched', {})} success={metrics.get('success', {})} failed={metrics.get('failed', {})} retried={metrics.get('retried', {})} timeouts={metrics.get('timeouts', {})}")


def make_task_key(watch, record_id):
    return f"{watch['script']}::{record_id}"


def count_running_by_script(script_name):
    count = 0
    for proc in running_processes.values():
        if proc['watch']['script'] == script_name:
            count += 1
    return count


def get_retry_count(task_key):
    state = load_retry_state()
    return int(state.get(task_key, {}).get('retry_count', 0) or 0)


def set_retry_count(task_key, retry_count, watch=None, record_id=None):
    state = load_retry_state()
    state[task_key] = {
        'retry_count': retry_count,
        'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'script': watch['script'] if watch else state.get(task_key, {}).get('script'),
        'record_id': record_id or state.get(task_key, {}).get('record_id'),
    }
    save_retry_state(state)


def clear_retry_count(task_key):
    state = load_retry_state()
    if task_key in state:
        state.pop(task_key, None)
        save_retry_state(state)


def maybe_retry_task(token, watch, record_id, task_key, reason):
    retry_count = get_retry_count(task_key)
    max_retries = watch.get('max_retries', 0)
    if retry_count < max_retries:
        new_retry = retry_count + 1
        set_retry_count(task_key, new_retry, watch=watch, record_id=record_id)
        try:
            safe_update_record(token, watch['table'], record_id, {
                watch['status_field']: watch['trigger_value']
            })
            bump_metric('retried', watch['name'])
            log.warning(f"[{watch['name']}] 任务失败，已回退待重试: {record_id} ({new_retry}/{max_retries}) reason={reason}")
            return True
        except Exception as e:
            log.error(f"[{watch['name']}] 回退重试状态失败: {record_id} error={e}")
            return False
    else:
        log.error(f"[{watch['name']}] 任务失败且超过重试上限: {record_id} retries={retry_count} reason={reason}")
        return False


def mark_task_failed(token, watch, record_id, task_key, reason='failed', timeout=False):
    append_last_error(watch['name'], record_id, reason)
    retried = maybe_retry_task(token, watch, record_id, task_key, reason)
    if retried:
        return
    try:
        safe_update_record(token, watch['table'], record_id, {
            watch['status_field']: '失败'
        })
    except Exception as e:
        log.error(f"[{watch['name']}] 标记失败写回失败: {record_id} error={e}")
    bump_metric('failed', watch['name'])
    if timeout:
        bump_metric('timeouts', watch['name'])


def cleanup_finished_processes(token):
    finished = []
    for task_key, proc_info in list(running_processes.items()):
        process = proc_info['process']
        watch = proc_info['watch']
        record_id = proc_info['record_id']
        started_at = proc_info['started_at']
        timeout = watch.get('timeout', 900)
        elapsed = time.time() - started_at

        if process.poll() is None and elapsed > timeout:
            log.error(f"[{watch['name']}] 任务超时，终止: {record_id}")
            try:
                process.kill()
            except Exception:
                pass
            mark_task_failed(token, watch, record_id, task_key, reason='timeout', timeout=True)
            finished.append(task_key)
            continue

        if process.poll() is not None:
            try:
                stdout, stderr = process.communicate(timeout=1)
            except Exception:
                stdout, stderr = '', ''

            if process.returncode == 0:
                log.info(f"[{watch['name']}] ✅ 完成: {record_id}")
                clear_retry_count(task_key)
                bump_metric('success', watch['name'])
            else:
                err_text = str(stderr)[-300:] if stderr else 'subprocess_nonzero_exit'
                log.error(f"[{watch['name']}] ❌ 失败: {record_id} stderr={err_text}")
                mark_task_failed(token, watch, record_id, task_key, reason=err_text)

            if stdout and stdout.strip():
                log.info(f"[{watch['name']}] stdout: {stdout.strip()[-300:]}")
            finished.append(task_key)

    if finished:
        running_state = load_running_tasks()
        for task_key in finished:
            running_processes.pop(task_key, None)
            running_state.pop(task_key, None)
        save_running_tasks(running_state)


def try_claim_task(token, watch, record_id):
    try:
        latest = safe_get_record(token, watch['table'], record_id)
        latest_status = extract_text(latest.get(watch['status_field'], ''))
        if latest_status != watch['trigger_value']:
            return False
        safe_update_record(token, watch['table'], record_id, {
            watch['status_field']: watch['running_value']
        })
        return True
    except Exception as e:
        log.warning(f"[{watch['name']}] claim任务失败 {record_id}: {e}")
        return False


def check_and_run(token, watch):
    try:
        records = safe_list_records(token, watch['table'])
    except Exception as e:
        log.error(f"[{watch['name']}] 读取表失败: {e}")
        append_last_error(watch['name'], 'TABLE', f'读取表失败: {e}')
        return

    current_running = count_running_by_script(watch['script'])
    available_slots = max(0, watch.get('max_concurrency', 1) - current_running)
    if available_slots <= 0:
        return

    launched = 0
    running_state = load_running_tasks()

    for rec in records:
        if launched >= available_slots:
            break

        record_id = rec['record_id']
        fields = rec.get('fields', {})
        status = extract_text(fields.get(watch['status_field'], ''))
        if status != watch['trigger_value']:
            continue

        task_key = make_task_key(watch, record_id)
        if task_key in running_processes or task_key in running_state:
            continue

        task_id = extract_text(fields.get('任务ID', '')) or extract_text(fields.get('任务名称', '')) or record_id
        if not try_claim_task(token, watch, record_id):
            continue

        script_path = os.path.join(SCRIPTS_DIR, watch['script'])
        try:
            extra_args = watch.get('args', []) or []
            process = subprocess.Popen(
                [sys.executable, script_path, *extra_args, record_id],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=SCRIPTS_DIR
            )
            running_processes[task_key] = {
                'process': process,
                'watch': watch,
                'record_id': record_id,
                'task_id': task_id,
                'started_at': time.time(),
            }
            running_state[task_key] = {
                'script': watch['script'],
                'record_id': record_id,
                'task_id': task_id,
                'started_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            save_running_tasks(running_state)
            bump_metric('launched', watch['name'])
            launched += 1
            log.info(f"[{watch['name']}] 🚀 已启动任务: {task_id} ({record_id}) retry={get_retry_count(task_key)}")
        except Exception as e:
            log.error(f"[{watch['name']}] 启动失败: {e}")
            append_last_error(watch['name'], record_id, f'启动失败: {e}')
            try:
                safe_update_record(token, watch['table'], record_id, {
                    watch['status_field']: watch['trigger_value']
                })
            except Exception:
                pass


def check_video_sync(token):
    try:
        records = safe_list_records(token, TABLE_VIDEO)
    except Exception as e:
        log.error(f"[视频同步] 读取表失败: {e}")
        append_last_error('视频同步', 'TABLE', f'读取表失败: {e}')
        return

    for rec in records:
        fields = rec.get('fields', {})
        sync_status = extract_text(fields.get('同步状态', ''))
        if sync_status == '待同步':
            record_id = rec['record_id']
            log.info(f"[视频同步] 检测到同步触发: {record_id}")
            try:
                safe_update_record(token, TABLE_VIDEO, record_id, {'同步状态': '同步中'})
            except Exception:
                pass

            script_path = os.path.join(SCRIPTS_DIR, 'tk_sync_video.py')
            try:
                result = subprocess.run(
                    [sys.executable, script_path],
                    capture_output=True, text=True, timeout=180,
                    cwd=SCRIPTS_DIR
                )
                if result.returncode == 0:
                    log.info(f"[视频同步] ✅ 同步完成")
                else:
                    err = result.stderr[-300:]
                    log.error(f"[视频同步] ❌ 同步失败: {err}")
                    append_last_error('视频同步', record_id, err)
                if result.stdout.strip():
                    log.info(f"  stdout: {result.stdout.strip()[-300:]}")
            except Exception as e:
                log.error(f"[视频同步] 执行异常: {e}")
                append_last_error('视频同步', record_id, e)

            try:
                safe_update_record(token, TABLE_VIDEO, record_id, {'同步状态': '已完成'})
            except Exception:
                pass
            break


def check_daily_health():
    now = datetime.now()
    if now.hour != HEALTHCHECK_HOUR:
        return
    if os.path.exists(HEALTHCHECK_DONE_FILE):
        with open(HEALTHCHECK_DONE_FILE) as f:
            done_date = f.read().strip()
        if done_date == now.strftime('%Y-%m-%d'):
            return
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
        with open(HEALTHCHECK_DONE_FILE, 'w') as f:
            f.write(now.strftime('%Y-%m-%d'))
    except Exception as e:
        log.error(f"[巡检] 执行异常: {e}")
        append_last_error('健康巡检', 'SYSTEM', e)


def bootstrap_running_state():
    if os.path.exists(RUNNING_TASKS_FILE):
        try:
            os.remove(RUNNING_TASKS_FILE)
        except Exception:
            pass


def main():
    log.info("🚀 TK 任务调度器启动（增强版 + 自动重试 + 运行统计）")
    log.info(f"   轮询间隔: {POLL_INTERVAL}秒")
    log.info(f"   监控环节: {', '.join(w['name'] for w in WATCH_LIST)}")

    bootstrap_running_state()
    token = get_feishu_token()
    token_time = time.time()
    last_metrics_log = 0

    while True:
        if time.time() - token_time > 1200:
            try:
                token = get_feishu_token()
                token_time = time.time()
            except Exception as e:
                log.error(f"刷新 token 失败: {e}")
                append_last_error('系统', 'TOKEN', e)
                time.sleep(POLL_INTERVAL)
                continue

        cleanup_finished_processes(token)
        check_video_sync(token)
        check_daily_health()

        for watch in WATCH_LIST:
            check_and_run(token, watch)

        if time.time() - last_metrics_log > 600:
            log_metrics_snapshot()
            last_metrics_log = time.time()

        time.sleep(POLL_INTERVAL)


if __name__ == '__main__':
    main()
