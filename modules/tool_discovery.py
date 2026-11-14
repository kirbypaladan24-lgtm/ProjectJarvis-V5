"""
JARVIS Tool Discovery System
================================================================
Lets the user say "add a tool that does X" and JARVIS generates
a tool skeleton that can be reviewed and added to the registry.

This turns the user from the only tool author into a tool reviewer.

Usage:
    from tool_discovery import generate_tool_skeleton, get_pending_tools, approve_tool

    # User says "add a tool that converts Celsius to Fahrenheit"
    skeleton = generate_tool_skeleton("convert Celsius to Fahrenheit")
    # Returns: tool name, description, parameters, function code

    # User reviews and approves
    approve_tool("celsius_to_fahrenheit")
    # Now it's registered in the tool registry
"""
import os
import sys
import json
import re
from datetime import datetime

_PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PARENT_DIR not in sys.path:
    sys.path.insert(0, _PARENT_DIR)

try:
    import config
except ImportError:
    class config:
        BASE_DIR = "."
        OLLAMA_BASE_URL = "http://localhost:11434"
        CASUAL_CHAT_MODEL = "qwen2.5:1.5b-instruct"

import requests


# ═════════════════════════════════════════════════════════════
# STATE
# ═════════════════════════════════════════════════════════════

_PENDING_FILE = os.path.join(getattr(config, 'BASE_DIR', '.'), "pending_tools.json")
_APPROVED_FILE = os.path.join(getattr(config, 'BASE_DIR', '.'), "custom_tools.json")


# ═════════════════════════════════════════════════════════════
# TOOL SKELETON GENERATION
# ═════════════════════════════════════════════════════════════

GENERATION_PROMPT = """You are a JARVIS tool generator. Given a description of what the user wants a tool to do, generate a Python tool definition.

Output format (STRICT — use this exact template):

NAME: <tool_name_in_snake_case>
DESCRIPTION: <one line description starting with a verb>
PARAMETERS:
  - <param1> (<type>): <description>
  - <param2> (<type>): <description>
CODE:
```python
def _<tool_name>(<param1>, <param2>=None):
    \"\"\"<description>\"\"\"
    try:
        # Implementation here
        result = <logic>
        return result
    except Exception as e:
        return f"Error: {e}"
```

Rules:
- Tool name must be snake_case (e.g., celsius_to_fahrenheit)
- Description should start with a verb (e.g., "Convert", "Get", "Search")
- Use standard Python only (no external libraries unless absolutely needed)
- Always include try/except for error handling
- Return a string result (JARVIS speaks this to the user)
- Address the user as "Sir" in any user-facing messages

Example:
User: "add a tool that converts Celsius to Fahrenheit"

NAME: celsius_to_fahrenheit
DESCRIPTION: Convert temperature from Celsius to Fahrenheit
PARAMETERS:
  - celsius (float): Temperature in Celsius
CODE:
```python
def _celsius_to_fahrenheit(celsius):
    \"\"\"Convert temperature from Celsius to Fahrenheit\"\"\"
    try:
        fahrenheit = (float(celsius) * 9/5) + 32
        return f"{celsius}°C = {fahrenheit:.1f}°F, Sir."
    except Exception as e:
        return f"Error converting temperature: {e}"
```"""


def generate_tool_skeleton(description):
    """
    Use the LLM to generate a tool skeleton from a description.
    Returns a dict with name, description, parameters, and code.
    """
    try:
        response = requests.post(
            f"{config.OLLAMA_BASE_URL}/api/chat",
            json={
                "model": getattr(config, 'CASUAL_CHAT_MODEL', 'qwen2.5:1.5b-instruct'),
                "messages": [
                    {"role": "system", "content": GENERATION_PROMPT},
                    {"role": "user", "content": f"Generate a tool for: {description}"},
                ],
                "stream": False,
                "options": {"temperature": 0.2, "num_predict": 300},
            },
            timeout=30
        )
        response.raise_for_status()
        result = response.json().get("message", {}).get("content", "").strip()

        # Parse the LLM output
        tool = _parse_tool_output(result)
        if tool:
            # Save to pending
            _save_pending(tool)
            return tool
        else:
            return {"error": "Could not parse LLM output", "raw": result}

    except Exception as e:
        return {"error": str(e)}


