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
from coding_agent import (
    WorkspaceDetector, ProjectContext, FileOperations, DiffManager,
    TerminalRunner, GitOperations, CodeGenerator, PlanMode
)


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
)

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

# Coding Mode Detection
MODE_PLAN_RE = re.compile(r'\b(mode\s+plan|rencana|plan\s+mode)\b', re.IGNORECASE)
MODE_EXECUTE_RE = re.compile(r'\b(mode\s+eksekusi|execute|lanjut\s+eksekusi|mulai\s+kerjakan)\b', re.IGNORECASE)
MODE_CANCEL_RE = re.compile(r'\b(batal|cancel|nggak\s+jadi|tidak\s+jadi)\b', re.IGNORECASE)

# Coding Command Detection
CODING_COMMAND_RE = re.compile(
    r'\b(buat|tambah|edit|fix|refactor|jalankan|run|test|git|install)\b.*',
    re.IGNORECASE,
)

# Confirmation Detection
CONFIRMATION_YES = re.compile(r'\b(oke|iya|ya|setuju|apply)\b', re.IGNORECASE)
CONFIRMATION_NO = re.compile(r'\b(batal|nggak|tidak|tunggu|cancel)\b', re.IGNORECASE)


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


# Global state for coding mode
coding_agent_state = {
    "mode": "normal",  # "normal", "plan", "execute"
    "plan_mode": None,
    "code_generator": None,
    "workspace_path": None,
    "coding_model": None,
    "pending_change": None,
    "file_operations": None,
    "diff_manager": None,
    "terminal_runner": None,
    "git_operations": None,
}


def is_coding_command(text: str) -> bool:
    """Check apakah text adalah coding command"""
    return bool(CODING_COMMAND_RE.search(text))


def _classify_coding_error(error_str: str) -> str:
    """Classify error type untuk pesan user yang lebih ramah"""
    error_lower = (error_str or "").lower()

    if "401" in error_lower or "invalid_api_key" in error_lower or "unauthorized" in error_lower:
        return "invalid_api_key"
    elif "429" in error_lower or "rate_limit" in error_lower or "quota" in error_lower:
        return "rate_limited"
    elif "timeout" in error_lower or "timed out" in error_lower or "gateway" in error_lower:
        return "timeout"
    elif "connection" in error_lower or "network" in error_lower or "resolve" in error_lower or "dns" in error_lower:
        return "network"
    else:
        return "unknown"


def _get_friendly_error_message(error_type: str) -> str:
    """Get pesan error yang ramah dalam Bahasa Indonesia"""
    messages = {
        "invalid_api_key": (
            "Maaf, API key untuk coding mode tidak valid. "
            "Cek kembali konfigurasi API key di opencode.json, atau bilang 'batal' untuk keluar."
        ),
        "rate_limited": (
            "Maaf, API sedang terlalu sibuk. Coba lagi dalam beberapa menit, "
            "atau bilang 'batal' untuk keluar dari mode plan."
        ),
        "timeout": (
            "Maaf, koneksi ke AI terlalu lama. Coba lagi ya, "
            "atau bilang 'batal' untuk keluar dari mode plan."
        ),
        "network": (
            "Maaf, ada masalah koneksi internet. Cek koneksi kamu, "
            "atau bilang 'batal' untuk keluar dari mode plan."
        ),
        "unknown": (
            "Maaf, ada masalah dengan coding mode. "
            "Bilang 'batal' untuk keluar, lalu coba lagi nanti."
        )
    }
    return messages.get(error_type, messages["unknown"])


def _is_error_response(text: str) -> bool:
    """Detect apakah response mengandung error teknis"""
    if not text:
        return False
    return (
        "Error" in text
        or "error" in text.lower()
        or "Exception" in text
        or text.startswith("Error:")
    )


def _shorten_for_tts(text: str, max_chars: int = 600) -> str:
    """Ringkas teks agar cepat dibacakan TTS (tanpa kode/markdown)."""
    if not text:
        return ""
    speak_text, _ = strip_code_blocks(text)           # buang blok kode
    speak_text = re.sub(r'[*_#`>|]', '', speak_text)  # buang marker markdown
    speak_text = re.sub(r'\s+', ' ', speak_text).strip()
    if len(speak_text) > max_chars:
        speak_text = speak_text[:max_chars].rsplit(' ', 1)[0] + '...'
    return speak_text


def _is_complete_response(text: str) -> bool:
    """Detect apakah response code lengkap (ditandai marker SELESAI)."""
    if not text:
        return False
    if re.search(r'(belum\s+selesai|incomplete|terpotong)', text, re.IGNORECASE):
        return False
    return re.search(r'\bSELESAI\b', text, re.IGNORECASE) is not None


