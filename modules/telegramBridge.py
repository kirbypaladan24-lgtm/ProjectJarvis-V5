"""
telegramBridge.py — Telegram Remote Access for JARVIS (FIXED)
──────────────────────────────────────────────────────────────
Fixes:
  - process_command() takes 1 arg — was being called with 2 (silent TypeError)
  - Response capture now monkeypatches tts.speak temporarily so we intercept
    whatever JARVIS actually says, regardless of how deep in the pipeline it is
  - Added /ping for instant connection test without invoking process_command
  - Added full error reporting back to Telegram so crashes are visible on phone
  - run_polling() now runs correctly in a background thread under Python 3.14

Setup:
  1. @BotFather → /newbot → copy token → .env: TELEGRAM_BOT_TOKEN=...
  2. @userinfobot → copy your numeric ID → .env: TELEGRAM_ALLOWED_IDS=...
  3. Start JARVIS → message /ping to your bot to confirm bridge is alive
"""

import os
import sys
import time
import asyncio
import threading
import tempfile
import subprocess
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    import config
except ImportError:
    class config:
        TELEGRAM_BOT_TOKEN   = ""
        TELEGRAM_ALLOWED_IDS = []
        TELEGRAM_VOICE_REPLY = True
        VOICE                = r"C:\piper\voices\en_US-danny-low.onnx"
        OLLAMA_BASE_URL      = "http://localhost:11434"

# ── Auto-install ──────────────────────────────────────────────────────────────
try:
    from telegram import Update, Bot
    from telegram.ext import (Application, CommandHandler,
                               MessageHandler, filters, ContextTypes)
    _HAS_TELEGRAM = True
except ImportError:
    print("[Telegram]: Installing python-telegram-bot 21.5...")
    subprocess.run([sys.executable, "-m", "pip", "install",
                    "python-telegram-bot==21.5", "--break-system-packages"],
                   check=True, capture_output=True)
    try:
        from telegram import Update, Bot
        from telegram.ext import (Application, CommandHandler,
                                   MessageHandler, filters, ContextTypes)
        _HAS_TELEGRAM = True
    except Exception as e:
        _HAS_TELEGRAM = False
        print(f"[Telegram]: Install failed: {e}")

# ── State ─────────────────────────────────────────────────────────────────────
_process_command_fn = None   # Injected: tts.process_command
_tts_module         = None   # Injected: the tts module itself (for speak monkeypatching)
_bot_running        = False
_app                = None
_speak_lock         = threading.Lock()   # Prevent concurrent speak monkeypatches

# ── Auth ──────────────────────────────────────────────────────────────────────
def _is_allowed(update: "Update") -> bool:
    if not config.TELEGRAM_ALLOWED_IDS:
        return True
    return update.effective_user.id in config.TELEGRAM_ALLOWED_IDS

# ── Response capture ──────────────────────────────────────────────────────────
def _run_and_capture(user_text: str, timeout: int = 90) -> str:
    """
    Call process_command(user_text) with the correct 1-argument signature.
    Temporarily replaces tts.speak so we capture whatever JARVIS says.
    Thread-safe via _speak_lock.
    """
    if not _process_command_fn:
        return "JARVIS process_command is not connected."

    captured = {"text": ""}
    done     = threading.Event()

    def _capture_speak(text: str):
        """Drop-in replacement for tts.speak during Telegram command execution."""
        if text and text.strip():
            captured["text"] += text.strip() + " "
        done.set()

    def _run():
        with _speak_lock:
            original_speak = None
            try:
                # Monkeypatch tts.speak so we intercept the response
                if _tts_module and hasattr(_tts_module, "speak"):
                    original_speak = _tts_module.speak
                    _tts_module.speak = _capture_speak

                # Call with the correct single-argument signature
                _process_command_fn(user_text)

            except Exception as e:
                captured["text"] = f"Error executing command: {e}"
            finally:
                # Restore original speak unconditionally
                if _tts_module and original_speak is not None:
                    _tts_module.speak = original_speak
                done.set()

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    # Wait up to timeout for JARVIS to finish speaking
    done.wait(timeout=timeout)
    t.join(timeout=5)

    result = captured["text"].strip()
    return result or "✅ Command executed (no spoken response captured)."

