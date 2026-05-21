#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
RECORD_IDS = {"recvkdsFe03R0T", "recvkdsFe042wG"}


def load_json(path: Path, default):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


def main() -> None:
    retry_path = ROOT / ".retry_state.ryan.json"
    circuit_path = ROOT / ".circuit_breakers.ryan.json"
    scan_path = ROOT / ".table_scan_state.ryan.json"
    cache_path = ROOT / ".record_state_cache.ryan.json"

    retry_state = load_json(retry_path, {})
    for key in list(retry_state.keys()):
        if any(rid in key for rid in RECORD_IDS):
            retry_state.pop(key, None)
    save_json(retry_path, retry_state)

    circuit_state = load_json(circuit_path, {})
    for key, value in circuit_state.items():
        if key.startswith("tk_shot_video.py::"):
            value["failures"] = []
            value["open_until"] = 0
    save_json(circuit_path, circuit_state)

    scan_state = load_json(scan_path, {})
    scan_state.pop("tbldPJLJhczlGzSt", None)
    save_json(scan_path, scan_state)

    cache_state = load_json(cache_path, {})
    for key in list(cache_state.keys()):
        if any(rid in key for rid in RECORD_IDS) and key.startswith("tbl"):
            cache_state.pop(key, None)
    save_json(cache_path, cache_state)


if __name__ == "__main__":
    main()
