import os
import requests
from dotenv import load_dotenv
from typing import Optional
import base64

load_dotenv()

SARVAM_API_KEY = os.getenv("SARVAM_API_KEY")
TTS_URL = "https://api.sarvam.ai/text-to-speech"

def generate_speech(text: str, language_code: str = "hi-IN", speaker: str = "pooja") -> Optional[str]:
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
        "audio_format": "wav"
    }

    try:
        response = requests.post(TTS_URL, json=payload, headers=headers)
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
    # Test
    print("Starting TTS Test...")
    audio_b64 = generate_speech("नमस्ते, आपका ऑर्डर ले लिया गया है।", language_code="hi-IN")
    if audio_b64:
        print("Success: Generated audio (first 100 chars):", audio_b64[:100])
        with open("test_tts.wav", "wb") as f:
            f.write(base64.b64decode(audio_b64))
        print("Saved to test_tts.wav")
    else:
        print("Failed to generate speech.")
