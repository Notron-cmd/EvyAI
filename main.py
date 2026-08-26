import os
import re
import time
import random
import threading
import keyboard
from datetime import datetime
from config import load_config, HOTKEY
from llm import create_client, chat, extract_search_intent, strip_code_blocks, extract_memory_and_summary, plan_browser_action, resolve_site, summarize_browser_result, classify_intent, generate_proactive_question, pick_proactive_category, resolve_search_query
from stt import listen
from tts import speak
from browser import is_available as browser_available, get_agent, verify_google_login_standalone, close as browser_close
from memory import load_memory, update_user_info, add_fact, add_preference, add_conversation_summary, get_memory_context
from local_apps import handle_command as handle_local_command, prewarm_index


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


_SIMILARITY_STOPWORDS = {
    "user", "evy", "yang", "dengan", "untuk", "tentang", "juga", "agar",
    "saat", "karena", "kemudian", "akan", "sudah", "sedang",
}


def _text_similarity(a, b):
    wa = [w for w in re.findall(r'\w+', a.lower()) if len(w) >= 4 and w not in _SIMILARITY_STOPWORDS]
    wb = [w for w in re.findall(r'\w+', b.lower()) if len(w) >= 4 and w not in _SIMILARITY_STOPWORDS]
    if not wa or not wb:
        return 0.0
    matched = 0
    pool = list(wb)
    for w in wa:
        for i, v in enumerate(pool):
            if w == v or (w in v or v in w):
                matched += 1
                pool.pop(i)
                break
    return matched / min(len(wa), len(wb))


def _is_duplicate_entry(text, existing, threshold=0.6):
    for e in existing:
        other = e.get("summary", "") if isinstance(e, dict) else e
        if other and _text_similarity(text, other) >= threshold:
            return True
    return False


def process_memory_background(client, model, memory, user_text, reply):
    def worker():
        try:
            data = extract_memory_and_summary(client, model, user_text, reply)
            if data:
                for key, value in data.get("user_info", {}).items():
                    if value and key:
                        update_user_info(memory, key, value)
                recent_facts = memory["facts"][-10:]
                for fact in data.get("facts", []):
                    if fact and not _is_duplicate_entry(fact, recent_facts, 0.7):
                        add_fact(memory, fact)
                        recent_facts.append(fact)
                for pref in data.get("preferences", []):
                    if pref:
                        add_preference(memory, pref)
                summary = data.get("summary", "")
                recent_summaries = [s.get("summary", "") for s in memory.get("conversation_summaries", [])[-5:]]
                if summary and not _is_duplicate_entry(summary, recent_summaries, 0.6):
                    add_conversation_summary(memory, summary)
        except Exception as e:
            print(f"[Memory] Background error: {e}")
    threading.Thread(target=worker, daemon=True).start()


def _spawn_proactive(client, model, memory, last_category, slot):
    def worker():
        try:
            ctx = get_memory_context(memory)
            category = pick_proactive_category(last_category)
            question = generate_proactive_question(client, model, ctx, category)
            slot["question"] = question
            slot["category"] = category
        except Exception as e:
            print(f"[Proactive] Error: {e}")
    threading.Thread(target=worker, daemon=True).start()


BROWSER_HINTS = re.compile(
    r'\b(buka|open|cari|carikan|cariin|search|google|youtube|chrome|browser|website|web|situs|wikipedia|internet|kunjungi|akses|login|scroll)\b',
    re.IGNORECASE,
)

PLAY_HINTS = re.compile(
    r'\b(play|playkan|putar|putarkan|mainkan|dengerin|dengarkan)\b',
    re.IGNORECASE,
)1

REFERENTIAL_HINTS = re.compile(
    r'\b(ini|itu|tadi|dia|lagunya|videonya|filmnya|barusan|yang kemarin)\b',
    re.IGNORECASE,
)

