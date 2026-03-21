from classifier_service import classify_order
import json

def reproduce():
    test_cases = [
        "Mohan Josh ane 10 Nan",
        "2 Burger and 1 Chai",
        "Paneer Tikka sathe 2 Butter Naan",
        "Masala Dosa, Paper Dosa ane 3 Coffee",
        "Mutton Rogan Josh one and 10 nan"
    ]
    for transcript in test_cases:
        print(f"\nTesting: '{transcript}'")
        result = classify_order(transcript)
        print(json.dumps(result, indent=4))

if __name__ == "__main__":
    reproduce()
