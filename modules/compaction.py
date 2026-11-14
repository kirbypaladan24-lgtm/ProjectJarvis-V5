"""
JARVIS Conversation Compaction
================================================================
When ai_memory.json hits N messages, summarize the oldest messages
into a single "session summary" and keep recent ones verbatim.

This gives JARVIS effectively infinite memory without unbounded context.
"""
import os
import sys
import json
import time
from datetime import datetime

_PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PARENT_DIR not in sys.path:
    sys.path.insert(0, _PARENT_DIR)

try:
    import config
except ImportError:
    class config:
        BASE_DIR = "."
        MAX_HISTORY = 50
        OLLAMA_BASE_URL = "http://localhost:11434"
        VOICE_FACE_MODEL = "qwen3:8b"

import requests


# ═════════════════════════════════════════════════════════════
# CONFIGURATION
# ═════════════════════════════════════════════════════════════

# When memory hits this many messages, trigger compaction
COMPACTION_THRESHOLD = 50  # messages

# After compaction, keep this many recent messages verbatim
KEEP_RECENT = 20

# The model to use for summarization
SUMMARY_MODEL = "qwen2.5:1.5b-instruct"  # Use small model for speed


# ═════════════════════════════════════════════════════════════
# COMPACTION LOGIC
# ═════════════════════════════════════════════════════════════

def needs_compaction(history):
    """Check if conversation history needs compaction."""
    return len(history) >= COMPACTION_THRESHOLD


def compact_history(history):
    """
    Compact conversation history.
    - Summarize oldest messages into a single "session summary"
    - Keep KEEP_RECENT most recent messages verbatim
    - Returns new compacted history
    """
    if len(history) < COMPACTION_THRESHOLD:
        return history

    print(f"[Compaction]: Compacting {len(history)} messages...")

    # Split: old messages to summarize, recent to keep
    to_summarize = history[:-KEEP_RECENT]
    to_keep = history[-KEEP_RECENT:]

    # Summarize the old messages
    summary = _summarize_messages(to_summarize)

    if not summary:
        # Summarization failed — just keep the recent ones
        print("[Compaction]: Summarization failed, keeping recent messages only.")
        return to_keep

    # Build new history: summary + recent
    new_history = [
        {
            "role": "system",
            "content": f"[SESSION SUMMARY]: {summary}"
        },
        *to_keep
    ]

    print(f"[Compaction]: Done. {len(history)} → {len(new_history)} messages.")

    # Save the summary to a daily summaries file
    _save_summary(summary, len(to_summarize))

    return new_history


def _summarize_messages(messages):
    """Use the LLM to summarize a batch of messages."""
    # Format messages for summarization
    convo_text = "\n".join([
        f"{'User' if m.get('role') == 'user' else 'JARVIS'}: {m.get('content', '')[:200]}"
        for m in messages
        if m.get("role") in ("user", "assistant") and m.get("content")
    ])

    if not convo_text.strip():
        return None

    prompt = f"""Summarize this conversation in 3-5 sentences. Focus on:
- What topics were discussed
- What actions were taken (tools used, files opened, etc.)
- Any important decisions or facts mentioned
- Any pending tasks or follow-ups

Conversation:
{convo_text}

Summary:"""

    try:
        response = requests.post(
            f"{config.OLLAMA_BASE_URL}/api/chat",
            json={
                "model": SUMMARY_MODEL,
                "messages": [
                    {"role": "system", "content": "You are a conversation summarizer. Be concise but capture all key points."},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
                "options": {"temperature": 0.2, "num_predict": 200},
            },
            timeout=30
        )
        response.raise_for_status()
        summary = response.json().get("message", {}).get("content", "").strip()
        return summary if summary else None

    except Exception as e:
        print(f"[Compaction]: Summarization error: {e}")
        return None


def _save_summary(summary, message_count):
    """Save summary to daily_summaries.json."""
    try:
        summary_file = os.path.join(getattr(config, 'BASE_DIR', '.'), "conversation_summaries.json")
        summaries = []
        if os.path.exists(summary_file):
            with open(summary_file, 'r') as f:
                summaries = json.load(f)

        summaries.append({
            "timestamp": datetime.now().isoformat(),
            "summary": summary,
            "messages_compacted": message_count,
        })

        # Keep only last 100 summaries
        if len(summaries) > 100:
            summaries = summaries[-100:]

        with open(summary_file, 'w') as f:
            json.dump(summaries, f, indent=2)

    except Exception as e:
        print(f"[Compaction]: Save summary error: {e}")


def get_summaries():
    """Load all conversation summaries."""
    try:
        summary_file = os.path.join(getattr(config, 'BASE_DIR', '.'), "conversation_summaries.json")
        if os.path.exists(summary_file):
            with open(summary_file, 'r') as f:
                return json.load(f)
    except Exception:
        pass
    return []


def check_and_compact(history, save_fn=None):
    """
    Check if compaction is needed and do it.
    save_fn: function to save the new history to disk.
    Returns (new_history, was_compacted).
    """
    if not needs_compaction(history):
        return history, False

    new_history = compact_history(history)

    if save_fn and new_history != history:
        try:
            save_fn(new_history)
        except Exception as e:
            print(f"[Compaction]: Save error: {e}")

    return new_history, True
