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
        _gemini_model = genai.Client(api_key=GEMINI_API_KEY)
    return _gemini_model

def extract_json(text):
    """
    Robustly extract JSON from text that might contain markdown blocks and <think> tags.
    Handles common LLM mistakes like trailing commas and unclosed reasoning blocks.
    """
    if not text:
        return ""
        
    # 1. Remove <think> blocks
    # Handle closed tags
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    # Handle unclosed tags (Sarvam-m sometimes cuts off)
    text = re.sub(r'<think>.*', '', text, flags=re.DOTALL)
    
    # 2. Try to find JSON block in markdown
    match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if match:
        text = match.group(1)
    else:
        # 3. If no markdown, find the first '{'/'[' and last '}'/']'
        # Use a more careful approach to handle trailing hallucinations
        brace_start = text.find('{')
        bracket_start = text.find('[')
        
        start_idx = -1
        if brace_start != -1 and bracket_start != -1:
            start_idx = min(brace_start, bracket_start)
        else:
            start_idx = brace_start if brace_start != -1 else bracket_start
            
        if start_idx != -1:
            # Find the last brace/bracket that might be part of the actual JSON
            # instead of blindly taking the last character of the string
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
    # Remove trailing commas before closing braces/brackets
    text = re.sub(r',\s*([\]}])', r'\1', text)
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
# INTENT_MAP = {
#     "affirmative": [
#         "yes", "yeah", "yep", "yup", "sure", "ok", "okay", "ha", "haan", "theek hai", "thek hai", "ji", "chalshe", "chalse", "kar do", "thik che", "thik chhe"
#     ],
#     "negative": [
#         "no", "nope", "not that", "nahi", "na", "nathi", "nathi joitu", "nako", "nai"
#     ],
#     "finishing": [
#         "done", "finished", "that's it", "bus", "bas", "bas itna hi", "itna hi dena", "itlu j", "pachi nai", "bas avu j", "order confirm"
#     ]
# }


def detect_intent(transcript: str):
    """
    Disabled local detection for transition to unified LLM intent detection.
    Always returns (None, 0).
    """
    return None, 0

# ORIGINAL detect_intent implementation (Commented out)
# def detect_intent(transcript: str):
#     """
#     Identifies if a short transcript matches a common intent (affirmative, negative, finishing)
#     using keyword matching. Returns (intent_name, confidence) or (None, 0).
#     """
#     if not transcript or len(transcript.split()) > 4: # Only for short responses
#         return None, 0
#     
#     transcript = re.sub(r'[^a-zA-Z0-9\s]', '', transcript.lower().strip())
#     
#     for intent, keywords in INTENT_MAP.items():
#         # Exact match
#         if transcript in keywords:
#             return intent, 1.0
#         
#         # Fuzzy match for typos
#         from rapidfuzz import process, fuzz
#         match = process.extractOne(transcript, keywords, scorer=fuzz.ratio)
#         if match and match[1] > 80:
#             return intent, 0.9
# 
#     return None, 0


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

# Global variables for Hybrid Matching State (Loaded once)
_model = None
_MENU_EMBEDDINGS = None
_KEYWORD_MAP = {} # token -> set of menu items
_INITIALIZED = False

def _initialize_hybrid_matching():
    """Builds keyword map and pre-calculates embeddings from INDIAN_MENU."""
    global _model, _MENU_EMBEDDINGS, _KEYWORD_MAP, _INITIALIZED
    if _INITIALIZED: return 
    
    print("DEBUG: Initializing Hybrid Matching System...")
    from sentence_transformers import SentenceTransformer
    _model = SentenceTransformer('all-MiniLM-L6-v2')
    
    menu_lower = [m.lower() for m in INDIAN_MENU]
    _MENU_EMBEDDINGS = _model.encode(menu_lower, convert_to_tensor=True)
    
    # Build Keyword Map
    stop_words = {"the", "a", "an", "and", "or", "for", "with", "of", "extra", "no", "add"}
    synonyms = {
        "dosa": ["dosai", "dose", "crepe"],
        "chai": ["tea", "chay", "cutting"],
        "coffee": ["kafi"],
        "bhature": ["bature"],
        "samosa": ["shamosa"],
        "jamun": ["jambu", "jamoon"]
    }
    
    for dish in INDIAN_MENU:
        d_lower = dish.lower().strip()
        # Clean text
        name_clean = re.sub(r'[^a-zA-Z0-9\s]', '', d_lower)
        tokens = name_clean.split()
        
        # 1. Full name as keyword
        clean_full = " ".join(tokens)
        if clean_full not in _KEYWORD_MAP: _KEYWORD_MAP[clean_full] = set()
        _KEYWORD_MAP[clean_full].add(dish)
        
        # 2. Individual tokens and their synonyms
        for t in tokens:
            if t not in stop_words and len(t) > 2:
                if t not in _KEYWORD_MAP: _KEYWORD_MAP[t] = set()
                _KEYWORD_MAP[t].add(dish)
                # Map synonyms too
                if t in synonyms:
                    for syn in synonyms[t]:
                        if syn not in _KEYWORD_MAP: _KEYWORD_MAP[syn] = set()
                        _KEYWORD_MAP[syn].add(dish)

        # 3. Bigrams for multi-word items
        if len(tokens) >= 2:
            for i in range(len(tokens) - 1):
                bigram = f"{tokens[i]} {tokens[i+1]}"
                if bigram not in _KEYWORD_MAP: _KEYWORD_MAP[bigram] = set()
                _KEYWORD_MAP[bigram].add(dish)
                
    _INITIALIZED = True
    print(f"DEBUG: Hybrid System Initialized. Keyword map size: {len(_KEYWORD_MAP)}")

