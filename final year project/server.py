from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import os
import shutil
import tempfile
import asyncio
from typing import List, Optional, Dict, Any
import json

# Import existing services
from audio_utils import safe_remove
from ordering_workflow import transcribe_audio
from classifier_service import classify_order, INDIAN_MENU
from correction_service import detect_correction, process_correction
from tts_service import generate_speech
import response_service
try:
    import winsound
except ImportError:
    winsound = None
import base64

app = FastAPI(title="Voice Ordering System API")

# Simple global state for the current session's order (for demo purposes)
# In a real app, this should be per session/table
current_order_state: Dict[str, Any] = {
    "confirmed": {},
    "pending_confirmation": None,
    "last_response": ""
}

# Enable CORS for frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"message": "Voice Ordering System API is running"}

@app.get("/menu")
async def get_menu():
    return {"menu": sorted(INDIAN_MENU)}

@app.post("/order/transcribe")
async def transcribe(audio: UploadFile = File(...), noise_profile: Optional[UploadFile] = File(None)):
    """
    Uploads an audio file and returns the transcript.
    """
    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp_audio:
        shutil.copyfileobj(audio.file, tmp_audio)
        tmp_audio_path = tmp_audio.name

    noise_bytes = None
    if noise_profile:
        noise_bytes = await noise_profile.read()

    try:
        transcript, processed_audio_bytes, _ = await transcribe_audio(tmp_audio_path, noise_profile_bytes=noise_bytes)
        return {
            "transcript": transcript,
            "has_speech": bool(transcript)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        safe_remove(tmp_audio_path)

@app.post("/order/classify")
async def classify(transcript: str = Form(...)):
    """
    Classifies a transcript and returns structured order data + TTS response.
    Now handles corrections (like removal) first.
    """
    try:
        # --- Handle Corrections First ---
        if detect_correction(transcript):
            current_items = list(current_order_state["confirmed"].keys())
            corrections = process_correction(transcript, current_order_items=current_items)
            
            # Apply corrections to current_order_state
            from ordering_workflow import apply_confirmed_corrections
            current_order_state["confirmed"] = apply_confirmed_corrections(current_order_state["confirmed"], corrections)
            
            # Determine feedback text
            # If it was a removal, mention it.
            response_text = "Theek hai, I've updated your order."
            if corrections:
                c = corrections[0]
                action = c.get("action")
                dish = c.get("dish") or c.get("original_dish")
                if action == "remove":
                    response_text = f"Theek hai, {dish} remove kar diya hai."
                elif action == "cancel_all":
                    response_text = "Theek hai, pura order cancel kar diya hai."
            
            # Generate and Play TTS
            speech_b64 = generate_speech(response_text)
            if speech_b64:
                def play_async():
                    try: 
                        if winsound:
                            winsound.PlaySound(base64.b64decode(speech_b64), winsound.SND_MEMORY)
                    except: pass
                asyncio.create_task(asyncio.to_thread(play_async))
            
            return {
                "classification": {"confirmed": {}, "needs_confirmation": [], "not_in_menu": [], "is_finished": False, "intent": "correction"},
                "response_text": response_text,
                "speech": speech_b64,
                "current_order": current_order_state["confirmed"],
                "is_finished": False
            }

        # --- Regular Classification ---
        result = classify_order(transcript)
        
        # --- Conversational Logic ---
        intent = result.get("intent")
        pending = current_order_state.get("pending_confirmation")
        is_finished = result.get("is_finished", False)
        response_text = ""

        if intent == "affirmative" and pending:
            # Confirm the pending suggestion
            sug_dish = pending["suggested"]
            sug_qty = pending.get("quantity", 1)
            sug_addons = pending.get("addons", [])
            
            if sug_dish in current_order_state["confirmed"]:
                current_order_state["confirmed"][sug_dish]["quantity"] += sug_qty
                current_order_state["confirmed"][sug_dish]["addons"] = list(set(current_order_state["confirmed"][sug_dish]["addons"] + sug_addons))
            else:
                current_order_state["confirmed"][sug_dish] = {"dish": sug_dish, "quantity": sug_qty, "addons": sug_addons}
            
            current_order_state["pending_confirmation"] = None
            response_text = f"Theek hai, adding {sug_qty} {sug_dish} to your order."
            
        elif intent == "negative" and pending:
            current_order_state["pending_confirmation"] = None
            response_text = "Theek hai, I won't add that. What else would you like?"

        elif result.get("confirmed"):
            # New items confirmed directly
            for dish, data in result["confirmed"].items():
                if dish in current_order_state["confirmed"]:
                    current_order_state["confirmed"][dish]["quantity"] += data["quantity"]
                    current_order_state["confirmed"][dish]["addons"] = list(set(current_order_state["confirmed"][dish]["addons"] + data.get("addons", [])))
                else:
                    current_order_state["confirmed"][dish] = data
            
            # Generate response
            confirmed_list = [{"dish": d, "quantity": v["quantity"]} for d, v in result["confirmed"].items()]
            response_text = response_service.get_item_confirmed_text(confirmed_list)
            
            # Check for concurrent suggestions
            if result.get("needs_confirmation"):
                sug = result["needs_confirmation"][0]
                current_order_state["pending_confirmation"] = sug
                response_text += " " + response_service.get_confirm_text(sug["suggested"], sug["original"])
        
        elif result.get("needs_confirmation"):
            # Just suggestions
            sug = result["needs_confirmation"][0]
            current_order_state["pending_confirmation"] = sug
            response_text = response_service.get_confirm_text(sug["suggested"], sug["original"])
        
        elif is_finished:
            response_text = response_service.get_final_order_text(current_order_state["confirmed"])
            
        else:
            response_text = "I'm sorry, I didn't quite catch that. Could you repeat?"

        # Override with LLM response if available
        if result.get("response_text"):
            response_text = result["response_text"]
        
        # Determine language for TTS
        lang_code = result.get("language_code", "hi-IN")
        
        # Generate TTS
        speech_b64 = generate_speech(response_text, language_code=lang_code)
        
        # --- Server-side Playback (for zero-latency "Call" feel) ---
        if speech_b64:
            try:
                # Play in a separate thread so we don't block the response
                def play_async():
                    try:
                        if winsound:
                            winsound.PlaySound(base64.b64decode(speech_b64), winsound.SND_MEMORY)
                    except: pass
                
                asyncio.create_task(asyncio.to_thread(play_async))
            except Exception as e:
                print(f"Server playback error: {e}")

        return {
            "classification": result,
            "response_text": response_text,
            "speech": speech_b64,
            "current_order": current_order_state["confirmed"],
            "is_finished": is_finished
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/order/correct")
async def correct(transcript: str = Form(...)):
    """
    Processes corrections and returns the updated state + TTS response.
    """
    try:
        current_items = list(current_order_state["confirmed"].keys())
        
        if detect_correction(transcript):
            corrections = process_correction(transcript, current_order_items=current_items)
            
            response_text = response_service.get_correction_feedback_text([])
            speech_b64 = generate_speech(response_text)
            
            if speech_b64:
                def play_async():
                    try: 
                        if winsound:
                            winsound.PlaySound(base64.b64decode(speech_b64), winsound.SND_MEMORY)
                    except: pass
                asyncio.create_task(asyncio.to_thread(play_async))
            
            return {
                "correction_found": True, 
                "corrections": corrections,
                "response_text": response_text,
                "speech": speech_b64
            }
        else:
            return {"correction_found": False, "response_text": "No correction detected."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/order/reset")
async def reset_order():
    """Resets the current order session."""
    current_order_state["confirmed"] = {}
    current_order_state["pending_confirmation"] = None
    return {"message": "Order reset successfully"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
