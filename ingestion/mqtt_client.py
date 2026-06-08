"""
ingestion/mqtt_client.py
────────────────────────────────────────────────────────────
Konsumer MQTT: terima data sensor real-time → validasi → analisis agent →
keputusan → log riwayat → alert Telegram → simpan realtime_results.json.

Alur tiap pesan (1 baris sensor):
    1) Terima pesan MQTT
    2) Parse JSON → dict (key dinormalkan ke lowercase)
    3) Validasi via guardrails.validate_input()
    4) anomaly_agent.analyze(sensor_dict)         (key di-map ke FEATURE_ORDER)
    5) decision_engine.process(analysis_result)
    6) root_cause.log_analysis(analysis, decision)
    7) Kalau MEDIUM/HIGH/CRITICAL → kirim Telegram alert
    8) Append hasil ke realtime_results.json (maks 100 entri terakhir)
    9) Print ringkasan

BUFFER_SIZE = 1 → tiap baris diproses langsung (real-time), tidak menunggu.
"""

import os
import sys
import json
from pathlib import Path

# ── Path setup: root repo masuk sys.path supaya import paket jalan ──
REPO_DIR = Path(__file__).resolve().parent.parent
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import pandas as pd
import paho.mqtt.client as mqtt

from agent.guardrails import validate_input
from agent.anomaly_agent import AnomalyAgent, FEATURE_ORDER
from agent.decision_engine import DecisionEngine
from agent.root_cause import RootCauseAnalyzer

# db_writer & telegram bersifat opsional — pipeline tetap jalan kalau tidak ada
try:
    from ingestion.db_writer import batch_write
except Exception as e:
    print(f"[mqtt_client] db_writer tidak tersedia ({e}), DB write dilewati")
    batch_write = None

try:
    from alert.telegram_alert import TelegramAlert
except Exception as e:
    print(f"[mqtt_client] TelegramAlert tidak tersedia ({e}), alert dilewati")
    TelegramAlert = None

# ─────────────────────────────────────────
# Konstanta
# ─────────────────────────────────────────
BUFFER_SIZE = 1  # proses tiap baris langsung (real-time)
REALTIME_PATH = REPO_DIR / "realtime_results.json"
MAX_ENTRIES = 100
ALERT_LEVELS = {"MEDIUM", "HIGH", "CRITICAL"}
BROKER = os.getenv("MQTT_BROKER", "localhost")
PORT = int(os.getenv("MQTT_PORT", "1883"))
TOPIC = "solar/+/+/+/data"

# 5 fitur untuk snapshot di realtime_results.json (nama lowercase)
SNAPSHOT_KEYS = [
    "pv_voltage", "pv_power_output", "battery_temperature",
    "grid_voltage", "sensor_latency",
]

# Map lowercase → nama FEATURE_ORDER (kapital) untuk dipakai analyze()
_LOWER_TO_FEATURE = {col.lower(): col for col in FEATURE_ORDER}

# ─────────────────────────────────────────
# Inisialisasi komponen agent SEKALI (model berat, jangan reload tiap pesan)
# ─────────────────────────────────────────
print("[mqtt_client] Inisialisasi komponen agent...")
AGENT = AnomalyAgent()
ENGINE = DecisionEngine()
ROOTCAUSE = RootCauseAnalyzer()
BOT = TelegramAlert() if TelegramAlert else None
print("[mqtt_client] ✓ Agent siap.\n")


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
        data = data[-MAX_ENTRIES:]  # simpan hanya 100 terakhir
        with open(REALTIME_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[mqtt_client] Gagal tulis realtime_results.json: {e}")


def process_row(row: dict):
    """Proses satu baris sensor lengkap (validasi → analisis → simpan)."""
    # Map ke FEATURE_ORDER lalu jalankan agent
    sensor_dict = _to_feature_dict(row)
    analysis = AGENT.analyze(sensor_dict)
    decision = ENGINE.process(analysis)
    ROOTCAUSE.log_analysis(analysis, decision)

    level = analysis.get("risk_level", "UNKNOWN")

    # Alert Telegram kalau perlu
    if level in ALERT_LEVELS and BOT is not None:
        try:
            if BOT.send_alert(analysis, decision):
                print("[mqtt_client] → Alert Telegram terkirim")
        except Exception as e:
            print(f"[mqtt_client] Alert Telegram gagal: {e}")

    # Snapshot 5 fitur utama (dari data lowercase mentah)
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

    # Simpan ke DB (opsional, fallback CSV kalau gagal)
    if batch_write is not None:
        try:
            batch_write(pd.DataFrame([row]))
        except Exception as e:
            print(f"[mqtt_client] DB write gagal (diabaikan): {e}")

    print(f"[MQTT] Data diterima → Risk: {analysis.get('risk_score')} | "
          f"Level: {level} | Fault: {analysis.get('dominant_fault')}")


# ─────────────────────────────────────────
# Callback MQTT
# ─────────────────────────────────────────
def on_message(client, userdata, msg):
    try:
        data = json.loads(msg.payload)
        # Normalisasi semua key ke lowercase (data MQTT pakai skema lowercase)
        row = {str(k).lower(): v for k, v in data.items()}

        # Validasi via guardrails (BUFFER_SIZE=1 → 1 baris per DataFrame)
        df = pd.DataFrame([row])
        df_clean, issues = validate_input(df)
        if df_clean is None or df_clean.empty:
            print(f"[mqtt_client] Baris ditolak guardrails: {issues}")
            return

        # Proses tiap baris valid (biasanya 1 baris)
        for _, r in df_clean.iterrows():
            process_row(r.to_dict())

    except Exception as e:
        print(f"[mqtt_client] error on_message: {e}")


def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print(f"[mqtt_client] Terhubung ke broker {BROKER}:{PORT}, subscribe '{TOPIC}'")
        client.subscribe(TOPIC)
    else:
        print(f"[mqtt_client] Gagal connect ke broker (rc={rc})")


def start():
    """Mulai loop MQTT (blocking). Dipanggil dari scripts/run_realtime.py."""
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(BROKER, PORT)
    client.loop_forever()


if __name__ == "__main__":
    start()
