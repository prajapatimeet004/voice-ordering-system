import sys
import os
import json
import asyncio

# Ensure correct path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from correction_service import process_correction
import ordering_workflow

async def test_addon_correction():
    current_order = {
        "Masala Dosa": {"quantity": 1, "addons": ["cheese"]}
    }
    
    # Test 1: Addon to existing
    transcript1 = "masala dosa mein extra spicy kar do"
    print(f"\nTranscript 1: {transcript1}")
    current_items = list(current_order.keys())
    corrections1 = process_correction(transcript1, current_order_items=current_items)
    updated1 = ordering_workflow.apply_confirmed_corrections(current_order.copy(), corrections1)
    print(f"Updated Order 1: {json.dumps(updated1, indent=2)}")

    # Test 2: Replace dish with another + addons
    transcript2 = "masala dosa ki jagah ek chicken biryani thodi tikhi wali"
    print(f"\nTranscript 2: {transcript2}")
    corrections2 = process_correction(transcript2, current_order_items=current_items)
    updated2 = ordering_workflow.apply_confirmed_corrections(current_order.copy(), corrections2)
    print(f"Updated Order 2: {json.dumps(updated2, indent=2)}")

if __name__ == "__main__":
    asyncio.run(test_addon_correction())
