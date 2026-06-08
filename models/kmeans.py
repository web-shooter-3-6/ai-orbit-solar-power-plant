"""
kmeans.py
────────────────────────────────────────────────────────────
Unsupervised clustering dengan KMeans untuk menemukan struktur/grup
pada data kondisi solar plant (49 fitur).

Karena dataset punya 10 kelas asli, kita set n_clusters=10 lalu ukur
seberapa cocok cluster dengan label asli pakai ARI & NMI (metrik clustering
yang tidak butuh urutan label sama).

Jalankan: python models/kmeans.py
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

from sklearn.cluster import KMeans
from sklearn.metrics import (
    adjusted_rand_score,
    normalized_mutual_info_score,
    silhouette_score,
)

BASE_DIR   = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
MODEL_PATH = OUTPUT_DIR / "kmeans_model.pkl"

N_CLUSTERS   = 10    # sesuai jumlah kelas asli di dataset
RANDOM_STATE = 42


def main():
    print("=" * 55)
    print("  KMEANS - Clustering Kondisi Solar Plant")
    print("=" * 55)

    print("\n[1/4] Load data dari models/output/ ...")
    X_train = pd.read_csv(OUTPUT_DIR / "X_train.csv")
    X_test  = pd.read_csv(OUTPUT_DIR / "X_test.csv")
    y_test  = pd.read_csv(OUTPUT_DIR / "y_test.csv")["label"].values
    print(f"      Train: {X_train.shape}, Test: {X_test.shape}")

    # ── STEP 2: Training ────────────────────────────────────
    print(f"\n[2/4] Training KMeans (n_clusters={N_CLUSTERS})...")
    model = KMeans(n_clusters=N_CLUSTERS, random_state=RANDOM_STATE, n_init=10)
    model.fit(X_train)
    print("      ✓ Training selesai")

    # ── STEP 3: Evaluasi pada data test ─────────────────────
    print("\n[3/4] Evaluasi clustering pada data test...")
    cluster_pred = model.predict(X_test)

    ari = adjusted_rand_score(y_test, cluster_pred)
    nmi = normalized_mutual_info_score(y_test, cluster_pred)
    # silhouette pakai subsample biar cepat (data besar)
    n_sample = min(5000, len(X_test))
    rng = np.random.RandomState(RANDOM_STATE)
    idx = rng.choice(len(X_test), n_sample, replace=False)
    sil = silhouette_score(X_test.iloc[idx], cluster_pred[idx])

    print(f"      Adjusted Rand Index (ARI) : {ari:.4f}  (1=sempurna, 0=acak)")
    print(f"      Normalized Mutual Info    : {nmi:.4f}")
    print(f"      Silhouette Score          : {sil:.4f}  (-1..1, makin tinggi makin baik)")

    # Mapping mayoritas: cluster -> label asli yang dominan (untuk interpretasi)
    print("\n      Komposisi cluster (label asli dominan per cluster):")
    for c in range(N_CLUSTERS):
        mask = cluster_pred == c
        if mask.sum() == 0:
            continue
        vals, counts = np.unique(y_test[mask], return_counts=True)
        dominant = vals[np.argmax(counts)]
        purity = counts.max() / counts.sum()
        print(f"        Cluster {c:2d}: {mask.sum():5d} data | "
              f"label dominan={dominant} | purity={purity:.2f}")

    # ── STEP 4: Simpan model ────────────────────────────────
    print("\n[4/4] Menyimpan model...")
    with open(MODEL_PATH, "wb") as f:
        pickle.dump(model, f)
    print(f"      ✓ {MODEL_PATH.name}")

    print("\n" + "=" * 55)
    print("  KMEANS SELESAI!")
    print(f"  ARI: {ari:.4f} | NMI: {nmi:.4f}")
    print("=" * 55)
    return ari


if __name__ == "__main__":
    main()
