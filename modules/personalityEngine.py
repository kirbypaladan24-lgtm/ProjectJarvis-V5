import os
import sys
import json

# Add root folder to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    import config
except ImportError:
    class config:
        PERSONALITY_FILE = "personality_state.json"

DEFAULT_PERSONALITY = {
    "tone": "helpful, polite, and deeply loyal",
    "humor_level": 0.3,
    "speech_rhythm": "eloquent, structured, and concise",
    "emotional_adjustment": "normal"
}

def load_personality_state():
    """Reads personality_state.json from disk."""
    if os.path.exists(config.PERSONALITY_FILE):
        try:
            with open(config.PERSONALITY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return DEFAULT_PERSONALITY.copy()

def save_personality_state(tone, humor_level, speech_rhythm):
    """Saves personality parameters to disk."""
    state = {
        "tone": tone,
        "humor_level": float(humor_level),
        "speech_rhythm": speech_rhythm,
        "emotional_adjustment": "normal"
    }
    try:
        with open(config.PERSONALITY_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        return "Personality profile updated successfully, Sir."
    except Exception as e:
        return f"Could not update personality: {e}"

def adapt_tone(emotional_state):
    """
    Adjusts personality state parameters on-the-fly based on inferred user emotion.
    For example, if the user is tired or frustrated, soften the tone and increase brevity.
    """
    state = load_personality_state()
    state["emotional_adjustment"] = emotional_state
    
    if emotional_state == "frustrated":
        state["tone"] = "extremely gentle, reassuring, and highly supportive"
        state["speech_rhythm"] = "brief, straightforward, and highly comforting"
    elif emotional_state == "tired":
        state["tone"] = "calm, quiet, and unobtrusive"
        state["speech_rhythm"] = "very brief and low-key"
    elif emotional_state == "pleased":
        state["tone"] = "warm, slightly witty, and highly appreciative"
        state["speech_rhythm"] = "engaging and expressive"
    else:
        # Revert to standard
        pass
        
    return state

def get_personality_prompt(emotional_state="neutral"):
    """
    Returns the personality system prompt snippet to inject.
    """
    state = adapt_tone(emotional_state)
    
    prompt = f"""
YOUR CURRENT PERSONALITY STATE:
- Tone: You are {state['tone']}.
- Humor Level: {state['humor_level']} out of 1.0 (inject subtle humor/wit only if humor level is above 0.5).
- Speech Rhythm: Speak in a {state['speech_rhythm']} manner.
"""
    if state["emotional_adjustment"] in ["frustrated", "tired"]:
        prompt += f"- Emotional Note: The user seems {state['emotional_adjustment']}. Adjust your style by being extremely supportive, brief, and avoiding unnecessary details."
        
    return prompt
