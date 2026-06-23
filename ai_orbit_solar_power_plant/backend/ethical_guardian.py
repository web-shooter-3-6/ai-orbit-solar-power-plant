"""
ai_orbit_solar_power_plant/backend/ethical_guardian.py
────────────────────────────────────────────────────────────
Ethical Guardian — lapisan kendali etis (guardrail) untuk Agen AI Otonom.

FILOSOFI DESAIN
═══════════════
Modul ini sengaja dibuat **rule-based (BUKAN machine learning)**. Sebuah
guardrail etis HARUS bersifat:
  • Deterministik  — input yang sama selalu menghasilkan keputusan yang sama,
                     tidak ada keacakan / drift seperti pada model statistik.
  • Auditable      — setiap keputusan dapat ditelusuri ke aturan eksplisit yang
                     tertulis di kode (bisa dibaca auditor non-teknis), dan
                     dicatat ke audit log permanen.
  • Konservatif    — bila ragu (action_type tak dikenal, error, dsb), default
                     yang dipilih adalah yang PALING AMAN (memblokir / minta
                     konfirmasi manusia), bukan yang paling agresif.

Guardian ini DUDUK DI ATAS pipeline deteksi anomali yang sudah ada. Ia tidak
mengubah skor risiko atau prediksi model — ia hanya MEMUTUSKAN apakah sebuah
aksi otonom yang diusulkan (throttle / isolate / shutdown) boleh dieksekusi
oleh AI sendiri, perlu konfirmasi manusia, atau harus diblokir.

Prinsip etis inti: **"Human-in-command, not just human-in-the-loop."**
Manusia tetap memegang kendali tertinggi; AI hanya boleh bertindak otonom di
ruang aksi yang reversibel & berbukti kuat, dan harus menyerahkan keputusan ke
manusia begitu aksi menjadi tak-terpulihkan atau bukti lemah.

Semua I/O file (audit log) ditangani graceful — kegagalan menulis log TIDAK
boleh meng-crash pipeline monitoring.
"""

import os
import json
from datetime import datetime


# ─────────────────────────────────────────────────────────
# Konstanta kebijakan (lookup table — sumber kebenaran tunggal)
# ─────────────────────────────────────────────────────────

# Ambang confidence minimum per jenis aksi.
#
# REASONING (kenapa nilainya begini):
# Confidence di sini = risk_score agregat dari ensemble model (0.0–1.0), yaitu
# seberapa yakin sistem bahwa kondisi anomali ini nyata. Semakin DISRUPTIF dan
# semakin SULIT DIPULIHKAN sebuah aksi, semakin TINGGI bukti yang kita wajibkan
# sebelum AI boleh bertindak SENDIRI. Ini menyeimbangkan dua jenis kesalahan:
#   - False positive yang memicu aksi  → kerugian operasional (downtime, energi).
#   - False negative yang menahan aksi → risiko kerusakan fisik.
# Aksi ringan (throttle) memakai ambang rendah karena murah & mudah dibatalkan;
# aksi berat (shutdown) memakai ambang tinggi karena salah-tindak sangat mahal.
CONFIDENCE_THRESHOLDS = {
    "throttle": 0.60,   # reversibel, dampak kecil → bukti cukup di 0.60
    "isolate": 0.80,    # semi-reversibel, memutus komponen → butuh bukti kuat
    "shutdown": 0.90,   # irreversibel, mematikan sistem → butuh bukti hampir pasti
}

# Default konservatif untuk action_type yang tidak dikenal: perlakukan seketat
# aksi paling berat. "Fail safe, not fail open."
_DEFAULT_CONFIDENCE_THRESHOLD = 0.90

# Klasifikasi reversibilitas tiap aksi.
#
# REASONING: reversibilitas adalah sumbu etis utama. "Reversible" artinya efek
# aksi bisa dibatalkan tanpa kerugian permanen; "irreversible" artinya begitu
# dieksekusi tidak ada jalan kembali tanpa biaya/risiko besar. Sumbu inilah yang
# menentukan apakah AI boleh bertindak sendiri atau wajib menyerahkan ke manusia.
REVERSIBILITY = {
    "throttle": "reversible",        # set ulang persentase daya → pulih seketika
    "isolate": "semi_reversible",    # komponen diputus, bisa disambung lagi via prosedur
    "shutdown": "irreversible",      # mematikan total → restart mahal/berisiko, butuh manusia
}

