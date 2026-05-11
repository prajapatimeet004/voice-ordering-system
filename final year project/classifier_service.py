import os
import json
import re
import time
import datetime
from dotenv import load_dotenv
from rapidfuzz import process, fuzz
import asyncio

# ─── Token Usage Logger ───────────────────────────────────────────────────────
_LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")

def log_token_usage(transcript: str, input_tokens: int, output_tokens: int, latency_ms: float, table: str = "unknown"):
    """Appends one line per LLM call to a daily log file inside logs/."""
    os.makedirs(_LOG_DIR, exist_ok=True)
    today = datetime.date.today().strftime("%Y-%m-%d")
    log_file = os.path.join(_LOG_DIR, f"token_usage_{today}.log")
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total_tokens = input_tokens + output_tokens
    snippet = transcript[:60].replace("\n", " ") if transcript else ""
    line = (
        f"[{now}] Table:{table} | "
        f"Input:{input_tokens} | Output:{output_tokens} | Total:{total_tokens} | "
        f"Latency:{latency_ms:.0f}ms | Transcript:\"{snippet}...\""
    )
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(f"DEBUG: [TOKEN LOG] {line}")
# ─────────────────────────────────────────────────────────────────────────────


load_dotenv(override=True)
import inventory_service
from groq import AsyncGroq

GROQ_API_KEY = os.getenv("GROQ_API_KEY") 
SARVAM_API_KEY = os.getenv("SARVAM_API_KEY") or "sk_gryfenq9_2CYOHCGaYJFAWf8VYpbPA959"

_llm_client = None

def get_llm_client():
    global _llm_client
    if _llm_client is None:
        from openai import OpenAI
        # Use Sarvam AI as the primary text model
        _llm_client = OpenAI(
            base_url="https://api.sarvam.ai/v1",
            api_key=SARVAM_API_KEY
        )
    return _llm_client

_cerebras_client = None

def get_cerebras_client():
    global _cerebras_client
    if _cerebras_client is None:
        from openai import AsyncOpenAI
        _cerebras_client = AsyncOpenAI(
            base_url="https://api.cerebras.ai/v1",
            api_key="csk-9fhkv3hvmt4krfdrkcwjhwvvd9wx9d8ddem4jcdndrhcphty"
        )
    return _cerebras_client


_gemini_model = None

def get_gemini_model():
    """Fallback Gemini model if needed."""
    global _gemini_model
    if _gemini_model is None:
        from google import genai
        GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
        client = genai.Client(api_key=GEMINI_API_KEY)
        _gemini_model = client
    return _gemini_model

def extract_json(text):
    """
    Robustly extract JSON from text that might contain markdown blocks and <think> tags.
    Handles common LLM mistakes like trailing commas and unclosed reasoning blocks.
    """
    if not text:
        return ""
        
    # 1. Remove <think> blocks
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    text = re.sub(r'<think>.*', '', text, flags=re.DOTALL)
    
    # 2. Try to find JSON block in markdown
    match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if match:
        text = match.group(1)
    else:
        # 3. If no markdown, find the first '{'/'[' and last '}'/']'
        brace_start = text.find('{')
        bracket_start = text.find('[')
        
        start_idx = -1
        if brace_start != -1 and bracket_start != -1:
            start_idx = min(brace_start, bracket_start)
        else:
            start_idx = brace_start if brace_start != -1 else bracket_start
            
        if start_idx != -1:
            last_brace = text.rfind('}')
            last_bracket = text.rfind(']')
            end_idx = max(last_brace, last_bracket)
            
            if end_idx > start_idx:
                text = text[start_idx:end_idx+1]
            else:
                text = text[start_idx:]
        else:
            text = text.strip()
            
    # Clean up common malformed JSON issues
    text = re.sub(r',\s*([\]}])', r'\1', text)
    return text

