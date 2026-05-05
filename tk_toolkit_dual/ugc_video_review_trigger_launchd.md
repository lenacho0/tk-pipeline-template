# UGC-06 分镜视频审核/重生轮询器 launchd

## 作用

`com.ryan.ugc-video-review-trigger` 每 60 秒扫描 UGC-06 的分镜视频动作字段：

- `分镜视频操作=重新生成分镜视频` → 只重跑当前这一条 UGC-06 的图生视频
- `分镜视频操作=生成分镜视频` → 同样按当前 UGC-06 记录生成/覆盖视频

没有明确动作时不会调用视频模型。

## 用户操作

打开：

- `UGC-06 分镜视频表`
- 视图：`04-分镜视频审核与重生`

如果某条分镜视频不满意，在对应 UGC-06 行设置：

- `分镜视频操作=重新生成分镜视频`
- 可选：在 `分镜视频备注` 写原因

系统处理后会：

- 覆盖当前 UGC-06 的 `分镜视频` / `本地视频路径` / `分镜视频file_token` / `分镜视频URL`
- 设置 `视频生成状态=成功`
- 设置 `分镜视频审核状态=待确认`
- 复位 `分镜视频操作=不触发`
- 写入 `分镜视频执行状态/分镜视频执行结果`

不会影响其他 UGC-06 分镜视频，也不会自动重跑 UGC-07 成片合成。

## 文件

- plist：`tk_toolkit_dual/com.ryan.ugc-video-review-trigger.plist`
- 已安装副本：`~/Library/LaunchAgents/com.ryan.ugc-video-review-trigger.plist`
- 执行脚本：`tk_toolkit_dual/run_ugc_video_review_trigger.sh`
- 业务日志：`tk_toolkit_dual/ugc_video_review_trigger.log`
- launchd stdout：`tk_toolkit_dual/launchd.ugc-video-review-trigger.out.log`
- launchd stderr：`tk_toolkit_dual/launchd.ugc-video-review-trigger.err.log`

## 状态检查

```bash
launchctl print gui/$(id -u)/com.ryan.ugc-video-review-trigger
```

查看最近日志：

```bash
tail -80 /Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit_dual/ugc_video_review_trigger.log
```

## 手动跑一次

```bash
cd /Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit_dual
./run_ugc_video_review_trigger.sh
```

## 停用

```bash
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.ryan.ugc-video-review-trigger.plist
```
