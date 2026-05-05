# TikTok 多维表工作流 - 表6 脚本生成多版本派生 Prompt 输入协议

> 更新时间：2026-04-21
> 适用环节：表6 `脚本执行总表` -> 脚本生成
> 目标：把多版本派生设计落成程序可直接组织、模型可直接消费的结构化输入协议。

---

## 1. 这份协议解决什么问题

前面 B / C1 已经解决了：
- 表6 多版本派生规则
- 表6 字段规格

但如果没有一个明确的 prompt 输入协议，程序层还是会回到“拼接文本 + 临时补字段”的混乱状态。

所以 C2 的目标非常明确：

**把表6 的脚本生成输入，收成一份稳定、可扩展、可审计的结构化 schema。**

这份 schema 要同时满足：
1. 程序容易组装
2. 模型容易理解
3. 支持单版本与多版本共存
4. 支持后续继续扩展到分镜、生图、图生视频

---

## 2. 顶层原则

### 2.1 Prompt 主体不要推翻，输入层结构化增强
不是重写现有正式脚本生成 prompt，
而是给现有 prompt 增加一个更稳定的“结构化输入层”。

### 2.2 先批次，再版本
多版本生成天然有两层：
- 批次级上下文
- 版本级派生任务

所以协议必须显式区分：
- 哪些输入对整个批次共享
- 哪些输入只属于当前版本

### 2.3 让“锁定项”和“变量位”成为一等公民
过去很多 prompt 漂移，本质上是：
- 没有明确写清楚什么不能动
- 没有明确写清楚什么才允许变

因此本协议必须单独给：
- `locked_elements`
- `variable_slots`

### 2.4 版本分配必须显式
不能只告诉模型“请生成 3 个不同版本”。
必须显式告诉它：
- 当前这个版本是谁
- 主测试点是什么
- 变化方向是什么
- 不允许动什么

所以需要：
- `variant_assignment`

---

## 3. 顶层结构

建议脚本生成环节的结构化输入协议顶层如下：

```json
{
  "protocol_version": "table6_script_multivariant_v1",
  "generation_mode": "multi_variant_controlled",
  "batch_context": {},
  "shared_truth_sources": {},
  "generation_constraints": {},
  "locked_elements": {},
  "variable_slots": {},
  "variant_assignment": {},
  "output_contract": {}
}
```

说明：
- `batch_context`：这批任务共享的业务上下文
- `shared_truth_sources`：产品/人物/场景/共性分析等真源
- `generation_constraints`：生成必须遵守的硬约束
- `locked_elements`：明确锁死的内容
- `variable_slots`：明确允许变化的维度
- `variant_assignment`：当前版本的派生角色
- `output_contract`：告诉模型输出格式和字段要求

---

## 4. 顶层字段定义

### 4.1 protocol_version
- 类型：string
- 必填：是
- 建议值：`table6_script_multivariant_v1`
- 作用：后续升级协议时可兼容旧代码

### 4.2 generation_mode
- 类型：string
- 必填：是
- 建议值：
  - `single_standard`
  - `multi_variant_controlled`
  - `targeted_dimension_test`
- 作用：对应表6 的脚本生成模式

### 4.3 batch_context
- 类型：object
- 必填：是
- 作用：承接整批任务的公共上下文

### 4.4 shared_truth_sources
- 类型：object
- 必填：是
- 作用：承接产品 / 人物 / 场景 / 共性分析真源

### 4.5 generation_constraints
- 类型：object
- 必填：是
- 作用：承接硬性生成规则

### 4.6 locked_elements
- 类型：object
- 必填：是
- 作用：明确哪些内容绝对不允许偏离

### 4.7 variable_slots
- 类型：object
- 必填：是
- 作用：定义允许变化的变量位与变化边界

### 4.8 variant_assignment
- 类型：object
- 必填：是
- 作用：描述当前这个版本的测试角色

### 4.9 output_contract
- 类型：object
- 必填：是
- 作用：约束最终 JSON_OUTPUT / TEXT_OUTPUT 的格式

