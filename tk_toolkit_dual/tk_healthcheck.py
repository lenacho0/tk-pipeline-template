#!/usr/bin/env python3
"""
TK Pipeline 健康巡检（支持实例化）
用法:
  python3 tk_healthcheck.py
  TK_INSTANCE=ryan TK_CONFIG_FILE=... python3 tk_healthcheck.py
"""
import json, os, sys, time, requests, subprocess
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
INSTANCE = os.environ.get('TK_INSTANCE', 'default')
sys.path.insert(0, SCRIPT_DIR)
from common import *


def check_fastmoss():
    try:
        token = get_feishu_token()
        api_cfg = get_fetch_api_config(token)
        now = int(time.time())
        headers = {'Authorization': f"Bearer {api_cfg['api_key']}", 'Content-Type': 'application/json'}
        body = {
            'keywords': 'pet',
            'filter': {'publish_time_range': {'min': now - 7*86400, 'max': now}},
            'page': 1, 'pagesize': 1,
        }
        resp = requests.post(f"{api_cfg['api_base']}/video/v1/search", json=body, headers=headers, timeout=15)
        data = resp.json()
        if data.get('code') == 0:
            return True, f"正常 (api_base={api_cfg['api_base']})"
        return False, f"异常 code={data.get('code')}, msg={data.get('message') or data.get('msg')}"
    except Exception as e:
        return False, f"请求失败: {e}"


def check_feishu_token():
    try:
        token = get_feishu_token()
        resp = requests.get(
            f'https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_DATA}/records?page_size=1',
            headers=feishu_headers(token), timeout=15)
        payload = resp.json()
        if payload.get('code') == 0:
            return True, '正常'
        return False, f"code={payload.get('code')}, msg={payload.get('msg')}"
    except Exception as e:
        return False, f"失败: {e}"


def check_gemini():
    try:
        token = get_feishu_token()
        cfg = get_model_config(token, CONFIG_RECORDS['analysis'])
        if not cfg.get('api_key') or not cfg.get('api_base'):
            return False, '飞书配置表缺少 API Key 或 Base URL'
        client = get_gemini_client(cfg['api_key'], cfg['api_base'])
        response = client.models.generate_content(
            model=cfg['model'] or 'gemini-2.0-flash',
            contents='回复"OK"两个字即可')
        if response and response.text:
            return True, f"正常 (模型: {cfg['model']})"
        return False, '无响应'
    except Exception as e:
        return False, f"失败: {e}"


def check_sora():
    try:
        token = get_feishu_token()
        cfg = get_model_config(token, CONFIG_RECORDS['video'])
        if not cfg.get('api_key') or not cfg.get('api_base'):
            return False, '飞书配置表缺少 API Key 或 Base URL'
        api_base = cfg['api_base'].rstrip('/')
        resp = requests.get(f'{api_base}/videos/test_nonexistent_id', headers={'Authorization': cfg['api_key']}, timeout=15)
        if resp.status_code < 500:
            return True, f"正常 (代理: {api_base})"
        return False, f"HTTP {resp.status_code}"
    except Exception as e:
        return False, f"失败: {e}"


