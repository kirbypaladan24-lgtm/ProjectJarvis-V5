# ──────────────────────────────────────────────────────────────────────────────
# config.py — JARVIS Centralized Configuration                          Tier 6
# All settings, paths, models, and thresholds live here.
# Change anything without hunting through 16 files.
# ──────────────────────────────────────────────────────────────────────────────

import os

# -- .env loader (stdlib only) -- secrets live in .env next to config.py.
# Real environment variables always win over .env file values.
def _load_dotenv():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))
    except OSError:
        pass

_load_dotenv()

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
MODULES_DIR = os.path.join(BASE_DIR, "modules")

# ── Model Stack (Tier 0) ──────────────────────────────────────────────────────
# Hardware rule: One model per request always.
# Escalation only when router confidence is below CONFIDENCE_THRESHOLD.
# Never parallel by default.
#
# UPGRADED 2026-08: Switched to Qwen 3 + uncensored vision stack
# - Qwen 3 8B has native tool-use support (the key upgrade)
# - Vision models are uncensored variants (no preaching for sensitive content)
# - Kept DeepSeek-Coder 6.7B as code specialist (still solid)

VOICE_FACE_MODEL     = "qwen3:8b"              # All spoken responses — the only JARVIS voice
INTENT_MODEL         = "qwen3:8b"              # Now uses tool-use, not classification (was 0.5B)
CODE_MODEL           = "deepseek-coder:6.7b"   # Code questions — generates silently (kept)
FALLBACK_MODEL       = "artifish/llama3.2-uncensored"  # Emergency fallback (was llama3:instruct)
CONFIDENCE_THRESHOLD = 0.70                     # Below this escalates to FALLBACK_MODEL

# ── Fast Pre-Filter Model (NEW) ──────────────────────────────────────────────
# Tiny model used to pre-classify inputs as "chat" vs "needs tool"
# Skips the full router for simple greetings/conversation
FAST_FILTER_MODEL    = "qwen2.5:1.5b-instruct"

# ── Multi-Agent Model Roles (UPGRADED) ───────────────────────────────────────
AGENT_PLANNER_MODEL     = "qwen3:4b"            # was phi3:mini — Qwen 3 4B supports tool-use
AGENT_WORKER_MODEL      = "qwen3:8b"            # was qwen2.5:7b — upgraded to Qwen 3
AGENT_CODE_MODEL        = "deepseek-coder:6.7b"   # Code subtasks (kept)
AGENT_SYNTHESIZER_MODEL = "qwen3:8b"            # was qwen2.5:7b — upgraded to Qwen 3
AGENT_MAX_WORKERS       = 3
AGENT_WORKER_TIMEOUT    = 120
AGENT_COMPLEX_TRIGGERS  = [
    "research and write", "analyze and summarize", "compare and contrast",
    "find everything about", "deep dive", "full report", "comprehensive",
    "refactor all", "rewrite all", "summarize all files", "investigate",
]

# Legacy aliases (backward compat with tts.py references)
DEFAULT_JARVIS_MODEL = VOICE_FACE_MODEL
MODEL_FAST           = INTENT_MODEL
MODEL_SMART          = CODE_MODEL
MODEL_SECONDARY      = VOICE_FACE_MODEL

# ── Paths ─────────────────────────────────────────────────────────────────────
MEMORY_FILE           = os.path.join(BASE_DIR, "ai_memory.json")
PROFILE_FILE          = os.path.join(BASE_DIR, "user_profile.json")
TASKS_FILE            = os.path.join(BASE_DIR, "tasks.json")
TIMERS_FILE           = os.path.join(BASE_DIR, "timers.json")
RECURRING_FILE        = os.path.join(BASE_DIR, "recurring_timers.json")
NOTES_FILE            = os.path.join(BASE_DIR, "notes.json")
HISTORY_FILE          = os.path.join(BASE_DIR, "command_history.json")
PERSONALITY_FILE      = os.path.join(BASE_DIR, "personality_state.json")
KNOWLEDGE_FILE        = os.path.join(BASE_DIR, "knowledge_base.json")
GOAL_TRACKER_FILE     = os.path.join(BASE_DIR, "long_term_goals.json")
CRASH_JOURNAL_FILE    = os.path.join(BASE_DIR, "crash_journal.json")
DAILY_SUMMARY_FILE    = os.path.join(BASE_DIR, "daily_summaries.json")
RESPONSE_CACHE_FILE   = os.path.join(BASE_DIR, "response_cache.json")
SNAPSHOT_FILE         = os.path.join(BASE_DIR, "project_snapshot.json")

