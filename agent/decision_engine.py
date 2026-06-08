"""
agent/decision_engine.py
────────────────────────────────────────────────────────────
DecisionEngine — menerjemahkan hasil AnomalyAgent jadi keputusan
yang bisa dibaca manusia: penjelasan, rekomendasi, urgency, komponen.

Tidak meng-import AnomalyAgent (hindari circular import). Cukup menerima
dict hasil analyze().
"""

import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ─────────────────────────────────────────
# Basis pengetahuan: fault → penjelasan + rekomendasi + komponen
# ─────────────────────────────────────────
KNOWLEDGE_BASE = {
    "Normal": {
        "explanation": "Sistem beroperasi normal.",
        "recommendations": ["Lanjutkan monitoring rutin"],
        "component": "Sistem",
    },
    "PV_Fault": {
        "explanation": "Panel surya terindikasi bermasalah.",
        "recommendations": [
            "Periksa sambungan kabel string",
            "Cek kebersihan panel",
            "Ukur tegangan tiap string secara manual",
        ],
        "component": "Panel Surya (PV)",
    },
    "Battery_Degradation": {
        "explanation": "Kapasitas baterai menurun dari spesifikasi awal.",
        "recommendations": [
            "Lakukan battery health check",
            "Pertimbangkan penggantian sel baterai",
            "Kurangi depth of discharge",
        ],
        "component": "Baterai",
    },
    "Battery_Overheating": {
        "explanation": "Suhu baterai melebihi batas aman.",
        "recommendations": [
            "Segera kurangi beban charging",
            "Periksa sistem ventilasi",
            "Aktifkan pendingin tambahan jika tersedia",
        ],
        "component": "Baterai",
    },
    "EV_Charging_Fault": {
        "explanation": "Gangguan pada stasiun pengisian EV.",
        "recommendations": [
            "Hentikan sesi charging sementara",
            "Periksa konektor charging",
            "Reset charging station",
        ],
        "component": "Stasiun Pengisian EV",
    },
    "Grid_Instability": {
        "explanation": "Ketidakstabilan tegangan/frekuensi grid.",
        "recommendations": [
            "Monitor frekuensi grid secara intensif",
            "Siapkan mode island operation",
            "Hubungi operator PLN jika berlanjut",
        ],
        "component": "Jaringan Listrik (Grid)",
    },
    "Inverter_Fault": {
        "explanation": "Inverter terdeteksi tidak bekerja optimal.",
        "recommendations": [
            "Restart inverter",
            "Cek log error inverter",
            "Periksa koneksi DC/AC inverter",
        ],
        "component": "Inverter",
    },
    "Communication_Failure": {
        "explanation": "Gangguan komunikasi sensor/jaringan.",
        "recommendations": [
            "Cek koneksi jaringan edge node",
            "Restart modul komunikasi",
            "Verifikasi data secara manual",
        ],
        "component": "Sistem Komunikasi / Sensor",
    },
    "Overload_Condition": {
        "explanation": "Beban sistem melebihi kapasitas.",
        "recommendations": [
            "Kurangi beban secara bertahap",
            "Prioritaskan beban kritis",
            "Aktifkan load shedding jika tersedia",
        ],
        "component": "Sistem Beban",
    },
    "Sensor_Failure": {
        "explanation": "Sensor terindikasi rusak atau tidak akurat.",
        "recommendations": [
            "Kalibrasi sensor yang bermasalah",
            "Bandingkan dengan pembacaan manual",
            "Ganti sensor jika diperlukan",
        ],
        "component": "Sensor",
    },
}

# Estimasi waktu respons berdasarkan level risiko
URGENCY_BY_LEVEL = {
    "LOW":      "Monitoring rutin (tidak mendesak)",
    "MEDIUM":   "Tindakan dalam 24 jam",
    "HIGH":     "Tindakan dalam 1-4 jam",
    "CRITICAL": "Tindakan SEGERA (< 30 menit)",
    "UNKNOWN":  "Perlu verifikasi manual",
}

# Fallback kalau fault tidak dikenal
_DEFAULT_KB = {
    "explanation": "Kondisi tidak dikenali, perlu pemeriksaan manual.",
    "recommendations": ["Lakukan inspeksi manual", "Periksa log sistem"],
    "component": "Tidak diketahui",
}


class DecisionEngine:
    """Mengubah hasil analisis numerik jadi penjelasan & rekomendasi."""

    def __init__(self, knowledge_base: dict = None):
        self.kb = knowledge_base or KNOWLEDGE_BASE

    def process(self, analysis_result: dict) -> dict:
        """Terima hasil AnomalyAgent.analyze() → dict keputusan."""
        try:
            fault = analysis_result.get("dominant_fault", "UNKNOWN")
            level = analysis_result.get("risk_level", "UNKNOWN")

            kb = self.kb.get(fault, _DEFAULT_KB)
            urgency = URGENCY_BY_LEVEL.get(level, URGENCY_BY_LEVEL["UNKNOWN"])

            return {
                "explanation": kb["explanation"],
                "recommendations": list(kb["recommendations"]),
                "urgency": urgency,
                "affected_component": kb["component"],
            }
        except Exception as e:
            print(f"[DecisionEngine] ✗ Gagal memproses keputusan: {e}")
            return {
                "explanation": "Terjadi error saat memproses keputusan.",
                "recommendations": ["Periksa log sistem"],
                "urgency": URGENCY_BY_LEVEL["UNKNOWN"],
                "affected_component": "Tidak diketahui",
            }


# Quick self-test
if __name__ == "__main__":
    engine = DecisionEngine()
    contoh = {"dominant_fault": "Inverter_Fault", "risk_level": "HIGH"}
    print(engine.process(contoh))
