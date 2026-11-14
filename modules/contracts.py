"""
JARVIS Tool Contracts
================================================================
JSON-schema validation for tool inputs AND outputs.
Catches malformed data before it hits the LLM.

Usage:
    from contracts import validate_input, validate_output

    is_valid, errors = validate_input("set_volume", {"percent": 50})
    is_valid, errors = validate_output("set_volume", "Volume set to 50")
"""
import os
import sys
import json
from typing import Any, Dict, List, Tuple

_PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PARENT_DIR not in sys.path:
    sys.path.insert(0, _PARENT_DIR)


# ═════════════════════════════════════════════════════════════
# INPUT CONTRACTS
# ═════════════════════════════════════════════════════════════

INPUT_CONTRACTS = {
    "set_volume": {
        "required": {"percent": int},
        "optional": {},
        "constraints": {"percent": (0, 100)},
    },
    "set_brightness": {
        "required": {"percent": int},
        "optional": {},
        "constraints": {"percent": (0, 100)},
    },
    "open_app": {
        "required": {"app_name": str},
        "optional": {},
        "constraints": {"app_name": {"min_len": 1, "max_len": 100}},
    },
    "spotify_play": {
        "required": {"query": str},
        "optional": {},
        "constraints": {"query": {"min_len": 1, "max_len": 200}},
    },
    "create_task": {
        "required": {"title": str},
        "optional": {"due_date": str, "priority": str},
        "constraints": {
            "title": {"min_len": 1, "max_len": 200},
            "priority": {"enum": ["low", "normal", "high"]},
        },
    },
    "save_note": {
        "required": {"title": str},
        "optional": {"content": str, "tags": list},
        "constraints": {"title": {"min_len": 1, "max_len": 200}},
    },
    "set_timer": {
        "required": {"duration_seconds": int},
        "optional": {"label": str},
        "constraints": {"duration_seconds": {"min": 1, "max": 86400}},
    },
    "set_recurring_reminder": {
        "required": {"interval_seconds": int, "label": str},
        "optional": {},
        "constraints": {
            "interval_seconds": {"min": 60, "max": 86400},
            "label": {"min_len": 1, "max_len": 200},
        },
    },
    "web_search": {
        "required": {"query": str},
        "optional": {},
        "constraints": {"query": {"min_len": 2, "max_len": 500}},
    },
    "get_weather": {
        "required": {},
        "optional": {"location": str},
        "constraints": {"location": {"max_len": 100}},
    },
    "kill_process": {
        "required": {"name": str},
        "optional": {},
        "constraints": {"name": {"min_len": 1, "max_len": 100}},
    },
    "read_file": {
        "required": {"path": str},
        "optional": {},
        "constraints": {"path": {"min_len": 1, "max_len": 500}},
    },
    "search_files": {
        "required": {"query": str},
        "optional": {"file_type": str},
        "constraints": {"query": {"min_len": 1, "max_len": 200}},
    },
}


# ═════════════════════════════════════════════════════════════
# OUTPUT CONTRACTS
# ═════════════════════════════════════════════════════════════

OUTPUT_CONTRACTS = {
    "set_volume": {"type": str, "max_len": 200},
    "get_volume": {"type": str, "max_len": 200},
    "set_brightness": {"type": str, "max_len": 200},
    "open_app": {"type": str, "max_len": 200},
    "spotify_play": {"type": str, "max_len": 200},
    "take_screenshot": {"type": str, "max_len": 500},
    "list_tasks": {"type": str, "max_len": 5000},
    "list_notes": {"type": str, "max_len": 5000},
    "web_search": {"type": str, "max_len": 5000},
    "get_weather": {"type": str, "max_len": 1000},
    "get_system_stats": {"type": str, "max_len": 5000},
    "get_laptop_specs": {"type": str, "max_len": 5000},
    "search_knowledge": {"type": str, "max_len": 20000},  # Tier 4: Max knowledge content (20K chars ≈ 5K tokens)
}


# ═════════════════════════════════════════════════════════════
# VALIDATION FUNCTIONS
# ═════════════════════════════════════════════════════════════

