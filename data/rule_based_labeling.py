# -*- coding: utf-8 -*-
"""
data/rule_based_labeling.py
────────────────────────────────────────────────────────────
Rule-based (re)labeling untuk Condition_Monitoring_Dataset.

LATAR BELAKANG
Diagnosis menunjukkan label ASLI pada Condition_Monitoring_Dataset.csv dibuat
acak — korelasi maksimum fitur↔label hanya ~0.02 dan shuffle-test menghasilkan
akurasi identik dengan baseline majority-class (45.35%). Artinya tidak ada
sinyal yang bisa dipelajari model.

Modul ini menurunkan label LANGSUNG dari nilai sensor, sehingga setiap kelas
fault punya tanda-tangan sensor yang jelas berbeda dari "Normal". Threshold
TIDAK di-hardcode sembarangan: dihitung dari distribusi aktual dataset
(percentile / IQR) supaya realistis terhadap data.

LOGIKA PRIORITAS (paling parah → normal, first-match-wins):
  1. Battery_Overheating  : Battery_Temperature sangat tinggi
  2. PV_Fault             : PV_Voltage / PV_Current di ekor ekstrem
  3. Grid_Instability     : Grid_Voltage di ekor ekstrem
  4. Communication_Failure: Sensor_Latency sangat tinggi
  5. Battery_Degradation  : Battery_Voltage rendah (kapasitas turun)
  6. Inverter_Fault       : PV_Voltage tinggi TAPI PV_Current rendah
  7. Normal               : tidak memenuhi kondisi di atas

Pemakaian:
    from data.rule_based_labeling import create_rule_based_labels
    df_labeled = create_rule_based_labels(df)

Atau jalankan langsung untuk membuat dataset berlabel + ringkasan:
    python data/rule_based_labeling.py
"""
from __future__ import annotations

import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from pathlib import Path
import numpy as np
import pandas as pd

# ─────────────────────────────────────────
# PATH
# ─────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent          # .../data
SRC_CSV = BASE_DIR / "Condition_Monitoring_Dataset.csv"
OUT_CSV = BASE_DIR / "Condition_Monitoring_Dataset_Labeled.csv"

LABEL_COL = "System_Condition_Label"

# ─────────────────────────────────────────
# Parameter percentile per-rule (mudah di-tune agar distribusi seimbang).
# Nilainya cutoff dalam satuan PERCENTILE, dihitung dari data aktual.
# Dipilih supaya: Normal ~40-50% dan tiap fault punya share yang layak,
# sambil tetap menempati EKOR ekstrem sensornya → separasi jelas vs Normal.
# ─────────────────────────────────────────
P = {
    "overheat_temp":      93,   # Battery_Temperature > p93  → Overheating (~7%)
    "pv_volt_lo":          5,   # PV_Voltage < p5
    "pv_volt_hi":         95,   # PV_Voltage > p95
    "pv_curr_lo":          5,   # PV_Current < p5
    "pv_curr_hi":         95,   # PV_Current > p95
    "grid_volt_lo":        6,   # Grid_Voltage < p6
    "grid_volt_hi":       94,   # Grid_Voltage > p94
    "latency_hi":         91,   # Sensor_Latency > p91  → Comm failure (~>5%)
    "batt_volt_lo":       12,   # Battery_Voltage < p12  → Degradation
    # Inverter fault = tegangan PV di atas rata-rata TAPI arus PV di bawah
    # rata-rata. Threshold dilonggarkan (p75 / p33) agar share >5% — tradeoff:
    # separasi vs Normal lebih lembut dari rule lain, tapi tetap deterministik.
    "inv_pv_volt_hi":     70,   # Inverter: PV_Voltage > p70 ...
    "inv_pv_curr_lo":     40,   # ... DAN PV_Current < p40
}


