#!/bin/bash
# LegalPerigee — GUI launcher
set -e

cd "$(dirname "$0")"

# Load .env if present
if [ -f .env ]; then
  export $(grep -v '^#' .env | xargs)
fi

# Check dependencies
if ! python3 -c "import streamlit" 2>/dev/null; then
  echo "Installing dependencies..."
  pip3 install -r requirements.txt
fi

echo "Starting LegalPerigee GUI..."
streamlit run gui.py \
  --server.headless false \
  --server.port 8501 \
  --server.runOnSave false \
  --server.fileWatcherType none \
  --browser.gatherUsageStats false
