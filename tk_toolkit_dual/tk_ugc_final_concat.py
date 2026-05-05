#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ugc_config import UGC_BASE_TOKEN, load_ugc_table_ids
from ugc_utils import extract_linked_record_ids, extract_text
from tk_ugc_six_grid import get_feishu_token, get_ugc_record, create_ugc_record, update_ugc_record, json_dumps
from tk_ugc_shot_videos import download_feishu_media, upload_video_to_feishu

BASE_WORK_DIR = Path(__file__).resolve().parent / "workspace_ryan" / "ugc_final_concat_work"
DEFAULT_UGC06_RECORD_IDS = [
    "recviqdQNUCITK",
    "recviqdRegrc0I",
    "recviqdRCF7vB4",
    "recviqdS12ne1Y",
    "recviqdSrQPN6A",
    "recviqdSPPUiSG",
]

RecordGetter = Callable[[str, str, str], Dict[str, Any]]
RecordCreator = Callable[[str, str, Dict[str, Any]], str]
RecordUpdater = Callable[[str, str, str, Dict[str, Any]], Any]
Uploader = Callable[[str, str, str], str]
FinalRunner = Callable[..., Dict[str, Any]]


def ensure_work_dir(batch_key: str) -> Path:
    work_dir = BASE_WORK_DIR / batch_key
    work_dir.mkdir(parents=True, exist_ok=True)
    return work_dir


def get_video_file_token(fields: Dict[str, Any]) -> str:
    text_token = extract_text(fields.get("分镜视频file_token")).strip()
    if text_token:
        return text_token
    attachments = fields.get("分镜视频")
    if isinstance(attachments, list) and attachments:
        first = attachments[0]
        if isinstance(first, dict):
            return str(first.get("file_token") or "").strip()
    return ""


def resolve_video_path(token: str, record_id: str, fields: Dict[str, Any], work_dir: Path) -> Path:
    local_path = extract_text(fields.get("本地视频路径")).strip()
    if local_path and Path(local_path).exists():
        return Path(local_path)
    file_token = get_video_file_token(fields)
    if not file_token:
        raise ValueError(f"UGC-06 {record_id} 缺少分镜视频 file_token/路径")
    return download_feishu_media(token, file_token, work_dir / f"{record_id}_video.mp4")


def resolve_selected_ugc06_records(records: List[Dict[str, Any]], expected_shot_count: int) -> List[str]:
    by_shot: Dict[int, str] = {}
    duplicates: List[int] = []
    for record in records:
        fields = record.get("fields") or {}
        if extract_text(fields.get("候选状态")).strip() != "采用":
            continue
        if extract_text(fields.get("视频生成状态")).strip() != "成功":
            continue
        try:
            shot_index = int(float(extract_text(fields.get("分镜序号") or 0)))
        except Exception:
            raise ValueError(f"采用的 UGC-06 记录缺少有效分镜序号: {record.get('record_id')}")
        if shot_index in by_shot:
            duplicates.append(shot_index)
        by_shot[shot_index] = record.get("record_id") or ""
    if duplicates:
        raise ValueError(f"同一分镜存在多个采用候选: {sorted(set(duplicates))}")
    missing = [idx for idx in range(1, expected_shot_count + 1) if idx not in by_shot]
    if missing:
        raise ValueError(f"缺少已采用且成功的 UGC-06 分镜候选: {missing}")
    return [by_shot[idx] for idx in range(1, expected_shot_count + 1)]


