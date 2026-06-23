"""
tests/test_ethical_guardian.py
────────────────────────────────────────────────────────────
Test sederhana Ethical Guardian + Tiered Response (deterministik, rule-based).

Jalankan dari root repo:
    python tests/test_ethical_guardian.py

Tiap test mencetak PASS/FAIL + verdict aktual vs ekspektasi. Skenario inti
sesuai requirement UAS:
  (a) confidence tinggi + reversible  → EXECUTE
  (b) confidence rendah               → BLOCKED
  (c) safety interlock aktif          → BLOCKED
  (d) aksi irreversible (shutdown)    → REQUIRE_HUMAN_CONFIRMATION
"""

import os
import sys
import json
import tempfile
from pathlib import Path

# Console Windows kadang cp1252 — paksa UTF-8 agar emoji/panah tidak crash.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ── Path setup: root repo masuk sys.path ──
REPO_DIR = Path(__file__).resolve().parent.parent
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from ai_orbit_solar_power_plant.backend import ethical_guardian as eg

# Arahkan audit log ke file sementara supaya test tidak mengotori log produksi.
_TMP_LOG = Path(tempfile.gettempdir()) / "test_ethical_audit_log.json"
eg.AUDIT_LOG_PATH = str(_TMP_LOG)
if _TMP_LOG.exists():
    _TMP_LOG.unlink()

_passed = 0
_failed = 0


def check(name: str, actual, expected):
    global _passed, _failed
    ok = actual == expected
    status = "PASS" if ok else "FAIL"
    if ok:
        _passed += 1
    else:
        _failed += 1
    print(f"  [{status}] {name}: expected={expected!r} actual={actual!r}")


