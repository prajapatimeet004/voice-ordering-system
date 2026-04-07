import os
import json
from audio_utils import split_wav, safe_remove
from transcription_service import transcribe_chunk

def get_full_transcript(orders, table_id):
    return orders[table_id]["full_transcript"].strip()

async def transcribe_with_context(chunk_path, index, semaphore):
    """Wrapper to handle parallel transcription with index tracking and isolated state."""
    async with semaphore:
        # Each task gets its OWN local state to avoid race conditions on shared lists
        local_orders = {"temp": {"full_transcript": "", "segments": []}}
        local_audio_list = []
        
        from transcription_service import transcribe_chunk
        await transcribe_chunk(chunk_path, local_orders, "temp", processed_audio_list=local_audio_list)
        
        # Return result tagged with index for ordered merging
        return {
            "index": index,
            "segment": local_orders["temp"]["segments"][0] if local_orders["temp"]["segments"] else None,
            "audio": local_audio_list[0] if local_audio_list else None,
            "chunk_path": chunk_path
        }

async def transcribe_audio(file_path, noise_profile_bytes=None):
    """Transcribes audio file chunks in parallel and returns (transcript, processed_audio_bytes, chunks_data)."""
    if not os.path.exists(file_path):
        return "", None, []
    
    import io
    import asyncio
    from pydub import AudioSegment
    
    temp_orders = {"temp": {"full_transcript": "", "segments": []}}
    processed_audio_chunks = []
    chunks_data = [] # List of {"audio": bytes, "transcript": str}
    
    # 1. Split audio into chunks
    chunks = split_wav(file_path, chunk_duration=20, noise_profile_bytes=noise_profile_bytes)
    if not chunks:
        return "", None, []

    # 2. Process chunks in parallel with a concurrency limit (Semaphore)
    semaphore = asyncio.Semaphore(3) # Max 3 parallel API calls
    tasks = [transcribe_with_context(chunk, i, semaphore) for i, chunk in enumerate(chunks)]
    
    print(f"DEBUG: Starting parallel transcription for {len(chunks)} chunks (limit: 3)...")
    results = await asyncio.gather(*tasks)
    
    # 3. Sort results by original index to preserve chronological order
    results.sort(key=lambda x: x["index"])
    
    # 4. Merge results back into the final order state and audio lists
    for res in results:
        if res["segment"]:
            txt = res["segment"]["text"].strip()
            temp_orders["temp"]["segments"].append(res["segment"])
            temp_orders["temp"]["full_transcript"] += " " + txt
            
            if res["audio"]:
                processed_audio_chunks.append(res["audio"])
                chunks_data.append({
                    "audio": res["audio"],
                    "transcript": txt
                })
        
        # Cleanup original chunk file
        if os.path.exists(res["chunk_path"]):
            from audio_utils import safe_remove
            safe_remove(res["chunk_path"])
    
    transcript = temp_orders["temp"]["full_transcript"].strip()
    
    # Reconstruct processed audio from ordered chunks
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
                target_orig = None
                if orig_dish:
                    mapped_orig, score_orig, _ = fuzzy_match_dish(orig_dish)
                    mapped_orig = mapped_orig.strip()
                    
                    # Try to find the original in final_confirmed_order (handles "half Masala Dosa")
                    if mapped_orig in final_confirmed_order:
                        target_orig = mapped_orig
                    elif orig_dish in final_confirmed_order:
                        target_orig = orig_dish
                    else:
                        # Search for portioned versions or similar keys
                        for k in final_confirmed_order.keys():
                            if k.endswith(f" {mapped_orig}") or k.endswith(f" {orig_dish}"):
                                target_orig = k
                                break
                        
                        if not target_orig:
                            # Fuzzy match against keys (High threshold for removals)
                            match = process.extractOne(mapped_orig, list(final_confirmed_order.keys()), scorer=fuzz.token_set_ratio)
                            if match and match[1] > 95:
                                target_orig = match[0]

                    if target_orig:
                        del final_confirmed_order[target_orig]
                        changed = True
                        print(f"DEBUG Correction: Removed '{target_orig}' during modification-replacement")
                
                # 2. Handle addition of new dish
                if new_dish:
                    mapped_new, score_new, is_amb_new = fuzzy_match_dish(new_dish)
                    mapped_new = mapped_new.strip()
                    
                    if score_new >= 0.30:
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
                mapped_dish, score, _ = fuzzy_match_dish(dish)
                mapped_dish = mapped_dish.strip()
                
                target_dish = None
                if mapped_dish in final_confirmed_order:
                    target_dish = mapped_dish
                elif dish in final_confirmed_order:
                    target_dish = dish
                else:
                    for k in final_confirmed_order.keys():
                        if k.endswith(f" {mapped_dish}") or k.endswith(f" {dish}"):
                            target_dish = k
                            break
                    if not target_dish:
                        match = process.extractOne(mapped_dish, list(final_confirmed_order.keys()), scorer=fuzz.token_set_ratio)
                        if match and match[1] > 95:
                            target_dish = match[0]

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
            mapped_dish, score, _ = fuzzy_match_dish(dish)
            mapped_dish = mapped_dish.strip()
            
            target = None
            if mapped_dish in final_confirmed_order:
                target = mapped_dish
            elif dish in final_confirmed_order:
                target = dish
            else:
                for k in final_confirmed_order.keys():
                    if k.endswith(f" {mapped_dish}") or k.endswith(f" {dish}"):
                        target = k
                        break
                if not target:
                    match = process.extractOne(mapped_dish, list(final_confirmed_order.keys()), scorer=fuzz.token_set_ratio)
                    if match and match[1] > 95:
                        target = match[0]
            
            if target:
                del final_confirmed_order[target]
                changed = True

        elif action == "quantity_change":
            dish = corr.get("dish")
            mapped_dish, score, _ = fuzzy_match_dish(dish)
            mapped_dish = mapped_dish.strip()
            
            target = None
            if mapped_dish in final_confirmed_order:
                target = mapped_dish
            elif dish in final_confirmed_order:
                target = dish
            else:
                for k in final_confirmed_order.keys():
                    if k.endswith(f" {mapped_dish}") or k.endswith(f" {dish}"):
                        target = k
                        break
                if not target:
                    match = process.extractOne(mapped_dish, list(final_confirmed_order.keys()), scorer=fuzz.token_set_ratio)
                    if match and match[1] > 95:
                        target = match[0]

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
