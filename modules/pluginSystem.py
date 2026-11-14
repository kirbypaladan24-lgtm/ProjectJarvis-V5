"""
JARVIS Plugin System (Tier 3.2)
================================================================
Allows live tool registration without restarting JARVIS.

How it works:
1. Drop a .py file into the plugins/ directory
2. The file must define a register_plugin() function that returns
   a list of tool definitions (name, description, parameters, function)
3. The watcher detects the new file, imports it, calls register_plugin()
4. The tools are live-registered into toolRegistry.py
5. The tool embeddings cache is updated incrementally (just the new tools)

Plugin file template:
    # plugins/my_plugin.py
    def register_plugin():
        return [
            {
                "name": "my_custom_tool",
                "description": "Does something custom",
                "parameters": {"type": "object", "properties": {...}, "required": [...]},
                "function": my_function,
                "needs_approval": False,
            }
        ]

    def my_function(**kwargs):
        return "Result"
"""
import os
import sys
import json
import time
import importlib
import threading
import traceback
from datetime import datetime

_PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PARENT_DIR not in sys.path:
    sys.path.insert(0, _PARENT_DIR)

try:
    import config
except ImportError:
    class config:
        BASE_DIR = _PARENT_DIR


# ═══════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════

PLUGIN_SYSTEM_ENABLED     = getattr(config, 'PLUGIN_SYSTEM_ENABLED', True)
PLUGINS_DIR               = getattr(config, 'PLUGINS_DIR',
    os.path.join(getattr(config, 'BASE_DIR', _PARENT_DIR), "plugins"))
PLUGIN_WATCH_INTERVAL     = getattr(config, 'PLUGIN_WATCH_INTERVAL', 5)  # seconds
PLUGIN_SYSTEM_ENABLE_LOG  = getattr(config, 'PLUGIN_SYSTEM_ENABLE_LOG', True)

# ═══════════════════════════════════════════════════════════════════════
# STATE
# ═══════════════════════════════════════════════════════════════════════

_loaded_plugins = {}  # {plugin_name: {path, mtime, tools, loaded_at}}
_watcher_thread = None
_watcher_running = threading.Event()
_lock = threading.Lock()


# ═══════════════════════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════════════════════

def _log(action, details):
    if not PLUGIN_SYSTEM_ENABLE_LOG:
        return
    try:
        log_path = os.path.join(getattr(config, 'BASE_DIR', _PARENT_DIR), "plugin_log.jsonl")
        entry = {
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "details": details,
        }
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════
# PLUGIN LOADING
# ═══════════════════════════════════════════════════════════════════════

def _load_plugin(file_path):
    """
    Load a single plugin file and register its tools.
    Returns the list of tool names registered, or empty list on failure.
    """
    plugin_name = os.path.splitext(os.path.basename(file_path))[0]

    try:
        # Add plugins dir to sys.path so imports work
        if PLUGINS_DIR not in sys.path:
            sys.path.insert(0, PLUGINS_DIR)

        # Import the plugin module
        spec = importlib.util.spec_from_file_location(f"plugins.{plugin_name}", file_path)
        if spec is None or spec.loader is None:
            print(f"[PluginSystem]: Could not create spec for {plugin_name}")
            return []

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # Check for register_plugin() function
        if not hasattr(module, 'register_plugin'):
            print(f"[PluginSystem]: {plugin_name} has no register_plugin() function")
            return []

        # Call register_plugin() to get tool definitions
        tool_defs = module.register_plugin()
        if not isinstance(tool_defs, list):
            print(f"[PluginSystem]: {plugin_name}.register_plugin() did not return a list")
            return []

        # Register each tool in the toolRegistry
        from toolRegistry import register_tool, _TOOLS
        registered_names = []

        for tool_def in tool_defs:
            name = tool_def.get("name")
            if not name:
                continue

            # Check if tool already exists (avoid duplicates)
            existing = [t for t in _TOOLS if t["name"] == name]
            if existing:
                # Remove the old version (reload)
                _TOOLS.remove(existing[0])
                print(f"[PluginSystem]: Replacing existing tool '{name}'")

            # Register the new tool
            register_tool(
                name=name,
                description=tool_def.get("description", ""),
                parameters=tool_def.get("parameters", {"type": "object", "properties": {}, "required": []}),
                function=tool_def.get("function"),
                needs_approval=tool_def.get("needs_approval", False),
                specialist=tool_def.get("specialist"),
                examples=tool_def.get("examples"),
                dont_use_for=tool_def.get("dont_use_for"),
            )
            registered_names.append(name)

        # Cache the plugin info
        with _lock:
            _loaded_plugins[plugin_name] = {
                "path": file_path,
                "mtime": os.path.getmtime(file_path),
                "tools": registered_names,
                "loaded_at": datetime.now().isoformat(),
            }

        if registered_names:
            print(f"[PluginSystem]: Loaded '{plugin_name}' — registered {len(registered_names)} tools: {registered_names}")
            _log("plugin_loaded", {"plugin": plugin_name, "tools": registered_names})

            # Incrementally update the embeddings cache for the new tools
            _update_embeddings_for_tools(registered_names)

        return registered_names

    except Exception as e:
        print(f"[PluginSystem]: Error loading '{plugin_name}': {e}")
        traceback.print_exc()
        _log("plugin_error", {"plugin": plugin_name, "error": str(e)})
        return []


