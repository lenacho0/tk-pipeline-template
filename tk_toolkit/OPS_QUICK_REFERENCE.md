# TK Pipeline 运维速查

## 1. 现在的运行方式

TK dispatcher 现在已经接入 macOS `launchd` 自动守护。

### 服务名
- `com.ryan.tk-dispatcher`

### 特性
- 自动启动
- 自动拉起
- 不需要每天手动启动

---

## 2. 常用命令

### 安装 / 启用自动守护
```bash
bash /Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit/install_launchd.sh
```

### 卸载 / 关闭自动守护
```bash
bash /Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit/uninstall_launchd.sh
```

### 手动查看 launchd 状态
```bash
launchctl print gui/$(id -u)/com.ryan.tk-dispatcher | sed -n '1,120p'
```

### 手动重启服务
```bash
launchctl kickstart -k gui/$(id -u)/com.ryan.tk-dispatcher
```

### 手动启动 dispatcher（非 launchd 方式）
```bash
bash /Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit/run_dispatcher.sh
```

### 手动停止 dispatcher（非 launchd 方式）
```bash
bash /Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit/stop_dispatcher.sh
```

---

## 3. 健康检查

### 跑一遍健康巡检
```bash
/Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit/.venv312/bin/python /Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit/tk_healthcheck.py
```

### 检查 dispatcher 心跳
```bash
cat /Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit/.dispatcher_heartbeat.json
```

### 心跳字段含义
- `time`: 最近心跳时间
- `status`: 运行状态（如 `running` / `crashed`）
- `note`: 崩溃说明或附加说明
- `pid`: 当时进程号

---

## 4. 关键日志与状态文件

### 主日志
- `/Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit/dispatcher.log`

### launchd 输出日志
- `/Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit/launchd.out.log`
- `/Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit/launchd.err.log`

### 运行中任务状态
- `/Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit/.running_tasks.json`

### 重试状态
- `/Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit/.retry_state.json`

### dispatcher 心跳
- `/Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit/.dispatcher_heartbeat.json`

### 每日统计
- `/Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit/.dispatcher_metrics.json`

---

## 5. 快速排查顺序

如果出现：
- 爆款抓取没动静
- 表格状态一直停在“待执行”
- pipeline 某环节突然不跑

按这个顺序查：

### 第一步：看 dispatcher 在不在
```bash
launchctl print gui/$(id -u)/com.ryan.tk-dispatcher | sed -n '1,80p'
```

或者：
```bash
cat /Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit/.dispatcher_heartbeat.json
```

### 第二步：看健康检查
```bash
python3 /Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit/tk_healthcheck.py
```

### 第三步：看最新日志
```bash
tail -n 120 /Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit/dispatcher.log
```

### 第四步：看有没有任务真的被捞起
关注日志里是否出现：
- `🚀 已启动任务`
- `✅ 完成`
- `❌ 失败`

### 第五步：看是不是 Feishu / Bitable 异常
重点关注这些报错：
- `code=1254002 msg=Fail`
- `Read timed out`
- `SSL EOF`
- `获取飞书 Token 失败`

---

## 6. 现在常见故障模式

### 故障模式 A：状态一直待执行，没有动静
大概率原因：
- dispatcher 没在跑
- dispatcher 掉线了
- launchd 没拉起来

优先检查：
- launchd 状态
- heartbeat
- dispatcher.log

### 故障模式 B：dispatcher 在跑，但任务还是不动
大概率原因：
- 表格读失败
- Feishu Bitable 异常
- 目标表字段状态不匹配

优先检查：
- `tk_healthcheck.py`
- `dispatcher.log`
- 表格里的状态字段值是否正确

### 故障模式 C：任务被启动了，但后面失败
大概率原因：
- 下游脚本自身报错
- 外部 API 异常
- 文件上传或写回失败

优先检查：
- `dispatcher.log`
- 对应脚本日志输出
- `.retry_state.json`

---

## 7. 任务触发的关键规则

### 爆款抓取
- 表：`TABLE_FETCH_CONFIG`
- 状态字段：`执行状态`
- 触发值：`待执行`
- 运行中：`抓取中`
- 脚本：`tk_fetch.py`

如果某条爆款抓取任务不动，首先确认：
- dispatcher 活着
- 那条记录的 `执行状态` 真的等于 `待执行`

---

## 8. 当前已做的稳定性增强

已经做了这些：
- dispatcher 顶层 crash 兜底
- heartbeat 心跳文件
- healthcheck 增强
- 启停脚本清理 heartbeat
- launchd 自动守护

这意味着现在比以前更容易：
- 发现掉线
- 自动恢复
- 查最后崩溃信息

---

## 9. 当前仍需注意的风险

虽然现在已经加了自动守护，但还不是绝对无敌。

仍需关注：
- Feishu / Bitable 波动
- token 刷新失败
- 网络超时
- 下游脚本逻辑错误

所以现在的状态是：
- **不容易悄悄死掉**
- 但外部依赖异常仍可能影响任务执行

---

## 10. 出现问题时最短处理法

### 如果你只想先恢复服务
```bash
launchctl kickstart -k gui/$(id -u)/com.ryan.tk-dispatcher
```

### 如果你想先快速看它是不是活着
```bash
cat /Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit/.dispatcher_heartbeat.json
```

### 如果你想先看最近到底报了什么错
```bash
tail -n 120 /Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit/dispatcher.log
```

---

## 11. 相关文件

### launchd 配置
- `tk_toolkit/com.ryan.tk-dispatcher.plist`

### 安装脚本
- `tk_toolkit/install_launchd.sh`

### 卸载脚本
- `tk_toolkit/uninstall_launchd.sh`

### 本文档
- `tk_toolkit/OPS_QUICK_REFERENCE.md`
