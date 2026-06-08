"""
ingestion/db_writer.py
────────────────────────────────────────────────────────────
Penulis data sensor ke TimescaleDB (PostgreSQL).

Disederhanakan: simpan SELURUH baris sensor (semua kolom dataset) ke
tabel `sensor_readings` secara dinamis — tidak lagi hardcode kolom yang
tidak sesuai dataset. Kalau DB tidak tersedia → fallback ke CSV (data
tidak boleh hilang). Tetap menyediakan write_audit() untuk audit log.
"""

import os
import time
from datetime import datetime

import pandas as pd

try:
    import psycopg2
    import psycopg2.extras
except Exception:  # psycopg2 belum terpasang — pipeline tetap jalan via fallback CSV
    psycopg2 = None

try:
    import yaml
    with open("config.yaml") as f:
        _cfg = yaml.safe_load(f)
    _db = _cfg.get("database", {})
except Exception:
    _db = {}

DB_CONFIG = {
    "host":     _db.get("host", "localhost"),
    "dbname":   _db.get("name", "solar_db"),
    "user":     _db.get("user", "postgres"),
    "password": os.getenv("DB_PASSWORD", "solar123"),
    "port":     _db.get("port", 5432),
}

FALLBACK_PATH = "data/raw/failed_writes.csv"

# ─────────────────────────────────────────────────────────
# Semua 52 kolom dataset (lowercase). Dipakai untuk auto-create tabel.
#   timestamp              → TIMESTAMPTZ
#   system_condition_label → TEXT
#   sisanya                → DOUBLE PRECISION
# ─────────────────────────────────────────────────────────
DATASET_COLUMNS = [
    "timestamp", "hour", "day_index", "pv_voltage", "pv_current",
    "pv_power_output", "pv_panel_temperature", "solar_irradiance",
    "pv_efficiency", "pv_dc_power", "pv_ac_power", "pv_inverter_temperature",
    "pv_frequency", "battery_soc", "battery_soh", "battery_voltage",
    "battery_current", "battery_temperature", "battery_charge_rate",
    "battery_discharge_rate", "battery_internal_resistance",
    "battery_cycle_count", "ev_charging_load", "ev_charging_current",
    "ev_charging_voltage", "charging_station_temperature", "active_ev_count",
    "charging_duration", "fast_charging_status", "grid_voltage", "grid_current",
    "grid_frequency", "power_demand", "reactive_power", "load_factor",
    "energy_export", "energy_import", "power_factor", "sensor_latency",
    "packet_loss_rate", "signal_strength", "data_transmission_rate",
    "edge_node_cpu_usage", "cloud_response_time", "dwt_coeff_a1",
    "dwt_coeff_d1", "dwt_coeff_d2", "signal_energy", "signal_entropy",
    "rms_value", "crest_factor", "system_condition_label",
]


def _col_type(col: str) -> str:
    """Tentukan tipe kolom SQL untuk auto-create tabel."""
    if col == "timestamp":
        return "TIMESTAMPTZ"
    if col == "system_condition_label":
        return "TEXT"
    return "DOUBLE PRECISION"


# connection pool sederhana — satu koneksi persistent
_conn = None


def get_conn():
    """Return koneksi yang sudah ada atau buat baru (auto-reconnect)."""
    global _conn
    if psycopg2 is None:
        raise RuntimeError("psycopg2 tidak terpasang")
    try:
        if _conn is None or _conn.closed:
            _conn = psycopg2.connect(**DB_CONFIG)
            _conn.autocommit = False
            print("[db_writer] Terhubung ke TimescaleDB")
    except psycopg2.OperationalError as e:
        print(f"[db_writer] Koneksi gagal: {e}. Retry dalam 5 detik...")
        time.sleep(5)
        _conn = psycopg2.connect(**DB_CONFIG)
    return _conn


