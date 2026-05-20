# UGC 分析结果 → 脚本生成环节 v1

## 1. 环节定位

本环节承接 `UGC-01 视频输入与分析表` 中的单条 UGC 爆款分析结果，将爆款视频的可复制机制迁移到入口任务选择的关联产品和目标市场，并按用户选择的目标脚本数量创建脚本批次和脚本版本任务。

本环节只使用 UGC 独立表组：

- `UGC-01 视频输入与分析表`
- `UGC-02 脚本批次表`
- `UGC-03 脚本版本表`

不使用其他项目表、不引用其他项目链路、不使用历史表编号说法。

脚本生成不从 Markdown 报告里反向抽字段，必须优先消费：

```json
JSON_OUTPUT.script_generation_handoff
```

---

## 2. 输入来源

### 2.1 UGC-01 必需输入

来自 `UGC-01 视频输入与分析表`：

| 字段 | 用途 |
|------|------|
| 视频链接 / 视频文件 | 爆款视频来源；链接需先下载，文件可直接分析 |
| 关联产品 | 用户唯一需要选择产品的位置；关联到 `初始化-产品信息` |
| 目标市场 | 用户想做的目标市场 |
| 目标脚本数量 | 用户希望生成几条脚本 |
| 分析结果JSON | UGC 单视频分析主产物 |
| 分析摘要 | 可选展示字段，来自分析 JSON 摘要 |
| 脚本派生状态 | 控制是否创建脚本批次/版本任务 |

### 2.2 分析 JSON 必需字段

来自 `UGC-01.分析结果JSON`：

- `analysis_scope = single_video`
- `video_type = UGC`
- `input_requirements.linked_product_record_id`
- `input_requirements.target_market`
- `script_generation_handoff`
- `replicable_factors`
- `ugc_authenticity`
- `risk_and_optimization`

### 2.3 产品真源

产品真源只来自：

```text
UGC-01.关联产品 → 初始化-产品信息
```

后续表如存在 `关联产品` 字段，只作为系统自动继承/只读展示字段，不要求用户重复选择。

如果后续继承字段与 `UGC-01.关联产品` 不一致，代码必须以 `UGC-01.关联产品` 为准，并记录风险。

---

## 3. UGC 脚本批次 / 脚本版本表关系

本链路使用独立 UGC 表组：

```text
UGC-01 视频输入与分析表
→ UGC-02 脚本批次表
→ UGC-03 脚本版本表
```

流转方式：

1. `UGC-01` 分析成功后，用户确认目标脚本数量。
2. 当 `UGC-01.脚本派生状态 = 待派生` 时，系统创建 1 条 `UGC-02 脚本批次表` 记录。
3. 系统根据 `UGC-01.目标脚本数量` 创建 N 条 `UGC-03 脚本版本表` 记录。
4. 每条 `UGC-03` 版本记录独立生成 1 条脚本。
5. 人工选择入选脚本后，入选脚本再进入 `UGC-04 6宫格分镜表`。

### 3.1 UGC-02 的作用

`UGC-02 脚本批次表` 是一次脚本生成批次的母记录，用于承接：

- 来源分析记录
- 关联产品继承展示
- 目标市场
- 目标脚本数量
- handoff JSON
- 必须保留项
- 可替换项
- UGC 风格要求
- 多版本规划状态

### 3.2 UGC-03 的作用

`UGC-03 脚本版本表` 是单条脚本生成任务。每条记录只生成 1 条脚本。

每条版本任务包含：

- 所属批次
- 来源分析记录
- 关联产品继承展示
- 版本 ID / 版本名称
- 主测试点
- 版本差异说明
- 锁定项说明
- 变量位说明
- 脚本生成状态
- 生成的脚本
- 结构化脚本 JSON
- 是否入选
- 下游推进状态

---

## 4. 字段使用口径

### 4.1 UGC-01 视频输入与分析表

