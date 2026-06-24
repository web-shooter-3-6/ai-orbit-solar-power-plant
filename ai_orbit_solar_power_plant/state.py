"""
ai_orbit_solar_power_plant/state.py
────────────────────────────────────────────────────────────
State global aplikasi Reflex AI-ORBIT Solar Monitor.

Menyimpan: navigasi halaman, nilai input sensor (slider), hasil analisis
terakhir, data realtime & history, serta status sistem (model/Telegram).
Semua logic berat didelegasikan ke backend/agent_bridge.py.
"""

import asyncio
from datetime import date, datetime

import reflex as rx

from .backend.agent_bridge import (
    run_full_analysis,
    build_sensor_data,
    get_realtime_data,
    get_history_data,
    clear_history,
    get_telegram_status,
    get_guardian_audit_log,
    get_guardian_interlock,
    set_guardian_interlock,
    resolve_guardian_pending,
    mark_guardian_pending_resolved,
    escalate_pending_action,
    auto_execute_pending_action,
)

# Eskalasi bertingkat (Opsi C) — selaras dengan konstanta ethical_guardian.
# _ESC_WINDOW : durasi tiap window (detik); countdown banner = sisa window INI.
# _ESC_TOTAL  : total waktu sebelum auto-execute (3 window). Sebuah pending
#               dianggap "masih aktif" selama elapsed < _ESC_TOTAL.
_ESC_WINDOW = 30
_ESC_MAX_LEVEL = 3
_ESC_TOTAL = _ESC_WINDOW * _ESC_MAX_LEVEL  # 90

# Pagination audit log Ethical Guardian: jumlah baris per halaman.
_AUDIT_PAGE_SIZE = 25

# Peta nama atribut slider (lowercase) -> nama fitur FEATURE_ORDER (berkapital)
# yang dipahami oleh AnomalyAgent.analyze().
_SLIDER_TO_FEATURE = {
    "pv_voltage": "PV_Voltage",
    "grid_voltage": "Grid_Voltage",
    "pv_panel_temperature": "PV_Panel_Temperature",
    "sensor_latency": "Sensor_Latency",
    "battery_temperature": "Battery_Temperature",
}

# Pilihan time window untuk grafik Distribusi Fault (Realtime) → durasi (detik).
# Urutan dict dipertahankan sebagai urutan opsi dropdown.
REALTIME_FAULT_WINDOWS = {
    "1 Jam Terakhir": 3600,
    "6 Jam Terakhir": 6 * 3600,
    "24 Jam Terakhir": 24 * 3600,
    "7 Hari Terakhir": 7 * 24 * 3600,
}


