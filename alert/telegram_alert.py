"""
alert/telegram_alert.py
────────────────────────────────────────────────────────────
TelegramAlert — kirim notifikasi anomali ke Telegram.

Kredensial dibaca dari .env (python-dotenv):
    TELEGRAM_TOKEN     -> token bot dari @BotFather
    TELEGRAM_CHAT_ID   -> chat/grup tujuan

Kalau TOKEN/CHAT_ID kosong, semua fungsi gracefully disabled
(tidak melempar error, hanya is_configured() == False).
"""

import os
from pathlib import Path
from datetime import datetime

import requests
from dotenv import load_dotenv

# Muat .env dari root repo (alert/ -> parent = root)
REPO_DIR = Path(__file__).resolve().parent.parent
load_dotenv(REPO_DIR / ".env")

# Level yang dianggap perlu alert
ALERT_LEVELS = {"MEDIUM", "HIGH", "CRITICAL"}

API_BASE = "https://api.telegram.org/bot{token}/sendMessage"
TIMEOUT = 10  # detik


class TelegramAlert:
    """Kirim alert anomali ke Telegram via Bot API."""

    def __init__(self, token: str = None, chat_id: str = None):
        self.token = token or os.getenv("TELEGRAM_TOKEN", "").strip()
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID", "").strip()

    # ─────────────────────────────────────────
    def is_configured(self) -> bool:
        """True kalau TOKEN & CHAT_ID terisi (dan bukan placeholder)."""
        if not self.token or not self.chat_id:
            return False
        # tolak nilai contoh dari .env.example
        if self.token.startswith("123456789:") or "xxxx" in self.token.lower():
            return False
        return True

    # ─────────────────────────────────────────
    def _send_raw(self, text: str) -> bool:
        """Kirim teks mentah ke Telegram. Return True kalau sukses."""
        if not self.is_configured():
            return False
        try:
            url = API_BASE.format(token=self.token)
            resp = requests.post(
                url,
                data={"chat_id": self.chat_id, "text": text},
                timeout=TIMEOUT,
            )
            return resp.status_code == 200 and resp.json().get("ok", False)
        except Exception as e:
            print(f"[TelegramAlert] gagal kirim: {e}")
            return False

    # ─────────────────────────────────────────
    def _format_message(self, analysis_result: dict, decision_result: dict) -> str:
        """Susun pesan alert sesuai template."""
        ts = analysis_result.get("timestamp", datetime.now().isoformat())
        try:
            ts = datetime.fromisoformat(ts).strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            pass

        score = analysis_result.get("risk_score", 0.0)
        level = analysis_result.get("risk_level", "UNKNOWN")
        fault = analysis_result.get("dominant_fault", "UNKNOWN")
        explanation = decision_result.get("explanation", "-")
        recs = decision_result.get("recommendations", [])

        lines = [
            "🚨 AI-ORBIT SOLAR ALERT",
            "─────────────────────",
            f"Waktu     : {ts}",
            f"Risk Score: {score:.2f} | {level}",
            f"Fault     : {fault}",
            "─────────────────────",
            f"Penjelasan: {explanation}",
            "",
            "Rekomendasi:",
        ]
        for rec in recs:
            lines.append(f"• {rec}")
        lines += [
            "─────────────────────",
            "[AI-ORBIT Solar Monitor]",
        ]
        return "\n".join(lines)

    # ─────────────────────────────────────────
    def send_alert(self, analysis_result: dict, decision_result: dict) -> bool:
        """Kirim alert kalau risk_level MEDIUM/HIGH/CRITICAL.

        Return:
            True  -> alert terkirim
            False -> tidak terkirim (level aman, belum dikonfigurasi, atau gagal)
        """
        level = analysis_result.get("risk_level", "UNKNOWN")
        if level not in ALERT_LEVELS:
            return False
        if not self.is_configured():
            return False
        message = self._format_message(analysis_result, decision_result)
        return self._send_raw(message)

    # ─────────────────────────────────────────
    def send_test(self) -> bool:
        """Kirim pesan test untuk verifikasi koneksi."""
        return self._send_raw("✅ AI-ORBIT Bot aktif dan terhubung!")


# Quick self-test
if __name__ == "__main__":
    bot = TelegramAlert()
    print("is_configured:", bot.is_configured())
    if bot.is_configured():
        print("Kirim test...", "OK" if bot.send_test() else "GAGAL")
    else:
        print("Telegram belum dikonfigurasi (.env kosong / placeholder).")