def _validate_api_key(api_key: str, base_url: str, model: str) -> tuple[bool, str]:
    """
    Validasi API key dengan request minimal.
    Returns: (is_valid, error_message)
    """
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url=base_url)

        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "test"}],
            max_tokens=5,
            timeout=15
        )
        if not response.choices:
            return False, "API mengembalikan response kosong"
        return True, ""
    except Exception as e:
        error_str = str(e)
        print(f"[API Validation] Failed ({model}): {error_str}")
        error_type = _classify_coding_error(error_str)
        friendly_msg = _get_friendly_error_message(error_type)
        return False, f"{error_type}: {friendly_msg}"


def handle_mode_switch(user_text: str, cfg: dict) -> str | None:
    """Handle mode switching (plan/execute/cancel)"""
    global coding_agent_state
    
    # Check mode plan trigger
    if MODE_PLAN_RE.search(user_text):
        if coding_agent_state["mode"] == "normal":
            # Validasi API key untuk coding model dulu
            print(f"[Mode Switch] Validating API key untuk {cfg['coding_model']}...")
            is_valid, _ = _validate_api_key(
                cfg["api_key"], cfg["base_url"], cfg["coding_model"]
            )

            model_to_use = cfg["coding_model"]
            model_warning = ""

            if not is_valid:
                print(f"[Mode Switch] {cfg['coding_model']} gagal validasi, mencoba fallback ke {cfg['model']}...")
                is_valid_fb, _ = _validate_api_key(
                    cfg["api_key"], cfg["base_url"], cfg["model"]
                )
                if is_valid_fb:
                    model_to_use = cfg["model"]
                    model_warning = (
                        f"Aku pakai model {cfg['model']} karena {cfg['coding_model']} "
                        f"sedang bermasalah. "
                    )
                else:
                    print(f"[Mode Switch] Fallback {cfg['model']} juga gagal validasi")
                    return (
                        f"Maaf, tidak bisa masuk mode plan. Model {cfg['coding_model']} gagal, "
                        f"dan fallback ke {cfg['model']} juga gagal. "
                        f"Periksa konfigurasi API key di opencode.json."
                    )
            else:
                print("[Mode Switch] Coding model valid")

            # Detect workspace
            detector = WorkspaceDetector()
            workspace = detector.get_active_workspace()
            
            if not workspace:
                workspace = detector.detect_from_process()
            
            if not workspace:
                coding_agent_state["mode"] = "normal"
                return "Maaf, aku nggak bisa detect VS Code workspace. Buka VS Code dulu ya."
            
            coding_agent_state["workspace_path"] = workspace
            coding_agent_state["coding_model"] = model_to_use
            coding_agent_state["plan_mode"] = PlanMode(
                workspace, 
                cfg["api_key"], 
                model_to_use,
                cfg["base_url"]
            )
            coding_agent_state["mode"] = "plan"
            
            return f"Oke, masuk mode plan. {model_warning}Aku detect workspace di {workspace.name}. Kasih tau aku apa yang mau kamu kerjakan, kita diskusi dulu tanpa eksekusi."
    
    # Check mode execute trigger
    elif MODE_EXECUTE_RE.search(user_text) and coding_agent_state["mode"] == "plan":
        # Finalisasi plan summary supaya teringat saat eksekusi
        plan_mode = coding_agent_state.get("plan_mode")
        plan_recap = "sesuai rencana yang kita diskusikan tadi"
        if plan_mode is not None:
            try:
                if not plan_mode.plan_summary:
                    result = plan_mode.finalize_plan()
                    if isinstance(result, dict) and "error" in result:
                        print(f"[Mode Switch] finalize_plan error: {result['error']}")
                    else:
                        print("[Mode Switch] Plan summary berhasil difinalisasi")
                summary = (plan_mode.plan_summary or "").strip()
                if summary:
                    short_summary = re.sub(r'\s+', ' ', summary)[:300]
                    plan_recap = f"sesuai rencana kita: {short_summary}"
                else:
                    plan_recap = "sesuai rencana yang kita diskusikan tadi"
            except Exception as e:
                print(f"[Mode Switch] finalize_plan exception: {e}")
        coding_agent_state["mode"] = "execute"
        return f"Oke, lanjut eksekusi {plan_recap}. Aku langsung kerjakan ya, tinggal kasih tahu kalau ada yang perlu disesuaikan."
    
    # Check mode cancel trigger
    elif MODE_CANCEL_RE.search(user_text) and coding_agent_state["mode"] == "plan":
        coding_agent_state["mode"] = "normal"
        coding_agent_state["plan_mode"] = None
        return "Oke, plan dibatalkan. Kembali ke mode normal."
    
    return None