def check_dispatcher():
    try:
        heartbeat_file = os.path.join(SCRIPT_DIR, f'.dispatcher_heartbeat.{INSTANCE}.json')
        runtime_log = os.path.join(SCRIPT_DIR, f'dispatcher-runtime.{INSTANCE}.log')
        legacy_log = os.path.join(SCRIPT_DIR, f'dispatcher.{INSTANCE}.log')
        pid_file = os.path.join(SCRIPT_DIR, f'dispatcher.{INSTANCE}.pid')
        heartbeat_fresh_seconds = 180

        pid = None
        if os.path.exists(pid_file):
            try:
                pid = open(pid_file, 'r', encoding='utf-8').read().strip()
            except Exception:
                pid = None

        pid_alive = False
        if pid:
            try:
                os.kill(int(pid), 0)
                pid_alive = True
            except Exception:
                pid_alive = False

        heartbeat = None
        heartbeat_age = None
        heartbeat_fresh = False
        if os.path.exists(heartbeat_file):
            try:
                with open(heartbeat_file, 'r', encoding='utf-8') as f:
                    heartbeat = json.load(f)
                hb_time = heartbeat.get('time')
                if hb_time:
                    hb_dt = datetime.strptime(hb_time, '%Y-%m-%d %H:%M:%S')
                    heartbeat_age = int(time.time() - hb_dt.timestamp())
                    heartbeat_fresh = heartbeat_age <= heartbeat_fresh_seconds
            except Exception:
                heartbeat = None
                heartbeat_age = None
                heartbeat_fresh = False

        log_summary = None
        log_path = runtime_log if os.path.exists(runtime_log) else legacy_log
        if os.path.exists(log_path):
            try:
                with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = [line.strip() for line in f.readlines()[-200:] if line.strip()]
                priority, fallback = [], []
                for line in reversed(lines):
                    if any(k in line for k in ['Traceback', '❌', 'ERROR', 'Exception', '失败', '崩溃']):
                        priority.append(line)
                    elif any(k in line for k in ['✅', '🚀', '完成', '启动任务', 'started', 'success', '运行统计']):
                        fallback.append(line)
                    elif 'heartbeat' not in line.lower():
                        fallback.append(line)
                picked = priority[0] if priority else (fallback[0] if fallback else None)
                if picked:
                    log_summary = picked[:240]
            except Exception:
                log_summary = None

        if pid_alive or (heartbeat_fresh and heartbeat and heartbeat.get('status') == 'running'):
            parts = [f'实例={INSTANCE}', '运行中']
            if pid:
                parts.append(f'pid={pid}')
            if heartbeat and heartbeat.get('time'):
                age_text = f', age={heartbeat_age}s' if heartbeat_age is not None else ''
                parts.append(f"heartbeat={heartbeat.get('time')} status={heartbeat.get('status')}{age_text}")
            if log_summary:
                parts.append(f'日志摘要={log_summary}')
            return True, ' | '.join(parts)

        if heartbeat:
            age_text = f' age={heartbeat_age}s' if heartbeat_age is not None else ''
            base = f"实例={INSTANCE} 调度器未运行，最近心跳={heartbeat.get('time')} status={heartbeat.get('status')}{age_text} note={heartbeat.get('note','')}"
            if log_summary:
                base += f'，日志摘要={log_summary}'
            return False, base
        if log_summary:
            return False, f'实例={INSTANCE} 调度器未运行，日志摘要={log_summary}'
        return False, f'实例={INSTANCE} 调度器未运行！'
    except Exception as e:
        return False, f'检测失败: {e}'


def send_feishu_report(results):
    try:
        token = get_feishu_token()
        now = datetime.now().strftime('%Y-%m-%d %H:%M')
        all_ok = all(ok for ok, _ in results.values())
        lines = [f'🔍 TK Pipeline 巡检 — {now}', f'实例: {INSTANCE}', '']
        status_map = {
            'FastMoss API': '📺 环节① 爆款抓取',
            'feishu_token': '📋 飞书多维表格',
            'gemini': '🤖 Gemini (环节②③④)',
            'sora': '🎬 Sora (环节⑤)',
            'dispatcher': '⚡ 调度器',
        }
        for key, (ok, msg) in results.items():
            label = status_map.get(key, key)
            icon = '✅' if ok else '❌'
            lines.append(f'{icon} {label}: {msg}')
        lines.append('')
        lines.append('🎉 所有接口正常运行' if all_ok else f"⚠️ 异常项: {', '.join(k for k, (ok, _) in results.items() if not ok)}")
        text = '\n'.join(lines)
        user_id = NOTIFICATION_USER_ID
        if user_id:
            resp = requests.post(
                'https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id',
                headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
                json={'receive_id': user_id, 'msg_type': 'text', 'content': json.dumps({'text': text})}, timeout=15)
            if resp.json().get('code') == 0:
                print('✅ 报告已发送到飞书')
            else:
                print(f"发送失败: {resp.json().get('msg')}")
                print(f'报告内容:\n{text}')
        else:
            print('未配置通知用户，报告仅输出到控制台：')
            print(text)
    except Exception as e:
        print(f'发送报告失败: {e}')


def main():
    print(f"🔍 TK Pipeline 健康巡检 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f'实例: {INSTANCE}')
    print()
    results = {}
    checks = [
        ('feishu_token', '飞书 Token', check_feishu_token),
        ('FastMoss API', 'FastMoss API', check_fastmoss),
        ('gemini', 'Gemini API', check_gemini),
        ('sora', 'Sora API', check_sora),
        ('dispatcher', '调度器', check_dispatcher),
    ]
    for key, label, check_fn in checks:
        print(f'检测 {label}...', end=' ', flush=True)
        try:
            ok, msg = check_fn()
            results[key] = (ok, msg)
            print(f"{'✅' if ok else '❌'} {msg}")
        except Exception as e:
            results[key] = (False, str(e))
            print(f'❌ {e}')
    print()
    send_feishu_report(results)


if __name__ == '__main__':
    main()
