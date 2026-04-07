try:
    import audioop
except ImportError:
    try:
        import audioopy
        sys.modules['audioop'] = audioopy
    except ImportError:
        pass

import asyncio
import uuid
import os
import json
from dotenv import load_dotenv
load_dotenv()
from audio_utils import record_audio, split_wav, get_vad_model
from transcription_service import transcribe_chunk, close_client
# Lazy imports for classifier and correction

TOTAL_TABLES = 5
CURRENT_TABLE = "table_1"

orders = {
    f"table_{i}": {
        "user_id": f"table_{i}_{str(uuid.uuid4())[:8]}",
        "segments": [],
        "full_transcript": "",
        "corrections": []
    }
    for i in range(1, TOTAL_TABLES + 1)
}

async def main():
    import threading
    # Pre-load/Warm up AI models in a background thread so recorder starts immediately
    def warm_up_models():
        try:
            from audio_utils import get_vad_model
            from classifier_service import get_embedding_model
            get_vad_model()
            get_embedding_model()
        except Exception as e:
            print(f"DEBUG: Warm up error: {e}")
    
    background_worker = threading.Thread(target=warm_up_models, daemon=True)
    background_worker.start()

    raw_audio_path = "raw_session.wav"
    cleaned_audio_path = "cleaned_session.wav"

    # Start recording
    print("Voice Ordering System Started")
    record_audio(raw_audio_path) # records until Ctrl+C

    if not os.path.exists(raw_audio_path):
        print("No audio recorded.")
        return

    # Process audio
    print("\nProcessing recorded session...")
    
    # We skip global noise reduction because Silero VAD handles noise much better
    # and it makes processing much faster.
    chunks = split_wav(raw_audio_path, chunk_duration=20)
    print(f"Split into {len(chunks)} chunks")

    for i, chunk in enumerate(chunks):
        print(f"\nProcessing chunk {i+1}/{len(chunks)}")
        await transcribe_chunk(chunk, orders, CURRENT_TABLE)

    # Cleanup
    if os.path.exists(raw_audio_path):
        os.remove(raw_audio_path)
    if os.path.exists(cleaned_audio_path):
        os.remove(cleaned_audio_path)

    print("\nFINAL TRANSCRIPT:")
    full_transcript = orders[CURRENT_TABLE]["full_transcript"].strip()
    print(f"'{full_transcript}'")

    if full_transcript:
        # Check for corrections in the ENTIRE final transcript
        from correction_service import detect_correction, process_correction
        if detect_correction(full_transcript):
            print("\nDEBUG: Analyzing transcript for corrections...")
            correction_data_all = process_correction(full_transcript)
            
            for correction_data in correction_data_all:
                if correction_data.get("correction_found"):
                    action = correction_data.get("action")
                    qty = correction_data.get("quantity", 1)
                    
                    if action == "modify":
                        orig = correction_data.get("original_dish")
                        new_d = correction_data.get("new_dish")
                        prompt = f"I heard a correction: replace {orig} with {new_d} (qty: {qty}). Correct? (y/n): "
                    elif action == "remove":
                        dish = correction_data.get("dish")
                        prompt = f"I heard a correction: remove {dish}. Correct? (y/n): "
                    elif action == "quantity_change":
                        dish = correction_data.get("dish")
                        prompt = f"I heard a correction: change {dish} quantity to {qty}. Correct? (y/n): "
                    else: # cancel_all
                        prompt = f"I heard a correction: cancel entire order. Correct? (y/n): "

                    # Ask for confirmation
                    while True:
                        user_confirm = input(prompt).strip().lower()
                        if user_confirm == 'y':
                            orders[CURRENT_TABLE]["corrections"].append(correction_data)
                            print("Correction confirmed and saved.")
                            break
                        elif user_confirm == 'n':
                            print("Correction ignored.")
                            break
                        else:
                            print("Please enter 'y' or 'n'.")

        print("\nCLASSIFYING ORDER (Groq LLM)...")
        from classifier_service import classify_order
        classification_result = classify_order(full_transcript)
        
        if "error" in classification_result:
            print(f"⚠️ Error during classification: {classification_result['error']}")
            return

        final_confirmed_order = classification_result.get("confirmed", {})
        uncertain_items = classification_result.get("needs_confirmation", [])
        not_in_menu = classification_result.get("not_in_menu", [])

        if uncertain_items:
            print("\n--- Some items were unclear. Please confirm: ---")
            for item in uncertain_items:
                orig = item['original']
                sugg = item['suggested']
                qty = item['quantity']
                
                # Manual confirmation loop
                while True:
                    choice = input(f"Did you mean '{sugg}' for '{orig}' (qty: {qty})? (y/n): ").strip().lower()
                    if choice == 'y':
                        final_confirmed_order[sugg] = final_confirmed_order.get(sugg, 0) + qty
                        print(f"Added {qty} {sugg} to order.")
                        break
                    elif choice == 'n':
                        print(f"Skipped '{orig}'.")
                        break
                    else:
                        print("Please enter 'y' for Yes or 'n' for No.")

        if not_in_menu:
            print("\n--- Items not on our menu: ---")
            for dish in not_in_menu:
                print(f"❌ Sorry, '{dish}' is not in the menu. Please order something else instead.")

        print("\nFINAL CONSOLIDATED ORDER:")
        if final_confirmed_order:
            print(json.dumps(final_confirmed_order, indent=4))
        else:
            print("No items confirmed in the order.")
        
        # Apply manual corrections to the classified order
        for corr in orders[CURRENT_TABLE]["corrections"]:
            action = corr.get("action")
            qty = corr.get("quantity", 1)
            from classifier_service import fuzzy_match_dish
            
            if action == "modify":
                orig_dish = corr.get("original_dish")
                new_dish = corr.get("new_dish")
                
                # Match original to remove it
                mapped_orig, score_orig, _ = fuzzy_match_dish(orig_dish)
                if score_orig > 0.5 and mapped_orig in final_confirmed_order:
                    del final_confirmed_order[mapped_orig]
                    print(f"Applied correction: Removed {mapped_orig} (to be replaced)")
                
                # Match new to add it
                mapped_new, score_new, _ = fuzzy_match_dish(new_dish)
                if score_new < 0.5: mapped_new = new_dish
                final_confirmed_order[mapped_new] = final_confirmed_order.get(mapped_new, 0) + qty
                print(f"Applied correction: Added {mapped_new} instead.")

            elif action == "remove":
                dish = corr.get("dish")
                mapped_dish, score, _ = fuzzy_match_dish(dish)
                if score > 0.5 and mapped_dish in final_confirmed_order:
                    del final_confirmed_order[mapped_dish]
                    print(f"Applied correction: Removed {mapped_dish}")
                elif dish in final_confirmed_order:
                    del final_confirmed_order[dish]
                    print(f"Applied correction: Removed {dish}")

            elif action == "quantity_change":
                dish = corr.get("dish")
                mapped_dish, score, _ = fuzzy_match_dish(dish)
                if score < 0.5: mapped_dish = dish
                final_confirmed_order[mapped_dish] = qty
                print(f"Applied correction: Updated {mapped_dish} to {qty}")

            elif action == "cancel_all":
                final_confirmed_order = {}
                print("Applied correction: Cancelled entire order")

        # Store it back in the orders dict
        orders[CURRENT_TABLE]["classified_order"] = final_confirmed_order
    else:
        print("\n⚠️ No transcript found to classify.")

    # Cleanly close the async client to avoid Windows event loop warnings
    await close_client()

if __name__ == "__main__":
    asyncio.run(main())
