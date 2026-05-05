# UGC 独立表组创建记录（2026-04-29）

Base：`TK爆款共性生视频全流程`
Base Token：`Zgzqbp71zaFXgOs94l4c0nlVnef`

## 创建结果

| 表名 | table_id | 字段数 | 说明 |
|---|---|---:|---|
| UGC-01 视频输入与分析表 | `tblDy0xA6nDVgyUW` | 18 | 用户入口：视频链接/文件、新产品、目标市场、UGC分析结果 |
| UGC-02 脚本批次表 | `tblOQAq5r12NOPv4` | 12 | 一次分析结果派生 N 条脚本的母批次 |
| UGC-03 脚本版本表 | `tblvJ3tVA4GUknPY` | 16 | 每条脚本版本任务 |
| UGC-04 6宫格分镜表 | `tblDqM0YCFIlvcWx` | 8 | 入选脚本生成一张 6 宫格分镜图 |
| UGC-05 分镜图片表 | `tbl6uwwsXeIt8FB2` | 10 | 6 宫格裁切后的单张分镜图与高清化结果 |
| UGC-06 分镜视频表 | `tblWmmrAYS0jwKig` | 13 | 每张分镜图生成一条分镜视频 |
| UGC-07 成片合成表 | `tblZJApmI81NhQtu` | 9 | 同一脚本下所有分镜视频的 FFmpeg 合成任务 |

## 关联关系

- `UGC-02 脚本批次表.来源分析记录` → `UGC-01 视频输入与分析表`
- `UGC-03 脚本版本表.所属批次` → `UGC-02 脚本批次表`
- `UGC-03 脚本版本表.来源分析记录` → `UGC-01 视频输入与分析表`
- `UGC-04 6宫格分镜表.关联脚本版本` → `UGC-03 脚本版本表`
- `UGC-05 分镜图片表.关联6宫格任务` → `UGC-04 6宫格分镜表`
- `UGC-05 分镜图片表.关联脚本版本` → `UGC-03 脚本版本表`
- `UGC-06 分镜视频表.关联分镜图片` → `UGC-05 分镜图片表`
- `UGC-06 分镜视频表.关联脚本版本` → `UGC-03 脚本版本表`
- `UGC-07 成片合成表.关联脚本版本` → `UGC-03 脚本版本表`

## 本地记录文件

- 表 ID：`docs/archive/wrong-ugc-base-2026-04-29/ugc-base-table-ids-2026-04-29.json`
- 字段结构快照：`docs/archive/wrong-ugc-base-2026-04-29/ugc-base-fields-2026-04-29.json`
- 建表脚本：`scripts/create_ugc_base_tables.py`

## 注意

- 本次只创建了独立 UGC 表组，没有修改旧 `tk_toolkit_dual` 表和代码。
- 字段类型以稳定可写为优先：文本、数字、单选、附件、关联。
- 复杂 lookup / formula 暂未创建，后续可在真实跑通后按需要补充，避免早期字段依赖过重。
