#!/bin/bash
echo "======================================================="
echo "   🚀 TELECLOUD: TELEGRAM STORAGE & WEB HOSTING"
echo "======================================================="
echo ""

# Check python
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] Python 3 is not installed!"
    exit 1
fi

echo "[1/2] Installing requirements..."
pip3 install -r requirements.txt --quiet

echo "[2/2] Launching server on http://127.0.0.1:8000 ..."
echo ""
python3 -m uvicorn app:app --host 0.0.0.0 --port 8000 --reload
