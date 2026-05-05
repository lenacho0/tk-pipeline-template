from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

UGC_BASE_TOKEN = "LBWUbgRfEavAgjsXNIhcpo0Dnvb"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
TABLE_IDS_PATH = PROJECT_ROOT / "docs" / "ugc" / "base" / "ugc-base-table-ids-LBWU-2026-04-29.json"
LEGACY_TABLE_IDS_PATH = PROJECT_ROOT / "docs" / "ugc-base-table-ids-LBWU-2026-04-29.json"

REQUIRED_UGC_TABLE_KEYS = [
    "ugc_01_analysis",
    "ugc_02_script_batch",
    "ugc_03_script_version",
    "ugc_04_six_grid_storyboard",
    "ugc_05_shot_images",
    "ugc_06_shot_videos",
    "ugc_07_final_concat",
]


def load_ugc_table_ids(path: Path = TABLE_IDS_PATH) -> Dict[str, str]:
    resolved_path = path
    if not resolved_path.exists() and path == TABLE_IDS_PATH and LEGACY_TABLE_IDS_PATH.exists():
        resolved_path = LEGACY_TABLE_IDS_PATH
    data = json.loads(resolved_path.read_text(encoding="utf-8"))
    missing = [key for key in REQUIRED_UGC_TABLE_KEYS if not data.get(key)]
    if missing:
        raise ValueError(f"Missing UGC table ids: {missing}")
    return data
