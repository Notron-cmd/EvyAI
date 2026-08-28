# Evy - Asisten Suara AI Indonesia

Evy adalah asisten suara AI berbasis Python yang ramah, ceria, dan responsif. Dibuat dengan kombinasi Speech-to-Text (STT), Large Language Model (LLM), dan Text-to-Speech (TTS) untuk pengalaman obrolan suara yang natural dalam bahasa Indonesia.

## Fitur Utama

- **Obrolan Suara Real-time**: Tekan Right Alt untuk bicara, Right Alt lagi untuk berhenti
- **Kepribadian Ceria**: Evy dirancang sebagai sahabat virtual yang asik dan penuh semangat
- **Kontrol Aplikasi Lokal**: Buka/tutup app desktop & UWP, atur volume, kontrol media player
- **Pencarian Google Otomatis**: Bilang "cari [sesuatu]" dan Evy akan buka Chrome dengan hasil pencarian
- **Auto-Save Kode**: Minta Evy bikin kode, otomatis disimpan ke folder `output/` tanpa dibacakan
- **Chrome Integration**: Pakai profil Chrome terpisah dengan anti-detection untuk akses web
- **Login Akun Google**: Setup akun Google sekali untuk akses berbagai layanan web
- **Coding Assistant (Voice-Powered)**: Evy bisa membantu coding di VS Code dengan mode plan & execute
  - Otomatis detect workspace dari VS Code yang sedang aktif
  - Smart context building (baca file tree, dependencies, relevant files)
  - Mode Plan: diskusi approach tanpa eksekusi
  - Mode Execute: generate & apply code dengan konfirmasi
  - Support terminal commands & git operations
- **Lightweight**: Tidak butuh GPU lokal, semua via API cloud

## Tech Stack

| Komponen | Library | Fungsi |
|----------|---------|--------|
| STT | SpeechRecognition + Google | Konversi suara ke teks (bahasa Indonesia) |
| LLM | OpenAI SDK (Cosmos Hub API) | Otak AI untuk generate response |
| TTS | edge-tts | Konversi teks ke suara natural Indonesia |
| Browser | Playwright | Kontrol Chrome untuk pencarian web |
| Audio | sounddevice + soundfile | Record mic & play audio |
| Hotkey | keyboard | Detect tombol Right Alt |

## Instalasi

### Prerequisites
- Python 3.10+
- Mikrofon
- Google Chrome (untuk fitur pencarian)
- API key dari Cosmos Hub atau provider OpenAI-compatible lainnya

### Setup

1. Clone repository ini:
```bash
git clone https://github.com/username/evy-voice-assistant.git
cd evy-voice-assistant
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Install Playwright Chromium:
```bash
python -m playwright install chromium
```

4. Setup konfigurasi:
   - Edit `config.py` dan sesuaikan `BASE_URL`, `API_KEY`, dan `MODEL` dengan provider LLM kamu
   - Contoh provider yang kompatibel: OpenAI, Groq, Together AI, atau Cosmos Hub

5. Setup akun Google (opsional):
```bash
python login_setup.py
```
Login Google manual di Chrome yang terbuka, lalu tutup setelah selesai.

## Cara Penggunaan

### Jalankan Evy
```bash
python main.py
```
Atau double-click `start.bat` di Windows.

### Commands

- **Tekan Right Alt**: Mulai merekam suara
- **Tekan Right Alt lagi**: Stop merekam dan proses
- **"buka [nama app]"**: Jalankan aplikasi lokal (Chrome, VS Code, Word, dll.)
- **"tutup [nama app]"**: Tutup aplikasi yang sedang berjalan
- **"besarkan/kecilkan volume"**: Atur volume sistem
- **"volume ke 50"**: Setel volume ke persentase tertentu (0-100)
- **"mute" / "bisukan"**: Bisukan suara
- **"pause" / "lanjutkan"**: Kontrol media player (play/pause)
- **"cari [sesuatu]"**: Buka Google Chrome dengan hasil pencarian
- **"buka [folder] di vscode"**: Buka folder di VS Code (dicari di Documents/Downloads/Desktop)
- **"login"**: Setup akun Google
- **Ctrl+C**: Keluar

### Contoh Interaksi

```
[STT] Kamu bilang: "buatkan kalkulator sederhana dalam C"
[LLM] Jawaban: Oke, aku buatin kalkulator C nih...
[Code] Disimpan: output/code_20250120_143022_0.c
[TTS] Mengucapkan: Oke, aku buatin kalkulator C nih...
```

```
[STT] Kamu bilang: "cari website belajar JavaScript"
[Browser] Cari di Google: website belajar JavaScript
[TTS] Mengucapkan: Sudah aku dapatkan Notron, silahkan cek di chrome
```

### Coding Assistant Mode

Evy bisa menjadi voice-powered coding assistant seperti opencode, tapi dikontrol via suara. Fitur ini memungkinkan Evy untuk:

- **Detect VS Code workspace** otomatis dari window yang aktif
- **Generate code** dengan context-aware (baca file tree, dependencies, relevant files)
- **Edit files** dengan diff preview dan konfirmasi sebelum apply
- **Run terminal commands** (npm, pytest, git, dll)
- **Git operations** (status, add, commit, push, pull)
- **Multi-turn conversation** untuk clarifikasi requirements

#### Setup Coding Mode

1. Install dependency tambahan:
```bash
pip install pywin32
```

2. Pastikan API key untuk **qwen-3.7-max** sudah dikonfigurasi di `config.py`:
```python
CODING_MODEL = "qwen-3.7-max"
```

#### Cara Penggunaan

**1. Masuk ke Plan Mode (Diskusi Approach)**
```
User: "mode plan"
Evy: "Oke, aku masuk ke plan mode. Kita bisa diskusi approach sebelum eksekusi. 
      Workspace apa yang mau kamu kerjakan?"

