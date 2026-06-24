"""
ai_orbit_solar_power_plant/pages/demo.py
────────────────────────────────────────────────────────────
Halaman Demo Otomatis: menjalankan 6 skenario anomali berurutan
lalu menampilkan hasilnya. Fungsi run_demo tidak berubah.

Gaya "Modern Minimalist": hasil per skenario sebagai baris dengan
garis pemisah bawah, bukan kotak.
"""

import reflex as rx

from ..state import AppState
from ..components.theme import (
    COLORS,
    FONT_MONO,
    PAGE_MAX_WIDTH,
    page_header,
    level_color,
)


def demo_result_row(result) -> rx.Component:
    """Satu baris hasil skenario: fault + level berwarna + score."""
    return rx.hstack(
        rx.text(
            result[0],  # nama fault
            font_size="15px",
            weight="medium",
            color=COLORS["text_primary"],
        ),
        rx.spacer(),
        rx.text(
            result[1],  # risk level
            font_size="11px",
            letter_spacing="1px",
            text_transform="uppercase",
            weight="medium",
            color=level_color(result[1]),
        ),
        rx.text(
            result[2],  # risk score
            font_size="18px",
            font_family=FONT_MONO,
            color=COLORS["text_primary"],
            min_width="56px",
            text_align="right",
        ),
        align="center",
        spacing="5",
        width="100%",
        padding_y="0.9em",
        border_bottom="0.5px solid " + COLORS["border"],
    )


def demo_page() -> rx.Component:
    """Susun halaman Demo Otomatis lengkap."""
    return rx.vstack(
        page_header("Demo", "Simulasi skenario"),
        rx.text(
            "Demo ini mensimulasikan 6 skenario anomali secara berurutan: "
            "Normal, PV_Fault, Battery_Overheating, Grid_Instability, "
            "Inverter_Fault, Communication_Failure.",
            color=COLORS["text_secondary"],
            size="2",
        ),
        rx.button(
            rx.icon("play", size=16),
            "Jalankan Demo",
            on_click=AppState.run_demo,
            size="3",
            width="100%",
            variant="outline",
            color_scheme="green",
        ),
        # Indikator status saat demo berjalan
        rx.cond(
            AppState.demo_running,
            rx.text("Menjalankan demo...", color=COLORS["medium"], size="2"),
            rx.box(),
        ),
        # Daftar hasil tiap skenario (baris bergaris, bukan kotak)
        rx.vstack(
            rx.foreach(AppState.demo_results, demo_result_row),
            spacing="0",
            width="100%",
        ),
        spacing="6",
        width="100%",
        max_width=PAGE_MAX_WIDTH,
    )


print("[demo] OK - Halaman Demo Otomatis di-restyle (Modern Minimalist)")
