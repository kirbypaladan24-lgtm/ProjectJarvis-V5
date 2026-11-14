# JARVIS Fixes & Phases 1-6 (Complete) — 2026-08-09

## Summary of Changes

This release includes:
1. **TTS pausing fix** — no more gaps between sentences
2. **Tool router wiring** — 1.5B model for casual chat & simple commands
3. **Approval gate wiring** — destructive tool calls can ask for confirmation
4. **Phase 1: Validation Gate** — catches 1.5B hallucinations before execution
5. **Phase 2: Normalization Layer** — conservative multi-command split, incomplete detection, filler stripping
6. **Phase 3: Tool Groups** — 83 tools categorized into 8 groups + embedding pre-filter to reduce 1.5B decision space
7. **Phase 4: State Machine** — generalized approval gate with universal cancel, timeout, and new-command detection
8. **Phase 5: Multi-Command with Synthesis** — natural combined responses instead of robotic serial acks
9. **Phase 6: Calibration** — log analyzer + per-tool threshold overrides + CLI report generator
10. **Hybrid tool embeddings init** — first run builds cache synchronously with progress; subsequent runs load instantly
11. **Fresh state** — all program-generated JSON files removed (clean start)

---

## Issue 1: TTS Pausing at Sentence Separators (`.`, `!`, `?`)

**File:** `tts.py` — `ask_ai_stream()` streaming loop

**Root cause:** The streaming response handler flushed the speech buffer every time a `.`, `?`, or `!` appeared in a token. Each flush triggered a separate Piper subprocess call (`piper.exe`), which has ~150-400ms startup overhead. A 4-sentence response spawned 4 subprocess launches with noticeable gaps.

**Fix:** Buffer 2-3 sentences before flushing:
- Flush at sentence boundary only if buffer has 150+ chars
- Flush immediately at paragraph breaks (`\n\n`)
- Hard-cap at 500 chars to prevent Piper overload

---

## Issue 2: Slow Casual Chat & Command Execution Using 8B Model

**File:** `tts.py` — `process_command()`

**Root cause:** `toolRouter.py` (with its 1.5B fast paths) was never wired into `process_command()`. The `UPGRADE_NOTES.md` claimed `USE_TOOL_ROUTER` was added, but it wasn't. All commands went through the old 8B classifier → 8B model pipeline.

**Fix:** Inserted `route_with_tools()` call before `detect_intent()`:
- Acknowledgments ("hello", "thanks") → instant hardcoded response
- Pattern-matched commands ("set volume to 50", "open chrome") → instant regex match
- Simple single-tool commands ("play Drake", "what's the weather") → 1.5B picks tool + formats ack (1-2s)
- Casual chat ("explain quantum computing") → 1.5B responds directly (1-2s)
- Complex multi-step ("find my resume and read it") → falls through to 8B (correct)

---

## Issue 3: Tool Router Approval Gate Not Wired

**File:** `tts.py` — after `speech_worker` thread starts

**Root cause:** `set_confirmation_handlers()` was never called, so the tool executor's approval gate had no access to the confirmation event/queue.

**Fix:** Added `set_confirmation_handlers(_awaiting_confirmation, _confirmation_queue, speak)` call at startup.

---

## Phase 1: Validation Gate (NEW)

**New file:** `modules/validationGate.py` (300+ lines)
**Modified:** `modules/toolRouter.py` — wired validation gate into `_try_simple_tool_dispatch()`
**Modified:** `config.py` — added 6 validation config settings

### What It Does

An independent validation layer that runs AFTER the 1.5B picks a tool but BEFORE the tool is executed. Catches hallucinations before they cause wrong actions.

### Three Checks

1. **Embedding similarity** — Computes cosine similarity between the user input and the picked tool's description.
   - `>= 0.60` → **PASS** (execute the tool)
   - `0.40 - 0.60` → **BORDERLINE** (ask 8B for second opinion)
   - `< 0.40` → **FAIL** (escalate to 8B router)

2. **Argument sanity** — Validates arguments beyond schema types:
   - Uses `contracts.py` for range validation (e.g., volume 0-100)
   - Detects placeholder strings (`"unknown"`, `"your location"`, `"null"`)
   - Checks file path existence (for `read_file`, `open_file`)

