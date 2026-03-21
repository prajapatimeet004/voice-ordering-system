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

def get_correction_feedback_text(modifications: List[str]) -> str:
    """Generates feedback for corrections (additions/removals)."""
    return "Got it. I've updated your order accordingly."
