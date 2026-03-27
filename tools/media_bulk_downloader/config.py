from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_BASE_URL = "https://api.meowload.net"


@dataclass
class AppConfig:
    api_key: str
    base_url: str = DEFAULT_BASE_URL
    timeout_seconds: int = 30
    retry_count: int = 3
    concurrency: int = 3
    output_dir: Path = Path("downloads")


def load_env_file(env_path: Path) -> None:
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def load_config(env_path: Path | None = None) -> AppConfig:
    if env_path:
        load_env_file(env_path)

    api_key = os.environ.get("HHM_API_KEY", "").strip()
    if not api_key:
        raise ValueError("Missing HHM_API_KEY. Put it in .env or export it before running.")

    base_url = os.environ.get("HHM_BASE_URL", DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL
    timeout_seconds = int(os.environ.get("HHM_TIMEOUT_SECONDS", "30"))
    retry_count = int(os.environ.get("HHM_RETRY_COUNT", "3"))
    concurrency = int(os.environ.get("HHM_CONCURRENCY", "3"))
    output_dir = Path(os.environ.get("HHM_OUTPUT_DIR", "downloads"))

    return AppConfig(
        api_key=api_key,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
        retry_count=retry_count,
        concurrency=concurrency,
        output_dir=output_dir,
    )
