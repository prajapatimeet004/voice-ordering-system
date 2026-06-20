import logging
logging.basicConfig(filename='ws_debug.log', level=logging.DEBUG)
import json
import os
import shutil
import tempfile
import asyncio
import base64
from contextlib import asynccontextmanager
from typing import List, Optional, Dict, Any
from collections import defaultdict

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response, StreamingResponse
from dotenv import load_dotenv

load_dotenv(override=True)

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

# ── DB + Redis optional imports ───────────────────────────────────────
_HAS_DB = bool(os.getenv("DATABASE_URL"))
_HAS_REDIS = bool(os.getenv("REDIS_URL"))

if _HAS_DB:
    from models.base import init_db, close_db
    from repositories.menu_repo import seed_menu_from_file, get_all_menu_items as db_get_menu
    from repositories.inventory_repo import (
        seed_inventory_from_file,
        check_availability as db_check_avail,
        update_stock as db_update_stock,
        get_full_inventory as db_get_inventory,
    )
else:
    print("INFO: DATABASE_URL not set — using file-based menu + inventory.")

if _HAS_REDIS:
    from services.redis_pubsub import (
        get_redis, close_redis, publish_update,
        get_order_state as redis_get_state,
        save_order_state as redis_save_state,
        delete_order_state as redis_delete_state,
        get_all_order_states as redis_get_all_states,
        subscribe_updates,
    )
else:
    print("INFO: REDIS_URL not set — using in-memory state + SSE queues.")

# ── Keywords ──────────────────────────────────────────────────────────
ADDITION_KEYWORDS = [
    "more", "another", "plus", "extra plate", "one more", "ek bija", "ek biju",
    "phir se", "aur ek", "beju", "bij"
]

# ── Menu ──────────────────────────────────────────────────────────────
MENU_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "menu.json")


def load_menu():
    if os.path.exists(MENU_FILE):
        with open(MENU_FILE, "r") as f:
            return json.load(f)
    return {}


MENU_DATA = load_menu()

# ── In-memory state (fallback / cache) ────────────────────────────────


def create_default_table_state():
    return {
        "confirmed": {},
        "pending_confirmation": None,
        "pending_upsell": None,
        "last_response": "",
        "transcript_history": [],
        "stats": {
            "active_orders": 0,
            "revenue": 0.0,
            "tables_booked": 1
        }
    }


tables_state: Dict[str, dict] = defaultdict(create_default_table_state)


# ── Optional Redis sync ───────────────────────────────────────────────
async def _maybe_sync_to_redis(table_id: str):
    """Write-through: save in-memory state to Redis after every mutation."""
    if not _HAS_REDIS:
        return
    try:
        tid = ensure_table_prefix(table_id)
        state = tables_state.get(tid)
        if state is not None:
            await redis_save_state(tid, dict(state))  # copy to avoid mutation
    except Exception as e:
        logging.warning(f"Redis sync failed for {table_id}: {e}")


async def _maybe_delete_from_redis(table_id: str):
    if not _HAS_REDIS:
        return
    try:
        await redis_delete_state(ensure_table_prefix(table_id))
    except Exception as e:
        logging.warning(f"Redis delete failed for {table_id}: {e}")


def ensure_table_prefix(table_id: str) -> str:
    if not table_id or table_id == "default":
        return "table_default"
    if not table_id.startswith("table_"):
        return f"table_{table_id}"
    return table_id


def get_table_state(table_id: str = "default") -> dict:
    tid = ensure_table_prefix(table_id)
    return tables_state[tid]


current_order_state = tables_state["table_default"]


def get_upsell_item(order_items):
    from classifier_service import MENU_CATEGORIES
    categories = set()
    for item in order_items.keys():
        for cat, dishes in MENU_CATEGORIES.items():
            if item in dishes:
                categories.add(cat)

    suggestions = []
    if "South Indian" in categories:
        suggestions = ["Mango Lassi", "Sweet Lassi", "Gulab Jamun"]
    elif "Punjabi" in categories:
        suggestions = ["Sweet Lassi", "Masala Chaas", "Gulab Jamun"]
    elif "Main Course" in categories:
        suggestions = ["Gulab Jamun", "Mango Lassi", "Rabdi"]
    elif "Pizza" in categories:
        suggestions = ["Oreo Shake", "Cold Coffee", "Brownie with Ice Cream"]
    elif "Rice" in categories:
        suggestions = ["Gulab Jamun", "Rabdi", "Sweet Lassi"]
    elif "Street Food" in categories:
        suggestions = ["Masala Chaas", "Sweet Lassi", "Gulab Jamun"]
    elif "Snacks" in categories:
        suggestions = ["Mango Lassi", "Cold Coffee", "Oreo Shake"]
    elif "Desserts" in categories:
        suggestions = ["Filter Coffee", "Masala Chai", "Green Tea"]
    elif "Drinks" in categories:
        suggestions = ["Paneer Tikka Sandwich", "Veg Momos", "Paneer Momos"]
    else:
        suggestions = ["Gulab Jamun", "Mango Lassi", "Sweet Lassi"]

    for sug in suggestions:
        if sug not in order_items:
            is_avail, _ = inventory_service.check_availability(sug, 1)
            if is_avail:
                return sug

    for item in ["Mango Lassi", "Gulab Jamun", "Sweet Lassi", "Veg Momos", "Paneer Tikka Sandwich"]:
        if item not in order_items:
            is_avail, _ = inventory_service.check_availability(item, 1)
            if is_avail:
                return item
    return None


