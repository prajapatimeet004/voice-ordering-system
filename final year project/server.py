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
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import base64
from audio_utils import safe_remove
from ordering_workflow import transcribe_audio
from classifier_service import classify_order, INDIAN_MENU
from correction_service import detect_correction, process_correction
from addon_extractor import merge_structured_addons
from tts_service import generate_speech
import response_service
import inventory_service
try:
    import winsound
except ImportError:
    winsound = None
 
 
# Keywords that indicate a clear intent to add another unit of a dish
ADDITION_KEYWORDS = [
    "more", "another", "plus", "extra plate", "one more", "ek bija", "ek biju", "phir se", "aur ek", "beju", "bij"
]


# Use a menu dictionary for prices and categories
MENU_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "menu.json")
def load_menu():
    if os.path.exists(MENU_FILE):
        with open(MENU_FILE, "r") as f:
            return json.load(f)
    return {}

MENU_DATA = load_menu()

app = FastAPI(title="Voice Ordering System API")

# Multi-table state management
from collections import defaultdict

def create_default_table_state():
    return {
        "confirmed": {},
        "pending_confirmation": None,
        "last_response": "",
        "stats": {
            "active_orders": 0,
            "revenue": 0.0,
            "tables_booked": 1
        }
    }

# Dictionary to store state for each table_id
tables_state = defaultdict(create_default_table_state)

def ensure_table_prefix(table_id: str) -> str:
    """Ensures table_id is in the format 'table_X'."""
    if not table_id or table_id == "default":
        return "table_default"
    if not table_id.startswith("table_"):
        return f"table_{table_id}"
    return table_id

def get_table_state(table_id: str = "default"):
    """Helper to get state for a specific table."""
    tid = ensure_table_prefix(table_id)
    return tables_state[tid]

# Keep current_order_state for backward compatibility but point it to a default
# This will be replaced by per-request lookups
current_order_state = tables_state["table_default"]

# Enable CORS for frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve the Dashboard UI
@app.get("/dashboard")
@app.get("/admin")
async def get_dashboard():
    return FileResponse(os.path.join(os.path.dirname(__file__), "admin.html"))

# Mount the current directory for static assets (CSS, JS)
app.mount("/static", StaticFiles(directory=os.path.dirname(__file__)), name="static")

@app.get("/")
async def root():
    return FileResponse(os.path.join(os.path.dirname(__file__), "index.html"))

@app.get("/menu")
async def get_menu():
    return {"menu": sorted(INDIAN_MENU)}

@app.get("/menu/details")
async def get_menu_details():
    """Returns the full menu details (prices, categories)."""
    return MENU_DATA

@app.get("/dashboard/stats")
async def get_dashboard_stats(table_id: Optional[str] = None):
    """Calculates and returns dashboard stats. If table_id is provided, returns for that table, else aggregate."""
    total_revenue = 0.0
    total_active_items = 0
    tables_active = 0
    
    if table_id:
        # Single table stats
        state = get_table_state(table_id)
        for dish, details in state["confirmed"].items():
            qty = details.get("quantity", 0)
            item_info = MENU_DATA.get(dish, {})
            price = item_info.get("price", 0)
            total_revenue += price * qty
            total_active_items += 1
        tables_active = 1 if total_active_items > 0 else 0
    else:
        # Aggregate stats across all tables
        active_table_ids = [tid for tid, s in tables_state.items() if s["confirmed"]]
        tables_active = len(active_table_ids)
        for tid in active_table_ids:
            state = tables_state[tid]
            for dish, details in state["confirmed"].items():
                qty = details.get("quantity", 0)
                item_info = MENU_DATA.get(dish, {})
                price = item_info.get("price", 0)
                total_revenue += price * qty
                total_active_items += 1

    print(f"DEBUG: [STATS] tables_active: {tables_active}, total_items: {total_active_items}, revenue: {total_revenue}")
    
    return {
        "active_orders": total_active_items,
        "revenue": round(total_revenue, 2),
        "tables_booked": tables_active or 1,
        "avg_order_value": round(total_revenue / total_active_items, 2) if total_active_items > 0 else 0,
        "total_tables_active": tables_active
    }