def run():
    print("=" * 64)
    print("  TEST ETHICAL GUARDIAN + TIERED RESPONSE — AI-ORBIT SOLAR")
    print("=" * 64)

    # Pastikan env interlock bersih untuk skenario non-interlock.
    os.environ.pop("SAFETY_INTERLOCK_ACTIVE", None)

    # ── Unit: helper individual ────────────────────────────
    print("\n[1] Unit helper")
    check("reversibility throttle", eg.classify_reversibility("throttle"), "reversible")
    check("reversibility isolate", eg.classify_reversibility("isolate"), "semi_reversible")
    check("reversibility shutdown", eg.classify_reversibility("shutdown"), "irreversible")
    check("reversibility unknown -> irreversible",
          eg.classify_reversibility("zap"), "irreversible")
    check("conf throttle 0.60 ok", eg.check_confidence_threshold(0.60, "throttle"), True)
    check("conf throttle 0.59 no", eg.check_confidence_threshold(0.59, "throttle"), False)
    check("conf isolate 0.80 ok", eg.check_confidence_threshold(0.80, "isolate"), True)
    check("conf isolate 0.79 no", eg.check_confidence_threshold(0.79, "isolate"), False)
    check("conf shutdown 0.90 ok", eg.check_confidence_threshold(0.90, "shutdown"), True)
    check("interlock via context (technician)",
          eg.check_safety_interlock({"technician_on_site": True}), True)
    check("interlock clean", eg.check_safety_interlock({}), False)

    # ── Skenario (a): confidence tinggi + reversible → EXECUTE ──
    print("\n[2] Skenario (a) — confidence tinggi + reversible (throttle)")
    r = eg.evaluate_action("throttle", "HIGH", 0.85, {},
                           fault_detected="Grid_Instability")
    print(f"      → {r}")
    check("verdict EXECUTE", r["verdict"], "EXECUTE")
    check("reversibility reversible", r["reversibility"], "reversible")
    check("no confirmation window", r["confirmation_window_seconds"], None)
    check("reason sebut fault", "Grid_Instability" in r["reason"], True)
    check("reason sebut confidence", "85%" in r["reason"], True)

    # ── Skenario (b): confidence rendah → BLOCKED ──
    print("\n[3] Skenario (b) — confidence rendah (isolate 0.65 < 0.80)")
    r = eg.evaluate_action("isolate", "CRITICAL", 0.65, {},
                           fault_detected="PV_Fault")
    print(f"      → {r}")
    check("verdict BLOCKED", r["verdict"], "BLOCKED")
    check("reason sebut fault", "PV_Fault" in r["reason"], True)
    check("reason sebut ambang", "ambang" in r["reason"].lower(), True)

    # ── Skenario (c): interlock aktif → BLOCKED ──
    print("\n[4] Skenario (c) — safety interlock aktif (technician on site)")
    r = eg.evaluate_action("throttle", "HIGH", 0.95, {"technician_on_site": True},
                           fault_detected="Battery_Overheating")
    print(f"      → {r}")
    check("verdict BLOCKED (interlock override confidence tinggi)", r["verdict"], "BLOCKED")
    check("reason sebut fault", "Battery_Overheating" in r["reason"], True)
    check("reason sebut maintenance", "maintenance" in r["reason"].lower(), True)

    print("      ...via env SAFETY_INTERLOCK_ACTIVE=1")
    os.environ["SAFETY_INTERLOCK_ACTIVE"] = "1"
    r = eg.evaluate_action("throttle", "HIGH", 0.95, {})
    print(f"      → {r}")
    check("verdict BLOCKED (env interlock)", r["verdict"], "BLOCKED")
    os.environ.pop("SAFETY_INTERLOCK_ACTIVE", None)

    # ── Skenario (d): irreversible → REQUIRE_HUMAN_CONFIRMATION ──
    print("\n[5] Skenario (d) — aksi irreversible (shutdown) high confidence")
    r = eg.evaluate_action("shutdown", "CRITICAL", 0.95, {},
                           fault_detected="Battery_Overheating")
    print(f"      → {r}")
    check("verdict REQUIRE_HUMAN_CONFIRMATION", r["verdict"], "REQUIRE_HUMAN_CONFIRMATION")
    check("confirmation window 30s", r["confirmation_window_seconds"], 30)
    check("reason sebut fault", "Battery_Overheating" in r["reason"], True)

    # ── Audit log tertulis untuk SEMUA verdict ──
    print("\n[6] Audit log")
    log = eg.get_audit_log()
    print(f"      total entri tercatat: {len(log)}")
    # 4 panggilan evaluate_action di atas → 5 entri (skenario c dipanggil 2x).
    check("audit log >= 5 entri", len(log) >= 5, True)
    verdicts = [e["verdict"] for e in log]
    check("audit mencatat BLOCKED", "BLOCKED" in verdicts, True)
    check("audit mencatat EXECUTE", "EXECUTE" in verdicts, True)
    check("audit mencatat REQUIRE_HUMAN_CONFIRMATION",
          "REQUIRE_HUMAN_CONFIRMATION" in verdicts, True)
    # File benar-benar JSON list of dict.
    with open(eg.AUDIT_LOG_PATH, "r", encoding="utf-8") as f:
        on_disk = json.load(f)
    check("audit file = list", isinstance(on_disk, list), True)
    # Field fault_detected tersimpan & terisi (transparansi kondisi pemicu).
    check("entri punya field fault_detected",
          all("fault_detected" in e for e in on_disk), True)
    check("fault_detected terisi untuk skenario shutdown",
          any(e.get("fault_detected") == "Battery_Overheating" for e in on_disk),
          True)

    # ── Eskalasi bertingkat (Opsi C) ──────────────────────
    print("\n[7] Eskalasi bertingkat (Opsi C)")

    def _entry(ts, verdict="REQUIRE_HUMAN_CONFIRMATION"):
        """Ambil entri terakhir di audit log dengan timestamp & verdict cocok."""
        matches = [e for e in eg.get_audit_log()
                   if e.get("timestamp") == ts and e.get("verdict") == verdict]
        return matches[-1] if matches else None

    # Field default escalation_level=0 & final_outcome=None pada entri baru.
    ts_a = "2099-01-01T00:00:00"
    eg.log_decision("shutdown", "CRITICAL", 0.95, "REQUIRE_HUMAN_CONFIRMATION",
                    "pending uji", ts_a, fault_detected="Battery_Overheating")
    ea = _entry(ts_a)
    check("default escalation_level = 0", ea.get("escalation_level"), 0)
    check("default final_outcome = None", ea.get("final_outcome"), None)

    # _update_entry_by_timestamp menaikkan level in-place.
    ok_upd = eg._update_entry_by_timestamp(ts_a, escalation_level=1)
    check("_update_entry_by_timestamp return True", ok_upd, True)
    check("escalation_level naik ke 1", _entry(ts_a).get("escalation_level"), 1)

    # auto_execute_after_timeout: verdict TETAP RHC, outcome & level 3.
    res = eg.auto_execute_after_timeout("shutdown", "CRITICAL", 0.95, ts_a,
                                        fault_detected="Battery_Overheating")
    ea = _entry(ts_a)
    check("auto verdict tetap REQUIRE_HUMAN_CONFIRMATION",
          ea.get("verdict"), "REQUIRE_HUMAN_CONFIRMATION")
    check("auto final_outcome = auto_executed_after_timeout",
          ea.get("final_outcome"), "auto_executed_after_timeout")
    check("auto escalation_level = 3", ea.get("escalation_level"), 3)
    check("auto return menyebut 90 detik di reason",
          "90" in res["reason"], True)

    # record_human_resolution menandai entri pending (human_confirmed).
    ts_b = "2099-02-02T00:00:00"
    eg.log_decision("shutdown", "CRITICAL", 0.90, "REQUIRE_HUMAN_CONFIRMATION",
                    "pending uji 2", ts_b, fault_detected="Inverter_Fault")
    eg.record_human_resolution("shutdown", "CRITICAL", 0.90, True,
                               fault_detected="Inverter_Fault",
                               pending_timestamp=ts_b, escalation_level=2)
    check("human_confirmed pada entri pending",
          _entry(ts_b).get("final_outcome"), "human_confirmed")

    ts_c = "2099-03-03T00:00:00"
    eg.log_decision("shutdown", "CRITICAL", 0.90, "REQUIRE_HUMAN_CONFIRMATION",
                    "pending uji 3", ts_c, fault_detected="Inverter_Fault")
    eg.record_human_resolution("shutdown", "CRITICAL", 0.90, False,
                               fault_detected="Inverter_Fault",
                               pending_timestamp=ts_c, escalation_level=1)
    check("human_cancelled pada entri pending",
          _entry(ts_c).get("final_outcome"), "human_cancelled")

    # ── Pesan Telegram eskalasi (dibangun tanpa jaringan) ──
    print("\n[8] Pesan Telegram eskalasi & graceful fallback")
    from ai_orbit_solar_power_plant.backend.alert.telegram_alert import TelegramAlert
    analysis = {
        "dominant_fault": "Battery_Overheating",
        "proposed_action": "shutdown",
        "risk_score": 0.95,
        "confirmation_window_seconds": 30,
    }
    m1 = TelegramAlert.build_escalation_message(1, analysis)
    m2 = TelegramAlert.build_escalation_message(2, analysis)
    mauto = TelegramAlert.build_auto_executed_message(analysis)
    check("L1 sebut kontak tidak merespon", "tidak merespon" in m1.lower(), True)
    check("L1 sebut aksi shutdown", "shutdown" in m1, True)
    check("L2 sebut eksekusi otomatis", "otomatis" in m2.lower(), True)
    check("auto sebut 90 detik", "90 detik" in mauto, True)
    check("auto sebut confidence 95%", "95%" in mauto, True)
    check("auto sebut aksi shutdown", "shutdown" in mauto, True)

    # Graceful: slot kontak kosong → send_escalation return False, tanpa exception.
    bot = TelegramAlert(token="testtoken", chat_id=["A", "", "C"])
    check("escalation_slots posisional", bot.escalation_slots, ["A", "", "C"])
    try:
        sent = bot.send_escalation(1, analysis)  # slot[1] kosong → skip
        check("send_escalation slot kosong → False (graceful)", sent, False)
    except Exception as exc:  # pragma: no cover
        check("send_escalation slot kosong tidak exception", str(exc), "")

    # ── Ringkasan ──
    print("\n" + "=" * 64)
    print(f"  HASIL: {_passed} PASS, {_failed} FAIL")
    print("=" * 64)
    return _failed == 0


if __name__ == "__main__":
    ok = run()
    sys.exit(0 if ok else 1)
