#!/usr/bin/env python3
"""Fail fast when tracked files are unsafe for a private GitHub handoff."""
from __future__ import annotations

from dataclasses import dataclass
import argparse
import subprocess
from pathlib import Path
from typing import Iterable, List, Sequence


MEDIA_SUFFIXES = {".mp4", ".mov", ".m4v", ".avi", ".png", ".jpg", ".jpeg", ".webp", ".gif"}
TEXT_SUFFIXES = {".py", ".sh", ".md", ".txt", ".json", ".plist", ".yaml", ".yml", ".toml"}
LOCAL_PATH_MARKER = "/Users/" + "ryanlynn"
APP_SECRET_MARKER = "app_" + 'secret": "'
IGNORED_PREFIXES = (
    "archive/",
    "docs/archive/",
    "memory/",
    "tk_toolkit/",
    "tools/media_bulk_downloader/",
)
IGNORED_FILES = {"MEMORY.md"}


@dataclass(frozen=True)
class Violation:
    path: str
    message: str


def is_real_config(path: Path) -> bool:
    name = path.name
    if name == "config.json.template":
        return False
    return name == "config.json" or (name.startswith("config.") and name.endswith(".json"))


def is_env_file(path: Path) -> bool:
    return path.name == ".env"


def is_media_artifact(path: Path) -> bool:
    return path.suffix.lower() in MEDIA_SUFFIXES


def should_scan_text(path: Path) -> bool:
    return path.suffix.lower() in TEXT_SUFFIXES or path.name in {".gitignore"}


def tracked_files(root: Path) -> List[str]:
    proc = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return [item for item in proc.stdout.decode("utf-8").split("\0") if item]


def find_violations(root: Path, files: Sequence[str]) -> List[Violation]:
    violations: List[Violation] = []
    for rel in files:
        if rel in IGNORED_FILES or any(rel.startswith(prefix) for prefix in IGNORED_PREFIXES):
            continue
        rel_path = Path(rel)
        abs_path = root / rel_path
        if is_real_config(rel_path):
            violations.append(Violation(rel, "tracked real config file; keep only template configs in Git"))
        if is_env_file(rel_path):
            violations.append(Violation(rel, "tracked .env file"))
        if is_media_artifact(rel_path):
            violations.append(Violation(rel, "tracked media artifact"))
        if not abs_path.exists() or not should_scan_text(rel_path):
            continue
        try:
            text = abs_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if LOCAL_PATH_MARKER in text:
            violations.append(Violation(rel, "hard-coded local path " + LOCAL_PATH_MARKER))
        if APP_SECRET_MARKER in text and not rel.endswith("config.json.template"):
            violations.append(Violation(rel, "possible app_secret in tracked file"))
    return violations


def print_violations(violations: Iterable[Violation]) -> None:
    for item in violations:
        print(f"{item.path}: {item.message}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Check tracked files before publishing the repository")
    parser.add_argument("--root", default=".", help="repository root")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    violations = find_violations(root, tracked_files(root))
    if violations:
        print_violations(violations)
        raise SystemExit(1)
    print("release safety check passed")


if __name__ == "__main__":
    main()
