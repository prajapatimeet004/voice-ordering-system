import os
import json
from audio_utils import split_wav, safe_remove
from transcription_service import transcribe_chunk

def get_full_transcript(orders, table_id):
    return orders[table_id]["full_transcript"].strip()

async def transcribe_audio(file_path, noise_profile_bytes=None):
    """Transcribes audio file chunks and returns (transcript, processed_audio_bytes, chunks_data) for THIS file only."""
    if not os.path.exists(file_path):
        return "", None, []
    
    import io
    from pydub import AudioSegment
    
    # Use a dummy orders object to avoid polluting the global state
    temp_orders = {"temp": {"full_transcript": "", "segments": []}}
    processed_audio_chunks = []
    chunks_data = [] # List of {"audio": bytes, "transcript": str}
    
    chunks = split_wav(file_path, chunk_duration=20, noise_profile_bytes=noise_profile_bytes)
    for chunk in chunks:
        # Track transcript before this chunk
        prev_len = len(temp_orders["temp"]["segments"])
        
        await transcribe_chunk(chunk, temp_orders, "temp", processed_audio_list=processed_audio_chunks)
        
        # Check if a new segment was added
        if len(temp_orders["temp"]["segments"]) > prev_len:
            latest_segment = temp_orders["temp"]["segments"][-1]
            latest_audio = processed_audio_chunks[-1]
            chunks_data.append({
                "audio": latest_audio,
                "transcript": latest_segment["text"].strip()
            })
            
        if os.path.exists(chunk):
            safe_remove(chunk)
    
    transcript = temp_orders["temp"]["full_transcript"].strip()
    
    # Reconstruct processed audio
    processed_audio_bytes = None
    if processed_audio_chunks:
        combined = AudioSegment.empty()
        for chunk_bytes in processed_audio_chunks:
            try:
                segment = AudioSegment.from_file(io.BytesIO(chunk_bytes), format="wav")
                combined += segment
            except Exception as e:
                print(f"WARNING: Skipping corrupted audio chunk: {e}")
        
        buffer = io.BytesIO()
        combined.export(buffer, format="wav")
        processed_audio_bytes = buffer.getvalue()
    
    return transcript, processed_audio_bytes, chunks_data

def apply_confirmed_corrections(final_confirmed_order, confirmed_corrections):
    """Applies a list of confirmed corrections to the final consolidated order."""
    from classifier_service import fuzzy_match_dish
    
    for corr in confirmed_corrections:
        action = corr.get("action")
        qty = corr.get("quantity", 1)
        is_rel = corr.get("is_relative", False)
        
        if action == "modify":
            orig_dish = corr.get("original_dish")
            new_dish = corr.get("new_dish")
            
            if orig_dish or new_dish:
                # 1. Handle removal of original if it exists
                if orig_dish:
                    mapped_orig, score_orig = fuzzy_match_dish(orig_dish)
                    target_orig = mapped_orig if (score_orig > 0.5 and mapped_orig in final_confirmed_order) else (orig_dish if orig_dish in final_confirmed_order else None)
                    if target_orig:
                        del final_confirmed_order[target_orig]
                        print(f"DEBUG Correction: Removed '{target_orig}'")
                
                # 2. Handle addition of new dish
                if new_dish:
                    mapped_new, score_new = fuzzy_match_dish(new_dish)
                    # STRICT ENFORCEMENT: Only add if it's in the menu
                    if score_new > 0.5:
                        existing_val = final_confirmed_order.get(mapped_new, {"quantity": 0, "addons": []})
                        if not isinstance(existing_val, dict): existing_val = {"quantity": existing_val, "addons": []}
                        
                        if is_rel:
                            final_qty = existing_val["quantity"] + qty
                        else:
                            final_qty = qty
                            
                        final_confirmed_order[mapped_new] = {
                            "quantity": final_qty, 
                            "addons": list(set(existing_val.get("addons", []) + corr.get("addons", [])))
                        }
                        print(f"DEBUG Correction: Added/Updated '{mapped_new}' to qty {final_qty}")
                    else:
                        print(f"DEBUG Correction: REJECTED '{new_dish}' (Not in menu, score {score_new:.2f})")
            else:
                # Modifier-only update on an existing dish (dish specified in 'dish' field)
                dish = corr.get("dish")
                mapped_dish, score = fuzzy_match_dish(dish)
                target_dish = mapped_dish if (score > 0.5 and mapped_dish in final_confirmed_order) else (dish if dish in final_confirmed_order else None)
                
                if target_dish:
                    val = final_confirmed_order[target_dish]
                    if not isinstance(val, dict): val = {"quantity": val, "addons": []}
                    
                    if is_rel:
                        final_qty = val["quantity"] + qty
                    else:
                        final_qty = qty
                        
                    val["quantity"] = final_qty
                    val["addons"] = list(set(val.get("addons", []) + corr.get("addons", [])))
                    final_confirmed_order[target_dish] = val
                    print(f"DEBUG Correction: Updated '{target_dish}' to qty {final_qty}")
                else:
                    print(f"DEBUG Correction: No target dish found for modifier update: '{dish}'")

        elif action == "remove":
            dish = corr.get("dish")
            mapped_dish, score = fuzzy_match_dish(dish)
            if score > 0.5 and mapped_dish in final_confirmed_order:
                del final_confirmed_order[mapped_dish]
                print(f"DEBUG Correction: Removed '{mapped_dish}'")
            elif dish in final_confirmed_order:
                del final_confirmed_order[dish]
                print(f"DEBUG Correction: Removed '{dish}'")

        elif action == "quantity_change":
            dish = corr.get("dish")
            mapped_dish, score = fuzzy_match_dish(dish)
            target_dish = mapped_dish if (score > 0.5 and mapped_dish in final_confirmed_order) else (dish if dish in final_confirmed_order else None)
            
            if target_dish:
                val = final_confirmed_order[target_dish]
                if not isinstance(val, dict): val = {"quantity": val, "addons": []}
                
                if is_rel:
                    final_qty = val["quantity"] + qty
                else:
                    final_qty = qty
                
                val["quantity"] = final_qty
                final_confirmed_order[target_dish] = val
                print(f"DEBUG Correction: Changed quantity of '{target_dish}' to {final_qty}")

        elif action == "cancel_all":
            final_confirmed_order.clear()
            print("DEBUG Correction: Cancelled entire order")
            
    return final_confirmed_order