def finalize_and_submit_order(table_state):
    for dish_name, item_data in list(table_state["confirmed"].items()):
        qty = item_data.get("quantity", 1)
        inventory_service.update_stock(dish_name, -qty)
    table_state["confirmed"] = {}
    table_state["pending_confirmation"] = None
    table_state["pending_upsell"] = None


# ── Legacy in-memory DashboardManager ────────────────────────────────
class DashboardManager:
    def __init__(self):
        self.queues = []

    def add_queue(self):
        q = asyncio.Queue()
        self.queues.append(q)
        return q

    def remove_queue(self, q):
        if q in self.queues:
            self.queues.remove(q)

    async def broadcast(self):
        for q in self.queues:
            await q.put(True)


dashboard_manager = DashboardManager()


async def _broadcast_update():
    """Notify all SSE listeners (legacy in-memory + Redis pub/sub)."""
    await dashboard_manager.broadcast()
    if _HAS_REDIS:
        try:
            await publish_update()
        except Exception as e:
            logging.warning(f"Redis pub/sub broadcast failed: {e}")


# ── Lifespan ──────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(application: FastAPI):
    print("INFO: Starting up...")

    # Init DB and seed from JSON files
    if _HAS_DB:
        await init_db()
        from models.base import get_session
        try:
            async for session in get_session():
                await seed_menu_from_file(session)
                await seed_inventory_from_file(session)
                break
        except Exception as e:
            logging.warning(f"DB seeding failed (non-fatal): {e}")

    # Init Redis connection
    if _HAS_REDIS:
        try:
            r = await get_redis()
            await r.ping()
            print("INFO: Redis connected.")
        except Exception as e:
            logging.warning(f"Redis connection failed: {e}")

    yield

    # Shutdown
    print("INFO: Shutting down...")
    if _HAS_DB:
        await close_db()
    if _HAS_REDIS:
        await close_redis()


