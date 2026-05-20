# TikTok 多维表工作流 - 表6 多版本脚本生成代码接入方案（旧 tkpipeline 参考稿）

> 更新时间：2026-04-21
> 状态说明：**此文档保留为旧 `tk_toolkit_dual` / tkpipeline 结构参考稿，不作为当前项目正式实施路径。**
> 当前项目正式边界见：`docs/tiktok-bitable-independent-project-boundary.md`
> 目标：沉淀“如果参考旧代码结构，哪些接线点值得借鉴”的分析。
> 核心原则：**只作参考，不直接挂接旧链路。**

---

## 1. 现状判断（基于现有代码）

从 `tk_toolkit_dual` 当前实现看，表6 `tk_script_gen.py` 已经具备这些基础：

### 已有能力
- 从表6 单条记录读取任务
- 从表4 读取产品真源
- 从表5 读取模特真源
- 从表2 自动筛参考分析记录
- 从配置表读取正式 prompt
- 调用 Gemini 生成脚本
- 把脚本文本写回 `生成的脚本`
- 把结构化 shot JSON 写回 `结构化脚本JSON`
- 下游 `tk_storyboard.py` 已能优先消费 `结构化脚本JSON`

### 当前缺口
当前 `tk_script_gen.py` 的设计本质仍是：

**一条记录 -> 一次脚本生成 -> 一条结果写回**

它还没有原生支持：
- 多版本任务批次规划
- 预创建多个版本记录
- 每个版本独立 `variant_assignment`
- 多版本差异自检
- 批次级字段与版本级字段协同写回

### 结论
好消息是：
**现有链路不需要推翻。**

坏消息是：
多版本能力不能只在 prompt 上补一句话，必须在表6 任务生命周期上加一层“批次规划 + 版本拆分”。

所以正确做法不是直接魔改 `tk_script_gen.py` 让它一次产 3 个版本，
而是：

**在 `tk_script_gen.py` 前面加一层“多版本预创建/拆分逻辑”，再继续复用现有单记录脚本生成主链。**

---

## 2. 推荐最小改造路线

我建议分两步，不要一步到位搞大重构。

## Phase D1：最小接线版（推荐先做）
目标：
- 不改 dispatcher 的基本模式
- 不改下游 storyboard / video 的单记录消费方式
- 只让表6 具备多版本预创建能力

做法：
1. 在表6 保持“一版本一行”
2. 新增一个“批次规划入口”脚本（建议独立）
3. 由这个脚本读取一条“母任务记录”或“模板任务记录”
4. 自动预创建 V1/V2/V3 多条子记录
5. 每条子记录继续由现有 `tk_script_gen.py` 按单记录方式执行

### 这是当前最稳的路线
原因：
- 对现有生产链影响最小
- 失败隔离最好
- 重试机制几乎可复用现有 dispatcher
- 下游链路几乎不用改

## Phase D2：增强版
在 D1 稳定后再考虑：
- 自动做版本差异自检
- 自动筛选推荐版本
- 更进一步抽象统一 protocol builder

---

## 3. 代码结构建议

建议新增一个前置脚本，而不是把所有逻辑硬塞进 `tk_script_gen.py`。

### 推荐新增文件
- `tk_toolkit_dual/tk_script_variant_plan.py`

### 角色分工

#### 1）`tk_script_variant_plan.py`
负责：
- 读取表6 中一条“批次入口任务”
- 解析多版本控制字段
- 生成批次级控制信息
- 计算版本分配
- 预创建多条版本记录
- 把母任务标成“已拆分”或“已展开”

#### 2）`tk_script_gen.py`
继续负责：
- 读取单条版本记录
- 组装当前版本 prompt payload
- 调用 LLM 生成单个版本脚本
- 写回单版本结果

### 关键思想
`tk_script_gen.py` 继续做“单条记录脚本生成器”，
而不是升级成“批量多版本 orchestrator”。

这能最大限度保住现有稳定链路。

---

## 4. dispatcher 层建议

当前 `tk_dispatcher.py` 已按单表单脚本轮询状态触发。

因此推荐新增一个 stage，而不是替换原有“产品脚本生成”。

### 推荐新增 watch
在 `tk_dispatcher.py` 中新增一个前置环节，例如：

- 名称：`脚本多版本预创建`
- script：`tk_script_variant_plan.py`
- table：仍然是 `TABLE_SCRIPT_GEN`
- status_field：建议新增一个专门字段，例如 `多版本规划状态`

### 推荐状态机（新增）
给“批次规划”单独一套字段，不和“脚本生成状态”混写。

