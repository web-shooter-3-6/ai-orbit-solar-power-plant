"""
run_all_models.py
────────────────────────────────────────────────────────────
Orkestrator training semua model offline untuk AI-Orbit Solar.

Alur:
  1. Cek apakah hasil preprocessing (models/output/) sudah ada.
     - Kalau belum → jalankan preprocessing.py dulu.
  2. Train semua model secara berurutan:
        XGBoost → Autoencoder → IsolationForest → KMeans → LSTM
  3. Print status tiap model (BERHASIL / GAGAL + durasi).
  4. Semua artefak tersimpan di models/output/.

Jalankan dari root repo:
    python run_all_models.py
"""

import sys
import os
import time
import subprocess
from pathlib import Path

# Paksa stdout UTF-8 supaya simbol (█ ✅ ❌ →) tidak crash di konsol Windows
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

REPO_DIR   = Path(__file__).resolve().parent
MODELS_DIR = REPO_DIR / "models"
OUTPUT_DIR = MODELS_DIR / "output"
PYTHON     = sys.executable   # pakai interpreter yang sama

# File wajib hasil preprocessing
REQUIRED_OUTPUTS = ["X_train.csv", "X_test.csv", "y_train.csv", "y_test.csv"]

# Urutan training sesuai permintaan
PIPELINE = [
    ("XGBoost",          MODELS_DIR / "train_xgboost.py"),
    ("Autoencoder",      MODELS_DIR / "autoencoder.py"),
    ("Isolation Forest", MODELS_DIR / "isolation_forest.py"),
    ("KMeans",           MODELS_DIR / "kmeans.py"),
    ("LSTM",             MODELS_DIR / "lstm.py"),
]


def run_script(name: str, path: Path) -> bool:
    """Jalankan satu script python sbg subprocess, stream output real-time."""
    print("\n" + "█" * 60)
    print(f"█  MENJALANKAN: {name}")
    print(f"█  File: {path.relative_to(REPO_DIR)}")
    print("█" * 60)

    if not path.exists():
        print(f"  ✗ File tidak ditemukan: {path}")
        return False

    start = time.time()
    child_env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    result = subprocess.run([PYTHON, str(path)], cwd=str(REPO_DIR), env=child_env)
    durasi = time.time() - start

    if result.returncode == 0:
        print(f"\n  ✅ {name} BERHASIL  (durasi: {durasi:.1f} detik)")
        return True
    else:
        print(f"\n  ❌ {name} GAGAL  (exit code: {result.returncode}, durasi: {durasi:.1f} detik)")
        return False


def ensure_preprocessing():
    """Jalankan preprocessing kalau output belum lengkap."""
    missing = [f for f in REQUIRED_OUTPUTS if not (OUTPUT_DIR / f).exists()]
    if not missing:
        print("  ✓ Hasil preprocessing sudah ada di models/output/ — skip.")
        return True

    print(f"  ! Output belum lengkap (hilang: {missing})")
    print("  → Menjalankan preprocessing.py ...")
    return run_script("Preprocessing", MODELS_DIR / "preprocessing.py")


def main():
    print("=" * 60)
    print("  AI-ORBIT SOLAR — TRAIN ALL MODELS")
    print("=" * 60)

    # ── STEP 0: Preprocessing ───────────────────────────────
    print("\n[STEP 0] Cek hasil preprocessing...")
    if not ensure_preprocessing():
        print("\n  ❌ Preprocessing gagal. Pipeline dihentikan.")
        sys.exit(1)

    # ── STEP 1: Train semua model ───────────────────────────
    results = {}
    total_start = time.time()
    for name, path in PIPELINE:
        results[name] = run_script(name, path)

    total_durasi = time.time() - total_start

    # ── RINGKASAN ───────────────────────────────────────────
    print("\n\n" + "=" * 60)
    print("  RINGKASAN HASIL TRAINING")
    print("=" * 60)
    for name, ok in results.items():
        status = "✅ BERHASIL" if ok else "❌ GAGAL"
        print(f"    {name:<18} : {status}")
    print("-" * 60)
    n_ok = sum(results.values())
    print(f"    Total: {n_ok}/{len(results)} model berhasil")
    print(f"    Total durasi: {total_durasi:.1f} detik")
    print(f"    Semua artefak → {OUTPUT_DIR}")
    print("=" * 60)

    # exit code != 0 kalau ada yang gagal (berguna utk CI)
    if n_ok != len(results):
        sys.exit(1)


if __name__ == "__main__":
    main()