# ── Voice / Audio ─────────────────────────────────────────────────────────────
VOICE                 = r"C:\piper\voices\en_US-danny-low.onnx"
SAMPLE_RATE           = 16000
CHUNK_DURATION        = 2
COMMAND_TIMEOUT       = 8
PROTECT_SPEECH_VOLUME = True     # Raise master volume if it is too low for JARVIS speech
MIN_SPEECH_VOLUME     = 35       # Minimum master volume used before speaking

# ── Memory ────────────────────────────────────────────────────────────────────
MAX_HISTORY           = 20
CONTEXT_RESTART_MSGS  = 5        # Last N exchanges loaded on restart

# ── Spotify Integrations ──────────────────────────────────────────────────────
SPOTIFY_CLIENT_ID     = os.environ.get("SPOTIFY_CLIENT_ID", "")        # .env
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "")    # .env
SPOTIFY_REDIRECT_URI  = os.environ.get("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback")

# ── Vector Memory (Tier 4) ────────────────────────────────────────────────────
# Hardware rule: max 5 results, 0.55 threshold — was too strict at 0.75
# Lowered threshold so RAG actually returns results
MAX_VECTOR_RESULTS    = 5
VECTOR_THRESHOLD      = 0.55
EMBEDDING_MODEL       = "nomic-embed-text" # <-- FIXED: Dedicated embedding model (Run: ollama pull nomic-embed-text)

# ── Daily Summary (Tier 4) ────────────────────────────────────────────────────
DAILY_SUMMARY_HOUR    = 23       # Hour (24h) to generate summary (11 PM)

# ── Idle & Focus Detection (Tier 1) ──────────────────────────────────────────
# Hardware rule: event-driven, not a polling loop
IDLE_TIMEOUT_MINUTES  = 5        # Minutes before one proactive check-in
AWAKE_TIMEOUT         = 30       # Seconds before wake-word session times out

# ── Body Awareness Thresholds (Tier 1) ───────────────────────────────────────
BATTERY_WARN_LOW      = 20       # % — first alert
BATTERY_WARN_CRIT     = 10       # % — critical alert
CPU_TEMP_THRESHOLD    = 85       # °C — thermal warning fires above this
DISK_FREE_WARN_GB     = 5        # GB — disk space warning

# ── Mic Auto-Calibration (Tier 6) ────────────────────────────────────────────
MIC_CALIBRATION_SECS  = 2        # Seconds of ambient sampling on startup
MIC_ENERGY_FLOOR      = 150      # Fallback energy threshold if calibration fails

# ── Response Cache (Tier 6) ──────────────────────────────────────────────────
RESPONSE_CACHE_TTL    = 300      # Seconds before cache expires (5 minutes)

# ── Auto-Copy (Tier 6) ───────────────────────────────────────────────────────
AUTO_COPY_THRESHOLD   = 300      # Chars — responses longer than this auto-copy to clipboard
AUTO_COPY_RESPONSES   = False    # Keep normal JARVIS answers out of clipboard by default
AUTO_COPY_CODE        = False    # Only enable if you want generated code copied automatically
LOG_SPOKEN_TEXT       = True     # Print the exact cleaned text sent to the voice engine
ENABLE_RESPONSE_CACHE = True     # Re-enabled with smarter skip-keyword list (Phase 2)

# ── Custom Voice Shorthands (Tier 2) ─────────────────────────────────────────
# Edit these to add your own personal triggers
CUSTOM_SHORTHANDS = {
    "yt":  "open youtube",
    "gg":  "google search",
    "mtg": "list today's tasks",
    "vs":  "open visual studio code",
    "gh":  "open github",
}

