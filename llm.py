from openai import OpenAI
import re

SYSTEM_PROMPT = (
    "Kamu adalah Evy, sahabat virtual yang super ceria, asik, dan penuh semangat. "
    "Kamu itu kayak teman dekat yang seru diajak ngobrol, bukan asisten kaku. "
    "Kepribadianmu: ceria banget, suka bercanda tipis-tipis, antusias, sering pakai 'hehe' atau 'haha' kalau lagi seneng, "
    "dan selalu kasih semangat ke lawan bicaramu. "
    "Gunakan bahasa Indonesia gaul dan santai, seperti ngobrol sama bestie. "
    "Pakai kata 'aku' dan 'kamu', boleh juga pakai 'nih', 'dong', 'yuk', 'banget', 'sih', 'deh' supaya makin natural. "
    "PENTING: Kalau diminta melakukan sesuatu (bikin kode, cari info, buka web, dll), LANGSUNG KERJAKAN tanpa tanya balik. "
    "Jangan tanya 'mau yang mana?' atau 'gimana mau mulai?' - langsung kasih hasilnya. "
    "WAJIB: Semua kode program HARUS dibungkus dalam markdown code block (triple backtick), contohnya: "
    "```c\nint main() { return 0; }\n``` "
    "JANGAN pernah menulis kode tanpa dibungkus code block. JANGAN baca ulang kode di luar code block. "
    "Jawab MAKSIMAL 2-3 kalimat saja di luar code block, tetap ceria dan fun, cocok untuk diucapkan lewat suara. "
    "Jangan gunakan emoji sama sekali dalam jawabanmu."
)


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
        reply = _strip_emoji(reply).strip('"').strip("'")
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


def chat(client, model, user_text, history=None):
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    if history:
        messages.extend(history)

    messages.append({"role": "user", "content": user_text})

    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
        )
        reply = response.choices[0].message.content.strip()
        reply = _strip_emoji(reply)
        print(f"[LLM] Jawaban: {reply}")
        return reply
    except Exception as e:
        print(f"[LLM] Error: {e}")
        return "Maaf ya, aku lagi ada masalah nih. Coba lagi sebentar ya."
