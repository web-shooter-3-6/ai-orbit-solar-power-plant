"""
models/evaluate_models.py
────────────────────────────────────────────────────────────
Evaluasi FORMAL model ML AI-ORBIT yang benar-benar ada di project:
  • XGBoost          — supervised classifier (10 kelas kondisi)
  • Isolation Forest — unsupervised anomaly detector (Normal vs Anomali)

Menghasilkan metrik siap-poster: accuracy, precision/recall/F1 (weighted),
confusion matrix, classification report per kelas (XGBoost); anomaly detection
rate, false positive rate, precision/F1, ROC-AUC, confusion matrix (Isolation
Forest). Output: terminal (tabel), evaluation_report.json (machine-readable),
evaluation_report.txt (human-readable), dan PNG confusion matrix.

────────────────────────────────────────────────────────────
METODOLOGI:
Evaluasi memakai SPLIT TEST 20% ASLI (models/output/X_test.csv + y_test.csv)
yang dihasilkan models/preprocessing.py dari dataset sumber
data/Condition_Monitoring_Dataset.csv (50.000 baris) dengan split 80/20,
random_state=42, stratify=y — IDENTIK dengan pipeline training. X_test sudah
ter-scale (StandardScaler di-fit dari train saja). Model di-RETRAIN dengan
scikit-learn versi runtime yang sama (lihat header laporan) sehingga TIDAK ada
mismatch versi pickle.

Model nyata di project: XGBoost, Isolation Forest, KMeans, Autoencoder, LSTM.
TIDAK ADA Random Forest / SVM / Neural-Network classifier. Evaluasi ini dibatasi
ke XGBoost + Isolation Forest (sesuai keputusan scope).

Jalankan: python models/evaluate_models.py
"""

import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import json
import pickle
from datetime import datetime
from pathlib import Path

import warnings
import sklearn

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Tangkap InconsistentVersionWarning (model di-pickle dgn versi sklearn berbeda)
# agar bisa dicatat sebagai caveat metodologi di laporan.
_VERSION_WARNINGS = []
try:
    from sklearn.exceptions import InconsistentVersionWarning
except Exception:  # pragma: no cover
    InconsistentVersionWarning = None

from sklearn.metrics import (
    accuracy_score,
    precision_score,
    recall_score,
    f1_score,
    confusion_matrix,
    classification_report,
    roc_auc_score,
)

# ─────────────────────────────────────────
# PATH SETUP
# ─────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent          # .../models
OUTPUT_DIR = BASE_DIR / "output"
REPO_DIR = BASE_DIR.parent
# Split test 20% ASLI (sudah ter-scale) hasil preprocessing.py.
X_TEST_PATH = OUTPUT_DIR / "X_test.csv"
Y_TEST_PATH = OUTPUT_DIR / "y_test.csv"

CM_DIR = BASE_DIR / "confusion_matrices"
REPORT_JSON = BASE_DIR / "evaluation_report.json"
REPORT_TXT = BASE_DIR / "evaluation_report.txt"

SCALER_PATH = OUTPUT_DIR / "scaler.pkl"
ENCODER_PATH = OUTPUT_DIR / "label_encoder.pkl"
XGB_PATH = OUTPUT_DIR / "xgboost_model.pkl"
IF_PATH = OUTPUT_DIR / "isolation_forest_model.pkl"

NORMAL_LABEL_NAME = "Normal"

# Kolom yang dibuang saat preprocessing training (lihat models/preprocessing.py).
DROP_COLS = ["Timestamp", "PV_DC_Power"]
LABEL_COL = "System_Condition_Label"

# Daftar kolom kanonik (untuk rename idempoten — selaras preprocessing.py).
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
    "RMS_Value", "Crest_Factor", LABEL_COL,
]

LINE = "=" * 70


# ─────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────
def _canonicalize(df: pd.DataFrame) -> pd.DataFrame:
    """Rename kolom ke konvensi kanonik (idempoten)."""
    by_lower = {c.lower(): c for c in CANON_COLS}
    return df.rename(columns={c: by_lower.get(str(c).lower(), c) for c in df.columns})


