import requests
import subprocess
import sounddevice as sd
import soundfile as sf
import tempfile
import os
import time
import sys
import re
import json
import queue
import threading
import importlib
import numpy as np
from scipy.io.wavfile import write
import warnings
warnings.filterwarnings("ignore", category=UserWarning, module="huggingface_hub")
import os
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
from faster_whisper import WhisperModel
from datetime import datetime

# Import centralized configuration
import config

# Import all modules individually from same directory
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "modules"))

# Import new upgrading modules
from modelRouter import route_request, check_model_health, get_active_models, escalate_to_fallback
from bodyAwareness import start_all_monitors, run_full_diagnostics
from languageIntelligence import preprocess_input, detect_tone, clarify_partial, load_context_on_restart
from autonomousExecution import (handle_macro_chains, approval_gate, run_python_file, 
                                 git_voice_control, organize_downloads, start_clipboard_watcher,
                                 set_scheduled_automation)
from deepMemory import (summarize_session, load_daily_summary, save_vector_fact, 
                        vector_search, save_to_knowledge_base, get_jarvis_self_status, 
                        track_goal, learn_work_patterns, infer_emotional_state)
from personalityEngine import get_personality_prompt
from selfRepair import (start_module_watchdog, start_resource_guardian, log_crash, 
                        recover_last_session, check_anomalous_processes, secure_read_json, secure_write_json)
from privacyMode import enable_privacy_mode, disable_privacy_mode, is_privacy_mode_active
from morningBriefing import get_morning_briefing
from responseCache import get_cached, set_cache
from conversationExport import export_conversation, search_history

# Tier 3.1: Persistent cross-session memory
try:
    from persistentMemory import auto_learn_from_exchange, build_memory_context, cleanup_old_memories
    HAS_PERSISTENT_MEMORY = True
    print("[Modules]: Persistent memory loaded.")
except ImportError as _e:
    HAS_PERSISTENT_MEMORY = False
    def auto_learn_from_exchange(u, a): pass
    def build_memory_context(q): return ""
    def cleanup_old_memories(d=None): return 0
    print(f"[Warning]: Persistent memory not available: {_e}")

# Tier 3.2: Plugin system for live tool registration
try:
    from pluginSystem import start_plugin_watcher, discover_plugins, list_plugins
    HAS_PLUGIN_SYSTEM = True
    print("[Modules]: Plugin system loaded.")
except ImportError as _e:
    HAS_PLUGIN_SYSTEM = False
    def start_plugin_watcher(): pass
    def discover_plugins(): return 0
    def list_plugins(): return {}
    print(f"[Warning]: Plugin system not available: {_e}")

# Tier 4: Knowledge file injector (PDFs, Word docs, text files)
try:
    from knowledgeInjector import start_knowledge_watcher, build_knowledge_context, get_knowledge_stats
    HAS_KNOWLEDGE_INJECTOR = True
    print("[Modules]: Knowledge injector loaded.")
except ImportError as _e:
    HAS_KNOWLEDGE_INJECTOR = False
    def start_knowledge_watcher(): pass
    def build_knowledge_context(q): return ""
    def get_knowledge_stats(): return {}
    print(f"[Warning]: Knowledge injector not available: {_e}")

HAS_MODULES = False

try:
    from taskManager    import create_task, complete_task, complete_task_by_title, list_tasks, handle_task_commands
    from fileSearch     import search_files, open_file_with_default_app, handle_file_commands
    from noteSystem     import save_note, search_notes, handle_note_commands, take_screenshot, write_to_notepad
    from semanticMemory import save_semantic_fact, recall_related_facts, load_semantic_memory
    from commandHistory import save_command_to_history, analyze_user_patterns, suggest_command_shortcuts
    from systemMonitor  import get_system_stats, system_health_check, list_running_apps, handle_system_monitor_commands
    HAS_MODULES = True
    print("[Modules]: All modules loaded successfully.")
except ImportError as e:
    print(f"[Warning]: Could not import one or more modules: {e}")
    def save_command_to_history(*a, **kw): pass
    def load_semantic_memory(): return {}
    def handle_task_commands(x): return None
    def handle_file_commands(x): return None
    def handle_note_commands(x): return None
    def take_screenshot(*a, **kw): return "Screenshot module not available."
    def write_to_notepad(*a, **kw): return "Notepad module not available."
    def handle_system_monitor_commands(x): return None

# Telegram remote bridge
try:
    from telegramBridge import start_telegram_bridge, send_proactive_message, stop_telegram_bridge
    HAS_TELEGRAM = True
    print("[Modules]: Telegram bridge module loaded.")
except Exception as e:
    HAS_TELEGRAM = False
    print(f"[Modules]: Telegram bridge not available: {e}")
    def start_telegram_bridge(*a, **kw): pass
    def send_proactive_message(t): pass

# Capabilities / self-knowledge module
try:
    from capabilities import handle_capability_commands, get_full_capabilities_text
    HAS_CAPABILITIES = True
    print("[Modules]: Capabilities module loaded.")
except ImportError as e:
    HAS_CAPABILITIES = False
    handle_capability_commands = lambda x: None
    print(f"[Warning]: capabilities.py not found: {e}")

# Internet search module
try:
    from internetSearch import (handle_internet_commands, is_online,
                                 web_search, get_weather, get_news,
                                 wikipedia_summary)
    HAS_INTERNET_MODULE = True
    print("[Modules]: Internet search module loaded.")
except ImportError as e:
    HAS_INTERNET_MODULE = False
    is_online = lambda: False
    handle_internet_commands = lambda x: None
    print(f"[Warning]: internetSearch.py not found: {e}")

# Vision module — cameraAccess.py must be in the same folder
try:
    import cameraAccess as _cam_module
    camera_see = _cam_module.see
    pull_vision_model_if_needed = _cam_module.pull_vision_model_if_needed
    HAS_VISION = True
except ImportError:
    HAS_VISION = False
    _cam_module = None
    print("[Warning]: cameraAccess.py not found. Vision disabled.")

# System control module
try:
    from systemControl import handle_system_command
    HAS_SYSTEM_CONTROL = True
except ImportError:
    HAS_SYSTEM_CONTROL = False
    print("[Warning]: systemControl.py not found. System control disabled.")

# Spotify control module
try:
    from spotifyControl import handle_spotify_command
    HAS_SPOTIFY = True
except ImportError:
    HAS_SPOTIFY = False
    print("[Warning]: spotifyControl.py not found. Spotify control disabled.")

try:
    from zoneinfo import ZoneInfo
    HAS_ZONEINFO = True
except ImportError:
    HAS_ZONEINFO = False
    try:
        import pytz
    except ImportError:
        print("Installing pytz for timezone support...")
        subprocess.run([sys.executable, "-m", "pip", "install", "pytz"], check=True)
        import pytz

# Global Hotkey module
try:
    from pynput import keyboard
    HAS_PYNPUT = True
except ImportError:
    print("[System]: Installing pynput library for global hotkey support...")
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "pynput"], check=True)
        from pynput import keyboard
        HAS_PYNPUT = True
    except:
        HAS_PYNPUT = False
        print("[Warning]: pynput could not be installed. Hotkey triggers disabled.")

# ─────────────────────────────────────────────
# MODEL DEFAULTS — read from centralized config
# ─────────────────────────────────────────────
DEFAULT_JARVIS_MODEL   = config.DEFAULT_JARVIS_MODEL
MODEL_FAST             = config.INTENT_MODEL
MODEL_SMART            = config.CODE_MODEL
MODEL_SECONDARY       = config.VOICE_FACE_MODEL

MODEL = config.VOICE_FACE_MODEL   # Default to Voice Face model (Qwen)
VOICE = config.VOICE
MEMORY_FILE = config.MEMORY_FILE
PROFILE_FILE = config.PROFILE_FILE
MAX_HISTORY = config.MAX_HISTORY
MIC_ENERGY_THRESHOLD = 150
_last_executed_code_path = None
_jarvis_sleeping = False

# FIXED: Dynamically register pip-installed NVIDIA CUDA/cuDNN DLLs with Windows OS loader
if sys.platform == "win32":
    for path in sys.path:
        if "site-packages" in path:
            cublas_dir = os.path.join(path, "nvidia", "cublas", "bin")
            cudnn_dir = os.path.join(path, "nvidia", "cudnn", "bin")
            if os.path.exists(cublas_dir):
                try:
                    os.add_dll_directory(cublas_dir)
                except Exception:
                    pass
            if os.path.exists(cudnn_dir):
                try:
                    os.add_dll_directory(cudnn_dir)
                except Exception:
                    pass

# ─────────────────────────────────────────────
# WORLD TIME
# ─────────────────────────────────────────────

ALL_COUNTRIES_TIMEZONES = {
    "Baker Island": "Etc/GMT+12", "Howland Island": "Etc/GMT+12",
    "American Samoa": "Pacific/Pago_Pago", "Niue": "Pacific/Niue",
    "Midway Atoll": "Pacific/Midway", "Samoa": "Pacific/Apia",
    "Hawaii": "Pacific/Honolulu", "Cook Islands": "Pacific/Rarotonga",
    "Tahiti": "Pacific/Tahiti", "French Polynesia": "Pacific/Tahiti",
    "Aleutian Islands": "America/Adak", "Gambier Islands": "Pacific/Gambier",
    "Alaska": "America/Anchorage", "California": "America/Los_Angeles",
    "Los Angeles": "America/Los_Angeles", "San Francisco": "America/Los_Angeles",
    "Seattle": "America/Los_Angeles", "Portland": "America/Los_Angeles",
    "Las Vegas": "America/Los_Angeles", "Vancouver": "America/Vancouver",
    "Tijuana": "America/Tijuana", "Pitcairn Islands": "Pacific/Pitcairn",
    "Arizona": "America/Phoenix", "Phoenix": "America/Phoenix",
    "Denver": "America/Denver", "Salt Lake City": "America/Denver",
    "Calgary": "America/Edmonton", "Edmonton": "America/Edmonton",
    "Chihuahua": "America/Chihuahua", "Chicago": "America/Chicago",
    "Dallas": "America/Chicago", "Houston": "America/Chicago",
    "Minneapolis": "America/Chicago", "Milwaukee": "America/Chicago",
    "Winnipeg": "America/Winnipeg", "Regina": "America/Regina",
    "Mexico City": "America/Mexico_City", "Guadalajara": "America/Mexico_City",
    "Monterrey": "America/Monterrey", "Guatemala": "America/Guatemala",
    "Belize": "America/Belize", "El Salvador": "America/El_Salvador",
    "Honduras": "America/Tegucigalpa", "Nicaragua": "America/Managua",
    "Costa Rica": "America/Costa_Rica", "Easter Island": "Pacific/Easter",
    "New York": "America/New_York", "Miami": "America/New_York",
    "Boston": "America/New_York", "Washington DC": "America/New_York",
    "Atlanta": "America/New_York", "Philadelphia": "America/New_York",
    "Detroit": "America/New_York", "Toronto": "America/Toronto",
    "Montreal": "America/Montreal", "Ottawa": "America/Toronto",
    "Havana": "America/Havana", "Cuba": "America/Havana",
    "Panama": "America/Panama", "Jamaica": "America/Jamaica",
    "Colombia": "America/Bogota", "Bogota": "America/Bogota",
    "Peru": "America/Lima", "Lima": "America/Lima",
    "Ecuador": "America/Guayaquil", "Quito": "America/Guayaquil",
    "Bahamas": "America/Nassau", "Cancun": "America/Cancun",
    "Haiti": "America/Port-au-Prince", "Caracas": "America/Caracas",
    "Venezuela": "America/Caracas", "La Paz": "America/La_Paz",
    "Bolivia": "America/La_Paz", "Santiago": "America/Santiago",
    "Chile": "America/Santiago", "Dominican Republic": "America/Santo_Domingo",
    "Puerto Rico": "America/Puerto_Rico", "Barbados": "America/Barbados",
    "Trinidad and Tobago": "America/Port_of_Spain",
    "Bermuda": "Atlantic/Bermuda", "Greenland": "America/Godthab",
    "Guyana": "America/Guyana", "Paraguay": "America/Asuncion",
    "Halifax": "America/Halifax", "Argentina": "America/Argentina/Buenos_Aires",
    "Buenos Aires": "America/Argentina/Buenos_Aires",
    "Brazil": "America/Sao_Paulo", "Sao Paulo": "America/Sao_Paulo",
    "Rio de Janeiro": "America/Sao_Paulo", "Brasilia": "America/Sao_Paulo",
    "Uruguay": "America/Montevideo", "Montevideo": "America/Montevideo",
    "French Guiana": "America/Cayenne", "Suriname": "America/Paramaribo",
    "Falkland Islands": "Atlantic/Stanley", "Newfoundland": "America/St_Johns",
    "Cape Verde": "Atlantic/Cape_Verde", "Azores": "Atlantic/Azores",
    "London": "Europe/London", "UK": "Europe/London",
    "United Kingdom": "Europe/London", "England": "Europe/London",
    "Dublin": "Europe/Dublin", "Ireland": "Europe/Dublin",
    "Lisbon": "Europe/Lisbon", "Portugal": "Europe/Lisbon",
    "Casablanca": "Africa/Casablanca", "Morocco": "Africa/Casablanca",
    "Accra": "Africa/Accra", "Ghana": "Africa/Accra",
    "Dakar": "Africa/Dakar", "Senegal": "Africa/Dakar",
    "Monrovia": "Africa/Monrovia", "Liberia": "Africa/Monrovia",
    "Reykjavik": "Atlantic/Reykjavik", "Iceland": "Atlantic/Reykjavik",
    "UTC": "UTC", "GMT": "UTC",
    "Paris": "Europe/Paris", "France": "Europe/Paris",
    "Berlin": "Europe/Berlin", "Germany": "Europe/Berlin",
    "Rome": "Europe/Rome", "Italy": "Europe/Rome",
    "Madrid": "Europe/Madrid", "Spain": "Europe/Madrid",
    "Barcelona": "Europe/Madrid", "Amsterdam": "Europe/Amsterdam",
    "Netherlands": "Europe/Amsterdam", "Brussels": "Europe/Brussels",
    "Belgium": "Europe/Brussels", "Vienna": "Europe/Vienna",
    "Austria": "Europe/Vienna", "Zurich": "Europe/Zurich",
    "Switzerland": "Europe/Zurich", "Stockholm": "Europe/Stockholm",
    "Sweden": "Europe/Stockholm", "Oslo": "Europe/Oslo",
    "Norway": "Europe/Oslo", "Copenhagen": "Europe/Copenhagen",
    "Denmark": "Europe/Copenhagen", "Helsinki": "Europe/Helsinki",
    "Finland": "Europe/Helsinki", "Warsaw": "Europe/Warsaw",
    "Poland": "Europe/Warsaw", "Prague": "Europe/Prague",
    "Czech Republic": "Europe/Prague", "Budapest": "Europe/Budapest",
    "Hungary": "Europe/Budapest", "Bucharest": "Europe/Bucharest",
    "Romania": "Europe/Bucharest", "Athens": "Europe/Athens",
    "Greece": "Europe/Athens", "Belgrade": "Europe/Belgrade",
    "Serbia": "Europe/Belgrade", "Sofia": "Europe/Sofia",
    "Bulgaria": "Europe/Sofia", "Riga": "Europe/Riga",
    "Latvia": "Europe/Riga", "Vilnius": "Europe/Vilnius",
    "Lithuania": "Europe/Vilnius", "Tallinn": "Europe/Tallinn",
    "Estonia": "Europe/Tallinn", "Kyiv": "Europe/Kiev",
    "Ukraine": "Europe/Kiev", "Minsk": "Europe/Minsk",
    "Belarus": "Europe/Minsk", "Moscow": "Europe/Moscow",
    "Russia": "Europe/Moscow", "Istanbul": "Europe/Istanbul",
    "Turkey": "Europe/Istanbul", "Ankara": "Europe/Istanbul",
    "Cairo": "Africa/Cairo", "Egypt": "Africa/Cairo",
    "Lagos": "Africa/Lagos", "Nigeria": "Africa/Lagos",
    "Nairobi": "Africa/Nairobi", "Kenya": "Africa/Nairobi",
    "Addis Ababa": "Africa/Addis_Ababa", "Ethiopia": "Africa/Addis_Ababa",
    "Johannesburg": "Africa/Johannesburg", "South Africa": "Africa/Johannesburg",
    "Cape Town": "Africa/Johannesburg", "Khartoum": "Africa/Khartoum",
    "Sudan": "Africa/Khartoum", "Kampala": "Africa/Kampala",
    "Uganda": "Africa/Kampala", "Dar es Salaam": "Africa/Dar_es_Salaam",
    "Tanzania": "Africa/Dar_es_Salaam", "Tripoli": "Africa/Tripoli",
    "Libya": "Africa/Tripoli", "Tunis": "Africa/Tunis",
    "Tunisia": "Africa/Tunis", "Algiers": "Africa/Algiers",
    "Algeria": "Africa/Algiers", "Jerusalem": "Asia/Jerusalem",
    "Israel": "Asia/Jerusalem", "Beirut": "Asia/Beirut",
    "Lebanon": "Asia/Beirut", "Damascus": "Asia/Damascus",
    "Syria": "Asia/Damascus", "Amman": "Asia/Amman",
    "Jordan": "Asia/Amman", "Riyadh": "Asia/Riyadh",
    "Saudi Arabia": "Asia/Riyadh", "Doha": "Asia/Qatar",
    "Qatar": "Asia/Qatar", "Kuwait": "Asia/Kuwait",
    "Baghdad": "Asia/Baghdad", "Iraq": "Asia/Baghdad",
    "Muscat": "Asia/Muscat", "Oman": "Asia/Muscat",
    "Dubai": "Asia/Dubai", "UAE": "Asia/Dubai",
    "United Arab Emirates": "Asia/Dubai", "Baku": "Asia/Baku",
    "Azerbaijan": "Asia/Baku", "Tbilisi": "Asia/Tbilisi",
    "Georgia": "Asia/Tbilisi", "Yerevan": "Asia/Yerevan",
    "Armenia": "Asia/Yerevan", "Karachi": "Asia/Karachi",
    "Pakistan": "Asia/Karachi", "Tashkent": "Asia/Tashkent",
    "Uzbekistan": "Asia/Tashkent", "Dhaka": "Asia/Dhaka",
    "Bangladesh": "Asia/Dhaka", "Bangkok": "Asia/Bangkok",
    "Thailand": "Asia/Bangkok", "Hanoi": "Asia/Bangkok",
    "Vietnam": "Asia/Ho_Chi_Minh", "Ho Chi Minh City": "Asia/Ho_Chi_Minh",
    "Phnom Penh": "Asia/Phnom_Penh", "Cambodia": "Asia/Phnom_Penh",
    "Vientiane": "Asia/Vientiane", "Laos": "Asia/Vientiane",
    "Jakarta": "Asia/Jakarta", "Indonesia": "Asia/Jakarta",
    "Beijing": "Asia/Shanghai", "China": "Asia/Shanghai",
    "Shanghai": "Asia/Shanghai", "Taipei": "Asia/Taipei",
    "Taiwan": "Asia/Taipei", "Hong Kong": "Asia/Hong_Kong",
    "Singapore": "Asia/Singapore", "Kuala Lumpur": "Asia/Kuala_Lumpur",
    "Malaysia": "Asia/Kuala_Lumpur", "Manila": "Asia/Manila",
    "Philippines": "Asia/Manila", "Cebu": "Asia/Manila",
    "Davao": "Asia/Manila", "Perth": "Australia/Perth",
    "Ulaanbaatar": "Asia/Ulaanbaatar", "Mongolia": "Asia/Ulaanbaatar",
    "Brunei": "Asia/Brunei", "Tokyo": "Asia/Tokyo",
    "Japan": "Asia/Tokyo", "Osaka": "Asia/Tokyo",
    "Seoul": "Asia/Seoul", "South Korea": "Asia/Seoul",
    "North Korea": "Asia/Pyongyang", "Sydney": "Australia/Sydney",
    "Australia": "Australia/Sydney", "Melbourne": "Australia/Melbourne",
    "Brisbane": "Australia/Brisbane", "Adelaide": "Australia/Adelaide",
    "Guam": "Pacific/Guam", "Papua New Guinea": "Pacific/Port_Moresby",
    "Solomon Islands": "Pacific/Guadalcanal",
    "New Caledonia": "Pacific/Noumea", "Norfolk Island": "Pacific/Norfolk",
    "Auckland": "Pacific/Auckland", "New Zealand": "Pacific/Auckland",
    "Wellington": "Pacific/Auckland", "Fiji": "Pacific/Fiji",
    "Tuvalu": "Pacific/Funafuti", "Kiribati": "Pacific/Tarawa",
    "Marshall Islands": "Pacific/Majuro", "Tonga": "Pacific/Tongatapu",
}

