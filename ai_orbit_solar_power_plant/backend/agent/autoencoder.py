"""
autoencoder.py
────────────────────────────────────────────────────────────
Anomaly detection berbasis reconstruction error dengan Autoencoder (PyTorch).

Ide: autoencoder dilatih HANYA dari data "Normal" sehingga belajar
merekonstruksi pola normal dengan error kecil. Saat data anomali masuk,
reconstruction error membesar. Threshold = persentil-95 error data normal.

Output:
  - autoencoder_model.pt   (state_dict + metadata)
  - autoencoder_threshold  (disimpan di dalam .pt)

Jalankan: python models/autoencoder.py
"""

import sys
# Paksa stdout UTF-8 supaya simbol (✓ dll) tidak crash di konsol Windows
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import pandas as pd
import numpy as np
from pathlib import Path

import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

from sklearn.metrics import classification_report, confusion_matrix, roc_auc_score

BASE_DIR   = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
MODEL_PATH = OUTPUT_DIR / "autoencoder_model.pt"

NORMAL_LABEL = 6
EPOCHS       = 50
BATCH_SIZE   = 64
LR           = 1e-3
THRESH_PCT   = 95     # persentil error normal sebagai ambang anomali
SEED         = 42

torch.manual_seed(SEED)
np.random.seed(SEED)
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")


class Autoencoder(nn.Module):
    """Encoder 49->32->16->8, lalu decoder simetris."""
    def __init__(self, input_dim):
        super().__init__()
        self.encoder = nn.Sequential(
            nn.Linear(input_dim, 32), nn.ReLU(),
            nn.Linear(32, 16), nn.ReLU(),
            nn.Linear(16, 8), nn.ReLU(),
        )
        self.decoder = nn.Sequential(
            nn.Linear(8, 16), nn.ReLU(),
            nn.Linear(16, 32), nn.ReLU(),
            nn.Linear(32, input_dim),
        )

    def forward(self, x):
        return self.decoder(self.encoder(x))


def recon_error(model, X_tensor):
    """Mean squared error per sampel."""
    model.eval()
    with torch.no_grad():
        out = model(X_tensor.to(DEVICE))
        err = ((out - X_tensor.to(DEVICE)) ** 2).mean(dim=1)
    return err.cpu().numpy()


def main():
    print("=" * 55)
    print("  AUTOENCODER - Anomaly Detection (PyTorch)")
    print("=" * 55)
    print(f"  Device: {DEVICE}")

    print("\n[1/5] Load data dari models/output/ ...")
    X_train = pd.read_csv(OUTPUT_DIR / "X_train.csv").values.astype(np.float32)
    X_test  = pd.read_csv(OUTPUT_DIR / "X_test.csv").values.astype(np.float32)
    y_train = pd.read_csv(OUTPUT_DIR / "y_train.csv")["label"].values
    y_test  = pd.read_csv(OUTPUT_DIR / "y_test.csv")["label"].values
    input_dim = X_train.shape[1]
    print(f"      Train: {X_train.shape}, Test: {X_test.shape}")

    # ── STEP 2: Data normal saja ────────────────────────────
    X_train_normal = X_train[y_train == NORMAL_LABEL]
    print(f"\n[2/5] Data normal untuk training: {len(X_train_normal)} baris")
    train_ds = TensorDataset(torch.from_numpy(X_train_normal))
    train_dl = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True)

    # ── STEP 3: Training ────────────────────────────────────
    print(f"\n[3/5] Training autoencoder ({EPOCHS} epoch)...")
    model = Autoencoder(input_dim).to(DEVICE)
    opt = torch.optim.Adam(model.parameters(), lr=LR)
    loss_fn = nn.MSELoss()

    for epoch in range(1, EPOCHS + 1):
        model.train()
        total = 0.0
        for (batch,) in train_dl:
            batch = batch.to(DEVICE)
            opt.zero_grad()
            out = model(batch)
            loss = loss_fn(out, batch)
            loss.backward()
            opt.step()
            total += loss.item() * len(batch)
        avg = total / len(train_ds)
        if epoch % 5 == 0 or epoch == 1:
            print(f"      Epoch {epoch:3d}/{EPOCHS} - loss: {avg:.6f}")

    # ── STEP 4: Threshold + evaluasi ────────────────────────
    print("\n[4/5] Hitung threshold & evaluasi...")
    train_err = recon_error(model, torch.from_numpy(X_train_normal))
    threshold = float(np.percentile(train_err, THRESH_PCT))
    print(f"      Threshold (persentil-{THRESH_PCT} error normal): {threshold:.6f}")

    test_err = recon_error(model, torch.from_numpy(X_test))
    y_pred_anom = (test_err > threshold).astype(int)
    y_true_anom = (y_test != NORMAL_LABEL).astype(int)

    try:
        auc = roc_auc_score(y_true_anom, test_err)
    except ValueError:
        auc = float("nan")

    print(f"\n      ROC-AUC (normal vs anomali): {auc:.4f}")
    print("\n      Classification Report (0=Normal, 1=Anomali):")
    print(classification_report(y_true_anom, y_pred_anom,
                                target_names=["Normal", "Anomali"], digits=4))
    print("      Confusion Matrix:")
    print(confusion_matrix(y_true_anom, y_pred_anom))

    # ── STEP 5: Simpan model + metadata ─────────────────────
    print("\n[5/5] Menyimpan model...")
    torch.save({
        "state_dict": model.state_dict(),
        "input_dim": input_dim,
        "threshold": threshold,
        "threshold_percentile": THRESH_PCT,
    }, MODEL_PATH)
    print(f"      ✓ {MODEL_PATH.name}")

    print("\n" + "=" * 55)
    print("  AUTOENCODER SELESAI!")
    print(f"  ROC-AUC: {auc:.4f}")
    print("=" * 55)
    return auc


if __name__ == "__main__":
    main()
