import re
import json
from enum import Enum
from rapidfuzz import process, fuzz

# --- CONFIGURATION (Provided by USER) ---
ADDON_KEYWORD_MAP = {
    # 🔥 INCREASE
    "extra": "increase",
    "vadhu": "increase",
    "vadhare": "increase",
    "jyada": "increase",
    "zyada": "increase",
    "double": "increase",
    "full": "increase",

    # 🔻 DECREASE
    "ochhu": "decrease",
    "ochu": "decrease",
    "kam": "decrease",
    "thodu": "decrease",
    "thoda": "decrease",
    "less": "decrease",

    # ❌ REMOVE / NEGATION
    "na": "remove",
    "nai": "remove",
    "nahi": "remove",
    "mat": "remove",
    "vagar": "remove",
    "without": "remove",
    "no": "remove",

    # ➕ ADD / INCLUDE
    "sathe": "add",
    "mukjo": "add",
    "nakho": "add",
    "add": "add",
    "include": "add",

    # 🔁 ACTION CHANGE
    "hatao": "remove_action",
    "nikalo": "remove_action",
    "remove": "remove_action",

    # 🔄 SWAP / REPLACE
    "badle": "swap",
    "badlama": "swap",
    "jagya": "swap",
    "jagyaae": "swap",
    "jagah": "swap",
    "instead": "swap",
    "replace": "swap",
    "substitute": "swap",
    "rakhta": "add",
    "rakhjo": "add",
    "rakhje": "add",
    "rakho": "add",

    # 🌶️ SPICE
    "tikhu": "spicy",
    "tikoo": "spicy",
    "tikhoo": "spicy",
    "teekha": "spicy",
    "spicy": "spicy",

    # 🧈 BUTTER / FAT
    "butter": "butter",
    "batr": "butter",
    "makhan": "butter",
    "ghee": "ghee",

    # 🧀 CHEESE
    "cheese": "cheese",

    # 🧅 ONION
    "kanda": "onion",
    "pyaz": "onion",
    "onion": "onion",

    # 🧄 GARLIC
    "lasan": "garlic",
    "garlic": "garlic",

    # 🍅 TOMATO
    "tamatar": "tomato",
    "tomato": "tomato",

    # 🥣 GRAVY / TEXTURE
    "gravy": "gravy",
    "ras": "gravy",
    "sukhu": "dry",
    "dry": "dry",

    # 🧂 SALT / TASTE
    "mithu": "salt",
    "namak": "salt",
    "salt": "salt",
    "mithi": "sweet",
    "meethi": "sweet",
    "glukose": "sweet",
    "sugar": "sweet",
    "shakkar": "sweet",
    "chini": "sweet",

    # 🌡️ TEMPERATURE
    "garam": "hot",
    "hot": "hot",
    "thandu": "cold",
    "thanda": "cold",
    "cold": "cold",

    # 🛢️ OIL
    "tel": "oil",
    "oil": "oil",

    # 🧃 SAUCE
    "sauce": "sauce",

    # 🍋 LEMON
    "limbu": "lemon",
    "lemon": "lemon",

    # 🧀 PANEER
    "paneer": "paneer",

    # 🥛 DAIRY
    "dahi": "curd",
    "curd": "curd",
    "malai": "cream",
    "cream": "cream",

    # 🍜 TEXTURE
    "crispy": "crispy",
    "soft": "soft"
}

# --- INTERNAL CATEGORIZATION ---
MODIFIER_CATEGORIES = {"increase", "decrease", "remove", "add", "remove_action", "swap"}

def normalize_text(text: str) -> str:
    """Normalize text by lowercasing and removing punctuation."""
    if not text:
        return ""
    # Lowercase and remove punctuation (keep spaces)
    text = text.lower()
    text = re.sub(r'[^\w\s]', '', text)
    return text.strip()

def tokenize(text: str) -> list:
    """Tokenize normalized text into words."""
    return text.split()

def exact_match(word: str):
    """Perform O(1) exact match in the keyword map."""
    category = ADDON_KEYWORD_MAP.get(word)
    if category:
        return category, 1.0
    return None, 0.0

def fuzzy_match(word: str, threshold: int = 75):
    """Perform fuzzy match using rapidfuzz. Skip very short words to avoid noise."""
    if len(word) < 4:
        return None, 0.0
        
    # We match against the keys of our keyword map
    match = process.extractOne(word, ADDON_KEYWORD_MAP.keys(), scorer=fuzz.ratio)
    if match and match[1] >= threshold:
        return ADDON_KEYWORD_MAP[match[0]], match[1] / 100.0
    return None, 0.0

