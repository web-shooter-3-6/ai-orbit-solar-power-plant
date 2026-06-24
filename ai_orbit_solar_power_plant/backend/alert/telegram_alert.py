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

# requests dipakai untuk memanggil Bot API. Import-nya di-guard agar modul tetap
# bisa di-import (mis. untuk memakai builder pesan statis / pengujian) walau
# requests belum terpasang — konsisten dgn pola graceful db_client (psycopg2).
try:
    import requests
    _REQUESTS_OK = True
except Exception:  # pragma: no cover
    requests = None
    _REQUESTS_OK = False
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
    # Notifikasi "perlu konfirmasi manusia": cukup sering untuk mendesak, tapi
    # tetap ber-cooldown agar fault yang berlangsung lama (puluhan event beruntun)
    # tidak membanjiri chat dengan permintaan konfirmasi berulang.
    "PENDING_CONFIRMATION": 60,
    # Eskalasi bertingkat: satu pesan PER transisi level (level 1/2) & satu pesan
    # final auto-executed. Idempotensi sudah dijaga oleh escalation_level di audit
    # log, jadi tanpa cooldown agar tiap transisi PASTI terkirim tepat waktu.
    "ESCALATION": 0,
}

# Retry
MAX_RETRY = 3
RETRY_DELAY = 2  # detik

# Window pengumpulan summary MEDIUM (detik)
SUMMARY_WINDOW = 300  # 5 menit

# File antrian alert yang gagal terkirim
FAILED_PATH = ALERT_DIR / "failed_alerts.json"

# File preference alert dari bot interaktif (/alert_on, /alert_off, /alert_medium)
CONFIG_PATH = ALERT_DIR / "bot_config.json"


def _read_alert_mode() -> str:
    """Baca mode alert dari alert/bot_config.json.

    Return salah satu: 'all' (semua level), 'off' (matikan sementara),
    'medium' (hanya MEDIUM ke atas). Default 'all' kalau file tidak ada/rusak.
    """
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        mode = str(data.get("alert_mode", "all")).lower()
        if mode in ("all", "off", "medium"):
            return mode
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    except Exception:
        pass
    return "all"

# Emoji ringkas per level
LEVEL_EMOJI = {"MEDIUM": "🟡", "HIGH": "🟠", "CRITICAL": "🔴"}