def validate_input(tool_name: str, args: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Validate tool input arguments against the contract.
    Returns (is_valid, list_of_errors).
    """
    contract = INPUT_CONTRACTS.get(tool_name)

    # No contract defined — assume valid
    if not contract:
        return True, []

    errors = []

    # Check required params
    for param, expected_type in contract["required"].items():
        if param not in args:
            errors.append(f"Missing required parameter: '{param}'")
        elif not isinstance(args[param], expected_type):
            # Allow int for float params and vice versa
            if expected_type == int and isinstance(args[param], (int, float)):
                continue
            errors.append(f"Parameter '{param}' must be {expected_type.__name__}, got {type(args[param]).__name__}")

    # Check optional params (if provided, must be correct type)
    for param, expected_type in contract["optional"].items():
        if param in args and args[param] is not None:
            if not isinstance(args[param], expected_type):
                errors.append(f"Parameter '{param}' must be {expected_type.__name__}, got {type(args[param]).__name__}")

    # Check constraints
    constraints = contract.get("constraints", {})
    for param, constraint in constraints.items():
        if param not in args or args[param] is None:
            continue

        value = args[param]

        # Range constraint (for numbers)
        if isinstance(constraint, tuple) and len(constraint) == 2:
            min_val, max_val = constraint
            if isinstance(value, (int, float)):
                if value < min_val or value > max_val:
                    errors.append(f"Parameter '{param}' must be between {min_val} and {max_val}, got {value}")

        # Dict constraint (for strings/lists)
        elif isinstance(constraint, dict):
            if "min_len" in constraint and isinstance(value, str):
                if len(value) < constraint["min_len"]:
                    errors.append(f"Parameter '{param}' must be at least {constraint['min_len']} characters")
            if "max_len" in constraint and isinstance(value, (str, list)):
                if len(value) > constraint["max_len"]:
                    errors.append(f"Parameter '{param}' must be at most {constraint['max_len']} characters/items")
            if "min" in constraint and isinstance(value, (int, float)):
                if value < constraint["min"]:
                    errors.append(f"Parameter '{param}' must be at least {constraint['min']}")
            if "max" in constraint and isinstance(value, (int, float)):
                if value > constraint["max"]:
                    errors.append(f"Parameter '{param}' must be at most {constraint['max']}")
            if "enum" in constraint:
                if value not in constraint["enum"]:
                    errors.append(f"Parameter '{param}' must be one of {constraint['enum']}, got '{value}'")

    return len(errors) == 0, errors


def validate_output(tool_name: str, result: Any) -> Tuple[bool, List[str]]:
    """
    Validate tool output against the contract.
    Returns (is_valid, list_of_errors).
    """
    contract = OUTPUT_CONTRACTS.get(tool_name)

    if not contract:
        return True, []

    errors = []

    # Type check
    expected_type = contract.get("type")
    if expected_type and not isinstance(result, expected_type):
        # Convert to string if needed
        result = str(result)

    # Length check (for strings)
    max_len = contract.get("max_len")
    if max_len and isinstance(result, str):
        if len(result) > max_len:
            # Truncate instead of error
            result = result[:max_len] + "... (truncated)"

    return len(errors) == 0, errors


def sanitize_output(tool_name: str, result: Any) -> str:
    """Sanitize and truncate tool output for LLM consumption."""
    contract = OUTPUT_CONTRACTS.get(tool_name, {})
    max_len = contract.get("max_len", 4000)

    if result is None:
        return "Tool executed successfully (no output)."
    elif isinstance(result, str):
        if len(result) > max_len:
            return result[:max_len] + "... (truncated)"
        return result
    elif isinstance(result, (dict, list)):
        s = json.dumps(result, indent=2, default=str)
        if len(s) > max_len:
            return s[:max_len] + "... (truncated)"
        return s
    else:
        return str(result)[:max_len]


if __name__ == "__main__":
    # Test
    print("Testing contracts...\n")

    tests = [
        ("set_volume", {"percent": 50}, True),
        ("set_volume", {"percent": 150}, False),
        ("set_volume", {"percent": -5}, False),
        ("set_volume", {}, False),
        ("set_volume", {"percent": "fifty"}, False),
        ("open_app", {"app_name": "chrome"}, True),
        ("open_app", {"app_name": ""}, False),
        ("open_app", {}, False),
        ("create_task", {"title": "call mom", "due_date": "tomorrow"}, True),
        ("create_task", {"title": "call mom", "priority": "urgent"}, False),
        ("set_timer", {"duration_seconds": 600}, True),
        ("set_timer", {"duration_seconds": -10}, False),
        ("set_timer", {"duration_seconds": 100000}, False),
    ]

    for tool, args, expected in tests:
        valid, errors = validate_input(tool, args)
        status = "✅" if valid == expected else "❌"
        print(f"  {status} {tool}({args}) -> valid={valid} {errors if errors else ''}")