# Default konservatif: aksi tak dikenal dianggap irreversibel (paling hati-hati).
_DEFAULT_REVERSIBILITY = "irreversible"

# Jendela waktu (detik) yang diberikan ke operator manusia untuk mengonfirmasi
# aksi irreversibel sebelum dianggap kedaluwarsa. Cukup untuk keputusan sadar,
# tapi tetap mendesak agar tidak menunda penanganan kondisi kritis.
CONFIRMATION_WINDOW_SECONDS = 30

# ─────────────────────────────────────────────────────────
# Eskalasi bertingkat (Opsi C) untuk timeout konfirmasi manusia
# ─────────────────────────────────────────────────────────
# Setelah window konfirmasi pertama habis tanpa respon, sistem TIDAK diam-diam
# membatalkan aksi. Ia naik level demi level (tiap ESCALATION_WINDOW_SECONDS),
# menghubungi kontak cadangan berikutnya, hingga ESCALATION_MAX_LEVEL. Bila tetap
# tak ada respon setelah ESCALATION_TOTAL_SECONDS, aksi dieksekusi otomatis
# (fallback Opsi B) sebagai last resort demi keselamatan sistem.
#
# REASONING ETIS: untuk kondisi kritis irreversibel, KEDIAMAN bukan pilihan aman.
# Bila manusia tak bisa dihubungi tepat waktu, menahan aksi selamanya justru bisa
# membahayakan (mis. baterai overheating yang dibiarkan). Eskalasi memberi manusia
# kesempatan maksimal untuk mengambil alih, tetapi tetap punya jaring pengaman.
ESCALATION_WINDOW_SECONDS = 30                 # durasi tiap window eskalasi
ESCALATION_MAX_LEVEL = 3                        # setelah level 3 → auto-execute
ESCALATION_TOTAL_SECONDS = ESCALATION_WINDOW_SECONDS * ESCALATION_MAX_LEVEL  # 90

# Lokasi audit log permanen (list of dict JSON). Diletakkan di backend/data/
# bersama artefak lain (normal_means.json) supaya ikut ter-deploy.
_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
AUDIT_LOG_PATH = os.path.join(_BACKEND_DIR, "data", "ethical_audit_log.json")

# Config kecil & persisten untuk toggle Safety Interlock (Maintenance Mode).
# Disimpan ke file (bukan sekadar env var dalam-proses) supaya bisa dibaca
# LINTAS-PROSES: dashboard Reflex menulis, worker realtime_simulator (proses
# terpisah) ikut membacanya saat memanggil check_safety_interlock(). Pola ini
# meniru alert/bot_config.json yang sudah dipakai TelegramAlert.
GUARDIAN_CONFIG_PATH = os.path.join(_BACKEND_DIR, "data", "guardian_config.json")

# Nilai env var yang dianggap "aktif/True" (case-insensitive).
_TRUTHY = {"1", "true", "yes", "on", "active"}


# ─────────────────────────────────────────────────────────
# Helper format teks (untuk reason yang deskriptif & dapat diaudit)
# ─────────────────────────────────────────────────────────
def _pct(value) -> str:
    """Format nilai 0.0–1.0 menjadi persen ringkas, mis. 0.95 → '95%'."""
    try:
        return f"{float(value) * 100:.0f}%"
    except (TypeError, ValueError):
        return "?"


def _fault_label(fault) -> str:
    """Nama fault yang aman untuk ditampilkan. Kosong/None → label generik.

    REASONING: reason wajib SELALU menyebut fault pemicu agar auditor tahu
    KENAPA sebuah aksi dipilih. Bila fault tak diketahui (mis. pemanggilan lama
    tanpa konteks), kita tetap beri label eksplisit alih-alih string kosong.
    """
    f = str(fault).strip() if fault else ""
    return f if f else "Anomali tak teridentifikasi"


