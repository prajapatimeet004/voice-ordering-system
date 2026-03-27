#!/bin/bash
# Start the FastAPI server with auto-reload enabled
echo "🚀 Starting server with auto-reload..."
cd "$(dirname "$0")"
uvicorn server:app --reload --host 0.0.0.0 --port 8000
