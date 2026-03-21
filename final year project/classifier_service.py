import os
import json
import re
from dotenv import load_dotenv
from rapidfuzz import process, fuzz
# from groq import Groq # Moved inside functions or lazy init
# from sentence_transformers import SentenceTransformer, util # Moved inside functions
# import torch # Moved inside functions

load_dotenv()
SARVAM_API_KEY = os.getenv("SARVAM_API_KEY")

if not SARVAM_API_KEY:
    raise ValueError("❌ SARVAM_API_KEY not found in .env")

_sarvam_client = None

def get_sarvam_client():
    global _sarvam_client
    if _sarvam_client is None:
        from sarvamai import SarvamAI
        _sarvam_client = SarvamAI(api_subscription_key=SARVAM_API_KEY)
    return _sarvam_client

def extract_json(text):
    """
    Robustly extract JSON from text that might contain markdown blocks and <think> tags.
    """
    # Remove <think> blocks
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    # Try to find JSON block
    match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if match:
        return match.group(1)
    # If no markdown, try to find the first { and last }
    match = re.search(r'(\{.*\})', text, re.DOTALL)
    if match:
        return match.group(1)
    return text.strip()

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
    "sixty": 60, "saath": 60,
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
    "sau": 100,
}

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

# ADDON CONFIGURATION
try:
    with open("addons.json", "r", encoding="utf-8") as f:
        ADDON_MODIFIERS = json.load(f)
except FileNotFoundError:
    print("WARNING: addons.json not found. Using empty addon dictionary.")
    ADDON_MODIFIERS = {}

# Pre-calculate flattened addon keywords for simpler matching
_ALL_ADDON_KEYWORDS = []
_ADDON_KEYWORD_MAP = {} # Keyword -> Category
for category, details in ADDON_MODIFIERS.items():
    for kw in details["keywords"]:
        _ALL_ADDON_KEYWORDS.append(kw)
        _ADDON_KEYWORD_MAP[kw] = category

# Global variables for Embeddings (Loaded lazily)
model = None
MENU_EMBEDDINGS = None
ADDON_EMBEDDINGS = None

def get_embedding_model():
    """Returns the embedding model and pre-calculated menu and addon embeddings."""
    global model, MENU_EMBEDDINGS, ADDON_EMBEDDINGS
    if model is None:
        print("DEBUG: Loading Embedding Model...")
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer('all-MiniLM-L6-v2')
        # Pre-calculate menu embeddings (lowercase for consistency)
        MENU_EMBEDDINGS = model.encode([m.lower() for m in INDIAN_MENU], convert_to_tensor=True)
        # Pre-calculate addon embeddings
        ADDON_EMBEDDINGS = model.encode([kw.lower() for kw in _ALL_ADDON_KEYWORDS], convert_to_tensor=True)
    return model, MENU_EMBEDDINGS, ADDON_EMBEDDINGS

def match_addon_hybrid(text: str):
    """
    Matches a piece of text (e.g., surrounding a dish) against ADDON_MODIFIERS
    using Hybrid Search (60% Semantic / 40% Fuzzy).
    """
    if not text or not text.strip():
        return None, 0.0

    model, _, addon_embs = get_embedding_model()
    clean_text = re.sub(r'[^a-zA-Z0-9\s]', '', text.lower()).strip()
    
    # 1. Semantic Search
    query_embedding = model.encode(clean_text, convert_to_tensor=True)
    from sentence_transformers import util
    import torch
    cos_scores = util.cos_sim(query_embedding, addon_embs)[0]
    semantic_score, best_idx = torch.max(cos_scores, dim=0)
    semantic_score = float(semantic_score)
    semantic_keyword = _ALL_ADDON_KEYWORDS[best_idx]
    semantic_category = _ADDON_KEYWORD_MAP[semantic_keyword]

    # 2. Keyword Search (Fuzzy) - Lowercase everything for matching
    from rapidfuzz import process, fuzz
    fuzzy_match, fuzzy_score, _ = process.extractOne(clean_text, [kw.lower() for kw in _ALL_ADDON_KEYWORDS], scorer=fuzz.token_set_ratio)
    fuzzy_score = fuzzy_score / 100.0
    fuzzy_category = _ADDON_KEYWORD_MAP.get(fuzzy_match, _ADDON_KEYWORD_MAP.get(fuzzy_match.title(), "unknown"))

    # 3. Hybrid Calculation
    # If they agree on category, simple weighted average
    if semantic_category == fuzzy_category:
        hybrid_score = (semantic_score * 0.6) + (fuzzy_score * 0.4)
        return semantic_category, hybrid_score
    else:
        # If they disagree, prefer semantic but check if fuzzy is very strong
        if fuzzy_score > 0.95:
            return fuzzy_category, (fuzzy_score * 0.6) + (semantic_score * 0.4)
        return semantic_category, (semantic_score * 0.6) + (fuzzy_score * 0.4)

