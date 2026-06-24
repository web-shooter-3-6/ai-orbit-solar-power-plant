"""
ai_orbit_solar_power_plant/backend/agent_bridge.py
────────────────────────────────────────────────────────────
Jembatan (bridge) antara aplikasi Reflex dengan logic agent yang
sudah ada di root repo (agent/, alert/, models/).

Tujuan:
  - Menambahkan path root repo ke sys.path supaya bisa import paket
    agent/, alert/, models/ dari dalam package Reflex.
  - Memuat model AI hanya SEKALI (pola singleton) — pemuatan model
    berat (torch/sklearn) tidak diulang tiap pemanggilan.
  - Menyediakan fungsi wrapper sederhana yang langsung dipakai State.

Semua I/O file ditangani dengan graceful fallback (return [] / {} /
nilai aman) supaya aplikasi TIDAK crash walau file/model belum ada.
"""

import os
import sys

# ─────────────────────────────────────────────────────────
# COPY DEPLOY (Reflex Cloud):
# Semua dependency (agent/, alert/, models_output/, data/) sudah DI-COPY
# ke dalam folder backend/ ini supaya ikut ter-upload oleh `reflex deploy`
# (yang hanya mengunggah isi folder app Reflex). Tidak perlu lagi menelusuri
# root repo / mengutak-atik sys.path — cukup pakai import relatif & path lokal.
# ─────────────────────────────────────────────────────────
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))

# Path file rata-rata fitur kelas Normal (untuk get_feature_means).
# Dulu dihitung on-the-fly dari Condition_Monitoring_Dataset.csv (21MB) yang
# bikin backend.zip > limit Reflex Cloud. Kini di-precompute ke JSON kecil
# (~2KB) supaya deploy ringan. Storage Realtime Feed & History tetap di
# Supabase PostgreSQL (lihat db_client).
MEANS_PATH = os.path.join(BACKEND_DIR, "data", "normal_means.json")

# Klien DB Supabase (import aman: bila modul/psycopg2 bermasalah, set None
# sehingga semua operasi DB graceful — aplikasi tetap jalan mode lokal).
try:
    from . import db_client
except Exception as e:  # pragma: no cover
    print(f"[agent_bridge] ! db_client tidak tersedia ({e}), storage DB dimatikan")
    db_client = None

# Ethical Guardian (import aman: bila modul bermasalah, set None sehingga
# pipeline tetap jalan TANPA aksi otonom — fail safe, hanya deteksi & notifikasi).
try:
    from . import ethical_guardian
except Exception as e:  # pragma: no cover
    print(f"[agent_bridge] ! ethical_guardian tidak tersedia ({e}), aksi otonom dimatikan")
    ethical_guardian = None

# Tiered Response: pemetaan severity → aksi otonom yang diusulkan.
# LOW/MEDIUM tidak punya aksi fisik (None): LOW hanya di-log, MEDIUM hanya
# notifikasi. HIGH → throttle (reversibel), CRITICAL → isolate (semi-reversibel),
# KECUALI fault katastrofik dengan keyakinan sangat tinggi → shutdown (irreversibel,
# wajib konfirmasi manusia). Setiap aksi WAJIB lolos Ethical Guardian dulu.

# Fault yang risikonya katastrofik (thermal runaway baterai / kegagalan inverter
# yang berpotensi memicu kebakaran). Untuk kondisi ini, mengisolasi saja tidak
# cukup — shutdown total adalah aksi yang pantas, dan karena irreversibel ia
# WAJIB menunggu konfirmasi manusia (verdict REQUIRE_HUMAN_CONFIRMATION).
_CATASTROPHIC_FAULTS = {"Battery_Overheating", "Inverter_Fault"}

# Ambang skor minimum untuk eskalasi ke shutdown (keyakinan sangat tinggi).
_SHUTDOWN_ESCALATION_SCORE = 0.90

# Detail simulasi aksi (semua SIMULASI — hanya update status/field, tanpa kontrol
# hardware nyata). Persentase reduksi daya untuk throttle dicatat di sini.
_THROTTLE_REDUCTION_PCT = 30


