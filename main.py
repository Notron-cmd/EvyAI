import os
import re
import time
import random
import threading
import keyboard
from datetime import datetime
from config import load_config
from llm import create_client, chat, extract_search_intent, strip_code_blocks, extract_memory_and_summary, plan_browser_action, resolve_site, summarize_browser_result, classify_intent, generate_proactive_question, pick_proactive_category
from stt import listen
from tts import speak
from browser import get_agent, verify_google_login as browser_verify_login, close as browser_close
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


def is_browser_command(text):
    text_lower = text.lower().strip()
    patterns = [
        r'^(buka|ke|open|pergi\s+ke|mau\s+ke)\b',
        r'\b(cari|carikan|cariin|telusuri)\b.*\b(di|pada)\s+youtube',
        r'^(cari|carikan|cariin|search)\b',
        r'\b(buka|open)\b',
    ]
    return any(re.search(p, text_lower) for p in patterns)


def _execute_plan(agent, plan):
    state = None
    for action in plan:
        act = action.get("action")
        if act == "done":
            return state
        try:
            if act == "open_url":
                state = agent.open_url(action.get("url", "about:blank"))
            elif act == "search_web":
                state = agent.search_web(action.get("query", ""))
            elif act == "search_youtube":
                state = agent.search_youtube(action.get("query", ""))
            elif act == "type_text":
                state = agent.type_text(action.get("text", ""))
            elif act == "press_key":
                state = agent.press_key(action.get("key", "Enter"))
            elif act == "click_text":
                state = agent.click_text(action.get("text", ""))
            elif act == "click_first_result":
                state = agent.click_first_result()
            elif act == "scroll":
                state = agent.scroll(action.get("direction", "down"))
            elif act == "go_back":
                state = agent.go_back()
            elif act == "go_forward":
                state = agent.go_forward()
            elif act == "read_content":
                state = agent.read_content()
            else:
                print(f"[Agent] Aksi tidak dikenal: {act}")
                continue
        except Exception as e:
            print(f"[Agent] Aksi {act} gagal: {e}")
            state = agent.get_state()
            continue
        print(f"[Agent] Aksi {act} -> {state.get('title', '')[:60]}")
    return state


def run_browser_agent(client, model, command):
    agent = get_agent()
    state = agent.get_state()
    print(f"[Agent] Mulai: {command}")
    wants_enter = bool(re.search(r'\b(masuk|kesimpulan|rangkum|ringkas|baca|detail|isi)\b', command.lower()))

    for step in range(5):
        plan = plan_browser_action(client, model, command, state)
        if not plan:
            print("[Agent] Tidak bisa plan, fallback ke Google search.")
            return agent.search_web(command)
        new_state = _execute_plan(agent, plan)
        if new_state is not None:
            state = new_state
        if wants_enter and "google.com/search" in state.get("url", ""):
            print("[Agent] Masih di hasil pencarian tapi user minta masuk/baca. Masuk hasil pertama...")
            state = agent.click_first_result()
            if "google.com/search" not in state.get("url", ""):
                state = agent.read_content()
            else:
                enter_cmd = ("User ingin masuk ke halaman artikel/website yang relevan dan membaca isinya. "
                             "Buka URL artikel yang relevan secara langsung, lalu baca isinya, baru done. " + command)
                plan2 = plan_browser_action(client, model, enter_cmd, state)
                if plan2:
                    new_state = _execute_plan(agent, plan2)
                    if new_state is not None:
                        state = new_state
            break
        if "done" in str(plan) or _plan_has_done(plan):
            break
    return state