def _parse_tool_output(text):
    """Parse the LLM output into a tool dict."""
    try:
        # Extract NAME
        name_match = re.search(r'NAME:\s*(\w+)', text, re.IGNORECASE)
        if not name_match:
            return None
        name = name_match.group(1).strip()

        # Extract DESCRIPTION
        desc_match = re.search(r'DESCRIPTION:\s*(.+?)(?=\nPARAMETERS:|\nCODE:|$)', text, re.IGNORECASE | re.DOTALL)
        description = desc_match.group(1).strip() if desc_match else "No description"

        # Extract PARAMETERS
        params = []
        params_section = re.search(r'PARAMETERS:\s*\n(.*?)(?=\nCODE:|$)', text, re.IGNORECASE | re.DOTALL)
        if params_section:
            for line in params_section.group(1).strip().split('\n'):
                line = line.strip()
                if line.startswith('-'):
                    # Parse: - param_name (type): description
                    param_match = re.match(r'-\s*(\w+)\s*\((\w+)\):\s*(.+)', line)
                    if param_match:
                        params.append({
                            "name": param_match.group(1),
                            "type": param_match.group(2),
                            "description": param_match.group(3).strip()
                        })

        # Extract CODE
        code_match = re.search(r'CODE:\s*```python\s*(.*?)```', text, re.IGNORECASE | re.DOTALL)
        if not code_match:
            # Try without python tag
            code_match = re.search(r'CODE:\s*```\s*(.*?)```', text, re.IGNORECASE | re.DOTALL)
        code = code_match.group(1).strip() if code_match else ""

        return {
            "name": name,
            "description": description,
            "parameters": params,
            "code": code,
            "created_at": datetime.now().isoformat(),
            "description_input": "",
        }

    except Exception as e:
        print(f"[ToolDiscovery]: Parse error: {e}")
        return None


# ═════════════════════════════════════════════════════════════
# PENDING TOOLS MANAGEMENT
# ═════════════════════════════════════════════════════════════

def _save_pending(tool):
    """Save a tool to pending list."""
    pending = _load_pending()
    pending.append(tool)
    with open(_PENDING_FILE, 'w') as f:
        json.dump(pending, f, indent=2)


def _load_pending():
    """Load pending tools."""
    try:
        if os.path.exists(_PENDING_FILE):
            with open(_PENDING_FILE, 'r') as f:
                return json.load(f)
    except Exception:
        pass
    return []


def get_pending_tools():
    """Get all pending tools awaiting review."""
    return _load_pending()


def approve_tool(tool_name):
    """
    Approve a pending tool. This:
    1. Moves it to approved tools
    2. Registers it in the tool registry
    3. Returns success message
    """
    pending = _load_pending()
    tool = None
    for t in pending:
        if t["name"] == tool_name:
            tool = t
            break

    if not tool:
        return f"Tool '{tool_name}' not found in pending tools."

    # Move to approved
    approved = _load_approved()
    approved.append(tool)
    with open(_APPROVED_FILE, 'w') as f:
        json.dump(approved, f, indent=2)

    # Remove from pending
    pending = [t for t in pending if t["name"] != tool_name]
    with open(_PENDING_FILE, 'w') as f:
        json.dump(pending, f, indent=2)

    # Register in the tool registry
    try:
        _register_custom_tool(tool)
        return f"Tool '{tool_name}' approved and registered, Sir."
    except Exception as e:
        return f"Tool approved but registration failed: {e}"


def reject_tool(tool_name):
    """Reject a pending tool — removes it without registering."""
    pending = _load_pending()
    pending = [t for t in pending if t["name"] != tool_name]
    with open(_PENDING_FILE, 'w') as f:
        json.dump(pending, f, indent=2)
    return f"Tool '{tool_name}' rejected, Sir."


def _load_approved():
    """Load approved custom tools."""
    try:
        if os.path.exists(_APPROVED_FILE):
            with open(_APPROVED_FILE, 'r') as f:
                return json.load(f)
    except Exception:
        pass
    return []


