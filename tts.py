import asyncio
import tempfile
import os
import subprocess
import sys
import time
import keyboard
import edge_tts
import sounddevice as sd
import soundfile as sf
from config import HOTKEY


def speak(text, voice):
    print(f"[TTS] Mengucapkan: {text[:80]}...")

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        code = f'''
import asyncio
import edge_tts
async def gen():
    c = edge_tts.Communicate(
        {text!r}, {voice!r},
        rate="+10%",
        volume="-10%",
        pitch="+15Hz",
    )
    await c.save({tmp_path!r})
asyncio.run(gen())
'''
        try:
            result = subprocess.run(
                [sys.executable, "-c", code],
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as e:
            print(f"[TTS] Error: {e.stderr.decode('utf-8', errors='replace')}")
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
