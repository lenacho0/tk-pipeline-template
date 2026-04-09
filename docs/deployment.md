# 部署说明

## 1. 初始化环境

```bash
cd tk-pipeline-template
./scripts/setup.sh
```

这会：

- 创建 `.venv`
- 安装 `requirements.txt`
- 创建 `workspace/`

## 2. 准备个人配置

```bash
cp config/config.template.json config/config.alice.json
```

然后填写：

- 飞书应用 `app_id / app_secret`
- 你的多维表 `app token`
- 每张表的 `table_id`
- 每个配置环节在配置表里的 `record_id`
- `workspace`

## 3. 运行健康检查

```bash
TK_INSTANCE=alice \
TK_CONFIG_FILE="$PWD/config/config.alice.json" \
./scripts/tk_healthcheck.py
```

## 4. 手动启动 dispatcher

```bash
TK_INSTANCE=alice \
TK_CONFIG_FILE="$PWD/config/config.alice.json" \
./scripts/run_dispatcher.sh
```

## 5. 安装为 launchd 常驻任务

```bash
TK_INSTANCE=alice \
TK_CONFIG_FILE="$PWD/config/config.alice.json" \
./scripts/install_launchd.sh
```

卸载：

```bash
TK_INSTANCE=alice ./scripts/uninstall_launchd.sh
```

## 已在运行中的同事如何升级

```bash
cd tk-pipeline-template
git pull
./scripts/setup.sh
```

然后检查飞书副本是否已经补齐新字段：

- `产品脚本生成` 表新增 `结构化脚本JSON`

最后再执行一次健康检查：

```bash
TK_INSTANCE=alice \
TK_CONFIG_FILE="$PWD/config/config.alice.json" \
./scripts/tk_healthcheck.py
```
