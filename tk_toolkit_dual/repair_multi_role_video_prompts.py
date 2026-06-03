#!/usr/bin/env python3
"""
Repair multi-role first/last-frame video prompts that still contain Chinese.

Default mode is read-only. Use --write to translate and write repaired prompts
back to Feishu. Running video tasks are skipped unless --include-running is set.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ai_routing  # noqa: E402
from common import (  # noqa: E402
    TABLE_CONFIG,
    TABLE_MULTI_ROLE_FIRST_LAST,
    build_error_payload,
    extract_text,
    get_feishu_token,
    safe_list_records,
    safe_update_record,
)
from tk_multi_role_first_last import PARSE_STAGE_NAME, get_stage_config  # noqa: E402
from tk_shot_storyboard import filter_existing_fields  # noqa: E402


CJK_TEXT_RE = re.compile(r"[\u3400-\u9fff]")
THAI_TEXT_RE = re.compile(r"[\u0e00-\u0e7f]")
RUNNING_STATUS = "生成中"
RETRY_STATE_FILE = Path(__file__).with_name(".retry_state.ryan.json")
DEAD_LETTER_FILE = Path(__file__).with_name(".dead_letter_tasks.ryan.json")


@dataclass(frozen=True)
class RepairCandidate:
    record_id: str
    parent_record_id: str
    clip_type: str
    status: str
    prompt: str
    snippet: str


def has_cjk_text(text: str) -> bool:
    return bool(CJK_TEXT_RE.search(text or ""))


def cjk_snippet(text: str, *, radius: int = 36) -> str:
    match = CJK_TEXT_RE.search(text or "")
    if not match:
        return ""
    start = max(0, match.start() - radius)
    end = min(len(text), match.end() + radius)
    return text[start:end].replace("\n", "\\n")


def _strip_code_fence(text: str) -> str:
    value = (text or "").strip()
    if value.startswith("```"):
        value = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", value)
        value = re.sub(r"\s*```$", "", value)
    return value.strip()


def build_repair_prompt(source_prompt: str) -> str:
    return f"""
You repair a Google Veo 3.1 video prompt.

Rules:
- Output only the repaired video prompt, with no markdown, no JSON, and no explanation.
- Translate Chinese visual/action directions into English.
- preserve Thai dialogue exactly, including every Thai character and punctuation mark.
- Keep existing English content unless it must be lightly adjusted for grammar.
- Do not remove conflict details, product actions, visible problem anchors, camera beats, sound effects, ambient noise, or reaction reversals.
- The final output must not contain Chinese or CJK text.
- Dialogue may use colon format, for example: The owner says in Thai: ไม่ต้องตกใจ

Source prompt:
{source_prompt}
""".strip()


def build_policy_safe_repair_prompt(source_prompt: str, *, clip_type: str = "") -> str:
    clip_rule = (
        "S01 rule: keep the scene before the completed cleaning result; the product may be aimed or beginning to spray, but do not show the stain fully cleaned."
        if clip_type == "S01"
        else "S02 result rule: show a realistic improved result only; describe the treated area as cleaner and slightly damp, not magically perfect."
    )
    return f"""
You rewrite a Google Veo 3.1 image-to-video prompt for a Thai TikTok UGC product scene.

Rules:
- Output only the repaired video prompt, with no markdown, no JSON, and no explanation.
- Visual, action, camera, environment, product action, sound effects, ambient noise, and restrictions must be written in English.
- preserve Thai dialogue exactly, including every Thai character and punctuation mark, unless a line is an explicit shopping CTA.
- avoid shopping CTA, cart/link language, order-now language, and product-link gestures.
- Avoid absolute or exaggerated claims such as completely removed, permanently removed, 100 percent, miracle, safe to lick, guaranteed, or instant perfect result.
- Avoid harsh aggression, threatening harm, throwing pets, animal abuse, injuries, blood, or violent physical contact.
- Keep the product action tied to the visible accident source, stain, odor source, carpet, sofa, mattress, tile crevice, or fabric area.
- {clip_rule}
- The final output must not contain Chinese or CJK text.
- Dialogue should use colon format, for example: The owner says in Thai: ไม่ต้องตกใจ
- Keep the prompt compact enough for Veo while preserving the conflict beat, product action, visible problem anchor, camera beats, sound effects, ambient noise, and reaction reversal.

