# Panda Codex Execution Guide - 2026-06-18

This guide is for the Panda computer. It assumes the source Mac keeps running the old Base and old `ryan.*` dispatcher instances during setup.

## Goal

Create a separate Panda shadow environment using a new Feishu tenant, new Feishu account, new Feishu app, new Base, and a separate local project checkout. Do not migrate OpenClaw.

## 1. Install Tools

```bash
npm install -g @openai/codex @larksuite/cli
codex --version
lark-cli --version
```

Expected baseline from the source Mac:

- `@openai/codex` was `0.137.0`
- `@larksuite/cli` was `1.0.47`

Newer versions are acceptable, but if a command fails, record the version in the migration notes.

## 2. Clone Project

```bash
git clone -b codex/unified-ai-route-slots https://github.com/lenacho0/tk-pipeline-template.git ~/workspace-tk-panda
cd ~/workspace-tk-panda
bash tk_toolkit_dual/setup_local.sh
```

## 3. Prepare New Feishu Tenant

In the new Feishu tenant:

- Create a new Feishu Open Platform app.
- Record the new `app_id` and `app_secret` in a local secret store.
- Enable and publish the permissions required for Base/Bitable read-write, Drive/media upload-download, and IM notification.
- Add the new app as a collaborator/document app for the new Base after the Base is imported.

Do not commit the app credentials.

## 4. Create New Base

Use the source Mac export artifact:

- Preferred first pass: import a `.base` file exported with structure only.
- If the structure-only import misses required operational rows, import a structure-and-data snapshot and then clean historical task rows in the new Base.

After import:

- Copy the new Base URL.
- Extract the token from `/base/<token>`.
- Confirm these table names survived import:
  - `初始化-模型与API配置`
  - `初始化-音色库`
  - `初始化-口播音频生成`
  - `初始化-产品信息`
  - `初始化-模特形象`
  - `003-脚本文档生产表`
  - `004-故事板视频生成表`
  - `005-多图九宫格视频生成表`
  - `008-图生视频生成表`
  - `002-首尾帧视频生成表`
  - `001-多角色首尾帧生成表`
  - `006-视频编辑任务表`

## 5. Configure `config.panda.json`

```bash
cd ~/workspace-tk-panda
cp tk_toolkit_dual/config.json.template tk_toolkit_dual/config.panda.json
```

Edit `tk_toolkit_dual/config.panda.json`:

- Set `feishu.app_id` to the new app ID.
- Set `feishu.app_secret` to the new app secret.
- Set `feishu.bitable_app_token` to the new Base token.
- Leave old table IDs as placeholders; the rebind step will rewrite them.

Run:

```bash
.venv/bin/python tk_toolkit_dual/rebind_copied_base.py \
  --config tk_toolkit_dual/config.panda.json --write
```

Expected result:

- `ready` is `true`.
- `missing_tables` is empty.
- `missing_config_records` is empty.
- `feishu.tables.*` now contains new `tbl...` IDs from the Panda Base.
- `config_records.*` now contains new `rec...` IDs from the Panda Base.

## 6. Configure `lark-cli`

```bash
lark-cli config init --new
lark-cli config default-as user
lark-cli config strict-mode off
lark-cli auth login --domain base --no-wait --json
```

Complete the login in the browser or Feishu client, then finish the device flow as instructed by `lark-cli`.

Verify access:

```bash
lark-cli base +table-list --as user --base-token <NEW_BASE_TOKEN> --limit 5
```

## 7. Health Check

```bash
cd ~/workspace-tk-panda
TK_INSTANCE=panda TK_CONFIG_FILE="$PWD/tk_toolkit_dual/config.panda.json" \
  .venv/bin/python tk_toolkit_dual/tk_healthcheck.py
```

Do not proceed until the health check can read the new Base.

## 8. Start Panda Dispatcher Against New Table IDs Only

Print the new table IDs:

```bash
python3 - <<'PY'
import json
cfg = json.load(open("tk_toolkit_dual/config.panda.json"))
for k, v in cfg["feishu"]["tables"].items():
    print(k, v)
PY
```

Start Panda instances:

```bash
for t in $(python3 - <<'PY'
import json
cfg = json.load(open("tk_toolkit_dual/config.panda.json"))
for v in cfg["feishu"]["tables"].values():
    if isinstance(v, str) and v.startswith("tbl"):
        print(v)
PY
); do
  PYTHON_BIN="$PWD/.venv/bin/python" TK_CONFIG_FILE="$PWD/tk_toolkit_dual/config.panda.json" \
    bash tk_toolkit_dual/install_launchd_instances.sh panda "$t"
done
```

Verify:

```bash
launchctl list | rg 'com.tk-pipeline.dispatcher.panda.'
```

For one or two table IDs:

```bash
tail -n 80 tk_toolkit_dual/dispatcher.panda.<NEW_TABLE_ID>.log
cat tk_toolkit_dual/.dispatcher_heartbeat.panda.<NEW_TABLE_ID>.json
```

## 9. Shadow Test

Use only low-risk test records in the new Panda Base:

- Create one small task in the new Base.
- Confirm status updates.
- Confirm generated attachments upload to the new Base.
- Confirm logs do not show permission errors.
- Confirm old Base and old source Mac continue running independently.

## 10. Final Cutover Later

Do not perform final cutover during shadow setup. After Panda is stable:

- Decide which unfinished or failed rows need a final incremental copy.
- Point new human task entry to the Panda Base.
- Then stop old `ryan.*` dispatcher instances.
- Keep the old Base as read-only archive until Panda has run reliably.
