from typing import List, Dict

def get_confirm_text(suggested: str, original: str) -> str:
    """Generates text for suggesting an item correction."""
    return f"Did you mean {suggested} instead of {original}? Please say yes or no."

def get_item_confirmed_text(items: List[Dict]) -> str:
    """Generates text for confirmed items."""
    if not items:
        return ""
    item_names = [f"{item['quantity']} {item['dish']}" for item in items]
    if len(item_names) == 1:
        return f"Theek hai, adding {item_names[0]} to your order."
    else:
        main_items = ", ".join(item_names[:-1])
        last_item = item_names[-1]
        return f"Okay, adding {main_items} and {last_item} to your order."

def get_final_order_text(confirmed_items: Dict) -> str:
    """Generates a summary of the entire order."""
    if not confirmed_items:
        return "Your order is empty. Would you like to add anything?"
    
    summary_parts = []
    for dish, data in confirmed_items.items():
        summary_parts.append(f"{data['quantity']} {dish}")
        if data.get('addons'):
            summary_parts[-1] += f" with {', '.join(data['addons'])}"
    
    summary = ", ".join(summary_parts)
    return f"Great! Your entire order is {summary}. Is that all, or would you like to add something else?"

def get_availability_feedback_text(unavailable_items: List[str]) -> str:
    """Generates feedback for items that are out of stock."""
    if not unavailable_items:
        return ""
    
    if len(unavailable_items) == 1:
        return f"Sorry, {unavailable_items[0]} available nathi. Kai biju laavu?"
    else:
        items_str = ", ".join(unavailable_items[:-1]) + " ane " + unavailable_items[-1]
        return f"Sorry, {items_str} available nathi. Kai biju laavu?"

def get_correction_feedback_text(corrections: List[Dict]) -> str:
    """Generates specific feedback for applied corrections (removals, mods)."""
    if not corrections:
        return "Theek hai, order update kar diya hai."
    
    parts = []
    for c in corrections:
        action = c.get("action")
        dish = c.get("dish") or c.get("new_dish") or c.get("original_dish")
        qty = c.get("quantity", 1)
        
        if action == "remove":
            parts.append(f"{dish} remove kar diya hai")
        elif action == "cancel_all":
            return "Theek hai, pura order cancel kar diya hai."
        elif action == "modify" or action == "quantity_change":
            if c.get("original_dish") and c.get("new_dish"):
                parts.append(f"{c['original_dish']} ki jagah {c['new_dish']} add kar diya hai")
            else:
                parts.append(f"{dish} update kar diya hai")
        elif action == "add":
            parts.append(f"{qty} {dish} add kar diya hai")
            
    if not parts:
        return "Theek hai, order update kar diya hai."
        
    feedback = "Theek hai, " + ", ".join(parts[:-1])
    if len(parts) > 1:
        feedback += " aur " + parts[-1]
    else:
        feedback = "Theek hai, " + parts[0]
        
    return feedback + "."


def get_time_based_greeting(lang_code: str = "hi-IN") -> str:
    """
    Returns a real-time, context-aware greeting based on India Standard Time (IST).
    Picks Good Morning / Good Afternoon / Good Evening depending on the hour.
    """
    from datetime import datetime, timezone, timedelta

    # India Standard Time = UTC+5:30
    IST = timezone(timedelta(hours=5, minutes=30))
    hour = datetime.now(IST).hour

    if 5 <= hour < 12:
        slot = "morning"
    elif 12 <= hour < 17:
        slot = "afternoon"
    elif 17 <= hour < 21:
        slot = "evening"
    else:
        slot = "night"

    greetings = {
        "gu-IN": {
            "morning":   "Shubh Savaar!",
            "afternoon": "Shubh Bapor!",
            "evening":   "Shubh Saanj!",
            "night":     "Shubh Raatri!",
        },
        "hi-IN": {
            "morning":   "Shubh Prabhat!",
            "afternoon": "Shubh Dopahar!",
            "evening":   "Shubh Sandhya!",
            "night":     "Shubh Ratri!",
        },
        "en-IN": {
            "morning":   "Good morning!",
            "afternoon": "Good afternoon!",
            "evening":   "Good evening!",
            "night":     "Good evening!",
        },
    }

    return greetings.get(lang_code, greetings["hi-IN"])[slot]