# ── Tagalog-English Keywords (Tier 2) ────────────────────────────────────────
TAGALOG_MAP = {
    "buksan":    "open",
    "isara":     "close",
    "i-play":    "play",
    "i-pause":   "pause",
    "susunod":   "next",
    "nakaraan":  "previous",
    "hinto":     "stop",
    "volume":    "volume",
    "mas malakas": "louder",
    "mas mahina":  "quieter",
    "matulog":   "sleep",
    "gising":    "wake up",
    "bukuhin":   "open",
    "patakbuhin": "run",
    "tanggalin":  "delete",
    "i-save":    "save",
    "hanapin":   "find",
    "ipakita":   "show",
    "ikansela":  "cancel",
    "kumpirmahin": "confirm",
    "listahan":  "list",
    "mag-type":  "type",
    "isulat":    "write",
    "basahin":   "read",
    "sabihin":   "say",
    "ulitin":    "repeat",
    "ang":       "",
    "mo":        "",
    "ko":        "",
    "na":        "",
    "sa":        "in",
    "ng":        "",
    "mga":       "",
    "at":        "and",
    "o":         "or",
}

# ── Phonetic Mishear Corrections (Tier 2) ────────────────────────────────────
PHONETIC_CORRECTIONS = {
    "jerry vis":        "jarvis",
    "jar vis":          "jarvis",
    "jar viss":         "jarvis",
    "jarvas":           "jarvis",
    "jarves":           "jarvis",
    "jarvus":           "jarvis",
    "spotter fly":      "spotify",
    "spot if i":        "spotify",
    "spottify":         "spotify",
    "sport if i":       "spotify",
    "you tube":         "youtube",
    "you toob":         "youtube",
    "you chube":        "youtube",
    "chrome book":      "chromebook",
    "visual studio cod": "visual studio code",
    "vs code":          "visual studio code",
    "git hub":          "github",
    "git hub.com":      "github",
    "windows explore":  "windows explorer",
    "task manage":      "task manager",
}

# ── Privacy Mode (Tier 5) ─────────────────────────────────────────────────────
PRIVACY_REMINDER_MINS  = 10      # Remind every N minutes while in private mode

# ── Security / Encryption (Tier 5) ───────────────────────────────────────────
ENCRYPT_MEMORY         = False   # AES encryption on JSON memory files — opt-in

# ── Approval Gate — Destructive Actions (Tier 3) ─────────────────────────────
# Any of these action types MUST require a spoken "confirm" before executing
APPROVAL_REQUIRED_ACTIONS = [
    "delete", "uninstall", "git_push", "git_force",
    "run_script", "format_drive", "organize_files", "clear_history",
]

# ── Voice Macro Chains (Tier 3) ───────────────────────────────────────────────
# Each key is a spoken trigger phrase; value is a list of commands to execute
MACRO_CHAINS = {
    "start work mode": [
        "open visual studio code",
        "pause spotify",
        "tasks today",
    ],
    "end work mode": [
        "save note session ended",
    ],
    "focus mode": [
        "pause spotify",
        "tasks today",
    ],
    "prepare for meeting": [
        "open visual studio code",
        "pause spotify",
        "tasks today",
    ],
}

# ── Morning Briefing (Tier 6) ─────────────────────────────────────────────────
MORNING_BRIEFING_START = 5       # Hour (24h)
MORNING_BRIEFING_END   = 12      # Hour (24h)
DEFAULT_CITY           = "Manila" # <-- FIXED: Parameterized default geographic query

# ── Long-term Goal Tracker (Tier 4) ──────────────────────────────────────────
# Hardware rule: simple Python threshold, no model in the loop
GOAL_NUDGE_INTERVAL_DAYS = 7    # Weekly progress nudge

# ── Resource Overload Guardian (Tier 5) ──────────────────────────────────────
# Hardware rule: simple Python threshold, no model in the loop
RAM_OVERLOAD_PCT       = 90      # % RAM usage threshold
CPU_OVERLOAD_PCT       = 95      # % CPU sustained threshold

# ── Ollama ────────────────────────────────────────────────────────────────────
OLLAMA_BASE_URL        = "http://localhost:11434"
OLLAMA_TIMEOUT         = None    # Stream timeout (None = unlimited)

