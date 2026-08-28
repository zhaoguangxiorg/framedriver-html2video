#!/usr/bin/env bash
# ============================================================
# Deployment script (Linux)
# 1. Create virtual environment  2. Install requirements.txt (versions locked)
# 3. Download Chromium into project-local .playwright-browsers (matches code path)
# Usage: bash scripts/setup.sh
# ============================================================
set -e
cd "$(dirname "$0")/.."

echo "[1/3] Creating virtual environment .venv ..."
if [ ! -x ".venv/bin/python" ]; then
    python3 -m venv .venv
fi

echo "[2/3] Installing Python dependencies (versions locked in requirements.txt)..."
.venv/bin/pip install -r requirements.txt

echo "[3/3] Downloading Chromium to project-local .playwright-browsers (matches html_to_image.py path)..."
export PLAYWRIGHT_BROWSERS_PATH="$(pwd)/.playwright-browsers"
.venv/bin/playwright install chromium

echo
echo "============================================================"
echo "Deployment complete!"
echo "Start server: .venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000"
echo "============================================================"
echo
echo "Note: If Chromium fails to launch due to missing system libraries, run:"
echo "  sudo .venv/bin/playwright install-deps chromium"
