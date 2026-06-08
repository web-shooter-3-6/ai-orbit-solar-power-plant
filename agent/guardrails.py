"""
agent/guardrails.py
────────────────────────────────────────────────────────────
Guardrail input: validasi DataFrame sensor sebelum masuk ke agent.

Fungsi utama:
    validate_input(df) -> (df_clean, issues)

Tujuan: pastikan data yang masuk ke pipeline bersih & lengkap supaya
analisis agent tidak menghasilkan hasil sampah karena data rusak.
"""

import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import pandas as pd

# Kolom wajib minimal yang harus ada (nama lowercase sesuai data MQTT)
KOLOM_WAJIB = [
    "pv_voltage",
    "pv_power_output",
    "battery_temperature",
    "grid_voltage",
    "sensor_latency",
]


def validate_input(df: pd.DataFrame):
    """Validasi DataFrame sensor.

    Aturan:
      1) DataFrame kosong              → (None, ["DataFrame kosong"])
      2) Kolom wajib tidak ada         → (None, ["Kolom X tidak ditemukan"])
      3) Ada baris null                → baris di-drop, dicatat di issues
      4) Setelah drop jadi kosong      → (None, issues)

    Return:
        (df_clean, issues) — df_clean = DataFrame bersih (atau None kalau gagal),
        issues = list string masalah yang ditemukan (semuanya juga di-print).
    """
    issues = []

    # 1) Cek DataFrame kosong / None
    if df is None or df.empty:
        pesan = "DataFrame kosong"
        print(f"[guardrails] ! {pesan}")
        return None, [pesan]

    # 2) Cek kolom wajib ada
    for kolom in KOLOM_WAJIB:
        if kolom not in df.columns:
            pesan = f"Kolom {kolom} tidak ditemukan"
            print(f"[guardrails] ! {pesan}")
            issues.append(pesan)
    # kalau ada kolom wajib yang hilang → tolak (data tidak bisa dianalisis)
    if issues:
        return None, issues

    # 3) Cek & buang baris yang mengandung null
    jml_awal = len(df)
    n_null = int(df.isnull().any(axis=1).sum())
    if n_null > 0:
        df = df.dropna().reset_index(drop=True)
        pesan = f"{n_null} baris mengandung null → di-drop"
        print(f"[guardrails] ! {pesan}")
        issues.append(pesan)

    # 4) Kalau setelah pembersihan jadi kosong
    if df.empty:
        pesan = "Semua baris ter-drop karena null, tidak ada data valid"
        print(f"[guardrails] ! {pesan}")
        issues.append(pesan)
        return None, issues

    if not issues:
        print(f"[guardrails] ✓ Validasi OK ({jml_awal} baris, tidak ada masalah)")

    return df, issues


# Quick self-test
if __name__ == "__main__":
    print("--- Test 1: DataFrame kosong ---")
    print(validate_input(pd.DataFrame()))

    print("\n--- Test 2: kolom wajib hilang ---")
    print(validate_input(pd.DataFrame([{"pv_voltage": 400}])))

    print("\n--- Test 3: data valid + 1 baris null ---")
    df = pd.DataFrame([
        {"pv_voltage": 400, "pv_power_output": 10, "battery_temperature": 35,
         "grid_voltage": 230, "sensor_latency": 20},
        {"pv_voltage": None, "pv_power_output": 10, "battery_temperature": 35,
         "grid_voltage": 230, "sensor_latency": 20},
    ])
    clean, iss = validate_input(df)
    print(f"clean rows={len(clean) if clean is not None else None}, issues={iss}")
