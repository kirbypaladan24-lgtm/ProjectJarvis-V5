import os
import sys
from datetime import datetime

# Add root folder to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    import config
except ImportError:
    class config:
        MORNING_BRIEFING_START = 5
        MORNING_BRIEFING_END = 12

def get_morning_briefing():
    """
    Construct a personalized morning briefing.
    Checks time, weather (if internet available), and task count.
    """
    now = datetime.now()
    hour = now.hour
    
    # Verify if it's morning
    if not (config.MORNING_BRIEFING_START <= hour < config.MORNING_BRIEFING_END):
        return "Sir, the morning briefing is only available between 5:00 AM and 12:00 PM."
        
    time_str = now.strftime("%I:%M %p")
    date_str = now.strftime("%A, %B %d")
    
    # 1. Greeting
    greeting = f"Good morning, Sir. It is currently {time_str} on {date_str}."
    
    # 2. Tasks count
    tasks_info = "You have no pending tasks on your checklist today."
    try:
        from taskManager import list_tasks
        # list_tasks() returns a string. Let's parse it or read tasks.json directly.
        tasks_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tasks.json")
        if os.path.exists(tasks_file):
            import json
            with open(tasks_file, "r", encoding="utf-8") as f:
                tasks = json.load(f)
            pending = [t for t in tasks if not t.get("completed")]
            if pending:
                tasks_info = f"You have {len(pending)} pending tasks scheduled on your plate today."
    except Exception:
        pass
        
    # 3. Weather
    weather_info = ""
    try:
        from internetSearch import is_online, get_weather, get_current_location
        if is_online():
            # Priority 1: Check user profile location override first
            from tts import load_profile
            profile = load_profile()
            city = profile.get("city")
            
            # Priority 2: Try dynamic Geo-IP location detection
            if not city:
                loc_data = get_current_location()
                if loc_data and isinstance(loc_data, dict) and loc_data.get("city"):
                    city = loc_data["city"]
            
            # Priority 3: Fallback to config default
            if not city:
                city = getattr(config, "DEFAULT_CITY", "Manila")
            
            weather_text = get_weather(city)
            if weather_text and "error" not in weather_text.lower():
                weather_info = f" Here is your local weather update: {weather_text}"
    except Exception:
        pass

    # FIXED: Restored truncated compilation blocks
    briefing = f"{greeting} {tasks_info}{weather_info} Have a highly productive day ahead."
    return briefing