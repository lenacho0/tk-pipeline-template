# Media Bulk Downloader Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a local bulk media downloader that starts with Instagram and is structured to support TikTok, YouTube, Douyin, Xiaohongshu, and other platforms supported by the Henghengmao API.

**Architecture:** A Python CLI reads URLs from text/CSV/direct args, normalizes and de-duplicates them, dispatches per-item resolution through a provider client, downloads the best available media with retries, and writes success/failure manifests for replay. The first implementation uses the Media Downloader API as the primary resolver and keeps the code organized around provider-independent task and download abstractions.

**Tech Stack:** Python 3, argparse, csv/json, urllib, standard library concurrency primitives (future-proofed), dotenv-style env loading (minimal custom parser for v1).

---

### Task 1: Create project skeleton
**Files:**
- Create: `tools/media_bulk_downloader/__init__.py`
- Create: `tools/media_bulk_downloader/cli.py`
- Create: `tools/media_bulk_downloader/config.py`
- Create: `tools/media_bulk_downloader/models.py`
- Create: `tools/media_bulk_downloader/provider.py`
- Create: `tools/media_bulk_downloader/downloader.py`
- Create: `tools/media_bulk_downloader/io_utils.py`
- Create: `tools/media_bulk_downloader/README.md`
- Create: `tools/media_bulk_downloader/.env.example`

### Task 2: Implement input loading and normalization
**Files:**
- Modify: `tools/media_bulk_downloader/io_utils.py`
- Modify: `tools/media_bulk_downloader/models.py`

### Task 3: Implement API configuration and auth loading
**Files:**
- Modify: `tools/media_bulk_downloader/config.py`
- Modify: `tools/media_bulk_downloader/provider.py`

### Task 4: Implement media resolution through Media Downloader API
**Files:**
- Modify: `tools/media_bulk_downloader/provider.py`
- Modify: `tools/media_bulk_downloader/models.py`

### Task 5: Implement robust file downloader with retries and naming
**Files:**
- Modify: `tools/media_bulk_downloader/downloader.py`
- Modify: `tools/media_bulk_downloader/models.py`

### Task 6: Wire end-to-end CLI flow
**Files:**
- Modify: `tools/media_bulk_downloader/cli.py`
- Modify: `tools/media_bulk_downloader/io_utils.py`
- Modify: `tools/media_bulk_downloader/provider.py`
- Modify: `tools/media_bulk_downloader/downloader.py`

### Task 7: Document usage and future multi-platform extension
**Files:**
- Modify: `tools/media_bulk_downloader/README.md`
- Modify: `tools/media_bulk_downloader/.env.example`
