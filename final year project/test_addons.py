from classifier_service import classify_order
import json

def test_addons():
    test_cases = [
        {
            "transcript": "one masala dosa tikhu rakhjo",
            "expected_addon": "less_spicy"
        },
        {
            "transcript": "ek dosa dungli vagar",
            "expected_addon": "no_onion"
        },
        {
            "transcript": "thodu ochu tikhu burger aapo",
            "expected_addon": "less_spicy"
        },
        {
            "transcript": "paneer tikka ma lasun na rakhta",
            "expected_addon": "no_garlic"
        },
        {
            "transcript": "ek pizza extra cheese and extra crispy",
            "expected_addons": ["extra_cheese", "extra_crispy"]
        },
        {
            "transcript": "thodu ochu tel valo dosa",
            "expected_addon": "less_oil"
        }
    ]

    print("--- Starting Addon Detection Verification ---\n")
    passed = 0
    for i, tc in enumerate(test_cases):
        print(f"Test case {i+1}: '{tc['transcript']}'")
        result = classify_order(tc['transcript'])
        
        # Check if any item (confirmed or needs_confirmation) has the expected addon
        found_addons = []
        for dish, details in result.get("confirmed", {}).items():
            found_addons.extend(details.get("addons", []))
        for item in result.get("needs_confirmation", []):
            found_addons.extend(item.get("addons", []))
        
        success = False
        if "expected_addons" in tc:
            if all(a in found_addons for a in tc["expected_addons"]):
                success = True
        elif tc["expected_addon"] in found_addons:
            success = True
            
        if success:
            print(f"Result: PASS (Detected: {found_addons})")
            passed += 1
        else:
            print(f"Result: FAIL (Detected: {found_addons}, Expected: {tc.get('expected_addon') or tc.get('expected_addons')})")
        print("-" * 30)

    print(f"\nFinal Result: {passed}/{len(test_cases)} tests passed.")

if __name__ == "__main__":
    test_addons()
