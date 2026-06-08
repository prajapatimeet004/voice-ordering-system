# ─────────────────────────────────────────────
# Voice Ordering System – Production Dockerfile
# ─────────────────────────────────────────────
FROM python:3.11-slim

# Install system dependencies required by audio processing libs
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    libportaudio2 \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory inside the container
WORKDIR /app

# Copy requirements first (for Docker layer caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire project into the container
COPY . .

# Create temp_audio and logs directories
RUN mkdir -p temp_audio logs

# Expose the FastAPI server port
EXPOSE 8000

# Run the server with uvicorn (no browser auto-open in container)
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
