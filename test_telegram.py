"""
test_telegram.py — Run this SEPARATELY from JARVIS to diagnose the Telegram issue.
Usage: python test_telegram.py
Keep it running and send /ping to your bot from Telegram.
"""
import sys
import subprocess
import requests

# ── Step 1: Load token from config ───────────────────────────────────────────
try:
    import config
    TOKEN = config.TELEGRAM_BOT_TOKEN
    IDS   = config.TELEGRAM_ALLOWED_IDS
except Exception as e:
    print(f"[FAIL] Cannot import config.py: {e}")
    sys.exit(1)

print(f"[INFO] Token loaded: ...{TOKEN[-10:] if TOKEN else 'EMPTY'}")
print(f"[INFO] Allowed IDs : {IDS}")

if not TOKEN:
    print("[FAIL] TELEGRAM_BOT_TOKEN is empty in .env.")
    print("       Get a new token from @BotFather → /mybots → your bot → API Token → Revoke → copy new one")
    sys.exit(1)

# ── Step 2: Test the token against Telegram API ───────────────────────────────
print("\n[TEST] Calling getMe to verify token...")
try:
    r = requests.get(f"https://api.telegram.org/bot{TOKEN}/getMe", timeout=10)
    data = r.json()
    if data.get("ok"):
        bot = data["result"]
        print(f"[PASS] Bot verified: @{bot['username']} (ID: {bot['id']})")
    else:
        print(f"[FAIL] Telegram rejected the token: {data.get('description')}")
        print("       Your token is revoked or wrong. Get a new one from @BotFather.")
        sys.exit(1)
except Exception as e:
    print(f"[FAIL] Cannot reach Telegram API: {e}")
    print("       Check your internet connection.")
    sys.exit(1)

# ── Step 3: Check for any pending updates (did messages arrive?) ──────────────
print("\n[TEST] Checking for pending updates...")
try:
    r = requests.get(f"https://api.telegram.org/bot{TOKEN}/getUpdates", timeout=10)
    updates = r.json().get("result", [])
    if updates:
        latest = updates[-1]
        msg    = latest.get("message", {})
        sender = msg.get("from", {})
        chat   = msg.get("chat", {})
        text   = msg.get("text", "(no text)")
        uid    = sender.get("id")
        print(f"[PASS] Latest message found:")
        print(f"       From: {sender.get('first_name')} (ID: {uid})")
        print(f"       Chat ID: {chat.get('id')}")
        print(f"       Text: {text}")
        if IDS and uid not in IDS:
            print(f"\n[WARN] Your user ID ({uid}) is NOT in TELEGRAM_ALLOWED_IDS ({IDS})")
            print(f"       Fix: TELEGRAM_ALLOWED_IDS = [{uid}] in config.py")
        else:
            print(f"[PASS] Your ID {uid} is authorized.")
    else:
        print("[INFO] No pending updates — no messages seen by this bot yet.")
        print("       Send /ping to your bot from Telegram, then re-run this script.")
except Exception as e:
    print(f"[FAIL] Could not fetch updates: {e}")

# ── Step 4: Run minimal bot that just replies ─────────────────────────────────
print("\n[TEST] Starting minimal echo bot (Ctrl+C to stop)...")
print("       Send any message to your bot now.\n")

try:
    from telegram import Update
    from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes

    async def ping(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id
        print(f"[RECV] /ping from user ID {uid}")
        await update.message.reply_text(f"🟢 PONG — bridge works! Your ID is {uid}")

    async def echo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid  = update.effective_user.id
        text = update.message.text
        print(f"[RECV] Message from {uid}: {text}")
        await update.message.reply_text(f"✅ Received: {text}\nYour ID: {uid}")

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(MessageHandler(filters.TEXT, echo))

    print("[RUNNING] Bot is live. Send /ping now...")
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    app.run_polling(drop_pending_updates=True)

except KeyboardInterrupt:
    print("\nStopped.")
except Exception as e:
    print(f"[FAIL] Bot crashed: {e}")
    import traceback
    traceback.print_exc()