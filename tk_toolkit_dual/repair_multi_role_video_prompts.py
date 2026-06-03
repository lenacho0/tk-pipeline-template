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
from typing import Any, Callable, Dict, Iterable, List, Tuple

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


def repair_prompt_text(source_prompt: str, *, translate_fn: Callable[[str], str]) -> str:
    prompt = source_prompt.strip()
    if not has_cjk_text(prompt):
        return prompt
    repaired = _strip_code_fence(translate_fn(build_repair_prompt(prompt)))
    if not repaired:
        raise ValueError("修复模型返回空视频提示词")
    if has_cjk_text(repaired):
        raise ValueError(f"修复后仍包含中文/CJK: {cjk_snippet(repaired)}")
    return repaired


def collect_repair_candidates(
    records: Iterable[Dict[str, Any]],
    *,
    include_running: bool = False,
) -> Tuple[List[RepairCandidate], List[RepairCandidate]]:
    candidates: List[RepairCandidate] = []
    skipped_running: List[RepairCandidate] = []
    for rec in records:
        fields = rec.get("fields") or {}
        if extract_text(fields.get("记录类型")).strip() != "视频片段":
            continue
        prompt = extract_text(fields.get("视频提示词")).strip()
        if not has_cjk_text(prompt):
            continue
        item = RepairCandidate(
            record_id=rec.get("record_id") or rec.get("id") or "",
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


def run_repair(*, write: bool = False, include_running: bool = False, limit: int = 0) -> Dict[str, Any]:
    if not TABLE_MULTI_ROLE_FIRST_LAST:
        raise RuntimeError("config.json 尚未配置 multi_role_first_last 表 ID")
    token = get_feishu_token()
    records = safe_list_records(token, TABLE_MULTI_ROLE_FIRST_LAST)
    candidates, skipped_running = collect_repair_candidates(records, include_running=include_running)
    if limit > 0:
        candidates = candidates[:limit]
    summary: Dict[str, Any] = {
        "dry_run": not write,
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
        repaired = repair_prompt_text(item.prompt, translate_fn=translate_fn)
        safe_update_record(
            token,
            TABLE_MULTI_ROLE_FIRST_LAST,
            item.record_id,
            filter_existing_fields(token, TABLE_MULTI_ROLE_FIRST_LAST, {"视频提示词": repaired}),
        )
        repaired_records.append({
            "record_id": item.record_id,
            "parent_record_id": item.parent_record_id,
            "clip_type": item.clip_type,
            "old_chars": len(item.prompt),
            "new_chars": len(repaired),
            "thai_preserved": bool(THAI_TEXT_RE.search(item.prompt)) == bool(THAI_TEXT_RE.search(repaired)),
        })
    summary["repaired_records"] = repaired_records
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="修复多角色首尾帧视频提示词中的中文动作描述")
    parser.add_argument("--write", action="store_true", help="真实回填修复后的视频提示词；默认只读 dry-run")
    parser.add_argument("--dry-run", action="store_true", help="兼容显式 dry-run；不写表")
    parser.add_argument("--include-running", action="store_true", help="包含视频生成状态=生成中的记录")
    parser.add_argument("--limit", type=int, default=0, help="最多修复 N 条；0 表示不限制")
    args = parser.parse_args()
    write = bool(args.write and not args.dry_run)
    try:
        result = run_repair(write=write, include_running=args.include_running, limit=args.limit)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    except Exception as exc:
        payload = build_error_payload(exc, stage="repair_multi_role_video_prompts")
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        sys.exit(1)


if __name__ == "__main__":
    main()
