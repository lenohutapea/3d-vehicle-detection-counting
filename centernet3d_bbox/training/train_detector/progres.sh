#!/bin/bash
# progres.sh - ringkasan progres latihan dari_lama dan dari_baru (hanya membaca log)
LOG=~/projects/hasil/log_latih_detektor
for tag in dari_lama dari_baru; do
  echo "=== $tag ==="
  csv=$(ls -t $LOG/${tag}_*.csv 2>/dev/null | head -1)
  if [ -z "$csv" ]; then echo "belum mulai"; echo; continue; fi
  n=$(($(wc -l < "$csv") - 1))
  if [ "$n" -lt 1 ]; then echo "epoch 1 belum selesai"; echo; continue; fi
  cut -d, -f1,3,7,8,12,13 "$csv" | awk -F, 'NR==1{printf "%6s %11s %13s %9s %11s %7s\n","epoch","train_loss","train_ukuran","val_loss","val_ukuran","detik";next}{printf "%6s %11.4f %13.4f %9.4f %11.4f %7.0f\n",$1,$2,$3,$4,$5,$6}'
  echo "val loss terbaik: $(tail -n +2 "$csv" | cut -d, -f8 | sort -g | head -1 | awk '{printf "%.4f",$1}')"
  echo
done
echo "--- sedang berjalan ---"
tr '\r' '\n' < $LOG/dua_latihan_stdout.txt 2>/dev/null | grep -E "^(latih|uji) \(" | tail -1 | cut -c1-180
pgrep -af "python3 train_session0_right" | sed 's/--init.*--tag/... --tag/' | cut -c1-90