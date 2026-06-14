"""
ai_orbit_solar_power_plant/backend/agent_bridge.py
────────────────────────────────────────────────────────────
Jembatan (bridge) antara aplikasi Reflex dengan logic agent yang
sudah ada di root repo (agent/, alert/, models/).

Tujuan:
  - Menambahkan path root repo ke sys.path supaya bisa import paket
    agent/, alert/, models/ dari dalam package Reflex.
  - Memuat model AI hanya SEKALI (pola singleton) — pemuatan model
    berat (torch/sklearn) tidak diulang tiap pemanggilan.
  - Menyediakan fungsi wrapper sederhana yang langsung dipakai State.

Semua I/O file ditangani dengan graceful fallback (return [] / {} /
nilai aman) supaya aplikasi TIDAK crash walau file/model belum ada.
"""

import os
import sys

# ─────────────────────────────────────────────────────────
# COPY DEPLOY (Reflex Cloud):
# Semua dependency (agent/, alert/, models_output/, data/) sudah DI-COPY
# ke dalam folder backend/ ini supaya ikut ter-upload oleh `reflex deploy`
# (yang hanya mengunggah isi folder app Reflex). Tidak perlu lagi menelusuri
# root repo / mengutak-atik sys.path — cukup pakai import relatif & path lokal.
# ─────────────────────────────────────────────────────────
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))

# Path dataset (untuk get_feature_means). Storage Realtime Feed & History
# sudah PINDAH dari file JSON lokal ke Supabase PostgreSQL (lihat db_client).
DATA_PATH = os.path.join(BACKEND_DIR, "data", "Condition_Monitoring_Dataset.csv")

# Klien DB Supabase (import aman: bila modul/psycopg2 bermasalah, set None
# sehingga semua operasi DB graceful — aplikasi tetap jalan mode lokal).
try:
    from . import db_client
except Exception as e:  # pragma: no cover
    print(f"[agent_bridge] ! db_client tidak tersedia ({e}), storage DB dimatikan")
    db_client = None

# Snapshot 5 fitur utama untuk ditampilkan di Realtime Feed.
# Map: key snapshot (lowercase) -> nama fitur FEATURE_ORDER (kapital).
_SNAPSHOT_MAP = {
    "pv_voltage": "PV_Voltage",
    "pv_power_output": "PV_Power_Output",
    "battery_temperature": "Battery_Temperature",
    "grid_voltage": "Grid_Voltage",
    "sensor_latency": "Sensor_Latency",
}

# Salinan urutan 49 fitur sebagai fallback bila import dari agent gagal.
# (Sumber kebenaran tetap agent.anomaly_agent.FEATURE_ORDER.)
_FEATURE_ORDER_FALLBACK = [
    "Hour", "Day_Index", "PV_Voltage", "PV_Current", "PV_Power_Output",
    "PV_Panel_Temperature", "Solar_Irradiance", "PV_Efficiency",
    "PV_AC_Power", "PV_Inverter_Temperature", "PV_Frequency",
    "Battery_SOC", "Battery_SOH", "Battery_Voltage", "Battery_Current",
    "Battery_Temperature", "Battery_Charge_Rate", "Battery_Discharge_Rate",
    "Battery_Internal_Resistance", "Battery_Cycle_Count",
    "EV_Charging_Load", "EV_Charging_Current", "EV_Charging_Voltage",
    "Charging_Station_Temperature", "Active_EV_Count", "Charging_Duration",
    "Fast_Charging_Status", "Grid_Voltage", "Grid_Current", "Grid_Frequency",
    "Power_Demand", "Reactive_Power", "Load_Factor", "Energy_Export",
    "Energy_Import", "Power_Factor", "Sensor_Latency", "Packet_Loss_Rate",
    "Signal_Strength", "Data_Transmission_Rate", "Edge_Node_CPU_Usage",
    "Cloud_Response_Time", "DWT_Coeff_A1", "DWT_Coeff_D1", "DWT_Coeff_D2",
    "Signal_Energy", "Signal_Entropy", "RMS_Value", "Crest_Factor",
]

# ─────────────────────────────────────────────────────────
# Singleton instances (dimuat sekali saja, malas/lazy)
# ─────────────────────────────────────────────────────────
_agent = None
_decision = None
_root_cause = None
_telegram = None
_feature_means = None  # cache rata-rata 49 fitur dari dataset
_feature_order = None  # cache FEATURE_ORDER dari agent (atau fallback)


def get_feature_order() -> list:
    """Ambil FEATURE_ORDER dari agent; fallback ke salinan lokal bila gagal."""
    global _feature_order
    if _feature_order is None:
        try:
            from .agent.anomaly_agent import FEATURE_ORDER
            _feature_order = list(FEATURE_ORDER)
        except Exception as e:
            print(f"[agent_bridge] ! Gagal import FEATURE_ORDER ({e}), pakai fallback.")
            _feature_order = list(_FEATURE_ORDER_FALLBACK)
    return _feature_order