def collect_ugc06_videos(
    record_ids: List[str],
    *,
    token: Optional[str] = None,
    get_record_fn: RecordGetter = get_ugc_record,
) -> Dict[str, Any]:
    token = token or get_feishu_token()
    table_ids = load_ugc_table_ids()
    ugc06_table = table_ids["ugc_06_shot_videos"]
    work_dir = ensure_work_dir("-".join([rid[-6:] for rid in record_ids]) or datetime.now().strftime("%Y%m%d%H%M%S"))
    items: List[Dict[str, Any]] = []
    script_ids: List[str] = []
    missing: List[str] = []
    for rid in record_ids:
        fields = get_record_fn(token, ugc06_table, rid)
        status = extract_text(fields.get("视频生成状态")).strip()
        shot_index = int(float(extract_text(fields.get("分镜序号") or 0)))
        if status != "成功":
            missing.append(f"{rid}: 视频生成状态={status or '空'}")
            continue
        script_ids.extend(extract_linked_record_ids(fields.get("关联脚本版本")))
        video_path = resolve_video_path(token, rid, fields, work_dir)
        items.append({
            "record_id": rid,
            "shot_index": shot_index,
            "video_path": str(video_path),
            "file_token": get_video_file_token(fields),
        })
    items.sort(key=lambda item: item["shot_index"])
    expected = list(range(1, len(items) + 1))
    actual = [int(item["shot_index"]) for item in items]
    if missing:
        raise ValueError("存在未完成分镜视频: " + "; ".join(missing))
    if actual != expected:
        raise ValueError(f"分镜序号不连续: actual={actual}, expected={expected}")
    return {
        "work_dir": str(work_dir),
        "shot_count": len(items),
        "items": items,
        "script_record_ids": sorted(set(script_ids)),
    }


def ffprobe_duration(path: str) -> float:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", path],
        text=True,
        capture_output=True,
        check=True,
    )
    return float(proc.stdout.strip())


def ffprobe_has_audio(path: str) -> bool:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=codec_type", "-of", "csv=p=0", path],
        text=True,
        capture_output=True,
        check=True,
    )
    return "audio" in proc.stdout


def run_ffmpeg_concat(items: List[Dict[str, Any]], work_dir: str, output_path: str) -> str:
    """Normalize and concat shot videos while preserving Veo-generated audio.

    UGC-06/Veo is expected to generate the final spoken audio directly from the
    image-to-video prompt. UGC-07 must not strip that audio and must not replace
    it with TTS. If a source clip unexpectedly lacks audio, add a silent AAC
    track only so FFmpeg concat has consistent streams.
    """
    normalized_paths: List[str] = []
    for item in items:
        src = item["video_path"]
        normalized = str(Path(work_dir) / f"shot_{int(item['shot_index']):02d}_norm_av.mp4")
        common_args = [
            "ffmpeg", "-y", "-hide_banner", "-i", src,
            "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps=30",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-pix_fmt", "yuv420p",
        ]
        if ffprobe_has_audio(src):
            subprocess.run(common_args + [
                "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
                "-af", "aresample=async=1:first_pts=0",
                "-shortest",
                normalized,
            ], check=True)
        else:
            subprocess.run(common_args + [
                "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
                "-map", "0:v:0", "-map", "1:a:0",
                "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
                "-shortest",
                normalized,
            ], check=True)
        normalized_paths.append(normalized)
    concat_list = Path(work_dir) / "concat_list.txt"
    concat_list.write_text("".join(f"file '{p}'\n" for p in normalized_paths), encoding="utf-8")
    subprocess.run([
        "ffmpeg", "-y", "-hide_banner", "-f", "concat", "-safe", "0", "-i", str(concat_list),
        "-c", "copy", output_path,
    ], check=True)
    if not Path(output_path).exists() or Path(output_path).stat().st_size < 10000:
        raise RuntimeError(f"成片输出失败或文件过小: {output_path}")
    if not ffprobe_has_audio(output_path):
        raise RuntimeError(f"成片输出缺少音轨: {output_path}")
    return str(concat_list)


