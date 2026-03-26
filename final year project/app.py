import sys
import os
from dotenv import load_dotenv
load_dotenv(override=True)
# Ensure the current directory is in the search path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    import audioop
except ImportError:
    try:
        import audioopy
        sys.modules['audioop'] = audioopy
    except ImportError:
        pass

import streamlit as st
import os
import json
import asyncio
import uuid
import tempfile
import base64
import streamlit.components.v1 as components
from audio_utils import get_vad_model, safe_remove
from transcription_service import transcribe_chunk
from classifier_service import classify_order, get_embedding_model
from correction_service import detect_correction, process_correction
from ordering_workflow import apply_confirmed_corrections
import httpx
from tts_service import generate_speech
import shutil
import hashlib
from typing import Optional

API_URL = "http://127.0.0.1:8000"

# Declare Custom Voice Recorder Component
vrecorder_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vrecorder")
_vrecorder_func = components.declare_component("voice_recorder_app", path=vrecorder_path)

def voice_recorder(key=None, autoStart=False):
    """Custom high-performance voice recorder with waveform and timer."""
    return _vrecorder_func(key=key, autoStart=autoStart, default=None)

def decode_base64_audio(base64_string):
    """Decodes base64 audio data from the custom recorder."""
    try:
        if "," in base64_string:
            _, encoded = base64_string.split(",", 1)
        else:
            encoded = base64_string
        return base64.b64decode(encoded)
    except Exception as e:
        st.error(f"Audio decoding error: {e}")
        return None

# Persistent Audio Storage Fix
AUDIO_TEMP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp_audio")
if not os.path.exists(AUDIO_TEMP_DIR):
    os.makedirs(AUDIO_TEMP_DIR)

def get_audio_path(audio_bytes: bytes, prefix: str = "audio") -> str:
    """Saves bytes to a hashed filename in the temp directory and returns the path."""
    if not audio_bytes:
        return ""
    file_hash = hashlib.md5(audio_bytes).hexdigest()
    file_path = os.path.join(AUDIO_TEMP_DIR, f"{prefix}_{file_hash}.wav")
    if not os.path.exists(file_path):
        with open(file_path, "wb") as f:
            f.write(audio_bytes)
    return file_path

def cleanup_temp_audio():
    """Removes all files in the temp_audio directory."""
    if os.path.exists(AUDIO_TEMP_DIR):
        for filename in os.listdir(AUDIO_TEMP_DIR):
            file_path = os.path.join(AUDIO_TEMP_DIR, filename)
            try:
                if os.path.isfile(file_path) or os.path.islink(file_path):
                    os.unlink(file_path)
            except Exception as e:
                print(f"Failed to delete {file_path}. Reason: {e}")

def play_voice(speech_b64):
    """Plays base64 audio in the UI using Data URIs for maximum stability."""
    if speech_b64:
        # Use Data URI for maximum stability and to avoid MediaFileStorageError
        audio_type = "audio/wav"
        st.audio(f"data:{audio_type};base64,{speech_b64}", format=audio_type, autoplay=True)

# Page Configuration
st.set_page_config(page_title="Voice Ordering System", page_icon="🎙️")

st.markdown("""
<style>
    .main { font-family: sans-serif; }
    .order-item {
        padding: 10px;
        border-bottom: 1px solid #eee;
        display: flex;
        justify-content: space-between;
    }
    .confirmed { color: #2ecc71; font-weight: bold; }
    .uncertain { color: #f39c12; }
    .header-text { text-align: center; margin-bottom: 20px; }
    .transcript-box {
        background-color: #f8f9fa;
        border-left: 5px solid #3498db;
        padding: 15px;
        margin-top: 20px;
        border-radius: 5px;
        font-style: italic;
        color: #2c3e50;
    }
    .assistant-box {
        background-color: #e8f4fd;
        border-left: 5px solid #2ecc71;
        padding: 15px;
        margin-top: 10px;
        border-radius: 5px;
        color: #1a5276;
    }
</style>
""", unsafe_allow_html=True)

# Session State Initialization
if "classification_result" not in st.session_state:
    st.session_state.classification_result = {"confirmed": {}, "needs_confirmation": [], "not_in_menu": []}
if "recording_history" not in st.session_state:
    st.session_state.recording_history = []
if "noise_profile" not in st.session_state:
    st.session_state.noise_profile = None
if "models_loaded" not in st.session_state:
    with st.spinner("System initializing..."):
        get_vad_model()
        get_embedding_model()
        st.session_state.models_loaded = True