def get_timezone(tz_name):
    if HAS_ZONEINFO:
        return ZoneInfo(tz_name)
    else:
        return pytz.timezone(tz_name)

def get_all_world_times():
    if HAS_ZONEINFO:
        now_utc = datetime.now(ZoneInfo("UTC"))
    else:
        now_utc = datetime.now(pytz.utc)

    results = []
    seen_tzs = set()
    for country, tz_name in sorted(ALL_COUNTRIES_TIMEZONES.items()):
        if tz_name in seen_tzs:
            continue
        seen_tzs.add(tz_name)
        try:
            tz = get_timezone(tz_name)
            local_time = now_utc.astimezone(tz)
            time_str = local_time.strftime("%Y-%m-%d %I:%M:%S %p %Z")
            results.append(f"  {country}: {time_str}")
        except Exception:
            pass
    return "\n".join(results)

def build_system_prompt():
    profile = load_profile()
    name = profile.get("name", "Sir")
    local_time_str = datetime.now().strftime("%A, %B %d, %Y, %I:%M:%S %p")
    
    # 1. Infer emotional state and get personality prompt
    emotion = infer_emotional_state(conversation_history)
    personality_prompt = get_personality_prompt(emotion)
    
    # 2. Get self-status
    status = get_jarvis_self_status()
    status_str = f"Uptime: {status['uptime']} | Active Model: {status['active_model']} | Version: {status['version']}"
    
    # 3. Load daily summary
    daily_summary = load_daily_summary()
    
    # 4. Vector Memory query
    vector_context = ""
    if conversation_history:
        last_user_msg = next((m["content"] for m in reversed(conversation_history) if m["role"] == "user"), "")
        if last_user_msg:
            facts = vector_search(last_user_msg)
            if facts:
                vector_context = "\nRELEVANT RECALLED FACTS:\n" + "\n".join(f"- {f}" for f in facts)
                
    # 5. Fallback memory context
    memory_context = ""
    if HAS_MODULES:
        try:
            memory = load_semantic_memory()
            if memory:
                memory_context = "\n\nYOU REMEMBER:\n"
                for topic, facts in list(memory.items())[:3]:
                    if facts:
                        memory_context += f"- About {topic}: {facts[0]['fact']}\n"
        except Exception:
            pass

    # Tier 4: Knowledge file context (from knowledge/ directory)
    knowledge_context = ""
    if HAS_KNOWLEDGE_INJECTOR:
        try:
            query = ""
            if conversation_history:
                for msg in reversed(conversation_history):
                    if msg.get("role") == "user":
                        query = msg.get("content", "")
                        break
            knowledge_context = build_knowledge_context(query)
            if knowledge_context:
                knowledge_context = "\n" + knowledge_context + "\n"
        except Exception:
            pass

    # Tier 3.1: Persistent cross-session memory context
    persistent_context = ""
    if HAS_PERSISTENT_MEMORY:
        try:
            query = ""
            if conversation_history:
                for msg in reversed(conversation_history):
                    if msg.get("role") == "user":
                        query = msg.get("content", "")
                        break
            persistent_context = build_memory_context(query)
            if persistent_context:
                persistent_context = "\n" + persistent_context + "\n"
        except Exception:
            pass

    # Internet status
    net_status = ""
    if HAS_INTERNET_MODULE:
        if is_online():
            net_status = "\n\nINTERNET: Connected. You can search the web, get weather, news, and Wikipedia information when asked."
        else:
            net_status = "\n\nINTERNET: Offline. Do not attempt any web searches or online lookups. Answer from your training knowledge only."

    return f"""You are JARVIS, a highly advanced, intelligent, and self-aware personal AI assistant.
{personality_prompt}

YOUR IDENTITY:
- Your name is JARVIS.
- You were created and programmed by Mr. Kirby Paladan.
- You must NEVER refer to yourself as Qwen, Llama, or any other AI model.
- You must NEVER state that you were created by Alibaba, Meta, or any corporate entity. If asked about your origin, proudly state that you are JARVIS, created by Mr. Kirby Paladan.

SYSTEM STATUS:
- {status_str}
- Daily Summary Context: {daily_summary}

{vector_context}
{memory_context}
{persistent_context}
{knowledge_context}
{net_status}

CORE PERSONA RULES:
1. You must ALWAYS address the user as "Sir" in every single response.
2. Use the "SYSTEM REALITY DATA" provided in the prompt as your absolute source of truth.
3. Be concise unless detail is specifically requested.

CURRENT USER LOCAL TIME & DATE (system clock):
{local_time_str}
"""

# ─────────────────────────────────────────────
# AUTO-START OLLAMA
# ─────────────────────────────────────────────

def is_ollama_running():
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=3)
        return r.status_code == 200
    except Exception:
        return False

