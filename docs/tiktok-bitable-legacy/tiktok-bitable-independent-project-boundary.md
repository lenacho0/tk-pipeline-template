# TikTok 多维表工作流 - 独立新项目边界约束

> 更新时间：2026-04-21
> 决策状态：已确认
> 结论：**本项目按“完全独立新项目”推进，不挂接旧 tkpipeline，不直接落到 `tk_toolkit_dual` 正式链路。**

---

## 1. 最终边界

本轮 TikTok 多维表工作流项目，和历史上的 tkpipeline / `tk_toolkit_dual` 项目 **彻底区分**。

这不是：
- 旧项目的小改版
- 在旧 dispatcher 上加几个 stage
- 在旧表结构上顺手扩几个字段
- 复用旧项目的正式运行入口

而是：

**一个全新的、独立的 TikTok 多维表工作流项目。**

---

## 2. 独立的含义

“完全独立”在这里不是一句口头说法，而是工程边界：

### 2.1 目录独立
后续代码应放在新的独立目录下，例如：
- `tiktok_bitable_workflow/`
或其他明确新目录名

**不直接写进 `tk_toolkit_dual/`。**

### 2.2 dispatcher 独立
后续若需要调度器：
- 用新的 dispatcher
- 新的状态字段
- 新的运行入口

**不直接接旧 `tk_dispatcher.py` 正式链路。**

### 2.3 表口径独立
虽然业务上也使用飞书多维表，但：
- 字段设计按新项目目标定义
- 状态字段按新项目定义
- 不为了兼容旧链路而被动复用旧命名

### 2.4 配置与 prompt 口径独立
- 新项目有自己的一套 prompt 输入协议
- 新项目有自己的配置组织方式
- 不默认依赖旧项目配置记录 ID 或旧 stage 名称

### 2.5 运行安全独立
- 新项目的实验、联调、失败，不应污染旧生产链路
- 新项目的任务状态，不应触发旧项目 watcher
- 新项目的表记录，不应被旧项目脚本误消费

---

## 3. 可以参考，但不能耦合

旧 tkpipeline / `tk_toolkit_dual` 仍然可以作为：
- 架构参考
- 经验参考
- 错误教训参考
- 某些通用工具函数写法参考

但只限于“参考”。

**不能直接默认：**
- 复用旧脚本作为正式实现
- 挂到旧 dispatcher
- 直接把新字段塞进旧运行表里
- 让新链路和旧链路共用一套任务状态机

一句话：

**可借鉴，不挂接。**

---

## 4. 对前面文档的解释口径

前面已经产出的几份文档中，有一部分内容是“以现有 `tk_toolkit_dual` 代码结构为参照，讨论如果接进去该怎么做”。

现在边界已经确认后，这些文档的正确理解方式应调整为：

- 那些关于 `tk_toolkit_dual` 的内容，**仅保留为参考对照分析**
- 不作为本项目正式实施路径
- 本项目正式实施时，应改为新目录、新脚本、新调度入口

也就是说：
- 设计原则仍然可用
- 字段思想仍然可用
- prompt 协议仍然可用
- 但“接旧代码”的落地路径，作废

---

## 5. 本项目后续推荐目录结构

建议后续改为类似：

```text
tiktok_bitable_workflow/
  README.md
  common.py
  dispatcher.py
  config.py
  stages/
    variant_plan.py
    script_generate.py
    storyboard_generate.py
    image_prompt_generate.py
    video_prompt_generate.py
  prompts/
    script_generate.md
    storyboard_generate.md
  schemas/
    script_multivariant_protocol.json
  tests/
```

重点是：

- 新项目目录独立
- 阶段脚本独立
- prompt 模板独立
- schema 独立
- 测试目录独立

---

## 6. 本项目后续命名原则

为了彻底避免串线，建议统一采用新前缀或新项目名。

例如：
- `tbw_dispatcher.py`
- `tbw_variant_plan.py`
- `tbw_script_generate.py`

或者：
- `tiktok_bitable_dispatcher.py`
- `tiktok_bitable_script_generate.py`

总之：

**不要继续沿用 `tk_*.py` 作为正式新项目命名。**

因为这会天然把新项目伪装成旧项目的一个分支，后面很容易混。

---

## 7. 对我接下来工作的约束

从现在开始，我后续如果继续做代码：

### 必须遵守
- 新建独立目录
- 新建独立脚本
- 新建独立 dispatcher
- 新建独立运行口径
- 不直接修改 `tk_toolkit_dual` 作为新项目正式实现

### 不应再做
- 不再继续输出“如何挂接到 `tk_toolkit_dual`”作为正式方案
- 不再把 `tk_script_gen.py` 当成目标落点
- 不再默认共用旧状态字段或旧 stage 名称

---

## 8. 正式实施口径（生效）

后续本项目的正确推进方式应是：

1. 保留前面已经沉淀的业务设计成果：
   - 多版本派生规则
   - 表6 字段规格
   - prompt 输入协议

2. 放弃“接旧 tkpipeline”的工程路径

3. 改为：
   - 新目录
   - 新脚本
   - 新 dispatcher
   - 新状态机
   - 新项目级 README / schema / prompt 组织

---

## 9. 一句话结论

**这个 TikTok 多维表工作流，从现在起按“完全独立新项目”执行。旧 tkpipeline 只作为参考资料，不作为正式落地底座。**
