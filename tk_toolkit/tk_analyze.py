#!/usr/bin/env python3
"""
环节2：爆款视频脚本分析
用法: python3 tk_analyze.py <record_id>
从飞书配置表读取提示词和模型 → 获取视频文件（本地 / 飞书附件 / 视频链接补拉）→ 上传视频到 Gemini → 分析 → 输出结构化摘要 + 详细分析 → 写回脚本结构 → 更新状态
"""
import json, os, sys, time, requests, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *

VIDEO_DIR = os.path.join(WORKSPACE, 'tiktok_videos')

DEFAULT_PROMPT = """
你是一个专业的 TikTok 带货视频脚本分析师。
请严格按以下格式输出，不要说多余的话：

第一行只输出：<<<JSON>>>
第二部分输出一个合法 JSON 对象，字段必须完整：
{
  "hook_summary": "",
  "pain_point_summary": "",
  "product_reveal_summary": "",
  "proof_summary": "",
  "cta_summary": "",
  "rhythm_summary": "",
  "visual_pattern": "",
  "viral_reason": "",
  "reusable_pattern": "",
  "trigger_type": "从 痛点直出 / 效果对比 / 场景带入 / 口播种草 / 达人信任 / 视觉反差 中选择最贴切的一种或两种",
  "fit_products": "这类表达更适合什么类型产品"
}
第三行只输出：<<<DETAIL>>>
第四部分输出详细中文分析，覆盖以下维度：
1. 开头Hook
2. 痛点/需求
3. 产品展示
4. 使用效果
5. CTA话术
6. 脚本结构
7. 视频节奏
8. BGM/音效
9. 文案风格
10. 爆款要素分析
11. 可复用模板

要求：
- 严格使用 <<<JSON>>> 和 <<<DETAIL>>> 作为分隔标记
- JSON 必须可解析
- JSON 内容要简洁、抽象、可迁移
- 详细分析要保留足够信息，供后续人工复查
"""


def ensure_video_dir():
    if os.path.lexists(VIDEO_DIR):
        if os.path.islink(VIDEO_DIR):
            target = os.readlink(VIDEO_DIR)
            raise Exception(f'视频目录路径被符号链接占用: {VIDEO_DIR} -> {target}')
        if not os.path.isdir(VIDEO_DIR):
            raise Exception(f'视频目录路径被非目录文件占用: {VIDEO_DIR}')
        return
    os.makedirs(VIDEO_DIR, exist_ok=True)


def download_feishu_media(token, file_token, save_path):
    resp = requests.get(
        f'https://open.feishu.cn/open-apis/drive/v1/medias/{file_token}/download',
        headers={'Authorization': f'Bearer {token}'},
        timeout=120,
        stream=True
    )
    if resp.status_code != 200:
        raise Exception(f'飞书附件下载失败 HTTP {resp.status_code}')
    with open(save_path, 'wb') as f:
        for chunk in resp.iter_content(8192):
            f.write(chunk)
    if os.path.getsize(save_path) < 1000:
        raise Exception('飞书附件下载成功但文件过小')
    return save_path


def download_from_video_link(video_url, save_path):
    candidate_urls = [video_url]
    m = re.search(r'(\d{10,})', video_url or '')
    if m:
        video_id = m.group(1)
        for extra in [
            f'https://www.tiktok.com/@user/video/{video_id}',
            f'https://www.tiktok.com/video/{video_id}',
            f'https://m.tiktok.com/v/{video_id}.html',
        ]:
            if extra not in candidate_urls:
                candidate_urls.append(extra)

    def _download(source_url):
        resp = requests.get('https://www.tikwm.com/api/', params={'url': source_url}, timeout=30)
        data = resp.json()
        play_url = data.get('data', {}).get('play') or data.get('data', {}).get('hdplay')
        if data.get('code') != 0 or not play_url:
            raise Exception(f"tikwm 解析失败: {data.get('msg', 'unknown')}")
        dl = requests.get(play_url, timeout=120, stream=True)
        if dl.status_code != 200:
            raise Exception(f'视频下载失败 HTTP {dl.status_code}')
        with open(save_path, 'wb') as f:
            for chunk in dl.iter_content(8192):
                f.write(chunk)
        if os.path.getsize(save_path) < 1000:
            raise Exception('视频下载后文件过小')
        return save_path

    last_error = None
    for source_url in candidate_urls:
        try:
            return with_retry(lambda url=source_url: _download(url), max_attempts=2, label=f'download analysis video from link via {source_url}')
        except Exception as e:
            last_error = e
            log_event('WARN', 'analysis download fallback failed', source_url=source_url, error=str(e)[:200])
            if os.path.exists(save_path):
                try:
                    os.remove(save_path)
                except Exception:
                    pass

    raise last_error or Exception('视频链接补拉失败')


