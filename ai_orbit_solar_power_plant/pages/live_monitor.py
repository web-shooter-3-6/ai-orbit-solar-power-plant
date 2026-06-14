"""
ai_orbit_solar_power_plant/pages/live_monitor.py
────────────────────────────────────────────────────────────
Halaman Live Monitor: input nilai sensor manual lewat slider,
lalu menjalankan analisis multi-model dan menampilkan hasilnya.

Gaya "Modern Minimalist": Risk Score sebagai angka fokus besar,
metrik dalam grid tanpa kotak, akordeon minimal. Fungsi analisis
tidak berubah (lihat AppState.run_analysis).
"""

import reflex as rx

from ..state import AppState
from ..components.theme import (
    COLORS,
    FONT_MONO,
    page_header,
    stat_value,
    section_divider,
    level_color,
)


# ─────────────────────────────────────────────────────────
# Baris slider sensor (label uppercase kecil + nilai besar)
# ─────────────────────────────────────────────────────────
def slider_card(label, value, on_change, min_v, max_v, unit) -> rx.Component:
    """Satu baris slider: label uppercase + nilai monospace besar + slider."""
    return rx.vstack(
        rx.hstack(
            rx.text(
                label,
                font_size="11px",
                letter_spacing="1px",
                text_transform="uppercase",
                color=COLORS["text_secondary"],
            ),
            rx.text(
                value.to_string() + " " + unit,
                font_size="24px",
                weight="medium",
                color=COLORS["accent"],
                font_family=FONT_MONO,
            ),
            justify="between",
            align="center",
            width="100%",
        ),
        rx.slider(
            default_value=[value],
            min=min_v,
            max=max_v,
            on_change=lambda v: on_change(v),
            width="100%",
        ),
        width="100%",
        spacing="2",
    )


# ─────────────────────────────────────────────────────────
# Risk Score sebagai angka fokus besar (kiri) + ringkasan (kanan)
# ─────────────────────────────────────────────────────────
def risk_score_section() -> rx.Component:
    """Angka risk score 56px di kiri, tingkat & fault di kanan."""
    color = level_color(AppState.risk_level)
    return rx.hstack(
        rx.vstack(
            rx.text(
                "Risk score",
                font_size="11px",
                letter_spacing="2px",
                text_transform="uppercase",
                color=COLORS["text_secondary"],
            ),
            rx.text(
                AppState.risk_score.to_string(),
                font_size="56px",
                weight="medium",
                line_height="1",
                color=COLORS["text_primary"],
                font_family=FONT_MONO,
            ),
            spacing="2",
            align="start",
        ),
        rx.vstack(
            rx.text(
                AppState.risk_level + " risk",
                font_size="13px",
                weight="medium",
                letter_spacing="1px",
                text_transform="uppercase",
                color=color,
            ),
            rx.text(
                AppState.dominant_fault + " terdeteksi",
                font_size="13px",
                color=COLORS["text_secondary"],
            ),
            spacing="1",
            align="start",
        ),
        spacing="6",
        align="center",
        width="100%",
    )


# ─────────────────────────────────────────────────────────
# Grid 4 metrik tanpa kotak (memakai stat_value)
# ─────────────────────────────────────────────────────────
def metrics_grid() -> rx.Component:
    """Empat metrik hasil analisis dalam grid 4 kolom."""
    return rx.grid(
        stat_value("Fault", AppState.dominant_fault, size="4"),
        stat_value(
            "Anomaly",
            rx.cond(AppState.anomaly_detected, "YA", "TIDAK"),
            size="4",
        ),
        stat_value(
            "Urgency",
            AppState.risk_level,
            color=level_color(AppState.risk_level),
            size="4",
        ),
        stat_value("Komponen", AppState.dominant_fault, size="4"),
        columns="4",
        spacing="6",
        width="100%",
    )