# ── App ───────────────────────────────────────────────────────────────
app = FastAPI(title="Voice Ordering System API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Health Check ──────────────────────────────────────────────────────
@app.get("/health")
async def health():
    status = {"status": "healthy", "database": _HAS_DB, "redis": _HAS_REDIS}
    if _HAS_REDIS:
        try:
            r = await get_redis()
            await r.ping()
            status["redis_connected"] = True
        except Exception:
            status["redis_connected"] = False
    return status


# ── Static Routes ─────────────────────────────────────────────────────
@app.get("/dashboard")
@app.get("/admin")
async def get_dashboard():
    return FileResponse(os.path.join(os.path.dirname(__file__), "admin.html"))


app.mount("/static", StaticFiles(directory=os.path.dirname(__file__)), name="static")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse("favicon.ico") if os.path.exists("favicon.ico") else Response(status_code=204)


@app.get("/")
async def root():
    return FileResponse(os.path.join(os.path.dirname(__file__), "index.html"))


@app.get("/menu")
async def get_menu():
    return {"menu": sorted(INDIAN_MENU)}


@app.get("/menu/details")
async def get_menu_details():
    return MENU_DATA


# ── Dashboard Stats ───────────────────────────────────────────────────
@app.get("/dashboard/stats")
async def get_dashboard_stats(table_id: Optional[str] = None):
    total_revenue = 0.0
    total_active_items = 0
    tables_active = 0

    if table_id:
        state = get_table_state(table_id)
        for dish, details in state["confirmed"].items():
            qty = details.get("quantity", 0)
            item_info = MENU_DATA.get(dish, {})
            price = item_info.get("price", 0)
            total_revenue += price * qty
            total_active_items += 1
        tables_active = 1 if total_active_items > 0 else 0
    else:
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


# ── SSE Dashboard Stream ──────────────────────────────────────────────
@app.get("/dashboard/stream")
async def dashboard_stream():
    async def event_generator():
        if _HAS_REDIS:
            # Use Redis pub/sub for multi-worker support
            try:
                yield "data: connected\n\n"
                async for msg in subscribe_updates():
                    yield f"data: {msg}\n\n"
            except Exception as e:
                logging.warning(f"Redis SSE error, falling back to in-memory: {e}")

        # Fallback to in-memory queues
        q = dashboard_manager.add_queue()
        try:
            yield "data: connected\n\n"
            while True:
                await q.get()
                yield "data: update\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            dashboard_manager.remove_queue(q)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ── Order Routes ──────────────────────────────────────────────────────
@app.get("/order/state")
async def get_order_state(table_id: str = "default"):
    return get_table_state(table_id)


@app.get("/order/all_states")
async def get_all_order_states():
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
    return inventory_service.get_full_inventory()


@app.post("/order/transcribe")
async def transcribe(audio: UploadFile = File(...), noise_profile: Optional[UploadFile] = File(None)):
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
async def process_order_logic(transcript: str, table_id: str):
    current_order_state = get_table_state(table_id)
    unavailable_items = []
    try:
        # Store transcript in history
        current_order_state["transcript_history"].append(transcript)
        if len(current_order_state["transcript_history"]) > 10:
            current_order_state["transcript_history"] = current_order_state["transcript_history"][-10:]

        confirmed_list = [f"{v['quantity']} {d}" for d, v in current_order_state["confirmed"].items()]
        order_summary = ", ".join(confirmed_list) if confirmed_list else "Order is empty"

        result = await classify_order(
            transcript,
            order_summary,
            history=current_order_state["transcript_history"]
        )

        intent = result.get("intent")

        clean_tx = transcript.lower().strip().replace(".", "").replace("!", "").replace(",", "")
        affirmative_words = [
            "yes", "yeah", "yep", "yup", "yess", "yesss", "sure", "ok", "okay", "okey",
            "alright", "right", "fine", "absolutely", "definitely", "of course", "go ahead",
            "yes please", "yes add that", "add it", "add that", "add karo", "add kar do",
            "ha", "haa", "haan", "hanji", "han ji", "ji", "ji ha", "ji haan",
            "theek hai", "thek hai", "theek he", "thik hai", "thik he",
            "kar do", "karo", "kar dena", "kardo", "kar dijiye", "kariye",
            "kari do", "kari dena", "kari dijiye",
            "de do", "dedo", "de dena", "de dijiye",
            "laga do", "lagado", "laga dena", "lagao",
            "rakh do", "rakhdo", "rakh dena", "rakho",
            "daal do", "daaldo", "daal dena", "daalo",
            "bilkul", "zaroor", "zarur", "pakka",
            "sahi hai", "sahi he", "accha", "acha",
            "ban jaye", "ban jayega", "chalo",
            "chalshe", "chalse", "chale", "chaalse", "chaalshe",
            "thik che", "thik chhe", "theek che", "theek chhe", "barabar che",
            "haji", "ha ji", "haa ji",
            "karo", "kari do", "kari nakh", "kari nakho", "kari de",
            "mukjo", "muki do", "muki de", "nakho", "nakhi do", "nakhi de",
            "rakhjo", "rakhje", "rakhi do", "rakhi de",
            "bhari do", "bhari de", "bharjo", "bharje",
            "haji add karo", "ha add karo", "ha kari do", "ha kar do",
            "ho", "hoy", "avse", "aa avse", "banne",
        ]
        if clean_tx in affirmative_words:
            intent = "affirmative"
        elif any(clean_tx.startswith(w + " ") or clean_tx.endswith(" " + w) for w in [
            "yes", "yeah", "ha", "haa", "haan", "hanji", "ji", "ok", "okay", "sure",
            "theek hai", "thek hai", "thik hai", "chalshe", "chalse", "thik che",
            "kari do", "kar do", "karo", "haji", "bilkul", "zaroor", "pakka", "accha"
        ]):
            intent = "affirmative"

        negative_words = ["no", "nope", "not that", "nahi", "na", "nathi", "nathi joitu", "nako", "nai", "no thanks", "no thank you", "nathi joiye", "nathi joitu", "na padse", "na padis"]
        finishing_words = [
            "done", "finished", "that's it", "bus", "bas", "bas itna hi", "itna hi dena",
            "itlu j", "pachi nai", "bas avu j", "order confirm", "my order is done",
            "order complete", "complete order", "aur kuch nahi chahiye", "kuch nahi chahiye",
            "nahi chahiye", "bas aur kuch nahi", "bas nahi chahiye", "biju kaik nahi",
            "biju nathi joitu", "biju kaik nathi joitu"
        ]

        if intent != "affirmative" and clean_tx in negative_words:
            intent = "negative"
        elif intent != "affirmative" and clean_tx in finishing_words:
            intent = "finishing"

        greeting_words = [
            "hello", "hi", "hey", "namaste", "namaskar", "halo", "helo",
            "good morning", "good afternoon", "good evening", "good night",
            "kem cho", "kem chho", "kaise ho", "kya haal hai", "suprabhat",
            "shubh prabhat", "shubh sandhya", "aavjo", "jai shree krishna"
        ]
        if any(clean_tx == g or clean_tx.startswith(g + " ") for g in greeting_words) or intent == "greeting":
            intent = "greeting"

        pending = current_order_state.get("pending_confirmation")
        pending_upsell = current_order_state.get("pending_upsell")
        is_finished = result.get("is_finished", False)
        lang_code = result.get("language_code", "hi-IN")
        response_text = ""

        if intent == "greeting":
            lang_code = result.get("language_code", "hi-IN")
            time_greet = response_service.get_time_based_greeting(lang_code=lang_code)
            if lang_code == "gu-IN":
                response_text = f"{time_greet} Hu Bhaiya chhu — Pooja Restaurant ma aapnu swagat che! Kaho, shu order karvu che?"
            elif lang_code == "hi-IN":
                response_text = f"{time_greet} Main Bhaiya hoon — Pooja Restaurant mein aapka swagat hai! Batao, kya order karna hai?"
            else:
                response_text = f"{time_greet} I'm Bhaiya, your waiter at Pooja Restaurant! What would you like to order today?"
            result["response_text"] = response_text
            result["items"] = []
            result["modifications"] = []
            intent = "none"

        upsell_handled = False
        if pending_upsell:
            if intent == "affirmative":
                is_available, stock = inventory_service.check_availability(pending_upsell, 1)
                if is_available:
                    current_order_state["confirmed"][pending_upsell] = {
                        "dish": pending_upsell,
                        "quantity": 1,
                        "addons": []
                    }
                    if lang_code == "gu-IN":
                        response_text = f"Saras! Ek {pending_upsell} add kari didhu che. Pooja Restaurant ma order karva badal aabhar!"
                    else:
                        response_text = f"Theek hai, ek {pending_upsell} add kar diya hai. Pooja Restaurant me order karne ke liye dhanyawad!"
                else:
                    if lang_code == "gu-IN":
                        response_text = f"Saras! Pan {pending_upsell} available nathi. Pooja Restaurant ma order karva badal aabhar!"
                    else:
                        response_text = f"Theek hai, par {pending_upsell} abhi available nahi hai. Pooja Restaurant me order karne ke liye dhanyawad!"
                finalize_and_submit_order(current_order_state)
                is_finished = True
                upsell_handled = True
            elif intent == "negative":
                if lang_code == "gu-IN":
                    response_text = f"Theek che, order finalize kari didhu che. Pooja Restaurant ma order karva badal aabhar!"
                else:
                    response_text = f"Theek hai, order finalize kar diya hai. Pooja Restaurant me order karne ke liye dhanyawad!"
                finalize_and_submit_order(current_order_state)
                is_finished = True
                upsell_handled = True
            else:
                current_order_state["pending_upsell"] = None

        if intent == "finishing" and not upsell_handled:
            confirmed_items = current_order_state["confirmed"]
            if not confirmed_items:
                if lang_code == "gu-IN":
                    response_text = "Bhaiya, tame haji sudhi kai order nathi karyu. Pehla kaik order kari lyo."
                else:
                    response_text = "Bhaiya, aapne abhi tak kuch order nahi kiya hai. Pehle kuch order kar lijiye."
            else:
                summary_parts = []
                for dish, data in confirmed_items.items():
                    qty = data.get("quantity", 1)
                    summary_parts.append(f"{qty} {dish}")
                summary_str = " aur ".join(summary_parts) if lang_code != "gu-IN" else " ane ".join(summary_parts)

                upsell_dish = get_upsell_item(confirmed_items)
                if upsell_dish:
                    current_order_state["pending_upsell"] = upsell_dish
                    if lang_code == "gu-IN":
                        response_text = f"Aabhar! Tame order karyu che: {summary_str}. Shu hu tamari sathe ek {upsell_dish} add kari dav?"
                    else:
                        response_text = f"Thank you! Aapne order kiya hai: {summary_str}. Kya main iske sath ek {upsell_dish} add karu?"
                else:
                    if lang_code == "gu-IN":
                        response_text = f"Aabhar! Tame order karyu che: {summary_str}. Pooja Restaurant ma order karva badal aabhar!"
                    else:
                        response_text = f"Thank you! Aapne order kiya hai: {summary_str}. Pooja Restaurant me order karne ke liye dhanyawad!"
                    finalize_and_submit_order(current_order_state)
                    is_finished = True

            result["response_text"] = response_text
            result["items"] = []
            result["modifications"] = []
            intent = "none"

        if upsell_handled:
            result["response_text"] = response_text
            result["items"] = []
            result["modifications"] = []
            intent = "none"

        confirmation_handled = False
        conf_response = ""

        if intent == "affirmative" and pending:
            if pending.get("is_correction"):
                from ordering_workflow import apply_confirmed_corrections
                confirmed_corr = [{
                    "action": pending.get("action"),
                    "dish": pending.get("suggested"),
                    "quantity": pending.get("quantity", 1),
                    "addons": pending.get("addons", []),
                    "is_relative": pending.get("is_relative", False)
                }]
                new_confirmed, changed, unavailable_items = apply_confirmed_corrections(
                    current_order_state["confirmed"].copy(), confirmed_corr
                )
                current_order_state["confirmed"] = new_confirmed
                conf_response = response_service.get_correction_feedback_text(confirmed_corr)
                if unavailable_items:
                    conf_response += " " + response_service.get_availability_feedback_text(unavailable_items)
            else:
                sug_dish = pending["suggested"]
                sug_qty = pending.get("quantity", 1)
                sug_addons = pending.get("addons", [])

                current_qty = current_order_state["confirmed"][sug_dish]["quantity"] if sug_dish in current_order_state["confirmed"] else 0
                target_qty = current_qty + sug_qty
                is_available, stock = inventory_service.check_availability(sug_dish, target_qty)

                if is_available:
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
                else:
                    conf_response = response_service.get_availability_feedback_text([sug_dish])
                    unavailable_items.append(sug_dish)

            current_order_state["pending_confirmation"] = None
            confirmation_handled = True

        elif intent == "negative" and pending:
            current_order_state["pending_confirmation"] = None
            conf_response = "Theek hai, I won't add that."
            confirmation_handled = True

        elif pending and intent not in ["affirmative", "negative"]:
            current_order_state["pending_confirmation"] = None
            print("DEBUG: User ignored confirmation. Discarding pending item.")

        items_msg = result.get("response_text", "")

        from classifier_service import fuzzy_match_dish as _fmatch
        modification_targets = set()
        for mod in result.get("modifications", []):
            t = mod.get("target_item", "")
            if t:
                matched_t, _, _ = _fmatch(t)
                modification_targets.add(matched_t)
                modification_targets.add(t)

        if result.get("items"):
            needs_conf_list = result.get("needs_confirmation", [])
            print(f"DEBUG: Processing {len(result['items'])} items for table '{table_id}'")

            for item in result["items"]:
                dish_name = item["dish"]
                qty = item.get("quantity", 1)
                addons = item.get("addons", [])
                modified_addons = item.get("modified_addons", {})

                if dish_name in modification_targets:
                    print(f"DEBUG: Skipping auto-add for '{dish_name}' (already a modification target)")
                    continue

                if any(nc["suggested"] == dish_name for nc in needs_conf_list):
                    print(f"DEBUG: Skipping auto-add for '{dish_name}' (needs confirmation)")
                    continue

                dish_already_exists = dish_name in current_order_state["confirmed"]
                has_addition_keywords = any(kw in transcript.lower() for kw in ADDITION_KEYWORDS)

                print(f"DEBUG: [ITEM] '{dish_name}' exists={dish_already_exists} add_kw={has_addition_keywords} modified_addons={modified_addons} addons={addons}")

                if dish_already_exists and not has_addition_keywords:
                    existing = current_order_state["confirmed"][dish_name]
                    if modified_addons:
                        current_addons = existing.get("addons", [])
                        existing["addons"] = merge_structured_addons(current_addons, modified_addons)
                        print(f"DEBUG: [GUARD] Updated addons for existing '{dish_name}' via modified_addons: {existing['addons']}")
                    elif addons:
                        parsed_addon_dict = {}
                        plain_addons = []
                        for a in addons:
                            if isinstance(a, str) and ":" in a:
                                k, v = a.split(":", 1)
                                parsed_addon_dict[k.strip()] = v.strip()
                            else:
                                plain_addons.append(a)
                        if parsed_addon_dict:
                            current_addons = existing.get("addons", [])
                            existing["addons"] = merge_structured_addons(current_addons, parsed_addon_dict)
                            print(f"DEBUG: [GUARD] Updated addons for existing '{dish_name}' via parsed addons: {existing['addons']}")
                        else:
                            existing["addons"] = list(set(existing.get("addons", []) + plain_addons))
                            print(f"DEBUG: [GUARD] Merged addons (list) for existing '{dish_name}': {existing['addons']}")
                    else:
                        print(f"DEBUG: [GUARD] '{dish_name}' already in order, no addons and no addition words — skipping.")
                    continue

                current_qty = current_order_state["confirmed"][dish_name]["quantity"] if dish_name in current_order_state["confirmed"] else 0
                target_qty = current_qty + qty
                is_available, stock = inventory_service.check_availability(dish_name, target_qty)
                if not is_available:
                    print(f"DEBUG: {dish_name} target quantity {target_qty} exceeds stock {stock}. Not adding.")
                    unavailable_items.append(dish_name)
                    continue

                print(f"DEBUG: Adding '{dish_name}' (qty: {qty}) to confirmed order for table '{table_id}'")
                if dish_name in current_order_state["confirmed"]:
                    current_order_state["confirmed"][dish_name]["quantity"] += qty
                    current_order_state["confirmed"][dish_name]["addons"] = list(set(current_order_state["confirmed"][dish_name]["addons"] + addons))
                else:
                    current_order_state["confirmed"][dish_name] = {"dish": dish_name, "quantity": qty, "addons": addons}

            if needs_conf_list:
                current_order_state["pending_confirmation"] = needs_conf_list[0]
                print(f"DEBUG: Set pending_confirmation for table '{table_id}': {needs_conf_list[0]['suggested']}")

        if result.get("modifications"):
            from classifier_service import fuzzy_match_dish
            for mod in result["modifications"]:
                target = mod.get("target_item")
                action = mod.get("action")
                changes = mod.get("changes", {})

                changes_dict = {}
                if isinstance(changes, list):
                    for c in changes:
                        if isinstance(c, dict) and "type" in c:
                            changes_dict[c["type"]] = c.get("value")
                elif isinstance(changes, dict):
                    changes_dict = changes

                matched_target, score, _ = fuzzy_match_dish(target)
                in_order = matched_target in current_order_state["confirmed"]
                if not in_order and target in current_order_state["confirmed"]:
                    matched_target = target
                    in_order = True

                if not in_order and action != "add":
                    print(f"DEBUG: Modification target '{target}' not found in order.")
                    feedback = f"Maaf karjo, tamara order ma {target} nathi. Tamare biju kai change karvu che? (Sorry, {target} is not in your order. What would you like to change?)"
                    if feedback not in response_text:
                        response_text += " " + feedback
                    continue

                if action == "add" and score < 0.3:
                    print(f"DEBUG: Modification 'add' target '{target}' not found in menu.")
                    continue

                if action == "remove":
                    del current_order_state["confirmed"][matched_target]
                    print(f"DEBUG: Removed '{matched_target}'")

                elif action == "replace":
                    new_item_name = changes_dict.get("new_item")
                    if new_item_name:
                        matched_new, score, _ = fuzzy_match_dish(new_item_name)
                        if score > 0.3:
                            qty = current_order_state["confirmed"][matched_target]["quantity"]
                            is_available, stock = inventory_service.check_availability(matched_new, qty)
                            if is_available:
                                del current_order_state["confirmed"][matched_target]
                                current_order_state["confirmed"][matched_new] = {
                                    "dish": matched_new,
                                    "quantity": qty,
                                    "addons": [f"{k}: {v}" for k, v in changes_dict.items() if k != "new_item"]
                                }
                                print(f"DEBUG: Replaced '{matched_target}' with '{matched_new}'")
                            else:
                                print(f"DEBUG: Replace target '{matched_new}' quantity {qty} exceeds stock {stock}.")
                                unavailable_items.append(matched_new)

                elif action in ["update", "add"]:
                    if matched_target not in current_order_state["confirmed"]:
                        current_order_state["confirmed"][matched_target] = {
                            "dish": matched_target,
                            "quantity": 1 if action == "add" else 0,
                            "addons": []
                        }

                    existing = current_order_state["confirmed"][matched_target]

                    if "quantity" in changes_dict:
                        qty_val = changes_dict.pop("quantity")
                        if isinstance(qty_val, int) or (isinstance(qty_val, str) and qty_val.isdigit()):
                            val_qty = int(qty_val)
                            is_relative = any(kw in transcript.lower() for kw in ADDITION_KEYWORDS) or any(
                                w in transcript.lower() for w in ["add", "aur", "bija", "biju", "more"])
                            target_qty = existing["quantity"] + val_qty if is_relative else val_qty
                        elif str(qty_val).lower() == "increase":
                            target_qty = existing["quantity"] + 1
                        elif str(qty_val).lower() == "decrease":
                            target_qty = max(1, existing["quantity"] - 1)
                        else:
                            target_qty = existing["quantity"]

                        is_available, stock = inventory_service.check_availability(matched_target, target_qty)
                        if is_available:
                            existing["quantity"] = target_qty
                        else:
                            print(f"DEBUG: Modification of '{matched_target}' target quantity {target_qty} exceeds stock {stock}. Rejecting change.")
                            unavailable_items.append(matched_target)

                    if changes_dict:
                        current_addons = existing.get("addons", [])
                        updated_addons = merge_structured_addons(current_addons, changes_dict)
                        existing["addons"] = updated_addons
                        print(f"DEBUG: Updated '{matched_target}' addons: {updated_addons} (from changes: {changes_dict})")

        if result.get("is_finished"):
            is_finished = True

        if unavailable_items:
            response_text = response_service.get_availability_feedback_text(unavailable_items)
        elif result.get("response_text") and not (intent in ["affirmative", "negative"] and pending):
            response_text = result["response_text"]
        else:
            response_parts = []
            if conf_response:
                response_parts.append(conf_response)
            if items_msg:
                response_parts.append(items_msg)
            if not response_parts:
                response_text = "I'm sorry, I didn't quite catch that."
            else:
                response_text = " ".join(response_parts)

        if result.get("needs_confirmation") and response_service.get_confirm_text(
            result["needs_confirmation"][0]["suggested"], result["needs_confirmation"][0]["original"]
        ) not in response_text:
            sug = result["needs_confirmation"][0]
            response_text += " " + response_service.get_confirm_text(sug["suggested"], sug["original"])

        lang_code = result.get("language_code", "hi-IN")

        # Sync state to Redis after mutation
        asyncio.create_task(_maybe_sync_to_redis(table_id))
        asyncio.create_task(_broadcast_update())

        return {
            "classification": result,
            "response_text": response_text,
            "current_order": current_order_state["confirmed"],
            "is_finished": is_finished,
            "language_code": lang_code
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/order/correct")
async def correct(transcript: str = Form(...), table_id: str = Form("default")):
    current_order_state = get_table_state(table_id)
    try:
        current_items = list(current_order_state["confirmed"].keys())

        if detect_correction(transcript):
            corrections = process_correction(transcript, current_order_items=current_items)
            response_text = response_service.get_correction_feedback_text([])
            speech_b64 = await generate_speech(response_text)

            if speech_b64:
                def play_async():
                    try:
                        if winsound:
                            winsound.PlaySound(base64.b64decode(speech_b64), winsound.SND_MEMORY)
                    except:
                        pass
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
    tid = ensure_table_prefix(table_id)
    if tid in tables_state:
        del tables_state[tid]
    asyncio.create_task(_maybe_delete_from_redis(table_id))
    return {"message": f"Order for table {table_id} reset successfully"}


@app.post("/order/submit")
async def submit_order(table_id: str = "default"):
    current_order_state = get_table_state(table_id)
    if not current_order_state["confirmed"]:
        raise HTTPException(status_code=400, detail="No items in the order to submit.")

    order_items = current_order_state["confirmed"]
    detailed_results = []

    for item_key, item_data in order_items.items():
        dish_name = item_data.get("dish")
        qty = item_data.get("quantity", 1)
        success = inventory_service.update_stock(dish_name, -qty)
        detailed_results.append({"dish": dish_name, "quantity": qty, "success": success})

    current_order_state["confirmed"] = {}
    current_order_state["pending_confirmation"] = None

    asyncio.create_task(_maybe_sync_to_redis(table_id))
    asyncio.create_task(_broadcast_update())

    return {
        "message": "Order submitted successfully!",
        "order_summary": order_items,
        "inventory_updates": detailed_results
    }


@app.get("/inventory/status")
async def get_inventory_status():
    return inventory_service.load_inventory()


@app.post("/inventory/update")
async def update_inventory(dish_name: str = Form(...), change: int = Form(...)):
    success = inventory_service.update_stock(dish_name, change)
    if success:
        return {
            "message": f"Updated {dish_name} stock by {change}.",
            "new_stock": inventory_service.get_stock(dish_name)
        }
    else:
        raise HTTPException(status_code=404, detail=f"Dish '{dish_name}' not found in inventory.")


@app.post("/inventory/availability")
async def toggle_availability(dish_name: str = Form(...), available: bool = Form(...)):
    success = inventory_service.toggle_availability(dish_name, status=available)
    if success:
        return {
            "message": f"Toggled {dish_name} availability to {available}.",
            "stock": inventory_service.get_stock(dish_name)
        }
    else:
        raise HTTPException(status_code=404, detail=f"Dish '{dish_name}' not found in inventory.")


@app.websocket("/order/stream_audio")
async def ws_stream_audio(websocket: WebSocket, table_id: str = "default"):
    await websocket.accept()
    audio_chunks = []

    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                logging.debug("WS Client disconnected.")
                print("WS Client disconnected.")
                break

            if message.get("text") is not None:
                try:
                    logging.debug("Received WS TEXT: " + str(message["text"]))
                    print("Received WS TEXT:", message["text"])
                    data = json.loads(message["text"])
                    if data.get("action") == "start":
                        audio_chunks = []
                        table_id = data.get("table_id", table_id)
                    elif data.get("action") == "stop":
                        total_bytes = sum(len(chunk) for chunk in audio_chunks)
                        if total_bytes < 3000:
                            print(f"DEBUG: Received audio is too short or empty ({total_bytes} bytes). Skipping transcription.")
                            try:
                                await websocket.send_json({"error": "No speech detected.", "transcript": ""})
                            except:
                                break
                            audio_chunks = []
                            continue

                        if audio_chunks:
                            import tempfile
                            with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as tmp_audio:
                                for chunk in audio_chunks:
                                    tmp_audio.write(chunk)
                                tmp_audio_path = tmp_audio.name
                            try:
                                from ordering_workflow import transcribe_audio
                                transcript, processed_audio_bytes, _ = await transcribe_audio(tmp_audio_path)
                                if transcript:
                                    result = None
                                    for attempt in range(3):
                                        try:
                                            result = await process_order_logic(transcript, table_id)
                                            break
                                        except Exception as classify_err:
                                            if "429" in str(classify_err) and attempt < 2:
                                                wait_time = (attempt + 1) * 3
                                                logging.warning(f"Rate limit 429 hit, retrying classify in {wait_time}s")
                                                await asyncio.sleep(wait_time)
                                            else:
                                                raise classify_err
                                    if result:
                                        result["transcript"] = transcript
                                        try:
                                            await websocket.send_json(result)
                                        except (WebSocketDisconnect, RuntimeError) as e:
                                            logging.info(f"WS Client disconnected during result delivery: {e}")
                                            break

                                        try:
                                            tts_lang = result.get("language_code", "hi-IN")
                                            tts_text = result.get("response_text", "")
                                            if tts_text:
                                                speech_b64 = await generate_speech(tts_text, language_code=tts_lang)
                                                if speech_b64:
                                                    await websocket.send_json({"type": "tts_audio", "speech": speech_b64})
                                        except (WebSocketDisconnect, RuntimeError):
                                            break
                                        except Exception as tts_err:
                                            print(f"TTS generation error: {tts_err}")
                                    else:
                                        try:
                                            await websocket.send_json({"error": "Classification failed.", "transcript": transcript})
                                        except:
                                            break
                                else:
                                    try:
                                        await websocket.send_json({"error": "No speech detected.", "transcript": ""})
                                    except:
                                        break
                            except Exception as e:
                                logging.error(f"Processing error in WS: {e}")
                                print(f"Processing error in WS: {e}")
                                try:
                                    await websocket.send_json({
                                        "classification": {},
                                        "response_text": f"Error: {e}",
                                        "is_finished": False,
                                        "transcript": "",
                                        "error": str(e)
                                    })
                                except:
                                    logging.warning("Could not send error response: Client likely disconnected.")
                                    break
                            finally:
                                from audio_utils import safe_remove
                                safe_remove(tmp_audio_path)
                                audio_chunks = []
                        else:
                            try:
                                await websocket.send_json({"error": "No audio chunks received"})
                            except:
                                break
                except Exception as e:
                    logging.error(f"WS text error: {e}")
                    print(f"WS text error: {e}")
            elif message.get("bytes") is not None:
                logging.debug(f"Received WS BYTES size: {len(message['bytes'])}")
                print(f"Received WS BYTES size: {len(message['bytes'])}")
                audio_chunks.append(message["bytes"])
    except WebSocketDisconnect:
        pass


if __name__ == "__main__":
    import uvicorn
    import webbrowser
    import threading
    import time

    def open_browser():
        time.sleep(2)
        webbrowser.open("http://127.0.0.1:8000/")
        webbrowser.open("http://127.0.0.1:8000/dashboard")

    threading.Thread(target=open_browser, daemon=True).start()
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True, reload_dirs=["."])
