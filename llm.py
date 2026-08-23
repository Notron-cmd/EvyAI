from openai import OpenAI
import re
import json

SYSTEM_PROMPT = (
    "Kamu adalah Evy, sahabat virtual yang super ceria, asik, dan penuh semangat. "
    "Kamu itu kayak teman dekat yang seru diajak ngobrol, bukan asisten kaku. "
    "Kepribadianmu: ceria banget, suka bercanda tipis-tipis, antusias, sering pakai 'hehe' atau 'haha' kalau lagi seneng, "
    "dan selalu kasih semangat ke lawan bicaramu. "
    "Gunakan bahasa Indonesia gaul dan santai, seperti ngobrol sama bestie. "
    "Pakai kata 'aku' dan 'kamu', boleh juga pakai 'nih', 'dong', 'yuk', 'banget', 'sih', 'deh' supaya makin natural. "
    "PENTING: Kalau diminta melakukan sesuatu (bikin kode, cari info, buka web, dll), LANGSUNG KERJAKAN tanpa tanya balik. "
    "Jangan tanya 'mau yang mana?' atau 'gimana mau mulai?' - langsung kasih hasilnya. "
    "TAPI kalau user bercerita hal pribadi (lagi ngapain, hobi, kerjaan, proyek, perasaan, cerita keseharian), "
    "jangan langsung menutup obrolan - lanjutkan dengan SATU pertanyaan follow-up yang natural dan hangat biar obrolan hidup. "
    "KAMU MEMILIKI AKSES CHROME: kamu bisa membuka website, mencari di internet, dan melihat isi halaman yang sudah terbuka. "
    "Kalau user minta cari/buka sesuatu, jangan pernah bilang tidak bisa akses browser - itu sudah dikerjakan lewat Chrome. "
    "WAJIB: Semua kode program HARUS dibungkus dalam markdown code block (triple backtick), contohnya: "
    "```c\nint main() { return 0; }\n``` "
    "JANGAN pernah menulis kode tanpa dibungkus code block. JANGAN baca ulang kode di luar code block. "
    "Jawab MAKSIMAL 2-3 kalimat saja di luar code block, tetap ceria dan fun, cocok untuk diucapkan lewat suara. "
    "Jangan gunakan emoji sama sekali dalam jawabanmu. "
    "DILARANG KERAS memakai sintaks tool call seperti [TB:...], [TOOL:...], [TOOL_CALL], <tool_call>, atau format internal lainnya. "
    "Jawab selalu dalam teks biasa bahasa Indonesia."
)


def _strip_tool_markers(text):
    patterns = [
        r'\[TB:[^\]]*\]',
        r'\[TOOL:[^\]]*\]',
        r'\[PLAN:[^\]]*\]',
        r'\[ACTION:[^\]]*\]',
        r'\[SEARCH:[^\]]*\]',
        r'<tool_call>.*?</tool_call>',
        r'<tool_code>.*?</tool_code>',
        r'<tool_result>.*?</tool_result>',
        r'<tool_response>.*?</tool_response>',
        r'<tool_calls>.*?</tool_calls>',
        r'<tool_[a-z_]+>.*?</tool_[a-z_]+>',
        r'<minimax:tool_call>.*?</minimax:tool_call>',
        r'<invoke\s+name="[^"]*">.*?</invoke>',
        r'<[a-z]+:tool_[a-z_]+>.*?</[a-z]+:tool_[a-z_]+>',
        r'\[TOOL[A-Z_]*\].*?\[/TOOL[A-Z_]*\]',
        r'\[/?TOOL[A-Z_]*\]',
    ]
    for pattern in patterns:
        text = re.sub(pattern, '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>]{0,30}>', '', text)
    return text.strip()


def _clean(text):
    return _strip_tool_markers(_strip_emoji(text))