建议新增字段：
- `多版本规划状态`

建议状态值：
- 待规划
- 规划中
- 已拆分
- 规划失败
- 已跳过

### 为什么要拆状态
因为：
- `脚本生成状态` 应只表示当前这条版本记录的脚本生成状态
- “批次拆分”是更上游的 orchestration，不应该复用“生成中/生成成功”

---

## 5. 两类记录角色建议

为了让表6 能同时兼容“母任务”与“版本任务”，建议引入记录角色。

### 建议新增字段
- `记录角色`

建议枚举值：
- 批次母任务
- 版本任务

### 作用

#### 批次母任务
作用：
- 承接用户填写的多版本控制参数
- 作为批次入口
- 不直接进入下游 storyboard / video

#### 版本任务
作用：
- 真正执行脚本生成
- 真正承接下游 storyboard / 生图 / 视频

### 重要规则
dispatcher 在：
- `tk_script_variant_plan.py` 环节处理 `批次母任务`
- `tk_script_gen.py` 环节处理 `版本任务`

这样职责清楚，不会互相踩。

---

## 6. 表6 字段 -> Prompt 协议映射表

下面给出最关键的映射关系。

## 6.1 批次级字段映射

| 表6 字段 | Prompt 协议字段 | 说明 |
|---|---|---|
| 批次ID | `batch_context.batch_id` | 批次唯一标识 |
| 项目ID | `batch_context.project_id` | 项目上下文 |
| 项目名称 | `batch_context.project_name` | 冗余可读信息 |
| 共性分析记录ID | `batch_context.common_analysis_record_id` | 来源于表2 |
| 产品ID | `batch_context.product_id` | 产品真源键 |
| 产品名称 | `batch_context.product_name` | 冗余可读信息 |
| 模特ID | `batch_context.model_id` | 人物真源键 |
| 模特名称 | `batch_context.model_name` | 冗余可读信息 |
| 目标市场 | `batch_context.target_market` | 市场 |
| 脚本生成模式 | `generation_mode` + `batch_context.script_generation_mode` | 协议模式 + 中文业务值 |
| 目标版本数 | `batch_context.target_variant_count` | 批次计划版本数 |
| 测试维度 | `batch_context.testing_dimensions` | 当前批次测试维度 |
| 派生策略 | `batch_context.derivation_strategy` | S1/S2/S3 |
| 版本差异强度 | `batch_context.difference_level` | 保守/标准/激进 |
| 脚本总时长目标 | `batch_context.target_duration` | 建议区间化 |
| 锁定项说明 | `locked_elements.notes` | 人类可读锁定项 |
| 变量位说明 | `variable_slots.*` | 允许变化维度 |
| 共性骨架摘要 | `shared_truth_sources.common_analysis.summary` | 摘要信息 |
| 场景参考图 | `shared_truth_sources.scene_context.scene_reference_images` | 附件URL或文件token转可用链接 |
| 场景参考说明 | `shared_truth_sources.scene_context.scene_reference_notes` | 场景补充说明 |

## 6.2 版本级字段映射

| 表6 字段 | Prompt 协议字段 | 说明 |
|---|---|---|
| 版本编号 | `variant_assignment.variant_id` | V1/V2/V3 |
| 版本名称 | `variant_assignment.variant_name` | 结构化命名 |
| 主测试点 | `variant_assignment.primary_test` | 主变量位 |
| 次测试点 | `variant_assignment.secondary_test` | 次变量位 |
| 版本差异说明 | `variant_assignment.difference_goal` | 版本目的说明 |

## 6.3 系统生成字段映射

| 系统逻辑 | Prompt 协议字段 |
|---|---|
| 产品真源锁定 | `locked_elements.product_truth_locked=true` |
| 人物真源锁定 | `locked_elements.character_truth_locked=true` |
| 共性骨架锁定 | `locked_elements.common_formula_locked=true` |
| 转化路径锁定 | `locked_elements.conversion_path_locked=true` |
| 目标市场锁定 | `locked_elements.target_market_locked=true` |
| 当前允许变化维度 | `variable_slots.allowed_dimensions` |
| 当前维度允许方向 | `variable_slots.dimension_directions` |
| 禁止变化维度 | `variable_slots.disallowed_dimensions` |

---

## 7. 批次规划脚本的执行顺序

下面是 `tk_script_variant_plan.py` 推荐执行顺序。

### Step 1：读取母任务记录
读取表6 当前记录，要求：
- `记录角色 = 批次母任务`
- `多版本规划状态 = 待规划`

