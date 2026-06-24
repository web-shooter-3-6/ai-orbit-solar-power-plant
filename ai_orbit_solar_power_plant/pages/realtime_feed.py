"""
ai_orbit_solar_power_plant/pages/realtime_feed.py
────────────────────────────────────────────────────────────
Halaman Realtime Feed: ringkasan data realtime (grid metrik) dan
tabel 10 analisis terakhir, dimuat dari realtime_results.json.
Auto-refresh dipicu lewat AppState.set_page("realtime_feed").

Gaya "Modern Minimalist": metrik tanpa kotak, tabel garis tipis.
"""

import reflex as rx

from ..state import AppState, REALTIME_FAULT_WINDOWS
from ..components.theme import (
    COLORS,
    PAGE_MAX_WIDTH,
    page_header,
    stat_value,
    section_divider,
    section_label,
    analysis_table,
)


def _realtime_fault_chart() -> rx.Component:
    """Bar chart distribusi fault realtime dalam time window terpilih.

    Gaya konsisten dengan grafik di halaman Statistik & Grafik (warna aksen hijau,
    grid & teks abu-abu). Dropdown memilih jendela waktu; data di-recompute tiap
    refresh realtime (3 detik) maupun saat window diganti.
    """
    return rx.box(
        rx.hstack(
            section_label("Distribusi Fault (Realtime)", margin_bottom="0"),
            rx.spacer(),
            rx.select(
                list(REALTIME_FAULT_WINDOWS.keys()),
                value=AppState.realtime_fault_window,
                on_change=AppState.set_realtime_fault_window,
                size="1",
            ),
            width="100%",
            align="center",
            margin_bottom="0.75em",
        ),
        rx.cond(
            AppState.realtime_fault_distribution.length() > 0,
            rx.recharts.bar_chart(
                rx.recharts.cartesian_grid(
                    stroke=COLORS["border"], stroke_dasharray="3 3"
                ),
                rx.recharts.bar(data_key="count", fill=COLORS["accent"]),
                rx.recharts.x_axis(
                    data_key="fault", stroke=COLORS["text_secondary"]
                ),
                rx.recharts.y_axis(stroke=COLORS["text_secondary"], allow_decimals=False),
                rx.recharts.graphing_tooltip(),
                data=AppState.realtime_fault_distribution,
                width="100%",
                height=300,
            ),
            rx.text(
                "Belum ada data realtime pada rentang waktu ini.",
                color=COLORS["text_tertiary"],
                size="2",
                padding_y="2em",
            ),
        ),
        width="100%",
    )


def realtime_feed_page() -> rx.Component:
    """Susun halaman Realtime Feed lengkap."""
    return rx.vstack(
        page_header("Realtime feed", "Live data"),
        rx.button(
            rx.icon("refresh-cw", size=14),
            "Refresh Data",
            on_click=AppState.load_realtime,
            variant="outline",
            color_scheme="gray",
            size="1",
        ),
        # Grid metrik tanpa kotak
        rx.grid(
            # Field sudah bertipe str; JANGAN .to_string() (akan menambah kutip).
            stat_value("Total Realtime", AppState.realtime_total),
            stat_value("Anomali", AppState.realtime_anomali, color=COLORS["high"]),
            stat_value("Fault Tersering", AppState.realtime_top_fault, size="4"),
            stat_value("Last Update", AppState.realtime_last_update, size="4"),
            columns="4",
            spacing="6",
            width="100%",
        ),
        section_divider(),
        # Tabel 10 analisis terbaru
        section_label("10 Analisis Terakhir", margin_bottom="0"),
        analysis_table(AppState.realtime_table_rows),
        section_divider(),
        # Grafik distribusi fault realtime (di bawah tabel feed).
        _realtime_fault_chart(),
        spacing="6",
        width="100%",
        max_width=PAGE_MAX_WIDTH,
    )


print("[realtime_feed] OK - Halaman Realtime Feed di-restyle (Modern Minimalist)")