# ─────────────────────────────────────────────────────────
# a) Safety interlock (prioritas etis TERTINGGI)
# ─────────────────────────────────────────────────────────
def check_safety_interlock(context: dict) -> bool:
    """Cek apakah interlock keselamatan manusia AKTIF (aksi harus diblokir).

    Return True  → interlock AKTIF  → AI DILARANG mengambil aksi fisik apa pun.
    Return False → interlock nonaktif → aksi boleh lanjut ke cek berikutnya.

    Sumber sinyal (cukup salah satu bernilai truthy):
      • context["maintenance_mode"]    — sistem sedang dalam mode perawatan.
      • context["technician_on_site"]  — ada teknisi di lokasi perangkat.
      • config guardian_config.json    — toggle manual dari dashboard (persisten,
                                         lintas-proses) lewat set_interlock_state().
      • env SAFETY_INTERLOCK_ACTIVE    — toggle manual global (untuk demo/operasi),
                                         truthy: "1"/"true"/"yes"/"on"/"active".

    REASONING ETIS (kenapa ini cek PERTAMA & meng-override segalanya):
    Nyawa & keselamatan manusia berada di atas keandalan/uptime sistem. Bila ada
    kemungkinan teknisi sedang menyentuh/menyervis komponen, aksi otonom seperti
    memutus daya atau mengisolasi rangkaian dapat membahayakan. Maka interlock
    ini adalah gerbang mutlak: berapa pun tingginya confidence model, aksi tetap
    diblokir selama interlock aktif. Ini menegakkan prinsip "human safety first"
    dan memberi manusia kontrol fisik tanpa-syarat atas mesin.
    """
    if context:
        if context.get("maintenance_mode") or context.get("technician_on_site"):
            return True
    if _read_interlock_config():
        return True
    env_val = os.getenv("SAFETY_INTERLOCK_ACTIVE", "").strip().lower()
    return env_val in _TRUTHY


