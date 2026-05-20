# UGC / 内容链路字段命名债务清理（2026-05-05）

## 背景

内容链路已从旧 `UGC-04 6宫格` 语义升级为固定 3×3 `9宫格` 容器 + 动态有效镜头数 N（1-9）。飞书表名已改为 `内容-04 9宫格分镜表` 等，但字段名仍残留 `6宫格`，容易误导人工审核与后续维护。

代码层已在 commit `914d86f Prepare grid field rename compatibility` 做好兼容：

- 写入优先使用新字段名；
- 读取兼容旧字段名；
- prompt 配置 stage 优先 `UGC-9宫格分镜图生成`，兼容查找旧 `UGC-6宫格分镜图生成`；
- UGC-05 / UGC-06 链路兼容 `关联9宫格任务` 与旧 `关联6宫格任务`。

## 目标 Base

- Base token: `LBWUbgRfEavAgjsXNIhcpo0Dnvb`
- 内容-04 9宫格分镜表: `tblkCASP9y1yZ1Sa`
- 内容-05 分镜图片表: `tblW1KwMasPcXoaR`

## 待改字段

| 表 | field_id | 旧字段名 | 新字段名 | 类型 |
|---|---|---|---|---|
| 内容-04 | `fldrn0DIkP` | `6宫格提示词JSON` | `9宫格提示词JSON` | text |
| 内容-04 | `fldGsLAZY5` | `6宫格生成状态` | `9宫格生成状态` | select |
| 内容-04 | `fldQJdfvc5` | `6宫格图片` | `9宫格图片` | attachment |
| 内容-04 | `fldHx28iSL` | `6宫格图片URL` | `9宫格图片URL` | text |
| 内容-04 | `fldmS8sKBM` | `6宫格图片file_token` | `9宫格图片file_token` | text |
| 内容-05 | `fldwIkfpDu` | `关联6宫格任务` | `关联9宫格任务` | link |

## lark-cli dry-run 已验证

`lark-cli config bind --source openclaw --app-id cli_a93014c004799cd1 --identity bot-only` 已成功。

以下 `--dry-run` 已验证会生成正确 PUT 请求，但真实执行被飞书应用 scope 阻塞：

- 缺少读字段 scope: `base:field:read`
- 缺少更新字段 scope: `base:field:update`

开通地址来自 lark-cli 错误信息：

- `https://open.feishu.cn/app/cli_a93014c004799cd1/auth?q=base:field:read&op_from=openapi&token_type=tenant`
- `https://open.feishu.cn/app/cli_a93014c004799cd1/auth?q=base:field:update&op_from=openapi&token_type=tenant`

## 真实执行命令

> 注意：这是字段 rename，不删除字段；字段数据会保留。执行前确保应用已开 `base:field:update`。如需先复核字段结构，开 `base:field:read` 后串行执行 `+field-list`。

```bash
BASE=LBWUbgRfEavAgjsXNIhcpo0Dnvb
T4=tblkCASP9y1yZ1Sa
T5=tblW1KwMasPcXoaR

lark-cli base +field-update --base-token "$BASE" --table-id "$T4" --field-id fldrn0DIkP --json '{"type":"text","name":"9宫格提示词JSON"}'

lark-cli base +field-update --base-token "$BASE" --table-id "$T4" --field-id fldGsLAZY5 --json '{"type":"select","name":"9宫格生成状态","multiple":false,"options":[{"name":"待生成","hue":"Blue","lightness":"Lighter"},{"name":"生成中","hue":"Orange","lightness":"Light"},{"name":"成功","hue":"Green","lightness":"Light"},{"name":"失败","hue":"Red","lightness":"Light"}]}'

lark-cli base +field-update --base-token "$BASE" --table-id "$T4" --field-id fldQJdfvc5 --json '{"type":"attachment","name":"9宫格图片"}'

lark-cli base +field-update --base-token "$BASE" --table-id "$T4" --field-id fldHx28iSL --json '{"type":"text","name":"9宫格图片URL"}'

lark-cli base +field-update --base-token "$BASE" --table-id "$T4" --field-id fldmS8sKBM --json '{"type":"text","name":"9宫格图片file_token"}'

lark-cli base +field-update --base-token "$BASE" --table-id "$T5" --field-id fldwIkfpDu --json '{"type":"link","name":"关联9宫格任务","link_table":"内容-04 9宫格分镜表"}'
```

## 执行后验证

```bash
lark-cli base +field-list --base-token "$BASE" --table-id "$T4" --limit 100
lark-cli base +field-list --base-token "$BASE" --table-id "$T5" --limit 100
```

确认不再出现以下字段名：

- `6宫格提示词JSON`
- `6宫格生成状态`
- `6宫格图片`
- `6宫格图片URL`
- `6宫格图片file_token`
- `关联6宫格任务`

## 备注

`UGC风格要求` 暂不纳入本次字段改名。该字段属于 UGC 模式特定语义，在双模式内容链路中仍可作为 UGC 批次 handoff 字段保留；非 UGC 链路另有自己的 prompt / handoff 字段语义。
