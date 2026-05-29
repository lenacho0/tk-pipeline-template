"""公共模块：飞书 Token、配置读取、工具函数"""
import json
import os
import requests
import time
import urllib3

urllib3.disable_warnings()

APP_TOKEN = 'LBWUbgRfEavAgjsXNIhcpo0Dnvb'

# 表 ID
TABLE_CONFIG = 'tblPUVFtpjogYOGn'       # 模型与API配置
TABLE_FETCH_CONFIG = 'tbl4cIPQYHSHbFzV'  # 抓取配置
TABLE_DATA = 'tblKNlGHJKwJWyRW'          # 爆款数据表
TABLE_ANALYSIS = 'tblozrImDy0r4dBN'      # 脚本分析
TABLE_SCRIPT_GEN = 'tbl2Yp6T4jDN8Rfr'   # 产品脚本生成
TABLE_PRODUCT = 'tblF2cZmbQEJMiUH'       # 产品信息
TABLE_MODEL = 'tblvpVOYockZmCG8'         # 模特形象
TABLE_VIDEO = 'tblQdTGSsmQbPMQd'         # 视频制作

OPENCLAW_CONFIG = os.path.expanduser('~/.openclaw/config.json')
WORKSPACE = os.path.expanduser('~/.openclaw/workspace-tk')

def load_openclaw_config():
    with open(OPENCLAW_CONFIG) as f:
        return json.load(f)

def get_feishu_token():
    cfg = load_openclaw_config()
    accounts = cfg['channels']['feishu']['accounts']
    account = accounts.get('default') or accounts.get('bot2') or list(accounts.values())[0]
    r = requests.post(
        'https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal',
        json={'app_id': account['appId'], 'app_secret': account['appSecret']}, timeout=10)
    return r.json()['tenant_access_token']

def feishu_headers(token):
    return {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}

def get_record(token, table_id, record_id):
    resp = requests.get(
        f'https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/records/{record_id}',
        headers=feishu_headers(token), timeout=15)
    data = resp.json()
    if data.get('code') != 0:
        raise Exception(f"读取记录失败: {data.get('msg')}")
    return data['data']['record']['fields']

def update_record(token, table_id, record_id, fields, retries=3, timeout=60):
    """飞书记录更新，支持重试机制（应对网络不稳定断连问题）"""
    import time
    url = f'https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/records/{record_id}'
    headers = feishu_headers(token)
    for attempt in range(retries):
        try:
            resp = requests.put(url, headers=headers, json={'fields': fields}, timeout=timeout)
            result = resp.json()
            # API 返回 code != 0 也视为失败（如字段内容超限），主动抛异常触发重试
            if result.get('code') != 0:
                raise Exception(f"飞书 API 错误: code={result.get('code')}, msg={result.get('msg')}")
            return result
        except Exception as e:
            if attempt < retries - 1:
                wait = (attempt + 1) * 5
                print(f'  ⚠️ 写回失败，{wait}秒后重试 ({attempt+1}/{retries}): {e}')
                time.sleep(wait)
            else:
                raise

def list_records(token, table_id, page_size=100, retries=3):
    import time
    all_items = []
    page_token = None
    for attempt in range(retries):
        try:
            while True:
                url = f'https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/records?page_size={page_size}'
                if page_token:
                    url += f'&page_token={page_token}'
                resp = requests.get(url, headers=feishu_headers(token), timeout=30)
                data = resp.json()
                if data.get('code') != 0:
                    break
                all_items.extend(data['data'].get('items', []))
                if not data['data'].get('has_more'):
                    break
                page_token = data['data'].get('page_token')
            return all_items
        except Exception as e:
            if attempt < retries - 1:
                wait = (attempt + 1) * 5
                print(f'  ⚠️ 读取失败，{wait}秒后重试 ({attempt+1}/{retries}): {e}')
                time.sleep(wait)
            else:
                raise

def extract_text(val):
    if isinstance(val, str): return val
    if isinstance(val, list):
        return ''.join(item.get('text', '') if isinstance(item, dict) else str(item) for item in val)
    return str(val) if val else ''

def get_model_config(token, record_id):
    """从模型配置表读取指定环节的配置"""
    fields = get_record(token, TABLE_CONFIG, record_id)
    return {
        'model': extract_text(fields.get('模型名称', '')),
        'api_key': extract_text(fields.get('API Key', '')),
        'api_base': extract_text(fields.get('API 代理地址', '')),
        'prompt': extract_text(fields.get('提示词', '')),
    }

def get_gemini_client(api_key, api_base):
    """
    返回 google.genai.Client（官方SDK客户端）。
    
    AIHubMix 的 /gemini 端点支持 google-genai 原生调用：
    - 文字生成：直接传字符串 contents
    - 视频分析：用 types.File(uri=url, mime_type='video/mp4')
    - 图片生成：需指定 response_modalities=['TEXT', 'IMAGE']
    
    不再区分 /v1（OpenAI兼容）和 /gemini 端点，统一用 google.genai.Client。
    """
    from google.genai import Client
    return Client(api_key=api_key, http_options={'base_url': api_base})
