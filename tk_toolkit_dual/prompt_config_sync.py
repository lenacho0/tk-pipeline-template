#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]

PROMPT_STAGE_FILES: Dict[str, Path] = {
    "爆款视频分析-UGC": PROJECT_ROOT / "docs/prompts/ugc-single-video-analysis-system-prompt-v1.md",
    "UGC-脚本生成": PROJECT_ROOT / "docs/prompts/ugc-script-generation-system-prompt-v1.md",
    "UGC-9宫格分镜图生成": PROJECT_ROOT / "docs/prompts/ugc-6-grid-storyboard-system-prompt-2026-04-30.md",
    "UGC-9宫格分镜图拆分": PROJECT_ROOT / "docs/prompts/content-nine-grid-split-system-prompt-2026-05-03.md",
    "UGC-视频提示词生成": PROJECT_ROOT / "docs/prompts/ugc-image-to-video-system-prompt-2026-05-02.md",
    "非UGC-爆款视频分析": PROJECT_ROOT / "docs/prompts/non-ugc-animation-video-analysis-system-prompt-v1.md",
    "非UGC-脚本生成": PROJECT_ROOT / "docs/prompts/non-ugc-animation-script-generation-system-prompt-v3-content.md",
    "非UGC-9宫格分镜图生成": PROJECT_ROOT / "docs/prompts/non-ugc-animation-nine-grid-storyboard-system-prompt-v1-content.md",
    "非UGC-视频提示词生成": PROJECT_ROOT / "docs/prompts/non-ugc-animation-image-to-video-system-prompt-v1-content.md",
}


@dataclass
class SyncResult:
    stage: str
    path: Path
    record_id: str = ""
    changed: bool = False
    local_len: int = 0
    remote_len: int = 0
    message: str = ""


def resolve_prompt_path(stage: str, *, custom_path: Optional[str] = None) -> Path:
    if custom_path:
        return Path(custom_path).expanduser().resolve()
    path = PROMPT_STAGE_FILES.get(stage)
    if not path:
        known = "、".join(sorted(PROMPT_STAGE_FILES))
        raise ValueError(f"未知提示词环节: {stage}。已知环节: {known}")
    return path


def _extract_text(value: Any) -> str:
    from common import extract_text

    return extract_text(value)


def find_config_record_by_stage(token: str, stage: str) -> Dict[str, Any]:
    from common import TABLE_CONFIG, safe_list_records

    for record in safe_list_records(token, TABLE_CONFIG):
        fields = record.get("fields", {})
        if _extract_text(fields.get("环节")).strip() == stage:
            return record
    raise ValueError(f"飞书配置表未找到环节: {stage}")


def read_remote_prompt(token: str, stage: str) -> tuple[str, str]:
    record = find_config_record_by_stage(token, stage)
    # Do not strip: prompt sync must preserve exact bytes/characters,
    # including intentional trailing newlines in local Markdown files.
    prompt = _extract_text(record.get("fields", {}).get("提示词"))
    return record.get("record_id", ""), prompt


def sync_from_feishu(
    stage: str,
    *,
    path: Optional[str] = None,
    dry_run: bool = False,
    token_getter: Optional[Callable[[], str]] = None,
) -> SyncResult:
    from common import get_feishu_token

    prompt_path = resolve_prompt_path(stage, custom_path=path)
    token = (token_getter or get_feishu_token)()
    record_id, remote_prompt = read_remote_prompt(token, stage)
    local_prompt = prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else ""
    changed = local_prompt != remote_prompt
    if changed and not dry_run:
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(remote_prompt, encoding="utf-8")
    return SyncResult(
        stage=stage,
        path=prompt_path,
        record_id=record_id,
        changed=changed,
        local_len=len(local_prompt),
        remote_len=len(remote_prompt),
        message="would update local file" if dry_run and changed else ("updated local file" if changed else "already in sync"),
    )


def update_remote_prompt(token: str, record_id: str, prompt: str, *, remark: str = "") -> Dict[str, Any]:
    from common import TABLE_CONFIG, update_record

    fields = {"提示词": prompt}
    if remark:
        fields["备注"] = remark
    result = update_record(token, TABLE_CONFIG, record_id, fields)
    if result.get("code") != 0:
        raise RuntimeError(f"写回飞书配置表失败: {result}")
    return result


def sync_to_feishu(
    stage: str,
    *,
    path: Optional[str] = None,
    dry_run: bool = True,
    token_getter: Optional[Callable[[], str]] = None,
    updater: Optional[Callable[[str, str, str], Any]] = None,
) -> SyncResult:
    from common import get_feishu_token

    prompt_path = resolve_prompt_path(stage, custom_path=path)
    if not prompt_path.exists():
        raise FileNotFoundError(f"本地提示词文件不存在: {prompt_path}")
    local_prompt = prompt_path.read_text(encoding="utf-8")
    token = (token_getter or get_feishu_token)()
    record_id, remote_prompt = read_remote_prompt(token, stage)
    changed = local_prompt != remote_prompt
    if changed and not dry_run:
        remark = f"prompt_config_sync: synced from local file {prompt_path.relative_to(PROJECT_ROOT)}"
        if updater:
            updater(token, record_id, local_prompt)
        else:
            update_remote_prompt(token, record_id, local_prompt, remark=remark)
    return SyncResult(
        stage=stage,
        path=prompt_path,
        record_id=record_id,
        changed=changed,
        local_len=len(local_prompt),
        remote_len=len(remote_prompt),
        message="would update Feishu config" if dry_run and changed else ("updated Feishu config" if changed else "already in sync"),
    )


def list_stages() -> str:
    lines = []
    for stage, path in sorted(PROMPT_STAGE_FILES.items()):
        rel = path.relative_to(PROJECT_ROOT)
        lines.append(f"{stage}\t{rel}")
    return "\n".join(lines)


def print_result(result: SyncResult) -> None:
    print(f"stage: {result.stage}")
    print(f"record_id: {result.record_id}")
    print(f"path: {result.path}")
    print(f"local_len: {result.local_len}")
    print(f"remote_len: {result.remote_len}")
    print(f"changed: {result.changed}")
    print(f"result: {result.message}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sync prompt text between Feishu config table and local docs/prompts files.")
    sub = parser.add_subparsers(dest="command", required=True)

    list_cmd = sub.add_parser("list", help="List known prompt stages and local files")
    list_cmd.set_defaults(func=lambda args: print(list_stages()))

    pull = sub.add_parser("from-feishu", help="Pull prompt from Feishu config table into local file")
    pull.add_argument("stage", help="配置表环节名，例如 非UGC-脚本生成")
    pull.add_argument("--path", help="Override local prompt path")
    pull.add_argument("--dry-run", action="store_true", help="Only compare, do not write local file")
    pull.set_defaults(func=lambda args: print_result(sync_from_feishu(args.stage, path=args.path, dry_run=args.dry_run)))

    push = sub.add_parser("to-feishu", help="Push local prompt file into Feishu config table")
    push.add_argument("stage", help="配置表环节名，例如 非UGC-脚本生成")
    push.add_argument("--path", help="Override local prompt path")
    push.add_argument("--write", action="store_true", help="Actually update Feishu; default is dry-run")
    push.set_defaults(func=lambda args: print_result(sync_to_feishu(args.stage, path=args.path, dry_run=not args.write)))
    return parser


def main(argv: Optional[Iterable[str]] = None) -> None:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    args.func(args)


if __name__ == "__main__":
    main()
