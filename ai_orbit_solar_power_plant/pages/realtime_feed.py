"""
ai_orbit_solar_power_plant/pages/realtime_feed.py
────────────────────────────────────────────────────────────
Halaman Realtime Feed: ringkasan data realtime (grid metrik) dan
tabel 10 analisis terakhir, dimuat dari realtime_results.json.
Auto-refresh dipicu lewat AppState.set_page("realtime_feed").

Gaya "Modern Minimalist": metrik tanpa kotak, tabel garis tipis.
"""

import reflex as rx

from ..state import AppState
from ..components.theme import (
    COLORS,
    page_header,
    stat_value,
    section_divider,
    analysis_table,
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
        rx.text(
            "10 Analisis Terakhir",
            font_size="11px",
            letter_spacing="2px",
            text_transform="uppercase",
            color=COLORS["text_secondary"],
        ),
        analysis_table(AppState.realtime_table_rows),
        spacing="6",
        width="100%",
        max_width="1100px",
    )


print("[realtime_feed] OK - Halaman Realtime Feed di-restyle (Modern Minimalist)")
