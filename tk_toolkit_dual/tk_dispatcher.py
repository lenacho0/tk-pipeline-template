#!/usr/bin/env python3
"""
TK 任务调度器 —— 轮询飞书多维表格，发现「待执行」任务后自动执行对应脚本
增强版：增加本地并发控制、避免同一任务重复启动、子进程异步轮询回收、最小任务级自动重试、运行统计

用法: python3 tk_dispatcher.py
后台运行: nohup python3 tk_dispatcher.py >> dispatcher.log 2>&1 &
"""
import json, os, sys, time, subprocess, logging, urllib.parse
from datetime import datetime
from logging.handlers import RotatingFileHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
INSTANCE = os.environ.get('TK_INSTANCE', 'default')


def get_dispatcher_table_key(argv=None, environ=None):
    env = environ if environ is not None else os.environ
    env_value = (env.get('TK_DISPATCHER_TABLE_KEY') or '').strip()
    if env_value:
        return env_value

    args = list(sys.argv[1:] if argv is None else argv)
    for index, arg in enumerate(args):
        if arg == '--table-key' and index + 1 < len(args):
            return args[index + 1].strip()
        if arg.startswith('--table-key='):
            return arg.split('=', 1)[1].strip()
    return ''


def sanitize_scope_component(value):
    text = str(value or '').strip()
    return ''.join(ch if ch.isalnum() or ch in ('_', '-') else '_' for ch in text)


def runtime_scope_name(instance, table_key=None):
    instance_part = sanitize_scope_component(instance or 'default') or 'default'
    table_part = sanitize_scope_component(table_key)
    if table_part:
        return f'{instance_part}.{table_part}'
    return instance_part


def scoped_runtime_file(prefix, instance, table_key=None, extension='json'):
    scope = runtime_scope_name(instance, table_key)
    suffix = f'.{extension}' if extension else ''
    return os.path.join(SCRIPTS_DIR, f'{prefix}.{scope}{suffix}')


TABLE_KEY = get_dispatcher_table_key()
RUNTIME_SCOPE = runtime_scope_name(INSTANCE, TABLE_KEY)
POLL_INTERVAL = int(DISPATCHER_CFG.get('poll_interval', 30) or 30)
HEALTHCHECK_HOUR = int(DISPATCHER_CFG.get('healthcheck_hour', 8) or 8)
HEALTHCHECK_DONE_FILE = os.path.join(SCRIPTS_DIR, f'.healthcheck_today.{INSTANCE}')
RUNNING_TASKS_FILE = scoped_runtime_file('.running_tasks', INSTANCE, TABLE_KEY)
RETRY_STATE_FILE = scoped_runtime_file('.retry_state', INSTANCE, TABLE_KEY)
METRICS_FILE = scoped_runtime_file('.dispatcher_metrics', INSTANCE, TABLE_KEY)
HEARTBEAT_FILE = scoped_runtime_file('.dispatcher_heartbeat', INSTANCE, TABLE_KEY)
DEAD_LETTER_FILE = scoped_runtime_file('.dead_letter_tasks', INSTANCE, TABLE_KEY)
CIRCUIT_BREAKER_FILE = scoped_runtime_file('.circuit_breakers', INSTANCE, TABLE_KEY)
STAGE_CFG = DISPATCHER_CFG.get('stages', {})
CIRCUIT_CFG = DISPATCHER_CFG.get('circuit_breaker', {})
GLOBAL_MAX_CONCURRENCY = int(DISPATCHER_CFG.get('global_max_concurrency') or 0)
TABLE_MAX_CONCURRENCY_CFG = DISPATCHER_CFG.get('table_max_concurrency', {})
DEFAULT_TABLE_MAX_CONCURRENCY = int(DISPATCHER_CFG.get('default_table_max_concurrency') or 20)
CONCURRENCY_CONTROL_STAGE = 'Dispatcher并发控制'
TABLE_CONCURRENCY_CONTROL_STAGE = 'Dispatcher表格并发'
CONCURRENCY_POLICY_TTL_SECONDS = int(DISPATCHER_CFG.get('concurrency_policy_ttl_seconds', 60) or 60)
_CONCURRENCY_POLICY_CACHE = {
    'loaded_at': 0,
    'policy': {'stage_policies': {}, 'table_policies': {}, 'global_max_concurrency': None, 'source_rows': []},
}
DISPATCHER_TABLE_ID_BY_APP_TABLE = {
    '001-多角色首尾帧生成表': TABLE_MULTI_ROLE_FIRST_LAST,
    '002-首尾帧视频生成表': TABLE_FIRST_LAST_VIDEO,
    '003-1脚本文档-任务表': TABLE_SCRIPT_DOC_TASKS,
    '003-2脚本文档-参考资产表': TABLE_SCRIPT_DOC_REFERENCE_ASSETS,
    '003-3脚本文档-分镜生产表': TABLE_SCRIPT_DOC_SHOTS,
    '003-脚本文档生产表': TABLE_SCRIPT_DOC_UNIFIED,
    '004-故事板视频生成表': TABLE_STORYBOARD_VIDEO,
    '005-多图宫格视频生成表': TABLE_NINE_GRID_VIDEO,
    '005-多图九宫格视频生成表': TABLE_NINE_GRID_VIDEO,
    '006-视频编辑任务表': TABLE_VIDEO_EDIT,
    '008-图生视频生成表': TABLE_PROMPT_IMAGE_VIDEO,
    '音色库': TABLE_VOICE_LIBRARY,
    '文案音频表': TABLE_TEXT_AUDIO,
}
TABLE_SCAN_STATE_FILE = scoped_runtime_file('.table_scan_state', INSTANCE, TABLE_KEY)
RECORD_STATE_CACHE_FILE = scoped_runtime_file('.record_state_cache', INSTANCE, TABLE_KEY)
SCAN_CFG = DISPATCHER_CFG.get('scan', {})
TABLE_MIN_INTERVAL_SECONDS = int(SCAN_CFG.get('table_min_interval_seconds', 20) or 20)
RECORD_STATE_CACHE_TTL_SECONDS = int(SCAN_CFG.get('record_state_cache_ttl_seconds', 300) or 300)
RUNTIME_LOG_FILE = scoped_runtime_file('dispatcher-runtime', INSTANCE, TABLE_KEY, extension='log')
_TABLE_FIELD_KINDS_CACHE = {}
_WATCH_CANDIDATE_CACHE = {}
ATTACHMENT_FIELD_TYPE_IDS = {17, '17', 'attachment'}
KNOWN_ATTACHMENT_FIELD_NAMES = {
    '参考图',
    '关键帧图',
    '视频片段',
    '首帧图',
    '尾帧图',
    '首尾帧视频',
    '故事板图',
    '分镜视频',
    '宫格图',
    '九宫格图',
    '生成图片',
    '生成视频',
    '源视频',
    '结果视频',
}

log = logging.getLogger('dispatcher')
log.handlers.clear()
log.setLevel(logging.INFO)
log.propagate = False
_formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', '%Y-%m-%d %H:%M:%S')
_stream_handler = logging.StreamHandler()
_stream_handler.setFormatter(_formatter)
log.addHandler(_stream_handler)
_file_handler = RotatingFileHandler(RUNTIME_LOG_FILE, maxBytes=2_000_000, backupCount=5, encoding='utf-8')
_file_handler.setFormatter(_formatter)
log.addHandler(_file_handler)