PLAY_COMMAND_STRIP = re.compile(
    r'\b(coba|tolong|dong|ya|deh|aja|saja|di youtube|pada youtube|youtube|yt|dan|terus|lalu|kemudian|'
    r'play|playkan|putar|putarkan|mainkan|dengerin|dengarkan|carikan|carikan aku|cariin|cari|search)\b',
    re.IGNORECASE,
)

SITE_MENTION = re.compile(
    r'\b(youtube|instagram|ig|gmail|google|wikipedia|whatsapp|wa|tiktok|facebook|github|'
    r'netflix|spotify|reddit|shopee|tokopedia|detik|kompas|medium|notion|'
    r'kuramanime|otakudesu|samehadaku|nanime|oploverz)\b',
    re.IGNORECASE,
)

ACTIVE_SITE_WORDS = re.compile(
    r'\b(di website|di situs|di web|di sana|di situ|situsnya|websitenya|webnya|'
    r'yang kebuka|yang tadi|website tersebut|situs tersebut|web tersebut|'
    r'ganti|pindah|ke video|ke lagu|ke anime|selanjutnya|sebelumnya)\b',
    re.IGNORECASE,
)

SCREENSHOT_RE = re.compile(r'\b(screenshot|ss|jepret|foto layar)\b', re.IGNORECASE)
TAB_NEW_RE = re.compile(r'\b(tab baru|new tab)\b', re.IGNORECASE)
TAB_CLOSE_RE = re.compile(
    r'^\s*(tutup|tutupin|close)\s+tab(\s+(ke[\s\-]*|nomor[\s\-]*|yang\s+)?'
    r'(\d+|pertama|kedua|ketiga|keempat|kelima|keenam|ketujuh|kedelapan|kesembilan|kesepuluh))?\s*$',
    re.IGNORECASE,
)
TAB_LIST_RE = re.compile(r'\b(tab apa aja|daftar tab|list tab|tab apa)\b', re.IGNORECASE)
TAB_SWITCH_RE = re.compile(
    r'^\s*(ganti|pindah)\s+tab\s+(ke[\s\-]*|yang\s+)?'
    r'(\d+|pertama|kedua|ketiga|keempat|kelima|keenam|ketujuh|kedelapan|kesembilan|kesepuluh)\s*$',
    re.IGNORECASE,
)
ORDINALS = {
    "pertama": 1, "kedua": 2, "ketiga": 3, "keempat": 4, "kelima": 5,
    "keenam": 6, "ketujuh": 7, "kedelapan": 8, "kesembilan": 9, "kesepuluh": 10,
}
SKIP_AD_RE = re.compile(r'\b(skip|skip ad|skip iklan|lewati iklan)\b', re.IGNORECASE)

TAB_NEW_SEARCH_RE = re.compile(
    r'(?:buka|open)?\s*(?:tab\s+baru|new\s+tab)\s+(?:dan|terus|lalu|kemudian)\s+(?:cari|search|cariin|carikan)\s+(.+)',
    re.IGNORECASE,
)

CLICK_FIRST_RE = re.compile(
    r'\b(buka|masuk|klik)\s+(hasil|website|link|artikel|situs)\s+(teratas|pertama|paling atas)\b',
    re.IGNORECASE,
)


def extract_play_query(text):
    q = PLAY_COMMAND_STRIP.sub(' ', text)
    q = re.sub(r'\s+', ' ', q).strip(' ,.-')
    return q or None

