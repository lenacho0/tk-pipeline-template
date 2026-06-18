# Secret Transfer Checklist - 2026-06-18

Do not paste secrets into chat, Git, docs, logs, screenshots, or test snapshots.

## Files Not To Commit

These files are intentionally ignored and must stay local:

- `.env`
- `tk_toolkit_dual/config.panda.json`
- `tk_toolkit_dual/config.ryan.json`
- `tk_toolkit_dual/config.local.json`
- `.venv/`
- runtime logs and cache files
- generated media work directories

## Source Mac Values To Use Only As Reference

`tk_toolkit_dual/config.ryan.json` can be used as a shape reference, but Panda must replace:

- `feishu.app_id`
- `feishu.app_secret`
- `feishu.bitable_app_token`
- every old `feishu.tables.*` value after `rebind_copied_base.py`
- every old `config_records.*` value after `rebind_copied_base.py`

Do not use the old Base token or old table IDs in Panda production.

## Panda Values To Create Fresh

Create these in the new Feishu tenant:

- New Feishu Open Platform app ID.
- New Feishu Open Platform app secret.
- New Base token from the imported Panda Base URL.
- New table IDs discovered by `rebind_copied_base.py`.
- New config record IDs discovered by `rebind_copied_base.py`.

## Optional `.env` Variables

If the HHM integration is still needed, recreate these on Panda with new or approved values:

- `HHM_API_KEY`
- `HHM_BASE_URL`
- `HHM_TIMEOUT_SECONDS`
- `HHM_RETRY_COUNT`
- `HHM_CONCURRENCY`
- `HHM_OUTPUT_DIR`

## Safe Transfer Methods

Use one of these:

- 1Password or another password manager.
- AirDrop an encrypted archive and share the password out-of-band.
- Manual entry on Panda from the Feishu developer console and approved local secret source.

Avoid:

- Git commits.
- Chat messages.
- Shared docs.
- Terminal screenshots.
- Copying the entire source `~/.openclaw` or `~/.lark-cli` directories.

## Post-Transfer Verification

On Panda:

```bash
cd ~/workspace-tk-panda
python3 tools/release_safety_check.py
git status --short
```

Expected:

- Safety check passes.
- `config.panda.json` and `.env` do not appear as tracked files.
- No real credential file is staged.