def _save_confusion_png(cm, class_names, title, path):
    """Simpan heatmap confusion matrix sebagai PNG."""
    n = len(class_names)
    plt.figure(figsize=(max(6, n * 0.9), max(5, n * 0.8)))
    plt.imshow(cm, cmap="Blues")
    plt.colorbar()
    plt.xticks(range(n), class_names, rotation=90, fontsize=8)
    plt.yticks(range(n), class_names, fontsize=8)
    plt.xlabel("Prediksi")
    plt.ylabel("Aktual")
    plt.title(title)
    thresh = cm.max() / 2 if cm.max() > 0 else 0.5
    for i in range(cm.shape[0]):
        for j in range(cm.shape[1]):
            plt.text(j, i, int(cm[i, j]), ha="center", va="center",
                     color="white" if cm[i, j] > thresh else "black", fontsize=8)
    plt.tight_layout()
    plt.savefig(path, dpi=120)
    plt.close()


def _fmt_pct(x):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "N/A"
    return f"{x * 100:.2f}%"


def _sanitize(obj):
    """Ubah NaN/Inf → None secara rekursif agar JSON valid (strict-parseable)."""
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, float) and not np.isfinite(obj):
        return None
    return obj


# ─────────────────────────────────────────
# Muat split test 20% ASLI (sudah ter-scale oleh preprocessing.py)
# ─────────────────────────────────────────
def load_test_split(encoder):
    """Muat X_test.csv (sudah ter-scale) + y_test.csv dari models/output/.

    Return (X_df, y_encoded, label_names). Mengangkat exception bila file tak
    ada (akan dilaporkan pemanggil).
    """
    if not X_TEST_PATH.exists() or not Y_TEST_PATH.exists():
        raise FileNotFoundError(
            f"X_test.csv / y_test.csv tidak ada di {OUTPUT_DIR}. "
            f"Jalankan models/preprocessing.py lebih dulu."
        )
    X = pd.read_csv(X_TEST_PATH)
    y_enc = pd.read_csv(Y_TEST_PATH)["label"].values.astype(int)
    y_names = encoder.inverse_transform(y_enc)
    return X, np.asarray(y_enc), np.asarray(y_names)


# ─────────────────────────────────────────
# Evaluasi XGBoost (supervised)
# ─────────────────────────────────────────
def eval_xgboost(model, X, y_true, encoder):
    y_pred = model.predict(X)
    y_pred = np.asarray(y_pred).astype(int)

    acc = accuracy_score(y_true, y_pred)
    prec = precision_score(y_true, y_pred, average="weighted", zero_division=0)
    rec = recall_score(y_true, y_pred, average="weighted", zero_division=0)
    f1 = f1_score(y_true, y_pred, average="weighted", zero_division=0)

    labels_present = sorted(set(np.concatenate([y_true, y_pred]).tolist()))
    target_names = [encoder.classes_[i] for i in labels_present]

    cm = confusion_matrix(y_true, y_pred, labels=labels_present)
    report_dict = classification_report(
        y_true, y_pred, labels=labels_present, target_names=target_names,
        digits=4, zero_division=0, output_dict=True,
    )
    report_txt = classification_report(
        y_true, y_pred, labels=labels_present, target_names=target_names,
        digits=4, zero_division=0,
    )

    # Baseline majority-class pada test set ini (untuk konteks kejujuran poster).
    vals, counts = np.unique(y_true, return_counts=True)
    majority_idx = int(vals[np.argmax(counts)])
    majority_acc = float(counts.max() / counts.sum())

    return {
        "metrics": {
            "accuracy": float(acc),
            "precision_weighted": float(prec),
            "recall_weighted": float(rec),
            "f1_weighted": float(f1),
        },
        "majority_baseline": {
            "majority_class": encoder.classes_[majority_idx],
            "accuracy": majority_acc,
        },
        "labels_present": [encoder.classes_[i] for i in labels_present],
        "confusion_matrix": cm.tolist(),
        "classification_report": report_dict,
        "_cm": cm,
        "_cm_names": target_names,
        "_report_txt": report_txt,
        "_y_pred": y_pred,
    }


