# TikTok 多维表工作流 - 表6 多版本脚本生成实施 TODO 清单（旧 tkpipeline 接法参考稿）

> 更新时间：2026-04-21  
> 状态说明：**此文档中的实施 TODO 主要面向“若接入旧 `tk_toolkit_dual`”的参考路线，不作为当前独立新项目正式施工清单。**  
> 当前项目正式边界见：`docs/tiktok-bitable-independent-project-boundary.md`  
> 目标：保留旧链路接法的参考拆解，供架构对比。  
> 原则：**只作参考，不直接施工。**

---

## 0. 实施目标（这轮到底要做成什么）

这一轮不是要把整套 TikTok 新工作流全部重写，
而是要在现有 `tk_toolkit_dual` 基础上完成下面这件事：

**让表6 支持“母任务 -> 自动拆分多版本 -> 每个版本独立生成脚本 -> 下游继续按单版本推进”。**

换句话说，这轮交付标准应该是：
1. 用户在表6 新建一条“批次母任务”
2. 系统自动生成 V1/V2/V3 多条“版本任务”
3. 每条版本任务由现有脚本生成链路独立执行
4. 生成结果分别写回各自记录
5. 人工可选其中一个或多个版本进入下游分镜/视频阶段

只要这 5 步真的打通，这轮就算成功。

---

## 1. 实施优先级分层

### P0：必须做，不做就跑不起来
- 表6 补核心字段
- 新增 `tk_script_variant_plan.py`
- dispatcher 增加多版本预创建 stage
- `tk_script_gen.py` 支持版本任务字段与 protocol block
- dispatcher / 下游链路避免母任务误触发

### P1：强烈建议同轮做
- 版本差异自检结果写回
- `script_meta` 写入版本元信息
- 默认版本分配策略落地
- 多版本规划失败时的错误写回

### P2：可下一轮做
- 自动推荐最佳版本
- 更精细的批次 review 视图
- 独立 diff-check 二次校验
- 更通用的 protocol builder 抽象

---

## 2. 飞书表6 字段改造 TODO

这部分建议优先做，因为代码接线离不开字段。

## 2.1 必须新增字段（P0）

### A. 任务角色与规划状态
- [ ] 新增字段：`记录角色`
  - 类型：单选
  - 选项：`批次母任务` / `版本任务`

- [ ] 新增字段：`多版本规划状态`
  - 类型：单选
  - 选项：`待规划` / `规划中` / `已拆分` / `规划失败` / `已跳过`

### B. 批次控制字段
- [ ] 新增字段：`批次ID`
  - 类型：单行文本

- [ ] 新增字段：`目标版本数`
  - 类型：数字

- [ ] 新增字段：`测试维度`
  - 类型：多选
  - 选项：`auto` / `hook_angle` / `scene_entry` / `product_entry_timing` / `trust_builder` / `cta_style` / `tone_style`

- [ ] 新增字段：`派生策略`
  - 类型：单选
  - 选项：`S1 单维强差异` / `S2 双维组合差异` / `S3 系统推荐探索`

- [ ] 新增字段：`版本差异强度`
  - 类型：单选
  - 选项：`保守` / `标准` / `激进`

- [ ] 新增字段：`脚本总时长目标`
  - 类型：单行文本

### C. 系统自动写入字段
- [ ] 新增字段：`锁定项说明`
  - 类型：多行文本

- [ ] 新增字段：`变量位说明`
  - 类型：多行文本

- [ ] 新增字段：`共性骨架摘要`
  - 类型：多行文本

- [ ] 新增字段：`父任务ID`
  - 类型：单行文本

### D. 版本任务字段
- [ ] 新增字段：`版本编号`
  - 类型：单行文本 或 单选

- [ ] 新增字段：`版本名称`
  - 类型：单行文本

- [ ] 新增字段：`主测试点`
  - 类型：单选
  - 选项：`hook_angle` / `scene_entry` / `product_entry_timing` / `trust_builder` / `cta_style` / `tone_style` / `standard`

- [ ] 新增字段：`次测试点`
  - 类型：单选

- [ ] 新增字段：`版本差异说明`
  - 类型：多行文本

- [ ] 新增字段：`版本差异自检结果`
  - 类型：多行文本

### E. 人工选择 / 下游推进字段
- [ ] 新增字段：`是否入选`
  - 类型：单选
  - 选项：`待定` / `入选` / `淘汰`

- [ ] 新增字段：`下游推进状态`
  - 类型：单选
  - 选项：`未推进` / `待分镜` / `分镜中` / `待生图` / `生图中` / `待图生视频` / `图生视频中` / `已完成` / `已终止`

