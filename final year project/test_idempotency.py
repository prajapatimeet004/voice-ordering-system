
from ordering_workflow import apply_confirmed_corrections
import sys
import io

# Setup Windows console encoding
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def test_idempotent_modify():
    print("Testing Idempotent Modify (Overwrite instead of Add)...")
    
    # Initial state: 1 Burger and 1 Pizza
    order = {"Burger": 1, "Pizza": 1}
    
    # Correction: Modify Burger to Pizza (quantity 1)
    # If idempotent, the total Pizza count should be 1 (from burger), NOT 2 (1+1)
    corrections = [
        {
            "action": "modify",
            "original_dish": "Burger",
            "new_dish": "Pizza",
            "dish": "",
            "quantity": 1,
            "correction_found": True
        }
    ]
    
    new_order = apply_confirmed_corrections(order.copy(), corrections)
    print(f"Original: {order}")
    print(f"After Modify Burger -> Pizza: {new_order}")
    
    assert new_order.get("Pizza") == 1, "Quantity should be 1 (idempotent), not added to existing count"
    assert "Burger" not in new_order, "Burger should be removed"
    
    print("✅ Idempotent Modify test passed!")

def test_idempotent_quantity_change():
    print("\nTesting Idempotent Quantity Change...")
    order = {"Chai": 2}
    
    # Correction: Change Chai quantity to 1
    corrections = [
        {
            "action": "quantity_change",
            "dish": "Chai",
            "quantity": 1,
            "original_dish": "",
            "new_dish": "",
            "correction_found": True
        }
    ]
    
    new_order = apply_confirmed_corrections(order.copy(), corrections)
    print(f"Original: {order}")
    print(f"After Quantity Change to 1: {new_order}")
    assert new_order.get("Chai") == 1, "Quantity should be set to 1, not added"

    print("✅ Idempotent Quantity Change test passed!")

if __name__ == "__main__":
    try:
        test_idempotent_modify()
        test_idempotent_quantity_change()
        print("\nAll idempotent tests completed successfully!")
    except AssertionError as e:
        print(f"\n[FAIL] Test Failed: {e}")
    except Exception as e:
        print(f"\n[ERROR] An error occurred: {e}")
