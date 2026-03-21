import sounddevice as sd
import numpy as np
import scipy.io.wavfile as wavfile
import os
import time
# import torch  # Moved inside functions
# import torch.nn.functional as F # Moved inside functions

def record_audio(filename, duration=None):
    """
    Records audio from the local microphone. 
    If duration is None, records until interrupted (Ctrl+C).
    """
    fs = 16000  # Sample rate (standard for speech-to-text)
    channels = 1
    
    print("Recording started... (Press Ctrl+C to stop)")
    
    audio_data = []
    
    try:
        if duration:
            recording = sd.rec(int(duration * fs), samplerate=fs, channels=channels)
            sd.wait()
            wavfile.write(filename, fs, (recording * 32767).astype(np.int16))
        else:
            def callback(indata, frames, time, status):
                if status:
                    print(status)
                audio_data.append(indata.copy())

            with sd.InputStream(samplerate=fs, channels=channels, callback=callback):
                while True:
                    sd.sleep(50)
    except KeyboardInterrupt:
        print("Recording stopped.")
        if not duration and audio_data:
            full_recording = np.concatenate(audio_data, axis=0)
            wavfile.write(filename, fs, (full_recording * 32767).astype(np.int16))

from scipy.signal import butter, lfilter

def butter_highpass(cutoff, fs, order=5):
    nyq = 0.5 * fs
    normal_cutoff = cutoff / nyq
    b, a = butter(order, normal_cutoff, btype='high', analog=False)
    return b, a

def apply_highpass_filter(data, cutoff=100, fs=16000):
    """Removes low-frequency noise (like fan hum) below the cutoff."""
    b, a = butter_highpass(cutoff, fs, order=5)
    return lfilter(b, a, data)

def reduce_noise_with_profile(audio_data, noise_profile, rate=16000):
    """
    Performs spectral subtraction using a specific noise profile.
    Used for removing consistent background noise like laptop fans.
    """
    import noisereduce as nr
    # noisereduce expects float32 or float64
    audio_float = audio_data.astype(np.float32)
    noise_float = noise_profile.astype(np.float32)
    
    reduced_noise = nr.reduce_noise(
        y=audio_float,
        sr=rate,
        y_noise=noise_float,
        stationary=True,
        prop_decrease=1.0 # Aggressive reduction for fan noise
    )
    return reduced_noise

def reduce_noise(input_path, output_path):
    print("Applying general noise reduction...")
    rate, data = wavfile.read(input_path)
    
    # Convert to float for noisereduce
    data_float = data.astype(float)
    
    import noisereduce as nr
    reduced_noise = nr.reduce_noise(
        y=data_float,
        sr=rate,
        prop_decrease=0.6
    )
    
    wavfile.write(output_path, rate, reduced_noise.astype(np.int16))

# Global variables for VAD (Loaded lazily)
model_vad = None
vad_utils = None

def get_vad_model():
    """Returns the Silero VAD model and utils, loading them if necessary."""
    global model_vad, vad_utils
    if model_vad is None:
        print("DEBUG: Loading Silero VAD Model...")
        import torch
        model_vad, utils = torch.hub.load(repo_or_dir='snakers4/silero-vad',
                                          model='silero_vad',
                                          force_reload=False,
                                          onnx=False,
                                          trust_repo=True)
        vad_utils = utils
    return model_vad, vad_utils

def trim_silence(input_wav, output_wav):
    """
    Uses Silero VAD to detect speech and trim silence.
    Returns True if speech is detected, False otherwise.
    """
    print("Detecting speech with Silero VAD...")
    
    # Ensure models are loaded
    model_vad, utils = get_vad_model()
    (get_speech_timestamps, save_audio, read_audio, VADIterator, collect_chunks) = utils
    
    # Read audio for VAD (must be 16kHz)
    wav = read_audio(input_wav, sampling_rate=16000)
    
    # Get speech timestamps
    speech_timestamps = get_speech_timestamps(wav, model_vad, sampling_rate=16000, threshold=0.6)
    
    if not speech_timestamps:
        return False
    
    # Collect speech chunks and save
    speech_data = collect_chunks(speech_timestamps, wav)
    save_audio(output_wav, speech_data, sampling_rate=16000)
    
    return True

def split_wav(filename, chunk_duration=20, noise_profile_bytes=None):
    """
    Splits the audio file into chunks, applying high-pass filter and 
    optional noise profiling (spectral subtraction) first.
    """
    print(f"Preprocessing and splitting {filename} into {chunk_duration}s chunks...")
    import io
    from pydub import AudioSegment, effects
    
    # Load original audio
    try:
        audio = AudioSegment.from_file(filename)
    except Exception as e:
        print(f"audio not found or could not be decoded: {e}")
        return []
    fs = audio.frame_rate
    
    # Preprocessing in NumPy domain
    samples = np.array(audio.get_array_of_samples())
    
    # 1. High-Pass Filter (Kill low-end rumble/fan vibrations)
    samples = apply_highpass_filter(samples, cutoff=100, fs=fs)
    
    # 2. Spectral Subtraction (using captured noise profile if available)
    if noise_profile_bytes:
        print("Using captured noise profile for spectral subtraction...")
        try:
            noise_audio = AudioSegment.from_file(io.BytesIO(noise_profile_bytes))
            noise_samples = np.array(noise_audio.get_array_of_samples())
            samples = reduce_noise_with_profile(samples, noise_samples, rate=fs)
        except Exception as e:
            print(f"WARNING: Could not decode noise profile: {e}")
    
    # Convert back to AudioSegment
    samples = samples.astype(audio.array_type)
    audio = audio._spawn(samples)
    
    # 3. Normalization (Volume Consistency)
    audio = effects.normalize(audio)
    
    chunk_length_ms = chunk_duration * 1000
    chunks = []
    
    for i, start in enumerate(range(0, len(audio), chunk_length_ms)):
        chunk = audio[start:start + chunk_length_ms]
        chunk_filename = os.path.abspath(f"chunk_{i}.wav")
        chunk.export(chunk_filename, format="wav")
        chunks.append(chunk_filename)
        
    return chunks

def safe_remove(file_path, max_retries=5, delay=0.2):
    """Attempt to remove a file with retries to handle transient locks on Windows."""
    if not os.path.exists(file_path):
        return
    for attempt in range(max_retries):
        try:
            os.remove(file_path)
            return
        except OSError as e:
            if attempt < max_retries - 1:
                time.sleep(delay)
            else:
                print(f"WARNING: Could not remove {file_path} after {max_retries} attempts: {e}")
