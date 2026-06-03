import psycopg2
import psycopg2.extras   # untuk executemany batch insert
import pandas as pd
import yaml, os, time
from datetime import datetime

# load config
with open("config.yaml") as f:
    cfg = yaml.safe_load(f)

DB_CONFIG = {
    "host":     cfg["database"]["host"],
    "dbname":   cfg["database"]["name"],
    "user":     "postgres",
    "password": os.getenv("DB_PASSWORD", "solar123"),
    "port":     5432
}

# connection pool sederhana — satu koneksi persistent
_conn: psycopg2.extensions.connection | None = None

def get_conn() -> psycopg2.extensions.connection:
    
    # return koneksi yang sudah ada, atau buat baru.
    # auto-reconnect kalau koneksi putus.
    
    global _conn
    try:
        if _conn is None or _conn.closed:
            _conn = psycopg2.connect(**DB_CONFIG)
            _conn.autocommit = False
            print("[db_writer] Connected to TimescaleDB")
    except psycopg2.OperationalError as e:
        print(f"[db_writer] Koneksi gagal: {e}. Retry dalam 5 detik...")
        time.sleep(5)
        _conn = psycopg2.connect(**DB_CONFIG)
    return _conn

# insert
INSERT_SQL = """
    INSERT INTO sensor_data (
        time, plant_id, device_id,
        irradiance, temp_ambient, temp_module,
        power_kw, voltage_v, current_a, pr,
        string_1_v, string_2_v, string_3_v, string_4_v
    ) VALUES (
        %(time)s, %(plant_id)s, %(device_id)s,
        %(irradiance)s, %(temp_ambient)s, %(temp_module)s,
        %(power_kw)s, %(voltage_v)s, %(current_a)s, %(pr)s,
        %(string_1_v)s, %(string_2_v)s,
        %(string_3_v)s, %(string_4_v)s
    )
    ON CONFLICT DO NOTHING
"""

def batch_write(df: pd.DataFrame) -> int:
    """
    Tulis DataFrame ke sensor_data.
    Pakai executemany — jauh lebih cepat dari insert satu-satu.
    Return: jumlah row yang berhasil ditulis.
    """
    if df.empty:
        return 0

    # Pastikan kolom timestamp ada dan benar formatnya
    if "time" not in df.columns:
        df["time"] = datetime.utcnow()
    if "device_id" not in df.columns:
        df["device_id"] = "inv-01"

    # Isi kolom yang mungkin tidak ada dengan None
    required_cols = [
        "time","plant_id","device_id",
        "irradiance","temp_ambient","temp_module",
        "power_kw","voltage_v","current_a","pr",
        "string_1_v","string_2_v","string_3_v","string_4_v"
    ]
    for col in required_cols:
        if col not in df.columns:
            df[col] = None

    records = df[required_cols].to_dict("records")

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            psycopg2.extras.execute_batch(cur, INSERT_SQL, records,
                                          page_size=100)
        conn.commit()
        return len(records)

    except psycopg2.Error as e:
        conn.rollback()
        print(f"[db_writer] Insert gagal: {e}")
        _fallback_to_file(df)   # jangan buang data
        return 0

# fallback
FALLBACK_PATH = "data/raw/failed_writes.csv"

def _fallback_to_file(df: pd.DataFrame):
    
    # kalau DB down, simpan ke CSV dulu.
    # ata tidak boleh hilang — lebih baik di file daripada lenyap.
    
    os.makedirs(os.path.dirname(FALLBACK_PATH), exist_ok=True)
    header = not os.path.exists(FALLBACK_PATH)
    df.to_csv(FALLBACK_PATH, mode="a", header=header, index=False)
    print(f"[db_writer] {len(df)} rows disimpan ke fallback: {FALLBACK_PATH}")

def flush_fallback():
    
    # coba kirim ulang data yang tersimpan di fallback csv.
    # dipanggil oleh scheduled_tasks.py setiap jam.
    
    if not os.path.exists(FALLBACK_PATH):
        return   # tidak ada yang perlu di-flush

    df = pd.read_csv(FALLBACK_PATH)
    written = batch_write(df)

    if written == len(df):
        os.remove(FALLBACK_PATH)   # berhasil semua, hapus file
        print(f"[db_writer] Fallback flushed: {written} rows dikirim ke DB")
    else:
        print(f"[db_writer] Flush sebagian: {written}/{len(df)} rows")

# single row write utk audit log
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
    
    # tulis satu record ke audit_log.
    # dipanggil dari alert/audit_log.py setiap ada keputusan agent.

    record.setdefault("time",            datetime.utcnow())
    record.setdefault("approved_by",     None)
    record.setdefault("response_time_s", None)
    record.setdefault("model_versions",  "{}")

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(AUDIT_SQL, record)
        conn.commit()
    except psycopg2.Error as e:
        conn.rollback()
        print(f"[db_writer] Audit log gagal: {e}")