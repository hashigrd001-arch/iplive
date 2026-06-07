#!/bin/bash
# Double-click launcher for IP LIVE Studio (macOS).
# If Finder says it can't open this, run once in Terminal:
#   chmod +x "เปิด IP LIVE.command"
cd "$(dirname "$0")/vcam-pc" || {
    echo "ไม่พบโฟลเดอร์ vcam-pc"; read -r; exit 1
}

# Use a real Python 3 if available.
PY="$(command -v python3 || true)"
if [ -z "$PY" ]; then
    echo "ไม่พบ Python 3 — ติดตั้งจาก https://www.python.org/downloads ก่อนครับ"
    read -r -p "กด Enter เพื่อปิด..."
    exit 1
fi

exec "$PY" -m src.main --studio
