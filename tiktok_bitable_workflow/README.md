# TikTok Bitable Workflow

独立新项目。

## 目标

围绕 TikTok 多维表工作流，独立实现：
- 多版本脚本批次规划
- 单版本脚本生成
- 后续分镜 / 生图 / 视频提示词阶段

## 当前原则

- 不挂接旧 `tk_toolkit_dual`
- 不复用旧 dispatcher 作为正式入口
- 旧项目仅作经验参考

## 当前骨架

- `common.py`：基础配置 / 飞书 API / 工具函数
- `config.example.json`：独立项目配置模板
- `dispatcher.py`：独立调度入口（占位）
- `stages/variant_plan.py`：多版本批次规划
- `stages/script_generate.py`：单版本脚本生成
- `schemas/script_multivariant_protocol.example.json`：协议示例

## 当前状态

这是第一版项目骨架，先把独立目录和关键阶段入口立起来，避免继续和旧 tkpipeline 混线。
