# Media Bulk Downloader

A local bulk downloader powered by the Henghengmao API.

## v1 goals
- Start with Instagram as the primary use case
- Keep the tool generic enough for TikTok, YouTube, Douyin, Xiaohongshu, and other supported platforms
- Optimize for simplicity, resumability, and high success rate

## Features
- Accept URLs from CSV, TXT, or command-line args
- Normalize and de-duplicate input URLs
- Resolve media through the Media Downloader API (`https://api.meowload.net/openapi/extract/post`)
- Download files with retries
- Skip existing files
- Emit `results.csv`, `failed.csv`, and `summary.json`
- Replay failed jobs with `--failed-only`

## Setup
Create a `.env` file in the project root or next to where you run the command:

```env
HHM_API_KEY=your_api_key_here
# Optional overrides
HHM_BASE_URL=https://api.meowload.net
HHM_TIMEOUT_SECONDS=30
HHM_RETRY_COUNT=3
HHM_CONCURRENCY=3
HHM_OUTPUT_DIR=downloads
```

## Usage

### Easiest daily workflow
1. Paste URLs into:
   `/Users/ryanlynn/.openclaw/workspace-tk/tools/media_bulk_downloader/inbox/urls.txt`
2. Run:
```bash
bash /Users/ryanlynn/.openclaw/workspace-tk/tools/media_bulk_downloader/run_daily.sh
```
3. Outputs will go to:
   `/Users/ryanlynn/.openclaw/workspace-tk/downloads/media_bulk/<timestamp>/`


### Download from txt
```bash
python -m tools.media_bulk_downloader.cli --input urls.txt --output downloads/ig_batch_01
```

### Download from csv
```bash
python -m tools.media_bulk_downloader.cli --input urls.csv --url-column url --output downloads/ig_batch_02
```

### Download direct URLs
```bash
python -m tools.media_bulk_downloader.cli --urls "https://www.instagram.com/reel/AAA/,https://www.instagram.com/reel/BBB/"
```

### Replay failed items
```bash
python -m tools.media_bulk_downloader.cli --failed-only downloads/ig_batch_02/results.csv --output downloads/ig_batch_02_rerun
```

## Design notes
- v1 uses the Media Downloader API as the primary resolution path.
- The internal structure is platform-agnostic so the provider client can be extended later.
- Playlist Downloader API can be added later as a fallback path for complex or collection-based URLs.

## Verified sample
Using the provided real URLs, the current build successfully downloaded:
- 4 Instagram reels
- 1 TikTok video

Example output root:
- `/Users/ryanlynn/.openclaw/workspace-tk/downloads/test_batch_01/`

## Included convenience files
- `run_daily.sh` — one-command daily batch runner
- `inbox/urls.txt` — paste links here
- `archive/` — processed queue snapshots
- `QUICKSTART.md` — fast usage guide

## Next extensions
- Platform-specific resolution tweaks
- Playlist fallback support
- Better file naming from returned metadata
- Optional thumbnail/metadata exports
- Smarter content-type validation
