# JARVIS Full Upgrade — 6-Tier Implementation Plan

## Overview

This plan covers all 54 upgrades across 7 tiers for the JARVIS AI assistant. The existing codebase
is a single large `tts.py` (2524 lines) with a `modules/` directory of 15 files.

The approach: **create a new `config.py` first** (Tier 6 priority), then build each new module, then wire everything into `tts.py` with surgical edits.

## Current Implementation Status - 2026-05-28

### Completed in the codebase

- `config.py` is present and centralizes models, paths, thresholds, shorthands, Tagalog maps, cache, privacy, and automation settings.
- All planned module files are present under `modules/`: `modelRouter`, `bodyAwareness`, `languageIntelligence`, `autonomousExecution`, `deepMemory`, `personalityEngine`, `selfRepair`, `privacyMode`, `morningBriefing`, `responseCache`, and `conversationExport`.
- `tts.py` now uses Qwen as the voice-face model, Phi3 as the classifier, DeepSeek for code/codebase containment, and Llama3 as the low-confidence fallback classifier/model.
- `detect_intent()` now re-checks low-confidence Phi3 classifications with the fallback model.
- Startup now prints both a model health board and a 16-module health board.
- Startup now loads the last configured conversation exchanges before proactive reminders run.
- Startup now starts self-repair, resource guardian, body-awareness monitors, clipboard watcher, hotkey listener, crash recovery, timers, recurring reminders, code-change alerts, and morning briefing.
- Language preprocessing is wired before routing, including phonetic correction, Tagalog keyword translation, shorthands, pronoun resolution, fuzzy correction, and partial-command clarification.
- Autonomous execution is wired for macro chains, scheduled automation, multi-step planning, screen-to-action OCR planning, Git commands, Downloads organization, clipboard watcher, and approval-gated Python file execution.
- Timer persistence is crash-safe by saving timer end times and resuming future timers on startup.
- Deep memory/personality state is injected into `build_system_prompt()`, including daily summaries, vector recall, emotional-state tone adaptation, and JARVIS self-status.
- Privacy mode, response cache, auto-copy for long responses, conversation export, and history search are wired into `tts.py`.
- Memory vault helper commands are wired (`encrypt memory` / `decrypt memory`) and remain opt-in through `ENCRYPT_MEMORY = False`.
- Robustness pass added after live testing: JARVIS now protects speech volume, has layered audio playback fallbacks, includes a `test voice` command, routes Spotify commands away from Windows master-volume control, routes storage questions to diagnostics, and makes model replies address the user naturally as Sir.

### Still requiring manual runtime verification

- Confirm the Ollama models are installed locally: `qwen2.5:7b-instruct`, `phi3:mini`, `deepseek-coder:6.7b`, and `llama3:instruct`.
- Run `python tts.py` on the actual laptop/audio setup and confirm all health-board entries pass.
- Voice-test these commands: `run diagnostics`, `start work mode`, `go private`, `export conversation`, a low-confidence chat command, and a code question.
- Verify encrypted memory behavior only after intentionally setting `ENCRYPT_MEMORY = True`; keep it `False` if you want readable JSON files.

---

## User Review Required

> [!IMPORTANT]
> **Model Stack Swap (Tier 0)** — Your requested model assignments are:
> - **Voice Face / All Responses**: `qwen2.5:7b-instruct` (Qwen speaks everything)
> - **Intent Classifier**: `phi3:mini` (already `MODEL_FAST`)
> - **Code Specialist**: `deepseek-coder:6.7b` (already `MODEL_SMART`)
> - **Uncertain Fallback**: `llama3:instruct` (already `DEFAULT_JARVIS_MODEL`)
>
> Currently `MODEL = DEFAULT_JARVIS_MODEL = llama3:instruct`. The new default voice (all responses) will become `qwen2.5:7b-instruct`. Llama3 only activates when Phi3 confidence < 70%.