def _strip_emoji(text):
    emoji_pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F"
        "\U0001F300-\U0001F5FF"
        "\U0001F680-\U0001F6FF"
        "\U0001F1E0-\U0001F1FF"
        "\U00002702-\U000027B0"
        "\U000024C2-\U0001F251"
        "\U0001F900-\U0001F9FF"
        "\U0001FA00-\U0001FA6F"
        "\U0001FA70-\U0001FAFF"
        "\U00002600-\U000026FF"
        "\u200b"
        "\ufeff"
        "]+",
        flags=re.UNICODE,
    )
    return emoji_pattern.sub("", text)


def strip_code_blocks(text):
    code_pattern = re.compile(r'```[\s\S]*?```', re.MULTILINE)
    codes = code_pattern.findall(text)
    text_only = code_pattern.sub('', text)
    inline_code_pattern = re.compile(r'`[^`]+`')
    inline_codes = inline_code_pattern.findall(text_only)
    text_only = inline_code_pattern.sub('', text_only)
    code_line_pattern = re.compile(
        r'^[ \t]*(?:'
        r'#include\s*<.+>'
        r'|#include\s+".+"'
        r'|import\s+\S+'
        r'|from\s+\S+\s+import'
        r'|def\s+\w+\s*\('
        r'|class\s+\w+'
        r'|public\s+static\s+void'
        r'|int\s+main\s*\('
        r'|void\s+\w+\s*\('
        r'|printf\s*\('
        r'|scanf\s*\('
        r'|return\s+[^;]+;'
        r'|if\s*\(.*\)\s*\{'
        r'|else\s*\{'
        r'|for\s*\(.*\)\s*\{'
        r'|while\s*\(.*\)\s*\{'
        r'|console\.log\s*\('
        r'|System\.out\.print'
        r'|print\s*\('
        r'|}\s*$'
        r'|[a-zA-Z_]\w*\s*=\s*[^=].*[;}]'
        r')[^\n]*$',
        re.MULTILINE,
    )
    fallback_codes = code_line_pattern.findall(text_only)
    if fallback_codes and len(fallback_codes) >= 3:
        text_only = code_line_pattern.sub('', text_only)
        codes.append('\n'.join(fallback_codes))
    codes.extend(inline_codes)
    text_only = re.sub(r'\n{3,}', '\n\n', text_only).strip()
    return text_only, codes


def extract_memory(client, model, user_text, reply):
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": (
                    "Tugasmu: extract informasi penting tentang USER (pengguna) dari percakapan ini. "
                    "PENTING: 'Evy' atau 'Evi' adalah nama AI assistant, BUKAN user. Jangan pernah extract itu sebagai nama user. "
                    "Nama user hanya dianggap valid jika user menyebutkan nama dirinya sendiri, bukan saat memanggil Evy. "
                    "Return JSON dengan format: "
                    "{\"user_info\": {\"key\": \"value\"}, \"facts\": [\"fact1\", \"fact2\"], \"preferences\": [\"pref1\"]} "
                    "Hanya extract jika ada info baru yang relevan tentang user. Kalau tidak ada, return {\"user_info\": {}, \"facts\": [], \"preferences\": []} "
                    "Contoh info yang layak diingat: nama user, umur, pekerjaan, hobi, makanan favorit, bahasa yang dipelajari, project yang dikerjakan, dll. "
                    "JANGAN pakai emoji."
                )},
                {"role": "user", "content": f"User bilang: {user_text}\nEvy jawab: {reply}"},
            ],
            max_tokens=150,
            temperature=0.3,
        )
        content = response.choices[0].message.content.strip()
        content = _clean(content)
        match = re.search(r'\{.*\}', content, re.DOTALL)
        if match:
            return json.loads(match.group())
        return {"user_info": {}, "facts": [], "preferences": []}
    except Exception as e:
        print(f"[Memory Extract] Error: {e}")
        return {"user_info": {}, "facts": [], "preferences": []}


