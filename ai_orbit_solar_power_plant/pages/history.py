"""
ai_orbit_solar_power_plant/pages/history.py
────────────────────────────────────────────────────────────
Halaman History Anomali: tabel seluruh riwayat analisis dari
history.json, dengan tombol Refresh dan Clear History.

Gaya "Modern Minimalist": tombol outline, tabel garis tipis.
"""

import reflex as rx

from ..state import AppState
from ..components.theme import PAGE_MAX_WIDTH, page_header, analysis_table


def history_page() -> rx.Component:
    """Susun halaman History Anomali lengkap."""
    return rx.vstack(
        page_header("History", "Riwayat anomali"),
        rx.hstack(
            rx.button(
                rx.icon("refresh-cw", size=14),
                "Refresh",
                on_click=AppState.load_history,
                variant="outline",
                color_scheme="gray",
                size="1",
            ),
            rx.button(
                rx.icon("trash-2", size=14),
                "Clear History",
                on_click=AppState.clear_history_data,
                variant="outline",
                color_scheme="red",
                size="1",
            ),
            spacing="3",
        ),
        analysis_table(AppState.history_table_rows),
        on_mount=AppState.load_history,
        spacing="6",
        width="100%",
        max_width=PAGE_MAX_WIDTH,
    )


print("[history] OK - Halaman History Anomali di-restyle (Modern Minimalist)")
