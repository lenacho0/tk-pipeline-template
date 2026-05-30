"""公共模块：飞书 Token、配置读取、工具函数
所有配置从同目录的 config.json 读取，不依赖任何外部系统。
"""
import json
import os
import requests
import time
import random
import traceback

# ============================================================
# 配置加载（从 config.json）
# ============================================================
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_CONFIG_PATH = os.path.join(_SCRIPT_DIR, 'config.json')
_CONFIG_PATH = os.environ.get('TK_CONFIG_FILE', _DEFAULT_CONFIG_PATH)
if not os.path.isabs(_CONFIG_PATH):
    _CONFIG_PATH = os.path.abspath(os.path.join(_SCRIPT_DIR, _CONFIG_PATH))

def _load_config():
    if not os.path.exists(_CONFIG_PATH):
        raise FileNotFoundError(
            f"找不到配置文件: {_CONFIG_PATH}\n"
            "请先复制 config.json.template 为 config.json 并填写你的配置。"
        )
    with open(_CONFIG_PATH, encoding='utf-8') as f:
        return json.load(f)

_CFG = _load_config()

# 飞书配置
_FEISHU = _CFG['feishu']
APP_TOKEN = _FEISHU['bitable_app_token']
_TABLES = _FEISHU['tables']

TABLE_CONFIG       = _TABLES['config']           # 模型与API配置
TABLE_SCRIPT_DOC_TASKS = _TABLES.get('script_doc_tasks', _TABLES.get('script_doc_shots', '')) # 脚本文档任务
TABLE_SCRIPT_DOC_REFERENCE_ASSETS = _TABLES.get('script_doc_reference_assets', _TABLES.get('script_doc_shots', '')) # 脚本文档参考资产
TABLE_SCRIPT_DOC_SHOTS = _TABLES.get('script_doc_shots', '') # 脚本文档分镜生产
TABLE_STORYBOARD_VIDEO = _TABLES.get('storyboard_video', '') # 故事板图片/Omni视频生成
TABLE_NINE_GRID_VIDEO = _TABLES.get('nine_grid_video', '') # 多图九宫格视频生成
TABLE_FIRST_LAST_VIDEO = _TABLES.get('first_last_video', '') # 首尾帧视频生成
TABLE_MULTI_ROLE_FIRST_LAST = _TABLES.get('multi_role_first_last', '') # 多角色首尾帧生成
TABLE_VOICE_LIBRARY = _TABLES.get('voice_library', '')        # 音色库
TABLE_TEXT_AUDIO = _TABLES.get('text_audio', '')              # 文案转音频
TABLE_PRODUCT      = _TABLES['product']           # 产品信息
TABLE_MODEL        = _TABLES['model_appearance']  # 模特形象

# 各环节在「模型与API配置」表中的 record_id
CONFIG_RECORDS = _CFG['config_records']

# 产品名称 → record_id 映射（旧版兼容；新逻辑优先动态查产品表）
PRODUCT_MAP = _CFG.get('products', {})

# 通知
NOTIFICATION_USER_ID = _CFG.get('notification', {}).get('feishu_user_id', '')
DISPATCHER_CFG = _CFG.get('dispatcher', {})

# 工作目录
WORKSPACE = os.path.abspath(os.path.join(_SCRIPT_DIR, _CFG.get('workspace', './workspace')))
os.makedirs(WORKSPACE, exist_ok=True)

# ============================================================
# 飞书 API 工具
# ============================================================
def get_feishu_token():
    """获取飞书 tenant_access_token"""
    r = requests.post(
        'https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal',
        json={'app_id': _FEISHU['app_id'], 'app_secret': _FEISHU['app_secret']},
        timeout=10)
    data = r.json()
    if 'tenant_access_token' not in data:
        raise Exception(f"获取飞书 Token 失败: {data}")
    return data['tenant_access_token']

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

def update_record(token, table_id, record_id, fields):
    resp = requests.put(
        f'https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/records/{record_id}',
        headers=feishu_headers(token),
        json={'fields': fields}, timeout=30)
    return resp.json()

def list_records(token, table_id, page_size=100):
    all_items = []
    page_token = None
    while True:
        url = f'https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/records?page_size={page_size}'
        if page_token:
            url += f'&page_token={page_token}'
        resp = requests.get(url, headers=feishu_headers(token), timeout=15)
        data = resp.json()
        if data.get('code') != 0:
            break
        all_items.extend(data['data'].get('items') or [])
        if not data['data'].get('has_more'):
            break
        page_token = data['data'].get('page_token')
    return all_items

def extract_text(val):
    if isinstance(val, str): return val
    if isinstance(val, list):
        return ''.join(item.get('text', '') if isinstance(item, dict) else str(item) for item in val)
    return str(val) if val else ''


def extract_linked_record_ids(val):
    record_ids = []
    if isinstance(val, list):
        for item in val:
            if isinstance(item, dict) and item.get('record_ids'):
                record_ids.extend(item.get('record_ids') or [])
    return [rid for rid in record_ids if rid]


