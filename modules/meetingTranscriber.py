"""
meetingTranscriber.py — Meeting Transcription for JARVIS
──────────────────────────────────────────────────────────
Captures system audio output (Zoom, Teams, Meet, YouTube — anything playing
through your speakers) via WASAPI loopback and transcribes with Whisper.

No cloud service. No screen recording. Just audio → text → summary.

Features:
  - Start/stop recording any meeting
  - Rolling live transcript in memory
  - On-demand summary with action items (via qwen2.5)
  - Answer questions about the meeting ("what did they say about the deadline?")
  - Auto-saves transcript to Desktop on stop
"""

import os
import sys
import re
import time
import queue
import threading
import tempfile
import subprocess
import json
import requests
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    import config
except ImportError:
    class config:
        MEETING_CHUNK_SECS           = 30
        MEETING_SUMMARY_MODEL        = "qwen2.5:7b-instruct"
        MEETING_MAX_TRANSCRIPT_CHARS = 12000
        OLLAMA_BASE_URL              = "http://localhost:11434"
        SAMPLE_RATE                  = 16000

# ── Auto-install pyaudiowpatch for WASAPI loopback ───────────────────────────
_LOOPBACK_INSTALL_ERROR = ""
try:
    import pyaudiowpatch as pyaudio
    _HAS_LOOPBACK = True
except ImportError:
    print("[Meeting]: pyaudiowpatch is not installed. Trying automatic install for WASAPI loopback...")
    try:
        install = subprocess.run(
            [sys.executable, "-m", "pip", "install", "pyaudiowpatch"],
            check=False,
            capture_output=True,
            text=True,
            timeout=120
        )
        if install.returncode != 0:
            _LOOPBACK_INSTALL_ERROR = (install.stderr or install.stdout or "").strip()
    except Exception as e:
        _LOOPBACK_INSTALL_ERROR = str(e)

    try:
        import pyaudiowpatch as pyaudio
        _HAS_LOOPBACK = True
    except Exception:
        _HAS_LOOPBACK = False
        print("[Meeting]: pyaudiowpatch unavailable. Meeting transcription is disabled.")
        print("[Meeting]: Install a pre-built pyaudiowpatch wheel, or install Microsoft Visual C++ Build Tools and run: python -m pip install pyaudiowpatch")
        if _LOOPBACK_INSTALL_ERROR:
            print(f"[Meeting]: Installer detail: {_LOOPBACK_INSTALL_ERROR[:500]}")

try:
    import numpy as np
    from scipy.io.wavfile import write as wav_write
except ImportError:
    import numpy as np
    from scipy.io.wavfile import write as wav_write

# ── State ─────────────────────────────────────────────────────────────────────
_transcript_lines  = []          # Full list of timestamped transcript lines
_is_recording      = False
_record_stop_event = threading.Event()
_record_thread     = None
_meeting_title     = "Meeting"
_meeting_start_ts  = None

# ── WASAPI loopback device finder ─────────────────────────────────────────────
def _find_loopback_device():
    """Find the WASAPI loopback device (what's playing through speakers)."""
    if not _HAS_LOOPBACK:
        return None, None
    pa = pyaudio.PyAudio()
    try:
        # pyaudiowpatch provides get_loopback_device_info_generator
        for loopback in pa.get_loopback_device_info_generator():
            return loopback, pa
        return None, pa
    except Exception:
        return None, pa

# ── Transcription helper ───────────────────────────────────────────────────────
def _transcribe_chunk(audio_data: bytes, sample_rate: int, channels: int) -> str:
    """Convert raw audio bytes to text via Whisper."""
    try:
        # Convert to mono int16 numpy
        import numpy as np
        arr = np.frombuffer(audio_data, dtype=np.int16)
        if channels == 2:
            arr = arr.reshape(-1, 2).mean(axis=1).astype(np.int16)

        tmp = tempfile.mktemp(suffix=".wav")
        wav_write(tmp, sample_rate, arr)

        # Import Whisper from tts.py (already loaded)
        try:
            from tts import get_whisper_model
            model = get_whisper_model()
            segments, _ = model.transcribe(
                tmp, language="en", task="transcribe",
                vad_filter=True, vad_parameters={"min_silence_duration_ms": 500}
            )
            text = " ".join(s.text for s in segments).strip()
        except Exception:
            text = ""

        try:
            os.remove(tmp)
        except Exception:
            pass
        return text
    except Exception as e:
        print(f"[Meeting]: Chunk transcription error: {e}")
        return ""

