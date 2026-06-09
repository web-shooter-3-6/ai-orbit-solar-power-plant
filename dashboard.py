"""
dashboard.py
────────────────────────────────────────────────────────────
AI-ORBIT Solar Monitor — Dashboard web monitoring anomali solar power plant.

Dibangun dengan Streamlit + Plotly + Lucide Icons (SVG inline).
Mengintegrasikan komponen agent:
    AnomalyAgent     -> deteksi anomali multi-model
    DecisionEngine   -> rekomendasi & penjelasan
    RootCauseAnalyzer-> simpan riwayat ke agent_memory/history.json
    TelegramAlert    -> kirim notifikasi anomali ke Telegram

Jalankan dari root repo:
    streamlit run dashboard.py
"""

import os
import sys
import json
import time
import subprocess
from pathlib import Path
from datetime import datetime

import psutil
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

import torch
torch.classes.__path__ = []  # fix warning Streamlit watcher pada torch.classes

# ── Path setup: root repo masuk sys.path supaya import paket agent/alert jalan ──
REPO_DIR = Path(__file__).resolve().parent
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

OUTPUT_DIR = REPO_DIR / "models" / "output"
DATA_PATH = REPO_DIR / "data" / "Condition_Monitoring_Dataset.csv"
HISTORY_PATH = REPO_DIR / "agent_memory" / "history.json"
REALTIME_PATH = REPO_DIR / "realtime_results.json"

APP_VERSION = "1.2.0"

# Kolom yang dibuang waktu training (bukan fitur model)
DROP_COLS = ["Timestamp", "PV_DC_Power", "System_Condition_Label"]

# ─────────────────────────────────────────
# Auto-start realtime simulator (untuk deploy cloud, mis. Railway)
# ─────────────────────────────────────────
# Guard level-PROSES: cek apakah proses simulator sudah benar-benar berjalan
# (pakai psutil), BUKAN st.session_state. Di Railway, session_state tidak
# persistent antar re-render → guard lama bisa men-spawn simulator berkali-kali.
# Set env DISABLE_AUTO_SIM=1 untuk mematikan auto-start (mis. saat dev lokal
# sudah menjalankan run_realtime.py sendiri).
def is_simulator_running():
    """True kalau ada proses python yang menjalankan realtime_simulator."""
    for proc in psutil.process_iter(['pid', 'cmdline']):
        try:
            cmdline = ' '.join(proc.info['cmdline'] or [])
            if 'realtime_simulator' in cmdline:
                return True
        except Exception:
            pass
    return False


