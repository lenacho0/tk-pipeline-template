# TK Editing Notes

## Why those `Edit ... failed` messages happened

These messages were not runtime failures of the pipeline itself. They happened during code editing when an exact text replacement did not match the current file content.

Typical causes:
- The target file had already changed, so the old snippet no longer matched exactly
- The same snippet appeared multiple times, so the edit tool could not decide which one to replace
- The path was mistyped during an edit call
- Large files were being patched with very small context windows, making exact replacement brittle

## What was done
- Verified the real file contents after each important change
- Repaired missed changes using more specific context
- Switched to safer editing patterns for repeated snippets
- Confirmed the important runtime changes actually exist in the real files

## Safer editing rules for future changes
1. For repeated code blocks, do not use a short ambiguous replacement.
   - First inspect the file
   - Then replace using a longer unique surrounding block

2. For large files like `tk_dispatcher.py`, prefer:
   - `read` + precise patch with enough context
   - or a controlled block rewrite

3. After important edits, always verify with one of:
   - `python3 -m py_compile ...`
   - `grep` / `read` confirmation
   - `git diff`

4. When adding new task fields or trigger rules, verify the real file contains:
   - the new field names
   - the new trigger values
   - the fallback logic

5. Treat `Edit failed` as a tooling patch miss, not as proof that runtime code is broken.
   Always verify the actual file state before deciding whether a fix is still needed.

## Current status
The key pipeline changes related to recent work have been verified in actual files, including:
- dynamic product resolution from the product table
- prioritizing `关联产品`
- auto-triggering storyboard after script generation
- dispatcher trigger support for storyboard regeneration