# Eager initialization to avoid first-request lag
_initialize_hybrid_matching()

def match_dish_with_embeddings(dish_name: str):
    """
    Tiered Hybrid Matcher:
    Step 1: O(1) Token/Keyword Lookup (Fast)
    Step 2: Semantic Similarity Fallback (Smart)
    Step 3: Fuzzy Guard (Robust)
    """
    if not dish_name:
        return None, 0.0, False
    
    start_time = time.perf_counter()
    clean_name = re.sub(r'[^a-zA-Z0-9\s]', '', dish_name).lower().strip()
    if not clean_name:
        return None, 0.0, False

    # --- Phase 1: Fast Token/Keyword Match ---
    candidates = set()
    input_tokens = clean_name.split()
    
    # Check full phrase first
    if clean_name in _KEYWORD_MAP:
        candidates.update(_KEYWORD_MAP[clean_name])
    
    # Check individual tokens
    for t in input_tokens:
        if t in _KEYWORD_MAP:
            candidates.update(_KEYWORD_MAP[t])
            
    if candidates and len(candidates) == 1:
        # Unique hit from keywords
        match = list(candidates)[0]
        
        # --- NEW: Partial Match Check ---
        # If user said 1 word but dish has 2+ words, force confirmation
        match_tokens = re.sub(r'[^a-zA-Z0-9\s]', '', match).lower().split()
        is_partial = len(input_tokens) < len(match_tokens)
        
        end_time = time.perf_counter()
        if is_partial:
            print(f"DEBUG: [AMBIGUOUS] Partial Keyword Match Hit in {(end_time - start_time)*1000:.2f}ms! '{dish_name}' -> '{match}'")
            return match, 0.82, True # Explicitly flag as ambiguous and slightly lower score
        else:
            print(f"DEBUG: [TIME] Perfect Keyword Match Hit in {(end_time - start_time)*1000:.2f}ms! '{dish_name}' -> '{match}'")
            return match, 1.0, False

    # --- Phase 2: Semantic Similarity Fallback ---
    # Triggered if no unique keyword match or input is descriptive
    query_emb = _model.encode(clean_name, convert_to_tensor=True)
    from sentence_transformers import util
    import torch
    
    cos_scores = util.cos_sim(query_emb, _MENU_EMBEDDINGS)[0]
    top_v, top_i = torch.topk(cos_scores, k=min(3, len(INDIAN_MENU)))
    
    semantic_match = INDIAN_MENU[int(top_i[0])]
    semantic_score = float(top_v[0])
    
    is_ambiguous = False
    if len(top_v) > 1:
        # If second best is within 0.05 of the best
        if (float(top_v[0]) - float(top_v[1])) < 0.05 and float(top_v[0]) > 0.40:
            is_ambiguous = True

    # --- Decision Engine ---
    # Force ambiguity if input is partial (e.g. 1 word matching 2+ words)
    match_tokens = re.sub(r'[^a-zA-Z0-9\s]', '', semantic_match).lower().split()
    if len(input_tokens) < len(match_tokens) and len(input_tokens) == 1:
        is_ambiguous = True

    # --- NEW: Semantic Early Stop ---
    # User requested: "if we get the semantic phase >80 still skip that part"
    if semantic_score > 0.8 and not is_ambiguous:
        print(f"DEBUG: Semantic Early Stop! '{dish_name}' -> '{semantic_match}' (Score: {semantic_score:.2f})")
        return semantic_match, semantic_score, False

    # --- Phase 3: Fuzzy Match Guard ---
    from rapidfuzz import process, fuzz
    menu_lower = [m.lower() for m in INDIAN_MENU]
    fuzzy_results = process.extract(clean_name, menu_lower, scorer=fuzz.token_set_ratio, limit=2)
    
    fuzzy_match = INDIAN_MENU[fuzzy_results[0][2]]
    fuzzy_score = fuzzy_results[0][1] / 100.0
    
    if len(fuzzy_results) > 1:
        if (fuzzy_results[0][1] - fuzzy_results[1][1]) < 7 and fuzzy_results[0][1] > 40:
            is_ambiguous = True

    # --- Decision Engine ---
    # User requested: "take the highest of which is the confidence"
    # We compare Semantic and Fuzzy scores and take the best one.
    if fuzzy_score > semantic_score:
        final_match = fuzzy_match
        hybrid_score = fuzzy_score
    else:
        final_match = semantic_match
        hybrid_score = semantic_score

    # Force ambiguity if top matches disagree but both are reasonably strong
    if semantic_match != fuzzy_match and semantic_score > 0.70 and fuzzy_score > 0.70:
        is_ambiguous = True

    end_time = time.perf_counter()
    print(f"DEBUG: [TIME] Hybrid Match (Semantic/Fuzzy) in {(end_time - start_time)*1000:.2f}ms for '{dish_name}'")
    print(f"DEBUG: Hybrid Pipeline result: {final_match} ({hybrid_score:.2f})")
    return final_match, hybrid_score, is_ambiguous

def fuzzy_match_dish(dish_name: str):
    """
    Primary matching function using the Hybrid approach.
    """
    return match_dish_with_embeddings(dish_name)