---

## 5. batch_context 结构

```json
{
  "batch_id": "SCRIPT-PJ001-20260421-01",
  "project_id": "PJ001",
  "project_name": "便携宠物清洁器泰国站",
  "common_analysis_record_id": "CA001",
  "product_id": "PR001",
  "product_name": "Pet Clean Roller",
  "model_id": "MD001",
  "model_name": "Nina",
  "target_market": "泰国",
  "target_language": "th",
  "script_generation_mode": "多版本受控派生",
  "target_variant_count": 3,
  "derivation_strategy": "S3 系统推荐探索",
  "testing_dimensions": ["auto"],
  "difference_level": "标准",
  "target_duration": "20-25s"
}
```

### 字段说明
- `batch_id`：同一批次唯一标识
- `project_id` / `project_name`：项目上下文
- `common_analysis_record_id`：表2 来源
- `product_id` / `model_id`：真源引用
- `target_market` / `target_language`：市场与语言
- `script_generation_mode`：保留中文业务语义，便于审计
- `target_variant_count`：本批共计划多少版本
- `derivation_strategy`：S1/S2/S3
- `testing_dimensions`：本批测试维度
- `difference_level`：保守/标准/激进
- `target_duration`：目标时长区间

---

## 6. shared_truth_sources 结构

```json
{
  "common_analysis": {
    "summary": "...",
    "recommended_reuse_mode": "B 80/20",
    "distribution_patterns": {},
    "conversion_patterns": {},
    "script_patterns": {},
    "market_adaptation": {},
    "variables": []
  },
  "product_truth": {
    "product_name": "...",
    "selling_points": [],
    "description": "...",
    "visual_truth": "来自表4，不得偏离",
    "reference_image_urls": []
  },
  "character_truth": {
    "model_name": "...",
    "persona": "...",
    "appearance_truth": "来自表5，不得偏离",
    "reference_image_urls": []
  },
  "scene_context": {
    "scene_reference_images": [],
    "scene_reference_notes": "...",
    "allow_scene_inference": true,
    "localization_requirement": "场景必须符合目标市场真实生活语境"
  }
}
```

### 说明
这一层的目标不是把所有原始信息无限堆进去，而是明确：
- 共性分析真源是什么
- 产品真源是什么
- 人物真源是什么
- 场景参考是什么

如果程序侧已有完整 JSON，可以直接塞；
如果太大，可以先摘要后塞，但必须保证“决定性规则”不丢。

---

## 7. generation_constraints 结构

```json
{
  "platform": "TikTok",
  "must_follow_common_formula": true,
  "must_preserve_conversion_path": true,
  "must_use_target_market_language": true,
  "must_include_chinese_translation": true,
  "must_reflect_localized_daily_scene": true,
  "shot_count_range": "4-10",
  "single_shot_duration_rule": "follow_common_constraints",
  "total_duration_rule": "20-25s",
  "product_must_appear_reasonably_early": true,
  "script_must_be_shot_level": true,
  "quality_card_suffix_required": "(no subtitles)",
  "forbidden_changes": [
    "不可更换产品真源",
    "不可更换人物真源",
    "不可偏离目标市场",
    "不可破坏共性脚本主骨架"
  ]
}
```

### 说明
这里放的是“全版本共享硬约束”，不是某个版本的差异点。

---

## 8. locked_elements 结构

`locked_elements` 是这份协议最关键的部分之一。

建议结构如下：

```json
{
  "product_truth_locked": true,
  "character_truth_locked": true,
  "target_market_locked": true,
  "common_formula_locked": true,
  "conversion_path_locked": true,
  "core_selling_point_locked": true,
  "duration_range_locked": true,
  "tone_persona_boundary_locked": true,
  "notes": [
    "产品外观、材质、包装结构不得偏离表4",
    "人物外貌与出镜气质不得偏离表5",
    "所有版本必须共用同一条基础转化路径",
    "所有版本必须维持同一目标市场语言和生活语境"
  ]
}
```

