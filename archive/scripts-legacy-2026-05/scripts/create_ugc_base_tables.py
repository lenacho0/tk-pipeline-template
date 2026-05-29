#!/usr/bin/env python3
"""
Create independent UGC workflow tables in existing TikTok Bitable Base.
Uses lark-cli shortcut commands, serially, with idempotent same-name checks.
"""
import json
import subprocess
import sys
from pathlib import Path

BASE_TOKEN = "Zgzqbp71zaFXgOs94l4c0nlVnef"
OUT_PATH = Path("docs/archive/wrong-ugc-base-2026-04-29/ugc-base-table-ids-2026-04-29.json")


def opt(name, hue="Blue", lightness="Lighter"):
    return {"name": name, "hue": hue, "lightness": lightness}


def text(name, url=False):
    d = {"name": name, "type": "text"}
    if url:
        d["style"] = {"type": "url"}
    return d


def long_text(name):
    # lark shortcut uses text; long text will be handled as text in API if no rich text type exposed.
    return {"name": name, "type": "text"}


def number(name):
    return {"name": name, "type": "number", "style": {"type": "plain", "precision": 0, "percentage": False, "thousands_separator": False}}


def attachment(name):
    return {"name": name, "type": "attachment"}


def select(name, options):
    return {"name": name, "type": "select", "multiple": False, "options": options}


def link(name, table_id):
    return {"name": name, "type": "link", "link_table": table_id, "bidirectional": False}


TABLE_SPECS = [
    {
        "key": "ugc_01_analysis",
        "name": "UGC-01 视频输入与分析表",
        "fields": [
            text("任务名称"),
            select("视频来源类型", [opt("视频链接"), opt("视频文件"), opt("链接+文件"), opt("缺失", "Red")]),
            text("视频链接", url=True),
            attachment("视频文件"),
            text("本地视频路径"),
            select("下载状态", [opt("无需下载", "Gray"), opt("待下载"), opt("下载中", "Orange"), opt("下载成功", "Green"), opt("下载失败", "Red")]),
            long_text("下载错误信息"),
            text("用户新产品"),
            text("目标市场"),
            select("视频类型", [opt("UGC"), opt("非UGC", "Gray")]),
            select("分析状态", [opt("待分析"), opt("分析中", "Orange"), opt("分析成功", "Green"), opt("分析失败", "Red")]),
            long_text("分析结果JSON"),
            long_text("分析结果Markdown"),
            long_text("分析摘要"),
            number("目标脚本数量"),
            select("脚本派生状态", [opt("未派生", "Gray"), opt("待派生"), opt("派生中", "Orange"), opt("已派生", "Green"), opt("派生失败", "Red")]),
            text("脚本批次ID"),
            long_text("备注"),
        ],
    },
    {
        "key": "ugc_02_script_batch",
        "name": "UGC-02 脚本批次表",
        "fields": [
            text("批次ID"),
            # link to UGC-01 added after creation
            text("用户新产品"),
            text("目标市场"),
            number("目标脚本数量"),
            long_text("分析handoff JSON"),
            long_text("必须保留"),
            long_text("可替换项"),
            long_text("UGC风格要求"),
            select("多版本规划状态", [opt("待规划"), opt("规划中", "Orange"), opt("已规划", "Green"), opt("失败", "Red")]),
            number("版本任务数量"),
            long_text("备注"),
        ],
    },
    {
        "key": "ugc_03_script_version",
        "name": "UGC-03 脚本版本表",
        "fields": [
            text("版本ID"),
            # links added after creation
            text("版本名称"),
            select("主测试点", [opt("hook_angle"), opt("pain_point_moment"), opt("scene_entry"), opt("trust_builder"), opt("cta_style"), opt("standard", "Gray")]),
            long_text("版本差异说明"),
            long_text("锁定项说明"),
            long_text("变量位说明"),
            text("用户新产品"),
            text("目标市场"),
            select("脚本生成状态", [opt("待生成"), opt("生成中", "Orange"), opt("生成成功", "Green"), opt("生成失败", "Red")]),
            long_text("生成的脚本"),
            long_text("结构化脚本JSON"),
            select("是否入选", [opt("待定", "Gray"), opt("入选", "Green"), opt("不入选", "Red")]),
            select("下游推进状态", [opt("未推进", "Gray"), opt("待6宫格分镜"), opt("分镜中", "Orange"), opt("已完成", "Green")]),
            long_text("错误信息"),
        ],
    },
    {
        "key": "ugc_04_six_grid_storyboard",
        "name": "UGC-04 6宫格分镜表",
        "fields": [
            text("分镜任务ID"),
            # link added after creation
            long_text("结构化脚本JSON"),
            long_text("6宫格提示词JSON"),
            select("6宫格生成状态", [opt("待生成"), opt("生成中", "Orange"), opt("成功", "Green"), opt("失败", "Red")]),
            attachment("6宫格图片"),
            select("布局", [opt("3行x2列"), opt("2行x3列")]),
            long_text("错误信息"),
        ],
    },
    {
        "key": "ugc_05_shot_images",
        "name": "UGC-05 分镜图片表",
        "fields": [
            text("分镜图片ID"),
            # links added after creation
            number("分镜序号"),
            long_text("对应脚本片段JSON"),
            select("裁切状态", [opt("待裁切"), opt("裁切中", "Orange"), opt("成功", "Green"), opt("失败", "Red")]),
            attachment("原始裁切图片"),
            select("高清化状态", [opt("待高清化"), opt("高清化中", "Orange"), opt("成功", "Green"), opt("失败", "Red")]),
            attachment("高清分镜图"),
            long_text("错误信息"),
        ],
    },
    {
        "key": "ugc_06_shot_videos",
        "name": "UGC-06 分镜视频表",
        "fields": [
            text("分镜视频ID"),
            # links added after creation
            number("分镜序号"),
            attachment("高清分镜图"),
            long_text("对应脚本片段JSON"),
            long_text("图生视频提示词"),
            select("提示词生成状态", [opt("待生成"), opt("生成中", "Orange"), opt("成功", "Green"), opt("失败", "Red")]),
            text("视频生成模型"),
            select("视频生成状态", [opt("待生成"), opt("生成中", "Orange"), opt("成功", "Green"), opt("失败", "Red")]),
            attachment("分镜视频"),
            text("本地视频路径"),
            long_text("错误信息"),
        ],
    },
    {
        "key": "ugc_07_final_concat",
        "name": "UGC-07 成片合成表",
        "fields": [
            text("成片任务ID"),
            # link added after creation
            number("分镜视频数量"),
            number("已完成分镜视频数量"),
            select("合成状态", [opt("待合成"), opt("合成中", "Orange"), opt("成功", "Green"), opt("失败", "Red")]),
            long_text("FFmpeg concat list"),
            attachment("成片视频"),
            text("本地成片路径"),
            long_text("错误信息"),
        ],
    },
]