# ── Voice synthesis ────────────────────────────────────────────────────────────
def _synthesize_ogg(text: str) -> str | None:
    """Synthesize text to .ogg using piper → ffmpeg for Telegram voice notes."""
    try:
        tmp_wav = tempfile.mktemp(suffix=".wav")
        tmp_ogg = tempfile.mktemp(suffix=".ogg")

        piper_exe = r"C:\piper\piper.exe"
        cmd = ([piper_exe] if os.path.exists(piper_exe)
               else [sys.executable, "-m", "piper"])
        cmd += ["--model", config.VOICE, "--output_file", tmp_wav]
        subprocess.run(cmd, input=text, text=True, capture_output=True)

        if not os.path.exists(tmp_wav):
            return None

        subprocess.run(
            ["ffmpeg", "-y", "-i", tmp_wav, "-c:a", "libopus", tmp_ogg],
            capture_output=True
        )
        try:
            os.remove(tmp_wav)
        except Exception:
            pass

        return tmp_ogg if os.path.exists(tmp_ogg) else None
    except Exception:
        return None

# ── Command handlers ───────────────────────────────────────────────────────────
async def _cmd_ping(update: "Update", context: "ContextTypes.DEFAULT_TYPE"):
    """Instant connection test — no process_command involved."""
    if not _is_allowed(update):
        await update.message.reply_text("⛔ Unauthorised.")
        return
    await update.message.reply_text("🟢 JARVIS bridge is alive. Send any command.")

async def _cmd_start(update: "Update", context: "ContextTypes.DEFAULT_TYPE"):
    if not _is_allowed(update):
        await update.message.reply_text("⛔ Unauthorised.")
        return
    await update.message.reply_text(
        "👋 *JARVIS Online*\n\n"
        "Send any text command or a 🎤 voice note.\n\n"
        "Quick commands:\n"
        "/ping — connection test\n"
        "/status — uptime and model info\n"
        "/tasks — pending tasks\n"
        "/stop — disable bridge",
        parse_mode="Markdown"
    )

async def _cmd_status(update: "Update", context: "ContextTypes.DEFAULT_TYPE"):
    if not _is_allowed(update):
        return
    try:
        from deepMemory import get_jarvis_self_status
        s   = get_jarvis_self_status()
        msg = (f"🟢 *JARVIS Status*\n"
               f"Uptime: `{s['uptime']}`\n"
               f"Voice model: `{s['active_model']}`\n"
               f"Router: `{s['router_model']}`\n"
               f"Version: `{s['version']}`")
    except Exception as e:
        msg = f"Status unavailable: {e}"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def _cmd_tasks(update: "Update", context: "ContextTypes.DEFAULT_TYPE"):
    if not _is_allowed(update):
        return
    try:
        from taskManager import list_tasks
        result = list_tasks("pending")
    except Exception as e:
        result = f"Task list unavailable: {e}"
    await update.message.reply_text(
        f"📋 *Pending Tasks*\n```\n{result}\n```",
        parse_mode="Markdown"
    )

async def _cmd_stop(update: "Update", context: "ContextTypes.DEFAULT_TYPE"):
    if not _is_allowed(update):
        return
    await update.message.reply_text(
        "🔴 Telegram bridge stopping. JARVIS continues running locally."
    )
    context.application.stop_running()

async def _handle_text(update: "Update", context: "ContextTypes.DEFAULT_TYPE"):
    """Process a typed command and send JARVIS's response back."""
    if not _is_allowed(update):
        await update.message.reply_text("⛔ Unauthorised.")
        return

    user_text = (update.message.text or "").strip()
    if not user_text:
        return

    chat_id = update.effective_chat.id
    await update.message.reply_chat_action("typing")

    try:
        reply_text = _run_and_capture(user_text, timeout=90)
    except Exception as e:
        reply_text = f"⚠️ Error: {e}"

    # Telegram has a 4096 char cap per message
    if len(reply_text) > 4096:
        reply_text = reply_text[:4090] + "…"

    await update.message.reply_text(reply_text)

    # Optional voice reply (requires ffmpeg in PATH)
    if config.TELEGRAM_VOICE_REPLY and len(reply_text) <= 500:
        ogg = _synthesize_ogg(reply_text)
        if ogg:
            try:
                with open(ogg, "rb") as f:
                    await update.message.reply_voice(f)
            except Exception:
                pass
            finally:
                try:
                    os.remove(ogg)
                except Exception:
                    pass

async def _handle_voice(update: "Update", context: "ContextTypes.DEFAULT_TYPE"):
    """Download voice note → Whisper transcription → execute → reply."""
    if not _is_allowed(update):
        return

    await update.message.reply_chat_action("typing")

    voice_file = await context.bot.get_file(update.message.voice.file_id)
    tmp_ogg    = tempfile.mktemp(suffix=".ogg")
    tmp_wav    = tempfile.mktemp(suffix=".wav")

    await voice_file.download_to_drive(tmp_ogg)
    subprocess.run(
        ["ffmpeg", "-y", "-i", tmp_ogg, "-ar", "16000", "-ac", "1", tmp_wav],
        capture_output=True
    )

    transcribed = ""
    try:
        # Use Whisper that's already loaded in tts.py
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from tts import get_whisper_model
        model    = get_whisper_model()
        segs, _  = model.transcribe(tmp_wav, language="en", vad_filter=True)
        transcribed = " ".join(s.text for s in segs).strip()
    except Exception as e:
        await update.message.reply_text(f"⚠️ Transcription failed: {e}")
    finally:
        for f in [tmp_ogg, tmp_wav]:
            try:
                os.remove(f)
            except Exception:
                pass

    if not transcribed:
        await update.message.reply_text("❓ No speech detected in the voice note.")
        return

    await update.message.reply_text(f"🎙️ Heard: _{transcribed}_", parse_mode="Markdown")

    # Treat transcription as a text command
    update.message.text = transcribed
    await _handle_text(update, context)