# Pre-defined Response Schema for Order Classification (Updated)
CLASSIFICATION_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "intent": {"type": "STRING", "enum": ["new_order", "modify_order", "affirmative", "negative", "finishing", "recommendation", "question", "none"], "description": "Type of intent extracted"},
        "items": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "name": {"type": "STRING", "description": "Standardized dish name"},
                    "quantity": {"type": "INTEGER", "description": "Number of units"},
                    "addons": {
                        "type": "ARRAY",
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "type": {"type": "STRING", "description": "e.g., butter, cheese, spicy"},
                                "value": {"type": "STRING", "description": "e.g., extra, less, remove"}
                            },
                            "required": ["type", "value"]
                        }
                    }
                },
                "required": ["name", "quantity", "addons"]
            }
        },
        "modifications": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "target_item": {"type": "STRING", "description": "Dish being modified"},
                    "action": {"type": "STRING", "enum": ["add", "remove", "update", "replace", "split_customization"], "description": "Type of modification"},
                    "changes": {
                        "type": "ARRAY",
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "type": {"type": "STRING"},
                                "value": {"type": "STRING"}
                            },
                            "required": ["type", "value"]
                        }
                    }
                },
                "required": ["target_item", "action", "changes"]
            }
        }
    },
    "required": ["intent", "items", "modifications"]
}


