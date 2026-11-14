"""
Spotify Control Module for JARVIS (UPGRADED)
- Authenticates with Spotify API (or falls back to Free Mode)
- Controls playback (pause, play, skip, previous)
- Searches local files for music before checking Spotify
- Supports web-app browser search fallbacks
"""
import subprocess
import sys
import re
import os

# Add root folder to sys.path so nested modules can resolve config.py in the parent directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import config
except ImportError:
    # Safe inline fallback if config.py cannot be found
    class config:
        SPOTIFY_CLIENT_ID     = ""
        SPOTIFY_CLIENT_SECRET = ""
        SPOTIFY_REDIRECT_URI  = "http://127.0.0.1:8888/callback"

# Auto-install spotipy if missing
try:
    import spotipy
    from spotipy.oauth2 import SpotifyOAuth
except ImportError:
    print("[Spotify]: Installing spotipy...")
    subprocess.run([sys.executable, "-m", "pip", "install", "spotipy"], check=True)
    import spotipy
    from spotipy.oauth2 import SpotifyOAuth

# ─────────────────────────────────────────────
# CREDENTIALS — dynamically loaded from config
# ─────────────────────────────────────────────
SPOTIFY_CLIENT_ID     = config.SPOTIFY_CLIENT_ID
SPOTIFY_CLIENT_SECRET = config.SPOTIFY_CLIENT_SECRET
SPOTIFY_REDIRECT_URI  = config.SPOTIFY_REDIRECT_URI

SCOPE = (
    "user-read-playback-state "
    "user-modify-playback-state "
    "user-read-currently-playing "
    "streaming "
    "playlist-read-private "
    "user-library-read"
)

_sp = None

def get_spotify():
    """Returns authenticated Spotify client, creates it if needed."""
    global _sp
    if _sp is not None:
        return _sp

    if "YOUR_CLIENT_ID_HERE" in SPOTIFY_CLIENT_ID:
        return None  # credentials not set yet

    try:
        auth = SpotifyOAuth(
            client_id=SPOTIFY_CLIENT_ID,
            client_secret=SPOTIFY_CLIENT_SECRET,
            redirect_uri=SPOTIFY_REDIRECT_URI,
            scope=SCOPE,
            open_browser=True,
            cache_path=".spotify_cache"
        )
        _sp = spotipy.Spotify(auth_manager=auth)
        _sp.current_user()  # test the connection
        return _sp
    except Exception as e:
        err = str(e)
        if "403" in err or "Premium" in err or "premium" in err:
            print("[Spotify]: Premium account required for API control. Using free fallback mode.")
            _sp = "FREE_MODE"  # flag for free mode
            return _sp
        print(f"[Spotify]: Auth error: {e}")
        return None


def is_free_mode():
    return _sp == "FREE_MODE"

def get_active_device():
    """Get the first available active Spotify device."""
    sp = get_spotify()
    if not sp or is_free_mode():
        return None
    try:
        devices = sp.devices()
        device_list = devices.get("devices", [])
        if not device_list:
            return None
        for d in device_list:
            if d["is_active"]:
                return d["id"]
        return device_list[0]["id"]
    except Exception:
        return None


def open_spotify_search(query):
    """Open Spotify app and search for a song — works without Premium."""
    import urllib.parse
    query_encoded = urllib.parse.quote(query)
    # Open Spotify with search URI — works on Windows with Spotify installed
    search_uri = f"spotify:search:{query_encoded}"
    try:
        subprocess.Popen(["start", search_uri], shell=True)
        return f"Opening Spotify and searching for {query}. Press play when it appears."
    except Exception as e:
        # Fallback: open Spotify web player search
        url = f"https://open.spotify.com/search/{query_encoded}"
        subprocess.Popen(["start", url], shell=True)
        return f"Opening Spotify web search for {query}."


# ─────────────────────────────────────────────
# LOCAL PLAYBACK
# ─────────────────────────────────────────────

def play_local_file(query):
    """Searches local storage for audio files and plays them."""
    try:
        from fileSearch import search_files
        # Search for audio files (mp3, wav)
        results = search_files(query, file_type=".mp3")
        if not results:
            results = search_files(query, file_type=".wav")
        
        if results:
            # Play the first match
            os.startfile(results[0])
            return f"Playing {os.path.basename(results[0])} from your local files, Sir."
    except Exception as e:
        print(f"[Local Music Error]: {e}")
    return None


# ─────────────────────────────────────────────
# PLAYBACK CONTROLS
# ─────────────────────────────────────────────

def play_song(query):
    """Search for a song/artist/album (Local or Spotify) and play it."""
    
    # 1. Local Search First
    local_res = play_local_file(query)
    if local_res: return local_res

    # 2. Spotify Search
    get_spotify()  # ensure initialized

    # Free mode — open Spotify app with search
    if is_free_mode():
        return open_spotify_search(query)

    sp = get_spotify()
    if not sp:
        return "Spotify is not connected. Please set your Client ID and Secret in spotifyControl.py."

    try:
        device_id = get_active_device()
        if not device_id:
            subprocess.Popen("spotify", shell=True)
            import time
            time.sleep(3)
            device_id = get_active_device()
            if not device_id:
                return open_spotify_search(query)

        results = sp.search(q=query, limit=1, type="track")
        tracks = results.get("tracks", {}).get("items", [])

        if not tracks:
            results = sp.search(q=query, limit=1, type="artist")
            artists = results.get("artists", {}).get("items", [])
            if artists:
                artist_uri = artists[0]["uri"]
                sp.start_playback(device_id=device_id, context_uri=artist_uri)
                return f"Playing music by {artists[0]['name']} on Spotify."
            return open_spotify_search(query)

        track = tracks[0]
        track_name = track["name"]
        artist_name = track["artists"][0]["name"]
        track_uri = track["uri"]

        sp.start_playback(device_id=device_id, uris=[track_uri])
        return f"Playing {track_name} by {artist_name} on Spotify."

    except spotipy.exceptions.SpotifyException as e:
        if "Premium" in str(e):
            return open_spotify_search(query)
        return f"Spotify error: {e}"
    except Exception as e:
        return f"Spotify error: {e}"


