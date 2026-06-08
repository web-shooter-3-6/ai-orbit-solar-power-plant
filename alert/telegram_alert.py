"""
alert/telegram_alert.py
────────────────────────────────────────────────────────────
TelegramAlert — kirim notifikasi anomali ke Telegram, anti rate-limit.

Kredensial dibaca dari .env (python-dotenv):
    TELEGRAM_TOKEN     -> token bot dari @BotFather
    TELEGRAM_CHAT_ID   -> chat/grup tujuan

Fitur anti-spam / rate limiting:
  1) Cooldown per risk_level (LOW tidak pernah, MEDIUM 300s, HIGH 120s, CRITICAL 30s)
  2) Retry 3x (delay 2s) saat gagal kirim; gagal total → simpan failed_alerts.json
  3) Queue: flush_failed_alerts() kirim ulang yang tertunda (dipanggil tiap send_alert)
  4) Summary: MEDIUM dikumpulkan, dikirim 1 ringkasan tiap 5 menit (bukan per-event)
  5) Format pesan ringkas untuk HIGH/CRITICAL (tidak memenuhi chat)

Kalau TOKEN/CHAT_ID kosong, semua fungsi gracefully disabled.
"""

import os
import json
import time
from pathlib import Path
from datetime import datetime
from collections import Counter

import requests
from dotenv import load_dotenv

# Muat .env dari root repo (alert/ -> parent = root)
ALERT_DIR = Path(__file__).resolve().parent
REPO_DIR = ALERT_DIR.parent
load_dotenv(REPO_DIR / ".env")

# Level yang dianggap perlu alert
ALERT_LEVELS = {"MEDIUM", "HIGH", "CRITICAL"}

API_BASE = "https://api.telegram.org/bot{token}/sendMessage"
TIMEOUT = 10  # detik

# Cooldown per level (detik). LOW = None → tidak pernah kirim.
COOLDOWN = {
    "LOW": None,
    "MEDIUM": 300,   # 5 menit
    "HIGH": 120,     # 2 menit
    "CRITICAL": 30,  # 30 detik (urgent)
}

# Retry
MAX_RETRY = 3
RETRY_DELAY = 2  # detik

# Window pengumpulan summary MEDIUM (detik)
SUMMARY_WINDOW = 300  # 5 menit

# File antrian alert yang gagal terkirim
FAILED_PATH = ALERT_DIR / "failed_alerts.json"

# Emoji ringkas per level
LEVEL_EMOJI = {"MEDIUM": "🟡", "HIGH": "🟠", "CRITICAL": "🔴"}