# ─────────────────────────────────────────────────────────
# a.1) Persistensi toggle interlock (config file lintas-proses)
# ─────────────────────────────────────────────────────────
def _read_interlock_config() -> bool:
    """Baca flag safety_interlock_active dari guardian_config.json.

    Graceful: file tidak ada / rusak → return False (interlock nonaktif).
    """
    try:
        with open(GUARDIAN_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return bool(data.get("safety_interlock_active", False))
    except (FileNotFoundError, json.JSONDecodeError):
        return False
    except Exception:  # pragma: no cover
        return False


def get_interlock_state() -> bool:
    """Status interlock manual saat ini (dari config file). Untuk dashboard."""
    return _read_interlock_config()


def set_interlock_state(active: bool) -> bool:
    """Set & PERSIST toggle interlock (Maintenance Mode) ke guardian_config.json.

    Dibaca ulang oleh check_safety_interlock() — termasuk dari proses lain
    (worker realtime). Return True bila tertulis. Graceful pada error I/O.

    REASONING: toggle ini bukan UI dummy — ia benar-benar mengubah keputusan
    backend. Operator (manusia) memegang sakelar fisik untuk menonaktifkan
    seluruh aksi otonom selama perawatan, konsisten dengan prinsip human-in-command.
    """
    try:
        os.makedirs(os.path.dirname(GUARDIAN_CONFIG_PATH), exist_ok=True)
        with open(GUARDIAN_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump({"safety_interlock_active": bool(active)}, f,
                      ensure_ascii=False, indent=2)
        return True
    except Exception as e:  # pragma: no cover
        print(f"[ethical_guardian] ! Gagal menulis guardian_config: {e}")
        return False


# ─────────────────────────────────────────────────────────
# b) Ambang confidence per jenis aksi
# ─────────────────────────────────────────────────────────
def check_confidence_threshold(confidence: float, action_type: str) -> bool:
    """Cek apakah `confidence` memenuhi ambang minimum untuk `action_type`.

    Return True  → confidence cukup tinggi → aksi memenuhi syarat bukti.
    Return False → confidence di bawah ambang → aksi tidak boleh dieksekusi otonom.

    Ambang (lihat CONFIDENCE_THRESHOLDS):
      throttle 0.60 | isolate 0.80 | shutdown 0.90.
    action_type tak dikenal → ambang default konservatif 0.90.

    REASONING ETIS:
    Aksi otonom hanya etis bila didukung bukti yang sebanding dengan dampaknya.
    Skala ambang naik seiring tingkat disrupsi & ketidak-pulihan aksi: makin
    besar potensi kerugian dari salah-tindak, makin tinggi keyakinan yang kita
    syaratkan. Dengan ambang eksplisit & tetap, keputusan dapat diaudit ("aksi
    diblokir karena confidence 0.72 < 0.80") alih-alih bergantung pada intuisi.
    """
    try:
        conf = float(confidence)
    except (TypeError, ValueError):
        # Confidence tak valid → anggap tidak memenuhi (fail safe).
        return False
    threshold = CONFIDENCE_THRESHOLDS.get(action_type, _DEFAULT_CONFIDENCE_THRESHOLD)
    return conf >= threshold


# ─────────────────────────────────────────────────────────
# c) Klasifikasi reversibilitas
# ─────────────────────────────────────────────────────────
def classify_reversibility(action_type: str) -> str:
    """Kembalikan kelas reversibilitas aksi: 'reversible' | 'semi_reversible'
    | 'irreversible'.

    action_type tak dikenal → 'irreversible' (default paling hati-hati).

    REASONING ETIS:
    Reversibilitas menentukan SIAPA yang berhak memutuskan. Aksi reversibel boleh
    diambil AI sendiri karena kesalahan mudah dipulihkan. Aksi irreversibel
    menutup pilihan masa depan secara permanen — keputusan moral seperti itu
    harus tetap di tangan manusia. Mengklasifikasikan aksi tak dikenal sebagai
    irreversibel memastikan sistem selalu memilih sisi paling aman saat ragu.
    """
    return REVERSIBILITY.get(action_type, _DEFAULT_REVERSIBILITY)


# ─────────────────────────────────────────────────────────
# d) Audit log (tulis & baca)
# ─────────────────────────────────────────────────────────
def log_decision(action_type, severity, confidence, verdict, reason, timestamp,
                 fault_detected=None, escalation_level=0, final_outcome=None) -> None:
    """Catat satu keputusan guardian ke audit log permanen (append).

    Ditulis sebagai list of dict di AUDIT_LOG_PATH (JSON). Dipanggil untuk
    SEMUA verdict (termasuk BLOCKED) agar jejak keputusan etis lengkap & dapat
    diaudit. Graceful: kegagalan I/O hanya dicetak, tidak meng-crash pipeline.

    `fault_detected` (opsional) = nama fault dominan yang memicu aksi. Disimpan
    eksplisit supaya auditor langsung tahu KONDISI yang mendasari keputusan
    (transparansi), bukan hanya jenis aksi. Nullable & backward-compatible:
    entri lama tanpa field ini tetap valid.

    `escalation_level` (int, default 0) & `final_outcome` (str|None, default None)
    mendukung eskalasi bertingkat (Opsi C). Saat entri pertama kali ditulis untuk
    REQUIRE_HUMAN_CONFIRMATION, keduanya bernilai default; nilai diperbarui
    in-place via _update_entry_by_timestamp() saat eskalasi naik / aksi diresolusi.
    Backward-compatible: entri lama tanpa field ini tetap valid (pembaca .get()).

    REASONING ETIS:
    Akuntabilitas menuntut jejak yang tak bisa disangkal. Mencatat juga keputusan
    BLOCKED sama pentingnya dengan EXECUTE — auditor perlu tahu kapan AI MENAHAN
    diri, bukan hanya kapan ia bertindak. Log inilah bukti bahwa kendali etis
    benar-benar berjalan, dan jadi sumber data untuk evaluasi/dokumentasi ilmiah.
    """
    entry = {
        "action_type": action_type,
        # Fault pemicu disimpan tepat di sebelah action_type agar pasangan
        # "kondisi → aksi" terbaca jelas saat audit log dibuka mentah.
        "fault_detected": fault_detected,
        "severity": severity,
        "confidence": confidence,
        # Reversibilitas dipersist langsung (bukan dihitung ulang saat baca)
        # supaya file audit self-contained: auditor yang membaca JSON mentah
        # tetap melihat dasar etis keputusan tanpa perlu logika tambahan.
        "reversibility": classify_reversibility(action_type),
        "verdict": verdict,
        "reason": reason,
        "timestamp": timestamp,
        # Eskalasi bertingkat (Opsi C): level eskalasi saat ini & hasil akhir.
        "escalation_level": escalation_level,
        "final_outcome": final_outcome,
    }
    try:
        os.makedirs(os.path.dirname(AUDIT_LOG_PATH), exist_ok=True)
        log = get_audit_log()  # baca yang sudah ada (graceful → [])
        log.append(entry)
        with open(AUDIT_LOG_PATH, "w", encoding="utf-8") as f:
            json.dump(log, f, ensure_ascii=False, indent=2)
    except Exception as e:  # pragma: no cover - logging tak boleh crash pipeline
        print(f"[ethical_guardian] ! Gagal menulis audit log: {e}")


def get_audit_log() -> list:
    """Baca seluruh audit log dan kembalikan sebagai list of dict.

    Return [] bila file belum ada / kosong / rusak. Disediakan terpisah supaya
    dashboard atau laporan dapat memanggilnya langsung tanpa menyentuh file.
    """
    try:
        if not os.path.exists(AUDIT_LOG_PATH):
            return []
        with open(AUDIT_LOG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    except Exception as e:  # pragma: no cover
        print(f"[ethical_guardian] ! Gagal membaca audit log: {e}")
        return []


def _update_entry_by_timestamp(timestamp, **fields) -> bool:
    """Perbarui IN-PLACE field tertentu pada entri pending di audit log.

    Mencari entri REQUIRE_HUMAN_CONFIRMATION TERAKHIR dengan `timestamp` cocok,
    lalu menimpa field yang diberikan (mis. escalation_level, final_outcome) dan
    menulis ulang file. Dipakai eskalasi bertingkat (Opsi C) supaya satu peristiwa
    pending punya SATU baris kanonik yang statusnya berkembang — bukan menambah
    baris baru tiap transisi (yang akan mengaburkan jejak).

    Return True bila ada entri yang diperbarui & tertulis. Graceful pada error I/O.
    """
    try:
        log = get_audit_log()
        target_idx = None
        for i, e in enumerate(log):
            if (e.get("timestamp") == timestamp
                    and e.get("verdict") == "REQUIRE_HUMAN_CONFIRMATION"):
                target_idx = i  # ambil yang paling akhir cocok
        if target_idx is None:
            return False
        log[target_idx].update(fields)
        os.makedirs(os.path.dirname(AUDIT_LOG_PATH), exist_ok=True)
        with open(AUDIT_LOG_PATH, "w", encoding="utf-8") as f:
            json.dump(log, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:  # pragma: no cover - update log tak boleh crash pipeline
        print(f"[ethical_guardian] ! Gagal update entri audit log: {e}")
        return False


# ─────────────────────────────────────────────────────────
# e) Orchestrator utama
# ─────────────────────────────────────────────────────────
def evaluate_action(action_type: str, severity: str, confidence: float,
                    context: dict, fault_detected: str = None) -> dict:
    """Evaluasi apakah sebuah aksi otonom boleh dieksekusi, sesuai urutan etis.

    `fault_detected` (opsional) = nama fault dominan pemicu aksi. Dipakai untuk
    menyusun `reason` yang deskriptif (SELALU menyebut fault & confidence) dan
    ikut dipersist ke audit log demi transparansi. Opsional agar pemanggil lama
    (4 argumen) tetap kompatibel.

    URUTAN KEPUTUSAN (precedence — yang lebih atas meng-override yang bawah):
      1. Safety interlock aktif        → BLOCKED
         (keselamatan manusia mutlak di atas segalanya).
      2. Confidence di bawah ambang    → BLOCKED
         (bukti tak cukup untuk bertindak otonom).
      3. Aksi irreversibel             → REQUIRE_HUMAN_CONFIRMATION
         (keputusan permanen wajib di tangan manusia; sertakan jendela waktu).
      4. Lolos semua cek               → EXECUTE
         (aksi reversibel/semi-reversibel dengan bukti cukup & tanpa interlock).

    Memanggil log_decision() SEBELUM setiap return (semua verdict tercatat).

    Return dict:
      {
        "verdict": "BLOCKED" | "REQUIRE_HUMAN_CONFIRMATION" | "EXECUTE",
        "reason": str,
        "reversibility": str,
        "confirmation_window_seconds": int | None,
        "timestamp": ISO-8601 str,
      }
    """
    timestamp = datetime.now().isoformat(timespec="seconds")
    reversibility = classify_reversibility(action_type)
    confirmation_window = None

    # Komponen reason yang dipakai ulang di semua cabang: SELALU sebut fault
    # pemicu + confidence supaya keputusan transparan & mudah diaudit.
    fault_label = _fault_label(fault_detected)
    conf_pct = _pct(confidence)

    # 1) Safety interlock — gerbang mutlak.
    if check_safety_interlock(context):
        verdict = "BLOCKED"
        reason = (f"{fault_label} terdeteksi, aksi {action_type} DIBLOKIR — "
                  f"mode keselamatan manusia (maintenance) sedang aktif")
    # 2) Ambang confidence.
    elif not check_confidence_threshold(confidence, action_type):
        verdict = "BLOCKED"
        threshold = CONFIDENCE_THRESHOLDS.get(action_type,
                                              _DEFAULT_CONFIDENCE_THRESHOLD)
        reason = (f"{fault_label} terdeteksi namun confidence {conf_pct} di bawah "
                  f"ambang minimum {_pct(threshold)} untuk aksi {action_type} — "
                  f"eskalasi ke pengawasan manual")
    # 3) Aksi irreversibel → wajib konfirmasi manusia.
    elif reversibility == "irreversible":
        verdict = "REQUIRE_HUMAN_CONFIRMATION"
        reason = (f"{fault_label} terdeteksi (confidence {conf_pct}) — aksi "
                  f"{action_type} tak terpulihkan (irreversibel), memerlukan "
                  f"konfirmasi manusia sesuai kebijakan keselamatan "
                  f"(window {CONFIRMATION_WINDOW_SECONDS} detik)")
        confirmation_window = CONFIRMATION_WINDOW_SECONDS
    # 4) Lolos semua → eksekusi.
    else:
        verdict = "EXECUTE"
        reason = (f"{fault_label} terdeteksi (confidence {conf_pct}), aksi "
                  f"{action_type} dieksekusi otonom — seluruh pemeriksaan etis "
                  f"terpenuhi")

    # Catat ke audit log untuk SEMUA verdict (termasuk BLOCKED).
    log_decision(action_type, severity, confidence, verdict, reason, timestamp,
                 fault_detected=fault_detected)

    return {
        "verdict": verdict,
        "reason": reason,
        "reversibility": reversibility,
        "confirmation_window_seconds": confirmation_window,
        "timestamp": timestamp,
    }


# ─────────────────────────────────────────────────────────
# Resolusi manusia atas aksi pending (konfirmasi / pembatalan)
# ─────────────────────────────────────────────────────────
def record_human_resolution(action_type: str, severity: str, confidence: float,
                            confirmed: bool, fault_detected: str = None,
                            pending_timestamp: str = None,
                            escalation_level: int = 0) -> dict:
    """Catat keputusan MANUSIA atas aksi yang menunggu konfirmasi.

    Dipanggil saat operator menekan "Konfirmasi & Eksekusi" (confirmed=True) atau
    "Batalkan" (confirmed=False) pada banner pending di dashboard. `fault_detected`
    (opsional) ikut dicatat & disebut di reason agar jejak audit menjelaskan
    kondisi yang mendasari aksi.

    `pending_timestamp` (opsional) = timestamp entri REQUIRE_HUMAN_CONFIRMATION
    asal. Bila diberikan, entri pending itu ditandai final_outcome="human_confirmed"
    / "human_cancelled" + escalation_level saat resolusi, sehingga eskalasi
    bertingkat (Opsi C) berhenti & jejaknya kanonik. Tetap meng-append entri
    EXECUTE/BLOCKED demi kompatibilitas mundur (perilaku lama dipertahankan).

    REASONING ETIS: untuk aksi irreversibel, keputusan akhir ada di tangan
    manusia. Resolusi ini ikut tercatat ke audit log agar jejak akuntabilitas
    lengkap: siapa pun bisa menelusuri bahwa aksi dieksekusi/dibatalkan atas
    persetujuan manusia, bukan secara otonom oleh AI.
    """
    fault_label = _fault_label(fault_detected)
    verdict = "EXECUTE" if confirmed else "BLOCKED"
    reason = (
        f"{fault_label}: aksi {action_type} DIKONFIRMASI & dieksekusi oleh manusia"
        if confirmed else
        f"{fault_label}: aksi {action_type} DIBATALKAN oleh manusia"
    )
    timestamp = datetime.now().isoformat(timespec="seconds")
    log_decision(action_type, severity, confidence, verdict, reason, timestamp,
                 fault_detected=fault_detected)
    # Tandai entri pending asli agar eskalasi berhenti & outcome kanonik tercatat.
    if pending_timestamp:
        _update_entry_by_timestamp(
            pending_timestamp,
            escalation_level=escalation_level,
            final_outcome=("human_confirmed" if confirmed else "human_cancelled"),
        )
    return {"verdict": verdict, "reason": reason, "timestamp": timestamp}


def auto_execute_after_timeout(action_type: str, severity: str, confidence: float,
                               timestamp: str, fault_detected: str = None) -> dict:
    """Eksekusi otomatis aksi pending setelah SELURUH window eskalasi habis.

    Fallback last resort (Opsi B) saat tak ada respon manusia dari semua kontak
    dalam ESCALATION_TOTAL_SECONDS (90 detik). Entri pending asli (`timestamp`)
    diperbarui IN-PLACE: verdict TETAP "REQUIRE_HUMAN_CONFIRMATION" (jejak bahwa
    aksi ini SEMESTINYA minta konfirmasi), namun ditambah escalation_level=3 dan
    final_outcome="auto_executed_after_timeout". Tidak meng-append baris baru.

    Catatan implementasi: tidak ada aktuator fisik di codebase ini, jadi
    "eksekusi" = pencatatan keputusan + notifikasi (lihat agent_bridge /
    telegram_alert). Sejalan dengan jalur EXECUTE yang sudah ada (component_status
    bersifat simulasi).

    REASONING ETIS: membiarkan kondisi kritis irreversibel menggantung selamanya
    karena manusia tak terjangkau bisa lebih berbahaya daripada bertindak. Setelah
    upaya eskalasi maksimal terdokumentasi, sistem mengambil tindakan demi
    keselamatan — dan mencatatnya gamblang sebagai aksi OTOMATIS, bukan persetujuan
    manusia, agar akuntabilitas tetap jujur.
    """
    fault_label = _fault_label(fault_detected)
    updated = _update_entry_by_timestamp(
        timestamp,
        escalation_level=ESCALATION_MAX_LEVEL,
        final_outcome="auto_executed_after_timeout",
    )
    reason = (
        f"{fault_label}: aksi {action_type} DIEKSEKUSI OTOMATIS — tidak ada respon "
        f"dari semua kontak dalam {ESCALATION_TOTAL_SECONDS} detik (eskalasi habis)"
    )
    return {
        "verdict": "REQUIRE_HUMAN_CONFIRMATION",
        "final_outcome": "auto_executed_after_timeout",
        "escalation_level": ESCALATION_MAX_LEVEL,
        "reason": reason,
        "updated": updated,
        "timestamp": timestamp,
    }