# ── Multi-Agent Model Roles (LEGACY — kept for reference, superseded above) ───
# These are now defined in the UPGRADED section above. Kept here only for
# modules that might import them directly (shouldn't happen after refactor).
# AGENT_PLANNER_MODEL     = "phi3:mini"
# AGENT_WORKER_MODEL      = "qwen2.5:7b-instruct"
# AGENT_CODE_MODEL        = "deepseek-coder:6.7b"
# AGENT_SYNTHESIZER_MODEL = "qwen2.5:7b-instruct"
AGENT_MAX_WORKERS       = 3
AGENT_WORKER_TIMEOUT    = 120

# ── Telegram Remote Access ────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN      = os.environ.get("TELEGRAM_BOT_TOKEN", "")     # .env - token from @BotFather
TELEGRAM_ALLOWED_IDS    = [int(x) for x in os.environ.get("TELEGRAM_ALLOWED_IDS", "").replace(",", " ").split() if x.strip().isdigit()]  # .env - Telegram user IDs allowed to control JARVIS
TELEGRAM_VOICE_REPLY    = True   # Reply with voice note in addition to text

# ── Smart VAD — End-of-Speech Detection ──────────────────────────────────────
VAD_AGGRESSIVENESS      = 2      # 0 = permissive, 3 = strict. 2 is best for indoors
VAD_FRAME_MS            = 30     # Frame size (webrtcvad supports 10, 20, 30)
VAD_PRE_ROLL_MS         = 400    # Audio kept before speech starts — captures first syllable
VAD_END_OF_SPEECH_MS    = 1200   # Silence duration before committing utterance
VAD_MAX_UTTERANCE_SECS  = 30     # Hard cap to prevent infinite open mic

# ── Always-On Wake Word (openWakeWord) ───────────────────────────────────────
USE_OPENWAKEWORD        = True
OWW_WAKE_WORD_MODEL     = "hey_jarvis"
OWW_DETECTION_THRESHOLD = 0.5   # 0.0–1.0 — lower = more sensitive
OWW_FRAME_MS            = 80    # openWakeWord processes 80ms frames

# ── Semantic File Content Index (RAG) ─────────────────────────────────────────
FILE_INDEX_PATH         = os.path.join(BASE_DIR, "file_content_index")
FILE_INDEX_CHUNK_CHARS  = 800
FILE_INDEX_CHUNK_OVERLAP= 100
FILE_INDEX_MAX_FILE_MB  = 20
FILE_INDEX_TOP_K        = 5
FILE_INDEX_EXTENSIONS   = [
    ".txt", ".md", ".py", ".js", ".ts", ".json", ".csv", ".log",
    ".html", ".css", ".yaml", ".yml", ".ini", ".cfg", ".toml",
    ".pdf", ".docx", ".doc", ".xlsx", ".xls",
]
FILE_INDEX_REBUILD_HOURS = 6

# ── Browser Agent (Playwright) ────────────────────────────────────────────────
BROWSER_HEADLESS        = False
BROWSER_TIMEOUT_MS      = 15000
BROWSER_SCREENSHOT_PATH = os.path.join(BASE_DIR, "browser_screenshot.png")

# ── Screen Understanding ──────────────────────────────────────────────────────
SCREEN_VISION_MODEL     = "llava:7b"
SCREEN_SHOT_RESIZE_W    = 1280
SCREEN_SHOT_RESIZE_H    = 720

# ── Meeting Transcription ─────────────────────────────────────────────────────
MEETING_CHUNK_SECS           = 30
MEETING_SUMMARY_MODEL        = "qwen3:8b"
MEETING_MAX_TRANSCRIPT_CHARS = 12000

# ── Vision ────────────────────────────────────────────────────────────────────
# UPGRADED 2026-08: Switched from LLaVA to Qwen 2.5 VL (abliterated = uncensored)
# - Better OCR and screen reading
# - No preaching on sensitive content
# - Native tool-use capable
VISION_MODEL_FAST      = "redule26/huihui_ai_qwen2.5-vl-7b-abliterated"
VISION_MODEL_DETAIL    = "llama3.2-vision:11b"
SCREEN_VISION_MODEL    = "redule26/huihui_ai_qwen2.5-vl-7b-abliterated"

