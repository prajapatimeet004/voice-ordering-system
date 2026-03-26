import os
import json
import re
from dotenv import load_dotenv
from classifier_service import fuzzy_match_dish

load_dotenv(override=True)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GROQ_API_KEY") or os.getenv("SARVAM_API_KEY")

if not GEMINI_API_KEY:
    raise ValueError("❌ No API key found in .env (expected GEMINI_API_KEY)")

_gemini_model = None

def get_gemini_model():
    global _gemini_model
    if _gemini_model is None:
        from google import genai
        client = genai.Client(api_key=GEMINI_API_KEY)
        _gemini_model = client
    return _gemini_model

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

CORRECTION_DICT = {
    "modify": [
        # Hindi
        "nahi", "nahi nahi", "galat", "badal do", "change karo", "uski jagah",
        "replace karo", "dusra wala", "pehle wala nahi", "sahi karo", "sudharo",
        "uski jagah", "uske badle", "badal do", "usko change karo", "jyada", "thoda jyada",
        # Gujarati
        "nai", "na na", "khotu", "badlo", "badli do", "eni jagyae", "biju aapo",
        "e nathi", "pela valu nahi", "sachu karo", "sudharjo", "ena badle", "badli do",
        # English
        "no no", "not that", "change it", "replace it", "instead", "wrong",
        "modify", "update it", "i mean", "sorry", "change karo", "rakhna", "rakhjo", "kar dena", "kari dejo"
    ],
    "remove": [
        # Hindi
        "cancel", "hatao", "mat do", "rehne do", "nikal do", "nahi chahiye",
        "remove karo", "delete karo", "mat lana", "ye hatao", "wo nahi chahiye", 
        "cancel karo isko", "ek kam karo", "kam karo", "thoda kam karo", "hata do", 
        "nikaal do", "remove karo", "cancel karo", "ek hata do", "ek kam kar do",
        # Gujarati
        "cancel karo", "hatao", "nahi joiye", "rehva do", "kadhi nakho",
        "nathi joiye", "remove karo", "aa kadhi lo", "pelu nathi joiye", "aa rehva dyo",
        # English
        "remove", "delete", "dont add", "don't add", "i dont want",
        "i don't want", "skip it", "leave it", "don't bring", "remove this", "take off", "cancel the"
    ],
    "quantity_change": [
        # Hindi
        "ek nahi", "do karo", "teen karo", "char karo", "quantity badhao",
        "quantity kam karo", "aur ek", "sirf ek", "zyada karo", "kam karo",
        "ek aur add karo", "thoda extra daal do", "extra daal do", "extra laga do", "aur daal do", 
        "ek aur bhej do", "ek aur laga do", "aur kar do", "ek aur plate", "ek aur item", 
        "badha do", "quantity badha do", "ek badha do", "do kar do", "teen kar do", 
        "chaar kar do", "paanch kar do", "do bana do", "teen bana do", "chaar bana do", 
        "quantity do kar do", "plate do kar do",
        # Gujarati
        "ek nahi be", "be karo", "tran karo", "quantity vadharo",
        "quantity ochi karo", "vadhu aapo", "ochu karo",
        "thodi vadhari do", 
        "thodu vadhu muki do", "ek aur nakho", "thodi add karo", "ek plate vadhaari do", 
        "ek biju aapona na", "char karo", "panch karo", 
        "be kari do", "tran kari do", "char kari do", "quantity be karo", "be plate karo",
        "ek vadhare", "be vadhare", "vadhari do", "ek add karo", 
        "ek aur add karo", "thodu extra muki do", "extra muki do", 
        "biju ek muki do", "ek aur muki do", "thodu vadhu kari do", 
        "ek plate vadhare", "ek item vadhare",
        # English
        "make it two", "make it three", "change to two", "increase quantity",
        "decrease quantity", "add one more", "only one"
    ],
    "cancel_all": [
        # Hindi
        "sab cancel", "pura cancel", "sab hatao", "order cancel", "order cancel karo", 
        "pura order hatado", "sab hatado", "kuch nahi chahiye", "rehne do sab", "pura order cancel",
        # Gujarati
        "badhu cancel", "badhu hatao", "puro cancel", "order cancel karo", "badhu cancel karo", 
        "order radd karo", "badhu kadhi nakho", "rehva dyo badhu", "kai nathi joiye", "order cancel kari do",
        # English
        "cancel everything", "cancel all", "clear order", "reset order", "cancel the entire order", 
        "clear my order", "i want to cancel", "cancel my whole order", "reset everything"
    ],
    "filler_stop": [
        "nahi nahi", "are nahi", "ruk", "ruk jao", "ek minute", "wait", "ek min"
    ]
}

