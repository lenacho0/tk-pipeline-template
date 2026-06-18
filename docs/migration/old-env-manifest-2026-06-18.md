# Old Environment Manifest - 2026-06-18

This manifest is intentionally redacted. It records structure, commands, and migration scope only. Do not add secrets, tokens, cookies, `.env` values, or private app credentials to this file.

## Source Repository

- Source local path pattern: `$HOME/.openclaw/workspace-tk`
- Remote: `https://github.com/lenacho0/tk-pipeline-template.git`
- Branch: `codex/unified-ai-route-slots`
- Commit: `c90e95e989913149995bf40f445ad323c05590e3`
- Safety check command: `python3 tools/release_safety_check.py`
- Safety check result on 2026-06-18: passed

## Runtime Stack

- Main runtime directory: `tk_toolkit_dual/`
- Python observed on source Mac: `Python 3.9.6`
- Python dependencies from `tk_toolkit_dual/requirements.txt`:
  - `requests>=2.28.0`
  - `google-genai>=1.0.0`
  - `socksio>=1.0.0`
- `lark-cli` observed on source Mac: `lark-cli version 1.0.47`
- Source Mac production instance name: `ryan`
- Panda target instance name: `panda`

## Source Config Shape

Reference file on source Mac: `tk_toolkit_dual/config.ryan.json`

Top-level keys:

- `feishu`
- `fastmoss`
- `config_records`
- `products`
- `notification`
- `dispatcher`
- `workspace`

`feishu` keys:

- `app_id`
- `app_secret`
- `bitable_app_token`
- `tables`

`feishu.tables` keys:

- `config`
- `voice_library`
- `text_audio`
- `product`
- `model_appearance`
- `script_doc_shots`
- `script_doc_tasks`
- `script_doc_reference_assets`
- `first_last_video`
- `multi_role_first_last`
- `nine_grid_video`
- `video_edit`
- `prompt_image_video`
- `storyboard_video`
- `script_doc_unified`

`config_records` keys:

- `script_doc_text_split`
- `main_image_otu`

`products` keys currently present:

- `宠物尿味分解除臭喷雾`
- `宠物皮肤护理喷雾`

`dispatcher` keys:

- `poll_interval`
- `healthcheck_hour`
- `global_max_concurrency`
- `circuit_breaker`
- `scan`
- `stages`

`dispatcher.stages` keys currently present:

- `tk_script_doc_shots.py`
- `tk_first_last_video.py`
- `tk_shot_voiceover.py`
- `tk_shot_storyboard.py`
- `tk_shot_video.py`
- `文案音频生成`
- `多图九宫格方案生成`
- `首尾帧批量场景拆分`
- `首尾帧文档拆分`
- `首尾帧场景重新拆分`
- `脚本文档解析拆分`
- `多角色首尾帧解析`
- `脚本文档口播音频生成`
- `多图九宫格参考图生成`
- `多图九宫格图片生成`
- `多图九宫格视频生成`
- `首尾帧首帧图生成`
- `首尾帧尾帧图生成`
- `多角色参考图生成`
- `多角色关键帧生成`
- `脚本文档参考底图生成`
- `脚本文档分镜图生成`
- `脚本文档尾帧图生成`
- `首尾帧视频生成`
- `脚本文档分镜视频生成`
- `多角色视频片段生成`

## Source Launchd Instances Still Running

Do not stop these during the parallel migration phase.

- `com.tk-pipeline.dispatcher.ryan.tblrLVPbX4RzXVFL`
- `com.tk-pipeline.dispatcher.ryan.tbldPJLJhczlGzSt`
- `com.tk-pipeline.dispatcher.ryan.tblBC37ktQBHPLep`
- `com.tk-pipeline.dispatcher.ryan.tblFg33rvB7eCyzr`
- `com.tk-pipeline.dispatcher.ryan.tblYvJfkayAbI6W1`
- `com.tk-pipeline.dispatcher.ryan.tblAY3rpgcbeMixC`
- `com.tk-pipeline.dispatcher.ryan.tblPfREXMoSafUDW`
- `com.tk-pipeline.dispatcher.ryan.tblAiOVwyscUAEBc`
- `com.tk-pipeline.dispatcher.ryan.tbliPDHXXr1S6oZJ`
- `com.tk-pipeline.dispatcher.ryan.tblPPfKQMMC0D4XC`
- `com.tk-pipeline.dispatcher.ryan.tblObiMzCDn9ilFQ`
- `com.tk-pipeline.dispatcher.ryan.tbliRML5KjmzVjB0`

## Data Scope For New Base

The new Panda Base should receive a fresh imported structure, then only useful operational data.

Migrate:

- Model/API configuration rows required by routing and concurrency.
- Product information rows still used by new tasks.
- Voice library rows still used by audio generation.
- Model appearance rows still used by image/video generation.
- Active or recently relevant unfinished tasks.
- Failed tasks that still need repair or re-run.
- Reference records needed by those active tasks.

Do not migrate by default:

- Old dispatcher logs.
- `.running_tasks*`, `.retry_state*`, `.table_cache*`, `.record_state_cache*`, `.dispatcher_metrics*`, `.dispatcher_heartbeat*`, `.dead_letter_tasks*`, `.circuit_breakers*`.
- Local generated media work directories, unless a specific active record needs a file.
- Large historical completed task rows, unless they are needed as templates.

## Important Migration Rule

Panda must not start dispatcher instances against old table IDs. After importing the new Base and filling new credentials, run `tk_toolkit_dual/rebind_copied_base.py` and use the new table IDs from `config.panda.json`.