## 2.2 能复用则复用，不强制新增（P0/P1）
- [ ] 确认现有 `脚本生成状态` 是否继续沿用
- [ ] 确认现有 `错误信息` 字段是否已有；若没有则补
- [ ] 确认现有 `结构化脚本JSON` 字段是否已足够承接新版脚本 JSON
- [ ] 确认现有 `生成的脚本` 字段长度是否足够

## 2.3 建议从项目表继承展示（P1）
- [ ] `场景参考图`
- [ ] `场景参考说明`
- [ ] `目标市场`

---

## 3. 新增脚本文件 TODO：tk_script_variant_plan.py

这是这一轮最关键的新文件。

### 文件建议
- [ ] 新建文件：`tk_toolkit_dual/tk_script_variant_plan.py`

### 目标职责
- [ ] 读取表6 的“批次母任务”记录
- [ ] 校验多版本必要字段
- [ ] 生成批次级控制信息
- [ ] 自动分配 V1/V2/V3...
- [ ] 预创建多个版本任务记录
- [ ] 更新母任务状态为 `已拆分`

### 建议函数清单
- [ ] `load_parent_task(token, record_id)`
- [ ] `validate_parent_task(fields)`
- [ ] `fill_default_multivariant_fields(fields)`
- [ ] `build_batch_id(fields)`
- [ ] `build_locked_notes(fields, product_info, model_info, common_analysis)`
- [ ] `build_variable_notes(fields)`
- [ ] `build_common_backbone_summary(common_analysis)`
- [ ] `plan_variants(fields)`
- [ ] `build_variant_record_fields(parent_fields, variant_plan, shared_context)`
- [ ] `batch_create_variant_records(token, table_id, records)`
- [ ] `update_parent_task_after_split(token, record_id, result)`

### 版本规划逻辑 TODO
- [ ] 实现默认模式：`目标版本数=3 + 测试维度=auto`
- [ ] 默认规划：
  - V1 = `hook_angle / 痛点直击`
  - V2 = `hook_angle / 结果前置`
  - V3 = `scene_entry / 家庭日常切入`
- [ ] 支持单版本模式：仅创建 V1
- [ ] 支持指定维度模式：按用户填写维度定向拆分

### 创建子记录时必须写入的字段
- [ ] `记录角色 = 版本任务`
- [ ] `父任务ID = 母任务 record_id`
- [ ] `批次ID`
- [ ] 所有共享输入字段（产品/模特/市场/共性分析等）
- [ ] `版本编号`
- [ ] `版本名称`
- [ ] `主测试点`
- [ ] `次测试点`
- [ ] `版本差异说明`
- [ ] `锁定项说明`
- [ ] `变量位说明`
- [ ] `共性骨架摘要`
- [ ] `脚本生成状态 = 待生成`
- [ ] `下游推进状态 = 未推进`
- [ ] `是否入选 = 待定`

### 母任务状态写回 TODO
- [ ] 开始时写：`多版本规划状态 = 规划中`
- [ ] 成功后写：`多版本规划状态 = 已拆分`
- [ ] 失败时写：`多版本规划状态 = 规划失败`
- [ ] 失败时补写：`错误信息`

---

## 4. dispatcher 改造 TODO

## 4.1 新增前置 stage（P0）
- [ ] 修改文件：`tk_toolkit_dual/tk_dispatcher.py`
- [ ] 新增 stage：`脚本多版本预创建`
- [ ] 对应脚本：`tk_script_variant_plan.py`
- [ ] 对应表：`TABLE_SCRIPT_GEN`
- [ ] 对应状态字段：`多版本规划状态`
- [ ] 触发状态：`待规划`

## 4.2 脚本生成 stage 增加角色过滤（P0）
- [ ] 确保 `tk_script_gen.py` 只处理 `记录角色 = 版本任务`
- [ ] 或在 dispatcher 侧预过滤版本任务

## 4.3 下游 stage 增加角色过滤（P1）
- [ ] `tk_storyboard.py` 对应阶段只推进版本任务
- [ ] `tk_video_from_storyboard.py` 对应阶段只推进版本任务
- [ ] 若采用人工筛选，则分镜阶段再加：`是否入选 = 入选`

---

## 5. tk_script_gen.py 改造 TODO

这部分是第二关键位。

## 5.1 新增版本任务识别（P0）
- [ ] 读取字段：`记录角色`
- [ ] 若为空：兼容老逻辑，但打印 warning
- [ ] 若为 `批次母任务`：直接跳过，不生成脚本
- [ ] 若为 `版本任务`：进入多版本增强逻辑

