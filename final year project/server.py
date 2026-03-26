from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import os
load_dotenv(override=True)
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
import inventory_service
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
            new_confirmed, changed = apply_confirmed_corrections(current_order_state["confirmed"].copy(), corrections)
            
            if (changed) or (corrections and corrections[0].get("action") == "cancel_all"):
                # Something was actually changed! Commit it and return.
                current_order_state["confirmed"] = new_confirmed
                
                # Determine feedback text
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
            else:
                print("DEBUG: Correction detected but no valid items affected. Falling back to regular classification.")
                # Proceed to regular classification...

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

        elif result.get("items"):
            # Load inventory for explicit server-side check
            from classifier_service import fuzzy_match_dish
            
            # Get items that need confirmation to avoid adding them prematurely
            needs_confirm_originals = [s.get("original", "").lower() for s in result.get("needs_confirmation", [])]
            suggested_dishes = [s.get("suggested", "").lower() for s in result.get("needs_confirmation", [])]

            # New items or modifications
            for item in result["items"]:
                dish_name = item["dish"]
                
                # SKIP if this item is currently being suggested for confirmation
                if dish_name.lower() in needs_confirm_originals or dish_name.lower() in suggested_dishes:
                    print(f"DEBUG: Skipping '{dish_name}' because it needs confirmation.")
                    continue

                qty = item.get("quantity", 1)
                portion = item.get("portion", "full")
                modifier = item.get("modifier", "set")
                addons = item.get("raw_addons", [])
                
                # Standardize dish name using fuzzy matching against inventory
                # Use a lower threshold (0.6) for consistent key normalization, but respect LLM's uncertainty
                matched_dish, score = fuzzy_match_dish(dish_name)
                final_dish_name = matched_dish if score > 0.7 else dish_name
                
                # Check Availability using standardized name
                is_available, stock = inventory_service.check_availability(final_dish_name, qty)
                if not is_available:
                    print(f"DEBUG: {final_dish_name} is OUT OF STOCK (Stock: {stock}). Not adding to state.")
                    # We continue to let the LLM handle the "out of stock" response if it already did
                    # but we don't add it to the confirmed state.
                    if stock <= 0:
                        continue
                
                # State update logic
                state_key = f"{portion} {final_dish_name}" if portion != "full" else final_dish_name
                
                if state_key in current_order_state["confirmed"]:
                    if modifier == "increase":
                        current_order_state["confirmed"][state_key]["quantity"] += qty
                    elif modifier == "decrease":
                        new_qty = current_order_state["confirmed"][state_key]["quantity"] - qty
                        if new_qty <= 0:
                            del current_order_state["confirmed"][state_key]
                        else:
                            current_order_state["confirmed"][state_key]["quantity"] = new_qty
                    else: # "set"
                        current_order_state["confirmed"][state_key]["quantity"] = qty
                    
                    if state_key in current_order_state["confirmed"]:
                        current_order_state["confirmed"][state_key]["addons"] = list(set(current_order_state["confirmed"][state_key]["addons"] + addons))
                else:
                    if modifier != "decrease":
                        current_order_state["confirmed"][state_key] = {"dish": state_key, "quantity": qty, "addons": addons}
            
            response_text = result.get("response_text", "")
            if not response_text:
                confirmed_list = [{"dish": d, "quantity": v["quantity"]} for d, v in current_order_state["confirmed"].items()]
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

@app.post("/order/submit")
async def submit_order():
    """
    Submits the current order, decreases inventory stock, and resets the session.
    """
    if not current_order_state["confirmed"]:
        raise HTTPException(status_code=400, detail="No items in the order to submit.")
    
    order_items = current_order_state["confirmed"]
    detailed_results = []
    
    # Process each item in the order
    for item_key, item_data in order_items.items():
        # item_key might be "half Masala Dosa" or just "Masala Dosa"
        # We need the base dish name for inventory
        dish_name = item_data.get("dish")
        qty = item_data.get("quantity", 1)
        
        # Standardize naming if it has portions (inventory usually tracks base items)
        # However, for this demo, we assume the dish_name in state matches inventory keys
        # If it doesn't, we'd need a mapping or fuzzy match here too.
        
        success = inventory_service.update_stock(dish_name, -qty)
        detailed_results.append({"dish": dish_name, "quantity": qty, "success": success})
    
    # Reset state after submission
    current_order_state["confirmed"] = {}
    current_order_state["pending_confirmation"] = None
    
    return {
        "message": "Order submitted successfully!",
        "order_summary": order_items,
        "inventory_updates": detailed_results
    }

@app.get("/inventory/status")
async def get_inventory_status():
    """Returns the current inventory status."""
    return inventory_service.load_inventory()

@app.post("/inventory/update")
async def update_inventory(dish_name: str = Form(...), change: int = Form(...)):
    """Manually updates the stock for a dish."""
    success = inventory_service.update_stock(dish_name, change)
    if success:
        return {"message": f"Updated {dish_name} stock by {change}.", "new_stock": inventory_service.get_stock(dish_name)}
    else:
        raise HTTPException(status_code=404, detail=f"Dish '{dish_name}' not found in inventory.")

@app.post("/inventory/availability")
async def toggle_availability(dish_name: str = Form(...), available: bool = Form(...)):
    """Manually toggles availability for a dish."""
    success = inventory_service.toggle_availability(dish_name, status=available)
    if success:
        return {"message": f"Toggled {dish_name} availability to {available}.", "stock": inventory_service.get_stock(dish_name)}
    else:
        raise HTTPException(status_code=404, detail=f"Dish '{dish_name}' not found in inventory.")

if __name__ == "__main__":
    import uvicorn
    # Use string import path to enable reload
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
