import os
import asyncio
import time
from dotenv import load_dotenv
from audio_utils import trim_silence, safe_remove
# from sarvamai import AsyncSarvamAI # Lazy import

load_dotenv()
API_KEY = os.getenv("SARVAM_API_KEY")

if not API_KEY:
    raise ValueError("❌ SARVAM_API_KEY not found in .env")

_sarvam_client = None
_sarvam_loop = None

def get_sarvam_client():
    global _sarvam_client, _sarvam_loop
    current_loop = asyncio.get_event_loop()
    # Create a new client if the event loop has changed (e.g. new asyncio.run())
    if _sarvam_client is None or _sarvam_loop is not current_loop:
        from sarvamai import AsyncSarvamAI
        _sarvam_client = AsyncSarvamAI(api_subscription_key=API_KEY)
        _sarvam_loop = current_loop
    return _sarvam_client

async def close_client():
    """Cleanly close the async HTTP client to prevent event loop warnings."""
    global _sarvam_client
    if _sarvam_client and hasattr(_sarvam_client, '_client') and _sarvam_client._client:
        await _sarvam_client._client.aclose()

async def transcribe_chunk(wav_filename, orders_dict, current_table, processed_audio_list=None):
    """
    Transcribes a single audio chunk by sending it directly to the Sarvam API.
    Silero VAD (trim_silence) is intentionally skipped here because:
    1. The browser already performs VAD — only speech segments are sent.
    2. torchaudio/torio segfaults on this machine when loading FFmpeg extensions.
    """
    try:
        if not os.path.exists(wav_filename):
            print(f"DEBUG: Audio file not found: {wav_filename}")
            return

        # If the caller wants the processed audio bytes, read them
        if processed_audio_list is not None:
            with open(wav_filename, "rb") as af:
                processed_audio_list.append(af.read())

        client = get_sarvam_client()
        
        # Simple retry logic for transient network issues
        max_retries = 3
        retry_delay = 1
        transcript_text = ""
        
        for attempt in range(max_retries):
            try:
                with open(wav_filename, "rb") as f:
                    response = await client.speech_to_text.transcribe(
                        model="saaras:v3",
                        file=f,
                        language_code="en-IN"
                    )
                transcript_text = getattr(response, "transcript", "")
                print(f"DEBUG: Sarvam API response transcript: '{transcript_text}'")
                break # Success
            except Exception as req_err:
                if attempt < max_retries - 1:
                    print(f"DEBUG: Transcription attempt {attempt+1} failed ({req_err}). Retrying in {retry_delay}s...")
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2 # Exponential backoff
                else:
                    raise req_err # Re-raise if all retries fail
        
        if transcript_text.strip():
            orders_dict[current_table]["segments"].append({
                "text": transcript_text
            })
            orders_dict[current_table]["full_transcript"] += " " + transcript_text.strip()
            print(f"Transcribed: {transcript_text}")
        else:
            print("DEBUG: Empty transcript returned (silence or unrecognized speech)")
            
    except Exception as e:
        print(f"Transcription error: {e}")
    finally:
        if os.path.exists(wav_filename):
            safe_remove(wav_filename)
