"""
Pipeline de traducción en tiempo real para videollamadas.
  Deepgram STT → Claude → ElevenLabs TTS
"""

import os
import anthropic

_LANG_NAMES = {
    "en": "English",
    "es": "Spanish",
    "pt": "Portuguese",
    "fr": "French",
}


def translate_text(text: str, source_lang: str, target_lang: str) -> str:
    if not text.strip():
        return ""
    client = anthropic.Anthropic(api_key=os.getenv("CLAUDE_API_KEY", ""))
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        messages=[{
            "role": "user",
            "content": (
                f"Translate from {_LANG_NAMES.get(source_lang, source_lang)} to "
                f"{_LANG_NAMES.get(target_lang, target_lang)}. "
                f"Return ONLY the translation, nothing else:\n\n{text}"
            ),
        }],
    )
    return msg.content[0].text.strip()


def synthesize_speech(text: str, language: str = "en") -> bytes:
    if not text.strip():
        return b""
    from elevenlabs import ElevenLabs
    client  = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY", ""))
    # Use env var per language or fall back to a multilingual default voice
    voice_id = os.getenv(
        f"ELEVENLABS_VOICE_{language.upper()}",
        os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM"),  # Rachel
    )
    gen = client.text_to_speech.convert(
        text=text,
        voice_id=voice_id,
        model_id="eleven_flash_v2_5",
        output_format="mp3_44100_128",
    )
    return b"".join(gen)