def pause_music():
    if is_free_mode():
        return "Pause is not available without Spotify Premium. Please pause manually."
    sp = get_spotify()
    if not sp:
        return "Spotify is not connected."
    try:
        sp.pause_playback()
        return "Music paused."
    except Exception as e:
        return f"Could not pause: {e}"


def resume_music():
    if is_free_mode():
        return "Resume control is not available without Spotify Premium. Please press play manually."
    sp = get_spotify()
    if not sp:
        return "Spotify is not connected."
    try:
        device_id = get_active_device()
        sp.start_playback(device_id=device_id)
        return "Music resumed."
    except Exception as e:
        return f"Could not resume: {e}"


def next_track():
    if is_free_mode():
        return "Track skipping is not available without Spotify Premium."
    sp = get_spotify()
    if not sp:
        return "Spotify is not connected."
    try:
        sp.next_track()
        import time; time.sleep(0.5)
        current = sp.current_playback()
        if current and current.get("item"):
            name = current["item"]["name"]
            artist = current["item"]["artists"][0]["name"]
            return f"Skipped. Now playing {name} by {artist}."
        return "Skipped to next track."
    except Exception as e:
        return f"Could not skip: {e}"


def previous_track():
    if is_free_mode():
        return "Track control is not available without Spotify Premium."
    sp = get_spotify()
    if not sp:
        return "Spotify is not connected."
    try:
        sp.previous_track()
        import time; time.sleep(0.5)
        current = sp.current_playback()
        if current and current.get("item"):
            name = current["item"]["name"]
            artist = current["item"]["artists"][0]["name"]
            return f"Going back. Now playing {name} by {artist}."
        return "Went back to previous track."
    except Exception as e:
        return f"Could not go back: {e}"


def set_spotify_volume(percent):
    if is_free_mode():
        return "Spotify volume control is not available without Premium. Use system volume instead."
    sp = get_spotify()
    if not sp:
        return "Spotify is not connected."
    try:
        percent = max(0, min(100, int(percent)))
        device_id = get_active_device()
        sp.volume(percent, device_id=device_id)
        return f"Spotify volume set to {percent} percent."
    except Exception as e:
        return f"Could not set Spotify volume: {e}"


def what_is_playing():
    if is_free_mode():
        return "Track info is not available without Spotify Premium."
    sp = get_spotify()
    if not sp:
        return "Spotify is not connected."
    try:
        current = sp.current_playback()
        if not current or not current.get("item"):
            return "Nothing is currently playing on Spotify."
        name = current["item"]["name"]
        artist = current["item"]["artists"][0]["name"]
        status = "playing" if current["is_playing"] else "paused"
        return f"Currently {status}: {name} by {artist}."
    except Exception as e:
        return f"Could not get current track: {e}"


def stop_music():
    return pause_music()


# ─────────────────────────────────────────────
# COMMAND PARSER — called from JARVIS
# ─────────────────────────────────────────────

def handle_spotify_command(user_input):
    """
    Parse user input for Spotify commands.
    Returns response string if handled, None otherwise.
    """
    text = re.sub(r'[.,!?;:]+', '', user_input.lower().strip())

    # What's playing
    if any(p in text for p in ["what's playing", "what is playing", "current song",
                                "what song", "now playing", "whats playing"]):
        return what_is_playing()

    # Pause / stop
    if any(p in text for p in ["pause", "stop the music", "stop music", "stop playing",
                                "stop spotify", "pause the music", "pause music"]):
        return pause_music()

    # Resume
    if any(p in text for p in ["resume", "continue playing", "unpause", "play again",
                                "keep playing"]):
        return resume_music()

    # Next
    if any(p in text for p in ["next song", "next track", "skip", "skip this",
                                "next one", "play next"]):
        return next_track()

    # Previous
    if any(p in text for p in ["previous song", "previous track", "go back", "last song",
                                "play previous", "back to previous"]):
        return previous_track()

    # Spotify volume
    vol_match = re.search(r'spotify\s+volume\s+(?:to\s+)?(\d+)', text)
    if vol_match:
        return set_spotify_volume(int(vol_match.group(1)))

    # Play a specific song/artist — most flexible pattern
    play_match = re.search(
        r'(?:play|put on|start playing|i want to hear|can you play|'
        r'play me|queue|listen to)\s+(.+?)(?:\s+on spotify)?$',
        text
    )
    if play_match:
        query = play_match.group(1).strip()
        # Filter out non-song words
        query = re.sub(r'\b(some|a|the|please|for me|right now)\b', '', query).strip()
        if query:
            return play_song(query)

    return None