if "recorder_key" not in st.session_state:
    st.session_state.recorder_key = 1
if "noise_key" not in st.session_state:
    st.session_state.noise_key = 1
if "last_speech" not in st.session_state:
    st.session_state.last_speech = None
if "last_response_text" not in st.session_state:
    st.session_state.last_response_text = ""
    # cleanup_temp_audio() # Initial cleanup on fresh session
if "call_mode" not in st.session_state:
    st.session_state.call_mode = True # Default to True
if "is_listening" not in st.session_state:
    st.session_state.is_listening = True

def reset_order():
    """Completely resets the frontend and backend order state."""
    try:
        httpx.post(f"{API_URL}/order/reset", timeout=5.0)
    except:
        pass # Backend might already be reset or unreachable
    st.session_state.classification_result = {"confirmed": {}, "needs_confirmation": [], "not_in_menu": []}
    st.session_state.recording_history = []
    st.session_state.last_response_text = ""
    st.session_state.pending_corrections = []
    if "last_audio_id" in st.session_state: 
        del st.session_state.last_audio_id
    st.session_state.last_speech = None
    st.session_state.recorder_key += 1 # Force refresh the recorder component
    # cleanup_temp_audio()
    st.rerun()

async def run_workflow(audio_bytes):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
        f.write(audio_bytes)
        temp_path = f.name
    try:
        from ordering_workflow import transcribe_audio
        noise_profile = st.session_state.get("noise_profile")
        current_transcript, processed_audio, _ = await transcribe_audio(temp_path, noise_profile_bytes=noise_profile)
        if not current_transcript:
            st.warning("No speech detected. Please try recording again.")
            return
        
        # Save to disk for stability
        original_audio_path = get_audio_path(audio_bytes, prefix="original")
        processed_audio_path = get_audio_path(processed_audio, prefix="processed") if processed_audio else None
        
        st.session_state.recording_history.append({
            "original_audio_path": original_audio_path, 
            "processed_audio_path": processed_audio_path, 
            "transcript": current_transcript
        })
        
        # Call FastAPI Classify for TTS and logic
        try:
            res = httpx.post(f"{API_URL}/order/classify", data={"transcript": current_transcript}, timeout=60.0)
            if res.status_code == 200:
                data = res.json()
                result = data["classification"]
                st.session_state.classification_result["confirmed"] = data["current_order"]
                st.session_state.classification_result["needs_confirmation"] = result.get("needs_confirmation", [])
                st.session_state.classification_result["not_in_menu"] = result.get("not_in_menu", [])
                st.session_state.last_response_text = data.get("response_text", "")
                
                # Play Speech using Data URI for stability
                if data.get("speech"):
                    st.session_state.last_speech = data["speech"]
                    st.audio(f"data:audio/wav;base64,{data['speech']}", format="audio/wav", autoplay=True)
                
                if data.get("is_finished"):
                    st.success("Order Finished!")
                    st.balloons()
                    st.session_state.call_mode = False # Stop auto-listening when done
                
                # Auto-restart mic removed as per user request
                # if st.session_state.call_mode:
                #     st.session_state.is_listening = True
            else:
                st.error(f"API Error: {res.text}")
        except Exception as e:
            st.error(f"Failed to connect to backend: {e}")
    finally:
        pass # Not deleting temp_path to avoid MediaFileStorageError

# --- Processing Logic ---
if "pending_workflow" not in st.session_state:
    st.session_state.pending_workflow = False

