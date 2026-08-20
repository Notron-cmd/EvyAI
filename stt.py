import sounddevice as sd
import soundfile as sf
import numpy as np
import speech_recognition as sr
import keyboard
from io import BytesIO

SAMPLE_RATE = 16000
CHANNELS = 1


def record_until_f2():
    print("[STT] Merekam... tekan F2 lagi untuk berhenti.")

    audio_chunks = []
    chunk_duration = 0.1
    chunk_size = int(SAMPLE_RATE * chunk_duration)

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, dtype="float32") as stream:
        while True:
            data, _ = stream.read(chunk_size)
            audio_chunks.append(data.copy())

            if keyboard.is_pressed("f2"):
                while keyboard.is_pressed("f2"):
                    pass
                break

    audio = np.concatenate(audio_chunks)
    print("[STT] Selesai merekam.")
    return audio


def audio_to_text(audio, language):
    buf = BytesIO()
    sf.write(buf, audio, SAMPLE_RATE, format="WAV")
    buf.seek(0)

    recognizer = sr.Recognizer()
    with sr.AudioFile(buf) as source:
        audio_data = recognizer.record(source)

    try:
        text = recognizer.recognize_google(audio_data, language=language)
        print(f"[STT] Kamu bilang: {text}")
        return text
    except sr.UnknownValueError:
        print("[STT] Hmm, aku tidak bisa dengar dengan jelas. Coba lagi ya.")
        return None
    except sr.RequestError as e:
        print(f"[STT] Koneksi bermasalah: {e}")
        return None


def listen(language):
    audio = record_until_f2()
    return audio_to_text(audio, language)