# Lazy-loaded embedding model and pre-calculated keyword embeddings
_embedding_model = None
_all_correction_phrases = []
_correction_embeddings = None

def get_embedding_model():
    """Returns the embedding model and pre-calculated embeddings for all correction keywords."""
    global _embedding_model, _all_correction_phrases, _correction_embeddings
    if _embedding_model is None:
        print("DEBUG: Loading Embedding Model for Corrections...")
        from sentence_transformers import SentenceTransformer
        _embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
        
        # Collect all unique correction phrases
        _all_correction_phrases = []
        for phrases in CORRECTION_DICT.values():
            _all_correction_phrases.extend(phrases)
        _all_correction_phrases = list(set(_all_correction_phrases)) # Unique only
        
        # Pre-calculate embeddings
        _correction_embeddings = _embedding_model.encode(_all_correction_phrases, convert_to_tensor=True)
        
    return _embedding_model, _all_correction_phrases, _correction_embeddings

def detect_correction(transcript: str, threshold=0.90):
    """
    Checks if the transcript contains any intent similar to correction keywords 
    using a Hybrid approach: 60% Semantic + 40% Fuzzy Keywords.
    """
    if not transcript.strip():
        return False
        
    # Get model and pre-calculated data
    model, dictionary_phrases, dictionary_embeddings = get_embedding_model()
    
    # Pre-process transcript: split into words and bigrams
    words = re.sub(r'[^a-zA-Z0-9\s]', '', transcript.lower()).split()
    if not words:
        return False
        
    tokens = list(set(words)) # Start with unique words
    # Add bigrams for phrases like "not that", "nahi nahi"
    for i in range(len(words) - 1):
        tokens.append(f"{words[i]} {words[i+1]}")
    
    # 1. Semantic Search
    token_embeddings = model.encode(tokens, convert_to_tensor=True)
    from sentence_transformers import util
    import torch
    similarity_matrix = util.cos_sim(token_embeddings, dictionary_embeddings)
    semantic_score = torch.max(similarity_matrix).item()
    
    # 2. Fuzzy Search (Keyword/String similarity)
    from rapidfuzz import process, fuzz
    # Check each token against the dictionary
    fuzzy_best_score = 0
    for token in tokens:
        _, f_score, _ = process.extractOne(token, dictionary_phrases, scorer=fuzz.ratio)
        if f_score > fuzzy_best_score:
            fuzzy_best_score = f_score
    
    fuzzy_score = fuzzy_best_score / 100.0 # Normalize 0.0 - 1.0

    # 3. Hybrid Calculation (60/40)
    hybrid_score = (semantic_score * 0.6) + (fuzzy_score * 0.4)
    
    if hybrid_score >= threshold:
        print(f"DEBUG: Correction detected! (Semantic: {semantic_score:.4f}, Fuzzy: {fuzzy_score:.4f}, Hybrid: {hybrid_score:.4f})")
    else:
        print(f"DEBUG: Max hybrid correction score: {hybrid_score:.4f}")
    
    return hybrid_score >= threshold