def _register_custom_tool(tool):
    """Register a custom tool in the tool registry."""
    from toolRegistry import register_tool

    # Build parameters schema
    properties = {}
    required = []
    for param in tool.get("parameters", []):
        properties[param["name"]] = {
            "type": param["type"],
            "description": param["description"]
        }
        # Mark first param as required (simple heuristic)
        if param == tool["parameters"][0]:
            required.append(param["name"])

    # Execute the code to get the function
    namespace = {}
    exec(tool["code"], namespace)

    # Find the function in the namespace
    func_name = f"_{tool['name']}"
    if func_name not in namespace:
        # Try to find any function that starts with _
        for key in namespace:
            if key.startswith('_') and callable(namespace[key]):
                func_name = key
                break

    if func_name not in namespace:
        raise ValueError(f"Could not find function in code. Expected '{func_name}'")

    register_tool(
        name=tool["name"],
        description=tool["description"],
        parameters={
            "type": "object",
            "properties": properties,
            "required": required
        },
        function=namespace[func_name],
        examples=[tool.get("description_input", "")]
    )

    print(f"[ToolDiscovery]: Registered custom tool '{tool['name']}'")


def load_all_custom_tools():
    """Load and register all approved custom tools at startup."""
    approved = _load_approved()
    count = 0
    for tool in approved:
        try:
            _register_custom_tool(tool)
            count += 1
        except Exception as e:
            print(f"[ToolDiscovery]: Could not load custom tool '{tool.get('name')}': {e}")
    if count > 0:
        print(f"[ToolDiscovery]: Loaded {count} custom tools.")


# ═════════════════════════════════════════════════════════════
# TEST
# ═════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("Testing Tool Discovery System...\n")

    # Test parsing (without LLM)
    sample_output = """NAME: celsius_to_fahrenheit
DESCRIPTION: Convert temperature from Celsius to Fahrenheit
PARAMETERS:
  - celsius (float): Temperature in Celsius
CODE:
```python
def _celsius_to_fahrenheit(celsius):
    \"\"\"Convert temperature from Celsius to Fahrenheit\"\"\"
    try:
        fahrenheit = (float(celsius) * 9/5) + 32
        return f"{celsius}°C = {fahrenheit:.1f}°F, Sir."
    except Exception as e:
        return f"Error converting temperature: {e}"
```"""

    print("Test 1: Parse LLM output")
    tool = _parse_tool_output(sample_output)
    assert tool is not None
    assert tool["name"] == "celsius_to_fahrenheit"
    assert "Convert temperature" in tool["description"]
    assert len(tool["parameters"]) == 1
    assert tool["parameters"][0]["name"] == "celsius"
    assert "def _celsius_to_fahrenheit" in tool["code"]
    print("  ✅ Parsing works")

    print("\nTest 2: Save and load pending")
    # Clear any existing
    if os.path.exists(_PENDING_FILE):
        os.remove(_PENDING_FILE)

    _save_pending(tool)
    pending = get_pending_tools()
    assert len(pending) == 1
    assert pending[0]["name"] == "celsius_to_fahrenheit"
    print("  ✅ Save/load works")

    print("\nTest 3: Approve and register")
    result = approve_tool("celsius_to_fahrenheit")
    print(f"  {result}")
    assert "approved" in result.lower()

    # Verify it's registered
    from toolRegistry import get_tool
    t = get_tool("celsius_to_fahrenheit")
    assert t is not None
    print("  ✅ Tool registered")

    # Test the registered tool
    func = t["function"]
    output = func(100)
    print(f"  celsius_to_fahrenheit(100) = {output}")
    assert "212.0" in output
    print("  ✅ Tool works")

    print("\nTest 4: Reject")
    _save_pending({"name": "test_reject", "description": "test", "parameters": [], "code": "def _test_reject(): return 'test'"})
    result = reject_tool("test_reject")
    assert "rejected" in result.lower()
    pending = get_pending_tools()
    assert all(t["name"] != "test_reject" for t in pending)
    print("  ✅ Reject works")

    # Cleanup
    if os.path.exists(_PENDING_FILE):
        os.remove(_PENDING_FILE)
    if os.path.exists(_APPROVED_FILE):
        os.remove(_APPROVED_FILE)

    print("\nAll Tool Discovery tests passed ✅")