WATCH_LIST = [
    {
        'name': '音色生成',
        'table': TABLE_VOICE_LIBRARY,
        'status_field': '生成状态',
        'trigger_value': '待生成',
        'trigger_values': ['待生成', '生成中'],
        'running_value': '生成中',
        'failed_value': '失败',
        'error_field': '错误信息',
        'script': 'tk_voice_library.py',
        'args': [],
        'timeout': 600,
        'max_concurrency': 1,
        'max_retries': 1,
    },
    {
        'name': '文案音频生成',
        'table': TABLE_TEXT_AUDIO,
        'status_field': '生成状态',
        'trigger_value': '待生成',
        'trigger_values': ['待生成', '生成中'],
        'running_value': '生成中',
        'failed_value': '失败',
        'error_field': '错误信息',
        'script': 'tk_text_audio.py',
        'args': [],
        'timeout': 300,
        'max_concurrency': 2,
        'max_retries': 2,
    },
    {
        'name': '视频编辑生成',
        'table': TABLE_VIDEO_EDIT,
        'status_field': '编辑状态',
        'trigger_value': '待生成',
        'trigger_values': ['待生成', '生成中'],
        'running_value': '生成中',
        'failed_value': '失败',
        'error_field': '错误信息',
        'script': 'tk_video_edit.py',
        'args': ['edit'],
        'timeout': 2400,
        'max_concurrency': 1,
        'max_retries': 1,
        'keep_when_table_missing': True,
        'claim_clear_values_by_trigger_value': {
            '待生成': {
                '结果视频': [],
                '视频任务ID': '',
                '错误信息': '',
            },
        },
    },
    {
        'name': '多图宫格方案生成',
        'table': TABLE_NINE_GRID_VIDEO,
        'status_field': '方案生成状态',
        'trigger_value': '待生成',
        'trigger_values': ['待生成', '生成中'],
        'running_value': '生成中',
        'failed_value': '失败',
        'error_field': '错误信息',
        'script': 'tk_nine_grid_video.py',
        'args': ['plan'],
        'timeout': 900,
        'max_concurrency': 1,
        'max_retries': 1,
        'keep_when_table_missing': True,
        'required_field_values': {'记录类型': ['母任务']},
    },
    {
        'name': '多图宫格参考图生成',
        'table': TABLE_NINE_GRID_VIDEO,
        'status_field': '参考图生成状态',
        'trigger_value': '待生成',
        'trigger_values': ['待生成', '生成中'],
        'running_value': '生成中',
        'failed_value': '失败',
        'error_field': '参考图错误信息',
        'script': 'tk_nine_grid_video.py',
        'args': ['reference'],
        'timeout': 1200,
        'max_concurrency': 1,
        'max_retries': 1,
        'required_field_values': {'记录类型': ['参考资产']},
        'claim_clear_values_by_trigger_value': {
            '待生成': {
                '参考图': [],
                '参考图file_token': '',
                '参考图本地路径': '',
                '参考图任务ID': '',
                '参考图错误信息': '',
                '参考图生成时间': None,
                '错误信息': '',
            },
        },
    },
    {
        'name': '多图宫格参考图审核推进',
        'table': TABLE_NINE_GRID_VIDEO,
        'status_field': '参考图审核状态',
        'trigger_value': '通过',
        'running_value': '通过',
        'failed_value': '通过',
        'error_field': '参考图错误信息',
        'script': 'tk_nine_grid_video.py',
        'args': ['reference-approval'],
        'timeout': 300,
        'max_concurrency': 1,
        'max_retries': 0,
        'required_field_values': {'记录类型': ['参考资产'], '参考图审核状态': ['通过']},
        'claim_clear_values': {
            '参考图操作': '不触发',
            '错误信息': '',
        },
    },
    {
        'name': '多图宫格参考图重生成',
        'table': TABLE_NINE_GRID_VIDEO,
        'status_field': '参考图操作',
        'trigger_value': '重新生成参考图',
        'running_value': '重新生成参考图',
        'failed_value': '不触发',
        'error_field': '参考图错误信息',
        'script': 'tk_nine_grid_video.py',
        'args': ['reference'],
        'timeout': 1200,
        'max_concurrency': 1,
        'max_retries': 0,
        'required_field_values': {'记录类型': ['参考资产']},
        'claim_clear_values': {
            '参考图': [],
            '参考图file_token': '',
            '参考图本地路径': '',
            '参考图任务ID': '',
            '参考图错误信息': '',
            '参考图生成时间': None,
            '参考图生成状态': '不触发',
            '错误信息': '',
        },
    },
    {
        'name': '多图宫格图片生成',
        'table': TABLE_NINE_GRID_VIDEO,
        'status_field': '图片生成状态',
        'trigger_value': '待生成',
        'trigger_values': ['待生成', '生成中'],
        'running_value': '生成中',
        'failed_value': '失败',
        'error_field': '图片错误信息',
        'script': 'tk_nine_grid_video.py',
        'args': ['image'],
        'timeout': 1200,
        'max_concurrency': 1,
        'max_retries': 1,
        'required_field_values': {'记录类型': ['Board分段']},
        'claim_clear_values_by_trigger_value': {
            '待生成': {
                '宫格图': [],
                '九宫格图': [],
                '图片任务ID': '',
                '图片错误信息': '',
                '图片生成时间': None,
                '分镜视频': [],
                '分镜视频URL': None,
                '视频任务ID': '',
                '视频错误信息': '',
                '视频生成时间': None,
                '视频生成状态': '不触发',
                '错误信息': '',
            },
        },
    },
    {
        'name': '多图宫格视频生成',
        'table': TABLE_NINE_GRID_VIDEO,
        'status_field': '视频生成状态',
        'trigger_value': '待生成',
        'trigger_values': ['待生成', '生成中'],
        'running_value': '生成中',
        'failed_value': '失败',
        'error_field': '视频错误信息',
        'script': 'tk_nine_grid_video.py',
        'args': ['video'],
        'timeout': 2400,
        'max_concurrency': 1,
        'max_retries': 3,
        'required_field_values': {'记录类型': ['Board分段']},
        'claim_clear_values_by_trigger_value': {
            '待生成': {
                '分镜视频': [],
                '分镜视频URL': None,
                '视频任务ID': '',
                '视频错误信息': '',
                '视频生成时间': None,
                '错误信息': '',
            },
        },
    },
    {
        'name': '008图生视频图片生成',
        'table': TABLE_PROMPT_IMAGE_VIDEO,
        'status_field': '图片生成状态',
        'trigger_value': '待生成',
        'trigger_values': ['待生成', '生成中'],
        'running_value': '生成中',
        'failed_value': '失败',
        'error_field': '图片错误信息',
        'script': 'tk_prompt_image_video.py',
        'args': ['image'],
        'timeout': 2400,
        'max_concurrency': 1,
        'max_retries': 1,
        'claim_clear_values_by_trigger_value': {
            '待生成': {
                '生成图片': [],
                '图片file_token': '',
                '图片本地路径': '',
                '图片任务ID': '',
                '图片原始响应JSON': '',
                '图片审核状态': '待确认',
                '图片错误信息': '',
                '视频生成状态': '不触发',
                '生成视频': [],
                '生成视频file_token': '',
                '视频本地路径': '',
                '视频任务ID': '',
                '视频原始响应JSON': '',
                '视频错误信息': '',
                '错误信息': '',
            },
        },
    },
    {
        'name': '008图生视频视频生成',
        'table': TABLE_PROMPT_IMAGE_VIDEO,
        'status_field': '视频生成状态',
        'trigger_value': '待生成',
        'trigger_values': ['待生成', '生成中'],
        'running_value': '生成中',
        'failed_value': '失败',
        'error_field': '视频错误信息',
        'script': 'tk_prompt_image_video.py',
        'args': ['video'],
        'timeout': 2400,
        'max_concurrency': 1,
        'max_retries': 1,
        'claim_clear_values_by_trigger_value': {
            '待生成': {
                '生成视频': [],
                '生成视频file_token': '',
                '视频本地路径': '',
                '视频任务ID': '',
                '视频原始响应JSON': '',
                '视频错误信息': '',
                '错误信息': '',
            },
        },
    },
    {
        'name': '004故事板文档解析',
        'table': TABLE_STORYBOARD_VIDEO,
        'status_field': '解析状态',
        'trigger_value': '待解析',
        'trigger_values': ['待解析', '解析中'],
        'running_value': '解析中',
        'failed_value': '失败',
        'error_field': '错误信息',
        'script': 'tk_storyboard_video.py',
        'args': ['parse'],
        'timeout': 900,
        'max_concurrency': 1,
        'max_retries': 1,
        'keep_when_table_missing': True,
        'required_field_values': {'记录类型': ['母任务']},
        'claim_clear_values': {
            '错误信息': '',
        },
    },
    {
        'name': '004故事板图片生成',
        'table': TABLE_STORYBOARD_VIDEO,
        'status_field': '图片生成状态',
        'trigger_value': '待生成',
        'trigger_values': ['待生成', '生成中'],
        'running_value': '生成中',
        'failed_value': '失败',
        'error_field': '图片错误信息',
        'script': 'tk_storyboard_video.py',
        'args': ['image'],
        'timeout': 2400,
        'max_concurrency': 1,
        'max_retries': 1,
        'keep_when_table_missing': True,
        'required_field_values': {'记录类型': ['Storyboard分段']},
        'claim_clear_values_by_trigger_value': {
            '待生成': {
                '生成图片': [],
                '图片file_token': '',
                '图片本地路径': '',
                '图片任务ID': '',
                '图片原始响应JSON': '',
                '图片审核状态': '待确认',
                '图片错误信息': '',
                '视频生成状态': '不触发',
                '生成视频': [],
                '生成视频file_token': '',
                '视频本地路径': '',
                '视频任务ID': '',
                '视频原始响应JSON': '',
                '视频错误信息': '',
                '错误信息': '',
            },
        },
    },
    {
        'name': '004故事板视频生成',
        'table': TABLE_STORYBOARD_VIDEO,
        'status_field': '视频生成状态',
        'trigger_value': '待生成',
        'trigger_values': ['待生成', '生成中'],
        'running_value': '生成中',
        'failed_value': '失败',
        'error_field': '视频错误信息',
        'script': 'tk_storyboard_video.py',
        'args': ['video'],
        'timeout': 2400,
        'max_concurrency': 1,
        'max_retries': 1,
        'keep_when_table_missing': True,
        'required_field_values': {'记录类型': ['Storyboard分段']},
        'claim_clear_values_by_trigger_value': {
            '待生成': {
                '生成视频': [],
                '生成视频file_token': '',
                '视频本地路径': '',
                '视频任务ID': '',
                '视频原始响应JSON': '',
                '视频错误信息': '',
                '错误信息': '',
            },
        },
    },
    {
        'name': '首尾帧批量场景拆分',
        'table': TABLE_FIRST_LAST_VIDEO,
        'status_field': '拆分状态',
        'trigger_value': '待拆分',
        'trigger_values': ['待拆分', '拆分中'],
        'running_value': '拆分中',
        'failed_value': '失败',
        'error_field': '错误信息',
        'script': 'tk_first_last_video.py',
        'args': ['batch-parse'],
        'timeout': 1200,
        'max_concurrency': 1,
        'max_retries': 1,
        'skip_deprecated_records': True,
        'skip_if_field_values': {'记录类型': ['场景子任务']},
    },
    {
        'name': '首尾帧文档拆分',
        'table': TABLE_FIRST_LAST_VIDEO,
        'status_field': '文档拆分状态',
        'trigger_value': '待拆分',
        'trigger_values': ['待拆分', '拆分中'],
        'running_value': '拆分中',
        'failed_value': '失败',
        'error_field': '错误信息',
        'script': 'tk_first_last_video.py',
        'args': ['parse'],
        'timeout': 900,
        'max_concurrency': 1,
        'max_retries': 1,
        'skip_deprecated_records': True,
    },
    {
        'name': '首尾帧场景重新拆分',
        'table': TABLE_FIRST_LAST_VIDEO,
        'status_field': '场景拆分操作',
        'trigger_value': '重新拆分场景',
        'running_value': '重新拆分场景',
        'failed_value': '不触发',
        'error_field': '错误信息',
        'script': 'tk_first_last_video.py',
        'args': ['regenerate-split'],
        'timeout': 1200,
        'max_concurrency': 1,
        'max_retries': 0,
        'skip_deprecated_records': True,
        'required_field_values': {'记录类型': ['', '母任务']},
    },
    {
        'name': '首尾帧首帧图重生成',
        'table': TABLE_FIRST_LAST_VIDEO,
        'status_field': '首帧图操作',
        'trigger_value': '重新生成首帧图',
        'running_value': '重新生成首帧图',
        'failed_value': '不触发',
        'error_field': '首帧图错误信息',
        'script': 'tk_first_last_video.py',
        'args': ['regenerate-first-frame'],
        'timeout': 120,
        'max_concurrency': 2,
        'max_retries': 0,
        'skip_deprecated_records': True,
        'skip_if_field_values': {'记录类型': ['母任务']},
    },
    {
        'name': '首尾帧首帧图生成',
        'table': TABLE_FIRST_LAST_VIDEO,
        'status_field': '首帧图生成状态',
        'trigger_value': '待生成',
        'trigger_values': ['待生成', '生成中'],
        'running_value': '生成中',
        'failed_value': '失败',
        'error_field': '首帧图错误信息',
        'script': 'tk_first_last_video.py',
        'args': ['first-frame'],
        'timeout': 1200,
        'max_concurrency': 1,
        'max_retries': 2,
        'skip_deprecated_records': True,
        'skip_if_field_values': {'记录类型': ['母任务']},
        'claim_clear_values_by_trigger_value': {
            '待生成': {
                '首帧图': [],
                '首帧图file_token': '',
                '首帧图本地路径': '',
                '首帧图任务ID': '',
                '首帧图原始响应JSON': '',
                '首帧图错误信息': '',
                '首帧图生成时间': None,
                '尾帧图': [],
                '尾帧图file_token': '',
                '尾帧图本地路径': '',
                '尾帧图任务ID': '',
                '尾帧图原始响应JSON': '',
                '尾帧图错误信息': '',
                '尾帧图生成时间': None,
                '尾帧图生成状态': '不触发',
                '首尾帧视频': [],
                '首尾帧视频URL': None,
                '视频任务ID': '',
                '视频错误信息': '',
                '视频生成状态': '不触发',
                '错误信息': '',
            },
        },
    },
    {
        'name': '首尾帧首帧审核推进',
        'table': TABLE_FIRST_LAST_VIDEO,
        'status_field': '首帧审核状态',
        'trigger_value': '通过',
        'running_value': '通过',
        'failed_value': '不通过',
        'error_field': '错误信息',
        'script': 'tk_first_last_video.py',
        'args': ['advance-first-review'],
        'timeout': 120,
        'max_concurrency': 2,
        'max_retries': 1,
        'skip_deprecated_records': True,
        'skip_if_field_values': {'记录类型': ['母任务']},
    },
    {
        'name': '首尾帧尾帧图重生成',
        'table': TABLE_FIRST_LAST_VIDEO,
        'status_field': '尾帧图操作',
        'trigger_value': '重新生成尾帧图',
        'running_value': '重新生成尾帧图',
        'failed_value': '不触发',
        'error_field': '尾帧图错误信息',
        'script': 'tk_first_last_video.py',
        'args': ['regenerate-last-frame'],
        'timeout': 120,
        'max_concurrency': 2,
        'max_retries': 0,
        'skip_deprecated_records': True,
        'skip_if_field_values': {'记录类型': ['母任务']},
    },
    {
        'name': '首尾帧尾帧图生成',
        'table': TABLE_FIRST_LAST_VIDEO,
        'status_field': '尾帧图生成状态',
        'trigger_value': '待生成',
        'trigger_values': ['待生成', '生成中'],
        'running_value': '生成中',
        'failed_value': '失败',
        'error_field': '尾帧图错误信息',
        'script': 'tk_first_last_video.py',
        'args': ['last-frame'],
        'timeout': 1200,
        'max_concurrency': 1,
        'max_retries': 2,
        'skip_deprecated_records': True,
        'skip_if_field_values': {'记录类型': ['母任务']},
        'claim_clear_values_by_trigger_value': {
            '待生成': {
                '尾帧图': [],
                '尾帧图file_token': '',
                '尾帧图本地路径': '',
                '尾帧图任务ID': '',
                '尾帧图原始响应JSON': '',
                '尾帧图错误信息': '',
                '尾帧图生成时间': None,
                '首尾帧视频': [],
                '首尾帧视频URL': None,
                '视频任务ID': '',
                '视频错误信息': '',
                '视频生成状态': '不触发',
                '错误信息': '',
            },
        },
    },
    {
        'name': '首尾帧尾帧审核推进',
        'table': TABLE_FIRST_LAST_VIDEO,
        'status_field': '尾帧审核状态',
        'trigger_value': '通过',
        'running_value': '通过',
        'failed_value': '不通过',
        'error_field': '错误信息',
        'script': 'tk_first_last_video.py',
        'args': ['advance-last-review'],
        'timeout': 120,
        'max_concurrency': 2,
        'max_retries': 1,
        'skip_deprecated_records': True,
        'skip_if_field_values': {'记录类型': ['母任务']},
    },
    {
        'name': '首尾帧视频重生成',
        'table': TABLE_FIRST_LAST_VIDEO,
        'status_field': '视频操作',
        'trigger_value': '重新生成首尾帧视频',
        'running_value': '重新生成首尾帧视频',
        'failed_value': '不触发',
        'error_field': '视频错误信息',
        'script': 'tk_first_last_video.py',
        'args': ['regenerate-video'],
        'timeout': 120,
        'max_concurrency': 2,
        'max_retries': 0,
        'skip_deprecated_records': True,
        'skip_if_field_values': {'记录类型': ['母任务']},
    },
    {
        'name': '首尾帧视频生成',
        'table': TABLE_FIRST_LAST_VIDEO,
        'status_field': '视频生成状态',
        'trigger_value': '待生成',
        'trigger_values': ['待生成', '生成中'],
        'running_value': '生成中',
        'failed_value': '失败',
        'error_field': '视频错误信息',
        'script': 'tk_first_last_video.py',
        'args': ['video'],
        'timeout': 2400,
        'max_concurrency': 1,
        'max_retries': 1,
        'skip_deprecated_records': True,
        'skip_if_field_values': {'记录类型': ['母任务']},
        'claim_clear_fields_by_trigger_value': {
            '待生成': [
                '视频任务ID',
                '首尾帧视频file_token',
                '本地视频路径',
                '视频生成原始响应JSON',
                '视频错误信息',
                '错误信息',
            ],
        },
        'claim_clear_values_by_trigger_value': {
            '待生成': {
                '首尾帧视频': [],
                '首尾帧视频URL': None,
            },
        },
    },
    {
        'name': '多角色首尾帧解析',
        'table': TABLE_MULTI_ROLE_FIRST_LAST,
        'status_field': '拆解状态',
        'trigger_value': '待生成',
        'trigger_values': ['待生成', '生成中'],
        'running_value': '生成中',
        'failed_value': '失败',
        'error_field': '错误信息',
        'script': 'tk_multi_role_first_last.py',
        'args': ['parse'],
        'timeout': 900,
        'max_concurrency': 1,
        'max_retries': 1,
        'required_field_values': {'记录类型': ['', '母任务']},
        'claim_clear_values': {
            '记录类型': '母任务',
            '记录状态': '有效',
            '错误信息': '',
        },
        'skip_deprecated_records': True,
    },
    {
        'name': '多角色参考图重生成',
        'table': TABLE_MULTI_ROLE_FIRST_LAST,
        'status_field': '参考图操作',
        'trigger_value': '重新生成参考图',
        'running_value': '重新生成参考图',
        'failed_value': '不触发',
        'error_field': '参考图错误信息',
        'script': 'tk_multi_role_first_last.py',
        'args': ['regenerate-reference-image'],
        'timeout': 120,
        'max_concurrency': 2,
        'max_retries': 0,
        'required_field_values': {'记录类型': ['参考资产']},
        'skip_deprecated_records': True,
    },
    {
        'name': '多角色参考图生成',
        'table': TABLE_MULTI_ROLE_FIRST_LAST,
        'status_field': '参考图生成状态',
        'trigger_value': '待生成',
        'trigger_values': ['待生成', '生成中'],
        'running_value': '生成中',
        'failed_value': '失败',
        'error_field': '参考图错误信息',
        'script': 'tk_multi_role_first_last.py',
        'args': ['reference-image'],
        'timeout': 1200,
        'max_concurrency': 1,
        'max_retries': 2,
        'required_field_values': {'记录类型': ['参考资产']},
        'skip_deprecated_records': True,
        'claim_clear_values_by_trigger_value': {
            '待生成': {
                '参考图': [],
                '参考图file_token': '',
                '参考图本地路径': '',
                '参考图任务ID': '',
                '参考图原始响应JSON': '',
                '参考图错误信息': '',
                '参考图生成时间': None,
                '错误信息': '',
            },
        },
    },
    {
        'name': '多角色参考图审核推进',
        'table': TABLE_MULTI_ROLE_FIRST_LAST,
        'status_field': '参考图审核状态',
        'trigger_value': '通过',
        'running_value': '通过',
        'failed_value': '不通过',
        'error_field': '错误信息',
        'script': 'tk_multi_role_first_last.py',
        'args': ['advance-reference-review'],
        'timeout': 120,
        'max_concurrency': 2,
        'max_retries': 1,
        'required_field_values': {'记录类型': ['参考资产']},
        'skip_deprecated_records': True,
    },
    {
        'name': '多角色关键帧重生成',
        'table': TABLE_MULTI_ROLE_FIRST_LAST,
        'status_field': '关键帧操作',
        'trigger_value': '重新生成关键帧图',
        'running_value': '重新生成关键帧图',
        'failed_value': '不触发',
        'error_field': '关键帧错误信息',
        'script': 'tk_multi_role_first_last.py',
        'args': ['regenerate-keyframe'],
        'timeout': 120,
        'max_concurrency': 2,
        'max_retries': 0,
        'required_field_values': {'记录类型': ['关键帧']},
        'skip_deprecated_records': True,
    },
    {
        'name': '多角色关键帧生成',
        'table': TABLE_MULTI_ROLE_FIRST_LAST,
        'status_field': '关键帧生成状态',
        'trigger_value': '待生成',
        'trigger_values': ['待生成', '生成中'],
        'running_value': '生成中',
        'failed_value': '失败',
        'error_field': '关键帧错误信息',
        'script': 'tk_multi_role_first_last.py',
        'args': ['keyframe-image'],
        'timeout': 1200,
        'max_concurrency': 1,
        'max_retries': 2,
        'required_field_values': {'记录类型': ['关键帧']},
        'skip_deprecated_records': True,
        'claim_clear_values_by_trigger_value': {
            '待生成': {
                '关键帧图': [],
                '关键帧图file_token': '',
                '关键帧图本地路径': '',
                '关键帧任务ID': '',
                '关键帧原始响应JSON': '',
                '关键帧错误信息': '',
                '关键帧生成时间': None,
                '错误信息': '',
            },
        },
    },
    {
        'name': '多角色关键帧审核推进',
        'table': TABLE_MULTI_ROLE_FIRST_LAST,
        'status_field': '关键帧审核状态',
        'trigger_value': '通过',
        'running_value': '通过',
        'failed_value': '不通过',
        'error_field': '错误信息',
        'script': 'tk_multi_role_first_last.py',
        'args': ['advance-keyframe-review'],
        'timeout': 120,
        'max_concurrency': 2,
        'max_retries': 1,
        'required_field_values': {'记录类型': ['关键帧']},
        'skip_deprecated_records': True,
    },
    {
        'name': '多角色视频片段重生成',
        'table': TABLE_MULTI_ROLE_FIRST_LAST,
        'status_field': '视频操作',
        'trigger_value': '重新生成视频片段',
        'running_value': '重新生成视频片段',
        'failed_value': '不触发',
        'error_field': '视频错误信息',
        'script': 'tk_multi_role_first_last.py',
        'args': ['regenerate-video'],
        'timeout': 120,
        'max_concurrency': 2,
        'max_retries': 0,
        'required_field_values': {'记录类型': ['视频片段']},
        'skip_deprecated_records': True,
    },
    {
        'name': '多角色视频片段生成',
        'table': TABLE_MULTI_ROLE_FIRST_LAST,
        'status_field': '视频生成状态',
        'trigger_value': '待生成',
        'trigger_values': ['待生成', '生成中'],
        'running_value': '生成中',
        'failed_value': '失败',
        'error_field': '视频错误信息',
        'script': 'tk_multi_role_first_last.py',
        'args': ['video'],
        'timeout': 2400,
        'max_concurrency': 2,
        'max_retries': 1,
        'required_field_values': {'记录类型': ['视频片段']},
        'skip_deprecated_records': True,
        'resubmit_on_retryable_failure': True,
        'claim_clear_fields_by_trigger_value': {
            '待生成': [
                '视频任务ID',
                '视频片段file_token',
                '视频本地路径',
                '视频原始响应JSON',
                '视频错误信息',
                '错误信息',
            ],
        },
        'claim_clear_values_by_trigger_value': {
            '待生成': {
                '视频片段URL': None,
            },
        },
    },
    {
        'name': '脚本文档解析拆分',
        'table': TABLE_SCRIPT_DOC_TASKS,
        'status_field': '解析状态',
        'trigger_value': '待解析',
        'trigger_values': ['待解析', '解析中'],
        'running_value': '解析中',
        'failed_value': '失败',
        'error_field': '解析错误信息',
        'script': 'tk_script_doc_shots.py',
        'args': ['parse'],
        'timeout': 900,
        'max_concurrency': 1,
        'max_retries': 1,
    },
    {
        'name': '脚本文档参考底图生成',
        'table': TABLE_SCRIPT_DOC_REFERENCE_ASSETS,
        'status_field': '参考图生成状态',
        'trigger_value': '待生成',
        'trigger_values': ['待生成', '生成中'],
        'running_value': '生成中',
        'failed_value': '失败',
        'error_field': '错误信息',
        'script': 'tk_script_doc_shots.py',
        'args': ['reference-image'],
        'timeout': 1200,
        'max_concurrency': 1,
        'max_retries': 3,
        'claim_clear_values_by_trigger_value': {
            '待生成': {
                '参考图': [],
                '参考图file_token': '',
                '参考图本地路径': '',
                '参考图任务ID': '',
                '参考图原始响应JSON': '',
                '错误信息': '',
            },
        },
    },
    {
        'name': '脚本文档口播音频生成',
        'table': TABLE_SCRIPT_DOC_SHOTS,
        'status_field': '口播音频状态',
        'trigger_value': '待生成',
        'trigger_values': ['待生成', '生成中'],
        'running_value': '生成中',
        'failed_value': '失败',
        'error_field': '口播音频错误信息',
        'script': 'tk_shot_voiceover.py',
        'args': ['--table', 'script_doc'],
        'timeout': 300,
        'max_concurrency': 2,
        'max_retries': 2,
    },
    {
        'name': '脚本文档分镜图生成',
        'table': TABLE_SCRIPT_DOC_SHOTS,
        'status_field': '分镜图生成状态',
        'trigger_value': '待生成',
        'trigger_values': ['待生成', '生成中'],
        'running_value': '生成中',
        'failed_value': '失败',
        'error_field': '分镜图错误信息',
        'script': 'tk_shot_storyboard.py',
        'args': ['render', '--table', 'script_doc'],
        'timeout': 1200,
        'max_concurrency': 2,
        'max_retries': 2,
        'claim_clear_values_by_trigger_value': {
            '待生成': {
                '分镜图': [],
                '分镜图file_token': '',
                '分镜图本地路径': '',
                '分镜图任务ID': '',
                '分镜图原始响应JSON': '',
                '分镜图错误信息': '',
                '分镜图生成时间': None,
                '尾帧图': [],
                '尾帧图file_token': '',
                '尾帧图本地路径': '',
                '尾帧图任务ID': '',
                '尾帧图原始响应JSON': '',
                '尾帧图错误信息': '',
                '尾帧图生成时间': None,
                '尾帧图生成状态': '不触发',
                '分镜视频': [],
                '分镜视频URL': None,
                '视频任务ID': '',
                '视频错误信息': '',
                '视频生成时间': None,
                '视频生成状态': '不触发',
                '错误信息': '',
            },
        },
    },
    {
        'name': '脚本文档尾帧图生成',
        'table': TABLE_SCRIPT_DOC_SHOTS,
        'status_field': '尾帧图生成状态',
        'trigger_value': '待生成',
        'trigger_values': ['待生成', '生成中'],
        'running_value': '生成中',
        'failed_value': '失败',
        'error_field': '尾帧图错误信息',
        'script': 'tk_shot_storyboard.py',
        'args': ['last-frame', '--table', 'script_doc'],
        'timeout': 1200,
        'max_concurrency': 2,
        'max_retries': 1,
        'claim_clear_values_by_trigger_value': {
            '待生成': {
                '尾帧图': [],
                '尾帧图file_token': '',
                '尾帧图本地路径': '',
                '尾帧图任务ID': '',
                '尾帧图原始响应JSON': '',
                '尾帧图错误信息': '',
                '尾帧图生成时间': None,
                '分镜视频': [],
                '分镜视频URL': None,
                '视频任务ID': '',
                '视频错误信息': '',
                '视频生成时间': None,
                '视频生成状态': '不触发',
                '错误信息': '',
            },
        },
    },
    {
        'name': '脚本文档分镜视频生成',
        'table': TABLE_SCRIPT_DOC_SHOTS,
        'status_field': '视频生成状态',
        'trigger_value': '待生成',
        'trigger_values': ['待生成', '生成中'],
        'running_value': '生成中',
        'failed_value': '失败',
        'error_field': '视频错误信息',
        'script': 'tk_shot_video.py',
        'args': ['--table', 'script_doc'],
        'timeout': 2400,
        'max_concurrency': 1,
        'max_retries': 1,
        'claim_clear_values_by_trigger_value': {
            '待生成': {
                '分镜视频': [],
                '分镜视频URL': None,
                '视频任务ID': '',
                '视频生成原始响应JSON': '',
                '视频错误信息': '',
                '视频生成时间': None,
                '本地视频路径': '',
                '分镜视频file_token': '',
                '错误信息': '',
            },
        },
    },
    {
        'name': '003新表脚本文档解析拆分',
        'table': TABLE_SCRIPT_DOC_UNIFIED,
        'status_field': '解析状态',
        'trigger_value': '待解析',
        'trigger_values': ['待解析', '解析中'],
        'running_value': '解析中',
        'failed_value': '失败',
        'error_field': '解析错误信息',
        'script': 'tk_script_doc_shots.py',
        'args': ['parse', '--unified'],
        'timeout': 900,
        'max_concurrency': 1,
        'max_retries': 1,
        'keep_when_table_missing': True,
        'required_field_values': {'记录类型': ['文档任务']},
    },
    {
        'name': '003新表脚本文档参考底图生成',
        'table': TABLE_SCRIPT_DOC_UNIFIED,
        'status_field': '参考图生成状态',
        'trigger_value': '待生成',
        'trigger_values': ['待生成', '生成中'],
        'running_value': '生成中',
        'failed_value': '失败',
        'error_field': '错误信息',
        'script': 'tk_script_doc_shots.py',
        'args': ['reference-image', '--unified'],
        'timeout': 1200,
        'max_concurrency': 1,
        'max_retries': 3,
        'keep_when_table_missing': True,
        'required_field_values': {'记录类型': ['参考资产']},
        'claim_clear_values_by_trigger_value': {
            '待生成': {
                '参考图': [],
                '参考图任务ID': '',
                '错误信息': '',
            },
        },
    },
    {
        'name': '003新表脚本文档分镜图生成',
        'table': TABLE_SCRIPT_DOC_UNIFIED,
        'status_field': '分镜图生成状态',
        'trigger_value': '待生成',
        'trigger_values': ['待生成', '生成中'],
        'running_value': '生成中',
        'failed_value': '失败',
        'error_field': '分镜图错误信息',
        'script': 'tk_shot_storyboard.py',
        'args': ['render', '--table', 'script_doc_unified'],
        'timeout': 1200,
        'max_concurrency': 2,
        'max_retries': 2,
        'keep_when_table_missing': True,
        'required_field_values': {'记录类型': ['分镜']},
        'claim_clear_values_by_trigger_value': {
            '待生成': {
                '分镜图': [],
                '分镜图任务ID': '',
                '分镜图错误信息': '',
                '尾帧图': [],
                '尾帧图任务ID': '',
                '尾帧图错误信息': '',
                '尾帧图生成状态': '不触发',
                '分镜视频': [],
                '分镜视频URL': None,
                '视频任务ID': '',
                '视频错误信息': '',
                '视频生成状态': '不触发',
                '错误信息': '',
            },
        },
    },
    {
        'name': '003新表脚本文档尾帧图生成',
        'table': TABLE_SCRIPT_DOC_UNIFIED,
        'status_field': '尾帧图生成状态',
        'trigger_value': '待生成',
        'trigger_values': ['待生成', '生成中'],
        'running_value': '生成中',
        'failed_value': '失败',
        'error_field': '尾帧图错误信息',
        'script': 'tk_shot_storyboard.py',
        'args': ['last-frame', '--table', 'script_doc_unified'],
        'timeout': 1200,
        'max_concurrency': 2,
        'max_retries': 1,
        'keep_when_table_missing': True,
        'required_field_values': {'记录类型': ['分镜']},
        'claim_clear_values_by_trigger_value': {
            '待生成': {
                '尾帧图': [],
                '尾帧图任务ID': '',
                '尾帧图错误信息': '',
                '分镜视频': [],
                '分镜视频URL': None,
                '视频任务ID': '',
                '视频错误信息': '',
                '视频生成状态': '不触发',
                '错误信息': '',
            },
        },
    },
    {
        'name': '003新表脚本文档分镜视频生成',
        'table': TABLE_SCRIPT_DOC_UNIFIED,
        'status_field': '视频生成状态',
        'trigger_value': '待生成',
        'trigger_values': ['待生成', '生成中'],
        'running_value': '生成中',
        'failed_value': '失败',
        'error_field': '视频错误信息',
        'script': 'tk_shot_video.py',
        'args': ['--table', 'script_doc_unified'],
        'timeout': 2400,
        'max_concurrency': 1,
        'max_retries': 1,
        'keep_when_table_missing': True,
        'required_field_values': {'记录类型': ['分镜']},
        'claim_clear_values_by_trigger_value': {
            '待生成': {
                '分镜视频': [],
                '分镜视频URL': None,
                '视频任务ID': '',
                '视频错误信息': '',
                '错误信息': '',
            },
        },
    },
]


