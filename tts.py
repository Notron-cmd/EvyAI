import asyncio
import tempfile
import os
import threading
import time
import keyboard
import edge_tts
import sounddevice as sd
import soundfile as sf
from config import HOTKEY


def _run_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()


_TTS_LOOP = asyncio.new_event_loop()
threading.Thread(target=_run_loop, args=(_TTS_LOOP,), name="tts-loop", daemon=True).start()


def speak(text, voice):
    print(f"[TTS] Mengucapkan: {text[:80]}...")

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        async def gen():
            c = edge_tts.Communicate(
                text, voice,
                rate="+10%",
                volume="-10%",
                pitch="+15Hz",
            )
            await c.save(tmp_path)

        try:
            asyncio.run_coroutine_threadsafe(gen(), _TTS_LOOP).result()
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