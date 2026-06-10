# 多图宫格视频生成 Agent 系统提示词 v1

运行时提示词真源应写入飞书 `初始化-模型与API配置` 表：

- `多图宫格方案生成`
- `多图宫格图片生成`
- `多图宫格视频生成`

本文件是本地镜像，便于代码审查和人工同步。

## 多图宫格方案生成

见 `tk_toolkit_dual/tk_nine_grid_video_prompt.py` 的 `NINE_GRID_PLAN_SYSTEM_PROMPT`。

核心口径：

- JSON 是程序执行真源。
- Markdown 只作为人工审核稿。
- 第一版只支持 4/6/8/9 宫格；AI 方案未显式填写时默认 4 宫格。
- 布局映射：4 宫格=2x2，6 宫格=3x2，8 宫格=4x2，9 宫格=3x3。
- 每张 Board 的 cells 数必须等于宫格数量，默认全部 active。
- 多 Board 时，上一张最后一个 Cell 必须作为下一张第 1 个 Cell 的视觉衔接锚点。
- 产品演示型必须覆盖使用前、使用中、使用后。
- 文档直拆时由 `Cell N:` 数量推断宫格数量；显式选择与 Cell 数不一致时失败，不截断。

## 多图宫格图片生成

见 `tk_toolkit_dual/tk_nine_grid_video_prompt.py` 的 `NINE_GRID_IMAGE_SYSTEM_PROMPT`。

核心口径：

- 提示词不绑定供应商或模型。
- 只输出一段英文通用图片生成指令。
- 生成一张竖屏 9:16 的对应布局宫格分镜图，例如 2x2、3x2、4x2、3x3 storyboard grid。
- 参考图锁定人物、宠物、产品、环境；宫格图只承担叙事时间线。
- 方案中的 `dialogue_or_voiceover` 若包含泰语台词，使用冒号直接承接台词，不用英文引号包裹台词。

## 多图宫格视频生成

见 `tk_toolkit_dual/tk_nine_grid_video_prompt.py` 的 `NINE_GRID_VIDEO_SYSTEM_PROMPT`。

核心口径：

- 提示词不绑定供应商或模型。
- 只输出一段英文通用视频生成指令。
- 宫格图是叙事顺序参考，不是最终分屏布局。
- 视频 prompt 必须按 `Cell 1` 到 `Cell N` 的顺序组织，N 由宫格数量决定。
- 最终视频是一段连续竖屏 UGC 视频，不保留宫格边框、编号、文字或 UI。
- 人物/宠物说话写成 `The influencer says in Thai: ...`，画外旁白写成 `Thai voiceover: ...`，不要写成带英文引号的 dialogue。
- 音频要单独说明 dialogue、ambient noise、sound effects、voice tone/timbre；口播只进入音频层，不生成字幕或画面文字。