def extract_addons(transcript: str, fuzzy_threshold: int = 75) -> dict:
    """
    Main extraction logic:
    1. Normalize and tokenize.
    2. Specific handling for multi-word modifiers like 'na badle'.
    3. Identify all keywords (Exact + Fuzzy).
    4. Pair modifiers with addons based on proximity.
    """
    normalized = normalize_text(transcript)
    
    # Specific fix for 'na badle' (Gujarati 'instead of') 
    # and verbose 'eni jagyae' phrases.
    normalized = re.sub(r'\bna\s+badle\b', 'badle', normalized)
    normalized = re.sub(r'\bna\s+badlama\b', 'badlama', normalized)
    normalized = re.sub(r'\beni\s+jagyaae\b', 'jagyaae', normalized)
    normalized = re.sub(r'\beni\s+jagyae\b', 'jagyaae', normalized)
    normalized = re.sub(r'\beni\s+jagah\b', 'jagah', normalized)
    
    tokens = tokenize(normalized)
    
    # Common filler words to ignore for fuzzy matching
    FILLER_WORDS = {"ane", "ek", "nu", "ma", "che", "chhe", "aapo", "do", "kar"}
    
    # Step 1: Identify all keyword positions
    identified = []
    for i, token in enumerate(tokens):
        # 1. Try exact match first (O(1))
        category, score = exact_match(token)
        
        # 2. Try fuzzy match if not in filler words
        if not category and token not in FILLER_WORDS:
            category, score = fuzzy_match(token, fuzzy_threshold)
        
        if category:
            is_mod = category in MODIFIER_CATEGORIES
            identified.append({
                "category": category,
                "index": i,
                "score": score,
                "is_modifier": is_mod
            })

    # Step 2: Proximity-based pairing
    addons_result = {}
    used_indices = set()
    
    # Try pairing Modifier + Addon or Addon + Modifier (distance <= 2)
    for i in range(len(identified)):
        if i in used_indices:
            continue
            
        curr = identified[i]
        
        # Look for a companion in the remaining identified tokens
        found_pair = False
        for j in range(i + 1, len(identified)):
            if j in used_indices:
                continue
            
            other = identified[j]
            # Check distance (increased for verbose Gujarati phrases)
            max_dist = 6 if curr["category"] == "swap" or other["category"] == "swap" else 3
            if abs(curr["index"] - other["index"]) <= max_dist:
                # If one is modifier and other is addon
                if curr["is_modifier"] != other["is_modifier"]:
                    modifier = curr["category"] if curr["is_modifier"] else other["category"]
                    addon = other["category"] if curr["is_modifier"] else curr["category"]
                    addons_result[addon] = modifier
                    used_indices.add(i)
                    used_indices.add(j)
                    found_pair = True
                    break
        
        # Individual standalone addon
        if not found_pair and i not in used_indices:
            if not curr["is_modifier"]:
                addons_result[curr["category"]] = "add"
            used_indices.add(i)

    return {"addons": addons_result}

def merge_structured_addons(current_addons: list, new_addons_dict: dict) -> list:
    """
    Intelligently merges a dictionary of new addons into the existing list of strings.
    Handles 'remove', 'remove_action', and 'swap' correctly by identifying 
    which existing strings belong to which categories.
    """
    if not new_addons_dict:
        return current_addons
        
    # Map current strings to their categories
    category_to_string = {}
    for s in current_addons:
        extracted = extract_addons(s)["addons"]
        if extracted:
            # Map the first category found to this string
            cat = next(iter(extracted.keys()))
            category_to_string[cat] = s
    
    final_addons = set(current_addons)
    
    for category, action in new_addons_dict.items():
        if action in ["remove", "remove_action", "swap"]:
            # If we know which string represents this category, remove it
            if category in category_to_string:
                final_addons.discard(category_to_string[category])
            # Also discard the category name itself if it was added directly
            final_addons.discard(category)
        
        if action in ["increase", "add", "swap"]:
            # For 'swap', we already removed the old one above. 
            # Now we add the category name as a new string (or we could use a default mapping)
            if action != "swap" or category not in category_to_string:
                # Map categories back to a friendly name for display
                display_name = category
                # Special cases for better UI
                friendly = {"spicy": "tikhi", "butter": "butter", "onion": "without onion", "sweet": "sweet"}
                display_name = friendly.get(category, category)
                final_addons.add(display_name)
    
    return list(final_addons)

# --- UNIT TESTS ---
def run_tests():
    test_cases = [
        {
            "input": "vadhu butter ane ochhu tikhu",
            "expected": {"addons": {"butter": "increase", "spicy": "decrease"}}
        },
        {
            "input": "mane ek pav bhaji vadhare batr ane tikoo ochu aapo",
            "expected": {"addons": {"butter": "increase", "spicy": "decrease"}}
        },
        {
            "input": "kanda vagar",
            "expected": {"addons": {"onion": "remove"}}
        },
        {
            "input": "extra cheese double paneer",
            "expected": {"addons": {"cheese": "increase", "paneer": "increase"}}
        },
        {
            "input": "garlic without",
            "expected": {"addons": {"garlic": "remove"}}
        },
        {
            "input": "hatao onion",
            "expected": {"addons": {"onion": "remove_action"}}
        },
        {
            "input": "thodu thandu lemon juice",
            "expected": {"addons": {"cold": "decrease", "lemon": "add"}}
        },
        {
            "input": "batr vadhare",
            "expected": {"addons": {"butter": "increase"}}
        },
        {
            "input": "butter na badle cheese nakho",
            "expected": {"addons": {"butter": "swap", "cheese": "add"}}
        }
    ]
    
    print("🚀 Running Unit Tests for Addon Extractor...")
    for i, tc in enumerate(test_cases):
        output = extract_addons(tc["input"])
        match = output["addons"] == tc["expected"]["addons"]
        status = "✅ PASS" if match else "❌ FAIL"
        print(f"Test {i+1}: {status}")
        print(f"  Input: {tc['input']}")
        print(f"  Output: {json.dumps(output)}")
        if not match:
            print(f"  Expected: {json.dumps(tc['expected'])}")
    print("Test execution finished.\n")

if __name__ == "__main__":
    run_tests()
    
    example_input = "mane ek pav bhaji vadhare batr ane tikoo ochu aapo"
    result = extract_addons(example_input)
    print(f"Final Example Input: '{example_input}'")
    print(f"Final Example Output: {json.dumps(result, indent=2)}")
