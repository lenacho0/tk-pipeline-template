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

FASTMOSS_TOKEN = 'fkhrujriavzpolvanncdmszthtpirpxz'
FASTMOSS_BASE = 'https://openapi.fastmoss.com'

def check_fastmoss():
    """环节1: FastMoss API"""
    try:
        now = int(time.time())
        headers = {'Authorization': f'Bearer {FASTMOSS_TOKEN}', 'Content-Type': 'application/json'}
        body = {
            'keywords': 'pet',
            'filter': {'publish_time_range': {'min': now - 7*86400, 'max': now}},
            'page': 1, 'pagesize': 1,
        }
        resp = requests.post(f'{FASTMOSS_BASE}/video/v1/search',
            json=body, headers=headers, timeout=15)
        data = resp.json()
        if data.get('code') == 0 and data.get('data', {}).get('list'):
            items = data['data']['list']
            return True, f"正常 (返回 {len(items)} 条数据)"
        else:
            return False, f"异常 code={data.get('code')}, msg={data.get('message')}"
    except Exception as e:
        return False, f"请求失败: {e}"

def check_feishu_token():
    """飞书 Token"""
    try:
        token = get_feishu_token()
        # 验证 token 有效性
        resp = requests.get(
            f'https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_DATA}/records?page_size=1',
            headers=feishu_headers(token), timeout=15)
        if resp.json().get('code') == 0:
            return True, "正常"
        return False, f"code={resp.json().get('code')}, msg={resp.json().get('msg')}"
    except Exception as e:
        return False, f"失败: {e}"

def check_gemini():
    """环节②③④: Gemini API（通过飞书配置表读取）"""
    try:
        token = get_feishu_token()
        # 读分析环节的配置
        cfg = get_model_config(token, 'recveizDqAaxWy')
        if not cfg.get('api_key') or not cfg.get('api_base'):
            return False, "飞书配置表缺少 API Key 或 Base URL"
        # 简单测试：发一个小请求
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
    """环节⑤: Sora API"""
    try:
        token = get_feishu_token()
        cfg = get_model_config(token, 'recveppNaVCcyd')
        if not cfg.get('api_key') or not cfg.get('api_base'):
            return False, "飞书配置表缺少 API Key 或 Base URL"
        # 测试连接：查一个不存在的任务，看是否返回有效错误而非连接失败
        api_base = cfg['api_base'].rstrip('/')
        resp = requests.get(f'{api_base}/videos/test_nonexistent_id',
            headers={'Authorization': cfg['api_key']}, timeout=15)
        if resp.status_code < 500:
            return True, f"正常 (代理: {api_base})"
        return False, f"HTTP {resp.status_code}"
    except Exception as e:
        return False, f"失败: {e}"

def check_dispatcher():
    """调度器进程"""
    try:
        import subprocess
        result = subprocess.run(['pgrep', '-f', 'tk_dispatcher.py'], capture_output=True, text=True)
        pids = result.stdout.strip().split('\n') if result.stdout.strip() else []
        if pids and pids[0]:
            return True, f"运行中 (PID: {pids[0]})"
        return False, "调度器未运行！"
    except Exception as e:
        return False, f"检测失败: {e}"

def send_feishu_report(results):
    """发送巡检报告到飞书"""
    try:
        openclaw_cfg = load_openclaw_config()
        account = openclaw_cfg['channels']['feishu']['accounts']['default']
        app_id = account['appId']
        app_secret = account['appSecret']
        
        # 获取 tenant token
        r = requests.post(
            'https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal',
            json={'app_id': app_id, 'app_secret': app_secret}, timeout=10)
        t_token = r.json().get('tenant_access_token')
        if not t_token:
            return
        
        now = datetime.now().strftime('%Y-%m-%d %H:%M')
        all_ok = all(ok for ok, _ in results.values())
        
        # 构建文本报告
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
        
        # 发到飞书（需要用户的 open_id）
        # 从 openclaw 配置找 owner 或者用固定的
        # 这里用 message tool 的方式发 — 但脚本里直接调 API
        # 我们先打印结果，由调度器或 cron 触发时通过其他方式通知
        
        # 直接用飞书发消息给自己
        user_id = 'ou_0e8b1b4dfca5a47166f0fa12c7a7a880'
        resp = requests.post(
            'https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id',
            headers={'Authorization': f'Bearer {t_token}', 'Content-Type': 'application/json'},
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
    
    # 发送飞书报告
    print()
    send_feishu_report(results)

if __name__ == '__main__':
    main()