@app.get("/order/state")
async def get_order_state(table_id: str = "default"):
    """Returns the current order state for a specific table."""
    return get_table_state(table_id)

@app.get("/order/all_states")
async def get_all_order_states():
    """Returns the order states for all tables that have activity (confirmed or pending)."""
    # Convert defaultdict to regular dict for clean JSON serialization
    serialized_states = {}
    for tid, state in tables_state.items():
        has_confirmed = bool(state.get("confirmed"))
        has_pending = bool(state.get("pending_confirmation"))
        
        if has_confirmed or has_pending:
            serialized_states[tid] = state
            
    print(f"DEBUG: [ALL_STATES] Returning {len(serialized_states)} active table states.")
    return serialized_states


@app.get("/inventory/status")
async def get_inventory_status():
    """Returns the current inventory status."""
    return inventory_service.get_full_inventory()

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
async def classify(transcript: str = Form(...), table_id: str = Form("default")):
    """
    Classifies a transcript and returns structured order data + TTS response.
    Now handles corrections (like removal) first.
    """
    current_order_state = get_table_state(table_id)
    try:
        # --- Unified Classification ---
        # Prepare order summary for LLM context
        confirmed_list = [f"{v['quantity']} {d}" for d, v in current_order_state["confirmed"].items()]
        order_summary = ", ".join(confirmed_list) if confirmed_list else "Order is empty"

        # Call the unified classifier
        result = await classify_order(transcript, order_summary)

        
        # --- Conversational Logic ---
        intent = result.get("intent")
        pending = current_order_state.get("pending_confirmation")
        is_finished = result.get("is_finished", False)
        response_text = ""

        confirmation_handled = False
        conf_response = ""
        
        if intent == "affirmative" and pending:
            # Confirm the pending suggestion
            if pending.get("is_correction"):
                # Re-apply the correction now that it's confirmed
                from ordering_workflow import apply_confirmed_corrections
                confirmed_corr = [{
                    "action": pending.get("action"),
                    "dish": pending.get("suggested"),
                    "quantity": pending.get("quantity", 1),
                    "addons": pending.get("addons", []),
                    "is_relative": pending.get("is_relative", False)
                }]
                new_confirmed, changed, unavailable_items = apply_confirmed_corrections(current_order_state["confirmed"].copy(), confirmed_corr)
                current_order_state["confirmed"] = new_confirmed
                conf_response = response_service.get_correction_feedback_text(confirmed_corr)
                if unavailable_items:
                    conf_response += " " + response_service.get_availability_feedback_text(unavailable_items)
            else:
                sug_dish = pending["suggested"]
                sug_qty = pending.get("quantity", 1)
                sug_addons = pending.get("addons", [])
                
                if sug_dish in current_order_state["confirmed"]:
                    current_order_state["confirmed"][sug_dish]["quantity"] += sug_qty
                    current_order_state["confirmed"][sug_dish]["addons"] = merge_structured_addons(
                        current_order_state["confirmed"][sug_dish]["addons"], 
                        {a: "add" for a in sug_addons} if isinstance(sug_addons, list) else sug_addons
                    )
                else:
                    current_order_state["confirmed"][sug_dish] = {
                        "dish": sug_dish, 
                        "quantity": sug_qty, 
                        "addons": sug_addons if isinstance(sug_addons, list) else merge_structured_addons([], sug_addons)
                    }
                conf_response = f"Theek hai, adding {sug_qty} {sug_dish} to your order."
            
            current_order_state["pending_confirmation"] = None
            confirmation_handled = True
            
        elif intent == "negative" and pending:
            current_order_state["pending_confirmation"] = None
            conf_response = "Theek hai, I won't add that."
            confirmation_handled = True

        # --- Item & Modification Processing ---
        items_msg = result.get("response_text", "")
        
        # Build a set of dish names that are already targeted by modifications.
        # This prevents adding a duplicate item when the user only wants to modify
        # an existing dish (e.g. "make butter chicken more spicy" should NOT add
        # another Butter Chicken, it should only update the addon).
        from classifier_service import fuzzy_match_dish as _fmatch
        modification_targets = set()
        for mod in result.get("modifications", []):
            t = mod.get("target_item", "")
            if t:
                matched_t, _, _ = _fmatch(t)
                modification_targets.add(matched_t)
                modification_targets.add(t)  # also keep raw in case fuzzy misses

        # 1. Process New Items (Only auto-confirm high-confidence matches)
        if result.get("items"):
            needs_conf_list = result.get("needs_confirmation", [])
            print(f"DEBUG: Processing {len(result['items'])} items for table '{table_id}'")
            
            for item in result["items"]:
                dish_name = item["dish"]
                qty = item.get("quantity", 1)
                addons = item.get("addons", [])
                modified_addons = item.get("modified_addons", {})

                # SKIP if this dish is already being handled by a modification entry
                # (e.g. "make butter chicken more spicy" – no new item should be added)
                if dish_name in modification_targets:
                    print(f"DEBUG: Skipping auto-add for '{dish_name}' (already a modification target)")
                    continue

                # SKIP auto-adding if this item is in the "needs_confirmation" list
                if any(nc["suggested"] == dish_name for nc in needs_conf_list):
                    print(f"DEBUG: Skipping auto-add for '{dish_name}' (needs confirmation)")
                    continue

                # KEY FIX: When intent is "modify_order" AND the dish already exists
                # in the confirmed order, treat this as an addon update — NOT a new item.
                # This handles cases like "Masala dosa thoda teekha rakhna" where the LLM
                # puts the dish in items[] without a corresponding modifications[] entry.
                dish_already_exists = dish_name in current_order_state["confirmed"]
                has_addition_keywords = any(kw in transcript.lower() for kw in ADDITION_KEYWORDS)

                if dish_already_exists and not has_addition_keywords:
                    # Treat as update even if LLM said it's a new item (Secondary Guard)
                    existing = current_order_state["confirmed"][dish_name]
                    if modified_addons:
                        # Use structured addon merging if LLM gave us a dict
                        current_addons = existing.get("addons", [])
                        existing["addons"] = merge_structured_addons(current_addons, modified_addons)
                        print(f"DEBUG: [GUARD] Merged addons for existing '{dish_name}': {existing['addons']}")
                    elif addons:
                        # Fallback: simple list merge
                        existing["addons"] = list(set(existing.get("addons", []) + addons))
                        print(f"DEBUG: [GUARD] Merged addons (list) for existing '{dish_name}': {existing['addons']}")
                    else:
                        print(f"DEBUG: [GUARD] '{dish_name}' already in order, no new addition words found. Skipping.")
                    continue  # Do NOT add as new item

                # Check Availability (only for genuinely new items)
                is_available, _ = inventory_service.check_availability(dish_name, qty)
                if not is_available:
                    print(f"DEBUG: {dish_name} is OUT OF STOCK. Not adding.")
                    continue
                
                print(f"DEBUG: Adding '{dish_name}' (qty: {qty}) to confirmed order for table '{table_id}'")
                if dish_name in current_order_state["confirmed"]:
                    current_order_state["confirmed"][dish_name]["quantity"] += qty
                    # Merge addons
                    current_order_state["confirmed"][dish_name]["addons"] = list(set(current_order_state["confirmed"][dish_name]["addons"] + addons))
                else:
                    current_order_state["confirmed"][dish_name] = {"dish": dish_name, "quantity": qty, "addons": addons}
            
            # Store the first item that needs confirmation in the session state
            if needs_conf_list:
                current_order_state["pending_confirmation"] = needs_conf_list[0]
                print(f"DEBUG: Set pending_confirmation for table '{table_id}': {needs_conf_list[0]['suggested']}")



        # 2. Process Modifications
        if result.get("modifications"):
            from classifier_service import fuzzy_match_dish
            for mod in result["modifications"]:
                target = mod.get("target_item")
                action = mod.get("action")
                changes = mod.get("changes", {})
                
                # Find the target item in current order
                matched_target, score, _ = fuzzy_match_dish(target)
                if score < 0.65 or matched_target not in current_order_state["confirmed"]:
                    # Try exact match if fuzzy fails
                    if target in current_order_state["confirmed"]:
                        matched_target = target
                    else:
                        print(f"DEBUG: Modification target '{target}' not found in order.")
                        feedback = f"Maaf karjo, tamara order ma {target} nathi. Tamare biju kai change karvu che? (Sorry, {target} is not in your order. What would you like to change?)"
                        if feedback not in response_text:
                            response_text += " " + feedback
                        continue

                if action == "remove":
                    del current_order_state["confirmed"][matched_target]
                    print(f"DEBUG: Removed '{matched_target}'")
                
                elif action == "replace":
                    new_item_name = changes.get("new_item")
                    if new_item_name:
                        matched_new, score, _ = fuzzy_match_dish(new_item_name)
                        if score > 0.3:
                            qty = current_order_state["confirmed"][matched_target]["quantity"]
                            del current_order_state["confirmed"][matched_target]
                            current_order_state["confirmed"][matched_new] = {
                                "dish": matched_new, 
                                "quantity": qty, 
                                "addons": [f"{k}: {v}" for k, v in changes.items() if k != "new_item"]
                            }
                            print(f"DEBUG: Replaced '{matched_target}' with '{matched_new}'")

                elif action in ["update", "add"]:
                    # Update addons or quantity
                    existing = current_order_state["confirmed"][matched_target]
                    
                    # Update quantity if present
                    if "quantity" in changes:
                        existing["quantity"] = int(changes.pop("quantity"))
                    
                    # Use merge_structured_addons for all other changes (which are assumed to be addons)
                    if changes:
                        current_addons = existing.get("addons", [])
                        updated_addons = merge_structured_addons(current_addons, changes)
                        existing["addons"] = updated_addons
                        print(f"DEBUG: Updated '{matched_target}' addons: {updated_addons} (from changes: {changes})")
        
        # fallback is_finished
        if result.get("is_finished"):
            is_finished = True


        # --- Final Response Construction ---
        if result.get("response_text") and not (intent in ["affirmative", "negative"] and pending):
            # If LLM gave a full response and it's not a simple confirmation, trust it
            response_text = result["response_text"]
        else:
            # Combine confirmation response and items response
            response_parts = []
            if conf_response: response_parts.append(conf_response)
            if items_msg: response_parts.append(items_msg)
            
            if not response_parts:
                response_text = "I'm sorry, I didn't quite catch that."
            else:
                response_text = " ".join(response_parts)
                
        # Ensure confirmation prompt is appended if added via LLM needs_confirmation
        if result.get("needs_confirmation") and response_service.get_confirm_text(result["needs_confirmation"][0]["suggested"], result["needs_confirmation"][0]["original"]) not in response_text:
            sug = result["needs_confirmation"][0]
            response_text += " " + response_service.get_confirm_text(sug["suggested"], sug["original"])
        
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
async def correct(transcript: str = Form(...), table_id: str = Form("default")):
    """
    Processes corrections and returns the updated state + TTS response.
    """
    current_order_state = get_table_state(table_id)
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
async def reset_order(table_id: str = "default"):
    """Resets the current order session for a specific table."""
    if table_id in tables_state:
        del tables_state[table_id]
    return {"message": f"Order for table {table_id} reset successfully"}

@app.post("/order/submit")
async def submit_order(table_id: str = "default"):
    """
    Submits the current order, decreases inventory stock, and resets the session.
    """
    current_order_state = get_table_state(table_id)
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
    import webbrowser
    import threading
    import time

    def open_browser():
        time.sleep(2)  # Wait for server to start
        webbrowser.open("http://127.0.0.1:8000/")
        webbrowser.open("http://127.0.0.1:8000/dashboard")

    # Start browser thread
    threading.Thread(target=open_browser, daemon=True).start()

    # Use string import path to enable reload
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True, reload_dirs=["."])