def _select_action(analysis: dict):
    """Pilih action_type berdasarkan severity + jenis fault (Tiered Response).

    - HIGH                                   → "throttle" (reversibel)
    - CRITICAL + fault katastrofik + score≥0.90 → "shutdown" (irreversibel)
    - CRITICAL (lainnya)                     → "isolate" (semi-reversibel)
    - LOW / MEDIUM / UNKNOWN                  → None (tidak ada aksi fisik)

    Eskalasi ke shutdown sengaja dibatasi pada fault yang benar-benar katastrofik
    (mis. thermal runaway baterai) dengan keyakinan sangat tinggi, supaya aksi
    irreversibel hanya muncul saat memang dibutuhkan — dan selalu lewat
    konfirmasi manusia.
    """
    level = analysis.get("risk_level", "UNKNOWN")
    if level == "HIGH":
        return "throttle"
    if level == "CRITICAL":
        fault = analysis.get("dominant_fault", "")
        try:
            score = float(analysis.get("risk_score") or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        if fault in _CATASTROPHIC_FAULTS and score >= _SHUTDOWN_ESCALATION_SCORE:
            return "shutdown"
        return "isolate"
    return None  # LOW / MEDIUM / UNKNOWN

# Snapshot 5 fitur utama untuk ditampilkan di Realtime Feed.
# Map: key snapshot (lowercase) -> nama fitur FEATURE_ORDER (kapital).
_SNAPSHOT_MAP = {
    "pv_voltage": "PV_Voltage",
    "pv_power_output": "PV_Power_Output",
    "battery_temperature": "Battery_Temperature",
    "grid_voltage": "Grid_Voltage",
    "sensor_latency": "Sensor_Latency",
}

# Salinan urutan 49 fitur sebagai fallback bila import dari agent gagal.
# (Sumber kebenaran tetap agent.anomaly_agent.FEATURE_ORDER.)
_FEATURE_ORDER_FALLBACK = [
    "Hour", "Day_Index", "PV_Voltage", "PV_Current", "PV_Power_Output",
    "PV_Panel_Temperature", "Solar_Irradiance", "PV_Efficiency",
    "PV_AC_Power", "PV_Inverter_Temperature", "PV_Frequency",
    "Battery_SOC", "Battery_SOH", "Battery_Voltage", "Battery_Current",
    "Battery_Temperature", "Battery_Charge_Rate", "Battery_Discharge_Rate",
    "Battery_Internal_Resistance", "Battery_Cycle_Count",
    "EV_Charging_Load", "EV_Charging_Current", "EV_Charging_Voltage",
    "Charging_Station_Temperature", "Active_EV_Count", "Charging_Duration",
    "Fast_Charging_Status", "Grid_Voltage", "Grid_Current", "Grid_Frequency",
    "Power_Demand", "Reactive_Power", "Load_Factor", "Energy_Export",
    "Energy_Import", "Power_Factor", "Sensor_Latency", "Packet_Loss_Rate",
    "Signal_Strength", "Data_Transmission_Rate", "Edge_Node_CPU_Usage",
    "Cloud_Response_Time", "DWT_Coeff_A1", "DWT_Coeff_D1", "DWT_Coeff_D2",
    "Signal_Energy", "Signal_Entropy", "RMS_Value", "Crest_Factor",
]

# ─────────────────────────────────────────────────────────
# Singleton instances (dimuat sekali saja, malas/lazy)
# ─────────────────────────────────────────────────────────
_agent = None
_decision = None
_root_cause = None
_telegram = None
_feature_means = None  # cache rata-rata 49 fitur dari dataset
_feature_order = None  # cache FEATURE_ORDER dari agent (atau fallback)


def get_feature_order() -> list:
    """Ambil FEATURE_ORDER dari agent; fallback ke salinan lokal bila gagal."""
    global _feature_order
    if _feature_order is None:
        try:
            from .agent.anomaly_agent import FEATURE_ORDER
            _feature_order = list(FEATURE_ORDER)
        except Exception as e:
            print(f"[agent_bridge] ! Gagal import FEATURE_ORDER ({e}), pakai fallback.")
            _feature_order = list(_FEATURE_ORDER_FALLBACK)
    return _feature_order


def get_agent():
    """AnomalyAgent (singleton). Return None bila gagal dimuat."""
    global _agent
    if _agent is None:
        try:
            from .agent.anomaly_agent import AnomalyAgent
            _agent = AnomalyAgent()
        except Exception as e:
            print(f"[agent_bridge] ✗ Gagal memuat AnomalyAgent: {e}")
            _agent = None
    return _agent


def get_decision_engine():
    """DecisionEngine (singleton). Return None bila gagal dimuat."""
    global _decision
    if _decision is None:
        try:
            from .agent.decision_engine import DecisionEngine
            _decision = DecisionEngine()
        except Exception as e:
            print(f"[agent_bridge] ✗ Gagal memuat DecisionEngine: {e}")
            _decision = None
    return _decision


def get_root_cause():
    """RootCauseAnalyzer (singleton). Return None bila gagal dimuat."""
    global _root_cause
    if _root_cause is None:
        try:
            from .agent.root_cause import RootCauseAnalyzer
            _root_cause = RootCauseAnalyzer()
        except Exception as e:
            print(f"[agent_bridge] ✗ Gagal memuat RootCauseAnalyzer: {e}")
            _root_cause = None
    return _root_cause


def get_telegram():
    """TelegramAlert (singleton). Return None bila gagal dimuat."""
    global _telegram
    if _telegram is None:
        try:
            from .alert.telegram_alert import TelegramAlert
            _telegram = TelegramAlert()
        except Exception as e:
            print(f"[agent_bridge] ✗ Gagal memuat TelegramAlert: {e}")
            _telegram = None
    return _telegram


# ─────────────────────────────────────────────────────────
# Penyusunan dict 49 fitur
# ─────────────────────────────────────────────────────────
def get_feature_means() -> dict:
    """Muat rata-rata tiap fitur kelas 'Normal' dari normal_means.json (cache sekali).

    FIX K2 (audit): baseline default HARUS merepresentasikan sampel Normal
    sejati, bukan rata-rata SEMUA kelas. Rata-rata campuran semua kelas berada
    di area kepadatan rendah sehingga Autoencoder/KMeans menandainya anomali —
    membuat input default Live Monitor mulai dari risiko ~0.2 (false positive).

    Nilai ini DI-PRECOMPUTE dari baris berlabel 'Normal' di
    Condition_Monitoring_Dataset.csv (logika identik dengan
    tests/test_risk_score.baseline_means()), lalu disimpan ke JSON kecil
    supaya backend.zip tidak perlu mengangkut CSV 21MB.

    Kunci JSON sudah berupa nama FEATURE_ORDER (berkapital) sehingga cocok
    dengan AnomalyAgent.analyze().
    Bila normal_means.json tidak ada / gagal dibaca → return {} (fitur akan
    jadi 0.0), sama seperti perilaku fallback sebelumnya.
    """
    global _feature_means
    if _feature_means is not None:
        return _feature_means

    means = {}
    try:
        import json

        if os.path.exists(MEANS_PATH):
            with open(MEANS_PATH, "r", encoding="utf-8") as f:
                raw = json.load(f)
            # Ambil hanya fitur yang ada di FEATURE_ORDER, pastikan bertipe float.
            for feat in get_feature_order():
                if feat in raw:
                    try:
                        means[feat] = float(raw[feat])
                    except (TypeError, ValueError):
                        pass
        else:
            print(f"[agent_bridge] ! File rata-rata tidak ditemukan: {MEANS_PATH} "
                  f"(fitur non-input dipakai 0.0)")
    except Exception as e:
        print(f"[agent_bridge] ! Gagal muat rata-rata fitur ({e}), pakai 0.0")

    _feature_means = means
    return _feature_means


def build_sensor_data(overrides: dict) -> dict:
    """Susun dict 49 fitur: rata-rata dataset + override manual dari slider.

    `overrides` memakai nama fitur berkapital (mis. {'PV_Voltage': 437.0}).
    Fitur yang tidak diisi memakai nilai rata-rata dataset (atau 0.0).
    """
    means = get_feature_means()
    data = {c: means.get(c, 0.0) for c in get_feature_order()}
    for k, v in (overrides or {}).items():
        try:
            data[k] = float(v)
        except (TypeError, ValueError):
            data[k] = 0.0
    return data


# ─────────────────────────────────────────────────────────
# Tiered Response + Ethical Guardian
# ─────────────────────────────────────────────────────────
def _empty_action_fields() -> dict:
    """Field aksi default (LOW/MEDIUM atau guardian tak tersedia): tidak ada aksi."""
    return {
        "action_taken": None,        # aksi yang BENAR-BENAR dieksekusi (None bila tidak)
        "proposed_action": None,     # aksi yang DIUSULKAN guardian (dipakai notifikasi pending)
        "action_status": "none",     # none|executed|pending_confirmation|blocked
        "guardian_reason": None,     # alasan keputusan guardian (untuk audit/notifikasi)
        "component_status": None,    # status komponen tersimulasi: throttled|isolated
        "action_detail": None,       # detail aksi (mis. "reduction 30%")
        "confirmation_window_seconds": None,  # window konfirmasi (bila pending)
    }


def _evaluate_tiered_response(analysis: dict) -> dict:
    """Terapkan Tiered Response + Ethical Guardian pada hasil analisis.

    Memetakan risk_level → action_type, lalu (bila ada aksi) memanggil
    ethical_guardian.evaluate_action() dan menerjemahkan verdict menjadi field
    aksi siap-pakai. SEMUA aksi adalah SIMULASI (update field saja).

    Confidence yang dipakai = risk_score (skor agregat ensemble model 0.0–1.0).
    Graceful: bila guardian None / error, kembalikan field default "no action".
    Return dict field aksi (lihat _empty_action_fields).
    """
    fields = _empty_action_fields()

    risk_level = analysis.get("risk_level", "UNKNOWN")
    action_type = _select_action(analysis)

    # LOW/MEDIUM (atau level tak dikenal) → tidak ada aksi fisik.
    if action_type is None:
        return fields

    # Guardian tak tersedia → fail safe: jangan ambil aksi otonom.
    if ethical_guardian is None:
        fields["action_status"] = "blocked"
        fields["guardian_reason"] = "Ethical guardian unavailable; autonomous action withheld"
        return fields

    confidence = float(analysis.get("risk_score") or 0.0)
    fault_detected = analysis.get("dominant_fault")

    # Aksi yang diusulkan (sebelum verdict guardian) — dipakai notifikasi pending
    # agar pesan bisa menyebut aksi spesifik walau belum/ tidak dieksekusi.
    fields["proposed_action"] = action_type

    # Konteks interlock: flag bisa di-toggle via env (lihat ethical_guardian).
    # Diteruskan eksplisit agar mudah diperluas (mis. dari config/DB) nanti.
    context = {
        "maintenance_mode": os.getenv("MAINTENANCE_MODE", "").strip().lower()
        in ("1", "true", "yes", "on"),
        "technician_on_site": os.getenv("TECHNICIAN_ON_SITE", "").strip().lower()
        in ("1", "true", "yes", "on"),
    }

    try:
        # Sertakan fault pemicu agar reason guardian deskriptif & dapat diaudit.
        verdict = ethical_guardian.evaluate_action(
            action_type, risk_level, confidence, context,
            fault_detected=fault_detected,
        )
    except Exception as e:
        print(f"[agent_bridge] ! Guardian evaluate_action gagal: {e}")
        return fields

    v = verdict.get("verdict")
    reason = verdict.get("reason", "")
    fields["guardian_reason"] = reason

    if v == "EXECUTE":
        # Eksekusi aksi SIMULASI: hanya update status komponen & field.
        fields["action_taken"] = action_type
        fields["action_status"] = "executed"
        if action_type == "throttle":
            fields["component_status"] = "throttled"
            fields["action_detail"] = f"power reduction {_THROTTLE_REDUCTION_PCT}%"
        elif action_type == "isolate":
            fields["component_status"] = "isolated"
            fields["action_detail"] = "component isolated from grid"
        elif action_type == "shutdown":
            fields["component_status"] = "shutdown"
            fields["action_detail"] = "system shutdown"
    elif v == "REQUIRE_HUMAN_CONFIRMATION":
        window = verdict.get("confirmation_window_seconds")
        fields["action_status"] = "pending_confirmation"
        fields["confirmation_window_seconds"] = window
        fields["action_detail"] = (
            f"awaiting human confirmation ({window}s)" if window else
            "awaiting human confirmation"
        )
    else:  # BLOCKED
        fields["action_status"] = "blocked"

    return fields


# ─────────────────────────────────────────────────────────
# Wrapper analisis lengkap
# ─────────────────────────────────────────────────────────
def run_full_analysis(sensor_data: dict) -> dict:
    """Jalankan analisis lengkap: agent -> decision -> root_cause -> telegram.

    Return dict gabungan (analysis + decision) yang siap dipakai State.
    Bila agent gagal dimuat, return dict default aman (tidak crash).
    """
    agent = get_agent()
    decision = get_decision_engine()
    rc = get_root_cause()
    telegram = get_telegram()

    # Fallback aman bila model inti tidak tersedia
    if agent is None:
        return {
            "timestamp": "",
            "predictions": {"error": "AnomalyAgent tidak tersedia"},
            "risk_score": 0.0,
            "risk_level": "UNKNOWN",
            "anomaly_detected": False,
            "dominant_fault": "UNKNOWN",
            "model_details": {},
            "explanation": "Model AI belum dimuat. Periksa folder models/output/.",
            "recommendations": ["Pastikan dependensi & file model tersedia."],
            "urgency": "",
            "affected_component": "Tidak diketahui",
        }

    try:
        analysis = agent.analyze(sensor_data)
    except Exception as e:
        print(f"[agent_bridge] ✗ Gagal menjalankan analyze(): {e}")
        return {
            "timestamp": "",
            "predictions": {"error": str(e)},
            "risk_score": 0.0,
            "risk_level": "UNKNOWN",
            "anomaly_detected": False,
            "dominant_fault": "UNKNOWN",
            "model_details": {},
            "explanation": f"Terjadi error saat analisis: {e}",
            "recommendations": ["Periksa log sistem"],
            "urgency": "",
            "affected_component": "Tidak diketahui",
        }

    # Keputusan (penjelasan + rekomendasi)
    decision_result = {}
    if decision is not None:
        try:
            decision_result = decision.process(analysis)
        except Exception as e:
            print(f"[agent_bridge] ! Gagal process() keputusan: {e}")

    # Simpan ke history (best effort)
    if rc is not None:
        try:
            rc.log_analysis(analysis, decision_result)
        except Exception as e:
            print(f"[agent_bridge] ! Gagal log_analysis(): {e}")

    # ── Tiered Response + Ethical Guardian ───────────────
    # Tentukan aksi otonom berdasarkan severity, lalu evaluasi lewat guardian.
    # Field aksi di-merge ke `analysis` agar IKUT terkirim ke Telegram (alasan
    # aksi) dan tersimpan di hasil akhir + DB. Graceful: tidak boleh crash.
    try:
        action_fields = _evaluate_tiered_response(analysis)
    except Exception as e:
        print(f"[agent_bridge] ! Tiered response gagal: {e}")
        action_fields = _empty_action_fields()
    analysis.update(action_fields)

    # Notifikasi Telegram (best effort, tidak boleh crash).
    # Aksi PENDING konfirmasi manusia memakai pesan KHUSUS yang mencolok & beda
    # dari alert biasa (operator harus tahu ada aksi menunggu keputusan mereka).
    # Selain itu, alert anomali biasa untuk level berisiko.
    if telegram is not None:
        try:
            if analysis.get("action_status") == "pending_confirmation":
                telegram.send_pending_confirmation(analysis)
            elif analysis.get("risk_level") in ("MEDIUM", "HIGH", "CRITICAL"):
                telegram.send_alert(analysis, decision_result)
        except Exception as e:
            print(f"[agent_bridge] ! Gagal kirim alert Telegram: {e}")

    result = {**analysis, **decision_result}

    # ── Simpan ke Supabase (history + realtime) ──────────
    # run_full_analysis dipakai BAIK oleh Live Monitor MAUPUN realtime_simulator,
    # jadi setiap analisis otomatis masuk ke kedua tabel. Semua graceful:
    # bila db_client None / DB tak tersedia, insert hanya di-skip (tidak crash).
    if db_client is not None:
        try:
            # Snapshot 5 fitur utama diambil dari sensor_data (key kapital).
            snapshot = {}
            for low, feat in _SNAPSHOT_MAP.items():
                try:
                    snapshot[low] = float(sensor_data.get(feat, 0.0))
                except (TypeError, ValueError):
                    snapshot[low] = 0.0

            db_row = {
                "timestamp": result.get("timestamp", ""),
                "risk_score": float(result.get("risk_score") or 0.0),
                "risk_level": result.get("risk_level", "UNKNOWN"),
                "dominant_fault": result.get("dominant_fault") or "Normal",
                "anomaly_detected": bool(result.get("anomaly_detected")),
                "explanation": result.get("explanation", ""),
                "recommendations": result.get("recommendations", []),
                "sensor_snapshot": snapshot,
                # Field Ethical Guardian / Tiered Response (nullable, backward-compat).
                "action_taken": result.get("action_taken"),
                "action_status": result.get("action_status", "none"),
                "guardian_reason": result.get("guardian_reason"),
            }
            db_client.insert_history(db_row)
            db_client.insert_realtime_result(db_row)
        except Exception as e:
            print(f"[agent_bridge] ! Gagal simpan ke Supabase: {e}")

    return result


# ─────────────────────────────────────────────────────────
# Pembacaan/penulisan data — kini lewat Supabase (semua graceful)
# ─────────────────────────────────────────────────────────
def get_realtime_data() -> list:
    """Ambil data Realtime Feed dari Supabase (list, graceful → [])."""
    if db_client is None:
        return []
    return db_client.get_realtime_results()


def get_history_data() -> list:
    """Ambil riwayat analisis dari Supabase (list, graceful → [])."""
    if db_client is None:
        return []
    return db_client.get_history()


def clear_history() -> bool:
    """Kosongkan tabel history di Supabase (graceful → False bila gagal)."""
    if db_client is None:
        return False
    return db_client.clear_history()


def get_telegram_status() -> dict:
    """Return status koneksi Telegram: {'configured': bool}."""
    bot = get_telegram()
    if bot is None:
        return {"configured": False}
    try:
        return {"configured": bool(bot.is_configured())}
    except Exception as e:
        print(f"[agent_bridge] ! Gagal cek status Telegram: {e}")
        return {"configured": False}


# ─────────────────────────────────────────────────────────
# Ethical Guardian — wrapper untuk dashboard (semua graceful)
# ─────────────────────────────────────────────────────────
def get_guardian_audit_log() -> list:
    """Ambil audit log guardian (list of dict diperkaya) untuk halaman dashboard.

    Tiap entri ditambah field turunan agar siap tampil:
      - confidence_pct : confidence diformat persen (mis. "85%")
      - reversibility  : pakai nilai tersimpan; fallback hitung dari action_type
                         (untuk entri lama yang belum menyimpan field ini)
    Urutan tetap terlama→terbaru (sesuai append). Graceful → [] bila guardian off.
    """
    if ethical_guardian is None:
        return []
    try:
        raw = ethical_guardian.get_audit_log()
    except Exception as e:
        print(f"[agent_bridge] ! Gagal baca audit log guardian: {e}")
        return []

    out = []
    for e in raw:
        action_type = e.get("action_type")
        try:
            conf = float(e.get("confidence") or 0.0)
        except (TypeError, ValueError):
            conf = 0.0
        try:
            # Utamakan reversibility yang sudah dipersist; fallback ke kalkulasi.
            rev = e.get("reversibility") or (
                ethical_guardian.classify_reversibility(action_type)
                if action_type else "-"
            )
        except Exception:
            rev = "-"
        # Fault pemicu (entri lama tanpa field ini → "-"). Memberi transparansi
        # KONDISI di balik aksi langsung di tabel audit.
        fault = e.get("fault_detected")
        # Eskalasi bertingkat (Opsi C): level & hasil akhir untuk tabel dashboard.
        try:
            esc_level = int(e.get("escalation_level", 0) or 0)
        except (TypeError, ValueError):
            esc_level = 0
        verdict = str(e.get("verdict", "-"))
        final_outcome = e.get("final_outcome")
        # Entri LAMA (pra-fitur Opsi C) tidak punya field tracking sama sekali —
        # jangan diperlakukan sebagai "pending" (akan memicu auto-execute massal
        # pada riwayat lama). Hanya entri ber-skema baru yang bisa "pending".
        has_tracking = ("final_outcome" in e) or ("escalation_level" in e)
        if final_outcome:
            outcome = str(final_outcome)
        elif verdict == "REQUIRE_HUMAN_CONFIRMATION" and has_tracking:
            outcome = "pending"  # masih menunggu / dalam eskalasi
        else:
            outcome = "-"        # legacy / verdict langsung → tak relevan
        out.append({
            "timestamp": str(e.get("timestamp", "-")),
            "fault": str(fault) if fault else "-",
            "action_type": str(action_type or "-"),
            "severity": str(e.get("severity", "-")),
            "confidence": conf,
            "confidence_pct": f"{conf * 100:.0f}%",
            "reversibility": rev,
            "verdict": verdict,
            "reason": str(e.get("reason", "")),
            "escalation_level": esc_level,
            "final_outcome": outcome,
        })
    return out


def get_guardian_interlock() -> bool:
    """Status toggle Safety Interlock saat ini (graceful → False)."""
    if ethical_guardian is None:
        return False
    try:
        return bool(ethical_guardian.get_interlock_state())
    except Exception as e:
        print(f"[agent_bridge] ! Gagal baca interlock: {e}")
        return False


def set_guardian_interlock(active: bool) -> bool:
    """Persist toggle Safety Interlock (dibaca ulang oleh check_safety_interlock).

    Graceful → False bila guardian tak tersedia / gagal tulis.
    """
    if ethical_guardian is None:
        return False
    try:
        return bool(ethical_guardian.set_interlock_state(bool(active)))
    except Exception as e:
        print(f"[agent_bridge] ! Gagal set interlock: {e}")
        return False


def resolve_guardian_pending(action_type: str, severity: str, confidence: float,
                             confirmed: bool, fault_detected: str = None,
                             pending_timestamp: str = None,
                             escalation_level: int = 0) -> None:
    """Catat resolusi manusia (konfirmasi/batal) atas aksi pending. Graceful.

    `pending_timestamp` & `escalation_level` diteruskan agar entri pending asli
    ditandai final_outcome (human_confirmed/human_cancelled) → menghentikan
    eskalasi bertingkat (Opsi C).
    """
    if ethical_guardian is None:
        return
    try:
        ethical_guardian.record_human_resolution(
            action_type, severity, confidence, confirmed,
            fault_detected=fault_detected,
            pending_timestamp=pending_timestamp,
            escalation_level=escalation_level,
        )
    except Exception as e:
        print(f"[agent_bridge] ! Gagal catat resolusi pending: {e}")

    # Notifikasi Telegram hasil resolusi (best-effort, graceful, tidak boleh crash).
    telegram = get_telegram()
    if telegram is not None:
        try:
            telegram.send_human_resolution(confirmed, {
                "dominant_fault": fault_detected or "UNKNOWN",
                "proposed_action": action_type,
                "risk_score": confidence,
            })
        except Exception as e:
            print(f"[agent_bridge] ! Gagal kirim notifikasi resolusi: {e}")


def mark_guardian_pending_resolved(pending_timestamp: str, confirmed: bool,
                                   escalation_level: int = 0) -> None:
    """Tandai SATU entri pending sebagai diresolusi (final_outcome) TANPA menambah
    baris resolusi baru ke audit log. Graceful.

    Satu situasi fault yang berlangsung lama memicu BANYAK entri pending beruntun
    (perilaku worker realtime; lihat _refresh_pending_count yang men-dedup per
    action_type+fault). Saat operator menekan Konfirmasi/Batalkan SEKALI, seluruh
    grup pending itu harus ikut tertutup. resolve_guardian_pending() mencatat SATU
    baris resolusi kanonik untuk entri yang ditampilkan; fungsi ini menutup entri
    pending lain di grup yang sama — cukup menandai final_outcome agar tidak
    muncul lagi sebagai pending (tanpa membanjiri log dengan baris resolusi ganda).
    """
    if ethical_guardian is None:
        return
    try:
        ethical_guardian._update_entry_by_timestamp(
            pending_timestamp,
            escalation_level=escalation_level,
            final_outcome=("human_confirmed" if confirmed else "human_cancelled"),
        )
    except Exception as e:
        print(f"[agent_bridge] ! Gagal tandai pending grup: {e}")


# ─────────────────────────────────────────────────────────
# Eskalasi bertingkat (Opsi C) — dipanggil oleh monitor di state.py
# ─────────────────────────────────────────────────────────
def _pending_to_analysis(pending_record: dict) -> dict:
    """Bangun dict 'analysis' minimal dari record pending untuk pesan Telegram."""
    try:
        conf = float(pending_record.get("confidence") or 0.0)
    except (TypeError, ValueError):
        conf = 0.0
    fault = pending_record.get("fault") or pending_record.get("fault_detected")
    action = (pending_record.get("action_type")
              or pending_record.get("proposed_action") or "?")
    return {
        "dominant_fault": fault if fault else "UNKNOWN",
        "proposed_action": action,
        "risk_score": conf,
        "confirmation_window_seconds": getattr(
            ethical_guardian, "ESCALATION_WINDOW_SECONDS", 30
        ) if ethical_guardian else 30,
    }


def escalate_pending_action(pending_record: dict, escalation_level: int) -> None:
    """Naikkan eskalasi aksi pending ke `escalation_level` (1 atau 2).

    Update audit log (escalation_level entri pending) + kirim Telegram ke kontak
    yang sesuai level. Semua graceful: kegagalan satu langkah tak menggagalkan
    yang lain & tak meng-crash monitor. Bila kontak level itu kosong di .env,
    pengiriman di-skip namun level tetap tercatat (transisi berbasis waktu).
    """
    ts = pending_record.get("timestamp")
    # 1) Tandai level eskalasi pada entri pending (sumber kebenaran server-side).
    if ethical_guardian is not None and ts:
        try:
            ethical_guardian._update_entry_by_timestamp(
                ts, escalation_level=escalation_level,
            )
        except Exception as e:
            print(f"[agent_bridge] ! Gagal update level eskalasi: {e}")
    # 2) Kirim notifikasi Telegram ke kontak level ini.
    telegram = get_telegram()
    if telegram is not None:
        try:
            telegram.send_escalation(
                escalation_level, _pending_to_analysis(pending_record)
            )
        except Exception as e:
            print(f"[agent_bridge] ! Gagal kirim eskalasi L{escalation_level}: {e}")


def auto_execute_pending_action(pending_record: dict) -> None:
    """Eksekusi otomatis aksi pending (fallback Opsi B) setelah eskalasi habis.

    Update audit log (final_outcome=auto_executed_after_timeout, level 3) + kirim
    pesan final ke KETIGA kontak + catat baris hasil ke Supabase. Semua graceful.
    """
    ts = pending_record.get("timestamp")
    action_type = pending_record.get("action_type") or "?"
    severity = pending_record.get("severity") or "-"
    fault = pending_record.get("fault") or pending_record.get("fault_detected")
    try:
        conf = float(pending_record.get("confidence") or 0.0)
    except (TypeError, ValueError):
        conf = 0.0

    # 1) Catat keputusan auto-execute ke audit log (in-place pada entri pending).
    if ethical_guardian is not None and ts:
        try:
            ethical_guardian.auto_execute_after_timeout(
                action_type, severity, conf, ts, fault_detected=fault,
            )
        except Exception as e:
            print(f"[agent_bridge] ! Gagal catat auto-execute: {e}")

    # 2) Beri tahu KETIGA kontak sekaligus.
    telegram = get_telegram()
    if telegram is not None:
        try:
            telegram.send_auto_executed(_pending_to_analysis(pending_record))
        except Exception as e:
            print(f"[agent_bridge] ! Gagal kirim notifikasi auto-execute: {e}")

    # 3) Catat baris hasil ke Supabase (best-effort, backward-compatible).
    if db_client is not None:
        try:
            db_row = {
                "timestamp": ts or "",
                "risk_score": conf,
                "risk_level": severity,
                "dominant_fault": fault or "Normal",
                "anomaly_detected": True,
                "explanation": "Auto-executed after escalation timeout (Opsi C)",
                "recommendations": [],
                "sensor_snapshot": {},
                "action_taken": action_type,
                "action_status": "auto_executed",
                "guardian_reason": (
                    "Tidak ada respon dari semua kontak dalam 90 detik — "
                    "aksi dieksekusi otomatis"
                ),
                "escalation_level": 3,
                "final_outcome": "auto_executed_after_timeout",
            }
            db_client.insert_history(db_row)
            db_client.insert_realtime_result(db_row)
        except Exception as e:
            print(f"[agent_bridge] ! Gagal simpan auto-execute ke Supabase: {e}")
