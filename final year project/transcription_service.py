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

def get_sarvam_client():
    global _sarvam_client
    if _sarvam_client is None:
        from sarvamai import AsyncSarvamAI
        _sarvam_client = AsyncSarvamAI(api_subscription_key=API_KEY)
    return _sarvam_client

async def close_client():
    """Cleanly close the async HTTP client to prevent event loop warnings."""
    global _sarvam_client
    if _sarvam_client and hasattr(_sarvam_client, '_client') and _sarvam_client._client:
        await _sarvam_client._client.aclose()

async def transcribe_chunk(wav_filename, orders_dict, current_table, processed_audio_list=None):
    directory = os.path.dirname(wav_filename)
    basename = os.path.basename(wav_filename)
    trimmed_file = os.path.join(directory, f"trimmed_{basename}")
    
    try:
        has_voice = trim_silence(wav_filename, trimmed_file)
        if os.path.exists(wav_filename):
            safe_remove(wav_filename)
            
        if not has_voice:
            print("Skipping silent chunk")
            return

        # If the caller wants the processed audio, read it before it might be deleted
        if processed_audio_list is not None and os.path.exists(trimmed_file):
            with open(trimmed_file, "rb") as af:
                processed_audio_list.append(af.read())

        client = get_sarvam_client()
        
        # Simple retry logic for transient network issues
        max_retries = 3
        retry_delay = 1
        transcript_text = ""
        
        for attempt in range(max_retries):
            try:
                with open(trimmed_file, "rb") as f:
                    response = await client.speech_to_text.transcribe(
                        model="saaras:v3",
                        file=f,
                        language_code="en-IN"
                    )
                transcript_text = getattr(response, "transcript", "")
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
            
    except Exception as e:
        print(f"Transcription error: {e}")
    finally:
        if os.path.exists(trimmed_file):
            safe_remove(trimmed_file)
