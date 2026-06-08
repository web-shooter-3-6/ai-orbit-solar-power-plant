"""
scripts/realtime_simulator.py
────────────────────────────────────────────────────────────
Simulator realtime TANPA MQTT — untuk deployment cloud (Railway, dll).

Menggantikan kombinasi mqtt_publisher.py + mqtt_client.py + run_realtime.py:
baca dataset baris per baris, jalankan agent langsung, tulis hasil ke
realtime_results.json, dan kirim alert Telegram bila perlu.

Alur tiap baris:
    1) Ambil 1 baris dari dataset (key lowercase)
    2) anomaly_agent.analyze(row)        (key di-map ke FEATURE_ORDER kapital)
    3) decision_engine.process(analysis)
    4) root_cause.log_analysis(analysis, decision)
    5) Tulis ke realtime_results.json (maks 100 entri terakhir)
    6) Kalau MEDIUM/HIGH/CRITICAL → kirim Telegram alert
    7) Print ringkasan, sleep 1 detik

Jalan terus (infinite loop). Kalau CSV habis → mulai lagi dari awal.
"""

import sys
import json
import time
from pathlib import Path

# ── Path setup: root repo masuk sys.path ──
REPO_DIR = Path(__file__).resolve().parent.parent
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import pandas as pd

from agent.anomaly_agent import AnomalyAgent, FEATURE_ORDER
from agent.decision_engine import DecisionEngine
from agent.root_cause import RootCauseAnalyzer

# Telegram opsional — sistem tetap jalan kalau tidak ada / belum dikonfigurasi
try:
    from alert.telegram_alert import TelegramAlert
except Exception as e:
    print(f"[REALTIME] TelegramAlert tidak tersedia ({e}), alert dilewati")
    TelegramAlert = None

# ─────────────────────────────────────────
# Konstanta
# ─────────────────────────────────────────
DATA_PATH = REPO_DIR / "data" / "Condition_Monitoring_Dataset.csv"
REALTIME_PATH = REPO_DIR / "realtime_results.json"
MAX_ENTRIES = 100
ALERT_LEVELS = {"MEDIUM", "HIGH", "CRITICAL"}
SLEEP_SEC = 1.0

# 5 fitur untuk snapshot (nama lowercase)
SNAPSHOT_KEYS = [
    "pv_voltage", "pv_power_output", "battery_temperature",
    "grid_voltage", "sensor_latency",
]

# Map lowercase → nama FEATURE_ORDER (kapital) untuk analyze()
_LOWER_TO_FEATURE = {col.lower(): col for col in FEATURE_ORDER}


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


def _append_realtime(entry: dict):
    """Append satu entri ke realtime_results.json (maks MAX_ENTRIES terakhir)."""
    try:
        data = []
        if REALTIME_PATH.exists():
            with open(REALTIME_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list):
                data = []
        data.append(entry)
        data = data[-MAX_ENTRIES:]
        with open(REALTIME_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[REALTIME] Gagal tulis realtime_results.json: {e}")


def process_row(row: dict, agent, engine, rootcause, bot):
    """Proses satu baris sensor: analisis → keputusan → log → simpan → alert."""
    try:
        sensor_dict = _to_feature_dict(row)
        analysis = agent.analyze(sensor_dict)
        decision = engine.process(analysis)
        rootcause.log_analysis(analysis, decision)

        level = analysis.get("risk_level", "UNKNOWN")

        # Snapshot 5 fitur utama dari data lowercase mentah
        snapshot = {}
        for k in SNAPSHOT_KEYS:
            try:
                snapshot[k] = float(row.get(k, 0.0))
            except (TypeError, ValueError):
                snapshot[k] = 0.0

        entry = {
            "timestamp":       analysis.get("timestamp"),
            "risk_score":      analysis.get("risk_score"),
            "risk_level":      level,
            "dominant_fault":  analysis.get("dominant_fault"),
            "explanation":     decision.get("explanation", ""),
            "recommendations": decision.get("recommendations", []),
            "sensor_snapshot": snapshot,
        }
        _append_realtime(entry)

        # Alert Telegram bila perlu
        if level in ALERT_LEVELS and bot is not None:
            try:
                if bot.send_alert(analysis, decision):
                    print("[REALTIME] → Alert Telegram terkirim")
            except Exception as e:
                print(f"[REALTIME] Alert Telegram gagal: {e}")

        print(f"[REALTIME] Risk: {analysis.get('risk_score')} | "
              f"Level: {level} | Fault: {analysis.get('dominant_fault')}")
    except Exception as e:
        print(f"[REALTIME] Gagal proses baris: {e}")


# ─────────────────────────────────────────
# Main loop
# ─────────────────────────────────────────
def run():
    print("=" * 60)
    print("  AI-ORBIT SOLAR — REALTIME SIMULATOR (tanpa MQTT)")
    print("=" * 60)

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

    # Inisialisasi komponen agent
    try:
        print("[REALTIME] Inisialisasi komponen agent...")
        agent = AnomalyAgent()
        engine = DecisionEngine()
        rootcause = RootCauseAnalyzer()
        bot = TelegramAlert() if TelegramAlert else None
        print("[REALTIME] ✓ Agent siap.")
    except Exception as e:
        print(f"[REALTIME] Gagal inisialisasi agent: {e}")
        sys.exit(1)

    print("[REALTIME] Pipeline aktif, memproses data setiap 1 detik...")
    print("[REALTIME] Tekan Ctrl+C untuk berhenti.\n")

    try:
        putaran = 0
        while True:  # infinite loop — ulang dari awal kalau CSV habis
            putaran += 1
            for _, row in df.iterrows():
                process_row(row.to_dict(), agent, engine, rootcause, bot)
                time.sleep(SLEEP_SEC)
            print(f"[REALTIME] Dataset selesai (putaran {putaran}), mulai ulang...\n")
    except KeyboardInterrupt:
        print("\n[REALTIME] Pipeline dihentikan")
        sys.exit(0)


if __name__ == "__main__":
    run()
