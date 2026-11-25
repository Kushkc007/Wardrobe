#!/usr/bin/env bash
# Wardrobe - Start script for Linux & macOS

set -e
cd "$(dirname "$0")"

echo "======================================================================"
echo "  ⚡ WARDROBE - Intelligent File Organizer & Live Control Room"
echo "======================================================================"
echo ""

# Find Python
if command -v python3 &>/dev/null; then
    PY_CMD="python3"
elif command -v python &>/dev/null; then
    PY_CMD="python"
else
    echo "[ERROR] Python 3 is not installed or not in PATH."
    exit 1
fi

# Check dependencies
echo "[*] Checking Python dependencies..."
if ! $PY_CMD -c "import flask, pymupdf, pypdf, PIL" &>/dev/null; then
    echo "[*] Installing dependencies from requirements.txt..."
    $PY_CMD -m pip install -r requirements.txt
else
    echo "[OK] All core dependencies verified."
fi

echo ""
echo "======================================================================"
echo "  Starting Live Dashboard at http://127.0.0.1:8765"
echo "  Press CTRL+C to stop the server."
echo "======================================================================"
echo ""

# Open browser in background
(sleep 2 && (xdg-open "http://127.0.0.1:8765" 2>/dev/null || open "http://127.0.0.1:8765" 2>/dev/null)) &

# Run server
$PY_CMD organize.py dashboard
