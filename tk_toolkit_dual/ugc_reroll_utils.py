#!/usr/bin/env python3
from __future__ import annotations

from typing import Any, Dict, Iterable


def make_group_id(stage: str, source_record_id: str) -> str:
    stage_key = stage.strip().upper()
    if stage_key == "GRID":
        prefix = "UGC-GRID-GROUP"
    elif stage_key == "VIDEO":
        prefix = "UGC-VIDEO-GROUP"
    else:
        raise ValueError(f"unsupported reroll stage: {stage}")
    return f"{prefix}-{source_record_id[-8:]}"


def coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return default


def next_candidate_index(records: Iterable[Dict[str, Any]]) -> int:
    max_seen = 0
    for record in records:
        fields = record.get("fields") if isinstance(record, dict) else {}
        max_seen = max(max_seen, coerce_int((fields or {}).get("候选序号"), 0))
    return max_seen + 1


def build_candidate_fields(
    group_id: str,
    candidate_index: int,
    *,
    source_record_id: str = "",
    status: str = "候选",
) -> Dict[str, Any]:
    fields: Dict[str, Any] = {
        "重生成组ID": group_id,
        "候选序号": candidate_index,
        "候选状态": status,
    }
    if source_record_id:
        fields["重生成来源记录ID"] = source_record_id
    return fields