def find_data_record_by_video_id(token, video_id):
    records = safe_list_records(token, TABLE_DATA)
    for rec in records:
        fields = rec.get('fields', {})
        if extract_text(fields.get('视频ID', '')) == video_id:
            return rec
    return None


def ensure_video_file(token, analysis_fields, video_id):
    ensure_video_dir()
    video_path = os.path.join(VIDEO_DIR, f'{video_id}.mp4')

    if os.path.exists(video_path) and os.path.getsize(video_path) >= 1000:
        return video_path, 'local'

    data_rec = find_data_record_by_video_id(token, video_id)
    if data_rec:
        data_fields = data_rec.get('fields', {})

        attachments = data_fields.get('无水印视频', [])
        if attachments and isinstance(attachments, list):
            file_token = attachments[0].get('file_token', '')
            if file_token:
                path = with_retry(
                    lambda: download_feishu_media(token, file_token, video_path),
                    max_attempts=3,
                    label='download analysis video from feishu attachment'
                )
                return path, 'feishu_attachment'

        video_link = data_fields.get('视频链接', {})
        if isinstance(video_link, dict):
            url = video_link.get('link', '')
            if url:
                path = download_from_video_link(url, video_path)
                return path, 'video_link'

    direct_link = analysis_fields.get('视频链接', {})
    if isinstance(direct_link, dict):
        url = direct_link.get('link', '')
        if url:
            path = download_from_video_link(url, video_path)
            return path, 'analysis_link'

    raise Exception(f'视频文件不存在，且无法从飞书附件或视频链接补拉: {video_id}')


def upload_and_wait_active(client, video_path, max_wait=180):
    uploaded = with_retry(lambda: client.files.upload(file=video_path), max_attempts=3, label='gemini file upload')
    waited = 0
    while uploaded.state.name == 'PROCESSING' and waited < max_wait:
        time.sleep(3)
        waited += 3
        uploaded = with_retry(lambda: client.files.get(name=uploaded.name), max_attempts=3, label='gemini file poll')
    if uploaded.state.name != 'ACTIVE':
        raise Exception(f'视频处理失败: {uploaded.state.name}')
    return uploaded


def generate_analysis(client, model_name, uploaded, prompt):
    response = with_retry(
        lambda: client.models.generate_content(model=model_name, contents=[uploaded, prompt]),
        max_attempts=3,
        label='gemini analyze generate_content'
    )
    result = getattr(response, 'text', '') or ''
    if not result.strip():
        raise Exception('Gemini 返回空结果')
    return result


def reformat_analysis_to_structured(client, model_name, raw_text):
    prompt = f"""
你是一个输出格式修复器，不需要重新分析视频，只需要把已有分析内容重整为指定格式。

请把下面这段分析内容，严格重写成以下格式：
第一行：<<<JSON>>>
第二部分：一个合法 JSON 对象，必须包含以下全部字段：
{{
  "hook_summary": "",
  "pain_point_summary": "",
  "product_reveal_summary": "",
  "proof_summary": "",
  "cta_summary": "",
  "rhythm_summary": "",
  "visual_pattern": "",
  "viral_reason": "",
  "reusable_pattern": "",
  "trigger_type": "",
  "fit_products": ""
}}
第三行：<<<DETAIL>>>
第四部分：保留并整理详细中文分析。

要求：
- 只能基于现有内容重整，不能虚构视频细节
- JSON 必须可解析
- 除上述格式外不要输出任何多余内容

原始分析内容如下：
{raw_text}
""".strip()

    response = with_retry(
        lambda: client.models.generate_content(model=model_name, contents=[prompt]),
        max_attempts=2,
        label='gemini analyze reformat generate_content'
    )
    result = getattr(response, 'text', '') or ''
    if not result.strip():
        raise Exception('Gemini 重整结果为空')
    return result