class TelegramAlert:
    """Kirim alert anomali ke Telegram via Bot API (dengan rate limiting)."""

    # Class variable: timestamp terakhir kirim per risk_level (shared satu proses)
    _last_alert_time = {}

    # Buffer event MEDIUM untuk summary: list (timestamp_epoch, fault)
    _medium_buffer = []
    _medium_window_start = None

    def __init__(self, token: str = None, chat_id: str = None):
        self.token = token or os.getenv("TELEGRAM_TOKEN", "").strip()
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID", "").strip()

    # ─────────────────────────────────────────
    def is_configured(self) -> bool:
        """True kalau TOKEN & CHAT_ID terisi (dan bukan placeholder)."""
        if not self.token or not self.chat_id:
            return False
        if self.token.startswith("123456789:") or "xxxx" in self.token.lower():
            return False
        return True

    # ─────────────────────────────────────────
    # Pengiriman low-level
    # ─────────────────────────────────────────
    def _post(self, text: str) -> bool:
        """Sekali kirim ke Telegram (tanpa retry, tanpa simpan). True kalau sukses."""
        if not self.is_configured():
            return False
        try:
            resp = requests.post(
                API_BASE.format(token=self.token),
                data={"chat_id": self.chat_id, "text": text},
                timeout=TIMEOUT,
            )
            return resp.status_code == 200 and resp.json().get("ok", False)
        except Exception as e:
            print(f"[Telegram] gagal kirim: {e}")
            return False

    def _send_with_retry(self, text: str, level: str = "UNKNOWN") -> bool:
        """Kirim dengan retry MAX_RETRY x (delay RETRY_DELAY). Gagal total → simpan."""
        for attempt in range(1, MAX_RETRY + 1):
            if self._post(text):
                return True
            print(f"[Telegram] Percobaan {attempt}/{MAX_RETRY} gagal "
                  f"({level}), retry dalam {RETRY_DELAY}s...")
            if attempt < MAX_RETRY:
                time.sleep(RETRY_DELAY)
        # gagal total → simpan ke antrian
        print(f"[Telegram] Gagal kirim setelah {MAX_RETRY}x, disimpan ke antrian.")
        self._save_failed(text, level)
        return False

    # ─────────────────────────────────────────
    # Queue: failed_alerts.json
    # ─────────────────────────────────────────
    def _read_failed(self) -> list:
        try:
            with open(FAILED_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except (FileNotFoundError, json.JSONDecodeError):
            return []
        except Exception:
            return []

    def _write_failed(self, data: list):
        try:
            with open(FAILED_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[Telegram] Gagal tulis antrian: {e}")

    def _save_failed(self, text: str, level: str):
        data = self._read_failed()
        data.append({
            "text": text,
            "level": level,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
        })
        self._write_failed(data)

    def flush_failed_alerts(self):
        """Coba kirim ulang alert yang tertunda di failed_alerts.json.

        Yang berhasil dihapus dari file; yang gagal tetap disimpan untuk nanti.
        """
        if not FAILED_PATH.exists() or not self.is_configured():
            return
        data = self._read_failed()
        if not data:
            return

        sisa = []
        terkirim = 0
        for item in data:
            text = item.get("text", "")
            if text and self._post(text):  # sekali coba, tanpa retry (hindari loop lama)
                terkirim += 1
            else:
                sisa.append(item)

        if terkirim:
            print(f"[Telegram] Flush antrian: {terkirim} alert terkirim ulang.")
        if sisa:
            self._write_failed(sisa)
        else:
            try:
                FAILED_PATH.unlink()  # semua terkirim → hapus file
            except Exception:
                self._write_failed([])

    # ─────────────────────────────────────────
    # Cooldown
    # ─────────────────────────────────────────
    def _cooldown_remaining(self, level: str) -> float:
        """Sisa detik cooldown untuk level. 0 = boleh kirim sekarang."""
        cd = COOLDOWN.get(level)
        if not cd:
            return 0.0
        last = self._last_alert_time.get(level)
        if last is None:
            return 0.0
        elapsed = time.time() - last
        return max(0.0, cd - elapsed)

    def _mark_sent(self, level: str):
        """Catat waktu kirim terakhir untuk level (mulai hitung cooldown)."""
        self._last_alert_time[level] = time.time()

    # ─────────────────────────────────────────
    # Format pesan
    # ─────────────────────────────────────────
    @staticmethod
    def _fmt_time(ts) -> str:
        try:
            return datetime.fromisoformat(ts).strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            return str(ts)

    def _format_compact(self, analysis: dict, decision: dict) -> str:
        """Format ringkas untuk HIGH/CRITICAL (maks ~5 baris)."""
        level = analysis.get("risk_level", "UNKNOWN")
        score = analysis.get("risk_score", 0.0)
        fault = analysis.get("dominant_fault", "UNKNOWN")
        ts = self._fmt_time(analysis.get("timestamp", datetime.now().isoformat()))
        emoji = LEVEL_EMOJI.get(level, "⚠️")
        urgency = decision.get("urgency", "")
        recs = decision.get("recommendations", [])[:2]  # cukup 2 rekomendasi teratas

        lines = [
            f"{emoji} {level} — {fault}",
            f"Risk {score:.2f} | {ts}",
        ]
        if urgency:
            lines.append(urgency)
        for rec in recs:
            lines.append(f"→ {rec}")
        lines.append("[AI-ORBIT Solar Monitor]")
        return "\n".join(lines)

    # ─────────────────────────────────────────
    # Summary MEDIUM
    # ─────────────────────────────────────────
    def _buffer_medium(self, fault: str):
        """Tambahkan event MEDIUM ke buffer summary."""
        now = time.time()
        if self._medium_window_start is None:
            type(self)._medium_window_start = now
        type(self)._medium_buffer.append((now, fault))

    def _summary_due(self) -> bool:
        """True kalau window 5 menit sudah lewat & ada event terkumpul."""
        if not self._medium_buffer or self._medium_window_start is None:
            return False
        return (time.time() - self._medium_window_start) >= SUMMARY_WINDOW

    def send_summary(self) -> bool:
        """Kirim 1 pesan ringkasan semua event MEDIUM yang terkumpul, lalu reset buffer.

        Return True kalau ringkasan terkirim.
        """
        if not self._medium_buffer:
            return False
        if not self.is_configured():
            return False

        counts = Counter(fault for _, fault in self._medium_buffer)
        total = sum(counts.values())
        lines = [f"🟡 {total} anomali MEDIUM terdeteksi dalam 5 menit terakhir:"]
        for fault, n in counts.most_common():
            lines.append(f"- {n}x {fault}")
        lines.append("[AI-ORBIT Solar Monitor]")
        message = "\n".join(lines)

        ok = self._send_with_retry(message, "MEDIUM")
        if ok:
            self._mark_sent("MEDIUM")
        # reset buffer apapun hasilnya (kalau gagal sudah masuk antrian failed)
        type(self)._medium_buffer = []
        type(self)._medium_window_start = None
        return ok

    # ─────────────────────────────────────────
    # API utama
    # ─────────────────────────────────────────
    def send_alert(self, analysis_result: dict, decision_result: dict) -> bool:
        """Kirim alert sesuai kebijakan rate-limit.

        - LOW            → tidak pernah kirim
        - MEDIUM         → dikumpulkan, dikirim sebagai ringkasan tiap 5 menit
        - HIGH/CRITICAL  → kirim ringkas, hormati cooldown per level

        Return True kalau ADA pesan yang benar-benar terkirim sekarang.
        """
        # Coba flush antrian dulu sebelum kirim yang baru
        self.flush_failed_alerts()

        level = analysis_result.get("risk_level", "UNKNOWN")
        if level not in ALERT_LEVELS:
            return False
        if not self.is_configured():
            return False

        # MEDIUM → buffer untuk summary, kirim ringkasan kalau window lewat
        if level == "MEDIUM":
            self._buffer_medium(analysis_result.get("dominant_fault", "UNKNOWN"))
            if self._summary_due():
                return self.send_summary()
            return False

        # HIGH/CRITICAL → cek cooldown
        sisa = self._cooldown_remaining(level)
        if sisa > 0:
            print(f"[Telegram] Cooldown aktif untuk {level}, "
                  f"skip alert ({int(sisa)}s lagi)")
            return False

        # Kirim ringkas dengan retry
        message = self._format_compact(analysis_result, decision_result)
        self._mark_sent(level)  # mulai cooldown saat dikirim
        return self._send_with_retry(message, level)

    # ─────────────────────────────────────────
    def send_test(self) -> bool:
        """Kirim pesan test untuk verifikasi koneksi."""
        return self._post("✅ AI-ORBIT Bot aktif dan terhubung!")


# Quick self-test
if __name__ == "__main__":
    bot = TelegramAlert()
    print("is_configured:", bot.is_configured())
    if bot.is_configured():
        print("Kirim test...", "OK" if bot.send_test() else "GAGAL")
    else:
        print("Telegram belum dikonfigurasi (.env kosong / placeholder).")
