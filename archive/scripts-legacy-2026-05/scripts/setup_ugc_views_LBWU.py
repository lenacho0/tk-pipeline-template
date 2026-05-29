#!/usr/bin/env python3
"""Create UGC user/review/debug views and set visible fields in LBWU Base."""
import json
import subprocess
import sys
from pathlib import Path

BASE = "LBWUbgRfEavAgjsXNIhcpo0Dnvb"
IDS = json.loads(Path("docs/ugc/base/ugc-base-table-ids-LBWU-2026-04-29.json").read_text(encoding="utf-8"))
OUT = Path("docs/ugc/base/ugc-base-views-LBWU-2026-04-29.json")

VIEW_SPECS = {
    "ugc_01_analysis": [
        ("01-用户填写入口", [
            "任务名称", "视频来源类型", "视频链接", "视频文件", "关联产品", "目标市场", "目标脚本数量", "分析状态", "脚本派生状态"
        ]),
        ("02-分析结果审核", [
            "任务名称", "关联产品", "目标市场", "分析状态", "分析摘要", "分析结果Markdown", "目标脚本数量", "脚本派生状态", "备注"
        ]),
        ("99-系统调试全字段", None),
    ],
    "ugc_02_script_batch": [
        ("01-批次查看", [
            "批次ID", "来源分析记录", "关联产品", "目标市场", "目标脚本数量", "多版本规划状态", "版本任务数量", "备注"
        ]),
        ("99-系统调试全字段", None),
    ],
    "ugc_03_script_version": [
        ("01-脚本审核选择", [
            "版本ID", "版本名称", "主测试点", "版本差异说明", "关联产品", "目标市场", "脚本生成状态", "生成的脚本", "是否入选", "下游推进状态", "错误信息"
        ]),
        ("99-系统调试全字段", None),
    ],
    "ugc_04_six_grid_storyboard": [
        ("01-6宫格结果查看", [
            "分镜任务ID", "关联脚本版本", "6宫格生成状态", "6宫格图片", "布局", "错误信息"
        ]),
        ("99-系统调试全字段", None),
    ],
    "ugc_05_shot_images": [
        ("01-分镜图片结果查看", [
            "分镜图片ID", "关联脚本版本", "关联6宫格任务", "分镜序号", "裁切状态", "原始裁切图片", "高清化状态", "高清分镜图", "错误信息"
        ]),
        ("99-系统调试全字段", None),
    ],
    "ugc_06_shot_videos": [
        ("01-分镜视频结果查看", [
            "分镜视频ID", "关联脚本版本", "关联分镜图片", "分镜序号", "提示词生成状态", "视频生成模型", "视频生成状态", "分镜视频", "本地视频路径", "错误信息"
        ]),
        ("99-系统调试全字段", None),
    ],
    "ugc_07_final_concat": [
        ("01-成片结果查看", [
            "成片任务ID", "关联脚本版本", "分镜视频数量", "已完成分镜视频数量", "合成状态", "成片视频", "本地成片路径", "错误信息"
        ]),
        ("99-系统调试全字段", None),
    ],
}


def run(args):
    print("$", " ".join(args), flush=True)
    p = subprocess.run(args, text=True, capture_output=True)
    if p.stdout:
        print(p.stdout, flush=True)
    if p.stderr:
        print(p.stderr, file=sys.stderr, flush=True)
    data = json.loads(p.stdout) if p.stdout.strip() else {}
    if p.returncode != 0:
        err = data.get("error", {}) if isinstance(data, dict) else {}
        if err.get("code") == 800070003 or "no operation produced" in json.dumps(err, ensure_ascii=False):
            print("NOOP treated as success", flush=True)
            return data
        raise RuntimeError(f"command failed: {' '.join(args)}")
    return data


def list_views(table_id):
    data = run(["lark-cli", "base", "+view-list", "--base-token", BASE, "--table-id", table_id, "--limit", "100"])
    return {v["name"]: v["id"] for v in data["data"].get("views", [])}


def list_fields(table_id):
    data = run(["lark-cli", "base", "+field-list", "--base-token", BASE, "--table-id", table_id, "--limit", "200"])
    return [f["name"] for f in data["data"].get("fields", [])]


def create_view(table_id, name):
    data = run(["lark-cli", "base", "+view-create", "--base-token", BASE, "--table-id", table_id, "--json", json.dumps({"name": name, "type": "grid"}, ensure_ascii=False)])
    views = data["data"].get("views", [])
    if not views:
        raise RuntimeError(f"view-create returned no views for {name}")
    return views[0]["id"]


def set_visible(table_id, view_id, visible_fields):
    body = json.dumps({"visible_fields": visible_fields}, ensure_ascii=False)
    return run(["lark-cli", "base", "+view-set-visible-fields", "--base-token", BASE, "--table-id", table_id, "--view-id", view_id, "--json", body])


def main():
    result = {}
    for key, specs in VIEW_SPECS.items():
        table_id = IDS[key]
        existing_views = list_views(table_id)
        all_fields = list_fields(table_id)
        result[key] = {"table_id": table_id, "views": {}}
        for view_name, visible in specs:
            view_id = existing_views.get(view_name)
            if view_id:
                print(f"SKIP existing view {key}.{view_name} {view_id}")
            else:
                view_id = create_view(table_id, view_name)
                print(f"CREATED view {key}.{view_name} {view_id}")
            if visible is None:
                visible_fields = all_fields
            else:
                missing = [f for f in visible if f not in all_fields]
                if missing:
                    print(f"WARN missing fields for {key}.{view_name}: {missing}", file=sys.stderr)
                visible_fields = [f for f in visible if f in all_fields]
            set_visible(table_id, view_id, visible_fields)
            result[key]["views"][view_name] = {"view_id": view_id, "visible_fields": visible_fields}
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"WROTE {OUT}")

if __name__ == "__main__":
    main()