Source prompt:
{source_prompt}
""".strip()


def repair_prompt_text(
    source_prompt: str,
    *,
    translate_fn: Callable[[str], str],
    policy_safe_regenerate: bool = False,
    clip_type: str = "",
) -> str:
    prompt = source_prompt.strip()
    if not has_cjk_text(prompt) and not policy_safe_regenerate:
        return prompt
    repair_request = (
        build_policy_safe_repair_prompt(prompt, clip_type=clip_type)
        if policy_safe_regenerate
        else build_repair_prompt(prompt)
    )
    repaired = _strip_code_fence(translate_fn(repair_request))
    if not repaired:
        raise ValueError("修复模型返回空视频提示词")
    if has_cjk_text(repaired):
        raise ValueError(f"修复后仍包含中文/CJK: {cjk_snippet(repaired)}")
    return repaired


def collect_repair_candidates(
    records: Iterable[Dict[str, Any]],
    *,
    include_running: bool = False,
    record_ids: Optional[Set[str]] = None,
    policy_safe_regenerate: bool = False,
) -> Tuple[List[RepairCandidate], List[RepairCandidate]]:
    candidates: List[RepairCandidate] = []
    skipped_running: List[RepairCandidate] = []
    for rec in records:
        record_id = rec.get("record_id") or rec.get("id") or ""
        if record_ids and record_id not in record_ids:
            continue
        fields = rec.get("fields") or {}
        if extract_text(fields.get("记录类型")).strip() != "视频片段":
            continue
        prompt = extract_text(fields.get("视频提示词")).strip()
        if not has_cjk_text(prompt) and not policy_safe_regenerate:
            continue
        item = RepairCandidate(
            record_id=record_id,
            parent_record_id=extract_text(fields.get("父任务记录ID")).strip(),
            clip_type=extract_text(fields.get("视频片段类型")).strip(),
            status=extract_text(fields.get("视频生成状态")).strip(),
            prompt=prompt,
            snippet=cjk_snippet(prompt),
        )
        if item.status == RUNNING_STATUS and not include_running:
            skipped_running.append(item)
            continue
        candidates.append(item)
    return candidates, skipped_running


def _translation_route() -> ai_routing.AiRoute:
    _, cfg = get_stage_config(
        PARSE_STAGE_NAME,
        default_model="gemini-3.1-pro-preview",
        default_api_base="https://aihubmix.com/gemini",
    )
    raw_model = extract_text(cfg.get("model")).strip() or "gemini-3.1-pro-preview"
    bits = ai_routing.parse_model_display(raw_model)
    provider = bits["provider"] or "AIHubMix"
    model = raw_model if bits["provider"] else f"{provider} / {bits['model'] or raw_model}"
    params: Dict[str, Any] = {}
    raw_params = extract_text(cfg.get("params")).strip()
    if raw_params:
        try:
            loaded = json.loads(raw_params)
            if isinstance(loaded, dict):
                params = loaded
        except json.JSONDecodeError:
            params = {}
    params.setdefault("temperature", 0.1)
    return ai_routing.AiRoute(
        provider=provider,
        capability="文本",
        task_type="多角色视频提示词英文化修复",
        model=model,
        call_type=extract_text(cfg.get("call_type")).strip() or "Gemini 原生 SDK",
        api_base=extract_text(cfg.get("api_base")).strip(),
        api_key=extract_text(cfg.get("api_key")).strip(),
        params=params,
    )


def _make_translate_fn(route: ai_routing.AiRoute) -> Callable[[str], str]:
    def _translate(prompt: str) -> str:
        return ai_routing.call_text_model(route, prompt).text

    return _translate


def _load_json_map(path: Path) -> Dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    return data if isinstance(data, dict) else {}


def _save_json_map(path: Path, data: Dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def clear_dispatcher_state_for_record(record_id: str, *, write: bool = False) -> Dict[str, Any]:
    key = f"tk_multi_role_first_last.py::video::{record_id}"
    retry_state = _load_json_map(RETRY_STATE_FILE)
    dead_letters = _load_json_map(DEAD_LETTER_FILE)
    removed_retry_keys = [key] if key in retry_state else []
    removed_dead_letter_keys = [key] if key in dead_letters else []
    if write:
        for item in removed_retry_keys:
            retry_state.pop(item, None)
        for item in removed_dead_letter_keys:
            dead_letters.pop(item, None)
        if removed_retry_keys:
            _save_json_map(RETRY_STATE_FILE, retry_state)
        if removed_dead_letter_keys:
            _save_json_map(DEAD_LETTER_FILE, dead_letters)
    return {
        "removed_retry_keys": removed_retry_keys,
        "removed_dead_letter_keys": removed_dead_letter_keys,
    }


def build_reset_for_rerun_payload(repaired_prompt: str) -> Dict[str, Any]:
    return {
        "视频提示词": repaired_prompt,
        "视频生成状态": "待生成",
        "视频操作": "不触发",
        "视频任务ID": "",
        "视频本地路径": "",
        "视频错误信息": "",
        "错误信息": "",
        "视频原始响应JSON": "",
    }


def run_repair(
    *,
    write: bool = False,
    include_running: bool = False,
    limit: int = 0,
    record_ids: Optional[Iterable[str]] = None,
    policy_safe_regenerate: bool = False,
    reset_for_rerun: bool = False,
) -> Dict[str, Any]:
    if not TABLE_MULTI_ROLE_FIRST_LAST:
        raise RuntimeError("config.json 尚未配置 multi_role_first_last 表 ID")
    token = get_feishu_token()
    records = safe_list_records(token, TABLE_MULTI_ROLE_FIRST_LAST)
    record_id_set = {str(item).strip() for item in (record_ids or []) if str(item).strip()}
    candidates, skipped_running = collect_repair_candidates(
        records,
        include_running=include_running,
        record_ids=record_id_set or None,
        policy_safe_regenerate=policy_safe_regenerate,
    )
    if limit > 0:
        candidates = candidates[:limit]
    summary: Dict[str, Any] = {
        "dry_run": not write,
        "policy_safe_regenerate": policy_safe_regenerate,
        "reset_for_rerun": reset_for_rerun,
        "candidate_count": len(candidates),
        "skipped_running_count": len(skipped_running),
        "candidates": [
            {
                "record_id": item.record_id,
                "parent_record_id": item.parent_record_id,
                "clip_type": item.clip_type,
                "status": item.status,
                "snippet": item.snippet,
            }
            for item in candidates
        ],
        "skipped_running": [
            {
                "record_id": item.record_id,
                "parent_record_id": item.parent_record_id,
                "clip_type": item.clip_type,
                "status": item.status,
                "snippet": item.snippet,
            }
            for item in skipped_running
        ],
    }
    if not write or not candidates:
        return summary

    route = _translation_route()
    translate_fn = _make_translate_fn(route)
    repaired_records = []
    for item in candidates:
        repaired = repair_prompt_text(
            item.prompt,
            translate_fn=translate_fn,
            policy_safe_regenerate=policy_safe_regenerate,
            clip_type=item.clip_type,
        )
        payload = (
            build_reset_for_rerun_payload(repaired)
            if reset_for_rerun
            else {"视频提示词": repaired}
        )
        safe_update_record(
            token,
            TABLE_MULTI_ROLE_FIRST_LAST,
            item.record_id,
            filter_existing_fields(token, TABLE_MULTI_ROLE_FIRST_LAST, payload),
        )
        cleanup = clear_dispatcher_state_for_record(item.record_id, write=reset_for_rerun)
        repaired_records.append({
            "record_id": item.record_id,
            "parent_record_id": item.parent_record_id,
            "clip_type": item.clip_type,
            "old_chars": len(item.prompt),
            "new_chars": len(repaired),
            "thai_preserved": bool(THAI_TEXT_RE.search(item.prompt)) == bool(THAI_TEXT_RE.search(repaired)),
            "reset_for_rerun": reset_for_rerun,
            "dispatcher_state_cleanup": cleanup,
        })
    summary["repaired_records"] = repaired_records
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="修复多角色首尾帧视频提示词中的中文动作描述")
    parser.add_argument("--write", action="store_true", help="真实回填修复后的视频提示词；默认只读 dry-run")
    parser.add_argument("--dry-run", action="store_true", help="兼容显式 dry-run；不写表")
    parser.add_argument("--include-running", action="store_true", help="包含视频生成状态=生成中的记录")
    parser.add_argument("--limit", type=int, default=0, help="最多修复 N 条；0 表示不限制")
    parser.add_argument("--record-id", action="append", default=[], help="只修复指定记录；可重复传入")
    parser.add_argument("--policy-safe-regenerate", action="store_true", help="即使原提示词无中文，也按最新安全规则重新生成")
    parser.add_argument("--reset-for-rerun", action="store_true", help="写回后清旧视频任务信息并置为待生成")
    args = parser.parse_args()
    write = bool(args.write and not args.dry_run)
    try:
        result = run_repair(
            write=write,
            include_running=args.include_running,
            limit=args.limit,
            record_ids=args.record_id,
            policy_safe_regenerate=args.policy_safe_regenerate,
            reset_for_rerun=args.reset_for_rerun,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    except Exception as exc:
        payload = build_error_payload(exc, stage="repair_multi_role_video_prompts")
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        sys.exit(1)


if __name__ == "__main__":
    main()