def make_feishu_preview_with_audio(master_path: str) -> str:
    """Create a smaller Feishu-upload preview while preserving the audio track."""
    src = Path(master_path)
    preview_path = str(src.with_name(f"{src.stem}_with_audio_feishu.mp4"))
    subprocess.run([
        "ffmpeg", "-y", "-hide_banner", "-i", master_path,
        "-c:v", "libx264", "-preset", "medium",
        "-b:v", "2800k", "-maxrate", "3200k", "-bufsize", "6400k",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart",
        preview_path,
    ], check=True)
    if not Path(preview_path).exists() or Path(preview_path).stat().st_size < 10000:
        raise RuntimeError(f"飞书压缩版输出失败或文件过小: {preview_path}")
    if not ffprobe_has_audio(preview_path):
        raise RuntimeError(f"飞书压缩版缺少音轨: {preview_path}")
    return preview_path


def upload_with_preview_fallback(token: str, uploader: Uploader, master_path: str, task_id: str) -> Dict[str, str]:
    """Upload master video; if Base rejects it, upload an audio-preserving preview."""
    try:
        file_token = uploader(token, master_path, f"{task_id}.mp4")
        return {"file_token": file_token, "uploaded_path": master_path, "uploaded_name": f"{task_id}.mp4", "note": "母版上传成功"}
    except Exception as exc:
        preview_path = make_feishu_preview_with_audio(master_path)
        file_token = uploader(token, preview_path, f"{task_id}_with_audio_feishu.mp4")
        return {
            "file_token": file_token,
            "uploaded_path": preview_path,
            "uploaded_name": f"{task_id}_with_audio_feishu.mp4",
            "note": f"母版上传失败({exc})，已上传保留音轨的飞书压缩预览版；母版本地保留",
        }


def build_ugc07_fields(task_id: str, collected: Dict[str, Any], concat_list_text: str, status: str = "待合成") -> Dict[str, Any]:
    fields: Dict[str, Any] = {
        "成片任务ID": task_id,
        "分镜视频数量": collected["shot_count"],
        "已完成分镜视频数量": collected["shot_count"],
        "合成状态": status,
        "FFmpeg concat list": concat_list_text[:10000],
        "错误信息": "",
    }
    script_ids = collected.get("script_record_ids") or []
    if script_ids:
        fields["关联脚本版本"] = script_ids
    return fields


def create_or_run_final_concat(
    record_ids: List[str],
    *,
    write: bool = False,
    token: Optional[str] = None,
    get_record_fn: RecordGetter = get_ugc_record,
    create_record_fn: RecordCreator = create_ugc_record,
    update_record_fn: RecordUpdater = update_ugc_record,
    uploader: Uploader = upload_video_to_feishu,
    selected_summary: str = "",
) -> Dict[str, Any]:
    token = token or get_feishu_token()
    table_ids = load_ugc_table_ids()
    ugc07_table = table_ids["ugc_07_final_concat"]
    collected = collect_ugc06_videos(record_ids, token=token, get_record_fn=get_record_fn)
    task_id = f"UGC-FINAL-{datetime.now().strftime('%Y%m%d%H%M%S')}-{record_ids[0][-6:]}"
    work_dir = collected["work_dir"]
    output_path = str(Path(work_dir) / f"{task_id}.mp4")
    concat_list_text = "".join(f"file '{item['video_path']}'\n" for item in collected["items"])
    result: Dict[str, Any] = {
        "dry_run": not write,
        "task_id": task_id,
        "record_ids": record_ids,
        "selected_summary": selected_summary,
        "collected": collected,
        "concat_list_preview": concat_list_text,
        "output_path": output_path,
        "created_record_id": "",
        "final_file_token": "",
    }
    if not write:
        return result

    initial_fields = build_ugc07_fields(task_id, collected, concat_list_text, status="合成中")
    if selected_summary:
        initial_fields["采用UGC06记录列表JSON"] = json_dumps(record_ids)
        initial_fields["候选选择摘要"] = selected_summary
    ugc07_record_id = create_record_fn(token, ugc07_table, initial_fields)
    result["created_record_id"] = ugc07_record_id
    try:
        actual_concat_list = run_ffmpeg_concat(collected["items"], work_dir, output_path)
        duration = ffprobe_duration(output_path)
        upload_result = upload_with_preview_fallback(token, uploader, output_path, task_id)
        file_token = upload_result["file_token"]
        update_record_fn(token, ugc07_table, ugc07_record_id, {
            "合成状态": "成功",
            "成片视频": [{"file_token": file_token, "name": upload_result["uploaded_name"]}],
            "本地成片路径": f"母版: {output_path}\n飞书上传版: {upload_result['uploaded_path']}",
            "FFmpeg concat list": Path(actual_concat_list).read_text(encoding="utf-8")[:10000],
            "错误信息": f"合成成功；保留 Veo 原始音轨；不做 TTS；duration={duration:.2f}s；shots={collected['shot_count']}；{upload_result['note']}",
            **({"采用UGC06记录列表JSON": json_dumps(record_ids), "候选选择摘要": selected_summary} if selected_summary else {}),
        })
        result.update({
            "status": "success",
            "final_file_token": file_token,
            "duration_seconds": duration,
            "output_size": Path(output_path).stat().st_size,
            "uploaded_path": upload_result["uploaded_path"],
            "uploaded_name": upload_result["uploaded_name"],
        })
        return result
    except Exception as exc:
        update_record_fn(token, ugc07_table, ugc07_record_id, {
            "合成状态": "失败",
            "错误信息": f"UGC-07 合成失败: {exc}"[:1000],
        })
        raise


