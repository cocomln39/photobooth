#!/bin/bash
# Sets up (if needed) and activates the virtual environment, then starts
# the photobooth Flask app.
#
# Usage:
#   ./start.sh
#
# Make it executable once with:
#   chmod +x start.sh

set -e

# Always run relative to this script's own location, no matter where
# it's called from.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR="venv"

if [ ! -f "$VENV_DIR/bin/activate" ]; then
    echo "No virtual environment found -- creating one at ./$VENV_DIR ..."
    python3 -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

echo "Checking dependencies..."
pip install -q -r requirements.txt

echo "Starting photobooth app..."
echo "Open http://localhost:5000 on this Pi, or http://<this-pi-ip>:5000/admin from another device to manage frames."
echo "Press Ctrl+C to stop."
echo

python3 app.py