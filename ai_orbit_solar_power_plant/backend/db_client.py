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
        action_taken    TEXT,     -- Ethical Guardian: aksi otonom yang dieksekusi
        action_status   TEXT,     -- none|executed|pending_confirmation|blocked
        guardian_reason TEXT,     -- alasan keputusan guardian (audit)
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
        action_taken    TEXT,
        action_status   TEXT,
        guardian_reason TEXT,
        created_at      TIMESTAMPTZ DEFAULT now()
    );

Kolom action_taken/action_status/guardian_reason — serta escalation_level &
final_outcome (Eskalasi Bertingkat / Opsi C) — DITAMBAHKAN belakangan dan bersifat
NULLABLE + backward-compatible: bila tabel lama belum punya kolom ini, insert/get
otomatis fallback ke skema 8-kolom lama. Jalankan init_tables() untuk migrasi
otomatis (ALTER TABLE ADD COLUMN IF NOT EXISTS), atau lihat SQL ALTER manual:

    ALTER TABLE realtime_results ADD COLUMN IF NOT EXISTS escalation_level INTEGER;
    ALTER TABLE realtime_results ADD COLUMN IF NOT EXISTS final_outcome TEXT;
    ALTER TABLE history          ADD COLUMN IF NOT EXISTS escalation_level INTEGER;
    ALTER TABLE history          ADD COLUMN IF NOT EXISTS final_outcome TEXT;
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

# Kolom Ethical Guardian (ditambahkan belakangan). Semua nullable & backward-
# compatible: insert/get mencoba menyertakannya, tapi fallback ke skema lama
# bila tabel belum dimigrasi (lihat _insert_row / _get_rows / init_tables).
_BASE_INSERT_COLS = (
    "timestamp", "risk_score", "risk_level", "dominant_fault",
    "anomaly_detected", "explanation", "recommendations", "sensor_snapshot",
)
# escalation_level & final_outcome ditambahkan untuk Eskalasi Bertingkat (Opsi C).
_EXTRA_COLS = (
    "action_taken", "action_status", "guardian_reason",
    "escalation_level", "final_outcome",
)
# Tipe SQL per kolom guardian (default TEXT); dipakai saat migrasi ADD COLUMN.
_EXTRA_COL_TYPES = {"escalation_level": "INTEGER"}


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
def _row_values(data: dict, cols: tuple) -> tuple:
    """Susun tuple nilai sesuai urutan `cols` (JSONB di-dump, sisanya .get())."""
    vals = []
    for c in cols:
        if c == "recommendations":
            vals.append(json.dumps(data.get("recommendations", [])))
        elif c == "sensor_snapshot":
            vals.append(json.dumps(data.get("sensor_snapshot", {})))
        elif c == "explanation":
            vals.append(data.get("explanation", ""))
        elif c == "action_status":
            vals.append(data.get("action_status", "none"))
        else:
            vals.append(data.get(c))
    return tuple(vals)


def _do_insert(conn, table: str, data: dict, cols: tuple, rolling_limit: int) -> None:
    """Eksekusi INSERT (+ rolling window) untuk himpunan kolom `cols`.

    Tidak menangani error — caller-lah yang membungkus try/except agar bisa
    fallback ke skema kolom lama bila kolom baru belum ada di tabel.
    """
    placeholders = ", ".join(["%s"] * len(cols))
    col_list = ", ".join(cols)
    with conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})",
            _row_values(data, cols),
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


def _insert_row(table: str, data: dict, rolling_limit: int = 0) -> bool:
    """Insert 1 baris ke `table`. Bila rolling_limit > 0, sisakan hanya
    `rolling_limit` baris terbaru (hapus sisanya). Graceful (return bool).

    Backward-compatible: coba insert DENGAN kolom Ethical Guardian; bila tabel
    belum dimigrasi (UndefinedColumn), fallback ke skema 8-kolom lama pada
    koneksi baru — penyimpanan tetap jalan tanpa migrasi.
    """
    conn = get_connection()
    if conn is None:
        return False

    full_cols = _BASE_INSERT_COLS + _EXTRA_COLS
    try:
        _do_insert(conn, table, data, full_cols, rolling_limit)
        conn.close()
        return True
    except Exception as e:
        # Kemungkinan kolom baru belum ada. Transaksi sudah abort → tutup & ulang
        # pada koneksi baru dengan skema lama (graceful fallback).
        print(f"[db_client] Insert {table} dengan kolom guardian gagal ({e}); "
              f"fallback ke skema lama.")
        try:
            conn.close()
        except Exception:
            pass

    conn = get_connection()
    if conn is None:
        return False
    try:
        _do_insert(conn, table, data, _BASE_INSERT_COLS, rolling_limit)
        conn.close()
        return True
    except Exception as e:
        print(f"[db_client] Insert {table} gagal: {e}")
        if conn:
            conn.close()
        return False


def _do_select(conn, table: str, cols: tuple, limit: int) -> list:
    """Eksekusi SELECT untuk himpunan kolom `cols`. Tidak menangani error."""
    col_list = ", ".join(cols)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"""
            SELECT {col_list}
            FROM {table}
            ORDER BY created_at DESC LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()
    return list(reversed([dict(r) for r in rows]))  # terlama dulu


def _get_rows(table: str, limit: int) -> list:
    """Ambil `limit` baris terbaru dari `table`, urut terlama→terbaru.
    Graceful (return [] bila gagal/kosong).

    Backward-compatible: coba SELECT termasuk kolom Ethical Guardian; bila tabel
    belum dimigrasi, fallback ke skema lama (caller membaca via .get()).
    """
    conn = get_connection()
    if conn is None:
        return []

    full_cols = _BASE_INSERT_COLS + _EXTRA_COLS
    try:
        rows = _do_select(conn, table, full_cols, limit)
        conn.close()
        return rows
    except Exception as e:
        print(f"[db_client] Get {table} dengan kolom guardian gagal ({e}); "
              f"fallback ke skema lama.")
        try:
            conn.close()
        except Exception:
            pass

    conn = get_connection()
    if conn is None:
        return []
    try:
        rows = _do_select(conn, table, _BASE_INSERT_COLS, limit)
        conn.close()
        return rows
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
        action_taken    TEXT,
        action_status   TEXT,
        guardian_reason TEXT,
        escalation_level INTEGER,
        final_outcome   TEXT,
        created_at      TIMESTAMPTZ DEFAULT now()
    );
    """
    try:
        with conn.cursor() as cur:
            for t in ("realtime_results", "history"):
                cur.execute(ddl.format(t=t))
                # Migrasi tabel LAMA yang sudah ada tapi belum punya kolom guardian
                # (CREATE IF NOT EXISTS tidak menambah kolom ke tabel eksisting).
                for col in _EXTRA_COLS:
                    col_type = _EXTRA_COL_TYPES.get(col, "TEXT")
                    cur.execute(
                        f"ALTER TABLE {t} ADD COLUMN IF NOT EXISTS {col} {col_type}"
                    )
        conn.commit()
        conn.close()
        print("[db_client] Tabel realtime_results & history siap (kolom guardian termigrasi).")
        return True
    except Exception as e:
        print(f"[db_client] init_tables gagal: {e}")
        if conn:
            conn.close()
        return False