def get_product_record_id(token, product_value):
    linked_ids = extract_linked_record_ids(product_value)
    if linked_ids:
        return linked_ids[0]

    product_name = extract_text(product_value).strip()
    if not product_name:
        return None

    mapped = PRODUCT_MAP.get(product_name)
    if mapped:
        return mapped

    records = safe_list_records(token, TABLE_PRODUCT)
    matched = []
    for rec in records:
        fields = rec.get('fields', {})
        candidates = [
            extract_text(fields.get('产品名称', '')).strip(),
            extract_text(fields.get('产品名称-th', '')).strip(),
            extract_text(fields.get('产品名', '')).strip(),
        ]
        if product_name in [c for c in candidates if c]:
            matched.append(rec)

    if len(matched) == 1:
        return matched[0]['record_id']
    if len(matched) > 1:
        raise Exception(f'产品名称重名，无法唯一匹配: {product_name}')
    return None


def get_product_record(token, product_value):
    record_id = get_product_record_id(token, product_value)
    if not record_id:
        return None, None
    fields = safe_get_record(token, TABLE_PRODUCT, record_id)
    return record_id, fields


def get_product_info(token, product_value):
    record_id, fields = get_product_record(token, product_value)
    if not record_id or not fields:
        return None
    return {
        '产品名称-th': extract_text(fields.get('产品名称-th', '')),
        '产品规格': extract_text(fields.get('产品规格', '')),
        '核心卖点': extract_text(fields.get('核心卖点', '')),
        '使用场景': extract_text(fields.get('使用场景', '')),
        '目标用户': extract_text(fields.get('目标用户', '')),
    }


def get_model_info(token, task_fields):
    model_link = task_fields.get('选择模特')
    if not model_link:
        return ''
    model_infos = []
    if isinstance(model_link, list):
        for item in model_link:
            if isinstance(item, dict) and 'record_ids' in item:
                for rid in item['record_ids']:
                    try:
                        mf = safe_get_record(token, TABLE_MODEL, rid)
                        info = f"- 名称: {extract_text(mf.get('模特名称',''))}"
                        info += f", 类型: {extract_text(mf.get('模特类型',''))}"
                        info += f", 品种: {extract_text(mf.get('品种',''))}"
                        info += f", 毛色/肤色: {extract_text(mf.get('毛色/肤色',''))}"
                        info += f", 性别: {extract_text(mf.get('性别',''))}"
                        info += f", 外观描述: {extract_text(mf.get('外观描述',''))}"
                        model_infos.append(info)
                    except Exception:
                        pass
    return '\n'.join(model_infos) if model_infos else '无指定模特'


def get_task_product_value(fields):
    linked = fields.get('关联产品')
    if linked and extract_linked_record_ids(linked):
        return linked
    return fields.get('选择产品', '')


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
    from google import genai
    return genai.Client(api_key=api_key, http_options={'base_url': api_base})


def ensure_task_dir(record_id):
    task_dir = os.path.join(WORKSPACE, 'storyboard_work', record_id)
    os.makedirs(task_dir, exist_ok=True)
    return task_dir


def download_attachment(token, file_token, save_path):
    resp = requests.get(
        f'https://open.feishu.cn/open-apis/drive/v1/medias/{file_token}/download',
        headers={'Authorization': f'Bearer {token}'}, timeout=120, stream=True)
    if resp.status_code == 200:
        with open(save_path, 'wb') as f:
            for chunk in resp.iter_content(8192):
                f.write(chunk)
        return True
    return False


def safe_download_attachment(token, file_token, save_path):
    return with_retry(
        lambda: _download_or_raise(token, file_token, save_path),
        max_attempts=3,
        label='feishu attachment download'
    )


def _download_or_raise(token, file_token, save_path):
    ok = download_attachment(token, file_token, save_path)
    if not ok:
        raise Exception(f'附件下载失败: {file_token}')
    return True


def upload_image_to_feishu(token, file_path, file_name):
    with open(file_path, 'rb') as f:
        resp = requests.post(
            'https://open.feishu.cn/open-apis/drive/v1/medias/upload_all',
            headers={'Authorization': f'Bearer {token}'},
            data={
                'file_name': file_name,
                'parent_type': 'bitable_file',
                'parent_node': APP_TOKEN,
                'size': str(os.path.getsize(file_path))
            },
            files={'file': (file_name, f, 'image/png')},
            timeout=120
        )
    data = resp.json()
    if data.get('code') != 0:
        raise Exception(f"飞书上传失败: {data.get('msg')}")
    return data['data']['file_token']


# ============================================================
# 稳定性增强：重试 / 安全请求 / 安全写回
# ============================================================
def log_event(level, message, **kwargs):
    ts = time.strftime('%Y-%m-%d %H:%M:%S')
    payload = ' '.join(f'{k}={repr(v)}' for k, v in kwargs.items() if v is not None)
    line = f"[{ts}] [{level}] {message}"
    if payload:
        line += f" | {payload}"
    print(line, flush=True)