# ── Tool Router (NEW — 2026-08) ──────────────────────────────────────────────
# The new tool-use architecture: Qwen 3 picks tools itself
USE_TOOL_ROUTER        = True                # Master switch — toggle to fall back to old detect_intent()
TOOL_ROUTER_MODEL      = "qwen3:8b"          # Same as VOICE_FACE_MODEL (one brain, many tools)
TOOL_PRE_FILTER_K      = 12                  # Show router only top 12 most relevant tools per query
TOOL_MAX_ITERATIONS    = 2                   # Max tool calls per request (2 = one tool + one verification. Prevents runaway tool chains)
TOOL_USE_EMBEDDING_FILTER = True             # Use embeddings to pre-filter tools (saves tokens)
TOOL_USE_THINK_MODE    = False               # Qwen 3 <think> mode for complex queries (slower but smarter)
TOOL_TEMPERATURE       = 0.3                 # Lower temp = more deterministic tool selection
TOOL_STREAM_FINAL_RESPONSE = True            # Stream the final response to user

# ── Casual Chat Fast-Path (NEW — 2026-08) ───────────────────────────────────
# Use a tiny 1.5B model for casual conversation (greetings, simple questions,
# opinions, acknowledgments). Qwen 3 8B only fires when tools are needed.
# Cuts response time from 5-8s to 1-2s for casual chat.
USE_CASUAL_CHAT_MODEL  = True                # Master switch for casual chat fast-path
CASUAL_CHAT_MODEL      = "qwen2.5:1.5b-instruct"  # Tiny model, 1 GB, instant load
CASUAL_CHAT_MAX_TOKENS = 200                 # Cap response length for casual chat
CASUAL_CHAT_TEMPERATURE = 0.5                # Slightly more conversational

# ── A/B Testing (NEW — 2026-08) ─────────────────────────────────────────────
# When enabled, 50% of commands go to control (current router), 50% to treatment.
# Both paths log results for comparison. Set to True to enable testing.
USE_AB_TESTING         = False               # Master switch for A/B testing (default off)
AB_TEST_CONTROL_PCT    = 50                  # Percentage of commands to control group

# ── Validation Gate (NEW — Phase 1, 2026-08-09) ─────────────────────────────
# Independent validation layer that runs AFTER the 1.5B picks a tool
# but BEFORE the tool is executed. Catches hallucinations before they
# cause wrong actions.
#
# Three checks:
#   1. Embedding similarity (input vs tool description)
#   2. Argument sanity (ranges, placeholders, file existence)
#   3. Verb alignment (off by default — too aggressive for natural language)
#
# Outcomes:
#   - pass (sim >= 0.60) → execute
#   - borderline (0.40 <= sim < 0.60) → ask 8B for second opinion
#   - fail (sim < 0.40, or arg sanity fails) → escalate to 8B router
#
# All decisions logged to validation_log.jsonl for calibration.
VALIDATION_ENABLE_SIMILARITY = True          # Embedding similarity check
VALIDATION_ENABLE_ARG_SANITY = True          # Argument sanity check (ranges, placeholders)
VALIDATION_ENABLE_VERB_ALIGN = False         # Verb alignment (off — too aggressive)
VALIDATION_ENABLE_LOGGING    = True          # Log all validation decisions

# Similarity thresholds (cosine similarity, 0.0 to 1.0)
# These are defaults — adjust based on validation_log.jsonl data over time.
VALIDATION_SIM_PASS      = 0.60              # >= 0.60 → pass
VALIDATION_SIM_BORDERLINE = 0.40             # 0.40-0.60 → second opinion from 8B
                                              # < 0.40 → fail (escalate to 8B)

# ── Normalization Layer (NEW — Phase 2, 2026-08-09) ──────────────────────────
# Conservative input normalization that runs BEFORE the tool router.
#
# Three functions:
#   1. Multi-command splitting ("set volume to 50 and play Drake" → 2 commands)
#      ONLY splits when conjunctions connect two imperative verbs.
#   2. Incomplete command detection ("play" with no argument → "Play what, Sir?")
#      Skips if the last assistant message was a question (input is an answer).
#   3. Leading filler stripping ("please open chrome" → "open chrome")
#      Does NOT strip trailing fillers or inside quotes.
#
# All decisions logged to normalization_log.jsonl.
NORMALIZATION_ENABLE_SPLIT      = True       # Multi-command splitting
NORMALIZATION_ENABLE_INCOMPLETE = True       # Incomplete command detection
NORMALIZATION_ENABLE_FILLERS    = True       # Leading filler stripping
NORMALIZATION_ENABLE_LOGGING    = True       # Log all normalization decisions
NORMALIZATION_MAX_SUBCOMMANDS   = 3          # Max sub-commands per split (prevents abuse)

