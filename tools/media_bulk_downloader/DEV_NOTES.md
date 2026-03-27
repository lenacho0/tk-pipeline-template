# Media Bulk Downloader — 开发记录与后续改造说明

## 1. 项目目标

这个工具的目标是做一个**本地批量下载社媒媒体内容**的小工具，优先服务日常高频抓取需求。

### 初始要求
- 批量下载 Instagram 视频/媒体内容
- 后续扩展到：
  - TikTok
  - YouTube
  - 抖音
  - 小红书
- 强调：
  - 简单
  - 稳定
  - 成功率高
  - 不要经常失败
  - 日常使用方便

---

## 2. 接口选型

开发初期评估了两类接口：
- `Media Downloader API`
- `Playlist Downloader API`

### 选型结论
第一版主链路使用：
- **Media Downloader API**

### 原因
- 更适合单条链接逐条处理的批量任务
- 容错更容易做
- 更适合记录每条任务的状态
- 更适合失败重跑
- 更适合 Instagram / TikTok 这种单条内容解析下载场景

### Playlist Downloader API 的定位
暂时没有作为主链路，只保留作未来扩展：
- 适合作者主页、合集、话题页、列表页批量抓取
- 如果未来要做整页采集，再作为 fallback 或增强方案接入

---

## 3. 真实接口定位过程

开发过程中，一开始对真实 API 地址判断有误，导致第一次真实请求返回 404。

### 错误阶段
初版误用了错误的 base URL / path，结果：
- 解析失败
- 真实请求 404

### 后续修正
通过直接抓文档页内容、提取示例代码与 curl 样例，最终确认：

### 正确接口
- Base URL: `https://api.meowload.net`
- Endpoint: `/openapi/extract/post`

### 关键请求头
- `x-api-key`
- `accept-language: zh`

### 请求体
```json
{
  "url": "https://example.com/post-url"
}
```

这是整个工具从“骨架”变成“可真实下载”的关键修正。

---

## 4. 代码目录与落地位置

正式目录固定为：

`/Users/ryanlynn/.openclaw/workspace-tk/tools/media_bulk_downloader/`

### 重要约束
后续所有与本工具有关的新文件，都应继续放在：
- `~/.openclaw/workspace-tk/`

### 不要再使用
- `~/.openclaw-autoclaw/`

这是一个明确要求，之前已经踩过坑。

---

## 5. 核心文件结构

### CLI 与核心逻辑
- `cli.py`：命令行入口
- `config.py`：配置与 `.env` 读取
- `models.py`：数据结构
- `provider.py`：对接 Meowload API
- `downloader.py`：文件下载逻辑
- `io_utils.py`：输入读取、去重、结果写入

### 日常化脚本
- `run_daily.sh`：读取队列文件并批量执行
- `run_web.sh`：通过终端启动本地网页端

### 网页端
- `web_app.py`：本地 HTTP 服务
- `web/index.html`：网页 UI
- `web/app.css`：样式
- `web/app.js`：交互逻辑

### macOS 双击启动器
- `Start Media Bulk Downloader.command`
- `Stop Media Bulk Downloader.command`

### 文档
- `README.md`
- `QUICKSTART.md`
- `DEV_NOTES.md`（本文件）

---

## 6. 开发过程演进

### 阶段 1：CLI 骨架
先构建了一个 Python CLI 版本，具备：
- txt / csv / 直接 urls 输入
- URL 标准化
- 去重
- 基本下载逻辑
- 结果清单输出
- 失败重试

### 阶段 2：真实联调
用户提供了真实测试链接：
- 4 条 Instagram reel
- 1 条 TikTok 视频

### 联调结果
最终验证成功：
- **5/5 下载成功**

这一步确认了：
- 接口可用
- 下载逻辑可用
- 真实链路成立

### 阶段 3：日常化改造
为了降低使用门槛，补充了：
- `inbox/urls.txt`
- `run_daily.sh`
- 自动归档输入队列
- 固定输出目录

这使工具从“开发脚本”升级为“日常可用的小工具”。

### 阶段 4：输出结构优化
最初视频文件和结果报表混在一起，容易误解 `results.csv` 就是下载产物。

### 优化后结构
每次输出目录内：
- 视频文件在平台子目录：
  - `instagram/`
  - `tiktok/`
- 报表统一放在：
  - `_meta/results.csv`
  - `_meta/failed.csv`
  - `_meta/summary.json`

这个调整显著提升了可理解性。

### 阶段 5：最小可用网页端
基于现有 Python 工具，新增了一个本地网页端，功能包括：
- 页面粘贴链接
- 一键开始下载
- 状态展示
- 结果展示
- 输出目录显示

### 阶段 6：网页端增强
继续补了两个高频动作：
- `Open Output Folder`
- `Rerun Failed`

网页端因此从“能看结果”提升为“可顺手日用”。

### 阶段 7：双击启动
为了避免每次手动敲终端命令，增加了 macOS 双击启动器：
- 双击启动网页端
- 双击停止网页端

---

## 7. 当前功能现状

### 已完成
- CLI 可用
- Web UI 可用
- 双击启动可用
- Instagram / TikTok 已真实验证下载成功
- 支持失败重跑
- 支持打开输出目录
- 支持批量输入
- 输出结构清晰
- 文档已整理

### 当前更适合的场景
- 本地个人使用
- 中小规模批量抓取
- 日常高频下载需求
- 为后续 pipeline 集成做准备

---

## 8. 关键设计决策