# Sidebar for App Settings
with st.sidebar:
    st.header("Voice Settings")
    # Toggle removed as per user request (Continuous mode is now default)
    
    if st.session_state.last_speech:
        if st.button("🔊 Replay Last Response"):
            play_voice(st.session_state.last_speech)
    if st.button("🗑️ Reset Order", type="primary"):
        reset_order()
    
    st.divider()
    st.write("Capture Noise Profile:")
    noise_data_b64 = voice_recorder(key=f"noise_recorder_{st.session_state.noise_key}")
    
    if noise_data_b64:
        noise_bytes = decode_base64_audio(noise_data_b64)
        if noise_bytes:
            st.session_state.noise_profile = noise_bytes
            st.session_state.noise_key += 1
            st.success("Noise profile saved!")
            st.rerun()

    st.divider()
    from classifier_service import INDIAN_MENU
    with st.expander("Show Available Items"):
        for item in sorted(INDIAN_MENU):
            st.write(f"- {item}")
    
    st.divider()
    st.subheader("🛠️ Inventory Management")
    with st.expander("Update Stock/Availability"):
        inv_dish = st.selectbox("Select Dish", sorted(INDIAN_MENU), key="inv_dish_select")
        inv_change = st.number_input("Change Stock By", value=0, step=1, key="inv_change_input")
        if st.button("Update Stock"):
            try:
                res = httpx.post(f"{API_URL}/inventory/update", data={"dish_name": inv_dish, "change": inv_change})
                if res.status_code == 200:
                    st.success(f"Updated! New stock: {res.json().get('new_stock')}")
                else:
                    st.error(f"Error: {res.text}")
            except Exception as e:
                st.error(f"Failed: {e}")
        
        st.write("---")
        inv_avail = st.toggle("Available", value=True, key="inv_avail_toggle")
        if st.button("Set Availability"):
            try:
                res = httpx.post(f"{API_URL}/inventory/availability", data={"dish_name": inv_dish, "available": inv_avail})
                if res.status_code == 200:
                    st.success(f"Set {inv_dish} to {'Available' if inv_avail else 'Unavailable'} (Stock: {res.json().get('stock')})")
                else:
                    st.error(f"Error: {res.text}")
            except Exception as e:
                st.error(f"Failed: {e}")

# Main UI Layout
st.markdown("<h1 class='header-text'>🎙️ Voice Ordering System</h1>", unsafe_allow_html=True)

# Application Workflow Diagram Section
with st.expander("📊 View System Workflow Flowchart"):
    workflow_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "system_workflow.txt")
    if os.path.exists(workflow_path):
        with open(workflow_path, "r", encoding="utf-8") as file:
            workflow_content = file.read()
        st.code(workflow_content, language="text")
        st.download_button(
            label="Download Flowchart (.txt)",
            data=workflow_content,
            file_name="system_workflow.txt",
            mime="text/plain"
        )
    else:
        st.info("Workflow flowchart text file not found.")

col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("Order via Voice")
    # Custom high-performance recorder with auto-stop (VAD)
    # autoStart is now False by default as per user request
    audio_data_b64 = voice_recorder(
        key=f"main_recorder_{st.session_state.recorder_key}",
        autoStart=False
    )

    if audio_data_b64:
        audio_id = hash(audio_data_b64)
        if "last_audio_id" not in st.session_state or st.session_state.last_audio_id != audio_id:
            st.session_state.last_audio_id = audio_id
            audio_bytes = decode_base64_audio(audio_data_b64)
            if audio_bytes:
                st.session_state.is_listening = False # Stop auto-start while processing
                with st.spinner("Processing..."):
                    asyncio.run(run_workflow(audio_bytes))
                st.session_state.recorder_key += 1
                st.rerun()

    if st.session_state.recording_history:
        latest = st.session_state.recording_history[-1]
        st.markdown(f"""
        <div class="transcript-box">
            <b>Latest Transcript:</b><br>
            "{latest['transcript']}"
        </div>
        """, unsafe_allow_html=True)

    if st.session_state.last_response_text:
        st.markdown(f"""
        <div class="assistant-box">
            <b>Assistant Reply:</b><br>
            "{st.session_state.last_response_text}"
        </div>
        """, unsafe_allow_html=True)