def extract_structured_summary(raw_text):
    raw_text = (raw_text or '').strip()
    if not raw_text:
        return None, ''

    if '<<<JSON>>>' in raw_text and '<<<DETAIL>>>' in raw_text:
        try:
            after_json = raw_text.split('<<<JSON>>>', 1)[1]
            json_part, detail_part = after_json.split('<<<DETAIL>>>', 1)
            summary = json.loads(json_part.strip())
            return summary, detail_part.strip()
        except Exception:
            pass

    match = re.search(r'\{[\s\S]*?\}', raw_text)
    if not match:
        return None, raw_text
    try:
        parsed = json.loads(match.group())
        detailed = raw_text[match.end():].strip()
        return parsed, detailed
    except Exception:
        return None, raw_text


def build_saved_analysis(summary, detailed):
    if not summary:
        return detailed[:10000]
    head = "【结构化摘要】\n" + json.dumps(summary, ensure_ascii=False, indent=2)
    if detailed:
        body = "\n\n【详细分析】\n" + detailed
    else:
        body = ''
    return (head + body)[:10000]


def main():
    if len(sys.argv) < 2:
        print("用法: python3 tk_analyze.py <record_id>")
        sys.exit(1)
    record_id = sys.argv[1]
    token = get_feishu_token()
    uploaded = None

    try:
        log_event('INFO', 'analysis task start', record_id=record_id)
        config = get_model_config(token, CONFIG_RECORDS['analysis'])
        model_name = config['model'] or 'gemini-2.5-flash'
        api_key = config['api_key']
        api_base = config['api_base'] or 'https://aihubmix.com/gemini'
        prompt = config['prompt'] or DEFAULT_PROMPT

        fields = safe_get_record(token, TABLE_ANALYSIS, record_id)
        video_id = extract_text(fields.get('视频ID', ''))
        if not video_id:
            raise Exception('无视频ID')

        safe_update_record(token, TABLE_ANALYSIS, record_id, {'分析状态': '分析中'})

        if not api_key:
            raise Exception('飞书配置表缺少 API Key，请在「模型与API配置」表中填写')

        video_path, source = ensure_video_file(token, fields, video_id)
        log_event('INFO', 'analysis video ready', record_id=record_id, video_id=video_id, source=source, path=video_path)

        from google import genai
        client = genai.Client(api_key=api_key, http_options={'base_url': api_base})

        uploaded = upload_and_wait_active(client, video_path, max_wait=180)
        raw_result = generate_analysis(client, model_name, uploaded, prompt)
        summary, detailed = extract_structured_summary(raw_result)
        if not summary:
            log_event('WARN', 'analysis missing structured summary, retry reformat', record_id=record_id, video_id=video_id)
            reformatted = reformat_analysis_to_structured(client, model_name, raw_result)
            summary, detailed = extract_structured_summary(reformatted)
            if summary:
                raw_result = reformatted
        saved_result = build_saved_analysis(summary, detailed)

        safe_update_record(token, TABLE_ANALYSIS, record_id, {
            '脚本结构': saved_result,
            '分析状态': '成功'
        })
        log_event('INFO', 'analysis task success', record_id=record_id, video_id=video_id, result_len=len(saved_result), has_summary=bool(summary))
        print(f'✅ 分析完成 ({len(saved_result)}字)')

    except Exception as e:
        err = str(e)[:500]
        log_event('ERROR', 'analysis task failed', record_id=record_id, error=err)
        try:
            safe_update_record(token, TABLE_ANALYSIS, record_id, {
                '分析状态': '失败',
                '脚本结构': f'错误: {err}'
            })
        except Exception as write_err:
            log_event('ERROR', 'analysis failure writeback failed', record_id=record_id, error=str(write_err)[:500])
        print(f'❌ {e}')
        sys.exit(1)
    finally:
        if uploaded is not None:
            try:
                with_retry(lambda: client.files.delete(name=uploaded.name), max_attempts=2, label='gemini file delete')
            except Exception as cleanup_err:
                log_event('WARN', 'gemini file cleanup failed', record_id=record_id, error=str(cleanup_err)[:300])


if __name__ == '__main__':
    main()