def _update_embeddings_for_tools(tool_names):
    """
    Incrementally update the tool embeddings cache for newly registered tools.
    Only embeds the new tools, not all 83.
    """
    try:
        from toolEmbeddings import _tool_embeddings, _embeddings_lock, _get_embedding, _save_cache_to_disk
        from toolRegistry import get_tool

        new_count = 0
        for name in tool_names:
            if name in _tool_embeddings:
                continue  # Already embedded

            tool = get_tool(name)
            if not tool:
                continue

            desc = tool.get("description", "")
            emb = _get_embedding(desc)
            if emb:
                with _embeddings_lock:
                    _tool_embeddings[name] = emb
                new_count += 1

        if new_count > 0:
            _save_cache_to_disk()
            print(f"[PluginSystem]: Updated embeddings cache for {new_count} new tools")
    except Exception as e:
        print(f"[PluginSystem]: Embedding update failed (non-fatal): {e}")


# ═══════════════════════════════════════════════════════════════════════
# PLUGIN DISCOVERY
# ═══════════════════════════════════════════════════════════════════════

def discover_plugins():
    """
    Scan the plugins directory for .py files and load any new/changed ones.
    Returns the total number of tools registered.
    """
    if not PLUGIN_SYSTEM_ENABLED:
        return 0

    if not os.path.exists(PLUGINS_DIR):
        os.makedirs(PLUGINS_DIR, exist_ok=True)
        # Create a README in the plugins directory
        readme_path = os.path.join(PLUGINS_DIR, "README.txt")
        if not os.path.exists(readme_path):
            with open(readme_path, 'w') as f:
                f.write(PLUGIN_README)
        return 0

    total_registered = 0

    for filename in os.listdir(PLUGINS_DIR):
        if not filename.endswith('.py') or filename.startswith('_'):
            continue

        file_path = os.path.join(PLUGINS_DIR, filename)
        plugin_name = os.path.splitext(filename)[0]
        mtime = os.path.getmtime(file_path)

        with _lock:
            cached = _loaded_plugins.get(plugin_name)

        # Skip if already loaded and unchanged
        if cached and cached["mtime"] == mtime:
            continue

        # Load (or reload) the plugin
        registered = _load_plugin(file_path)
        total_registered += len(registered)

    return total_registered


# ═══════════════════════════════════════════════════════════════════════
# DIRECTORY WATCHER
# ═══════════════════════════════════════════════════════════════════════

def _watcher_loop():
    """Background thread that watches the plugins directory for changes."""
    while _watcher_running.is_set():
        try:
            discover_plugins()
        except Exception as e:
            print(f"[PluginSystem]: Watcher error: {e}")
        time.sleep(PLUGIN_WATCH_INTERVAL)


