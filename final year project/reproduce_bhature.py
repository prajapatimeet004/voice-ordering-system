from classifier_service import classify_order
import json

def reproduce():
    transcript = "Chole Bhature ane ek Bhature"
    print(f"Testing: '{transcript}'")
    result = classify_order(transcript)
    print(json.dumps(result, indent=4))

if __name__ == "__main__":
    reproduce()
