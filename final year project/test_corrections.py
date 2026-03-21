import json
from ordering_workflow import apply_confirmed_corrections

def test_corrections():
    print("--- Starting Correction Logic Verification ---\n")
    
    # Initial order state
    order = {
        "Masala Dosa": {"quantity": 1, "addons": []},
        "Burger": {"quantity": 1, "addons": []}
    }
    print(f"Initial Order: {json.dumps(order, indent=4)}")

    # Test cases for corrections
    test_cases = [
        {
            "description": "Add one more Masala Dosa (Relative)",
            "correction": {
                "action": "modify",
                "dish": "masala dosa",
                "quantity": 1,
                "is_relative": True,
                "addons": [],
                "correction_found": True
            },
            "expected_qty": 2,
            "dish_name": "Masala Dosa"
        },
        {
            "description": "Add Ben Ali Nepal (Not in menu)",
            "correction": {
                "action": "modify",
                "original_dish": "",
                "new_dish": "Ben Ali Nepal",
                "quantity": 1,
                "is_relative": False,
                "addons": [],
                "correction_found": True
            },
            "should_not_exist": "Ben Ali Nepal"
        },
        {
            "description": "Set Burger quantity to 5 (Absolute)",
            "correction": {
                "action": "quantity_change",
                "dish": "burger",
                "quantity": 5,
                "is_relative": False,
                "correction_found": True
            },
            "expected_qty": 5,
            "dish_name": "Burger"
        }
    ]

    for i, tc in enumerate(test_cases):
        print(f"\nTest {i+1}: {tc['description']}")
        order = apply_confirmed_corrections(order, [tc['correction']])
        
        passed = True
        if "expected_qty" in tc:
            actual_qty = order.get(tc['dish_name'], {}).get("quantity", 0)
            if actual_qty != tc['expected_qty']:
                print(f"FAILED: Expected {tc['dish_name']} qty {tc['expected_qty']}, got {actual_qty}")
                passed = False
            else:
                print(f"PASSED: {tc['dish_name']} qty is {actual_qty}")
        
        if "should_not_exist" in tc:
            if tc['should_not_exist'] in order:
                print(f"FAILED: {tc['should_not_exist']} should NOT be in order, but it is.")
                passed = False
            else:
                print(f"PASSED: {tc['should_not_exist']} was correctly rejected.")
        
        print(f"Current Order State: {json.dumps(order)}")

    print("\n--- Verification Complete ---")

if __name__ == "__main__":
    test_corrections()
