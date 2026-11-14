# JARVIS AI Assistant

An offline, voice-controlled AI assistant for Windows — created by **Mr. Kirby Paladan**.

JARVIS runs 100% locally through [Ollama](https://ollama.com): it listens to your microphone (or Telegram), understands natural speech (English + Tagalog), picks the right tool for the job from a registry of **84 tools**, executes it safely, and answers out loud through a local TTS voice. No cloud, no subscriptions — everything lives on your machine.

---

## 1. What It Can Do

| Area | Examples |
|------|----------|
| **System control** | "set volume to 50", "set brightness to 80", "shutdown the laptop", "what's my battery" |
| **Music** | "play some Drake", "next song", "what's playing" (Spotify integration) |
| **Tasks & notes** | "create a task to fix the bug by Friday", "note that I need to buy milk", "show all notes" |
| **Files** | "find my resume", "read that file", "open the PDF" (search + RAG semantic file search) |
| **Web & info** | "what's the weather", "search for X", "Wikipedia summary of Y", news, stocks, crypto |
| **Vision** | "what do you see" (camera), "read my screen" (OCR + vision model), screenshots |
| **Code** | Programming questions, silent code generation, multi-language code execution, Git voice control |
| **Timers & habits** | "set a timer for 10 minutes", recurring reminders, pomodoro, habit tracking |
| **Automation** | Voice macros, scheduled automations, Downloads organizer, browser agent (Playwright) |
| **Memory** | Vector memory, daily summaries, persistent facts, "what do I usually ask about?" |
| **Remote** | Full control via Telegram bot (text + voice notes) |

See `MyCommands.txt` for a cheat sheet of example phrases.

---

## 2. What It Needs

### Hardware / OS
- **Windows** (system control, audio, hotkeys are Windows-specific)
- A microphone and speakers
- ~16 GB RAM recommended (runs 8B-class local models)

### Software
1. **Python 3.12+** — `python --version` should work (or the `py` launcher)
2. **Ollama** — get it from <https://ollama.com>. JARVIS talks to it at `localhost:11434`
3. **Python packages** — install everything at once:
   ```powershell
   pip install -r requirements.txt
   ```

### Ollama models to pull
```powershell
ollama pull qwen3:8b                                # Main brain — routing + all spoken replies
ollama pull qwen2.5:1.5b-instruct                   # Fast path — casual chat + quick commands
ollama pull qwen3:4b                                # Multi-agent planner
ollama pull deepseek-coder:6.7b                     # Code specialist
ollama pull nomic-embed-text                        # Embeddings (memory + tool filtering)
ollama pull artifish/llama3.2-uncensored            # Emergency fallback
ollama pull redule26/huihui_ai_qwen2.5-vl-7b-abliterated   # Vision (fast)
ollama pull llama3.2-vision:11b                     # Vision (detail)
```
The vision models are optional on first run — JARVIS pulls them automatically when a vision query needs one.

### Optional integrations
- **Spotify** — put your Client ID / Secret / Redirect URI in `config.py` (section `SPOTIFY_*`). First use opens a one-time local OAuth page
- **Telegram remote control** — paste your BotFather token and numeric user ID into `config.py` (section `TELEGRAM_*`), then say "start telegram"

---

## 3. How to Run It

### The easy way — `start.bat`
Double-click **`start.bat`** (or run it in a terminal). It checks Ollama and Python, then shows a menu:

| Choice | Action |
|--------|--------|
| **1** (default) | Start JARVIS — runs `py tts.py` |
| **2** | Run evaluation tests — 50 test queries through `modules/eval_harness` (~5 min) |
| **3** | Rebuild the tool embeddings cache — run this after adding/changing tools |
| **4** | Open the stats dashboard (`jarvis_stats.html`) in your browser |
| **5** | Exit |

### The direct way
```powershell
py tts.py                      # start JARVIS
py -m modules.eval_harness     # evaluation suite
py build_tool_cache.py         # rebuild tool cache
py run_calibration.py          # threshold calibration report
```
Press `Ctrl+C` to stop.

### First run
On startup JARVIS prints a **model health board** and a **module health board**, calibrates your microphone (2 seconds of ambient noise), starts its background daemons, then says it's online. Default mode is **Speak Mode**: press Enter to record, or just type.

---

## 4. How It Works

### The pipeline
Every input (mic, keyboard, hotkey, or Telegram) flows through the same pipeline in `tts.py → process_command()`:

```
Input  →  Language Intelligence  →  Tool Router  →  Tool Executor  →  Voice Face model  →  Piper TTS
         (phonetic fixes,           (Qwen 3 8B       (approval gates,   (Qwen 3 wraps the     (spoken reply
          Tagalog→English,          picks tools       sandboxing,        result in natural      + console
          shorthands,               from the 84-      error recovery)    spoken language)       + optional
          pronoun resolution)       tool registry)                                             Telegram note)
```

### Model stack (Tier 0)
One model per request — escalation only when confidence drops below `CONFIDENCE_THRESHOLD` (0.70).

| Role | Model | Notes |
|------|-------|-------|
| Voice face + tool router | `qwen3:8b` | The only model that speaks; picks its own tools via native tool-use |
| Fast path | `qwen2.5:1.5b-instruct` | Casual chat + simple single-tool commands (1–2 s) |
| Code specialist | `deepseek-coder:6.7b` | Generates code *silently*; Qwen wraps it into speech |
| Multi-agent planner | `qwen3:4b` | Decomposes complex tasks into subtasks |
| Fallback | `artifish/llama3.2-uncensored` | Kicks in when router confidence < 70% |
| Embeddings | `nomic-embed-text` | Vector memory, RAG, tool pre-filtering |
| Vision (fast / detail) | `redule26/huihui_ai_qwen2.5-vl-7b-abliterated` / `llama3.2-vision:11b` | Camera + screen understanding |

### The tool system (v6.1+)
- **`modules/toolRegistry.py`** — catalog of **84 tools** with descriptions, JSON schemas, and function pointers
- **`modules/toolRouter.py`** — the tool-use loop: embedding pre-filter picks the ~12 most relevant tools per query, then Qwen 3 chooses and chains tools (up to 5 iterations, so "set volume to 30 **and** play relaxing jazz" works as one request)
- **`modules/toolExecutor.py`** — safe execution: approval gates for destructive actions, error handling, validation gate against hallucinated parameters
- **`modules/toolGroups.py`** — tools categorized into 8 groups to shrink the decision space
- **`modules/toolEmbeddings.py`** + `build_tool_cache.py` — semantic tool filtering, cached in `tool_embeddings_cache.json`

The old regex/intent-classifier routing still exists as an instant rollback: set `USE_TOOL_ROUTER = False` in `config.py` and you're back on `detect_intent()`.

### Memory
| Store | File | Holds |
|-------|------|-------|
| Conversation history | `ai_memory.json` | Last 20 exchanges |
| Knowledge base | `knowledge_base.json` | Vector facts (FAISS / cosine similarity) |
| Persistent memory | auto-learned facts across sessions | |
| Daily summaries | `daily_summaries.json` | End-of-day recaps |
| Goals | `long_term_goals.json` | Deadlines + weekly nudges |
| Command history | `command_history.json` | Pattern analysis, shortcut suggestions |
| Personality state | `personality_state.json` | Tone / humor / rhythm, adapts to your mood |

All state files are plain JSON and auto-created on first run. `ENCRYPT_MEMORY = True` in `config.py` switches them to an AES-encrypted vault (opt-in).

### Safety layers
- **Approval gate** — destructive actions (`delete`, `uninstall`, `git_push`, `git_force`, `run_script`, `format_drive`, `organize_files`, `clear_history`) require a spoken or typed "confirm"
- **Privacy mode** — "go private" stops all memory saving and logging until you turn it off
- **Self-repair** — module watchdog restarts crashed modules; resource guardian alerts at 90% RAM / 95% CPU; crash journal + session recovery
- **Identity** — JARVIS never reveals its base models; it is "JARVIS, created by Mr. Kirby Paladan"

---

## 5. Controls

### Wake & sleep
| | Phrases |
|---|---|
| **Wake words** | "hey jarvis", "jarvis", "wake up jarvis", "yo jarvis", "okay jarvis" |
| **Sleep phrases** | "go to sleep", "goodbye jarvis", "that's all", "stop listening", "thank you jarvis" |

### Global hotkey
- **`Ctrl + Space`** — push-to-talk from anywhere in Windows (uses `pynput` global hook)

### Listening modes (say or type the mode name)
| Mode | Behavior |
|------|----------|
| **speak mode** (default) | Press Enter to record, or type directly |
| **text mode** | Keyboard only, no microphone |
| **auto mode** | Always-on background listening, wake-word gated |
| **convo mode** | Always listening, no wake word needed |
| **silent mode** | Wake word only, ignores everything else |

### Voice commands — quick examples
```
"set volume to 50"                    → system tool, instant
"play some Drake"                     → Spotify
"set volume to 30 and play jazz"      → two tools chained in one request
"note that I need milk"               → notes
"create a task to study at 8pm"       → tasks
"find my resume"                      → file search
"what's the weather"                  → internet
"read my screen"                      → vision + OCR
"run diagnostics"                     → full system report
"how's my computer?"                  → system monitor
"what can you do?"                    → capabilities list
"go private" / "stop private mode"    → privacy toggle
"test voice"                          → TTS check
```

### Confirmation flow (approval gate)
When you trigger a destructive action, JARVIS asks for confirmation and waits — reply **"confirm"** to execute or **"cancel"** (or anything else / just wait for the timeout) to abort. The state machine also detects if you issue a *new* command mid-confirmation and cancels cleanly.

---

## 6. Configuration

Everything lives in **`config.py`** — 90+ settings in one file, grouped by section.

**Secrets live in `.env`** (git-ignored, loaded automatically at startup by `config.py`): `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_IDS`, `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, `SPOTIFY_REDIRECT_URI`. No credentials are hardcoded in the repo. The most useful toggles:

| Setting | Default | What it does |
|---------|---------|--------------|
| `USE_TOOL_ROUTER` | `True` | Master switch: new Qwen 3 tool-use routing vs. old `detect_intent()` |
| `USE_CASUAL_CHAT_MODEL` | `True` | 1.5B fast path for casual chat |
| `CONFIDENCE_THRESHOLD` | `0.70` | Below this, escalate to the fallback model |
| `VOICE` | `en_US-danny-low.onnx` | Piper TTS voice |
| `MAX_HISTORY` | `20` | Conversation window |
| `OWW_DETECTION_THRESHOLD` | `0.5` | Wake-word sensitivity (lower = more sensitive) |
| `ENCRYPT_MEMORY` | `False` | AES-encrypt all JSON state files (opt-in) |
| `AUTO_COPY_RESPONSES` | `False` | Auto-copy long replies to clipboard |

`knowledge_routing.txt` controls which model answers your **knowledge-file queries**: WHITELIST words (single-value lookups like "what's my GWA") go to the fast 1.5B; BLACKLIST words (listing/comparing like "what are my grades") force the accurate 8B. Edit that file to tune it — one phrase per line, `#` comments ignored.

---

## 7. Maintenance & Utilities

| Task | How |
|------|-----|
| Rebuild tool cache (after editing tools) | `start.bat` → option 3, or `py build_tool_cache.py` |
| Run the 50-query evaluation suite | `start.bat` → option 2, or `py -m modules.eval_harness` |
| Live stats dashboard | `start.bat` → option 4 (JARVIS must be running for live data) |
| Calibration report (per-tool thresholds) | `py run_calibration.py`, or schedule it with `setup_calibration_schedule.bat` |
| Roll back a file | every modified file has a `.bak` twin — e.g. `Move-Item config.py.bak config.py` |
| Clean state | delete the auto-generated JSON files (ai_memory, tasks, notes, timers, …) — they regenerate |

---

## 8. Project Structure

```
projectjarvis_latest/
├── tts.py                     # Main engine — entry point, pipeline, modes, TTS/STT (3,000+ lines)
├── config.py                  # ALL configuration (models, thresholds, keys, toggles)
├── start.bat                  # Friendly launcher + menu
├── requirements.txt           # Python dependencies
├── build_tool_cache.py        # Rebuilds tool embeddings cache
├── run_calibration.py         # Threshold calibration analyzer
├── setup_calibration_schedule.bat
├── systemControl.py           # Volume, brightness, apps, power (root-level hardware control)
├── spotifyControl.py          # Spotify Web API integration
├── cameraAccess.py            # Webcam capture + vision analysis
├── modules/                   # ~70 capability modules
│   ├── toolRegistry.py        #   84-tool catalog
│   ├── toolRouter.py          #   Tool-use loop (Qwen 3)
│   ├── toolExecutor.py        #   Safe execution + approval gates
│   ├── toolEmbeddings.py      #   Semantic tool pre-filter
│   ├── toolGroups.py          #   8 tool categories
│   ├── validationGate.py      #   Catches hallucinated tool parameters
│   ├── normalization.py       #   Multi-command splitting, filler stripping
│   ├── stateMachine.py        #   Generalized approval-gate state machine
│   ├── smartRouter.py         #   Fast-path routing
│   ├── modelRouter.py         #   Model selection + health checks
│   ├── languageIntelligence.py#   Phonetic/Tagalog/pronoun preprocessing
│   ├── deepMemory.py          #   Vector memory + summaries + goals
│   ├── persistentMemory.py    #   Cross-session auto-learning
│   ├── multiAgent.py          #   Planner → workers → synthesizer
│   ├── selfRepair.py          #   Watchdog, resource guardian, crash recovery
│   ├── ...                    #   (tasks, notes, timers, browser agent, Telegram,
│   │                          #    screen vision, file search/RAG, metrics, plugins, ...)
│   └── eval_harness.py        #   50-query evaluation suite
├── JarvisUI/JarvisPanel.html  # Optional UI panel
├── jarvis_stats.html          # Stats dashboard (open in browser)
├── knowledge_routing.txt      # 1.5B/8B knowledge-query routing rules
├── MyCommands.txt             # Example voice commands
├── CHANGES.md                 # Full changelog (fixes + phases 1–6)
├── UPGRADE_NOTES.md           # 6.0 → 6.1 upgrade notes (tool-use routing)
├── IMPLEMENTATION PLAN/       # Original 6-tier implementation plan
└── jarvis_system_report.md    # Deep-dive system report (6.0-era, still very useful)
```

---

## 9. Troubleshooting

| Symptom | Fix |
|---------|-----|
| "ToolRouter: Error — falling back to old router" | Ollama not running (`ollama serve`) or `qwen3:8b` not pulled (`ollama pull qwen3:8b`) |
| Model health board shows failures | Pull the missing models (section 2), then restart |
| Mic never triggers | Re-run and let the 2-second calibration run in a quiet room; lower `OWW_DETECTION_THRESHOLD` for more sensitivity |
| Mishears words | The phonetic dictionary (167 entries) is in `modules/languageIntelligence.py` — add your own corrections |
| Slow replies on simple chat | Check `USE_CASUAL_CHAT_MODEL = True`; the 1.5B fast path needs `qwen2.5:1.5b-instruct` pulled |
| Tools misbehave after edits | Rebuild the cache: `py build_tool_cache.py` |
| Anything else breaks | Flip `USE_TOOL_ROUTER = False` for the battle-tested old routing, or restore `.bak` files |

---

*JARVIS addresses you as "Sir", never names its base models, and was created by Mr. Kirby Paladan.*
