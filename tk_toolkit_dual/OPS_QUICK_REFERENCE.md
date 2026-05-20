# TK Pipeline Dual 运维速查

## 1. 当前运行方式

当前旧 TK pipeline 主线由 `tk_toolkit_dual/` 承载，同一套代码跑两个 macOS `launchd` 实例：

- `com.ryan.tk-dispatcher.ryan`
- `com.ryan.tk-dispatcher.colleague`

`tk_toolkit/` 暂时保留，因为 dual launchd 仍复用其中的 `.venv312` Python 运行时。

---

## 2. 常用命令

### 安装 / 启用双实例自动守护

```bash
bash /Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit_dual/install_launchd_instances.sh
```

### 卸载 / 关闭双实例自动守护

```bash
bash /Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit_dual/uninstall_launchd_instances.sh
```

### 查看 launchd 状态

```bash
launchctl print gui/$(id -u)/com.ryan.tk-dispatcher.ryan | sed -n '1,120p'
launchctl print gui/$(id -u)/com.ryan.tk-dispatcher.colleague | sed -n '1,120p'
```

### 重启服务

```bash
launchctl kickstart -k gui/$(id -u)/com.ryan.tk-dispatcher.ryan
launchctl kickstart -k gui/$(id -u)/com.ryan.tk-dispatcher.colleague
```

### 手动启动 dispatcher

```bash
cd /Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit_dual
TK_INSTANCE=ryan TK_CONFIG_FILE=$PWD/config.ryan.json ./run_dispatcher_instance.sh
TK_INSTANCE=colleague TK_CONFIG_FILE=$PWD/config.colleague.json ./run_dispatcher_instance.sh
```

### 手动停止 dispatcher

```bash
cd /Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit_dual
TK_INSTANCE=ryan ./stop_dispatcher_instance.sh
TK_INSTANCE=colleague ./stop_dispatcher_instance.sh
```

---

## 3. 健康检查

### Ryan

```bash
TK_INSTANCE=ryan TK_CONFIG_FILE=/Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit_dual/config.ryan.json /Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit/.venv312/bin/python /Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit_dual/tk_healthcheck.py
```

### Colleague

```bash
TK_INSTANCE=colleague TK_CONFIG_FILE=/Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit_dual/config.colleague.json /Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit/.venv312/bin/python /Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit_dual/tk_healthcheck.py
```

### 心跳文件

```bash
cat /Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit_dual/.dispatcher_heartbeat.ryan.json
cat /Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit_dual/.dispatcher_heartbeat.colleague.json
```

心跳字段含义：

- `time`：最近心跳时间
- `status`：运行状态
- `note`：崩溃说明或附加说明
- `pid`：当时进程号

---

## 4. 关键日志与状态文件

### Ryan

- `/Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit_dual/dispatcher.ryan.log`
- `/Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit_dual/dispatcher-runtime.ryan.log`
- `/Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit_dual/launchd.ryan.out.log`
- `/Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit_dual/launchd.ryan.err.log`
- `/Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit_dual/.dispatcher_heartbeat.ryan.json`
- `/Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit_dual/.dispatcher_metrics.ryan.json`

### Colleague

- `/Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit_dual/dispatcher.colleague.log`
- `/Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit_dual/dispatcher-runtime.colleague.log`
- `/Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit_dual/launchd.colleague.out.log`
- `/Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit_dual/launchd.colleague.err.log`
- `/Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit_dual/.dispatcher_heartbeat.colleague.json`
- `/Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit_dual/.dispatcher_metrics.colleague.json`

---

## 5. 快速排查顺序

如果出现爆款抓取没动静、表格状态一直停在“待执行”、pipeline 某环节突然不跑，按这个顺序查。

### 第一步：看实例在不在

```bash
launchctl print gui/$(id -u)/com.ryan.tk-dispatcher.ryan | sed -n '1,80p'
launchctl print gui/$(id -u)/com.ryan.tk-dispatcher.colleague | sed -n '1,80p'
```

### 第二步：看心跳

```bash
cat /Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit_dual/.dispatcher_heartbeat.ryan.json
cat /Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit_dual/.dispatcher_heartbeat.colleague.json
```

### 第三步：跑健康检查

```bash
TK_INSTANCE=ryan TK_CONFIG_FILE=/Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit_dual/config.ryan.json /Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit/.venv312/bin/python /Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit_dual/tk_healthcheck.py
TK_INSTANCE=colleague TK_CONFIG_FILE=/Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit_dual/config.colleague.json /Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit/.venv312/bin/python /Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit_dual/tk_healthcheck.py
```

### 第四步：看最新日志

```bash
tail -n 120 /Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit_dual/dispatcher.ryan.log
tail -n 120 /Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit_dual/dispatcher.colleague.log
```

### 第五步：确认任务是否被捞起

关注日志里是否出现：

- `已启动任务`
- `完成`
- `失败`

---

## 6. 常见故障模式

### 状态一直待执行，没有动静

大概率原因：

- 对应 dispatcher 实例没在跑
- launchd 没拉起来
- 记录状态字段不匹配

优先检查 launchd 状态、heartbeat、dispatcher 日志。

### dispatcher 在跑，但任务还是不动

大概率原因：

- 表格读失败
- Feishu Bitable 异常
- 目标表字段或状态值不匹配

优先检查 `tk_healthcheck.py`、dispatcher 日志、表格里的状态字段值。

### 任务被启动了，但后面失败

大概率原因：

- 下游脚本自身报错
- 外部 API 异常
- 文件上传或写回失败

优先检查 dispatcher 日志、对应脚本输出和 `.retry_state.<instance>.json`。

---

## 7. 相关文件

- `tk_toolkit_dual/README_DUAL.md`
- `tk_toolkit_dual/launchd_usage_dual.md`
- `tk_toolkit_dual/com.ryan.tk-dispatcher.ryan.plist`
- `tk_toolkit_dual/com.ryan.tk-dispatcher.colleague.plist`
- `tk_toolkit_dual/install_launchd_instances.sh`
- `tk_toolkit_dual/uninstall_launchd_instances.sh`
