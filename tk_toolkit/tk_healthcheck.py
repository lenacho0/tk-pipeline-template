#!/usr/bin/env python3
"""
TK Pipeline 每日健康巡检
检测所有环节的关键接口是否正常，结果发送到飞书。
用法: python3 tk_healthcheck.py
"""
import json, os, sys, time, requests
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *

FASTMOSS_BASE = 'https://openapi.fastmoss.com'

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
        resp = requests.post(f"{api_cfg['api_base']}/video/v1/search",
            json=body, headers=headers, timeout=15)
        data = resp.json()
        if data.get('code') == 0:
            return True, f"正常 (api_base={api_cfg['api_base']})"
        else:
            return False, f"异常 code={data.get('code')}, msg={data.get('message') or data.get('msg')}"
    except Exception as e:
        return False, f"请求失败: {e}"

def check_feishu_token():
    try:
        token = get_feishu_token()
        resp = requests.get(
            f'https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_DATA}/records?page_size=1',
            headers=feishu_headers(token), timeout=15)
        if resp.json().get('code') == 0:
            return True, "正常"
        return False, f"code={resp.json().get('code')}, msg={resp.json().get('msg')}"
    except Exception as e:
        return False, f"失败: {e}"

def check_gemini():
    try:
        token = get_feishu_token()
        cfg = get_model_config(token, CONFIG_RECORDS['analysis'])
        if not cfg.get('api_key') or not cfg.get('api_base'):
            return False, "飞书配置表缺少 API Key 或 Base URL"
        client = get_gemini_client(cfg['api_key'], cfg['api_base'])
        response = client.models.generate_content(
            model=cfg['model'] or 'gemini-2.0-flash',
            contents='回复"OK"两个字即可')
        if response and response.text:
            return True, f"正常 (模型: {cfg['model']})"
        return False, "无响应"
    except Exception as e:
        return False, f"失败: {e}"

def check_sora():
    try:
        token = get_feishu_token()
        cfg = get_model_config(token, CONFIG_RECORDS['video'])
        if not cfg.get('api_key') or not cfg.get('api_base'):
            return False, "飞书配置表缺少 API Key 或 Base URL"
        api_base = cfg['api_base'].rstrip('/')
        resp = requests.get(f'{api_base}/videos/test_nonexistent_id',
            headers={'Authorization': cfg['api_key']}, timeout=15)
        if resp.status_code < 500:
            return True, f"正常 (代理: {api_base})"
        return False, f"HTTP {resp.status_code}"
    except Exception as e:
        return False, f"失败: {e}"

def check_dispatcher():
    try:
        import subprocess, os, json, time
        script_dir = os.path.dirname(os.path.abspath(__file__))
        heartbeat_file = os.path.join(script_dir, '.dispatcher_heartbeat.json')
        dispatcher_log = os.path.join(script_dir, 'dispatcher.log')
        result = subprocess.run(['pgrep', '-f', 'tk_dispatcher.py'], capture_output=True, text=True)
        pids = [p for p in result.stdout.strip().split('\n') if p.strip()]
        heartbeat = None
        if os.path.exists(heartbeat_file):
            try:
                with open(heartbeat_file, 'r', encoding='utf-8') as f:
                    heartbeat = json.load(f)
            except Exception:
                heartbeat = None

        log_summary = None
        try:
            if os.path.exists(dispatcher_log):
                with open(dispatcher_log, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = [line.strip() for line in f.readlines()[-200:] if line.strip()]
                priority = []
                fallback = []
                for line in reversed(lines):
                    if any(k in line for k in ['Traceback', '❌', 'ERROR', 'Exception', '失败', '崩溃']):
                        priority.append(line)
                    elif any(k in line for k in ['✅', '🚀', '完成', '启动任务', 'started', 'success']):
                        fallback.append(line)
                    elif 'heartbeat' not in line.lower():
                        fallback.append(line)
                picked = priority[0] if priority else (fallback[0] if fallback else None)
                if picked:
                    log_summary = picked[:240]
        except Exception:
            log_summary = None

        if pids:
            parts = [f"运行中 (PID: {pids[0]}"]
            if heartbeat and heartbeat.get('time'):
                parts.append(f", heartbeat={heartbeat.get('time')}, status={heartbeat.get('status')}")
            if log_summary:
                parts.append(f", 日志摘要={log_summary}")
            parts.append(')')
            return True, ''.join(parts)
        if heartbeat:
            base = f"调度器未运行，最近心跳={heartbeat.get('time')} status={heartbeat.get('status')} note={heartbeat.get('note','')}"
            if log_summary:
                base += f"，日志摘要={log_summary}"
            return False, base
        if log_summary:
            return False, f"调度器未运行，日志摘要={log_summary}"
        return False, "调度器未运行！"
    except Exception as e:
        return False, f"检测失败: {e}"

def send_feishu_report(results):
    try:
        token = get_feishu_token()
        now = datetime.now().strftime('%Y-%m-%d %H:%M')
        all_ok = all(ok for ok, _ in results.values())

        lines = [f"🔍 TK Pipeline 每日巡检 — {now}", ""]
        status_map = {
            'FastMoss API': '📺 环节① 爆款抓取',
            'feishu_token': '📋 飞书多维表格',
            'gemini': '🤖 Gemini (环节②③④)',
            'sora': '🎬 Sora (环节⑤)',
            'dispatcher': '⚡ 调度器',
        }
        for key, (ok, msg) in results.items():
            label = status_map.get(key, key)
            icon = "✅" if ok else "❌"
            lines.append(f"{icon} {label}: {msg}")

        if all_ok:
            lines.append("")
            lines.append("🎉 所有接口正常运行")
        else:
            failed = [k for k, (ok, _) in results.items() if not ok]
            lines.append("")
            lines.append(f"⚠️ 异常项: {', '.join(failed)}")

        text = '\n'.join(lines)

        # 如果配置了通知用户 ID，发送飞书消息
        user_id = NOTIFICATION_USER_ID
        if user_id:
            resp = requests.post(
                'https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id',
                headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
                json={
                    'receive_id': user_id,
                    'msg_type': 'text',
                    'content': json.dumps({'text': text})
                }, timeout=15)
            if resp.json().get('code') == 0:
                print("✅ 报告已发送到飞书")
            else:
                print(f"发送失败: {resp.json().get('msg')}")
                print(f"报告内容:\n{text}")
        else:
            print("未配置通知用户，报告仅输出到控制台：")
            print(text)
    except Exception as e:
        print(f"发送报告失败: {e}")

def main():
    print(f"🔍 TK Pipeline 健康巡检 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
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
        print(f"检测 {label}...", end=" ", flush=True)
        try:
            ok, msg = check_fn()
            results[key] = (ok, msg)
            icon = "✅" if ok else "❌"
            print(f"{icon} {msg}")
        except Exception as e:
            results[key] = (False, str(e))
            print(f"❌ {e}")

    print()
    send_feishu_report(results)

if __name__ == '__main__':
    main()