# ── Tool Groups (NEW — Phase 3, 2026-08-09) ─────────────────────────────────
# Categorizes all 83 tools into 8 groups to reduce the 1.5B model's decision
# space. Instead of picking from 83 flat tools, the 1.5B sees tools organized
# by category — providing semantic context that reduces hallucination.
#
# Groups:
#   1. CHAT           — conversation, memory, meta (7 tools)
#   2. MEDIA_CONTROL  — volume, brightness, power, spotify (11 tools)
#   3. APPS_WINDOWS   — open/close apps, window management (5 tools)
#   4. TASKS_NOTES    — tasks, notes, facts, timers (16 tools)
#   5. FILES          — file search, read, compress, diff (9 tools)
#   6. INTERNET       — web lookups, calculations (10 tools)
#   7. SYSTEM_VISION  — monitor, specs, camera, screen (13 tools)
#   8. DEV_TOOLS      — code, git, clipboard, privacy, utilities (12 tools)
#
# The 1.5B outputs GROUP + TOOL + ARGS + CONF in one call.
# Single model call (no latency doubling) with reduced decision space.
# Paired with embedding pre-filter (top 12 tools shown instead of 83).
TOOL_GROUPS_ENABLED              = True       # Master switch for tool groups
TOOL_GROUPS_LOG_MISMATCHES       = True       # Log when 1.5B states wrong group

# ── State Machine (NEW — Phase 4, 2026-08-09) ────────────────────────────────
# Generalizes the _awaiting_confirmation event into a full state machine
# that handles multi-turn interactions:
#
# States:
#   IDLE                    — normal operation
#   AWAITING_APPROVAL       — "Confirm shutdown?" (yes/no)
#   AWAITING_DISAMBIGUATION — "Did you mean file A or file B?" (pick option)
#   AWAITING_ARG            — "Set volume to what?" (provide a value)
#   AWAITING_CLARIFICATION  — "I didn't understand, can you rephrase?"
#
# Features:
#   1. Universal cancel — "cancel", "never mind", "forget it" work in ANY state
#   2. 30-second timeout — auto-clears state if user doesn't respond
#   3. New-command detector — action verb at start → clear state, process normally
#      (disabled for AWAITING_ARG — verb could be a value like "play")
#   4. Thread-safe — lock protects all state transitions
#   5. Backward compatible — sets _awaiting_confirmation when active
STATE_MACHINE_ENABLED            = True       # Master switch for state machine
STATE_MACHINE_TIMEOUT            = 30         # Default timeout in seconds
STATE_MACHINE_ENABLE_LOG         = True       # Log state transitions

# ── Multi-Command Synthesis (NEW — Phase 5, 2026-08-09) ──────────────────────
# When the normalization layer (Phase 2) splits a multi-command like
# "set volume to 50 and play Drake" into sub-commands, this module:
#
#   1. Executes each sub-command through the tool router independently
#   2. Sends all results to the 1.5B model for synthesis into ONE natural
#      sentence
#   3. Speaks the synthesized response once
#
# Produces: "Done, Sir — volume set to 50 and playing Drake."
# Instead of: "Volume set to 50, Sir. Playing Drake, Sir." (robotic serial)
#
# If synthesis fails (e.g., Ollama down), falls back to concatenated
# responses (still a single speak() call, not serial).
MULTI_COMMAND_ENABLED            = True       # Master switch for multi-command synthesis
MULTI_COMMAND_SYNTHESIS_ENABLED  = True       # Use 1.5B to synthesize (False = just concatenate)
MULTI_COMMAND_MAX_TOKENS         = 120        # Max tokens for synthesis response
MULTI_COMMAND_TEMPERATURE        = 0.4        # Temperature for synthesis (lower = more deterministic)
MULTI_COMMAND_ENABLE_LOG         = True       # Log multi-command executions
MULTI_COMMAND_TIMEOUT            = 10         # Timeout for synthesis API call (seconds)
MULTI_COMMAND_PARALLEL           = True       # Tier 2.2: Run independent sub-commands in parallel