def list_ugc_records(token: str, table_id: str, *, page_size: int = 500) -> List[Dict[str, Any]]:
    from common import feishu_headers, safe_request

    records: List[Dict[str, Any]] = []
    page_token = ""
    while True:
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{UGC_BASE_TOKEN}/tables/{table_id}/records?page_size={page_size}"
        if page_token:
            url += f"&page_token={page_token}"
        data = safe_request("get", url, headers=feishu_headers(token), timeout=30, max_attempts=3)
        records.extend(data.get("data", {}).get("items") or [])
        if not data.get("data", {}).get("has_more"):
            break
        page_token = data.get("data", {}).get("page_token") or ""
        if not page_token:
            break
    return records


def create_or_run_final_concat_from_selected(
    *,
    expected_shot_count: int,
    records: Optional[List[Dict[str, Any]]] = None,
    write: bool = False,
    token: Optional[str] = None,
    runner: FinalRunner = create_or_run_final_concat,
) -> Dict[str, Any]:
    if records is None:
        token = token or get_feishu_token()
        table_ids = load_ugc_table_ids()
        records = list_ugc_records(token, table_ids["ugc_06_shot_videos"])
    selected_ids = resolve_selected_ugc06_records(records, expected_shot_count=expected_shot_count)
    summary = f"按候选状态=采用选择 {len(selected_ids)} 条 UGC-06 成功分镜：{', '.join(selected_ids)}"
    result = runner(selected_ids, write=write, token=token, selected_summary=summary)
    result["selected_ugc06_record_ids"] = selected_ids
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="UGC-07 成片合成/拼接。默认 dry-run；--write 创建 UGC-07 记录、FFmpeg 拼接并写回成片。")
    parser.add_argument("record_ids", nargs="*", help="UGC-06 record_id 列表；为空使用当前 6 条已生成分镜视频，或配合 --from-selected 从候选状态=采用解析")
    parser.add_argument("--from-selected", action="store_true", help="从 UGC-06 候选状态=采用 的成功记录解析有序分镜列表")
    parser.add_argument("--expected-shot-count", type=int, default=6, help="--from-selected 时要求的分镜数量")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--output-file")
    args = parser.parse_args()
    if args.from_selected:
        if args.record_ids:
            raise ValueError("--from-selected 模式下不要同时手动传 record_ids")
        result = create_or_run_final_concat_from_selected(expected_shot_count=args.expected_shot_count, write=args.write)
    else:
        result = create_or_run_final_concat(args.record_ids or DEFAULT_UGC06_RECORD_IDS, write=args.write)
    text = json_dumps(result)
    print(text)
    if args.output_file:
        Path(args.output_file).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_file).write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