def extract_memory_and_summary(client, model, user_text, reply):
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": (
                    "Tugasmu: extract informasi dari percakapan user dengan Evy (AI assistant). "
                    "PENTING: 'Evy' atau 'Evi' adalah nama AI assistant, BUKAN user. Jangan pernah extract itu sebagai nama user. "
                    "NAMA USER TETAP: 'Notron'. Jangan simpan nama lain sebagai nama user kecuali user secara eksplisit bilang ganti nama. "
                    "GUNAKAN key Bahasa Indonesia untuk user_info (contoh: nama, umur, pekerjaan, lokasi, hobi, sedang_dipelajari). "
                    "JANGAN pakai key bahasa Inggris seperti name, occupation, location. "
                    "Return SATU JSON object dengan format: "
                    "{\"user_info\": {\"key\": \"value\"}, \"facts\": [\"fact1\"], \"preferences\": [\"pref1\"], \"summary\": \"ringkasan topik\"} "
                    "user_info/facts/preferences: hanya info baru tentang user. Kalau tidak ada, kosongkan array/object-nya. "
                    "Jangan extract info yang sudah jelas duplikat atau sudah pernah ada. "
                    "ATURAN FACTS: hanya fakta yang PENTING dan tahan lama (skill, project, hobi, info pribadi). "
                    "TOLAK fakta trivia/temporer seperti 'user menyapa', 'user berterima kasih', 'user pernah bicara dengan Evy', 'sedang mendengarkan lagu'. "
                    "ATURAN SUMMARY: isi summary HANYA jika ada TOPIK BERARTI yang dibahas (project, pertanyaan teknis, rekomendasi, diskusi, aktivitas user yang penting). "
                    "Kalau obrolannya cuma sapaan, basa-basi, terima kasih, koreksi nama, atau pertanyaan sekali lewat tanpa topik - return summary KOSONG \"\". "
                    "summary maksimal 15 kata, fokus pada apa yang user minta/tanyakan. "
                    "Contoh info user yang layak diingat: umur, pekerjaan, hobi, makanan favorit, bahasa yang dipelajari, project yang dikerjakan. "
                    "JANGAN pakai emoji."
                )},
                {"role": "user", "content": f"User bilang: {user_text}\nEvy jawab: {reply}"},
            ],
            max_tokens=180,
            temperature=0.3,
        )
        content = response.choices[0].message.content.strip()
        content = _clean(content)
        match = re.search(r'\{.*\}', content, re.DOTALL)
        if match:
            data = json.loads(match.group())
            data.setdefault("user_info", {})
            data.setdefault("facts", [])
            data.setdefault("preferences", [])
            data.setdefault("summary", "")
            return data
        return {"user_info": {}, "facts": [], "preferences": [], "summary": ""}
    except Exception as e:
        print(f"[Memory Extract] Error: {e}")
        return {"user_info": {}, "facts": [], "preferences": [], "summary": ""}


def extract_conversation_summary(client, model, user_text, reply):
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": (
                    "Tugasmu: buat summary singkat (maksimal 15 kata) tentang topik percakapan ini. "
                    "Focus pada apa yang user tanyakan atau minta, bukan detail jawaban. "
                    "Return HANYA summary-nya saja, tanpa prefix apapun. "
                    "Contoh: 'User minta bantuan coding Python' atau 'User tanya tentang JavaScript' atau 'User cerita tentang project web'. "
                    "JANGAN pakai emoji. JANGAN pakai tanda kutip."
                )},
                {"role": "user", "content": f"User bilang: {user_text}\nEvy jawab: {reply}"},
            ],
            max_tokens=30,
            temperature=0.3,
        )
        summary = response.choices[0].message.content.strip()
        summary = _clean(summary).strip('"').strip("'")
        if len(summary.split()) <= 15:
            return summary
        return " ".join(summary.split()[:15])
    except Exception as e:
        print(f"[Summary Extract] Error: {e}")
        return None


