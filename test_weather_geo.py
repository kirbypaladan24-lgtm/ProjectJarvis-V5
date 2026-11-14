import sys
import os
import json

# Ensure modules folder is on path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "modules"))

try:
    from internetSearch import get_current_location, get_weather, is_online
    from morningBriefing import get_morning_briefing
    from tts import load_profile, save_profile
except ImportError as e:
    print(f"Error importing modules: {e}")
    sys.exit(1)

# Ensure console supports printing UTF-8 characters (like temperature symbols / emojis)
try:
    sys.stdout.reconfigure(encoding='utf-8')
except AttributeError:
    # Older Python versions fallback
    pass

def run_test():
    print("=" * 60)
    print("JARVIS GEOLOCATION & WEATHER DIAGNOSTIC TEST")
    print("=" * 60)
    
    # 1. Connection Check
    online = is_online()
    print(f"Internet Status: {'ONLINE' if online else 'OFFLINE'}")
    if not online:
        print("[!] Warning: Internet is required for geolocation and weather lookup.")
        print("=" * 60)
        return

    # Backup original profile
    original_profile = load_profile()
    
    try:
        # TEST A: Dynamic Geo-IP Geolocation
        print("\n--- TEST A: DYNAMIC GEO-IP GEOLOCATION (No profile override) ---")
        
        # Clear profile city override for this test
        temp_profile = original_profile.copy()
        if "city" in temp_profile:
            del temp_profile["city"]
        save_profile(temp_profile)
        
        print("\n1. Detecting current location via IP...")
        loc = get_current_location()
        if loc and isinstance(loc, dict):
            print(f"   - Detected City:    {loc.get('city')}")
            print(f"   - Region & Country: {loc.get('region')}, {loc.get('country')}")
        else:
            print("   - [!] Location detection failed (returned None/Invalid).")

        print("\n2. Weather lookup for dynamic location ('auto'):")
        weather_auto = get_weather("auto")
        print(f"   - Result: {weather_auto}")

        print("\n3. Morning Briefing with dynamic location:")
        briefing_auto = get_morning_briefing()
        print(f"   - Briefing: {briefing_auto}")


        # TEST B: Custom Profile Override (Goa, Camarines Sur)
        print("\n--- TEST B: PROFILE OVERRIDE (Goa, Camarines Sur) ---")
        
        # Set profile city override
        override_profile = original_profile.copy()
        override_profile["city"] = "Goa, Camarines Sur"
        save_profile(override_profile)
        print("\n1. Profile location override set to: 'Goa, Camarines Sur'")
        
        print("\n2. Weather lookup for override location ('auto'):")
        weather_override = get_weather("auto")
        print(f"   - Result: {weather_override}")

        print("\n3. Morning Briefing with override location:")
        briefing_override = get_morning_briefing()
        print(f"   - Briefing: {briefing_override}")

    finally:
        # Restore original profile
        save_profile(original_profile)
        print("\n" + "=" * 60)
        print("Original profile state restored.")
        print("=" * 60)
        print("TEST COMPLETED")
        print("=" * 60)

if __name__ == "__main__":
    run_test()
