import re
from rapidfuzz import process, fuzz
from classifier_service import INDIAN_MENU, match_dish_with_embeddings

dish = "palarmeo pasta"
print(f"Testing fuzzy match for: '{dish}'")

# Test embeddings/hybrid
match, score, is_ambiguous = match_dish_with_embeddings(dish)
print(f"Hybrid Match: {match} (Score: {score:.2f}, Ambiguous: {is_ambiguous})")

# Test raw rapidfuzz
best_match = process.extractOne(dish, INDIAN_MENU, scorer=fuzz.WRatio)
print(f"Rapidfuzz WRatio: {best_match}")

best_match_token = process.extractOne(dish, INDIAN_MENU, scorer=fuzz.token_set_ratio)
print(f"Rapidfuzz Token Set: {best_match_token}")
