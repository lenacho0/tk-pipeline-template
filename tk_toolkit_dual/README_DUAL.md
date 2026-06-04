# tk_toolkit_dual

当前 TK pipeline 主线运行目录。交付给同事时，推荐使用私有 GitHub 仓库 + 独立复制的飞书多维表格 Base + macOS `launchd` 常驻运行。

## 本地配置

- 本地配置文件：`config.local.json`
- 配置模板：`config.json.template`
- 默认实例：`TK_INSTANCE=colleague`
- 默认 launchd label：`com.tk-pipeline.dispatcher.colleague`
- 默认 Python：仓库根目录 `.venv/bin/python`

真实配置文件不进入 Git。首次安装先运行：

```bash
bash tk_toolkit_dual/setup_local.sh
```

然后填写 `tk_toolkit_dual/config.local.json` 里的飞书应用凭证和复制 Base token。

## 复制 Base 后重映射

同事应先在飞书 UI 复制完整 Base，再执行：

```bash
.venv/bin/python tk_toolkit_dual/rebind_copied_base.py --config tk_toolkit_dual/config.local.json --write
```

脚本会按表名发现新 Base 的 `table_id`，并按 `初始化-模型与API配置` 的 `环节` 字段重写 `config_records`。

## 手动启动

```bash
cd tk_toolkit_dual
TK_INSTANCE=colleague TK_CONFIG_FILE=$PWD/config.local.json PYTHON_BIN=../.venv/bin/python ./run_dispatcher_instance.sh
```

## launchd 常驻

```bash
PYTHON_BIN=$PWD/.venv/bin/python TK_CONFIG_FILE=$PWD/tk_toolkit_dual/config.local.json bash tk_toolkit_dual/install_launchd_instances.sh colleague
```

查看状态：

```bash
launchctl print gui/$(id -u)/com.tk-pipeline.dispatcher.colleague | sed -n '1,120p'
```

卸载：

```bash
bash tk_toolkit_dual/uninstall_launchd_instances.sh colleague
```

## 健康检查

```bash
TK_INSTANCE=colleague TK_CONFIG_FILE=$PWD/tk_toolkit_dual/config.local.json .venv/bin/python tk_toolkit_dual/tk_healthcheck.py
```

## 运行态文件

以 `colleague` 为例，本地会生成：

- `dispatcher.colleague.log`
- `dispatcher-runtime.colleague.log`
- `.dispatcher_heartbeat.colleague.json`
- `.dispatcher_metrics.colleague.json`
- `.running_tasks.colleague.json`
- `.retry_state.colleague.json`
- `.dead_letter_tasks.colleague.json`
- `.circuit_breakers.colleague.json`
- `.table_scan_state.colleague.json`
- `.record_state_cache.colleague.json`
- `.table_cache_<tableId>.colleague.json`

这些文件都属于本地运行态，不应提交到 Git。
