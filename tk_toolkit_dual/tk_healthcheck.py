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
from tk_shot_storyboard import get_table_field_names


def check_feishu_token():
    try:
        token = get_feishu_token()
        resp = requests.get(
            f'https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_CONFIG}/records?page_size=1',
            headers=feishu_headers(token), timeout=15)
        payload = resp.json()
        if payload.get('code') == 0:
            return True, '正常'
        return False, f"code={payload.get('code')}, msg={payload.get('msg')}"
    except Exception as e:
        return False, f"失败: {e}"


def check_first_last_video_config():
    try:
        if not TABLE_FIRST_LAST_VIDEO:
            return False, 'config.json 缺少 first_last_video 表 ID'
        token = get_feishu_token()
        required_table_fields = {
            '记录类型',
            '记录状态',
            '父任务记录ID',
            '批次ID',
            '当前批次ID',
            '场景编号',
            '关联产品记录',
            '产品名称',
            '产品参考图file_tokenJSON',
            '首尾帧文档附件',
            '拆分状态',
            '场景拆分操作',
            '首帧图操作',
            '尾帧图操作',
            '视频操作',
            '拆分版本',
            '首帧图版本',
            '尾帧图版本',
            '视频版本',
        }
        field_names = get_table_field_names(token, TABLE_FIRST_LAST_VIDEO)
        missing_table_fields = sorted(required_table_fields - set(field_names))
        if missing_table_fields:
            return False, f"首尾帧表缺少字段: {', '.join(missing_table_fields)}"

        required = {
            '图片生成-OTU': ('模型名称', 'API Key', 'API 代理地址'),
            '分镜视频生成-OTU': ('模型名称', 'API Key', 'API 代理地址'),
        }
        records = safe_list_records(token, TABLE_CONFIG)
        stage_map = {}
        for rec in records:
            fields = rec.get('fields', {})
            stage_name = extract_text(fields.get('环节', '')).strip()
            if stage_name in required:
                stage_map[stage_name] = fields

        missing_stages = [name for name in required if name not in stage_map]
        if missing_stages:
            return False, f"缺少配置环节: {', '.join(missing_stages)}"

        bad = []
        for stage_name, field_names in required.items():
            fields = stage_map[stage_name]
            missing_fields = [
                field_name
                for field_name in field_names
                if not extract_text(fields.get(field_name, '')).strip()
            ]
            if missing_fields:
                bad.append(f"{stage_name} 缺少 {', '.join(missing_fields)}")
        if bad:
            return False, '；'.join(bad)
        return True, f"正常 (表={TABLE_FIRST_LAST_VIDEO}, Markdown直拆✓, 图片生成-OTU✓, 分镜视频生成-OTU✓)"
    except Exception as e:
        return False, f'失败: {e}'


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
            'feishu_token': '📋 飞书多维表格',
            'first_last_video': '🎬 首尾帧视频',
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
        ('first_last_video', '首尾帧视频配置', check_first_last_video_config),
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
