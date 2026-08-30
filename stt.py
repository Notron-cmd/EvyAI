import json
import os
import time
from pathlib import Path

import sounddevice as sd
import soundfile as sf
import numpy as np
import speech_recognition as sr
import keyboard
from io import BytesIO
from config import HOTKEY

SAMPLE_RATE = 16000
CHANNELS = 1

GLOSSARY_PATH = Path(__file__).resolve().parent / "stt_glossary.json"
GLOSSARY_MAX = 40
STOPWORDS = {
    "saya", "kamu", "kita", "apa", "yang", "dan", "di", "ke", "itu", "ini",
    "dengan", "untuk", "dari", "sudah", "belum", "tidak", "ya", "oke", "oh",
    "aja", "jangan", "bisa", "tolong", "buka", "cari", "buat",
}

_WHISPER_MODEL = None
_SEED_WORDS = [
    "vm", "ai speech", "coding", "vs code", "browser", "wifi",
    "aplikasi", "sistem parkir", "bahasa C", "login", "error",
]


def _load_glossary():
    if not GLOSSARY_PATH.exists():
        return {w: 1 for w in _SEED_WORDS}
    try:
        data = json.loads(GLOSSARY_PATH.read_text(encoding="utf-8"))
        words = data.get("words", {})
        if not words:
            words = {w: 1 for w in _SEED_WORDS}
    except Exception:
        words = {w: 1 for w in _SEED_WORDS}
    # Pertahankan maksimal N kata terpopuler
    top = sorted(words.items(), key=lambda kv: kv[1], reverse=True)[:GLOSSARY_MAX]
    return dict(top)


def _save_glossary(words):
    GLOSSARY_PATH.write_text(
        json.dumps({"words": words}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _trim_glossary(words):
    top = sorted(words.items(), key=lambda kv: kv[1], reverse=True)[:GLOSSARY_MAX]
    return dict(top)


def add_glossary_word(word):
    """Tambahkan kata penting ke glosarium (belajar dari koreksi/disambiguasi)."""
    if not word:
        return
    clean = word.strip().strip(".,!?;:\"").lower()
    if not clean or clean in STOPWORDS or len(clean) > 60:
        return
    words = _load_glossary()
    words[clean] = words.get(clean, 0) + 1
    _save_glossary(_trim_glossary(words))
    print(f"[STT] Kata '{clean}' masuk glosarium (total {len(_load_glossary())} entri).")


def _build_initial_prompt():
    words = _load_glossary()
    top = sorted(words.items(), key=lambda kv: kv[1], reverse=True)[:20]

    # Kata paling sering mendapat penekanan ekstra
    max_count = top[0][1] if top else 1
    parts = []
    for word, count in top:
        emphasis = max(1, min(3, 1 + count // (max(1, max_count // 2))))
        parts.append((word + " ") * emphasis)
    return "Kata-kata penting yang sering dipakai: " + ", ".join(p.strip() for p in parts) + "."


def _get_whisper_model():
    global _WHISPER_MODEL
    if _WHISPER_MODEL is None:
        from faster_whisper import WhisperModel
        _WHISPER_MODEL = WhisperModel("small", device="cpu", compute_type="int8")
    return _WHISPER_MODEL


def record_until_hotkey():
    print("[STT] Merekam... tekan Right Alt lagi untuk berhenti.")

    audio_chunks = []
    chunk_duration = 0.1
    chunk_size = int(SAMPLE_RATE * chunk_duration)

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, dtype="float32") as stream:
        while True:
            data, _ = stream.read(chunk_size)
            audio_chunks.append(data.copy())

            if keyboard.is_pressed(HOTKEY):
                while keyboard.is_pressed(HOTKEY):
                    pass
                break

    audio = np.concatenate(audio_chunks)
    if audio.ndim > 1 and audio.shape[1] == 1:
        audio = audio[:, 0]
    print("[STT] Selesai merekam.")
    return audio


def _whisper_lang(language):
    return {"id-ID": "id", "en-US": "en", "ja-JP": "ja"}.get(language, "id")


def _transcribe_whisper(audio, language):
    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    model = _get_whisper_model()
    segments, info = model.transcribe(
        audio,
        language=_whisper_lang(language),
        temperature=0,
        condition_on_previous_text=False,
        vad_filter=True,
        initial_prompt=_build_initial_prompt(),
    )

    texts, logprobs, no_speeches = [], [], []
    for seg in segments:
        texts.append(seg.text)
        logprobs.append(seg.avg_logprob)
        no_speeches.append(seg.no_speech_prob)

    if not texts:
        return None

    if max(no_speeches) > 0.8:
        return None

    text = " ".join(texts).strip()
    if not text:
        return None

    avg_logprob = float(np.mean(logprobs)) if logprobs else -1.0
    confidence = round(float(np.exp(max(avg_logprob, -5.0))), 3)
    print(f"[STT] Kamu bilang: {text} (conf {confidence})")
    return {"text": text, "confidence": confidence, "alternatives": []}


def _transcribe_google(audio, language):
    buf = BytesIO()
    sf.write(buf, audio, SAMPLE_RATE, format="WAV")
    buf.seek(0)

    recognizer = sr.Recognizer()
    with sr.AudioFile(buf) as source:
        audio_data = recognizer.record(source)

    try:
        data = recognizer.recognize_google(audio_data, language=language, show_all=True)

        if isinstance(data, dict) and data.get("alternative"):
            best = data["alternative"][0]["transcript"]
            confidence = data["alternative"][0].get("confidence")
            alternatives = [
                alt for alt in data["alternative"][1:]
                if alt.get("transcript") and alt["transcript"] != best
            ]
            print(f"[STT] Kamu bilang: {best}")
            return {
                "text": best,
                "confidence": confidence,
                "alternatives": alternatives[:2],
            }

        if isinstance(data, str) and data.strip():
            print(f"[STT] Kamu bilang: {data}")
            return {"text": data, "confidence": None, "alternatives": []}

        print("[STT] Hmm, aku tidak bisa dengar dengan jelas. Coba lagi ya.")
        return None
    except sr.UnknownValueError:
        print("[STT] Hmm, aku tidak bisa dengar dengan jelas. Coba lagi ya.")
        return None
    except sr.RequestError as e:
        print(f"[STT] Koneksi bermasalah: {e}")
        return None


def audio_to_text(audio, language):
    # Utamakan faster-whisper (lokal, akurat); fallback ke Google bila gagal.
    try:
        result = _transcribe_whisper(audio, language)
        if result:
            return result
    except Exception as e:
        print(f"[STT] Whisper gagal ({e}), pakai Google.")

    return _transcribe_google(audio, language)


def listen(language):
    audio = record_until_hotkey()
    return audio_to_text(audio, language)