User: "buka project di Documents/animeProjectV2"
Evy: "Oke, aku detect workspace di Documents/animeProjectV2. 
      Apa yang mau kita kerjakan?"

User: "buat fitur login dengan JWT authentication"
Evy: "Oke, mari kita rencanakan fitur login dengan JWT...
      [Evy akan tanya clarifikasi, suggest approach, kasih code snippets]"

User: "oke, lanjut ke eksekusi"
Evy: "Oke, aku eksekusi plan yang sudah kita sepakati..."
```

**2. Direct Execute Mode**
```
User: "mode execute"
Evy: "Oke, aku masuk ke execute mode. Apa yang mau dikerjakan?"

User: "buat function untuk calculate fibonacci"
Evy: "Oke, aku akan buat function fibonacci di src/utils/math.js...
      [Generate code dengan diff preview]
      Mau apply perubahan ini? Bilang 'oke' untuk apply atau 'batal' untuk cancel."

User: "oke"
Evy: "Oke, perubahan sudah diapply ke src/utils/math.js"
```

**3. Terminal Commands**
```
User: "jalankan npm test"
Evy: "Oke, aku jalankan npm test di terminal...
      [Output terminal ditampilkan]
      Semua test passed!"

User: "git status"
Evy: "Oke, aku cek git status...
      Ada 3 file yang berubah: src/auth.js, src/utils.js, package.json"
```

**4. Git Operations**
```
User: "git commit dengan message 'add login feature'"
Evy: "Oke, aku commit dengan message 'add login feature'...
      Commit berhasil! 3 files changed."

User: "git push"
Evy: "Oke, aku push ke remote...
      Push berhasil!"
```

#### Voice Commands untuk Coding

**Mode Control:**
- `"mode plan"` - Masuk ke plan mode (diskusi tanpa eksekusi)
- `"mode execute"` - Masuk ke execute mode (langsung eksekusi)
- `"batal"` - Keluar dari coding mode

**Code Generation:**
- `"buat [feature/function/component]"` - Generate code baru
- `"edit [file] untuk [perubahan]"` - Edit existing file
- `"refactor [code/function]"` - Refactor code

**Terminal & Git:**
- `"jalankan [command]"` - Run terminal command (npm, pytest, dll)
- `"git [status/add/commit/push/pull]"` - Git operations

**File Operations:**
- `"baca file [filename]"` - Read file content
- `"cari file yang mengandung [keyword]"` - Search files
- `"buat file baru [filename]"` - Create new file

#### Smart Context Building

Evy menggunakan smart context building untuk memberikan code yang relevan:

1. **File Tree Analysis**: Scan struktur project (max 3 level)
2. **Dependencies Detection**: Baca package.json, requirements.txt, Cargo.toml
3. **Relevant Files**: Cari files yang relevan dengan request (max 5 files, 100 lines each)
4. **Pattern Detection**: Detect framework, style, libraries dari existing code

Contoh context yang dikirim ke LLM:
```
PROJECT STRUCTURE:
myproject/
├── src/
│   ├── auth/
│   │   ├── login.js
│   │   └── middleware.js
│   ├── models/
│   │   └── User.js
│   └── utils/
│       └── helpers.js
├── package.json
└── README.md

DEPENDENCIES:
express@4.18.0, bcrypt@5.1.0, jsonwebtoken@9.0.0

RELEVANT FILES:
- src/auth/login.js (50 lines)
- src/models/User.js (30 lines)
- src/auth/middleware.js (40 lines)