| 字段 | 用途 |
|------|------|
| 视频来源类型 | 视频链接 / 视频文件 / 链接+文件 / 缺失 |
| 视频链接 | 用户输入链接；用于下载流程 |
| 视频文件 | 用户上传文件；可跳过下载流程 |
| 关联产品 | 用户唯一选择产品的位置，关联 `初始化-产品信息` |
| 目标市场 | 用户想做的目标市场 |
| 视频类型 | 首版固定 UGC |
| 分析状态 | 待分析 / 分析中 / 分析成功 / 分析失败 |
| 分析结果JSON | UGC 分析主产物 |
| 分析结果Markdown | 人工审阅报告 |
| 分析摘要 | 从 handoff 摘要提取 |
| 目标脚本数量 | 用户希望生成几条脚本 |
| 脚本派生状态 | 未派生 / 待派生 / 派生中 / 已派生 / 派生失败 |
| 脚本批次ID | 系统创建 UGC-02 后写回 |

### 4.2 UGC-02 脚本批次表

| 字段 | 用途 |
|------|------|
| 批次ID | 唯一批次号 |
| 来源分析记录 | 关联 `UGC-01` |
| 关联产品 | 系统从 `UGC-01.关联产品` 自动继承，只读展示 |
| 目标市场 | 从 `UGC-01` 继承 |
| 目标脚本数量 | 从 `UGC-01` 继承 |
| 分析handoff JSON | 从 `UGC-01.分析结果JSON.script_generation_handoff` 提取 |
| 必须保留 | handoff.must_preserve |
| 可替换项 | handoff.can_replace |
| UGC风格要求 | handoff.ugc_style_requirements |
| 多版本规划状态 | 待规划 / 规划中 / 已规划 / 失败 |
| 版本任务数量 | 实际创建的 UGC-03 数量 |
| 备注 | 运行记录或错误信息 |

### 4.3 UGC-03 脚本版本表

| 字段 | 用途 |
|------|------|
| 版本ID | V1 / V2 / V3 / V4 |
| 所属批次 | 关联 `UGC-02` |
| 来源分析记录 | 关联 `UGC-01` |
| 关联产品 | 系统从 `UGC-01.关联产品` 自动继承，只读展示 |
| 版本名称 | 如 `V1-Hook痛点直击版` |
| 主测试点 | 系统生成版本任务时必填。可选值：hook_angle / pain_point_moment / scene_entry / trust_builder / cta_style / standard。用户通常不需要手动填写；由系统根据目标脚本数量和 handoff 自动分配。 |
| 版本差异说明 | 本版本的明确差异 |
| 锁定项说明 | 来自 handoff.must_preserve |
| 变量位说明 | 来自 handoff.can_replace |
| 用户新产品 | 如保留旧字段，仅作展示；产品真源仍以 `关联产品` 为准 |
| 目标市场 | 从 `UGC-01` 继承 |
| 脚本生成状态 | 待生成 / 生成中 / 生成成功 / 生成失败 |
| 生成的脚本 | 人工审阅版脚本 |
| 结构化脚本JSON | 后续 6 宫格和视频环节消费 |
| 是否入选 | 待定 / 入选 / 不入选 |
| 下游推进状态 | 未推进 / 待6宫格分镜 / 分镜中 / 已完成 |
| 错误信息 | 失败原因 |

---

## 5. 多版本派生策略

首版不让模型一次性生成 N 条完整脚本，而是：

```text
UGC-02 批次母记录
→ 创建 N 条 UGC-03 版本任务
→ 每条 UGC-03 独立调用脚本生成
```

优点：

- 单条失败可单独重跑
- 每条脚本有独立差异说明
- 后续可人工选择入选脚本进入 6 宫格
- 成本和错误更容易追踪

### 5.1 默认版本差异池

这里的“测试维度”不是要求用户在入口表里手动填写，也不是说 `UGC-03.主测试点` 可以长期为空。

准确含义是：