# ─────────────────────────────────────────────────────────
# Tabel detail per model
# ─────────────────────────────────────────────────────────
def model_details_table() -> rx.Component:
    """Tabel hasil tiap model AI (XGBoost, Isolation Forest, dst)."""
    return rx.table.root(
        rx.table.header(
            rx.table.row(
                rx.table.column_header_cell(
                    "Model",
                    font_size="11px",
                    letter_spacing="1px",
                    text_transform="uppercase",
                    color=COLORS["text_secondary"],
                ),
                rx.table.column_header_cell(
                    "Hasil",
                    font_size="11px",
                    letter_spacing="1px",
                    text_transform="uppercase",
                    color=COLORS["text_secondary"],
                ),
            )
        ),
        rx.table.body(
            rx.foreach(
                AppState.model_details,
                lambda item: rx.table.row(
                    rx.table.cell(item[0]),
                    rx.table.cell(item[1], font_family=FONT_MONO),
                ),
            )
        ),
        variant="ghost",
        width="100%",
    )


# ─────────────────────────────────────────────────────────
# Daftar rekomendasi tindakan
# ─────────────────────────────────────────────────────────
def recommendations_list() -> rx.Component:
    """Daftar rekomendasi tindakan dari DecisionEngine."""
    return rx.vstack(
        rx.foreach(
            AppState.recommendations,
            lambda rec: rx.hstack(
                rx.icon("chevron-right", size=14, color=COLORS["accent"]),
                rx.text(rec, color=COLORS["text_primary"]),
                align="center",
            ),
        ),
        align="start",
        spacing="2",
    )


# ─────────────────────────────────────────────────────────
# Bagian hasil analisis (tampil kondisional setelah analisis)
# ─────────────────────────────────────────────────────────
def result_section() -> rx.Component:
    """Bagian hasil: Risk Score fokus, grid metrik, dan akordeon minimal."""
    return rx.vstack(
        risk_score_section(),
        section_divider(),
        metrics_grid(),
        section_divider(),
        # Akordeon minimal (varian ghost, tanpa fill saat tertutup)
        rx.accordion.root(
            rx.accordion.item(
                header="Detail per Model",
                content=model_details_table(),
            ),
            rx.accordion.item(
                header="Rekomendasi",
                content=recommendations_list(),
            ),
            rx.accordion.item(
                header="Penjelasan",
                content=rx.text(AppState.explanation, color=COLORS["text_secondary"]),
            ),
            collapsible=True,
            variant="ghost",
            width="100%",
        ),
        spacing="6",
        width="100%",
        margin_top="1.5em",
    )


# ─────────────────────────────────────────────────────────
# Halaman Live Monitor (komponen utama)
# ─────────────────────────────────────────────────────────
def live_monitor_page() -> rx.Component:
    """Susun halaman Live Monitor lengkap."""
    return rx.vstack(
        page_header("Live monitor", "Status sistem"),
        rx.text(
            "Masukkan nilai sensor manual lalu jalankan analisis multi-model.",
            color=COLORS["text_secondary"],
            size="2",
        ),
        # Section slider (kontainer halus, border 0.5px)
        rx.box(
            rx.grid(
                slider_card(
                    "PV Voltage", AppState.pv_voltage,
                    AppState.set_pv_voltage, 100, 600, "V",
                ),
                slider_card(
                    "Grid Voltage", AppState.grid_voltage,
                    AppState.set_grid_voltage, 200, 600, "V",
                ),
                slider_card(
                    "PV Panel Temperature", AppState.pv_panel_temperature,
                    AppState.set_pv_panel_temperature, 10, 100, "°C",
                ),
                slider_card(
                    "Sensor Latency", AppState.sensor_latency,
                    AppState.set_sensor_latency, 0, 10000, "ms",
                ),
                slider_card(
                    "Battery Temperature", AppState.battery_temperature,
                    AppState.set_battery_temperature, 10, 100, "°C",
                ),
                columns="2",
                spacing="6",
                width="100%",
            ),
            border="0.5px solid " + COLORS["border"],
            border_radius="12px",
            padding="1.75em",
            bg=COLORS["bg_secondary"],
            width="100%",
        ),
        # Tombol analisis (minimal, outline)
        rx.button(
            rx.icon("cpu", size=16),
            "Analisis Sekarang",
            on_click=AppState.run_analysis,
            size="3",
            width="100%",
            variant="outline",
            color_scheme="green",
        ),
        # Hasil analisis - tampil kondisional
        rx.cond(
            AppState.has_result,
            result_section(),
            rx.box(),
        ),
        spacing="6",
        width="100%",
        max_width="900px",
    )


print("[live_monitor] OK - Halaman Live Monitor di-restyle (Modern Minimalist)")