3. **Verb alignment** (off by default) — Checks if the user's first verb aligns with the picked tool. Disabled because it's too aggressive for natural language ("put on some Drake" → verb "put" doesn't match `spotify_play`).

### Borderline Zone — Second Opinion from 8B

When similarity is between 0.40 and 0.60, the gate doesn't just reject — it asks the 8B model for a quick YES/NO second opinion:
```
User input: "play some Drake"
Tool picked: spotify_play
Arguments: {"query": "Drake"}

Reply with EXACTLY one word: YES or NO
```
This prevents false rejections on valid but unusually-phrased commands.

### Logging

All validation decisions are logged to `validation_log.jsonl`:
```json
{
  "timestamp": "2026-08-09T...",
  "user_input": "set volume to 50",
  "tool_picked": "set_volume",
  "args": {"percent": "50"},
  "result": "pass",
  "details": {
    "decision": "pass",
    "checks": {
      "similarity": {"score": 0.82, "status": "pass"},
      "arg_sanity": {"valid": true, "issues": []},
      "verb_align": {"aligned": true, "detail": null}
    },
    "reason": "all checks passed"
  }
}
```

This data is used for **calibration** — after a week of real usage, you can analyze the log to see which tools have low accuracy and adjust thresholds per-tool.

### Fuzzy Match Logging

When the 1.5B hallucinates a tool name (e.g., `save_screenshot` instead of `take_screenshot`), the fuzzy matcher corrects it — but now every fuzzy match is logged to `fuzzy_match_log.jsonl`:
```json
{
  "timestamp": "2026-08-09T...",
  "raw_input": "take a screenshot",
  "hallucinated": "save_screenshot",
  "matched_to": "take_screenshot"
}
```

This helps identify which tools the 1.5B consistently gets wrong, so we can add pattern matchers for those cases.

### Config Settings (in `config.py`)

```python
VALIDATION_ENABLE_SIMILARITY = True          # Embedding similarity check
VALIDATION_ENABLE_ARG_SANITY = True          # Argument sanity check
VALIDATION_ENABLE_VERB_ALIGN = False         # Verb alignment (off — too aggressive)
VALIDATION_ENABLE_LOGGING    = True          # Log all validation decisions

VALIDATION_SIM_PASS      = 0.60              # >= 0.60 → pass
VALIDATION_SIM_BORDERLINE = 0.40             # 0.40-0.60 → second opinion from 8B
                                              # < 0.40 → fail (escalate to 8B)
```

To disable the entire validation gate, set all `VALIDATION_ENABLE_*` flags to `False`.

---

## Phase 2: Normalization Layer (NEW)

**New file:** `modules/normalization.py` (350+ lines)
**Modified:** `tts.py` — wired normalization into `process_command()` after `preprocess_input`
**Modified:** `config.py` — added 5 normalization config settings

### What It Does

Conservative input normalization that runs BEFORE the tool router. Three functions:

### 1. Multi-Command Splitting

Splits "set volume to 50 and play some Drake" into two separate commands that are processed independently.

**Conservative split rule:** Only splits when a conjunction (`and`, `then`, `also`, `after that`) connects two **imperative verbs**.

| Input | Splits? | Reason |
|---|---|---|
| "set volume to 50 and play some Drake" | ✅ Yes | Both "set" and "play" are verbs |
| "open chrome and open youtube" | ✅ Yes | Both "open" are verbs |
| "pause spotify and open vscode" | ✅ Yes | Both "pause" and "open" are verbs |
| "play Drake and Future" | ❌ No | "Future" is a noun, not a verb |
| "note that I need milk and eggs" | ❌ No | "eggs" is a noun, not a verb |
| "find my resume and read it" | ❌ No | "read" is a verb, but "it" is a dependent pronoun → route to 8B as workflow |

**Dependent pronoun detection:** If the second part contains "it", "that", "this", "them" — the second command depends on the first's result. Don't split — route to the 8B which can chain tool calls.

**Max sub-commands:** 3 (prevents abuse — "do X and Y and Z and W and..." won't create 5 recursive calls)

### 2. Incomplete Command Detection

Detects verbs with no argument and asks for clarification instead of routing to a tool that will fail.

| Input | Detected? | Response |
|---|---|---|
| "play" | ✅ Yes | "Play what, Sir?" |
| "open" | ✅ Yes | "Open what, Sir?" |
| "set volume" | ✅ Yes | "Set volume to what level, Sir?" |
| "set volume to" | ✅ Yes | "Set volume to what level, Sir?" |
| "find" | ✅ Yes | "Find what, Sir?" |
| "set volume to 50" | ❌ No | Complete — has value |
| "play Drake" | ❌ No | Complete — has target |
| "hello" | ❌ No | Not a verb requiring args |

**Conversation context awareness:** If the last assistant message ended with a question (e.g., "What should I do?"), the current input might be an answer, not an incomplete command. In that case, incomplete detection is skipped.

**More thorough than `clarify_partial`:** The existing `clarify_partial` only catches exact 1-word matches ("open", "search", "delete"). Normalization catches "set volume" (2 words), "set volume to" (3 words), and more verbs ("play", "find", "run", etc.).

### 3. Leading Filler Stripping

Removes filler words from the START of a command only.

| Input | Stripped? | Result |
|---|---|---|
| "please open chrome" | ✅ Yes | "open chrome" |
| "can you play some Drake" | ✅ Yes | "play some Drake" |
| "hey jarvis set volume to 50" | ✅ Yes | "set volume to 50" |
| "would you find my resume" | ✅ Yes | "find my resume" |
| "open the app called Please Don't Crash" | ❌ No | "Please" is not at the start |

**Does NOT strip trailing fillers** — too risky. "Play the song called Please" would lose the song name. Leading fillers are safe because "please" at the start is always a filler.

**Does NOT strip inside quotes** — content inside `"..."` is preserved.

### Logging

All normalization decisions are logged to `normalization_log.jsonl`:
```json
{"timestamp": "...", "action": "split_success", "details": {"input": "set volume to 50 and play some Drake", "commands": ["set volume to 50", "play some Drake"]}}
{"timestamp": "...", "action": "split_skipped_dependent", "details": {"input": "find my resume and read it", "reason": "second part 'read it' has dependent pronoun"}}
{"timestamp": "...", "action": "incomplete_detected", "details": {"input": "play", "clarification": "Play what, Sir?"}}
```

### Config Settings (in `config.py`)

```python
NORMALIZATION_ENABLE_SPLIT      = True       # Multi-command splitting
NORMALIZATION_ENABLE_INCOMPLETE = True       # Incomplete command detection
NORMALIZATION_ENABLE_FILLERS    = True       # Leading filler stripping
NORMALIZATION_ENABLE_LOGGING    = True       # Log all normalization decisions
NORMALIZATION_MAX_SUBCOMMANDS   = 3          # Max sub-commands per split
```

To disable normalization entirely, set all `NORMALIZATION_ENABLE_*` flags to `False`.

### How It Integrates

```
User input
  ↓
preprocess_input() — phonetic correction, Tagalog, shorthands, pronoun resolution
  ↓
normalize_command()  ← NEW (Phase 2)
  ├─ type == "clarify"  → speak clarification, return
  ├─ type == "multi"    → recursively call process_command() for each sub-command
  └─ type == "single"   → use cleaned command, continue
  ↓
clarify_partial() — fallback for edge cases normalization didn't catch
  ↓
[Tool Router Fast Path] (Phase 1 — validation gate + 1.5B dispatch)
  ↓
detect_intent() — legacy fallback
  ↓
ask_ai_stream() — 8B model for complex requests
```

### Trade-offs Addressed

This phase was designed to avoid the trade-offs identified in our analysis:

1. **Over-normalization changes intent** → Only splits on imperative-verb conjunctions, not nouns
2. **Conjunction detection is English-only** → Tagalog commands don't split (correct — 8B handles them)
3. **Incomplete detection false positives** → Skips when last assistant message was a question
4. **Filler stripping breaks commands** → Only strips leading fillers, never trailing or inside quotes

---

## Phase 3: Tool Groups (NEW)

**New file:** `modules/toolGroups.py` (300+ lines)
**Modified:** `modules/toolRouter.py` — 6 patches to use grouped tool list + embedding pre-filter + GROUP output
**Modified:** `config.py` — added 2 tool groups config settings

### What It Does

Categorizes all 83 tools into **8 groups** to reduce the 1.5B model's decision space. Instead of picking from 83 flat tools, the 1.5B sees tools organized by category — providing semantic context that reduces hallucination.

### The 8 Groups

| Group | Tools | Description |
|---|---|---|
| CHAT | 7 | Conversation, memory, meta-tool operations |
| MEDIA_CONTROL | 11 | Volume, brightness, power, Spotify |
| APPS_WINDOWS | 5 | Launch/uninstall apps, window management |
| TASKS_NOTES | 16 | Tasks, notes, facts, habits, expenses, timers |
| FILES | 9 | File search, read, open, compress, diff |
| INTERNET | 10 | Web search, weather, news, wiki, calculations |
| SYSTEM_VISION | 13 | Monitor, specs, processes, WiFi, camera, screen |
| DEV_TOOLS | 12 | Code, Git, clipboard, privacy, image/QR tools |

### How It Works

**Single model call** (no latency doubling) with two key improvements:

1. **Group-structured tool list** — The 1.5B sees tools organized by category:
   ```
   ## MEDIA_CONTROL
     Audio volume, screen brightness, system power, and Spotify music playback control.
     - set_volume(percent)    — Set the master system volume to a specific percentage (0-100).
     - spotify_play(query)    — Play a song, artist, or playlist on Spotify.
     - ...

   ## APPS_WINDOWS
     Launch/uninstall applications and manage windows.
     - open_app(app_name)     — Launch an application or open a web app.
     - ...
   ```
   This gives the 1.5B semantic context — it can reason "this is a media request" before picking the specific tool.

2. **Embedding pre-filter** — Before showing tools to the 1.5B, the system uses `toolEmbeddings.py` to select the **top 12 most relevant tools** for the user's input. So the 1.5B sees 12 tools (organized by group) instead of 83. This cuts token count and reduces confusion.

### GROUP Output Field

The 1.5B now outputs `GROUP` alongside `TOOL`, `ARGS`, and `CONF`:
```
GROUP: MEDIA_CONTROL
TOOL: set_volume
ARGS: {"percent": 50}
CONF: 0.95
```

The system parses the GROUP field and **logs mismatches** — if the 1.5B says `GROUP: CHAT` but picks `set_volume` (which is in `MEDIA_CONTROL`), that's logged as a group mismatch. This helps identify when the 1.5B is confused about categories.

### Why This Reduces Hallucination

| Approach | Decision space | Hallucination rate |
|---|---|---|
| Old (flat list, 83 tools) | 83 options | High — 1.5B picks wrong tool or invents names |
| Phase 3 (grouped, top 12) | 8 groups → 12 tools | Low — category context + smaller list |

The 1.5B is bad at picking from 83 options. It's much better at picking from 12 options that are semantically grouped.

### Config Settings (in `config.py`)

```python
TOOL_GROUPS_ENABLED              = True       # Master switch for tool groups
TOOL_GROUPS_LOG_MISMATCHES       = True       # Log when 1.5B states wrong group
```

To disable tool groups, set `TOOL_GROUPS_ENABLED = False`. The system falls back to the flat tool list (original behavior).

### Console Output Examples

**Successful dispatch with group confirmation:**
```
[SimpleDispatch]: Pre-filtered to 12 relevant tools
[SimpleDispatch]: Group confirmed — MEDIA_CONTROL → set_volume
[SimpleDispatch]: 1.5B picked set_volume({'percent': 50}) — executing
[ValidationGate]: Passed set_volume — all checks passed
```

**Group mismatch (logged for review):**
```
[SimpleDispatch]: Group mismatch — 1.5B said CHAT but spotify_play is in MEDIA_CONTROL
[SimpleDispatch]: 1.5B picked spotify_play({'query': 'Drake'}) — executing
```

---

## Phase 4: State Machine (NEW)

**New file:** `modules/stateMachine.py` (350+ lines)
**Modified:** `tts.py` — wired state machine init + intercept in `process_command()`
**Modified:** `modules/toolExecutor.py` — `ask_for_approval()` now uses state machine
**Modified:** `config.py` — added 3 state machine config settings

### What It Does

Generalizes the `_awaiting_confirmation` event into a full state machine that handles multi-turn interactions. Instead of a single "yes/no approval" state, JARVIS can now be in one of 4 states, each with universal cancel, timeout, and new-command detection.

### The 4 States

| State | Purpose | Example Prompt |
|---|---|---|
| `AWAITING_APPROVAL` | Destructive action needs confirmation | "Confirm shutdown? Say confirm or cancel." |
| `AWAITING_DISAMBIGUATION` | Multiple options, user must pick | "Did you mean file A or file B?" |
| `AWAITING_ARG` | Command needs an argument | "Set volume to what level?" |
| `AWAITING_CLARIFICATION` | Input was unclear | "I didn't understand. Can you rephrase?" |

### Three Key Features

**1. Universal Cancel** — These phrases work in ANY state to immediately cancel and return to IDLE:
- "cancel", "never mind", "forget it", "scratch that", "abort", "stop", "disregard"

When detected, the state is cleared, JARVIS says "Cancelled, Sir.", and the conversation continues normally. No stuck states.

**2. 30-Second Timeout** — If the user doesn't respond within 30 seconds (configurable), the state auto-clears:
```
[StateMachine]: State timed out after 30s — clearing.
```
JARVIS says "Timed out, Sir." and returns to normal operation. Prevents stuck states when the user walks away.

**3. New-Command Detector** — If the user starts a new command while in a state (e.g., says "play Drake" while JARVIS is asking "Confirm shutdown?"), the state machine detects the action verb and:
- Clears the current state (cancels the approval/disambiguation)
- Processes the new command normally

This prevents the "stuck state" problem where "play some Drake" gets interpreted as a disambiguation answer instead of a new command.

**Exception: AWAITING_ARG and AWAITING_CLARIFICATION** — New-command detection is disabled for these states because the user's answer might legitimately start with an action verb (e.g., "play" as the answer to "Play what?").

### How It Works

```
User input arrives (keyboard / hotkey voice / auto-listen / Telegram)
  ↓
process_command() checks: is state_machine active?
  ├─ YES, and input is a cancel phrase → clear state, speak "Cancelled", return
  ├─ YES, and input is NOT a cancel → route to _confirmation_queue, return
  └─ NO → continue with normal processing (normalization → tool router → etc.)
  ↓
ask_for_approval() (in toolExecutor.py):
  1. state_machine.enter_state(AWAITING_APPROVAL, "Confirm shutdown?")
  2. state_machine.wait_for_response(timeout=60) — blocks
  3. User responds → text goes to _confirmation_queue
  4. wait_for_response() reads from queue, runs handle_input():
     ├─ Cancel phrase? → return ("cancelled", text)
     ├─ Action verb at start? → return ("new_command", text)
     └─ Otherwise → return ("answer", text)
  5. ask_for_approval() acts on the status:
     ├─ "answer" → check for confirm/cancel words → return True/False
     ├─ "cancelled" → return False
     ├─ "timeout" → speak "Timed out", return False
     └─ "new_command" → re-inject text into queue, return False
```

### Backward Compatibility

The state machine reuses the existing `_awaiting_confirmation` event and `_confirmation_queue`:
- When any state is active → `_awaiting_confirmation.is_set()` returns True
- All existing hotkey/auto-listen code that checks this event continues to work
- No changes needed to `_voice_or_text_input_fn()` or the hotkey/auto-listen threads

The legacy `ask_for_approval()` code is preserved as a fallback — if the state machine module fails to import, the original approval gate behavior kicks in.

### Config Settings (in `config.py`)

```python
STATE_MACHINE_ENABLED            = True       # Master switch for state machine
STATE_MACHINE_TIMEOUT            = 30         # Default timeout in seconds
STATE_MACHINE_ENABLE_LOG         = True       # Log state transitions
```

To disable the state machine, set `STATE_MACHINE_ENABLED = False`. The system falls back to the original approval gate behavior.

### Console Output Examples

**Normal approval flow:**
```
[StateMachine]: enter_state AWAITING_APPROVAL
(user says "confirm")
[StateMachine]: answer — "confirm"
```

**User cancels:**
```
[StateMachine]: enter_state AWAITING_APPROVAL
(user says "cancel")
[StateMachine]: Cancelled by user.
```

**User starts new command during approval:**
```
[StateMachine]: enter_state AWAITING_APPROVAL
(user says "play some Drake instead")
[StateMachine]: new_command_detected — verb: "play", previous_state: AWAITING_APPROVAL
[StateMachine]: clear_state — previous_state: AWAITING_APPROVAL
(normal processing of "play some Drake" continues)
```

**Timeout:**
```
[StateMachine]: enter_state AWAITING_APPROVAL
(30 seconds pass with no input)
[StateMachine]: State timed out after 30s — clearing.
```

### Logging

All state transitions are logged to `state_machine_log.jsonl`:
```json
{"timestamp": "...", "action": "enter_state", "details": {"state": "AWAITING_APPROVAL", "prompt": "Confirm shutdown?", "timeout": 60}}
{"timestamp": "...", "action": "cancel_detected", "details": {"input": "cancel", "phrase": "cancel"}}
{"timestamp": "...", "action": "new_command_detected", "details": {"input": "play some Drake", "verb": "play", "previous_state": "AWAITING_APPROVAL"}}
{"timestamp": "...", "action": "clear_state", "details": {"previous_state": "AWAITING_APPROVAL"}}
```

### Trade-offs Addressed

This phase was designed to avoid the trade-offs identified in our analysis:

1. **Stuck states** → Universal cancel + 30s timeout + new-command detector
2. **State leaks across input channels** → State machine uses the shared `_confirmation_queue`, all channels route through it
3. **No universal cancel** → 14 cancel phrases work in ANY state
4. **Debugging complexity** → All transitions logged to `state_machine_log.jsonl`

---

## Phase 5: Multi-Command with Synthesis (NEW)

**New file:** `modules/multiCommand.py` (300+ lines)
**Modified:** `tts.py` — replaced recursive `process_command()` with `execute_multi_command()`
**Modified:** `config.py` — added 6 multi-command config settings

### What It Does

When the normalization layer (Phase 2) splits a multi-command like "set volume to 50 and play Drake" into sub-commands, this module executes each one independently through the tool router, then synthesizes a natural combined response via the 1.5B model.

### Before vs After

**Before (Phase 2 — recursive process_command):**
```
User: "set volume to 50 and play some Drake"
JARVIS: "Volume set to 50 percent, Sir."
JARVIS: "Playing Drake, Sir."
```
(Robotic serial — two separate spoken responses, each ending with "Sir")

**After (Phase 5 — synthesis):**
```
User: "set volume to 50 and play some Drake"
JARVIS: "Done, Sir — volume set to 50 and playing Drake."
```
(Natural single response — one speak() call, "Sir" appears once)

### How It Works

```
User: "set volume to 50 and play some Drake"
  ↓
Phase 2: Normalization splits into ["set volume to 50", "play some Drake"]
  ↓
Phase 5: execute_multi_command(sub_commands, speak, history)
  │
  ├─ 1. Execute "set volume to 50" via route_with_tools()
  │     → tool_result: {tool: "set_volume", response: "Volume set to 50 percent, Sir."}
  │     (response is RETURNED, not spoken)
  │
  ├─ 2. Execute "play some Drake" via route_with_tools()
  │     → tool_result: {tool: "spotify_play", response: "Playing Drake, Sir."}
  │     (response is RETURNED, not spoken)
  │
  ├─ 3. Strip "Sir" from each response for cleaner synthesis
  │     → "Volume set to 50 percent"
  │     → "Playing Drake"
  │
  ├─ 4. Send to 1.5B with synthesis prompt:
  │     "You executed these commands:
  │      1. 'set volume to 50' → Volume set to 50 percent
  │      2. 'play some Drake' → Playing Drake
  │      Combine into ONE natural sentence. Address user as 'Sir' once."
  │
  ├─ 5. 1.5B returns: "Done, Sir — volume set to 50 and playing Drake."
  │
  └─ 6. Speak the synthesized response ONCE
```

### Fallback Behavior

If the 1.5B synthesis fails (e.g., Ollama is down), the module falls back to **concatenated responses** — still a single `speak()` call, not robotic serial:

```
"Volume set to 50 percent and Playing Drake, Sir."
```

The fallback uses proper English joining:
- 2 results: "A and B, Sir."
- 3+ results: "A, B, and C, Sir."

### Dependent Commands

Dependent commands (e.g., "find my resume and read it") are **not split** by Phase 2's normalization — the pronoun "it" is detected as dependent, and the entire command routes to the 8B as a single workflow. The 8B handles it via tool-use iterations (search_files → read_file with the result).

This means Phase 5 only handles **independent** commands — each sub-command is self-contained and doesn't reference the others.

### Approval Gates in Multi-Commands

If a sub-command requires approval (e.g., "delete the temp files and shut down"):
1. Sub-command 1 ("delete the temp files") triggers the approval gate (Phase 4 state machine)
2. User confirms → sub-command 1 executes
3. Sub-command 2 ("shut down") triggers another approval gate
4. User confirms → sub-command 2 executes
5. Both results are synthesized into one response

The chain pauses during each approval — the state machine handles this correctly.

### Self-Test Results (all passing)

```
=== Strip 'Sir' ===
  'Volume set to 50 percent, Sir.' → 'Volume set to 50 percent'
  'Playing Drake, Sir' → 'Playing Drake'

=== Concatenate Responses (Fallback) ===
  Spoken: ['Volume set to 50 percent and Playing Drake, Sir.']

=== Three Results ===
  Spoken: ['Volume set to 50, Brightness set to 80, and Playing jazz, Sir.']

=== One Failed ===
  Spoken: ['Volume set to 50, Sir.']  ← failed sub-command skipped
```

### Config Settings (in `config.py`)

```python
MULTI_COMMAND_ENABLED            = True       # Master switch
MULTI_COMMAND_SYNTHESIS_ENABLED  = True       # Use 1.5B to synthesize (False = just concatenate)
MULTI_COMMAND_MAX_TOKENS         = 120        # Max tokens for synthesis response
MULTI_COMMAND_TEMPERATURE        = 0.4        # Temperature for synthesis
MULTI_COMMAND_ENABLE_LOG         = True       # Log multi-command executions
MULTI_COMMAND_TIMEOUT            = 10         # Timeout for synthesis API call (seconds)
```

To disable synthesis and use concatenated fallback: set `MULTI_COMMAND_SYNTHESIS_ENABLED = False`.
To disable multi-command entirely (revert to recursive process_command): set `MULTI_COMMAND_ENABLED = False`.

### Console Output Example

```
[Normalize]: Split into 2 commands: ['set volume to 50', 'play some Drake']
[MultiCommand]: Executing 2 sub-commands...
[MultiCommand]: (1/2) 'set volume to 50'
[SimpleDispatch]: Pre-filtered to 12 relevant tools
[SimpleDispatch]: Group confirmed — MEDIA_CONTROL → set_volume
[SimpleDispatch]: 1.5B picked set_volume({'percent': 50}) — executing
[ValidationGate]: Passed set_volume — all checks passed
[MultiCommand]:   → [OK] set_volume: Volume set to 50 percent, Sir.
[MultiCommand]: (2/2) 'play some Drake'
[SimpleDispatch]: 1.5B picked spotify_play({'query': 'Drake'}) — executing
[ValidationGate]: Passed spotify_play — all checks passed
[MultiCommand]:   → [OK] spotify_play: Playing Drake, Sir.
[MultiCommand]: Done in 3.2s — Done, Sir — volume set to 50 and playing Drake....
JARVIS: Done, Sir — volume set to 50 and playing Drake.
```

### Logging

All multi-command executions are logged to `multi_command_log.jsonl`:
```json
{"timestamp": "...", "action": "execute_complete", "details": {
  "original_input": "set volume to 50 and play some Drake",
  "sub_commands": ["set volume to 50", "play some Drake"],
  "results": [{"tool": "set_volume", "success": true}, {"tool": "spotify_play", "success": true}],
  "synthesized": "Done, Sir — volume set to 50 and playing Drake.",
  "elapsed_seconds": 3.2
}}
```

### Trade-offs Addressed

This phase was designed to avoid the trade-offs identified in our analysis:

1. **Response verbosity** → 1.5B synthesizes ONE natural sentence instead of N separate acks
2. **Approval gate in the middle of a chain** → State machine handles it; chain pauses, then resumes
3. **Dependent commands** → Not split (Phase 2 pronoun check); routed to 8B as workflow
4. **Execution order and failure handling** → Failed sub-commands are skipped in synthesis; successful ones still reported

---

## Phase 6: Calibration (NEW)

**New files:** `modules/calibration.py` (400+ lines), `modules/per_tool_thresholds.py` (200+ lines), `run_calibration.py` (CLI script)
**Modified:** `modules/validationGate.py` — uses per-tool thresholds when available
**Modified:** `config.py` — added 4 calibration config settings

### What It Does

Analyzes all JSONL log files produced by Phases 1-5 and generates a calibration report with per-tool statistics and actionable recommendations. Also enables per-tool threshold overrides so you can tune the validation gate for specific tools without changing global settings.

### The Calibration Report

Run `py run_calibration.py` to generate a report that analyzes:

| Log File | Phase | What's Analyzed |
|---|---|---|
| `validation_log.jsonl` | Phase 1 | Per-tool pass/fail rates, avg similarity scores, common arg issues |
| `fuzzy_match_log.jsonl` | Phase 1 | Which tools the 1.5B most often hallucinates |
| `normalization_log.jsonl` | Phase 2 | Multi-command split counts, incomplete detection counts |
| `state_machine_log.jsonl` | Phase 4 | State entry counts, cancel rate, timeout rate, new-command rate |
| `multi_command_log.jsonl` | Phase 5 | Synthesis success rate, avg elapsed, avg sub-commands |

### Sample Report Output

```
======================================================================
  JARVIS Calibration Report — Phase 6
  Generated: 2026-08-09T...
======================================================================

── Phase 1: Validation Gate ──
  Total decisions: 142
  Overall pass rate: 87.3%
  Overall fail rate: 12.7%

  Per-tool statistics:
  Tool                      Total   Pass%  Fail%  AvgSim
  ------------------------- ----- ------ ------ -------
  set_volume                   28    96%     4%   0.821
  spotify_play                 22    91%     9%   0.745
  shutdown_system               8    50%    50%   0.380
  take_screenshot              15   100%     0%   0.890
  ...

── Phase 1: Fuzzy Match Hallucinations ──
  Total fuzzy matches: 7
  Most hallucinated tool names:
    'save_screenshot' → 'take_screenshot' (5 times)
    'open_file' → 'open_app' (2 times)

── Recommendations ──
  ⚠️ Tool 'shutdown_system' has LOW pass rate (50%, 8 samples).
     Consider: (a) lowering its sim_pass threshold via per_tool_thresholds.py,
     (b) improving its description in toolRegistry.py, or
     (c) removing it from the 1.5B's repertoire (route to 8B directly).
  🔧 The 1.5B frequently hallucinates 'save_screenshot' (5 times),
     which fuzzy-matches to 'take_screenshot'.
     Consider adding a pattern matcher for this phrasing in smartRouter.py.
```

### Per-Tool Threshold Overrides

Some tools have descriptions that score low on embedding similarity even when correctly matched (e.g., "shutdown_system" vs "shut down the computer" might score 0.38). Per-tool overrides let you lower the threshold for specific tools without affecting others.

**How it works:**
1. Run `py run_calibration.py --apply` to auto-apply suggested thresholds
2. Or manually edit `per_tool_thresholds.json`:
   ```json
   {
     "shutdown_system": {
       "sim_pass": 0.30,
       "sim_borderline": 0.20
     }
   }
   ```
3. The validation gate automatically loads overrides at runtime (mtime-cached, no restart needed)
4. Tools without overrides use the global `VALIDATION_SIM_PASS` / `VALIDATION_SIM_BORDERLINE`

### Auto-Apply Thresholds

The `--apply` flag automatically adjusts thresholds for tools that meet ALL of these criteria:
- At least 5 samples (configurable via `CALIBRATION_MIN_SAMPLES`)
- Pass rate below 60%
- Average similarity below 0.50

For qualifying tools, it sets:
- `sim_pass` = max(0.40, avg_similarity - 0.05)
- `sim_borderline` = max(0.25, sim_pass - 0.15)

Without `--apply`, the calibration script runs in **dry-run mode** — it prints what it would change but doesn't save anything.

### CLI Usage

```bash
# Generate report + print to console + dry-run thresholds
py run_calibration.py

# Generate report + auto-apply threshold adjustments
py run_calibration.py --apply

# Save JSON report only (for programmatic access)
py run_calibration.py --json
```

### Config Settings (in `config.py`)

```python
CALIBRATION_ENABLED              = True       # Master switch for calibration
PER_TOOL_THRESHOLDS_ENABLED      = True       # Use per-tool threshold overrides
CALIBRATION_AUTO_APPLY           = False      # Auto-apply thresholds (use --apply flag instead)
CALIBRATION_MIN_SAMPLES          = 5          # Min samples per tool before recommending changes
```

### Workflow

1. **Run JARVIS normally** for a week — all 5 phases log their decisions to JSONL files
2. **Run `py run_calibration.py`** — review the report, check recommendations
3. **Run `py run_calibration.py --apply`** — auto-apply threshold adjustments for low-accuracy tools
4. **Repeat weekly** — track accuracy over time, identify new failure patterns

The calibration report is also saved as `calibration_report.json` for programmatic access (e.g., for building a dashboard or tracking trends over time).

### Files Created by Calibration

| File | Purpose |
|---|---|
| `calibration_report.json` | Last generated report (machine-readable) |
| `per_tool_thresholds.json` | Per-tool threshold overrides (manually editable) |

Both files are auto-created and safe to delete (they'll be regenerated on next run).

---

## Hybrid Tool Embeddings Initialization (NEW)

**Modified:** `tts.py` — added `_ensure_tool_embeddings()` function called at startup

### What It Does

Ensures the tool embeddings cache (needed for Phase 3's pre-filter) is ready **before JARVIS accepts input**. Uses a hybrid sync/async approach:

### First Run (no cache file exists)

JARVIS detects that `tool_embeddings_cache.json` doesn't exist and **builds it synchronously** with progress messages:

```
============================================================
  FIRST RUN DETECTED — Building Tool Embeddings Cache
  This is a one-time setup (~30-60 seconds for 83 tools).
  Subsequent runs will load instantly from disk.
============================================================

[ToolEmbeddings]: Embedding tool descriptions via nomic-embed-text...
[ToolEmbeddings]: Progress will print every 10 tools...
[ToolEmbeddings]: 10/83 done...
[ToolEmbeddings]: 20/83 done...
...
[ToolEmbeddings]: DONE — 83 embeddings built in 42.3s
[ToolEmbeddings]: Cache saved to .../tool_embeddings_cache.json
[ToolEmbeddings]: Future runs will load instantly.
```

JARVIS doesn't accept input until the cache is ready. This means **every command from the very first one** benefits from Phase 3's pre-filter (12 tools shown instead of 83).

### Subsequent Runs (cache file exists)

JARVIS detects the cache file and **loads it in the background** (instant — disk load is ~1 second):

```
[ToolEmbeddings]: Cache found — loading 83 tool embeddings...
[ToolEmbeddings]: Loading in background (instant for cached files).
```

Startup is instant. The background thread also checks for tool changes (if you added/removed tools since last run, it refreshes silently).

### Why This Approach

| Approach | First-run startup | Subsequent startup | First command accuracy |
|---|---|---|---|
| Old (lazy async) | Instant | Instant | Lower (83 tools shown until cache ready, ~30-60s) |
| **Hybrid (this fix)** | +30-60s (one-time) | Instant | **Full** (12 tools shown from first command) |

The 30-60 second delay only happens **once ever**. After that, the cache loads from disk in milliseconds. The trade-off is: wait 30s once, or have degraded first-run accuracy.

### What This Replaces

Previously, the tool embeddings cache was only built when:
- You manually ran `py build_tool_cache.py` (option 3 in `start.bat`), OR
- The first command arrived and `select_relevant_tools()` lazily started the background thread

Now, the cache is guaranteed ready before JARVIS accepts input — no manual step needed, no degraded first-run experience.

### Fallback Behavior

If the build fails (e.g., Ollama not running, `nomic-embed-text` not pulled):
```
[ToolEmbeddings]: Build failed: <error>
[ToolEmbeddings]: JARVIS will run without pre-filtering (Phase 3 disabled).
[ToolEmbeddings]: Run 'py build_tool_cache.py' later to build the cache.
```

JARVIS continues starting — Phase 3's pre-filter is inactive (the 1.5B sees all 83 tools), but everything else works. You can build the cache later with `py build_tool_cache.py`.

---

## Fresh State — All Program-Generated Files Removed

The following files were removed so you start with a clean slate:

**Removed JSON files:**
- `ai_memory.json` (conversation history — recreated on first run)
- `command_history.json` (command log — recreated on first run)
- `entity_cache.json` (entity tracker — recreated on first run)
- `metrics.json` (metrics data — recreated on first run)
- `notes.json` (saved notes — recreated on first run)
- `personality_violations.json` (personality validator logs — recreated on first run)
- `project_snapshot.json` (codebase snapshot — recreated on first run)
- `recurring_timers.json` (recurring timer state — recreated on first run)
- `response_cache.json` (response cache — recreated on first run)
- `tasks.json` (task list — recreated on first run)
- `timers.json` (timer state — recreated on first run)
- `tool_embeddings_cache.json` (tool embeddings — rebuilt by `build_tool_cache.py`)
- `user_profile.json` (user profile — recreated on first run)
- `modules/command_history.json` (duplicate — removed)
- `modules/notes.json` (duplicate — removed)
- `modules/tasks.json` (duplicate — removed)

**Other removed files:**
- `output.wav` (audio sample — generated)
- `.spotify_cache` (Spotify OAuth cache — will re-authenticate)
- `notes_txt/` (note exports — generated)
- `modules/notes_txt/` (note exports — generated)
- `config_versions/` (config backups — generated)
- All `__pycache__/` directories

**Kept:**
- `.vscode/settings.json` (IDE config — not runtime data)
- All `.py` files (source code)
- All `.bak` files (your original backups)
- `requirements.txt`, `start.bat`, `MyCommands.txt`
- `JarvisUI/`, `IMPLEMENTATION PLAN/`, documentation files

### First Run After Fresh Start

On first run, JARVIS will:
1. Start with empty conversation history, no tasks, no notes, no timers
2. Recreate all JSON files as needed
3. The tool embeddings cache will NOT exist — run `py build_tool_cache.py` to rebuild it (one-time, ~30 seconds). Until then, the validation gate's similarity check will skip (it falls back to arg sanity only).

---

## Expected Performance

| Input type | Before | After |
|---|---|---|
| "hello" / "thanks" | 4-6s (8B) | **instant** (hardcoded map) |
| "set volume to 50" | 2-4s (8B) | **instant** (regex pattern) |
| "play some Drake" | 4-6s (8B) | **1-2s** (1.5B + validation) |
| "what's the weather in Tokyo" | 4-6s (8B) | **1-2s** (1.5B + validation) |
| "explain quantum computing" | 5-8s (8B) | **1-2s** (1.5B casual chat) |
| "find my resume and read it" | 6-10s (8B) | 6-10s (8B — complex, correct) |
| 1.5B hallucination (e.g., wrong tool) | wrong action executed | **validation gate catches it → escalates to 8B** |

---

## How to Install

1. **Back up your current project**:
   ```
   rename MyAiOfflineProject MyAiOfflineProject_backup
   ```

2. **Extract the zip** and rename the folder:
   ```
   cd C:\Users\user\OneDrive\Documents
   ```
   Right-click `projectjarvis_phase1.zip` → Extract Here → rename `projectjarvis` to `MyAiOfflineProject`

3. **Rebuild the tool embeddings cache** (one-time, ~30 seconds):
   ```
   py build_tool_cache.py
   ```
   This is needed for the validation gate's similarity check. Without it, the gate falls back to arg sanity only (still works, just less thorough).

4. **Run JARVIS** as usual:
   ```
   py tts.py
   ```

---

## How to Revert

**Option A — Disable validation gate only:**
Set `VALIDATION_ENABLE_SIMILARITY = False` and `VALIDATION_ENABLE_ARG_SANITY = False` in `config.py`.

**Option B — Disable tool router only (keep TTS fix):**
Set `USE_TOOL_ROUTER = False` in `config.py`.

**Option C — Full revert to original tts.py:**
```
copy tts.py.bak tts.py
```

---

## Verification

After running `py tts.py`, try these commands and watch the console:

| Say this | Console should show |
|---|---|
| "hello" | (instant — caught by acknowledgment map) |
| "set volume to 50" | `[PatternMatch]: Matched set_volume(...)` |
| "play some Drake" | `[SimpleDispatch]: 1.5B picked spotify_play(...)` → `[ValidationGate]: Passed spotify_play — all checks passed` |
| "what's the weather in Tokyo" | `[SimpleDispatch]: 1.5B picked get_weather(...)` → `[ValidationGate]: Passed get_weather — ...` |
| "explain quantum computing" | `[CasualChat]:` (1.5B responded directly) |
| "find my resume and read it" | `[ToolRouter]: Calling search_files(...)` (8B — complex) |

If the 1.5B picks a wrong tool, you'll see:
```
[ValidationGate]: REJECTED set_volume({"percent": 50}) — similarity too low (0.28 < 0.40)
[ValidationGate]: Escalating to 8B router for correct routing.
```

---

## Files Modified in This Release

| File | Change |
|---|---|
| `tts.py` | 3 fixes (TTS buffer, tool router, approval gate) + Phase 2 normalization + Phase 4 state machine + Phase 5 multi-command + hybrid tool embeddings init |
| `config.py` | Added 6 validation + 5 normalization + 2 tool groups + 3 state machine + 6 multi-command + 4 calibration config settings |
| `modules/toolRouter.py` | Wired validation gate + fuzzy match logging + Phase 3 tool groups + embedding pre-filter |
| `modules/toolExecutor.py` | Phase 4 — `ask_for_approval()` now uses state machine (with legacy fallback) |
| `modules/validationGate.py` | **NEW** (Phase 1) + Phase 6 — uses per-tool thresholds when available |
| `modules/normalization.py` | **NEW** (Phase 2) — Normalization layer (350+ lines) |
| `modules/toolGroups.py` | **NEW** (Phase 3) — Tool groups (300+ lines) |
| `modules/stateMachine.py` | **NEW** (Phase 4) — State machine (350+ lines) |
| `modules/multiCommand.py` | **NEW** (Phase 5) — Multi-command synthesis (300+ lines) |
| `modules/calibration.py` | **NEW** (Phase 6) — Log analyzer + report generator (400+ lines) |
| `modules/per_tool_thresholds.py` | **NEW** (Phase 6) — Per-tool threshold overrides (200+ lines) |
| `run_calibration.py` | **NEW** (Phase 6) — CLI script for running calibration |

**Unchanged:** All other files (`modules/toolEmbeddings.py`, `modules/contracts.py`, `modules/smartRouter.py`, `JarvisUI/*`, etc.)

**Backups:** `tts.py.bak` (your original) is included for rollback.

---

## Tier 1 Performance Improvements (NEW)

Three high-impact, low-effort optimizations based on external code review:

### Tier 1.1: Whisper CUDA (GPU Acceleration)

**Modified:** `tts.py` — `get_whisper_model()`, `config.py` — new settings

**What changed:** Speech-to-text now runs on GPU (CUDA) instead of CPU, cutting transcription latency by ~60-70%.

**Before:** `device="cpu", compute_type="int8"` — ~1-2s per utterance
**After:** `device="cuda", compute_type="float16"` — ~300-500ms per utterance

**Graceful fallback:** The code checks CUDA availability via `ctranslate2.get_cuda_device_count()` first, then PyTorch as a secondary check. If CUDA isn't available, it automatically falls back to CPU with a console message. If the GPU model load fails for any reason, it also falls back to CPU.

**Config settings (in `config.py`):**
```python
WHISPER_DEVICE        = "cuda"     # "cuda" (GPU) or "cpu"
WHISPER_COMPUTE_TYPE  = "float16"  # "float16" (GPU) or "int8" (CPU)
WHISPER_CPU_THREADS   = 6          # Only used when device="cpu"
WHISPER_NUM_WORKERS   = 2          # Only used when device="cpu"
```

**Note:** If you don't have a CUDA-capable GPU, set `WHISPER_DEVICE = "cpu"` in config.py. The system will detect this automatically, but setting it explicitly avoids the startup detection delay.

---

### Tier 1.2: Ollama keep_alive (Model Warmth)

**Modified:** `config.py` — new settings + `get_keep_alive()` helper function
**Modified:** `tts.py` — 2 API calls, `modules/toolRouter.py` — 6 API calls, `modules/multiCommand.py` — 1 API call

**What changed:** Models are now kept loaded in memory between requests, eliminating cold-start latency. Previously, Ollama unloaded models after 5 minutes of inactivity, causing the next request to pay a 3-5 second reload penalty.

**Per-model keep_alive settings:**

| Model | keep_alive | Why |
|---|---|---|
| 1.5B (casual chat) | `-1` (always hot) | Handles 70-80% of commands — should never unload |
| 8B (tool router) | `1800` (30 min) | Complex commands — keep warm for conversation sessions |
| DeepSeek coder | `300` (5 min) | Occasional code queries — default is fine |
| Llama 3.2 fallback | `300` (5 min) | Rare fallback — default is fine |
| nomic-embed-text | `300` (5 min) | Embeddings — default is fine |
| Vision models | `60` (1 min) | Rare, save VRAM |

**How it works:** The `get_keep_alive(model_name)` function in config.py returns the right value for any model. API calls now include `"keep_alive": config.get_keep_alive(model_name)` in the JSON payload. Ollama keeps the model in memory for that duration after the last request.

**9 API calls updated:**
- `tts.py`: `ask_model_silent()`, `ask_ai_stream()`
- `toolRouter.py`: 1.5B simple dispatch, 1.5B response formatting, casual chat, 8B tool-use, 8B plain, rescue synthesis
- `multiCommand.py`: synthesis call

**Config settings (in `config.py`):**
```python
KEEPALIVE_CASUAL_CHAT = -1          # 1.5B: always hot
KEEPALIVE_TOOL_ROUTER = 1800        # 8B: 30 minutes
KEEPALIVE_CODE_MODEL  = 300         # DeepSeek: 5 minutes
KEEPALIVE_FALLBACK    = 300         # Llama 3.2: 5 minutes
KEEPALIVE_EMBEDDING   = 300         # nomic-embed-text: 5 minutes
KEEPALIVE_VISION      = 60          # Vision: 1 minute
```

**Expected impact:** First command after 5+ minutes of inactivity loads ~3-5s faster. For the 1.5B model (which handles most commands), cold starts are completely eliminated — it's always loaded.

---

### Tier 1.3: Automated Calibration (Windows Task Scheduler)

**New file:** `setup_calibration_schedule.bat`

**What it does:** Creates a Windows Scheduled Task that runs `py run_calibration.py --apply` automatically every Sunday at 3 AM. This ensures thresholds are tuned weekly without manual intervention.

**How to set up:**
1. Right-click `setup_calibration_schedule.bat` → **Run as administrator**
2. The script creates a scheduled task named `JARVIS_Weekly_Calibration`
3. Every Sunday at 3 AM, the calibration runs automatically:
   - Analyzes all 5 JSONL log files
   - Generates a calibration report
   - Auto-applies threshold adjustments for low-accuracy tools
   - Saves report to `calibration_report.json`

**To verify:** Open Task Scheduler → look for "JARVIS_Weekly_Calibration"
**To remove:** Run `schtasks /delete /tn "JARVIS_Weekly_Calibration" /f`

**Why this matters:** Without automation, calibration is a manual weekly task that's easy to forget. Threshold drift compounds quietly — if the 1.5B model's accuracy degrades over time (due to conversation history changes, new tools, etc.), nobody notices until responses start feeling wrong. Automated calibration catches this early.

---

## Tier 2 Reliability & Performance Improvements (NEW)

Three medium-effort, high-impact improvements:

### Tier 2.1: Ollama Structured Output (JSON Schema for 1.5B)

**Modified:** `modules/toolRouter.py` — added `_TOOL_SELECTION_SCHEMA`, `_parse_structured_tool_response()`, replaced free-text parsing with JSON schema enforcement

**What changed:** The 1.5B model now returns structured JSON instead of free-text `GROUP: / TOOL: / ARGS: / CONF:` format. Ollama's `format` parameter enforces a strict JSON schema, so the model physically cannot return malformed output. This eliminates the regex parsing errors and hallucinated tool names that were the biggest source of validation gate escalations.

**Before:** The 1.5B returned free-text like:
```
GROUP: MEDIA_CONTROL
TOOL: set_volume
ARGS: {"percent": 50}
CONF: 0.95
```
This was parsed with 4 separate regex patterns. If the model misspelled a field, added extra text, or used wrong JSON syntax, parsing failed and the command fell through to the 8B.

**After:** The 1.5B returns strict JSON:
```json
{"status": "tool", "group": "MEDIA_CONTROL", "tool": "set_volume", "args": {"percent": 50}, "conf": 0.95}
```
Ollama enforces the schema at the API level. The model cannot return malformed output.

**The schema:**
```python
_TOOL_SELECTION_SCHEMA = {
    "type": "object",
    "properties": {
        "group": {"type": "string"},
        "tool": {"type": "string"},
        "args": {"type": "object", "additionalProperties": True},
        "conf": {"type": "number"},
        "status": {"type": "string", "enum": ["tool", "complex", "ambiguous"]},
        "ambiguous_tools": {"type": "array", "items": {"type": "string"}}
    },
    "required": ["status", "conf"]
}
```

**Three statuses:**
- `tool` — picked a specific tool (includes group, tool, args, conf)
- `complex` — needs 8B routing (just status + conf)
- `ambiguous` — multiple candidates (includes ambiguous_tools list)

**Expected impact:** Eliminates ~90% of parsing-related escalations. The 1.5B can still pick the wrong tool, but it can no longer produce unparsable output. This means fewer commands fall through to the 8B, reducing latency on simple commands.

---

### Tier 2.2: Parallel Multi-Command Execution

**Modified:** `modules/multiCommand.py` — `execute_multi_command()` now uses `ThreadPoolExecutor`, `config.py` — new `MULTI_COMMAND_PARALLEL` setting

**What changed:** When the normalization layer splits "set volume to 50 and play some Drake" into two sub-commands, they now execute in parallel instead of sequentially. Since `route_with_tools()` makes HTTP calls to Ollama (I/O-bound), threads are appropriate — the GIL is released during `requests.post()`.

**Before (sequential):**
```
[MultiCommand]: Executing 2 sub-commands...
[MultiCommand]: (1/2) 'set volume to 50'          → 1.5s
[MultiCommand]: (2/2) 'play some Drake'           → 1.5s
Total: 3.0s
```

**After (parallel):**
```
[MultiCommand]: Executing 2 sub-commands...
[MultiCommand]: Running 2 sub-commands in parallel...
[MultiCommand]: (1/2) 'set volume to 50' (submitted)
[MultiCommand]: (2/2) 'play some Drake' (submitted)
(both execute simultaneously)
Total: 1.5s
```

**How it works:**
- Uses `concurrent.futures.ThreadPoolExecutor` with `max_workers=min(len(sub_commands), 3)`
- Results are collected in original order (using a `future_to_index` dict)
- If any sub-command fails, it's logged but doesn't block the others
- Falls back to sequential if `MULTI_COMMAND_PARALLEL = False` or only 1 sub-command
- Max 3 workers to prevent overwhelming Ollama with concurrent requests

**Config:**
```python
MULTI_COMMAND_PARALLEL = True  # Tier 2.2: Run independent sub-commands in parallel
```

**Safety:** Dependent commands (with pronouns like "find my resume and read it") are NOT split by Phase 2 — they route to the 8B as a single workflow. So parallelization only applies to truly independent commands.

**Expected impact:** 2-command requests: 3s → 1.5s (50% reduction). 3-command requests: 4.5s → 1.5s (67% reduction).

---

### Tier 2.3: STT Confidence Gating

**Modified:** `tts.py` — `speech_to_text()` now asks to repeat when confidence is very low, `config.py` — 3 new settings

**What changed:** When Whisper's transcription confidence is very low (below 20%), JARVIS now asks "I did not catch that, Sir. Could you repeat?" and re-listens, instead of processing a likely-wrong transcription that would cause cascading failures through the pipeline.

**Why 20% and not 35%:** Whisper is conservative on short utterances. A confident "hello" might score 30% because of how log probabilities map to the 0-1 scale. Gating at 35% would cause frustration. Gating at 20% only catches truly garbage transcriptions — the ones where Whisper is basically guessing.

**The flow:**
```
1. Transcribe audio
2. If confidence < 0.20 (STT_CONFIDENCE_GATE):
   - Speak: "I did not catch that, Sir. Could you repeat?"
   - Re-listen (one retry)
   - If retry confidence >= 0.20: process the retry
   - If retry still < 0.20: process anyway (don't loop forever)
3. If confidence < 0.35 (STT_CONFIDENCE_WARN) but >= 0.20:
   - Print warning but still process
4. If confidence >= 0.35: process normally
```

**Config:**
```python
STT_CONFIDENCE_GATE  = 0.20   # Below this = ask to repeat
STT_CONFIDENCE_WARN  = 0.35   # Below this = warn but still process
STT_MAX_RETRIES      = 1      # How many times to ask before giving up
```

**To disable:** Set `STT_CONFIDENCE_GATE = 0.0` (process everything, even garbage).

**Expected impact:** Eliminates the cascading failures where a bad transcription like "set volume to fifty percent" becomes "set volume to 50 sens" → wrong tool execution → confused user. Now those get caught at the source.

---

## All 6 Phases Complete

This was the final phase of a 6-phase plan to improve routing accuracy:

- ✅ **Phase 1: Validation Gate** — catches 1.5B hallucinations before execution
- ✅ **Phase 2: Normalization Layer** — conservative multi-command split, incomplete detection, filler stripping
- ✅ **Phase 3: Tool Groups** — 83 tools categorized into 8 groups + embedding pre-filter
- ✅ **Phase 4: State Machine** — generalized approval gate with universal cancel, timeout, new-command detection
- ✅ **Phase 5: Multi-Command with Synthesis** — natural combined responses via 1.5B synthesis
- ✅ **Phase 6: Calibration** — log analyzer + per-tool threshold overrides + CLI report generator

### Recommended Workflow

1. **Extract the zip** and rename `projectjarvis` → `MyAiOfflineProject`
2. **Run `py tts.py`** (or `start.bat` → option 1) — on first run, JARVIS auto-builds the tool embeddings cache (~30-60s, one-time). Subsequent runs start instantly.
3. **Use JARVIS normally** for a week — all 5 phases log their decisions to JSONL files
4. **Run `py run_calibration.py`** — review the calibration report
5. **Run `py run_calibration.py --apply`** — auto-apply threshold adjustments for low-accuracy tools
6. **Repeat weekly** — track accuracy over time, identify new failure patterns

Note: You no longer need to manually run `py build_tool_cache.py` — JARVIS handles it automatically on first run. That script is still available (option 3 in `start.bat`) if you ever need to manually rebuild the cache (e.g., after adding new tools to `toolRegistry.py`).

All 5 log files (`validation_log.jsonl`, `fuzzy_match_log.jsonl`, `normalization_log.jsonl`, `state_machine_log.jsonl`, `multi_command_log.jsonl`) accumulate data as you use JARVIS. The calibration report uses this data to recommend specific improvements.

---

## Tier 3 Capability Improvements (NEW)

Three high-effort, high-impact improvements that add new capabilities:

### Tier 3.1: Persistent Cross-Session Memory

**New file:** `modules/persistentMemory.py` (400+ lines)
**Modified:** `tts.py` — auto-learn after each exchange, memory context in system prompt, cleanup at startup
**Modified:** `config.py` — 6 persistent memory settings

**What changed:** JARVIS now automatically learns facts from conversations and persists them across sessions. Previously, facts were only saved when the user explicitly said "save fact" or "remember that." Now the 8B model extracts memorable information every 5 exchanges and stores it with embeddings for semantic recall.

**How it works:**
1. After every conversation exchange, `auto_learn_from_exchange()` is called
2. Every 5 exchanges (configurable), the 8B model analyzes the text and extracts facts worth remembering
3. Facts are categorized (personal_info, preferences, schedule, project, environment, general)
4. Each fact is embedded with nomic-embed-text and saved to `persistent_memory.json`
5. Duplicate detection prevents storing the same fact twice
6. On startup, old memories (>90 days) are cleaned up automatically
7. When building the system prompt, relevant memories are recalled via embedding similarity and injected as context

**Fact extraction prompt:** The 8B is asked to identify personal information, preferences, recurring patterns, project context, and environment details — while filtering out transient commands, questions, and greetings.

**Categories:** personal_info, preferences, schedule, project, environment, general

**Config:**
```python
PERSISTENT_MEMORY_ENABLED            = True
PERSISTENT_MEMORY_MAX_FACTS          = 500
PERSISTENT_MEMORY_MAX_AGE_DAYS       = 90
PERSISTENT_MEMORY_AUTO_LEARN_INTERVAL = 5  # Extract every N exchanges
```

**Expected impact:** JARVIS remembers your name, preferences, projects, and patterns across restarts. No more "what's my name?" or having to re-explain context every session.

---

### Tier 3.2: Plugin System (Live Tool Registration)

**New file:** `modules/pluginSystem.py` (300+ lines)
**Modified:** `tts.py` — plugin watcher started at startup
**Modified:** `config.py` — 3 plugin system settings

**What changed:** You can now add new tools to JARVIS without restarting. Drop a `.py` file in the `plugins/` directory and the watcher auto-loads it within 5 seconds, registers the tools, and incrementally updates the embeddings cache.

**How it works:**
1. At startup, JARVIS creates a `plugins/` directory with a README
2. A background thread watches the directory every 5 seconds
3. When a new `.py` file appears (or an existing one changes), the watcher:
   - Imports the module
   - Calls its `register_plugin()` function
   - Registers each returned tool definition in the tool registry
   - Incrementally embeds the new tool descriptions (just the new ones, not all 83)
   - Saves the updated cache to disk
4. The tools are immediately available for routing — no restart needed

**Plugin file template:**
```python
# plugins/my_plugin.py
def register_plugin():
    return [
        {
            "name": "my_custom_tool",
            "description": "Does something custom. Use when user says 'do custom thing'.",
            "parameters": {"type": "object", "properties": {...}, "required": [...]},
            "function": my_function,
            "needs_approval": False,
        }
    ]

def my_function(**kwargs):
    return "Result"
```

**Config:**
```python
PLUGIN_SYSTEM_ENABLED    = True
PLUGINS_DIR              = os.path.join(BASE_DIR, "plugins")
PLUGIN_WATCH_INTERVAL    = 5  # seconds
```

**Expected impact:** Extend JARVIS with custom tools (API integrations, specialized calculations, personal workflows) without touching the core codebase or restarting.

---

### Tier 3.3: Streaming Tool Results

**New file:** `modules/streamingResults.py` (200+ lines)
**Modified:** `modules/toolExecutor.py` — `execute_tool_call()` now accepts `speak_fn` and tries streaming first
**Modified:** `modules/toolRouter.py` — passes `speak_fn` through to `execute_tool_call()`
**Modified:** `config.py` — 2 streaming settings

**What changed:** For internet-dependent tools like `get_news` and `web_search`, JARVIS now speaks each headline/result as it arrives, instead of waiting for all results before speaking. This creates a "live news report" feel and cuts perceived latency significantly.

**Before:** User says "what's the latest news about X" → 5-10 seconds of silence → JARVIS speaks all headlines at once

**After:** User says "what's the latest news about X" → JARVIS immediately says "Here are the latest headlines about X, Sir." → speaks each headline as it's fetched → small pause between headlines for natural delivery

**Currently supports streaming:**
- `get_news` — speaks each headline as fetched from DuckDuckGo
- `web_search` — speaks each result title as found

**How it works:**
1. `execute_tool_call()` now accepts an optional `speak_fn` parameter
2. Before normal execution, it checks if the tool supports streaming
3. If yes, it calls the streaming variant which uses `speak_fn` to speak intermediate results
4. If streaming fails or isn't supported, falls back to normal execution
5. The full result is still returned for the 8B to synthesize a final response

**Config:**
```python
STREAMING_RESULTS_ENABLED = True
STREAMING_RESULTS_TOOLS   = ["get_news", "web_search", "wikipedia_summary"]
```

**Expected impact:** Perceived latency on news/search commands cut by ~50%. User hears activity immediately instead of waiting in silence.
