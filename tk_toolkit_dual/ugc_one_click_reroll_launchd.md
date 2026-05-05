# UGC 一键重生成轮询器 launchd

## 作用

`com.ryan.ugc-one-click-reroll` 每 60 秒检查一次 UGC-04：

- 如果有记录勾选 `一键重生成9宫格`，则调用真实图片模型，覆盖当前 UGC-04 记录的 9宫格结果，并同步重新切分/覆盖 UGC-05 单张分镜图。
- 如果没有勾选记录，只输出空结果，不调用模型。

## 文件

- plist：`tk_toolkit_dual/com.ryan.ugc-one-click-reroll.plist`
- 已安装副本：`~/Library/LaunchAgents/com.ryan.ugc-one-click-reroll.plist`
- 执行脚本：`tk_toolkit_dual/run_ugc_one_click_reroll.sh`
- 业务日志：`tk_toolkit_dual/ugc_one_click_reroll.log`
- launchd stdout：`tk_toolkit_dual/launchd.ugc-one-click-reroll.out.log`
- launchd stderr：`tk_toolkit_dual/launchd.ugc-one-click-reroll.err.log`

## 状态检查

```bash
launchctl print gui/$(id -u)/com.ryan.ugc-one-click-reroll
```

查看最近业务日志：

```bash
tail -80 /Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit_dual/ugc_one_click_reroll.log
```

## 手动跑一次

```bash
cd /Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit_dual
./run_ugc_one_click_reroll.sh
```

## 安装/重载

```bash
cp /Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit_dual/com.ryan.ugc-one-click-reroll.plist ~/Library/LaunchAgents/com.ryan.ugc-one-click-reroll.plist
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.ryan.ugc-one-click-reroll.plist 2>/dev/null || true
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.ryan.ugc-one-click-reroll.plist
launchctl kickstart -k gui/$(id -u)/com.ryan.ugc-one-click-reroll
```

## 停用

```bash
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.ryan.ugc-one-click-reroll.plist
```

## 注意

脚本默认使用 `/usr/bin/python3`，因为旧 dispatcher venv 缺少 `PIL`。已验证 `/usr/bin/python3` 可导入 PIL 并运行当前 UGC 脚本。