RAW_WATCH_LIST = list(WATCH_LIST)
MEDIA_REGENERATION_WATCH_NAMES = [
    '多角色视频片段生成',
    '多图宫格参考图重生成',
    '首尾帧首帧图重生成',
    '首尾帧尾帧图重生成',
    '首尾帧视频重生成',
    '多角色参考图重生成',
    '多角色关键帧重生成',
    '多角色视频片段重生成',
]


def group_watches_by_table(watches=None):
    grouped = {}
    for watch in list(watches if watches is not None else WATCH_LIST):
        table_id = watch.get('table')
        if not table_id:
            continue
        grouped.setdefault(table_id, []).append(watch)
    return grouped


def filter_watches_by_table_key(watches, table_key):
    if not table_key:
        return list(watches)
    return [watch for watch in watches if watch.get('table') == table_key]


WATCH_LIST = [w for w in WATCH_LIST if w.get('table') or w.get('keep_when_table_missing')]
WATCH_LIST = filter_watches_by_table_key(WATCH_LIST, TABLE_KEY)


def ordered_watch_list(watches=None, normal_rotation_offset=0):
    source = list(watches if watches is not None else WATCH_LIST)
    priority = [watch for watch in source if watch.get('name') in MEDIA_REGENERATION_WATCH_NAMES]
    normal = [watch for watch in source if watch.get('name') not in MEDIA_REGENERATION_WATCH_NAMES]
    priority.sort(key=lambda watch: MEDIA_REGENERATION_WATCH_NAMES.index(watch.get('name')))
    if normal and normal_rotation_offset:
        offset = normal_rotation_offset % len(normal)
        normal = normal[offset:] + normal[:offset]
    return priority + normal


