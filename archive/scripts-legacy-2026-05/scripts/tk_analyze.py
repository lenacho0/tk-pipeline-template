#!/usr/bin/env python3
"""
环节2：爆款视频脚本分析
用法: python3 tk_analyze.py <record_id>
从飞书配置表读取提示词和模型 → 上传视频到 Gemini Files API → 等待 ACTIVE → 分析 → 写回结果
"""
import json, os, sys, time, requests, urllib3
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *

urllib3.disable_warnings()

VIDEO_DIR = os.path.join(WORKSPACE, 'tiktok_videos')
ANALYSIS_CONFIG_RECORD = 'recveizDqAaxWy'

DEFAULT_PROMPT = """你是一个专业的 TikTok 带货视频脚本分析师。请仔细观看这个视频，然后按以下维度进行详细拆解：

1. **开头Hook**：视频前3秒是如何吸引观众停留的？
2. **痛点/需求**：视频展示了什么痛点或需求？
3. **产品展示**：产品是如何展示的？
4. **使用效果**：展示了什么使用前后的效果？
5. **CTA话术**：视频有什么行动号召？
6. **脚本结构**：整个视频的结构是什么？
7. **视频节奏**：节奏感、镜头切换频率？
8. **BGM/音效**：背景音乐或音效类型？
9. **文案风格**：口播/字幕风格？
10. **爆款要素分析**：能火的关键要素是什么？
11. **可复用模板**：提炼一个可复用的脚本模板。

请用中文回答，每个维度详细分析。"""

def wait_for_file_active(client, file_name, api_base, api_key, max_wait=120):
    """轮询等待 Gemini Files API 文件变为 ACTIVE 状态"""
    print(f'  等待文件激活: {file_name}')
    for i in range(max_wait // 5):
        time.sleep(5)
        try:
            resp = requests.get(
                f'{api_base}/v1beta/files/{file_name}?key={api_key}',
                timeout=30, verify=False
            )
            data = resp.json()
            state = data.get('state', 'UNKNOWN')
            print(f'  文件状态: {state}')
            if state == 'ACTIVE':
                return True
            elif state in ('FAILED', 'ERROR'):
                raise Exception(f'文件上传失败: {state}')
        except Exception as e:
            print(f'  状态检查异常: {e}')
    raise Exception(f'文件激活超时（等待 {max_wait} 秒）')

def main():
    if len(sys.argv) < 2:
        print("用法: python3 tk_analyze.py <record_id>")
        sys.exit(1)
    record_id = sys.argv[1]
    token = get_feishu_token()

    try:
        # ---- 1. 读取配置 ----
        config = get_model_config(token, ANALYSIS_CONFIG_RECORD)
        model_name = config['model'] or 'gemini-2.5-flash'
        api_key = config['api_key']
        api_base = config['api_base']
        prompt = config['prompt'] or DEFAULT_PROMPT

        # ---- 2. 读取任务信息 ----
        fields = get_record(token, TABLE_ANALYSIS, record_id)
        video_id = extract_text(fields.get('视频ID', ''))
        if not video_id:
            raise Exception('无视频ID')

        video_path = os.path.join(VIDEO_DIR, f'{video_id}.mp4')
        if not os.path.exists(video_path) or os.path.getsize(video_path) < 1000:
            raise Exception(f'视频文件不存在或太小: {video_path}')

        update_record(token, TABLE_ANALYSIS, record_id, {'分析状态': '分析中'})
        print(f'开始分析视频: {video_id}')

        # ---- 3. 获取 API Key（优先飞书配置，fallback openclaw.json）----
        if not api_key:
            cfg = load_openclaw_config()
            for pk, pv in cfg.get('models', {}).get('providers', {}).items():
                if 'aihubmix' in pv.get('baseUrl', ''):
                    api_key = pv['apiKey']
                    api_base = api_base or pv['baseUrl']
                    break
        if not api_key:
            raise Exception('找不到 API Key')
        if not api_base:
            api_base = 'https://aihubmix.com/gemini'

        # ---- 4. 用 inline_data 方式直接传视频给 Gemini ----
        # 不依赖外部 URL，直接 base64 编码传输（适合 20MB 以下文件）
        from google.genai import Client, types
        client = Client(api_key=api_key, http_options={'base_url': api_base})

        print(f'  读取视频: {os.path.getsize(video_path)//1024//1024}MB')
        with open(video_path, 'rb') as f:
            video_bytes = f.read()

        print(f'  发送 Gemini 分析请求...')
        response = client.models.generate_content(
            model=model_name,
            contents=[
                types.Content(parts=[
                    types.Part(
                        inline_data=types.Blob(data=video_bytes, mime_type='video/mp4')
                    ),
                    types.Part(text=prompt)
                ])
            ]
        )
        result = response.text

        # ---- 7. 写回结果 ----
        update_record(token, TABLE_ANALYSIS, record_id, {
            '脚本结构': result[:10000],
            '分析状态': '成功'})
        print(f'✅ 分析完成 ({len(result)}字)')

    except Exception as e:
        try:
            update_record(token, TABLE_ANALYSIS, record_id, {
                '分析状态': '失败', '脚本结构': f'错误: {str(e)[:500]}'})
        except:
            pass
        print(f'❌ {e}')
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()