def create_table_if_not_exists():
    """Auto-create tabel sensor_readings (id serial + semua kolom dataset)."""
    kolom_sql = ",\n        ".join(
        f"{c} {_col_type(c)}" for c in DATASET_COLUMNS
    )
    ddl = f"""
    CREATE TABLE IF NOT EXISTS sensor_readings (
        id SERIAL PRIMARY KEY,
        {kolom_sql}
    )
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(ddl)
        conn.commit()
        print("[db_writer] Tabel sensor_readings siap")
    except Exception as e:
        conn.rollback()
        print(f"[db_writer] Gagal create tabel: {e}")
        raise


def batch_write(df: pd.DataFrame) -> int:
    """Tulis DataFrame sensor ke sensor_readings (kolom dinamis).

    Hanya kolom yang termasuk DATASET_COLUMNS yang ditulis. Kalau DB gagal
    → fallback ke CSV. Return jumlah baris yang berhasil ditulis ke DB.
    """
    if df is None or df.empty:
        return 0

    # Pilih hanya kolom dataset yang benar-benar ada di df
    cols = [c for c in DATASET_COLUMNS if c in df.columns]
    if not cols:
        print("[db_writer] Tidak ada kolom dataset yang cocok, fallback ke CSV")
        _fallback_to_file(df)
        return 0

    if psycopg2 is None:
        # DB tidak tersedia sama sekali → langsung fallback
        _fallback_to_file(df)
        return 0

    placeholders = ", ".join(f"%({c})s" for c in cols)
    col_names = ", ".join(cols)
    insert_sql = f"INSERT INTO sensor_readings ({col_names}) VALUES ({placeholders})"

    # Bersihkan record: ganti NaN dengan None supaya psycopg2 happy
    records = (
        df[cols]
        .astype(object)
        .where(pd.notnull(df[cols]), None)
        .to_dict("records")
    )

    try:
        create_table_if_not_exists()  # pastikan tabel ada
        conn = get_conn()
        with conn.cursor() as cur:
            psycopg2.extras.execute_batch(cur, insert_sql, records, page_size=100)
        conn.commit()
        print(f"[db_writer] {len(records)} baris ditulis ke sensor_readings")
        return len(records)
    except Exception as e:
        try:
            get_conn().rollback()
        except Exception:
            pass
        print(f"[db_writer] Insert gagal: {e} → fallback ke CSV")
        _fallback_to_file(df)
        return 0


# ─────────────────────────────────────────────────────────
# Fallback CSV — data tidak boleh hilang kalau DB down
# ─────────────────────────────────────────────────────────
def _fallback_to_file(df: pd.DataFrame):
    """Simpan ke CSV kalau DB tidak bisa ditulis."""
    try:
        os.makedirs(os.path.dirname(FALLBACK_PATH), exist_ok=True)
        header = not os.path.exists(FALLBACK_PATH)
        df.to_csv(FALLBACK_PATH, mode="a", header=header, index=False)
        print(f"[db_writer] {len(df)} baris disimpan ke fallback: {FALLBACK_PATH}")
    except Exception as e:
        print(f"[db_writer] Fallback CSV juga gagal: {e}")


def flush_fallback():
    """Coba kirim ulang data yang tersimpan di fallback CSV ke DB."""
    if not os.path.exists(FALLBACK_PATH):
        return
    try:
        df = pd.read_csv(FALLBACK_PATH)
        written = batch_write(df)
        if written == len(df):
            os.remove(FALLBACK_PATH)
            print(f"[db_writer] Fallback flushed: {written} baris ke DB")
        else:
            print(f"[db_writer] Flush sebagian: {written}/{len(df)} baris")
    except Exception as e:
        print(f"[db_writer] Flush fallback gagal: {e}")


# ─────────────────────────────────────────────────────────
# Audit log (single row) — dipertahankan
# ─────────────────────────────────────────────────────────
AUDIT_SQL = """
    INSERT INTO audit_log (
        time, plant_id, risk_score, anomaly_type,
        action, severity, root_cause, reasoning,
        approved_by, response_time_s, model_versions
    ) VALUES (
        %(time)s, %(plant_id)s, %(risk_score)s, %(anomaly_type)s,
        %(action)s, %(severity)s, %(root_cause)s, %(reasoning)s,
        %(approved_by)s, %(response_time_s)s, %(model_versions)s
    )
"""


def write_audit(record: dict):
    """Tulis satu record ke audit_log (dipanggil saat ada keputusan agent)."""
    record.setdefault("time", datetime.utcnow())
    record.setdefault("approved_by", None)
    record.setdefault("response_time_s", None)
    record.setdefault("model_versions", "{}")

    if psycopg2 is None:
        print("[db_writer] psycopg2 tidak ada, audit log dilewati")
        return

    try:
        conn = get_conn()
        with conn.cursor() as cur:
            cur.execute(AUDIT_SQL, record)
        conn.commit()
    except Exception as e:
        try:
            get_conn().rollback()
        except Exception:
            pass
        print(f"[db_writer] Audit log gagal: {e}")