class TelegramAlert:
    """Kirim alert anomali ke Telegram via Bot API (dengan rate limiting)."""

    # Class variable: timestamp terakhir kirim per risk_level (shared satu proses)
    _last_alert_time = {}

    # Buffer event MEDIUM untuk summary: list (timestamp_epoch, fault)
    _medium_buffer = []
    _medium_window_start = None

    def __init__(self, token: str = None, chat_id=None):
        self.token = token or os.getenv("TELEGRAM_TOKEN", "").strip()
        # Kumpulkan SEMUA chat id tujuan (bisa lebih dari satu).
        # Sumber: argumen chat_id (str/list) ATAU env TELEGRAM_CHAT_ID,
        # TELEGRAM_CHAT_ID_2, TELEGRAM_CHAT_ID_3, ... (dibaca berurutan).
        if chat_id is not None:
            ids = chat_id if isinstance(chat_id, (list, tuple)) else [chat_id]
        else:
            ids = [
                os.getenv("TELEGRAM_CHAT_ID", ""),
                os.getenv("TELEGRAM_CHAT_ID_2", ""),
                os.getenv("TELEGRAM_CHAT_ID_3", ""),
            ]
        # buang yang kosong & duplikat, jaga urutan
        self.chat_ids = list(dict.fromkeys(str(c).strip() for c in ids if str(c).strip()))
        # Slot kontak POSISIONAL untuk eskalasi bertingkat (Opsi C): indeks 0 =
        # kontak utama, 1 = kontak kedua, 2 = kontak ketiga. Berbeda dari
        # self.chat_ids yang sudah di-dedup/dibuang-kosongnya — di sini posisi
        # DIPERTAHANKAN (slot kosong tetap "") agar level eskalasi memetakan ke
        # kontak yang tepat dan slot yang absen bisa di-skip dengan graceful.
        # Dibangun dari sumber `ids` yang sama (mendukung argumen chat_id untuk tes).
        slots = [str(c).strip() if c is not None else "" for c in ids]
        slots += [""] * (3 - len(slots))  # pastikan minimal 3 slot
        self.escalation_slots = slots[:3]

    # ─────────────────────────────────────────
    def is_configured(self) -> bool:
        """True kalau TOKEN & minimal 1 CHAT_ID terisi (dan bukan placeholder)."""
        if not _REQUESTS_OK:
            return False  # tanpa requests, pengiriman mustahil → anggap belum siap
        if not self.token or not self.chat_ids:
            return False
        if self.token.startswith("123456789:") or "xxxx" in self.token.lower():
            return False
        return True

    # ─────────────────────────────────────────
    # Pengiriman low-level
    # ─────────────────────────────────────────
    def _post(self, text: str) -> bool:
        """Kirim ke SEMUA chat id (tanpa retry, tanpa simpan).

        Return True kalau minimal satu chat berhasil dikirim (supaya cooldown/
        antrian tidak memicu kirim ulang yang menyebabkan duplikat ke chat yang
        sudah berhasil).
        """
        if not self.is_configured():
            return False
        url = API_BASE.format(token=self.token)
        ada_sukses = False
        for cid in self.chat_ids:
            try:
                resp = requests.post(
                    url,
                    data={"chat_id": cid, "text": text},
                    timeout=TIMEOUT,
                )
                if resp.status_code == 200 and resp.json().get("ok", False):
                    ada_sukses = True
                else:
                    print(f"[Telegram] gagal kirim ke {cid}: {resp.text[:120]}")
            except Exception as e:
                print(f"[Telegram] gagal kirim ke {cid}: {e}")
        return ada_sukses

    def _post_to(self, chat_id: str, text: str) -> bool:
        """Kirim ke SATU chat id spesifik (tanpa retry, tanpa simpan).

        Dipakai eskalasi bertingkat yang menargetkan kontak berbeda per level.
        Return True bila terkirim sukses ke chat id tersebut.
        """
        if not self.is_configured() or not str(chat_id).strip():
            return False
        url = API_BASE.format(token=self.token)
        try:
            resp = requests.post(
                url,
                data={"chat_id": str(chat_id).strip(), "text": text},
                timeout=TIMEOUT,
            )
            if resp.status_code == 200 and resp.json().get("ok", False):
                return True
            print(f"[Telegram] gagal kirim ke {chat_id}: {resp.text[:120]}")
        except Exception as e:
            print(f"[Telegram] gagal kirim ke {chat_id}: {e}")
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

        # Ethical Guardian / Tiered Response: jelaskan aksi otonom AI (bila ada).
        # Aditif & aman — dibaca via .get(), pemanggil lama tak terpengaruh.
        action_status = analysis.get("action_status")
        guardian_reason = analysis.get("guardian_reason") or ""
        if action_status == "executed":
            act = analysis.get("action_taken", "?")
            detail = analysis.get("action_detail")
            extra = f" ({detail})" if detail else ""
            lines.append(f"🤖 Aksi otonom: {act}{extra} — {guardian_reason}")
        elif action_status == "blocked":
            lines.append(f"🛡️ Aksi diblokir: {guardian_reason} (eskalasi manual)")
        elif action_status == "pending_confirmation":
            detail = analysis.get("action_detail") or "menunggu konfirmasi manusia"
            lines.append(f"⏳ {detail}: {guardian_reason}")

        lines.append("[AI-ORBIT Solar Monitor]")
        return "\n".join(lines)

    # ─────────────────────────────────────────
    # Notifikasi PERLU KONFIRMASI MANUSIA (verdict REQUIRE_HUMAN_CONFIRMATION)
    # ─────────────────────────────────────────
    @staticmethod
    def build_pending_confirmation_message(analysis: dict) -> str:
        """Susun teks pesan pending confirmation yang MENONJOL & BEDA dari alert biasa.

        Dipisah dari pengiriman supaya isinya bisa diuji/ditampilkan tanpa jaringan.
        Memuat: fault terdeteksi, aksi yang diusulkan, confidence, window konfirmasi,
        dan instruksi membuka dashboard untuk konfirmasi/pembatalan.
        """
        fault = analysis.get("dominant_fault", "UNKNOWN")
        action = (analysis.get("proposed_action")
                  or analysis.get("action_taken") or "?")
        score = analysis.get("risk_score", 0.0)
        window = analysis.get("confirmation_window_seconds") or 30
        try:
            score_pct = f"{float(score) * 100:.0f}%"
        except (TypeError, ValueError):
            score_pct = str(score)
        lines = [
            "⚠️ PERLU KONFIRMASI MANUSIA ⚠️",
            f"Fault terdeteksi: {fault}",
            f"Aksi diusulkan: {action}",
            f"Confidence: {score_pct}",
            f"Window konfirmasi: {window} detik",
            "",
            "Aksi ini TAK TERPULIHKAN sehingga TIDAK dieksekusi otonom. Buka "
            "dashboard Ethical Guardian untuk KONFIRMASI atau BATALKAN sebelum "
            "window konfirmasi habis.",
            "[AI-ORBIT Solar Monitor]",
        ]
        return "\n".join(lines)

    def send_pending_confirmation(self, analysis: dict) -> bool:
        """Kirim notifikasi mencolok saat ada aksi menunggu konfirmasi manusia.

        Hormati mode alert 'off' dan cooldown khusus PENDING_CONFIRMATION agar
        tidak membanjiri chat. Return True bila pesan benar-benar terkirim.
        """
        if not self.is_configured():
            return False
        if _read_alert_mode() == "off":
            print("[Telegram] Alert dinonaktifkan (mode=off), skip pending confirmation")
            return False
        sisa = self._cooldown_remaining("PENDING_CONFIRMATION")
        if sisa > 0:
            print(f"[Telegram] Cooldown pending confirmation, "
                  f"skip ({int(sisa)}s lagi)")
            return False
        message = self.build_pending_confirmation_message(analysis)
        self._mark_sent("PENDING_CONFIRMATION")  # mulai cooldown saat dikirim
        return self._send_with_retry(message, "PENDING_CONFIRMATION")

    # ─────────────────────────────────────────
    # ESKALASI BERTINGKAT (Opsi C) — timeout konfirmasi manusia
    # ─────────────────────────────────────────
    @staticmethod
    def _analysis_bits(analysis: dict):
        """Ekstrak (fault, action, confidence%) dari dict analisis untuk pesan."""
        fault = analysis.get("dominant_fault", "UNKNOWN")
        action = (analysis.get("proposed_action")
                  or analysis.get("action_taken") or "?")
        score = analysis.get("risk_score", 0.0)
        try:
            score_pct = f"{float(score) * 100:.0f}%"
        except (TypeError, ValueError):
            score_pct = str(score)
        return fault, action, score_pct

    @staticmethod
    def build_escalation_message(level: int, analysis: dict) -> str:
        """Susun pesan eskalasi sesuai LEVEL (1 = kontak kedua, 2 = kontak ketiga).

        Pesan makin mendesak tiap level & menyebut bahwa kontak sebelumnya tidak
        merespon. Dipisah dari pengiriman agar isinya bisa diuji/ditampilkan tanpa
        jaringan. Window yang ditampilkan = ESCALATION_WINDOW_SECONDS (30 detik).
        """
        fault, action, score_pct = TelegramAlert._analysis_bits(analysis)
        window = analysis.get("confirmation_window_seconds") or 30
        if level == 1:
            lines = [
                "🟠 ESKALASI L1 — PERLU KONFIRMASI SEGERA 🟠",
                "Kontak pertama TIDAK merespon dalam 30 detik.",
                f"Fault terdeteksi: {fault}",
                f"Aksi diusulkan: {action}",
                f"Confidence: {score_pct}",
                f"Sisa window konfirmasi: {window} detik",
                "",
                "Anda kontak kedua. Buka dashboard Ethical Guardian dan KONFIRMASI "
                "atau BATALKAN aksi ini SEGERA.",
                "[AI-ORBIT Solar Monitor]",
            ]
        else:  # level 2 (dan lebih, jaga-jaga)
            lines = [
                "🔴 ESKALASI L2 — TINDAKAN MENDESAK 🔴",
                "Dua kontak sebelumnya TIDAK merespon.",
                f"Fault terdeteksi: {fault}",
                f"Aksi diusulkan: {action}",
                f"Confidence: {score_pct}",
                f"Sisa window konfirmasi: {window} detik",
                "",
                "Anda kontak ketiga (terakhir). Jika tidak ada respon, sistem akan "
                "MENGEKSEKUSI aksi ini secara OTOMATIS dalam 30 detik. Buka dashboard "
                "dan KONFIRMASI atau BATALKAN sekarang.",
                "[AI-ORBIT Solar Monitor]",
            ]
        return "\n".join(lines)

    @staticmethod
    def build_auto_executed_message(analysis: dict) -> str:
        """Susun pesan FINAL saat aksi dieksekusi otomatis (semua kontak diam)."""
        fault, action, score_pct = TelegramAlert._analysis_bits(analysis)
        lines = [
            "⛔ EKSEKUSI OTOMATIS DILAKUKAN ⛔",
            f"Sistem telah mengeksekusi {action} secara otomatis karena tidak ada "
            f"respon dari semua kontak dalam 90 detik.",
            f"Alasan: {fault} {score_pct}.",
            f"Aksi: {action}.",
            "",
            "Tinjau dashboard Ethical Guardian & audit log untuk detail.",
            "[AI-ORBIT Solar Monitor]",
        ]
        return "\n".join(lines)

    def send_escalation(self, level: int, analysis: dict) -> bool:
        """Kirim notifikasi eskalasi level-N ke kontak yang tepat.

        level 1 → TELEGRAM_CHAT_ID_2 (slot idx 1), level 2 → TELEGRAM_CHAT_ID_3
        (slot idx 2). Bila slot kosong/tak dikonfigurasi → skip dengan graceful
        (return False) — transisi level di state TETAP berlanjut. Hormati mode 'off'.
        Return True bila pesan benar-benar terkirim.
        """
        if not self.is_configured():
            return False
        if _read_alert_mode() == "off":
            print(f"[Telegram] Alert dinonaktifkan (mode=off), skip eskalasi L{level}")
            return False
        if level < 1 or level >= len(self.escalation_slots):
            return False
        target = self.escalation_slots[level]
        if not target:
            print(f"[Telegram] Eskalasi L{level}: kontak tidak dikonfigurasi, skip")
            return False
        message = self.build_escalation_message(level, analysis)
        # Retry ringan langsung ke kontak tertentu (tanpa cooldown).
        for attempt in range(1, MAX_RETRY + 1):
            if self._post_to(target, message):
                return True
            if attempt < MAX_RETRY:
                time.sleep(RETRY_DELAY)
        self._save_failed(message, "ESCALATION")
        return False

    def send_auto_executed(self, analysis: dict) -> bool:
        """Kirim pesan FINAL auto-executed ke KETIGA kontak sekaligus.

        Broadcast ke semua slot yang terisi (dedup). Hormati mode 'off'. Return
        True bila minimal satu kontak menerima pesan.
        """
        if not self.is_configured():
            return False
        if _read_alert_mode() == "off":
            print("[Telegram] Alert dinonaktifkan (mode=off), skip auto-executed")
            return False
        message = self.build_auto_executed_message(analysis)
        targets = list(dict.fromkeys(c for c in self.escalation_slots if c))
        ada_sukses = False
        for cid in targets:
            if self._post_to(cid, message):
                ada_sukses = True
        if not ada_sukses:
            self._save_failed(message, "ESCALATION")
        return ada_sukses

    # ─────────────────────────────────────────
    # RESOLUSI MANUSIA (konfirmasi / pembatalan dari dashboard)
    # ─────────────────────────────────────────
    @staticmethod
    def build_human_resolution_message(confirmed: bool, analysis: dict) -> str:
        """Susun pesan saat operator MENGONFIRMASI atau MEMBATALKAN aksi pending.

        Dipisah dari pengiriman supaya bisa diuji tanpa jaringan.
        """
        fault, action, score_pct = TelegramAlert._analysis_bits(analysis)
        if confirmed:
            lines = [
                "✅ AKSI DIKONFIRMASI OPERATOR ✅",
                f"Operator menyetujui & mengeksekusi {action}.",
                f"Kondisi: {fault} (confidence {score_pct}).",
            ]
        else:
            lines = [
                "🚫 AKSI DIBATALKAN OPERATOR 🚫",
                f"Operator membatalkan aksi {action}.",
                f"Kondisi: {fault} (confidence {score_pct}).",
            ]
        lines.append("[AI-ORBIT Solar Monitor]")
        return "\n".join(lines)

    def send_human_resolution(self, confirmed: bool, analysis: dict) -> bool:
        """Kirim notifikasi hasil resolusi manusia ke SEMUA kontak (broadcast).

        Hormati mode 'off'. Tanpa cooldown (satu peristiwa resolusi = satu pesan).
        Return True bila minimal satu kontak menerima pesan. Graceful.
        """
        if not self.is_configured():
            return False
        if _read_alert_mode() == "off":
            print("[Telegram] Alert dinonaktifkan (mode=off), skip resolusi manusia")
            return False
        message = self.build_human_resolution_message(confirmed, analysis)
        return self._send_with_retry(message, "PENDING_CONFIRMATION")

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

        # Hormati preference dari bot interaktif (bot_config.json).
        # 'off'    → matikan semua alert.
        # 'medium' → hanya MEDIUM ke atas (sama dengan default ALERT_LEVELS).
        # 'all'    → semua level yang perlu alert (default).
        mode = _read_alert_mode()
        if mode == "off":
            print(f"[Telegram] Alert dinonaktifkan (mode=off), skip {level}")
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
