# Media Bulk Downloader

> ⚠️ This tk-local copy has been superseded by the shared version at:
> `/Users/ryanlynn/.openclaw/skills/media_bulk_downloader`
>
> New multi-agent usage should prefer the shared copy.
> See: `MIGRATED-TO-SHARED.md`


A local bulk downloader powered by the Henghengmao / Meowload API.

## What it does
- Batch download media from supported platforms
- Currently verified with Instagram and TikTok
- Structured to support YouTube, Douyin, Xiaohongshu, and other supported platforms later
- Provides both CLI and local web UI

## Core features
- Accept URLs from direct input, TXT, or CSV
- Normalize and de-duplicate URLs
- Resolve media through the Media Downloader API
- Download files with retries
- Skip existing files
- Write reports into `_meta/`
- Rerun failed items
- Open output folder from the web UI

## API endpoint used
- `https://api.meowload.net/openapi/extract/post`

## Local setup
Create a `.env` file at:

`/Users/ryanlynn/.openclaw/workspace-tk/.env`

Example:

```env
HHM_API_KEY=your_api_key_here
HHM_BASE_URL=https://api.meowload.net
HHM_TIMEOUT_SECONDS=30
HHM_RETRY_COUNT=3
HHM_CONCURRENCY=3
HHM_OUTPUT_DIR=downloads
```

## Recommended usage: web UI

### Double-click launcher (macOS)
Double-click:
- `/Users/ryanlynn/.openclaw/workspace-tk/tools/media_bulk_downloader/Start Media Bulk Downloader.command`

Stop later with:
- `/Users/ryanlynn/.openclaw/workspace-tk/tools/media_bulk_downloader/Stop Media Bulk Downloader.command`

### Terminal launcher
```bash
bash /Users/ryanlynn/.openclaw/workspace-tk/tools/media_bulk_downloader/run_web.sh
```

Then open:

```bash
http://127.0.0.1:8765
```

## Daily CLI usage

### Simplest batch mode
Paste URLs into:

`/Users/ryanlynn/.openclaw/workspace-tk/tools/media_bulk_downloader/inbox/urls.txt`

Then run:

```bash
bash /Users/ryanlynn/.openclaw/workspace-tk/tools/media_bulk_downloader/run_daily.sh
```

## Direct CLI examples

### Download from txt
```bash
cd /Users/ryanlynn/.openclaw/workspace-tk
python3 -m tools.media_bulk_downloader.cli --input urls.txt --env-file /Users/ryanlynn/.openclaw/workspace-tk/.env --output /Users/ryanlynn/.openclaw/workspace-tk/downloads/media_bulk/manual_run
```

### Download from csv
```bash
cd /Users/ryanlynn/.openclaw/workspace-tk
python3 -m tools.media_bulk_downloader.cli --input urls.csv --url-column url --env-file /Users/ryanlynn/.openclaw/workspace-tk/.env --output /Users/ryanlynn/.openclaw/workspace-tk/downloads/media_bulk/manual_csv_run
```

### Download direct URLs
```bash
cd /Users/ryanlynn/.openclaw/workspace-tk
python3 -m tools.media_bulk_downloader.cli --urls "https://www.instagram.com/reel/AAA/,https://www.tiktok.com/@user/video/123" --env-file /Users/ryanlynn/.openclaw/workspace-tk/.env --output /Users/ryanlynn/.openclaw/workspace-tk/downloads/media_bulk/direct_run
```

## Output structure
Each batch writes to a timestamped directory, for example:

`/Users/ryanlynn/.openclaw/workspace-tk/downloads/media_bulk/20260327_110500/`

Inside it:
- platform folders like `instagram/`, `tiktok/`
- reports in `_meta/`

Report files:
- `_meta/results.csv`
- `_meta/failed.csv`
- `_meta/summary.json`

## Convenience files
- `run_daily.sh` — one-command daily batch runner
- `run_web.sh` — terminal launcher for local web UI
- `Start Media Bulk Downloader.command` — double-click launcher on macOS
- `Stop Media Bulk Downloader.command` — double-click stop script on macOS
- `QUICKSTART.md` — fast usage guide

## Verified sample
Using real sample URLs, the tool successfully downloaded:
- 4 Instagram reels
- 1 TikTok video

## Notes
- The current web UI is local-only and runs on `127.0.0.1:8765`
- The tool depends on your local `.env` and network access to the API
- Playlist-style extraction can be added later as a fallback if needed