async def classify_order(transcript: str, current_order_summary: str = "Order is empty", history: list = None):
    from correction_service import get_correction_hints

    """
    Classifies a voice order transcript into a structured JSON format.
    Uses a single LLM pass for maximum speed.
    """
    if not transcript or not transcript.strip():
        return {}

    client = get_llm_client()
    # Fetch current inventory status to inform the LLM
    inventory_summary = inventory_service.get_inventory_summary()

    categories_summary = "\n".join([f"- {cat}: {', '.join(dishes)}" for cat, dishes in MENU_CATEGORIES.items()])

    # Unified System Prompt based on user requirements
    system_prompt_template = """
🎯 SYSTEM PROMPT: Multilingual Indian Food Voice Agent

You are an intelligent voice-based restaurant ordering assistant designed for Indian users. Your primary goal is to accurately understand customer orders, answer general restaurant questions, and provide smart recommendations based on the menu and conversation history.

---

### 🏛️ RESTAURANT INFORMATION
{RESTAURANT_INFO}

---

### 🥣 MENU CATEGORIES & RECOMMENDATIONS
{MENU_CATEGORIES}

---

### 🕒 CONVERSATION HISTORY (Last 10 turns)
{CONVERSATION_HISTORY}

---

### 🧠 Core Capabilities
You are an intelligent Indian restaurant voice-ordering assistant.

Your job is to:

* Understand customer questions and food preferences naturally.
* Recommend dishes from the provided menu.
* Handle multilingual conversations (English, Hindi, Gujarati, Hinglish).
* Suggest items based on cuisine type, meal time, taste preferences, and conversation history.
* Act like a polite, smart Indian waiter.

---

# 🍽 MENU DATA

Use ONLY the dishes available inside:
{MENU_CATEGORIES}

Never invent dishes that are not present in the menu.

---

# 📦 INVENTORY & STOCK RULES

Use stock data to determine availability.

If a customer orders an OUT OF STOCK item:

1. Politely apologize.
2. Inform them the item is unavailable.
3. Suggest the exact alternative provided in stock rules.
4. If no alternative exists:

   * Recommend a similar item from the SAME category or cuisine.
   * Prefer items with similar taste/profile.

Example:
User: "Paneer Tikka"
If out of stock:
"Sorry sir, Paneer Tikka currently unavailable che. Tame Paneer Malai Tikka try karso? E pan customer favorite che."

---

# 🧠 RECOMMENDATION LOGIC

## 1. Cuisine-Based Recommendations

If the user asks for a regional cuisine, identify dishes from that cuisine category inside the menu and recommend ONLY matching dishes.

Examples:

* "Gujarati food"
* "Punjabi dishes"
* "South Indian breakfast"
* "Chinese starter"
* "Kathiyawadi"
* "Jain food"

Steps:

1. Detect cuisine/region.
2. Search menu for matching dishes.
3. Recommend best matching items.
4. If no exact match exists:

   * Recommend closest available cuisine.
   * Mention politely.

Example:
User: "Punjabi ma su che?"
Response:
"Punjabi ma Amritsari Kulcha, Paneer Butter Masala ane Dal Makhani available che."

---

## 2. Meal-Time Recommendations

Recommend based on time context:

Breakfast:

* Dosa
* Idli
* Poha
* Sandwich
* Tea/Coffee

Lunch/Dinner:

* Thali
* Sabji
* Roti
* Rice
* Punjabi dishes

Snacks:

* Chaat
* Sandwich
* Fries
* Pav Bhaji

Desserts:

* Ice Cream
* Gulab Jamun
* Brownie

---

## 3. Preference-Based Recommendations

Use conversation history and keywords.

Examples:

* spicy
* less spicy
* Jain
* healthy
* cheesy
* kids food
* protein rich
* veg/non-veg
* light food
* street food

Example:
User: "Something spicy"
Recommend spicy dishes from menu.

User: "Healthy breakfast"
Recommend lighter items.

---

## 4. Smart Upselling

If appropriate, suggest:

* beverages
* desserts
* combos
* add-ons

Example:
"Tamari pasta sathe garlic bread ane cold coffee pan sari jase."

Do NOT oversell aggressively.

---

# 🌐 LANGUAGE HANDLING

Detect and respond in the user's language automatically.

Supported:

* English → en-IN
* Hindi → hi-IN
* Gujarati → gu-IN
* Hinglish → mixed Hindi-English
* Gujarati-English mixed

Always keep tone natural and conversational.

Examples:

* "Su recommend karso?"
* "Kuch spicy batao"
* "South Indian breakfast hai?"

---

# 💬 CONVERSATIONAL STYLE

Behavior should feel like:

* Friendly Indian waiter
* Natural
* Polite
* Quick
* Helpful

Avoid robotic responses.

Use natural phrases:

* "Aap try kar sakte ho"
* "Customer favorite hai"
* "Freshly bana che"
* "Ye kaafi popular item hai"

---

# 🧾 OUTPUT FORMAT

Always return STRICT JSON.

Format:
{
"intent": "",
"items": [],
"modifications": [],
"response_text": "",
"language_code": ""
}

---

# 🎯 INTENT RULES

Use these intents:

## "order"

When customer is placing or modifying an order.

Examples:

* "1 dosa"
* "Add coke"
* "Remove onion"

---

## "recommendation"

When customer asks:

* suggestions
* menu options
* cuisine recommendations
* best sellers
* meal ideas
* what is available

Examples:

* "What do you have for breakfast?"
* "Punjabi ma su che?"
* "Recommend something spicy"

---

## "question"

For general restaurant questions.

Examples:

* opening hours
* delivery time
* address
* payment methods

---

# 🧠 IMPORTANT RULES

* NEVER hallucinate dishes.
* ONLY use menu data.
* If cuisine requested is unavailable:
  politely suggest closest alternatives.
* Keep responses concise but useful.
* Prefer top-selling or signature dishes while recommending.
* Use conversational Indian tone.
* Understand spelling mistakes and speech-to-text errors.
* Understand Indian food pronunciations.

Examples:

* "pav bhajji"
* "panir"
* "manchuriyan"
* "dhosa"

should still work.

---

# 📌 EXAMPLES

Example 1:
User: "Gujarati food ma su recommend karso?"

Output:
{
"intent": "recommendation",
"items": [],
"modifications": [],
"response_text": "Gujarati ma ame Kathiyawadi Thali, Sev Tameta ane Bajra Rotla recommend kariye chhiye. Kathiyawadi Thali customer favorite che.",
"language_code": "gu-IN"
}

---

Example 2:
User: "Something spicy in Punjabi"

Output:
{
"intent": "recommendation",
"items": [],
"modifications": [],
"response_text": "Spicy Punjabi ma tame Paneer Tikka Masala ane Kolhapuri Sabji try kari sako. Banney flavorful ane spicy che.",
"language_code": "en-IN"
}

---

Example 3:
User: "Breakfast me kya hai?"

Output:
{
"intent": "recommendation",
"items": [],
"modifications": [],
"response_text": "Breakfast me Masala Dosa, Idli, Medu Vada aur Poha available hai. Masala Dosa kaafi popular hai.",
"language_code": "hi-IN"
}


#### 1. 🌐 Language Detection & Single-Language Response
- **DETECT**: For every input, identify the user's primary language (Hindi, Gujarati, or English).
- **STICK**: Respond ONLY in that detected language. 
- **NO TRANSLATION**: Never translate between languages. If the user speaks Gujarati, the `response_text` must be in Gujarati/Gujlish only.
- **NO TRILINGUAL OUTPUT**: Never include multiple language versions in your JSON (e.g., don't use keys like "hindi", "gujarati"). Use the standard `response_text` field only.
- **LANGUAGE CODE**: Set the `language_code` appropriately (`gu-IN`, `hi-IN`, or `en-IN`).

#### 🚫 STRICT STATE-AWARENESS RULE 🚫
- **BEFORE MODIFYING ADDONS**, check the `Current Order Summary`.
- **REMOVE/CANCEL**: If a user asks to "remove/cancel X", only output a modification if "X" is currently in the order. If it's not there, ignore the removal but acknowledge it politely.
- **ADD vs UPDATE**: If the user says "more X" or "add X", check if it's already there. If yes, use `action: "update"` with `changes: {"X": "increase"}`. If no, use `action: "add"` or include it in `items`.
- **CRITICAL**: If a user says "remove X" for an addon, YOU MUST find the corresponding dish in the current order and set its addon to "remove" (e.g., target_item: "Dosa", changes: {"chutney": "remove"}). NEVER use an addon name as the 'target_item'.

#### 🚫 NO DUPLICATE WITHOUT EXPLICIT INTENT 🚫
- If a dish is already in the `Current Order Summary`, mentioning its name again **WITHOUT** explicit addition words (like "one more", "another", "plus", "extra plate", "ek biju", "phir se", "aur ek") must **NEVER** result in a new item in the `items` list.
- **EXAMPLE**: If order has "1x Masala Dosa" and user says "Masala Dosa butter vadhu", the output should have `items: []` and a `modification` for the existing Dosa.
- **ONLY** add to `items` if they say "One more Masala Dosa" or "Ek bija Masala Dosa add karo".

AVAILABLE MENU:
{AVAILABLE_MENU}

INVENTORY STATUS:
{INVENTORY_STATUS}

---

### 🏛️ 8. Intent Understanding Examples

#### Case A: New Order (Split Customization)
Input: "2 dosa, ek ma butter vadhu ane bijama cheese add karo"
Output: {
  "intent": "new_order",
  "items": [
    { "name": "Masala Dosa", "quantity": 1, "addons": [{ "type": "butter", "value": "increase" }] },
    { "name": "Masala Dosa", "quantity": 1, "addons": [{ "type": "cheese", "value": "extra" }] }
  ],
  "response_text": "Saras! Be dosa, ek ma butter vadhu ane bijama cheese. Bijikoi seva?",
  "language_code": "gu-IN"
}

#### Case B: Modification (Replacement)
Input: "Paneer tikka nahi, paneer butter masala kar do aur cheese extra"
Output: {
  "intent": "modify_order",
  "modifications": [
    { "target_item": "Paneer Tikka", "action": "remove", "changes": [] },
    { "target_item": "Paneer Butter Masala", "action": "add", "changes": [{ "type": "cheese", "value": "extra" }, { "type": "quantity", "value": "1" }] }
  ],
  "response_text": "Theek hai, Paneer Tikka hata diya hai aur Paneer Butter Masala with extra cheese add kar diya hai.",
  "language_code": "hi-IN"
}

#### Case C: Relative Quantity / Addon Update
Input: "Ek plate more spicy"
Output: {
  "intent": "modify_order",
  "modifications": [
    { "target_item": "last_item", "action": "update", "changes": [{ "type": "spicy", "value": "increase" }] }
  ],
  "response_text": "Done! Thodu vadhu spicy banavi daish.",
  "language_code": "gu-IN"
}

---

### 🍽️ 2. Dish Recognition
* Identify dish names even with misspellings or regional pronunciations.
Map all inputs to a standardized menu item name from the AVAILABLE MENU above.

---

### ➕ 3. Add-on / Customization Extraction
Extract modifications (addons) from user input.
- Common Addons: "butter", "cheese", "spicy", "sambar", "chutney", "ghee", "papad", "salad", "extra"
- Quantity changes: "extra", "double", "more", "vadhu", "zyada"
- Reduction: "less", "light", "ocha", "kam"
- Removal: "no", "without", "nahi", "vina"
- **CRITICAL RULE**: If a user says "remove X" for an addon, YOU MUST find the corresponding dish in the current order and set its addon to "remove" (e.g., target_item: "Dosa", changes: {"chutney": "remove"}). NEVER use an addon as the 'target_item'.

---

### 🔁 4. Change / Correction Intent Detection
Detect when the user wants to modify an already placed order.
Keywords indicating change:
    - English: change, replace, update, instead, remove, cancel, take out
    - Hindi: badal do, change karo, hatao, nikal do, cancel kar do, nahi chahiye, mat rakho
    - Gujarati: badli do, hataavi do, ni jagya, ni jagyae, ni badle, na badle, kadh do, kadhi nakho, nathi joitu, rehva do

#### 🚫 STRICT REMOVAL RULE 🚫
- If the user uses phrases like "Ena thi..." (From that...), "From the order...", or "Vela ma thi...", it indicates they are modifying the **Current Order Summary**.
- **REMOVAL INTENT**: If the user says "X kadh do", "X hatao", or "remove X", you MUST add X to the `modifications` list with `action: "remove"`. 
- **DO NOT** add the removed item to the `items` list.
- **EXAMPLE**: "Ena thi ek samosa kadh do" -> modifications: [{"target_item": "Samosa", "action": "remove", "changes": {}}], items: [].

---

### 🔢 5. Quantity Extraction
- Detect numeric quantities in all formats: "2", "two", "do", "be", "ek", "1 plate"
- Default quantity = 1 if not specified

---

### 🧾 6. Structured Output Format (MANDATORY)
Always return output in JSON format:
{
  "intent": "new_order | modify_order | affirmative | negative | finishing",
  "items": [ ... ],
  "modifications": [ ... ],
  "response_text": "Warm and efficient concierge response (Hinglish/Gujlish).",
  "language_code": "hi-IN | gu-IN",
  "is_finished": false
}

---

### ⚠️ INVENTORY & STOCK RULES
1. **CHECK INVENTORY STATUS**: Before generating the `response_text`, check the `INVENTORY STATUS` provided above.
2. **OUT OF STOCK**: If a customer orders an item that is listed as OUT OF STOCK in the `INVENTORY STATUS`:
    - **APOLOGIZE**: Start your response by apologizing in the user's language (e.g., "Sorry sir", "Maaf karjo").
    - **INFORM**: State clearly that the item is currently not available.
    - **RECOMMEND**: Suggest the specific **alternative** listed for that item in the status.
    - **DO NOT CONFIRM**: Do not say you are adding it.
3. **IN STOCK**: If the item is in stock, proceed normally.

---

---

### ⚠️ 7. Important Rules
- Always normalize dish names to menu-friendly format
- **STRICT ITEM RULE:** Any item mentioned as the "final choice" in the current transcript MUST be included in the `items` list.
- **HISTORY REPLACEMENT RULE:** If a user replaces an item that is ALREADY in the *Current Order Summary* with a new item (e.g., "Remove A and add B instead", "A ni jagya B karo", "A ki jagah B"), you MUST:
    1. Add the removal of A to the `modifications` list.
    2. Add the new item B to the `items` list.
- **Instant Self-Correction:** If a user mentions an item but immediately negates/cancels it in the *same* transcript (e.g., "Butter chicken... no wait, Chole Bhature"), the final intended item (Chole Bhature) MUST go into the `items` list. DO NOT put new items from the current transcript into the `modifications` list.
- **Modifications vs Items:** Use `modifications` ONLY for changes to items that already exist in the *Current Order Summary* (previous history). 
- Do NOT ask questions unless absolutely necessary
- Prefer structured extraction over conversational reply

### 🏛️ 8. Intent Understanding Examples (Extended)

#### Case D: Instant Self-Correction (Single Transcript)
Input: "Ha ek butter chicken karjo. Na na ek butter chicken na karta eni badle ek chole bhature ane dal bhakri."
Current Order Summary: "Order is empty"
Output: {
  "intent": "new_order",
  "items": [
    { "name": "Chhole Bhature", "quantity": 1, "addons": {} },
    { "name": "Dal Makhani", "quantity": 1, "addons": {} }
  ],
  "modifications": [],
  "response_text": "Theek hai, Butter Chicken cancel kari ne ek Chole Bhature ane ek Dal Bhakri rakhu chu. Biju kai?",
  "language_code": "gu-IN"
}

#### Case E: Contextual Modification (No Duplicate)
Input: "Masala dosa thodu teekhu karjo"
Current Order Summary: "1x Masala Dosa"
Output: {
  "intent": "modify_order",
  "items": [],
  "modifications": [
    { "target_item": "Masala Dosa", "action": "update", "changes": { "spicy": "increase" } }
  ],
  "response_text": "Done! Masala dosa teekhu kari daish.",
  "language_code": "gu-IN"
}

#### Case F: Explicit Addition (Duplicate)
Input: "Ek biju masala dosa add karo"
Current Order Summary: "1x Masala Dosa"
Output: {
  "intent": "new_order",
  "items": [
    { "name": "Masala Dosa", "quantity": 1, "addons": {} }
  ],
  "modifications": [],
  "response_text": "Saras! Ek biju Masala Dosa add kari didhu che.",
  "language_code": "gu-IN"
}

#### Case G: Addon Swap (Instead of X, use Y)
Input: "Butter chicken ma teekha mat rakhna, uske badle thoda extra butter dal dena"
Current Order Summary: "1x Butter Chicken"
Output: {
  "intent": "modify_order",
  "items": [],
  "modifications": [
    {
      "target_item": "Butter Chicken",
      "action": "update",
      "changes": { "spicy": "remove", "butter": "increase" }
    }
  ],
  "response_text": "Theek hai, Butter Chicken spicy nahi rahega aur extra butter add kar diya hai.",
  "language_code": "hi-IN"
}

#### Case K: Existing Item Addon Update (Sambar/Chutney)
Input: "Idli mein teekha mat rakhna, Idli mein extra sambhar do."
Current Order Summary: "1x Idli"
Output: {
  "intent": "modify_order",
  "items": [],
  "modifications": [
    {
      "target_item": "Idli",
      "action": "update",
      "changes": { "spicy": "remove", "sambar": "increase" }
    }
  ],
  "response_text": "Saras! Idli teekhu nahi rahe ane extra sambhar add kari didhu che.",
  "language_code": "gu-IN"
}

#### Case H: Affirmative Confirmation
Input: "Yes", "Haan", "Ha", "Theek hai", "Sure","done","ok","haan ji","haan ji done","kari do","kari lo","kari lo done","kari lo done ji","haan ji done ji"
Output: {
  "intent": "affirmative",
  "items": [],
  "modifications": [],
  "response_text": "Saras! Done.",
  "language_code": "gu-IN"
}

#### Case I: Negative Confirmation
Input: "No", "Nahi", "Nathi joitu", "Nako","nathi joitu done","nathi joitu done ji","nathi joitu done ji done","nathi joitu done ji done ji","nathi joitu done ji done ji done","reva do","reva kari lo","reva kari lo done","reva kari lo done ji","reva kari lo done ji done","reva kari lo done ji done ji","reva kari lo done ji done ji done""
Output: {
  "intent": "negative",
  "items": [],
  "modifications": [],
  "response_text": "Theek hai, cancel kari didhu che.",
  "language_code": "gu-IN"
}

#### 🚫 STRICT UNCERTAINTY RULE 🚫
- **ITEM NOT IN MENU**: If the user mentions an item that is NOT in the AVAILABLE MENU (even after considering semantic similarities), YOU MUST:
    1.  Do NOT add it to the `items` list.
    2.  Mention politely in the `response_text` that you couldn't find that item (e.g., "Sorry, [item] is not on our menu today").
- **LOW CONFIDENCE**: If you are unsure what the user said (very noisy input), ask for clarification in the `response_text`.
- **🚫 STRICT CONSERVATIVENESS RULE 🚫**: 
    - **NEVER GUESS**. If a word only slightly sounds like a food item but is not clearly one, DO NOT extract it. 
    - For example, if the user says "Shahane", "Kishi", or other random words, return `items: []` and ask "Maaf karjo, tame shu kidhu?" (Sorry, what did you say?).
    - Only extract items if you are at least 90% sure the user intended to order that specific dish.
- **🚫 NONSENSE / UNKNOWN 🚫**: If the user says something that is not clearly an order, modification, or confirmation (e.g., "kuch bhi", "kuchh bhi", "xyz", "abracadabra"):
    1.  **NEVER** map it to `negative` or `affirmative` intent.
    2.  Return `intent: "none"`, `items: []`.
    3.  Ask for repetition in `response_text` ("Maaf karjo, tame shu kidhu?").

#### Case J: Nonsense / Unknown
Input: "kuchh bhi bol rha hu"
Output: {
  "intent": "none",
  "items": [],
  "modifications": [],
  "response_text": "Maaf karjo, tame shu kidhu? Ek vaar fari thi bolsho?",
  "language_code": "hi-IN"
}

#### Case L: General Question / Recommendation
Input: "What do you have for breakfast?" or "Opening hours kya hai?"
Output: {
  "intent": "recommendation",
  "items": [],
  "modifications": [],
  "response_text": "Amara pase breakfast ma Masala Dosa, Idli ane Vada che. Ame savare 11 vagya thi sharu kariye chhiye.",
  "language_code": "gu-IN"
}

Goal: Act like a smart Indian waiter. If asked a question, use intent 'question' or 'recommendation'.
"""

    history_str = "\n".join([f"- {h}" for h in (history or [])]) if history else "No previous history."
    
    restaurant_info = "Pooja Restaurant (Ahmedabad). Open 11AM-11PM. Specialties: Dosa, Butter Chicken. Accepts UPI/Cash. Facilities: Wi-Fi, Parking."

    system_prompt = system_prompt_template.replace("{AVAILABLE_MENU}", ", ".join(INDIAN_MENU)) \
                                         .replace("{INVENTORY_STATUS}", inventory_summary) \
                                         .replace("{MENU_CATEGORIES}", categories_summary) \
                                         .replace("{RESTAURANT_INFO}", restaurant_info) \
                                         .replace("{CONVERSATION_HISTORY}", history_str)



    # 1. Get Keyword Hints (Semantic Match against local dict)
    hints, hint_latency = get_correction_hints(transcript)
    
    hint_prompt = ""
    if hints:
        hint_str = ", ".join([f"{h['category']} (via '{h['matched_keyword']}')" for h in hints])
        hint_prompt = f"\n💡 INTENT HINTS (Detected from local vocabulary): {hint_str}\n"
    
    # Estimate tokens added by hints (approx 4 chars per token)
    hint_tokens = len(hint_prompt) // 4
    
    client = get_cerebras_client()
    preprocessed_text = preprocess_transcript(transcript)
    
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
    
    try:
        # Start Timing the LLM Call
        llm_start = time.perf_counter()
        
        # Run LLM call using Gemini
        try:
            from google.genai import types
            
            # Gemini Native Call (Async)
            client = get_gemini_model()
            response = await client.aio.models.generate_content(
                model='gemini-3.1-flash-lite',
                contents=f"{hint_prompt}Current Order Summary: {current_order_summary}\n\nUser Order:\nOriginal: {transcript}\nPreprocessed: {preprocessed_text}",
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    response_mime_type='application/json',
                    response_schema=CLASSIFICATION_SCHEMA,
                    temperature=0.1,
                ),
            )
            text_content = response.text
            usage = response.usage_metadata
            
            # Map usage for logging
            prompt_tokens = usage.prompt_token_count if usage else 0
            completion_tokens = usage.candidates_token_count if usage else 0
            
        except Exception as e:
            print(f"Gemini Error: {e}. Falling back to Cerebras...")
            # Fallback to Cerebras if Gemini fails
            client = get_cerebras_client()
            completion = await client.chat.completions.create(
                model="llama3.1-8b",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"{hint_prompt}Current Order Summary: {current_order_summary}\n\nUser Order:\nOriginal: {transcript}\nPreprocessed: {preprocessed_text}"}
                ],
                response_format={"type": "json_object"},
                temperature=0.1
            )
            text_content = completion.choices[0].message.content
            usage_obj = getattr(completion, "usage", None)
            prompt_tokens = getattr(usage_obj, "prompt_tokens", 0)
            completion_tokens = getattr(usage_obj, "completion_tokens", 0)
        llm_end = time.perf_counter()
        total_llm_time = (llm_end - llm_start) * 1000
        print(f"DEBUG: [METRICS] Keyword Scanning: {hint_latency:.2f}ms | Added Tokens: ~{hint_tokens}")
        print(f"DEBUG: [METRICS] LLM Extraction: {total_llm_time:.2f}ms")

        # ── Token Usage Logging ──
        log_token_usage(
            transcript=transcript,
            input_tokens=prompt_tokens,
            output_tokens=completion_tokens,
            latency_ms=total_llm_time
        )

        print(f"DEBUG LLM Raw: {text_content}")  # Log raw response for debugging
        cleaned_json = extract_json(text_content)
        parsed_data = json.loads(cleaned_json)


        
        # Process all extracted data
        extracted_items = parsed_data.get("items", [])
        extracted_modifications = parsed_data.get("modifications", [])
        
        for item in extracted_items:
            # Time the per-item processing
            item_start = time.perf_counter()
            
            dish = item.get("name")
            qty = item.get("quantity", 1)
            # Addons are now a dictionary from the LLM
            # Convert structured array back to dictionary for backend compatibility
            addons_list = item.get("addons", [])
            if isinstance(addons_list, list):
                addons_dict = {a.get("type"): a.get("value") for a in addons_list if isinstance(a, dict) and a.get("type")}
            else:
                addons_dict = {}

            # Map dish name
            mapped_dish, dish_score, is_ambiguous = fuzzy_match_dish(dish)
            
            # Filter out junk item matches
            if not is_ambiguous and dish_score < 0.30 and len(dish.split()) > 2:
                print(f"DEBUG: Skipping false item extraction for '{dish}' (score: {dish_score})")
                continue
            
            item_end = time.perf_counter()
            print(f"DEBUG: [TIME] Processed item '{mapped_dish}' in {(item_end - item_start)*1000:.2f}ms")

            processed_item = {
                "dish": mapped_dish.strip() if dish_score >= 0.10 else dish.strip(),
                "quantity": qty,
                "portion": "full", # Portions not explicitly in new schema but can be part of dish name
                "modified_addons": addons_dict, # Use the structured dict from LLM
                "addons": [f"{k}: {v}" for k, v in addons_dict.items() if v not in ["remove", "remove_action"]]
            }
            final_order_result["items"].append(processed_item)
            
            # --- NEW: Raw Transcript Guard ---
            # If the LLM guessed a multi-word name but only one word was said, force confirm
            raw_clean = re.sub(r'[^a-zA-Z0-9\s]', '', transcript).lower()
            dish_clean = re.sub(r'[^a-zA-Z0-9\s]', '', processed_item["dish"]).lower()
            is_partial_in_raw = (dish_clean not in raw_clean) and any(word in raw_clean for word in dish_clean.split())
            
            # Threshold checks
            AUTO_REPLACE_THRESHOLD = 0.85
            MIN_CONFIDENCE_THRESHOLD = 0.65

            if is_ambiguous or is_partial_in_raw or (dish_score >= MIN_CONFIDENCE_THRESHOLD and dish_score < AUTO_REPLACE_THRESHOLD):
                # Suggest item for confirmation
                final_order_result["needs_confirmation"].append({
                    "original": dish,
                    "suggested": mapped_dish.strip(),
                    "quantity": qty,
                    "score": round(dish_score, 2),
                    "addons": processed_item["addons"]
                })
            elif dish_score >= AUTO_REPLACE_THRESHOLD:
                # Auto-confirm high confidence
                final_order_result["confirmed"][processed_item["dish"]] = {
                    "quantity": qty,
                    "addons": processed_item["addons"]
                }
            else: # Below MIN_CONFIDENCE_THRESHOLD
                # Unknown dish - Ask to repeat
                final_order_result["not_in_menu"].append(dish)
                if not final_order_result["response_text"]:
                    final_order_result["response_text"] = f"Maaf karjo, ek vaar fari thi bolsho? ('{dish}' khabar na padi). (Sorry, I didn't catch {dish}, could you say it again?)"

        # Store modifications for server processing
        final_order_result["modifications"] = extracted_modifications
        
        # Global flags & Response
        final_order_result["is_finished"] = parsed_data.get("is_finished", False)
        final_order_result["intent"] = parsed_data.get("intent", "none")
        final_order_result["response_text"] = parsed_data.get("response_text", "").strip()
        final_order_result["language_code"] = parsed_data.get("language_code", "hi-IN")


    except Exception as e:
        print(f"ERROR processing transcript: {e}")
        # FALLBACK: Try simple fuzzy matching for the whole transcript
        mapped_dish, score, _ = fuzzy_match_dish(preprocessed_text)
        if score > 0.5:
            final_order_result["items"].append({"dish": mapped_dish, "quantity": 1, "portion": "full", "modifier": "set"})
            final_order_result["confirmed"][mapped_dish] = {"quantity": 1, "addons": []}

    return final_order_result

