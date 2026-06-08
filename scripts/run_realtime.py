"""
scripts/run_realtime.py
────────────────────────────────────────────────────────────
Jalankan pipeline ingestion real-time:
    MQTT → guardrails → agent → keputusan → alert → realtime_results.json

Cara pakai (dari root repo):
    python scripts/run_realtime.py

Hentikan dengan Ctrl+C.
"""

import sys
import time
import threading
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
    print("=" * 60)
    print("  AI-ORBIT SOLAR — REALTIME INGESTION PIPELINE")
    print("=" * 60)

    # Import di dalam main supaya error import (mis. model belum ada) tertangkap rapi
    try:
        from ingestion import mqtt_client
    except Exception as e:
        print(f"[REALTIME] Gagal inisialisasi pipeline: {e}")
        sys.exit(1)

    # Jalankan loop MQTT di thread terpisah (daemon → ikut mati saat program berhenti)
    t = threading.Thread(target=mqtt_client.start, daemon=True)
    t.start()

    print("[REALTIME] Pipeline aktif, menunggu data dari MQTT...")
    print("[REALTIME] Tekan Ctrl+C untuk berhenti.\n")

    try:
        # Main thread tetap hidup selama thread MQTT jalan
        while t.is_alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n[REALTIME] Pipeline dihentikan")
        sys.exit(0)


if __name__ == "__main__":
    main()
