# tk_toolkit_dual launchd usage

## Install / enable both auto-start services
bash /Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit_dual/install_launchd_instances.sh

## Disable / uninstall both
bash /Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit_dual/uninstall_launchd_instances.sh

## Manual status check
launchctl print gui/$(id -u)/com.ryan.tk-dispatcher.ryan | sed -n '1,120p'
launchctl print gui/$(id -u)/com.ryan.tk-dispatcher.colleague | sed -n '1,120p'

## Manual restart
launchctl kickstart -k gui/$(id -u)/com.ryan.tk-dispatcher.ryan
launchctl kickstart -k gui/$(id -u)/com.ryan.tk-dispatcher.colleague

## Manual health check
TK_INSTANCE=ryan TK_CONFIG_FILE=/Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit_dual/config.ryan.json /Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit/.venv312/bin/python /Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit_dual/tk_healthcheck.py
TK_INSTANCE=colleague TK_CONFIG_FILE=/Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit_dual/config.colleague.json /Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit/.venv312/bin/python /Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit_dual/tk_healthcheck.py