def extract_search_intent(client, model, text):
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": (
                    "Tugasmu: tentukan apakah user ini ingin mencari sesuatu di internet. "
                    "Kalau YA, balas HANYA dengan query pencarian yang singkat dan tepat (tanpa penjelasan). "
                    "Kalau TIDAK, balas 'NONE'. "
                    "JANGAN pakai emoji. JANGAN pakai tanda kutip."
                )},
                {"role": "user", "content": text},
            ],
            max_tokens=50,
            temperature=0.3,
        )
        reply = response.choices[0].message.content.strip()
        reply = _clean(reply).strip('"').strip("'")
        if reply.upper() == "NONE":
            return None
        return reply
    except Exception:
        return None


def create_client(base_url, api_key):
    return OpenAI(
        base_url=base_url,
        api_key=api_key,
        timeout=60.0,
        max_retries=2,
    )


BROWSER_ACTIONS_DESC = (
    "Aksi yang tersedia:\n"
    "- {\"action\": \"open_url\", \"url\": \"...\"} - buka URL/situs tertentu\n"
    "- {\"action\": \"search_web\", \"query\": \"...\"} - cari di Google\n"
    "- {\"action\": \"search_youtube\", \"query\": \"...\"} - cari video di YouTube\n"
    "- {\"action\": \"type_text\", \"text\": \"...\"} - ketik teks di kolom yang fokus\n"
    "- {\"action\": \"press_key\", \"key\": \"Enter\"} - tekan Enter/Escape\n"
    "- {\"action\": \"click_text\", \"text\": \"...\"} - klik elemen berdasarkan teks terlihat\n"
    "- {\"action\": \"click_first_result\"} - masuk ke hasil pencarian pertama (cara paling andal untuk buka artikel)\n"
    "- {\"action\": \"scroll\", \"direction\": \"down\"} - scroll down/up\n"
    "- {\"action\": \"go_back\"} - kembali ke halaman sebelumnya\n"
    "- {\"action\": \"go_forward\"} - maju ke halaman berikutnya\n"
    "- {\"action\": \"read_content\"} - baca isi penuh halaman saat ini\n"
    "- {\"action\": \"done\"} - tugas selesai, berhenti\n"
)


