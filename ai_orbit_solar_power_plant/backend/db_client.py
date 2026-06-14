"""
ai_orbit_solar_power_plant/backend/db_client.py
────────────────────────────────────────────────────────────
Modul koneksi Supabase PostgreSQL untuk storage Realtime Feed & History,
agar sistem bisa full-cloud: worker Railway (realtime_simulator) MENULIS
data, Reflex Cloud MEMBACA data — keduanya lewat tabel Supabase yang sama.

Semua operasi GRACEFUL: bila SUPABASE_DB_URL tidak ada, psycopg2 belum
terpasang, atau koneksi gagal → fungsi mengembalikan nilai aman ([] / False)
dan TIDAK meng-crash aplikasi (mode lokal / tanpa DB tetap jalan).

──────────────────────────────────────────────────────────────
SKEMA TABEL (jalankan sekali di Supabase SQL editor, atau panggil
init_tables() dari Python setelah SUPABASE_DB_URL terisi):

    CREATE TABLE IF NOT EXISTS realtime_results (
        id              BIGSERIAL PRIMARY KEY,
        timestamp       TEXT,
        risk_score      DOUBLE PRECISION,
        risk_level      TEXT,
        dominant_fault  TEXT,
        anomaly_detected BOOLEAN,
        explanation     TEXT,
        recommendations JSONB,
        sensor_snapshot JSONB,
        created_at      TIMESTAMPTZ DEFAULT now()
    );

    CREATE TABLE IF NOT EXISTS history (
        id              BIGSERIAL PRIMARY KEY,
        timestamp       TEXT,
        risk_score      DOUBLE PRECISION,
        risk_level      TEXT,
        dominant_fault  TEXT,
        anomaly_detected BOOLEAN,
        explanation     TEXT,
        recommendations JSONB,
        sensor_snapshot JSONB,
        created_at      TIMESTAMPTZ DEFAULT now()
    );
──────────────────────────────────────────────────────────────
"""

import os
import json

from dotenv import load_dotenv

load_dotenv()

# Import psycopg2 secara aman: bila belum terpasang, modul tetap bisa di-import
# dan semua fungsi DB akan jalan dalam mode graceful (return kosong/False).
try:
    import psycopg2
    import psycopg2.extras
    _PSYCOPG2_OK = True
except Exception as _e:  # pragma: no cover
    psycopg2 = None
    _PSYCOPG2_OK = False
    _PSYCOPG2_ERR = _e

# Supaya pesan status koneksi hanya muncul SEKALI (hindari spam tiap operasi).
_announced = False


# ─────────────────────────────────────────────────────────
# Koneksi
# ─────────────────────────────────────────────────────────
def get_connection():
    """Koneksi ke Supabase PostgreSQL (graceful).

    Return koneksi psycopg2, atau None bila:
      - psycopg2 belum terpasang, atau
      - SUPABASE_DB_URL tidak ada di env (mode lokal), atau
      - koneksi gagal.
    """
    global _announced

    if not _PSYCOPG2_OK:
        if not _announced:
            print("[db_client] psycopg2 belum terpasang, mode lokal")
            _announced = True
        return None

    db_url = os.getenv("SUPABASE_DB_URL")
    if not db_url:
        if not _announced:
            print("[db_client] SUPABASE_DB_URL tidak ditemukan, mode lokal")
            _announced = True
        return None

    try:
        conn = psycopg2.connect(db_url)
        if not _announced:
            print("[db_client] Terhubung ke Supabase")
            _announced = True
        return conn
    except Exception as e:
        print(f"[db_client] Koneksi gagal: {e}")
        return None


