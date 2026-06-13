from __future__ import annotations

import copy
import datetime as dt
import json
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, MutableMapping, Optional


SNAPSHOT_PATH = Path(__file__).resolve().parent / "view_visibility_snapshot.ryan.json"


def load_visibility_snapshot(snapshot_path: Optional[Path] = None) -> Dict[str, Any]:
    path = Path(snapshot_path or SNAPSHOT_PATH)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _snapshot_table_for_id(snapshot: Mapping[str, Any], table_id: str) -> Optional[Mapping[str, Any]]:
    tables = snapshot.get("tables") if isinstance(snapshot, Mapping) else None
    if not isinstance(tables, Mapping):
        return None
    for table in tables.values():
        if isinstance(table, Mapping) and table.get("table_id") == table_id:
            return table
    return None


def _default_uses_dict_definitions(default_views: Mapping[str, Any]) -> bool:
    return any(isinstance(value, Mapping) for value in default_views.values())


def _visible_fields_from_snapshot(view_definition: Any) -> Optional[list[str]]:
    if isinstance(view_definition, Mapping):
        fields = view_definition.get("visible_fields")
    else:
        fields = view_definition
    if not isinstance(fields, list):
        return None
    return [str(field) for field in fields]


def apply_view_visibility_snapshot(
    table_id: str,
    default_views: Mapping[str, Any],
    *,
    snapshot_path: Optional[Path] = None,
) -> Dict[str, Any]:
    snapshot = load_visibility_snapshot(snapshot_path)
    table = _snapshot_table_for_id(snapshot, table_id)
    if not table:
        return copy.deepcopy(dict(default_views))

    snapshot_views = table.get("views") if isinstance(table, Mapping) else None
    if not isinstance(snapshot_views, Mapping):
        return copy.deepcopy(dict(default_views))

    result: Dict[str, Any] = copy.deepcopy(dict(default_views))
    extra_view_as_dict = _default_uses_dict_definitions(default_views)
    for view_name, snapshot_definition in snapshot_views.items():
        visible_fields = _visible_fields_from_snapshot(snapshot_definition)
        if visible_fields is None:
            continue
        current_definition = result.get(str(view_name))
        if isinstance(current_definition, MutableMapping):
            current_definition["visible_fields"] = visible_fields
        elif current_definition is not None:
            result[str(view_name)] = visible_fields
        elif extra_view_as_dict:
            result[str(view_name)] = {"visible_fields": visible_fields}
        else:
            result[str(view_name)] = visible_fields
    return result


def build_visibility_snapshot(*, base_token: str, table_entries: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    del base_token
    tables: Dict[str, Any] = {}
    for entry in table_entries:
        table_key = str(entry.get("table_key") or "")
        table_id = str(entry.get("table_id") or "")
        if not table_key or not table_id:
            continue
        views = entry.get("views") or {}
        tables[table_key] = {
            "table_id": table_id,
            "views": copy.deepcopy(views),
        }
    return {
        "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "current ryan Base view visible fields",
        "tables": tables,
    }