_browser_lock = threading.Lock()


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
    with _browser_lock:
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
    print("Tekan Right Alt untuk ngobrol, tekan Right Alt lagi kalau sudah selesai.")
    print("Bilang 'cari ...' untuk buka Google Chrome.")
    print("Bilang 'login' untuk setup akun Google.")
    print("Login Google dicek di background - Right Alt bisa langsung ditekan kapan saja.")
    print("Tekan Ctrl+C untuk keluar.\n")

    client = create_client(cfg["base_url"], cfg["api_key"])
    memory = load_memory()
    history = []
    last_assistant_reply = ""
    last_activity = time.time()
    last_proactive_category = ""
    pending_proactive = {"question": None, "category": ""}

    login_status = {"checked": False, "logged_in": False, "email": None, "notified": False}

    def _verify_login_background():
        try:
            with _browser_lock:
                logged_in, email = verify_google_login_standalone()
        except Exception as e:
            print(f"[Login] Error verifikasi: {e}")
            logged_in, email = False, None
        login_status["checked"] = True
        login_status["logged_in"] = logged_in
        login_status["email"] = email
        if logged_in:
            account_name = email or cfg.get("evy_google_account", "akun Google Evy")
            print(f"[Login] Google aktif: {account_name}")
        else:
            print("[Login] Belum login Google. Membuka setup login...")
            import subprocess
            import sys
            subprocess.Popen([sys.executable, "login_setup.py"])

    print("[Login] Verifikasi login Google jalan di background...")
    threading.Thread(target=_verify_login_background, daemon=True).start()

    print("[Apps] Scanning aplikasi lokal di background...")
    prewarm_index()

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
                if keyboard.is_pressed(HOTKEY):
                    if pending_proactive["question"]:
                        print("[Proactive] Dibatalkan (user mau ngomong).")
                        pending_proactive["question"] = None
                    while keyboard.is_pressed(HOTKEY):
                        time.sleep(0.05)
                    break
                if pending_proactive["question"]:
                    question = pending_proactive["question"]
                    last_proactive_category = pending_proactive["category"]
                    pending_proactive["question"] = None
                    print("[Proactive] Evy bertanya acak.")
                    speak(question, cfg["tts_voice"])
                    last_activity = time.time()
                    continue
                if login_status["checked"] and not login_status["notified"]:
                    login_status["notified"] = True
                    if not login_status["logged_in"]:
                        speak("Hei Notron, aku belum login pakai akun Google Evy nih. Aku buka Chrome buat login dulu ya, setelah selesai bilang aja lagi.", cfg["tts_voice"])
                if time.time() - last_activity > cfg["idle_trigger_seconds"]:
                    if (random.random() < cfg["idle_checkin_chance"]
                            and not pending_proactive["question"]):
                        print("[Idle] Menyiapkan check-in di background...")
                        _spawn_proactive(client, cfg["model"], memory, last_proactive_category, pending_proactive)
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

        try:
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

            if SKIP_AD_RE.search(user_text):
                if browser_available():
                    with _browser_lock:
                        agent = get_agent()
                        skipped = agent.skip_ad()
                        reply = "Iklannya sudah aku skip ya" if skipped else "Nggak ada iklan yang bisa di-skip nih"
                else:
                    reply = "Chrome belum terbuka, bilang cari sesuatu dulu ya"
                speak(reply, cfg["tts_voice"])
                history.append({"role": "user", "content": user_text})
                history.append({"role": "assistant", "content": reply})
                last_assistant_reply = reply
                continue

            if SCREENSHOT_RE.search(user_text):
                if browser_available():
                    with _browser_lock:
                        agent = get_agent()
                        agent.capture_screenshot()
                        reply = "Oke, screenshot sudah disimpan ya Notron"
                else:
                    reply = "Chrome belum terbuka, bilang cari sesuatu dulu ya"
                speak(reply, cfg["tts_voice"])
                history.append({"role": "user", "content": user_text})
                history.append({"role": "assistant", "content": reply})
                last_assistant_reply = reply
                continue

            m = TAB_NEW_SEARCH_RE.search(user_text)
            if m:
                search_query = m.group(1).strip()
                if browser_available():
                    with _browser_lock:
                        agent = get_agent()
                        agent.new_tab()
                        state = agent.search_web(search_query)
                    reply = f"Tab baru dibuka, hasil pencarian '{search_query}' sudah tampil"
                else:
                    reply = "Chrome belum terbuka, bilang cari sesuatu dulu ya"
                speak(reply, cfg["tts_voice"])
                history.append({"role": "user", "content": user_text})
                history.append({"role": "assistant", "content": reply})
                last_assistant_reply = reply
                continue

            if TAB_NEW_RE.search(user_text):
                if browser_available():
                    with _browser_lock:
                        agent = get_agent()
                        agent.new_tab()
                        reply = "Oke, tab baru sudah terbuka"
                else:
                    reply = "Chrome belum terbuka, bilang cari sesuatu dulu ya"
                speak(reply, cfg["tts_voice"])
                history.append({"role": "user", "content": user_text})
                history.append({"role": "assistant", "content": reply})
                last_assistant_reply = reply
                continue

            m = TAB_CLOSE_RE.match(user_text)
            if m:
                if browser_available():
                    idx = m.group(4)
                    with _browser_lock:
                        agent = get_agent()
                        if idx:
                            n = int(idx) if idx.isdigit() else ORDINALS[idx.lower()]
                            result = agent.close_tab(n - 1)
                        else:
                            result = agent.close_tab()
                        reply = result["error"] if "error" in result else "Oke, tab sudah ditutup"
                else:
                    reply = "Chrome belum terbuka, nggak ada tab yang bisa ditutup"
                speak(reply, cfg["tts_voice"])
                history.append({"role": "user", "content": user_text})
                history.append({"role": "assistant", "content": reply})
                last_assistant_reply = reply
                continue

            if TAB_LIST_RE.search(user_text):
                if browser_available():
                    with _browser_lock:
                        agent = get_agent()
                        tabs = agent.list_tabs()
                        if not tabs:
                            reply = "Nggak ada tab yang terbuka"
                        else:
                            lines = [f"Tab {t['index']+1}. {t['title'][:50]}" for t in tabs]
                            reply = "\n".join(lines)
                            print(f"[Router] Tab list:\n" + "\n".join(lines))
                else:
                    reply = "Chrome belum terbuka"
                speak(reply, cfg["tts_voice"])
                history.append({"role": "user", "content": user_text})
                history.append({"role": "assistant", "content": reply})
                last_assistant_reply = reply
                continue

            m = TAB_SWITCH_RE.match(user_text)
            if m:
                if browser_available():
                    tok = m.group(3)
                    idx = (int(tok) if tok.isdigit() else ORDINALS[tok.lower()]) - 1
                    with _browser_lock:
                        agent = get_agent()
                        result = agent.switch_tab(idx)
                        reply = result["error"] if "error" in result else f"Pindah ke tab {idx+1}"
                else:
                    reply = "Chrome belum terbuka"
                speak(reply, cfg["tts_voice"])
                history.append({"role": "user", "content": user_text})
                history.append({"role": "assistant", "content": reply})
                last_assistant_reply = reply
                continue

            m = CLICK_FIRST_RE.search(user_text)
            if m:
                if browser_available():
                    with _browser_lock:
                        agent = get_agent()
                        state = agent.click_first_result()
                    reply = "Oke, aku buka website teratasnya ya"
                else:
                    reply = "Chrome belum terbuka, bilang cari sesuatu dulu ya"
                speak(reply, cfg["tts_voice"])
                history.append({"role": "user", "content": user_text})
                history.append({"role": "assistant", "content": reply})
                last_assistant_reply = reply
                continue

            local_reply = handle_local_command(user_text)
            if local_reply is not None:
                history.append({"role": "user", "content": user_text})
                history.append({"role": "assistant", "content": local_reply})
                last_assistant_reply = local_reply
                speak(local_reply, cfg["tts_voice"])
                if len(history) > 20:
                    history = history[-20:]
                continue

            search_query = extract_search_query(user_text)
            browser_task = None
            wants_play = bool(PLAY_HINTS.search(user_text))
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
                yt_query = PLAY_COMMAND_STRIP.sub(' ', yt_query)
                yt_query = re.sub(r'\s+', ' ', yt_query).strip(' ,.-') or yt_query
                browser_task = ("search_youtube", yt_query, wants_play)
            elif wants_play and not search_query and not follow_through and not is_browser_command(user_text):
                yt_query = extract_play_query(user_text)
                if yt_query:
                    browser_task = ("search_youtube", yt_query, True)
            elif search_query and not follow_through:
                if REFERENTIAL_HINTS.search(search_query):
                    query = resolve_search_query(client, cfg["model"], search_query, last_assistant_reply) or search_query
                else:
                    refined_query = extract_search_intent(client, cfg["model"], f"Cari: {search_query}")
                    query = refined_query if refined_query else search_query
                browser_task = ("search_web", query, False)

            if browser_task:
                task_type, q, auto_play = browser_task
                if task_type == "search_youtube" and REFERENTIAL_HINTS.search(q):
                    resolved = resolve_search_query(client, cfg["model"], q, last_assistant_reply)
                    if resolved:
                        q = resolved
                with _browser_lock:
                    agent = get_agent()
                    if task_type == "search_youtube":
                        if auto_play:
                            print("[YouTube] Eksplor dan putar video...")
                            state = agent.explore_youtube_and_play(q)
                            agent._auto_skip_ad()
                        else:
                            state = agent.search_youtube(q)
                    else:
                        print(f"[Browser] Eksplor 3 website untuk: {q}")
                        state = agent.explore_and_summarize(q)
                reply = summarize_browser_result(client, cfg["model"], user_text, state, recent_context=last_assistant_reply)
            elif search_query and follow_through:
                state = run_browser_agent(client, cfg["model"], user_text)
                reply = summarize_browser_result(client, cfg["model"], user_text, state, recent_context=last_assistant_reply)
            elif is_browser_command(user_text):
                resolved = resolve_site(client, cfg["model"], user_text)
                if resolved:
                    with _browser_lock:
                        state = get_agent().resolve_and_open(resolved)
                    if state.get("url"):
                        reply = summarize_browser_result(client, cfg["model"], user_text, state, recent_context=last_assistant_reply)
                    else:
                        reply = "Maaf ya, sepertinya aku belum berhasil buka situs itu. Coba lagi ya."
                else:
                    state = run_browser_agent(client, cfg["model"], user_text)
                    reply = summarize_browser_result(client, cfg["model"], user_text, state, recent_context=last_assistant_reply)
            else:
                force_browser = False
                if SITE_MENTION.search(user_text) and re.search(r'\b(buka|cari|putar|play|nonton|tonton|mainkan|dengerin|masuk|ganti|pindah)\b', user_text.lower()):
                    force_browser = True
                    print("[Router] Nama situs + aksi terdeteksi → paksa browser.")
                elif ACTIVE_SITE_WORDS.search(user_text) and last_assistant_reply:
                    force_browser = True
                    print("[Router] Rujukan situs aktif terdeteksi → paksa browser.")
                if force_browser:
                    state = run_browser_agent(client, cfg["model"], user_text)
                    reply = summarize_browser_result(client, cfg["model"], user_text, state, recent_context=last_assistant_reply)
                elif BROWSER_HINTS.search(user_text):
                    intent = classify_intent(client, cfg["model"], user_text, last_assistant_reply)
                    if intent == "browser":
                        state = run_browser_agent(client, cfg["model"], user_text)
                        reply = summarize_browser_result(client, cfg["model"], user_text, state, recent_context=last_assistant_reply)
                    else:
                        memory_context = get_memory_context(memory)
                        reply = chat(client, cfg["model"], user_text, history, memory_context)
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

            if (random.random() < cfg["proactive_chance"]
                    and not keyboard.is_pressed(HOTKEY)
                    and not pending_proactive["question"]):
                _spawn_proactive(client, cfg["model"], memory, last_proactive_category, pending_proactive)
        except Exception as e:
            print(f"[Error] Perintah gagal: {e}")
            try:
                speak("Aduh Notron, ada masalah sebentar. Coba ulang ya.", cfg["tts_voice"])
            except Exception:
                pass


if __name__ == "__main__":
    main()
