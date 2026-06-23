import pandas as pd
import numpy as np
from sklearn.preprocessing import StandardScaler, LabelEncoder
from sklearn.model_selection import train_test_split
import pickle
import os
from pathlib import Path

# ─────────────────────────────────────────
# PATH SETUP — robust, tidak peduli dari mana script dijalankan
# ─────────────────────────────────────────
BASE_DIR   = Path(__file__).resolve().parent        # .../models
REPO_DIR   = BASE_DIR.parent                         # root repo
# Sumber dataset bisa di-override via env var DATASET_CSV (dipakai saat retrain
# dengan dataset relabel). Default tetap dataset asli — perilaku lama tak berubah.
DATA_PATH  = (Path(os.environ["DATASET_CSV"]) if os.environ.get("DATASET_CSV")
              else REPO_DIR / "data" / "Condition_Monitoring_Dataset.csv")
OUTPUT_DIR = BASE_DIR / "output"                     # .../models/output

print("=" * 50)
print("  PREPROCESSING - Solar Power Plant Dataset")
print("=" * 50)

# ─────────────────────────────────────────
# STEP 1: Load Data
# ─────────────────────────────────────────
print("\n[1/5] Loading data...")
print(f"      Sumber: {DATA_PATH}")
df = pd.read_csv(DATA_PATH)
print(f"      {len(df)} baris, {len(df.columns)} kolom")

# ─────────────────────────────────────────
# STEP 1b: Normalisasi nama kolom → konvensi kanonik (berkapital)
# ─────────────────────────────────────────
# Dataset sumber memakai nama lowercase (pv_voltage, ...), sedangkan artefak
# downstream (X_train.csv) dan agent.FEATURE_ORDER memakai nama berkapital
# (PV_Voltage, ...). Rename ini idempoten — aman untuk dataset yang sudah
# berkapital maupun yang lowercase — agar kontrak nama fitur tetap konsisten.
CANON_COLS = [
    "Timestamp", "Hour", "Day_Index", "PV_Voltage", "PV_Current",
    "PV_Power_Output", "PV_Panel_Temperature", "Solar_Irradiance",
    "PV_Efficiency", "PV_DC_Power", "PV_AC_Power", "PV_Inverter_Temperature",
    "PV_Frequency", "Battery_SOC", "Battery_SOH", "Battery_Voltage",
    "Battery_Current", "Battery_Temperature", "Battery_Charge_Rate",
    "Battery_Discharge_Rate", "Battery_Internal_Resistance",
    "Battery_Cycle_Count", "EV_Charging_Load", "EV_Charging_Current",
    "EV_Charging_Voltage", "Charging_Station_Temperature", "Active_EV_Count",
    "Charging_Duration", "Fast_Charging_Status", "Grid_Voltage", "Grid_Current",
    "Grid_Frequency", "Power_Demand", "Reactive_Power", "Load_Factor",
    "Energy_Export", "Energy_Import", "Power_Factor", "Sensor_Latency",
    "Packet_Loss_Rate", "Signal_Strength", "Data_Transmission_Rate",
    "Edge_Node_CPU_Usage", "Cloud_Response_Time", "DWT_Coeff_A1",
    "DWT_Coeff_D1", "DWT_Coeff_D2", "Signal_Energy", "Signal_Entropy",
    "RMS_Value", "Crest_Factor", "System_Condition_Label",
]
_canon_by_lower = {c.lower(): c for c in CANON_COLS}
df = df.rename(columns={c: _canon_by_lower.get(str(c).lower(), c) for c in df.columns})

# ─────────────────────────────────────────
# STEP 2: Drop kolom yang ga berguna
# ─────────────────────────────────────────
print("\n[2/5] Drop kolom tidak relevan...")

drop_cols = [
    'Timestamp',   # string waktu, ga dipakai langsung
    'PV_DC_Power', # sangat redundan dengan PV_AC_Power & PV_Current
]

df = df.drop(columns=drop_cols)
print(f"      Kolom dibuang: {drop_cols}")
print(f"      Sisa kolom: {len(df.columns)}")

# ─────────────────────────────────────────
# STEP 3: Pisah Fitur (X) dan Label (y)
# ─────────────────────────────────────────
print("\n[3/5] Pisah fitur dan label...")

