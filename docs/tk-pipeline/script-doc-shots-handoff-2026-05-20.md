# 脚本文档逐分镜生成表交接文档

更新时间：2026-05-21

## 背景

本次新增一条独立链路，用于把“已经生成好的完整脚本文档”自动解析成逐分镜记录，并让每条分镜独立生成：

- 分镜图
- 分镜视频
- MiniMax 口播音频
- 发布标题 / 标签 / 文案等发布信息

关键要求不是简单拆行，而是要处理脚本文档中的全局一致性资产：

- 宠物形象参考提示词
- 环境背景参考提示词
- 人类角色参考提示词
- 产品表中的产品资料和产品图片

分镜图生成时不能默认把所有参考图都上传给每一条分镜。必须根据每条分镜结构化结果判断：这一条到底需要产品图、宠物图、环境图、人类角色图中的哪些。

## 飞书表

已在 ryan Base 将原单表拆成 3 张表：

- `脚本文档-任务表`：`tblBC37ktQBHPLep`
- `脚本文档-参考资产表`：`tblFg33rvB7eCyzr`
- `脚本文档-分镜生产表`：`tbldPJLJhczlGzSt`

已写入：

- `tk_toolkit_dual/config.json`
- `tk_toolkit_dual/config.ryan.json`
- keys：
  - `feishu.tables.script_doc_tasks`
  - `feishu.tables.script_doc_reference_assets`
  - `feishu.tables.script_doc_shots`

建表脚本：

```bash
python3 tk_toolkit_dual/tk_create_script_doc_shots_table.py --update-config
```

该脚本是幂等的：同名表存在时跳过建表，只补缺失字段、补齐视图并回写配置。

## 记录类型

原先单表用 `记录类型` 区分三类记录；现在已拆成三张表，不再需要 `记录类型` 字段。

### 1. 文档母记录

用户入口。用户在 `脚本文档-任务表` 粘贴整篇脚本文档。

核心字段：

- `任务名称`
- `脚本文档标题`
- `脚本文档正文`
- `关联产品记录`：链接到现有产品表，推荐使用
- `关联产品` / `选择产品`：兼容文本兜底
- `分镜风格`
- `视频时长`
- `口播音色ID`
- `解析状态`
- `解析结果JSON`
- `解析后逐镜头脚本`
- `总分镜数`
- `解析错误信息`

触发方式：

- 把 `解析状态` 改成 `待解析`
- dispatcher 会调用：

```bash
python3 tk_script_doc_shots.py parse <record_id>
```

### 2. 参考底图记录

系统从脚本文档里解析出的全局一致性资产，写入 `脚本文档-参考资产表`。

核心字段：

- `关联任务`
- `父文档记录ID`
- `资产ID`
- `参考类型`：`pet` / `environment` / `human`
- `参考名称`
- `参考提示词`
- `参考图生成状态`
- `参考图`
- `参考图file_token`
- `参考图本地路径`
- `参考图审核状态`
- `参考图修改要求`
- `错误信息`

触发方式：

- 把 `参考图生成状态` 改成 `待生成`
- dispatcher 会调用：

```bash
python3 tk_script_doc_shots.py reference-image <record_id>
```

重要规则：

- 参考底图生成后默认 `参考图审核状态=待确认`
- 只有 `参考图审核状态=通过` 的底图，才允许被分镜图生成使用
- 不通过时，可以填写 `参考图修改要求` 后重新生成

### 3. 分镜记录

系统批量创建到 `脚本文档-分镜生产表`，一行对应一个分镜。

核心字段：

- `关联任务`
- `父文档记录ID`
- `批次ID`
- `分镜序号`
- `总分镜数`
- `分镜原文`
- `口播文本`
- `目标时长秒`
- `画面描述`
- `人物描述`
- `场景描述`
- `产品焦点`
- `连续性要求`
- `结构化分镜JSON`
- `图片提示词`
- `视频提示词`
- `需要产品参考图`
- `参考资产ID列表`
- `参考图选择原因`
- `分镜图生成状态`
- `口播音频状态`
- `视频生成状态`
- `发布视频标题`
- `发布视频标签`
- `发布文案`
- `发布状态`

2026-05-21 字段整理补充：

- `视频生成模型` 已改为单选：`默认（配置表）` / `veo3.1` / `seeddance2.0`。
- `视频生成模型=默认（配置表）`、`默认`、`待确认` 都按配置表默认视频模型执行。
- `视频生成时间`、`生成时间` 已改为 `datetime`；`分镜图生成时间` 维持 `datetime`。
- 新建分镜记录时 `口播音频状态` 一律默认 `不触发`。即使有 `口播文本`，也不会自动生成 MiniMax 音频；用户需要音频时，手动改为 `待生成`。
- `发布平台` 字段仍保留兼容旧数据/排错，但日常 `04-发布素材` 视图不再展示，只在 `99-排错` 或全字段系统视图中保留。

`脚本文档-分镜生产表` 日常视图：

