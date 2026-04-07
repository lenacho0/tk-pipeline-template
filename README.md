# TK Pipeline 团队模板仓库

这是一套可分发给同事独立部署的 `OpenClaw + 飞书多维表 + TK Pipeline` 模板仓库。

目标：

- 每位同事使用自己的电脑
- 每位同事使用自己的飞书应用机器人
- 每位同事使用自己独立的多维表
- 共享同一套 Python 脚本、调度器逻辑和表结构约定

## 仓库结构

- `scripts/`：核心 pipeline 脚本与调度器
- `config/`：配置模板与个人配置文件
- `docs/`：接入文档、多维表说明、launchd 使用方式
- `workspace/`：本地运行产物目录，不提交业务文件

## 推荐接入方式

1. `git clone` 本仓库
2. 在飞书开放平台创建你自己的应用并拿到 `app_id / app_secret`
3. 新建你自己的飞书多维表，并按 `docs/bitable-schema.md` 建表
4. 复制 `config/config.template.json` 为 `config/config.<你的名字>.json`
5. 填入你自己的飞书凭证、表 ID、配置 record_id、工作目录
6. 运行 `./scripts/setup.sh`
7. 运行 `TK_INSTANCE=<你的实例名> TK_CONFIG_FILE=$PWD/config/config.<你的名字>.json ./scripts/tk_healthcheck.py`
8. 通过 `./scripts/run_dispatcher.sh` 手动启动，验证没问题后再安装 launchd

## 最常用命令

```bash
cd tk-pipeline-template

./scripts/setup.sh

TK_INSTANCE=alice \
TK_CONFIG_FILE="$PWD/config/config.alice.json" \
./scripts/tk_healthcheck.py

TK_INSTANCE=alice \
TK_CONFIG_FILE="$PWD/config/config.alice.json" \
./scripts/run_dispatcher.sh
```

## 配置文件建议

- `config/config.template.json`：仓库保留的基础模板
- `config/config.sample.json`：给同事看的填写示例
- `config/config.<name>.json`：每个人自己的本地配置，不提交 Git

## 重要原则

- 不要把真实 `app_secret`、表 token、API Key 提交进 Git
- 每个人都维护自己的 `config/config.<name>.json`
- `workspace/`、日志、缓存、heartbeat 都只保存在本地
- 表结构尽量统一，避免脚本依赖被人随手改掉

## 你可以怎么给同事发

- 最推荐：一个私有 Git 仓库
- 次选：打一个 zip 包

如果以后你更新流程，只要更新仓库脚本和文档，同事拉取新版本后保留自己的 `config/config.<name>.json` 即可。
