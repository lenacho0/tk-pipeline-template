# TikTok Bitable Workflow - 方向 B 收口计划

## 目标
把当前“已能联调”的后半段链路，收口成更清晰的正式运行口径，尤其是脚本生成阶段的模型配置与 fallback 边界。

---

## 当前真实问题

### 1. `script_generate` 已可运行，但配置优先级不清晰
当前代码实际同时混用了：
- `config.json` 的 `llm.*`
- 表0 配置表里的 `模型名 / API 配置 / API Key / API 代理地址`
- 联调期 fallback 逻辑

结果是：
- 跑得起来，但正式口径不够清楚
- 一旦缺 key，会退到 fallback
- README 里没有把优先级说明写清楚

### 2. fallback 现在既承担“联调兜底”，又混在正式链路里
这对快速联调有效，但从工程视角看边界不够清楚。

### 3. `config.example.json` 与 README 仍偏模板态
还没有把“当前真实 Base / 表 / provider 配置策略”写成实际可执行口径。

---

## 收口原则

### 原则 1：脚本生成正式配置优先级必须明确
建议统一为：
1. **表0 配置表记录**（脚本生成环节）
   - `模型名`
   - `API Key`
   - `API 代理地址`
   - `API 配置`
2. **本地 `config.json` 兜底**
   - 仅当表0缺失相应字段时使用
3. **fallback 脚本生成**
   - 仅当正式 LLM 路径不可用时启用
   - 明确标记为 `联调兜底，不代表正式模型产出`

### 原则 2：fallback 必须显式，不应伪装成正式成功
建议在记录备注中明确写入：
- LLM 路径失败原因
- 已使用 fallback
- 当前结果仅用于联调流转验证

### 原则 3：README 必须与真实口径一致
README 需要补：
- 当前已打通的是后半段主干链路
- `script_generate` 当前存在 fallback 机制
- 表0 配置表优先级高于 `config.json`
- 还未打通前半段分析链路

---

## 建议落地动作

### B1. 配置优先级收口
在 `script_generate.py` 中显式整理：
- 表0 配置读取逻辑
- `config.json` 兜底逻辑
- fallback 进入条件

### B2. fallback 标记收口
统一备注写法，例如：
- `script_generate fallback: missing api_key`
- `script_generate fallback: llm init failed`

### B3. README / config.example 同步更新
补充：
- 正式配置优先级
- 联调 fallback 说明
- 当前项目真实状态

### B4. 后续可选
如果要进一步正式化，再补：
- Feishu 写回 retry/timeout 封装
- dispatcher 正式运行策略
- 把 fallback 开关做成显式配置项

---

## 当前建议执行顺序
1. 先改 `script_generate.py` 的配置优先级说明与 fallback 标记
2. 再改 `README.md`
3. 再改 `config.example.json`
4. 最后决定是否把 fallback 做成配置开关