# ─────────────────────────────────────────────────────────
# Helper internal insert (dipakai realtime & history)
# ─────────────────────────────────────────────────────────
def _insert_row(table: str, data: dict, rolling_limit: int = 0) -> bool:
    """Insert 1 baris ke `table`. Bila rolling_limit > 0, sisakan hanya
    `rolling_limit` baris terbaru (hapus sisanya). Graceful (return bool)."""
    conn = get_connection()
    if conn is None:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {table}
                (timestamp, risk_score, risk_level, dominant_fault,
                 anomaly_detected, explanation, recommendations,
                 sensor_snapshot)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    data.get("timestamp"),
                    data.get("risk_score"),
                    data.get("risk_level"),
                    data.get("dominant_fault"),
                    data.get("anomaly_detected"),
                    data.get("explanation", ""),
                    json.dumps(data.get("recommendations", [])),
                    json.dumps(data.get("sensor_snapshot", {})),
                ),
            )
            # Rolling window: simpan hanya N baris terbaru (mis. realtime=500).
            if rolling_limit and rolling_limit > 0:
                cur.execute(
                    f"""
                    DELETE FROM {table}
                    WHERE id NOT IN (
                        SELECT id FROM {table}
                        ORDER BY created_at DESC LIMIT %s
                    )
                    """,
                    (rolling_limit,),
                )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[db_client] Insert {table} gagal: {e}")
        if conn:
            conn.close()
        return False


def _get_rows(table: str, limit: int) -> list:
    """Ambil `limit` baris terbaru dari `table`, urut terlama→terbaru.
    Graceful (return [] bila gagal/kosong)."""
    conn = get_connection()
    if conn is None:
        return []
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT timestamp, risk_score, risk_level, dominant_fault,
                       anomaly_detected, explanation, recommendations,
                       sensor_snapshot
                FROM {table}
                ORDER BY created_at DESC LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
        conn.close()
        return list(reversed([dict(r) for r in rows]))  # terlama dulu
    except Exception as e:
        print(f"[db_client] Get {table} gagal: {e}")
        if conn:
            conn.close()
        return []


# ─────────────────────────────────────────────────────────
# Realtime results (rolling window 500)
# ─────────────────────────────────────────────────────────
def insert_realtime_result(data: dict) -> bool:
    """Insert 1 hasil analisis ke tabel realtime_results.

    Setelah insert, hapus baris lama jika total > 500 (rolling window,
    hanya simpan 500 terbaru). Return True jika sukses, False jika gagal.
    """
    return _insert_row("realtime_results", data, rolling_limit=500)


def get_realtime_results(limit: int = 500) -> list:
    """Ambil N data terakhir dari realtime_results, urut terlama→terbaru
    (untuk grafik timeline). Return list of dict, [] bila gagal/kosong."""
    return _get_rows("realtime_results", limit)


# ─────────────────────────────────────────────────────────
# History (tanpa rolling window — simpan semua)
# ─────────────────────────────────────────────────────────
def insert_history(data: dict) -> bool:
    """Sama seperti insert_realtime_result tapi ke tabel history,
    TANPA rolling window (simpan semua). Return True jika sukses."""
    return _insert_row("history", data, rolling_limit=0)


def get_history(limit: int = 1000) -> list:
    """Ambil N data terakhir dari tabel history, urut terlama→terbaru.
    Return list of dict, [] bila gagal/kosong."""
    return _get_rows("history", limit)


def clear_history() -> bool:
    """TRUNCATE TABLE history. Return True jika sukses, False jika gagal."""
    conn = get_connection()
    if conn is None:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE history")
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[db_client] Clear history gagal: {e}")
        if conn:
            conn.close()
        return False


# ─────────────────────────────────────────────────────────
# Utilitas: buat tabel (opsional — bila belum dibuat via SQL editor)
# ─────────────────────────────────────────────────────────
def init_tables() -> bool:
    """Buat tabel realtime_results & history bila belum ada (CREATE IF NOT
    EXISTS). Jalankan sekali setelah SUPABASE_DB_URL terisi. Graceful."""
    conn = get_connection()
    if conn is None:
        return False
    ddl = """
    CREATE TABLE IF NOT EXISTS {t} (
        id              BIGSERIAL PRIMARY KEY,
        timestamp       TEXT,
        risk_score      DOUBLE PRECISION,
        risk_level      TEXT,
        dominant_fault  TEXT,
        anomaly_detected BOOLEAN,
        explanation     TEXT,
        recommendations JSONB,
        sensor_snapshot JSONB,
        created_at      TIMESTAMPTZ DEFAULT now()
    );
    """
    try:
        with conn.cursor() as cur:
            cur.execute(ddl.format(t="realtime_results"))
            cur.execute(ddl.format(t="history"))
        conn.commit()
        conn.close()
        print("[db_client] Tabel realtime_results & history siap.")
        return True
    except Exception as e:
        print(f"[db_client] init_tables gagal: {e}")
        if conn:
            conn.close()
        return False