> [!WARNING]
> **Code Containment Layer** — DeepSeek generates code *silently*, Qwen wraps it in spoken language. This means for code-intent queries, JARVIS will make **two sequential Ollama calls** (DeepSeek → Qwen). Slightly more latency on code questions.

> [!IMPORTANT]
> **Encrypted Memory Vault (Tier 5)** — AES encryption on all JSON memory files (`ai_memory.json`, `tasks.json`, `notes.json`, `timers.json`, etc.). This is a one-way operation — once enabled, memory files become encrypted and JARVIS must always be running to read them. Confirm you want this, or I can make it opt-in via a setting in `config.py`.

---

## Open Questions

> [!IMPORTANT]
> **Tagalog-English Code Switching (Tier 2)** — Should "Buksan mo ang Spotify" (open Spotify in Tagalog) route to the Spotify module, or should JARVIS just understand the intent and translate it internally first? I'll implement keyword maps for both — just confirming expected behavior.

> [!IMPORTANT]
> **Idle & Focus Detector (Tier 1)** — How many minutes of inactivity before JARVIS checks in? Default plan: **5 minutes**. JARVIS says one proactive line (e.g., "Still with you, Sir. Say hey Jarvis if you need me.") then goes quiet.

> [!IMPORTANT]
> **Personality Consistency Engine (Tier 4)** — Currently JARVIS has a system prompt defining its persona. The consistency engine will save tone/humor/speech rhythm descriptors in a `personality_state.json` and inject them each session. Should this also apply when DeepSeek generates code (before Qwen wraps it)?

---

## Proposed Changes

### Phase 0 — Foundation (Do First)

---

#### [NEW] config.py — Centralized Configuration

All constants, paths, model names, thresholds moved here.

```python
# Model stack
VOICE_FACE_MODEL   = "qwen2.5:7b-instruct"   # All spoken responses
INTENT_MODEL       = "fervent_mcclintock/Qwen2.5-Coder-0.5B-Instruct:Q8_0"              # Router — never speaks
CODE_MODEL         = "deepseek-coder:6.7b"   # Code — silent generator
FALLBACK_MODEL     = "llama3:instruct"        # Uncertain escalation
CONFIDENCE_THRESHOLD = 0.70                   # Below = escalate to llama3

# Hardware rules
MAX_VECTOR_RESULTS   = 3
VECTOR_THRESHOLD     = 0.75
DAILY_SUMMARY_HOUR   = 23   # 11 PM
IDLE_TIMEOUT_MINUTES = 5
MIC_CALIBRATION_SECS = 2
RESPONSE_CACHE_TTL   = 300  # seconds
ENCRYPT_MEMORY       = False  # opt-in
```

---

### Tier 0 — Model Brain

#### [MODIFY] tts.py — Model routing overhaul

**Changes to `tts.py`:**
- `DEFAULT_JARVIS_MODEL` → reads from `config.py`
- `MODEL` → set to `VOICE_FACE_MODEL` (Qwen) by default
- `ask_ai_stream()` → always uses `VOICE_FACE_MODEL` for final spoken output
- Add `ask_code_ai()` → calls `CODE_MODEL` (DeepSeek) silently, returns raw code/answer
- `detect_intent()` always uses `INTENT_MODEL` (Phi3)
- Add confidence scoring: if Phi3 returns < 70%, re-classify with `FALLBACK_MODEL`
- **Model health monitor**: on startup, ping each model; mark unavailable, fall back gracefully
- **Task-aware routing**: code intent → DeepSeek generates → Qwen wraps in speech

#### [NEW] modules/modelRouter.py

```
- route_request(user_input, intent, confidence) → picks model
- check_model_health() → dict of {model: bool}
- get_active_models() → list of available models
- escalate_to_fallback(user_input) → ask llama3 when uncertain
```

---

### Tier 1 — Laptop Body Awareness