def handle_coding_command(user_text: str, cfg: dict) -> str:
    """Handle coding commands dalam execute mode"""
    global coding_agent_state
    
    workspace = coding_agent_state["workspace_path"]
    api_key = cfg["api_key"]
    coding_model = coding_agent_state.get("coding_model") or cfg["coding_model"]
    
    # Initialize components jika belum
    if not coding_agent_state["code_generator"]:
        coding_agent_state["code_generator"] = CodeGenerator(api_key, coding_model, cfg["base_url"])
        print(f"[CodingAgent] Menggunakan model {coding_model}")
    if not coding_agent_state["file_operations"]:
        coding_agent_state["file_operations"] = FileOperations(workspace)
    if not coding_agent_state["diff_manager"]:
        coding_agent_state["diff_manager"] = DiffManager()
    if not coding_agent_state["terminal_runner"]:
        coding_agent_state["terminal_runner"] = TerminalRunner(workspace)
    if not coding_agent_state["git_operations"]:
        coding_agent_state["git_operations"] = GitOperations(workspace)
    
    # Get project context
    context_builder = ProjectContext(workspace)
    context = context_builder.get_context()
    
    # Add relevant files ke context
    relevant_files = coding_agent_state["file_operations"].find_relevant_files(user_text, max_files=5)
    context["relevant_files"] = []
    
    for file_path in relevant_files:
        content = coding_agent_state["file_operations"].read_file(file_path, max_lines=100)
        if content:
            context["relevant_files"].append({
                "path": str(file_path.relative_to(workspace)),
                "content": content
            })
    
    # Get plan context jika ada
    plan_context = None
    if coding_agent_state["plan_mode"] and coding_agent_state["plan_mode"].conversation_history:
        plan_context = {
            "plan_summary": coding_agent_state["plan_mode"].plan_summary or "No summary",
            "conversation_history": coding_agent_state["plan_mode"].conversation_history
        }
    
    # Generate code
    print(f"[CodingAgent] Generating code untuk: {user_text}")
    result = coding_agent_state["code_generator"].generate_code(
        context, user_text, plan_context=plan_context
    )
    
    if not result.get("success"):
        return f"Error generating code: {result.get('error', 'Unknown error')}"
    
    created_files = set()
    edited_files = set()
    failed_lines = []
    iterations = 0
    max_iterations = 3
    response_text = result.get("response", "")
    
    while True:
        actions = result.get("actions", [])
        applied_any = False
        completed = _is_complete_response(response_text)
        
        for action in actions:
            if action["type"] == "write":
                file_path = workspace / action["file_path"]
                change = coding_agent_state["file_operations"].write_file(
                    file_path, action["content"], dry_run=False
                )
                if "error" not in change:
                    created_files.add(action["file_path"])
                    applied_any = True
                    print(f"[CodingAgent] File dibuat: {action['file_path']} ({len(action['content'])} chars)")
                    if change.get("diff"):
                        print(f"[CodingAgent] Diff:\n{change['diff']}")
                else:
                    failed_lines.append(f"**{action['file_path']}**: {change['error']}")
            
            elif action["type"] == "edit":
                file_path = workspace / action["file_path"]
                change = coding_agent_state["file_operations"].edit_file(
                    file_path, action["old_string"], action["new_string"], dry_run=False
                )
                if "error" not in change:
                    edited_files.add(action["file_path"])
                    applied_any = True
                    print(f"[CodingAgent] File diedit: {action['file_path']}")
                    if change.get("diff"):
                        print(f"[CodingAgent] Diff:\n{change['diff']}")
                else:
                    failed_lines.append(f"**{action['file_path']}**: {change['error']}")
        
        if completed or not actions:
            break
        
        # Auto-continue: lengkapi file yang belum selesai
        iterations += 1
        if iterations >= max_iterations:
            print(f"[CodingAgent] Maks {max_iterations} iterasi tercapai, file mungkin belum lengkap")
            break
        
        print(f"[CodingAgent] Iterasi lanjut {iterations}/{max_iterations}: melengkapi file...")
        continue_prompt = "Lanjutkan dan lengkapi file yang sedang dibuat. Ini isi file saat ini:\n\n"
        for f in created_files:
            content = coding_agent_state["file_operations"].read_file(workspace / f)
            content_preview = (content or "")[:4000]
            continue_prompt += f"--- ISI SAAT INI {f} ---\n{content_preview}\n\n"
        continue_prompt += "Lengkapi seluruh kode hingga benar-benar selesai. Tulis ulang file secara lengkap. Jika sudah lengkap, akhiri response dengan SELESAI."
        
        result = coding_agent_state["code_generator"].generate_code(
            context, continue_prompt, plan_context=plan_context
        )
        if not result.get("success"):
            failed_lines.append(f"Error melengkapi: {result.get('error', 'Unknown error')}")
            break
        response_text = result.get("response", "")
    
    # Susun reply ringkas (tanpa blok kode, untuk dibaca TTS)
    parts = []
    if not created_files and not edited_files:
        parts.append(str(response_text or "Tidak ada file yang perlu diubah."))
    else:
        parts.append("Oke, ini hasil codingnya:")
        if created_files:
            parts.append(f"File baru: {', '.join(sorted(created_files))}")
        if edited_files:
            parts.append(f"File diubah: {', '.join(sorted(edited_files))}")
        if iterations >= max_iterations and applied_any:
            parts.append("File sudah dibuat tapi mungkin belum sepenuhnya lengkap. Bilang 'lanjutkan' kalau mau aku lengkapi lagi, atau cek langsung di VS Code.")
    parts.extend(failed_lines)
    
    return "\n".join(parts)


