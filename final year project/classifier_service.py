import os
import json
import re
from dotenv import load_dotenv
from rapidfuzz import process, fuzz

load_dotenv(override=True)
from groq import Groq
import inventory_service
from addon_extractor import extract_addons

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

# Keep for backward compat
def get_groq_client():
    return get_llm_client()

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
    Handles common LLM mistakes like trailing commas.
    """
    # Remove <think> blocks
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    
    # Try to find JSON block
    match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if match:
        text = match.group(1)
    else:
        # If no markdown, try to find the first { and last }
        match = re.search(r'(\{.*\})', text, re.DOTALL)
        if match:
            text = match.group(1)
        else:
            text = text.strip()
            
    # Clean up common malformed JSON issues
    # 1. Remove trailing commas before closing braces/brackets
    text = re.sub(r',\s*([\]}])', r'\1', text)
    # 2. Basic cleanup for any other weirdness
    return text

# Custom Number Map for English, Hindi, and Gujarati
NUMBER_MAP = {
    # 1–10
    "one": 1, "ek": 1,
    "two": 2, "do": 2, "be": 2,
    "three": 3, "teen": 3, "tran": 3,
    "four": 4, "chaar": 4, "char": 4,
    "five": 5, "paanch": 5, "panch": 5,
    "six": 6, "chhe": 6, "che": 6,
    "seven": 7, "saat": 7,
    "eight": 8, "aath": 8,
    "nine": 9, "nau": 9, "nav": 9,
    "ten": 10, "das": 10,

    # 11–19
    "eleven": 11, "gyarah": 11, "gyara": 11, "agiyar": 11,
    "twelve": 12, "baarah": 12, "barah": 12, "baar": 12,
    "thirteen": 13, "terah": 13, "tera": 13,
    "fourteen": 14, "chaudah": 14, "chauda": 14,
    "fifteen": 15, "pandrah": 15, "pandhar": 15,
    "sixteen": 16, "solah": 16, "sola": 16,
    "seventeen": 17, "satrah": 17, "sattarh": 17,
    "eighteen": 18, "atharah": 18,
    "nineteen": 19, "unnis": 19,

    # 20–29
    "twenty": 20, "bees": 20, "vis": 20,
    "twenty one": 21, "ikkees": 21, "ekvis": 21,
    "twenty two": 22, "bais": 22, "bavis": 22,
    "twenty three": 23, "teis": 23, "trevis": 23,
    "twenty four": 24, "chaubees": 24, "chovis": 24,
    "twenty five": 25, "pachis": 25,
    "twenty six": 26, "chabbis": 26,
    "twenty seven": 27, "sattais": 27,
    "twenty eight": 28, "athais": 28,
    "twenty nine": 29, "untis": 29,

    # 30–39
    "thirty": 30, "tees": 30, "tris": 30,
    "thirty one": 31, "ikattis": 31,
    "thirty two": 32, "battis": 32,
    "thirty three": 33, "tettis": 33,
    "thirty four": 34, "chauntis": 34,
    "thirty five": 35, "paintis": 35,
    "thirty six": 36, "chhattis": 36,
    "thirty seven": 37, "saintis": 37,
    "thirty eight": 38, "adhtis": 38,
    "thirty nine": 39, "untalis": 39,

    # 40–49
    "forty": 40, "chalis": 40,
    "forty one": 41, "iktalis": 41,
    "forty two": 42, "bayalis": 42,
    "forty three": 43, "tetalis": 43,
    "forty four": 44, "chawalis": 44,
    "forty five": 45, "paintalis": 45,
    "forty six": 46, "chiyalis": 46,
    "forty seven": 47, "saitalis": 47,
    "forty eight": 48, "adhtalis": 48,
    "forty nine": 49, "unchaas": 49,

    # 50–59
    "fifty": 50, "pachaas": 50,
    "fifty one": 51, "ikavan": 51,
    "fifty two": 52, "bawan": 52,
    "fifty three": 53, "tirpan": 53,
    "fifty four": 54, "chauvan": 54,
    "fifty five": 55, "pachpan": 55,
    "fifty six": 56, "chappan": 56,
    "fifty seven": 57, "sattavan": 57,
    "fifty eight": 58, "athavan": 58,
    "fifty nine": 59, "unsath": 59,

    # 60–69
    "sixty": 60,
    "sixty one": 61, "iksath": 61,
    "sixty two": 62, "basath": 62,
    "sixty three": 63, "tirsath": 63,
    "sixty four": 64, "chausath": 64,
    "sixty five": 65, "painsath": 65,
    "sixty six": 66, "chhiyasath": 66,
    "sixty seven": 67, "sadsath": 67,
    "sixty eight": 68, "adhsath": 68,
    "sixty nine": 69, "unsath": 69,

    # 70–79
    "seventy": 70, "sattar": 70,
    "seventy one": 71, "ikhattar": 71,
    "seventy two": 72, "bahattar": 72,
    "seventy three": 73, "tihattar": 73,
    "seventy four": 74, "chauhattar": 74,
    "seventy five": 75, "pachattar": 75,
    "seventy six": 76, "chhihattar": 76,
    "seventy seven": 77, "sattattar": 77,
    "seventy eight": 78, "athattar": 78,
    "seventy nine": 79, "unasi": 79,

    # 80–89
    "eighty": 80, "assi": 80,
    "eighty one": 81, "ikiyasi": 81,
    "eighty two": 82, "bayasi": 82,
    "eighty three": 83, "tirasi": 83,
    "eighty four": 84, "chaurasi": 84,
    "eighty five": 85, "pachasi": 85,
    "eighty six": 86, "chhiyasi": 86,
    "eighty seven": 87, "sattasi": 87,
    "eighty eight": 88, "athasi": 88,
    "eighty nine": 89, "navasi": 89,

    # 90–99
    "ninety": 90, "nabbe": 90,
    "ninety one": 91, "ikyanve": 91,
    "ninety two": 92, "bayanve": 92,
    "ninety three": 93, "tiranve": 93,
    "ninety four": 94, "chauranve": 94,
    "ninety five": 95, "pachanve": 95,
    "ninety six": 96, "chhiyanve": 96,
    "ninety seven": 97, "sattanve": 97,
    "ninety eight": 98, "athanve": 98,
    "ninety nine": 99, "ninyanve": 99,

    # 100
    "hundred": 100,
    "one hundred": 100,
    "one hundred": 100,
    "sau": 100,
}

# Portion Mapping for Standardization
PORTION_MAP = {
    "half": "half", "ardhu": "half", "1/2": "half", "aadha": "half", "adha": "half",
    "quarter": "quarter", "pav": "quarter", "pau": "quarter", "1/4": "quarter", "pa": "quarter",
    "full": "full", "ek": "full", "akhay": "full", "akha": "full", "single": "full"
}

def standardize_portion(raw_text: str):
    """
    Standardizes portion names (e.g., 'ardhu' -> 'half') using a predefined map.
    Returns the standardized string or the original text if no match is found.
    """
    if not raw_text or not isinstance(raw_text, str):
        return "full"
    
    raw_text = raw_text.lower().strip()
    
    # Direct match attempt
    if raw_text in PORTION_MAP:
        return PORTION_MAP[raw_text]
    
    # Fuzzy match for minor typos or variations
    from rapidfuzz import process, fuzz
    match = process.extractOne(raw_text, list(PORTION_MAP.keys()), scorer=fuzz.ratio)
    if match and match[1] > 80:
        return PORTION_MAP[match[0]]
        
    return raw_text

# Intent Mapping for Standard Responses
INTENT_MAP = {
    "affirmative": [
        "yes", "yeah", "yep", "yup", "sure", "ok", "okay", "ha", "haan", "theek hai", "thek hai", "ji", "chalshe", "chalse", "kar do", "thik che", "thik chhe"
    ],
    "negative": [
        "no", "nope", "not that", "nahi", "na", "nathi", "nathi joitu", "nako", "nai"
    ],
    "finishing": [
        "done", "finished", "that's it", "bus", "bas", "bas itna hi", "itna hi dena", "itlu j", "pachi nai", "bas avu j", "order confirm"
    ]
}

def detect_intent(transcript: str):
    """
    Identifies if a short transcript matches a common intent (affirmative, negative, finishing)
    using keyword matching. Returns (intent_name, confidence) or (None, 0).
    """
    if not transcript or len(transcript.split()) > 4: # Only for short responses
        return None, 0
    
    transcript = re.sub(r'[^a-zA-Z0-9\s]', '', transcript.lower().strip())
    
    for intent, keywords in INTENT_MAP.items():
        # Exact match
        if transcript in keywords:
            return intent, 1.0
        
        # Fuzzy match for typos
        from rapidfuzz import process, fuzz
        match = process.extractOne(transcript, keywords, scorer=fuzz.ratio)
        if match and match[1] > 80:
            return intent, 0.9

    return None, 0

# Multi-lingual splitting keywords (Item Separators)
SPLIT_KEYWORDS = [
    # English
    "and", "plus", "also", "then", "another",
    # Hindi
    "aur", "saath", "phir", "dusra", "aur ek", "iske baad", "uske baad",
    # Gujarati
    "ane", "sathe", "jode", "beju", "pachi", "ane biju", "ana pachi", "iske bad", "uske pele"
]

def split_transcript(transcript: str):
    """
    Splits a long transcript into individual item chunks based on keywords.
    Regex handles word boundaries to avoid splitting mid-word (e.g., 'another' vs 'an').
    """
    if not transcript:
        return []
    
    # Create regex pattern for all keywords with word boundaries
    pattern = r'\b(?:' + '|'.join(map(re.escape, SPLIT_KEYWORDS)) + r')\b'
    
    # Split but filter out empty/whitespace strings
    chunks = re.split(pattern, transcript, flags=re.IGNORECASE)
    return [c.strip() for c in chunks if c.strip()]

def get_number_from_map(word: str):
    """
    Finds the number from the NUMBER_MAP using EXACT matching only.
    Returns the integer value if a match is found, else None.
    """
    word = word.lower().strip()
    if not word:
        return None
    
    # Direct match only (No fuzzy matching for numbers)
    return NUMBER_MAP.get(word)

def preprocess_transcript(transcript: str):
    """
    Searches for number words in the transcript and replaces them with numeric digits
    using EXACT matching against the NUMBER_MAP.
    """
    words = transcript.lower().split()
    processed_words = []
    
    i = 0
    while i < len(words):
        # Check bigram first (exact)
        if i + 1 < len(words):
            bigram = f"{words[i]} {words[i+1]}"
            num = get_number_from_map(bigram)
            if num is not None:
                processed_words.append(str(num))
                i += 2
                continue
        
        # Check single word (exact)
        num = get_number_from_map(words[i])
        if num is not None:
            processed_words.append(str(num))
        else:
            processed_words.append(words[i])
        i += 1
        
    return " ".join(processed_words)

# Comprehensive Indian Menu
INDIAN_MENU = [
    "Masala Dosa", "Paneer Tikka", "Butter Chicken", "Chicken Biryani", 
    "Samosa", "Chhole Bhature", "Dal Makhani", "Palak Paneer", 
    "Aloo Gobi", "Naan", "Roti", "Chai", "Coffee", "Tea", "Burger", "Pizza",
    "Gulab Jamun", "Jalebi", "Idli", "Vada", "Uttapam", "Pav Bhaji", "Misal Pav",
    "Dhokla", "Thepla", "Khandvi", "Vada Pav", "Rajma Chawal",
    "Chicken Tikka", "Mutton Rogan Josh", "Fish Curry", "Prawn Curry"
]

# Global variables for Embeddings (Loaded lazily)
model = None
MENU_EMBEDDINGS = None

def get_embedding_model():
    """Returns the embedding model and pre-calculated menu embeddings."""
    global model, MENU_EMBEDDINGS
    if model is None:
        print("DEBUG: Loading Embedding Model...")
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer('all-MiniLM-L6-v2')
        # Pre-calculate menu embeddings (lowercase for consistency)
        MENU_EMBEDDINGS = model.encode([m.lower() for m in INDIAN_MENU], convert_to_tensor=True)
    return model, MENU_EMBEDDINGS

def match_dish_with_embeddings(dish_name: str):
    """
    Matches a dish name against INDIAN_MENU using a Hybrid approach:
    60% SentenceTransformers (Meaning) + 40% RapidFuzz (Keywords).
    Returns (matched_item, hybrid_score).
    """
    if not dish_name:
        return None, 0.0
    
    # Ensure model and embeddings are loaded
    model, menu_embs = get_embedding_model()
    
    # Remove noise characters (like ?, !, .) before matching
    clean_name = re.sub(r'[^a-zA-Z0-9\s]', '', dish_name).strip()
    if not clean_name:
        return None, 0.0

    # 1. Semantic Search (SentenceTransformers)
    query_embedding = model.encode(clean_name, convert_to_tensor=True)
    from sentence_transformers import util
    import torch
    cos_scores = util.cos_sim(query_embedding, menu_embs)[0]
    semantic_score, best_idx = torch.max(cos_scores, dim=0)
    semantic_score = float(semantic_score)
    semantic_match = INDIAN_MENU[best_idx]

    # 2. Keyword Search (RapidFuzz) - Case-insensitive
    from rapidfuzz import process, fuzz
    # Match against lowercase menu
    menu_lower = [m.lower() for m in INDIAN_MENU]
    fuzzy_match_lower, fuzzy_score, fuzzy_idx = process.extractOne(clean_name.lower(), menu_lower, scorer=fuzz.token_set_ratio)
    fuzzy_score = fuzzy_score / 100.0 # Normalize to 0.0 - 1.0
    fuzzy_match = INDIAN_MENU[fuzzy_idx]

    # 3. Hybrid Calculation (60/40)
    # If the matches differ, we prioritize the semantic match but incorporate fuzzy signals
    if semantic_match == fuzzy_match:
        hybrid_score = (semantic_score * 0.6) + (fuzzy_score * 0.4)
        final_match = semantic_match
    else:
        # If they disagree, we check if the fuzzy match is exceptionally strong
        if fuzzy_score > 0.95 and semantic_score < 0.7:
            final_match = fuzzy_match
            hybrid_score = (fuzzy_score * 0.6) + (semantic_score * 0.4) # Shift weight toward certain fuzzy
        else:
            final_match = semantic_match
            hybrid_score = (semantic_score * 0.6) + (fuzzy_score * 0.4)

    print(f"DEBUG: Hybrid Match for '{dish_name}': {final_match} (Semantic: {semantic_score:.2f}, Fuzzy: {fuzzy_score:.2f}, Hybrid: {hybrid_score:.2f})")
    return final_match, hybrid_score

def fuzzy_match_dish(dish_name: str):
    """
    Primary matching function using the Hybrid approach.
    """
    return match_dish_with_embeddings(dish_name)

# Pre-defined Response Schema for Order Classification
CLASSIFICATION_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "items": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "dish": {"type": "STRING", "description": "Dish name exactly from transcript"},
                    "quantity": {"type": "INTEGER", "description": "Number of units"},
                    "portion": {"type": "STRING", "enum": ["full", "half", "quarter"], "description": "Size/Portion of the dish"},
                    "modifier": {"type": "STRING", "enum": ["set", "increase", "decrease"], "description": "Change type (set/increase/decrease)"},
                    "raw_addons": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Customization phrases for this dish"}
                },
                "required": ["dish", "quantity", "portion", "modifier", "raw_addons"]
            }
        },
        "is_finished": {"type": "BOOLEAN", "description": "True if user is done ordering"},
        "intent": {"type": "STRING", "enum": ["affirmative", "negative", "inquiry", "none"], "description": "User intent (yes/no/question)"},
        "response_text": {"type": "STRING", "description": "Friendly response from Pooja"},
        "language_code": {"type": "STRING", "description": "Sarvam AI language code (hi-IN, gu-IN, etc.)"}
    },
    "required": ["items", "is_finished", "intent", "response_text", "language_code"]
}

def classify_order(transcript: str):
    """
    Classifies a voice order transcript into a structured JSON format.
    Uses Python-based splitting to process multiple items accurately.
    """
    if not transcript.strip():
        return {}

    # Split transcript into chunks
    chunks = split_transcript(transcript)
    if not chunks:
        chunks = [transcript] # Fallback if splitting fails or no keywords found
    
    print(f"DEBUG: Split into {len(chunks)} chunks: {chunks}")

    final_order_result = {
        "items": [],
        "confirmed": {},
        "needs_confirmation": [],
        "not_in_menu": [],
        "is_finished": False,
        "intent": "none",
        "response_text": "",
        "language_code": "hi-IN"
    }

    # Fetch current inventory status to inform the LLM
    inventory_summary = inventory_service.get_inventory_summary()

    # Optimized System Prompt - Focusing on Extraction and Persona
    system_prompt = f"""
    You are Pooja, a warm and efficient restaurant concierge.
    You can understand all major Indian languages (including Gujarati, Hindi, Hinglish, Gujlish, and mixed speech) and accurately interpret user intent from informal, spoken, and speech-to-text inputs. 
    Your task is to extract dishes, quantities, and customizations from a customer's voice order.
    
    AVAILABLE MENU:
    {', '.join(INDIAN_MENU)}

    INVENTORY STATUS (CRITICAL):
    {inventory_summary}

    CRITICAL EXTRACTION RULES:
    1. NEVER TRANSLATE: Keep names like "tikhu", "dungli", "vadhare" exactly as spoken.
    2. RAW CUSTOMIZATION: "biryani ma thodu vadhu tikhu" -> dish: "biryani", raw_addons: ["thodu vadhu tikhu"]. 
    3. QUANTITY MODIFIER: 
       - Use "increase" for adding to existing count. Set "quantity" to the number being added.
         Example: "bija be add karo" -> quantity: 2, modifier: "increase".
       - Use "decrease" for reducing count. Set "quantity" to the number being subtracted.
         Example: "ek ochhu karo" -> quantity: 1, modifier: "decrease".
       - Use "set" for absolute totals. Set "quantity" to the final desired number.
         Example: "be aapo" -> quantity: 2, modifier: "set".
    4. OUT OF STOCK: If user orders an item listed as OUT OF STOCK, apologize warmly in Gujlish and suggest the Alternative.
    5. PERSONA: Respond in natural, polite Gujlish (Gujarati-English).
    
    REQUIRED JSON OUTPUT FORMAT:
    {{
      "items": [
        {{
          "dish": "Samosa", 
          "quantity": 2, 
          "portion": "full", 
          "modifier": "set", // "set", "increase", or "decrease"
          "raw_addons": []
        }}
      ],
      "response_text": "Haan ji, 2 Samosa. Biju kai?",
      "is_finished": false,
      "intent": "none"
    }}
    """

    client = get_llm_client()

    for chunk in chunks:
        preprocessed_text = preprocess_transcript(chunk)
        try:
            completion = client.chat.completions.create(
                model="sarvam-m",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"User Order Chunk:\nOriginal: {chunk}\nPreprocessed: {preprocessed_text}"}
                ],
                response_format={"type": "json_object"},
                temperature=0.1
            )

            text_content = completion.choices[0].message.content
            print(f"DEBUG LLM Raw: {text_content}")
            parsed_data = json.loads(extract_json(text_content))
            
            # Merge results
            extracted_items = parsed_data.get("items", [])
            for item in extracted_items:
                dish = item.get("dish")
                qty = item.get("quantity", 1)
                portion = item.get("portion", "full")
                modifier = item.get("modifier", "set")
                raw_addons = item.get("raw_addons", [])
                
                mapped_dish, dish_score = fuzzy_match_dish(dish)
                
                # Use the new high-performance addon extractor
                structured_addons = extract_addons(" ".join(raw_addons))["addons"]
                
                processed_item = {
                    "dish": mapped_dish.strip() if dish_score > 0.6 else dish.strip(),
                    "quantity": qty,
                    "portion": portion.strip() if portion else "full",
                    "modifier": modifier,
                    "raw_addons": raw_addons,
                    "addons": structured_addons
                }
                final_order_result["items"].append(processed_item)
                
                # Update confirmed dict
                final_order_result["confirmed"][processed_item["dish"]] = {
                    "quantity": qty,
                    "addons": structured_addons
                }

                # Threshold checks
                AUTO_REPLACE_THRESHOLD = 0.85
                CONFIRMATION_THRESHOLD = 0.55
                if dish_score >= CONFIRMATION_THRESHOLD and dish_score < AUTO_REPLACE_THRESHOLD:
                    final_order_result["needs_confirmation"].append({
                        "original": dish,
                        "suggested": mapped_dish,
                        "quantity": qty,
                        "score": round(dish_score, 2),
                        "addons": raw_addons
                    })
                elif dish_score < 0.35:
                    final_order_result["not_in_menu"].append(dish)

            # Global flags
            if parsed_data.get("is_finished"):
                final_order_result["is_finished"] = True
            if parsed_data.get("intent") != "none":
                final_order_result["intent"] = parsed_data.get("intent")
            
            # Concatenate response text politely
            chunk_resp = parsed_data.get("response_text", "").strip()
            if chunk_resp:
                if final_order_result["response_text"]:
                    final_order_result["response_text"] += " " + chunk_resp
                else:
                    final_order_result["response_text"] = chunk_resp
            
            if "language_code" in parsed_data:
                final_order_result["language_code"] = parsed_data["language_code"]

        except Exception as e:
            print(f"ERROR processing chunk '{chunk}': {e}")
            # FALLBACK: Try to extract dish from chunk using fuzzy matching
            preprocessed = preprocess_transcript(chunk)
            words = preprocessed.split()
            # Try to find quantity + dish pattern
            fallback_qty = 1
            fallback_dish_text = preprocessed
            if words and words[0].isdigit():
                fallback_qty = int(words[0])
                fallback_dish_text = " ".join(words[1:])
            
            if fallback_dish_text.strip():
                mapped_dish, score = fuzzy_match_dish(fallback_dish_text.strip())
                if score > 0.5:
                    print(f"DEBUG FALLBACK: Matched '{fallback_dish_text}' -> '{mapped_dish}' (score: {score:.2f})")
                    processed_item = {
                        "dish": mapped_dish.strip(),
                        "quantity": fallback_qty,
                        "portion": "full",
                        "modifier": "set",
                        "raw_addons": []
                    }
                    final_order_result["items"].append(processed_item)
                    final_order_result["confirmed"][processed_item["dish"]] = {
                        "quantity": fallback_qty,
                        "addons": []
                    }
                    
                    if score >= 0.55 and score < 0.85:
                        final_order_result["needs_confirmation"].append({
                            "original": fallback_dish_text.strip(),
                            "suggested": mapped_dish,
                            "quantity": fallback_qty,
                            "score": round(score, 2),
                            "addons": []
                        })
                else:
                    print(f"DEBUG FALLBACK: No match for '{fallback_dish_text}' (score: {score:.2f})")

    return final_order_result

if __name__ == "__main__":
    test_transcripts = [
        "give me teen coffee and char samosa extra spicy",
        "ek masala dosa dungli vagar nu and thodu vadhu tikhu",
        "i want be masala dosa less oil",
        "mujhe gyara biryani chahiye bina lahsun ke",
        "i want some sushi"
    ]
    
    for t in test_transcripts:
        print(f"\n--- Testing: '{t}' ---")
        result = classify_order(t)
        print(json.dumps(result, indent=4))

def refine_addons_with_llm(dish_name: str, current_addons: list, new_transcript: str) -> list:
    """
    Specifically handles modifications/corrections to addons using a targeted LLM prompt.
    Triggered only when correction keywords are detected for an existing item.
    """
    system_prompt = f"""
    You are an expert restaurant order assistant specializing in precision customizations.
    Task: Update the current addons for '{dish_name}' based on the user's new request.
    
    CURRENT ADDONS for {dish_name}:
    {', '.join(current_addons) if current_addons else "None"}

    RULES (STRICT):
    1. REPLACEMENT/SWAP: If you see "instead of X, add Y", "X na badle Y", or "X ni jagyae Y", you MUST REMOVE X from the list and ADD Y. This is a priority rule.
    2. EXPLICIT REMOVAL: If user says "remove X", "X na rakhta", "X vagar", "don't make X", remove X from the list.
    3. ADDITION: If user says "extra X", "Y nakho", "make it Y", add Y to the list.
    4. PRESERVE CATEGORY: Ensure you identify addons correctly regardless of spelling (e.g., 'meethi' and 'mithi' are the same).
    5. NO DUPLICATES: The final list should have unique addon strings.
    6. OUTPUT: Return only the updated JSON list.

    OUTPUT FORMAT:
    {{ "updated_addons": ["addon1", "addon2"] }}
    """
    
    client = get_llm_client()
    try:
        completion = client.chat.completions.create(
            model="sarvam-m",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"New Request for {dish_name}:\n{new_transcript}"}
            ],
            response_format={"type": "json_object"},
            temperature=0.0
        )
        data = json.loads(extract_json(completion.choices[0].message.content))
        return data.get("updated_addons", current_addons)
    except Exception as e:
        print(f"ERROR in refine_addons_with_llm: {e}")
        # Fallback to the existing current_addons if LLM fails
        return current_addons