running_processes = {}


def load_dead_letters():
    return load_json_file(DEAD_LETTER_FILE)


def save_dead_letters(data):
    save_json_file(DEAD_LETTER_FILE, data)


def load_circuit_breakers():
    return load_json_file(CIRCUIT_BREAKER_FILE)


def save_circuit_breakers(data):
    save_json_file(CIRCUIT_BREAKER_FILE, data)


def parse_concurrency_cell(value):
    if value is None:
        return None
    if isinstance(value, int):
        if value >= 0:
            return value
        log.warning(f"忽略无效并发配置: {value!r}")
        return None
    if isinstance(value, float):
        if value >= 0 and value.is_integer():
            return int(value)
        log.warning(f"忽略无效并发配置: {value!r}")
        return None

    text_value = extract_text(value).strip()
    if not text_value:
        return None
    if not text_value.isdigit():
        log.warning(f"忽略无效并发配置: {text_value!r}")
        return None
    return int(text_value)


def _config_status_is_active(fields):
    return extract_text(fields.get('状态', '')).strip() != '停用'


def get_current_concurrency_policy():
    return _CONCURRENCY_POLICY_CACHE.get('policy') or {'stage_policies': {}, 'table_policies': {}, 'global_max_concurrency': None, 'source_rows': []}


def load_feishu_concurrency_policy(token, *, force=False):
    now = time.time()
    cached = get_current_concurrency_policy()
    loaded_at = float(_CONCURRENCY_POLICY_CACHE.get('loaded_at') or 0)
    if not force and (token in {'t', 'token', 'test-token', 'fake-token'} or str(token).startswith('test_')):
        return cached
    if not force and loaded_at and now - loaded_at < CONCURRENCY_POLICY_TTL_SECONDS:
        return cached

    try:
        records = safe_list_records(token, TABLE_CONFIG)
    except Exception as exc:
        log.warning(f"读取飞书并发配置失败，沿用缓存/本地默认: {exc}")
        return cached

    stage_candidates = {}
    table_candidates = {}
    global_limit = None

    for record in records:
        fields = record.get('fields') or {}
        if not _config_status_is_active(fields):
            continue
        config_type = extract_text(fields.get('配置类型', '')).strip()
        stage = extract_text(fields.get('环节', '')).strip()
        if config_type in {'运行环节', '任务默认'}:
            limit = parse_concurrency_cell(fields.get('环节最大并发'))
            matched_stage = extract_text(fields.get('调度环节名', '')).strip() or stage
            if limit is None or not matched_stage:
                continue
            source_row = {
                'record_id': record.get('record_id') or record.get('id'),
                '配置类型': config_type,
                '环节': stage,
                '调度环节名': extract_text(fields.get('调度环节名', '')).strip(),
                'matched_stage': matched_stage,
                '环节最大并发': limit,
            }
            stage_candidates.setdefault(matched_stage, []).append((fields, limit, source_row))
        elif config_type == '路由开关' and stage == CONCURRENCY_CONTROL_STAGE:
            parsed_global = parse_concurrency_cell(fields.get('全局最大并发'))
            if parsed_global is not None:
                global_limit = parsed_global
        elif config_type == '路由开关' and stage == TABLE_CONCURRENCY_CONTROL_STAGE:
            table_limit = parse_concurrency_cell(fields.get('表格最大并发'))
            app_table = extract_text(fields.get('应用表格', '')).strip()
            table_id = DISPATCHER_TABLE_ID_BY_APP_TABLE.get(app_table)
            if table_limit is None or not table_id:
                continue
            source_row = {
                'record_id': record.get('record_id') or record.get('id'),
                '配置类型': config_type,
                '环节': stage,
                '应用表格': app_table,
                'matched_table': table_id,
                '表格最大并发': table_limit,
            }
            table_candidates.setdefault(table_id, []).append((fields, table_limit, source_row))

    stage_policies = {}
    source_rows = []
    for stage, candidates in stage_candidates.items():
        online = [
            item for item in candidates
            if extract_text(item[0].get('生效来源', '')).strip() in ('', '线上配置')
        ]
        selected = online or candidates
        task_default_selected = [
            item for item in selected
            if (item[2] or {}).get('配置类型') == '任务默认'
        ]
        if task_default_selected:
            selected = task_default_selected
        if len(selected) != 1:
            log.warning(f"忽略重复并发配置: stage={stage} count={len(selected)}")
            continue
        stage_policies[stage] = {'max_concurrency': selected[0][1]}
        source_rows.append(selected[0][2])

    table_policies = {}
    for table_id, candidates in table_candidates.items():
        online = [
            item for item in candidates
            if extract_text(item[0].get('生效来源', '')).strip() in ('', '线上配置')
        ]
        selected = online or candidates
        if len(selected) != 1:
            log.warning(f"忽略重复表格并发配置: table={table_id} count={len(selected)}")
            continue
        table_policies[table_id] = {'max_concurrency': selected[0][1]}
        source_rows.append(selected[0][2])

    policy = {
        'stage_policies': stage_policies,
        'table_policies': table_policies,
        'global_max_concurrency': global_limit,
        'source_rows': source_rows,
    }
    _CONCURRENCY_POLICY_CACHE['loaded_at'] = now
    _CONCURRENCY_POLICY_CACHE['policy'] = policy
    return policy