### Step 2：标准化输入
整理：
- 项目 / 产品 / 模特 / 市场
- 共性分析记录
- 场景参考图 / 说明
- 模式 / 版本数 / 测试维度 / 派生策略 / 差异强度 / 时长目标

### Step 3：补默认值
若为空则补：
- 脚本生成模式 = 多版本受控派生
- 目标版本数 = 3
- 测试维度 = auto
- 派生策略 = S3 系统推荐探索
- 版本差异强度 = 标准

### Step 4：生成批次级控制信息
输出：
- 批次ID
- 锁定项说明
- 变量位说明
- 共性骨架摘要

### Step 5：做版本分配
例如默认 3 版本：
- V1 = hook_angle / 痛点直击
- V2 = hook_angle / 结果前置
- V3 = scene_entry / 家庭日常切入

### Step 6：预创建子记录
在表6 中创建 N 条 `版本任务` 记录，写入：
- 记录角色 = 版本任务
- 批次ID
- 所有共享字段
- 当前版本字段
- 脚本生成状态 = 待生成
- 下游推进状态 = 未推进

### Step 7：更新母任务状态
把母任务写成：
- 多版本规划状态 = 已拆分
- 可选写入：已创建版本数 / 子记录IDs / 批次摘要

---

## 8. 版本任务脚本生成的接线点

接下来 `tk_script_gen.py` 只需要做增强，不需要推翻。

## 8.1 当前最重要的改造点

### 改造点 A：识别版本任务字段
当前 `tk_script_gen.py` 只把表6 当“单脚本任务”。
后续要额外读取：
- 批次ID
- 版本编号
- 版本名称
- 主测试点
- 次测试点
- 版本差异说明
- 锁定项说明
- 变量位说明
- 共性骨架摘要
- 测试维度 / 派生策略 / 版本差异强度 / 总时长目标

### 改造点 B：构造 structured protocol payload
建议新增函数，例如：
- `build_multivariant_protocol_payload(fields, product_info, model_info, common_analysis, scene_context)`

这个函数负责把表字段组装成：
- `batch_context`
- `shared_truth_sources`
- `generation_constraints`
- `locked_elements`
- `variable_slots`
- `variant_assignment`
- `output_contract`

### 改造点 C：把 protocol payload 注入 prompt
当前 `build_script_generation_prompt(...)` 还是老式拼接。
建议最小改法：
- 不直接推翻现有 prompt 模板
- 在 prompt 前面新增一个结构化上下文区块

例如：

```text
## 多版本派生控制协议
[protocol payload JSON]

## 正式脚本生成要求
[原有正式 prompt 模板]
```

这条路最稳，风险最小。

### 改造点 D：把版本元信息写入 script_meta
当前 structured JSON 主要是 shots。
后续建议在 `script_meta` 补上：
- batch_id
- variant_id
- variant_name
- primary_test
- secondary_test
- direction

这样后续分镜/视频链路更容易追溯。

---

## 9. 建议的函数级改造点（tk_script_gen.py）

下面是我建议的最小函数级调整。

### 可新增函数
- `normalize_multivariant_fields(fields)`
- `build_locked_elements(fields, product_info, model_info, strategy_summary)`
- `build_variable_slots(fields)`
- `build_variant_assignment(fields)`
- `build_output_contract()`
- `build_multivariant_protocol_payload(...)`
- `render_protocol_block(payload)`

### 可修改函数
- `build_script_generation_prompt(...)`
  - 扩展为支持可选 `protocol_payload`

### 现有主流程中插入点
在生成普通脚本 prompt 前，插入：
1. 判断 `记录角色`
2. 若为版本任务，则尝试构建 protocol payload
3. 若构建成功，则走增强版 prompt
4. 若缺少字段，则回退老逻辑（但记 log）

### 为什么要保留回退
因为现在是生产链，不适合一刀切。
最安全做法是：
- 多版本字段齐全时 -> 新逻辑
- 多版本字段缺失时 -> 老逻辑继续可跑

---

## 10. 版本差异自检接在哪

我建议不要先新建独立脚本，先在 `tk_script_gen.py` 成功生成后追加一个轻量步骤。

### 方案 A：同一次模型调用内要求附带 diff-check（推荐首版）
即让模型在输出脚本 JSON 时，顺手附加：
- `variant_diff_check`

优点：
- 快
- 改动小
- 少一次模型调用

缺点：
- 自检质量可能偏乐观

### 方案 B：后置独立自检调用
优点：更稳
缺点：多一次调用

### 结论
首版建议：
**先用方案 A，同一次调用里带 diff-check。**
等后面发现质量不够，再拆成独立步骤。

