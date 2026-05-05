# TikTok Bitable Workflow - 方向 B 最终收口（2026-04-21）

## 收口目标
将后半段链路从“联调可跑”收口到“正式模型路径已验证、配置口径清晰、fallback 边界明确”。

---

## 一、已完成事项

### 1. 正式配置优先级已明确
当前 `script_generate` 的正式配置优先级为：

1. **表0 配置表**（脚本生成环节）
   - `模型名 / 模型名称`
   - `API Key`
   - `API 代理地址`
   - `API配置`
2. **本地 `config.json` 兜底**
3. **fallback 联调兜底**

该口径已同步到：
- `tiktok_bitable_workflow/README.md`
- `tiktok_bitable_workflow/config.example.json`
- `tiktok_bitable_workflow/stages/script_generate.py`
- `docs/tiktok-bitable-direction-b-closure-plan.md`

### 2. `script_generate` 的 runtime mode 已显式化
当前代码已区分：
- `formal_llm`
- `fallback_only`

运行时会记录：
- `runtime_mode`
- `source`
- `model`
- `has_api_key`

### 3. fallback 已从“主路径”退回为“联调兜底”
当前 fallback 不再伪装成普通成功，而是通过备注明确标记：
- `script_generate fallback: ...`

并且开始/成功状态语义也已收紧：
- `script_generate started`
- `script_generate success (formal_llm)`

### 4. 正式 LLM 路径已真实验证成功
2026-04-21 已完成一次真实验证：
- record: `recvhplDKL51Fz`
- source: `bitable:recvhkwG00ECUj`
- model: `gemini-3.1-pro-preview`
- runtime_mode: `formal_llm`

实际结果：
- 能从表0读取 `API Key` 与 `API 代理地址`
- 能成功初始化 client
- 能成功调用模型
- 能拿到返回结果
- 能成功写回表6

这意味着：
**脚本生成已不再依赖 fallback 才能运行。**

### 5. 文档已同步更新
已落地文档：
- `docs/tiktok-bitable-current-status-2026-04-21.md`
- `docs/tiktok-bitable-direction-b-closure-plan.md`
- `docs/tiktok-bitable-direction-b-final-closure.md`

---

## 二、本次方向 B 的核心成果

### 工程层面
- 配置来源不再混乱
- runtime mode 不再隐性
- fallback 与 formal_llm 的边界已清晰

### 业务层面
- 后半段链路不只是“能联调”
- 而是已经具备“正式脚本模型路径可用”的基础

---

## 三、仍未纳入本次方向 B 范围的事项
以下不属于本次方向 B 最终收口完成范围：

### 1. 前半段分析链路
- 单视频分析
- 共性分析

### 2. 真正执行层
- 分镜图生成
- 图片生成
- 图生视频执行
- 最终拼接

### 3. 更深的工程治理
- 统一 requests retry/timeout 封装
- dispatcher 正式运行策略
- 更系统的异常码/状态机治理

---

## 四、最终结论

**方向 B 可以视为阶段性完成。**

更准确地说：
- `script_generate` 的正式配置优先级已经收清楚
- fallback 已明确退回联调兜底
- 正式 LLM 路径已经被真实验证成功
- 文档、README、配置模板、代码语义已基本一致

因此，后续如果继续推进，优先级已经可以自然切到：
1. 前半段分析链路接入
2. 执行层接入
3. 更深的工程治理