def start_simulator_once():
    """Start simulator HANYA bila belum ada prosesnya (anti spawn ganda)."""
    if os.getenv("DISABLE_AUTO_SIM") == "1":
        return
    if not is_simulator_running():
        try:
            subprocess.Popen(
                [sys.executable, str(REPO_DIR / "scripts" / "realtime_simulator.py")],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            print("[dashboard] Simulator started")
        except Exception as e:
            print(f"[dashboard] Gagal start simulator: {e}")
    else:
        print("[dashboard] Simulator sudah jalan, skip")

# Level yang dianggap perlu alert (selaras dengan alert/telegram_alert.py)
ALERT_LEVELS = {"MEDIUM", "HIGH", "CRITICAL"}

# ─────────────────────────────────────────
# Palet warna per level risiko (dark industrial)
# ─────────────────────────────────────────
COLOR_NORMAL = "#00FF88"   # hijau
COLOR_MEDIUM = "#FFD700"   # kuning
COLOR_HIGH = "#FF6B35"     # oranye
COLOR_CRITICAL = "#FF0000" # merah

LEVEL_COLORS = {
    "LOW": COLOR_NORMAL,
    "MEDIUM": COLOR_MEDIUM,
    "HIGH": COLOR_HIGH,
    "CRITICAL": COLOR_CRITICAL,
    "UNKNOWN": "#888888",
}

# Icon + warna per level risiko
LEVEL_ICONS = {
    "LOW": ("shield", COLOR_NORMAL),
    "MEDIUM": ("alert-triangle", COLOR_MEDIUM),
    "HIGH": ("alert-triangle", COLOR_HIGH),
    "CRITICAL": ("alert-triangle", COLOR_CRITICAL),
    "UNKNOWN": ("shield", "#888888"),
}

# Skenario inject untuk Demo Otomatis (nilai ekstrem per fault)
DEMO_SCENARIOS = {
    "Normal": {
        "PV_Voltage": 437, "Battery_Temperature": 35, "Grid_Voltage": 415,
        "Sensor_Latency": 100, "PV_Panel_Temperature": 38,
    },
    "PV_Fault": {
        "PV_Voltage": 150, "PV_Current": 2, "PV_Power_Output": 1.5,
        "PV_Efficiency": 0.3, "PV_Panel_Temperature": 25,
    },
    "Battery_Overheating": {
        "Battery_Temperature": 85, "Battery_SOC": 10,
        "Battery_Voltage": 40, "Battery_Discharge_Rate": 95,
    },
    "Grid_Instability": {
        "Grid_Voltage": 550, "Grid_Frequency": 47.2,
        "Reactive_Power": 9000, "Load_Factor": 0.99,
    },
    "Inverter_Fault": {
        "PV_AC_Power": 0.5, "PV_Inverter_Temperature": 90,
        "Power_Factor": 0.3, "PV_Frequency": 48.0,
    },
    "Communication_Failure": {
        "Sensor_Latency": 9000, "Packet_Loss_Rate": 0.95,
        "Signal_Strength": -100, "Edge_Node_CPU_Usage": 99,
    },
}
DEMO_ORDER = [
    "Normal", "PV_Fault", "Battery_Overheating",
    "Grid_Instability", "Inverter_Fault", "Communication_Failure",
]


# ─────────────────────────────────────────
# Lucide Icons (SVG inline)
# ─────────────────────────────────────────
def lucide_icon(name, size=16, color="currentColor"):
    icons = {
        "activity": '<svg xmlns="http://www.w3.org/2000/svg" width="{s}" height="{s}" viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline></svg>',
        "alert-triangle": '<svg xmlns="http://www.w3.org/2000/svg" width="{s}" height="{s}" viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>',
        "bar-chart": '<svg xmlns="http://www.w3.org/2000/svg" width="{s}" height="{s}" viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="20" x2="18" y2="10"></line><line x1="12" y1="20" x2="12" y2="4"></line><line x1="6" y1="20" x2="6" y2="14"></line></svg>',
        "clock": '<svg xmlns="http://www.w3.org/2000/svg" width="{s}" height="{s}" viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>',
        "cpu": '<svg xmlns="http://www.w3.org/2000/svg" width="{s}" height="{s}" viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="4" width="16" height="16" rx="2" ry="2"></rect><rect x="9" y="9" width="6" height="6"></rect><line x1="9" y1="1" x2="9" y2="4"></line><line x1="15" y1="1" x2="15" y2="4"></line><line x1="9" y1="20" x2="9" y2="23"></line><line x1="15" y1="20" x2="15" y2="23"></line><line x1="20" y1="9" x2="23" y2="9"></line><line x1="20" y1="14" x2="23" y2="14"></line><line x1="1" y1="9" x2="4" y2="9"></line><line x1="1" y1="14" x2="4" y2="14"></line></svg>',
        "list": '<svg xmlns="http://www.w3.org/2000/svg" width="{s}" height="{s}" viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="8" y1="6" x2="21" y2="6"></line><line x1="8" y1="12" x2="21" y2="12"></line><line x1="8" y1="18" x2="21" y2="18"></line><line x1="3" y1="6" x2="3.01" y2="6"></line><line x1="3" y1="12" x2="3.01" y2="12"></line><line x1="3" y1="18" x2="3.01" y2="18"></line></svg>',
        "play": '<svg xmlns="http://www.w3.org/2000/svg" width="{s}" height="{s}" viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>',
        "send": '<svg xmlns="http://www.w3.org/2000/svg" width="{s}" height="{s}" viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>',
        "shield": '<svg xmlns="http://www.w3.org/2000/svg" width="{s}" height="{s}" viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path></svg>',
        "sun": '<svg xmlns="http://www.w3.org/2000/svg" width="{s}" height="{s}" viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"></circle><line x1="12" y1="1" x2="12" y2="3"></line><line x1="12" y1="21" x2="12" y2="23"></line><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line><line x1="1" y1="12" x2="3" y2="12"></line><line x1="21" y1="12" x2="23" y2="12"></line><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line></svg>',
        "trash": '<svg xmlns="http://www.w3.org/2000/svg" width="{s}" height="{s}" viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"></path></svg>',
        "wifi-off": '<svg xmlns="http://www.w3.org/2000/svg" width="{s}" height="{s}" viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="1" y1="1" x2="23" y2="23"></line><path d="M16.72 11.06A10.94 10.94 0 0 1 19 12.55"></path><path d="M5 12.55a10.94 10.94 0 0 1 5.17-2.39"></path><path d="M10.71 5.05A16 16 0 0 1 22.56 9"></path><path d="M1.42 9a15.91 15.91 0 0 1 4.7-2.88"></path><path d="M8.53 16.11a6 6 0 0 1 6.95 0"></path><line x1="12" y1="20" x2="12.01" y2="20"></line></svg>',
        "zap": '<svg xmlns="http://www.w3.org/2000/svg" width="{s}" height="{s}" viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon></svg>',
        "download": '<svg xmlns="http://www.w3.org/2000/svg" width="{s}" height="{s}" viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>',
        "check-circle": '<svg xmlns="http://www.w3.org/2000/svg" width="{s}" height="{s}" viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>',
        "x-circle": '<svg xmlns="http://www.w3.org/2000/svg" width="{s}" height="{s}" viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg>',
    }
    svg = icons.get(name, icons["activity"])
    return svg.replace("{s}", str(size)).replace("{c}", color)


def icon_header(icon_name, text, size=22, color=COLOR_NORMAL, tag="h2"):
    """Render header: icon + teks dalam satu baris (via markdown HTML)."""
    st.markdown(
        f'<{tag} style="display:flex;align-items:center;gap:10px;margin-bottom:4px;">'
        f'{lucide_icon(icon_name, size, color)}<span>{text}</span></{tag}>',
        unsafe_allow_html=True,
    )


def labeled_value(icon_name, label, value, color="#aaa"):
    """Kartu kecil: icon + label di atas, value monospace di bawah."""
    return (
        '<div style="background:#141a24;border:1px solid #222b38;border-radius:8px;'
        'padding:12px 14px;margin-bottom:8px;">'
        f'<div style="display:flex;align-items:center;gap:6px;font-size:12px;'
        f'color:{color};letter-spacing:1px;">{lucide_icon(icon_name, 14, color)}'
        f'<span>{label}</span></div>'
        f'<div class="sensor-value" style="font-size:20px;color:#e8e8e8;'
        f'margin-top:4px;">{value}</div></div>'
    )


# ─────────────────────────────────────────
# Konfigurasi halaman
# ─────────────────────────────────────────
st.set_page_config(
    layout="wide",
    page_title="AI-ORBIT Solar Monitor",
    page_icon="⚡",
)

# ─────────────────────────────────────────
# CSS — dark mode industrial
# ─────────────────────────────────────────
st.markdown(
    """
    <style>
    .stApp { background-color: #0a0e14; color: #e0e0e0; }
    section[data-testid="stSidebar"] { background-color: #11161f; }
    h1, h2, h3 { color: #e8e8e8 !important; letter-spacing: 0.5px; }
    .sensor-value { font-family: 'Courier New', monospace; font-weight: bold; }
    .risk-card {
        border-radius: 10px; padding: 22px; text-align: center;
        font-family: 'Courier New', monospace; margin-bottom: 12px;
    }
    .risk-card h1 { font-size: 56px; margin: 0; }
    .risk-card .lbl { font-size: 14px; letter-spacing: 2px; opacity: 0.8; }
    div[data-testid="stMetricValue"] { font-family: 'Courier New', monospace; }
    .scenario-card {
        border-left: 6px solid #888; border-radius: 6px;
        padding: 12px 16px; margin: 8px 0;
        background-color: #141a24; font-family: 'Courier New', monospace;
    }
    .status-line {
        display: flex; align-items: center; gap: 6px;
        font-family: 'Courier New', monospace; font-size: 13px; margin: 4px 0;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ─────────────────────────────────────────
# Loader (cache)
# ─────────────────────────────────────────
@st.cache_resource(show_spinner="Memuat model AI...")
def load_agent():
    """Load AnomalyAgent + DecisionEngine + RootCauseAnalyzer (cache resource)."""
    from agent.anomaly_agent import AnomalyAgent, FEATURE_ORDER
    from agent.decision_engine import DecisionEngine
    from agent.root_cause import RootCauseAnalyzer

    agent = AnomalyAgent()
    engine = DecisionEngine()
    rootcause = RootCauseAnalyzer()
    return agent, engine, rootcause, FEATURE_ORDER


@st.cache_resource(show_spinner=False)
def load_telegram():
    """Load TelegramAlert (gracefully disabled kalau modul/.env tidak ada)."""
    try:
        from alert.telegram_alert import TelegramAlert
        return TelegramAlert()
    except Exception as e:
        print(f"[dashboard] TelegramAlert tidak tersedia: {e}")
        return None


@st.cache_data(show_spinner="Memuat dataset...")
def load_feature_means():
    """Hitung rata-rata tiap fitur dari dataset (untuk fitur tak diinput).

    Casing-agnostic: dataset bisa lowercase (mis. 'pv_voltage'), tapi key
    hasil dipetakan ke nama FEATURE_ORDER (kapital, mis. 'PV_Voltage') supaya
    cocok dengan yang dipakai build_sensor_data → AnomalyAgent.analyze().
    """
    if not DATA_PATH.exists():
        return {}
    from agent.anomaly_agent import FEATURE_ORDER
    df = pd.read_csv(DATA_PATH)
    # peta lowercase → nama kolom asli, supaya tahan apapun casing CSV
    lower_map = {str(c).lower(): c for c in df.columns}
    means = {}
    for feat in FEATURE_ORDER:
        col = lower_map.get(feat.lower())
        if col is not None and pd.api.types.is_numeric_dtype(df[col]):
            means[feat] = float(df[col].mean())
    return means


def models_available() -> bool:
    """Cek apakah file model inti sudah ada di models/output/."""
    required = [
        "xgboost_model.pkl", "isolation_forest_model.pkl", "kmeans_model.pkl",
        "autoencoder_model.pt", "lstm_model.pt", "scaler.pkl", "label_encoder.pkl",
    ]
    return all((OUTPUT_DIR / f).exists() for f in required)


# ─────────────────────────────────────────
# History helper
# ─────────────────────────────────────────
def read_history() -> list:
    """Baca history.json → list (kosong kalau tidak ada / rusak)."""
    try:
        with open(HISTORY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    except Exception:
        return []


def clear_history():
    """Kosongkan history.json."""
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump([], f, ensure_ascii=False, indent=2)


def clear_realtime():
    """Kosongkan realtime_results.json supaya statistik Realtime Feed kembali 0.

    Pakai FileLock (lock yang sama dengan simulator) agar reset tidak tabrakan
    dengan penulis konkuren. Kalau filelock tak tersedia, fallback tulis biasa.
    """
    try:
        from filelock import FileLock
        lock = FileLock(str(REALTIME_PATH) + ".lock", timeout=5)
        with lock:
            with open(REALTIME_PATH, "w", encoding="utf-8") as f:
                json.dump([], f, ensure_ascii=False, indent=2)
    except Exception:
        # Fallback: tetap coba tulis kosong walau lock gagal/tidak ada
        try:
            with open(REALTIME_PATH, "w", encoding="utf-8") as f:
                json.dump([], f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[dashboard] Gagal reset realtime: {e}")


def read_realtime() -> list:
    """Baca realtime_results.json → list (kosong kalau tidak ada / rusak)."""
    try:
        with open(REALTIME_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    except Exception:
        return []


def build_sensor_data(feature_means: dict, overrides: dict, feature_order: list) -> dict:
    """Susun dict 49 fitur: rata-rata dataset + override manual."""
    data = {c: feature_means.get(c, 0.0) for c in feature_order}
    for k, v in overrides.items():
        data[k] = float(v)
    return data


def run_analysis(agent, engine, rootcause, sensor_data: dict, force_fault: str = None) -> dict:
    """Jalankan analyze → process → log. Return gabungan hasil untuk display."""
    analysis = agent.analyze(sensor_data)
    # Untuk demo inject: paksa dominant_fault sesuai skenario (ground-truth diketahui)
    if force_fault and force_fault != "Normal":
        analysis["dominant_fault"] = force_fault
        analysis["anomaly_detected"] = True
    decision = engine.process(analysis)
    rootcause.log_analysis(analysis, decision)
    return {"analysis": analysis, "decision": decision}


def maybe_send_alert(bot, analysis: dict, decision: dict) -> str:
    """Kirim alert Telegram bila level perlu. Return status: sent/failed/notconfig/skip."""
    level = analysis.get("risk_level", "UNKNOWN")
    if level not in ALERT_LEVELS:
        return "skip"
    if bot is None or not bot.is_configured():
        return "notconfig"
    return "sent" if bot.send_alert(analysis, decision) else "failed"


# ─────────────────────────────────────────
# Komponen UI reusable
# ─────────────────────────────────────────
def risk_card(level: str, score: float):
    """Kartu besar RISK SCORE + LEVEL berwarna + icon sesuai level."""
    color = LEVEL_COLORS.get(level, "#888888")
    icon_name, icon_color = LEVEL_ICONS.get(level, ("shield", "#888888"))
    st.markdown(
        f"""
        <div class="risk-card" style="background-color:{color}1a; border:2px solid {color};">
            <div class="lbl">RISK SCORE</div>
            <h1 style="color:{color};">{score:.2f}</h1>
            <div class="lbl" style="color:{color}; font-size:20px;
                 display:flex;align-items:center;justify-content:center;gap:8px;">
                 {lucide_icon(icon_name, 18, icon_color)}<span>{level}</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def show_result(result: dict):
    """Tampilkan hasil analisis lengkap (dipakai Live Monitor)."""
    analysis = result["analysis"]
    decision = result["decision"]
    level = analysis["risk_level"]
    score = analysis["risk_score"]

    c1, c2, c3 = st.columns([1.2, 1, 1])
    with c1:
        risk_card(level, score)
    with c2:
        st.markdown(
            labeled_value("cpu", "Fault Terdeteksi", analysis["dominant_fault"]),
            unsafe_allow_html=True,
        )
        st.markdown(
            labeled_value("clock", "Urgency", decision["urgency"]),
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown(
            labeled_value(
                "shield", "Anomaly Detected",
                "YA" if analysis["anomaly_detected"] else "TIDAK",
            ),
            unsafe_allow_html=True,
        )
        st.markdown(
            labeled_value("sun", "Komponen", decision["affected_component"]),
            unsafe_allow_html=True,
        )

    with st.expander("Detail per Model", expanded=True):
        preds = analysis.get("predictions", {})
        df_pred = pd.DataFrame(
            [{"Model": k, "Hasil": str(v)} for k, v in preds.items()]
        )
        st.dataframe(df_pred, hide_index=True)

        details = analysis.get("model_details", {})
        if details:
            st.caption("Nilai numerik mentah tiap model:")
            st.json(details)

    with st.expander("Rekomendasi"):
        for rec in decision["recommendations"]:
            st.markdown(f"- {rec}")

    with st.expander("Penjelasan"):
        st.info(decision["explanation"])


# ─────────────────────────────────────────
# HALAMAN 1 — Live Monitor
# ─────────────────────────────────────────
def page_live_monitor(agent, engine, rootcause, bot, feature_means, feature_order):
    icon_header("activity", "Live Monitor", 26, COLOR_NORMAL, tag="h1")
    st.caption("Masukkan nilai sensor manual lalu jalankan analisis multi-model.")

    with st.form("sensor_form"):
        col1, col2 = st.columns(2)
        with col1:
            pv_voltage = st.slider("PV_Voltage (V)", 100, 600, 437)
            pv_temp = st.slider("PV_Panel_Temperature (°C)", 10, 100, 38)
            batt_temp = st.slider("Battery_Temperature (°C)", 10, 100, 35)
        with col2:
            grid_voltage = st.slider("Grid_Voltage (V)", 200, 600, 415)
            sensor_latency = st.slider("Sensor_Latency (ms)", 0, 10000, 100)

        st.markdown(
            f'<div class="status-line">{lucide_icon("cpu", 14, "#aaa")}'
            f'<span>Klik untuk menjalankan 5 model deteksi anomali</span></div>',
            unsafe_allow_html=True,
        )
        submitted = st.form_submit_button("Analisis Sekarang")

    if submitted:
        overrides = {
            "PV_Voltage": pv_voltage,
            "PV_Panel_Temperature": pv_temp,
            "Battery_Temperature": batt_temp,
            "Grid_Voltage": grid_voltage,
            "Sensor_Latency": sensor_latency,
        }
        sensor_data = build_sensor_data(feature_means, overrides, feature_order)
        with st.spinner("Menganalisis..."):
            result = run_analysis(agent, engine, rootcause, sensor_data)
        st.session_state["last_result"] = result
        st.success("Analisis selesai & tersimpan ke history.")

        # Kirim alert Telegram bila level MEDIUM/HIGH/CRITICAL
        status = maybe_send_alert(bot, result["analysis"], result["decision"])
        if status == "sent":
            st.success("Alert Telegram terkirim!")
        elif status == "notconfig":
            st.warning("Telegram belum dikonfigurasi")
        elif status == "failed":
            st.error("Gagal mengirim alert Telegram (cek token/koneksi).")

    # Tampilkan hasil terakhir (persist via session_state)
    if "last_result" in st.session_state:
        st.divider()
        show_result(st.session_state["last_result"])
    else:
        st.info("Belum ada analisis. Atur slider lalu klik **Analisis Sekarang**.")


# ─────────────────────────────────────────
# HALAMAN 2 — Statistik & Grafik
# ─────────────────────────────────────────
def page_statistics():
    icon_header("bar-chart", "Statistik & Grafik", 26, COLOR_NORMAL, tag="h1")
    history = read_history()

    if not history:
        st.warning("Belum ada data. Jalankan analisis dulu di Live Monitor.")
        return

    df = pd.DataFrame(history)
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df["hour"] = df["timestamp"].dt.hour

    total = len(df)
    # anomali dihitung dari risk_score > 0.25 (selaras logika analyze baru)
    anomali = int((pd.to_numeric(df["risk_score"], errors="coerce") > 0.25).sum())
    rate = (anomali / total * 100) if total else 0.0
    fault_sering = df["dominant_fault"].mode()
    fault_sering = fault_sering.iloc[0] if not fault_sering.empty else "-"

    m1, m2, m3, m4 = st.columns(4)
    m1.markdown(labeled_value("list", "Total Analisis", total, COLOR_NORMAL), unsafe_allow_html=True)
    m2.markdown(labeled_value("alert-triangle", "Total Anomali", anomali, COLOR_HIGH), unsafe_allow_html=True)
    m3.markdown(labeled_value("activity", "Anomali Rate", f"{rate:.1f}%", COLOR_MEDIUM), unsafe_allow_html=True)
    m4.markdown(labeled_value("cpu", "Fault Tersering", fault_sering, COLOR_NORMAL), unsafe_allow_html=True)

    st.divider()

    col1, col2 = st.columns(2)
    with col1:
        icon_header("bar-chart", "Distribusi Tipe Fault", 18, COLOR_NORMAL, tag="h3")
        fault_counts = df["dominant_fault"].value_counts().reset_index()
        fault_counts.columns = ["fault", "jumlah"]
        colors = [COLOR_NORMAL if f == "Normal" else COLOR_CRITICAL
                  for f in fault_counts["fault"]]
        fig1 = go.Figure(go.Bar(
            x=fault_counts["fault"], y=fault_counts["jumlah"], marker_color=colors,
        ))
        fig1.update_layout(template="plotly_dark", height=350, margin=dict(t=20, b=20))
        st.plotly_chart(fig1, width='stretch')

    with col2:
        icon_header("activity", "Distribusi Risk Level", 18, COLOR_NORMAL, tag="h3")
        level_counts = df["risk_level"].value_counts().reset_index()
        level_counts.columns = ["level", "jumlah"]
        fig3 = px.pie(
            level_counts, names="level", values="jumlah", hole=0.45,
            color="level", color_discrete_map=LEVEL_COLORS,
        )
        fig3.update_layout(template="plotly_dark", height=350, margin=dict(t=20, b=20))
        st.plotly_chart(fig3, width='stretch')

    icon_header("activity", "Risk Score Timeline", 18, COLOR_NORMAL, tag="h3")
    df_sorted = df.sort_values("timestamp")
    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(
        x=df_sorted["timestamp"], y=df_sorted["risk_score"],
        mode="lines+markers", line=dict(color=COLOR_MEDIUM), name="Risk Score",
    ))
    fig2.add_hline(y=0.3, line_dash="dash", line_color=COLOR_MEDIUM,
                   annotation_text="MEDIUM (0.3)")
    fig2.add_hline(y=0.6, line_dash="dash", line_color=COLOR_HIGH,
                   annotation_text="HIGH (0.6)")
    fig2.update_layout(template="plotly_dark", height=350, margin=dict(t=20, b=20),
                       yaxis_range=[0, 1.05])
    st.plotly_chart(fig2, width='stretch')

    icon_header("clock", "Anomali per Jam", 18, COLOR_NORMAL, tag="h3")
    anom_df = df[df["dominant_fault"] != "Normal"]
    if anom_df.empty:
        st.caption("Belum ada anomali tercatat.")
    else:
        hour_counts = anom_df["hour"].value_counts().reindex(range(24), fill_value=0)
        fig4 = go.Figure(go.Bar(
            x=list(range(24)), y=hour_counts.values, marker_color=hour_counts.values,
            marker_colorscale=[[0, COLOR_NORMAL], [0.5, COLOR_HIGH], [1, COLOR_CRITICAL]],
        ))
        fig4.update_layout(template="plotly_dark", height=320, margin=dict(t=20, b=20),
                           xaxis_title="Jam (0-23)", yaxis_title="Jumlah anomali")
        st.plotly_chart(fig4, width='stretch')


# ─────────────────────────────────────────
# HALAMAN 3 — History Anomali
# ─────────────────────────────────────────
def page_history():
    icon_header("list", "History Anomali", 26, COLOR_NORMAL, tag="h1")
    history = read_history()

    if not history:
        st.warning("Belum ada data. Jalankan analisis dulu di Live Monitor.")
        return

    df = pd.DataFrame(history)

    # Filter di sidebar
    st.sidebar.divider()
    icon_sidebar("list", "Filter History", COLOR_NORMAL)
    levels = sorted(df["risk_level"].dropna().unique().tolist())
    faults = sorted(df["dominant_fault"].dropna().unique().tolist())
    sel_levels = st.sidebar.multiselect("Risk Level", levels, default=levels)
    sel_faults = st.sidebar.multiselect("Fault Type", faults, default=faults)

    filtered = df[
        df["risk_level"].isin(sel_levels) & df["dominant_fault"].isin(sel_faults)
    ].copy()

    def trunc(recs):
        txt = "; ".join(recs) if isinstance(recs, list) else str(recs)
        return txt[:60] + "…" if len(txt) > 60 else txt

    table = pd.DataFrame({
        "Timestamp": filtered["timestamp"],
        "Risk Score": filtered["risk_score"],
        "Risk Level": filtered["risk_level"],
        "Fault": filtered["dominant_fault"],
        "Rekomendasi": filtered["recommendations"].apply(trunc),
    })

    def color_row(row):
        color = LEVEL_COLORS.get(row["Risk Level"], "#888888")
        return [f"background-color: {color}22; color: #e8e8e8"] * len(row)

    st.caption(f"Menampilkan **{len(table)}** dari {len(df)} entri.")
    if table.empty:
        st.info("Tidak ada entri yang cocok dengan filter.")
    else:
        st.dataframe(
            table.style.apply(color_row, axis=1),
            hide_index=True,
        )

    st.divider()
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(
            f'<div class="status-line">{lucide_icon("download", 14, "#aaa")}'
            f'<span>Export riwayat ke CSV</span></div>',
            unsafe_allow_html=True,
        )
        csv = table.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Download CSV", data=csv, file_name="history_anomali.csv",
            mime="text/csv",
        )
    with c2:
        st.markdown(
            f'<div class="status-line">{lucide_icon("trash", 14, COLOR_HIGH)}'
            f'<span>Hapus seluruh riwayat</span></div>',
            unsafe_allow_html=True,
        )
        if st.button("Clear History"):
            st.session_state["confirm_clear"] = True

    if st.session_state.get("confirm_clear"):
        st.warning("Yakin ingin menghapus SEMUA riwayat? Tindakan ini tidak bisa dibatalkan.")
        cc1, cc2 = st.columns(2)
        if cc1.button("Ya, hapus"):
            clear_history()
            st.session_state["confirm_clear"] = False
            st.success("History berhasil dihapus.")
            st.rerun()
        if cc2.button("Batal"):
            st.session_state["confirm_clear"] = False
            st.rerun()


# ─────────────────────────────────────────
# HALAMAN 4 — Demo Otomatis
# ─────────────────────────────────────────
def page_demo(agent, engine, rootcause, bot, feature_means, feature_order):
    icon_header("play", "Demo Otomatis", 26, COLOR_NORMAL, tag="h1")
    st.markdown(
        "Demo ini mensimulasikan **6 skenario anomali** secara berurutan "
        "(Normal, PV_Fault, Battery_Overheating, Grid_Instability, "
        "Inverter_Fault, Communication_Failure). "
        "Hasil tiap skenario ikut tersimpan ke history; skenario anomali "
        "memicu alert Telegram (bila dikonfigurasi)."
    )

    st.markdown(
        f'<div class="status-line">{lucide_icon("play", 14, "#aaa")}'
        f'<span>Jalankan 6 skenario sekaligus</span></div>',
        unsafe_allow_html=True,
    )
    if st.button("Jalankan Demo"):
        progress = st.progress(0, text="Memulai demo...")
        results = []
        alert_sent = 0
        for i, fault in enumerate(DEMO_ORDER, start=1):
            overrides = DEMO_SCENARIOS[fault]
            sensor_data = build_sensor_data(feature_means, overrides, feature_order)
            result = run_analysis(agent, engine, rootcause, sensor_data, force_fault=fault)
            if maybe_send_alert(bot, result["analysis"], result["decision"]) == "sent":
                alert_sent += 1
            results.append((fault, result))
            progress.progress(i / len(DEMO_ORDER),
                              text=f"Skenario {i}/{len(DEMO_ORDER)}: {fault}")
            time.sleep(0.3)
        progress.empty()
        st.session_state["demo_results"] = results
        st.session_state["demo_alert_sent"] = alert_sent
        st.success("Demo selesai!")

    if "demo_results" in st.session_state:
        results = st.session_state["demo_results"]
        st.divider()

        anomali_count = 0
        for fault, result in results:
            analysis = result["analysis"]
            decision = result["decision"]
            level = analysis["risk_level"]
            color = LEVEL_COLORS.get(level, "#888888")
            icon_name, icon_color = LEVEL_ICONS.get(level, ("shield", "#888888"))
            if analysis["anomaly_detected"]:
                anomali_count += 1

            head_icon = lucide_icon(icon_name, 14, icon_color)
            with st.expander(f"{fault} — {level} (score {analysis['risk_score']:.2f})"):
                st.markdown(
                    f"""<div class="scenario-card" style="border-left-color:{color};">
                    <div style="display:flex;align-items:center;gap:8px;">
                    {head_icon}<b style="color:{color};">RISK {analysis['risk_score']:.2f} — {level}</b></div>
                    Fault: {analysis['dominant_fault']}<br>
                    Anomaly: {'YA' if analysis['anomaly_detected'] else 'TIDAK'}<br>
                    {decision['explanation']}
                    </div>""",
                    unsafe_allow_html=True,
                )
                st.caption("Rekomendasi:")
                for rec in decision["recommendations"]:
                    st.markdown(f"- {rec}")

        st.divider()
        col1, col2 = st.columns(2)
        col1.markdown(
            labeled_value("alert-triangle", "Anomali Terdeteksi",
                          f"{anomali_count} / {len(results)} skenario", COLOR_HIGH),
            unsafe_allow_html=True,
        )
        col2.markdown(
            labeled_value("send", "Alert Telegram Terkirim",
                          f"{st.session_state.get('demo_alert_sent', 0)} alert", COLOR_NORMAL),
            unsafe_allow_html=True,
        )


# ─────────────────────────────────────────
# HALAMAN 5 — Realtime Feed
# ─────────────────────────────────────────
def page_realtime(auto_refresh: bool):
    icon_header("cpu", "Realtime Feed", 26, COLOR_NORMAL, tag="h1")
    st.caption("Hasil analisis real-time yang diproses otomatis oleh sistem.")

    # read_realtime() sudah membaca file dengan try/except dan hanya
    # mengembalikan list bila file ADA, TIDAK kosong, dan JSON valid.
    data = read_realtime()
    if not data:
        # Bedakan dua kondisi:
        # - File belum ada sama sekali → sistem memang belum memproses.
        # - File ada tapi kosong/korup/belum valid → sedang loading, coba lagi.
        if REALTIME_PATH.exists():
            st.info("Memuat data...")
            time.sleep(2)
            st.rerun()
        else:
            st.warning("Data realtime sedang diproses otomatis oleh sistem.")
        return

    df = pd.DataFrame(data)
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.sort_values("timestamp").reset_index(drop=True)

    # ── Metric row ──────────────────────────────────────────
    # Total Realtime = jumlah semua entri di file
    total = len(df)

    # Anomali = entri dengan anomaly_detected == True ATAU risk_score > 0.25
    risk_num = pd.to_numeric(df["risk_score"], errors="coerce").fillna(0.0)
    anomaly_flag = risk_num > 0.25
    if "anomaly_detected" in df.columns:
        anomaly_flag = df["anomaly_detected"].fillna(False).astype(bool) | anomaly_flag
    anomali = int(anomaly_flag.sum())

    # Fault Tersering = dominant_fault paling sering; kecualikan "Normal"
    # selama masih ada fault lain (biar tidak selalu "Normal").
    faults = df["dominant_fault"].dropna().astype(str)
    faults = faults[faults.str.strip() != ""]
    non_normal = faults[faults != "Normal"]
    if not non_normal.empty:
        fault_sering = non_normal.value_counts().idxmax()
    elif not faults.empty:
        fault_sering = faults.value_counts().idxmax()
    else:
        fault_sering = "-"

    # Last Update = timestamp entri paling terakhir
    last_ts = df["timestamp"].max()
    last_str = last_ts.strftime("%H:%M:%S") if pd.notnull(last_ts) else "-"

    m1, m2, m3, m4 = st.columns(4)
    m1.markdown(labeled_value("list", "Total Realtime", total, COLOR_NORMAL),
                unsafe_allow_html=True)
    m2.markdown(labeled_value("alert-triangle", "Anomali", anomali, COLOR_HIGH),
                unsafe_allow_html=True)
    m3.markdown(labeled_value("cpu", "Fault Tersering", fault_sering, COLOR_NORMAL),
                unsafe_allow_html=True)
    m4.markdown(labeled_value("clock", "Last Update", last_str, COLOR_MEDIUM),
                unsafe_allow_html=True)

    st.divider()

    # ── Tabel 10 analisis terbaru ───────────────────────────
    icon_header("list", "10 Analisis Terbaru", 18, COLOR_NORMAL, tag="h3")
    recent = df.tail(10).iloc[::-1]  # terbaru di atas

    def trunc(recs):
        txt = "; ".join(recs) if isinstance(recs, list) else str(recs)
        return txt[:50] + "…" if len(txt) > 50 else txt

    table = pd.DataFrame({
        "Waktu": recent["timestamp"].dt.strftime("%H:%M:%S"),
        "Risk Score": recent["risk_score"],
        "Level": recent["risk_level"],
        "Fault": recent["dominant_fault"],
        "Rekomendasi": recent["recommendations"].apply(trunc),
    })

    def color_row(row):
        color = LEVEL_COLORS.get(row["Level"], "#888888")
        return [f"background-color: {color}22; color: #e8e8e8"] * len(row)

    st.dataframe(table.style.apply(color_row, axis=1),
                 hide_index=True)

    # ── Line chart risk score 20 terakhir ───────────────────
    icon_header("activity", "Risk Score (20 data terakhir)", 18, COLOR_NORMAL, tag="h3")
    last20 = df.tail(20)
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=last20["timestamp"], y=last20["risk_score"],
        mode="lines+markers", line=dict(color=COLOR_MEDIUM), name="Risk Score",
    ))
    fig.add_hline(y=0.25, line_dash="dash", line_color=COLOR_MEDIUM,
                  annotation_text="MEDIUM (0.25)")
    fig.add_hline(y=0.50, line_dash="dash", line_color=COLOR_HIGH,
                  annotation_text="HIGH (0.50)")
    fig.add_hline(y=0.75, line_dash="dash", line_color=COLOR_CRITICAL,
                  annotation_text="CRITICAL (0.75)")
    fig.update_layout(template="plotly_dark", height=340, margin=dict(t=20, b=20),
                      yaxis_range=[0, 1.05])
    st.plotly_chart(fig, width='stretch')

    # ── Card "Analisis Terbaru" ─────────────────────────────
    st.divider()
    icon_header("activity", "Analisis Terbaru", 18, COLOR_NORMAL, tag="h3")
    latest = df.iloc[-1]
    level = latest["risk_level"]
    score = float(latest["risk_score"]) if pd.notnull(latest["risk_score"]) else 0.0

    c1, c2 = st.columns([1.2, 1.8])
    with c1:
        risk_card(level, score)
    with c2:
        st.markdown(
            labeled_value("cpu", "Fault Terdeteksi", latest["dominant_fault"]),
            unsafe_allow_html=True,
        )
        snap = latest.get("sensor_snapshot", {}) or {}
        snap_txt = " | ".join(f"{k}={v}" for k, v in snap.items())
        st.markdown(
            labeled_value("sun", "Sensor Snapshot", snap_txt or "-", "#aaa"),
            unsafe_allow_html=True,
        )

    with st.expander("Penjelasan & Rekomendasi", expanded=True):
        st.info(latest.get("explanation", "-"))
        recs = latest.get("recommendations", [])
        if isinstance(recs, list):
            for rec in recs:
                st.markdown(f"- {rec}")

    # ── Reset data realtime (Total kembali 0) ───────────────
    st.divider()
    st.markdown(
        f'<div class="status-line">{lucide_icon("trash", 14, COLOR_HIGH)}'
        f'<span>Hapus semua data realtime — statistik kembali 0</span></div>',
        unsafe_allow_html=True,
    )
    if st.button("Reset Data Realtime"):
        st.session_state["confirm_reset_rt"] = True

    if st.session_state.get("confirm_reset_rt"):
        st.warning("Yakin hapus SEMUA data realtime? Tindakan ini tidak bisa dibatalkan.")
        rc1, rc2 = st.columns(2)
        if rc1.button("Ya, reset"):
            clear_realtime()
            st.session_state["confirm_reset_rt"] = False
            st.success("Data realtime berhasil direset.")
            st.rerun()
        if rc2.button("Batal"):
            st.session_state["confirm_reset_rt"] = False
            st.rerun()

    # ── Auto-refresh: tunggu 3 detik lalu rerun ─────────────
    # Saat dialog konfirmasi reset terbuka, jangan auto-rerun supaya tombol
    # konfirmasi tidak hilang sebelum sempat diklik.
    if auto_refresh and not st.session_state.get("confirm_reset_rt"):
        time.sleep(3)
        st.rerun()


