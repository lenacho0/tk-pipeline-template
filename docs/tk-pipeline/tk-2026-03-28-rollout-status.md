# TK Pipeline 2026-03-28 实际上线状态记录

## 今天实际完成的内容

### 1. dispatcher P0 第一版硬化已落地
已上线并验证过：
- 分阶段并发 / timeout / retry 参数化
- 统一错误分类入口 `build_error_payload()`
- dead letter
- circuit breaker
- storyboard 双层 fallback
- 子任务标准错误输出（部分脚本）

### 2. dispatcher 扫描减负第一刀已落地
已上线并恢复稳定：
- 有空闲并发槽位才扫描
- 表级缓存
- 记录状态缓存
- 减少重复 claim

### 3. dispatcher runtime log 独立化已落地
当前主日志文件：
- `tk_toolkit/dispatcher-runtime.log`

launchd 侧日志仍保留：
- `tk_toolkit/launchd.err.log`
- `tk_toolkit/launchd.out.log`

### 4. 当前已确认恢复稳定
后续验证状态：
- heartbeat 为 `running`
- runtime log 已有新启动日志与运行统计
- dispatcher 已重新进入主循环

---

## 今天过程中真实发生过的问题

### 问题 A：扫描优化引入常量缺失
出现过：
- `STAGE_CFG is not defined`
- `RECORD_STATE_CACHE_TTL_SECONDS is not defined`

根因：
- 在多次编辑 dispatcher 顶部配置区时，初始化常量区被局部覆盖/顺序打乱

已修复。

### 问题 B：runtime log 改造引入初始化顺序错误
出现过：
- `RUNTIME_LOG_FILE is not defined`

根因：
- `RotatingFileHandler(RUNTIME_LOG_FILE, ...)` 初始化早于 `RUNTIME_LOG_FILE` 定义

已修复。

---

## 当前结论

### 可以确认的
- dispatcher 当前已经恢复运行
- 这次 P0 与扫描减负改造不是停留在文档层，而是已经真正进到线上
- 当前系统比今天开始前更强：
  - 更可控
  - 更可观测
  - 更接近批量运行形态

### 仍然不建议今天继续做的
- 继续大改 dispatcher 主调度文件
- 继续往主循环里塞新状态机/新批次结构

原因：
- 今天已经多轮在线修改并经历过 crash/hotfix
- 当前稳定性来之不易
- 继续动主链风险不划算

---

## 建议的后续路线

### 低风险优先
1. 统一更多下游脚本的错误输出协议
2. 做一次小批量真实验证
3. 完善运维文档与排障文档

### 下一轮再做
4. 更正式的增量扫描
5. 批次语义
6. 母子任务追踪
7. Feishu 侧状态字段进一步标准化
