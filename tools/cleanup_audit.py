#!/usr/bin/env python3
"""Dry-run cleanup audit for this workspace.

This script only reads files and git metadata. It does not delete, move, or
modify anything.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable


EXCLUDED_DIRS = {".git"}
LOCAL_DEPENDENCY_DIR_NAMES = {".venv", "venv", ".venv312", "node_modules"}

SAFE_JUNK_FILE_NAMES = {".DS_Store"}
SAFE_JUNK_DIR_NAMES = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
SAFE_JUNK_PATTERNS = (
    ".tmp_*",
    "tmp_*",
    "*.pyc",
    "*.pyo",
    "*.bak",
    "*.bak.*",
    "*.bak-*",
)

RUNTIME_STATE_PATTERNS = (
    "*.pid",
    "*.log",
    "dispatcher*.log",
    "dispatcher-runtime*.log",
    "launchd.*.log",
    ".dispatcher_heartbeat*.json",
    ".dispatcher_metrics*.json",
    ".retry_state*.json",
    ".running_tasks*.json",
    ".record_state_cache*.json",
    ".table_cache_*.json",
    ".table_scan_state*.json",
    ".dead_letter_tasks*.json",
    ".circuit_breakers*.json",
    ".healthcheck_today*",
)

GENERATED_DIR_NAMES = (
    "first_last_video_work",
    "script_doc_reference_work",
    "shot_video_work",
    "shot_voiceover_work",
    "storyboard_video_work",
    "storyboard_work",
    "structured_script_shadow_output",
    "tiktok_videos",
    "video_from_storyboard_work",
    "video_work",
    "workspace",
)

GENERATED_DIR_PATTERNS = (
    "tk_toolkit_dual/workspace_*",
    "tk_toolkit_dual/workspace",
    "tk_toolkit_dual/*_work",
    "tk_toolkit_dual/ugc_*_work",
    "archive_from_autoclaw_*",
)

SUGGESTED_GITIGNORE_PATTERNS = (
    ".clawhub/",
    "config/mcporter.json",
    "first_last_video_work/",
    "script_doc_reference_work/",
    "shot_video_work/",
    "shot_voiceover_work/",
    "storyboard_video_work/",
    "tmp_*.png",
)


@dataclass(frozen=True)
class FileItem:
    path: str
    size_bytes: int
    kind: str


@dataclass(frozen=True)
class DirItem:
    path: str
    size_bytes: int
    file_count: int
    latest_mtime: float
    kind: str


def run_git(root: Path, args: list[str]) -> list[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line]


def rel_path(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def matches_any(name_or_path: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatch(name_or_path, pattern) for pattern in patterns)


def file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def dir_stats(root: Path, directory: Path) -> tuple[int, int, float]:
    total = 0
    count = 0
    latest = 0.0
    for current, dirnames, filenames in os.walk(directory):
        dirnames[:] = [name for name in dirnames if name not in EXCLUDED_DIRS]
        current_path = Path(current)
        try:
            latest = max(latest, current_path.stat().st_mtime)
        except OSError:
            pass
        for filename in filenames:
            path = current_path / filename
            try:
                stat = path.stat()
            except OSError:
                continue
            total += stat.st_size
            count += 1
            latest = max(latest, stat.st_mtime)
    return total, count, latest


def format_size(size: int) -> str:
    units = ("B", "K", "M", "G", "T")
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)}B"
            return f"{value:.1f}{unit}"
        value /= 1024
    return f"{size}B"


def iter_paths(root: Path) -> Iterable[Path]:
    for current, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            name
            for name in dirnames
            if name not in EXCLUDED_DIRS and name not in LOCAL_DEPENDENCY_DIR_NAMES
        ]
        current_path = Path(current)
        for dirname in dirnames:
            yield current_path / dirname
        for filename in filenames:
            yield current_path / filename


def collect_safe_junk(root: Path) -> list[FileItem]:
    items: list[FileItem] = []
    for path in iter_paths(root):
        relative = rel_path(root, path)
        name = path.name
        if path.is_dir() and name in SAFE_JUNK_DIR_NAMES:
            size, _, _ = dir_stats(root, path)
            items.append(FileItem(relative, size, "safe_junk_dir"))
            continue
        if not path.is_file():
            continue
        if name in SAFE_JUNK_FILE_NAMES or matches_any(name, SAFE_JUNK_PATTERNS):
            items.append(FileItem(relative, file_size(path), "safe_junk_file"))
    return sorted(items, key=lambda item: (-item.size_bytes, item.path))


def collect_runtime_state(root: Path) -> list[FileItem]:
    items: list[FileItem] = []
    for path in iter_paths(root):
        if not path.is_file():
            continue
        relative = rel_path(root, path)
        if matches_any(path.name, RUNTIME_STATE_PATTERNS):
            items.append(FileItem(relative, file_size(path), "runtime_state"))
    return sorted(items, key=lambda item: (-item.size_bytes, item.path))


def is_generated_dir(root: Path, path: Path) -> bool:
    relative = rel_path(root, path)
    return path.name in GENERATED_DIR_NAMES or matches_any(relative, GENERATED_DIR_PATTERNS)


def collect_generated_dirs(root: Path) -> list[DirItem]:
    items: list[DirItem] = []
    for child in root.iterdir():
        if child.name in EXCLUDED_DIRS or not child.is_dir():
            continue
        if is_generated_dir(root, child):
            size, count, latest = dir_stats(root, child)
            items.append(DirItem(rel_path(root, child), size, count, latest, "generated_artifact_dir"))

    dual_root = root / "tk_toolkit_dual"
    if dual_root.is_dir():
        for child in dual_root.iterdir():
            if child.name in EXCLUDED_DIRS or not child.is_dir():
                continue
            if is_generated_dir(root, child):
                size, count, latest = dir_stats(root, child)
                items.append(DirItem(rel_path(root, child), size, count, latest, "generated_artifact_dir"))

    return sorted(items, key=lambda item: (-item.size_bytes, item.path))


def collect_local_dependency_dirs(root: Path) -> list[DirItem]:
    items: list[DirItem] = []
    for current, dirnames, _ in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in EXCLUDED_DIRS]
        current_path = Path(current)
        for dirname in list(dirnames):
            if dirname not in LOCAL_DEPENDENCY_DIR_NAMES:
                continue
            path = current_path / dirname
            size, count, latest = dir_stats(root, path)
            items.append(DirItem(rel_path(root, path), size, count, latest, "local_dependency_dir"))
            dirnames.remove(dirname)
    return sorted(items, key=lambda item: (-item.size_bytes, item.path))


def collect_untracked(root: Path) -> list[str]:
    return sorted(run_git(root, ["ls-files", "--others", "--exclude-standard"]))


def collect_ignored(root: Path) -> list[str]:
    return sorted(run_git(root, ["ls-files", "--ignored", "--others", "--exclude-standard"]))


def collect_modified(root: Path) -> list[str]:
    return sorted(run_git(root, ["status", "--short"]))


def top_level_counts(paths: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in paths:
        top = path.split("/", 1)[0]
        counts[top] = counts.get(top, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def is_likely_generated_untracked(path: str) -> bool:
    top = path.split("/", 1)[0]
    return (
        top in GENERATED_DIR_NAMES
        or matches_any(path, GENERATED_DIR_PATTERNS)
        or matches_any(Path(path).name, SAFE_JUNK_PATTERNS)
        or Path(path).name in SAFE_JUNK_FILE_NAMES
    )


def build_report(root: Path) -> dict[str, object]:
    untracked = collect_untracked(root)
    ignored = collect_ignored(root)
    modified = collect_modified(root)

    generated_untracked = [path for path in untracked if is_likely_generated_untracked(path)]
    source_untracked = [path for path in untracked if path not in generated_untracked]

    suggested_missing = [
        pattern
        for pattern in SUGGESTED_GITIGNORE_PATTERNS
        if not any(fnmatch.fnmatch(path, pattern.rstrip("/") + "*") for path in ignored)
        and any(fnmatch.fnmatch(path, pattern.rstrip("/") + "*") for path in untracked)
    ]

    return {
        "root": root.as_posix(),
        "git": {
            "modified_count": len(modified),
            "modified": modified,
            "untracked_count": len(untracked),
            "untracked_top_level_counts": top_level_counts(untracked),
            "ignored_count": len(ignored),
            "ignored_top_level_counts": top_level_counts(ignored),
        },
        "safe_junk": [asdict(item) for item in collect_safe_junk(root)],
        "runtime_state": [asdict(item) for item in collect_runtime_state(root)],
        "local_dependency_dirs": [asdict(item) for item in collect_local_dependency_dirs(root)],
        "generated_artifact_dirs": [asdict(item) for item in collect_generated_dirs(root)],
        "untracked_generated_candidates": generated_untracked,
        "untracked_review_candidates": source_untracked,
        "suggested_gitignore_additions": suggested_missing,
    }


def print_section(title: str) -> None:
    print(f"\n## {title}")


def print_items(items: list[dict[str, object]], limit: int) -> None:
    if not items:
        print("- none")
        return
    for item in items[:limit]:
        size = format_size(int(item.get("size_bytes", 0)))
        print(f"- {size:>8}  {item['path']}")
    if len(items) > limit:
        print(f"- ... {len(items) - limit} more")


def print_path_list(paths: list[str], limit: int) -> None:
    if not paths:
        print("- none")
        return
    for path in paths[:limit]:
        print(f"- {path}")
    if len(paths) > limit:
        print(f"- ... {len(paths) - limit} more")


def print_markdown(report: dict[str, object], limit: int) -> None:
    git = report["git"]
    assert isinstance(git, dict)

    print(f"# Cleanup Audit Dry Run")
    print(f"\nRoot: `{report['root']}`")
    print("\nThis report is read-only. No files were changed.")

    print_section("Git State")
    print(f"- modified entries: {git['modified_count']}")
    print(f"- untracked entries: {git['untracked_count']}")
    print(f"- ignored local entries: {git['ignored_count']}")
    print("- untracked top-level counts:")
    for name, count in dict(git["untracked_top_level_counts"]).items():
        print(f"  - {name}: {count}")

    print_section("Safe Junk Candidates")
    print_items(report["safe_junk"], limit)

    print_section("Runtime State Candidates")
    print("Keep or archive these before deleting if dispatcher recovery state matters.")
    print_items(report["runtime_state"], limit)

    print_section("Local Dependency Directories")
    dependency_dirs = report["local_dependency_dirs"]
    if not dependency_dirs:
        print("- none")
    else:
        for item in dependency_dirs[:limit]:
            size = format_size(int(item["size_bytes"]))
            print(f"- {size:>8}  {item['path']}  ({item['file_count']} files)")
        if len(dependency_dirs) > limit:
            print(f"- ... {len(dependency_dirs) - limit} more")

    print_section("Generated Artifact Directories")
    generated_dirs = report["generated_artifact_dirs"]
    if not generated_dirs:
        print("- none")
    else:
        for item in generated_dirs[:limit]:
            size = format_size(int(item["size_bytes"]))
            print(f"- {size:>8}  {item['path']}  ({item['file_count']} files)")
        if len(generated_dirs) > limit:
            print(f"- ... {len(generated_dirs) - limit} more")

    print_section("Untracked Generated Candidates")
    print_path_list(report["untracked_generated_candidates"], limit)

    print_section("Untracked Review Candidates")
    print("Review these manually: some may be source, docs, skills, or config.")
    print_path_list(report["untracked_review_candidates"], limit)

    print_section("Suggested .gitignore Additions")
    print_path_list(report["suggested_gitignore_additions"], limit)

    print_section("Next Commands To Review")
    print("```bash")
    print("# Re-run this audit")
    print("python3 tools/cleanup_audit.py")
    print("")
    print("# Inspect only git noise")
    print("git status --short")
    print("git ls-files --others --exclude-standard")
    print("")
    print("# Inspect large generated directories")
    print("du -sh tk_toolkit_dual/workspace_ryan/* first_last_video_work shot_video_work storyboard_video_work 2>/dev/null | sort -h")
    print("```")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dry-run cleanup audit for the workspace.")
    parser.add_argument(
        "root",
        nargs="?",
        default=".",
        help="Workspace root to audit. Defaults to current directory.",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON instead of Markdown.")
    parser.add_argument("--limit", type=int, default=40, help="Maximum rows per section.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    report = build_report(root)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print_markdown(report, args.limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