async def main():
    test_transcripts = [
        "1 biryani and 2 coke",
        "vadhu butter pav bhaji",
        "thodu tikhu dal tadka",
        "xyz",
        "halogobi"
    ]
    for transcript in test_transcripts:
        print(f"\n--- Testing: '{transcript}' ---")
        result = await classify_order(transcript)
        print(json.dumps(result, indent=2))

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())

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

    CRITICAL: YOU MUST RETURN A JSON OBJECT WITH THE KEY "corrections". THE OUTPUT SHOULD START WITH {{ AND END WITH }}.
    Example root structure: {{ "corrections": [...] }}
    
    10. RULES FOR FIELDS:
    1. REPLACEMENT/SWAP: If you see "instead of X, add Y", "X na badle Y", or "X ni jagyae Y", you MUST REMOVE X from the list and ADD Y. This is a priority rule.
    2. EXPLICIT REMOVAL: If user says "remove X", "X na rakhta", "X vagar", "don't make X", remove X from the list.
    3. ADDITION: If user says "extra X", "Y nakho", "make it Y", add Y to the list.
    4. PRESERVE CATEGORY: Ensure you identify addons correctly regardless of spelling (e.g., 'meethi' and 'mithi' are the same).
    5. NO DUPLICATES: The final list should have unique addon strings.

    OUTPUT FORMAT:
    {{ "updated_addons": ["addon1", "addon2"] }}
    """
    
    try:
        from google.genai import types
        response = get_gemini_model().models.generate_content(
            model='gemini-1.5-flash-latest',
            contents=f"New Request for {dish_name}:\n{new_transcript}",
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                response_mime_type='application/json',
                temperature=0.0
            )
        )
        data = json.loads(response.text)
        return data.get("updated_addons", current_addons)
    except Exception as e:
        print(f"ERROR in refine_addons_with_llm: {e}")
        # Fallback to the existing current_addons if LLM fails
        return current_addons