def _plan_has_done(plan):
    return any(isinstance(a, dict) and a.get("action") == "done" for a in plan)


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
    last_assistant_reply = ""
    last_activity = time.time()
    last_proactive_category = ""

    try:
        logged_in, email = browser_verify_login()
    except Exception as e:
        print(f"[Login] Error verifikasi: {e}")
        logged_in, email = False, None

    if logged_in:
        account_name = email or cfg.get("evy_google_account", "akun Google Evy")
        print(f"[Login] Google aktif: {account_name}")
    else:
        print("[Login] Belum login Google. Membuka setup login...")
        import subprocess
        import sys
        subprocess.Popen([sys.executable, "login_setup.py"])
        speak("Hei Notron, aku belum login pakai akun Google Evy nih. Aku buka Chrome buat login dulu ya, setelah selesai bilang aja lagi.", cfg["tts_voice"])

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
            while True:
                if keyboard.is_pressed("f2"):
                    while keyboard.is_pressed("f2"):
                        time.sleep(0.05)
                    break
                if time.time() - last_activity > cfg["idle_trigger_seconds"]:
                    if random.random() < cfg["idle_checkin_chance"]:
                        memory_context = get_memory_context(memory)
                        category = pick_proactive_category(last_proactive_category)
                        checkin = generate_proactive_question(
                            client, cfg["model"], memory_context, category
                        )
                        last_proactive_category = category
                        print("[Idle] Check-in aktif.")
                        speak(checkin, cfg["tts_voice"])
                    last_activity = time.time()
                time.sleep(0.3)
        except KeyboardInterrupt:
            print("\nDadah, sampai ketemu lagi!")
            browser_close()
            break

        last_activity = time.time()
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
        browser_task = None
        follow_through = bool(re.search(
            r'\b(masuk|kesimpulan|rangkum|ringkas|baca|read|intip|pembahasan|detail|lanjut)\b',
            user_text.lower()
        ))

        if search_query and re.search(r'\b(di|pada)\s+youtube', search_query):
            yt_query = re.sub(r'\b(di|pada)\s+youtube\b.*$', '', search_query, flags=re.IGNORECASE).strip()
            if not yt_query:
                yt_query = search_query.replace("di youtube", "").replace("pada youtube", "").strip()
            if not yt_query:
                yt_query = search_query
            browser_task = ("search_youtube", yt_query)
        elif search_query and not follow_through:
            refined_query = extract_search_intent(client, cfg["model"], f"Cari: {search_query}")
            query = refined_query if refined_query else search_query
            browser_task = ("search_web", query)

        if browser_task:
            agent = get_agent()
            task_type, q = browser_task
            if task_type == "search_youtube":
                state = agent.search_youtube(q)
            else:
                state = agent.search_web(q)
            reply = summarize_browser_result(client, cfg["model"], user_text, state, recent_context=last_assistant_reply)
        elif search_query and follow_through:
            state = run_browser_agent(client, cfg["model"], user_text)
            reply = summarize_browser_result(client, cfg["model"], user_text, state, recent_context=last_assistant_reply)
        elif is_browser_command(user_text):
            agent = get_agent()
            resolved = resolve_site(client, cfg["model"], user_text)
            if resolved:
                state = agent.resolve_and_open(resolved)
                if state.get("url"):
                    reply = summarize_browser_result(client, cfg["model"], user_text, state, recent_context=last_assistant_reply)
                else:
                    reply = "Maaf ya, sepertinya aku belum berhasil buka situs itu. Coba lagi ya."
            else:
                state = run_browser_agent(client, cfg["model"], user_text)
                reply = summarize_browser_result(client, cfg["model"], user_text, state, recent_context=last_assistant_reply)
        else:
            intent = classify_intent(client, cfg["model"], user_text, last_assistant_reply)
            if intent == "browser":
                state = run_browser_agent(client, cfg["model"], user_text)
                reply = summarize_browser_result(client, cfg["model"], user_text, state, recent_context=last_assistant_reply)
            else:
                memory_context = get_memory_context(memory)
                reply = chat(client, cfg["model"], user_text, history, memory_context)

        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": reply})
        last_assistant_reply = reply

        if len(history) > 20:
            history = history[-20:]

        speak_text, code_blocks = strip_code_blocks(reply)
        if code_blocks:
            save_code(code_blocks)
            if not speak_text.strip():
                speak_text = "Oke, kodenya sudah aku simpan di folder output ya"

        speak(speak_text, cfg["tts_voice"])

        process_memory_background(client, cfg["model"], memory, user_text, reply)

        if random.random() < cfg["proactive_chance"]:
            memory_context = get_memory_context(memory)
            category = pick_proactive_category(last_proactive_category)
            question = generate_proactive_question(
                client, cfg["model"], memory_context, category
            )
            last_proactive_category = category
            print("[Proactive] Evy bertanya acak.")
            speak(question, cfg["tts_voice"])


if __name__ == "__main__":
    main()
