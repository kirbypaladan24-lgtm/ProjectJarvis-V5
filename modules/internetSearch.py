"""
Internet Search Module for JARVIS (UPGRADED)
- Uses 'ddgs' for highly reliable web and news scraping
- Weather lookup via wttr.in
- Wikipedia summary
- Dedicated Free API for Live Exchange Rates
"""
import re
import socket
import requests
import subprocess
import sys
from datetime import datetime

# Auto-install ddgs if missing
try:
    from ddgs import DDGS
except ImportError:
    print("[Internet]: Installing ddgs library...")
    subprocess.run([sys.executable, "-m", "pip", "install", "ddgs"], check=True)
    from ddgs import DDGS

import time

# ─────────────────────────────────────────────
# CONNECTION CHECK
# ─────────────────────────────────────────────

# PERF #4: Cache is_online result for 30s — network state rarely changes mid-session
_online_cache_result    = None
_online_cache_ts        = 0.0
_ONLINE_CACHE_TTL       = 30.0

def is_online(timeout=3):
    """Check internet availability with a 30s TTL cache to avoid per-request socket tests."""
    global _online_cache_result, _online_cache_ts
    now = time.time()
    if _online_cache_result is not None and (now - _online_cache_ts) < _ONLINE_CACHE_TTL:
        return _online_cache_result
    try:
        socket.setdefaulttimeout(timeout)
        with socket.create_connection(("8.8.8.8", 53)):
            _online_cache_result = True
    except OSError:
        _online_cache_result = False
    _online_cache_ts = time.time()
    return _online_cache_result

def require_internet():
    if not is_online():
        return "I cannot do that right now. There is no internet connection available."
    return None

# ─────────────────────────────────────────────
# LIVE EXCHANGE RATES (No API Key required)
# ─────────────────────────────────────────────

def get_exchange_rate():
    """Fetches highly accurate live exchange rates from a free public API."""
    err = require_internet()
    if err: return err

    try:
        url = "https://open.er-api.com/v6/latest/USD"
        r = requests.get(url, timeout=5)
        data = r.json()
        if data.get("result") == "success":
            php = data["rates"].get("PHP", "Unknown")
            eur = data["rates"].get("EUR", "Unknown")
            gbp = data["rates"].get("GBP", "Unknown")
            jpy = data["rates"].get("JPY", "Unknown")
            
            return f"""LIVE EXCHANGE RATES (Base: 1 US Dollar / USD):
- Philippine Peso (PHP): {php}
- Euro (EUR): {eur}
- British Pound (GBP): {gbp}
- Japanese Yen (JPY): {jpy}
(Data provided accurately by open.er-api)"""
    except Exception as e:
        print(f"[Exchange Rate Error]: {e}")
        return None

# ─────────────────────────────────────────────
# WEB SEARCH — Reliable DuckDuckGo Library
# ─────────────────────────────────────────────

def web_search(query, max_results=5):
    """Search the web using the DDGS library with a fallback."""
    err = require_internet()
    if err: return err

    results_text = []

    # Attempt 1: Using the DDGS package
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
            for r in results:
                title = r.get("title", "")
                body = r.get("body", "")
                if title and body:
                    results_text.append(f"Title: {title}\nSnippet: {body}")
    except Exception as e:
        print(f"[DDGS Warning]: {e}")

    # Attempt 2: Fallback to direct HTML scrape if DDGS is blocked
    if not results_text:
        try:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            r = requests.get("https://html.duckduckgo.com/html/", params={"q": query}, headers=headers, timeout=8)
            snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', r.text, re.DOTALL)
            
            for s in snippets[:max_results]:
                clean_s = re.sub(r'<[^>]+>', '', s).strip()
                if clean_s:
                    results_text.append(f"Snippet: {clean_s}")
        except Exception as e:
            print(f"[Fallback Search Error]: {e}")

    if results_text:
        return f"Search results for '{query}':\n\n" + "\n\n".join(results_text)
    
    return f"No readable results found for '{query}'. The search engine might be blocking the request."

# ─────────────────────────────────────────────
# GEO-IP LOCATION DETECTION
# ─────────────────────────────────────────────

_geo_cache = None
_geo_cache_ts = 0.0
_GEO_CACHE_TTL = 600.0   # 10 min — location doesn't change often

