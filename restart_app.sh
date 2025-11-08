#!/bin/bash

# Script to restart the Streamlit Whisper app
# This ensures the new config.toml settings are loaded

echo "🔄 Restarting Whisper Transcription App..."

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Kill any existing Streamlit processes
echo "🛑 Stopping existing Streamlit processes..."
pkill -f "streamlit run app.py" 2>/dev/null
sleep 2

# Check if there are any remaining Streamlit processes
if pgrep -f "streamlit" > /dev/null; then
    echo "⚠️  Some Streamlit processes may still be running. Attempting to force kill..."
    pkill -9 -f "streamlit" 2>/dev/null
    sleep 1
fi

# Activate virtual environment
echo "📦 Activating virtual environment..."
source venv/bin/activate

# Verify config file exists
if [ -f ".streamlit/config.toml" ]; then
    echo "✅ Config file found: .streamlit/config.toml"
    echo "   Upload limit: 2GB (2000 MB)"
else
    echo "⚠️  Warning: Config file not found. Creating it now..."
    mkdir -p .streamlit
    cat > .streamlit/config.toml << EOF
[server]
maxUploadSize = 2000
maxMessageSize = 2000

[server.fileWatcherType]
auto = true
EOF
fi

# Start Streamlit
echo "🚀 Starting Streamlit app..."
echo ""
echo "=========================================="
echo "  Whisper Transcription App Starting"
echo "=========================================="
echo ""
echo "The app will open in your browser at:"
echo "  http://localhost:8501"
echo ""
echo "Press Ctrl+C to stop the app"
echo ""

streamlit run app.py