# ─────────────────────────────────────────
# Evaluasi Isolation Forest (unsupervised anomaly)
# ─────────────────────────────────────────
def eval_isolation_forest(model, X, y_true, encoder):
    normal_idx = int(list(encoder.classes_).index(NORMAL_LABEL_NAME))

    pred_raw = model.predict(X)                       # 1=inlier, -1=outlier
    y_pred_anom = (pred_raw == -1).astype(int)        # 1 = anomali
    y_true_anom = (y_true != normal_idx).astype(int)  # 1 = anomali (ground truth)
    anomaly_score = -model.decision_function(X)       # makin besar = makin anomali

    cm = confusion_matrix(y_true_anom, y_pred_anom, labels=[0, 1])
    tn, fp, fn, tp = cm.ravel()

    detection_rate = tp / (tp + fn) if (tp + fn) else float("nan")  # recall anomali
    false_positive_rate = fp / (fp + tn) if (fp + tn) else float("nan")
    precision_anom = tp / (tp + fp) if (tp + fp) else float("nan")
    f1_anom = (2 * precision_anom * detection_rate / (precision_anom + detection_rate)
               if (precision_anom + detection_rate) else float("nan"))
    accuracy = (tp + tn) / cm.sum() if cm.sum() else float("nan")
    try:
        auc = float(roc_auc_score(y_true_anom, anomaly_score))
    except ValueError:
        auc = float("nan")

    report_txt = classification_report(
        y_true_anom, y_pred_anom, labels=[0, 1],
        target_names=["Normal", "Anomali"], digits=4, zero_division=0,
    )
    report_dict = classification_report(
        y_true_anom, y_pred_anom, labels=[0, 1],
        target_names=["Normal", "Anomali"], digits=4, zero_division=0,
        output_dict=True,
    )

    return {
        "metrics": {
            "anomaly_detection_rate": float(detection_rate),
            "false_positive_rate": float(false_positive_rate),
            "precision_anomaly": float(precision_anom),
            "f1_anomaly": float(f1_anom),
            "accuracy_binary": float(accuracy),
            "roc_auc": auc,
        },
        "counts": {"TN": int(tn), "FP": int(fp), "FN": int(fn), "TP": int(tp),
                    "n_normal": int(tn + fp), "n_anomaly": int(tp + fn)},
        "confusion_matrix": cm.tolist(),
        "classification_report": report_dict,
        "_cm": cm,
        "_cm_names": ["Normal", "Anomali"],
        "_report_txt": report_txt,
    }