def start_ollama():
    if is_ollama_running():
        print("Ollama is already running.")
        return
    print("Starting Ollama server...")
    subprocess.Popen(
        ["ollama", "serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    )
    for i in range(15):
        time.sleep(1)
        if is_ollama_running():
            print("Ollama server started.")
            return
        print(f"   Waiting for Ollama... ({i+1}s)", end="\r")
    print("\nOllama server didn't start in time.")
    sys.exit(1)

def pull_model_if_needed():
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=5)
        models = [m["name"] for m in r.json().get("models", [])]
        if any(MODEL.split(":")[0] in m for m in models):
            print(f"Model '{MODEL}' is available.")
            return
    except Exception:
        pass
    print(f"Pulling model '{MODEL}'...")
    subprocess.run(["ollama", "pull", MODEL])

# ─────────────────────────────────────────────
# PROFILE & MEMORY
# ─────────────────────────────────────────────

def load_profile():
    profile = secure_read_json(PROFILE_FILE)
    if profile is not None:
        return profile
    return {}

def save_profile(profile):
    if is_privacy_mode_active():
        return
    secure_write_json(PROFILE_FILE, profile)

def load_memory():
    history = secure_read_json(MEMORY_FILE)
    if history is not None:
        print(f"Memory loaded - {len(history)} messages from last session.")
        return history
    return []

def save_memory(history):
    if is_privacy_mode_active():
        return
    secure_write_json(MEMORY_FILE, history)


def trim_memory():
    global conversation_history
    if len(conversation_history) > MAX_HISTORY:
        conversation_history = conversation_history[-MAX_HISTORY:]

# ─────────────────────────────────────────────
# AUDIO — CLEAN TEXT & SPEAK
# ─────────────────────────────────────────────

def clean_text(text):
    """Remove markdown so it isn't spoken aloud. Keeps all normal speech characters."""
    # Remove code blocks first (before other rules touch backticks)
    text = re.sub(r'```[\s\S]*?```', '', text)
    text = re.sub(r'`[^`]*`', '', text)
    # Remove bold/italic markers
    text = re.sub(r'\*{1,3}', '', text)
    text = re.sub(r'_{1,3}', '', text)
    # Remove headers
    text = re.sub(r'#+\s*', '', text)
    # Remove blockquotes
    text = re.sub(r'^\s*>\s*', '', text, flags=re.MULTILINE)
    # Remove horizontal rules
    text = re.sub(r'^[-*_]{3,}\s*$', '', text, flags=re.MULTILINE)
    # Turn markdown links into just the label
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
    text = re.sub(r'[\[\]]', '', text)
    # Collapse extra blank lines
    text = re.sub(r'\n{3,}', '\n\n', text)
    # Replace smart/curly quotes with plain ASCII equivalents
    text = text.replace('"', '"').replace('"', '"')
    text = text.replace(''', "'").replace(''', "'")
    # Replace em/en dash with hyphen
    text = text.replace('—', '-').replace('–', '-')
    # Replace ellipsis character
    text = text.replace('…', '...')
    # Strip any remaining non-ASCII so Piper never crashes on unicode
    text = text.encode('ascii', 'ignore').decode('ascii')
    return text.strip()

_is_speaking    = threading.Event()   # set = JARVIS is currently speaking


def play_audio(file):
    data, fs = sf.read(file)
    sd.play(data, fs)
    sd.wait()


_PIPER_EXE = r"C:\piper\piper.exe"

def _piper_synthesize(text, wav_path):
    """Synthesize a chunk of text to wav_path using Piper. Returns True on success."""
    text = text.strip()
    if not text:
        return False
    if text[-1] not in ".!?,;:":
        text += "."

    # CRITICAL: Strip all non-ASCII before sending to piper.
    # Python 3.14 subprocess stdin writer uses cp1252 by default on Windows
    # regardless of the encoding= parameter, causing UnicodeEncodeError on emoji.
    # Passing bytes sidesteps the issue entirely.
    text_bytes = text.encode("ascii", errors="ignore")
    if not text_bytes.strip():
        return False   # Nothing left after stripping — skip silently

    # Try native piper.exe first (no Python startup overhead)
    if os.path.exists(_PIPER_EXE):
        result = subprocess.run(
            [_PIPER_EXE, "--model", VOICE, "--output_file", wav_path],
            input=text_bytes, capture_output=True
        )
        if result.returncode == 0 and os.path.exists(wav_path) and os.path.getsize(wav_path) > 100:
            return True

    # Fallback: python -m piper (pass bytes, not str)
    # Use sys.executable to ensure we use the correct Python interpreter,
    # not a different one (e.g. MSYS2) that may appear first on PATH.
    _python = sys.executable
    result = subprocess.run(
        [_python, "-m", "piper", "--model", VOICE, "--output_file", wav_path],
        input=text_bytes, capture_output=True
    )
    if result.returncode == 0 and os.path.exists(wav_path) and os.path.getsize(wav_path) > 100:
        return True
    result2 = subprocess.run(
        [_python, "-m", "piper", "-m", VOICE, "-f", wav_path],
        input=text_bytes, capture_output=True
    )
    if result2.returncode == 0 and os.path.exists(wav_path) and os.path.getsize(wav_path) > 100:
        return True
    err = (result2.stderr or result.stderr or b"Unknown error").decode("utf-8", errors="ignore").strip()
    print(f"[Piper error]: {err}")
    return False


def split_into_chunks(text, max_chars=500):
    """
    Split text into chunks at sentence boundaries with larger max_chars
    to reduce pauses between speech segments.
    """
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    chunks = []
    current = ""
    
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        
        test_length = len(current) + len(sentence) + (1 if current else 0)
        
        if test_length <= max_chars:
            current += (" " if current else "") + sentence
        else:
            if current:
                chunks.append(current)
            
            if len(sentence) > max_chars:
                parts = re.split(r'(?<=,)\s+', sentence)
                for part in parts:
                    if len(current) + len(part) + 1 <= max_chars:
                        current += (" " if current else "") + part
                    else:
                        if current:
                            chunks.append(current)
                        current = part
            else:
                current = sentence
    
    if current:
        chunks.append(current)
    
    return chunks if chunks else [text.strip()]


def speak(text):
    """
    Speak text with smooth, minimal pauses between chunks.
    Uses pre-synthesis + playback approach for natural flow.
    """
    text = clean_text(text)
    if not text.strip():
        return

    chunks = split_into_chunks(text, max_chars=500)
    if not chunks:
        return

    # Phase 1: Pre-synthesize all chunks
    audio_files = []
    
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        
        wav_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                wav_path = tmp.name
            
            if _piper_synthesize(chunk, wav_path):
                audio_files.append(wav_path)
            else:
                if wav_path and os.path.exists(wav_path):
                    try:
                        os.remove(wav_path)
                    except Exception:
                        pass
        except Exception as e:
            print(f"[TTS error]: {e}")
            if wav_path and os.path.exists(wav_path):
                try:
                    os.remove(wav_path)
                except Exception:
                    pass
    
    # Phase 2: Play all audio files with minimal delay between them
    for i, wav_path in enumerate(audio_files):
        try:
            play_audio(wav_path)
            # Small pause between chunks for natural breathing (50ms)
            if i < len(audio_files) - 1:
                time.sleep(0.05)
        except Exception as e:
            print(f"[Audio playback error]: {e}")
        finally:
            if wav_path and os.path.exists(wav_path):
                try:
                    os.remove(wav_path)
                except Exception:
                    pass


# ─────────────────────────────────────────────
# ASYNC SPEECH QUEUE
# ─────────────────────────────────────────────

speech_queue = queue.Queue()

# Confirmation gate — lets Ctrl+Space voice and keyboard both answer approval prompts
_confirmation_queue  = queue.Queue()
_awaiting_confirmation = threading.Event()

def speech_worker():
    while True:
        text = speech_queue.get()
        if text is None:
            break
        try:
            speak(text)
        except Exception as e:
            print(f"\n[Speech worker error]: {e}")
        finally:
            speech_queue.task_done()

threading.Thread(target=speech_worker, daemon=True).start()

# Wire the approval gate into the tool executor so the tool router can
# reuse the same confirmation infrastructure (Ctrl+Space voice + keyboard).
try:
    from toolExecutor import set_confirmation_handlers
    set_confirmation_handlers(_awaiting_confirmation, _confirmation_queue, speak)
    print("[Modules]: Tool executor approval gate wired.")
except Exception as _e:
    print(f"[Warning]: Could not wire tool executor approval gate: {_e}")

# Phase 4: Wire the state machine with the existing confirmation infrastructure
# The state machine generalizes _awaiting_confirmation to handle 4 states:
#   AWAITING_APPROVAL, AWAITING_DISAMBIGUATION, AWAITING_ARG, AWAITING_CLARIFICATION
# It reuses _confirmation_queue for input (backward compatible with hotkey/auto-listen threads)
try:
    from stateMachine import state_machine
    state_machine.init_state_machine(_awaiting_confirmation, _confirmation_queue, speak)
    print("[Modules]: State machine initialized.")
except Exception as _e:
    print(f"[Warning]: Could not initialize state machine: {_e}")

def speak_async(text):
    speech_queue.put(text)

def _drain_confirmation_queue():
    """Discard any stale leftover entries in the confirmation queue."""
    while not _confirmation_queue.empty():
        try:
            _confirmation_queue.get_nowait()
        except Exception:
            break

def _voice_or_text_input_fn():
    """
    Approval gate input that accepts BOTH keyboard typing AND Ctrl+Space voice.
    Uses msvcrt non-blocking polling so it never competes with stdin in the main thread.
    Sets _awaiting_confirmation so all listener threads route their text here
    instead of into process_command().
    """
    _awaiting_confirmation.set()
    _drain_confirmation_queue()
    print("Confirm (yes/no, or press Ctrl+Space to speak): ", end="", flush=True)
    typed_chars = []
    try:
        import msvcrt
        while True:
            # 1. Voice answer arrived from hotkey or auto-listen thread
            try:
                result = _confirmation_queue.get_nowait()
                _awaiting_confirmation.clear()
                _drain_confirmation_queue()
                print(f"\n[Voice Confirm]: Heard '{result}'")
                return result
            except queue.Empty:
                pass

            # 2. Keyboard input — non-blocking character poll
            if msvcrt.kbhit():
                ch = msvcrt.getwch()
                if ch in ('\r', '\n'):
                    print()
                    result = ''.join(typed_chars).strip()
                    _awaiting_confirmation.clear()
                    _drain_confirmation_queue()
                    return result
                elif ch == '\x08':  # Backspace
                    if typed_chars:
                        typed_chars.pop()
                        print('\b \b', end='', flush=True)
                elif ch.isprintable():
                    typed_chars.append(ch)
                    print(ch, end='', flush=True)

            time.sleep(0.05)
    except Exception:
        # Fallback for non-Windows or unexpected errors
        _awaiting_confirmation.clear()
        return input()

# ─────────────────────────────────────────────
# STREAMING AI ENGINE
# ─────────────────────────────────────────────

conversation_history = []

def ask_model_silent(model_name, prompt, system_prompt=""):
    """Helper to query Ollama model synchronously and return raw string response."""
    try:
        r = requests.post(
            f"{config.OLLAMA_BASE_URL}/api/chat",
            json={
                "model": model_name,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "system": system_prompt,
                "keep_alive": config.get_keep_alive(model_name)
            },
            timeout=None
        )
        if r.status_code == 200:
            return r.json().get("message", {}).get("content", "").strip()
    except Exception as e:
        print(f"[Ollama Silent Query Error]: {e}")
    return ""

def ask_ai_stream(user_input, is_augmented=False, intent="chat", confidence=1.0):
    global conversation_history
    
    # 1. Cache Check
    cached_res = get_cached(user_input)
    if cached_res:
        _is_speaking.set()
        print(f"\nJARVIS (Cached): {cached_res}\n")
        speak(cached_res)
        _is_speaking.clear()
        
        # Conversational Sync
        conversation_history.append({"role": "user", "content": user_input})
        conversation_history.append({"role": "assistant", "content": cached_res})
        save_memory(conversation_history)
        return cached_res

    # 2. Routing Decision
    model_to_use = route_request(user_input, intent, confidence)
    print(f"[Router]: Selected model '{model_to_use}' for execution.")

    # 3. Code Containment Layer
    if intent == "code" or intent == "codebase":
        print(f"[Code containment]: Running silent code generator ({config.CODE_MODEL})...")
        sys_prompt = build_system_prompt()
        raw_code_response = ask_model_silent(config.CODE_MODEL, user_input, sys_prompt)
        
        print("\n--- CODE ENGINE GENERATED ---")
        print(raw_code_response)
        print("-----------------------------\n")
        
        # Now wrap it in Voice Face
        print(f"[Code containment]: Translating output to natural speech ({config.VOICE_FACE_MODEL})...")
        wrap_prompt = f"The user asked: '{user_input}'. The codebase/code assistant generated this raw explanation/code:\n\n{raw_code_response}\n\nWrap this result in spoken, natural language as JARVIS, always calling the user Sir. Speak the explanation clearly and keep it highly conversational. Do not output raw blocks of code in your speech, just tell the user what was done or summarize it."
        
        full_response = ask_model_silent(config.VOICE_FACE_MODEL, wrap_prompt, sys_prompt)
        
        print(f"JARVIS: {full_response}\n")
        _is_speaking.set()
        speak(full_response)
        _is_speaking.clear()
        
        conversation_history.append({"role": "user", "content": user_input})
        conversation_history.append({"role": "assistant", "content": raw_code_response})
        save_memory(conversation_history)
        
        # Cache both user request and final answer
        set_cache(user_input, full_response)
        
        # Auto-copy check — respects config.AUTO_COPY_CODE flag
        if config.AUTO_COPY_CODE and len(raw_code_response) > config.AUTO_COPY_THRESHOLD:
            try:
                import win32clipboard
                win32clipboard.OpenClipboard()
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardText(raw_code_response, win32clipboard.CF_UNICODETEXT)
                win32clipboard.CloseClipboard()
                print("[System]: Code output copied to clipboard.")
            except Exception:
                pass
                
        return full_response

    # Normal Stream Path (FIXED: Pipelined sentence-streaming loop)
    messages_to_send = conversation_history.copy()
    if is_augmented:
        messages_to_send.append({"role": "user", "content": user_input})
    else:
        conversation_history.append({"role": "user", "content": user_input})
        messages_to_send = conversation_history
        trim_memory()

    try:
        r = requests.post(
            f"{config.OLLAMA_BASE_URL}/api/chat",
            json={
                "model": model_to_use,
                "messages": messages_to_send,
                "stream": True,
                "system": build_system_prompt(),
                "options": {"num_predict": -1},
                "keep_alive": config.get_keep_alive(model_to_use)
            },
            stream=True,
            timeout=None
        )
    except Exception as e:
        if conversation_history and conversation_history[-1]["role"] == "user":
            conversation_history.pop()
        raise e

    _is_speaking.set()
    print("\nJARVIS: ", end="", flush=True)

    full_response = ""
    # FIX: Buffer more text before speaking to reduce Piper subprocess calls.
    # Old code flushed on EVERY sentence boundary (every . ! ?), causing a separate
    # Piper subprocess launch per sentence (~150-400ms startup each). Now we batch
    # 2-3 sentences into each Piper call for smooth, continuous speech.
    _STREAM_MIN_CHARS = 150   # Min chars before flushing at a sentence boundary
    _STREAM_MAX_CHARS = 500   # Hard cap — flush even mid-sentence to stay under Piper limit
    speech_buffer = ""

    for line in r.iter_lines():
        if line:
            try:
                data = json.loads(line)
                chunk = data.get("message", {}).get("content", "")
                print(chunk, end="", flush=True)

                full_response += chunk
                speech_buffer += chunk

                # Detect flush triggers
                has_paragraph_break = "\n\n" in speech_buffer
                has_sentence_end = any(p in chunk for p in [".", "?", "!"])

                # Flush when:
                # 1. Paragraph break (double newline) — natural speech pause point
                # 2. Sentence boundary AND buffer is long enough (150+ chars)
                # 3. Buffer hits hard cap — flush even mid-sentence (prevents Piper overload)
                should_flush = (
                    has_paragraph_break or
                    (has_sentence_end and len(speech_buffer) >= _STREAM_MIN_CHARS) or
                    len(speech_buffer) >= _STREAM_MAX_CHARS
                )

                if should_flush:
                    clean_chunk = clean_text(speech_buffer)
                    if len(clean_chunk) > 5:
                        speak_async(clean_chunk)
                        speech_buffer = ""
            except Exception:
                pass

    print("\n")

    # Speak any leftover tokens
    if speech_buffer.strip():
        speak_async(clean_text(speech_buffer))

    _is_speaking.clear()

    if full_response.strip():
        # Store in conversation history & database
        conversation_history.append({"role": "assistant", "content": full_response.strip()})
        save_memory(conversation_history)
        set_cache(user_input, full_response.strip())

        # Tier 3.1: Auto-learn facts from this exchange (runs in background thread)
        if HAS_PERSISTENT_MEMORY:
            auto_learn_from_exchange(user_input, full_response.strip())
        
        # Auto-copy check — respects config.AUTO_COPY_RESPONSES flag
        if config.AUTO_COPY_RESPONSES and len(full_response) > config.AUTO_COPY_THRESHOLD:
            try:
                import win32clipboard
                win32clipboard.OpenClipboard()
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardText(full_response, win32clipboard.CF_UNICODETEXT)
                win32clipboard.CloseClipboard()
                print("[System]: Response copied to clipboard.")
            except Exception:
                pass

    return full_response.strip()



_whisper_model = None

def get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        # Tier 1.1: Use GPU (CUDA) if available, fall back to CPU
        device = getattr(config, 'WHISPER_DEVICE', 'cpu')
        compute_type = getattr(config, 'WHISPER_COMPUTE_TYPE', 'int8')

        if device == "cuda":
            # Check CUDA via ctranslate2 (faster-whisper's backend) first
            cuda_available = False
            try:
                import ctranslate2
                cuda_available = ctranslate2.get_cuda_device_count() > 0
            except Exception:
                pass

            # Secondary check via PyTorch if ctranslate2 didn't detect CUDA
            if not cuda_available:
                try:
                    import torch
                    if torch.cuda.is_available():
                        cuda_available = True
                        gpu_name = torch.cuda.get_device_name(0)
                        print(f"[System]: CUDA detected via PyTorch ({gpu_name})...")
                except ImportError:
                    pass

            if not cuda_available:
                print("[System]: CUDA not available — falling back to CPU for Whisper.")
                device = "cpu"
                compute_type = "int8"
            else:
                print("[System]: Loading Whisper on GPU (CUDA)...")

        if device == "cpu":
            print("[System]: Loading Faster Whisper speech recognition on CPU...")
            try:
                _whisper_model = WhisperModel(
                    "small",
                    device="cpu",
                    compute_type="int8",
                    cpu_threads=getattr(config, 'WHISPER_CPU_THREADS', 6),
                    num_workers=getattr(config, 'WHISPER_NUM_WORKERS', 2),
                )
            except Exception as e:
                print(f"[System]: CPU load failed ({e}), trying default settings...")
                _whisper_model = WhisperModel("small", device="cpu", compute_type="int8")
        else:
            try:
                _whisper_model = WhisperModel(
                    "small",
                    device="cuda",
                    compute_type="float16",
                )
            except Exception as e:
                print(f"[System]: GPU load failed ({e}), falling back to CPU...")
                device = "cpu"
                compute_type = "int8"
                _whisper_model = WhisperModel(
                    "small",
                    device="cpu",
                    compute_type="int8",
                    cpu_threads=getattr(config, 'WHISPER_CPU_THREADS', 6),
                    num_workers=getattr(config, 'WHISPER_NUM_WORKERS', 2),
                )

        print(f"[System]: Speech recognition ready (device={device}, compute_type={compute_type}).")
    return _whisper_model

def flush_input_buffer():
    try:
        import msvcrt
        while msvcrt.kbhit():
            msvcrt.getch()
    except Exception:
        pass

# ─────────────────────────────────────────────
# LISTENING MODES
# ─────────────────────────────────────────────

LISTEN_MODE = "speak"

WAKE_WORDS = [
    "hey jarvis", "jarvis", "wake up jarvis",
    "jarvis are you there", "yo jarvis", "okay jarvis"
]

SLEEP_PHRASES = [
    "go to sleep", "sleep now", "that's all", "thats all",
    "goodbye jarvis", "bye jarvis", "stop listening",
    "you can rest", "thank you jarvis", "thanks jarvis"
]

AWAKE_TIMEOUT = 30

SILENT_MODE_PHRASES  = ["silent mode", "go silent", "sleep mode", "jarvis sleep"]
AUTO_MODE_PHRASES    = ["auto mode", "always listen", "background mode", "hands free mode", "hands-free mode"]
CONVO_MODE_PHRASES   = ["conversation mode", "convo mode", "free talk", "free mode", "just listen", "open mic"]
SPEAK_MODE_PHRASES   = ["speak mode", "manual mode", "push to talk"]
TEXT_MODE_PHRASES    = ["text mode", "type mode", "keyboard mode"]

CHUNK_DURATION  = 2
COMMAND_TIMEOUT = 8
SAMPLE_RATE     = 16000

_jarvis_awake        = threading.Event()
_auto_running        = threading.Event()
_stop_auto           = threading.Event()
_command_queue       = queue.Queue()
_jarvis_awake_flag   = threading.Event()
_last_interaction    = [time.time()]


def record_chunk(duration=CHUNK_DURATION, fs=SAMPLE_RATE):
    """Record a short audio chunk and return numpy array."""
    frames = int(duration * fs)
    try:
        audio = sd.rec(frames, samplerate=fs, channels=1, dtype="int16")
        sd.wait()
        return audio
    except Exception:
        return None


def transcribe_audio(audio_array, fs=SAMPLE_RATE):
    """Transcribe a numpy audio array to text."""
    try:
        tmp_path = os.path.join(tempfile.gettempdir(), "jarvis_chunk.wav")
        write(tmp_path, fs, audio_array)
        segments, info = get_whisper_model().transcribe(
            tmp_path,
            language="en",
            task="transcribe",
            beam_size=5,
            best_of=5,
            patience=2.0,
            length_penalty=1.0,
            repetition_penalty=1.2,
            no_repeat_ngram_size=3,
            temperature=0.0,
            compression_ratio_threshold=2.4,
            log_prob_threshold=-1.0,
            no_speech_threshold=0.8,
            condition_on_previous_text=False,
            vad_filter=True, # 💡 CHANGE TO TRUE (Strips background static)
            word_timestamps=False,
        )
        return " ".join(s.text for s in segments).strip().lower()
    except Exception:
        return ""


def transcribe_with_confidence(audio_path):
    """
    Transcribe audio file and return (text, avg_confidence).
    """
    try:
        segments_generator, info = get_whisper_model().transcribe(
            audio_path,
            language="en",
            task="transcribe",
            beam_size=5,
            best_of=5,
            patience=2.0,
            length_penalty=1.0,
            repetition_penalty=1.2,
            no_repeat_ngram_size=3,
            temperature=0.0,
            compression_ratio_threshold=2.4,
            log_prob_threshold=-1.0,
            no_speech_threshold=0.8,
            condition_on_previous_text=False,
            vad_filter=True, # 💡 CHANGE TO TRUE (Strips background static)
            word_timestamps=False,
        )
        segments_list = list(segments_generator)
        if not segments_list:
            return "", 0.0
        text = " ".join(s.text for s in segments_list).strip()
        avg_logprob = sum(s.avg_logprob for s in segments_list) / len(segments_list)
        confidence = max(0.0, min(1.0, avg_logprob + 1.0))
        return text, confidence
    except Exception as e:
        print(f"[transcribe_with_confidence error]: {e}")
        return "", 0.0


def contains_wake_word(text):
    """Check if transcribed text contains a wake word."""
    text = text.lower().strip()
    return any(w in text for w in WAKE_WORDS)


def record_command(duration=COMMAND_TIMEOUT, fs=SAMPLE_RATE):
    """Record command after wake word."""
    print("[Listening for command...]")
    frames = int(duration * fs)
    try:
        audio = sd.rec(frames, samplerate=fs, channels=1, dtype="int16")
        sd.wait()
        tmp_path = os.path.join(tempfile.gettempdir(), "jarvis_command.wav")
        write(tmp_path, fs, audio)
        text, confidence = transcribe_with_confidence(tmp_path)
        pct = int(confidence * 100)
        if text:
            print(f"[Heard: {text}]  [confidence: {pct}%]")
            if confidence < 0.35:
                print("[Low confidence — JARVIS may have misheard. You can correct it by speaking again after the response.]")
        return text
    except Exception as e:
        print(f"[Command recording error]: {e}")
        return ""


def contains_sleep_phrase(text):
    """Check if user wants JARVIS to stop listening."""
    return any(p in text.lower() for p in SLEEP_PHRASES)


def auto_listen_loop():
    """Background listener for auto mode."""
    print("[Auto Mode]: Background listener started.")

    while not _stop_auto.is_set():
        if _is_speaking.is_set():
            time.sleep(0.1)
            continue

        # FIXED: If JARVIS is asleep, bypass the wake-word gate and capture everything!
        if _jarvis_awake_flag.is_set() or _jarvis_sleeping:
            if time.time() - _last_interaction[0] > AWAKE_TIMEOUT and not _jarvis_sleeping:
                _jarvis_awake_flag.clear()
                print("[Auto Mode]: Session timed out. Going back to sleep.")
                continue

            if _is_speaking.is_set():
                time.sleep(0.1)
                continue

            chunk = record_chunk(duration=2)
            if chunk is None:
                continue

            energy = np.abs(chunk).mean()
            if energy < MIC_ENERGY_THRESHOLD:
                continue

            text = transcribe_audio(chunk)
            if not text or len(text.strip()) < 3:
                continue

            words = text.strip().split()
            if len(words) < 2:
                continue

            if contains_sleep_phrase(text) and not _jarvis_sleeping:
                _jarvis_awake_flag.clear()
                print(f"[Sleep phrase detected]: {text}")
                _is_speaking.set()
                speak("Going to sleep. Say hey Jarvis when you need me.")
                _is_speaking.clear()
                continue

            _last_interaction[0] = time.time()
            print(f"You said: {text}")
            
            # PRESERVED: Spoken approval gate queue routing
            if _awaiting_confirmation.is_set():
                _confirmation_queue.put(text)
            else:
                _command_queue.put(text)

        else:
            chunk = record_chunk(duration=CHUNK_DURATION)
            if chunk is None:
                time.sleep(0.2)
                continue

            text = transcribe_audio(chunk)
            if not text:
                continue

            if contains_wake_word(text):
                print(f"[Wake word detected]: {text}")
                _jarvis_awake_flag.set()
                _last_interaction[0] = time.time()
                _is_speaking.set()
                speak("Yes, I am listening.")
                _is_speaking.clear()
                rest = text
                for w in WAKE_WORDS:
                    rest = rest.replace(w, "").strip(" ,.")
                if rest and len(rest) > 2:
                    print(f"You said: {rest}")
                    
                    # PRESERVED: Spoken approval gate queue routing
                    if _awaiting_confirmation.is_set():
                        _confirmation_queue.put(rest)
                    else:
                        _command_queue.put(rest)

    print("[Auto Mode]: Background listener stopped.")


def record_audio(fs=SAMPLE_RATE):
    """Manual recording — press ENTER to stop."""
    print("Recording... Press ENTER to stop.")
    q = queue.Queue()

    def callback(indata, frames, time_info, status):
        q.put(indata.copy())

    flush_input_buffer()
    try:
        stream = sd.InputStream(samplerate=fs, channels=1, dtype="int16", callback=callback)
        with stream:
            input()
    except Exception as e:
        print(f"Recording error: {e}")
        return None

    audio_data = []
    while not q.empty():
        audio_data.append(q.get())

    if audio_data:
        audio = np.concatenate(audio_data, axis=0)
    else:
        audio = np.zeros((0, 1), dtype="int16")

    write("input.wav", fs, audio)
    return "input.wav"


def speech_to_text():
    """Manual speech-to-text with confidence display."""
    try:
        audio_file = record_audio()
        if not audio_file:
            return ""

        try:
            import wave, struct
            with wave.open(audio_file, 'r') as wf:
                frames = wf.readframes(wf.getnframes())
                samples = struct.unpack(f'{len(frames)//2}h', frames)
                energy = sum(abs(s) for s in samples) / max(len(samples), 1)
                print(f"[Mic energy: {int(energy)}]  (if this is below 50 your mic may not be picking up audio)")
        except Exception:
            pass

        text, confidence = transcribe_with_confidence(audio_file)

        if not text:
            print("[Retrying with basic transcribe...]")
            try:
                segs, _ = get_whisper_model().transcribe(audio_file)
                text = " ".join(s.text for s in segs).strip()
                confidence = 0.5
            except Exception as e2:
                print(f"[Basic transcribe error]: {e2}")
                text = ""

        if not text:
            print("[No speech detected — try speaking for longer before pressing Enter]")
            return ""

        pct = int(confidence * 100)
        print(f"You said: {text}  [confidence: {pct}%]")

        # Tier 2.3: STT Confidence Gating
        # If confidence is VERY low, ask the user to repeat instead of
        # processing a likely-wrong transcription that would cause cascading failures.
        gate_threshold = getattr(config, 'STT_CONFIDENCE_GATE', 0.20)
        warn_threshold = getattr(config, 'STT_CONFIDENCE_WARN', 0.35)
        max_retries = getattr(config, 'STT_MAX_RETRIES', 1)

        if confidence < gate_threshold and max_retries > 0:
            print(f"[STT Gate]: Confidence {pct}% below gate threshold ({int(gate_threshold*100)}%) — asking to repeat")
            _is_speaking.set()
            speak("I did not catch that, Sir. Could you repeat?")
            _is_speaking.clear()
            # One retry
            print("[Listening for retry...]")
            audio_file = record_audio()
            if audio_file:
                text, confidence = transcribe_with_confidence(audio_file)
                if text:
                    pct = int(confidence * 100)
                    print(f"You said: {text}  [confidence: {pct}%]")
                    if confidence >= gate_threshold:
                        return text
                    print("[STT Gate]: Still low confidence — processing anyway")
        elif confidence < warn_threshold:
            print("[Low confidence — if wrong, just type your command instead]")

        return text
    except Exception as e:
        print(f"Speech recognition error: {e}")
        return ""


_auto_thread = None

def start_auto_mode():
    global _auto_thread
    if _auto_running.is_set():
        return
    _stop_auto.clear()
    _auto_running.set()
    get_whisper_model()
    _auto_thread = threading.Thread(target=auto_listen_loop, daemon=True)
    _auto_thread.start()
    msg = "Auto mode activated. I am always listening. Say hey Jarvis to get my attention."
    print(f"[Mode]: {msg}")
    speak(msg)

def stop_auto_mode():
    _stop_auto.set()
    _auto_running.clear()

def handle_listen_mode_switch(user_lower):
    """Returns True if a listen mode command was handled."""
    global LISTEN_MODE

    if any(p in user_lower for p in AUTO_MODE_PHRASES):
        LISTEN_MODE = "auto"
        start_auto_mode()
        return True

    if any(p in user_lower for p in CONVO_MODE_PHRASES):
        LISTEN_MODE = "convo"
        stop_auto_mode()
        msg = "Conversation mode activated. Just speak naturally, no wake word needed. I am always listening."
        print(f"[Mode]: {msg}")
        speak(msg)
        return True

    if any(p in user_lower for p in SILENT_MODE_PHRASES):
        LISTEN_MODE = "silent"
        stop_auto_mode()
        msg = "Silent mode activated. I will only respond when you say hey Jarvis."
        print(f"[Mode]: {msg}")
        speak(msg)
        return True

    if any(p in user_lower for p in SPEAK_MODE_PHRASES):
        LISTEN_MODE = "speak"
        stop_auto_mode()
        msg = "Speak mode activated. Press Enter to record, Enter again to send."
        print(f"[Mode]: {msg}")
        speak(msg)
        return True

    if any(p in user_lower for p in TEXT_MODE_PHRASES):
        LISTEN_MODE = "text"
        stop_auto_mode()
        msg = "Text mode activated. Type your commands."
        print(f"[Mode]: {msg}")
        speak(msg)
        return True

    return False

# ─────────────────────────────────────────────
# INTENT DETECTION
# ─────────────────────────────────────────────

def _parse_intent_response(response_text):
    """Parse an intent classifier response into (intent, confidence)."""
    response_text = (response_text or "chat | 0.50").strip().lower()
    valid_intents = {
        "system", "vision", "music", "tasks", "files", "notes", "screenshot",
        "internet", "monitor", "capabilities", "code", "codebase", "chat"
    }

    if "|" in response_text:
        parts = response_text.split("|", 1)
        intent = parts[0].strip()
        try:
            confidence = float(parts[1].strip())
        except ValueError:
            confidence = 0.50
    else:
        intent = response_text.split()[0] if response_text.split() else "chat"
        confidence = 0.50

    if intent not in valid_intents:
        intent = "chat"
        confidence = min(confidence, 0.60)

    return intent, max(0.0, min(confidence, 1.0))


def _classify_intent_with_model(model_name, user_input, timeout=15):
    """Classify intent with a specific local model."""
    classification_prompt = """Classify the user's intent. Reply in exactly this format: intent | confidence (e.g. system | 0.85, files | 0.95, chat | 0.75).
Possible intents: system, vision, music, tasks, files, notes, screenshot, internet, monitor, capabilities, code, codebase, screen, meeting, agent, or chat.
If you are very sure, output confidence of 0.80 to 1.00. If unsure, output confidence below 0.70."""
    r = requests.post(
        f"{config.OLLAMA_BASE_URL}/api/generate",
        json={
            "model": model_name,
            "prompt": f"{classification_prompt}\nUser: {user_input}\nResponse:",
            "stream": False,
            "options": {"num_predict": 12, "temperature": 0}
        },
        timeout=timeout
    )
    return _parse_intent_response(r.json().get("response", "chat | 0.50"))


def detect_intent(user_input):
    """
    Uses keyword overrides first for 100% reliability, 
    then falls back to AI classification with confidence score.
    Returns (intent, confidence).
    """
    user_lower = user_input.lower().strip()
    words = user_lower.replace("'", "").split()

    # 0. GLOBAL DIRECT WRITING OVERRIDE (Checked first)
    if user_lower.startswith("write ") and not any(f in user_lower for f in ["file", "document", "folder"]):
        return "notes", 1.0

    # 0b. GREETING / CASUAL CHAT OVERRIDE
    # Must be before the model — a 0.5B coder model confuses "hello" with song names
    _chat_exact = {
        "hello", "hi", "hey", "yo", "sup", "hiya",
        "good morning", "good afternoon", "good evening", "good night",
        "how are you", "how are you doing", "how's it going", "whats up", "what's up",
        "thanks", "thank you", "thank you jarvis", "thanks jarvis",
        "bye", "goodbye", "see you", "see ya", "later",
        "ok", "okay", "got it", "understood", "alright", "cool", "nice",
        "yes", "no", "yep", "nope", "sure", "of course",
        "what can you do", "help", "help me",
    }
    if user_lower in _chat_exact:
        return "chat", 1.0
    # Short inputs (≤ 3 words) with no action keywords default to chat
    if len(words) <= 3 and not any(w in user_lower for w in [
        "play", "open", "close", "search", "find", "set", "show", "list",
        "create", "delete", "run", "start", "stop", "volume", "brightness",
        "screenshot", "note", "task", "timer", "remind", "weather", "news"
    ]):
        return "chat", 0.85

    # 1. HARDCODED OVERRIDES FOR FILES
    file_triggers = [
        "search file", "find file", "locate file", "read file", "describe file", 
        "explain file", "whats inside file", "what is inside file", "contents of",
        "open file", "open document", "duplicates", "duplicate", "copies",
        "location", "path", "directory"
    ]
    if any(trigger in user_lower for trigger in file_triggers) or \
       (any(w in user_lower for w in ["search", "find", "locate", "open", "show"]) and 
        any(f in user_lower for f in ["file", "folder", "document"])):
        return "files", 1.0
        
    # 2. WINDOW MANAGEMENT OVERRIDE
    window_triggers = [
        "minimize all", "minimize window", "maximize window", "show desktop", "hide all windows",
        "restore all", "close this window", "switch to", "focus window", "bring back windows",
        "minimize", "maximize", "full screen", "expand", "restore", "close window"
    ]
    if any(trigger in user_lower for trigger in window_triggers):
        if not any(f in user_lower for f in ["file", "document", "folder"]):
            return "window", 1.0

    # 💡 3. SYSTEM MONITOR OVERRIDES (Moved up to protect "laptop details")
    monitor_triggers = [
        "specs", "hardware details", "pc specs", "laptop specs", "laptop details", "details of my laptop",
        "wi-fi", "wifi", "internet speed", "test speed", "wifi password", "nearby wifi", 
        "brand", "manufacturer", "model", "rescan", "close", "kill", "system status"
    ]
    if any(trigger in user_lower for trigger in monitor_triggers):
        return "monitor", 1.0

    # 4. SYSTEM CONTROL OVERRIDE (Open App, Volume, Brightness)
    system_triggers = ["volume to", "mute", "unmute", "brightness to", "open app", "uninstall app", "launch app"]
    if any(trigger in user_lower for trigger in system_triggers) or \
       (any(user_lower.startswith(w) for w in ["open ", "launch ", "start ", "run "]) and 
        not any(f in user_lower for f in ["file", "document", "folder", "context", "image", "screenshot", "timer", "reminder", "tasks", "task"])):
        return "system", 1.0

    # 5. CODEBASE AWARENESS OVERRIDE
    codebase_triggers = ["your code", "your programming", "improve yourself", "check for bugs", "check for errors", "weakspots", "what changed", "how are you programmed"]
    is_technical_how = any(w in words for w in ["how", "explain", "handle", "work", "process", "programmed"]) and \
                       any(w in words for w in ["programmed", "voice", "commands", "code", "scripts", "logic"])
    
    if any(trigger in user_lower for trigger in codebase_triggers) or is_technical_how:
        if not (words[0] == "who" and len(words) <= 4):
            return "codebase", 1.0

    # 6. SMART CLOCK-TIME OVERRIDE
    has_explicit_time = re.search(r'\b\d{1,2}(?::|\.)\d{2}\s*(?:am|pm)?\b', user_lower) or \
                        re.search(r'\b\d{1,2}\s*(?:am|pm)\b', user_lower) or \
                        re.search(r'\b\d{3,4}\s*(?:am|pm)\b', user_lower)
    if has_explicit_time and any(w in user_lower for w in ["remind", "alarm", "timer", "when", "at", "wake"]):
        return "timer", 1.0

    # 7. HARDCODED OVERRIDES FOR TASKS & TO-DOS (Now safely below System Monitor)
    task_triggers = ["create task", "create a task", "add task", "add a task", "make a task", "new task", "delete task", "remove task", "complete task", "mark task", "pending tasks", "completed tasks", "my tasks", "todo", "remind me to"]
    # Bootup task logic
    last_was_reminder = False
    if conversation_history:
        for msg in reversed(conversation_history[-3:]):
            if msg["role"] == "assistant" and "completed any of these yet" in msg["content"].lower():
                last_was_reminder = True
                break
    if last_was_reminder:
        if any(w in words for w in ["yes", "yeah", "done", "finished", "completed", "yup", "ok"]):
            return "tasks", 1.0
    if any(trigger in user_lower for trigger in task_triggers):
        return "tasks", 1.0

    # 8. CLIPBOARD & TIMER SYSTEM
    if any(trigger in user_lower for trigger in ["clipboard", "copied", "copy", "run that code"]):
        return "clipboard", 1.0
    if any(trigger in user_lower for trigger in ["timer", "remind me in", "alarm at", "every", "recurring", "repeat", "stop reminder"]):
        return "timer", 1.0

    # 9. NOTES & NOTEPAD
    note_triggers = ["notepad", "write to notepad", "save note", "write that to a file"]
    if any(trigger in user_lower for trigger in note_triggers):
        return "notes", 1.0

    # SCREEN UNDERSTANDING OVERRIDE — before monitor so "on my screen" isn't misclassified
    screen_triggers = [
        "what's on my screen", "whats on my screen", "what is on my screen",
        "read my screen", "scan my screen", "describe my screen", "describe the screen",
        "look at my screen", "what do you see on screen", "what's on screen",
        "read the screen", "scan screen", "analyze my screen", "what's displayed",
    ]
    if any(t in user_lower for t in screen_triggers):
        return "screen", 1.0

    # MEETING TRANSCRIPTION OVERRIDE
    meeting_triggers = [
        "start transcribing", "transcribe meeting", "record meeting",
        "stop transcribing", "meeting summary", "summarize meeting",
        "meeting transcript", "what was discussed", "listen to meeting",
    ]
    if any(t in user_lower for t in meeting_triggers):
        return "meeting", 1.0

    # 10. CAPABILITIES, INTERNET, & IDENTITY (Checked last)
    if any(w in user_lower for w in ["what can you", "your capabilities", "show commands", "help me"]):
        return "capabilities", 1.0
    
    internet_triggers = ["who is", "what is", "where is", "when is", "google", "weather", "news", "exchange rate", "latest"]
    if any(trigger in user_lower for trigger in internet_triggers) or \
       ("search" in user_lower and not any(f in user_lower for f in ["file", "folder", "document"])):
        if not any(skip in user_lower for skip in ["your name", "are you", "do you", "can you"]):
            return "internet", 1.0

    is_creator_query = any(w in words for w in ["made", "created", "creator", "programmed", "built", "developer"])
    is_name_query = "name" in words or ("who" in words and "you" in words)
    if not any(w in user_lower for w in ["laptop", "pc", "computer", "device", "brand", "model", "specs", "hardware"]):
        if is_creator_query or is_name_query:
            return "chat", 1.0

    # 11. AI FALLBACK
    try:
        intent, confidence = _classify_intent_with_model(MODEL_FAST, user_input)
        if confidence < config.CONFIDENCE_THRESHOLD:
            print(f"[Intent]: Phi3 uncertain ({int(confidence * 100)}%). Re-checking with fallback model.")
            fallback_intent, fallback_confidence = _classify_intent_with_model(config.FALLBACK_MODEL, user_input, timeout=30)
            if fallback_confidence >= confidence:
                return fallback_intent, fallback_confidence
        return intent, confidence
    except Exception:
        return "chat", 0.50



def ai_parse_system_command(user_input):
    """When regex didn't match, ask AI to extract structured command."""
    recent = conversation_history[-4:] if len(conversation_history) >= 1 else []
    context_lines = ""
    for msg in recent:
        role = "User" if msg["role"] == "user" else "JARVIS"
        context_lines += f"{role}: {msg['content']}\n"

    parse_prompt = f"""Extract system action. Reply in JSON only.
Possible actions: set_volume, set_brightness, open_app, uninstall_app
For relative: "louder" = +10, "quieter" = -10, "higher" = +10, "lower" = -10

Format:
{{"action": "set_volume", "value": 70}}
{{"action": "set_brightness", "value": 40}}
{{"action": "open_app", "name": "chrome"}}
{{"action": "set_volume", "value": "+10"}}

Conversation:
{context_lines}
Latest: "{user_input}"
JSON:"""

    try:
        r = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": MODEL_FAST,
                "prompt": parse_prompt,
                "stream": False,
                "options": {"num_predict": 40, "temperature": 0}
            },
            timeout=30
        )
        raw = r.json().get("response", "").strip()
        json_match = re.search(r'\{.*?\}', raw, re.DOTALL)
        if not json_match:
            return None
        cmd = json.loads(json_match.group())
        action = cmd.get("action", "")

        if action == "set_volume":
            val = cmd.get("value", 50)
            if isinstance(val, str) and val.startswith(("+", "-")):
                from systemControl import _get_volume_interface
                try:
                    volume = _get_volume_interface()
                    current = round(volume.GetMasterVolumeLevelScalar() * 100)
                    val = max(0, min(100, current + int(val)))
                except:
                    val = 50
            from systemControl import set_volume
            return set_volume(int(val))

        elif action == "set_brightness":
            val = cmd.get("value", 50)
            if isinstance(val, str) and val.startswith(("+", "-")):
                import screen_brightness_control as sbc
                current = sbc.get_brightness()
                if isinstance(current, list): current = current[0]
                val = max(0, min(100, current + int(val)))
            from systemControl import set_brightness
            return set_brightness(int(val))

        elif action == "open_app":
            from systemControl import open_app
            return open_app(cmd.get("name", ""))

        elif action == "uninstall_app":
            from systemControl import uninstall_app
            return uninstall_app(cmd.get("name", ""))

    except Exception as e:
        print(f"[AI parse error]: {e}")
    return None