def concurrency_policy_diagnostics(policy, watches=None):
    watch_list = watches if watches is not None else WATCH_LIST
    watch_names = {
        extract_text((watch or {}).get('name', '')).strip()
        for watch in watch_list
        if extract_text((watch or {}).get('name', '')).strip()
    }
    source_rows = list(policy.get('source_rows') or [])
    unmatched_rows = [
        row for row in source_rows
        if extract_text(row.get('matched_stage', '')).strip() not in watch_names
    ]
    return {
        'matched_count': len(source_rows) - len(unmatched_rows),
        'unmatched_count': len(unmatched_rows),
        'unmatched_rows': unmatched_rows,
    }


def current_global_max_concurrency(policy):
    configured = policy.get('global_max_concurrency')
    if configured is None:
        return GLOBAL_MAX_CONCURRENCY
    return int(configured)


def table_max_concurrency_for_watch(watch):
    if not TABLE_KEY:
        return None
    table_id = watch.get('table')
    feishu_table_policy = (get_current_concurrency_policy().get('table_policies') or {}).get(table_id)
    if feishu_table_policy and 'max_concurrency' in feishu_table_policy:
        return int(feishu_table_policy['max_concurrency'])
    direct = parse_concurrency_cell(watch.get('table_max_concurrency'))
    if direct is not None:
        return direct

    configured = None
    if isinstance(TABLE_MAX_CONCURRENCY_CFG, dict):
        configured = TABLE_MAX_CONCURRENCY_CFG.get(table_id)
        if isinstance(configured, dict):
            configured = configured.get('max_concurrency')
    parsed = parse_concurrency_cell(configured)
    if parsed is not None:
        return parsed
    return DEFAULT_TABLE_MAX_CONCURRENCY


def apply_stage_policy(watch):
    merged = dict(watch)
    args_key = ' '.join(watch.get('args') or [])
    stage_keys = [watch.get('script')]
    if args_key:
        stage_keys.append(f"{watch.get('script')} {args_key}")
    stage_keys.append(watch.get('name'))
    for stage_key in stage_keys:
        cfg = STAGE_CFG.get(stage_key) if stage_key else None
        if not cfg:
            continue
        for key in ('max_concurrency', 'max_retries', 'timeout'):
            if key in cfg:
                merged[key] = cfg[key]
    feishu_stage_policy = (get_current_concurrency_policy().get('stage_policies') or {}).get(watch.get('name'))
    if feishu_stage_policy:
        for key in ('max_concurrency',):
            if key in feishu_stage_policy:
                merged[key] = feishu_stage_policy[key]
    return merged


def apply_local_stage_config(watch):
    merged = dict(watch)
    args_key = ' '.join(watch.get('args') or [])
    stage_keys = [watch.get('script')]
    if args_key:
        stage_keys.append(f"{watch.get('script')} {args_key}")
    stage_keys.append(watch.get('name'))
    for stage_key in stage_keys:
        cfg = STAGE_CFG.get(stage_key) if stage_key else None
        if not cfg:
            continue
        for key in ('max_concurrency', 'max_retries', 'timeout'):
            if key in cfg:
                merged[key] = cfg[key]
    return merged


def effective_concurrency_report(policy, watches=None):
    rows = []
    stage_policies = (policy or {}).get('stage_policies') or {}
    for watch in list(watches if watches is not None else WATCH_LIST):
        local_default = watch.get('max_concurrency', 1)
        applied = apply_local_stage_config(watch)
        policy_source = 'local'
        feishu_stage_policy = stage_policies.get(watch.get('name'))
        if feishu_stage_policy and 'max_concurrency' in feishu_stage_policy:
            applied['max_concurrency'] = feishu_stage_policy['max_concurrency']
            policy_source = 'feishu'
        rows.append({
            'watch_name': watch.get('name'),
            'local_default': local_default,
            'applied_max_concurrency': applied.get('max_concurrency', 1),
            'policy_source': policy_source,
        })
    return rows


def normalize_dispatcher_error_payload(payload):
    message = extract_text(payload.get('message'))[:500]
    lower = message.lower()
    retryable_markers = (
        'official_generation_error',
        '请重新提交',
        'no active tokens available in the pool',
    )
    if any(marker in lower or marker in message for marker in retryable_markers):
        payload = dict(payload)
        payload['status'] = 'failed_retryable'
        payload['error_code'] = 'UPSTREAM_RETRYABLE'
        payload['retryable'] = True
        payload['message'] = message
    return payload


def parse_subprocess_error_payload(stdout_text, stderr_text, stage):
    combined_parts = [x for x in [stdout_text or '', stderr_text or ''] if x]
    combined = '\n'.join(combined_parts).strip()

    lines = []
    for block in combined_parts:
        lines.extend(block.splitlines())

    for line in reversed(lines):
        text = line.strip()
        if not (text.startswith('{') and text.endswith('}')):
            continue
        try:
            payload = json.loads(text)
        except Exception:
            continue
        if isinstance(payload, dict) and isinstance(payload.get('error'), dict):
            payload = payload['error']
        if not isinstance(payload, dict) or 'message' not in payload:
            continue
        return normalize_dispatcher_error_payload({
            'stage': payload.get('stage') or stage,
            'status': payload.get('status') or 'failed_terminal',
            'error_code': payload.get('error_code') or 'RUNTIME_BUG',
            'retryable': bool(payload.get('retryable')),
            'message': extract_text(payload.get('message'))[:500],
        })

    structured_line = None
    for line in reversed(lines):
        text = line.strip()
        if text.startswith('ERROR_CODE='):
            structured_line = text
            break

    if structured_line:
        code = 'RUNTIME_BUG'
        retryable = False
        message = structured_line

        try:
            if ' MESSAGE=' in structured_line:
                prefix, message = structured_line.split(' MESSAGE=', 1)
            else:
                prefix = structured_line
            for token in prefix.split():
                if token.startswith('ERROR_CODE='):
                    code = token.split('=', 1)[1].strip() or code
                elif token.startswith('RETRYABLE='):
                    retryable = token.split('=', 1)[1].strip().lower() == 'true'
        except Exception:
            pass

        return normalize_dispatcher_error_payload({
            'stage': stage,
            'status': 'failed_retryable' if retryable else 'failed_terminal',
            'error_code': code,
            'retryable': retryable,
            'message': extract_text(message)[:500],
        })

    err_text = combined[-1000:] if combined else 'subprocess_nonzero_exit'
    return normalize_dispatcher_error_payload(build_error_payload(err_text, stage=stage))