# Custom Number Map
NUMBER_MAP = {
    "one": 1, "ek": 1, "two": 2, "do": 2, "be": 2,
    "three": 3, "teen": 3, "tran": 3, "four": 4, "chaar": 4, "char": 4,
    "five": 5, "paanch": 5, "panch": 5, "six": 6, "chhe": 6, "che": 6,
    "seven": 7, "saat": 7, "eight": 8, "aath": 8, "nine": 9, "nau": 9, "nav": 9,
    "ten": 10, "das": 10
}

def preprocess_transcript(transcript: str):
    """Replaces number words with digits."""
    words = transcript.lower().split()
    processed_words = []
    for word in words:
        num = NUMBER_MAP.get(word)
        processed_words.append(str(num) if num is not None else word)
    return " ".join(processed_words)

# Comprehensive Indian Menu
INDIAN_MENU = [
    "Masala Dosa", "Plain Dosa", "Mysore Dosa", "Rava Dosa",
    "Paneer Tikka", "Palak Paneer", "Paneer Pasanda", "Paneer Butter Masala",
    "Butter Chicken", "Chicken Biryani", "Chicken Tikka", "Chicken Masala",
    "Samosa", "Chhole Bhature", "Dal Makhani", "Aloo Gobi", "Mix Veg", 
    "Aloo Bhuri", "Puri Bhaji", "Aloo Paratha",
    "Naan", "Roti", "Chai", "Coffee", "Tea", "Burger", "Pizza",
    "Gulab Jamun", "Jalebi", "Idli", "Vada", "Uttapam", "Pav Bhaji", "Misal Pav",
    "Dhokla", "Thepla", "Khandvi", "Vada Pav", "Rajma Chawal",
    "Mutton Rogan Josh", "Fish Curry", "Prawn Curry", "Tandoori Roti"
]

MENU_CATEGORIES = {
    "Dosas": ["Masala Dosa", "Plain Dosa", "Mysore Dosa", "Rava Dosa", "Uttapam"],
    "Paneer": ["Paneer Tikka", "Palak Paneer", "Paneer Pasanda", "Paneer Butter Masala"],
    "Chicken": ["Butter Chicken", "Chicken Biryani", "Chicken Tikka", "Chicken Masala"],
    "Main Course": ["Dal Makhani", "Chhole Bhature", "Mix Veg", "Aloo Gobi", "Aloo Bhuri", "Rajma Chawal"],
    "Starters": ["Samosa", "Vada Pav", "Pav Bhaji", "Misal Pav", "Dhokla", "Thepla", "Khandvi"],
    "South Indian": ["Idli", "Vada", "Uttapam", "Masala Dosa"],
    "Breads": ["Naan", "Roti", "Aloo Paratha", "Puri Bhaji", "Tandoori Roti"],
    "Beverages": ["Chai", "Coffee", "Tea"],
    "Desserts": ["Gulab Jamun", "Jalebi"],
    "Fusion/Global": ["Burger", "Pizza"],
    "Non-Veg": ["Mutton Rogan Josh", "Fish Curry", "Prawn Curry", "Chicken Biryani", "Chicken Tikka", "Butter Chicken", "Chicken Masala"]
}

# Global variables for Hybrid Matching
_model = None
_MENU_EMBEDDINGS = None
_KEYWORD_MAP = {} 
_INITIALIZED = False

def _initialize_hybrid_matching():
    global _model, _MENU_EMBEDDINGS, _KEYWORD_MAP, _INITIALIZED
    if _INITIALIZED: return 
    from sentence_transformers import SentenceTransformer
    _model = SentenceTransformer('all-MiniLM-L6-v2')
    menu_lower = [m.lower() for m in INDIAN_MENU]
    _MENU_EMBEDDINGS = _model.encode(menu_lower, convert_to_tensor=True)
    for dish in INDIAN_MENU:
        tokens = re.sub(r'[^a-zA-Z0-9\s]', '', dish.lower()).split()
        for t in tokens:
            if len(t) > 2:
                if t not in _KEYWORD_MAP: _KEYWORD_MAP[t] = set()
                _KEYWORD_MAP[t].add(dish)
    _INITIALIZED = True