### 设计原则
- 尽量显式布尔化，方便程序检查
- 允许保留 `notes` 供 prompt 解释层使用

---

## 9. variable_slots 结构

建议收成“允许变化的维度 + 每个维度允许的方向”。

```json
{
  "allowed_dimensions": [
    "hook_angle",
    "scene_entry",
    "trust_builder"
  ],
  "dimension_directions": {
    "hook_angle": [
      "痛点直击",
      "结果前置",
      "认知冲突"
    ],
    "scene_entry": [
      "家庭日常切入",
      "出门前切入",
      "任务处理中切入"
    ],
    "trust_builder": [
      "个人体验",
      "可见细节证据",
      "前后对比"
    ]
  },
  "disallowed_dimensions": [
    "product_core_truth",
    "character_identity",
    "target_market",
    "main_conversion_path"
  ],
  "max_primary_dimensions_to_change": 1,
  "max_total_dimensions_to_change": 2
}
```

### 关键点
- `allowed_dimensions`：当前批次允许动哪些变量位
- `dimension_directions`：每个变量位具体允许朝哪些方向变化
- `disallowed_dimensions`：明确禁止变化的维度
- `max_primary_dimensions_to_change`：用于限制版本过于发散

---

## 10. variant_assignment 结构

这是“当前版本”的任务卡。

```json
{
  "variant_id": "V2",
  "variant_name": "V2-hook_angle-结果前置开场",
  "primary_test": "hook_angle",
  "secondary_test": null,
  "direction": "结果前置",
  "difference_goal": "通过先给出清洁结果，再回带产品露出，测试是否比痛点直击型开场更容易建立兴趣",
  "must_keep_same_as_batch": [
    "产品真源",
    "人物真源",
    "目标市场",
    "共性脚本主骨架",
    "总时长区间"
  ],
  "must_change_vs_other_variants": [
    "开场切入方式",
    "前3秒信息组织"
  ],
  "do_not_do": [
    "不要把版本差异退化成同义词替换",
    "不要改成完全不同的视频结构",
    "不要削弱产品转化路径"
  ]
}
```

### 作用
程序生成多版本时，应当：
- 为每个版本生成一份独立 `variant_assignment`
- 再逐版本调用脚本生成 prompt

而不是让模型在一次 prompt 里自由生成多个版本。

我更推荐：
**程序预创建版本记录 -> 逐版本调用生成**
而不是：
**一次 prompt 产 3 条后再拆**

前者更稳，更容易失败重试，也更容易控制差异。

---

## 11. output_contract 结构

这里用来约束输出格式，不让模型跑偏。

```json
{
  "output_format": "JSON_OUTPUT_THEN_TEXT_OUTPUT",
  "json_top_level_fields": [
    "script_meta",
    "static_cards",
    "structure_summary",
    "shots",
    "final_cta",
    "notes"
  ],
  "must_include_variant_meta": true,
  "variant_meta_fields": [
    "batch_id",
    "variant_id",
    "variant_name",
    "primary_test",
    "secondary_test",
    "direction"
  ],
  "text_output_sections": [
    "共性与变量说明",
    "人物卡片",
    "场景卡片",
    "完整脚本",
    "画质卡片"
  ],
  "language_rules": {
    "explanation_in_zh": true,
    "dialogue_in_target_language": true,
    "dialogue_zh_required": true
  }
}
```

### 建议补充
为了后续落表更稳，我建议在脚本 JSON 的 `script_meta` 里强制带上版本元信息。

例如：
```json
{
  "script_meta": {
    "batch_id": "SCRIPT-PJ001-20260421-01",
    "variant_id": "V2",
    "variant_name": "V2-hook_angle-结果前置开场",
    "primary_test": "hook_angle",
    "direction": "结果前置",
    "target_market": "泰国"
  }
}
```

这样后面即使文本脱离表，也能追溯版本身份。

---

## 12. 单版本模式的兼容写法

本协议不是只服务多版本，单版本也可以兼容。