### 为什么先做 Python CLI
原因：
- 易于快速实现
- 易于做重试和文件落盘
- 易于对接本地脚本和 pipeline
- 易于后续再包一层网页端

### 为什么网页端做成本地版
原因：
- 开发快
- 不需要部署
- 风险低
- 适合当前单人日常使用场景

### 为什么没有一开始就做完整产品化 Web
因为当前目标是：
- 尽快可用
- 稳定
- 降低操作成本

而不是马上做：
- 登录
- 多用户
- 数据库存储
- 服务端部署
- 完整任务中心

---

## 9. 开发过程中踩过的坑

### 坑 1：写到了错误目录
一开始误把工具写进了：
- `~/.openclaw-autoclaw/...`

后来迁移到正确目录：
- `~/.openclaw/workspace-tk/...`

### 坑 2：接口路径误判
初版用了错误的 base URL/path，导致 404。
后续通过抓文档示例修正到了真实地址。

### 坑 3：Python 3.9 兼容问题
初版使用了：
- `@dataclass(slots=True)`

本机 Python 不支持，后续去掉 `slots=True` 修正兼容性。

### 坑 4：README 自动编辑失败
有一次自动编辑 README 没命中原文，出现 edit failed 提示。
后续通过整体重写 README 收干净。

### 坑 5：不该进入 git 的运行文件被提交
曾误提交：
- `.DS_Store`
- `archive/*`
- `inbox/urls.txt`

后续做了：
- `.gitignore`
- git tracking 清理

---

## 10. 当前运行前提

### CLI / Web UI 的共同前提
- 本地存在 `.env`
- 机器能联网访问 API
- Python 运行环境可用

### `.env` 文件位置
`/Users/ryanlynn/.openclaw/workspace-tk/.env`

### 示例
```env
HHM_API_KEY=your_api_key_here
HHM_BASE_URL=https://api.meowload.net
HHM_TIMEOUT_SECONDS=30
HHM_RETRY_COUNT=3
HHM_CONCURRENCY=3
HHM_OUTPUT_DIR=downloads
```

### Web UI 当前性质
- 本地运行
- 地址：`http://127.0.0.1:8765`
- 不是云部署版
- 不是公网服务

---

## 11. 当前推荐使用方式

### 方式 A：双击启动网页端（推荐）
双击：
- `Start Media Bulk Downloader.command`

停止时双击：
- `Stop Media Bulk Downloader.command`

### 方式 B：终端启动网页端
```bash
bash /Users/ryanlynn/.openclaw/workspace-tk/tools/media_bulk_downloader/run_web.sh
```

然后访问：
```bash
http://127.0.0.1:8765
```

### 方式 C：CLI 批量模式
把链接写到：
- `inbox/urls.txt`

然后执行：
```bash
bash /Users/ryanlynn/.openclaw/workspace-tk/tools/media_bulk_downloader/run_daily.sh
```

---

## 12. 输出结构说明

每次任务会写入一个时间戳目录，例如：

`/Users/ryanlynn/.openclaw/workspace-tk/downloads/media_bulk/20260327_110500/`

或网页端：

`/Users/ryanlynn/.openclaw/workspace-tk/downloads/media_bulk_web/20260327_110500/`

### 目录内容
- `instagram/`：Instagram 视频文件
- `tiktok/`：TikTok 视频文件
- `_meta/`：任务报表

### `_meta/` 内文件
- `results.csv`
- `failed.csv`
- `summary.json`

---

## 13. git 与仓库清洁规则

### 已加入忽略规则的内容
- `.DS_Store`
- `.env`
- `downloads/`
- `tools/media_bulk_downloader/archive/`
- `tools/media_bulk_downloader/inbox/urls.txt`
- `__pycache__/`
- `*.pyc`

### 后续注意
不要把以下内容重新提交进 git：
- 运行时输入文件
- 归档队列
- 下载产物
- 本地环境变量文件
- 系统临时文件

---

## 14. 如果后续要继续升级，优先建议

### 高优先级
1. 历史批次列表
   - 网页里查看过去跑过的任务

2. 更直观的文件操作
   - 可点击定位视频文件
   - 可直接打开单个结果

3. 文件命名优化
   - 平台 + 标题/ID + 时间戳

4. 平台定制选择策略
   - 更聪明地选最优资源

### 中优先级
5. YouTube / 抖音 / 小红书专项适配
6. Playlist API fallback
7. 更细的错误分类与提示

### 低优先级 / 后期
8. 后台常驻服务
9. 局域网 / 服务器部署
10. 完整任务管理界面

---

## 15. 后续接手改造时必须先知道的事

如果未来要修改、扩展、重构这个工具，优先记住这几个点：

1. 正式目录是：
   - `~/.openclaw/workspace-tk/tools/media_bulk_downloader/`

2. 真实接口是：
   - `https://api.meowload.net/openapi/extract/post`

3. 认证头：
   - `x-api-key`

4. 报表目录：
   - `_meta/`

5. Web UI 是本地服务：
   - `127.0.0.1:8765`

6. 不要再往 autoclaw 目录写

7. 不要再把运行文件提交进 git

---

## 16. 当前总结

这个工具已经从一个“临时脚本需求”演化成一个：
- 本地可用
- 已真实验证
- 可日常操作
- 可网页化使用
- 可继续扩展的平台型下载工具

它目前仍然偏轻量，但架构已经足够支撑后续继续做：
- 改造
- 升级
- 扩平台
- 接 pipeline

后续修改时，优先保持两件事：
- **简单好用**
- **稳定高成功率**
