import json
import os
from pathlib import Path
from datetime import datetime

MEMORY_FILE = Path(__file__).parent / "memory.json"


def load_memory():
    if MEMORY_FILE.exists():
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                memory = json.load(f)
                if "conversation_summaries" not in memory:
                    memory["conversation_summaries"] = []
                return memory
        except Exception:
            pass
    return {"user_info": {}, "facts": [], "preferences": [], "conversation_summaries": []}


def save_memory(memory):
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(memory, f, ensure_ascii=False, indent=2)


def update_user_info(memory, key, value):
    memory["user_info"][key] = value
    save_memory(memory)
    print(f"[Memory] Updated user_info: {key} = {value}")


def add_fact(memory, fact):
    if fact not in memory["facts"]:
        memory["facts"].append(fact)
        if len(memory["facts"]) > 50:
            memory["facts"] = memory["facts"][-50:]
        save_memory(memory)
        print(f"[Memory] Added fact: {fact}")


def add_preference(memory, preference):
    if preference not in memory["preferences"]:
        memory["preferences"].append(preference)
        if len(memory["preferences"]) > 20:
            memory["preferences"] = memory["preferences"][-20:]
        save_memory(memory)
        print(f"[Memory] Added preference: {preference}")


def add_conversation_summary(memory, summary):
    if summary:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        memory["conversation_summaries"].append({
            "timestamp": timestamp,
            "summary": summary
        })
        if len(memory["conversation_summaries"]) > 15:
            memory["conversation_summaries"] = memory["conversation_summaries"][-15:]
        save_memory(memory)
        print(f"[Memory] Added conversation summary: {summary}")


def get_memory_context(memory):
    context_parts = []

    if memory["user_info"]:
        info_items = [f"- {k}: {v}" for k, v in memory["user_info"].items()]
        context_parts.append("Informasi tentang user:\n" + "\n".join(info_items))

    if memory["facts"]:
        recent_facts = memory["facts"][-10:]
        context_parts.append("Fakta yang diingat:\n" + "\n".join([f"- {f}" for f in recent_facts]))

    if memory["preferences"]:
        context_parts.append("Preferensi user:\n" + "\n".join([f"- {p}" for p in memory["preferences"]]))

    if memory.get("conversation_summaries"):
        summaries = memory["conversation_summaries"][-5:]
        summary_items = [f"- [{s['timestamp']}] {s['summary']}" for s in summaries]
        context_parts.append("Topik obrolan sebelumnya:\n" + "\n".join(summary_items))

    return "\n\n".join(context_parts) if context_parts else ""