def get_current_location():
    """
    Detect the user's current city and country via IP geolocation.
    Uses free APIs (no key required). Returns dict with 'city', 'region',
    'country', 'lat', 'lon' or None on failure. Cached for 10 minutes.
    """
    global _geo_cache, _geo_cache_ts
    now = time.time()
    if _geo_cache is not None and (now - _geo_cache_ts) < _GEO_CACHE_TTL:
        return _geo_cache

    err = require_internet()
    if err:
        return _geo_cache  # Return stale cache if offline

    # Attempt 1: ip-api.com (free, no key, 45 req/min)
    try:
        r = requests.get("http://ip-api.com/json/?fields=status,city,regionName,country,lat,lon", timeout=5)
        if r.status_code == 200:
            data = r.json()
            if data.get("status") == "success" and data.get("city"):
                _geo_cache = {
                    "city": data["city"],
                    "region": data.get("regionName", ""),
                    "country": data.get("country", ""),
                    "lat": data.get("lat"),
                    "lon": data.get("lon"),
                }
                _geo_cache_ts = time.time()
                print(f"[GeoIP]: Detected location — {_geo_cache['city']}, {_geo_cache['country']}")
                return _geo_cache
    except Exception as e:
        print(f"[GeoIP]: ip-api.com failed: {e}")

    # Attempt 2: ipinfo.io fallback (free, 50k/month)
    try:
        r = requests.get("https://ipinfo.io/json", timeout=5, headers={"User-Agent": "JARVIS-AI/1.0"})
        if r.status_code == 200:
            data = r.json()
            if data.get("city"):
                loc = data.get("loc", "0,0").split(",")
                _geo_cache = {
                    "city": data["city"],
                    "region": data.get("region", ""),
                    "country": data.get("country", ""),
                    "lat": float(loc[0]) if len(loc) == 2 else None,
                    "lon": float(loc[1]) if len(loc) == 2 else None,
                }
                _geo_cache_ts = time.time()
                print(f"[GeoIP]: Detected location — {_geo_cache['city']}, {_geo_cache['country']}")
                return _geo_cache
    except Exception as e:
        print(f"[GeoIP]: ipinfo.io failed: {e}")

    return _geo_cache  # Return stale cache or None

# ─────────────────────────────────────────────
# WEATHER
# ─────────────────────────────────────────────

def get_weather(location="auto"):
    """Get current weather using wttr.in."""
    err = require_internet()
    if err: return err

    resolved_location = location
    if location == "auto":
        # Priority 1: Check user profile location override first
        try:
            from tts import load_profile
            profile = load_profile()
            if profile and isinstance(profile, dict) and profile.get("city"):
                resolved_location = profile["city"]
        except Exception:
            pass

        # Priority 2: Try dynamic Geo-IP location detection
        if resolved_location == "auto":
            loc_data = get_current_location()
            if loc_data and isinstance(loc_data, dict) and loc_data.get("city"):
                resolved_location = loc_data["city"]

    try:
        url = f"https://wttr.in/{resolved_location}"
        r = requests.get(url, params={"format": 3}, timeout=8, headers={"User-Agent": "curl/7.0"})
        weather_text = r.text.strip()

        if weather_text and len(weather_text) > 3:
            weather_text = re.sub(r'\x1b\[[0-9;]*m', '', weather_text)
            if location == "auto" and resolved_location != "auto":
                return f"Current weather in {resolved_location}: {weather_text}"
            return f"Current weather: {weather_text}"

        r2 = requests.get(url, params={"format": "%l:+%C,+%t,+feels+like+%f,+humidity+%h,+wind+%w"}, timeout=8, headers={"User-Agent": "curl/7.0"})
        if location == "auto" and resolved_location != "auto":
            return f"Weather in {resolved_location}: {r2.text.strip()}"
        return f"Weather: {r2.text.strip()}"
    except Exception as e:
        return f"Weather error: {e}"

# ─────────────────────────────────────────────
# NEWS HEADLINES
# ─────────────────────────────────────────────

