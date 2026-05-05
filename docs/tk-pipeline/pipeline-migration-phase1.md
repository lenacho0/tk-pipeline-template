# 不停产迁移：第一阶段改造项（Phase 1）

目标：在不影响现有飞书多维表格日常使用、不停止每日分镜图/视频生产的前提下，为现有工作流加上一层稳定性与执行控制能力。

## 本阶段原则

1. 不替换飞书作为业务操作台
2. 不直接停掉老调度器和老脚本
3. 先补“稳定性底座”，再逐步迁移执行权
4. 先做兼容层，再做重构

---

## Phase 1 目标

### 1. 统一外部 API 调用层
将 FastMoss / Gemini / Sora / Feishu 的调用统一收口，提供：
- 超时控制
- 指数退避重试
- 错误码规范化
- 请求 ID
- 结构化日志

### 2. 引入最小任务模型
先建立统一的任务定义与状态机，但暂时不强制替换现有脚本。

最小状态模型：
- pending
- running
- retry_waiting
- completed
- failed
- dead_letter

最小阶段模型：
- fetch_trending
- analyze_script
- generate_script
- generate_storyboard
- render_video
- sync_result

### 3. 给视频生成阶段加保护
优先对最不稳定、最昂贵的 render 阶段增加：
- 并发限制
- 幂等 key
- 超时
- 自动重试

### 4. 给飞书回写加保护
- 回写失败不立即判定主流程失败
- 支持异步重试
- 支持批量写入（后续阶段实现）

---

## 推荐落地顺序

### Step 1：接入统一配置
新增：
- `src/config/env.ts`
- `src/config/concurrency.ts`

目的：
- 把 API 地址、token、并发、超时集中管理

### Step 2：建立错误码体系
新增：
- `src/core/error-codes.ts`
- `src/core/app-error.ts`

目的：
- 避免系统里到处散落字符串报错
- 区分可重试/不可重试错误

### Step 3：统一重试和超时封装
新增：
- `src/core/retry-policy.ts`
- `src/core/request-context.ts`

目的：
- 所有外部 API 一律走同一套 retry/backoff/timeout 逻辑

### Step 4：统一日志
新增：
- `src/core/logger.ts`

目的：
- 每个任务/请求带 requestId / taskId / recordId
- 后续排障能串起全链路

### Step 5：定义任务模型
新增：
- `src/types/task.ts`

目的：
- 统一 stage/status/payload 定义
- 为后面数据库落地做准备

### Step 6：搭服务层骨架
新增：
- `src/services/fastmoss.ts`
- `src/services/gemini.ts`
- `src/services/sora.ts`
- `src/services/feishu.ts`

目的：
- 让现有脚本后续逐步改成调用 service，而不是直接散调 API

### Step 7：先做 render worker 骨架
新增：
- `src/workers/render.worker.ts`

目的：
- 先把视频生成阶段规范化
- 后续可单独给 render 阶段上并发控制和队列

---

## 飞书兼容策略

本阶段只建议“增字段”，不要删改老字段。

建议新增字段：
- 系统任务ID
- 当前阶段
- 执行状态
- 重试次数
- 最近错误码
- 最近错误信息
- 下次重试时间
- 处理版本

注意：
- 旧字段继续保留
- 老脚本还能继续读
- 新系统优先读新字段，没有则回退旧逻辑

---

## 并发建议（Phase 1 初始值）

- fetch: 3
- analyze: 5
- script: 5
- storyboard: 3
- render: 2
- feishu sync: 3

说明：
- render 最贵最慢，先保守
- Gemini 类文本任务可略高
- 飞书回写不要打太猛，避免限流

---

## 错误处理建议

### 可重试
- timeout
- 429
- 502/503/504
- 临时网络错误
- Feishu 写入失败
- 模型空输出（限制次数）

### 不可重试
- 输入缺失
- 字段配置错误
- prompt 模板错误
- API key 无效
- schema 校验失败（视情况）

---

## 这阶段的交付物

1. 一套工程骨架
2. 一套错误码体系
3. 一套重试/超时/日志基础设施
4. 一套任务类型定义
5. 一套服务层封装入口
6. 一个 render worker 骨架

---

## 成功标准

如果 Phase 1 做完，应该达到：

- 老系统继续跑，不停产
- 新代码可以逐步接入现有脚本
- 关键外部 API 调用可观测、可重试、可限流
- 视频生成阶段可以先被单独加固
- 后续 Phase 2 可以无缝接数据库和任务队列
