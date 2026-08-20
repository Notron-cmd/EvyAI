import asyncio
import tempfile
import os
import subprocess
import sys
import edge_tts
import sounddevice as sd
import soundfile as sf


def speak(text, voice):
    print(f"[TTS] Mengucapkan: {text[:80]}...")

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        code = f'''
import asyncio
import edge_tts
async def gen():
    c = edge_tts.Communicate({text!r}, {voice!r}, rate="+20%")
    await c.save({tmp_path!r})
asyncio.run(gen())
'''
        subprocess.run(
            [sys.executable, "-c", code],
            check=True,
            capture_output=True,
        )

        data, samplerate = sf.read(tmp_path)
        sd.play(data, samplerate)
        sd.wait()
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    print("[TTS] Selesai.")