def start_plugin_watcher():
    """Start the background plugin directory watcher."""
    global _watcher_thread

    if not PLUGIN_SYSTEM_ENABLED:
        return

    if _watcher_thread is not None and _watcher_thread.is_alive():
        return

    # Do an initial discovery
    count = discover_plugins()
    if count > 0:
        print(f"[PluginSystem]: Initial discovery found {count} plugin tools")

    # Start the watcher thread
    _watcher_running.set()
    _watcher_thread = threading.Thread(target=_watcher_loop, daemon=True, name="plugin-watcher")
    _watcher_thread.start()
    print(f"[PluginSystem]: Watching '{PLUGINS_DIR}' for plugin changes (interval: {PLUGIN_WATCH_INTERVAL}s)")


def stop_plugin_watcher():
    """Stop the background watcher."""
    _watcher_running.clear()
    if _watcher_thread:
        _watcher_thread.join(timeout=2)


# ═══════════════════════════════════════════════════════════════════════
# PLUGIN MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════

def list_plugins():
    """Return info about all loaded plugins."""
    with _lock:
        return dict(_loaded_plugins)


def reload_plugin(plugin_name):
    """Force reload a specific plugin."""
    file_path = os.path.join(PLUGINS_DIR, f"{plugin_name}.py")
    if not os.path.exists(file_path):
        return False, f"Plugin file not found: {file_path}"
    registered = _load_plugin(file_path)
    return True, f"Reloaded '{plugin_name}' — {len(registered)} tools"


def unload_plugin(plugin_name):
    """Unload a plugin and remove its tools from the registry."""
    with _lock:
        info = _loaded_plugins.pop(plugin_name, None)

    if not info:
        return False, f"Plugin '{plugin_name}' not loaded"

    # Remove the tools from the registry
    try:
        from toolRegistry import _TOOLS
        tool_names = info.get("tools", [])
        _TOOLS[:] = [t for t in _TOOLS if t["name"] not in tool_names]
        print(f"[PluginSystem]: Unloaded '{plugin_name}' — removed {len(tool_names)} tools")
        _log("plugin_unloaded", {"plugin": plugin_name, "tools": tool_names})
        return True, f"Unloaded '{plugin_name}'"
    except Exception as e:
        return False, f"Error unloading: {e}"


# ═══════════════════════════════════════════════════════════════════════
# PLUGIN README
# ═══════════════════════════════════════════════════════════════════════

PLUGIN_README = """JARVIS Plugin System
=====================

Drop .py files in this directory to add new tools to JARVIS without restarting.

Each plugin file must define a register_plugin() function that returns a list
of tool definitions.

Example plugin (save as my_tools.py):

    def register_plugin():
        return [
            {
                "name": "my_custom_tool",
                "description": "Does something custom. Use when user says 'do custom thing'.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "arg1": {"type": "string", "description": "First argument"}
                    },
                    "required": ["arg1"]
                },
                "function": my_function,
                "needs_approval": False,
            }
        ]

    def my_function(arg1):
        return f"Result for {arg1}"

The plugin watcher checks this directory every 5 seconds for new or changed files.
New tools are automatically registered and their embeddings are added to the cache.
"""


# ═══════════════════════════════════════════════════════════════════════
# SELF-TEST
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("Testing Plugin System (Tier 3.2)...\n")

    # Test 1: Discover plugins (should create the directory if missing)
    print("=== Plugin Discovery ===")
    count = discover_plugins()
    print(f"  Registered {count} plugin tools")

    # Test 2: List loaded plugins
    print(f"\n=== Loaded Plugins ===")
    plugins = list_plugins()
    if plugins:
        for name, info in plugins.items():
            print(f"  {name}: {info['tools']}")
    else:
        print("  (no plugins loaded)")

    # Test 3: Check plugins directory
    print(f"\n=== Plugins Directory ===")
    print(f"  Path: {PLUGINS_DIR}")
    print(f"  Exists: {os.path.exists(PLUGINS_DIR)}")
    if os.path.exists(PLUGINS_DIR):
        files = os.listdir(PLUGINS_DIR)
        print(f"  Contents: {files}")