- 用户在 `UGC-01` 入口表通常只填写 `目标脚本数量`，不需要选择每条脚本具体测试什么。
- 系统创建 `UGC-03` 版本任务时，必须给每条版本任务自动写入一个 `主测试点`。
- `主测试点` 是版本任务的生成控制字段，用来告诉脚本生成 Agent：这一版脚本主要变化哪个维度。
- 因此，`UGC-03.主测试点` 对系统生成的版本任务来说是必填字段；只是用户不需要手填。

建议默认池：

1. `hook_angle`
   - 测试不同开场钩子
   - 来源：`hook_templates`
2. `pain_point_moment`
   - 测试不同痛点场景
   - 来源：`pain_point_moment_template`
3. `scene_entry`
   - 测试不同目标市场生活场景切入
   - 来源：`can_replace` + `target_market`
4. `trust_builder`
   - 测试不同信任建立方式
   - 来源：`trust_rule` / `proof_rule`
5. `cta_style`
   - 测试软 CTA / 直接 CTA / 评论区引导
   - 来源：`cta_rule`

首版如果生成 3 条，建议默认：

- V1：Hook 痛点直击版
- V2：场景代入版
- V3：信任证明版

如果生成 4 条，再增加：

- V4：CTA / 优惠推动版

### 5.2 `standard` 选项的用途

`standard` 是系统兜底选项，不属于常规多版本差异池。

使用场景：

1. 用户只要求生成 1 条脚本时，系统可创建：
   - `版本ID = V1`
   - `主测试点 = standard`
   - `版本名称 = V1-standard-标准版`
2. UGC handoff 信息不足，无法判断应该测试哪个维度时，系统可临时使用 `standard`，并在备注/风险中说明。
3. 调试链路时，可以用 `standard` 做最小可运行脚本生成。

不建议的用法：

- 当用户要求生成多条脚本时，不应把多条都设为 `standard`。
- `standard` 不应作为用户常规手选项。
- 多版本脚本应优先使用 `hook_angle`、`pain_point_moment`、`scene_entry`、`trust_builder`、`cta_style` 形成真实差异。

---

## 6. 脚本生成 Prompt 输入块

脚本生成时，需要把 UGC handoff 整理成以下输入块：

```markdown
## UGC 单视频爆款分析 Handoff（最高优先级）

### 必须保留
{must_preserve}

### 可以替换
{can_replace}

### 可复用 Hook 模板
{hook_templates}

### 可复用脚本骨架
{script_skeleton}

### 情绪曲线
{emotional_curve}

### 痛点 moment 模板
{pain_point_moment_template}

### 产品出场规则
{product_entry_rule}

### 证明规则
{proof_rule}

### 信任建立规则
{trust_rule}

### CTA 规则
{cta_rule}

### UGC 风格要求
{ugc_style_requirements}

### 禁止事项
{avoid_in_new_scripts}
```

### 6.1 关联产品和目标市场必须覆盖原视频产品

脚本生成必须明确：

- 原视频产品只用于理解爆款机制
- 不得继续销售原视频产品
- 新脚本必须围绕 `UGC-01.关联产品` 指向的产品真源
- 场景、语言、人设、本土化必须围绕 `UGC-01.目标市场`

### 6.2 输出结构建议

脚本生成继续输出：

```text
JSON_OUTPUT
{...}
MARKDOWN_OUTPUT
...
```

JSON 顶层建议：

```json
{
  "script_meta": {
    "source": "ugc_single_video_handoff",
    "analysis_record_id": "",
    "script_batch_id": "",
    "script_version_id": "",
    "variant_id": "V1",
    "target_market": "",
    "linked_product_record_id": "",
    "new_product": "",
    "duration_target": "20-30s",
    "ugc_style": true
  },
  "character_card": {},
  "environment_card": {},
  "video_setup": {},
  "shots": [
    {
      "shot_index": 1,
      "duration_sec": 3,
      "content_type": "dialogue|voiceover|silent_action",
      "function": "Hook",
      "speaker": "",
      "speaker_visible": true,
      "dialogue": "",
      "dialogue_zh": "",
      "visual_description": "",
      "product_presence": "none|implied|visible|in_use|closeup",
      "image_generation_focus": ""
    }
  ],
  "six_grid_summary": [],
  "final_cta": {},
  "self_check": {},
  "risk_notes": []
}
```