def register_dead_letter(watch, record_id, reason, payload=None):
    data = load_dead_letters()
    data[make_task_key(watch, record_id)] = {
        'watch': watch['name'],
        'record_id': record_id,
        'script': watch['script'],
        'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'reason': str(reason)[:500],
        'payload': payload or {},
    }
    save_dead_letters(data)


def circuit_breaker_key(watch):
    return f"{watch['script']}::{watch['name']}"


def record_circuit_failure(watch):
    data = load_circuit_breakers()
    key = circuit_breaker_key(watch)
    now = int(time.time())
    entry = data.get(key, {'failures': [], 'open_until': 0})
    window_seconds = int(watch.get('circuit_window_seconds') or CIRCUIT_CFG.get('window_seconds', 900) or 900)
    threshold = int(watch.get('circuit_threshold') or CIRCUIT_CFG.get('threshold', 3) or 3)
    cooldown_seconds = int(watch.get('circuit_cooldown_seconds') or CIRCUIT_CFG.get('cooldown_seconds', 600) or 600)
    failures = [ts for ts in entry.get('failures', []) if now - ts <= window_seconds]
    failures.append(now)
    entry['failures'] = failures
    if len(failures) >= threshold:
        entry['open_until'] = now + cooldown_seconds
        log.warning(f"[{watch['name']}] 熔断开启 {cooldown_seconds}s, failures={len(failures)}")
    data[key] = entry
    save_circuit_breakers(data)


def clear_circuit_failure(watch):
    data = load_circuit_breakers()
    key = circuit_breaker_key(watch)
    if key in data:
        data[key]['failures'] = []
        data[key]['open_until'] = 0
        save_circuit_breakers(data)


def is_circuit_open(watch):
    data = load_circuit_breakers()
    entry = data.get(circuit_breaker_key(watch), {})
    open_until = int(entry.get('open_until', 0) or 0)
    return open_until > int(time.time())
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


def load_table_scan_state():
    return load_json_file(TABLE_SCAN_STATE_FILE)


def save_table_scan_state(data):
    save_json_file(TABLE_SCAN_STATE_FILE, data)


def load_record_state_cache():
    return load_json_file(RECORD_STATE_CACHE_FILE)


def save_record_state_cache(data):
    save_json_file(RECORD_STATE_CACHE_FILE, data)


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
    args = watch.get('args') or []
    action_key = ' '.join(str(arg) for arg in args)
    script = watch.get('script') or watch.get('name') or 'unknown'
    table = watch.get('table') or 'no-table'
    status_field = watch.get('status_field') or 'no-status'
    return f"{table}::{status_field}::{script}::{action_key}::{record_id}"


def format_timeout_reason(watch, record_id, elapsed):
    timeout = int(watch.get('timeout', 900) or 900)
    return (
        f"{watch.get('name', '任务')} worker timeout: record_id={record_id}, "
        f"elapsed={int(elapsed)}s, timeout={timeout}s. 上游任务可能仍在生成或轮询未结束。"
    )


def legacy_task_key(watch, record_id):
    script = watch.get('script') or watch.get('name') or 'unknown'
    return f"{script}::{record_id}"


def pop_legacy_running_state(running_state, watch, record_id):
    old_key = legacy_task_key(watch, record_id)
    if old_key not in running_state:
        return False
    task_info = running_state.get(old_key) or {}
    if has_live_process_for_task_key(old_key, task_info):
        return True
    running_state.pop(old_key, None)
    save_running_tasks(running_state)
    return False


def count_running_by_watch(watch_name):
    count = 0
    for proc in running_processes.values():
        process = proc.get('process')
        if process is not None and process.poll() is not None:
            continue
        if proc['watch']['name'] == watch_name:
            count += 1
    return count


def count_active_running_tasks():
    count = 0
    for proc in running_processes.values():
        process = proc.get('process')
        if process is not None and process.poll() is not None:
            continue
        count += 1
    return count


def count_running_by_table(table_id):
    count = 0
    for proc in running_processes.values():
        process = proc.get('process')
        if process is not None and process.poll() is not None:
            continue
        if proc.get('watch', {}).get('table') == table_id:
            count += 1
    return count


def running_state_entry_matches_watch(task_info, watch):
    if task_info.get('script') != watch.get('script'):
        return False
    if task_info.get('table') and task_info.get('table') != watch.get('table'):
        return False
    if task_info.get('status_field') and task_info.get('status_field') != watch.get('status_field'):
        return False
    stored_args = [str(arg) for arg in (task_info.get('args') or [])]
    watch_args = [str(arg) for arg in (watch.get('args') or [])]
    trigger_arg_sets = [
        [str(arg) for arg in (args or [])]
        for args in (watch.get('args_by_trigger_value') or {}).values()
    ]
    if stored_args:
        if trigger_arg_sets:
            return stored_args in trigger_arg_sets
        return stored_args == watch_args
    return False


def count_live_persisted_by_watch(watch, running_state):
    count = 0
    for task_key, task_info in (running_state or {}).items():
        if task_key in running_processes:
            continue
        if not running_state_entry_matches_watch(task_info or {}, watch):
            continue
        if has_live_process_for_task_key(task_key, task_info or {}):
            count += 1
    return count


def running_state_entry_matches_table(task_info, table_id):
    if not table_id:
        return False
    stored_table = task_info.get('table')
    if stored_table:
        return stored_table == table_id
    return False


def count_live_persisted_by_table(table_id, running_state):
    count = 0
    for task_key, task_info in (running_state or {}).items():
        if task_key in running_processes:
            continue
        if not running_state_entry_matches_table(task_info or {}, table_id):
            continue
        if has_live_process_for_task_key(task_key, task_info or {}):
            count += 1
    return count


