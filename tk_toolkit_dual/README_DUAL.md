# tk_toolkit_dual

ryan 主线运行目录。`tk_toolkit/` 老项目保持不动，当前目录继续复用其中的 Python 虚拟环境。

## 目标

- 唯一正式实例：`TK_INSTANCE=ryan`
- 唯一正式配置：`config.ryan.json`
- dispatcher、healthcheck 和 launchd 只维护 ryan 主线
- UGC/内容链路、colleague 实例和旧 fastmoss/九宫格链路已下线

## 关键环境变量

- `TK_INSTANCE`: 固定使用 `ryan`
- `TK_CONFIG_FILE`: 指向 `config.ryan.json`

## 启动示例

```bash
cd tk_toolkit_dual
TK_INSTANCE=ryan TK_CONFIG_FILE=$PWD/config.ryan.json ./run_dispatcher_instance.sh
```

## 停止示例

```bash
cd tk_toolkit_dual
TK_INSTANCE=ryan ./stop_dispatcher_instance.sh
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

- `config.ryan.json` 指向当前 ryan 主线表。
- 老项目 `tk_toolkit/` 没有被改动。
- 当前新项目已清理复制时带入的运行态垃圾文件和重复 `.venv312`，默认继续复用老项目的 Python 虚拟环境路径。
- ryan launchd 与实例化 healthcheck：
  - `com.ryan.tk-dispatcher.ryan.plist`
  - `install_launchd_instances.sh`
  - `uninstall_launchd_instances.sh`
  - `launchd_usage_dual.md`
  - `tk_healthcheck.py`（支持 `TK_INSTANCE` / `TK_CONFIG_FILE`）