def plan_browser_action(client, model, command, page_state):
    system_prompt = (
        "Kamu adalah pengendali browser yang mengerjakan perintah user di Chrome. "
        "Diberikan perintah dan kondisi halaman saat ini (URL, judul, teks terlihat). "
        + BROWSER_ACTIONS_DESC +
        "Return HANYA satu JSON array berisi urutan aksi, contoh: "
        "[{\"action\": \"open_url\", \"url\": \"https://www.youtube.com\"}, {\"action\": \"type_text\", \"text\": \"python\"}, {\"action\": \"press_key\", \"key\": \"Enter\"}, {\"action\": \"done\"}] "
        "Aturan: kerjakan tugas langkah demi langkah. Gunakan type_text hanya setelah halaman yang butuh input terbuka. "
        "Jika user minta mencari video/channel di YouTube, langsung pakai aksi search_youtube (tanpa perlu buka youtube dulu). "
        "Jika user minta mencari/memasukkan sesuatu di website tertentu, buka websitenya dulu baru type_text. "
        "Jika perintah user menyebut kata seperti 'masuk', 'buka artikel', 'baca', 'kesimpulan', 'rangkum', 'ringkas', 'detail', "
        "maka kamu WAJIB masuk ke halaman website/artikel yang relevan dan baca isinya sebelum done. "
        "Gunakan aksi click_first_result untuk masuk ke hasil pencarian pertama, atau open_url langsung ke URL artikel yang relevan. "
        "JANGAN pernah done saat masih berada di halaman hasil pencarian jika user minta masuk/baca isi. "
        "Jika user bilang 'di website ini/situs tersebut/di sana/di situ/situsnya/website yang kebuka/webnya', "
        "maka gunakan situs yang SEDANG DIBUKA (lihat URL halaman sekarang): cari kolom pencarian internal situs (type_text) lalu tekan Enter. "
        "Jika URL halaman sekarang sudah adalah situs yang dimaksud, JANGAN buka Google - langsung pakai type_text di situs itu. "
        "Jika ada kolom pencarian, ketik query di situ lalu Enter, JANGAN buka search engine baru. "
        "Akiri dengan {\"action\": \"done\"} saat tugas benar-benar selesai. Maksimal 5 aksi. "
        "JANGAN pakai penjelasan, HANYA JSON array. JANGAN pakai emoji."
    )
    user_content = (
        f"Perintah user: {command}\n"
        f"Kondisi halaman sekarang: URL={page_state.get('url')}, Title={page_state.get('title')}\n"
        f"Teks halaman: {page_state.get('text', '')[:1200]}"
    )
    valid = {"open_url", "search_web", "search_youtube", "type_text",
             "press_key", "click_text", "click_first_result", "scroll",
             "go_back", "go_forward", "read_content", "done"}

    def extract_actions(content):
        content = _clean(content)
        for pattern in (r'\[.*\]', r'\{.*\}'):
            match = re.search(pattern, content, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group())
                except Exception:
                    continue
                items = data if isinstance(data, list) else data.get("actions", []) if isinstance(data, dict) else []
                if isinstance(items, list):
                    return [a for a in items
                            if isinstance(a, dict) and a.get("action") in valid]
        return None

    for attempt in range(2):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                max_tokens=400,
                temperature=0.2,
            )
            content = response.choices[0].message.content.strip()
            actions = extract_actions(content)
            if actions:
                return actions
        except Exception as e:
            print(f"[Plan] Error (attempt {attempt+1}): {e}")
    return None


def resolve_site(client, model, text):
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": (
                    "Ini tugas klasifikasi sederhana. Tentukan situs web yang dimaksud user dari teksnya. "
                    "Balas HANYA satu kata nama situs saja (contoh: youtube, gmail, instagram, whatsapp, tiktok). "
                    "JANGAN menulis kode, penjelasan, kalimat, atau apapun selain nama situs. "
                    "Kalau user TIDAK menyebut nama situs apapun, balas 'NONE'."
                )},
                {"role": "user", "content": text},
            ],
            max_tokens=10,
            temperature=0.0,
        )
        reply = response.choices[0].message.content.strip()
        reply = _strip_emoji(reply).strip('"').strip("'").strip(".")
        if "```" in reply or len(reply) > 40:
            return None
        if reply.upper() == "NONE":
            return None
        if not re.fullmatch(r"[A-Za-z ._'-]+", reply):
            return None
        return reply
    except Exception:
        return None


