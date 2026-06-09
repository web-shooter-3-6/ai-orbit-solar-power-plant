"""
scripts/run_realtime.py
────────────────────────────────────────────────────────────
Runner pipeline realtime untuk development lokal (TANPA MQTT, tanpa Docker).

Menjalankan DUA komponen sekaligus:
    1) TelegramBot (interaktif) di thread terpisah — menjawab command user
       (/status, /history, /inject, dll) lewat long-polling.
    2) realtime_simulator di thread utama — baca dataset, analisis agent,
       tulis realtime_results.json, kirim alert Telegram bila perlu.

Keduanya jalan bersamaan. Bot interaktif hanya aktif bila TELEGRAM_TOKEN
terkonfigurasi di .env; kalau tidak, simulator tetap jalan normal.

Cara pakai (dari root repo):
    python scripts/run_realtime.py

Hentikan dengan Ctrl+C.
"""

import sys
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


def _start_telegram_bot():
    """Jalankan TelegramBot interaktif di thread terpisah (daemon)."""
    try:
        from alert.telegram_bot import TelegramBot
    except Exception as e:
        print(f"[REALTIME] TelegramBot tidak tersedia ({e}), bot interaktif dilewati")
        return

    def _run():
        try:
            TelegramBot().run()
        except Exception as e:
            print(f"[REALTIME] Bot interaktif berhenti: {e}")

    t = threading.Thread(target=_run, name="telegram-bot", daemon=True)
    t.start()


def main():
    print("[REALTIME] Mode lokal — menjalankan simulator + bot interaktif (tanpa MQTT)...")

    # 1) Bot interaktif di thread terpisah (non-blocking)
    _start_telegram_bot()

    # 2) Simulator realtime di thread utama
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