def get_agent():
    """AnomalyAgent (singleton). Return None bila gagal dimuat."""
    global _agent
    if _agent is None:
        try:
            from .agent.anomaly_agent import AnomalyAgent
            _agent = AnomalyAgent()
        except Exception as e:
            print(f"[agent_bridge] ✗ Gagal memuat AnomalyAgent: {e}")
            _agent = None
    return _agent


def get_decision_engine():
    """DecisionEngine (singleton). Return None bila gagal dimuat."""
    global _decision
    if _decision is None:
        try:
            from .agent.decision_engine import DecisionEngine
            _decision = DecisionEngine()
        except Exception as e:
            print(f"[agent_bridge] ✗ Gagal memuat DecisionEngine: {e}")
            _decision = None
    return _decision


def get_root_cause():
    """RootCauseAnalyzer (singleton). Return None bila gagal dimuat."""
    global _root_cause
    if _root_cause is None:
        try:
            from .agent.root_cause import RootCauseAnalyzer
            _root_cause = RootCauseAnalyzer()
        except Exception as e:
            print(f"[agent_bridge] ✗ Gagal memuat RootCauseAnalyzer: {e}")
            _root_cause = None
    return _root_cause


def get_telegram():
    """TelegramAlert (singleton). Return None bila gagal dimuat."""
    global _telegram
    if _telegram is None:
        try:
            from .alert.telegram_alert import TelegramAlert
            _telegram = TelegramAlert()
        except Exception as e:
            print(f"[agent_bridge] ✗ Gagal memuat TelegramAlert: {e}")
            _telegram = None
    return _telegram


# ─────────────────────────────────────────────────────────
# Penyusunan dict 49 fitur
# ─────────────────────────────────────────────────────────
def get_feature_means() -> dict:
    """Hitung rata-rata tiap fitur dari baris berlabel 'Normal' (cache sekali).

    FIX K2 (audit): baseline default HARUS merepresentasikan sampel Normal
    sejati, bukan rata-rata SEMUA kelas. Rata-rata campuran semua kelas berada
    di area kepadatan rendah sehingga Autoencoder/KMeans menandainya anomali —
    membuat input default Live Monitor mulai dari risiko ~0.2 (false positive).
    Logika ini disamakan persis dengan tests/test_risk_score.baseline_means().

    Casing-agnostic: kolom dataset bisa lowercase, hasil dipetakan ke nama
    FEATURE_ORDER (berkapital) supaya cocok dengan AnomalyAgent.analyze().
    Bila dataset tidak ada / gagal dibaca → return {} (fitur akan jadi 0.0).
    """
    global _feature_means
    if _feature_means is not None:
        return _feature_means

    means = {}
    try:
        import pandas as pd

        if os.path.exists(DATA_PATH):
            df = pd.read_csv(DATA_PATH)
            lower_map = {str(c).lower(): c for c in df.columns}
            # Saring hanya baris kelas 'Normal' (baseline normal sejati).
            label_col = lower_map.get("system_condition_label")
            if label_col is not None:
                df = df[df[label_col] == "Normal"]
            for feat in get_feature_order():
                col = lower_map.get(feat.lower())
                if col is not None and pd.api.types.is_numeric_dtype(df[col]):
                    means[feat] = float(df[col].mean())
        else:
            print(f"[agent_bridge] ! Dataset tidak ditemukan: {DATA_PATH} "
                  f"(fitur non-input dipakai 0.0)")
    except Exception as e:
        print(f"[agent_bridge] ! Gagal hitung rata-rata fitur ({e}), pakai 0.0")

    _feature_means = means
    return _feature_means


def build_sensor_data(overrides: dict) -> dict:
    """Susun dict 49 fitur: rata-rata dataset + override manual dari slider.

    `overrides` memakai nama fitur berkapital (mis. {'PV_Voltage': 437.0}).
    Fitur yang tidak diisi memakai nilai rata-rata dataset (atau 0.0).
    """
    means = get_feature_means()
    data = {c: means.get(c, 0.0) for c in get_feature_order()}
    for k, v in (overrides or {}).items():
        try:
            data[k] = float(v)
        except (TypeError, ValueError):
            data[k] = 0.0
    return data


