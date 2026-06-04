# TK Pipeline 本地运维速查

## 当前运行方式

当前主线由 `tk_toolkit_dual/` 承载。同事本地默认实例：

- `TK_INSTANCE=colleague`
- launchd label：`com.tk-pipeline.dispatcher.colleague`
- 配置文件：`tk_toolkit_dual/config.local.json`

## 首次设置

```bash
bash tk_toolkit_dual/setup_local.sh
```

填写 `tk_toolkit_dual/config.local.json` 后，重映射复制 Base：

```bash
.venv/bin/python tk_toolkit_dual/rebind_copied_base.py --config tk_toolkit_dual/config.local.json --write
```

## 安装 / 卸载自动守护

```bash
PYTHON_BIN=$PWD/.venv/bin/python TK_CONFIG_FILE=$PWD/tk_toolkit_dual/config.local.json bash tk_toolkit_dual/install_launchd_instances.sh colleague
```

```bash
bash tk_toolkit_dual/uninstall_launchd_instances.sh colleague
```

## 查看与重启

```bash
launchctl print gui/$(id -u)/com.tk-pipeline.dispatcher.colleague | sed -n '1,120p'
```

```bash
launchctl kickstart -k gui/$(id -u)/com.tk-pipeline.dispatcher.colleague
```

## 手动运行 dispatcher

```bash
cd tk_toolkit_dual
TK_INSTANCE=colleague TK_CONFIG_FILE=$PWD/config.local.json PYTHON_BIN=../.venv/bin/python ./run_dispatcher_instance.sh
```

停止手动进程：

```bash
cd tk_toolkit_dual
TK_INSTANCE=colleague ./stop_dispatcher_instance.sh
```

## 健康检查

```bash
TK_INSTANCE=colleague TK_CONFIG_FILE=$PWD/tk_toolkit_dual/config.local.json .venv/bin/python tk_toolkit_dual/tk_healthcheck.py
```

## 关键日志与状态文件

- `tk_toolkit_dual/dispatcher.colleague.log`
- `tk_toolkit_dual/dispatcher-runtime.colleague.log`
- `tk_toolkit_dual/launchd.colleague.out.log`
- `tk_toolkit_dual/launchd.colleague.err.log`
- `tk_toolkit_dual/.dispatcher_heartbeat.colleague.json`
- `tk_toolkit_dual/.dispatcher_metrics.colleague.json`

## 快速排查顺序

1. 看 launchd 是否在：

```bash
launchctl print gui/$(id -u)/com.tk-pipeline.dispatcher.colleague | sed -n '1,80p'
```

2. 看心跳：

```bash
cat tk_toolkit_dual/.dispatcher_heartbeat.colleague.json
```

3. 跑健康检查：

```bash
TK_INSTANCE=colleague TK_CONFIG_FILE=$PWD/tk_toolkit_dual/config.local.json .venv/bin/python tk_toolkit_dual/tk_healthcheck.py
```

4. 看最新日志：

```bash
tail -n 120 tk_toolkit_dual/dispatcher.colleague.log
```

## GitHub 上传前检查

```bash
python3 tools/release_safety_check.py
```
