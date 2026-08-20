import json
from pathlib import Path

OPENCODE_CONFIG_PATH = Path.home() / ".config" / "opencode" / "opencode.json"
PROVIDER_NAME = "cosmoshub"
MODEL = "minimax-m2.5"
STT_LANGUAGE = "id-ID"
TTS_VOICE = "id-ID-GadisNeural"


def load_config():
    with open(OPENCODE_CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)

    providers = config.get("provider", {})
    if PROVIDER_NAME not in providers:
        raise ValueError(f"Provider '{PROVIDER_NAME}' tidak ditemukan di config opencode")

    provider = providers[PROVIDER_NAME]
    options = provider.get("options", {})

    base_url = options.get("baseURL")
    api_key = options.get("apiKey")

    if not base_url or not api_key:
        raise ValueError(f"baseURL atau apiKey tidak ditemukan di provider '{PROVIDER_NAME}'")

    return {
        "base_url": base_url,
        "api_key": api_key,
        "model": MODEL,
        "stt_language": STT_LANGUAGE,
        "tts_voice": TTS_VOICE,
    }
