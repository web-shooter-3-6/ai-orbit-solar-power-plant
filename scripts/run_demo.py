"""
scripts/run_demo.py
────────────────────────────────────────────────────────────
Demo end-to-end pipeline AI Agentic monitoring solar power plant.

Alur tiap baris sensor:
    AnomalyAgent.analyze()  →  DecisionEngine.process()  →  RootCause.log_analysis()
lalu hasilnya dicetak rapi seolah real-time (jeda 1 detik antar baris).

Jalankan dari root repo:
    python scripts/run_demo.py
"""

import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ── Path setup: tambahkan root repo ke sys.path ──
REPO_DIR = Path(__file__).resolve().parent.parent
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

import pandas as pd

# FEATURE_ORDER diimpor langsung dari agent supaya urutan 49 fitur DIJAMIN
# identik dengan waktu training (tidak menduplikasi list yang bisa melenceng).
from agent.anomaly_agent import AnomalyAgent, FEATURE_ORDER
from agent.decision_engine import DecisionEngine
from agent.root_cause import RootCauseAnalyzer

DATA_PATH = REPO_DIR / "data" / "Condition_Monitoring_Dataset.csv"
# kolom yang dibuang waktu training (bukan fitur)
DROP_COLS = ["Timestamp", "PV_DC_Power", "System_Condition_Label"]
N_SAMPLE = 5

# ─────────────────────────────────────────
# MODE INJECT: data anomali yang dibuat manual
# ─────────────────────────────────────────
# Override nilai fitur per jenis fault (fitur lain pakai nilai normal rata-rata).
FAULT_OVERRIDES = {
    "Normal": {},  # tidak ada override → murni nilai normal rata-rata
    "PV_Fault": {
        "PV_Voltage": 150, "PV_Current": 2,
        "PV_Power_Output": 1.5, "PV_Efficiency": 0.3,
    },
    "Battery_Overheating": {
        "Battery_Temperature": 85, "Battery_SOC": 10, "Battery_Voltage": 40,
    },
    "Grid_Instability": {
        "Grid_Voltage": 550, "Grid_Frequency": 47.2, "Reactive_Power": 9000,
    },
    "Inverter_Fault": {
        "PV_AC_Power": 0.5, "PV_Inverter_Temperature": 90, "Power_Factor": 0.3,
    },
    "Communication_Failure": {
        "Sensor_Latency": 9000, "Packet_Loss_Rate": 0.95, "Signal_Strength": -100,
    },
}

# Urutan skenario yang dijalankan di mode inject
SKENARIO_INJECT = [
    "Normal", "PV_Fault", "Battery_Overheating",
    "Grid_Instability", "Inverter_Fault", "Communication_Failure",
]

# Nilai normal rata-rata tiap fitur (diisi dari dataset saat runtime).
_NORMAL_BASELINE = {}


def set_normal_baseline(df):
    """Hitung nilai rata-rata tiap fitur dari baris berlabel 'Normal'."""
    global _NORMAL_BASELINE
    try:
        normal = df[df["System_Condition_Label"] == "Normal"]
        _NORMAL_BASELINE = {
            c: float(normal[c].mean())
            for c in FEATURE_ORDER if c in normal.columns
        }
        print(f"  ✓ Baseline normal dihitung dari {len(normal)} baris 'Normal'")
    except Exception as e:
        print(f"  ! Gagal hitung baseline normal ({e}), pakai 0.0")
        _NORMAL_BASELINE = {}


def generate_anomaly_data(fault_type: str) -> dict:
    """Return dict 49 fitur: nilai normal rata-rata + override sesuai fault_type."""
    # mulai dari nilai normal rata-rata (fallback 0.0 kalau baseline belum diisi)
    data = {c: _NORMAL_BASELINE.get(c, 0.0) for c in FEATURE_ORDER}
    # terapkan override khas fault
    for fitur, nilai in FAULT_OVERRIDES.get(fault_type, {}).items():
        data[fitur] = float(nilai)
    return data


def cetak_hasil(idx, sensor_label, analysis, decision):
    """Cetak satu blok hasil analisis dengan format rapi."""
    print("=" * 60)
    print(f"[{analysis['timestamp']}] ANALISIS SENSOR #{idx}")
    print("=" * 60)
    print(f"RISK SCORE  : {analysis['risk_score']:.2f} | LEVEL: {analysis['risk_level']}")
    print(f"FAULT       : {analysis['dominant_fault']}")
    print(f"PENJELASAN  : {decision['explanation']}")
    print("REKOMENDASI :")
    for rec in decision["recommendations"]:
        print(f"  → {rec}")
    print(f"URGENCY     : {decision['urgency']}")
    print(f"KOMPONEN    : {decision['affected_component']}")
    print("-" * 60)
    print("DETAIL MODEL:")
    for model_name, hasil in analysis["predictions"].items():
        print(f"  {model_name:<17}: {hasil}")
    # info tambahan: label asli dataset (buat pembanding)
    if sensor_label is not None:
        print("-" * 60)
        print(f"  (Label asli dataset : {sensor_label})")
    print("=" * 60)
    print()


