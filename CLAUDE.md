# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Start / Dev

```bash
cd /root/charcard
python3 server.py          # starts Flask on 0.0.0.0:5000
```

No test suite exists. Manual smoke test: `python3 -c "from charcard.llm import generate_card; from charcard.card_builder import build; print('imports ok')"`

## Architecture

5-stage async generation pipeline, orchestrated by Flask in a background thread with in-memory job store:

```
POST /api/generate → job_id → client polls /api/status/<id>
                              ↓ (background thread)
                        1. LLM (SiliconFlow Chat API) → raw card dict
                        2. Build (card_builder.py) → v2 spec envelope
                        3. Image (SiliconFlow images API fallback) → PNG
                        4. Embed (png_assembler.py) → JSON → tEXt chunk
                        5. Done → /api/download/<id>
```

**Key constraint:** Everything runs synchronously in a single `daemon=True` thread. There is no task queue, no worker pool. Jobs live in the `_jobs` dict protected by `_jobs_lock` and are never cleaned up (memory leak on purpose — session-scoped).

## Module Map

| Module | Responsibility | Key export |
|--------|---------------|------------|
| `config.py` | All defaults, env-var reads | `SILICONFLOW_API_KEY`, `OUTPUT_DIR`, `DEFAULT_LLM_MODEL` |
| `llm.py` | Chat API call + JSON parse + retry | `generate_card(description, model?) → dict` |
| `card_builder.py` | Normalize LLM dict → v2 spec | `build(card_dict) → dict` with `_image_prompt` attached |
| `comfy.py` | Image generation (cloud-only currently) | `_cloud_generate(prompt, model, output_dir) → path` |
| `png_assembler.py` | JSON → base64 → PNG tEXt chunk | `embed(card_json, png_path, output_path) → path` |
| `server.py` | Flask routes + job orchestration | 6 routes, `_run_generation()`, `_update_job()` |
| `templates/index.html` | Vanilla JS/CSS SPA | Client-side polling every 1500ms |

## Data Flow Conventions

- **`_image_prompt`**: The LLM generates this field in the raw dict. `card_builder.build()` pops it out of `data`, attaches it to the envelope as `card["_image_prompt"]`. `server.py` reads it from the envelope, feeds it to image generation, then strips all `_`-prefixed keys before PNG embedding.
- **Retry on JSON failure**: `llm.generate_card()` calls the API once; if JSON parsing fails, it retries with a stricter system prompt (`RETRY_SYSTEM_PROMPT`). No third attempt.
- **Image fallback chain**: `comfy.generate_portrait()` always delegates to `_cloud_generate()` (ComfyUI path is stubbed). If `_cloud_generate()` raises, `server._run_generation()` catches and falls back to `build_placeholder_card()`.

## Constraints

- Python 3.8+ (uses `from __future__ import annotations` in llm.py for `Optional[str]`)
- `SILICONFLOW_API_KEY` must be set in the environment before starting the server
- Output PNGs written to `/sdcard/Download/claude code/characters/` (Android filesystem, may not exist — code calls `os.makedirs` defensively)
- ComfyUI integration is intentionally stubbed; only the cloud image API path is wired
- No database, no auth, no rate limiting — single-user tool