- `01-分镜图生成`：任务、分镜序号、画面描述、图片提示词、产品/参考资产需求、分镜图状态、分镜图和错误信息。
- `02-口播音频`：口播文本、口播音频状态、音频附件/下载链接和错误信息。
- `03-分镜视频`：分镜图、视频提示词、目标时长、视频生成模型、视频状态、视频附件/URL 和错误信息。
- `04-发布素材`：发布标题、文案、标签、发布状态；不展示 `发布平台`。
- `99-排错`：错误字段、raw JSON、file token、本地路径、任务 ID、实际 prompt、模型响应 JSON、`发布平台`。
- 原 `Grid View` 已重命名为 `99-全字段系统视图`，用于全字段排错，不作为日常入口。

## 参考图选择规则

这是本链路最关键的设计点。

每条分镜记录里有两个字段决定分镜图生成时上传哪些参考图：

- `需要产品参考图`
- `参考资产ID列表`

规则：

- 如果 `需要产品参考图=是`，从产品表读取 `产品图片` 作为参考图。
- 产品表读取优先级：
  - 母记录 `关联产品记录`
  - 母记录 `关联产品`
  - 母记录 `选择产品`
  - 分镜记录自身的产品字段兜底
- 如果 `参考资产ID列表` 包含某些 asset id，只上传这些资产对应的参考底图。
- 如果某个被点名的参考底图不存在、没有附件、或 `参考图审核状态` 不是 `通过`，该分镜图生成会拒绝继续，并写回明确错误。
- 不会默认上传所有宠物 / 环境 / 人类 / 产品图。

相关实现：

- `tk_toolkit_dual/tk_script_doc_shots.py`
  - `collect_reference_images_for_shot()`
  - `build_reference_prompt_note()`
  - 解析母任务从任务表读取，参考资产/分镜分别写入独立表
- `tk_toolkit_dual/tk_shot_storyboard.py`
  - `render_script_doc_shot()` 从任务表读取父任务、从参考资产表读取已审核底图、向分镜生产表写回分镜图

## Dispatcher 接入

ryan dispatcher 已重启并确认加载以下 5 个新 watch：

- `脚本文档解析拆分`：监听任务表
- `脚本文档参考底图生成`：监听参考资产表
- `脚本文档口播音频生成`：监听分镜生产表
- `脚本文档分镜图生成`：监听分镜生产表
- `脚本文档分镜视频生成`：监听分镜生产表

日志确认位置：

```bash
tail -n 80 tk_toolkit_dual/dispatcher-runtime.ryan.log
```

启动日志里应包含：

```text
监控环节: ... 脚本文档解析拆分, 脚本文档参考底图生成, 脚本文档口播音频生成, 脚本文档分镜图生成, 脚本文档分镜视频生成 ...
```

## 命令入口

解析整篇脚本文档（record_id 来自 `脚本文档-任务表`）：

```bash
python3 tk_toolkit_dual/tk_script_doc_shots.py parse <文档母记录ID>
```

生成参考底图（record_id 来自 `脚本文档-参考资产表`）：

```bash
python3 tk_toolkit_dual/tk_script_doc_shots.py reference-image <参考底图记录ID>
```

生成脚本文档分镜图（record_id 来自 `脚本文档-分镜生产表`）：

```bash
python3 tk_toolkit_dual/tk_shot_storyboard.py render <分镜记录ID> --table script_doc
```

生成脚本文档分镜口播音频（record_id 来自 `脚本文档-分镜生产表`）：

```bash
python3 tk_toolkit_dual/tk_shot_voiceover.py <分镜记录ID> --table script_doc
```

生成脚本文档分镜视频（record_id 来自 `脚本文档-分镜生产表`）：

```bash
python3 tk_toolkit_dual/tk_shot_video.py <分镜记录ID> --table script_doc
```

## 本次新增 / 修改文件

新增：

- `tk_toolkit_dual/tk_script_doc_shots.py`
- `tk_toolkit_dual/tk_create_script_doc_shots_table.py`
- `tk_toolkit_dual/test_script_doc_shots.py`

修改：

- `tk_toolkit_dual/common.py`
- `tk_toolkit_dual/config.json`
- `tk_toolkit_dual/config.ryan.json`
- `tk_toolkit_dual/config.json.template`
- `tk_toolkit_dual/tk_dispatcher.py`
- `tk_toolkit_dual/tk_shot_storyboard.py`
- `tk_toolkit_dual/tk_shot_video.py`
- `tk_toolkit_dual/tk_shot_voiceover.py`
- `memory/2026-05-20.md`

注意：工作区本来已有一些未提交改动，例如 `tk_toolkit_dual/tk_shot_storyboard.py`、`tk_toolkit_dual/tk_shot_video.py`、相关测试文件等。本次实现是在这些现有改动基础上继续追加，没有回退用户已有内容。

## 验证记录

已运行并通过：

```bash
python3 -m unittest \
  tk_toolkit_dual/test_script_doc_shots.py \
  tk_toolkit_dual/test_shot_video.py \
  tk_toolkit_dual/test_shot_voiceover.py \
  tk_toolkit_dual/test_handwritten_shot_script_gen.py -v
```

结果：

- 46 个测试通过

已运行并通过：

