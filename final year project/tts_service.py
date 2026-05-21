import os
import time
from dotenv import load_dotenv
from typing import Optional
import base64

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

async def generate_speech(text: str, language_code: str = "hi-IN", speaker: str = "pooja") -> Optional[str]:
    """
    Generates speech using Sarvam's Bulbul model.
    Returns: Base64 encoded audio string or None on failure.
    """
    if not SARVAM_API_KEY:
        print("ERROR: SARVAM_API_KEY not found in environment.")
        return None

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
            return None
        else:
            print(f"ERROR: TTS Request failed with status {response.status_code}: {response.text}")
            return None
    except Exception as e:
        print(f"ERROR: Exception in generate_speech: {e}")
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
