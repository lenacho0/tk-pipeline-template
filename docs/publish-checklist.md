# 发布前检查清单

在把这个仓库发给同事之前，建议你过一遍下面清单。

## 不要提交的内容

- 任何真实 `app_secret`
- 任何真实 `bitable_app_token`
- 任何真实 API Key
- 任何 `config/config.<name>.json`
- 日志、PID、heartbeat、缓存文件
- `workspace/` 里的业务产物

## 建议你确认的内容

- [ ] `config/config.template.json` 仍然是纯模板
- [ ] `config/config.sample.json` 没有真实密钥
- [ ] `docs/bitable-schema.md` 与当前脚本依赖字段一致
- [ ] `docs/deployment.md` 里的命令可以直接复制运行
- [ ] `scripts/setup.sh` 能在新机器上创建 `.venv`
- [ ] `scripts/run_dispatcher.sh` / `install_launchd.sh` 使用的是相对路径

## 交给同事时要说明的东西

- 需要自己创建飞书应用
- 需要自己创建独立多维表
- 需要自己填写 `config/config.<name>.json`
- 首次先跑健康检查，再启动 dispatcher
