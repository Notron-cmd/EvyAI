import os
import re
import threading
import keyboard
from datetime import datetime
from config import load_config
from llm import create_client, chat, extract_search_intent, strip_code_blocks, extract_memory_and_summary
from stt import listen
from tts import speak
from browser import search as browser_search, close as browser_close
from memory import load_memory, update_user_info, add_fact, add_preference, add_conversation_summary, get_memory_context


def extract_search_query(text):
    text_lower = text.lower()
    patterns = [
        r'cari(?:in|kan)?(?:\s+dong)?[:\s]+(.+)',
        r'tolong\s+cari(?:in|kan)?[:\s]+(.+)',
        r'carikan\s+aku[:\s]+(.+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, text_lower)
        if match:
            query = match.group(1).strip()
            query = query.replace("dong", "").replace("ya", "").strip()
            if query:
                return query
    return None


OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")


def save_code(codes):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    for i, code_block in enumerate(codes):
        lang_match = re.match(r'```(\w+)', code_block)
        lang = lang_match.group(1) if lang_match else "txt"
        code = re.sub(r'^```\w*\n?', '', code_block)
        code = re.sub(r'\n?```$', '', code)
        ext_map = {"python": "py", "javascript": "js", "typescript": "ts", "cpp": "cpp", "c": "c", "java": "java", "html": "html", "css": "css", "bash": "sh", "shell": "sh"}
        ext = ext_map.get(lang.lower(), lang)
        filename = f"code_{timestamp}_{i}.{ext}"
        filepath = os.path.join(OUTPUT_DIR, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(code)
        print(f"[Code] Disimpan: {filepath}")


def process_memory_background(client, model, memory, user_text, reply):
    def worker():
        try:
            data = extract_memory_and_summary(client, model, user_text, reply)
            if data:
                for key, value in data.get("user_info", {}).items():
                    if value and key:
                        update_user_info(memory, key, value)
                for fact in data.get("facts", []):
                    if fact:
                        add_fact(memory, fact)
                for pref in data.get("preferences", []):
                    if pref:
                        add_preference(memory, pref)
                summary = data.get("summary", "")
                if summary:
                    add_conversation_summary(memory, summary)
        except Exception as e:
            print(f"[Memory] Background error: {e}")
    threading.Thread(target=worker, daemon=True).start()


def main():
    print("=" * 50)
    print("  Hai! Aku Evy, asisten pribadimu")
    print("=" * 50)

    cfg = load_config()
    print(f"Provider : {cfg['base_url']}")
    print(f"Model    : {cfg['model']}")
    print(f"STT Lang : {cfg['stt_language']}")
    print(f"TTS Voice: {cfg['tts_voice']}")
    print("=" * 50)
    print("Tekan F2 untuk ngobrol, tekan F2 lagi kalau sudah selesai.")
    print("Bilang 'cari ...' untuk buka Google Chrome.")
    print("Bilang 'login' untuk setup akun Google.")
    print("Tekan Ctrl+C untuk keluar.\n")

    client = create_client(cfg["base_url"], cfg["api_key"])
    memory = load_memory()
    history = []

    if memory["user_info"] or memory["facts"] or memory["preferences"] or memory.get("conversation_summaries"):
        print("[Memory] Memory loaded:")
        if memory["user_info"]:
            print(f"  - User info: {memory['user_info']}")
        if memory["facts"]:
            print(f"  - Facts: {len(memory['facts'])} items")
        if memory["preferences"]:
            print(f"  - Preferences: {len(memory['preferences'])} items")
        if memory.get("conversation_summaries"):
            print(f"  - Conversation summaries: {len(memory['conversation_summaries'])} items")
        print()

    while True:
        try:
            keyboard.wait("f2")
            while keyboard.is_pressed("f2"):
                pass
        except KeyboardInterrupt:
            print("\nDadah, sampai ketemu lagi!")
            browser_close()
            break

        user_text = listen(cfg["stt_language"])

        if not user_text:
            continue

        if user_text.lower().strip() in ("login", "loginin", "masuk"):
            print("[Login] Membuka setup akun Google...")
            import subprocess
            import sys
            subprocess.Popen([sys.executable, "login_setup.py"])
            reply = "Oke Notron, aku buka Chrome buat login ya. Login dulu terus tutup Chrome setelah selesai, hehe"
            history.append({"role": "user", "content": user_text})
            history.append({"role": "assistant", "content": reply})
            speak(reply, cfg["tts_voice"])
            continue

        search_query = extract_search_query(user_text)
        if search_query:
            refined_query = extract_search_intent(client, cfg["model"], f"Cari: {search_query}")
            query = refined_query if refined_query else search_query
            browser_search(query)
            memory_context = get_memory_context(memory)
            explanation = chat(client, cfg["model"], f"Jelaskan secara singkat (1-2 kalimat) tentang '{query}'. Akhiri dengan 'sudah aku dapatkan Notron, silahkan cek di chrome'. Jawab ceria dan natural.", history, memory_context)
            reply = explanation
        else:
            memory_context = get_memory_context(memory)
            reply = chat(client, cfg["model"], user_text, history, memory_context)

        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": reply})

        if len(history) > 20:
            history = history[-20:]

        speak_text, code_blocks = strip_code_blocks(reply)
        if code_blocks:
            save_code(code_blocks)
            if not speak_text.strip():
                speak_text = "Oke, kodenya sudah aku simpan di folder output ya"

        speak(speak_text, cfg["tts_voice"])

        process_memory_background(client, cfg["model"], memory, user_text, reply)


if __name__ == "__main__":
    main()
