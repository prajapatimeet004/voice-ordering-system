import os
import time
import base64
import asyncio
import tempfile
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

SARVAM_API_KEY = os.getenv("SARVAM_API_KEY")
TTS_URL = "https://api.sarvam.ai/text-to-speech"

import httpx

# Persistent HTTP client — avoids TCP/TLS handshake on every call
_tts_client: Optional[httpx.AsyncClient] = None

async def _get_client() -> httpx.AsyncClient:
    global _tts_client
    if _tts_client is None or _tts_client.is_closed:
        _tts_client = httpx.AsyncClient(timeout=15.0)
    return _tts_client

def _google_tts(text: str, language_code: str) -> Optional[str]:
    from google.cloud import texttospeech
    client = texttospeech.TextToSpeechClient()
    synthesis_input = texttospeech.SynthesisInput(text=text)
    
    if "hi" in language_code.lower():
        voice_lang = "hi-IN"
        voice_name = "hi-IN-Standard-A"
    else:
        voice_lang = "en-IN"
        voice_name = "en-IN-Standard-A"
        
    voice = texttospeech.VoiceSelectionParams(
        language_code=voice_lang,
        name=voice_name
    )
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3
    )
    response = client.synthesize_speech(
        input=synthesis_input,
        voice=voice,
        audio_config=audio_config
    )
    return base64.b64encode(response.audio_content).decode("utf-8")

def _gtts_fallback(text: str, language_code: str) -> Optional[str]:
    from gtts import gTTS
    lang = "hi" if "hi" in language_code.lower() else "en"
    tts = gTTS(text=text, lang=lang)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as fp:
        temp_filename = fp.name
    try:
        tts.save(temp_filename)
        with open(temp_filename, "rb") as f:
            audio_bytes = f.read()
        return base64.b64encode(audio_bytes).decode("utf-8")
    finally:
        if os.path.exists(temp_filename):
            os.remove(temp_filename)

async def generate_speech(text: str, language_code: str = "hi-IN", speaker: str = "pooja") -> Optional[str]:
    """
    Generates speech using Sarvam's Bulbul model with fallbacks to Google Cloud TTS and gTTS.
    Returns: Base64 encoded audio string or None on failure.
    """
    # ── 1. Try Sarvam AI ──
    if SARVAM_API_KEY:
        headers = {
            "api-subscription-key": SARVAM_API_KEY,
            "Content-Type": "application/json"
        }
        
        payload = {
            "inputs": [text],
            "model": "bulbul:v3",
            "speaker": speaker,
            "language_code": language_code,
            "audio_format": "mp3"
        }

        try:
            start = time.time()
            client = await _get_client()
            response = await client.post(TTS_URL, json=payload, headers=headers)
            elapsed = (time.time() - start) * 1000
            print(f"DEBUG: [TTS] Sarvam response in {elapsed:.0f}ms (status={response.status_code})")
            
            if response.status_code == 200:
                resp_json = response.json()
                audio_data = resp_json.get("audios") or resp_json.get("audio_content") or resp_json.get("audio")
                
                if isinstance(audio_data, list) and len(audio_data) > 0:
                    return audio_data[0]
                elif isinstance(audio_data, str):
                    return audio_data
            else:
                print(f"ERROR: Sarvam TTS failed with status {response.status_code}: {response.text}")
        except Exception as e:
            print(f"ERROR: Exception in Sarvam TTS: {e}")
    else:
        print("WARNING: SARVAM_API_KEY not found in environment. Skipping Sarvam TTS.")

    # ── 2. Fallback to Google Cloud TTS ──
    try:
        print("DEBUG: [TTS] Attempting Google Cloud TTS fallback...")
        google_audio = await asyncio.to_thread(_google_tts, text, language_code)
        if google_audio:
            print("DEBUG: [TTS] Google Cloud TTS succeeded!")
            return google_audio
    except Exception as e:
        print(f"ERROR: Google Cloud TTS fallback failed: {e}")

    # ── 3. Fallback to gTTS ──
    try:
        print("DEBUG: [TTS] Attempting gTTS fallback...")
        gtts_audio = await asyncio.to_thread(_gtts_fallback, text, language_code)
        if gtts_audio:
            print("DEBUG: [TTS] gTTS succeeded!")
            return gtts_audio
    except Exception as e:
        print(f"ERROR: gTTS fallback failed: {e}")

    # ── 4. All failed ──
    print("ERROR: All TTS options (Sarvam, Google Cloud TTS, gTTS) failed.")
    return None

if __name__ == "__main__":
    import asyncio
    # Test
    async def test():
        print("Starting TTS Test...")
        audio_b64 = await generate_speech("Namaste, aapka order le liya gaya hai.", language_code="hi-IN")
        if audio_b64:
            print("Success: Generated audio (first 100 chars):", audio_b64[:100])
            with open("test_tts.mp3", "wb") as f:
                f.write(base64.b64decode(audio_b64))
            print("Saved to test_tts.mp3")
        else:
            print("Failed to generate speech.")
    asyncio.run(test())

