"""
train_xgboost.py
────────────────────────────────────────────────────────────
Train XGBoost classifier untuk klasifikasi kondisi solar power plant.
Membaca hasil preprocessing dari models/output/ lalu menyimpan model
terlatih + plot feature importance ke folder yang sama.

Jalankan dari mana saja:
    python models/train_xgboost.py
"""

import sys
# Paksa stdout UTF-8 supaya simbol (✓, ×, dll) tidak crash di konsol Windows
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import pandas as pd
import numpy as np
import pickle
from pathlib import Path

from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
)

# matplotlib pakai backend non-interaktif biar aman tanpa display (server/CI)
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from xgboost import XGBClassifier

# ─────────────────────────────────────────
# PATH SETUP — robust terhadap CWD
# ─────────────────────────────────────────
BASE_DIR   = Path(__file__).resolve().parent     # .../models
OUTPUT_DIR = BASE_DIR / "output"

MODEL_PATH   = OUTPUT_DIR / "xgboost_model.pkl"
FEATIMP_PATH = OUTPUT_DIR / "feature_importance.png"
CONFMAT_PATH = OUTPUT_DIR / "xgboost_confusion_matrix.png"

# Mapping label (urutan = hasil LabelEncoder dari preprocessing)
LABEL_NAMES = [
    "Battery_Degradation",    # 0
    "Battery_Overheating",    # 1
    "Communication_Failure",  # 2
    "EV_Charging_Fault",      # 3
    "Grid_Instability",       # 4
    "Inverter_Fault",         # 5
    "Normal",                 # 6
    "Overload_Condition",     # 7
    "PV_Fault",               # 8
    "Sensor_Failure",         # 9
]

# Hyperparameter (sesuai permintaan)
PARAMS = dict(
    n_estimators=200,
    max_depth=6,
    learning_rate=0.1,
    random_state=42,
)


def main():
    print("=" * 55)
    print("  TRAIN XGBOOST - Solar Power Plant Classifier")
    print("=" * 55)

    # ── STEP 1: Load data hasil preprocessing ───────────────
    print("\n[1/6] Load data dari models/output/ ...")
    for f in ["X_train.csv", "X_test.csv", "y_train.csv", "y_test.csv"]:
        if not (OUTPUT_DIR / f).exists():
            raise FileNotFoundError(
                f"      ✗ {f} tidak ditemukan di {OUTPUT_DIR}\n"
                f"        Jalankan preprocessing.py dulu!"
            )

    X_train = pd.read_csv(OUTPUT_DIR / "X_train.csv")
    X_test  = pd.read_csv(OUTPUT_DIR / "X_test.csv")
    y_train = pd.read_csv(OUTPUT_DIR / "y_train.csv")["label"].values
    y_test  = pd.read_csv(OUTPUT_DIR / "y_test.csv")["label"].values

    feature_names = list(X_train.columns)
    n_classes = len(np.unique(y_train))
    print(f"      Train : {X_train.shape[0]} baris × {X_train.shape[1]} fitur")
    print(f"      Test  : {X_test.shape[0]} baris")
    print(f"      Kelas : {n_classes}")

    # ── STEP 2: Inisialisasi model ──────────────────────────
    print("\n[2/6] Inisialisasi XGBoost classifier...")
    print(f"      Param: {PARAMS}")
    model = XGBClassifier(
        **PARAMS,
        objective="multi:softprob",
        num_class=n_classes,
        eval_metric="mlogloss",
        tree_method="hist",   # cepat & hemat memori
        n_jobs=-1,
    )

    # ── STEP 3: Training ────────────────────────────────────
    print("\n[3/6] Training model (mohon tunggu)...")
    model.fit(X_train, y_train)
    print("      ✓ Training selesai")

    # ── STEP 4: Evaluasi ────────────────────────────────────
    print("\n[4/6] Evaluasi pada data test...")
    y_pred = model.predict(X_test)

    acc = accuracy_score(y_test, y_pred)
    # hanya tampilkan nama kelas yang benar-benar muncul
    labels_present = sorted(np.unique(np.concatenate([y_test, y_pred])))
    target_names = [LABEL_NAMES[i] for i in labels_present]

    print(f"\n      >>> Accuracy: {acc:.4f} ({acc*100:.2f}%) <<<\n")
    print("      Classification Report:")
    print(
        classification_report(
            y_test, y_pred,
            labels=labels_present,
            target_names=target_names,
            digits=4,
        )
    )

    cm = confusion_matrix(y_test, y_pred, labels=labels_present)
    print("      Confusion Matrix (baris=aktual, kolom=prediksi):")
    print(cm)

    # ── STEP 5: Simpan model ────────────────────────────────
    print("\n[5/6] Menyimpan model...")
    with open(MODEL_PATH, "wb") as f:
        pickle.dump(model, f)
    print(f"      ✓ {MODEL_PATH.name}")

    # ── STEP 6: Plot feature importance + confusion matrix ──
    print("\n[6/6] Membuat plot...")

    importances = model.feature_importances_
    order = np.argsort(importances)[::-1]
    top_n = min(20, len(feature_names))
    top_idx = order[:top_n]

    plt.figure(figsize=(10, 8))
    plt.barh(
        [feature_names[i] for i in top_idx][::-1],
        importances[top_idx][::-1],
        color="#2e86de",
    )
    plt.xlabel("Importance")
    plt.title(f"XGBoost - Top {top_n} Feature Importance")
    plt.tight_layout()
    plt.savefig(FEATIMP_PATH, dpi=120)
    plt.close()
    print(f"      ✓ {FEATIMP_PATH.name}")

    # bonus: confusion matrix heatmap
    plt.figure(figsize=(9, 8))
    plt.imshow(cm, cmap="Blues")
    plt.colorbar()
    plt.xticks(range(len(target_names)), target_names, rotation=90, fontsize=7)
    plt.yticks(range(len(target_names)), target_names, fontsize=7)
    plt.xlabel("Prediksi")
    plt.ylabel("Aktual")
    plt.title("XGBoost - Confusion Matrix")
    for i in range(cm.shape[0]):
        for j in range(cm.shape[1]):
            plt.text(j, i, cm[i, j], ha="center", va="center",
                     color="white" if cm[i, j] > cm.max() / 2 else "black",
                     fontsize=6)
    plt.tight_layout()
    plt.savefig(CONFMAT_PATH, dpi=120)
    plt.close()
    print(f"      ✓ {CONFMAT_PATH.name}")

    print("\n" + "=" * 55)
    print("  XGBOOST SELESAI!")
    print(f"  Accuracy akhir: {acc*100:.2f}%")
    print("=" * 55)
    return acc


if __name__ == "__main__":
    main()
