# UGC-05 审核推进轮询器 launchd

## 作用

`com.ryan.ugc-review-trigger` 每 60 秒扫描 UGC-05 的人工确认动作：

- `分镜图审核状态=通过` + `分镜图操作=确认分镜图并高清化` → 运行高清化
- `高清图审核状态=通过` + `高清图操作=生成分镜视频` → 创建 UGC-06 并运行图生视频

没有明确动作时不会调用模型。

## 文件

- plist：`tk_toolkit_dual/com.ryan.ugc-review-trigger.plist`
- 已安装副本：`~/Library/LaunchAgents/com.ryan.ugc-review-trigger.plist`
- 执行脚本：`tk_toolkit_dual/run_ugc_review_trigger.sh`
- 业务日志：`tk_toolkit_dual/ugc_review_trigger.log`
- launchd stdout：`tk_toolkit_dual/launchd.ugc-review-trigger.out.log`
- launchd stderr：`tk_toolkit_dual/launchd.ugc-review-trigger.err.log`

## 状态检查

```bash
launchctl print gui/$(id -u)/com.ryan.ugc-review-trigger
```

查看最近日志：

```bash
tail -80 /Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit_dual/ugc_review_trigger.log
```

## 手动跑一次

```bash
cd /Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit_dual
./run_ugc_review_trigger.sh
```

## 停用

```bash
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.ryan.ugc-review-trigger.plist
```
