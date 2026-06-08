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
DATA_PATH  = REPO_DIR / "data" / "Condition_Monitoring_Dataset.csv"
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
# STEP 5: Normalisasi Fitur
# ─────────────────────────────────────────
print("\n[5/5] Normalisasi fitur (StandardScaler)...")

scaler = StandardScaler()
X_scaled = scaler.fit_transform(X)
X_scaled = pd.DataFrame(X_scaled, columns=X.columns)

print(f"      Semua fitur sudah di-scale ke mean=0, std=1")

# ─────────────────────────────────────────
# STEP 6: Split Train / Test
# ─────────────────────────────────────────
print("\n[6/6] Split data train & test (80:20)...")

X_train, X_test, y_train, y_test = train_test_split(
    X_scaled, y_encoded,
    test_size=0.2,
    random_state=42,
    stratify=y_encoded   # pastikan proporsi label sama di train & test
)

print(f"      Train: {len(X_train)} baris")
print(f"      Test : {len(X_test)} baris")

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