### 单版本时建议：
- `generation_mode = single_standard`
- `target_variant_count = 1`
- `variant_assignment.variant_id = V1`
- `primary_test = standard`
- `direction = standard`
- `allowed_dimensions = []` 或最小化

这样程序就不需要维护两套完全不同的输入结构。

---

## 13. 推荐程序接线方式

## 13.1 不推荐：一次 prompt 生成全部版本
原因：
- 差异容易失控
- 一条失败拖全批
- 不利于重试
- 不利于逐条落表
- 不利于下游逐版本推进

## 13.2 推荐：分两段执行

### 第一步：批次规划
程序先读取表6 / 表2 / 表4 / 表5 / 项目表，生成：
- `batch_context`
- `shared_truth_sources`
- `generation_constraints`
- `locked_elements`
- `variable_slots`
- 多个版本的 `variant_assignment`

### 第二步：逐版本执行
对每个版本：
- 复制整批共享信息
- 替换当前版本的 `variant_assignment`
- 调用正式脚本生成 prompt
- 回写当前行结果

这条路最稳。

---

## 14. 推荐的内部数据流

建议内部数据流这样分层：

### Layer A：表字段层
来自多维表的原始字段

### Layer B：任务规范化层
程序把表字段整理成内部统一结构，例如：
- `normalized_batch_context`
- `normalized_truth_sources`
- `normalized_constraints`

### Layer C：prompt 输入协议层
整理成本文定义的最终 payload

### Layer D：prompt 文本层
把 payload + 正式脚本生成 prompt 模板拼成最终模型输入

这样后面维护起来才不会越来越乱。

---

## 15. 推荐的完整示例 payload（3版本中的 V1）