# ─────────────────────────────────────────────────────────
# Wrapper analisis lengkap
# ─────────────────────────────────────────────────────────
def run_full_analysis(sensor_data: dict) -> dict:
    """Jalankan analisis lengkap: agent -> decision -> root_cause -> telegram.

    Return dict gabungan (analysis + decision) yang siap dipakai State.
    Bila agent gagal dimuat, return dict default aman (tidak crash).
    """
    agent = get_agent()
    decision = get_decision_engine()
    rc = get_root_cause()
    telegram = get_telegram()

    # Fallback aman bila model inti tidak tersedia
    if agent is None:
        return {
            "timestamp": "",
            "predictions": {"error": "AnomalyAgent tidak tersedia"},
            "risk_score": 0.0,
            "risk_level": "UNKNOWN",
            "anomaly_detected": False,
            "dominant_fault": "UNKNOWN",
            "model_details": {},
            "explanation": "Model AI belum dimuat. Periksa folder models/output/.",
            "recommendations": ["Pastikan dependensi & file model tersedia."],
            "urgency": "",
            "affected_component": "Tidak diketahui",
        }

    try:
        analysis = agent.analyze(sensor_data)
    except Exception as e:
        print(f"[agent_bridge] ✗ Gagal menjalankan analyze(): {e}")
        return {
            "timestamp": "",
            "predictions": {"error": str(e)},
            "risk_score": 0.0,
            "risk_level": "UNKNOWN",
            "anomaly_detected": False,
            "dominant_fault": "UNKNOWN",
            "model_details": {},
            "explanation": f"Terjadi error saat analisis: {e}",
            "recommendations": ["Periksa log sistem"],
            "urgency": "",
            "affected_component": "Tidak diketahui",
        }

    # Keputusan (penjelasan + rekomendasi)
    decision_result = {}
    if decision is not None:
        try:
            decision_result = decision.process(analysis)
        except Exception as e:
            print(f"[agent_bridge] ! Gagal process() keputusan: {e}")

    # Simpan ke history (best effort)
    if rc is not None:
        try:
            rc.log_analysis(analysis, decision_result)
        except Exception as e:
            print(f"[agent_bridge] ! Gagal log_analysis(): {e}")

    # Kirim alert hanya untuk level berisiko (best effort, tidak boleh crash)
    if telegram is not None and analysis.get("risk_level") in (
        "MEDIUM", "HIGH", "CRITICAL"
    ):
        try:
            telegram.send_alert(analysis, decision_result)
        except Exception as e:
            print(f"[agent_bridge] ! Gagal kirim alert Telegram: {e}")

    result = {**analysis, **decision_result}

    # ── Simpan ke Supabase (history + realtime) ──────────
    # run_full_analysis dipakai BAIK oleh Live Monitor MAUPUN realtime_simulator,
    # jadi setiap analisis otomatis masuk ke kedua tabel. Semua graceful:
    # bila db_client None / DB tak tersedia, insert hanya di-skip (tidak crash).
    if db_client is not None:
        try:
            # Snapshot 5 fitur utama diambil dari sensor_data (key kapital).
            snapshot = {}
            for low, feat in _SNAPSHOT_MAP.items():
                try:
                    snapshot[low] = float(sensor_data.get(feat, 0.0))
                except (TypeError, ValueError):
                    snapshot[low] = 0.0

            db_row = {
                "timestamp": result.get("timestamp", ""),
                "risk_score": float(result.get("risk_score") or 0.0),
                "risk_level": result.get("risk_level", "UNKNOWN"),
                "dominant_fault": result.get("dominant_fault") or "Normal",
                "anomaly_detected": bool(result.get("anomaly_detected")),
                "explanation": result.get("explanation", ""),
                "recommendations": result.get("recommendations", []),
                "sensor_snapshot": snapshot,
            }
            db_client.insert_history(db_row)
            db_client.insert_realtime_result(db_row)
        except Exception as e:
            print(f"[agent_bridge] ! Gagal simpan ke Supabase: {e}")

    return result


# ─────────────────────────────────────────────────────────
# Pembacaan/penulisan data — kini lewat Supabase (semua graceful)
# ─────────────────────────────────────────────────────────
def get_realtime_data() -> list:
    """Ambil data Realtime Feed dari Supabase (list, graceful → [])."""
    if db_client is None:
        return []
    return db_client.get_realtime_results()


def get_history_data() -> list:
    """Ambil riwayat analisis dari Supabase (list, graceful → [])."""
    if db_client is None:
        return []
    return db_client.get_history()


def clear_history() -> bool:
    """Kosongkan tabel history di Supabase (graceful → False bila gagal)."""
    if db_client is None:
        return False
    return db_client.clear_history()


def get_telegram_status() -> dict:
    """Return status koneksi Telegram: {'configured': bool}."""
    bot = get_telegram()
    if bot is None:
        return {"configured": False}
    try:
        return {"configured": bool(bot.is_configured())}
    except Exception as e:
        print(f"[agent_bridge] ! Gagal cek status Telegram: {e}")
        return {"configured": False}