```bash
env PYTHONPYCACHEPREFIX=/private/tmp/workspace-tk-pycache \
python3 -m compileall -q \
  tk_toolkit_dual/tk_script_doc_shots.py \
  tk_toolkit_dual/tk_create_script_doc_shots_table.py \
  tk_toolkit_dual/tk_shot_storyboard.py \
  tk_toolkit_dual/tk_shot_video.py \
  tk_toolkit_dual/tk_shot_voiceover.py \
  tk_toolkit_dual/tk_dispatcher.py \
  tk_toolkit_dual/common.py
```

dispatcher 导入检查通过：

```bash
python3 -c 'import sys; sys.path.insert(0, "tk_toolkit_dual"); import tk_dispatcher; print(len(tk_dispatcher.WATCH_LIST)); print([w["name"] for w in tk_dispatcher.WATCH_LIST if "脚本文档" in w["name"]])'
```

输出确认有 5 个脚本文档 watch。

2026-05-20 拆表后补充验证：

- `脚本文档-任务表`：18 字段；视图 `01-用户入口`、`99-解析排错`
- `脚本文档-参考资产表`：13 字段；视图 `01-参考图确认`、`99-参考图排错`
- `脚本文档-分镜生产表`：54 字段；视图 `01-分镜图生成`、`02-口播音频`、`03-分镜视频`、`04-发布素材`、`99-排错`
- ryan dispatcher 已重启，启动日志确认脚本文档 5 个 watch 已加载

## 真实 smoke test

2026-05-20 已用真实脚本文档完成 smoke test。

任务记录：

- `脚本文档-任务表` record_id：`recvk8uUo5tb4o`
- 批次ID：`SCRIPTDOC-20260520134303-o5tb4o`
- 解析状态：`成功`
- 总分镜数：`2`

参考资产：

- `pet_1`：`recvk8vXfX8vhi`，参考图生成 `成功`，审核 `通过`，file_token `VPeXbi7jlo4i7YxG2CuccQaSn9g`
- `env_1`：`recvk8vXfXHS4V`，参考图生成 `成功`，审核 `通过`，file_token `AFqJbOJQYoeU9kxfFWQcHrTHn9g`

分镜记录：

- 分镜 1：`recvk8vXL2vhL4`
  - `需要产品参考图=否`
  - `参考资产ID列表=pet_1,env_1`
  - 分镜图生成 `成功`
  - 口播音频 `成功`
  - 视频 `不触发`
- 分镜 2：`recvk8vXL2JSsU`
  - `需要产品参考图=是`
  - `参考资产ID列表=pet_1,env_1`
  - 分镜图生成 `成功`
  - 口播音频 `成功`
  - 分镜视频 `成功`
  - 视频 task_id：`models/veo-3.1-fast-generate-preview/operations/zzctwataj7ubchannel5096`
  - 本地视频：`/Users/ryanlynn/.openclaw/workspace-tk/shot_video_work/recvk8vXL2JSsU/recvk8vXL2JSsU_video.mp4`
  - 飞书视频 file_token：`C3UGbM8Olox6UTxBoSlctsnon04`
  - `ffprobe`：`720x1280`，`4.000000s`

关键验证点：

- 分镜 1 分镜图生成日志 `reference_count=2`
- 分镜 2 分镜图生成日志 `reference_count=3`
- 证明 `需要产品参考图` 与 `参考资产ID列表` 生效：不是每条分镜默认上传所有参考图。

smoke test 中修复的问题：

- `safe_download_attachment()` 返回 `True` 时，参考图路径曾被错误写成字符串 `"True"`；已改为布尔返回时使用目标本地路径。
- 直接 OpenAPI 写 URL 字段时，`分镜视频URL` 不能写裸字符串；已改为 `{"link": url, "text": url}`。

当前仍建议下一步做一条完整用户真实脚本文档，不再用 smoke test 样本。

## 后续真实业务测试建议

建议下一步按以下顺序做 smoke test：

1. 在 `脚本文档-任务表` 新建一条任务记录
2. 填：
   - `任务名称`
   - `脚本文档标题`
   - `脚本文档正文`
   - `关联产品记录`
   - `分镜风格`
   - `视频时长`
   - `口播音色ID`
3. 设置 `解析状态=待解析`
4. 确认系统生成：
   - `脚本文档-参考资产表` 若干参考底图记录
   - `脚本文档-分镜生产表` 若干分镜记录
5. 先挑参考资产表记录生成底图，人工审核通过
6. 挑两条参考需求不同的分镜：
   - 一条只需要宠物/环境
   - 一条需要产品图
7. 分别设置 `分镜图生成状态=待生成`
8. 检查两条分镜实际上传的参考图集合是否不同，并确认画面一致性
9. 如需 MiniMax 音频，再对其中一条分镜手动设置 `口播音频状态=待生成`
10. 最后跑 `视频生成状态=待生成`

## 新开对话接续提示

如果新开对话，可以直接这样说：

```text
请读取 docs/tk-pipeline/script-doc-shots-handoff-2026-05-20.md，
继续推进脚本文档逐分镜生成表的真实 smoke test。
重点验证每条分镜按 `需要产品参考图` 和 `参考资产ID列表` 精确选择参考图。
```