# ─────────────────────────────────────────
# Main
# ─────────────────────────────────────────
def main():
    print(LINE)
    print("  EVALUASI FORMAL MODEL ML — AI-ORBIT SOLAR POWER PLANT")
    print(LINE)
    print("  Test set = SPLIT 20% ASLI (models/output/X_test.csv, 10.000 baris)")
    print("  dari data/Condition_Monitoring_Dataset.csv — split 80/20,")
    print("  random_state=42, stratify=y. Model di-retrain di sklearn runtime ini.")
    print("  Model dievaluasi: XGBoost + Isolation Forest.")
    print(LINE)

    CM_DIR.mkdir(parents=True, exist_ok=True)

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "sklearn_runtime": sklearn.__version__,
        "test_set": {
            "source": "models/output/X_test.csv (+ y_test.csv)",
            "origin_dataset": "data/Condition_Monitoring_Dataset.csv",
            "split": "80/20, random_state=42, stratify=y (identik training)",
            "note": ("Split 20% ASLI hasil models/preprocessing.py; X_test sudah "
                      "ter-scale (StandardScaler fit dari train saja). Model "
                      "di-retrain dgn scikit-learn versi runtime → tanpa mismatch."),
        },
        "models_evaluated": ["XGBoost", "Isolation Forest"],
        "models_in_project_not_evaluated": ["KMeans", "Autoencoder", "LSTM"],
        "models_requested_but_absent": ["Random Forest", "SVM", "Neural Network"],
        "results": {},
        "errors": {},
    }

    # ── Muat scaler & encoder (wajib) ──
    try:
        with warnings.catch_warnings(record=True) as wlist:
            warnings.simplefilter("always")
            with open(SCALER_PATH, "rb") as f:
                scaler = pickle.load(f)
            with open(ENCODER_PATH, "rb") as f:
                encoder = pickle.load(f)
        for w in wlist:
            if InconsistentVersionWarning and issubclass(w.category,
                                                         InconsistentVersionWarning):
                _VERSION_WARNINGS.append(str(w.message).split("\n")[0])
        if _VERSION_WARNINGS:
            note = (f"Model di-pickle dengan versi scikit-learn BERBEDA dari "
                    f"runtime (runtime={sklearn.__version__}). Hasil unsupervised "
                    f"(Isolation Forest) khususnya dapat terpengaruh — verifikasi "
                    f"ulang di environment training (sklearn pin pyproject) bila "
                    f"dipakai untuk klaim ilmiah.")
            report["environment_caveat"] = {
                "runtime_sklearn": sklearn.__version__,
                "warnings": _VERSION_WARNINGS,
                "note": note,
            }
            print(f"\n[CAVEAT versi sklearn] runtime={sklearn.__version__}; "
                  f"model dilatih di versi berbeda. {note}")
    except Exception as e:
        print(f"\n[FATAL] Gagal memuat scaler/encoder: {e}")
        report["errors"]["preprocessing_artifacts"] = repr(e)
        _dump(report)
        return

    # ── Muat split test 20% asli ──
    try:
        X, y_true, y_names = load_test_split(encoder)
        n = len(y_true)
        print(f"\nTest set dimuat: {n} baris × {X.shape[1]} fitur")
        vals, counts = np.unique(y_names, return_counts=True)
        dist = {str(k): int(v) for k, v in zip(vals, counts)}
        report["test_set"]["n_rows"] = int(n)
        report["test_set"]["n_features"] = int(X.shape[1])
        report["test_set"]["label_distribution"] = dist
        print("Distribusi label:", dist)
    except Exception as e:
        print(f"\n[FATAL] Gagal preprocessing test set: {e}")
        report["errors"]["preprocessing"] = repr(e)
        _dump(report)
        return

    txt_sections = []

    # ── XGBoost ──
    print("\n" + LINE)
    print("  [1] XGBOOST — Supervised Classifier (10 kelas)")
    print(LINE)
    try:
        with open(XGB_PATH, "rb") as f:
            xgb = pickle.load(f)
        res = eval_xgboost(xgb, X, y_true, encoder)
        m = res["metrics"]
        print(f"  Accuracy           : {_fmt_pct(m['accuracy'])}")
        print(f"  Precision (weighted): {_fmt_pct(m['precision_weighted'])}")
        print(f"  Recall    (weighted): {_fmt_pct(m['recall_weighted'])}")
        print(f"  F1-score  (weighted): {_fmt_pct(m['f1_weighted'])}")
        print(f"  [baseline majority '{res['majority_baseline']['majority_class']}'"
              f" : {_fmt_pct(res['majority_baseline']['accuracy'])}]")
        print("\n  Classification report per kelas:")
        print("  " + res["_report_txt"].replace("\n", "\n  "))
        print("  Confusion matrix (baris=aktual, kolom=prediksi):")
        print("    kelas:", res["_cm_names"])
        print("  " + str(res["_cm"]).replace("\n", "\n  "))

        cm_png = CM_DIR / "xgboost_confusion_matrix.png"
        _save_confusion_png(res["_cm"], res["_cm_names"],
                            "XGBoost — Confusion Matrix (Realtime Test Set)", cm_png)
        print(f"\n  PNG confusion matrix → {cm_png.relative_to(REPO_DIR)}")

        # bersihkan field internal (underscore) sebelum json
        clean = {k: v for k, v in res.items() if not k.startswith("_")}
        clean["confusion_matrix_png"] = str(cm_png.relative_to(REPO_DIR))
        report["results"]["XGBoost"] = clean

        txt_sections.append(_xgb_txt(res))
    except Exception as e:
        import traceback
        err = traceback.format_exc()
        print(f"  [ERROR] Evaluasi XGBoost gagal:\n{err}")
        report["errors"]["XGBoost"] = repr(e)

    # ── Isolation Forest ──
    print("\n" + LINE)
    print("  [2] ISOLATION FOREST — Unsupervised Anomaly Detector")
    print(LINE)
    print("  (Metrik BERBEDA dari supervised: tugasnya memisahkan Normal vs")
    print("   Anomali, bukan klasifikasi 10 kelas. Dilatih HANYA dari data Normal.)")
    try:
        with open(IF_PATH, "rb") as f:
            iforest = pickle.load(f)
        res = eval_isolation_forest(iforest, X, y_true, encoder)
        m = res["metrics"]
        c = res["counts"]
        print(f"\n  Anomaly detection rate (recall anomali): {_fmt_pct(m['anomaly_detection_rate'])}"
              f"   [{c['TP']}/{c['n_anomaly']} anomali terdeteksi]")
        print(f"  False positive rate (Normal→Anomali)   : {_fmt_pct(m['false_positive_rate'])}"
              f"   [{c['FP']}/{c['n_normal']} normal salah-flag]")
        print(f"  Precision (anomali)                    : {_fmt_pct(m['precision_anomaly'])}")
        print(f"  F1-score  (anomali)                    : {_fmt_pct(m['f1_anomaly'])}")
        print(f"  Accuracy  (biner Normal/Anomali)       : {_fmt_pct(m['accuracy_binary'])}")
        print(f"  ROC-AUC                                : {m['roc_auc']:.4f}")
        print("\n  Classification report (0=Normal, 1=Anomali):")
        print("  " + res["_report_txt"].replace("\n", "\n  "))
        print("  Confusion matrix [ [TN FP] [FN TP] ]:")
        print("  " + str(res["_cm"]).replace("\n", "\n  "))

        cm_png = CM_DIR / "isolation_forest_confusion_matrix.png"
        _save_confusion_png(res["_cm"], res["_cm_names"],
                            "Isolation Forest — Normal vs Anomali (Realtime Test Set)",
                            cm_png)
        print(f"\n  PNG confusion matrix → {cm_png.relative_to(REPO_DIR)}")

        clean = {k: v for k, v in res.items() if not k.startswith("_")}
        clean["confusion_matrix_png"] = str(cm_png.relative_to(REPO_DIR))
        report["results"]["Isolation Forest"] = clean

        txt_sections.append(_if_txt(res))
    except Exception as e:
        import traceback
        err = traceback.format_exc()
        print(f"  [ERROR] Evaluasi Isolation Forest gagal:\n{err}")
        report["errors"]["Isolation Forest"] = repr(e)

    # ── Simpan laporan ──
    _dump(report, txt_sections)

    print("\n" + LINE)
    print("  SELESAI. File output:")
    print(f"    • {REPORT_JSON.relative_to(REPO_DIR)}")
    print(f"    • {REPORT_TXT.relative_to(REPO_DIR)}")
    print(f"    • {CM_DIR.relative_to(REPO_DIR)}/  (PNG confusion matrix)")
    if report["errors"]:
        print(f"  CATATAN: ada {len(report['errors'])} error — lihat bagian errors.")
    print(LINE)


