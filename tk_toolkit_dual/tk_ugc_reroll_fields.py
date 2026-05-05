#!/usr/bin/env python3
from __future__ import annotations

import json

DEPRECATED_MESSAGE = "UGC 旧候选池字段方案已废弃；飞书字段已删除。当前重生成入口为 UGC-04 的 一键重生成9宫格。"
ONE_CLICK_FIELDS = {
    "ugc04": {
        "一键重生成9宫格": 7,
        "一键重生成状态": 3,
        "一键重生成结果": 1,
    }
}


def required_fields_for_table(key: str):
    if key == "ugc04":
        return dict(ONE_CLICK_FIELDS["ugc04"])
    return {}


def missing_field_names(existing_fields, required):
    existing_names = {f.get("name") or f.get("field_name") for f in existing_fields}
    return [name for name in required if name not in existing_names]


def build_dry_run_plan(existing_by_key):
    existing = existing_by_key.get("ugc04", [])
    required = required_fields_for_table("ugc04")
    missing = missing_field_names(existing, required)
    return {
        "deprecated": DEPRECATED_MESSAGE,
        "ugc04": {
            "required": required,
            "missing": {name: required[name] for name in missing},
        },
    }


def main() -> int:
    print(json.dumps({"deprecated": DEPRECATED_MESSAGE, "required": ONE_CLICK_FIELDS}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