## 5.2 新增多版本字段读取（P0）
- [ ] 读取字段：
  - `批次ID`
  - `父任务ID`
  - `版本编号`
  - `版本名称`
  - `主测试点`
  - `次测试点`
  - `版本差异说明`
  - `锁定项说明`
  - `变量位说明`
  - `共性骨架摘要`
  - `测试维度`
  - `派生策略`
  - `版本差异强度`
  - `脚本总时长目标`

## 5.3 新增 protocol payload builder（P0）
- [ ] 新增函数：`build_multivariant_protocol_payload(...)`
- [ ] 子函数建议：
  - `normalize_multivariant_fields(fields)`
  - `build_batch_context(fields, ...)`
  - `build_shared_truth_sources(...)`
  - `build_generation_constraints(fields, ...)`
  - `build_locked_elements(fields, ...)`
  - `build_variable_slots(fields)`
  - `build_variant_assignment(fields)`
  - `build_output_contract()`

## 5.4 新增 protocol block 注入（P0）
- [ ] 修改 `build_script_generation_prompt(...)`
- [ ] 支持参数：`protocol_payload=None`
- [ ] 若存在 protocol_payload：
  - 在正式 prompt 前插入 `## 多版本派生控制协议`
  - 用 JSON 文本方式注入
- [ ] 若不存在：保留老逻辑

## 5.5 输出增强（P1）
- [ ] 要求模型在 `script_meta` 中附带：
  - `batch_id`
  - `variant_id`
  - `variant_name`
  - `primary_test`
  - `secondary_test`
- [ ] 要求模型附带 `variant_diff_check`
- [ ] 成功后把 `variant_diff_check` 写回 `版本差异自检结果`

## 5.6 回写顺序调整（P1）
- [ ] 先写：`生成的脚本`
- [ ] 再写：`结构化脚本JSON`
- [ ] 再写：`版本差异自检结果`
- [ ] 最后写：`脚本生成状态 = 生成成功`
- [ ] 失败时写：`脚本生成状态 = 生成失败` + `错误信息`

## 5.7 老逻辑兼容（P0）
- [ ] 若版本字段缺失，仍允许按现有单版本逻辑执行
- [ ] 但打印 log：`multivariant fields missing, fallback to legacy mode`

---

## 6. 共性分析 / 真源数据读取复用 TODO

为了避免新脚本重复造轮子，优先复用现有函数。

### 可优先复用
- [ ] `get_product_info(...)`
- [ ] `get_model_info(...)`
- [ ] `get_reference_scripts(...)`
- [ ] `generate_strategy_summary(...)`
- [ ] `safe_get_record(...)`
- [ ] `safe_update_record(...)`
- [ ] `safe_list_records(...)`

### 需要补的
- [ ] 若现在没有“按共性分析记录ID定向读取”的函数，补一个更直读的 helper
- [ ] 若现在 `get_reference_scripts(...)` 更偏“按产品筛多个参考”，评估是否增加“直接使用指定共性分析记录”模式

### 我建议
这轮最好明确：
**表6 脚本生成应该优先消费“指定的共性分析记录ID”，而不是再临时扫描一遍表2 猜参考。**

这一点我觉得很重要，不然多版本测试的输入基线会漂。

---

## 7. 下游链路 TODO

## 7.1 tk_storyboard.py（P1）
- [ ] 确认它只处理版本任务
- [ ] 可选增强：日志中打印 `批次ID / 版本编号 / 版本名称`
- [ ] 保持优先读取 `结构化脚本JSON`

## 7.2 tk_video_from_storyboard.py（P1）
- [ ] 确认它只处理版本任务
- [ ] 可选增强：日志中打印版本信息

## 7.3 人工筛选口径（P1）
- [ ] 确认是否采用：只有 `是否入选 = 入选` 才进入分镜
- [ ] 如果采用，则 dispatcher 对分镜阶段增加该条件
- [ ] 如果不采用，则默认全部版本都能继续推进

### 我的建议
首版最好采用：
**先人工选中，再进分镜。**

原因：
- 多版本就是为了比，不是都往后跑
- 可以省分镜/视频成本
- 逻辑更贴近真实 A/B 预筛选

---

## 8. 默认值与校验规则 TODO

## 8.1 批次母任务默认值（P0）
- [ ] 若 `脚本生成模式` 为空 -> 默认 `多版本受控派生`
- [ ] 若 `目标版本数` 为空 -> 默认 `3`
- [ ] 若 `测试维度` 为空 -> 默认 `auto`
- [ ] 若 `派生策略` 为空 -> 默认 `S3 系统推荐探索`
- [ ] 若 `版本差异强度` 为空 -> 默认 `标准`

