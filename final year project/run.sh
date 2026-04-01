#!/bin/bash
# Pooja Voice Ordering System Launcher

echo "------------------------------------------------"
echo "🚀 Starting Pooja - Voice Ordering Dashboard..."
echo "------------------------------------------------"

# Check if server.py exists
if [ ! -f "server.py" ]; then
    echo "❌ Error: server.py not found in current directory."
    exit 1
fi

# Run the server which handles the dashboard auto-launch
python3 server.py