X = df.drop(columns=['System_Condition_Label'])
y = df['System_Condition_Label']

print(f"      Jumlah fitur (X): {X.shape[1]} kolom")
print(f"      Label (y): {y.nunique()} kelas unik")

# ─────────────────────────────────────────
# STEP 4: Encode Label → Angka
# ─────────────────────────────────────────
print("\n[4/5] Encode label teks → angka...")

le = LabelEncoder()
y_encoded = le.fit_transform(y)

print("     Mapping label:")
for idx, name in enumerate(le.classes_):
    count = (y == name).sum()
    print(f"       {idx} = {name} ({count} data)")

# ─────────────────────────────────────────
# STEP 5: Split Train / Test  (DILAKUKAN SEBELUM SCALING — cegah data leakage)
# ─────────────────────────────────────────
# FIX K1 (audit metodologi): split dulu, baru fit scaler dari train saja.
# Sebelumnya scaler di-fit dari SELURUH data (train+test) → statistik test
# bocor ke scaler. Urutan baru ini menutup celah leakage tersebut.
print("\n[5/6] Split data train & test (80:20) — SEBELUM scaling...")

X_train_raw, X_test_raw, y_train, y_test = train_test_split(
    X, y_encoded,                # X masih mentah (belum di-scale)
    test_size=0.2,
    random_state=42,
    stratify=y_encoded   # pastikan proporsi label sama di train & test
)

print(f"      Train: {len(X_train_raw)} baris")
print(f"      Test : {len(X_test_raw)} baris")

# ─────────────────────────────────────────
# STEP 6: Normalisasi Fitur  (fit HANYA dari train, transform keduanya)
# ─────────────────────────────────────────
print("\n[6/6] Normalisasi fitur (StandardScaler, fit dari train saja)...")

scaler = StandardScaler()
scaler.fit(X_train_raw)          # fit HANYA dari train → tidak ada leakage dari test

X_train = pd.DataFrame(scaler.transform(X_train_raw), columns=X.columns)
X_test  = pd.DataFrame(scaler.transform(X_test_raw),  columns=X.columns)

print(f"      Scaler di-fit dari X_train saja; X_test hanya di-transform.")
print(f"      Semua fitur di-scale ke mean=0, std=1 (basis statistik train).")

# ─────────────────────────────────────────
# STEP 7: Simpan Hasil
# ─────────────────────────────────────────
print("\n Menyimpan hasil preprocessing...")

os.makedirs(OUTPUT_DIR, exist_ok=True)
print(f"      Tujuan: {OUTPUT_DIR}")

# Simpan data split
X_train.to_csv(OUTPUT_DIR / 'X_train.csv', index=False)
X_test.to_csv(OUTPUT_DIR / 'X_test.csv', index=False)
pd.Series(y_train, name='label').to_csv(OUTPUT_DIR / 'y_train.csv', index=False)
pd.Series(y_test, name='label').to_csv(OUTPUT_DIR / 'y_test.csv', index=False)

# Simpan scaler & encoder (dipakai nanti saat deployment)
with open(OUTPUT_DIR / 'scaler.pkl', 'wb') as f:
    pickle.dump(scaler, f)
with open(OUTPUT_DIR / 'label_encoder.pkl', 'wb') as f:
    pickle.dump(le, f)

# Simpan mapping label biar gampang dibaca
label_map = {idx: name for idx, name in enumerate(le.classes_)}
pd.DataFrame(label_map.items(), columns=['id', 'label']).to_csv(OUTPUT_DIR / 'label_map.csv', index=False)

print("      X_train.csv, X_test.csv")
print("      y_train.csv, y_test.csv")
print("      scaler.pkl, label_encoder.pkl")
print("      label_map.csv")

print("\n" + "=" * 50)
print("  PREPROCESSING SELESAI!")
print("=" * 50)
print(f"\n  Total fitur siap pakai : {X_train.shape[1]}")
print(f"  Total data train       : {len(X_train)}")
print(f"  Total data test        : {len(X_test)}")
print(f"  Jumlah kelas           : {len(le.classes_)}")
print("\n  Next step → train model XGBoost!")