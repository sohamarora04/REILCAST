#!/usr/bin/env bash
# Capture each ReliCast transfer mode (tcp / udp / naive / relicast) into its own pcap with 8 receivers.
# Usage: sudo ./demo/capture_modes.sh [receivers] [loss] [shared_loss] [size_kb]
# Output: demo/captures/<mode>.pcap   (open in Wireshark with demo/relicast.lua loaded)
set -euo pipefail
cd "$(dirname "$0")/.."

N=${1:-8}; LOSS=${2:-0.05}; SHARED=${3:-0.02}; SIZE=${4:-256}
PY=${PYTHON:-python3}
OUT=demo/captures
mkdir -p "$OUT"

# Which interface carries the traffic? The app uses the LAN address if multicast works there, else 127.0.0.1.
IP=$($PY -c "from relicast import engine; print(engine.get_iface())")
if [ "$IP" = "127.0.0.1" ]; then
  case "$(uname)" in Darwin) IF=lo0 ;; *) IF=lo ;; esac
else
  case "$(uname)" in
    Darwin) IF=$(route -n get "$IP" 2>/dev/null | awk '/interface:/{print $2}'); IF=${IF:-en0} ;;
    *)      IF=$(ip -o addr | awk -v ip="$IP" '$4 ~ ip"/" {print $2; exit}') ;;
  esac
fi
echo "ReliCast interface $IP -> capturing on $IF, $N receivers, loss $LOSS (+$SHARED shared), $SIZE KB"

for MODE in tcp udp naive relicast; do
  echo "== $MODE"
  tcpdump -i "$IF" -n -U -w "$OUT/$MODE.pcap" "ip" >/dev/null 2>&1 &
  TD=$!
  sleep 1
  $PY - "$MODE" "$N" "$LOSS" "$SHARED" "$SIZE" <<'PYEOF'
import sys
from relicast import engine
m, n, loss, shared, size = sys.argv[1], int(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4]), int(sys.argv[5])
r = engine.run_transfer(m, n, loss, shared, size, seed=7)
print("   duration %.2fs  delivery %.1f%%  verified %s  sender %d B  NACKs %d  repairs %d" % (
    r["duration_s"], 100 * r["delivery_ratio"], r["all_verified"], r["sender_bytes"], r["nack_packets"], r["repair_packets"]))
PYEOF
  sleep 1
  kill "$TD" 2>/dev/null || true
  wait "$TD" 2>/dev/null || true
  echo "   saved $OUT/$MODE.pcap ($(du -h "$OUT/$MODE.pcap" | cut -f1))"
done
echo "Done. Open: wireshark -X lua_script:demo/relicast.lua $OUT/relicast.pcap"