```json
{
  "protocol_version": "table6_script_multivariant_v1",
  "generation_mode": "multi_variant_controlled",
  "batch_context": {
    "batch_id": "SCRIPT-PJ001-20260421-01",
    "project_id": "PJ001",
    "project_name": "便携宠物清洁器泰国站",
    "common_analysis_record_id": "CA001",
    "product_id": "PR001",
    "product_name": "Pet Clean Roller",
    "model_id": "MD001",
    "model_name": "Nina",
    "target_market": "泰国",
    "target_language": "th",
    "script_generation_mode": "多版本受控派生",
    "target_variant_count": 3,
    "derivation_strategy": "S3 系统推荐探索",
    "testing_dimensions": ["hook_angle", "scene_entry", "trust_builder"],
    "difference_level": "标准",
    "target_duration": "20-25s"
  },
  "shared_truth_sources": {
    "common_analysis": {
      "summary": "样本共性集中在短平快痛点切入、快速露出产品、用生活化场景建立真实感，并通过自然口播推动转化。",
      "recommended_reuse_mode": "B 80/20"
    },
    "product_truth": {
      "product_name": "Pet Clean Roller",
      "selling_points": ["快速粘毛", "便携", "适合外出和家里随手用"],
      "visual_truth": "来自表4，不得偏离",
      "reference_image_urls": ["https://example.com/product.jpg"]
    },
    "character_truth": {
      "model_name": "Nina",
      "persona": "年轻、自然、像真实养宠用户",
      "appearance_truth": "来自表5，不得偏离",
      "reference_image_urls": ["https://example.com/model.jpg"]
    },
    "scene_context": {
      "scene_reference_images": [],
      "scene_reference_notes": "优先贴近泰国普通养宠用户熟悉的真实家庭空间或出门前空间",
      "allow_scene_inference": true,
      "localization_requirement": "场景必须符合目标市场真实生活语境"
    }
  },
  "generation_constraints": {
    "platform": "TikTok",
    "must_follow_common_formula": true,
    "must_preserve_conversion_path": true,
    "must_use_target_market_language": true,
    "must_include_chinese_translation": true,
    "must_reflect_localized_daily_scene": true,
    "shot_count_range": "4-10",
    "total_duration_rule": "20-25s",
    "product_must_appear_reasonably_early": true,
    "script_must_be_shot_level": true,
    "quality_card_suffix_required": "(no subtitles)"
  },
  "locked_elements": {
    "product_truth_locked": true,
    "character_truth_locked": true,
    "target_market_locked": true,
    "common_formula_locked": true,
    "conversion_path_locked": true,
    "core_selling_point_locked": true,
    "duration_range_locked": true,
    "tone_persona_boundary_locked": true,
    "notes": [
      "产品外观不得偏离表4",
      "人物外貌与气质不得偏离表5",
      "所有版本必须共用同一条基础转化路径"
    ]
  },
  "variable_slots": {
    "allowed_dimensions": ["hook_angle", "scene_entry", "trust_builder"],
    "dimension_directions": {
      "hook_angle": ["痛点直击", "结果前置", "认知冲突"],
      "scene_entry": ["家庭日常切入", "出门前切入"],
      "trust_builder": ["个人体验", "前后对比"]
    },
    "disallowed_dimensions": ["product_core_truth", "character_identity", "target_market", "main_conversion_path"],
    "max_primary_dimensions_to_change": 1,
    "max_total_dimensions_to_change": 2
  },
  "variant_assignment": {
    "variant_id": "V1",
    "variant_name": "V1-hook_angle-痛点直击开场",
    "primary_test": "hook_angle",
    "secondary_test": null,
    "direction": "痛点直击",
    "difference_goal": "用宠物毛发带来的即时困扰直接开场，测试是否比结果前置更容易抓住注意力",
    "must_keep_same_as_batch": ["产品真源", "人物真源", "目标市场", "共性脚本主骨架", "总时长区间"],
    "must_change_vs_other_variants": ["开场切入方式", "前3秒信息组织"],
    "do_not_do": ["不要退化成同义词替换", "不要变成完全不同的视频结构"]
  },
  "output_contract": {
    "output_format": "JSON_OUTPUT_THEN_TEXT_OUTPUT",
    "json_top_level_fields": ["script_meta", "static_cards", "structure_summary", "shots", "final_cta", "notes"],
    "must_include_variant_meta": true,
    "variant_meta_fields": ["batch_id", "variant_id", "variant_name", "primary_test", "secondary_test", "direction"],
    "text_output_sections": ["共性与变量说明", "人物卡片", "场景卡片", "完整脚本", "画质卡片"],
    "language_rules": {
      "explanation_in_zh": true,
      "dialogue_in_target_language": true,
      "dialogue_zh_required": true
    }
  }
}
```

---

## 16. 版本差异自检建议也结构化

既然前面已经决定要做“版本差异自检”，那我建议这一步也别写成散文，最好结构化。

可额外增加一个内部输出协议：

```json
{
  "variant_diff_check": {
    "same_backbone_confirmed": true,
    "structural_difference_confirmed": true,
    "difference_strength": "sufficient",
    "risk_of_similarity": "low",
    "deviation_from_common_analysis": "none",
    "notes": "本版本主要差异集中在 hook 与前3秒组织方式，未偏离主转化路径"
  }
}
```

这个结果可以直接写回表6 的 `版本差异自检结果` 字段。

---

## 17. 最终收口结论

### 这份协议最重要的价值
1. 把“多版本生成”从一句模糊指令，变成清晰的程序协议。
2. 把“锁定项”和“变量位”显式化，减少 prompt 漂移。
3. 把“版本分配”显式化，避免多个版本只是换词。
4. 让单版本和多版本共用同一套输入骨架，减少工程复杂度。
5. 为后续分镜/生图/图生视频的结构化接线打基础。

### 我建议下一步怎么走
最自然的下一步已经不是继续写概念文档，而是进入：

**D：把这套协议映射到实际代码接线方案**

也就是继续产出：
1. 表6 -> 协议 payload 的字段映射表
2. 预创建多版本记录的执行流程
3. 脚本生成代码的接入改造点
4. 写回表6 的回写字段顺序

如果继续往下，我建议下一份文档直接做这个：
**`docs/tiktok-bitable-table6-code-integration-plan.md`**
