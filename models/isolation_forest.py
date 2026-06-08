"""
isolation_forest.py
────────────────────────────────────────────────────────────
Unsupervised anomaly detection dengan Isolation Forest.

Strategi: model dilatih HANYA dari data "Normal" (label 6) supaya belajar
profil kondisi sehat. Saat evaluasi, semua label != Normal dianggap anomali,
lalu kita ukur seberapa baik IF memisahkan normal vs anomali.

Jalankan: python models/isolation_forest.py
"""

import sys
# Paksa stdout UTF-8 supaya simbol (✓ dll) tidak crash di konsol Windows
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import pandas as pd
import numpy as np
import pickle
from pathlib import Path

from sklearn.ensemble import IsolationForest
from sklearn.metrics import classification_report, confusion_matrix, roc_auc_score

BASE_DIR   = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
MODEL_PATH = OUTPUT_DIR / "isolation_forest_model.pkl"

NORMAL_LABEL = 6   # index 'Normal' dari label_map

# Hyperparameter (selaras config.yaml -> models.isolation_forest)
PARAMS = dict(
    n_estimators=100,
    contamination=0.05,
    random_state=42,
)


def main():
    print("=" * 55)
    print("  ISOLATION FOREST - Anomaly Detection")
    print("=" * 55)

    print("\n[1/5] Load data dari models/output/ ...")
    X_train = pd.read_csv(OUTPUT_DIR / "X_train.csv")
    X_test  = pd.read_csv(OUTPUT_DIR / "X_test.csv")
    y_train = pd.read_csv(OUTPUT_DIR / "y_train.csv")["label"].values
    y_test  = pd.read_csv(OUTPUT_DIR / "y_test.csv")["label"].values
    print(f"      Train: {X_train.shape}, Test: {X_test.shape}")

    # ── STEP 2: Ambil data normal saja untuk training ───────
    print("\n[2/5] Filter data 'Normal' untuk training...")
    X_train_normal = X_train[y_train == NORMAL_LABEL]
    print(f"      Data normal untuk training: {len(X_train_normal)} baris")

    # ── STEP 3: Training ────────────────────────────────────
    print("\n[3/5] Training Isolation Forest...")
    print(f"      Param: {PARAMS}")
    model = IsolationForest(**PARAMS, n_jobs=-1)
    model.fit(X_train_normal)
    print("      ✓ Training selesai")

    # ── STEP 4: Evaluasi ────────────────────────────────────
    print("\n[4/5] Evaluasi pada data test...")
    # IF: predict -> 1 (inlier/normal), -1 (outlier/anomali)
    pred_raw = model.predict(X_test)
    y_pred_anom = (pred_raw == -1).astype(int)        # 1 = anomali
    y_true_anom = (y_test != NORMAL_LABEL).astype(int)  # 1 = anomali (ground truth)

    # decision_function: makin kecil = makin anomali -> dibalik utk skor anomali
    anomaly_score = -model.decision_function(X_test)

    try:
        auc = roc_auc_score(y_true_anom, anomaly_score)
    except ValueError:
        auc = float("nan")

    print(f"\n      ROC-AUC (normal vs anomali): {auc:.4f}")
    print("\n      Classification Report (0=Normal, 1=Anomali):")
    print(classification_report(y_true_anom, y_pred_anom,
                                target_names=["Normal", "Anomali"], digits=4))
    print("      Confusion Matrix:")
    print(confusion_matrix(y_true_anom, y_pred_anom))

    # ── STEP 5: Simpan model ────────────────────────────────
    print("\n[5/5] Menyimpan model...")
    with open(MODEL_PATH, "wb") as f:
        pickle.dump(model, f)
    print(f"      ✓ {MODEL_PATH.name}")

    print("\n" + "=" * 55)
    print("  ISOLATION FOREST SELESAI!")
    print(f"  ROC-AUC: {auc:.4f}")
    print("=" * 55)
    return auc


if __name__ == "__main__":
    main()
