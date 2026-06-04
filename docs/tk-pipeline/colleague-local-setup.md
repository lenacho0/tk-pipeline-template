# 同事本地运行 TK Pipeline

本说明用于私有 GitHub 仓库交付。同事本地会连接一套独立复制的飞书多维表格 Base，并通过 macOS `launchd` 常驻运行 dispatcher。

## 1. clone 私有仓库

```bash
git clone <private-repo-url> workspace-tk
cd workspace-tk
```

## 2. 准备飞书开放平台应用

创建或复用一个飞书开放平台自建应用，把应用凭证填入后面的 `config.local.json`：

- `feishu.app_id`
- `feishu.app_secret`

应用需要能读取/写入多维表格记录、字段、附件，以及上传/下载云空间媒体。若需要健康检查主动发飞书消息，再补 IM 发消息权限并填写通知用户 `open_id`。

## 3. 复制飞书 Base

在飞书 UI 中复制当前完整 Base。复制时要保留：

- 业务表结构和视图
- `初始化-模型与API配置`
- `初始化-产品信息`
- `初始化-模特形象`
- `初始化-音色库`
- 其他初始化表和配置记录

首次交付不建议用代码从零建 Base，因为当前建表脚本只覆盖部分业务表；复制完整 Base 更稳。

## 4. 本地初始化

```bash
bash tk_toolkit_dual/setup_local.sh
```

然后编辑：

```bash
tk_toolkit_dual/config.local.json
```

至少填写：

- `feishu.app_id`
- `feishu.app_secret`
- `feishu.bitable_app_token`

`bitable_app_token` 是复制后 Base URL 中 `/base/` 后面的 token。

## 5. 重映射复制 Base

```bash
.venv/bin/python tk_toolkit_dual/rebind_copied_base.py --config tk_toolkit_dual/config.local.json --dry-run
```

确认 `ready=true` 后写回：

```bash
.venv/bin/python tk_toolkit_dual/rebind_copied_base.py --config tk_toolkit_dual/config.local.json --write
```

脚本会：

- 按表名发现新 Base 的 `table_id`
- 按 `初始化-模型与API配置.环节` 发现新的配置 `record_id`
- 清空本地 `products` 映射，避免沿用旧 Base 的产品 record_id

## 6. 健康检查

```bash
TK_INSTANCE=colleague TK_CONFIG_FILE=$PWD/tk_toolkit_dual/config.local.json .venv/bin/python tk_toolkit_dual/tk_healthcheck.py
```

如果飞书 token 或表字段检查失败，优先确认：

- 飞书应用权限是否已发布/生效
- 应用是否有复制 Base 权限
- `config.local.json` 的 Base token 是否填错
- 复制 Base 中是否保留了初始化配置表和关键业务表

## 7. 安装 launchd 常驻

```bash
PYTHON_BIN=$PWD/.venv/bin/python TK_CONFIG_FILE=$PWD/tk_toolkit_dual/config.local.json bash tk_toolkit_dual/install_launchd_instances.sh colleague
```

查看状态：

```bash
launchctl print gui/$(id -u)/com.tk-pipeline.dispatcher.colleague | sed -n '1,120p'
```

查看心跳：

```bash
cat tk_toolkit_dual/.dispatcher_heartbeat.colleague.json
```

查看日志：

```bash
tail -n 120 tk_toolkit_dual/dispatcher.colleague.log
```

卸载：

```bash
bash tk_toolkit_dual/uninstall_launchd_instances.sh colleague
```

## 8. 上传 GitHub 前安全检查

在推送前运行：

```bash
python3 tools/release_safety_check.py
```

该检查会拦截真实配置、`.env`、本机绝对路径和媒体产物。真实配置只保留在本机，不提交到仓库。