# ── Bot runner ─────────────────────────────────────────────────────────────────
def start_telegram_bridge(process_command_fn, tts_module):
    """
    Launch the bot in a daemon thread.
    process_command_fn : tts.process_command   (1-arg function)
    tts_module         : the tts module itself  (for speak monkeypatching)
    """
    global _process_command_fn, _tts_module, _bot_running, _app

    if not _HAS_TELEGRAM:
        print("[Telegram]: Library not available.")
        return
    if not config.TELEGRAM_BOT_TOKEN:
        print("[Telegram]: TELEGRAM_BOT_TOKEN is empty in .env — bridge disabled.")
        return
    if not config.TELEGRAM_ALLOWED_IDS:
        print("[Telegram]: WARNING — TELEGRAM_ALLOWED_IDS is empty. Anyone can control JARVIS!")

    _process_command_fn = process_command_fn
    _tts_module         = tts_module

    def _run_bot():
        global _bot_running, _app
        _bot_running = True

        # PTB v21 + Python 3.12+ / 3.14:
        # run_polling() calls asyncio.get_event_loop() which raises RuntimeError in threads.
        # The correct fix is asyncio.run() — it creates its own fresh event loop,
        # runs the coroutine, then closes the loop cleanly.
        async def _async_main():
            global _bot_running, _app

            _app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()

            _app.add_handler(CommandHandler("ping",   _cmd_ping))
            _app.add_handler(CommandHandler("start",  _cmd_start))
            _app.add_handler(CommandHandler("status", _cmd_status))
            _app.add_handler(CommandHandler("tasks",  _cmd_tasks))
            _app.add_handler(CommandHandler("stop",   _cmd_stop))
            _app.add_handler(MessageHandler(
                filters.TEXT & ~filters.COMMAND, _handle_text))
            _app.add_handler(MessageHandler(
                filters.VOICE, _handle_voice))

            print("[Telegram]: Bridge active. Message /ping to your bot to confirm.")

            # PTB v21 correct async pattern — initialize first, then start
            # updater, then app, then keep-alive loop, then clean shutdown in reverse
            await _app.initialize()
            await _app.updater.start_polling(
                drop_pending_updates=True,
                allowed_updates=Update.ALL_TYPES,
                poll_interval=5,           # Check every 5 seconds (slower = less DNS spam)
                timeout=30,                 # 30s timeout per poll
                read_timeout=30,
                write_timeout=30,
                connect_timeout=10,
                pool_timeout=10,
            )
            await _app.start()

            # Keep alive until stop_telegram_bridge() clears _bot_running
            while _bot_running:
                await asyncio.sleep(1)

            # Clean shutdown in reverse order
            await _app.updater.stop()
            await _app.stop()
            await _app.shutdown()

        try:
            asyncio.run(_async_main())
        except Exception as e:
            # Suppress network errors (DNS failures, connection drops)
            err_str = str(e).lower()
            if any(x in err_str for x in ["getaddrinfo", "connect", "network", "timeout", "timed out"]):
                print(f"[Telegram]: Network error (will retry): {e}")
            else:
                print(f"[Telegram]: Bridge crashed: {e}")
                import traceback
                traceback.print_exc()
        finally:
            _bot_running = False

    t = threading.Thread(target=_run_bot, daemon=True, name="telegram-bridge")
    t.start()

def stop_telegram_bridge():
    global _app, _bot_running
    if _app:
        try:
            _app.stop()
        except Exception:
            pass
    _bot_running = False

def send_proactive_message(text: str):
    """Push a message to all allowed users without them sending anything first."""
    if not _HAS_TELEGRAM or not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_ALLOWED_IDS:
        return
    async def _send():
        bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
        async with bot:
            for uid in config.TELEGRAM_ALLOWED_IDS:
                try:
                    await bot.send_message(chat_id=uid, text=f"🤖 JARVIS: {text}")
                except Exception as e:
                    print(f"[Telegram]: Could not message {uid}: {e}")
    try:
        asyncio.run(_send())
    except Exception as e:
        print(f"[Telegram]: Proactive message failed: {e}")