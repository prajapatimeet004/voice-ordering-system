# 🎙️ Voice Ordering System (Sarvam AI)

A modern voice-based ordering system built with Streamlit and Sarvam AI.

## Features
- **Multilingual Support**: Supports Gujarati, Hindi, and English transcription via Sarvam AI's `saaras:v3`.
- **Intelligent Classification**: Uses `sarvam-m` LLM for structured order extraction.
- **Smart Corrections**: Supports "Add one more", "Remove X", and "Change quantity of Y" style voice corrections.
- **Hybrid Matching**: Combines Semantic Search (Sentence Transformers) and Fuzzy Matching for robust menu item detection.
- **Non-Translation Policy**: Preserves original language for dish names and customizations.

## Tech Stack
- **Frontend**: Streamlit
- **ASR/LLM**: Sarvam AI SDK
- **Speech Processing**: Pydub, PyAudio
- **Search**: Sentence Transformers, RapidFuzz

## Setup
1. Clone the repository.
2. Install dependencies: `pip install -r requirements.txt`
3. Create a `.env` file with your `SARVAM_API_KEY`.
4. Run the app: `streamlit run app.py`