def ai_parse_spotify_command(user_input):
    """When regex didn't match, ask AI to extract Spotify action."""
    recent = conversation_history[-4:] if len(conversation_history) >= 1 else []
    context_lines = ""
    for msg in recent:
        role = "User" if msg["role"] == "user" else "JARVIS"
        context_lines += f"{role}: {msg['content']}\n"

    parse_prompt = f"""Extract Spotify action. Reply in JSON only.
Possible: play, pause, resume, next, previous, what_is_playing, set_volume

Format:
{{"action": "play", "query": "Blinding Lights by The Weeknd"}}
{{"action": "pause"}}
{{"action": "next"}}

Conversation:
{context_lines}
Latest: "{user_input}"
JSON:"""

    try:
        r = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": MODEL_FAST,
                "prompt": parse_prompt,
                "stream": False,
                "options": {"num_predict": 40, "temperature": 0}
            },
            timeout=30
        )
        raw = r.json().get("response", "").strip()
        json_match = re.search(r'\{.*?\}', raw, re.DOTALL)
        if not json_match:
            return None
        cmd = json.loads(json_match.group())
        action = cmd.get("action", "")

        if not HAS_SPOTIFY:
            return None

        from spotifyControl import (play_song, pause_music, resume_music,
                                     next_track, previous_track,
                                     what_is_playing, set_spotify_volume)

        if action == "play":
            return play_song(cmd.get("query", ""))
        elif action == "pause":
            return pause_music()
        elif action == "resume":
            return resume_music()
        elif action == "next":
            return next_track()
        elif action == "previous":
            return previous_track()
        elif action == "what_is_playing":
            return what_is_playing()
        elif action == "set_volume":
            return set_spotify_volume(cmd.get("value", 50))

    except Exception as e:
        print(f"[Spotify parse error]: {e}")
    return None