# ─────────────────────────────────────────
# Penyusun teks human-readable
# ─────────────────────────────────────────
def _xgb_txt(res):
    m = res["metrics"]
    b = res["majority_baseline"]
    lines = [
        "-" * 70,
        "MODEL 1: XGBoost — Supervised Classifier (10 kelas kondisi)",
        "-" * 70,
        f"  Accuracy            : {_fmt_pct(m['accuracy'])}",
        f"  Precision (weighted): {_fmt_pct(m['precision_weighted'])}",
        f"  Recall    (weighted): {_fmt_pct(m['recall_weighted'])}",
        f"  F1-score  (weighted): {_fmt_pct(m['f1_weighted'])}",
        f"  Baseline majority-class ('{b['majority_class']}'): {_fmt_pct(b['accuracy'])}",
        "",
        "  Classification report per kelas:",
        "    " + res["_report_txt"].replace("\n", "\n    "),
        "  Confusion matrix (baris=aktual, kolom=prediksi):",
        "    kelas: " + ", ".join(res["_cm_names"]),
        "    " + str(res["_cm"]).replace("\n", "\n    "),
        "",
    ]
    return "\n".join(lines)


def _if_txt(res):
    m = res["metrics"]
    c = res["counts"]
    lines = [
        "-" * 70,
        "MODEL 2: Isolation Forest — Unsupervised Anomaly Detector",
        "-" * 70,
        "  CATATAN: metrik berbeda dari supervised. Tugas = memisahkan Normal vs",
        "  Anomali (semua label != Normal). Model dilatih HANYA dari data Normal.",
        "",
        f"  Anomaly detection rate (recall anomali): {_fmt_pct(m['anomaly_detection_rate'])} "
        f"[{c['TP']}/{c['n_anomaly']}]",
        f"  False positive rate (Normal->Anomali)  : {_fmt_pct(m['false_positive_rate'])} "
        f"[{c['FP']}/{c['n_normal']}]",
        f"  Precision (anomali)                    : {_fmt_pct(m['precision_anomaly'])}",
        f"  F1-score  (anomali)                    : {_fmt_pct(m['f1_anomaly'])}",
        f"  Accuracy  (biner)                      : {_fmt_pct(m['accuracy_binary'])}",
        f"  ROC-AUC                                : {m['roc_auc']:.4f}",
        "",
        "  Classification report (0=Normal, 1=Anomali):",
        "    " + res["_report_txt"].replace("\n", "\n    "),
        "  Confusion matrix [ [TN FP] [FN TP] ]:",
        "    " + str(res["_cm"]).replace("\n", "\n    "),
        "",
    ]
    return "\n".join(lines)