DETECTED PATTERNS:
- Framework: Express.js
- Style: CommonJS (require/module.exports)
- Pattern: Router-based, async/await
```

#### Model Configuration

Evy menggunakan **model switching** untuk efisiensi:

| Task | Model | Alasan |
|------|-------|--------|
| Chat/Search/General | minimax-m2.5 | Cepat, murah, cukup untuk percakapan |
| Coding/Plan Mode | qwen-3.7-max | Powerful untuk code generation |

Konfigurasi di `config.py`:
```python
MODEL = "minimax-m2.5"           # Untuk general tasks
CODING_MODEL = "qwen-3.7-max"    # Untuk coding tasks
```

#### Safety Features

1. **Dry-run Mode**: Semua perubahan ditampilkan sebagai diff dulu sebelum apply
2. **Confirmation Required**: User harus konfirmasi "oke" untuk apply perubahan
3. **Rollback Support**: Pending changes bisa di-discard dengan "batal"
4. **Workspace Detection**: Hanya aktif di VS Code workspace yang terdeteksi

#### Troubleshooting Coding Mode

**Evy tidak detect workspace:**
- Pastikan VS Code sedang aktif dan window-nya tidak minimized
- Cek apakah pywin32 sudah terinstall: `pip install pywin32`
- Restart Evy dan buka VS Code dengan project

**Error: "API key not found":**
- Cek `config.py` apakah `CODING_MODEL` dan API key sudah dikonfigurasi
- Pastikan provider support model qwen-3.7-max

**Code generation lambat:**
- qwen-3.7-max lebih lambat dari minimax karena lebih powerful
- Tunggu 5-10 detik untuk response
- Cek koneksi internet

**Perubahan tidak diapply:**
- Pastikan user bilang "oke" untuk konfirmasi
- Cek diff preview di console untuk melihat perubahan yang akan diapply
- Kalau ada error, cek log di console

## Struktur Project

```
AI SPEECH/
├── main.py              # Entry point & orchestrator
├── stt.py               # Speech-to-Text module
├── llm.py               # LLM integration & intent extraction
├── tts.py               # Text-to-Speech module
├── browser.py           # Chrome Playwright automation
├── local_apps.py        # Kontrol app lokal, volume & media
├── config.py            # Configuration loader
├── memory.py            # Persistent memory management
├── login_setup.py       # Google account setup script
├── start.bat            # Windows launcher
├── requirements.txt     # Python dependencies
└── output/              # Generated code files (auto-created)
```

## Konfigurasi

### Ganti Voice TTS
Edit `config.py`:
```python
TTS_VOICE = "id-ID-GadisNeural"  # Suara perempuan Indonesia
# atau
TTS_VOICE = "id-ID-ArdiNeural"   # Suara laki-laki Indonesia
```

Lihat semua voice yang tersedia: https://docs.microsoft.com/en-us/azure/cognitive-services/speech-service/language-support

### Ganti Model LLM
Edit `config.py`:
```python
MODEL = "gpt-4"           # OpenAI GPT-4
MODEL = "llama-3.1-70b"   # Groq Llama
MODEL = "minimax-m2.5"    # Cosmos Hub MiniMax
```

### Ganti Bahasa STT
Edit `config.py`:
```python
STT_LANGUAGE = "id-ID"  # Indonesia
STT_LANGUAGE = "en-US"  # English (US)
STT_LANGUAGE = "ja-JP"  # Japanese
```

## Troubleshooting

### Error: "asyncio.run() cannot be called from a running event loop"
Ini terjadi kalau Playwright dan edge-tts conflict. Sudah di-fix dengan subprocess isolation di `tts.py`.

### Error: "TargetClosedError: BrowserContext.new_page"
Chrome ditutup manual. Sudah di-fix dengan auto-recovery di `browser.py` - akan restart browser otomatis.

### Error: Google minta verifikasi saat search
Jalankan `login_setup.py` atau bilang "login" ke Evy, lalu login Google manual. Session tersimpan permanen.

### Kode masih dibacakan TTS
System prompt sudah diupdate untuk memaksa kode dalam markdown code block. Kalau masih terjadi, update model LLM yang lebih patuh (seperti GPT-4 atau Claude).

## Kontribusi

Pull request diterima! Untuk perubahan besar, buka issue dulu untuk diskusi.

## Lisensi

MIT License - bebas digunakan dan dimodifikasi.

## Credits

- Edge TTS voices oleh Microsoft
- Google Speech Recognition
- Playwright untuk browser automation
- OpenAI SDK untuk LLM integration

---

**Note**: Project ini untuk pembelajaran dan penggunaan pribadi. Pastikan API key tidak di-commit ke repository publik.
