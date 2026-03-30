# tk_toolkit_dual

双实例隔离实验目录。`tk_toolkit/` 老项目保持不动，继续承担现有单表生产。

## 目标

- 同一套代码
- 两份配置
- 两个 dispatcher 实例并存
- 日志 / heartbeat / pid / metrics / cache 全部分离

## 关键环境变量

- `TK_INSTANCE`: 实例名，例如 `ryan` / `colleague`
- `TK_CONFIG_FILE`: 指向对应配置文件，例如 `config.ryan.json`

## 启动示例

### Ryan 实例

```bash
cd tk_toolkit_dual
TK_INSTANCE=ryan TK_CONFIG_FILE=$PWD/config.ryan.json ./run_dispatcher_instance.sh
```

### Colleague 实例

```bash
cd tk_toolkit_dual
TK_INSTANCE=colleague TK_CONFIG_FILE=$PWD/config.colleague.json ./run_dispatcher_instance.sh
```

## 停止示例

```bash
cd tk_toolkit_dual
TK_INSTANCE=ryan ./stop_dispatcher_instance.sh
TK_INSTANCE=colleague ./stop_dispatcher_instance.sh
```

## 目前已隔离的文件

以 `ryan` 为例：

- `dispatcher.ryan.pid`
- `dispatcher.ryan.log`
- `.dispatcher_heartbeat.ryan.json`
- `.dispatcher_metrics.ryan.json`
- `.running_tasks.ryan.json`
- `.retry_state.ryan.json`
- `.dead_letter_tasks.ryan.json`
- `.circuit_breakers.ryan.json`
- `.table_scan_state.ryan.json`
- `.record_state_cache.ryan.json`
- `dispatcher-runtime.ryan.log`
- `.table_cache_<tableId>.ryan.json`

## 注意

- `config.ryan.json` 仍指向老项目当前使用的原表。
- `config.colleague.json` 已切到你提供的新 Bitable：`南-TK爆款视频全自动生产🦞`
- 老项目 `tk_toolkit/` 没有被改动。
- 当前新项目已清理复制时带入的运行态垃圾文件和重复 `.venv312`，默认继续复用老项目的 Python 虚拟环境路径。
- 已新增双 launchd 配置与实例化 healthcheck：
  - `com.ryan.tk-dispatcher.ryan.plist`
  - `com.ryan.tk-dispatcher.colleague.plist`
  - `install_launchd_instances.sh`
  - `uninstall_launchd_instances.sh`
  - `launchd_usage_dual.md`
  - `tk_healthcheck.py`（支持 `TK_INSTANCE` / `TK_CONFIG_FILE`）
