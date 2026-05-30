# tk_toolkit_dual launchd usage

## Install / enable ryan auto-start service
bash /Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit_dual/install_launchd_instances.sh

## Disable / uninstall ryan
bash /Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit_dual/uninstall_launchd_instances.sh

## Manual status check
launchctl print gui/$(id -u)/com.ryan.tk-dispatcher.ryan | sed -n '1,120p'

## Manual restart
launchctl kickstart -k gui/$(id -u)/com.ryan.tk-dispatcher.ryan

## Manual health check
TK_INSTANCE=ryan TK_CONFIG_FILE=/Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit_dual/config.ryan.json /Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit/.venv312/bin/python /Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit_dual/tk_healthcheck.py
