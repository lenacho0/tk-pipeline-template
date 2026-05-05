# TK Pipeline P0 落地说明（2026-03-28）

本次已完成一版“今天可上线”的 P0 最小落地，目标是优先提升：

- 调度可控性
- 失败可恢复性
- 坏任务隔离
- storyboard 空输出容错

## 已完成

### 1. dispatcher 并发/超时/重试参数化
从 `tk_toolkit/config.json` 新增：
- `dispatcher.poll_interval`
- `dispatcher.healthcheck_hour`
- `dispatcher.circuit_breaker`
- `dispatcher.stages[*].max_concurrency`
- `dispatcher.stages[*].max_retries`
- `dispatcher.stages[*].timeout`

现在每个 stage 的并发和重试不再只靠硬编码。

### 2. 统一错误分类入口
在 `tk_toolkit/common.py` 新增：
- `build_error_payload(error, stage)`

当前支持的错误码归类：
- `UPSTREAM_NETWORK`
- `UPSTREAM_RATE_LIMIT`
- `MODEL_EMPTY_OUTPUT`
- `MODEL_SCHEMA_INVALID`
- `PROMPT_BUILD_FAILED`
- `INPUT_MISSING`
- `CONFIG_INVALID`
- `UPLOAD_FAILED`
- `WRITEBACK_FAILED`
- `RUNTIME_BUG`

并且每个错误会附带：
- `status`（failed_retryable / failed_terminal）
- `retryable`
- `message`

### 3. dispatcher 基于错误类别决定是否重试
现在 dispatcher 不再只看“子进程非 0 退出就重试”。
而是读取子任务输出中的错误语义，统一归类后决定：
- 可重试 → 回退待重试
- 不可重试 → 直接失败

### 4. 坏任务隔离 / 死信
新增本地文件：
- `.dead_letter_tasks.json`

超过重试上限或不可重试任务，会登记到 dead letter。

### 5. 熔断器（最小版）
新增本地文件：
- `.circuit_breakers.json`

同一 stage 在窗口内连续失败达到阈值，会短暂熔断，防止坏任务持续吃执行位。

### 6. 九宫格 storyboard 空输出容错
`tk_storyboard.py` 已增加双 prompt 方案：
- 第一轮：原始 prompt
- 第二轮：更强约束的稳态 JSON prompt

用于缓解：
- 模型空输出
- 没有合法 JSON
- shots 数量不足

### 7. 子任务错误输出标准化
`tk_storyboard.py` 与 `tk_shot_storyboard.py` 失败时现在会输出：
- `ERROR_CODE=...`
- `RETRYABLE=true|false`
- `MESSAGE=...`

这让 dispatcher 可以更稳定判断策略。

---

## 这次还没完全做完的

今天这版是 **P0 最小可上线版**，不是最终完整版。

还没彻底做完的包括：

1. 全链路 stage/status 字段真正写回 Feishu 新字段
2. 各脚本都统一成结构化 stdout/stderr 协议
3. 批次字段 / 母子任务字段
4. Feishu 增量扫描 / 本地状态缓存
5. 更完整的 dead-letter 回放机制
6. 更正式的 pause / resume 控制

---

## 当前建议

如果今天要尽快上线：
1. 先重启 dispatcher
2. 观察 1~2 轮真实任务
3. 看 dead letter / circuit breaker / retry 行为是否符合预期
4. 再继续补剩余 P0/P1

## 风险提示

因为 dispatcher 是线上消费入口，本次属于“在线增强改造”。
虽然已经通过 py_compile 语法检查，但仍建议：
- 重启后先盯日志
- 先跑小批
- 再逐步放大
