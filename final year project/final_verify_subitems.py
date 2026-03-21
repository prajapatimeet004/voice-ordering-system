from classifier_service import classify_order
import json

def final_verify():
    test_cases = [
        "Chole Bhature ane ek Bhature",
        "Pav Bhaji sathe 2 Pav",
        "Misal Pav ane ek extra Pav",
        "Mohan Josh ane 10 Nan" # To ensure original fix still works
    ]
    for transcript in test_cases:
        print(f"\nTesting: '{transcript}'")
        result = classify_order(transcript)
        print(json.dumps(result, indent=4))

if __name__ == "__main__":
    final_verify()
