from classifier_service import classify_order
import json

def debug_test_3():
    transcript = "thodu vadhu tikhu burger aapo"
    print(f"Testing: '{transcript}'")
    result = classify_order(transcript)
    print(json.dumps(result, indent=4))

if __name__ == "__main__":
    debug_test_3()
