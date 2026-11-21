
#!/bin/bash

D=~/dataset_publik/hasil_klasifikasi

CSV=$(ls -t $D/klas_ft2_*.csv 2>/dev/null | head -1)

echo "=== $(date '+%H:%M:%S') ==="

P=$(pgrep -f "latih_klasifikasi.py" | head -1)

if [ -n "$P" ]; then

  echo "STATUS : berjalan (pid $P) | waktu berjalan $(ps -o etime= -p $P) | CPU $(ps -o pcpu= -p $P)%"

else

  echo "STATUS : tidak berjalan (selesai atau berhenti)"

fi

echo

if [ -n "$CSV" ]; then

  awk -F, 'NR==1{printf "%-6s %-10s %-11s %-10s %-9s %-8s %s\n","epoch","lr","latih_loss","latih_acc","val_loss","val_acc","detik"; next}

           {printf "%-6s %-10.2e %-11.4f %-10.4f %-9.4f %-8.4f %s\n",$1,$2,$3,$4,$5,$6,$7}' "$CSV"

else

  echo "belum ada epoch yang selesai"

fi

echo

tail -n 3 ~/dataset_publik/hasil_klasifikasi/log/klas_ft2_stdout.txt

