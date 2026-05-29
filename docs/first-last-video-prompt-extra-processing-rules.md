# 首尾帧表格提示词额外加工规则清单（收口前）

## 结论

本文记录的是收口前代码曾经对首尾帧提示词做过的额外加工规则，用于把仍然需要的规则迁移回首尾帧提示词源文档。

收口后，表格字段里的三个 prompt 保持文档真源；提交给首帧、尾帧、视频模型时不再额外拼接任何自然语言 prompt 文本。产品图、首帧图、尾帧图仍可作为参考图传入。

收口前，`首尾帧生视频提示词` 没有被代码额外改写，视频阶段直接使用表格字段内容提交。

收口前，代码额外加工主要发生在：

- `首帧生图提示词`
- `尾帧生图提示词`
- 首尾帧文档的结构化 Markdown 拆分清洗

## 1. 首帧生图提示词额外追加规则

触发位置：生成首帧图时。

代码会在原始 `首帧生图提示词` 前面额外追加产品参考说明。

### 1.1 产品参考图说明

如果有关联产品图，会追加类似规则：

```text
Reference image 1 = product reference. Keep the product packaging, bottle shape, sprayer, label layout, label text impression, color, logo, and proportions unchanged.
Use the product reference as a hard identity anchor, not optional inspiration. Do not redesign the product packaging.
```

如果有多张产品参考图，会按 `Reference image 1 / 2 / 3...` 追加。

### 1.2 产品身份锚点

还会追加产品名和包装一致性规则：

```text
Product identity anchor: {product_name}. Keep the product exactly as visible in Reference image 1: same packaging, bottle shape, sprayer, label layout, color, logo, and proportions.
Do not redesign the product packaging or change the label impression.
Never replace it with a generic pet spray brand or invented label such as pawradise, Pawradise, Pet Lily, Pet Care, PetX, PAWS, Paws, Odor Gone, Stain & Odor Remover, or any other unrelated brand.
```

### 1.3 尿味产品专属包装补充

如果产品名包含 `尿味` 或英文 `odor`，还会追加：

```text
Preserve the white trigger sprayer, white bottle body, yellow top label band, teal/green lower label, dog and cat illustration group, and the PET URINE ODOR DEODORIZING SPRAY label impression from the uploaded reference.
```

## 2. 尾帧生图提示词额外追加规则

触发位置：生成尾帧图时。

代码会在原始 `尾帧生图提示词` 前面额外追加“首帧编辑基准”和产品参考规则。

### 2.1 首帧作为编辑基准

```text
Vertical 9:16 portrait frame. Use the uploaded starting-frame image as the editing base; preserve the uploaded starting-frame aspect ratio and composition.

Reference image 1 = starting frame editing base. Keep the same camera angle, lighting, floor pattern, grout lines, hand identity, bottle placement logic, and scene continuity unless the ending-frame prompt explicitly changes them.
```

### 2.2 产品参考图说明

从第二张参考图开始，会追加：

```text
Reference image 2 = product identity reference. Keep the product packaging, bottle shape, sprayer, label layout, label text impression, color, logo, and proportions unchanged.
```

多张产品图会继续编号。

### 2.3 产品身份锚点

```text
Product identity anchor: {product_name}. Keep the product exactly as visible in the product reference image and consistent with the starting frame.
Do not redesign the bottle, label, nozzle, colors, logo, visible text impression, or packaging proportions.
Never replace it with a generic pet spray brand or invented label such as pawradise, Pawradise, Pet Lily, Pet Care, PetX, PAWS, Paws, Odor Gone, Stain & Odor Remover, or any other unrelated brand.
```

### 2.4 尿味产品专属包装补充

如果产品名包含 `尿味` 或 `odor`：

```text
Preserve the white trigger sprayer, white bottle body, yellow top label band, teal/green lower label, dog and cat illustration group, and the PET URINE ODOR DEODORIZING SPRAY label impression from the product reference.
```

## 3. 首尾帧视频提示词

当前没有发现视频阶段额外追加自然语言规则。

视频生成时直接读取：

```text
首尾帧生视频提示词
```

并作为 `prompt` 提交给 OTU / Veo。

但视频提交参数会额外传：

```text
seconds = 目标时长秒
size = 配置表画面尺寸
aspect_ratio = 配置表画面比例
input_reference[] = 首帧图
input_reference[] = 尾帧图
```

注意：代码没有把产品参考图作为视频阶段第三张参考图传入，但已有视频 prompt 里可能写了 “Use the uploaded product reference image...”，这会造成文档描述和实际视频输入不一致。

## 4. 结构化 Markdown 拆分清洗规则

如果上传的首尾帧文档是结构化 Markdown，代码会直接解析，不调用模型。

### 4.1 场景标题识别

场景标题格式：

```markdown
## S01 场景标题
```

### 4.2 子段落识别

子段落格式：

```markdown
### S01-1 首帧生图提示词
### S01-2 尾帧生图 / 编辑提示词
### S01-3 首尾帧图生视频提示词
```

代码按编号和标题关键词映射：

```text
Sxx-1 且标题包含“首帧” -> 首帧生图提示词
Sxx-2 且标题包含“尾帧” -> 尾帧生图提示词
Sxx-3 且标题包含“视频” -> 首尾帧生视频提示词
```

### 4.3 代码块提取

如果段落里有 Markdown 代码块，只提取代码块内部内容。

示例：

````markdown
```text
prompt content
```
````

### 4.4 中文拍摄理解截断

如果没有代码块，代码会去掉标题，并截断：

```text
中文拍摄理解
```

之后的内容。

也就是说，`中文拍摄理解` 不会进入三个提示词字段。

## 5. 非结构化文档的模型拆分规则

如果文档不是上述结构化 Markdown，代码会调用文本模型做拆分。

模型拆分提示词要求输出 JSON：

```json
{
  "first_frame_prompt": "用于 OTU/gpt-image-2 直接生成首帧图的完整英文提示词，9:16 vertical",
  "last_frame_prompt": "用于以上传首帧图为参考生成尾帧图的完整英文提示词，9:16 vertical",
  "video_prompt": "用于以上传首帧图和尾帧图为参考生成首尾帧视频的完整英文提示词"
}
```

拆分提示词里写了：

```text
请只抽取信息，不要改写创意，不要补充不存在的设定。
```

但只要走模型拆分，就仍存在模型改写、补充、压缩或遗漏的风险。

## 建议迁移到源文档里的规则

如果后续要取消代码层额外加工，建议把需要保留的规则直接写进首尾帧提示词文档，例如：

- 产品参考图编号说明
- 产品包装一致性约束
- 禁止改品牌 / 改标签
- 首帧作为尾帧编辑基准
- 尾帧保持首帧构图、光线、地面纹理、手部身份
- 视频阶段 8 秒完整动作节奏
- 泡沫必须完全覆盖尿渍后才能擦
- 擦拭阶段只允许一只擦拭手
- 禁止第二只手扶纸巾、压纸巾、整理纸巾或二次擦拭
