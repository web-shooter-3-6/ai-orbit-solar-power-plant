"""
scripts/realtime_simulator.py
────────────────────────────────────────────────────────────
Worker realtime (mis. dijalankan di Railway) — MENULIS data ke Supabase.

Arsitektur full-cloud:
    worker ini  ──insert──►  Supabase (tabel realtime_results & history)
    Reflex Cloud ──select──►  Supabase  (Realtime Feed, History, Statistik)

Alur tiap baris:
    1) Ambil 1 baris dari CSV simulasi (key dinormalkan ke lowercase)
    2) Konversi ke dict 49 fitur (key FEATURE_ORDER kapital)
    3) agent_bridge.run_full_analysis(...) → analisis SEKALIGUS insert ke
       Supabase (history + realtime) via db_client + kirim Telegram bila perlu
    4) Print ringkasan, sleep 1 detik

Jalan terus (infinite loop). Kalau CSV habis → mulai lagi dari awal.
Concurrency ditangani Supabase (tidak perlu filelock / file JSON lagi).
"""

# ============================================================
# CATATAN PENTING:
# File ini menggunakan Realtime_Test_Sequence.csv yang berisi
# data SIMULASI (bukan dataset asli) — dibuat khusus untuk
# demonstrasi Realtime Feed dengan story arc:
# Normal -> PV_Fault -> Normal -> Battery_Overheating -> Normal
# -> Grid_Instability -> Normal -> Communication_Failure -> Normal
#
# Data ini TIDAK digunakan untuk training atau evaluasi model.
# Evaluasi model menggunakan dataset asli
# (Condition_Monitoring_Dataset.csv) sesuai Bias Analysis Report.
# ============================================================

import sys
import time
from pathlib import Path

# ── Path setup: root repo masuk sys.path supaya paket app bisa di-import ──
REPO_DIR = Path(__file__).resolve().parent.parent
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import pandas as pd

# Pakai agent_bridge dari paket app (copy backend). run_full_analysis sudah
# meng-handle: load model, analisis, kirim Telegram, DAN insert ke Supabase.
from ai_orbit_solar_power_plant.backend import agent_bridge

# ─────────────────────────────────────────
# Konstanta
# ─────────────────────────────────────────
# Dataset SIMULASI khusus Realtime Feed (story arc), BUKAN dataset training.
DATA_PATH = REPO_DIR / "data" / "Realtime_Test_Sequence.csv"
SLEEP_SEC = 1.0

# Map lowercase → nama FEATURE_ORDER (kapital) untuk analyze().
# FEATURE_ORDER diambil dari agent_bridge (sumber kebenaran 49 fitur).
_LOWER_TO_FEATURE = {col.lower(): col for col in agent_bridge.get_feature_order()}


# ─────────────────────────────────────────
# Helper
# ─────────────────────────────────────────
def _to_feature_dict(row: dict) -> dict:
    """Konversi dict sensor (key lowercase) → dict ber-key FEATURE_ORDER (kapital)."""
    out = {}
    for low, feat in _LOWER_TO_FEATURE.items():
        if low in row:
            out[feat] = row[low]
        elif feat in row:  # jaga-jaga kalau sudah kapital
            out[feat] = row[feat]
    return out


def process_row(row: dict):
    """Proses satu baris sensor: analisis + insert Supabase (via agent_bridge)."""
    try:
        sensor_dict = _to_feature_dict(row)
        # run_full_analysis: analisis → Telegram alert → insert history & realtime.
        result = agent_bridge.run_full_analysis(sensor_dict)
        print(f"[REALTIME] Risk: {result.get('risk_score')} | "
              f"Level: {result.get('risk_level')} | "
              f"Fault: {result.get('dominant_fault')}")
    except Exception as e:
        print(f"[REALTIME] Gagal proses baris: {e}")


# ─────────────────────────────────────────
# Main loop
# ─────────────────────────────────────────
def run():
    print("=" * 60)
    print("  AI-ORBIT SOLAR — REALTIME SIMULATOR (Supabase)")
    print("=" * 60)
    print("Realtime simulator menggunakan Realtime_Test_Sequence.csv "
          "(data simulasi untuk demo)")

    # Load dataset
    if not DATA_PATH.exists():
        print(f"[REALTIME] Dataset tidak ditemukan: {DATA_PATH}")
        sys.exit(1)
    try:
        df = pd.read_csv(DATA_PATH)
        # normalkan kolom ke lowercase supaya konsisten
        df.columns = [str(c).lower() for c in df.columns]
        print(f"[REALTIME] Dataset dimuat: {len(df)} baris")
    except Exception as e:
        print(f"[REALTIME] Gagal baca dataset: {e}")
        sys.exit(1)

    # Warm-up: muat model sekali di awal (sekaligus memunculkan status koneksi DB).
    print("[REALTIME] Inisialisasi agent & koneksi Supabase...")
    if agent_bridge.get_agent() is None:
        print("[REALTIME] Agent gagal dimuat, pipeline dihentikan.")
        sys.exit(1)
    print("[REALTIME] ✓ Siap.")
    print("[REALTIME] Pipeline aktif, memproses data setiap 1 detik...")
    print("[REALTIME] Tekan Ctrl+C untuk berhenti.\n")

    try:
        putaran = 0
        while True:  # infinite loop — ulang dari awal kalau CSV habis
            putaran += 1
            for _, row in df.iterrows():
                process_row(row.to_dict())
                time.sleep(SLEEP_SEC)
            print(f"[REALTIME] Dataset selesai (putaran {putaran}), mulai ulang...\n")
    except KeyboardInterrupt:
        print("\n[REALTIME] Pipeline dihentikan")
        sys.exit(0)


if __name__ == "__main__":
    run()