#### [NEW] modules/bodyAwareness.py

Event-driven (no polling loops). Uses `psutil`, `wmi`, `win32api`.

```
- start_window_watcher()     → fires on active window change
- start_battery_monitor()    → threshold alerts at 20% and 10%
- start_thermal_monitor()    → fires when CPU temp > threshold
- check_disk_health()        → SMART health + free space (startup + on-demand)
- start_network_monitor()    → fires on connect/disconnect events
- start_idle_detector()      → detects N minutes of inactivity, proactive check-in once
- start_device_monitor()     → USB/monitor/charger connect/disconnect events
- run_full_diagnostics()     → triggered by "run diagnostics" voice command
```

All monitors run as daemon threads. No AI called on a timer — only on threshold events.

---

### Tier 2 — Language Intelligence

All fixes run **locally in Python before any model call** — zero latency, zero GPU cost.

#### [NEW] modules/languageIntelligence.py

```
- fuzzy_correct(text)          → edit-distance matching for typos
- phonetic_correct(text)       → Whisper mishear dictionary corrections
- tagalog_translate(text)      → keyword maps for Tagalog-English bilingual commands
- resolve_pronouns(text, ctx)  → "open it" → resolves to last object
- apply_shorthands(text)       → user-defined triggers ("yt" → YouTube)
- detect_tone(text)            → frustration/tiredness from word choice
- clarify_partial(text)        → asks one smart question if half-understood
- load_context_on_restart()    → loads last 5 exchanges on startup
```

#### [MODIFY] tts.py

- Pre-process every input through `languageIntelligence` before routing
- Load last 5 exchanges from memory on restart (already partially done, needs explicit wiring)
- Add `CUSTOM_SHORTHANDS` dict to `config.py`

---

### Tier 3 — Autonomous Task Execution

#### [NEW] modules/autonomousExecution.py

All destructive actions require a spoken `"confirm"` gate.

```
- handle_macro_chains(trigger)         → "start work mode" → multi-app chain
- plan_multi_step(goal)                → breaks goal into steps, executes in order
- approval_gate(action, description)   → speak + wait for "confirm" voice/text
- run_python_file(path)                → run + capture output + DeepSeek explains errors
- set_scheduled_automation(cmd, cron)  → recurring voice-set schedules
- git_voice_control(cmd)               → commit/push/pull; DeepSeek writes commit msg
- clipboard_auto_action()              → detect clipboard change, offer action once
- organize_downloads(path)             → plan + show + approval-gated execute
- screen_to_action(prompt)             → OCR read + understand + approval-gated act
```

#### [MODIFY] modules/timerSystem.py

- Save `end_timestamp` instead of `duration` so timers resume correctly after crash

#### [MODIFY] tts.py

- Wire `autonomousExecution` into `process_command()`
- Add macro chain phrases ("start work mode", "prepare for meeting")
- Approval gate intercepts before any delete/uninstall/git push

---

### Tier 4 — Deep Memory and Self-Knowledge

#### [NEW] modules/deepMemory.py

```
- summarize_session()          → end-of-day GPT-style summary via Qwen
- load_daily_summary()         → loads compressed context on startup
- vector_search(query)         → ChromaDB local embeddings, max 3 results, threshold 0.75
- save_vector_fact(fact)       → saves to ChromaDB
- get_jarvis_self_status()     → uptime, loaded modules, active model, version
- track_goal(goal, deadline)   → long-term goal with weekly nudges
- learn_work_patterns()        → peak hours from command timestamps
- save_to_knowledge_base(fact) → personal wiki from user-told facts
- infer_emotional_state()      → mood from word patterns, adapts verbosity
```

#### [NEW] modules/personalityEngine.py

```
- load_personality_state()    → reads personality_state.json
- save_personality_state()    → saves tone, humor level, speech rhythm
- get_personality_prompt()    → returns persona injection for system prompt
- adapt_tone(emotional_state) → softens if tired/frustrated
```