# ── Calibration (NEW — Phase 6, 2026-08-09) ──────────────────────────────────
# Analyzes all JSONL log files from Phases 1-5 and generates a calibration
# report with per-tool statistics and actionable recommendations.
#
# Per-tool thresholds allow overriding the global VALIDATION_SIM_PASS and
# VALIDATION_SIM_BORDERLINE for specific tools. Useful when a tool's
# description scores low on similarity even when correctly matched.
#
# To run calibration:
#   py run_calibration.py              # Generate report + dry-run thresholds
#   py run_calibration.py --apply      # Generate report + auto-apply thresholds
#   py run_calibration.py --json       # Save JSON report only
#
# Per-tool overrides are stored in per_tool_thresholds.json (auto-created).
# Run calibration weekly to track accuracy over time.
CALIBRATION_ENABLED              = True       # Master switch for calibration
PER_TOOL_THRESHOLDS_ENABLED      = True       # Use per-tool threshold overrides
CALIBRATION_AUTO_APPLY           = False      # Auto-apply thresholds (use --apply flag instead)
CALIBRATION_MIN_SAMPLES          = 5          # Min samples per tool before recommending changes

# ═══════════════════════════════════════════════════════════════════════
# TIER 1 PERFORMANCE SETTINGS (NEW — 2026-08-09)
# ═══════════════════════════════════════════════════════════════════════

# ── Whisper STT (Tier 1.1) ──────────────────────────────────────────────
# Run speech-to-text on GPU instead of CPU for ~60-70% latency reduction.
# Requires CUDA-capable GPU. Falls back to CPU automatically if CUDA unavailable.
# GPU: ~300-500ms transcription | CPU: ~1-2s transcription
WHISPER_DEVICE        = "cpu"      # "cuda" (GPU) or "cpu"
WHISPER_COMPUTE_TYPE  = "int8"     # "float16" (GPU) or "int8" (CPU)
WHISPER_CPU_THREADS   = 6          # Only used when device="cpu"
WHISPER_NUM_WORKERS   = 2          # Only used when device="cpu"

# ── STT Confidence Gating (Tier 2.3) ───────────────────────────────────
# When transcription confidence is very low, JARVIS asks the user to repeat
# instead of processing a likely-wrong transcription.
#   - 0.20 = very aggressive (only gate truly garbage transcriptions)
#   - 0.35 = moderate (catches more, but may frustrate on short utterances)
#   - 0.0  = disabled (process everything, even garbage)
STT_CONFIDENCE_GATE       = 0.20   # Below this = ask to repeat
STT_CONFIDENCE_WARN       = 0.35   # Below this = warn but still process
STT_MAX_RETRIES           = 1      # How many times to ask for repeat before giving up

# ── Ollama keep_alive (Tier 1.2) ────────────────────────────────────────
# Keeps models loaded in memory between requests to eliminate cold-start latency.
# Default Ollama behavior unloads after 5 minutes of inactivity.
#   -1 = always keep loaded (never unload)
#   N = keep loaded for N seconds after last use
#   0 = unload immediately after each request
KEEPALIVE_CASUAL_CHAT = -1          # 1.5B: always hot (handles 70-80% of commands)
KEEPALIVE_TOOL_ROUTER = 1800        # 8B: keep for 30 minutes (complex commands)
KEEPALIVE_CODE_MODEL  = 300         # DeepSeek: 5 minutes (occasional code queries)
KEEPALIVE_FALLBACK    = 300         # Llama 3.2: 5 minutes (rare fallback)
KEEPALIVE_EMBEDDING   = 300         # nomic-embed-text: 5 minutes
KEEPALIVE_VISION      = 60          # Vision models: 1 minute (rare, save VRAM)

