"""
scripts/run_realtime.py
────────────────────────────────────────────────────────────
Runner pipeline realtime untuk development lokal (TANPA MQTT, tanpa Docker).

Cukup jalankan realtime_simulator.py langsung — baca dataset, analisis agent,
tulis realtime_results.json, kirim alert Telegram bila perlu.

Cara pakai (dari root repo):
    python scripts/run_realtime.py

Hentikan dengan Ctrl+C.
"""

import sys
from pathlib import Path

# ── Path setup: root repo masuk sys.path ──
REPO_DIR = Path(__file__).resolve().parent.parent
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def main():
    print("[REALTIME] Mode lokal — menjalankan simulator tanpa MQTT...")
    try:
        from scripts.realtime_simulator import run
    except Exception as e:
        print(f"[REALTIME] Gagal import simulator: {e}")
        sys.exit(1)

    try:
        run()
    except KeyboardInterrupt:
        print("\n[REALTIME] Pipeline dihentikan")
        sys.exit(0)


if __name__ == "__main__":
    main()