#### [MODIFY] tts.py `build_system_prompt()`

- Inject personality state from `personalityEngine`
- Load daily summary instead of raw history snippets
- Include JARVIS self-status (uptime, active model)

---

### Tier 5 — Defense and Self-Repair

#### [NEW] modules/selfRepair.py

```
- start_module_watchdog()      → detects crashed modules, reloads silently
- check_resource_overload()    → kills runaway processes (pure Python threshold)
- encrypt_memory_files()       → AES encryption on JSON memory (opt-in)
- decrypt_memory_files()       → decrypts on read
- log_crash(context)           → crash journal with context
- recover_last_session()       → on startup, resume from crash journal
- check_anomalous_processes()  → new unknown startup processes, alerts once
```

#### [NEW] modules/privacyMode.py

```
- enable_privacy_mode()        → disables disk logging, wipes on exit
- disable_privacy_mode()       → re-enables logging
- periodic_privacy_reminder()  → every N minutes reminds user they're in private mode
```

#### [MODIFY] tts.py startup

- Add startup health check board (all modules pass/fail) 
- Start `selfRepair` watchdog thread
- Load crash journal and offer session recovery

---

### Tier 6 — Quality of Life

#### [NEW] modules/morningBriefing.py

```
- get_morning_briefing()   → spoken briefing between 5-12am: time, tasks count, weather
```

#### [NEW] modules/conversationExport.py

```
- export_conversation(history)  → saves session as Markdown to Desktop
- search_history(query)         → keyword scoring over full history file
```

#### [NEW] modules/responseCache.py

```
- get_cached(query)    → returns cached response if < 5 min old
- set_cache(query, r)  → caches response; skips time/news queries
```

#### [MODIFY] tts.py

- **Mic auto-calibration**: sample 2 sec ambient noise on startup, set energy threshold
- **Auto-copy long responses**: any response > 300 chars auto-copied to clipboard
- Wire morning briefing into startup proactive reminders thread
- Wire response cache into `ask_ai_stream()`
- Wire conversation export ("export conversation" command)
- Wire history search ("what did we talk about regarding X")

---

## Execution Order

| Step | File | Priority |
|------|------|----------|
| 1 | `config.py` (new) | Do first |
| 2 | `modules/modelRouter.py` (new) | Do first |
| 3 | `tts.py` — model stack swap | Do first |
| 4 | `tts.py` — mic auto-calibration | Do first |
| 5 | `modules/languageIntelligence.py` (new) | Do first |
| 6 | `modules/bodyAwareness.py` (new) | High value |
| 7 | `modules/autonomousExecution.py` (new) | New |
| 8 | `modules/deepMemory.py` (new) | New |
| 9 | `modules/personalityEngine.py` (new) | New |
| 10 | `modules/selfRepair.py` (new) | High value |
| 11 | `modules/privacyMode.py` (new) | New |
| 12 | `modules/morningBriefing.py` (new) | New |
| 13 | `modules/responseCache.py` (new) | New |
| 14 | `modules/conversationExport.py` (new) | New |
| 15 | `tts.py` — wire all new modules | Final |
| 16 | `modules/timerSystem.py` — crash timestamps | Safety |

## Verification Plan

### Automated Checks
- Run `python config.py` to verify all paths resolve
- Run `python tts.py` startup: all 16 modules should show `[PASS]` on the health board
- Verify model health monitor detects missing models gracefully

### Manual Verification
- Say a command → verify Phi3 classifies it → verify Qwen speaks the response
- Say a code question → verify DeepSeek generates silently → Qwen wraps it
- Test "run diagnostics" command → full body health report spoken
- Test "start work mode" macro chain
- Test "go private" → verify nothing logged
- Test "export conversation" → Markdown file on Desktop
- Verify timer crash recovery by killing JARVIS mid-countdown and restarting