def get_news(topic=None, max_headlines=5):
    """Get latest news using DDGS for specific topics, or BBC RSS for general headlines."""
    err = require_internet()
    if err: return err

    try:
        if topic:
            results_text = []
            with DDGS() as ddgs:
                news_results = list(ddgs.news(topic, max_results=max_headlines))
                for r in news_results:
                    title = r.get("title", "")
                    body = r.get("body", "")
                    date = r.get("date", "Recent")
                    source = r.get("source", "News")
                    results_text.append(f"- [{source} | {date}] {title}: {body}")

            if results_text:
                return f"Latest news regarding '{topic}':\n" + "\n".join(results_text)
            return f"No news found about '{topic}'."
            
        else:
            feed_url = "https://feeds.bbci.co.uk/news/rss.xml"
            r = requests.get(feed_url, timeout=8, headers={"User-Agent": "JARVIS-AI/1.0"})
            titles = re.findall(r'<title><!\[CDATA\[(.*?)\]\]></title>', r.text)
            titles = [t.strip() for t in titles[1:max_headlines+1] if t.strip()]

            if titles:
                result = "Latest general headlines:\n"
                for i, title in enumerate(titles, 1):
                    result += f"  {i}. {title}\n"
                return result
            return "Could not retrieve general news headlines."
    except Exception as e:
        return f"News error: {e}"

# ─────────────────────────────────────────────
# WIKIPEDIA QUICK SUMMARY
# ─────────────────────────────────────────────

def wikipedia_summary(topic, sentences=3):
    err = require_internet()
    if err: return err

    try:
        r = requests.get(
            "https://en.wikipedia.org/api/rest_v1/page/summary/" + requests.utils.quote(topic),
            timeout=8, headers={"User-Agent": "JARVIS-AI/1.0"}
        )
        if r.status_code == 200:
            data = r.json()
            extract = data.get("extract", "")
            if extract:
                sentence_list = re.split(r'(?<=[.!?])\s+', extract)
                return " ".join(sentence_list[:sentences])
        return f"No Wikipedia article found for '{topic}'."
    except Exception as e:
        return f"Wikipedia error: {e}"

# ─────────────────────────────────────────────
# COMMAND HANDLER
# ─────────────────────────────────────────────

def handle_internet_commands(user_input):
    text = re.sub(r'[.,!?;:]+', '', user_input.lower().strip())

    # Exchange Rate / Currencies
    currency_match = re.search(r'(?:exchange rate|how much is|currency).*?(dollar|peso|usd|php|euro|pound)', text)
    if currency_match:
        rates = get_exchange_rate()
        if rates:
            return rates

    # Weather
    weather_match = re.search(r'(?:what(?:\'s| is)(?: the)? weather|weather|temperature|how hot|how cold|is it raining|forecast)(?:\s+(?:in|at|for)\s+(.+))?$', text)
    if weather_match:
        location = weather_match.group(1).strip() if weather_match.group(1) else "auto"
        return get_weather(location)

    # News
    news_match = re.search(r'(?:latest|recent|today\'?s?|current|whats|what is)\s+(?:news|headlines|updates?)(?:\s+(?:about|on|for)\s+(.+))?$', text)
    if news_match:
        topic = news_match.group(1).strip() if news_match.group(1) else None
        return get_news(topic)

    if any(p in text for p in ["show me the news", "tell me the news", "news today", "top news", "whats happening"]):
        return get_news()

    # Wikipedia
    wiki_match = re.search(r'(?:wikipedia|wiki|tell me about|define)\s+(.+)$', text)
    if wiki_match:
        topic = wiki_match.group(1).strip()
        skip = ["volume", "brightness", "spotify", "notepad", "screenshot", "open", "close", "task", "note", "time", "weather"]
        if not any(s in topic for s in skip):
            result = wikipedia_summary(topic)
            if result and "No Wikipedia" not in result and "error" not in result.lower():
                return result

    # Standard Web Search Triggers
    search_patterns = [
        r'(?:search|google|look up|search for|search the web for|find online|search online)\s+(?:for\s+)?(.+)$',
    ]
    for pattern in search_patterns:
        match = re.search(pattern, text)
        if match:
            query = match.group(1).strip()
            local_keywords = ["volume", "brightness", "open", "close", "notepad", "screenshot", "task", "note"]
            if not any(kw in query for kw in local_keywords):
                return web_search(query)

    return None