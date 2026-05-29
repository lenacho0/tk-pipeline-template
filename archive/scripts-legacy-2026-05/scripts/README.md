# TK 独立脚本

零 Token 消耗的独立执行脚本。所有配置从飞书多维表格实时读取。

## 脚本列表

| 脚本 | 环节 | 飞书表 | 用法 |
|------|------|--------|------|
| `tk_fetch.py` | 爆款视频抓取 | 抓取配置表 | `python3 tk_fetch.py <record_id>` |
| `tk_analyze.py` | 视频脚本分析 | 脚本分析表 | `python3 tk_analyze.py <record_id>` |
| `tk_script_gen.py` | 产品脚本生成 | 产品脚本生成表 | `python3 tk_script_gen.py <record_id>` |
| `tk_storyboard.py` | 九宫格分镜图 | 产品脚本生成表 | `python3 tk_storyboard.py <record_id>` |

## 执行结果
- 成功 → 飞书表格对应记录状态更新为「成功」
- 失败 → 状态更新为「失败」+ 失败原因写入备注字段

## 示例
```bash
cd ~/.openclaw/workspace-tk/scripts

# 抓取视频
python3 tk_fetch.py recXXXXX

# 分析视频脚本
python3 tk_analyze.py recXXXXX

# 生成产品脚本
python3 tk_script_gen.py recXXXXX

# 生成分镜图
python3 tk_storyboard.py recXXXXX
```

## 配置
所有配置从飞书多维表格实时读取：
- 模型名称、API Key、代理地址、提示词 → 「模型与API配置」表
- 飞书凭证 → `~/.openclaw/config.json`
