# This tool has been migrated to the shared layer

This bulk media downloader is no longer the preferred primary copy in `workspace-tk`.

## New shared location
`/Users/ryanlynn/.openclaw/skills/media_bulk_downloader`

## Why
It was reclassified as a **shared tool capability**, not a tk-only workflow.
Multiple agents may use it, so the canonical copy now lives in the shared skills layer.

## Use this instead
### CLI
```bash
cd /Users/ryanlynn/.openclaw/skills
python3 -m media_bulk_downloader.cli --help
```

### Web UI
```bash
bash /Users/ryanlynn/.openclaw/skills/media_bulk_downloader/run_web.sh
```

## Notes
- Prefer passing explicit `--env-file`
- Prefer passing explicit `--output`
- Avoid adding new changes only to this tk copy
- If you need to modify the tool, modify the shared copy first