def summarize_browser_result(client, model, command, state, recent_context=""):
    system_content = (
        "Kamu adalah Evy, sahabat virtual yang ceria dan natural. "
        "Kamu BARU SAJA mengerjakan perintah user di Chrome (membuka situs / mencari di internet / membaca artikel). "
        "Kamu BISA melihat isi halaman yang sedang terbuka, itu sudah diberikan padamu. "
        "DILARANG keras bilang kamu tidak bisa akses browser, tidak bisa melihat halaman, atau menyuruh user melakukannya sendiri. "
        "Jika user meminta kesimpulan/rangkuman/ringkasan isi artikel atau halaman, berikan KESIMPULAN 2-3 kalimat "
        "berdasarkan isi halaman yang diberikan. Jika hanya membuka/mencari, konfirmasi singkat 1-2 kalimat dan sebutkan 1 hal yang terlihat. "
        "Jawab bahasa Indonesia gaul santai, tanpa emoji, tanpa markdown, tanpa kode, tanpa sintaks tool call. "
        "Tugasmu HANYA menceritakan hasil yang SUDAH terjadi - kamu TIDAK BISA menjalankan aksi/tool call lagi di mode ini. "
        "DILARANG keras menulis blok [TOOL_CALL], <tool_call>, atau rencana langkah berikutnya. "
        "Kalau tujuan belum sepenuhnya tercapai, cukup ceritakan apa yang sudah terlihat sekarang."
    )
    user_content = (
        f"Perintah user: {command}\n"
        f"Kondisi halaman sekarang: URL={state.get('url')}, Title={state.get('title')}\n"
        f"Isi halaman: {state.get('text', '')[:2500]}"
    )
    if recent_context:
        user_content += f"\n\nKonteks percakapan sebelumnya (Evy): {recent_context}"
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_content},
                {"role": "user", "content": user_content},
            ],
            max_tokens=250,
            temperature=0.3,
        )
        reply = response.choices[0].message.content.strip()
        reply = _clean(reply)
        print(f"[LLM] Rangkuman browser: {reply}")
        return reply
    except Exception as e:
        print(f"[LLM] Rangkuman error: {e}")
        return "Udah aku buka ya Notron, silahkan cek di Chrome."


def classify_intent(client, model, user_text, recent_context=""):
    try:
        user_content = user_text
        if recent_context:
            user_content = f"Konversi sebelumnya: {recent_context}\nPerintah user sekarang: {user_text}"
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": (
                    "Kamu adalah classifier. Klasifikasikan permintaan user menjadi SATU kategori: "
                    "'browser' (mencari/membuka situs/navigasi web/baca halaman/artikel/scroll/klik/konfirmasi lanjut ke situs seperti 'ya silakan ke wikipedia'), "
                    "'code' (minta kode program), atau 'chat' (obrolan biasa lainnya). "
                    "Balas HANYA satu kata kategori. JANGAN pakai sintaks tool call, penjelasan, atau emoji."
                )},
                {"role": "user", "content": user_content},
            ],
            max_tokens=10,
            temperature=0.0,
        )
        reply = response.choices[0].message.content.strip()
        reply = _clean(reply).strip('"').strip("'").strip(".")
        if reply.lower() in ("browser", "code"):
            return reply.lower()
        return "chat"
    except Exception:
        return "chat"


PROACTIVE_CATEGORIES = (
    "aktivitas user saat ini",
    "hobi dan minat",
    "musik, film, atau series",
    "makanan dan minuman favorit",
    "rencana dan impian",
    "hal random atau favorit",
    "kenangan santai",
    "pertanyaan playful atau lucu",
    "cuaca atau suasana sekitar",
    "hal yang baru user pelajari",
)

PROACTIVE_FALLBACK_QUESTIONS = [
    "Kamu lagi ngapain sekarang?",
    "Kalau lagi gabut, kamu biasanya suka ngapain?",
    "Lagu apa yang lagi kamu putar akhir-akhir ini?",
    "Film atau series apa yang akhir-akhir ini kamu tonton?",
    "Lagi craving makanan apa hari ini?",
    "Kalau akhir pekan nanti ada rencana seru nggak?",
    "Kalau disuruh pilih satu tempat buat liburan, mau ke mana?",
    "Ada kenangan lucu yang bikin kamu ketawa kalau inget?",
    "Kalau bisa punya satu kekuatan super, mau kekuatan apa?",
    "Di tempatmu lagi hujan atau panas sih?",
    "Ada project baru yang lagi kamu kerjain nggak?",
    "Minuman favoritmu apa nih, kopi atau teh?",
    "Kalau bisa jago satu skill instan, skill apa yang kamu mau?",
    "Hewan favoritmu apa?",
    "Kamu tipe orang yang suka begadang atau tidur cepat?",
    "Kalau lagi dengerin musik, genre apa yang paling kamu suka?",
    "Ada tempat favorit yang bikin kamu nyaman nggak?",
    "Kalau bisa ngobrol sama satu orang terkenal, mau ngobrol sama siapa?",
]


