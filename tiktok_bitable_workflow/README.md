# TikTok Bitable Workflow — 独立新项目

> 状态：开发中  
> 边界：不挂接旧 tkpipeline / tk_toolkit_dual，独立执行。

## 项目目标

围绕 TikTok 多维表工作流，独立实现：
- 多版本脚本批次规划（variant_plan）
- 单版本脚本生成（script_generate）
- 后续分镜 / 生图 / 视频提示词阶段

## 当前文件结构

```
tiktok_bitable_workflow/
  README.md
  config.example.json          # 配置模板，复制为 config.json
  common.py                    # 公共函数（占位，供后续各阶段复用）
  dispatcher.py                # 独立轮询调度器（已可运行）
  stages/
    __init__.py
    variant_plan.py            # 阶段1：多版本批次规划（已可运行）
    script_generate.py         # 阶段2：单版本脚本生成（已可运行）
  schemas/
    script_multivariant_protocol.example.json
```

## 运行前提

1. 复制 `config.example.json` → `config.json`，填入飞书 app_id / app_secret / bitable_app_token / table IDs / LLM 配置
2. 确保飞书多维表已按 `docs/tiktok-bitable-table6-field-spec.md` 补好字段
3. 确认飞书配置表中有"脚本生成"环节的提示词记录

## 运行方式

```bash
# 单独测试 variant_plan
python3 tiktok_bitable_workflow/stages/variant_plan.py <parent_record_id>

# 单独测试 script_generate
python3 tiktok_bitable_workflow/stages/script_generate.py <version_task_record_id>

# 启动 dispatcher（持续轮询）
python3 tiktok_bitable_workflow/dispatcher.py
```

## dispatcher 状态触发规则

- `多版本规划状态 = 待规划` + `记录角色 = 批次母任务` → 触发 variant_plan
- `脚本生成状态 = 待生成` + `记录角色 = 版本任务` → 触发 script_generate

## 表结构假设

当前代码假设表字段如下（需在飞书多维表中确认或调整）：

**批次母任务**（触发 variant_plan）：
- 记录角色
- 多版本规划状态
- 项目ID / 项目名称
- 共性分析记录ID
- 产品关联 / 产品ID / 产品名称
- 模特关联 / 模特ID / 模特名称
- 目标市场
- 场景参考图 / 场景参考说明
- 脚本生成模式 / 目标版本数 / 测试维度 / 派生策略 / 版本差异强度 / 脚本总时长目标

**版本任务**（触发 script_generate，包含母任务全部字段 plus）：
- 父任务ID / 批次ID
- 版本编号 / 版本名称
- 主测试点 / 次测试点 / 版本差异说明
- 锁定项说明 / 变量位说明 / 共性骨架摘要
- 脚本生成状态 / 生成的脚本 / 结构化脚本JSON
- 下游推进状态 / 是否入选 / 版本差异自检结果

## 与旧 tkpipeline 的关系

仅作经验参考：
- 不共用目录
- 不共用脚本
- 不共用 dispatcher
- 不共用状态字段命名
- 不修改旧 tk_toolkit_dual 任何代码