def handle_confirmation(user_text: str, cfg: dict) -> str | None:
    """Handle user confirmation untuk pending changes"""
    global coding_agent_state
    
    if not coding_agent_state["pending_change"]:
        return None
    
    if CONFIRMATION_YES.search(user_text):
        # Apply all changes
        applied_files = []
        for change in coding_agent_state["pending_change"]:
            result = coding_agent_state["diff_manager"].apply_change(
                change_id=str(id(change)),
                file_path=change["file_path"],
                original_content=change["original_content"],
                new_content=change["new_content"],
                diff=change["diff"]
            )
            if "error" not in result:
                applied_files.append(change["file_path"])
        
        coding_agent_state["pending_change"] = None
        return f"Oke, aku sudah apply {len(applied_files)} perubahan: {', '.join(applied_files)}"
    
    elif CONFIRMATION_NO.search(user_text):
        # Discard all changes
        coding_agent_state["pending_change"] = None
        return "Oke, perubahan aku batalkan."
    
    return None


def main():
    print("=" * 50)
    print("  Hai! Aku Evy, asisten pribadimu")
    print("=" * 50)

    cfg = load_config()
    print(f"Provider : {cfg['base_url']}")
    print(f"Model    : {cfg['model']}")
    print(f"Coding   : {cfg['coding_model']}")
    print(f"STT Lang : {cfg['stt_language']}")
    print(f"TTS Voice: {cfg['tts_voice']}")
    print("=" * 50)
    print("Tekan Right Alt untuk ngobrol, tekan Right Alt lagi kalau sudah selesai.")
    print("Bilang 'cari ...' untuk buka Google Chrome.")
    print("Bilang 'login' untuk setup akun Google.")
    print("Bilang 'mode plan' untuk coding mode (diskusi tanpa eksekusi).")
    print("Bilang 'mode eksekusi' untuk mulai coding.")
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

            # Handle mode switching (plan/execute/cancel)
            mode_switch = handle_mode_switch(user_text, cfg)
            if mode_switch:
                reply = mode_switch
                speak(reply, cfg["tts_voice"])
                history.append({"role": "user", "content": user_text})
                history.append({"role": "assistant", "content": reply})
                last_assistant_reply = reply
                print(f"[CodingMode] Mode: {coding_agent_state['mode']}")
                continue

            # Handle confirmation untuk pending changes
            if coding_agent_state["pending_change"]:
                confirmation = handle_confirmation(user_text, cfg)
                if confirmation:
                    reply = confirmation
                    speak(reply, cfg["tts_voice"])
                    history.append({"role": "user", "content": user_text})
                    history.append({"role": "assistant", "content": reply})
                    last_assistant_reply = reply
                    continue

            # Handle plan mode conversation
            if coding_agent_state["mode"] == "plan" and coding_agent_state["plan_mode"]:
                if not MODE_CANCEL_RE.search(user_text) and not MODE_EXECUTE_RE.search(user_text):
                    # Continue planning conversation
                    plan_response = coding_agent_state["plan_mode"].continue_planning(user_text)
                    if _is_error_response(plan_response):
                        error_type = _classify_coding_error(plan_response)
                        reply = _get_friendly_error_message(error_type)
                        print(f"[PlanMode] Error: {plan_response}")
                        print(f"[PlanMode] Friendly: {reply}")
                    else:
                        reply = plan_response
                    speak(_shorten_for_tts(reply), cfg["tts_voice"])
                    history.append({"role": "user", "content": user_text})
                    history.append({"role": "assistant", "content": reply})
                    last_assistant_reply = reply
                    continue

            # Handle coding commands dalam execute mode
            if coding_agent_state["mode"] == "execute" and is_coding_command(user_text):
                reply = handle_coding_command(user_text, cfg)
                if _is_error_response(reply):
                    error_type = _classify_coding_error(reply)
                    friendly_reply = _get_friendly_error_message(error_type)
                    print(f"[CodingAgent] Error: {reply}")
                    print(f"[CodingAgent] Friendly: {friendly_reply}")
                    reply = friendly_reply
                speak(_shorten_for_tts(reply), cfg["tts_voice"])
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
