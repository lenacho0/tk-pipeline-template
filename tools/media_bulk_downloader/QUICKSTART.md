# Quick Start

## Web UI

### Easiest way (double-click on macOS)
Double-click:
- `/Users/ryanlynn/.openclaw/workspace-tk/tools/media_bulk_downloader/Start Media Bulk Downloader.command`

To stop it later, double-click:
- `/Users/ryanlynn/.openclaw/workspace-tk/tools/media_bulk_downloader/Stop Media Bulk Downloader.command`

### Terminal way
```bash
bash /Users/ryanlynn/.openclaw/workspace-tk/tools/media_bulk_downloader/run_web.sh
```

Then open:

```bash
http://127.0.0.1:8765
```

## Daily usage

1. Open this file and paste URLs, one per line:
   `/Users/ryanlynn/.openclaw/workspace-tk/tools/media_bulk_downloader/inbox/urls.txt`

2. Run:

```bash
bash /Users/ryanlynn/.openclaw/workspace-tk/tools/media_bulk_downloader/run_daily.sh
```

3. Downloaded files will be written to:

```bash
/Users/ryanlynn/.openclaw/workspace-tk/downloads/media_bulk/
```

Inside each run folder:
- videos go into platform folders like `instagram/` and `tiktok/`
- reports go into `_meta/`

4. The input queue file will be archived automatically after a successful run.

## Retry failed items

```bash
cd /Users/ryanlynn/.openclaw/workspace-tk
python3 -m tools.media_bulk_downloader.cli \
  --failed-only /Users/ryanlynn/.openclaw/workspace-tk/downloads/media_bulk/<run_id>/_meta/results.csv \
  --env-file /Users/ryanlynn/.openclaw/workspace-tk/.env \
  --output /Users/ryanlynn/.openclaw/workspace-tk/downloads/media_bulk/<run_id>_rerun
```