def process_correction(transcript: str, current_order_items=None):
    """
    Sends the correction transcript to Groq LLM to identify the corrected dish and action.
    Returns a list of structured dictionaries with correction details.
    
    current_order_items: A list of dish names currently in the user's order.
    """
    order_context = ""
    if current_order_items:
        order_context = f"\nCURRENT ORDER ITEMS: {', '.join(current_order_items)}\n"

    system_prompt = f"""
    You are a restaurant order correction assistant.
    Analyze the customer's transcript which contains one or more corrections.
    {order_context}
    
    ADDON INDICATORS (Words meaning "with"):
    Gujarati: sathe, jode, sathe aapo, sathe aapjo, sathe mukjo, sathe rakho, sathe aapvu, sathe pan aapo, sathe pan mukjo, sathe add karo, sathe lai aavo, sathe serve karo, sathe muki do, sathe pan aapjo, sathe pan moklo
    Hindi: ke saath, saath mein, saath, iske saath, iske saath dena, saath mein dena, saath mein laana, saath mein daalna, saath mein bhejna, iske saath bhi, saath mein jodo, saath mein laga do, saath mein rakho, saath mein serve karo
    English: with, along with, together with, serve with, add with, include with, give with, bring with, send with, pair with, served with, side with, with extra, with side, with topping

    NUMBER & QUANTITY INDICATORS (Gujarati/Hindi/English):
    Often customers will state a quantity at the end of a sentence like "e 10" (make it 10), "e be kari do" (make that two), "usko 5 kar do" (make it 5). 
    - DETECT RELATIVE CHANGES: If the user says "add one more", "vadhare", "zyada", "increase", "extra", set 'is_relative' to true.
    - If they say "make it 5" or "e 5 kar do", 'is_relative' is false.

    CRITICAL RULES (STRICT ADHERENCE REQUIRED):
    1. NEVER TRANSLATE ANY WORD INTO ENGLISH. If the user speaks in Gujarati, Hindi, or any other language, you MUST keep the dish name and raw_addons EXACTLY as they appear in the transcript.
    2. DO NOT "CORRECT" OR "ALIENATE" THE LANGUAGE. If the user says "tikhu", do not write "spicy". If the user says "dungli", do not write "onion".
    3. THE ONLY PART THAT SHOULD BE ENGLISH IS THE JSON KEYS.
    4. Only use ACTION 'cancel_all' if the user explicitly wants to clear the ENTIRE order.
    5. If the user mentions a specific dish to remove or change, use 'remove', 'modify', or 'quantity_change'.
    6. Use 'modify' if they want to change customization/addons (e.g., "make it extra spicy instead") OR if they replace a dish (e.g., "coffee badle fish curry karo e 10" -> action: 'modify', original_dish: 'coffee', new_dish: 'fish curry', quantity: 10, is_relative: false).
    7. If the user mentions adding a new item within a correction (e.g., "Ek dal makhani karo"), use action: 'modify', original_dish: '', new_dish: 'dal makhani', quantity: 1, is_relative: false.
    8. ADDON INDICATORS: If you see any of the "with" indicator words listed above (e.g., "sathe", "ke saath", "with"), the phrase following it MUST be extracted into 'raw_addons'. PRESERVE ORIGINAL LANGUAGE.
    9. 'raw_addons': Extract phrases like "extra spicy", "no onion", "thodu vadhu tikhu". Keep original language words. EXACTLY AS SPOKEN.
    10. CRITICAL: INCLUDE ALL ITEMS. If the customer mentions multiple items (e.g., "Ek burger, ek chai..."), EVERY item must be represented in the "corrections" list. 
        - For items with no modifications, use action: 'modify', dish: '[item name]', quantity: [qty], raw_addons: [].
        - NEVER omit an item just because it doesn't have a correction. If it's in the transcript, it MUST be in the JSON.
    
    Output ONLY a clean JSON object with a key "corrections" which is a LIST of objects.
    
    Each object must have:
    - action: string ('modify', 'remove', 'quantity_change', 'cancel_all')
    - dish: string (the item being corrected, EXACTLY from transcript)
    - original_dish: string (empty unless replacing dish A with dish B)
    - new_dish: string (empty unless replacing dish A with dish B)
    - original_addon: string (empty unless replacing addon A with addon B, e.g., "medium spicy" badle "tikha")
    - new_addon: string (empty unless replacing addon A with addon B)
    - quantity: integer (the quantity mentioned, e.g. 1)
    - is_relative: boolean (true if user said "add", "more", "vadhare", "zyada", else false)
    - raw_addons: list of strings (new customization requested, EXACTLY from transcript)
    - correction_found: boolean

    EXAMPLES:
    - [Transcript]: "Ek burger, ek chai, thoda masala dosa spicy rakhjo"
      [Correct Output]: {{"corrections": [
          {{"action": "modify", "dish": "burger", "quantity": 1, "is_relative": false, "raw_addons": [], "correction_found": true}},
          {{"action": "modify", "dish": "chai", "quantity": 1, "is_relative": false, "raw_addons": [], "correction_found": true}},
          {{"action": "modify", "dish": "masala dosa", "quantity": 1, "is_relative": false, "raw_addons": ["spicy"], "correction_found": true}}
      ]}}

    - [Transcript]: "masala dosa nahi be coffee aapo"
      [Correct Output]: {{"corrections": [{{"action": "modify", "original_dish": "masala dosa", "new_dish": "coffee", "quantity": 2, "is_relative": false, "raw_addons": [], "correction_found": true}}]}}
    
    - [Transcript]: "biryani ma spicy badle medium spicy rakho"
      [Correct Output]: {{"corrections": [{{"action": "modify", "dish": "biryani", "original_addon": "spicy", "new_addon": "medium spicy", "quantity": 1, "is_relative": false, "raw_addons": ["medium spicy"], "correction_found": true}}]}}

    - [Transcript]: "Add one more masala toss"
      [Correct Output]: {{"corrections": [{{"action": "modify", "dish": "masala toss", "quantity": 1, "is_relative": true, "raw_addons": [], "correction_found": true}}]}}
    """

    model = get_gemini_model()
    try:
        full_prompt = system_prompt + f"\n\nCorrection Transcript: {transcript}"
        response = model.models.generate_content(
            model="gemini-2.5-flash",
            contents=full_prompt
        )

        result_content = response.text
        if not result_content or not result_content.strip():
            print("WARNING: Gemini API returned empty response for correction processing.")
            return []
        # Extract JSON from potential <think> or ``` markdown blocks
        clean_json = extract_json(result_content)
        try:
            corrections = json.loads(clean_json).get("corrections", [])
        except json.JSONDecodeError as json_err:
            print(f"WARNING: Could not parse correction JSON: {json_err}. Raw: {result_content[:200]}")
            return []
        
        # Enhance corrections with matching scores and addons
        # from classifier_service import match_addon_hybrid # This import was already present in the original, keeping it.

        for corr in corrections:
            if not corr.get("correction_found"):
                continue
                
            action = corr.get("action")
            raw_addons = corr.get("raw_addons", [])
            
            # Match Addons
            # We allow ALL raw_addons directly, no threshold drop.
            corr["addons"] = raw_addons

            if action == "modify":
                orig = corr.get("original_dish")
                new = corr.get("new_dish")
                if orig:
                    matched_orig, score_orig = fuzzy_match_dish(orig)
                    corr["original_dish"] = matched_orig if score_orig > 0.5 else orig
                    corr["original_score"] = round(float(score_orig), 2)
                if new:
                    matched_new, score_new = fuzzy_match_dish(new)
                    corr["new_dish"] = matched_new if score_new > 0.5 else new
                    corr["new_score"] = round(float(score_new), 2)
            elif action in ["remove", "quantity_change"]:
                dish = corr.get("dish")
                if dish:
                    matched_dish, score = fuzzy_match_dish(dish)
                    corr["dish"] = matched_dish if score > 0.5 else dish
                    corr["score"] = round(float(score), 2)
                    
        return corrections

    except Exception as e:
        print(f"ERROR: Groq Correction Processing Error: {e}")
        return []

if __name__ == "__main__":
    test_cases = [
        "Masala Dosa nahi Butter Chicken",
        "make it two coffee",
        "hatao samosa",
        "sab cancel karo",
        "order radd karo",
        "ye hatao dosa",
        "cancel my whole order",
        "aa kadhi lo sandwich"
    ]
    for tc in test_cases:
        print(f"\nTesting: {tc}")
        if detect_correction(tc):
            print("Correction Detected!")
            # Note: process_correction requires an active Groq API key to run fully.
            # We are primarily testing the detection logic (detect_correction) here.
            # print(json.dumps(process_correction(tc), indent=4))
        else:
            print("No Correction Detected.")