# ─────────────────────────────────────────
# Sidebar helper
# ─────────────────────────────────────────
def icon_sidebar(icon_name, text, color="#aaa", size=16):
    """Render baris icon + teks di sidebar."""
    st.sidebar.markdown(
        f'<div class="status-line" style="font-size:14px;font-weight:bold;">'
        f'{lucide_icon(icon_name, size, color)}<span>{text}</span></div>',
        unsafe_allow_html=True,
    )


def sidebar_status(icon_name, label, value, color):
    """Render baris status (model/telegram) dengan icon berwarna."""
    st.sidebar.markdown(
        f'<div class="status-line">{lucide_icon(icon_name, 14, color)}'
        f'<span><b>{label}:</b> <span style="color:{color};">{value}</span></span></div>',
        unsafe_allow_html=True,
    )


# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────
NAV_ITEMS = {
    "Live Monitor": "activity",
    "Realtime Feed": "cpu",
    "Statistik & Grafik": "bar-chart",
    "History Anomali": "list",
    "Demo Otomatis": "play",
}


def main():
    # Auto-start simulator realtime di background (anti spawn ganda via psutil)
    start_simulator_once()

    # Sidebar — logo (icon zap) + judul
    st.sidebar.markdown(
        f'<div style="display:flex;align-items:center;gap:10px;">'
        f'{lucide_icon("zap", 24, COLOR_NORMAL)}'
        f'<span style="font-size:22px;font-weight:bold;color:#e8e8e8;">AI-ORBIT</span></div>',
        unsafe_allow_html=True,
    )
    st.sidebar.caption("Solar Power Plant Anomaly Monitor")

    # ── Navigasi: SATU menu saja — tombol dengan icon Lucide SVG ──
    # (Sebelumnya ada 2 elemen: legend statis + st.radio → tampak double.
    #  Sekarang icon Lucide langsung jadi tombol yang bisa diklik.)
    if "page" not in st.session_state:
        st.session_state["page"] = "Live Monitor"

    st.sidebar.markdown('<div style="height:4px;"></div>', unsafe_allow_html=True)
    for name, ic in NAV_ITEMS.items():
        active = st.session_state["page"] == name
        color = COLOR_NORMAL if active else "#9aa"
        col_icon, col_btn = st.sidebar.columns([1, 5], vertical_alignment="center")
        with col_icon:
            st.markdown(
                f'<div style="padding-top:6px;text-align:center;">'
                f'{lucide_icon(ic, 18, color)}</div>',
                unsafe_allow_html=True,
            )
        with col_btn:
            if st.button(
                name, key=f"nav_{name}",
                type="primary" if active else "secondary",
            ):
                st.session_state["page"] = name
                st.rerun()

    page = st.session_state["page"]

    # Toggle auto-refresh untuk halaman Realtime Feed
    st.sidebar.divider()
    auto_refresh = st.sidebar.toggle("Auto-refresh (Realtime, 3 detik)", value=False)

    model_ok = models_available()
    bot = load_telegram()
    telegram_ok = bool(bot and bot.is_configured())

    # Info sidebar — versi, status model, status telegram
    st.sidebar.divider()
    icon_sidebar("zap", "Status Sistem", COLOR_NORMAL)
    st.sidebar.markdown(
        f'<div class="status-line"><span><b>Versi App:</b> '
        f'<span class="sensor-value">{APP_VERSION}</span></span></div>',
        unsafe_allow_html=True,
    )
    if model_ok:
        sidebar_status("check-circle", "Model", "Loaded", COLOR_NORMAL)
    else:
        sidebar_status("x-circle", "Model", "Not Loaded", COLOR_CRITICAL)

    if telegram_ok:
        sidebar_status("send", "Telegram", "Terhubung", COLOR_NORMAL)
    else:
        sidebar_status("wifi-off", "Telegram", "Tidak dikonfigurasi", COLOR_HIGH)

    # Status bot interaktif (polling jalan bila token Telegram terkonfigurasi)
    if telegram_ok:
        sidebar_status("activity", "Bot Interaktif", "Aktif", COLOR_NORMAL)
    else:
        sidebar_status("x-circle", "Bot Interaktif", "Nonaktif", COLOR_HIGH)

    # Tombol test Telegram
    st.sidebar.markdown(
        f'<div class="status-line">{lucide_icon("send", 14, "#aaa")}'
        f'<span>Verifikasi koneksi bot</span></div>',
        unsafe_allow_html=True,
    )
    if st.sidebar.button("Kirim Test"):
        if bot is None or not bot.is_configured():
            st.sidebar.warning("Telegram belum dikonfigurasi (.env kosong).")
        elif bot.send_test():
            st.sidebar.success("Pesan test terkirim ke Telegram!")
        else:
            st.sidebar.error("Gagal kirim — cek TOKEN/CHAT_ID di .env.")

    # Info bot interaktif
    st.sidebar.caption("Ketik /help di bot Telegram untuk command interaktif")

    # Guard: model belum ada
    if not model_ok:
        icon_header("zap", "AI-ORBIT Solar Monitor", 26, COLOR_NORMAL, tag="h1")
        st.error(
            "Model belum diload, jalankan **run_all_models.py** dulu.\n\n"
            f"File model dicari di: `{OUTPUT_DIR}`"
        )
        return

    # Load resource (dengan penanganan error)
    try:
        agent, engine, rootcause, feature_order = load_agent()
    except Exception as e:
        icon_header("zap", "AI-ORBIT Solar Monitor", 26, COLOR_NORMAL, tag="h1")
        st.error(
            "Model belum diload, jalankan **run_all_models.py** dulu.\n\n"
            f"Detail error: `{e}`"
        )
        return

    feature_means = load_feature_means()

    # Routing halaman
    if page == "Live Monitor":
        page_live_monitor(agent, engine, rootcause, bot, feature_means, feature_order)
    elif page == "Realtime Feed":
        page_realtime(auto_refresh)
    elif page == "Statistik & Grafik":
        page_statistics()
    elif page == "History Anomali":
        page_history()
    elif page == "Demo Otomatis":
        page_demo(agent, engine, rootcause, bot, feature_means, feature_order)


if __name__ == "__main__":
    main()
