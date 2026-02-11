#!/usr/bin/env bash
# Run project in dev mode (Unix)
set -euo pipefail

if [ -f venv/bin/activate ]; then
  source venv/bin/activate
else
  echo "No venv found. Create one: python3 -m venv venv" >&2
fi

if [ "$1" = "install" ]; then
  echo "Installing dependencies..."
  python -m pip install --upgrade pip
  pip install -r requirements.txt
fi

echo "Starting application (dev mode)"
python start.py
