"""
ai_orbit_solar_power_plant/state.py
────────────────────────────────────────────────────────────
State global aplikasi Reflex AI-ORBIT Solar Monitor.

Menyimpan: navigasi halaman, nilai input sensor (slider), hasil analisis
terakhir, data realtime & history, serta status sistem (model/Telegram).
Semua logic berat didelegasikan ke backend/agent_bridge.py.
"""

import asyncio

import reflex as rx

from .backend.agent_bridge import (
    run_full_analysis,
    build_sensor_data,
    get_realtime_data,
    get_history_data,
    clear_history,
    get_telegram_status,
)

# Peta nama atribut slider (lowercase) -> nama fitur FEATURE_ORDER (berkapital)
# yang dipahami oleh AnomalyAgent.analyze().
_SLIDER_TO_FEATURE = {
    "pv_voltage": "PV_Voltage",
    "grid_voltage": "Grid_Voltage",
    "pv_panel_temperature": "PV_Panel_Temperature",
    "sensor_latency": "Sensor_Latency",
    "battery_temperature": "Battery_Temperature",
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
