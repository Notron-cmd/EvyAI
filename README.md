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