with col2:
    st.subheader("🛒 Current Order")
    
    res = st.session_state.classification_result
    confirmed = res.get("confirmed", {})
    uncertain = res.get("needs_confirmation", [])
    not_in_menu = res.get("not_in_menu", [])

    # Handle Corrections
    if st.session_state.get("pending_corrections"):
        corr = st.session_state.pending_corrections[0]
        st.warning(f"Detected: {corr.get('action')}")
        if st.button("Apply Correction", key="apply_corr"):
            # Update local state
            st.session_state.classification_result["confirmed"] = \
                apply_confirmed_corrections(st.session_state.classification_result["confirmed"], [corr])
            st.session_state.pending_corrections.pop(0)
            
            # Speak confirmation
            play_voice(generate_speech("Theek hai, I've updated your order."))
            st.rerun()
        if st.button("Ignore", key="ignore_corr"):
            st.session_state.pending_corrections.pop(0)
            st.rerun()

    # Display List
    if not confirmed and not uncertain:
        st.info("Your cart is empty.")
    else:
        for item, details in confirmed.items():
            if isinstance(details, dict):
                qty = details.get("quantity", 1)
                addons = details.get("addons", [])
            else:
                qty = details
                addons = []
                
            addon_text = f"<br><small style='color: #7f8c8d;'>+ {', '.join(addons)}</small>" if addons else ""
            st.markdown(f'<div class="order-item confirmed"><span>{item}{addon_text}</span><span>x{qty}</span></div>', unsafe_allow_html=True)
        
        for i, item in enumerate(uncertain):
            # Two-step confirmation logic
            name_confirmed = item.get("name_confirmed", False)
            
            if not name_confirmed:
                # Step 1: Dish Name Confirmation
                st.markdown(f'<div class="order-item uncertain"><span>Did you mean <b>{item["suggested"]}</b>?</span></div>', unsafe_allow_html=True)
                col_y, col_n = st.columns(2)
                with col_y:
                    if st.button(f"Yes ({item['suggested']})", key=f"unc_y_{i}"):
                        # Use voice to confirm!
                        res = httpx.post(f"{API_URL}/order/classify", data={"transcript": "yes"}, timeout=30)
                        if res.status_code == 200:
                            data = res.json()
                            st.session_state.classification_result["confirmed"] = data["current_order"]
                            st.session_state.classification_result["needs_confirmation"].pop(i)
                            if data.get("speech"):
                                st.audio(f"data:audio/wav;base64,{data['speech']}", format="audio/wav", autoplay=True)
                            st.rerun()
                with col_n:
                    if st.button(f"No (Remove)", key=f"unc_n_{i}"):
                        res = httpx.post(f"{API_URL}/order/classify", data={"transcript": "no"}, timeout=30)
                        if res.status_code == 200:
                            data = res.json()
                            if data.get("speech"):
                                play_voice(data["speech"])
                        st.session_state.classification_result["needs_confirmation"].pop(i)
                        st.rerun()
            else:
                # Step 2: Addon/Modification Confirmation
                unc_addons = item.get("addons", [])
                addon_text = ", ".join(unc_addons)
                st.markdown(f'<div class="order-item uncertain"><span>Confirm modifications for <b>{item["suggested"]}</b>:<br><small>+ {addon_text}</small></span></div>', unsafe_allow_html=True)
                
                col_confirm, col_back = st.columns(2)
                with col_confirm:
                    if st.button("Confirm All", key=f"unc_c_{i}"):
                        st.session_state.classification_result["confirmed"][item['suggested']] = {
                            "quantity": item.get('quantity', 1),
                            "addons": unc_addons
                        }
                        st.session_state.classification_result["needs_confirmation"].pop(i)
                        st.rerun()
                with col_back:
                    if st.button("Back", key=f"unc_b_{i}"):
                        # Go back to name confirmation step
                        st.session_state.classification_result["needs_confirmation"][i]["name_confirmed"] = False
                        st.rerun()

    if not_in_menu:
        st.error(f"Not in menu: {', '.join(not_in_menu)}")

    if confirmed:
        if st.button("Submit Order", key="submit_order_btn"):
            try:
                with st.spinner("Submitting..."):
                    res = httpx.post(f"{API_URL}/order/submit", timeout=30.0)
                if res.status_code == 200:
                    data = res.json()
                    st.success("Order Placed Successfully!")
                    st.json(data.get("inventory_updates", []))
                    st.balloons()
                    # Clear local state
                    st.session_state.classification_result = {"confirmed": {}, "needs_confirmation": [], "not_in_menu": []}
                    st.rerun()
                else:
                    st.error(f"Submission failed: {res.text}")
            except Exception as e:
                st.error(f"Submission error: {e}")

if st.session_state.recording_history:
    with st.expander("Recent Audio History"):
        for entry in reversed(st.session_state.recording_history):
            st.write(f"Transcript: {entry['transcript']}")
            col_audio1, col_audio2 = st.columns(2)
            with col_audio1:
                st.caption("Original Audio")
                if os.path.exists(entry["original_audio_path"]):
                    try:
                        with open(entry["original_audio_path"], "rb") as f:
                            b64 = base64.b64encode(f.read()).decode()
                            st.audio(f"data:audio/wav;base64,{b64}", format="audio/wav")
                    except Exception as e:
                        st.warning(f"Audio file unavailable: {e}")
            with col_audio2:
                if entry.get("processed_audio_path") and os.path.exists(entry["processed_audio_path"]):
                    st.caption("Processed Audio (Sent to API)")
                    try:
                        with open(entry["processed_audio_path"], "rb") as f:
                            b64 = base64.b64encode(f.read()).decode()
                            st.audio(f"data:audio/wav;base64,{b64}", format="audio/wav")
                    except Exception as e:
                        st.warning(f"Audio file unavailable: {e}")
