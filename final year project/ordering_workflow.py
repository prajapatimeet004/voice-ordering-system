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

def is_correction_phrase(text):
    """Checks if a phrase contains words indicating negation or replacement using semantic similarity."""
    from correction_service import detect_correction
    # We use a slightly lower threshold for individual phrases
    return detect_correction(text, threshold=0.85)

def apply_confirmed_corrections(final_confirmed_order, confirmed_corrections):
    """
    Applies a list of confirmed corrections to the final consolidated order.
    Returns (updated_order, changed, unavailable_list).
    Now with granular addon management and availability checks.
    """
    from classifier_service import fuzzy_match_dish
    from rapidfuzz import fuzz, process
    import inventory_service
    changed = False
    unavailable_list = []
    
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
                    target_orig = mapped_orig.strip() if (score_orig > 0.6 and mapped_orig.strip() in final_confirmed_order) else (orig_dish.strip() if orig_dish.strip() in final_confirmed_order else None)
                    if target_orig:
                        del final_confirmed_order[target_orig]
                        changed = True
                        print(f"DEBUG Correction: Removed '{target_orig}' during modification-replacement")
                
                # 2. Handle addition of new dish
                if new_dish:
                    mapped_new, score_new = fuzzy_match_dish(new_dish)
                    mapped_new = mapped_new.strip()
                    
                    if score_new > 0.6:
                        # Check Availability
                        is_avail, stock = inventory_service.check_availability(mapped_new, qty)
                        if not is_avail:
                            print(f"DEBUG Correction: '{mapped_new}' is out of stock.")
                            unavailable_list.append(mapped_new)
                            if stock <= 0: continue
                        
                        existing_val = final_confirmed_order.get(mapped_new, {"quantity": 0, "addons": []})
                        if not isinstance(existing_val, dict): existing_val = {"quantity": existing_val, "addons": []}
                        
                        if is_rel:
                            final_qty = existing_val["quantity"] + qty
                        else:
                            final_qty = qty
                            
                        # Granular Addon Management
                        new_addons_list = corr.get("addons", [])
                        orig_addon = corr.get("original_addon")
                        new_addon_val = corr.get("new_addon")
                        current_addons = existing_val.get("addons", [])
                        final_addons = list(current_addons)
                        
                        if orig_addon and new_addon_val:
                            match = process.extractOne(orig_addon, current_addons, scorer=fuzz.token_set_ratio) if current_addons else None
                            if match and match[1] > 70:
                                final_addons.remove(match[0])
                                final_addons.append(new_addon_val)
                        
                        for na in new_addons_list:
                            if na == new_addon_val: continue
                            match = process.extractOne(na, current_addons, scorer=fuzz.token_set_ratio) if current_addons else None
                            if match and match[1] > 70:
                                if is_correction_phrase(na):
                                    if match[0] in final_addons: final_addons.remove(match[0])
                            else:
                                if not is_correction_phrase(na): final_addons.append(na)
                        
                        if final_qty <= 0:
                            if mapped_new in final_confirmed_order:
                                del final_confirmed_order[mapped_new]
                                changed = True
                        else:
                            final_confirmed_order[mapped_new] = {"quantity": final_qty, "addons": list(set(final_addons))}
                            changed = True
                    else:
                        print(f"DEBUG Correction: REJECTED '{new_dish}' (Not in menu)")
            else:
                # Modifier-only update
                dish = corr.get("dish")
                mapped_dish, score = fuzzy_match_dish(dish)
                target_dish = mapped_dish if (score > 0.5 and mapped_dish in final_confirmed_order) else (dish if dish in final_confirmed_order else None)
                
                if target_dish:
                    # Check Availability if increasing qty
                    if is_rel and qty > 0:
                        is_avail, _ = inventory_service.check_availability(target_dish, qty)
                        if not is_avail: unavailable_list.append(target_dish)

                    val = final_confirmed_order[target_dish]
                    if not isinstance(val, dict): val = {"quantity": val, "addons": []}
                    final_qty = val["quantity"] + qty if is_rel else qty
                    val["quantity"] = final_qty
                        
                    # Handle addons...
                    new_addons_list = corr.get("addons", [])
                    current_addons = val.get("addons", [])
                    final_addons = list(current_addons)
                    for na in new_addons_list:
                        match = process.extractOne(na, current_addons, scorer=fuzz.token_set_ratio) if current_addons else None
                        if match and match[1] > 70:
                            if is_correction_phrase(na):
                                if match[0] in final_addons: final_addons.remove(match[0])
                        else:
                            if not is_correction_phrase(na): final_addons.append(na)

                        # Use intelligent merge
                        from addon_extractor import extract_addons, merge_structured_addons
                        new_structured = extract_addons(" ".join(new_addons_list))["addons"]
                        val["addons"] = merge_structured_addons(current_addons, new_structured)
                        final_confirmed_order[target_dish] = val
                        changed = True
                else:
                    if score > 0.5:
                         # Availability check for new item
                         is_avail, _ = inventory_service.check_availability(mapped_dish, qty)
                         if is_avail:
                            final_confirmed_order[mapped_dish] = {"quantity": qty, "addons": corr.get("addons", [])}
                            changed = True
                         else:
                            unavailable_list.append(mapped_dish)
        
        elif action == "remove":
            dish = corr.get("dish")
            mapped_dish, score = fuzzy_match_dish(dish)
            target = mapped_dish if (score > 0.5 and mapped_dish in final_confirmed_order) else (dish if dish in final_confirmed_order else None)
            if target:
                del final_confirmed_order[target]
                changed = True

        elif action == "quantity_change":
            dish = corr.get("dish")
            mapped_dish, score = fuzzy_match_dish(dish)
            target = mapped_dish if (score > 0.5 and mapped_dish in final_confirmed_order) else (dish if dish in final_confirmed_order else None)
            if target:
                final_qty = final_confirmed_order[target]["quantity"] + qty if is_rel else qty
                if is_rel and qty > 0:
                    is_avail, _ = inventory_service.check_availability(target, qty)
                    if not is_avail: unavailable_list.append(target)

                if final_qty <= 0:
                    del final_confirmed_order[target]
                else:
                    final_confirmed_order[target]["quantity"] = final_qty
                changed = True

        elif action == "cancel_all":
            final_confirmed_order.clear()
            changed = True
            
    return final_confirmed_order, changed, unavailable_list