def run(args):
    print("$", " ".join(args), flush=True)
    p = subprocess.run(args, text=True, capture_output=True)
    if p.stdout:
        print(p.stdout, flush=True)
    if p.stderr:
        print(p.stderr, file=sys.stderr, flush=True)
    if p.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(args)}")
    return json.loads(p.stdout)


def list_tables():
    data = run(["lark-cli", "base", "+table-list", "--base-token", BASE_TOKEN, "--limit", "200"])
    return {t["name"]: t["id"] for t in data["data"]["tables"]}


def create_table(name, fields):
    payload = json.dumps(fields, ensure_ascii=False)
    data = run(["lark-cli", "base", "+table-create", "--base-token", BASE_TOKEN, "--name", name, "--fields", payload])
    table = data["data"]["table"]
    return table["id"]


def create_field(table_id, field):
    payload = json.dumps(field, ensure_ascii=False)
    return run(["lark-cli", "base", "+field-create", "--base-token", BASE_TOKEN, "--table-id", table_id, "--json", payload])


def main():
    existing = list_tables()
    ids = {}
    for spec in TABLE_SPECS:
        name = spec["name"]
        if name in existing:
            print(f"SKIP existing table: {name} {existing[name]}")
            ids[spec["key"]] = existing[name]
            continue
        table_id = create_table(name, spec["fields"])
        print(f"CREATED table: {name} {table_id}")
        ids[spec["key"]] = table_id

    # Add link fields after all target tables exist.
    link_specs = [
        ("ugc_02_script_batch", link("来源分析记录", ids["ugc_01_analysis"])),
        ("ugc_03_script_version", link("所属批次", ids["ugc_02_script_batch"])),
        ("ugc_03_script_version", link("来源分析记录", ids["ugc_01_analysis"])),
        ("ugc_04_six_grid_storyboard", link("关联脚本版本", ids["ugc_03_script_version"])),
        ("ugc_05_shot_images", link("关联6宫格任务", ids["ugc_04_six_grid_storyboard"])),
        ("ugc_05_shot_images", link("关联脚本版本", ids["ugc_03_script_version"])),
        ("ugc_06_shot_videos", link("关联分镜图片", ids["ugc_05_shot_images"])),
        ("ugc_06_shot_videos", link("关联脚本版本", ids["ugc_03_script_version"])),
        ("ugc_07_final_concat", link("关联脚本版本", ids["ugc_03_script_version"])),
    ]
    for table_key, field in link_specs:
        try:
            create_field(ids[table_key], field)
            print(f"CREATED link field: {table_key}.{field['name']}")
        except Exception as e:
            print(f"WARN link field failed: {table_key}.{field['name']} error={e}", file=sys.stderr)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(ids, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"WROTE {OUT_PATH}")


if __name__ == "__main__":
    main()