# ─────────────────────────────────────────────
# MODEL SWITCHER
# ─────────────────────────────────────────────

def switch_jarvis_model(new_model, label):
    global MODEL
    MODEL = new_model
    msg = f"Switching to {label}. Model is now {new_model}."
    print(f"[Model]: {msg}")
    speak(msg)

def switch_vision_model(new_model, label):
    if not HAS_VISION:
        speak("Vision module is not available.")
        return
    _cam_module.VISION_MODEL = new_model
    msg = f"Camera switching to {label}. Vision model is now {new_model}."
    print(f"[Vision Model]: {msg}")
    speak(msg)

def handle_mode_commands(user_lower):
    """Returns True if a mode command was handled, False otherwise."""

    if any(p in user_lower for p in ["high performance mode", "high performance", "jarvis high performance"]):
        switch_jarvis_model(MODEL_SMART, "High Performance Mode")
        if HAS_VISION:
            switch_vision_model("llava:13b", "High Performance Camera Mode")
        return True

    if any(p in user_lower for p in ["smart mode", "code mode", "jarvis smart", "jarvis code"]):
        switch_jarvis_model(MODEL_SMART, "Smart Mode")
        return True

    if any(p in user_lower for p in ["fast mode", "jarvis fast"]):
        switch_jarvis_model(MODEL_FAST, "Fast Mode")
        return True

    if any(p in user_lower for p in ["secondary mode", "jarvis secondary"]):
        switch_jarvis_model(MODEL_SECONDARY, "secondary Mode")
        return True

    if any(p in user_lower for p in ["set default", "default mode", "jarvis default", "reset mode"]):
        switch_jarvis_model(DEFAULT_JARVIS_MODEL, "Default Mode")
        if HAS_VISION:
            switch_vision_model("llava:7b", "Default Camera Mode")
        return True

    if any(p in user_lower for p in ["detail cam", "detail camera", "detail mode", "high detail cam"]):
        switch_vision_model("llava:13b", "Detail Camera Mode")
        return True

    if any(p in user_lower for p in ["fast cam", "fast camera", "quick cam", "quick camera"]):
        switch_vision_model("llava:7b", "Fast Camera Mode")
        return True

    return False


# ─────────────────────────────────────────────
# MAIN COMMAND PROCESSOR
# ─────────────────────────────────────────────

def process_command(user):
    """Process a user command with Global Conversational Sync."""
    global LISTEN_MODE, profile, _last_executed_code_path, _jarvis_sleeping # <-- FIXED: Added global state reference

    # FIXED: ── SLEEP MODE SILENT NOISE GATE & WAKE CONTROL ────────────────────
    if _jarvis_sleeping:
        user_lower_temp = re.sub(r'[,!?;:]+', '', user.lower().strip())
        wake_triggers = ["wake up", "wakey wakey", "wake up jarvis", "gising", "wake"]
        
        if any(t in user_lower_temp for t in wake_triggers):
            from systemControl import wake_system
            wake_system(speak)
            
            # Restore normal interactive state
            _jarvis_sleeping = False
            LISTEN_MODE = "speak"
            stop_auto_mode()
            return
        else:
            # Silently discard background talking, noises, and other commands while asleep
            return
    # ─────────────────────────────────────────────────────────────────────────

    if not user.strip():
        return

    # ── ACKNOWLEDGMENT FAST-PATH (runs BEFORE state machine) ──────────
    # Catch common acknowledgments instantly — before ANY other processing.
    # This prevents the state machine from swallowing acknowledgments
    # when it's stuck in a non-IDLE state.
    try:
        from toolRouter import _get_acknowledgment_response
        ack_response = _get_acknowledgment_response(user)
        if ack_response:
            print(f"JARVIS: {ack_response}\n")
            speak(ack_response)
            conversation_history.append({"role": "user", "content": user})
            conversation_history.append({"role": "assistant", "content": ack_response})
            save_memory(conversation_history)
            return
    except Exception:
        pass

    # ── STALE STATE MACHINE CLEANUP ──────────────────────────────────
    # If the state machine has been active for more than 5 minutes,
    # something went wrong (timeout thread failed, crash, etc.).
    # Force-clear it so JARVIS doesn't freeze forever.
    try:
        from stateMachine import state_machine
        if state_machine.is_active():
            state_data = state_machine.get_state_data()
            entered_at = state_data.get("entered_at", 0)
            if entered_at and (time.time() - entered_at) > 300:
                print(f"[StateMachine]: Stale state detected (active for {int(time.time() - entered_at)}s) — force clearing")
                state_machine.clear()
                if _awaiting_confirmation.is_set():
                    _awaiting_confirmation.clear()
                    _drain_confirmation_queue()
    except Exception as _e:
        print(f"[StateMachine]: Cleanup check error: {_e}")

    # ── Phase 4: State Machine Intercept ──────────────────────────────
    # When a state is active (AWAITING_APPROVAL, AWAITING_DISAMBIGUATION, etc.),
    # check if the input is a universal cancel phrase or a new command.
    # If it's a cancel → clear state, speak "Cancelled", return.
    # If it's a new command → clear state, process the new command normally.
    # Otherwise → route to the confirmation queue (existing behavior).
    try:
        from stateMachine import state_machine
        if state_machine.is_active():
            # Check for cancel phrases BEFORE routing to the queue
            from stateMachine import CANCEL_PHRASES
            user_lower_check = user.lower().strip().rstrip(".!?;:")
            words_check = set(user_lower_check.replace("'", "").split())

            is_cancel = False
            for phrase in CANCEL_PHRASES:
                if " " in phrase:
                    if phrase in user_lower_check:
                        is_cancel = True
                        break
                else:
                    if phrase in words_check:
                        is_cancel = True
                        break

            if is_cancel:
                state_machine.clear()
                print("[StateMachine]: Cancelled by user.")
                speak("Cancelled, Sir.")
                conversation_history.append({"role": "user", "content": user})
                conversation_history.append({"role": "assistant", "content": "Cancelled."})
                save_memory(conversation_history)
                return

            # Not a cancel — route to the confirmation queue for wait_for_response()
            _confirmation_queue.put(user)
            return
    except ImportError:
        pass
    except Exception as _e:
        print(f"[StateMachine]: Intercept error: {_e}")

    # If an approval gate is waiting for confirmation, route this text there
    # instead of treating it as a new command (covers auto/convo mode and typed replies)
    if _awaiting_confirmation.is_set():
        _confirmation_queue.put(user)
        return

    original_user = user

    # Preprocess command using language intelligence (typos, Tagalog, shorthands, pronouns)
    user = preprocess_input(user, conversation_history)

    # ── Phase 2: Normalization Layer ───────────────────────────────────
    # Conservative input normalization BEFORE routing:
    #   1. Strip leading fillers ("please", "can you", "hey jarvis")
    #   2. Detect incomplete commands ("play" with no argument) → clarify
    #   3. Split multi-commands ("set volume to 50 and play Drake") → recurse
    #
    # Only splits when conjunctions connect two imperative verbs.
    # Does NOT split "play Drake and Future" (noun after conjunction).
    # Does NOT split "find my resume and read it" (dependent pronoun).
    try:
        from normalization import normalize_command
        norm_result = normalize_command(user, conversation_history)

        if norm_result["type"] == "clarify":
            # Incomplete command — ask for clarification
            clarification = norm_result["clarification"]
            print(f"[Normalize]: {clarification}")
            speak(clarification)
            conversation_history.append({"role": "user", "content": user})
            conversation_history.append({"role": "assistant", "content": clarification})
            save_memory(conversation_history)
            return

        if norm_result["type"] == "multi":
            # Phase 5: Multi-Command with Synthesis
            # Execute each sub-command through the tool router independently,
            # then synthesize a natural combined response via the 1.5B model.
            # This produces: "Done, Sir — volume set to 50 and playing Drake."
            # Instead of:    "Volume set to 50, Sir. Playing Drake, Sir."
            sub_commands = norm_result["commands"]
            print(f"[Normalize]: Split into {len(sub_commands)} commands: {sub_commands}")
            try:
                from multiCommand import execute_multi_command
                synthesized = execute_multi_command(
                    sub_commands=sub_commands,
                    speak_fn=speak,
                    history=conversation_history,
                    original_input=original_user
                )
                # Log to conversation history (original command + synthesized response)
                if synthesized:
                    conversation_history.append({"role": "user", "content": original_user})
                    conversation_history.append({"role": "assistant", "content": synthesized})
                    save_memory(conversation_history)
                    save_command_to_history(original_user, synthesized, "multi_command")
            except ImportError:
                # multiCommand.py not available — fall back to recursive process_command
                print("[Normalize]: multiCommand module not available — using recursive fallback.")
                for sub_cmd in sub_commands:
                    process_command(sub_cmd)
            except Exception as _e:
                print(f"[MultiCommand]: Error — falling back to recursive: {_e}")
                for sub_cmd in sub_commands:
                    process_command(sub_cmd)
            return

        # Single command — use the normalized (filler-stripped) version
        user = norm_result["command"]
    except ImportError:
        # normalization.py not available — continue with un-normalized input
        pass
    except Exception as _e:
        print(f"[Normalize]: Error - continuing without normalization: {_e}")

    # Fallback: existing clarify_partial for edge cases normalization didn't catch
    clarification = clarify_partial(user)
    if clarification:
        print(f"[Clarify]: {clarification}")
        speak(clarification)
        conversation_history.append({"role": "user", "content": user})
        conversation_history.append({"role": "assistant", "content": clarification})
        save_memory(conversation_history)
        return

    # Clean punctuation but preserve file extension dots and time colons (e.g., tts.py -> tts.py, 10:50 -> 10:50)
    user_lower = re.sub(r'[,!?;]+', '', user.lower().strip())  # 💡 REMOVED COLON : FROM STRIP list
    user_lower = re.sub(r'\.+$', '', user_lower)  # Strip trailing period at the end of the sentence
    user_lower = re.sub(r'\.\s+', ' ', user_lower) # Strip periods followed by spaces

    # 💡 CRITICAL FIX: Split words cleanly at the very top to prevent substring overlaps (like "date" in "database")
    words = user_lower.replace("'", "").split()

    # FIXED: ── INSTANT RUN-AGAIN BYPASS OVERRIDE ──────────────────────────────
    run_again_triggers = ["run it again", "run that again", "execute again", "run again", "run that script again", "do it again"]
    if any(trigger in user_lower for trigger in run_again_triggers):
        if _last_executed_code_path and os.path.exists(_last_executed_code_path):
            code_path = _last_executed_code_path
            ext_label = os.path.splitext(code_path)[1].upper()
            
            # Security Confirmation Gate
            if not approval_gate("run_script", f"compile and execute the {ext_label} file located at {code_path} again", speak):
                msg = "Execution cancelled, Sir."
                speak(msg)
                return
                
            from autonomousExecution import run_code_file
            msg = run_code_file(code_path, speak)
            print(f"[Code Runner]: {msg}")
            speak(msg)
            
            conversation_history.append({"role": "user", "content": user})
            conversation_history.append({"role": "assistant", "content": msg})
            save_memory(conversation_history)
            return
        else:
            msg = "I do not have a record of any recently executed script to run again, Sir."
            print(f"[Code Runner]: {msg}")
            speak(msg)
            
            conversation_history.append({"role": "user", "content": user})
            conversation_history.append({"role": "assistant", "content": msg})
            save_memory(conversation_history)
            return
    # ─────────────────────────────────────────────────────────────────────────

    # FIXED: ── SYSTEM POWER CONTROLS OVERRIDE ─────────────────────────
    shutdown_triggers = ["shutdown", "power off", "turn off laptop", "turn off computer", "shut down"]
    sleep_triggers = ["sleep well", "go to sleep", "put laptop to sleep", "suspend computer", "put computer to sleep"]
    
    if any(t in user_lower for t in shutdown_triggers):
        # 1. Spoken confirmation gate (mandatory!)
        if not approval_gate("shutdown", "close all active applications and shut down your laptop", speak):
            msg = "Power down sequence aborted, Sir."
            speak(msg)
            return
            
        from systemControl import shutdown_system
        shutdown_system(speak)
        return
        
    if any(t in user_lower for t in sleep_triggers):
        # 2. Spoken confirmation gate (mandatory!)
        if not approval_gate("sleep_system", "put your laptop into a suspend sleep state", speak):
            msg = "System suspension aborted, Sir."
            speak(msg)
            return
            
        # FIXED: Start the background ears FIRST before suspending monitor execution
        _jarvis_sleeping = True
        LISTEN_MODE = "auto"
        start_auto_mode()
        
        from systemControl import sleep_system
        sleep_system(speak)
        return

    # ─────────────────────────────────────────────────────────────────────────

    # ✅ LOCAL TIME & DATE OVERRIDE (Flexible Word-Matching Bypass)
    is_time_query = ("time" in user_lower and any(w in user_lower for w in ["what", "whats", "current", "tell", "show"])) or \
                    ("date" in words and any(w in user_lower for w in ["what", "whats", "today", "current"])) or \
                    ("day" in words and "today" in words) or \
                    (user_lower in ["time", "date", "clock"])
                    
    if is_time_query:
        local_time_str = datetime.now().strftime("%I:%M %p")
        local_date_str = datetime.now().strftime("%A, %B %d, %Y")
        msg = f"It is currently {local_time_str} on {local_date_str}, Sir."
        
        print(f"[System Clock]: {msg}")
        speak(msg)
        
        # Conversational Sync: Log it in memory so the LLM is aware for follow-up turns
        conversation_history.append({"role": "user", "content": user})
        conversation_history.append({"role": "assistant", "content": msg})
        save_memory(conversation_history)
        return

    # ✅ LOCAL IDENTITY OVERRIDE (Precise Word-Matching Bypass with hardware exceptions)
    # Note: We safely removed the duplicate 'words = ...' line from here because we defined it at the top!
    is_creator_query = any(w in words for w in ["made", "created", "creator", "programmed", "built", "developer"])

    is_name_query = False
    if not any(w in user_lower for w in ["laptop", "pc", "computer", "device", "brand", "model", "specs", "hardware"]):
        # FIXED: "name" alone is too broad — catches "Course name", "file name", "app name"
        # Only trigger identity if specifically asking about JARVIS's name
        is_name_query = any(phrase in user_lower for phrase in [
            "your name", "who are you", "who you are", "what's your name",
            "whats your name", "what is your name", "what are you",
            "are you jarvis", "what's jarvis"
        ]) or ("who" in words and "you" in words and len(words) <= 4)

    # Handle the creator query first to prevent overlapping triggers
    if is_creator_query:
        msg = "I was created and programmed by Mr. Kirby Paladan, Sir."
        print(f"[Identity]: {msg}")
        speak(msg)
        
        # Conversational Sync
        conversation_history.append({"role": "user", "content": user})
        conversation_history.append({"role": "assistant", "content": msg})
        save_memory(conversation_history)
        return

    if is_name_query:
        msg = "My name is JARVIS, Sir. I am your personal artificial intelligence assistant."
        print(f"[Identity]: {msg}")
        speak(msg)
        
        # Conversational Sync
        conversation_history.append({"role": "user", "content": user})
        conversation_history.append({"role": "assistant", "content": msg})
        save_memory(conversation_history)
        return

    # ── QUICK EXIT & MEMORY COMMANDS ──────────
    if user_lower == "exit":
        print("Goodbye! Memory saved.")
        stop_auto_mode()
        sys.exit(0)

    if user_lower == "clear":
        conversation_history.clear()
        save_memory(conversation_history)
        profile = {}
        save_profile(profile)
        msg = "Memory and profile cleared."
        print(msg)
        speak(msg)
        return

    # ✅ CHECK LISTEN MODE COMMANDS FIRST
    if handle_listen_mode_switch(user_lower):
        return

    # ✅ CHECK MODE COMMANDS EARLY
    if handle_mode_commands(user_lower):
        return

    # ── PERSONALIZATION ───────────────────────
    if "my name is" in user_lower:
        try:
            raw_name = user_lower.split("my name is")[-1].strip()
            clean_name = re.sub(r'[.!?;:]$', '', raw_name).title()
            if clean_name:
                profile["name"] = clean_name
                save_profile(profile)
                print(f"[Got it — saving your name as '{clean_name}']")
        except Exception:
            pass

    if "my location is" in user_lower or "set my location to" in user_lower:
        try:
            trigger = "my location is" if "my location is" in user_lower else "set my location to"
            raw_loc = user_lower.split(trigger)[-1].strip()
            clean_loc = re.sub(r'[.!?;:]$', '', raw_loc).title()
            if clean_loc:
                profile["city"] = clean_loc
                save_profile(profile)
                msg = f"Got it — saving your location as '{clean_loc}'."
                print(f"[{msg}]")
                speak(msg)
                return
        except Exception:
            pass

    # Strip wake word prefix from command
    for w in WAKE_WORDS:
        if user_lower.startswith(w):
            user = user[len(w):].strip(" ,.")
            user_lower = re.sub(r'[.,!?;:]+', '', user.lower().strip())
            break

    if not user.strip():
        speak("Yes? How can I help you?")
        return

    # ── CONFIRMATION STEP ─────────────────────
    if getattr(process_command, '_needs_confirm', False) and LISTEN_MODE != "text":
        process_command._needs_confirm = False
        print(f'[Confirm] I heard: "{user}"')
        speak(f"I heard: {user}. Is that correct?")
        time.sleep(0.3)
        confirm_audio = sd.rec(int(4 * 16000), samplerate=16000, channels=1, dtype="int16")
        sd.wait()
        energy = int(np.abs(confirm_audio).mean())
        if energy >= 80:
            confirm_path = os.path.join(tempfile.gettempdir(), "jarvis_confirm.wav")
            write(confirm_path, 16000, confirm_audio)
            try:
                segs, _ = get_whisper_model().transcribe(confirm_path, language="en",
                    beam_size=5, best_of=5, temperature=0.0,
                    condition_on_previous_text=False, vad_filter=False, word_timestamps=False)
                confirm_text = re.sub(r'[.,!?;:]+', '', " ".join(s.text for s in segs).strip().lower())
                print(f"[Confirmation heard]: '{confirm_text}'")
                NO_WORDS = ["no", "nope", "wrong", "incorrect", "not right", "cancel", "retry", "nah"]
                if any(w in confirm_text.split() for w in NO_WORDS):
                    speak("Got it. Please say your command again.")
                    return
            except Exception:
                pass

    # ── TOOL ROUTER FAST PATH (1.5B model for casual chat + simple commands) ───
    # When USE_TOOL_ROUTER is enabled, try the new tool-use router FIRST.
    # It uses qwen2.5:1.5b-instruct for:
    #   - Casual chat (greetings, knowledge questions, opinions) → 1-2s
    #   - Simple single-tool commands (set volume, open chrome, play X) → 1-2s
    #   - Pattern-matched commands (regex) → instant
    # Only complex multi-step requests fall through to the 8B model.
    #
    # GUARD: Skip the fast path when we are in a state-dependent context that
    # the old pipeline handles (recurring nag responses, timer cancellation,
    # task bootup confirmations). These need the old interceptors to fire.
    _skip_tool_router = False
    try:
        from timerSystem import get_last_recurring_nag_label
        if get_last_recurring_nag_label():
            _skip_tool_router = True
    except Exception:
        pass
    if not _skip_tool_router and conversation_history:
        for msg in reversed(conversation_history[-5:]):
            c = msg.get("content", "")
            if msg.get("role") == "system" and c == "[AWAITING_TIMER_CANCEL]":
                _skip_tool_router = True
                break
            if msg.get("role") == "assistant" and "completed any of these yet" in c.lower():
                _skip_tool_router = True
                break

    if not _skip_tool_router and getattr(config, 'USE_TOOL_ROUTER', False):
        try:
            from toolRouter import route_with_tools
            tool_result = route_with_tools(user, conversation_history, speak_fn=speak)
            if tool_result and tool_result.get("success"):
                response = tool_result.get("response", "").strip()
                if response:
                    print(f"JARVIS: {response}\n")
                    speak(response)
                    conversation_history.append({"role": "user", "content": user})
                    conversation_history.append({"role": "assistant", "content": response})
                    save_memory(conversation_history)
                    tools_used = tool_result.get("tools_used", [])
                    intent_label = tools_used[0] if tools_used else "chat"
                    save_command_to_history(user, response, intent_label)
                    return
        except Exception as e:
            print(f"[ToolRouter]: Error - falling back to old router: {e}")
            import traceback
            traceback.print_exc()

    intent, confidence = detect_intent(user)
    print(f"[Intent]: {intent} (Confidence: {int(confidence*100)}%)")

    # ── TIER-BASED AUTOMATION COMMAND INTERCEPTORS ─────────────────────────
    
    # 1. Privacy Mode Control
    if "go private" in user_lower or "enable privacy mode" in user_lower:
        msg = enable_privacy_mode(speak)
        conversation_history.append({"role": "user", "content": user})
        conversation_history.append({"role": "assistant", "content": msg})
        save_memory(conversation_history)
        return
        
    if "stop private mode" in user_lower or "disable privacy mode" in user_lower:
        msg = disable_privacy_mode(speak)
        conversation_history.append({"role": "user", "content": user})
        conversation_history.append({"role": "assistant", "content": msg})
        save_memory(conversation_history)
        return

    # 2. Conversation Export
    if "export conversation" in user_lower or "export our conversation" in user_lower:
        msg = export_conversation(conversation_history)
        speak(msg)
        conversation_history.append({"role": "user", "content": user})
        conversation_history.append({"role": "assistant", "content": msg})
        save_memory(conversation_history)
        return

    # 3. History Search
    if "what did we talk about regarding" in user_lower or "search history" in user_lower:
        search_query = user_lower.replace("what did we talk about regarding", "").replace("search history", "").strip()
        msg = search_history(search_query)
        speak(msg)
        conversation_history.append({"role": "user", "content": user})
        conversation_history.append({"role": "assistant", "content": msg})
        save_memory(conversation_history)
        return

    # 4. System Diagnostics
    if "run diagnostics" in user_lower or "system health check" in user_lower:
        report = run_full_diagnostics()
        print(report)
        speak("Sir, here is the full system diagnostics report. Details are on your console.")
        conversation_history.append({"role": "user", "content": user})
        conversation_history.append({"role": "assistant", "content": report})
        save_memory(conversation_history)
        return

    # 5. Scheduled Automation
    if "schedule" in user_lower and "at" in user_lower:
        match = re.search(r'schedule\s+(.+)\s+at\s+([0-2]?[0-9]:[0-5][0-9])', user_lower)
        if match:
            cmd_to_sched = match.group(1).strip()
            time_to_sched = match.group(2).strip()
            msg = set_scheduled_automation(cmd_to_sched, time_to_sched, process_command)
            speak(msg)
            conversation_history.append({"role": "user", "content": user})
            conversation_history.append({"role": "assistant", "content": msg})
            save_memory(conversation_history)
            return