def compute_thresholds(df: pd.DataFrame) -> dict:
    """Hitung nilai threshold absolut dari percentile pada data aktual."""
    def q(col, p):
        return float(df[col].quantile(p / 100.0))

    t = {
        "overheat_temp":  q("Battery_Temperature", P["overheat_temp"]),
        "pv_volt_lo":     q("PV_Voltage", P["pv_volt_lo"]),
        "pv_volt_hi":     q("PV_Voltage", P["pv_volt_hi"]),
        "pv_curr_lo":     q("PV_Current", P["pv_curr_lo"]),
        "pv_curr_hi":     q("PV_Current", P["pv_curr_hi"]),
        "grid_volt_lo":   q("Grid_Voltage", P["grid_volt_lo"]),
        "grid_volt_hi":   q("Grid_Voltage", P["grid_volt_hi"]),
        "latency_hi":     q("Sensor_Latency", P["latency_hi"]),
        "batt_volt_lo":   q("Battery_Voltage", P["batt_volt_lo"]),
        "inv_pv_volt_hi": q("PV_Voltage", P["inv_pv_volt_hi"]),
        "inv_pv_curr_lo": q("PV_Current", P["inv_pv_curr_lo"]),
    }
    return t


def create_rule_based_labels(df: pd.DataFrame, return_thresholds: bool = False):
    """Buat kolom label baru dari nilai sensor (first-match-wins, prioritas
    paling parah → normal). Mengembalikan COPY df dengan System_Condition_Label
    di-overwrite. Bila return_thresholds=True → (df_labeled, thresholds_dict).
    """
    df = df.copy()
    t = compute_thresholds(df)

    bt = df["Battery_Temperature"]
    pv_v = df["PV_Voltage"]
    pv_i = df["PV_Current"]
    gv = df["Grid_Voltage"]
    lat = df["Sensor_Latency"]
    bv = df["Battery_Voltage"]

    cond_overheat = bt > t["overheat_temp"]
    cond_pv = (pv_v < t["pv_volt_lo"]) | (pv_v > t["pv_volt_hi"]) | \
              (pv_i < t["pv_curr_lo"]) | (pv_i > t["pv_curr_hi"])
    cond_grid = (gv < t["grid_volt_lo"]) | (gv > t["grid_volt_hi"])
    cond_comm = lat > t["latency_hi"]
    cond_degrade = bv < t["batt_volt_lo"]
    cond_inverter = (pv_v > t["inv_pv_volt_hi"]) & (pv_i < t["inv_pv_curr_lo"])

    # np.select menerapkan first-match-wins sesuai urutan prioritas.
    choices = [
        "Battery_Overheating",
        "PV_Fault",
        "Grid_Instability",
        "Communication_Failure",
        "Battery_Degradation",
        "Inverter_Fault",
    ]
    conds = [cond_overheat, cond_pv, cond_grid, cond_comm, cond_degrade, cond_inverter]

    df[LABEL_COL] = np.select(conds, choices, default="Normal")

    if return_thresholds:
        return df, t
    return df


def _print_report(df_old: pd.DataFrame, df_new: pd.DataFrame, t: dict):
    n = len(df_new)
    print("=" * 64)
    print("  RULE-BASED RELABELING — RINGKASAN")
    print("=" * 64)

    print("\n[THRESHOLD ABSOLUT dari distribusi aktual]")
    for k, v in t.items():
        print(f"    {k:16s} = {v:.3f}")

    print("\n[DISTRIBUSI LABEL BARU]  (value_counts)")
    vc = df_new[LABEL_COL].value_counts()
    pct = df_new[LABEL_COL].value_counts(normalize=True) * 100
    for cls in vc.index:
        print(f"    {cls:22s} {vc[cls]:6d}  ({pct[cls]:5.2f}%)")
    print(f"    {'TOTAL':22s} {n:6d}")
    print(f"\n    Jumlah kelas : {df_new[LABEL_COL].nunique()}")
    print(f"    Normal share : {pct.get('Normal', 0):.2f}%  (target 40-50%)")

    print("\n[PERBANDINGAN DISTRIBUSI: LAMA vs BARU]")
    old = df_old[LABEL_COL].value_counts()
    all_cls = sorted(set(old.index) | set(vc.index))
    print(f"    {'Kelas':24s} {'LAMA':>8s} {'BARU':>8s}")
    for c in all_cls:
        print(f"    {c:24s} {int(old.get(c,0)):8d} {int(vc.get(c,0)):8d}")


if __name__ == "__main__":
    print(f"Membaca: {SRC_CSV}")
    df = pd.read_csv(SRC_CSV)
    df_new, t = create_rule_based_labels(df, return_thresholds=True)
    _print_report(df, df_new, t)
    df_new.to_csv(OUT_CSV, index=False)
    print(f"\n✓ Dataset berlabel disimpan: {OUT_CSV}")
    print(f"  (Dataset asli TIDAK diubah: {SRC_CSV.name})")
