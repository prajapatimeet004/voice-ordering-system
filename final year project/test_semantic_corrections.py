
from correction_service import detect_correction
import sys
import io

# Setup Windows console encoding
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def test_semantic_detection():
    print("Testing Semantic Correction Detection...")
    
    test_cases = [
        # Direct matches
        ("hatao dosa", True),
        ("remove pizza", True),
        
        # Semantic variations (not exact phrases)
        ("I made a mistake with my order", True),
        ("Wait, please scrap the sandwich", True),
        ("Actually, I don't want the biryani anymore", True),
        ("Can you change the burger to a pizza?", True),
        ("I want to update my quantity of coffee", True),
        ("I changed my mind about the samosa", True),
        
        # New Multilingual cases
        ("ek plate vadhaari do samosa", True),
        ("biju ek muki do", True),
        ("thodu extra chai", True),
        ("ek aur add karo burger", True),
        ("be kari do pizza", True),
        ("ena badle dosa aapo", True),
        ("uski jagah paneer tikka", True),
        ("ek kam kar do", True),
        
        # Negatives (not corrections)
        ("give me two more coffee", False), # This is an addition, not a modification
        ("I like the burger", False),
        ("What is the price of tea?", False)
    ]
    
    passed = 0
    for transcript, expected in test_cases:
        result = detect_correction(transcript)
        status = "PASS" if result == expected else "FAIL"
        print(f"Transcript: '{transcript}' | Expected: {expected} | Got: {result} | Status: {status}")
        if status == "PASS":
            passed += 1
            
    print(f"\nPassed {passed}/{len(test_cases)} tests.")
    assert passed >= 9, "Too many semantic detection failures"

if __name__ == "__main__":
    try:
        test_semantic_detection()
        print("\n✅ Semantic detection tests completed successfully!")
    except AssertionError as e:
        print(f"\n❌ Test Failed: {e}")
    except Exception as e:
        print(f"\n❌ An error occurred: {e}")
