# JARVIS 6.0 → 6.1 Upgrade Notes (2026-08)

## What's New

This upgrade replaces JARVIS's brittle intent-classifier routing with **native LLM tool-use**. Instead of 30+ regex layers + a 0.5B Qwen Coder classifier picking one of 13 hardcoded intents, Qwen 3 8B now picks tools itself based on tool descriptions.

---

## Model Stack Changes

| Role | Old Model | New Model |
|---|---|---|
| Voice Face / Router | `qwen2.5:7b-instruct` | **`qwen3:8b`** |
| Intent Classifier | `Qwen2.5-Coder-0.5B` | **Retired** (Qwen 3 does routing itself) |
| Code Specialist | `deepseek-coder:6.7b` | (unchanged) |
| Fallback | `llama3:instruct` | **`artifish/llama3.2-uncensored`** |
| Multi-Agent Planner | `phi3:mini` | **`qwen3:4b`** |
| Vision (Fast) | `llava:7b` | **`redule26/huihui_ai_qwen2.5-vl-7b-abliterated`** |
| Vision (Detail) | `llava:13b` | **`llama3.2-vision:11b`** |
| Embeddings | `nomic-embed-text` | (unchanged) |

---

## New Files (4)

| File | Purpose |
|---|---|
| `modules/toolRegistry.py` | Catalog of 60 tools with descriptions, JSON schemas, and function pointers |
| `modules/toolRouter.py` | The tool-use loop — calls Qwen 3 with tools, executes calls, iterates up to 5× |
| `modules/toolExecutor.py` | Safe tool execution with approval gates and error handling |
| `modules/toolEmbeddings.py` | Embeds tool descriptions for semantic pre-filtering |

## Modified Files (6)

| File | Change |
|---|---|
| `config.py` | New model assignments + 8 new tool-router constants |
| `cameraAccess.py` | Switched from `/api/generate`+base64 → `/api/chat`+image blocks (Qwen 2.5 VL format) |
| `modules/screenUnderstanding.py` | Same vision API refactor + detail_mode toggle |
| `modules/multiAgent.py` | Updated planner model to `qwen3:4b` |
| `modules/deepMemory.py` | Lowered `VECTOR_THRESHOLD` 0.75→0.55, `MAX_VECTOR_RESULTS` 3→5 |
| `tts.py` | Added `USE_TOOL_ROUTER` flag — when True, routes via new tool router; when False, falls back to old `detect_intent()` |

## Backup Files (6)

Every modified file has a `.bak` copy (e.g., `config.py.bak`, `tts.py.bak`). To roll back any file:

```bash
mv config.py.bak config.py
mv tts.py.bak tts.py
# etc.
```

---

## How to Enable / Disable

The new tool router is controlled by **`USE_TOOL_ROUTER = True`** in `config.py` (line ~306).

- **`True`** (default): New Qwen 3 tool-use routing
- **`False`**: Old `detect_intent()` + regex layers (your original behavior)

If the new router ever misbehaves, flip this to `False` and you're back to the old system instantly. No reinstall needed.

---

## Quick Test (after running `python tts.py`)

Try these commands and watch the console for `[ToolRouter]:` log lines:

| Say This | Should See in Console |
|---|---|
| "hello" | `[ToolRouter]: Used tools ['chat_only'] in 1 iterations` |
| "set volume to 50" | `[ToolRouter]: Used tools ['set_volume'] in 1 iterations` |
| "play some Drake" | `[ToolRouter]: Used tools ['spotify_play'] in 1 iterations` |
| "set volume to 30 and play relaxing jazz" | `[ToolRouter]: Used tools ['set_volume', 'spotify_play'] in 2 iterations` |
| "what's the weather" | `[ToolRouter]: Used tools ['get_weather'] in 1 iterations` |
| "find my resume" | `[ToolRouter]: Used tools ['search_files'] in 1 iterations` |
| "note that I need milk" | `[ToolRouter]: Used tools ['save_note'] in 1 iterations` |
| "shutdown the laptop" | `[ToolRouter]: Used tools ['shutdown_system'] in 1 iterations` (will trigger approval gate) |

---

## What's Preserved (Untouched)

All of these still work exactly as before:

- All 30+ existing modules (systemControl, spotifyControl, taskManager, noteSystem, etc.)
- Language preprocessing pipeline (phonetic corrections, Tagalog→English, pronoun resolution)
- Sleep mode / wake word / hotkey listener (Ctrl+Space)
- Background daemons (body awareness, clipboard watcher, codebase watcher, etc.)
- Piper TTS pipeline
- Telegram bridge
- Approval gate system (now centralized in `toolExecutor.py`)
- Privacy mode
- Morning briefing
- Crash recovery / self-repair
- All JSON state files (ai_memory, tasks, notes, timers, etc.)

---

## What's Improved

1. **Smart triggering** — Qwen 3 reads tool descriptions and decides which tool fits, instead of regex pattern matching
2. **Multi-step requests** — "set volume to 50 and play some Drake" actually chains both tools in one request
3. **`chat_only` default** — greetings and general questions no longer get force-routed through 30 regex layers
4. **Better vision** — Qwen 2.5 VL is dramatically better at OCR and screen reading than LLaVA 7B
5. **Uncensored vision** — camera/screen analysis won't refuse to read sensitive content
6. **Lower RAG threshold** — `VECTOR_THRESHOLD` lowered from 0.75→0.55 so semantic memory actually returns results
7. **Tool pre-filtering** — Embeddings select top 12 most relevant tools per query, saving tokens and reducing confusion

---

## Troubleshooting

### "ToolRouter: Error - falling back to old router"

This means the new router threw an exception. The console will print the full traceback. Common causes:
- Ollama not running → start it with `ollama serve`
- `qwen3:8b` not pulled → run `ollama pull qwen3:8b`
- Network/firewall blocking localhost:11434

The system automatically falls back to the old `detect_intent()` router, so JARVIS keeps working.

### "Tool 'X' not found in registry"

The model tried to call a tool that doesn't exist. This is rare (Qwen 3 is good at sticking to the provided tool list) but can happen. The system will tell the model the tool doesn't exist and it will retry with a different approach.

### Approval gate not working

The new tool router uses the same approval gate infrastructure as the old system. If approvals aren't working:
1. Check that `_awaiting_confirmation` and `_confirmation_queue` are defined in `tts.py` (they are — same as before)
2. The `set_confirmation_handlers()` call in the new tool router path wires them in

### Vision not working

The new vision API uses `/api/chat` instead of `/api/generate`. If vision fails:
1. Make sure `redule26/huihui_ai_qwen2.5-vl-7b-abliterated` is pulled
2. Check Ollama logs for any API errors
3. If the model name is wrong, update `VISION_MODEL_FAST` in `config.py`

---

## What's Next

This is **Phase 1-3 of the upgrade**. Future phases (not included in this zip):

- **Phase 4**: Smart enhancements (self-correction loop, tool cooldown, confidence-aware fallback)
- **Phase 5**: 25+ new tools (semantic_file_search wired into system prompt, quick_calc, find_large_files, compress_files, pdf_merge, translate_text, etc.)
- **Phase 6**: Evaluation harness with 50+ test queries

For now, test the new tool router with your normal commands. If triggering feels smarter, we proceed to Phase 4. If something breaks, flip `USE_TOOL_ROUTER = False` and report back.

---

## File Sizes

| File | Old Size | New Size | Delta |
|---|---|---|---|
| `tts.py` | 143 KB | 146 KB | +3 KB (new tool router path added) |
| `config.py` | 16 KB | 18 KB | +2 KB (new model assignments + 8 constants) |
| `cameraAccess.py` | 4 KB | 7 KB | +3 KB (new vision API + detail mode) |
| `modules/screenUnderstanding.py` | 13 KB | 13 KB | ~0 (same size, API refactored) |
| `modules/multiAgent.py` | 15 KB | 15 KB | ~0 (one model name change) |
| `modules/deepMemory.py` | 14 KB | 14 KB | ~0 (two constant changes) |
| `modules/toolRegistry.py` | — | 18 KB | NEW |
| `modules/toolRouter.py` | — | 11 KB | NEW |
| `modules/toolExecutor.py` | — | 6 KB | NEW |
| `modules/toolEmbeddings.py` | — | 6 KB | NEW |

Total new code: ~50 KB across 4 new files. Total modified code: ~8 KB across 6 existing files.
