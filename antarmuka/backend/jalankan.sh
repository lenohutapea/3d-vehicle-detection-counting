#!/bin/bash
# Menjalankan server antarmuka. Buka http://127.0.0.1:8000 di peramban. Berhenti: Ctrl+C.
# Bila "izinkan_jaringan" di ../data/setelan.json bernilai true, server juga menerima kiriman
# Raspberry Pi dari jaringan (hanya alamat /api/node/... dan wajib token).
cd "$(dirname "$0")" || exit 1
source ~/projects/venv_3dbbox/bin/activate
HOST=127.0.0.1
if python3 -c "import json,sys; sys.exit(0 if json.load(open('../data/setelan.json')).get('izinkan_jaringan') else 1)" 2>/dev/null; then
  HOST=0.0.0.0
fi
echo "Server di http://127.0.0.1:8000 (menerima dari: $HOST)"
exec uvicorn app:app --host "$HOST" --port 8000
