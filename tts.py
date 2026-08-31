import asyncio
import tempfile
import os
import re
import threading
import time
import keyboard
import numpy as np
import edge_tts
import sounddevice as sd
import soundfile as sf
from config import HOTKEY


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
        # Satu bagian utuh: jalur cepat satu request (tanpa overhead kecil).
        async def gen():
            c = edge_tts.Communicate(
                parts[0], voice,
                rate="+10%",
                volume="-10%",
                pitch="+15Hz",
            )
            await c.save(tmp_path)
        asyncio.run_coroutine_threadsafe(gen(), _TTS_LOOP).result()
        return

    async def stream_one(part):
        c = edge_tts.Communicate(
            part, voice,
            rate="+10%",
            volume="-10%",
            pitch="+15Hz",
        )
        buf = b""
        async for chunk in c.stream():
            if chunk["type"] == "audio":
                buf += chunk["data"]
        return buf

    async def gather_all():
        results = await asyncio.gather(*[stream_one(p) for p in parts])
        return b"".join(results)

    mp3 = asyncio.run_coroutine_threadsafe(gather_all(), _TTS_LOOP).result()
    with open(tmp_path, "wb") as f:
        f.write(mp3)


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