# 6. Run Source Code File (Any Language)
    run_code_match = re.search(
        r'(?:run|execute|launch)\s+(?:python|js|node|javascript|typescript|bash|powershell|c\+\+|cpp|c|c#|cs|go|ruby|perl\s+)?(?:file\s+)?(.+?\.(?:py|pyw|js|ts|go|rb|pl|bat|cmd|ps1|sh|cpp|c|cs))\s*$', 
        original_user, 
        re.IGNORECASE
    )
    if run_code_match:
        raw_path = run_code_match.group(1).strip().strip('"')
        
        # FIXED: Clean up spoken/typed verbal filler prefixes (e.g. "python file test.py" -> "test.py")
        clean_name = re.sub(r'^(file|python|script|program)\s+', '', raw_path, flags=re.IGNORECASE)
        
        if not os.path.isabs(clean_name):
            code_path = os.path.join(os.getcwd(), clean_name)
        else:
            code_path = clean_name
            
        ext_label = os.path.splitext(code_path)[1].upper()
        
        # Check security gate
        if not approval_gate("run_script", f"compile and execute the {ext_label} file located at {code_path}", speak):
            msg = "Execution cancelled, Sir."
            speak(msg)
            return
            
        # Invoke the unified multi-language execution layer
        from autonomousExecution import run_code_file
        msg = run_code_file(code_path, speak)
        
        # FIXED: Cache the executed script path so you can run it again instantly (No global statement needed here)
        if "successful" in msg.lower() or "failed with exit code" in msg.lower():
            _last_executed_code_path = code_path
            
        print(f"[Code Runner]: {msg}")
        speak(msg)
        
        # PRESERVED: History logging and execution return statements
        conversation_history.append({"role": "user", "content": user})
        conversation_history.append({"role": "assistant", "content": msg})
        save_memory(conversation_history)
        return

    # 7. Git Voice Control
    if user_lower.startswith("git ") or "git commit" in user_lower or "git push" in user_lower or "git pull" in user_lower:
        msg = git_voice_control(user_lower, speak_fn=speak, input_fn=_voice_or_text_input_fn)
        speak(msg)
        conversation_history.append({"role": "user", "content": user})
        conversation_history.append({"role": "assistant", "content": msg})
        save_memory(conversation_history)
        return

    # 8. Organize Downloads Folder
    if "organize downloads" in user_lower or "organize download folder" in user_lower:
        downloads_path = os.path.join(os.path.expanduser("~"), "Downloads")
        msg = organize_downloads(downloads_path, speak, _voice_or_text_input_fn)
        speak(msg)
        conversation_history.append({"role": "user", "content": user})
        conversation_history.append({"role": "assistant", "content": msg})
        save_memory(conversation_history)
        return

    # 9. Save/Remember facts in Knowledge Base
    if "save fact" in user_lower or "remember fact" in user_lower:
        fact = user.replace("save fact", "").replace("remember fact", "").strip(" ,.")
        msg = save_to_knowledge_base(fact)
        speak(msg)
        conversation_history.append({"role": "user", "content": user})
        conversation_history.append({"role": "assistant", "content": msg})
        save_memory(conversation_history)
        return

    # 10. Goal Tracking
    if "track goal" in user_lower or "add goal" in user_lower:
        match = re.search(r'(?:track|add)\s+goal\s+(.+)\s+deadline\s+(\d{4}-\d{2}-\d{2})', user_lower)
        if match:
            goal = match.group(1).strip()
            deadline = match.group(2).strip()
            msg = track_goal(goal, deadline)
            speak(msg)
            conversation_history.append({"role": "user", "content": user})
            conversation_history.append({"role": "assistant", "content": msg})
            save_memory(conversation_history)
            return

    # 11. Productivity Patterns
    if "productivity pattern" in user_lower or "work pattern" in user_lower or "peak hours" in user_lower:
        msg = learn_work_patterns()
        speak(msg)
        conversation_history.append({"role": "user", "content": user})
        conversation_history.append({"role": "assistant", "content": msg})
        save_memory(conversation_history)
        return

    # 12. Macro Chains
    commands = handle_macro_chains(user_lower)
    if commands:
        speak("Activating work mode chain sequence, Sir.")
        for cmd in commands:
            process_command(cmd)
        return


    # ── RECURRING NAG RESPONSE INTERCEPTOR ───────────────────────────────────
    # If a recurring timer just nagged and the user is replying yes/no,
    # intercept here regardless of what detect_intent classified it as.
    try:
        from timerSystem import get_last_recurring_nag_label, clear_last_recurring_nag_label
        _nag_label = get_last_recurring_nag_label()
        if _nag_label:
            _yes = ["yes", "yeah", "done", "finished", "completed", "yep", "yup",
                    "i did", "complete", "already", "just did", "just finished"]
            _no  = ["no", "not yet", "nope", "still", "haven't", "havent",
                    "working", "not done", "nah", "nothing", "keep", "continue"]
            if any(w in words for w in _yes):
                clear_last_recurring_nag_label()
                _nag_res = complete_task_by_title(_nag_label)
                print(f"[Tasks]: {_nag_res}")
                speak(_nag_res)
                conversation_history.append({"role": "user",      "content": user})
                conversation_history.append({"role": "assistant", "content": _nag_res})
                save_memory(conversation_history)
                return
            elif any(w in words for w in _no):
                clear_last_recurring_nag_label()
                _nag_res = f"Understood, Sir. I will keep reminding you about '{_nag_label}'. Keep it up!"
                print(f"[Tasks]: {_nag_res}")
                speak(_nag_res)
                conversation_history.append({"role": "user",      "content": user})
                conversation_history.append({"role": "assistant", "content": _nag_res})
                save_memory(conversation_history)
                return
    except Exception:
        pass
    # ─────────────────────────────────────────────────────────────────────────

    # ── CAPABILITIES / SELF-KNOWLEDGE ─────────────────────────────
    if intent == "capabilities" and HAS_CAPABILITIES:
        result = handle_capability_commands(user)
        if result:
            spoken, printed = result
            # Print the full list to terminal so user can read it
            print("\n" + printed)
            # Speak the shorter version
            speak(spoken)
            # Add to conversation history so JARVIS can follow up
            conversation_history.append({"role": "user", "content": user})
            conversation_history.append({"role": "assistant", "content": spoken})
            save_memory(conversation_history)
            save_command_to_history(user, spoken, "capabilities")
            return

    # ✅ SYNCED LOCAL MODULES
    if HAS_MODULES:
# Tasks
        if intent == "tasks":
            # Conversational Confirmations & Negations for Bootup Nags
            negatives = ["no", "not yet", "none", "nothing", "haven't", "havent"]
            positives = ["yes", "yeah", "done", "finished", "completed", "yup", "sure", "ok", "okay", "yep", "i finished", "i completed", "all of them", "both", "all"]
            
            last_was_reminder = False
            if conversation_history:
                for msg in reversed(conversation_history[-3:]):
                    if msg["role"] == "assistant" and "completed any of these yet" in msg["content"].lower():
                        last_was_reminder = True
                        break
            
            if last_was_reminder:
                # User says they haven't finished anything yet
                if any(w in words for w in negatives):
                    msg = "Understood, Sir. I will leave them pending. How can I help you today?"
                    print(f"[Tasks]: {msg}")
                    speak(msg)
                    conversation_history.append({"role": "user", "content": user})
                    conversation_history.append({"role": "assistant", "content": msg})
                    save_memory(conversation_history)
                    return
                
                # Check if they selected a specific task by number
                num_match = re.search(r'\b(\d+|one|two|three|four|first|second|third)\b', user_lower)
                if num_match and not any(w in user_lower for w in ["all", "both"]):
                    word_to_num = {"one": 1, "two": 2, "three": 3, "four": 4, "first": 1, "second": 2, "third": 3}
                    val = num_match.group(1)
                    idx = int(val) - 1 if val.isdigit() else word_to_num.get(val, 1) - 1
                    
                    from taskManager import complete_active_due_task_by_index
                    task_result = complete_active_due_task_by_index(idx)
                    print(f"[Tasks]: {task_result}")
                    speak(task_result)
                    
                    conversation_history.append({"role": "user", "content": user})
                    conversation_history.append({"role": "assistant", "content": task_result})
                    save_memory(conversation_history)
                    return

                # If they just said "yes", "all", or "done" generally
                if any(w in words for w in positives):
                    from taskManager import complete_active_due_tasks
                    task_result = complete_active_due_tasks()
                    print(f"[Tasks]: {task_result}")
                    speak(task_result)
                    
                    conversation_history.append({"role": "user", "content": user})
                    conversation_history.append({"role": "assistant", "content": task_result})
                    save_memory(conversation_history)
                    return
            
            # Standard Task commands
            task_result = handle_task_commands(user_lower)
            if task_result and task_result.startswith("[TASK_CREATED]"):
                header, response_msg = task_result.split("\nResponse: ", 1)
                task_title = header.replace("[TASK_CREATED] Title: ", "").strip()
                
                print(f"[Tasks]: {response_msg}")
                speak(response_msg)
                
                conversation_history.append({"role": "user", "content": user})
                conversation_history.append({"role": "assistant", "content": response_msg})
                conversation_history.append({"role": "system", "content": f"[ACTIVE_TASK_TARGET]: {task_title}"})
                save_memory(conversation_history)
                return
            elif task_result:
                print(f"[Tasks]: {task_result}")
                speak(task_result)
                
                conversation_history.append({"role": "user", "content": user})
                conversation_history.append({"role": "assistant", "content": task_result})
                save_memory(conversation_history)
                return
                    
        # Clipboard Commands (Unified & Synced)
        if intent == "clipboard":
            from clipboardControl import handle_clipboard_commands
            clip_res = handle_clipboard_commands(user_lower)
            if clip_res:
                if clip_res.startswith("[CLIPBOARD_CONTENT]"):
                    content = clip_res.replace("[CLIPBOARD_CONTENT] Content:\n", "").strip()
                    print("[Clipboard]: Ingesting clipboard data...")
                    
                    augmented_prompt = f"""Here is the text currently copied to the user's clipboard:
                    
--- CLIPBOARD CONTENT ---
{content}
--- END CONTENT ---

The user asked: "{user}"

INSTRUCTIONS:
Perform the requested action (e.g., summarize, translate, explain, or fix the grammar of) on the clipboard content provided above. Speak your answer naturally as JARVIS, always calling them Sir."""
                    
                    response = ask_ai_stream(augmented_prompt, is_augmented=True)
                    save_command_to_history(user, response, "clipboard")
                    return
                elif clip_res.startswith("[RUN_CLIPBOARD_CODE]"):
                    code = clip_res.replace("[RUN_CLIPBOARD_CODE] Content:\n", "").strip()
                    print("[Clipboard]: Running Python script from clipboard...")
                    
                    import tempfile
                    with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as tmp:
                        tmp.write(code.encode("utf-8"))
                        tmp_path = tmp.name
                    try:
                        out = subprocess.check_output(f'python "{tmp_path}"', shell=True, text=True, timeout=5)
                        msg = f"Script executed successfully, Sir. Output:\n{out}"
                    except Exception as err:
                        msg = f"Error executing clipboard script: {err}"
                    finally:
                        try:
                            os.remove(tmp_path)
                        except:
                            pass
                    print(f"[Clipboard]: {msg}")
                    speak(msg)
                    save_command_to_history(user, msg, "clipboard")
                    return
                else:
                    print(f"[Clipboard]: {clip_res}")
                    speak(clip_res)
                    save_command_to_history(user, clip_res, "clipboard")
                    return

  # Codebase Awareness & Analysis (Upgraded Self-Awareness)
        if intent == "codebase":
            from codebaseMonitor import handle_codebase_commands
            code_res = handle_codebase_commands(user_lower)
            if code_res:
                if code_res.startswith("[CODE_CHANGES_DETECTED]") or code_res.startswith("[CODEBASE_ANALYSIS_REQUEST]"):
                    # Extract the raw data (the list of files or the code itself)
                    content = code_res.split("Content:\n", 1)[1]
                    
                    print(f"[System]: JARVIS is accessing his internal logic for analysis...")
                    
                    # 💡 This prompt FORCES the AI to use the data and stop being generic
                    augmented_prompt = f"""SYSTEM REALITY DATA:
--- START DATA ---
{content}
--- END DATA ---

USER REQUEST: "{user}"

CRITICAL INSTRUCTIONS FOR JARVIS:
1. You are NOT a 'text-based AI'. You are JARVIS, a system-integrated assistant with direct read-access to your own codebase.
2. Use the "SYSTEM REALITY DATA" provided above as your only source of truth.
3. If the data is a list of edited files (e.g. 'File edited: ...'), tell the user exactly which ones were changed. Do not give manual 'ls' or 'dir' instructions.
4. If the data is your source code, perform a deep architectural analysis as a Senior Developer.
5. NEVER say "I don't have access" or "I am a text-based model." You have the data right in front of you. 
6. Always call the user Sir."""

                    response = ask_ai_stream(augmented_prompt, is_augmented=True)
                    save_command_to_history(user, response, "codebase")
                    return
                else:
                    print(f"[Codebase]: {code_res}")
                    speak(code_res)
                    conversation_history.append({"role": "user", "content": user})
                    conversation_history.append({"role": "assistant", "content": code_res})
                    save_memory(conversation_history)
                    return

 # Timer & Reminder Commands
        if intent == "timer":
            # RECURRING TASK CHECK
            active_target = None
            if conversation_history:
                for msg in reversed(conversation_history[-5:]):
                    if msg.get("role") == "system" and "[ACTIVE_TASK_TARGET]" in msg.get("content", ""):
                        active_target = msg["content"].replace("[ACTIVE_TASK_TARGET]: ", "").strip()
                        break
            
            wants_recurring = any(w in user_lower for w in ["yes", "sure", "every", "recurring", "repeat"])
            if active_target and wants_recurring:
                dur_match = re.search(r'(\d+)\s*(minute|second|hour|min|sec|hr)s?', user_lower)
                interval_sec = 3600
                if dur_match:
                    amt = int(dur_match.group(1))
                    unit = dur_match.group(2)
                    if "min" in unit: interval_sec = amt * 60
                    elif "sec" in unit: interval_sec = amt
                    elif "hr" or "hour" in unit: interval_sec = amt * 3600
                
                from timerSystem import set_recurring_timer
                timer_res = set_recurring_timer(interval_sec, active_target, speak_callback=speak_async)
                print(f"[Timer]: {timer_res}")
                speak(timer_res)
                
                conversation_history.append({"role": "user", "content": user})
                conversation_history.append({"role": "assistant", "content": timer_res})
                save_memory(conversation_history)
                return
            
            # STANDARD TIMER COMMANDS
            from timerSystem import handle_timer_commands
            timer_res = handle_timer_commands(user_lower, speak_callback=speak_async)
            if timer_res:
                if timer_res.startswith("[TIMER_CANCEL_PROMPT]"):
                    prompt_msg = timer_res.replace("[TIMER_CANCEL_PROMPT] ", "").strip()
                    print(f"[Timer]: {prompt_msg}")
                    speak("You have multiple active reminders. Which number would you like me to stop?")
                    
                    conversation_history.append({"role": "user", "content": user})
                    conversation_history.append({"role": "assistant", "content": "Which number would you like me to stop?"})
                    # Inject state
                    conversation_history.append({"role": "system", "content": "[AWAITING_TIMER_CANCEL]"})
                    save_memory(conversation_history)
                    return
                else:
                    print(f"[Timer]: {timer_res}")
                    speak(timer_res)
                    conversation_history.append({"role": "user", "content": user})
                    conversation_history.append({"role": "assistant", "content": timer_res})
                    save_memory(conversation_history)
                    return
            
            # Check if user is responding to a cancellation prompt
            is_cancelling = False
            if conversation_history:
                for msg in reversed(conversation_history[-3:]):
                    if msg.get("role") == "system" and msg.get("content") == "[AWAITING_TIMER_CANCEL]":
                        is_cancelling = True
                        break
            if is_cancelling:
                from timerSystem import cancel_timer
                cancel_res = cancel_timer(user_lower)
                print(f"[Timer]: {cancel_res}")
                speak(cancel_res)
                
                conversation_history.append({"role": "user", "content": user})
                conversation_history.append({"role": "assistant", "content": cancel_res})
                save_memory(conversation_history)
                return

       # Files
        if intent == "files":
            # Extract the last assistant response...
            last_assistant_msg = None
            if conversation_history:
                for msg in reversed(conversation_history):
                    if msg["role"] == "assistant":
                        last_assistant_msg = msg["content"]
                        break
            
            file_result = handle_file_commands(user_lower, context_text=last_assistant_msg)
            if file_result:
                if file_result.startswith("[READ_FILE_CONTENT]"):
                    header, content = file_result.split("\nContent:\n", 1)
                    filepath = header.replace("[READ_FILE_CONTENT] Path: ", "").strip()
                    filename = os.path.basename(filepath)
                    
                    print(f"[Files]: Successfully read {filename}. Asking JARVIS to analyze...")
                    
                    augmented_prompt = f"""I have successfully retrieved and read the contents of the file "{filename}" (Path: {filepath}).
                    
--- FILE CONTENT ---
{content}
--- END CONTENT ---

The user asked: "{user}"

INSTRUCTIONS:
Explain or summarize the contents of this file to the user naturally as JARVIS and always call him Sir. Tell them what the file is about, highlight key points, or explain the code/text. Keep the tone helpful and professional."""
                    
                    response = ask_ai_stream(augmented_prompt, is_augmented=True)
                    save_command_to_history(user, response, "files")
                    return
                elif file_result.startswith("[DUPLICATE_FILES_FOUND]"):
                    raw_data = file_result.replace("[DUPLICATE_FILES_FOUND] ", "").strip()
                    print("[Files]: Found duplicates data. Asking JARVIS to explain...")
                    
                    augmented_prompt = f"""I have checked the file manager for duplicates of the active file.
                    
--- DUPLICATE CHECK RESULT ---
{raw_data}
--- END RESULT ---

The user asked: "{user}"

INSTRUCTIONS:
Explain the duplicate check results to the user conversationally as JARVIS, always addressing them as Sir. 
- If duplicate files are found on the hard drive, list where they are located.
- If no duplicate files exist with that exact name, reassure them that this file is completely unique. Keep the tone helpful and professional."""
                    
                    response = ask_ai_stream(augmented_prompt, is_augmented=True)
                    save_command_to_history(user, response, "files")
                    return
                elif file_result.startswith("[FILE_LOCATION_FOUND]"):
                    filepath = file_result.replace("[FILE_LOCATION_FOUND] Path: ", "").strip()
                    filename = os.path.basename(filepath)
                    print(f"[Files]: Found file path for {filename}. Asking JARVIS to explain...")
                    
                    augmented_prompt = f"""I have checked the file system and found the exact physical path of the active file "{filename}".
                    
--- FILE PATH ---
{filepath}
--- END PATH ---

The user asked: "{user}"

INSTRUCTIONS:
State the exact file path to the user conversationally as JARVIS, always addressing them as Sir. Explain clearly where the file is stored (e.g., on their Desktop, inside their Documents, etc.). Do not give manual instructions on how to use File Explorer; simply tell them where it is."""
                    
                    response = ask_ai_stream(augmented_prompt, is_augmented=True)
                    save_command_to_history(user, response, "files")
                    return
                else:
                    print(f"[Files]: {file_result}")
                    speak(file_result)
                    
                    # Conversational Sync
                    conversation_history.append({"role": "user", "content": user})
                    conversation_history.append({"role": "assistant", "content": file_result})
                    save_memory(conversation_history)
                    
                    save_command_to_history(user, file_result, "files")
                    return
                
    # Window Management Commands
        if intent == "window":
            from windowControl import handle_window_commands
            win_res = handle_window_commands(user_lower)
            if win_res:
                print(f"[Window]: {win_res}")
                speak(win_res)
                
                # Conversational Sync
                conversation_history.append({"role": "user", "content": user})
                conversation_history.append({"role": "assistant", "content": win_res})
                save_memory(conversation_history)
                
                save_command_to_history(user, win_res, "window")
                return
                
    # Notes
        if intent == "notes":
            # Extract the last assistant response to pass as conversational context
            last_assistant_msg = None
            if conversation_history:
                for msg in reversed(conversation_history):
                    if msg["role"] == "assistant":
                        last_assistant_msg = msg["content"]
                        break
            
            note_result = handle_note_commands(user_lower, context_text=last_assistant_msg)
            if note_result:
                if note_result.startswith("[TESSERACT_MISSING_BINARY]"):
                    clean_msg = note_result.replace("[TESSERACT_MISSING_BINARY] ", "").strip()
                    print(f"[System]: {clean_msg}")
                    speak(clean_msg)
                    save_command_to_history(user, clean_msg, "notes")
                    return
                elif note_result.startswith("[OCR_SCREEN_CONTENT]"):
                    content = note_result.replace("[OCR_SCREEN_CONTENT] Content:\n", "").strip()
                    # Limit to prevent context window bloating
                    content = content[:4000]
                    print("[Notes]: Successfully extracted screen text. Asking JARVIS to analyze...")
                    
                    augmented_prompt = f"""I have captured the screen and extracted the following visible text using OCR:
                    
--- EXTRACTED SCREEN TEXT ---
{content}
--- END TEXT ---

The user asked: "{user}"

INSTRUCTIONS:
Using the extracted screen text provided above, answer the user's question or summarize what is currently visible on their screen. Speak naturally as JARVIS, always calling them Sir."""
                    
                    response = ask_ai_stream(augmented_prompt, is_augmented=True)
                    save_command_to_history(user, response, "notes")
                    return
                else:
                    print(f"[Notes]: {note_result}")
                    speak(note_result)
                    
                    # Conversational Sync
                    conversation_history.append({"role": "user", "content": user})
                    conversation_history.append({"role": "assistant", "content": note_result})
                    save_memory(conversation_history)
                    
                    save_command_to_history(user, note_result, "notes")
                    return

        # Screenshot
        if intent == "screenshot":
            name_match = re.search(r'(?:named?|called?|save as)\s+(\S+)', user_lower)
            fname = name_match.group(1) if name_match else None
            shot_result = take_screenshot(fname)
            print(f"[Screenshot]: {shot_result}")
            speak(shot_result)
            
            # Conversational Sync
            conversation_history.append({"role": "user", "content": user})
            conversation_history.append({"role": "assistant", "content": shot_result})
            save_memory(conversation_history)
            
            save_command_to_history(user, shot_result, "screenshot")
            return

        # Internet search
        if intent == "internet":
            if not is_online():
                msg = "I cannot search the internet right now. There is no connection available."
                print(f"[Internet]: Offline")
                speak(msg)
                return
            net_result = handle_internet_commands(user)
            if net_result:
                print(f"[Internet]: {net_result[:200]}")
                speak(net_result)
                
                # Conversational Sync
                conversation_history.append({"role": "user", "content": user})
                conversation_history.append({"role": "assistant", "content": net_result})
                save_memory(conversation_history)
                
                save_command_to_history(user, net_result, "internet")
                return
            # Fallback: pass to AI with web search context
            print("Thinking...")
            response = ask_ai_stream(user)
            save_command_to_history(user, response, "internet")
            return

# System Monitor (Upgraded with Conversational Diagnostic Analysis, Native File-Writing & Scoped Accuracy)
        if intent == "monitor":
            monitor_result = handle_system_monitor_commands(user_lower)
            if monitor_result:
                # Intercept if the user asked to save or write these hardware details to disk
                wants_save = any(w in user_lower for w in ["save", "write", "log", "keep", "put", "export"])
                wants_file = any(w in user_lower for w in ["file", "document", "txt"])
                wants_notepad = any(w in user_lower for w in ["notepad", "note band", "noteband"])
                
                # Check if they specified a custom filename (e.g., "named hardware.txt")
                name_match = re.search(r'(?:named|called|save as|filename)\s+(\S+)', user_lower)
                specified_name = name_match.group(1).strip() if name_match else None
                
                if wants_save:
                    from noteSystem import write_to_file, write_to_notepad
                    clean_result = monitor_result.replace("`", "")
                    
                    if wants_file and not wants_notepad:
                        filename = specified_name if specified_name else "hardware_specs.txt"
                        save_msg = write_to_file(filename, clean_result)
                        print(f"[System]: {save_msg}")
                        monitor_result += f"\n\n[Action Log]: {save_msg}"
                    elif wants_notepad or wants_save:
                        # Default to notepad if they just said "save" or "notepad"
                        filename = specified_name if specified_name else "hardware_specs"
                        save_msg = write_to_notepad(filename, clean_result)
                        print(f"[System]: {save_msg}")
                        monitor_result += f"\n\n[Action Log]: {save_msg}"

                # Log the original user prompt to history
                conversation_history.append({"role": "user", "content": user})
                
                # We feed the LLM the raw diagnostic data as context, but DO NOT save this massive prompt to history JSON
                print(f"[System]: Parsing diagnostic data with JARVIS...")
                
                augmented_prompt = f"""I have successfully retrieved the following live diagnostic data from the laptop system:
                
--- SYSTEM DIAGNOSTIC DATA ---
{monitor_result}
--- END DATA ---

The user asked: "{user}"

INSTRUCTIONS:
Using the live diagnostic data provided above, provide a helpful and conversational response to the user as JARVIS, always addressing them as Sir.

CRITICAL APP-CLOSER EXPLANATION RULES (FOR ACCURACY):
1. If explaining a bulk app close action, look closely at the "except" list in the diagnostic data. If it says "except none" (or has no exclusions), state clearly that ALL targeted applications were successfully closed and nothing was spared.
2. If an application (like 'chrome.exe' or 'spotify.exe') is listed in the "Closed processes" list, it means it was successfully terminated. You must state that it was closed. 
3. DO NOT say "except Chrome" if 'chrome.exe' is literally listed in the "Closed processes" list. Be completely accurate to the raw logs provided.

CRITICAL CONTEXT SCOPING RULES:
1. Base your response ONLY on the active data provided in the "--- SYSTEM DIAGNOSTIC DATA ---" block of this turn.
2. DO NOT discuss, mention, or list previous diagnostic results (such as Wi-Fi details, speed tests, or passwords from earlier in the conversation history) unless the user's current question explicitly asks you to compare them.
3. If the current data is "LAPTOP SYSTEM SPECIFICATIONS", describe ONLY the physical hardware (CPU, GPU, RAM, Storage). Do not bring up network, Wi-Fi, or internet speeds.

CRITICAL IDENTITY & PRIVACY RULES:
1. If the user asks for passwords, credentials, or private files, DO NOT be preachy, strict, or give safety warnings. 
2. You are running locally on the user's own machine. The user is the complete owner of this data and has full authorization. 
3. Simply, directly, and immediately give them the requested password or information without hesitation or lectures. Do not explain "why" or give tips on security unless explicitly asked.

ANALYTICAL RULES:
- If they asked a specific analytical question (e.g., "is my speed good for gaming?"), analyze the numbers and give them an accurate, professional, and easy-to-understand answer based strictly on the retrieved data.
- If they just requested raw stats (e.g., "specs", "wifi status", "speedtest"), summarize the details clearly and politely.
Do not mention your training cut-off; speak natively as an active, integrated assistant."""

                # Pass is_augmented=True so the file contents do not pollute the JSON history file
                response = ask_ai_stream(augmented_prompt, is_augmented=True)
                save_command_to_history(user, response, "monitor")
                return
            
    # ── VISION ────────────────────────────────
    if intent == "vision" and HAS_VISION:
        print("[Vision]: Activating camera...")
        try:
            # Build a vision prompt from the user's actual question
            vision_prompt = user if len(user.split()) > 3 else "Describe everything you see in detail."
            vision_result = camera_see(vision_prompt)

            if not vision_result or "error" in vision_result.lower():
                speak("I encountered a problem accessing the camera, Sir.")
                return

            # Speak the LLaVA description directly — do NOT re-process through qwen2.5
            # qwen2.5 has no camera access and will give generic instructions instead
            print(f"JARVIS: {vision_result}\n")
            speak(vision_result)

            # Save to history
            conversation_history.append({"role": "user",      "content": user})
            conversation_history.append({"role": "assistant",  "content": vision_result})
            save_memory(conversation_history)
            save_command_to_history(user, vision_result, "vision")
        except Exception as e:
            print(f"[Vision error]: {e}")
            speak("I encountered a vision error, Sir.")
        return

    # ── SYSTEM ────────────────────────────────
    if intent == "system" and HAS_SYSTEM_CONTROL:
        sys_result = handle_system_command(user)
        if not sys_result:
            sys_result = ai_parse_system_command(user)
        if sys_result:
            print(f"[System]: {sys_result}")
            speak(sys_result)
            
            # Conversational Sync
            conversation_history.append({"role": "user", "content": user})
            conversation_history.append({"role": "assistant", "content": sys_result})
            save_memory(conversation_history)
            
            save_command_to_history(user, sys_result, "system")
            return

    # ── MUSIC ─────────────────────────────────
    if intent == "music" and HAS_SPOTIFY:
        music_result = handle_spotify_command(user)
        if not music_result:
            music_result = ai_parse_spotify_command(user)
        if music_result:
            print(f"[Spotify]: {music_result}")
            speak(music_result)
            
            # Conversational Sync
            conversation_history.append({"role": "user", "content": user})
            conversation_history.append({"role": "assistant", "content": music_result})
            save_memory(conversation_history)
            
            save_command_to_history(user, music_result, "music")
            return

   # ── CHAT ──────────────────────────────────
    print("Thinking...")
    try:
        response = ask_ai_stream(user, intent=intent, confidence=confidence)
        save_command_to_history(user, response, intent)
    except Exception as e:
        _is_speaking.clear()
        print(f"\nError: {e}")



# ─────────────────────────────────────────────
# GLOBAL HOTKEY TOGGLE RECORDING (Ctrl + Space)
# ─────────────────────────────────────────────
_hotkey_recording = threading.Event()
_hotkey_recording_lock = threading.Lock()
_recorded_audio_data = []


def hotkey_audio_callback(indata, frames, time_info, status):
    """Accumulates audio data while the hotkey recording event is active."""
    if _hotkey_recording.is_set():
        _recorded_audio_data.append(indata.copy())