注意：

- `shots` 必须正好 6 个。
- `six_grid_summary` 必须正好 6 个。
- `content_type` 必须沿用 `dialogue / voiceover / silent_action` 结构，避免下游退化成旁白。
- 如果是 `dialogue`，必须明确 `speaker` 与 `speaker_visible=true`。
- `dialogue` 使用目标市场语言；`dialogue_zh` 是中文检查用，不进入最终视频口播。
- `image_generation_focus` 给下一环节 6 宫格分镜图使用。

---

## 7. 后续代码实现任务

### 7.1 UGC 脚本批次创建

这是后续实际写代码时要实现的第一个任务：把 `UGC-01` 的分析结果派生成 `UGC-02` 批次和 `UGC-03` 版本任务。

1. 读取 `UGC-01` 源记录。
2. 校验：分析成功、有关联产品、有目标市场、有目标脚本数量、有分析结果 JSON。
3. 解析 `script_generation_handoff`。
4. 创建 1 条 `UGC-02` 批次记录。
5. 将 `UGC-01.关联产品` 自动复制到 `UGC-02.关联产品`。
6. 根据目标脚本数量创建 N 条 `UGC-03` 版本记录。
7. 将 `UGC-01.关联产品` 自动复制到每条 `UGC-03.关联产品`。
8. 回写 `UGC-01.脚本批次ID` 与 `UGC-01.脚本派生状态`。

### 7.2 UGC 脚本版本生成

这是后续实际写代码时要实现的第二个任务：读取单条 `UGC-03` 版本任务，并生成这一版的 1 条脚本。

1. 读取 `UGC-03` 版本记录。
2. 通过 `来源分析记录` 回读 `UGC-01`。
3. 以 `UGC-01.关联产品` 为产品真源读取 `初始化-产品信息`。
4. 读取 `UGC-01.分析结果JSON.script_generation_handoff`。
5. 拼接 `UGC 脚本生成 System Prompt v1`。
6. 调用模型生成 `JSON_OUTPUT + MARKDOWN_OUTPUT`。
7. 写回 `UGC-03.结构化脚本JSON` 与 `UGC-03.生成的脚本`。
8. 更新 `UGC-03.脚本生成状态`。

### 7.3 UGC dispatcher 状态流

这是后续实际写代码时要实现的调度入口。首版状态流建议：

1. `UGC-01.脚本派生状态 = 待派生` → 创建 `UGC-02` 和 N 条 `UGC-03`。
2. `UGC-03.脚本生成状态 = 待生成` → 生成当前版本脚本。
3. `UGC-03.是否入选 = 入选` 且 `下游推进状态 = 待6宫格分镜` → 进入 `UGC-04`。

---

## 8. 实施顺序

1. 实现 UGC-01 → UGC-02/UGC-03 的批次派生逻辑。
2. 实现 UGC-03 单版本脚本生成逻辑。
3. 用 1 条 UGC 分析 JSON 做离线 dry-run，生成 3 条脚本。
4. 人工审脚本质量。
5. 再接入 dispatcher 自动流转。

---

## 9. 当前建议

先不要直接把 UGC 分析完成后自动推进到分镜。

建议首版流程：

```text
UGC 单视频分析完成
→ 用户选择目标脚本数量
→ 派生 N 条脚本版本
→ 生成 N 条脚本
→ 人工选择入选脚本
→ 再进入 6 宫格分镜
```

这样能控制质量和成本，也方便调 prompt。