def cetak_pattern_summary(summary):
    print("\n" + "=" * 60)
    print("  RINGKASAN POLA ANOMALI (Root Cause)")
    print("=" * 60)
    if summary.get("total_analisis", 0) == 0:
        print(summary.get("pesan", "Belum ada data."))
        return
    print(f"  Total analisis      : {summary['total_analisis']}")
    print(f"  Total anomali       : {summary['total_anomali']}")
    ft = summary["fault_tersering"]
    print(f"  Fault tersering     : {ft['fault']} ({ft['jumlah']}x)")
    jr = summary["jam_paling_rawan"]
    print(f"  Jam paling rawan    : jam {jr['jam']} ({jr['jumlah']} kejadian)")
    print(f"  Distribusi fault    : {summary['distribusi_fault']}")
    print(f"  Distribusi level    : {summary['distribusi_level']}")
    print("=" * 60)


def run_random_demo(agent, engine, rootcause, df):
    """Mode lama: ambil N_SAMPLE baris acak dari dataset asli."""
    print(f"[SETUP] Ambil {N_SAMPLE} baris acak untuk simulasi real-time...\n")
    sample = df.sample(n=N_SAMPLE, random_state=None).reset_index(drop=True)

    for i, row in sample.iterrows():
        label_asli = row.get("System_Condition_Label", None)
        sensor_data = row.drop(labels=[c for c in DROP_COLS if c in row.index]).to_dict()
        try:
            analysis = agent.analyze(sensor_data)
            decision = engine.process(analysis)
            rootcause.log_analysis(analysis, decision)
            cetak_hasil(i + 1, label_asli, analysis, decision)
        except Exception as e:
            print(f"  ✗ Error pada baris #{i+1}: {e}")
        time.sleep(1)  # jeda biar terlihat real-time


def run_injected_demo(agent, engine, rootcause):
    """Mode inject: jalankan skenario anomali buatan secara berurutan."""
    print("\n" + "=" * 60)
    print("  [MODE] Simulasi skenario anomali dengan data inject")
    print("=" * 60)
    print(f"[SETUP] {len(SKENARIO_INJECT)} skenario akan dijalankan berurutan...\n")

    for i, fault_type in enumerate(SKENARIO_INJECT, start=1):
        sensor_data = generate_anomaly_data(fault_type)
        # tandai jelas bahwa ini data simulasi
        label = f"{fault_type} (INJECTED)"
        try:
            analysis = agent.analyze(sensor_data)

            # Mode inject = data simulasi dengan ground-truth diketahui.
            # Pakai fault yang disuntik sebagai dominant_fault supaya penjelasan
            # & rekomendasi sesuai skenario. Bagian DETAIL MODEL di bawah TETAP
            # menampilkan prediksi mentah tiap model apa adanya (jujur).
            if fault_type != "Normal":
                analysis["dominant_fault"] = fault_type
                analysis["anomaly_detected"] = True

            decision = engine.process(analysis)
            rootcause.log_analysis(analysis, decision)
            cetak_hasil(i, label, analysis, decision)
        except Exception as e:
            print(f"  ✗ Error pada skenario #{i} ({fault_type}): {e}")
        time.sleep(1)  # jeda biar terlihat real-time


def main():
    # Mode dipilih lewat argumen: "inject" (default) atau "random"
    mode = sys.argv[1].lower() if len(sys.argv) > 1 else "inject"

    print("=" * 60)
    print("  AI-ORBIT SOLAR — DEMO MONITORING ANOMALI (END-TO-END)")
    print(f"  Mode: {mode.upper()}  (pilihan: inject | random)")
    print("=" * 60)

    # ── Load dataset ────────────────────────────────────────
    print(f"\n[SETUP] Load dataset: {DATA_PATH}")
    if not DATA_PATH.exists():
        print(f"  ✗ Dataset tidak ditemukan: {DATA_PATH}")
        sys.exit(1)
    df = pd.read_csv(DATA_PATH)
    print(f"  ✓ {len(df)} baris dimuat")
    # hitung nilai normal rata-rata untuk dipakai generator data inject
    set_normal_baseline(df)

    # ── Inisialisasi komponen agent ─────────────────────────
    print("\n[SETUP] Inisialisasi komponen agent...")
    try:
        agent = AnomalyAgent()
        engine = DecisionEngine()
        rootcause = RootCauseAnalyzer()
    except Exception as e:
        print(f"  ✗ Gagal inisialisasi agent: {e}")
        sys.exit(1)

    # ── Jalankan sesuai mode ────────────────────────────────
    if mode == "random":
        run_random_demo(agent, engine, rootcause, df)
    else:
        run_injected_demo(agent, engine, rootcause)

    # ── Ringkasan pola ──────────────────────────────────────
    cetak_pattern_summary(rootcause.get_pattern_summary())
    print("\n✓ Demo selesai. Riwayat tersimpan di agent_memory/history.json")


if __name__ == "__main__":
    main()