_initialize_hybrid_matching()

def fuzzy_match_dish(dish_name: str):
    if not dish_name: return None, 0.0, False
    from sentence_transformers import util
    import torch
    clean_name = re.sub(r'[^a-zA-Z0-9\s]', '', dish_name.lower()).strip()
    query_emb = _model.encode(clean_name, convert_to_tensor=True)
    cos_scores = util.cos_sim(query_emb, _MENU_EMBEDDINGS)[0]
    top_v, top_i = torch.topk(cos_scores, k=1)
    return INDIAN_MENU[int(top_i[0])], float(top_v[0]), False

# Response Schema
CLASSIFICATION_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "intent": {"type": "STRING", "enum": ["new_order", "modify_order", "affirmative", "negative", "finishing", "recommendation", "question", "none"]},
        "items": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "name": {"type": "STRING"},
                    "quantity": {"type": "INTEGER"},
                    "addons": {"type": "OBJECT"}
                },
                "required": ["name", "quantity", "addons"]
            }
        },
        "modifications": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "target_item": {"type": "STRING"},
                    "action": {"type": "STRING", "enum": ["add", "remove", "update", "replace"]},
                    "changes": {"type": "OBJECT"}
                },
                "required": ["target_item", "action", "changes"]
            }
        },
        "response_text": {"type": "STRING"},
        "language_code": {"type": "STRING"},
        "is_finished": {"type": "BOOLEAN"}
    },
    "required": ["intent", "items", "modifications", "response_text", "language_code", "is_finished"]
}

