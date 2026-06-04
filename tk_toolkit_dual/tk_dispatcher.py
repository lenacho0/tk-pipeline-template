#!/usr/bin/env python3
"""
TK 任务调度器 —— 轮询飞书多维表格，发现「待执行」任务后自动执行对应脚本
增强版：增加本地并发控制、避免同一任务重复启动、子进程异步轮询回收、最小任务级自动重试、运行统计

用法: python3 tk_dispatcher.py
后台运行: nohup python3 tk_dispatcher.py >> dispatcher.log 2>&1 &
"""
import json, os, sys, time, subprocess, logging
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
POLL_INTERVAL = int(DISPATCHER_CFG.get('poll_interval', 30) or 30)
HEALTHCHECK_HOUR = int(DISPATCHER_CFG.get('healthcheck_hour', 8) or 8)
HEALTHCHECK_DONE_FILE = os.path.join(SCRIPTS_DIR, f'.healthcheck_today.{INSTANCE}')
RUNNING_TASKS_FILE = os.path.join(SCRIPTS_DIR, f'.running_tasks.{INSTANCE}.json')
RETRY_STATE_FILE = os.path.join(SCRIPTS_DIR, f'.retry_state.{INSTANCE}.json')
METRICS_FILE = os.path.join(SCRIPTS_DIR, f'.dispatcher_metrics.{INSTANCE}.json')
HEARTBEAT_FILE = os.path.join(SCRIPTS_DIR, f'.dispatcher_heartbeat.{INSTANCE}.json')
DEAD_LETTER_FILE = os.path.join(SCRIPTS_DIR, f'.dead_letter_tasks.{INSTANCE}.json')
CIRCUIT_BREAKER_FILE = os.path.join(SCRIPTS_DIR, f'.circuit_breakers.{INSTANCE}.json')
STAGE_CFG = DISPATCHER_CFG.get('stages', {})
CIRCUIT_CFG = DISPATCHER_CFG.get('circuit_breaker', {})
GLOBAL_MAX_CONCURRENCY = int(DISPATCHER_CFG.get('global_max_concurrency') or 0)
TABLE_SCAN_STATE_FILE = os.path.join(SCRIPTS_DIR, f'.table_scan_state.{INSTANCE}.json')
RECORD_STATE_CACHE_FILE = os.path.join(SCRIPTS_DIR, f'.record_state_cache.{INSTANCE}.json')
SCAN_CFG = DISPATCHER_CFG.get('scan', {})
TABLE_MIN_INTERVAL_SECONDS = int(SCAN_CFG.get('table_min_interval_seconds', 20) or 20)
RECORD_STATE_CACHE_TTL_SECONDS = int(SCAN_CFG.get('record_state_cache_ttl_seconds', 300) or 300)
RUNTIME_LOG_FILE = os.path.join(SCRIPTS_DIR, f'dispatcher-runtime.{INSTANCE}.log')
_TABLE_FIELD_KINDS_CACHE = {}
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
    '九宫格图',
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
        'name': '故事板提示词拆分',
        'table': TABLE_STORYBOARD_VIDEO,
        'status_field': '拆分状态',
        'trigger_value': '待拆分',
        'running_value': '拆分中',
        'failed_value': '失败',
        'error_field': '错误信息',
        'script': 'tk_storyboard_video.py',
        'args': ['split'],
        'timeout': 900,
        'max_concurrency': 1,
        'max_retries': 1,
        'required_field_values': {'记录类型': ['母任务']},
    },
    {
        'name': '故事板图片生成',
        'table': TABLE_STORYBOARD_VIDEO,
        'status_field': '故事板图片生成状态',
        'trigger_value': '待生成',
        'trigger_values': ['待生成', '生成中'],
        'running_value': '生成中',
        'failed_value': '失败',
        'error_field': '故事板图片错误信息',
        'script': 'tk_storyboard_video.py',
        'args': ['image'],
        'timeout': 1200,
        'max_concurrency': 1,
        'max_retries': 2,
        'required_field_values': {'记录类型': ['Storyboard分段']},
        'claim_clear_values_by_trigger_value': {
            '待生成': {
                '故事板图': [],
                '故事板图片任务ID': '',
                '故事板图片错误信息': '',
                '故事板图片生成时间': None,
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
        'name': '故事板Omni视频生成',
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
        'required_field_values': {'记录类型': ['Storyboard分段']},
        'claim_clear_values': {
            '分镜视频': [],
            '分镜视频URL': None,
            '视频错误信息': '',
            '视频生成时间': None,
            '错误信息': '',
        },
        'claim_clear_fields_by_trigger_value': {
            '待生成': ['视频任务ID'],
        },
    },
    {
        'name': '多图九宫格方案生成',
        'table': TABLE_NINE_GRID_VIDEO,
        'status_field': '方案生成状态',
        'trigger_value': '待生成',
        'running_value': '生成中',
        'failed_value': '失败',
        'error_field': '错误信息',
        'script': 'tk_nine_grid_video.py',
        'args': ['plan'],
        'timeout': 900,
        'max_concurrency': 1,
        'max_retries': 1,
        'required_field_values': {'记录类型': ['母任务']},
    },
    {
        'name': '多图九宫格参考图生成',
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
        'name': '多图九宫格参考图审核推进',
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
        'name': '多图九宫格参考图重生成',
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
        'name': '多图九宫格图片生成',
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
        'name': '多图九宫格视频生成',
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
        'max_retries': 1,
        'required_field_values': {'记录类型': ['Board分段']},
        'claim_clear_values': {
            '分镜视频': [],
            '分镜视频URL': None,
            '视频错误信息': '',
            '视频生成时间': None,
            '错误信息': '',
        },
        'claim_clear_fields_by_trigger_value': {
            '待生成': ['视频任务ID'],
        },
    },
    {
        'name': '首尾帧批量场景拆分',
        'table': TABLE_FIRST_LAST_VIDEO,
        'status_field': '拆分状态',
        'trigger_value': '待拆分',
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
        'running_value': '生成中',
        'failed_value': '失败',
        'error_field': '视频错误信息',
        'script': 'tk_shot_video.py',
        'args': ['--table', 'script_doc'],
        'timeout': 2400,
        'max_concurrency': 1,
        'max_retries': 1,
        'claim_clear_fields': ['视频任务ID', '视频生成原始响应JSON'],
    },
]


RAW_WATCH_LIST = list(WATCH_LIST)
WATCH_LIST = [w for w in WATCH_LIST if w.get('table') or w.get('keep_when_table_missing')]


running_processes = {}


def load_dead_letters():
    return load_json_file(DEAD_LETTER_FILE)


def save_dead_letters(data):
    save_json_file(DEAD_LETTER_FILE, data)


def load_circuit_breakers():
    return load_json_file(CIRCUIT_BREAKER_FILE)


def save_circuit_breakers(data):
    save_json_file(CIRCUIT_BREAKER_FILE, data)


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
    return merged


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
    return f"{watch['script']}::{action_key}::{record_id}"


def format_timeout_reason(watch, record_id, elapsed):
    timeout = int(watch.get('timeout', 900) or 900)
    return (
        f"{watch.get('name', '任务')} worker timeout: record_id={record_id}, "
        f"elapsed={int(elapsed)}s, timeout={timeout}s. 上游任务可能仍在生成或轮询未结束。"
    )


def legacy_task_key(watch, record_id):
    return f"{watch['script']}::{record_id}"


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


def running_state_entry_matches_watch(task_info, watch):
    if task_info.get('script') != watch.get('script'):
        return False
    stored_args = [str(arg) for arg in (task_info.get('args') or [])]
    watch_args = [str(arg) for arg in (watch.get('args') or [])]
    if stored_args:
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


def has_live_process_for_task_key(task_key, task_info):
    script = task_info.get('script') or task_key.split('::', 1)[0]
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
    cache_file = os.path.join(SCRIPTS_DIR, f'.table_cache_{table_id}.{INSTANCE}.json')

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


def check_and_run(token, watch):
    watch = apply_stage_policy(watch)
    cleanup_finished_processes(token)
    running_state = load_running_tasks()
    current_running = count_running_by_watch(watch['name']) + count_live_persisted_by_watch(watch, running_state)
    available_slots = max(0, watch.get('max_concurrency', 1) - current_running)
    if GLOBAL_MAX_CONCURRENCY > 0:
        global_slots = max(0, GLOBAL_MAX_CONCURRENCY - count_active_running_tasks())
        available_slots = min(available_slots, global_slots)
    if available_slots <= 0:
        return

    try:
        records = get_table_records_cached(token, watch['table'])
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
        if status not in valid_trigger_values:
            update_record_state_cache(watch, record_id, status)
            continue

        task_key = make_task_key(watch, record_id)
        running_info = {'script': watch['script'], 'record_id': record_id}
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


def main():
    log.info("🚀 TK 任务调度器启动（增强版 + 自动重试 + 运行统计）")
    log.info(f"   实例名: {INSTANCE}")
    log.info(f"   配置文件: {os.environ.get('TK_CONFIG_FILE', os.path.join(SCRIPTS_DIR, 'config.json'))}")
    log.info(f"   轮询间隔: {POLL_INTERVAL}秒")
    log.info(f"   监控环节: {', '.join(w['name'] for w in WATCH_LIST)}")

    bootstrap_running_state()
    token = get_feishu_token()
    token_time = time.time()
    last_metrics_log = 0

    while True:
        write_heartbeat(status='running')
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
        check_daily_health()

        for watch in WATCH_LIST:
            if not watch.get('table'):
                continue
            check_and_run(token, watch)

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
