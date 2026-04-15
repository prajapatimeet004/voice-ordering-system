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
    "nakhal": "add",

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

    # 🥣 CHUTNEY
    "chutney": "chutney",
    "chutany": "chutney",
    "chutni": "chutney",
    "chatunry": "chutney",
    "chatni": "chutney",

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
    
    # Priority 1: Explicit Swaps (Instead of A, do B)
    for i, curr in enumerate(identified):
        if curr["category"] == "swap":
            before = None
            before_idx = -1
            after = None
            after_idx = -1
            
            # Find nearest category before 'swap'
            for j in range(i - 1, -1, -1):
                if not identified[j]["is_modifier"] and j not in used_indices:
                    before = identified[j]
                    before_idx = j
                    break
            
            # Find nearest category after 'swap'
            for j in range(i + 1, len(identified)):
                if not identified[j]["is_modifier"] and j not in used_indices:
                    after = identified[j]
                    after_idx = j
                    break
            
            if before and after:
                # We found both! (e.g., "A instead B")
                addons_result[before["category"]] = "swap"
                addons_result[after["category"]] = "add"
                used_indices.update({i, before_idx, after_idx})
            elif after:
                # Only something after (e.g., "instead of A")
                # If there's an 'of' keyword, it's definitely the target. 
                # Our current map doesn't have 'of', but we can assume 'after' is the target if swap is a prefix.
                addons_result[after["category"]] = "swap" 
                used_indices.update({i, after_idx})
            elif before:
                # Something before and swap at end (e.g., "no spicy instead")
                addons_result[before["category"]] = "swap"
                used_indices.update({i, before_idx})

    # Priority 2: Standard Pairing (Modifier + Addon or Addon + Modifier)
    for i, curr in enumerate(identified):
        if i in used_indices:
            continue
            
        # Look for a companion in the remaining identified tokens
        found_pair = False
        for j in range(i + 1, len(identified)):
            if j in used_indices:
                continue
            
            other = identified[j]
            # Check distance
            max_dist = 4 
            if abs(curr["index"] - other["index"]) <= max_dist:
                # If one is modifier and other is addon
                if curr["is_modifier"] != other["is_modifier"]:
                    modifier = curr["category"] if curr["is_modifier"] else other["category"]
                    addon = other["category"] if curr["is_modifier"] else curr["category"]
                    
                    # If this addon category already has a 'swap' or specific action, 
                    # and the new one is just a generic 'remove', don't overwrite it.
                    existing_action = addons_result.get(addon)
                    is_new_specific = modifier in ["increase", "decrease"]
                    is_old_generic = existing_action in ["remove", "remove_action", "swap"]
                    
                    if not existing_action or (is_new_specific and is_old_generic):
                        addons_result[addon] = modifier
                    
                    used_indices.update({i, j})
                    found_pair = True
                    break
        
        # Priority 3: Standalone addon (default to 'add')
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
        
        if action in ["increase", "decrease", "add", "swap"]:
            # For 'swap', we already removed the old one above. 
            # Now we add the category name as a new string (or we could use a default mapping)
            if action != "swap" or category not in category_to_string:
                # Map categories back to a friendly name for display
                display_name = category
                # Special cases for better UI
                friendly = {
                    "spicy": "tikhu" if action != "decrease" else "ochhu tikhu", 
                    "butter": "butter", 
                    "onion": "without onion", 
                    "sweet": "sweet",
                    "cold": "cold" if action != "decrease" else "thodu thandu",
                    "chutney": "chutney"
                }
                
                # If it was a decrease, use a better name if not in friendly
                if action == "decrease" and category not in friendly:
                    display_name = f"less {category}"
                else:
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
        },
        {
            "input": "remove spicy ness and instead make it less spicy",
            "expected": {"addons": {"spicy": "swap"}} # Swapping spicy category
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
