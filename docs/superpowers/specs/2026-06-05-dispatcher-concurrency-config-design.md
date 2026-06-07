# Dispatcher Concurrency Config Design

## Goal

让 `初始化-模型与API配置` 成为 dispatcher 并发控制入口。用户可以在飞书表格中直接调整每个环节的并发数量，也可以设置全局并发数量，不再需要每次改 `tk_dispatcher.py` 或 `config.json`。

## Current State

- `tk_toolkit_dual/tk_dispatcher.py` 已经有每个 watch 的 `max_concurrency`。
- `apply_stage_policy()` 会用 `config.json` 的 `dispatcher.stages` 覆盖 watch 默认值。
- `check_and_run()` 已经支持 `GLOBAL_MAX_CONCURRENCY`，并在拉起任务前同时扣环节槽位和全局槽位。
- `初始化-模型与API配置` 已经是运行环节模型、API、提示词的线上真源，管理员视图由 `cleanup_model_config_table.py` 维护。

## Field Model

在 `初始化-模型与API配置` 新增两个数字字段：

- `环节最大并发`
- `全局最大并发`

字段语义：

- `环节最大并发` 只作用于 `配置类型=运行环节` 的记录。
- `全局最大并发` 只作用于 `配置类型=路由开关` 且 `环节=Dispatcher并发控制` 的记录。
- 空值表示不覆盖，继续使用 `config.json` 或代码默认值。
- `环节最大并发=0` 表示暂停该环节，不再拉起新任务。
- `全局最大并发=0` 或空值表示不启用全局限制。
- 负数、非数字、小数字符串都视为无效配置，忽略并记录 warning，不让 dispatcher 崩溃。

## Precedence

并发配置优先级从高到低：

1. 飞书 `初始化-模型与API配置`
2. `config.json` 的 `dispatcher.global_max_concurrency` / `dispatcher.stages`
3. `tk_dispatcher.py` 中 watch 的代码默认值

这样飞书表格是日常操作入口，本地配置保留为兜底，代码默认值只做最后保底。

## Matching Rules

环节并发匹配使用 dispatcher watch 名称：

- watch `name` 与配置表 `环节` 完全一致时生效。
- 只读取 `配置类型=运行环节` 且 `状态 != 停用` 的记录。
- 如果同一个环节存在多条启用记录，优先 `生效来源=线上配置`。
- 如果仍有多条可用记录，忽略该环节的飞书并发覆盖并记录 warning。

全局并发匹配：

- `配置类型=路由开关`
- `环节=Dispatcher并发控制`
- `状态 != 停用`

## Runtime Behavior

dispatcher 每次主循环读取一次并发策略，避免每个 watch 重复扫描配置表。

推荐新增模块级缓存：

- `CONCURRENCY_POLICY_TTL_SECONDS = 60`
- 缓存内容包含 `global_max_concurrency` 和 `stage_policies`
- 飞书读取失败时继续使用上一次成功读取的策略
- 如果从未读取成功，则使用 `config.json` / 代码默认

暂停语义：

- 当 `环节最大并发=0` 时，`apply_stage_policy()` 将 watch 的 `max_concurrency` 设置为 `0`。
- `check_and_run()` 原本通过 `available_slots = max(0, max_concurrency - current_running)` 判断是否拉新任务，因此不需要额外暂停分支。
- 已经运行中的任务不被杀掉；暂停只影响新任务拉起。

## Admin View

更新 `cleanup_model_config_table.py` 的字段规格和管理员视图：

- `CONFIG_FIELD_SPECS` 增加 `环节最大并发`、`全局最大并发`。
- `01-运行配置-管理员` 显示 `环节最大并发`。
- `01-运行配置-管理员` 也显示 `全局最大并发`，方便路由开关记录直接可见。

## Testing

单元测试覆盖：

- 空值不覆盖本地默认。
- `环节最大并发=3` 覆盖 `config.json`。
- `环节最大并发=0` 暂停环节，`check_and_run()` 不拉起任务。
- `全局最大并发=1` 时已有 1 个活跃任务会阻止新任务。
- 飞书读取失败时保留本地配置，不崩溃。
- 重复启用配置不会随机选一条，应该忽略并 warning。
- 字段规格和管理员视图包含新增字段。

## Out Of Scope

- 不改变任务状态机。
- 不杀掉已经运行中的进程。
- 不做按供应商/API Key 的令牌桶限流。
- 不把并发配置拆成新表。
- 不改各 worker 的模型调用逻辑。

