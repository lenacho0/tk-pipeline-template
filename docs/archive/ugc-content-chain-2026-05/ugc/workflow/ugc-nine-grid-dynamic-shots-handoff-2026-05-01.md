# UGC 9宫格动态分镜链路接力说明（2026-05-01）

## 当前结论

2026-05-01 已将 UGC 分镜图链路从“固定 6宫格 / 固定 6 个镜头”升级为：

> 固定 3×3 9宫格容器 + 动态有效镜头数 N（1-9，默认优先 5-6）+ 只让 active panels 进入后续链路。

字段名为了避免大规模改表，暂时仍保留 `6宫格...` 相关字段；业务语义已经升级为 9宫格容器。

## 核心设计

- UGC-03 脚本生成不再固定 6 shots，支持 `1-9` 个有效镜头。
- 默认节奏偏好 `5-6` 个镜头，避免 9 段视频导致整体过长。
- UGC-04 固定生成 `3行x3列`：
  - 总画布：`9:16`
  - 每格：`9:16`
  - `1..N`：active story panels
  - `N+1..9`：inactive white placeholders
- UGC-05 会裁切全部 9 格用于检查，但只对 active panels 创建记录、上传、进入高清化和 UGC-06。
- 无效格会在本地后处理中强制刷白，避免模型不听话。

## 已完成代码改造

### `tk_toolkit_dual/tk_ugc_script_generate.py`

- 脚本生成从固定 6 shots 改为动态 `1-9`。
- 支持并标准化：
  - `optimal_shot_count`
  - `effective_shot_count`
  - `storyboard_grid_summary`
- 兼容旧 `six_grid_summary`。
- 默认提示：优先 `5-6` 个镜头，除非爆款结构强依赖更多阶段，否则不要超过 6。

### `tk_toolkit_dual/tk_ugc_six_grid.py`

- UGC-04 固定 `3行x3列` 9宫格容器。
- `task_type=UGC_9_GRID_STORYBOARD_DYNAMIC_SHOTS`。
- `combined_canvas_aspect_ratio=9:16`，`panel_aspect_ratio=9:16`。
- 出图后执行比例校验：总图和单格都必须接近 `9:16`。
- inactive panels 会被本地强制刷白。
- prompt 增加强约束：禁止边框、黑框、分割线、网格线、gutter、panel outline、comic-strip boxes。

### `tk_toolkit_dual/tk_ugc_shot_images.py`

- UGC-05 支持 `3行x3列` 裁切。
- 新增 `inset_cell_box()`：默认对每格轻微内缩裁切（约 1.2%，至少 2px），丢弃模型可能生成的黑色分割线/边框。
- 只为 active panels 创建 UGC-05 记录。
- 新增真正高清化方案 A：
  - 无黑边 crop = 主构图参考图
  - 完整 9宫格 = 一致性参考图
  - 精简 shot prompt = 语义约束
  - 通过 Feishu 临时下载 URL 放入 OTU `metadata.urls`
  - 调用 `UGC-分镜图片高清化` / `gpt-image-2` 做参考重绘
  - 模型返回图再本地适配为最终 `1080x1920`
- CLI 新增：

```bash
python3 tk_ugc_shot_images.py <UGC04_RECORD_ID> --write --enhance
```

## Prompt 文档

已更新：

- `docs/prompts/ugc-6-grid-storyboard-system-prompt-2026-04-30.md`

当前该文件实际为 `2026-05-01 v3` 的 9宫格动态分镜图生成审核稿。文件名暂未改，避免引用路径变更。

## 真实验证记录

### 9宫格生成验证

- 源 UGC-03：`recvieE3B2omPp`
- 新 UGC-04：`recvimPkZjza7b`
- 模型：OTU `gpt-image-2`
- metadata：`aspectRatio=9:16` / `panelAspectRatio=9:16`
- 返回图尺寸：`941x1672`
- 比例校验：通过，总图和单格比例约 `0.562799`，接近 `9:16=0.5625`
- inactive grids：`[7,8,9]`，已本地强制刷白

### 普通 UGC-05 active 裁切验证

曾创建一批 active 分镜记录：

- `recvimPZUPdKBU`
- `recvimQ0OkQeiH`
- `recvimQ1pciJNl`
- `recvimQ1YFdRtf`
- `recvimQ2CH3V2m`
- `recvimQ3g3KcCb`

后续发现九宫格有黑色分割线，已对这批记录做过无黑边内缩裁切覆盖；但它们早期高清图主要来自 resize，不建议作为下一阶段首选。

### 高清化方案 A 验证

用户确认方案 A 效果最好：

- 方案 A：crop + 9宫格 + 精简 shot prompt，基本保持原图一致。
- 方案 B：只指定 9宫格第 x 行第 y 列，不带 shot prompt，出现明显不一致。

因此正式采用方案 A。

新建并验证通过的 UGC-05 高清记录：

- `recvin7kJqxQuo`
- `recvin7Er2INZu`
- `recvin861Zu2yh`
- `recvin8p8l8dx0`
- `recvin8FNrUi0W`
- `recvin8XX3Z0Iw`

这 6 条均：

- `高清化状态=成功`
- `高清分镜图` 已写回
- 最终高清图尺寸：`1080x1920`

本地预览：

```text
tk_toolkit_dual/workspace_ryan/ugc_shot_image_work/recvimPkZjza7b/enhanced_repaint_916/enhanced_repaint_6shots_preview.png
```

## 测试门禁

2026-05-01 UGC 全量单测：

```bash
cd tk_toolkit_dual
python3 -m py_compile tk_ugc_shot_images.py test_ugc_shot_images.py
python3 -m unittest test_ugc_shot_images test_ugc_six_grid test_ugc_script_generate test_ugc_script_derive test_ugc_utils test_ugc_single_video_analyze -v
```

结果：57 项通过。

## 下次继续推进建议

### 1. 优先从 UGC-06 分镜视频生成继续

建议使用这批新的高清 UGC-05 记录作为输入：

- `recvin7kJqxQuo`
- `recvin7Er2INZu`
- `recvin861Zu2yh`
- `recvin8p8l8dx0`
- `recvin8FNrUi0W`
- `recvin8XX3Z0Iw`

不要优先使用旧的 resize 分镜记录。

### 2. 先检查 UGC-06 附件字段限制

此前 `UGC-06 分镜视频表` 的两个附件字段仍可能是扫码限制：

- `高清分镜图`
- `分镜视频`

如果仍为 `allowed_edit_modes.manual=false, scan=true`，API 写附件会失败。两个选择：

1. 在飞书 UI 修改附件字段上传属性；或
2. 先给 UGC-06 加文本兜底字段，例如：
   - `高清分镜图file_token`
   - `高清分镜图路径`
   - `分镜视频file_token`
   - `分镜视频URL`
   - `分镜视频路径`

### 3. UGC-06 技术注意

- OTU 图片高清化 `gpt-image-2` 使用 JSON + `metadata.urls`。
- OTU Veo 图生视频此前验证需要 `multipart/form-data` + `input_reference[]` 传首帧/参考帧，不要沿用图片高清化的 JSON `metadata.urls`。

## 当前状态一句话

UGC-03 → UGC-04 9宫格 → UGC-05 active 裁切 + 无黑边 + 参考重绘高清图 已真实跑通；下一步应从 6 条 `recvin...` 高清分镜记录进入 UGC-06 分镜视频生成。