---

## 11. 回写顺序建议

单条版本任务成功后，建议按以下顺序回写：

### 第一步：写脚本主结果
- 生成的脚本
- 结构化脚本JSON
- 脚本摘要

### 第二步：写版本辅助字段
- 版本差异自检结果
- 参考分析记录IDs
- 参考来源摘要

### 第三步：更新状态
- 脚本生成状态 = 生成成功
- 错误信息 = 清空

失败时：
- 脚本生成状态 = 生成失败 / 待重试
- 错误信息 = 具体错误

### 为什么这个顺序更稳
因为即使状态回写失败，核心结果也已经先落表，不容易丢。

---

## 12. 新增字段对下游脚本的影响

好消息是：
下游影响其实不大。

## 12.1 `tk_storyboard.py`
理论上无需大改。
原因：
- 它本来就按单记录消费
- 它本来就优先读 `结构化脚本JSON`

最多只需要后续增强：
- 读取 `script_meta.variant_id`
- 在日志里打印版本信息

## 12.2 `tk_video_from_storyboard.py`
理论上也无需大改。
它继续按单版本单记录推进即可。

## 12.3 需要注意的地方
只要保证：
- 入选的是版本任务，不是批次母任务
- 下游 dispatcher 只对版本任务进行推进

就不会乱。

---

## 13. dispatcher 过滤规则建议

为了避免母任务误进下游，建议各阶段加一条轻过滤规则。

### 在脚本生成阶段
只处理：
- `记录角色 = 版本任务`
- `脚本生成状态 = 待生成`

### 在分镜阶段
只处理：
- `记录角色 = 版本任务`
- `是否入选 = 入选`（如果你要先人工选）
- 或者 `下游推进状态 = 待分镜`

### 在视频阶段
同样只处理版本任务。

### 这很重要
不然母任务会因为共用表6，被误当成普通任务推进下去。

---

## 14. 最小改造清单（按优先级）

### P0：必须做
1. 表6 新增字段：
   - 记录角色
   - 多版本规划状态
   - 批次ID
   - 版本编号
   - 版本名称
   - 主测试点
   - 次测试点
   - 版本差异说明
2. 新增 `tk_script_variant_plan.py`
3. dispatcher 新增“脚本多版本预创建” stage
4. `tk_script_gen.py` 支持读取版本字段并注入 protocol block

### P1：强烈建议做
5. 写回 `版本差异自检结果`
6. `script_meta` 中写入版本元信息
7. 下游 dispatcher 增加 `记录角色=版本任务` 过滤

### P2：可后做
8. 自动推荐“最佳版本”
9. 更完整的批次 review 输出
10. 独立 diff-check 二次校验

---

## 15. 风险与对应策略

## 风险 1：一次改动太多，生产链不稳
### 策略
- 先新增前置 planning 脚本
- 保持 `tk_script_gen.py` 主体不推翻
- 多版本字段缺失时允许回退老逻辑

## 风险 2：母任务和版本任务混用导致 dispatcher 误触发
### 策略
- 强制新增 `记录角色`
- 每个阶段都过滤角色

## 风险 3：多版本差异仍然不够真实
### 策略
- 首版就写 `主测试点` 和 `版本差异说明`
- 同时增加 `版本差异自检结果`
- 后续再上更严格独立校验

## 风险 4：表字段太多，用户填不动
### 策略
- 用户只填少数字段
- 大量字段系统自动生成/继承
- 批次母任务做输入，版本任务主要系统回填

---

## 16. 我建议的最终工程路线

### 第一步（最优先）
先补表字段 + 新增 `tk_script_variant_plan.py`

### 第二步
让 `tk_script_gen.py` 支持消费版本字段与 protocol block

### 第三步
让 dispatcher 串起：
- 母任务规划
- 版本任务生成

### 第四步
等稳定后，再补：
- diff-check 增强
- 自动选择推荐版本
- 更深的 schema 抽象

---

## 17. 直接可执行的下一份文档建议

如果再往下走，下一份不该再是泛方案，而是更硬一点的：

### 方案 A：字段创建清单
直接列出需要在飞书表6 新增/调整的字段名、类型、选项值

### 方案 B：代码改造 TODO 清单
直接列出：
- 哪个文件改
- 加什么函数
- 哪个函数插哪段逻辑
- 哪些状态值新增

我建议下一步直接做 **方案 B**，产出：

`docs/tiktok-bitable-table6-implementation-todo.md`

这样就从“工程方案”进一步落到“开发清单”，可以直接照单开干。