# tk_toolkit_dual launchd usage

## Install / enable colleague auto-start service

```bash
PYTHON_BIN=$PWD/.venv/bin/python TK_CONFIG_FILE=$PWD/tk_toolkit_dual/config.local.json bash tk_toolkit_dual/install_launchd_instances.sh colleague
```

## Disable / uninstall

```bash
bash tk_toolkit_dual/uninstall_launchd_instances.sh colleague
```

## Manual status check

```bash
launchctl print gui/$(id -u)/com.tk-pipeline.dispatcher.colleague | sed -n '1,120p'
```

## Manual restart

```bash
launchctl kickstart -k gui/$(id -u)/com.tk-pipeline.dispatcher.colleague
```

## Manual health check

```bash
TK_INSTANCE=colleague TK_CONFIG_FILE=$PWD/tk_toolkit_dual/config.local.json .venv/bin/python tk_toolkit_dual/tk_healthcheck.py
```