# ── Recording loop ─────────────────────────────────────────────────────────────
def _recording_loop(device_info, pa):
    """Background loop: capture CHUNK_SECS of loopback audio, transcribe, append."""
    global _transcript_lines, _is_recording

    sample_rate = int(device_info["defaultSampleRate"])
    channels    = min(int(device_info["maxInputChannels"]), 2)
    chunk_secs  = config.MEETING_CHUNK_SECS
    chunk_size  = 1024

    stream = pa.open(
        format=pyaudio.paInt16,
        channels=channels,
        rate=sample_rate,
        input=True,
        input_device_index=int(device_info["index"]),
        frames_per_buffer=chunk_size
    )

    print(f"[Meeting]: Recording started — {sample_rate}Hz, {channels}ch")
    frames_per_chunk = sample_rate * chunk_secs

    while not _record_stop_event.is_set():
        frames = []
        for _ in range(0, frames_per_chunk, chunk_size):
            if _record_stop_event.is_set():
                break
            try:
                data = stream.read(chunk_size, exception_on_overflow=False)
                frames.append(data)
            except Exception:
                pass

        if frames:
            raw = b"".join(frames)
            text = _transcribe_chunk(raw, sample_rate, channels)
            if text and len(text.strip()) > 5:
                ts   = datetime.now().strftime("%H:%M:%S")
                line = f"[{ts}] {text}"
                _transcript_lines.append(line)
                print(f"[Meeting Transcript]: {line}")

    stream.stop_stream()
    stream.close()
    pa.terminate()
    print("[Meeting]: Recording stopped.")

# ── Public API ─────────────────────────────────────────────────────────────────

def start_meeting_transcription(title: str = "Meeting") -> str:
    """Start capturing and transcribing system audio."""
    global _is_recording, _record_thread, _transcript_lines
    global _meeting_title, _meeting_start_ts, _record_stop_event

    if not _HAS_LOOPBACK:
        return ("Meeting transcription requires pyaudiowpatch. "
                "Run: python -m pip install pyaudiowpatch. If that fails on Windows, install Microsoft Visual C++ Build Tools or a pre-built pyaudiowpatch wheel, Sir.")

    if _is_recording:
        return "A meeting is already being transcribed, Sir."

    device_info, pa = _find_loopback_device()
    if not device_info:
        return ("No WASAPI loopback device found. Make sure your speakers are the default "
                "audio output and that you are on Windows, Sir.")

    _transcript_lines  = []
    _meeting_title     = title
    _meeting_start_ts  = datetime.now()
    _record_stop_event = threading.Event()
    _is_recording      = True

    _record_thread = threading.Thread(
        target=_recording_loop,
        args=(device_info, pa),
        daemon=True,
        name="meeting-transcriber"
    )
    _record_thread.start()

    return (f"Meeting transcription started, Sir. I am now capturing all audio "
            f"playing through your speakers. Say 'stop transcribing' when the meeting ends.")


def stop_meeting_transcription(save: bool = True) -> str:
    """Stop recording and optionally save the transcript to Desktop."""
    global _is_recording, _record_stop_event

    if not _is_recording:
        return "No meeting is currently being transcribed, Sir."

    _record_stop_event.set()
    _is_recording = False

    if not _transcript_lines:
        return "Meeting ended. No speech was detected in the audio, Sir."

    result = f"Meeting transcription stopped. Captured {len(_transcript_lines)} segments.\n"

    if save:
        saved_path = _save_transcript()
        result += f"Transcript saved to: {saved_path}"
    return result


def get_transcript() -> str:
    """Return the full transcript captured so far."""
    if not _transcript_lines:
        return "No transcript available yet, Sir."
    return "\n".join(_transcript_lines)


