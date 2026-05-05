# Storyboard Consistency Phase 2

目标：把“逐镜头一致性增强”从经验性 prompt 技巧，收敛成工程内稳定可复用的输入结构与 prompt 构造层。

## 本次落地内容

### 1. 新增一致性数据结构
文件：`src/types/storyboard.ts`

核心对象：
- `StoryboardConsistencySpec`
- `StoryboardShot`
- `StoryboardRenderPayload`
- `RenderPromptBundle`

这意味着后续无论是：
- Feishu 记录驱动
- Gemini 生成 shot script
- Sora / 图像模型出图

都可以围绕统一 payload 工作，而不是每个脚本自己拼 prompt。

---

### 2. 新增一致性 prompt 构造器
文件：`src/core/storyboard-consistency.ts`

当前策略：
- 默认单主角叙事
- 禁止新增明确配角
- 背景人物弱化
- 环境连续性约束
- 产品/风格/世界观锚点统一
- 统一 negative prompt 输出

这正对应第二轮方案中的 P0：
1. 单主角
2. 弱化其他人物
3. 环境连续性

---

### 3. 新增逐镜头失败分类错误码
文件：`src/core/error-codes.ts`

新增：
- `STORYBOARD_INVALID_CONFIG`
- `STORYBOARD_MISSING_ASSET`
- `STORYBOARD_PROMPT_BUILD_FAILED`
- `STORYBOARD_EMPTY_OUTPUT`
- `STORYBOARD_UPLOAD_FAILED`
- `STORYBOARD_WRITEBACK_FAILED`
- `STORYBOARD_RUNTIME_BUG`

说明：
这批错误码虽然服务于后续“失败分类”目标，但现在先建码表是对的。否则 worker/service 接进来时又会回到散乱字符串报错。

---

## 建议下一步接法

### 方案 A：先接逐镜头图片 worker
新增：
- `src/workers/storyboard-image.worker.ts`

最小职责：
1. 接收 `StoryboardRenderPayload`
2. 调 `buildStoryboardPromptBundle(payload)`
3. 逐 shot 调图像模型
4. 分类抛出 `AppError`
5. 回写 artifacts / Feishu

### 方案 B：先接逐镜头脚本生成
把 `shot_script_gen` 的输出直接约束成：
- `visual`
- `camera`
- `motion`
- `environment`
- `productFocus`
- `characterNotes`

这样进入图片阶段前，镜头语义就更稳定。

---

## 当前判断

如果你是按今天的第二轮方案继续推进，优先顺序我建议：

1. 先接 `storyboard-image.worker.ts`
2. 再补失败分类落盘/写回
3. 再做 analysis summary 质量校验

原因很简单：一致性问题最直接影响视觉结果，回报最大。
