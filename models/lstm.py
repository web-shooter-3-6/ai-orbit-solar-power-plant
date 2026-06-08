"""
lstm.py
────────────────────────────────────────────────────────────
Klasifikasi 10 kelas kondisi solar plant dengan LSTM (PyTorch).

Catatan: dataset CSV ini tabular (tiap baris independen, bukan time-series
murni). Agar LSTM tetap bisa dipakai sebagai pembanding deep-learning,
49 fitur diperlakukan sebagai SEQUENCE sepanjang 49 langkah × 1 fitur.
Ini pendekatan umum untuk membandingkan LSTM pada data tabular.

Output: lstm_model.pt (state_dict + metadata)

Jalankan: python models/lstm.py
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

from sklearn.metrics import accuracy_score, classification_report, confusion_matrix

BASE_DIR   = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
MODEL_PATH = OUTPUT_DIR / "lstm_model.pt"

HIDDEN_SIZE = 64
NUM_LAYERS  = 2
EPOCHS      = 15      # cukup utk konvergen di CPU; naikkan jika pakai GPU
BATCH_SIZE  = 128
LR          = 1e-3
SEED        = 42

torch.manual_seed(SEED)
np.random.seed(SEED)
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

LABEL_NAMES = [
    "Battery_Degradation", "Battery_Overheating", "Communication_Failure",
    "EV_Charging_Fault", "Grid_Instability", "Inverter_Fault", "Normal",
    "Overload_Condition", "PV_Fault", "Sensor_Failure",
]


class LSTMClassifier(nn.Module):
    def __init__(self, input_size, hidden_size, num_layers, n_classes):
        super().__init__()
        self.lstm = nn.LSTM(input_size, hidden_size, num_layers,
                            batch_first=True, dropout=0.2)
        self.fc = nn.Linear(hidden_size, n_classes)

    def forward(self, x):
        out, _ = self.lstm(x)        # x: (batch, seq_len, input_size)
        last = out[:, -1, :]         # ambil output langkah terakhir
        return self.fc(last)


def main():
    print("=" * 55)
    print("  LSTM - Klasifikasi Kondisi Solar Plant (PyTorch)")
    print("=" * 55)
    print(f"  Device: {DEVICE}")

    print("\n[1/5] Load data dari models/output/ ...")
    X_train = pd.read_csv(OUTPUT_DIR / "X_train.csv").values.astype(np.float32)
    X_test  = pd.read_csv(OUTPUT_DIR / "X_test.csv").values.astype(np.float32)
    y_train = pd.read_csv(OUTPUT_DIR / "y_train.csv")["label"].values.astype(np.int64)
    y_test  = pd.read_csv(OUTPUT_DIR / "y_test.csv")["label"].values.astype(np.int64)
    n_features = X_train.shape[1]
    n_classes  = len(np.unique(y_train))
    print(f"      Train: {X_train.shape}, Test: {X_test.shape}, kelas: {n_classes}")

    # ── STEP 2: Reshape jadi sequence (seq_len=n_features, input_size=1) ──
    print("\n[2/5] Reshape fitur jadi sequence (49 langkah × 1 fitur)...")
    X_train_seq = X_train.reshape(-1, n_features, 1)
    X_test_seq  = X_test.reshape(-1, n_features, 1)

    train_ds = TensorDataset(torch.from_numpy(X_train_seq), torch.from_numpy(y_train))
    train_dl = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True)

    # ── STEP 3: Training ────────────────────────────────────
    print(f"\n[3/5] Training LSTM ({EPOCHS} epoch)...")
    model = LSTMClassifier(1, HIDDEN_SIZE, NUM_LAYERS, n_classes).to(DEVICE)
    opt = torch.optim.Adam(model.parameters(), lr=LR)
    loss_fn = nn.CrossEntropyLoss()

    for epoch in range(1, EPOCHS + 1):
        model.train()
        total, correct, loss_sum = 0, 0, 0.0
        for xb, yb in train_dl:
            xb, yb = xb.to(DEVICE), yb.to(DEVICE)
            opt.zero_grad()
            logits = model(xb)
            loss = loss_fn(logits, yb)
            loss.backward()
            opt.step()
            loss_sum += loss.item() * len(xb)
            correct += (logits.argmax(1) == yb).sum().item()
            total += len(xb)
        print(f"      Epoch {epoch:2d}/{EPOCHS} - loss: {loss_sum/total:.4f} "
              f"- train_acc: {correct/total:.4f}")

    # ── STEP 4: Evaluasi ────────────────────────────────────
    print("\n[4/5] Evaluasi pada data test...")
    model.eval()
    preds = []
    test_dl = DataLoader(TensorDataset(torch.from_numpy(X_test_seq)),
                         batch_size=512, shuffle=False)
    with torch.no_grad():
        for (xb,) in test_dl:
            logits = model(xb.to(DEVICE))
            preds.append(logits.argmax(1).cpu().numpy())
    y_pred = np.concatenate(preds)

    acc = accuracy_score(y_test, y_pred)
    labels_present = sorted(np.unique(np.concatenate([y_test, y_pred])))
    target_names = [LABEL_NAMES[i] for i in labels_present]

    print(f"\n      >>> Accuracy: {acc:.4f} ({acc*100:.2f}%) <<<\n")
    print("      Classification Report:")
    print(classification_report(y_test, y_pred, labels=labels_present,
                                target_names=target_names, digits=4))
    print("      Confusion Matrix:")
    print(confusion_matrix(y_test, y_pred, labels=labels_present))

    # ── STEP 5: Simpan model ────────────────────────────────
    print("\n[5/5] Menyimpan model...")
    torch.save({
        "state_dict": model.state_dict(),
        "n_features": n_features,
        "hidden_size": HIDDEN_SIZE,
        "num_layers": NUM_LAYERS,
        "n_classes": n_classes,
    }, MODEL_PATH)
    print(f"      ✓ {MODEL_PATH.name}")

    print("\n" + "=" * 55)
    print("  LSTM SELESAI!")
    print(f"  Accuracy: {acc*100:.2f}%")
    print("=" * 55)
    return acc


if __name__ == "__main__":
    main()
