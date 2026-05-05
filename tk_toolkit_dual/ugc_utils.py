from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Dict, Iterable, List


def extract_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        # Feishu URL fields are returned as {"link": "...", "text": "..."}.
        # For downstream downloads/calls the actual URL is the safest value.
        if value.get("link"):
            return str(value.get("link") or "")
        if value.get("text"):
            return str(value.get("text") or "")
        return ""
    if isinstance(value, list):
        parts: List[str] = []
        for item in value:
            if isinstance(item, dict):
                parts.append(extract_text(item))
            else:
                parts.append(str(item))
        return "".join(parts)
    return str(value)


def extract_linked_record_ids(value: Any) -> List[str]:
    ids: List[str] = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                record_ids = item.get("record_ids") or []
                ids.extend(str(record_id) for record_id in record_ids if record_id)
    return ids


def first_present(fields: Dict[str, Any], names: Iterable[str], default: Any = None) -> Any:
    """Return the first field value present in a Feishu record.

    Used during schema rename windows: code writes the new field names while
    still reading historical/legacy field names until all Base fields are
    renamed and old records are stable.
    """
    for name in names:
        if name in fields:
            return fields.get(name)
    return default


@dataclass
class DualOutput:
    json_obj: Dict[str, Any]
    markdown: str


def parse_dual_output(raw: str) -> DualOutput:
    if "JSON_OUTPUT" not in raw:
        raise ValueError("Missing JSON_OUTPUT marker")
    if "MARKDOWN_OUTPUT" not in raw:
        raise ValueError("Missing MARKDOWN_OUTPUT marker")

    json_part = raw.split("JSON_OUTPUT", 1)[1].split("MARKDOWN_OUTPUT", 1)[0].strip()
    markdown = raw.split("MARKDOWN_OUTPUT", 1)[1].strip()

    if json_part.startswith("```"):
        raise ValueError("JSON_OUTPUT must not be wrapped in markdown code fence")

    json_obj = json.loads(json_part)
    if not isinstance(json_obj, dict):
        raise ValueError("JSON_OUTPUT must be a JSON object")

    return DualOutput(json_obj=json_obj, markdown=markdown)