class AppState(rx.State):
    """State utama aplikasi."""

    # ── Navigasi ──
    current_page: str = "live_monitor"

    # ── Nilai input sensor (slider) ──
    # FIX K2: default = rata-rata kelas 'Normal' dari dataset, sehingga state
    # awal Live Monitor (slider belum digeser) merepresentasikan kondisi normal
    # sejati → risk_score 0.0. (Sebelumnya 437/415/100 menyimpang dari normal.)
    pv_voltage: float = 420.0
    grid_voltage: float = 230.0
    pv_panel_temperature: float = 38.0
    sensor_latency: float = 20.0
    battery_temperature: float = 35.0

    # ── Hasil analisis ──
    risk_score: float = 0.0
    risk_level: str = "LOW"
    dominant_fault: str = "Normal"
    anomaly_detected: bool = False
    explanation: str = ""
    recommendations: list[str] = []
    # Disimpan sebagai list pasangan (nama_model, hasil) agar bisa dipakai
    # langsung oleh rx.foreach di tabel detail (dict TIDAK didukung foreach).
    model_details: list[tuple[str, str]] = []
    has_result: bool = False

    # ── Data realtime & history ──
    realtime_data: list[dict] = []
    history_data: list[dict] = []

    # ── Ringkasan Realtime Feed ──
    realtime_total: str = "0"
    realtime_anomali: str = "0"
    realtime_top_fault: str = "Normal"
    realtime_last_update: str = "-"
    realtime_table_rows: list[list[str]] = []
    # Grafik Distribusi Fault (Realtime): window terpilih + data agregat.
    realtime_fault_window: str = "24 Jam Terakhir"
    realtime_fault_distribution: list[dict] = []  # [{"fault": .., "count": ..}, ..]

    # ── Ringkasan Statistik & Grafik ──
    stat_total: str = "0"
    stat_anomali: str = "0"
    stat_top_fault: str = "Normal"
    fault_distribution: list[dict] = []  # [{"fault": "PV_Fault", "count": 5}, ...]
    risk_level_distribution: list[dict] = []  # [{"name": "LOW", "value": 80}, ...]

    # ── Tabel History ──
    history_table_rows: list[list[str]] = []

    # ── Demo otomatis ──
    demo_running: bool = False
    demo_results: list[list[str]] = []

    # ── Auto-refresh Realtime Feed ──
    is_refreshing: bool = False
    # Token internal (backend-only) untuk mematikan loop lama saat user
    # cepat keluar-masuk halaman; mencegah ada >1 background task aktif.
    _refresh_token: int = 0

    # ── Status sistem ──
    telegram_connected: bool = False
    model_status: str = "Loaded"

    # ── Ethical Guardian ──
    # Tabel audit: [timestamp, fault, action_type, severity, confidence_pct,
    #               reversibility, verdict, reason] (terbaru di atas).
    guardian_audit_rows: list[list[str]] = []
    guardian_has_log: bool = False
    # Pagination audit log: halaman aktif (1-based). Di-reset ke 1 tiap refresh.
    guardian_audit_page: int = 1
    guardian_blocked_today: str = "0"
    guardian_executed_today: str = "0"
    guardian_interlock_active: bool = False
    # Banner pending confirmation (aksi irreversibel menunggu manusia)
    guardian_pending_active: bool = False
    guardian_pending_action: str = ""
    guardian_pending_severity: str = ""
    guardian_pending_fault: str = ""
    guardian_pending_reason: str = ""
    guardian_pending_countdown: int = 0
    # Eskalasi bertingkat (Opsi C): 0=window awal, 1=kontak kedua dihubungi,
    # 2=kontak ketiga dihubungi, 3=auto-execute. Menggerakkan warna & teks banner.
    guardian_pending_escalation_level: int = 0
    # Badge global (terlihat dari halaman manapun via sidebar): jumlah aksi
    # pending konfirmasi yang masih dalam window & belum ditangani.
    guardian_pending_count: int = 0
    # Guard agar monitor eskalasi cross-page hanya berjalan SATU loop per sesi.
    guardian_badge_polling: bool = False
    # Internal (backend-only)
    guardian_pending_ts: str = ""
    guardian_pending_conf: float = 0.0
    _guardian_resolved: list[str] = []   # timestamp entri pending yang sudah ditangani

    @rx.var
    def guardian_has_pending(self) -> bool:
        """True bila ada minimal satu aksi menunggu konfirmasi (untuk badge sidebar)."""
        return self.guardian_pending_count > 0

    # ── Pagination audit log (25 baris/halaman) ──
    @rx.var
    def guardian_audit_total(self) -> int:
        """Jumlah total entri audit log."""
        return len(self.guardian_audit_rows)

    @rx.var
    def guardian_audit_total_pages(self) -> int:
        """Jumlah halaman (minimal 1, walau log kosong)."""
        total = len(self.guardian_audit_rows)
        if total == 0:
            return 1
        return (total + _AUDIT_PAGE_SIZE - 1) // _AUDIT_PAGE_SIZE

    @rx.var
    def guardian_audit_page_rows(self) -> list[list[str]]:
        """Slice baris audit log untuk halaman aktif (25 baris/halaman)."""
        start = (self.guardian_audit_page - 1) * _AUDIT_PAGE_SIZE
        return self.guardian_audit_rows[start:start + _AUDIT_PAGE_SIZE]

    @rx.var
    def guardian_audit_page_label(self) -> str:
        """Indikator 'Halaman X dari Y'."""
        return f"Halaman {self.guardian_audit_page} dari {self.guardian_audit_total_pages}"

    @rx.var
    def guardian_audit_range_label(self) -> str:
        """Info 'Menampilkan X-Y dari Z entri'."""
        total = len(self.guardian_audit_rows)
        if total == 0:
            return "Menampilkan 0 dari 0 entri"
        start = (self.guardian_audit_page - 1) * _AUDIT_PAGE_SIZE
        end = min(start + _AUDIT_PAGE_SIZE, total)
        return f"Menampilkan {start + 1}-{end} dari {total} entri"

    @rx.var
    def guardian_audit_on_first_page(self) -> bool:
        """True bila di halaman pertama (untuk disable tombol Sebelumnya)."""
        return self.guardian_audit_page <= 1

    @rx.var
    def guardian_audit_on_last_page(self) -> bool:
        """True bila di halaman terakhir (untuk disable tombol Berikutnya)."""
        return self.guardian_audit_page >= self.guardian_audit_total_pages

    def guardian_audit_prev_page(self):
        """Pindah ke halaman audit log sebelumnya (clamp di halaman 1)."""
        if self.guardian_audit_page > 1:
            self.guardian_audit_page -= 1

    def guardian_audit_next_page(self):
        """Pindah ke halaman audit log berikutnya (clamp di halaman terakhir)."""
        if self.guardian_audit_page < self.guardian_audit_total_pages:
            self.guardian_audit_page += 1

    # ─────────────────────────────────────────
    # Navigasi
    # ─────────────────────────────────────────
    def set_page(self, page: str):
        """Pindah halaman aktif.

        Saat MASUK ke Realtime Feed, kembalikan event auto_refresh_realtime
        agar background refresh mulai. Saat KELUAR dari Realtime Feed,
        matikan flag supaya loop yang sedang jalan berhenti.
        """
        # Hentikan auto-refresh bila meninggalkan halaman Realtime Feed.
        if self.current_page == "realtime_feed" and page != "realtime_feed":
            self.stop_refresh()
        # Catatan: countdown/eskalasi guardian kini ditangani monitor CROSS-PAGE
        # (guardian_escalation_monitor) yang berjalan sejak app dimuat, jadi tidak
        # perlu dihentikan/dimulai ulang saat berpindah halaman.
        self.current_page = page
        # Mulai auto-refresh begitu masuk halaman Realtime Feed.
        if page == "realtime_feed":
            return AppState.auto_refresh_realtime

    # ─────────────────────────────────────────
    # Auto-refresh Realtime Feed (background task)
    # ─────────────────────────────────────────
    @rx.event(background=True)
    async def auto_refresh_realtime(self):
        """Muat ulang data realtime tiap 3 detik selama di halaman Realtime Feed.

        Memakai token untuk menjamin hanya SATU loop yang aktif: tiap kali
        task baru dimulai, token dinaikkan sehingga loop lama (jika masih
        sempat tertidur) akan berhenti sendiri saat tokennya tak lagi cocok.
        """
        async with self:
            # Cegah dua task start bersamaan dari pemicu yang berbeda.
            if self.is_refreshing:
                return
            self._refresh_token += 1
            my_token = self._refresh_token
            self.is_refreshing = True

        while True:
            async with self:
                # Berhenti bila: flag dimatikan, sudah pindah halaman,
                # atau sudah ada loop yang lebih baru (token tak cocok).
                if (
                    not self.is_refreshing
                    or self.current_page != "realtime_feed"
                    or self._refresh_token != my_token
                ):
                    # Hanya matikan flag bila loop ini masih pemilik token,
                    # supaya tidak ikut mematikan loop baru yang mengambil alih.
                    if self._refresh_token == my_token:
                        self.is_refreshing = False
                    return
                self.load_realtime()
            await asyncio.sleep(3)

    def stop_refresh(self):
        """Matikan auto-refresh (dipanggil saat user pindah halaman)."""
        self.is_refreshing = False

    # ─────────────────────────────────────────
    # Input sensor
    # ─────────────────────────────────────────
    def set_sensor(self, key: str, value: list[float]):
        """Set nilai sensor dari rx.slider (nilainya berupa list, ambil [0])."""
        if isinstance(value, (list, tuple)) and value:
            setattr(self, key, float(value[0]))
        else:
            # Antisipasi bila nilai dikirim sebagai skalar
            try:
                setattr(self, key, float(value))
            except (TypeError, ValueError):
                pass

    # ── Setter spesifik per sensor (dibutuhkan rx.slider on_change) ──
    # rx.slider mengirim nilai berupa list, jadi ambil elemen pertama [0].
    def set_pv_voltage(self, value: list[float]):
        """Set tegangan PV (V) dari slider."""
        self.pv_voltage = value[0]

    def set_grid_voltage(self, value: list[float]):
        """Set tegangan grid (V) dari slider."""
        self.grid_voltage = value[0]

    def set_pv_panel_temperature(self, value: list[float]):
        """Set suhu panel PV (°C) dari slider."""
        self.pv_panel_temperature = value[0]

    def set_sensor_latency(self, value: list[float]):
        """Set latensi sensor (ms) dari slider."""
        self.sensor_latency = value[0]

    def set_battery_temperature(self, value: list[float]):
        """Set suhu baterai (°C) dari slider."""
        self.battery_temperature = value[0]

    # ─────────────────────────────────────────
    # Analisis
    # ─────────────────────────────────────────
    def run_analysis(self):
        """Jalankan analisis lengkap berdasarkan nilai sensor saat ini."""
        sensor_data = self._build_sensor_dict()
        result = run_full_analysis(sensor_data)

        self.risk_score = result.get("risk_score", 0.0)
        self.risk_level = result.get("risk_level", "LOW")
        self.dominant_fault = result.get("dominant_fault", "Normal")
        self.anomaly_detected = result.get("anomaly_detected", False)
        self.explanation = result.get("explanation", "")
        self.recommendations = result.get("recommendations", [])

        # predictions dari agent berbentuk dict {"XGBoost": "Normal", ...}.
        # rx.foreach tidak mendukung dict, jadi diubah ke list pasangan
        # (nama_model, hasil) dengan nilai dipaksa menjadi string.
        predictions = result.get("predictions", {}) or {}
        if isinstance(predictions, dict):
            self.model_details = [(str(k), str(v)) for k, v in predictions.items()]
        else:
            self.model_details = []

        self.has_result = True

    def _build_sensor_dict(self) -> dict:
        """Susun dict 49 fitur untuk agent.

        Fitur yang tidak diatur slider memakai nilai rata-rata dataset
        (dihitung di agent_bridge.build_sensor_data). Lima nilai dari slider
        di-override menggunakan nama fitur FEATURE_ORDER yang benar.
        """
        overrides = {
            _SLIDER_TO_FEATURE["pv_voltage"]: self.pv_voltage,
            _SLIDER_TO_FEATURE["grid_voltage"]: self.grid_voltage,
            _SLIDER_TO_FEATURE["pv_panel_temperature"]: self.pv_panel_temperature,
            _SLIDER_TO_FEATURE["sensor_latency"]: self.sensor_latency,
            _SLIDER_TO_FEATURE["battery_temperature"]: self.battery_temperature,
        }
        return build_sensor_data(overrides)

    # ─────────────────────────────────────────
    # Demo otomatis (6 skenario anomali berurutan)
    # ─────────────────────────────────────────
    # Nama fitur memakai FEATURE_ORDER (berkapital) agar dipahami agent.
    _DEMO_SCENARIOS = [
        ("Normal", {}),
        ("PV_Fault", {"PV_Voltage": 150, "PV_Current": 2}),
        ("Battery_Overheating", {"Battery_Temperature": 85, "Battery_SOC": 10}),
        ("Grid_Instability", {"Grid_Voltage": 550, "Grid_Frequency": 47.2}),
        ("Inverter_Fault", {"PV_AC_Power": 0.5, "PV_Inverter_Temperature": 90}),
        ("Communication_Failure", {"Sensor_Latency": 9000, "Packet_Loss_Rate": 0.95}),
    ]

    def run_demo(self):
        """Jalankan 6 skenario anomali berurutan dan kumpulkan hasilnya."""
        self.demo_running = True
        self.demo_results = []
        # Yield agar UI menampilkan status "Menjalankan demo..." lebih dulu.
        yield

        results: list[list[str]] = []
        for _name, overrides in self._DEMO_SCENARIOS:
            sensor_data = build_sensor_data(overrides)
            result = run_full_analysis(sensor_data)
            results.append([
                str(result.get("dominant_fault", "Normal")),
                str(result.get("risk_level", "LOW")),
                str(result.get("risk_score", 0.0)),
            ])

        self.demo_results = results
        self.demo_running = False

    # ─────────────────────────────────────────
    # Data realtime & history
    # ─────────────────────────────────────────
    @staticmethod
    def _entry_to_row(entry: dict) -> list[str]:
        """Ubah satu entri analisis menjadi baris tabel [waktu, skor, level, fault]."""
        return [
            str(entry.get("timestamp", "-")),
            str(entry.get("risk_score", 0.0)),
            str(entry.get("risk_level", "-")),
            str(entry.get("dominant_fault", "-")),
        ]

    @staticmethod
    def _top_fault(entries: list[dict]) -> str:
        """Cari dominant_fault paling sering. 'Normal' diabaikan bila ada fault lain."""
        counts: dict[str, int] = {}
        for e in entries:
            fault = str(e.get("dominant_fault", "Normal"))
            counts[fault] = counts.get(fault, 0) + 1
        if not counts:
            return "Normal"
        # Buang 'Normal' bila masih ada jenis fault lain
        non_normal = {k: v for k, v in counts.items() if k != "Normal"}
        pool = non_normal if non_normal else counts
        return max(pool, key=pool.get)

    @staticmethod
    def _is_anomaly(entry: dict) -> bool:
        """Entri dianggap anomali bila flag-nya True atau risk_score > 0.25."""
        if entry.get("anomaly_detected") is True:
            return True
        try:
            return float(entry.get("risk_score", 0.0)) > 0.25
        except (TypeError, ValueError):
            return False

    def load_realtime(self):
        """Muat ulang data realtime + hitung ringkasan untuk Realtime Feed."""
        data = get_realtime_data()
        self.realtime_data = data

        self.realtime_total = str(len(data))
        self.realtime_anomali = str(sum(1 for e in data if self._is_anomaly(e)))
        self.realtime_top_fault = self._top_fault(data)
        self.realtime_last_update = (
            str(data[-1].get("timestamp", "-")) if data else "-"
        )
        # 10 entri terakhir (terbaru di atas)
        last10 = data[-10:][::-1]
        self.realtime_table_rows = [self._entry_to_row(e) for e in last10]

        # Grafik distribusi fault dalam time window terpilih (auto-update tiap refresh).
        self._compute_realtime_fault_distribution()

    def _compute_realtime_fault_distribution(self):
        """Hitung distribusi fault dari realtime_data dalam time window terpilih.

        Memfilter entri berdasarkan selisih waktu (now - timestamp) ≤ window, lalu
        menghitung kemunculan tiap dominant_fault (termasuk Normal), terurut menurun.
        Entri dengan timestamp tak-terbaca di-skip dengan graceful.
        """
        window = REALTIME_FAULT_WINDOWS.get(self.realtime_fault_window, 24 * 3600)
        now = datetime.now()
        counts: dict[str, int] = {}
        for e in self.realtime_data:
            ts = e.get("timestamp")
            try:
                started = datetime.fromisoformat(str(ts))
            except (ValueError, TypeError):
                continue
            try:
                if (now - started).total_seconds() > window:
                    continue
            except TypeError:
                # timestamp tz-aware vs now() naive → abaikan entri ini.
                continue
            fault = str(e.get("dominant_fault", "Normal"))
            counts[fault] = counts.get(fault, 0) + 1
        self.realtime_fault_distribution = [
            {"fault": k, "count": v}
            for k, v in sorted(counts.items(), key=lambda x: -x[1])
        ]

    def set_realtime_fault_window(self, value: str):
        """Ganti time window grafik Distribusi Fault & hitung ulang seketika."""
        self.realtime_fault_window = value
        self._compute_realtime_fault_distribution()

    def load_history(self):
        """Muat ulang riwayat analisis + hitung statistik & tabel History."""
        data = get_history_data()
        self.history_data = data

        # Ringkasan Statistik
        self.stat_total = str(len(data))
        self.stat_anomali = str(sum(1 for e in data if self._is_anomaly(e)))
        self.stat_top_fault = self._top_fault(data)

        # Distribusi fault (semua jenis, termasuk Normal)
        fault_counts: dict[str, int] = {}
        for e in data:
            fault = str(e.get("dominant_fault", "Normal"))
            fault_counts[fault] = fault_counts.get(fault, 0) + 1
        self.fault_distribution = [
            {"fault": k, "count": v}
            for k, v in sorted(fault_counts.items(), key=lambda x: -x[1])
        ]

        # Distribusi risk level
        level_counts: dict[str, int] = {}
        for e in data:
            level = str(e.get("risk_level", "-"))
            level_counts[level] = level_counts.get(level, 0) + 1
        self.risk_level_distribution = [
            {"name": k, "value": v} for k, v in level_counts.items()
        ]

        # Tabel History (semua entri, terbaru di atas)
        self.history_table_rows = [self._entry_to_row(e) for e in data[::-1]]

    def clear_history_data(self):
        """Kosongkan riwayat analisis (file + state) lalu muat ulang ringkasan."""
        clear_history()
        self.history_data = []
        self.load_history()

    # ─────────────────────────────────────────
    # Status sistem
    # ─────────────────────────────────────────
    def check_telegram(self):
        """Perbarui status koneksi Telegram."""
        status = get_telegram_status()
        self.telegram_connected = status.get("configured", False)

    # ─────────────────────────────────────────
    # Ethical Guardian
    # ─────────────────────────────────────────
    def load_guardian(self):
        """Muat audit log guardian + counter harian + status interlock + pending.

        Dipanggil saat halaman Ethical Guardian dimuat (on_mount) dan oleh tombol
        Refresh. Mengevaluasi pending (termasuk auto-execute zombie dari sesi lama)
        & memastikan monitor eskalasi cross-page berjalan.
        """
        log = get_guardian_audit_log()  # terlama→terbaru, dict diperkaya
        self.guardian_has_log = len(log) > 0
        # Pagination: selalu kembali ke halaman 1 saat audit log dimuat ulang.
        self.guardian_audit_page = 1

        # Tabel: terbaru di atas → list[list[str]] sesuai pola tabel lain.
        # Kolom "fault" disisipkan setelah timestamp untuk transparansi kondisi.
        # Dua kolom terakhir (eskalasi, outcome) mendukung Opsi C.
        self.guardian_audit_rows = [
            [
                e["timestamp"], e["fault"], e["action_type"], e["severity"],
                e["confidence_pct"], e["reversibility"], e["verdict"], e["reason"],
                str(e["escalation_level"]), e["final_outcome"],
            ]
            for e in reversed(log)
        ]

        # Counter "hari ini" berdasarkan tanggal pada timestamp ISO.
        today = date.today().isoformat()
        self.guardian_blocked_today = str(sum(
            1 for e in log
            if e["verdict"] == "BLOCKED" and e["timestamp"].startswith(today)
        ))
        self.guardian_executed_today = str(sum(
            1 for e in log
            if e["verdict"] == "EXECUTE" and e["timestamp"].startswith(today)
        ))

        # Status toggle interlock (dari config file backend).
        self.guardian_interlock_active = get_guardian_interlock()

        # Segarkan badge global (jumlah pending) dari log yang baru dimuat.
        self._refresh_pending_count(log)

        # Evaluasi pending: set tampilan, picu transisi eskalasi yang terlewat,
        # atau auto-execute bila window total sudah habis (termasuk "zombie
        # pending" dari sesi sebelumnya saat app restart).
        self._evaluate_escalation(log)

        # Pastikan monitor eskalasi cross-page berjalan (guard membuatnya idempoten).
        return AppState.guardian_escalation_monitor

    def _find_active_pending(self, log: list[dict]):
        """Cari entri REQUIRE_HUMAN_CONFIRMATION TERBARU yang belum diresolusi
        (final_outcome masih "pending") & belum ditandai resolved di sesi ini.

        Return (entry_dict, elapsed_seconds) atau None. elapsed bisa >= total
        (menandakan perlu auto-execute / zombie).
        """
        now = datetime.now()
        found = None
        for e in log:  # terlama→terbaru: ambil yang paling baru yang cocok
            if e["verdict"] != "REQUIRE_HUMAN_CONFIRMATION":
                continue
            if e.get("final_outcome") != "pending":
                continue  # sudah diresolusi manusia / auto-executed
            ts = e["timestamp"]
            if ts in self._guardian_resolved:
                continue
            try:
                started = datetime.fromisoformat(ts)
            except (ValueError, TypeError):
                continue
            found = (e, (now - started).total_seconds())
        return found

    def _apply_pending_display(self, entry: dict, elapsed: float) -> int:
        """Set state banner dari entri pending + elapsed. Countdown = sisa window
        SAAT INI (reset tiap naik level). Return level eskalasi saat ini (0/1/2)."""
        level = min(int(elapsed // _ESC_WINDOW), _ESC_MAX_LEVEL - 1)
        self.guardian_pending_active = True
        self.guardian_pending_ts = entry["timestamp"]
        self.guardian_pending_action = entry["action_type"]
        self.guardian_pending_severity = entry["severity"]
        self.guardian_pending_fault = entry["fault"]
        self.guardian_pending_reason = entry["reason"]
        self.guardian_pending_conf = entry["confidence"]
        self.guardian_pending_countdown = _ESC_WINDOW - int(elapsed) % _ESC_WINDOW
        self.guardian_pending_escalation_level = level
        return level

    def _evaluate_escalation(self, log: list[dict]):
        """Versi SINKRON (dipakai load_guardian): set tampilan + picu transisi
        eskalasi yang terlewat, atau auto-execute bila window total habis.

        Monitor background memakai logika setara tetapi melakukan I/O di LUAR lock
        (lihat guardian_escalation_monitor)."""
        found = self._find_active_pending(log)
        if found is None:
            self._clear_pending()
            return
        entry, elapsed = found
        if elapsed >= _ESC_TOTAL:
            # Window total habis → eksekusi otomatis (juga menangani zombie pending).
            self._guardian_resolved.append(entry["timestamp"])
            self._clear_pending()
            auto_execute_pending_action(entry)
            return
        level = self._apply_pending_display(entry, elapsed)
        stored = int(entry.get("escalation_level", 0) or 0)
        for lvl in range(stored + 1, level + 1):
            escalate_pending_action(entry, lvl)

    def _clear_pending(self):
        """Reset seluruh state banner pending."""
        self.guardian_pending_active = False
        self.guardian_pending_ts = ""
        self.guardian_pending_action = ""
        self.guardian_pending_severity = ""
        self.guardian_pending_fault = ""
        self.guardian_pending_reason = ""
        self.guardian_pending_conf = 0.0
        self.guardian_pending_countdown = 0
        self.guardian_pending_escalation_level = 0

    def toggle_interlock(self, value: bool):
        """Aktifkan/nonaktifkan Safety Interlock (Maintenance Mode).

        Benar-benar mengubah nilai yang dibaca check_safety_interlock() di backend
        (persist ke guardian_config.json), bukan sekadar UI.
        """
        set_guardian_interlock(value)
        self.guardian_interlock_active = value

    def _resolve_pending_group(self, confirmed: bool):
        """Resolusi SELURUH grup pending yang ditampilkan banner (Konfirmasi/Batal).

        FIX (tombol tidak berfungsi): satu situasi fault yang berlangsung memicu
        BANYAK entri REQUIRE_HUMAN_CONFIRMATION beruntun (worker realtime). Badge &
        banner men-dedup-nya jadi SATU permintaan, tetapi versi lama hanya menutup
        SATU timestamp — sehingga monitor langsung menampilkan ulang banner dengan
        entri pending berikutnya dan tombol seolah "tidak berfungsi".

        Kini SATU klik menutup seluruh grup pending dengan (action_type, fault) yang
        sama yang masih aktif: satu baris resolusi kanonik dicatat untuk entri yang
        ditampilkan (resolve_guardian_pending), sisanya cukup ditandai final_outcome
        (mark_guardian_pending_resolved) agar tidak muncul lagi.
        """
        shown_ts = self.guardian_pending_ts
        shown_action = self.guardian_pending_action
        shown_fault = self.guardian_pending_fault

        # Catat SATU baris resolusi kanonik untuk entri yang sedang ditampilkan.
        resolve_guardian_pending(
            shown_action, self.guardian_pending_severity,
            self.guardian_pending_conf, confirmed,
            fault_detected=shown_fault,
            pending_timestamp=shown_ts,
            escalation_level=self.guardian_pending_escalation_level,
        )
        self._guardian_resolved.append(shown_ts)

        # Tutup entri pending lain di grup yang sama (action_type + fault) yang
        # masih aktif & belum diresolusi — cukup tandai final_outcome (tanpa baris
        # resolusi ganda). Ini yang membuat banner benar-benar hilang setelah klik.
        now = datetime.now()
        for e in get_guardian_audit_log():
            if e["verdict"] != "REQUIRE_HUMAN_CONFIRMATION":
                continue
            if e.get("final_outcome") != "pending":
                continue
            ts = e["timestamp"]
            if ts in self._guardian_resolved:
                continue
            if e["action_type"] != shown_action or e["fault"] != shown_fault:
                continue
            try:
                started = datetime.fromisoformat(ts)
            except (ValueError, TypeError):
                continue
            if (now - started).total_seconds() >= _ESC_TOTAL:
                continue  # sudah lewat window total → biarkan monitor auto-execute
            mark_guardian_pending_resolved(
                ts, confirmed, escalation_level=self.guardian_pending_escalation_level
            )
            self._guardian_resolved.append(ts)

        self._clear_pending()
        self.load_guardian()

    def confirm_pending(self):
        """Operator menyetujui eksekusi aksi pending → catat & bersihkan banner.

        Menutup seluruh grup pending (final_outcome="human_confirmed") sehingga
        eskalasi bertingkat berhenti & banner hilang. Lihat _resolve_pending_group.
        """
        self._resolve_pending_group(True)

    def cancel_pending(self):
        """Operator membatalkan aksi pending → catat & bersihkan banner.

        Menutup seluruh grup pending (final_outcome="human_cancelled", stop eskalasi).
        """
        self._resolve_pending_group(False)

    # ─────────────────────────────────────────
    # Badge global pending (terlihat dari halaman manapun via sidebar)
    # ─────────────────────────────────────────
    def _refresh_pending_count(self, log=None):
        """Hitung jumlah aksi pending konfirmasi yang masih dalam window TOTAL
        eskalasi (90 detik) & belum diresolusi, lalu set guardian_pending_count
        (sumber badge sidebar).

        Dideduplikasi per (action_type, fault) agar satu situasi fault yang
        memicu PULUHAN entri beruntun (perilaku worker realtime) tetap tampil
        sebagai SATU permintaan konfirmasi, bukan angka yang membengkak.
        """
        if log is None:
            log = get_guardian_audit_log()
        now = datetime.now()
        aktif = set()
        for e in log:
            if e["verdict"] != "REQUIRE_HUMAN_CONFIRMATION":
                continue
            if e.get("final_outcome") != "pending":
                continue
            ts = e["timestamp"]
            if ts in self._guardian_resolved:
                continue
            try:
                started = datetime.fromisoformat(ts)
            except (ValueError, TypeError):
                continue
            if (now - started).total_seconds() < _ESC_TOTAL:
                aktif.add((e["action_type"], e["fault"]))
        self.guardian_pending_count = len(aktif)

    @rx.event(background=True)
    async def guardian_escalation_monitor(self):
        """Monitor eskalasi bertingkat CROSS-PAGE (Opsi C), tiap 1 detik.

        Dipanggil saat aplikasi dimuat (on_load route "/") sehingga badge sidebar
        AKURAT & eskalasi BERJALAN di halaman manapun, bukan hanya saat membuka
        Ethical Guardian. Guard `guardian_badge_polling` memastikan hanya satu
        loop per sesi (sekali aktif, tetap aktif selama sesi).

        Setiap detik: segarkan badge, hitung level eskalasi dari elapsed
        (= now - timestamp pending, server-side & persisten → akurat walau
        refresh/pindah halaman), dan picu transisi yang terlewat. I/O Telegram +
        tulis audit log dilakukan DI LUAR `async with self` agar UI tak membeku.
        """
        async with self:
            if self.guardian_badge_polling:
                return
            self.guardian_badge_polling = True

        while True:
            transitions = []      # daftar (entry, level) yang perlu dieskalasi
            auto_exec_entry = None
            async with self:
                log = get_guardian_audit_log()
                self._refresh_pending_count(log)
                found = self._find_active_pending(log)
                if found is None:
                    self._clear_pending()
                else:
                    entry, elapsed = found
                    if elapsed >= _ESC_TOTAL:
                        self._guardian_resolved.append(entry["timestamp"])
                        self._clear_pending()
                        auto_exec_entry = entry
                    else:
                        level = self._apply_pending_display(entry, elapsed)
                        stored = int(entry.get("escalation_level", 0) or 0)
                        transitions = [
                            (entry, lvl) for lvl in range(stored + 1, level + 1)
                        ]
            # ── I/O di luar lock (network + tulis file) ──
            for entry, lvl in transitions:
                escalate_pending_action(entry, lvl)
            if auto_exec_entry is not None:
                auto_execute_pending_action(auto_exec_entry)
            await asyncio.sleep(1)