def match_dish_with_embeddings(dish_name: str):
    """
    Matches a dish name against INDIAN_MENU using a Hybrid approach:
    60% SentenceTransformers (Meaning) + 40% RapidFuzz (Keywords).
    Returns (matched_item, hybrid_score).
    """
    if not dish_name:
        return None, 0.0
    
    # Ensure model and embeddings are loaded
    model, menu_embs, _ = get_embedding_model()
    
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

def classify_order(transcript: str):
    """
    Classifies a voice order transcript into a structured JSON format 
    identifying dishes, their quantities, and any addon modifiers (extra spicy, etc.).
    """
    if not transcript.strip():
        return {}

    # Preprocess transcript to resolve number words
    preprocessed_text = preprocess_transcript(transcript)
    print(f"DEBUG: Preprocessed Transcript: {preprocessed_text}")

    # Generate a string description of addons for the LLM
    addon_context = ""
    for category, details in ADDON_MODIFIERS.items():
        addon_context += f"- {category}: {details['meaning']} (Keywords: {', '.join(details['keywords'][:5])}...)\n"

    system_prompt = f"""
    You are a professional restaurant ordering assistant. 
    Your task is to take a transcript of a customer's voice order and 
    extract the dishes, their quantities, and any specific customizations (addons).

    AVAILABLE ADDON CATEGORIES:
    {addon_context}

    ITEM SEPARATORS (Words indicating the start of a NEW dish):
    Gujarati: ane, sathe (if it has quantity), jode, beju, pachi, plus, ane biju
    Hindi: aur, and, saath (if it has quantity), phir, dusra, plus, aur ek
    English: and, plus, also, then, with (if it has quantity), another

    ADDON INDICATORS (Words meaning "with" or customization):
    Gujarati: sathe, jode, sathe aapo, sathe aapjo, sathe mukjo, sathe rakho, sathe aapvu, sathe pan aapo, sathe pan mukjo, sathe add karo, sathe lai aavo, sathe serve karo, sathe muki do, sathe pan aapjo, sathe pan moklo
    Hindi: ke saath, saath mein, saath, iske saath, iske saath dena, saath mein dena, saath mein laana, saath mein daalna, saath mein bhejna, iske saath bhi, saath mein jodo, saath mein laga do, saath mein rakho, saath mein serve karo
    English: with, along with, together with, serve with, add with, include with, give with, bring with, send with, pair with, served with, side with, with extra, with side, with topping

    CRITICAL RULES (STRICT ADHERENCE REQUIRED):
    1. NEVER TRANSLATE ANY WORD INTO ENGLISH. If the user speaks in Gujarati, Hindi, or any other language, you MUST keep the dish name and the raw_addons EXACTLY as they appear in the transcript.
    2. DO NOT "CORRECT" OR "ALIENATE" THE LANGUAGE. If the user says "tikhu", do not write "spicy". If the user says "dungli", do not write "onion".
    3. THE ONLY PART THAT SHOULD BE ENGLISH IS THE JSON KEYS ("dish", "quantity", "raw_addons").
    4. SEPARATE CUSTOMIZATION FROM DISH: The pattern is usually [Dish Name] -> [Add-on/Modifier]. For example, "biryani ma thodu vadhu tikhu rakho", the dish is "biryani" and the addon phrase "thodu vadhu tikhu" goes into "raw_addons".
    5. MULTIPLE ITEMS: If you see "ITEM SEPARATORS" (like "ane", "aur", "and", "plus"), the words following them are usually a NEW DISH, not an addon. 
       - ESPECIALLY if the following words contain a QUANTITY (e.g., "10 nan"), it MUST be treated as a separate dish.
    6. ADDON INDICATORS: If you see any of the "ADDON INDICATORS" (e.g., "sathe", "ke saath", "with"), AND it DOES NOT have a quantity following it, then the phrase following it is an addon.
    7. DISHES LIKE NAAN/ROTI: "Naan", "Roti", "Papad", "Chai" are almost always SEPARATE DISHES, not addons. Even if someone says "Curry sathe 2 Pan Naan", the "2 Pan Naan" is a separate item.
    8. CONTEXTUAL MODIFICATIONS MUST MERGE: If a user mentions the same dish multiple times specifically to add a modifier to it (e.g. "masala dosa... masala dosa thoda tikka rakhjo"), DO NOT increase the quantity. Instead, merge the modifier into the initial dish object and keep the quantity as 1.
    9. Output ONLY a clean JSON object with the following structure:
       {{
         "items": [
           {{"dish": "string", "quantity": integer, "raw_addons": ["string"]}}
         ],
         "is_finished": boolean (default false),
         "intent": "affirmative" | "negative" | null (default null),
         "response_text": "string",
         "language_code": "hi-IN" | "gu-IN" | "en-IN" | "mr-IN" | "ta-IN" | etc.
       }}
    
    10. Rules for Fields:
        - "items": List of dishes extracted.
        - "dish": string (EXACTLY from transcript, PRESERVE Gujarati/Hindi, NO TRANSLATION)
        - "quantity": integer (default 1)
        - "raw_addons": list of strings (phrases used for customization from transcript, EXACTLY as spoken, PRESERVE Gujarati/Hindi, NO TRANSLATION)
        - "is_finished": true only if "done", "bus", etc. detected.
        - "intent": "affirmative" if "yes", "haan" etc. detected; "negative" if "no", "nahi" etc. detected.
        - "response_text": A friendly, concierge-like response from 'Pooja' in the SAME language as the transcript. (e.g., "Theek hai, aapka order..." or "Saru, tamaro order...").
        - "language_code": The Sarvam AI language code for the transcript (gu-IN for Gujarati, hi-IN for Hindi, en-IN for English, mr-IN for Marathi).

    EXAMPLES (STUDY THESE CAREFULLY):
    - [Transcript]: "ek masala dosa dungli vagar nu and thodu vadhu tikhu"
      [Correct Output]: {{"items": [{{"dish": "masala dosa", "quantity": 1, "raw_addons": ["dungli vagar nu", "thodu vadhu tikhu"]}}]}}
    
    - [Transcript]: "paneer tikka sathe extra chutney aapjo"
      [Correct Output]: {{"items": [{{"dish": "paneer tikka", "quantity": 1, "raw_addons": ["extra chutney aapjo"]}}]}}
    
    - [Transcript]: "Mohan Josh ane 10 Nan"
      [Correct Output]: {{"items": [{{"dish": "Mohan Josh", "quantity": 1, "raw_addons": []}}, {{"dish": "Nan", "quantity": 10, "raw_addons": []}}]}}
    10. SUB-ITEMS AS ADDONS: Items like 'Bhature', 'Pav', 'Puri', 'Sambar', 'Chutney', 'Papad', 'Raita' are often components of other dishes. If they are mentioned immediately AFTER a main dish (like Chole Bhature, Pav Bhaji, etc.), extract them in the `raw_addons` of that main dish, even if they have a quantity.
        - Example: "Chole Bhature ane ek Bhature" -> dish: "Chole Bhature", raw_addons: ["ek Bhature"]
        - Example: "Pav Bhaji sathe 2 Pav" -> dish: "Pav Bhaji", raw_addons: ["2 Pav"]

    11. FINISHING INTENT: Detect if the user is finished with the entire order. 
        - Indicators: "done", "ok", "bus", "ajj", "bas", "bas itna hi", "bas ho gaya", "finish", "no more", "itna hi chahiye".
        - If detected, set a top-level boolean key "is_finished" to true.

    12. CONFIRMATION INTENT: Detect if the user is saying "yes" or "no" to a previous question.
        - Yes Indicators: "yes", "ha", "haan", "haji", "ok", "theek hai", "sahi hai", "correct", "yep", "yeah".
        - No Indicators: "no", "nahi", "na", "naji", "galat", "wrong", "nope".
        - If "yes" detected, set "intent" to "affirmative". If "no", set "intent" to "negative".

    13. PERSONA (POOJA): You are Pooja, a warm and efficient restaurant concierge. Speak naturally and politely.

    CRITICAL: ALWAYS extract the QUANTITY as a separate integer. NEVER include "10", "one", "ek", etc. in the "dish" string.
    """

    AUTO_REPLACE_THRESHOLD = 0.85
    CONFIRMATION_THRESHOLD = 0.55
    ADDON_THRESHOLD = 0.70

    client = get_sarvam_client()
    try:
        response = client.chat.completions(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Original: {transcript}\nPreprocessed: {preprocessed_text}"}
            ],
            temperature=0
        )

        result_content = response.choices[0].message.content
        # Extract JSON from potential <think> or ``` markdown blocks
        clean_json = extract_json(result_content)
        parsed_data = json.loads(clean_json)
        extracted_data = parsed_data.get("items", [])
        is_finished = parsed_data.get("is_finished", False)
        intent = parsed_data.get("intent", None)
        
        final_order_result = {
            "confirmed": {},
            "needs_confirmation": [],
            "not_in_menu": [],
            "is_finished": is_finished,
            "intent": intent
        }

        for item in extracted_data:
            dish = item.get("dish")
            qty = item.get("quantity", 1)
            raw_addons = item.get("raw_addons", [])
            
            # Match Dish
            mapped_dish, dish_score = fuzzy_match_dish(dish)
            
            # Allow ALL addons extracted by the LLM
            processed_addons = raw_addons

            item_details = {
                "quantity": qty,
                "addons": list(set(processed_addons))
            }

            if dish_score >= AUTO_REPLACE_THRESHOLD:
                if mapped_dish in final_order_result["confirmed"]:
                    final_order_result["confirmed"][mapped_dish]["quantity"] += qty
                    # Merge addons if needed, here we just extend
                    final_order_result["confirmed"][mapped_dish]["addons"] = list(set(final_order_result["confirmed"][mapped_dish]["addons"] + item_details["addons"]))
                else:
                    final_order_result["confirmed"][mapped_dish] = item_details
                print(f"DEBUG: Auto-matched '{dish}' -> '{mapped_dish}' (Score: {dish_score:.2f}) with Addons: {processed_addons}")
            
            elif dish_score >= CONFIRMATION_THRESHOLD:
                final_order_result["needs_confirmation"].append({
                    "original": dish,
                    "suggested": mapped_dish,
                    "quantity": qty,
                    "score": round(dish_score, 2),
                    "addons": item_details["addons"]
                })
                print(f"DEBUG: Needs confirmation '{dish}' -> '{mapped_dish}'? (Score: {dish_score:.2f})")
            
            else:
                final_order_result["not_in_menu"].append(dish)
                print(f"DEBUG: Not in menu: '{dish}' (Score: {dish_score:.2f})")
            
        return final_order_result

    except Exception as e:
        print(f"ERROR: Groq Classification Error: {e}")
        return {"error": str(e), "confirmed": {}, "needs_confirmation": [], "not_in_menu": []}

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
