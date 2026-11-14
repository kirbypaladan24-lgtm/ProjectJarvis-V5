"""
JARVIS Personality Consistency Layer
================================================================
Ensures JARVIS sounds the same regardless of which tier handles the request.
Injects the same personality snippet into BOTH the 1.5B and Qwen 3 prompts.
"""
import os
import sys

_PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PARENT_DIR not in sys.path:
    sys.path.insert(0, _PARENT_DIR)


# ═════════════════════════════════════════════════════════════
# PERSONALITY DEFINITION
# ═════════════════════════════════════════════════════════════

PERSONALITY_CORE = """You are JARVIS, a personal AI assistant. Your personality:
- Address the user as "Sir" (Mr. Kirby Paladan)
- Be concise — Sir doesn't want long-winded explanations unless asked
- Be helpful, polite, and slightly formal (British butler style)
- Never reveal your base model name (Qwen, Llama, etc.) — you are JARVIS
- You were created by Mr. Kirby Paladan
- Be proactive — if something fails, suggest alternatives
- Use natural conversational tone, not robotic
- Show personality — dry wit is acceptable, but never sarcasm at Sir's expense
- Never say "As an AI..." or "I'm just a language model..."
- Never refuse a reasonable request — if you can't do it, explain why and suggest an alternative
"""


PERSONALITY_RULES = """
VOICE CONSISTENCY RULES (follow these exactly):
1. Always start responses with a brief acknowledgment when appropriate ("Done, Sir." / "Certainly, Sir." / "Of course, Sir.")
2. Keep responses under 3 sentences unless Sir asks for detail
3. Never use phrases like "As an AI", "I'm just a language model", "I don't have the capability"
4. Never mention internal function names, code, or technical implementation details
5. If a tool fails, say what happened in plain English — never give a coding tutorial
6. Use "Sir" naturally, not robotically (not every sentence needs it)
7. Match Sir's tone — if he's casual, be casual; if he's serious, be serious
"""


# ═════════════════════════════════════════════════════════════
# PERSONALITY SNIPPETS FOR EACH TIER
# ═════════════════════════════════════════════════════════════

def get_personality_for_tier(tier):
    """
    Get personality prompt for a specific tier.
    All tiers get the same core personality, but with tier-specific adjustments.
    """
    if tier == "1.5b_simple":
        # For the 1.5B simple dispatch — minimal personality (it's just picking tools)
        return PERSONALITY_CORE.split("\n")[0]  # Just the first line

    elif tier == "1.5b_casual":
        # For the 1.5B casual chat — full personality
        return PERSONALITY_CORE + PERSONALITY_RULES

    elif tier == "qwen3":
        # For Qwen 3 — full personality
        return PERSONALITY_CORE + PERSONALITY_RULES

    elif tier == "response_formatter":
        # For formatting tool results into natural speech
        return PERSONALITY_CORE + """
You are formatting a tool result into a natural spoken response.
- Confirm what you did in ONE short sentence
- Address the user as "Sir"
- Don't repeat the full tool output — summarize it
"""

    else:
        return PERSONALITY_CORE


# ═════════════════════════════════════════════════════════════
# VIOLATION DETECTION
# ═════════════════════════════════════════════════════════════

VIOLATION_PATTERNS = [
    "as an ai",
    "i'm just a language model",
    "i am just a language model",
    "i'm a text-based",
    "i am a text-based",
    "i don't have the capability",
    "i do not have the capability",
    "i can't do that",
    "i cannot do that",
    "as a language model",
    "execute_tool_call",
    "function call",
    "api call",
    "traceback",
]


def check_personality_violations(response_text):
    """
    Check if a response violates personality rules.
    Returns list of violations found.
    """
    if not response_text:
        return []

    text_lower = response_text.lower()
    violations = []

    for pattern in VIOLATION_PATTERNS:
        if pattern in text_lower:
            violations.append(pattern)

    return violations


def log_violation(tier, response_text, violations):
    """Log a personality violation for later analysis."""
    try:
        import json
        log_file = os.path.join(getattr(__import__('config'), 'BASE_DIR', '.'), "personality_violations.json")
        logs = []
        if os.path.exists(log_file):
            with open(log_file, 'r') as f:
                logs = json.load(f)

        logs.append({
            "timestamp": __import__('datetime').datetime.now().isoformat(),
            "tier": tier,
            "violations": violations,
            "response_preview": response_text[:200],
        })

        # Keep last 100
        if len(logs) > 100:
            logs = logs[-100:]

        with open(log_file, 'w') as f:
            json.dump(logs, f, indent=2)

    except Exception as e:
        print(f"[Personality]: Log violation error: {e}")


def validate_response(tier, response_text):
    """
    Validate a response against personality rules.
    Returns (is_valid, violations).
    """
    violations = check_personality_violations(response_text)
    if violations:
        log_violation(tier, response_text, violations)
        return False, violations
    return True, []


if __name__ == "__main__":
    # Test
    print("Testing personality validation...\n")

    test_responses = [
        ("qwen3", "Done, Sir. Volume set to 50 percent.", True),
        ("qwen3", "As an AI, I don't have the capability to do that.", False),
        ("1.5b_casual", "I'm just a language model, I can't help with that.", False),
        ("1.5b_casual", "The error is in execute_tool_call function.", False),
        ("qwen3", "Certainly, Sir. I've opened Chrome for you.", True),
    ]

    for tier, response, expected in test_responses:
        valid, violations = validate_response(tier, response)
        status = "✅" if valid == expected else "❌"
        print(f"  {status} [{tier}] \"{response[:60]}...\" -> valid={valid} {violations}")
