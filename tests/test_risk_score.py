"""
tests/test_risk_score.py
────────────────────────────────────────────────────────────
Test sederhana logika risk_score 2-layer (model + rule sensor).

Jalankan dari root repo:
    python tests/test_risk_score.py

Tiap test mencetak PASS/FAIL + risk_score aktual vs ekspektasi.
"""

import sys
from pathlib import Path

# ── Path setup: root repo masuk sys.path ──
REPO_DIR = Path(__file__).resolve().parent.parent
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

import pandas as pd
from agent.anomaly_agent import AnomalyAgent, FEATURE_ORDER

DATA_PATH = REPO_DIR / "data" / "Condition_Monitoring_Dataset.csv"


def baseline_means() -> dict:
    """Nilai rata-rata tiap fitur dari baris berlabel 'Normal' (baseline normal asli).

    Dipakai untuk mengisi fitur yang tidak di-override sehingga benar-benar
    merepresentasikan sampel normal (bukan campuran semua kelas).
    """
    if not DATA_PATH.exists():
        return {c: 0.0 for c in FEATURE_ORDER}
    df = pd.read_csv(DATA_PATH)
    if "System_Condition_Label" in df.columns:
        df = df[df["System_Condition_Label"] == "Normal"]
    num = df.select_dtypes(include="number")
    return {c: float(num[c].mean()) for c in FEATURE_ORDER if c in num.columns}


def make_input(means: dict, overrides: dict) -> dict:
    """Susun 49 fitur: rata-rata dataset + override manual."""
    d = {c: means.get(c, 0.0) for c in FEATURE_ORDER}
    d.update(overrides)
    return d


def run():
    print("=" * 64)
    print("  TEST LOGIKA RISK SCORE — AI-ORBIT SOLAR")
    print("=" * 64)

    agent = AnomalyAgent()
    means = baseline_means()
    results = []

    # ── Definisi test case ──────────────────────────────────
    # (nama, override, cek_fungsi(hasil) -> (ok, info_ekspektasi))
    cases = []

    # Test 1: input normal → risk_score < 0.25, level LOW
    def t1(r):
        ok = r["risk_score"] < 0.25 and r["risk_level"] == "LOW"
        return ok, "risk_score < 0.25 & level == LOW"
    # Sampel normal asli = semua fitur di nilai rata-rata kelas Normal
    cases.append(("Input normal", {}, t1))

    # Test 2: Battery_Temperature=85 → risk_score >= 0.75, level CRITICAL
    def t2(r):
        ok = r["risk_score"] >= 0.75 and r["risk_level"] == "CRITICAL"
        return ok, "risk_score >= 0.75 & level == CRITICAL"
    cases.append(("Battery_Temperature=85", {"Battery_Temperature": 85}, t2))

    # Test 3: PV_Voltage=150 → risk_score >= 0.50, level HIGH atau CRITICAL
    def t3(r):
        ok = r["risk_score"] >= 0.50 and r["risk_level"] in ("HIGH", "CRITICAL")
        return ok, "risk_score >= 0.50 & level in {HIGH, CRITICAL}"
    cases.append(("PV_Voltage=150", {"PV_Voltage": 150}, t3))

    # Test 4: Sensor_Latency=9000 → risk_score >= 0.40, level MEDIUM atau HIGH
    def t4(r):
        ok = r["risk_score"] >= 0.40 and r["risk_level"] in ("MEDIUM", "HIGH")
        return ok, "risk_score >= 0.40 & level in {MEDIUM, HIGH}"
    cases.append(("Sensor_Latency=9000", {"Sensor_Latency": 9000}, t4))

    # Test 5: semua nilai normal → dominant_fault = "Normal"
    def t5(r):
        ok = r["dominant_fault"] == "Normal"
        return ok, 'dominant_fault == "Normal"'
    cases.append(("Semua normal (fault)", {}, t5))

    # Test 6: Battery_Temperature=85 AND PV_Voltage=150 → risk_score >= 0.90, CRITICAL
    def t6(r):
        ok = r["risk_score"] >= 0.90 and r["risk_level"] == "CRITICAL"
        return ok, "risk_score >= 0.90 & level == CRITICAL"
    cases.append(("Battery=85 & PV=150", {
        "Battery_Temperature": 85, "PV_Voltage": 150,
    }, t6))

    # ── Jalankan ────────────────────────────────────────────
    print()
    for i, (nama, ov, cek) in enumerate(cases, start=1):
        hasil = agent.analyze(make_input(means, ov))
        ok, ekspektasi = cek(hasil)
        results.append(ok)
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] Test {i}: {nama}")
        print(f"        Ekspektasi : {ekspektasi}")
        print(f"        Aktual     : risk_score={hasil['risk_score']} | "
              f"level={hasil['risk_level']} | fault={hasil['dominant_fault']} | "
              f"anomaly={hasil['anomaly_detected']}")
        print()

    # ── Ringkasan ───────────────────────────────────────────
    lulus = sum(results)
    total = len(results)
    print("=" * 64)
    print(f"  HASIL: {lulus}/{total} test PASS")
    print("=" * 64)
    return lulus == total


if __name__ == "__main__":
    semua_lulus = run()
    sys.exit(0 if semua_lulus else 1)