def has_live_process_for_task_key(task_key, task_info):
    key_parts = task_key.split('::')
    script_from_key = key_parts[2] if len(key_parts) >= 5 else key_parts[0]
    script = task_info.get('script') or script_from_key
    record_id = task_info.get('record_id') or (task_key.rsplit('::', 1)[1] if '::' in task_key else '')
    if not script or not record_id:
        return False
    try:
        result = subprocess.run(
            ['ps', 'axo', 'pid=,command='],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return False
    if result.returncode != 0:
        return False
    current_pid = str(os.getpid())
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        pid, _, command = stripped.partition(' ')
        if pid == current_pid:
            continue
        if script in command and record_id in command:
            return True
    return False


def prune_stale_running_state():
    running_state = load_running_tasks()
    stale_keys = [
        task_key for task_key, task_info in running_state.items()
        if task_key not in running_processes and not has_live_process_for_task_key(task_key, task_info)
    ]
    if not stale_keys:
        return 0
    for task_key in stale_keys:
        running_state.pop(task_key, None)
    save_running_tasks(running_state)
    return len(stale_keys)


def get_retry_count(task_key):
    state = load_retry_state()
    return int(state.get(task_key, {}).get('retry_count', 0) or 0)


def set_retry_count(task_key, retry_count, watch=None, record_id=None):
    state = load_retry_state()
    state[task_key] = {
        'retry_count': retry_count,
        'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'script': watch['script'] if watch else state.get(task_key, {}).get('script'),
        'args': watch.get('args', []) if watch else state.get(task_key, {}).get('args', []),
        'record_id': record_id or state.get(task_key, {}).get('record_id'),
    }
    save_retry_state(state)


def clear_retry_count(task_key):
    state = load_retry_state()
    if task_key in state:
        state.pop(task_key, None)
        save_retry_state(state)


def clear_dead_letter(task_key):
    data = load_dead_letters()
    if task_key in data:
        data.pop(task_key, None)
        save_dead_letters(data)


SYSTEM_REQUEUE_ERROR_PREFIXES = (
    '自动重试中[',
    'dispatcher兜底失败回写[',
    '自动重新提交新任务[',
)

RETRYABLE_FAILED_ERROR_CODES = {
    'UPSTREAM_NETWORK',
    'UPSTREAM_RATE_LIMIT',
    'UPSTREAM_RETRYABLE',
    'FEISHU_API_TRANSIENT',
}
DEFAULT_RETRYABLE_FAILED_VALUES = {'失败'}


def retryable_error_code_from_text(error_text):
    text = extract_text(error_text).strip()
    for prefix in SYSTEM_REQUEUE_ERROR_PREFIXES:
        if not text.startswith(prefix):
            continue
        remainder = text[len(prefix):]
        code, _, _ = remainder.partition(']')
        code = code.strip()
        if code in RETRYABLE_FAILED_ERROR_CODES:
            return code
    return ''


def retryable_failed_statuses_for_watch(watch):
    values = watch.get('retryable_failed_values')
    if values is None:
        failed_value = watch.get('failed_value')
        values = [failed_value] if failed_value in DEFAULT_RETRYABLE_FAILED_VALUES else []
    return set(_unique_preserve_order(values))


def maybe_requeue_failed_candidate(token, watch, record_id, task_key, fields, status):
    if status not in retryable_failed_statuses_for_watch(watch):
        return False
    error_field = watch.get('error_field')
    error_code = retryable_error_code_from_text((fields or {}).get(error_field, '') if error_field else '')
    if not error_code:
        return False
    retry_count = get_retry_count(task_key)
    new_retry = retry_count + 1
    max_retries = int(watch.get('max_retries', 1) or 0)
    if new_retry > max_retries:
        return False
    fallback_trigger = (watch.get('trigger_values') or [watch.get('trigger_value')])[0]
    update_payload = {watch['status_field']: fallback_trigger}
    if error_field:
        update_payload[error_field] = (
            f"自动重试中[{error_code}] 第 {new_retry} 次失败队列重新排队，等待 dispatcher 重新处理。"
        )[:1000]
    safe_update_record(token, watch['table'], record_id, update_payload)
    set_retry_count(task_key, new_retry, watch=watch, record_id=record_id)
    clear_dead_letter(task_key)
    update_record_state_cache(watch, record_id, fallback_trigger)
    bump_metric('retried', watch['name'])
    log.warning(f"[{watch['name']}] 失败可重试任务已重新排队: {record_id} retry={new_retry}/{max_retries} error_code={error_code}")
    return True


def clear_retry_count_for_manual_requeue(watch, task_key, latest_status, latest_fields):
    if latest_status != watch.get('trigger_value'):
        return False
    error_field = watch.get('error_field')
    error_text = extract_text((latest_fields or {}).get(error_field, '')).strip() if error_field else ''
    if error_text.startswith(SYSTEM_REQUEUE_ERROR_PREFIXES):
        return False
    clear_retry_count(task_key)
    clear_dead_letter(task_key)
    return True


def maybe_retry_task(token, watch, record_id, task_key, reason, error_payload=None):
    error_payload = error_payload or build_error_payload(reason, stage=watch.get('script', 'unknown'))
    if not error_payload.get('retryable'):
        log.error(f"[{watch['name']}] 错误不可重试，直接终止: {record_id} error_code={error_payload.get('error_code')} reason={error_payload.get('message')}")
        return False

    valid_retry_statuses = set(watch.get('trigger_values') or [watch['trigger_value']])
    valid_retry_statuses.add(watch.get('running_value'))
    valid_retry_statuses.add(watch.get('failed_value', '失败'))
    try:
        latest = safe_get_record(token, watch['table'], record_id)
        latest_status = extract_text(latest.get(watch['status_field'], '')).strip()
        if latest_status not in valid_retry_statuses:
            log.info(f"[{watch['name']}] 检测到用户手动停止重试: {record_id} current_status={latest_status or '<empty>'}")
            return True
    except Exception as e:
        log.warning(f"[{watch['name']}] 重试前读取最新状态失败，继续按可重试错误回退: {record_id} error={e}")

    if watch.get('resubmit_on_retryable_failure'):
        try:
            error_message = error_payload.get('message') or str(reason)
            update_payload = {
                watch['status_field']: watch.get('trigger_value', '待生成'),
                '视频操作': '不触发',
                '视频任务ID': '',
                '视频本地路径': '',
                '视频原始响应JSON': '',
                '视频错误信息': f"自动重新提交新任务[{error_payload.get('error_code', 'UNKNOWN')}]: 已丢弃旧任务，等待 dispatcher 提交新任务。{error_message}"[:1000],
                '错误信息': '',
            }
            if watch.get('status_field') == '视频生成状态':
                current_version = 1
                try:
                    current_version = int(float(extract_text(latest.get('视频版本')).strip() or latest.get('视频版本') or 1))
                except Exception:
                    current_version = 1
                update_payload['视频版本'] = current_version + 1
                update_payload['视频片段URL'] = None
                update_payload['视频片段file_token'] = ''
            safe_update_record(token, watch['table'], record_id, update_payload)
            clear_retry_count(task_key)
            clear_dead_letter(task_key)
            bump_metric('retried', watch['name'])
            log.warning(f"[{watch['name']}] 可重试错误已清旧任务并重新排队: {record_id} error_code={error_payload.get('error_code')} reason={error_payload.get('message')}")
            return True
        except Exception as e:
            log.error(f"[{watch['name']}] 清旧任务并重新排队失败: {record_id} error={e}")
            return False

    retry_count = get_retry_count(task_key)
    new_retry = retry_count + 1
    set_retry_count(task_key, new_retry, watch=watch, record_id=record_id)
    max_retries = int(watch.get('max_retries', 1) or 0)
    if new_retry > max_retries:
        log.error(
            f"[{watch['name']}] 可重试错误已超过重试上限: {record_id} "
            f"retries={retry_count}/{max_retries} error_code={error_payload.get('error_code')} "
            f"reason={error_payload.get('message')}"
        )
        return False
    try:
        fallback_trigger = (watch.get('trigger_values') or [watch['trigger_value']])[0]
        error_message = error_payload.get('message') or str(reason)
        update_payload = {watch['status_field']: fallback_trigger}
        error_field = watch.get('error_field')
        if error_field and error_message:
            update_payload[error_field] = (
                f"自动重试中[{error_payload.get('error_code', 'UNKNOWN')}] "
                f"第 {new_retry} 次失败，将继续重试：{error_message}"
            )[:1000]
        safe_update_record(token, watch['table'], record_id, update_payload)
        bump_metric('retried', watch['name'])
        log.warning(f"[{watch['name']}] 可重试错误已回退继续重试: {record_id} retry={new_retry} error_code={error_payload.get('error_code')} reason={error_payload.get('message')}")
        return True
    except Exception as e:
        log.error(f"[{watch['name']}] 回退重试状态失败: {record_id} error={e}")
        return False


def mark_task_failed(token, watch, record_id, task_key, reason='failed', timeout=False, error_payload=None):
    error_payload = error_payload or build_error_payload(reason, stage=watch.get('script', 'unknown'))
    append_last_error(watch['name'], record_id, f"{error_payload.get('error_code')}: {error_payload.get('message')}")
    retried = maybe_retry_task(token, watch, record_id, task_key, reason, error_payload=error_payload)
    if retried:
        return
    failed_value = watch.get('failed_value', '失败')
    payload = {
        watch['status_field']: failed_value
    }
    error_field = watch.get('error_field')
    error_message = error_payload.get('message') if error_payload else str(reason)
    if error_field and error_message:
        payload[error_field] = f"dispatcher兜底失败回写[{error_payload.get('error_code', 'UNKNOWN')}]: {error_message}"[:1000]
    try:
        safe_update_record(token, watch['table'], record_id, payload)
    except Exception as e:
        log.error(f"[{watch['name']}] 标记失败写回失败: {record_id} payload={payload} error={e}")
    register_dead_letter(watch, record_id, reason, payload=error_payload)
    bump_metric('failed', watch['name'])
    if timeout:
        bump_metric('timeouts', watch['name'])


def cleanup_finished_processes(token):
    pruned = prune_stale_running_state()
    if pruned:
        log.warning(f"已清理 stale running state: {pruned}")
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
            mark_task_failed(token, watch, record_id, task_key, reason=format_timeout_reason(watch, record_id, elapsed), timeout=True)
            finished.append(task_key)
            continue

        if process.poll() is not None:
            try:
                stdout, stderr = process.communicate(timeout=1)
            except Exception:
                stdout, stderr = '', ''

            if process.returncode == 0:
                log.info(f"[{watch['name']}] ✅ 完成: {record_id}")
                refresh_record_state_cache_from_record(token, watch, record_id)
                clear_retry_count(task_key)
                clear_dead_letter(task_key)
                clear_circuit_failure(watch)
                bump_metric('success', watch['name'])
            else:
                error_payload = parse_subprocess_error_payload(stdout, stderr, watch['script'])
                err_text = error_payload.get('message') or 'subprocess_nonzero_exit'
                log.error(f"[{watch['name']}] ❌ 失败: {record_id} error_code={error_payload['error_code']} retryable={error_payload['retryable']} stderr={error_payload['message']}")
                mark_task_failed(token, watch, record_id, task_key, reason=err_text, error_payload=error_payload)


            if stdout and stdout.strip():
                log.info(f"[{watch['name']}] stdout: {stdout.strip()[-300:]}")
            finished.append(task_key)

    if finished:
        running_state = load_running_tasks()
        for task_key in finished:
            running_processes.pop(task_key, None)
            running_state.pop(task_key, None)
        save_running_tasks(running_state)


def should_skip_claim_by_cache(watch, record_id, observed_status):
    cache = load_record_state_cache()
    key = f"{watch['table']}::{record_id}::{watch['status_field']}"
    item = cache.get(key)
    if not item:
        return False
    now = int(time.time())
    seen_at = int(item.get('seen_at', 0) or 0)
    if now - seen_at > RECORD_STATE_CACHE_TTL_SECONDS:
        return False
    if item.get('status') == observed_status == watch.get('running_value'):
        return True
    return False


def update_record_state_cache(watch, record_id, status):
    cache = load_record_state_cache()
    key = f"{watch['table']}::{record_id}::{watch['status_field']}"
    cache[key] = {
        'status': status,
        'seen_at': int(time.time()),
    }
    # 简单清理过期项
    now = int(time.time())
    cleaned = {
        k: v for k, v in cache.items()
        if now - int(v.get('seen_at', 0) or 0) <= RECORD_STATE_CACHE_TTL_SECONDS
    }
    save_record_state_cache(cleaned)


def refresh_record_state_cache_from_record(token, watch, record_id):
    try:
        latest = safe_get_record(token, watch['table'], record_id)
        latest_status = extract_text(latest.get(watch['status_field'], '')).strip()
        update_record_state_cache(watch, record_id, latest_status)
    except Exception as e:
        log.warning(f"[{watch['name']}] 完成后刷新状态缓存失败 {record_id}: {e}")


def get_table_field_kinds(token, table_id):
    cache_key = table_id
    if cache_key in _TABLE_FIELD_KINDS_CACHE:
        return _TABLE_FIELD_KINDS_CACHE[cache_key]
    kinds = {}
    page_token = None
    while True:
        url = f'https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/fields?page_size=100'
        if page_token:
            url += f'&page_token={page_token}'
        data = safe_request('get', url, headers=feishu_headers(token), timeout=30, max_attempts=3, acceptable_codes=(0,))
        for item in data.get('data', {}).get('items', []):
            name = item.get('field_name') or item.get('name')
            if name:
                kinds[name] = item.get('type') or item.get('ui_type') or item.get('field_type')
        if not data.get('data', {}).get('has_more'):
            break
        page_token = data.get('data', {}).get('page_token')
    _TABLE_FIELD_KINDS_CACHE[cache_key] = kinds
    return kinds


def sanitize_claim_fields_for_update(token, table_id, claim_fields):
    if not any(value == [] for value in claim_fields.values()):
        return claim_fields
    try:
        field_kinds = get_table_field_kinds(token, table_id)
    except Exception as e:
        log.warning(f"读取字段类型失败，按已知附件字段保护 claim payload: table={table_id} error={e}")
        field_kinds = {}
    sanitized = {}
    for field_name, value in claim_fields.items():
        kind = field_kinds.get(field_name)
        is_attachment_field = kind in ATTACHMENT_FIELD_TYPE_IDS or field_name in KNOWN_ATTACHMENT_FIELD_NAMES
        if value == [] and is_attachment_field:
            log.info(f"claim payload 跳过附件字段清空: table={table_id} field={field_name}")
            continue
        sanitized[field_name] = value
    return sanitized


def apply_claim_clear_fields(claim_fields, watch, trigger_value=None):
    for field_name in watch.get('claim_clear_fields') or []:
        claim_fields[field_name] = ''
    for field_name in (watch.get('claim_clear_fields_by_trigger_value') or {}).get(trigger_value, []):
        claim_fields[field_name] = ''
    for field_name, value in (watch.get('claim_clear_values') or {}).items():
        claim_fields[field_name] = value
    for field_name, value in (watch.get('claim_clear_values_by_trigger_value') or {}).get(trigger_value, {}).items():
        claim_fields[field_name] = value
    return claim_fields


def record_matches_watch_filters(watch, fields):
    if watch.get('skip_deprecated_records'):
        if extract_text(fields.get('记录状态', '')).strip() == '已废弃':
            return False

    for field_name, blocked_values in (watch.get('skip_if_field_values') or {}).items():
        value = extract_text(fields.get(field_name, '')).strip()
        if value in blocked_values:
            return False

    for field_name, required_values in (watch.get('required_field_values') or {}).items():
        value = extract_text(fields.get(field_name, '')).strip()
        if value not in required_values:
            return False

    return True


def try_claim_task(token, watch, record_id):
    try:
        latest = safe_get_record(token, watch['table'], record_id)
        if not record_matches_watch_filters(watch, latest):
            return False
        latest_status = extract_text(latest.get(watch['status_field'], ''))
        valid_trigger_values = watch.get('trigger_values') or [watch['trigger_value']]
        if latest_status not in valid_trigger_values:
            update_record_state_cache(watch, record_id, latest_status)
            return False
        clear_retry_count_for_manual_requeue(watch, make_task_key(watch, record_id), latest_status, latest)
        claim_fields = {watch['status_field']: watch['running_value']}
        apply_claim_clear_fields(claim_fields, watch, latest_status)
        claim_fields = sanitize_claim_fields_for_update(token, watch['table'], claim_fields)
        safe_update_record(token, watch['table'], record_id, claim_fields)
        update_record_state_cache(watch, record_id, watch['running_value'])
        return True
    except Exception as e:
        log.warning(f"[{watch['name']}] claim任务失败 {record_id}: {e}")
        return False


def get_table_records_cached(token, table_id, force=False):
    state = load_table_scan_state()
    now = int(time.time())
    entry = state.get(table_id, {})
    last_scan = int(entry.get('last_scan_at', 0) or 0)
    cache_file = os.path.join(SCRIPTS_DIR, f'.table_cache_{table_id}.{RUNTIME_SCOPE}.json')

    if not force and os.path.exists(cache_file) and now - last_scan < TABLE_MIN_INTERVAL_SECONDS:
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass

    records = safe_list_records(token, table_id)
    try:
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(records, f, ensure_ascii=False)
    except Exception:
        pass
    state[table_id] = {'last_scan_at': now}
    save_table_scan_state(state)
    return records


def _unique_preserve_order(values):
    result = []
    seen = set()
    for value in values:
        text = extract_text(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def build_watch_candidate_filter(watch):
    status_field = watch.get('status_field')
    statuses = _unique_preserve_order(
        list(watch.get('trigger_values') or [watch.get('trigger_value')])
        + list(retryable_failed_statuses_for_watch(watch))
    )
    conditions = []
    if status_field and statuses:
        conditions.append([status_field, 'intersects', statuses])
    for field_name, required_values in (watch.get('required_field_values') or {}).items():
        raw_values = list(required_values or [])
        if any(extract_text(value).strip() == '' for value in raw_values):
            continue
        values = _unique_preserve_order(required_values)
        if values:
            conditions.append([field_name, 'intersects', values])
    return {'logic': 'and', 'conditions': conditions}


def base_v3_filter_records(token, table_id, filter_payload, *, limit=100):
    records = []
    offset = 0
    encoded_filter = urllib.parse.quote(json.dumps(filter_payload, ensure_ascii=False))
    while True:
        url = (
            f'https://open.feishu.cn/open-apis/base/v3/bases/{APP_TOKEN}/tables/{table_id}/records'
            f'?filter={encoded_filter}&limit={limit}&offset={offset}'
        )
        data = safe_request(
            'get',
            url,
            headers=feishu_headers(token),
            timeout=30,
            max_attempts=3,
            acceptable_codes=(0,),
        )
        payload = data.get('data') or {}
        field_names = payload.get('fields') or []
        rows = payload.get('data') or []
        record_ids = payload.get('record_id_list') or []
        for index, row in enumerate(rows):
            record_id = record_ids[index] if index < len(record_ids) else ''
            fields = {
                field_name: row[field_index] if field_index < len(row) else None
                for field_index, field_name in enumerate(field_names)
                if field_name
            }
            records.append({'record_id': record_id, 'fields': fields})
        if not payload.get('has_more') or not rows:
            break
        offset += len(rows)
    return records


def get_watch_candidate_records_cached(token, watch, force=False):
    table_id = watch['table']
    filter_payload = build_watch_candidate_filter(watch)
    cache_key = json.dumps({
        'table': table_id,
        'filter': filter_payload,
    }, ensure_ascii=False, sort_keys=True)
    now = int(time.time())
    cached = _WATCH_CANDIDATE_CACHE.get(cache_key)
    if not force and cached and now - int(cached.get('loaded_at', 0) or 0) < TABLE_MIN_INTERVAL_SECONDS:
        return cached.get('records') or []

    try:
        records = base_v3_filter_records(token, table_id, filter_payload)
    except Exception as exc:
        log.warning(f"[{watch['name']}] 精准查询候选失败，回退全表缓存扫描: {exc}")
        records = get_table_records_cached(token, table_id, force=force)
    _WATCH_CANDIDATE_CACHE[cache_key] = {'loaded_at': now, 'records': records}
    return records


def check_and_run(token, watch):
    policy = load_feishu_concurrency_policy(token)
    watch = apply_stage_policy(watch)
    cleanup_finished_processes(token)
    running_state = load_running_tasks()
    current_running = count_running_by_watch(watch['name']) + count_live_persisted_by_watch(watch, running_state)
    available_slots = max(0, watch.get('max_concurrency', 1) - current_running)
    table_limit = table_max_concurrency_for_watch(watch)
    if table_limit is not None:
        current_table_running = count_running_by_table(watch['table']) + count_live_persisted_by_table(watch['table'], running_state)
        table_slots = max(0, table_limit - current_table_running)
        available_slots = min(available_slots, table_slots)
    elif not TABLE_KEY:
        global_limit = current_global_max_concurrency(policy)
        if global_limit <= 0:
            global_limit = 0
    else:
        global_limit = 0
    if not TABLE_KEY and global_limit > 0:
        global_slots = max(0, global_limit - count_active_running_tasks())
        available_slots = min(available_slots, global_slots)
    if available_slots <= 0:
        return

    try:
        records = get_watch_candidate_records_cached(token, watch)
    except Exception as e:
        log.error(f"[{watch['name']}] 读取表失败: {e}")
        append_last_error(watch['name'], 'TABLE', f'读取表失败: {e}')
        return

    launched = 0

    for rec in records:
        if launched >= available_slots:
            break

        record_id = rec['record_id']
        fields = rec.get('fields', {})
        if not record_matches_watch_filters(watch, fields):
            continue
        status = extract_text(fields.get(watch['status_field'], ''))
        valid_trigger_values = watch.get('trigger_values') or [watch['trigger_value']]
        task_key = make_task_key(watch, record_id)
        if status in retryable_failed_statuses_for_watch(watch):
            if maybe_requeue_failed_candidate(token, watch, record_id, task_key, fields, status):
                continue
        if status not in valid_trigger_values:
            update_record_state_cache(watch, record_id, status)
            continue

        running_info = {
            'table': watch.get('table'),
            'status_field': watch.get('status_field'),
            'script': watch['script'],
            'args': watch.get('args', []) or [],
            'record_id': record_id,
        }
        if task_key in running_processes:
            process = running_processes[task_key].get('process')
            if process is None or process.poll() is None:
                continue

        if pop_legacy_running_state(running_state, watch, record_id):
            continue

        if task_key in running_state:
            running_info = running_state.get(task_key) or running_info
            if has_live_process_for_task_key(task_key, running_info):
                continue
            log.warning(f"[{watch['name']}] 清理无活跃进程的 running state，准备接管: {record_id}")
            running_state.pop(task_key, None)
            save_running_tasks(running_state)

        stale_running_candidate = False
        if status == watch.get('running_value') and status != watch.get('trigger_value'):
            if has_live_process_for_task_key(task_key, running_info):
                continue
            stale_running_candidate = True
        elif should_skip_claim_by_cache(watch, record_id, status):
            continue

        task_id = extract_text(fields.get('任务ID', '')) or extract_text(fields.get('任务名称', '')) or record_id
        if not try_claim_task(token, watch, record_id):
            continue
        if stale_running_candidate:
            log.info(f"[{watch['name']}] 接管 stale 生成中任务: {record_id}")

        script_path = os.path.join(SCRIPTS_DIR, watch['script'])
        try:
            extra_args = (watch.get('args_by_trigger_value') or {}).get(status)
            if extra_args is None:
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
                'table': watch.get('table'),
                'status_field': watch.get('status_field'),
                'script': watch['script'],
                'args': extra_args,
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
                fallback_trigger = (watch.get('trigger_values') or [watch['trigger_value']])[0]
                safe_update_record(token, watch['table'], record_id, {
                    watch['status_field']: fallback_trigger
                })
            except Exception:
                pass


def check_daily_health():
    if TABLE_KEY:
        return
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


def write_heartbeat(status='running', note=None):
    payload = {
        'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'status': status,
        'note': note or '',
        'pid': os.getpid(),
    }
    save_json_file(HEARTBEAT_FILE, payload)


def log_effective_concurrency(policy, watches=None):
    rows = effective_concurrency_report(policy, watches)
    compact_rows = [
        f"{row['watch_name']} local={row['local_default']} applied={row['applied_max_concurrency']} source={row['policy_source']}"
        for row in rows
        if row['policy_source'] == 'feishu' or row['watch_name'] in MEDIA_REGENERATION_WATCH_NAMES
    ]
    if compact_rows:
        log.info(f"   最终生效并发: {'; '.join(compact_rows)}")


def main():
    log.info("🚀 TK 任务调度器启动（增强版 + 自动重试 + 运行统计）")
    log.info(f"   实例名: {INSTANCE}")
    log.info(f"   表格作用域: {TABLE_KEY or '<all>'}")
    log.info(f"   配置文件: {os.environ.get('TK_CONFIG_FILE', os.path.join(SCRIPTS_DIR, 'config.json'))}")
    log.info(f"   轮询间隔: {POLL_INTERVAL}秒")
    log.info(f"   监控环节: {', '.join(w['name'] for w in ordered_watch_list())}")
    if TABLE_KEY and not WATCH_LIST:
        note = f"table_key={TABLE_KEY} 未匹配任何 watch"
        write_heartbeat(status='blocked', note=note)
        log.error(note)
        raise SystemExit(2)

    bootstrap_running_state()
    token = get_feishu_token()
    token_time = time.time()
    log_effective_concurrency(load_feishu_concurrency_policy(token, force=True), ordered_watch_list())
    last_metrics_log = 0
    normal_watch_rotation_offset = 0

    while True:
        write_heartbeat(status='running')
        if time.time() - token_time > 1200:
            try:
                token = get_feishu_token()
                token_time = time.time()
                log_effective_concurrency(load_feishu_concurrency_policy(token, force=True), ordered_watch_list())
            except Exception as e:
                log.error(f"刷新 token 失败: {e}")
                append_last_error('系统', 'TOKEN', e)
                time.sleep(POLL_INTERVAL)
                continue

        cleanup_finished_processes(token)
        check_daily_health()

        for watch in ordered_watch_list(normal_rotation_offset=normal_watch_rotation_offset):
            if not watch.get('table'):
                continue
            check_and_run(token, watch)
        normal_watch_rotation_offset += 1

        if time.time() - last_metrics_log > 600:
            log_metrics_snapshot()
            last_metrics_log = time.time()

        time.sleep(POLL_INTERVAL)


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        try:
            write_heartbeat(status='crashed', note=str(e)[:500])
        except Exception:
            pass
        log.exception(f'💥 dispatcher crashed: {e}')
        raise