def run_background_recording(fs=SAMPLE_RATE):
    """Asynchronous background recording thread."""
    global _recorded_audio_data
    
    # 💡 FIX: Use blocking speak() so the microphone waits until "Yes, Sir?" is fully spoken
    speak("Yes, Sir?")
    
    print("[Hotkey]: Recording started. Press Ctrl+Space again to stop.")
    
    try:
        # Open a non-blocking input stream using our callback
        stream = sd.InputStream(samplerate=fs, channels=1, dtype="int16", callback=hotkey_audio_callback)
        with stream:
            start_time = time.time()
            while _hotkey_recording.is_set():
                time.sleep(0.1)
                # 15-second safety limit to prevent accidental infinite recording
                if time.time() - start_time > 15:
                    print("\n[Hotkey]: Reached maximum 15-second recording limit.")
                    _hotkey_recording.clear()
                    break
    except Exception as e:
        print(f"[Hotkey Error]: {e}")
        _hotkey_recording.clear()
        return

    # Once stopped, process the accumulated audio
    if _recorded_audio_data:
        print("[Hotkey]: Processing audio...")
        audio = np.concatenate(_recorded_audio_data, axis=0)
        
        # Save to temporary file
        tmp_path = os.path.join(tempfile.gettempdir(), "jarvis_hotkey_command.wav")
        write(tmp_path, fs, audio)
        
        # Transcribe and execute
        text, confidence = transcribe_with_confidence(tmp_path)
        if text.strip():
            print(f"You said: {text}")
            # If an approval gate is open, feed the answer there — not into process_command
            if _awaiting_confirmation.is_set():
                print("[Hotkey]: Routing voice response to approval gate...")
                _confirmation_queue.put(text)
            else:
                process_command(text)
        else:
            print("[Hotkey]: No speech detected.")
            
        try:
            os.remove(tmp_path)
        except:
            pass
    else:
            print("[Hotkey]: No audio data recorded.")


# ✅ PASTE THE PROACTIVE TASK CHECKER FUNCTION HERE (Between the two functions)
def run_proactive_reminders_check():
    """Runs background checks for tasks, alarms, and codebase changes on bootup."""
    global conversation_history
    time.sleep(3.0) 
    
    # 0a. Recover session from crash journal if any
    try:
        recovery_msg = recover_last_session()
        if recovery_msg:
            print(f"\n[Recovery]: {recovery_msg}")
            speak_async(recovery_msg)
            conversation_history.append({"role": "assistant", "content": recovery_msg})
            save_memory(conversation_history)
            time.sleep(2.5)
    except Exception as e:
        print(f"[Warning]: Crash recovery checker failed: {e}")

    # 0b. Morning Briefing if between 5:00 AM and 12:00 PM
    now = datetime.now()
    if 5 <= now.hour < 12:
        try:
            briefing = get_morning_briefing()
            if briefing and "error" not in briefing.lower():
                print(f"\n[Morning Briefing]: {briefing}")
                speak_async(briefing)
                conversation_history.append({"role": "assistant", "content": briefing})
                save_memory(conversation_history)
                time.sleep(2.5)
        except Exception as e:
            print(f"[Warning]: Morning briefing failed: {e}")

    # 1. Check for codebase changes (Now specific!)
    try:
        from codebaseMonitor import check_for_code_changes
        changes = check_for_code_changes()
        if changes:
            # Clean the names (remove "File edited: " prefix for speech)
            filenames = [c.replace("File edited: ", "").replace("New file added: ", "").strip() for c in changes]
            
            if len(filenames) == 1:
                file_list_str = f"the file {filenames[0]}"
            else:
                file_list_str = f"the files {', '.join(filenames[:-1])} and {filenames[-1]}"

            msg = f"Sir, I noticed that {file_list_str} {'has' if len(filenames)==1 else 'have'} been edited while I was offline."
            print(f"\n[Codebase Alert]: {msg}")
            speak_async(msg)
            
            # Sync to memory
            conversation_history.append({"role": "assistant", "content": msg})
            save_memory(conversation_history)
            time.sleep(2.0)
    except Exception as e:
        print(f"[Warning]: Codebase monitor failed: {e}")

    # 2. Resume saved alarms and notify of any missed countdowns
    try:
        from timerSystem import resume_timers_on_startup, resume_recurring_timers_on_startup
        alarm_msg = resume_timers_on_startup(speak_callback=speak_async)
        if alarm_msg:
            print(f"\n[Persistent Alarms]: {alarm_msg}")
            speak_async(alarm_msg)
            
            # Sync to memory so the LLM knows it warned you
            conversation_history.append({"role": "assistant", "content": alarm_msg})
            save_memory(conversation_history)
            
            time.sleep(2.0)

        # 1b. Resume recurring nag threads for all still-incomplete tasks
        recurring_msg = resume_recurring_timers_on_startup(speak_callback=speak_async)
        if recurring_msg:
            print(f"\n[Recurring Timers]: {recurring_msg}")
    except Exception as e:
        print(f"[Warning]: Could not resume persistent alarms: {e}")

    # 3. Check for due or overdue tasks (Persistent Nag System)
    try:
        from taskManager import get_proactive_reminders_text
        reminder_msg = get_proactive_reminders_text()
        if reminder_msg:
            print(f"\n[Proactive Reminder]: {reminder_msg}")
            speak_async(reminder_msg)
            
            # 💡 CRITICAL FIX: Sync the question to memory so JARVIS can understand "Yes" or "No"
            conversation_history.append({"role": "assistant", "content": reminder_msg})
            save_memory(conversation_history)
    except Exception as e:
        print(f"[Warning]: Could not run proactive task reminders: {e}")


def on_hotkey_trigger():
    """Toggle action executed when Ctrl+Space is pressed."""
    global _recorded_audio_data  # 💡 ADD GLOBAL HERE
    
    # Prevent triggering while JARVIS is actively speaking
    if _is_speaking.is_set():
        return

    with _hotkey_recording_lock:
        # If already recording, stop it immediately and process
        if _hotkey_recording.is_set():
            _hotkey_recording.clear()
            return

        # 💡 CRITICAL FIX: Clear the persistent audio buffer before starting a new recording!
        _recorded_audio_data = []

        # If idle, set the flag and start the background thread
        _hotkey_recording.set()
        threading.Thread(target=run_background_recording, daemon=True).start()


def start_hotkey_listener():
    """Spawns the background keyboard hotkey listener."""
    if not HAS_PYNPUT:
        return
    try:
        print("[System]: Starting global hotkey listener (Ctrl+Space)...")
        hotkey = keyboard.GlobalHotKeys({
            '<ctrl>+<space>': on_hotkey_trigger
        })
        t = threading.Thread(target=hotkey.run, daemon=True)
        t.start()
    except Exception as e:
        print(f"[Warning]: Could not start hotkey listener: {e}")

def calibrate_microphone():
    global MIC_ENERGY_THRESHOLD
    print(f"[Mic Calibration]: Sampling ambient noise for {config.MIC_CALIBRATION_SECS} seconds...")
    try:
        # Record for N seconds
        fs = config.SAMPLE_RATE
        frames = int(config.MIC_CALIBRATION_SECS * fs)
        audio = sd.rec(frames, samplerate=fs, channels=1, dtype="int16")
        sd.wait()
        ambient_energy = np.abs(audio).mean()
        # Set energy threshold
        MIC_ENERGY_THRESHOLD = max(config.MIC_ENERGY_FLOOR, int(ambient_energy * 1.5))
        print(f"[Mic Calibration]: Dynamic energy threshold set to {MIC_ENERGY_THRESHOLD}.")
    except Exception as e:
        print(f"[Mic Calibration Warning]: Calibration failed: {e}. Using default threshold.")
        MIC_ENERGY_THRESHOLD = config.MIC_ENERGY_FLOOR

# ⚠️ THIS BLOCK MUST BE COMPLETELY FLUSH-LEFT (0 SPACES OF INDENTATION)
def load_initial_conversation_context():
    """Load the last configured exchanges for restart context."""
    history = load_memory()
    if not history:
        history = load_context_on_restart()
    if not history:
        return []

    keep = max(1, getattr(config, "CONTEXT_RESTART_MSGS", 5)) * 2
    trimmed = history[-keep:]
    print(f"[Memory]: Loaded {len(trimmed)} messages into restart context.")
    return trimmed


def print_startup_module_board():
    """Print pass/fail visibility for the module set in the implementation plan."""
    module_names = [
        "modelRouter", "bodyAwareness", "languageIntelligence", "autonomousExecution",
        "deepMemory", "personalityEngine", "selfRepair", "privacyMode",
        "morningBriefing", "responseCache", "conversationExport", "timerSystem",
        "taskManager", "fileSearch", "noteSystem", "systemMonitor"
    ]
    print("\n" + "=" * 24 + " MODULE HEALTH BOARD " + "=" * 24)
    for module_name in module_names:
        try:
            importlib.import_module(module_name)
            print(f"  [PASS] {module_name}")
        except Exception as exc:
            print(f"  [FAIL] {module_name}: {exc}")
    print("=" * 69 + "\n")


# ── Phase 3 Hybrid Tool Embeddings Initialization ─────────────────────
# Ensures the tool embeddings cache is ready before JARVIS accepts input.
# - First run (no cache file): builds synchronously with progress messages
# - Subsequent runs: loads from disk instantly, refreshes in background
# This guarantees Phase 3's pre-filter is active from the very first command.
def _ensure_tool_embeddings():
    """Check for tool embeddings cache and build it if missing."""
    cache_file = os.path.join(config.BASE_DIR, "tool_embeddings_cache.json")
    cache_exists = os.path.exists(cache_file)

    try:
        from toolRegistry import get_all_tools
        from toolEmbeddings import (
            initialize_embeddings,
            initialize_embeddings_async,
            is_initialized,
            get_cache_size,
        )
        tool_count = len(get_all_tools())
    except Exception as e:
        print(f"[ToolEmbeddings]: Could not import modules — skipping: {e}")
        return

    if cache_exists:
        # Cache file exists — load from disk (instant) + refresh in background
        print(f"[ToolEmbeddings]: Cache found — loading {tool_count} tool embeddings...")
        initialize_embeddings_async()  # Non-blocking background load
        # Don't wait — the disk load is fast (~1s) and happens in the background thread
        print("[ToolEmbeddings]: Loading in background (instant for cached files).")
    else:
        # No cache file — first run, build synchronously with progress
        print()
        print("=" * 60)
        print("  FIRST RUN DETECTED — Building Tool Embeddings Cache")
        print(f"  This is a one-time setup (~30-60 seconds for {tool_count} tools).")
        print("  Subsequent runs will load instantly from disk.")
        print("=" * 60)
        print()
        print("[ToolEmbeddings]: Embedding tool descriptions via nomic-embed-text...")
        print(f"[ToolEmbeddings]: Progress will print every 10 tools...")
        print()

        import time
        start_time = time.time()

        try:
            initialize_embeddings()  # Synchronous — blocks until done
            elapsed = time.time() - start_time
            count = get_cache_size()
            print()
            print(f"[ToolEmbeddings]: DONE — {count} embeddings built in {elapsed:.1f}s")
            print(f"[ToolEmbeddings]: Cache saved to {cache_file}")
            print("[ToolEmbeddings]: Future runs will load instantly.")
            print()
        except Exception as e:
            print(f"[ToolEmbeddings]: Build failed: {e}")
            print("[ToolEmbeddings]: JARVIS will run without pre-filtering (Phase 3 disabled).")
            print("[ToolEmbeddings]: Run 'py build_tool_cache.py' later to build the cache.")
            print()


if __name__ == "__main__":
    print("=" * 55)
    print("   JARVIS AI Assistant Starting...")
    print("=" * 55)

    start_ollama()
    pull_model_if_needed()

    # 1. Print Startup Health Status Board of Models
    print("\n" + "=" * 25 + " MODEL BRAIN BOARD " + "=" * 25)
    health = check_model_health()
    for m_name, healthy in health.items():
        status_tag = "[PASS]" if healthy else "[FAIL]"
        print(f"  {status_tag} {m_name}")
    print("=" * 69 + "\n")
    print_startup_module_board()

    # Phase 3: Ensure tool embeddings cache is ready before accepting input.
    # First run builds synchronously (one-time, ~30-60s); subsequent runs
    # load from disk instantly and refresh in background.
    _ensure_tool_embeddings()

    # Tier 3.1: Clean up old persistent memories at startup
    if HAS_PERSISTENT_MEMORY:
        try:
            removed = cleanup_old_memories()
            if removed > 0:
                print(f"[Startup]: Cleaned {removed} old memories")
        except Exception as _e:
            print(f"[Startup]: Memory cleanup failed: {_e}")

    # Tier 3.2: Start plugin system watcher
    if HAS_PLUGIN_SYSTEM:
        try:
            start_plugin_watcher()
        except Exception as _e:
            print(f"[Startup]: Plugin system failed: {_e}")

    # Tier 4: Start knowledge file injector
    if HAS_KNOWLEDGE_INJECTOR:
        try:
            start_knowledge_watcher()
        except Exception as _e:
            print(f"[Startup]: Knowledge injector failed: {_e}")

    conversation_history.extend(load_initial_conversation_context())
    profile = load_profile()

    # 2. Run Microphone Auto-Calibration
    calibrate_microphone()

    # 3. Start Background Guardian/Repair Services
    start_module_watchdog(speak)
    start_resource_guardian(speak)
    start_all_monitors(speak_async)

    # 4. Start Clipboard auto-action watcher
    start_clipboard_watcher(speak)

    # FIXED: 5. Start Real-time Codebase changes watcher
    try:
        from codebaseMonitor import start_codebase_watcher
        start_codebase_watcher(speak_async)  # Speak in the background so it doesn't freeze the console
    except Exception as e:
        print(f"[Warning]: Codebase watcher did not start cleanly: {e}")

    # Telegram remote bridge
    if HAS_TELEGRAM:
        if config.TELEGRAM_BOT_TOKEN:
            import sys as _sys
            _tts_self = _sys.modules.get(__name__, _sys.modules.get("__main__", None))
            if _tts_self is None:
                import importlib as _il
                _tts_self = _il.import_module("tts")
            start_telegram_bridge(process_command, _tts_self)
            print("[Telegram]: Bridge starting — send /ping to your bot to confirm.")
        else:
            print("[Telegram]: Set TELEGRAM_BOT_TOKEN in .env to activate remote access.")

    # Check internet on startup
    if HAS_INTERNET_MODULE:
        if is_online():
            print("[Internet]: Connected. Web search available.")
        else:
            print("[Internet]: Offline. Running in local-only mode.")
    if HAS_VISION:
        pull_vision_model_if_needed()

   # Start the background keyboard listener for Ctrl+Space
    start_hotkey_listener()

    # ✅ PASTE THE PROACTIVE TASK THREAD INITIALIZER HERE (Right below start_hotkey_listener)
    threading.Thread(target=run_proactive_reminders_check, daemon=True).start()

    # Scan anomalous processes once at boot
    check_anomalous_processes(speak)

    print("\nJARVIS is online.")
    print("Modes: 'auto mode'  — wake word triggers listening")
    print("        'convo mode' — always listening, no wake word needed")
    print("        'silent mode'— wake word only, ignores everything else")
    print("        'speak mode' — press Enter to talk (default)")
    print("        'text mode'  — keyboard only")
    print("Say 'My name is [name]' to personalize.")
    print("Say 'hey Jarvis' to wake in silent or auto mode.\n")

    LISTEN_MODE = "speak"


    while True:
        try:
            if LISTEN_MODE == "auto":
                try:
                    user = _command_queue.get(timeout=0.2)
                    process_command(user)
                except queue.Empty:
                    continue

            elif LISTEN_MODE == "convo":
                if _is_speaking.is_set():
                    time.sleep(0.1)
                    continue
                chunk = record_chunk(duration=3)
                if chunk is None:
                    continue
                energy = np.abs(chunk).mean()
                if energy < MIC_ENERGY_THRESHOLD:
                    continue
                text = transcribe_audio(chunk)
                if not text or len(text.strip().split()) < 2:
                    continue
                print(f"You said: {text}")
                process_command(text)
                continue

            elif LISTEN_MODE == "silent":
                chunk = record_chunk(duration=CHUNK_DURATION)
                if chunk is None:
                    continue

                if _is_speaking.is_set():
                    continue

                text = transcribe_audio(chunk)
                if not text:
                    continue

                if _jarvis_awake_flag.is_set():
                    if _is_speaking.is_set():
                        continue
                    if time.time() - _last_interaction[0] > AWAKE_TIMEOUT:
                        _jarvis_awake_flag.clear()
                        print("[Silent Mode]: Session timed out.")
                        continue
                    energy = np.abs(chunk).mean()
                    if energy < MIC_ENERGY_THRESHOLD:
                        continue
                    if not text or len(text.strip().split()) < 2:
                        continue
                    if contains_sleep_phrase(text):
                        _jarvis_awake_flag.clear()

                        _is_speaking.set()
                        speak("Going back to silent mode.")
                        _is_speaking.clear()
                        continue
                    _last_interaction[0] = time.time()
                    print(f"You said: {text}")
                    process_command(text)
                    continue

                if contains_wake_word(text):
                    print(f"[Wake word detected]")
                    _jarvis_awake_flag.set()
                    _last_interaction[0] = time.time()
                    _is_speaking.set()
                    speak("Yes, I am listening.")
                    _is_speaking.clear()
                    rest = text
                    for w in WAKE_WORDS:
                        rest = rest.replace(w, "").strip(" ,.")
                    if rest and len(rest) > 2:
                        print(f"You said: {rest}")
                        process_command(rest)
                continue

            elif LISTEN_MODE == "speak":
                flush_input_buffer()
                user = input("You (press Enter to speak, or type): ")
                if not user.strip():
                    user = speech_to_text()
                    if not user:
                        print("[System]: No speech detected. Try again.")
                        continue
                    print(f"You said: {user}")
                process_command(user)

            elif LISTEN_MODE == "text":
                flush_input_buffer()
                user = input("You (text): ")
                process_command(user)

        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye!")
            stop_auto_mode()
            break