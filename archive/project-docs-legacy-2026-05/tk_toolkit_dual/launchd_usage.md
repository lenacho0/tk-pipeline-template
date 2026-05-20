# TK Dispatcher launchd usage

## Install / enable auto-start
bash /Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit/install_launchd.sh

## Disable / uninstall
bash /Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit/uninstall_launchd.sh

## Manual status check
launchctl print gui/$(id -u)/com.ryan.tk-dispatcher | sed -n '1,120p'

## Manual restart
launchctl kickstart -k gui/$(id -u)/com.ryan.tk-dispatcher

## Manual health check
/Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit/.venv312/bin/python /Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit/tk_healthcheck.py
