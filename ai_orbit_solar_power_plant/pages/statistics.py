"""
ai_orbit_solar_power_plant/pages/statistics.py
────────────────────────────────────────────────────────────
Halaman Statistik & Grafik: ringkasan riwayat (grid metrik),
bar chart distribusi fault, dan pie chart distribusi risk level.
Data berasal dari history.json.

Gaya "Modern Minimalist": metrik tanpa kotak, grafik dengan
warna aksen hijau, grid & teks abu-abu.
"""

import reflex as rx

from ..state import AppState
from ..components.theme import COLORS, page_header, stat_value, section_divider


def _chart_label(text: str) -> rx.Component:
    """Label kecil uppercase di atas tiap grafik."""
    return rx.text(
        text,
        font_size="11px",
        letter_spacing="2px",
        text_transform="uppercase",
        color=COLORS["text_secondary"],
        margin_bottom="0.75em",
    )


def statistics_page() -> rx.Component:
    """Susun halaman Statistik & Grafik lengkap."""
    return rx.vstack(
        page_header("Statistik", "Ringkasan & grafik"),
        rx.button(
            rx.icon("refresh-cw", size=14),
            "Refresh Data",
            on_click=AppState.load_history,
            variant="outline",
            color_scheme="gray",
            size="1",
        ),
        # Grid metrik tanpa kotak
        rx.grid(
            stat_value("Total Analisis", AppState.stat_total),
            stat_value("Total Anomali", AppState.stat_anomali, color=COLORS["high"]),
            stat_value("Fault Tersering", AppState.stat_top_fault, size="4"),
            columns="3",
            spacing="6",
            width="100%",
        ),
        section_divider(),
        # Bar chart distribusi fault
        rx.box(
            _chart_label("Distribusi Fault"),
            rx.recharts.bar_chart(
                rx.recharts.cartesian_grid(
                    stroke=COLORS["border"], stroke_dasharray="3 3"
                ),
                rx.recharts.bar(data_key="count", fill=COLORS["accent"]),
                rx.recharts.x_axis(
                    data_key="fault", stroke=COLORS["text_secondary"]
                ),
                rx.recharts.y_axis(stroke=COLORS["text_secondary"]),
                data=AppState.fault_distribution,
                width="100%",
                height=300,
            ),
            width="100%",
        ),
        section_divider(),
        # Pie chart distribusi risk level
        rx.box(
            _chart_label("Distribusi Risk Level"),
            rx.recharts.pie_chart(
                rx.recharts.pie(
                    data=AppState.risk_level_distribution,
                    data_key="value",
                    name_key="name",
                    fill=COLORS["accent"],
                ),
                width="100%",
                height=300,
            ),
            width="100%",
        ),
        on_mount=AppState.load_history,
        spacing="6",
        width="100%",
        max_width="1100px",
    )


print("[statistics] OK - Halaman Statistik & Grafik di-restyle (Modern Minimalist)")
