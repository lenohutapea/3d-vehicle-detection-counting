#!/bin/bash
# Menjalankan server antarmuka. Buka http://127.0.0.1:8000 di peramban. Berhenti: Ctrl+C.
cd "$(dirname "$0")" || exit 1
source ~/projects/venv_3dbbox/bin/activate
exec uvicorn app:app --host 127.0.0.1 --port 8000