## 8.2 强校验（P0）
- [ ] 若缺产品ID -> 失败
- [ ] 若缺模特ID -> 失败
- [ ] 若缺目标市场 -> 失败
- [ ] 若缺共性分析记录ID -> 失败
- [ ] 若 `记录角色 != 批次母任务` 却触发 variant planner -> 跳过
- [ ] 若 `记录角色 != 版本任务` 却触发 script gen -> 跳过

## 8.3 定向测试校验（P1）
- [ ] 若 `脚本生成模式 = 指定维度定向测试` 且 `测试维度=auto` -> 失败
- [ ] 若 `目标版本数 = 1` 且模式是多版本 -> warning 或自动改写

---

## 9. 日志与错误写回 TODO

## 9.1 tk_script_variant_plan.py 日志（P0）
- [ ] 任务开始
- [ ] 母任务字段校验结果
- [ ] 默认值补全结果
- [ ] 版本规划结果
- [ ] 创建子记录数量
- [ ] 母任务状态更新结果

## 9.2 tk_script_gen.py 日志增强（P1）
- [ ] 打印 `批次ID`
- [ ] 打印 `版本编号`
- [ ] 打印 `主测试点`
- [ ] 打印是否走 `protocol_payload` 模式

## 9.3 错误信息口径（P0/P1）
- [ ] 规划失败：错误写到母任务 `错误信息`
- [ ] 版本生成失败：错误写到对应版本任务 `错误信息`
- [ ] 不要把母任务错误和版本任务错误混在一起

---

## 10. 测试计划 TODO

这部分别省，不测很容易表面通了，实则乱写表。

## 10.1 最小联调样例（P0）
- [ ] 样例 A：默认多版本（3 版本，auto）
- [ ] 样例 B：单版本标准生成
- [ ] 样例 C：指定维度定向测试（例如只测 hook_angle 2 版本）

## 10.2 每个样例需要验证的点
- [ ] 母任务是否能正确拆分
- [ ] 批次ID 是否一致
- [ ] 版本编号 / 名称是否正确
- [ ] 脚本生成是否按子记录独立执行
- [ ] 生成结果是否分别回写
- [ ] 母任务是否不会误进下游
- [ ] 版本任务是否能按规则进入下游

## 10.3 建议联调顺序
1. 先只测 `tk_script_variant_plan.py` 预创建，不跑 LLM
2. 再测 `tk_script_gen.py` 单条版本记录生成
3. 再让 dispatcher 串起来跑
4. 最后再测到 storyboard

这个顺序稳很多。

---

## 11. 实施顺序（建议按这个来）

### Day 1 / Step 1：补字段
- [ ] 先把表6 所需字段补齐
- [ ] 补单选选项值

### Day 1 / Step 2：写 variant planner
- [ ] 新建 `tk_script_variant_plan.py`
- [ ] 跑通“母任务 -> 预创建版本任务”

### Day 1 / Step 3：接 dispatcher 前置 stage
- [ ] 让母任务能自动拆分

### Day 2 / Step 4：增强 tk_script_gen.py
- [ ] 支持版本字段
- [ ] 支持 protocol block
- [ ] 支持写回 diff-check

### Day 2 / Step 5：做最小联调
- [ ] 跑默认 3 版本样例

### Day 2 / Step 6：接下游筛选口径
- [ ] 确定是否“入选后再进分镜”
- [ ] 加 dispatcher 过滤

---

## 12. 我自己的最终建议（直话版）

如果只允许我给一个最稳的落地策略，我会选这个：

### 方案
- 表6 加 `记录角色`
- 母任务只负责填参数和拆分
- 版本任务才真正生成脚本
- 继续复用 `tk_script_gen.py` 单条记录生成能力
- 下游只认版本任务
- 首版先人工选中再进分镜

### 为什么这是最对的
因为它：
- 最符合现有代码形态
- 最少破坏生产链
- 失败隔离最好
- 版本管理最清楚
- 后面扩展也最顺

反过来说，**最不建议** 的就是：
- 一条记录里生成多个版本 JSON 再拆
- 让 `tk_script_gen.py` 直接兼任批处理 orchestrator
- 不加 `记录角色` 就硬做母任务 / 子任务共表流转

这些都很容易把链路搞脏。

---

## 13. 下一步最自然的动作

如果继续往下，不该再写方案文档了，而是该开始真正干两类事：

### 路线 A：先补飞书表字段
直接把字段加上

### 路线 B：开始改代码
从 `tk_script_variant_plan.py` 起手

如果你要我继续，我建议下一步不再写新文档，而是直接开始做代码：
1. 先读一下 `tk_dispatcher.py` / `common.py` / `tk_script_gen.py`
2. 新建 `tk_script_variant_plan.py`
3. 最小改造 dispatcher 接进来
4. 再补 `tk_script_gen.py` 的 protocol block

这时候就已经从“设计阶段”切进“施工阶段”了。