def pick_proactive_category(last_category=""):
    import random
    if last_category:
        options = [c for c in PROACTIVE_CATEGORIES if c != last_category]
        if options:
            return random.choice(options)
    return random.choice(PROACTIVE_CATEGORIES)


def generate_proactive_question(client, model, memory_context="", category=""):
    import random
    if not category:
        category = random.choice(PROACTIVE_CATEGORIES)
    system = (
        "Kamu adalah Evy, sahabat virtual yang ceria dan asik. "
        "Tugasmu: buat SATU pertanyaan santai dan personal untuk user supaya obrolan terasa hidup dan dua arah. "
        "Buat pertanyaan dalam kategori ini: '" + category + "'. "
        "Pertanyaan boleh BEDA TOTAL dari topik pembicaraan yang sedang berlangsung. Jangan selalu tentang proyek, kerjaan, atau aktivitas user. "
        "Memori tentang user boleh dipakai biar terasa personal, tapi tidak wajib dan jangan terlalu menyerempet privasi. "
        "Output HANYA satu pertanyaan pendek bahasa Indonesia gaul. Tanpa emoji, tanpa tool call, tanpa penjelasan, tanpa markdown."
    )
    user_content = f"Memori tentang user: {memory_context if memory_context else '(tidak ada)'}"
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            max_tokens=60,
            temperature=0.9,
        )
        reply = response.choices[0].message.content.strip()
        reply = _clean(reply).strip('"').strip("'").strip()
        if not reply or len(reply) < 5 or len(reply) > 120:
            raise ValueError("pertanyaan tidak valid")
        print(f"[Proactive] Pertanyaan ({category}): {reply}")
        return reply
    except Exception as e:
        print(f"[Proactive] Fallback ({e})")
        return random.choice(PROACTIVE_FALLBACK_QUESTIONS)


def resolve_search_query(client, model, raw_query, recent_context=""):
    system = (
        "Tugasmu: ubah permintaan pencarian user menjadi KEYWORD pencarian yang konkret dan lengkap. "
        "Kalau user pakai kata rujukan seperti 'lagu ini', 'itu', 'yang tadi', 'lagunya', 'videonya' - "
        "ganti dengan judul/nama yang SEBENARNYA berdasarkan konteks obrolan sebelumnya. "
        "Buang kata perintah seperti 'play', 'putar', 'mainkan', 'dengerin', 'carikan', 'dong' dari keyword. "
        "Output HANYA keyword pencarian akhir. Tanpa penjelasan, tanpa tanda kutip, tanpa emoji."
    )
    user_content = (
        f"Konteks obrolan terakhir:\n{recent_context if recent_context else '(tidak ada)'}\n\n"
        f"Permintaan pencarian user: {raw_query}"
    )
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            max_tokens=40,
            temperature=0.2,
        )
        q = _clean(response.choices[0].message.content.strip()).strip('"').strip("'").strip()
        if q and 2 <= len(q) <= 100:
            print(f"[Resolver] '{raw_query}' -> '{q}'")
            return q
        return None
    except Exception as e:
        print(f"[Resolver] Error: {e}")
        return None


def chat(client, model, user_text, history=None, memory_context=""):
    system_content = SYSTEM_PROMPT
    if memory_context:
        system_content += f"\n\nMEMORY (informasi yang kamu ingat tentang user):\n{memory_context}"

    messages = [{"role": "system", "content": system_content}]

    if history:
        messages.extend(history)

    messages.append({"role": "user", "content": user_text})

    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=500,
        )
        reply = response.choices[0].message.content.strip()
        reply = _clean(reply)
        print(f"[LLM] Jawaban: {reply}")
        return reply
    except Exception as e:
        print(f"[LLM] Error: {e}")
        return "Maaf ya, aku lagi ada masalah nih. Coba lagi sebentar ya."