def build_error_payload(error, stage='unknown'):
    msg = extract_text(str(error))[:500]
    lower = msg.lower()

    error_code = 'RUNTIME_BUG'
    retryable = False
    failure_status = 'failed_terminal'

    if '429' in lower or 'rate limit' in lower or 'too many requests' in lower:
        error_code = 'UPSTREAM_RATE_LIMIT'
        retryable = True
        failure_status = 'failed_retryable'
    elif 'read timed out' in lower or 'timeout' in lower or 'timed out' in lower:
        error_code = 'UPSTREAM_NETWORK'
        retryable = True
        failure_status = 'failed_retryable'
    elif 'server disconnected without sending a response' in lower or 'remoteprotocolerror' in lower or 'connection reset by peer' in lower or 'remote end closed connection' in lower:
        error_code = 'UPSTREAM_NETWORK'
        retryable = True
        failure_status = 'failed_retryable'
    elif 'ssl' in lower or 'connection' in lower or 'httpsconnectionpool' in lower or 'max retries exceeded' in lower:
        error_code = 'UPSTREAM_NETWORK'
        retryable = True
        failure_status = 'failed_retryable'
    elif '空文本' in msg or '未返回图片内容' in msg or '返回图片过小' in msg or 'empty output' in lower:
        error_code = 'MODEL_EMPTY_OUTPUT'
        retryable = True
        failure_status = 'failed_retryable'
    elif 'json 解析失败' in msg or '未返回有效 json' in msg or 'schema' in lower:
        error_code = 'MODEL_SCHEMA_INVALID'
        retryable = True
        failure_status = 'failed_retryable'
    elif 'prompt' in lower:
        error_code = 'PROMPT_BUILD_FAILED'
        retryable = False
        failure_status = 'failed_terminal'
    elif '产品图片缺失' in msg or '缺少' in msg or '为空' in msg or '无脚本内容' in msg:
        error_code = 'INPUT_MISSING'
        retryable = False
        failure_status = 'failed_terminal'
    elif 'api key' in lower or '配置' in msg:
        error_code = 'CONFIG_INVALID'
        retryable = False
        failure_status = 'failed_terminal'
    elif 'upload' in lower and 'feishu' in lower:
        error_code = 'UPLOAD_FAILED'
        retryable = True
        failure_status = 'failed_retryable'
    elif '写回' in msg or 'fieldnamenotfound' in lower:
        error_code = 'WRITEBACK_FAILED'
        retryable = True
        failure_status = 'failed_retryable'

    return {
        'stage': stage,
        'status': failure_status,
        'error_code': error_code,
        'retryable': retryable,
        'message': msg,
    }


def sleep_backoff(attempt, base=1.5, cap=20):
    delay = min(cap, base * (2 ** max(0, attempt - 1)))
    delay = delay + random.uniform(0, 0.8)
    time.sleep(delay)


def with_retry(fn, max_attempts=3, label='operation', retry_predicate=None):
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except Exception as e:
            last_error = e
            should_retry = attempt < max_attempts
            if retry_predicate is not None:
                try:
                    should_retry = should_retry and retry_predicate(e)
                except Exception:
                    pass
            log_event('WARN', f'{label} failed', attempt=attempt, max_attempts=max_attempts, error=str(e)[:500])
            if not should_retry:
                break
            sleep_backoff(attempt)
    raise last_error


def safe_request(method, url, *, headers=None, timeout=30, max_attempts=3, acceptable_codes=(0,), **kwargs):
    def _do():
        resp = requests.request(method, url, headers=headers, timeout=timeout, **kwargs)
        resp.raise_for_status()
        data = resp.json()
        if 'code' in data and acceptable_codes is not None and data.get('code') not in acceptable_codes:
            raise Exception(f"API返回异常 code={data.get('code')} msg={data.get('msg')}")
        return data
    return with_retry(_do, max_attempts=max_attempts, label=f'{method.upper()} {url}')


def safe_update_record(token, table_id, record_id, fields, max_attempts=3):
    url = f'https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/records/{record_id}'
    return safe_request(
        'put', url,
        headers=feishu_headers(token),
        json={'fields': fields},
        timeout=30,
        max_attempts=max_attempts,
    )


def safe_get_record(token, table_id, record_id, max_attempts=3):
    url = f'https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/records/{record_id}'
    data = safe_request('get', url, headers=feishu_headers(token), timeout=15, max_attempts=max_attempts)
    return data['data']['record']['fields']


def safe_list_records(token, table_id, page_size=100, max_attempts=3):
    all_items = []
    page_token = None
    while True:
        url = f'https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/records?page_size={page_size}'
        if page_token:
            url += f'&page_token={page_token}'
        data = safe_request('get', url, headers=feishu_headers(token), timeout=15, max_attempts=max_attempts)
        all_items.extend(data['data'].get('items') or [])
        if not data['data'].get('has_more'):
            break
        page_token = data['data'].get('page_token')
    return all_items
