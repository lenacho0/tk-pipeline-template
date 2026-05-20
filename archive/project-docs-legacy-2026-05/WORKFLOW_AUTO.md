# WORKFLOW_AUTO.md — TK 内容自动化工作流

## 总览

UooTaPet TikTok 内容自动化 Pipeline，6 个环节 + 1 个同步 + 1 个调度器。
全部由飞书多维表格按钮触发，调度器后台轮询执行，零 token 消耗。

```
① 爆款抓取 → ② 脚本分析 → ③ 产品脚本生成 → ④ 分镜图生成 → [同步] → ⑤ 视频制作
```

## 飞书多维表格
- URL: https://my.feishu.cn/base/LBWUbgRfEavAgjsXNIhcpo0Dnvb
- app_token: LBWUbgRfEavAgjsXNIhcpo0Dnvb

## 表 ID 速查

| 表名 | table_id | 用途 |
|------|----------|------|
| 爆款数据表 | tblKNlGHJKwJWyRW | 存储抓取的爆款视频数据 |
| 脚本分析 | tblozrImDy0r4dBN | 视频脚本拆解结果 |
| 产品信息 | tblF2cZmbQEJMiUH | 产品基本信息 |
| 产品脚本生成 | tbl2Yp6T4jDN8Rfr | 生成的产品带货脚本 + 分镜图 |
| 模型与API配置 | tblPUVFtpjogYOGn | 各环节的模型、API、提示词配置 |
| 抓取配置 | tbl4cIPQYHSHbFzV | FastMoss 抓取参数 |
| 模特形象 | tblvpVOYockZmCG8 | 模特参考图片 |
| 视频制作 | tblQdTGSsmQbPMQd | Sora 视频生成任务 |

## 脚本清单

所有脚本位于 `~/.openclaw/workspace-tk/scripts/`

| 脚本 | 环节 | 触发字段 | 触发值 | 配置 record_id | 超时 |
|------|------|---------|--------|---------------|------|
| `tk_fetch.py` | ① 爆款视频抓取 | 执行状态 | 待执行 | recveiIeCBik6u | 600s |
| `tk_analyze.py` | ② 视频脚本分析 | 分析状态 | 待分析 | recveizDqAaxWy | 600s |
| `tk_script_gen.py` | ③ 产品脚本生成 | 生成状态 | 待生成 | recveizDqAB9Xo | 600s |
| `tk_storyboard.py` | ④ 九宫格分镜图 | 分镜图状态 | 待执行 | recveizDqA44fi | 600s |
| `tk_video.py` | ⑤ 视频制作 | 制作状态 | 待执行 | recveppNaVCcyd | 900s |
| `tk_sync_video.py` | 同步 | 同步状态 | 待同步 | — | — |
| `tk_dispatcher.py` | 调度器 | — | — | — | — |
| `common.py` | 公共模块 | — | — | — | — |

## 各环节详情

### ① 爆款视频抓取 (tk_fetch.py)
- 从 FastMoss API 抓取指定品类的爆款视频
- Token: 从飞书配置表读取
- 结果写入「爆款数据表」

### ② 视频脚本分析 (tk_analyze.py)
- 用 Gemini 分析爆款视频内容，拆解脚本结构
- 模型/API/提示词：从飞书配置表读取
- 结果写入「脚本分析」

### ③ 产品脚本生成 (tk_script_gen.py)
- 根据产品信息 + 爆款参考 + 提示词生成带货脚本
- 输出格式：分镜 X（时长 Xs）/ 画面 / 口播（泰文）/ 口播（中文）
- 结果写入「产品脚本生成」的「生成的脚本」字段

### ④ 九宫格分镜图 (tk_storyboard.py)
- 步骤1: gemini-2.5-flash 生成 9 个 shot prompts JSON → 写入「分镜图提示词」
- 步骤2: 组合 grid prompt → 写入「图片生成提示词」
- 步骤3: gemini-3.1-flash-image-preview 生成九宫格图片 → 写入「分镜图」附件
- 铁律：9:16 竖屏、白色边框、无编号、无文字标签、产品 EXACT visual copy

### 同步 (tk_sync_video.py)
- 扫描「产品脚本生成」表中分镜图状态=成功的记录
- 对比「视频制作」表，缺失的自动创建
- 自动填充：关联脚本、来源任务ID、选择产品、分镜图、脚本、视频时长
- 自动设为「制作状态=待执行」

### ⑤ 视频制作 (tk_video.py)
- Sora API: own-jarvis (https://own-jarvis-api.com/v1)
- 端点: POST /v1/videos (multipart/form-data) — 注意不是 /v1/video/generations
- 认证: Authorization 头直接放 API Key（不带 Bearer）
- **提示词优先级**: 飞书表格「视频提示词」字段 > 配置表模板自动生成
- 自动生成的提示词会写回「视频提示词」字段供老板检查修改
- 流程: 读配置 → 读任务 → 构建/读取提示词 → 下载分镜图 → 提交 Sora → 轮询 → 下载视频 → 上传飞书

## 调度器 (tk_dispatcher.py)

### 启动
```bash
cd ~/.openclaw/workspace-tk
nohup python3 scripts/tk_dispatcher.py >> scripts/dispatcher.log 2>&1 &
```

### 工作机制
- 30 秒轮询一次
- 检查 WATCH_LIST 中 5 个环节的触发状态
- 额外检查 check_video_sync()（同步状态=待同步）
- 发现触发值 → 子进程执行对应脚本 → 更新状态为成功/失败
- Token 每 90 分钟自动刷新

### 老板的操作
1. 在飞书多维表格点按钮 → 自动化设置触发值
2. 调度器自动执行 → 结果写回表格
3. 视频制作前可以在「视频提示词」字段编辑提示词

## 铁律
1. **飞书多维表格 = 唯一配置中心**（所有模型/API/提示词从飞书读取）
2. **产品形象必须与实物完全一致**
3. **分镜图竖屏 9:16 + 无文字叠加**
4. **禁止擅自更改模型名称**
5. **所有提示词必须在飞书表格中可见可编辑**
