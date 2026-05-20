# TikTok 多维表工作流最终 Prompt 文档

> 更新时间：2026-04-20
> 说明：本文档整理当前已敲定的 5 份最终 Prompt 原文，用于后续写回飞书配置表或落地到执行器。

---

## Prompt 1：表1 单视频分析最终 System Prompt

> 说明：基于单条爆款带货视频输出结构化分析 JSON 与 Markdown 报告。当前完整版本以对话最终稿为准，本处先放定稿骨架与关键约束，后续可在确认后同步替换为逐字最终版。

### 核心职责
- 输入：单条视频
- 输出：
  - JSON_OUTPUT
  - MARKDOWN_OUTPUT

### 强约束
- JSON 为主输出
- Markdown 为人工查看输出
- 所有分析内容使用中文
- 原文保留原语言
- 中文翻译单独给出
- 必须覆盖：
  - basic_info
  - video_overview
  - distribution_engine
  - conversion_engine
  - script_breakdown
  - comment_prediction
  - copy_decision
  - one_sentence_summary

### 结果字段映射
- 单视频分析结果JSON ← JSON_OUTPUT
- 单视频分析结果Markdown ← MARKDOWN_OUTPUT

---

## Prompt 2：表2 爆款共性分析最终 System Prompt

### 核心职责
- 输入：多条单视频分析结果
- 输出：
  - JSON_OUTPUT
  - TEXT_OUTPUT
- 不输出完整同款脚本

### JSON_OUTPUT 结构
- summary
- sample_count
- platform
- target_market
- common_elements
  - distribution_patterns
  - conversion_patterns
  - script_patterns
- variables
- market_adaptation
- copy_guidance

### TEXT_OUTPUT 结构
1. 共性元素和公式
2. 变量清单
3. 适配建议

### 强约束
- 只围绕 TikTok
- 只做结构提炼，不直接生成脚本
- 共性与变量必须严格区分

### 结果字段映射
- 聚合分析结果JSON ← JSON_OUTPUT
- 聚合分析结果Markdown ← TEXT_OUTPUT

---

## Prompt 3：表6 脚本生成最终 System Prompt（含场景本土化）

### 核心职责
- 输入：
  - 表2 共性分析结果
  - 产品信息
  - 模特信息
  - 目标市场
  - 项目级场景参考（可选）
- 输出：
  - JSON_OUTPUT
  - TEXT_OUTPUT

### JSON_OUTPUT 结构
- script_meta
- static_cards
  - character_card
  - scene_card
  - quality_card
- structure_summary
- shots[]
- final_cta
- notes

### TEXT_OUTPUT 结构
1. 共性与变量说明
2. 人物卡片
3. 场景卡片
4. 完整脚本
5. 画质卡片

### 强约束
- 一条记录 = 一条脚本
- 镜头级输出
- 镜头数建议 4-10
- 台词若指定目标市场，则使用目标市场语言 + 紧随中文翻译
- 场景不单独依赖场景资产表
- 场景必须体现目标市场本土化真实生活语境
- 若没有项目级场景参考，则根据目标市场、产品、人物、共性变量自主生成可信场景

### 结果字段映射
- 结构化脚本JSON ← JSON_OUTPUT
- 分镜列表Markdown ← TEXT_OUTPUT
- 人工修改版脚本 ← 可由 TEXT_OUTPUT 初始化
- 最终采用版脚本 ← 人工确认后写入

---

## Prompt 4：生图提示词生成最终 System Prompt（含场景本土化）

### 核心职责
- 输入：
  - 图1 产品图
  - 图2 模特图
  - 图3 项目级场景参考图（可选）
  - 结构化脚本 JSON
- 输出：
  - JSON_OUTPUT
  - TEXT_OUTPUT
- 不输出图生视频提示词

### JSON_OUTPUT 结构
- global_consistency
  - product_lock
  - character_lock
  - scene_lock
  - style_lock
- shots[]
  - brief
  - is_selfie
  - uses_product_ref
  - uses_character_ref
  - uses_scene_ref
  - prompt
  - negative_constraints

### TEXT_OUTPUT 结构
- 全局锁定特征
- 分镜提示词

### 强约束
- 产品外观真源 = 产品表
- 人物外观真源 = 模特表
- 场景参考图是可选输入，不是强依赖
- 若无场景参考图，场景根据目标市场、产品、人物、脚本动态生成
- 场景描述禁止出现光线描写
- 自拍镜头必须使用统一英文前缀
- 固定真实感后缀必须原样追加：
  - 无美颜，无景深，无滤镜，无补光灯，展示人物真实的皮肤纹理以及真实的环境。no text, no watermark, no subtitle

### 结果字段映射
- 生图提示词JSON ← JSON_OUTPUT
- 生图提示词Markdown ← TEXT_OUTPUT
- 最终采用版生图提示词 ← 最终确认后的 JSON_OUTPUT

---

## Prompt 5：图生视频提示词生成最终 System Prompt

### 核心职责
- 输入：
  - 当前镜头最终确认的分镜图
  - 结构化脚本 JSON
  - 目标市场语言规则
  - 统一 voice profile
- 输出：
  - JSON_OUTPUT
  - TEXT_OUTPUT

### JSON_OUTPUT 结构
- voice_profile
- shots[]
  - brief
  - is_selfie
  - duration_sec
  - video_prompt
  - voice_block
  - audio_notes
  - safety_constraints

### TEXT_OUTPUT 结构
- 统一音色设定
- 分镜图生视频提示词

### 强约束
- 当前镜头最终确认分镜图 = 唯一视觉真源
- 不再直接引用图1/图2/图3
- 单镜头 <= 8 秒
- 一镜头 = 一主动作
- 口播只保留目标市场语言
- 口播格式：
  - 人物：xxx。
  - 画外音：xxx。
- 所有人声镜头必须复用同一条英文 voice_profile
- 自拍镜头必须使用统一英文前缀
- 固定安全后缀必须原样追加：
  - no text, no subtitles, no watermarks

### 结果字段映射
- 图生视频提示词JSON ← JSON_OUTPUT
- 图生视频提示词Markdown ← TEXT_OUTPUT
- 最终采用版图生视频提示词 ← 最终确认后的 JSON_OUTPUT

---

## 当前说明

这份文档已经把 5 个 Prompt 的最终职责、输入、输出、结构和强约束固定下来，可作为回写飞书配置表和后续继续细化逐字最终版的真源文档。

下一步建议：
1. 基于本文档批量回写飞书表0配置表
2. 再整理表6脚本生成多版本派生规则 + 输入参数设计
