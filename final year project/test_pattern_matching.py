import json
from classifier_service import classify_order

def test_pattern_matching():
    test_cases = [
        "biryani ma thodu vadhu tikhu rakho",
        "paneer tikka vadhare tikhu banavo",
        "pizza ma extra cheese nakho",
        "burger ma dungli nahi mukta",
        "biryani thodi kam teekhi banao",
        "Masala dosa, paneer tikka, butter chicken, tikka misha. Masala dosa thoda tikka rakhjo. Paneer tikka bhi thoda tikka rakhjo.",
        "pizza with pineapple and magic dust",
        "ek butter chicken ke saath extra naan dena"
    ]
    
    print("Starting Pattern Matching Verification...\n")
    
    for tc in test_cases:
        print(f"--- Testing Transcript: '{tc}' ---")
        result = classify_order(tc)
        print(json.dumps(result, indent=4))
        print("\n" + "="*50 + "\n")

if __name__ == "__main__":
    test_pattern_matching()
