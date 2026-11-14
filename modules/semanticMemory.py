"""
Semantic Memory Module for JARVIS
"""
import json
import os
from datetime import datetime

SEMANTIC_MEMORY_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "semantic_memory.json")


def load_semantic_memory():
    if os.path.exists(SEMANTIC_MEMORY_FILE):
        try:
            with open(SEMANTIC_MEMORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_semantic_memory(memory):
    try:
        with open(SEMANTIC_MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(memory, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[SemanticMemory Error]: {e}")


def save_semantic_fact(topic, fact, importance="normal"):
    try:
        memory = load_semantic_memory()
        if topic not in memory:
            memory[topic] = []
        # Update if exists
        for existing in memory[topic]:
            if fact.lower() == existing["fact"].lower():
                existing["accessed"] = existing.get("accessed", 1) + 1
                existing["last_accessed"] = datetime.now().isoformat()
                save_semantic_memory(memory)
                return f"Updated memory: {fact}"
        # Add new
        memory[topic].append({
            "fact": fact,
            "importance": importance,
            "created_at": datetime.now().isoformat(),
            "accessed": 1,
            "last_accessed": datetime.now().isoformat()
        })
        save_semantic_memory(memory)
        return f"Remembered: {fact}"
    except Exception as e:
        return f"Error saving fact: {e}"


def recall_related_facts(topic):
    try:
        memory = load_semantic_memory()
        if topic not in memory:
            return []
        facts = sorted(memory[topic], key=lambda x: x.get("accessed", 0), reverse=True)
        return [f["fact"] for f in facts[:5]]
    except Exception:
        return []


def get_all_facts(topic):
    try:
        memory = load_semantic_memory()
        return memory.get(topic, [])
    except Exception:
        return []


def forget_fact(topic, fact_text):
    try:
        memory = load_semantic_memory()
        if topic in memory:
            memory[topic] = [f for f in memory[topic] if f["fact"].lower() != fact_text.lower()]
            save_semantic_memory(memory)
            return f"Forgot: {fact_text}"
        return "Fact not found."
    except Exception as e:
        return f"Error: {e}"