def _dump(report, txt_sections=None):
    with open(REPORT_JSON, "w", encoding="utf-8") as f:
        json.dump(_sanitize(report), f, ensure_ascii=False, indent=2,
                  allow_nan=False)

    header = [
        LINE,
        "  LAPORAN EVALUASI MODEL ML — AI-ORBIT SOLAR POWER PLANT",
        LINE,
        f"  Dibuat            : {report['generated_at']}",
        f"  Runtime sklearn   : {report.get('sklearn_runtime','?')} "
        f"(model di-retrain di versi ini → tanpa mismatch pickle)",
        f"  Test set          : {report['test_set']['source']} "
        f"({report['test_set'].get('n_rows','?')} baris, "
        f"{report['test_set'].get('n_features','?')} fitur)",
        f"  Dataset sumber    : {report['test_set'].get('origin_dataset','?')}",
        f"  Split             : {report['test_set'].get('split','?')}",
        f"  Distribusi label  : {report['test_set'].get('label_distribution', {})}",
        "",
        f"  Model dievaluasi  : {', '.join(report['models_evaluated'])}",
        f"  Model lain di proj.: {', '.join(report['models_in_project_not_evaluated'])} "
        "(unsupervised/sequence, di luar scope)",
        f"  Diminta tapi TIDAK ADA di project: "
        f"{', '.join(report['models_requested_but_absent'])}",
    ]
    if report.get("environment_caveat"):
        ec = report["environment_caveat"]
        header += [
            "",
            f"  CAVEAT VERSI: runtime scikit-learn {ec['runtime_sklearn']} != versi",
            "  saat model dilatih. " + ec["note"],
        ]
    header += [LINE, ""]
    body = txt_sections or []
    if report.get("errors"):
        body.append("-" * 70)
        body.append("ERROR SAAT EVALUASI:")
        for k, v in report["errors"].items():
            body.append(f"  • {k}: {v}")
        body.append("")
    with open(REPORT_TXT, "w", encoding="utf-8") as f:
        f.write("\n".join(header) + "\n" + "\n".join(body))


if __name__ == "__main__":
    main()