def summarize_meeting(focus: str = None) -> str:
    """
    Summarize the transcript using qwen2.5.
    focus: optional topic to focus on (e.g. 'deadlines', 'action items')
    """
    if not _transcript_lines:
        return "There is no transcript to summarize yet, Sir."

    transcript = "\n".join(_transcript_lines)
    # Trim to model context limit
    if len(transcript) > config.MEETING_MAX_TRANSCRIPT_CHARS:
        transcript = transcript[-config.MEETING_MAX_TRANSCRIPT_CHARS:]

    focus_note = f" Focus specifically on: {focus}." if focus else ""
    prompt = f"""You are JARVIS summarizing a meeting transcript for Mr. Kirby Paladan.

TRANSCRIPT:
{transcript}

Task: Provide a concise professional summary.{focus_note}
Include:
1. Main topics discussed
2. Key decisions made  
3. Action items with owners if mentioned
4. Any deadlines mentioned

Keep it under 200 words. Address the user as Sir."""

    try:
        r = requests.post(
            f"{config.OLLAMA_BASE_URL}/api/chat",
            json={
                "model": config.MEETING_SUMMARY_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False
            },
            timeout=60
        )
        if r.status_code == 200:
            return r.json().get("message", {}).get("content", "").strip()
    except Exception as e:
        return f"Could not generate summary: {e}"
    return "Summary unavailable, Sir."


def answer_from_transcript(question: str) -> str:
    """Answer a specific question using only the transcript content."""
    if not _transcript_lines:
        return "There is no transcript to search yet, Sir."

    transcript = "\n".join(_transcript_lines)
    if len(transcript) > config.MEETING_MAX_TRANSCRIPT_CHARS:
        transcript = transcript[-config.MEETING_MAX_TRANSCRIPT_CHARS:]

    prompt = f"""You are JARVIS. Answer the following question using ONLY the meeting transcript below.
If the answer is not in the transcript, say so clearly.

QUESTION: {question}

TRANSCRIPT:
{transcript}

Answer concisely as JARVIS, addressing the user as Sir."""

    try:
        r = requests.post(
            f"{config.OLLAMA_BASE_URL}/api/chat",
            json={
                "model": config.MEETING_SUMMARY_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False
            },
            timeout=45
        )
        if r.status_code == 200:
            return r.json().get("message", {}).get("content", "").strip()
    except Exception as e:
        return f"Could not search transcript: {e}"
    return "Could not answer from transcript, Sir."


def _save_transcript() -> str:
    """Save transcript to Desktop as a Markdown file."""
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    os.makedirs(desktop, exist_ok=True)
    ts      = datetime.now().strftime("%Y-%m-%d_%H-%M")
    path    = os.path.join(desktop, f"JARVIS_Meeting_{ts}.md")
    dur_min = int((datetime.now() - _meeting_start_ts).total_seconds() / 60) if _meeting_start_ts else 0
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"# Meeting Transcript: {_meeting_title}\n")
            f.write(f"*Recorded: {datetime.now().strftime('%Y-%m-%d %I:%M %p')} | Duration: ~{dur_min} min*\n\n")
            f.write("---\n\n")
            for line in _transcript_lines:
                f.write(f"{line}\n\n")
    except Exception as e:
        return f"Save failed: {e}"
    return path


# ── Command router ─────────────────────────────────────────────────────────────
def handle_meeting_commands(user_input: str) -> str | None:
    text = re.sub(r'[.,!?;:]+', '', user_input.lower().strip())

    # Start
    if any(p in text for p in ["start transcribing", "transcribe meeting", "record meeting",
                                "start meeting", "start recording meeting",
                                "transcribe the call", "transcribe the meeting",
                                "listen to meeting"]):
        title_match = re.search(r'(?:called|named|titled)\s+(.+)$', text)
        title = title_match.group(1).strip() if title_match else "Meeting"
        return start_meeting_transcription(title)

    # Stop
    if any(p in text for p in ["stop transcribing", "stop meeting", "end meeting",
                                "stop recording", "finish meeting"]):
        return stop_meeting_transcription(save=True)

    # Summary
    if any(p in text for p in ["summarize meeting", "meeting summary", "what was discussed",
                                "what did they talk about", "summarize the call",
                                "summary of the meeting"]):
        focus_match = re.search(r'(?:about|regarding|focus on|focusing on)\s+(.+)$', text)
        focus = focus_match.group(1).strip() if focus_match else None
        return summarize_meeting(focus)

    # Full transcript
    if any(p in text for p in ["show transcript", "meeting transcript", "full transcript",
                                "read the transcript"]):
        t = get_transcript()
        return t[:2000] + ("..." if len(t) > 2000 else "")

    # Q&A from transcript
    transcript_qa = re.search(
        r'(?:what did (?:they|he|she|the (?:speaker|presenter|host)) say about|'
        r'was (?:there|anything) mentioned about|'
        r'find in transcript|search transcript for)\s+(.+)$', text)
    if transcript_qa:
        return answer_from_transcript(transcript_qa.group(1).strip())

    return None