def get_keep_alive(model_name):
    """
    Returns the keep_alive value for a given model.
    Usage in Ollama API calls:
        payload = {"model": model, "messages": [...], "keep_alive": get_keep_alive(model)}
    """
    if not model_name:
        return 300
    m = model_name.lower()
    # 1.5B casual chat model — always hot
    if "1.5b" in m or "qwen2.5:1.5b" in m:
        return KEEPALIVE_CASUAL_CHAT
    # 8B tool router / voice face
    if "qwen3:8b" in m or "qwen3:8" in m:
        return KEEPALIVE_TOOL_ROUTER
    # DeepSeek coder
    if "deepseek" in m or "code" in m:
        return KEEPALIVE_CODE_MODEL
    # Fallback model (llama3.2)
    if "llama" in m or "fallback" in m:
        return KEEPALIVE_FALLBACK
    # Embedding model
    if "embed" in m or "nomic" in m:
        return KEEPALIVE_EMBEDDING
    # Vision models
    if "vl" in m or "vision" in m or "llava" in m:
        return KEEPALIVE_VISION
    # Default
    return 300


# ═══════════════════════════════════════════════════════════════════════
# TIER 3 CAPABILITY SETTINGS (NEW — 2026-08-09)
# ═══════════════════════════════════════════════════════════════════════

# ── Persistent Memory (Tier 3.1) ───────────────────────────────────────
# Auto-learns facts from conversations and persists them across sessions.
# Uses the 8B model to extract memorable facts every N exchanges.
# Facts are embedded with nomic-embed-text for semantic recall.
PERSISTENT_MEMORY_ENABLED            = True
PERSISTENT_MEMORY_FILE               = os.path.join(BASE_DIR, "persistent_memory.json")
PERSISTENT_MEMORY_MAX_FACTS          = 500       # Max facts to store
PERSISTENT_MEMORY_MAX_AGE_DAYS       = 90        # Auto-cleanup after 90 days
PERSISTENT_MEMORY_THRESHOLD          = 0.55      # Similarity threshold for recall
PERSISTENT_MEMORY_AUTO_LEARN_INTERVAL = 5        # Extract facts every N exchanges
PERSISTENT_MEMORY_ENABLE_LOG         = True

# ── Plugin System (Tier 3.2) ───────────────────────────────────────────
# Allows live tool registration without restarting JARVIS.
# Drop .py files in the plugins/ directory — they're auto-loaded.
PLUGIN_SYSTEM_ENABLED    = True
PLUGINS_DIR              = os.path.join(BASE_DIR, "plugins")
PLUGIN_WATCH_INTERVAL    = 5         # Check for new plugins every N seconds
PLUGIN_SYSTEM_ENABLE_LOG = True

# ── Streaming Tool Results (Tier 3.3) ──────────────────────────────────
# Speak news headlines as they arrive instead of waiting for all results.
# Reduces perceived latency on internet-dependent tools (get_news, web_search).
STREAMING_RESULTS_ENABLED = True
STREAMING_RESULTS_TOOLS   = ["get_news", "web_search", "wikipedia_summary"]  # Tools that support streaming

# ── Knowledge File Injector (Tier 4) ───────────────────────────────────
# Drop files (PDF, Word, text, JSON) in the knowledge/ directory and
# JARVIS indexes them for semantic search. Ask questions about your
# own documents and JARVIS answers based on their content.
#
# Supported: .pdf, .docx, .doc, .txt, .md, .json, .log, .ini, .cfg, .xlsx
# The system watches for file changes and re-indexes automatically.
KNOWLEDGE_INJECTOR_ENABLED        = True
KNOWLEDGE_DIR                     = os.path.join(BASE_DIR, "knowledge")
KNOWLEDGE_INDEX_FILE              = os.path.join(BASE_DIR, "knowledge_index.json")
KNOWLEDGE_WATCH_INTERVAL          = 10         # Check for changes every N seconds
KNOWLEDGE_MAX_CHUNKS_INJECTED     = 3          # Max chunks to inject into system prompt
KNOWLEDGE_SIMILARITY_THRESHOLD    = 0.55       # Minimum similarity to include
KNOWLEDGE_CHUNK_CHARS             = 800        # Chunk size in characters
KNOWLEDGE_CHUNK_OVERLAP           = 100        # Overlap between chunks
KNOWLEDGE_MAX_FILE_MB             = 20         # Max file size to index
KNOWLEDGE_ENABLE_LOG              = True
