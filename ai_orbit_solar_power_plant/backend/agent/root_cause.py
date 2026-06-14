"""
agent/root_cause.py
────────────────────────────────────────────────────────────
RootCauseAnalyzer — menyimpan riwayat analisis & mendeteksi pola
anomali berulang (fault tersering, jam rawan, dll).

Riwayat disimpan APPEND ke agent_memory/history.json (tidak menimpa).
"""

import sys
import json
from pathlib import Path
from datetime import datetime
from collections import Counter

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

REPO_DIR    = Path(__file__).resolve().parent.parent
MEMORY_DIR  = REPO_DIR / "agent_memory"
HISTORY_PATH = MEMORY_DIR / "history.json"


class RootCauseAnalyzer:
    """Kelola memory analisis & ringkasan pola anomali."""

    def __init__(self, history_path: Path = HISTORY_PATH):
        self.history_path = Path(history_path)
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.history_path.exists():
            self._write_all([])
            print(f"[RootCause] File history baru dibuat: {self.history_path}")

    # ─────────────────────────────────────────
    # I/O helper (robust terhadap file rusak)
    # ─────────────────────────────────────────
    def _read_all(self) -> list:
        try:
            with open(self.history_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except (FileNotFoundError, json.JSONDecodeError):
            return []
        except Exception as e:
            print(f"[RootCause] ! Gagal baca history ({e}), mulai dari kosong")
            return []

    def _write_all(self, data: list):
        try:
            with open(self.history_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[RootCause] ✗ Gagal tulis history: {e}")

    # ─────────────────────────────────────────
    # API utama
    # ─────────────────────────────────────────
    def log_analysis(self, analysis_result: dict, decision_result: dict) -> dict:
        """Simpan satu entri analisis (append) ke history.json."""
        try:
            entry = {
                "timestamp":       analysis_result.get("timestamp", datetime.now().isoformat()),
                "risk_score":      analysis_result.get("risk_score", 0.0),
                "risk_level":      analysis_result.get("risk_level", "UNKNOWN"),
                "dominant_fault":  analysis_result.get("dominant_fault", "UNKNOWN"),
                "explanation":     decision_result.get("explanation", ""),
                "recommendations": decision_result.get("recommendations", []),
            }
            data = self._read_all()
            data.append(entry)
            self._write_all(data)
            return entry
        except Exception as e:
            print(f"[RootCause] ✗ Gagal log analisis: {e}")
            return {}

    def get_recent_history(self, n: int = 10) -> list:
        """Kembalikan n entri terakhir (paling baru di belakang)."""
        try:
            return self._read_all()[-n:]
        except Exception as e:
            print(f"[RootCause] ✗ Gagal ambil history: {e}")
            return []

    def get_pattern_summary(self) -> dict:
        """Ringkas pola: fault tersering, jam rawan, distribusi level risiko."""
        try:
            data = self._read_all()
            if not data:
                return {
                    "total_analisis": 0,
                    "pesan": "Belum ada data riwayat.",
                }

            fault_counter = Counter()
            hour_counter = Counter()
            level_counter = Counter()
            anomaly_count = 0

            for e in data:
                fault = e.get("dominant_fault", "UNKNOWN")
                fault_counter[fault] += 1
                level_counter[e.get("risk_level", "UNKNOWN")] += 1
                # anomali dihitung dari risk_score > 0.25 (selaras logika baru)
                try:
                    if float(e.get("risk_score", 0.0)) > 0.25:
                        anomaly_count += 1
                except (TypeError, ValueError):
                    pass
                # ambil jam dari timestamp ISO
                ts = e.get("timestamp", "")
                try:
                    hour = datetime.fromisoformat(ts).hour
                    hour_counter[hour] += 1
                except (ValueError, TypeError):
                    pass

            fault_terbanyak = fault_counter.most_common(1)[0]
            jam_terbanyak = hour_counter.most_common(1)[0] if hour_counter else (None, 0)

            return {
                "total_analisis":     len(data),
                "total_anomali":      anomaly_count,
                "fault_tersering":    {"fault": fault_terbanyak[0], "jumlah": fault_terbanyak[1]},
                "jam_paling_rawan":   {"jam": jam_terbanyak[0], "jumlah": jam_terbanyak[1]},
                "distribusi_fault":   dict(fault_counter.most_common()),
                "distribusi_level":   dict(level_counter),
            }
        except Exception as e:
            print(f"[RootCause] ✗ Gagal buat pattern summary: {e}")
            return {"total_analisis": 0, "pesan": f"Error: {e}"}


# Quick self-test
if __name__ == "__main__":
    rc = RootCauseAnalyzer()
    rc.log_analysis(
        {"timestamp": datetime.now().isoformat(), "risk_score": 0.75,
         "risk_level": "HIGH", "dominant_fault": "Inverter_Fault"},
        {"explanation": "Inverter bermasalah", "recommendations": ["Restart inverter"]},
    )
    print("Pattern summary:", rc.get_pattern_summary())