async def classify_order(transcript: str, current_order_summary: str = "Order is empty", history: list = None):
    from correction_service import get_correction_hints
    if not transcript or not transcript.strip(): return {}
    
    inventory_summary = inventory_service.get_inventory_summary()
    categories_summary = "\n".join([f"- {cat}: {', '.join(dishes)}" for cat, dishes in MENU_CATEGORIES.items()])

    # Consolidated System Prompt: Polite Indian Waiter + Recommendations + Strict Ordering
    system_prompt_template = """
🎯 SYSTEM PROMPT: Multilingual Indian Food Voice Agent

You are an intelligent Indian restaurant voice-ordering assistant. Act like a polite, smart Indian waiter.

---

### 🏛️ RESTAURANT INFORMATION
{RESTAURANT_INFO}

---

# 🍽 MENU & INVENTORY
Use ONLY dishes from:
{MENU_CATEGORIES}

INVENTORY STATUS:
{INVENTORY_STATUS}

---

### 🕒 HISTORY
{CONVERSATION_HISTORY}

---

# 🧠 RECOMMENDATION ENGINE
1. Cuisine & Region: Suggest regional dishes (Gujarati, Punjabi, etc.) from categories.
2. Meal-Time: Suggest Breakfast (Dosa/Idli), Lunch (Thali/Sabji), Snacks (Chaat/Fries), Desserts.
3. Preferences: Use keywords like spicy, Jain, healthy, cheesy. Suggest beverages/upsells naturally.

---

# 🚫 STRICT RULES
- Multilingual: Respond in natural Gujlish (Gujarati+English) or Hinglish (Hindi+English). Match language_code (gu-IN/hi-IN/en-IN).
- State-Aware: Only remove if item exists. Use action: "update" for quantity/addons. For addon removal, target the dish (e.g. target: "Dosa", changes: {"chutney": "remove"}).
- No Duplicates: Do NOT add to `items` if mentioned without addition words like "one more".
- Inventory: Apologize if out of stock and suggest specific alternative.

---

# 🧾 OUTPUT FORMAT (JSON)
{
  "intent": "new_order | modify_order | recommendation | question | affirmative | negative | none",
  "items": [],
  "modifications": [],
  "response_text": "Polite concierge response",
  "language_code": "hi-IN | gu-IN | en-IN",
  "is_finished": false
}
"""

    history_str = "\n".join([f"- {h}" for h in (history or [])]) if history else "No history."
    restaurant_info = "Pooja Restaurant (Ahmedabad). Open 11AM-11PM."

    system_prompt = system_prompt_template.replace("{INVENTORY_STATUS}", inventory_summary) \
                                         .replace("{MENU_CATEGORIES}", categories_summary) \
                                         .replace("{RESTAURANT_INFO}", restaurant_info) \
                                         .replace("{CONVERSATION_HISTORY}", history_str)

    hints, hint_latency = get_correction_hints(transcript)
    hint_prompt = f"### HINTS: {hints}\n" if hints else ""
    preprocessed_text = preprocess_transcript(transcript)

    final_order_result = {
        "items": [], "confirmed": {}, "needs_confirmation": [], "not_in_menu": [],
        "is_finished": False, "intent": "none", "response_text": "", "language_code": "hi-IN"
    }

    try:
        llm_start = time.perf_counter()
        try:
            from google.genai import types
            response = get_gemini_model().models.generate_content(
                model='gemini-1.5-flash-latest',
                contents=f"{hint_prompt}Summary: {current_order_summary}\nUser: {transcript}",
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    response_mime_type='application/json',
                    response_schema=CLASSIFICATION_SCHEMA,
                    temperature=0.1,
                ),
            )
            text_content = response.text
            usage = response.usage_metadata
            prompt_tokens = usage.prompt_token_count if usage else 0
            completion_tokens = usage.candidates_token_count if usage else 0
        except Exception as e:
            print(f"Gemini Error: {e}. Falling back to Cerebras...")
            client = get_cerebras_client()
            completion = await client.chat.completions.create(
                model="llama3.1-8b",
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": transcript}],
                response_format={"type": "json_object"},
                temperature=0.1
            )
            text_content = completion.choices[0].message.content
            usage_obj = getattr(completion, "usage", None)
            prompt_tokens = getattr(usage_obj, "prompt_tokens", 0)
            completion_tokens = getattr(usage_obj, "completion_tokens", 0)
            
        llm_end = time.perf_counter()
        total_llm_time = (llm_end - llm_start) * 1000
        
        log_token_usage(transcript, prompt_tokens, completion_tokens, total_llm_time)
        parsed_data = json.loads(extract_json(text_content))

        for item in parsed_data.get("items", []):
            mapped_dish, score, _ = fuzzy_match_dish(item.get("name"))
            processed_item = {
                "dish": mapped_dish,
                "quantity": item.get("quantity", 1),
                "portion": "full",
                "modified_addons": item.get("addons", {}),
                "addons": [f"{k}: {v}" for k, v in item.get("addons", {}).items()]
            }
            final_order_result["items"].append(processed_item)
            final_order_result["confirmed"][mapped_dish] = {"quantity": processed_item["quantity"], "addons": processed_item["addons"]}

        final_order_result["modifications"] = parsed_data.get("modifications", [])
        final_order_result["intent"] = parsed_data.get("intent", "none")
        final_order_result["response_text"] = parsed_data.get("response_text", "")
        final_order_result["language_code"] = parsed_data.get("language_code", "hi-IN")
        final_order_result["is_finished"] = parsed_data.get("is_finished", False)

    except Exception as e:
        print(f"Classification error: {e}")
    
    return final_order_result

def refine_addons_with_llm(dish_name: str, current_addons: list, new_transcript: str) -> list:
    system_prompt = f"Update addons for '{dish_name}'. Current: {current_addons}. User: {new_transcript}. Return JSON: {{\"updated_addons\": []}}"
    try:
        from google.genai import types
        response = get_gemini_model().models.generate_content(
            model='gemini-1.5-flash-latest',
            contents=new_transcript,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                response_mime_type='application/json',
                temperature=0.0
            )
        )
        return json.loads(response.text).get("updated_addons", current_addons)
    except Exception as e:
        print(f"Refine error: {e}")
        return current_addons
