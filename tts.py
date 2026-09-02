import asyncio
import tempfile
import os
import re
import threading
import time
import random
import keyboard
import numpy as np
import edge_tts
import sounddevice as sd
import soundfile as sf
from pydub import AudioSegment
from config import HOTKEY

_FFMPEG_DIR = os.path.join(
    os.environ.get("LOCALAPPDATA", ""),
    "Microsoft", "WinGet", "Links",
)
_FFMPEG = os.path.join(_FFMPEG_DIR, "ffmpeg.exe")
_FFPROBE = os.path.join(_FFMPEG_DIR, "ffprobe.exe")
if os.path.exists(_FFMPEG):
    AudioSegment.converter = _FFMPEG
if os.path.exists(_FFPROBE):
    AudioSegment.ffprobe = _FFPROBE


_SENTENCE_PROFILES = {
    "question": {
        "rate": "-5%",
        "volume": "+0%",
        "pitch": "+20Hz",
        "pause_ms": 600,
    },
    "exclamation": {
        "rate": "+5%",
        "volume": "+10%",
        "pitch": "+25Hz",
        "pause_ms": 500,
    },
    "casual": {
        "rate": "+5%",
        "volume": "-5%",
        "pitch": "+10Hz",
        "pause_ms": 350,
    },
    "statement": {
        "rate": "+0%",
        "volume": "+0%",
        "pitch": "+0Hz",
        "pause_ms": 400,
    },
}


def _detect_sentence_type(text):
    text_stripped = text.strip()
    text_lower = text_stripped.lower()
    
    if text_stripped.endswith("?"):
        return "question"
    
    if text_stripped.endswith("!"):
        return "exclamation"
    
    casual_markers = [
        r'\b(nah|kan|dong|sih|deh|nih|tuh|kok)\b',
        r'\b(ya|yuk|ayo)\b',
        r'\b(kayak|kayaknya|sepertinya)\b',
    ]
    for pattern in casual_markers:
        if re.search(pattern, text_lower):
            return "casual"
    
    return "statement"


def _add_human_variation(profile):
    p = dict(profile)
    
    rate_val = int(p["rate"].replace("%", "").replace("+", ""))
    rate_val += random.randint(-3, 3)
    p["rate"] = f"{rate_val:+d}%"
    
    pitch_val = int(p["pitch"].replace("Hz", "").replace("+", ""))
    pitch_val += random.randint(-3, 3)
    p["pitch"] = f"{pitch_val:+d}Hz"
    
    p["pause_ms"] += random.randint(-50, 50)
    
    return p


def _run_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()


_TTS_LOOP = asyncio.new_event_loop()
threading.Thread(target=_run_loop, args=(_TTS_LOOP,), name="tts-loop", daemon=True).start()

_FEEDBACK_EVENT = threading.Event()


_SENTENCE_SPLIT = re.compile(r'(?<=[.!?])\s+|\n{2,}')


def _split_tts(text):
    parts = [p.strip() for p in _SENTENCE_SPLIT.split(text) if p.strip()]
    return parts if parts else [text.strip()]


def _generate(text, voice, tmp_path):
    parts = _split_tts(text)

    if len(parts) == 1:
        sentence_type = _detect_sentence_type(parts[0])
        profile = _add_human_variation(_SENTENCE_PROFILES[sentence_type])

        async def gen():
            c = edge_tts.Communicate(
                parts[0], voice,
                rate=profile["rate"],
                volume=profile["volume"],
                pitch=profile["pitch"],
            )
            await c.save(tmp_path)
        asyncio.run_coroutine_threadsafe(gen(), _TTS_LOOP).result()
        return

    async def stream_one(part):
        sentence_type = _detect_sentence_type(part)
        profile = _add_human_variation(_SENTENCE_PROFILES[sentence_type])

        c = edge_tts.Communicate(
            part, voice,
            rate=profile["rate"],
            volume=profile["volume"],
            pitch=profile["pitch"],
        )
        buf = b""
        async for chunk in c.stream():
            if chunk["type"] == "audio":
                buf += chunk["data"]
        return buf, profile["pause_ms"]

    async def gather_all():
        return await asyncio.gather(*[stream_one(p) for p in parts])

    results = asyncio.run_coroutine_threadsafe(gather_all(), _TTS_LOOP).result()

    try:
        tmp_files = []
        segments = []
        for buf, pause_ms in results:
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as seg:
                seg.write(buf)
                seg_path = seg.name
            tmp_files.append(seg_path)
            segments.append((AudioSegment.from_file(seg_path, format="mp3"), pause_ms))

        merged = None
        for seg, pause_ms in segments:
            if merged is None:
                merged = seg
            else:
                merged = merged + AudioSegment.silent(duration=pause_ms) + seg

        if merged is not None:
            target_peak = -14.0
            peak = merged.max_dBFS
            if peak is not None and peak != float("-inf"):
                merged = merged.apply_gain(target_peak - peak)
            merged.export(tmp_path, format="mp3", bitrate="192k")
    finally:
        for p in tmp_files:
            if os.path.exists(p):
                os.remove(p)


def _speak_impl(text, voice):
    print(f"[TTS] Mengucapkan: {text[:80]}...")

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        try:
            _generate(text, voice, tmp_path)
        except Exception as e:
            print(f"[TTS] Error: {e}")
            return

        data, samplerate = sf.read(tmp_path)
        sd.play(data, samplerate)
        duration = len(data) / samplerate
        start = time.time()
        interrupted = False
        while time.time() - start < duration:
            if keyboard.is_pressed(HOTKEY):
                sd.stop()
                interrupted = True
                print("[TTS] Dipotong oleh user (barge-in).")
                break
            time.sleep(0.05)
        if not interrupted:
            sd.stop()
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    print("[TTS] Selesai.")


def _feedback_impl(text, voice):
    print(f"[TTS] Feedback: {text[:60]}...")

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        try:
            _generate(text, voice, tmp_path)
        except Exception as e:
            print(f"[TTS] Feedback gen error: {e}")
            return

        if _FEEDBACK_EVENT.is_set():
            print("[TTS] Feedback dibatalkan sebelum diputar.")
            return

        data, samplerate = sf.read(tmp_path, dtype="float32")
        if data.ndim == 1:
            data = np.column_stack([data, data])
        stream = sd.OutputStream(samplerate=samplerate, channels=data.shape[1], dtype="float32")
        stream.start()
        chunk = int(samplerate * 0.1)
        interrupted = False
        for i in range(0, len(data), chunk):
            if _FEEDBACK_EVENT.is_set():
                interrupted = True
                print("[TTS] Feedback dihentikan oleh jawaban berikutnya.")
                break
            stream.write(data[i:i + chunk])
        stream.stop()
        stream.close()
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    print("[TTS] Feedback selesai.")


def speak(text, voice):
    _speak_impl(text, voice)


def start_feedback(text, voice):
    _FEEDBACK_EVENT.clear()
    def worker():
        try:
            _feedback_impl(text, voice)
        except Exception as e:
            print(f"[TTS] Feedback error: {e}")
    threading.Thread(target=worker, daemon=True).start()


def stop_feedback():
    _FEEDBACK_EVENT.set()