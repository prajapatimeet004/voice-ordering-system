from classifier_service import fuzzy_match_dish

def test_match():
    dish = "Ajwa chawal"
    match, score = fuzzy_match_dish(dish)
    print(f"Match for '{dish}':")
    print(f"  Result: {match}")
    print(f"  Score: {score:.4f}")

if __name__ == "__main__":
    test_match()
