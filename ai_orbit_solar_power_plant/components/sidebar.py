"""
ai_orbit_solar_power_plant/components/sidebar.py
────────────────────────────────────────────────────────────
Sidebar navigasi tetap (fixed) bergaya "Modern Minimalist".
Flat tanpa border tebal; item aktif ditandai garis kiri hijau.
"""

import reflex as rx

from ..state import AppState
from .theme import COLORS, stat_value


def nav_item(label: str, page_key: str, icon: str) -> rx.Component:
    """Satu item navigasi. Aktif = garis kiri hijau + teks terang."""
    active = AppState.current_page == page_key
    text_color = rx.cond(active, COLORS["text_primary"], COLORS["text_secondary"])
    return rx.box(
        rx.hstack(
            rx.icon(icon, size=16, color=text_color),
            rx.text(
                label,
                color=text_color,
                weight=rx.cond(active, "medium", "regular"),
                font_size="14px",
            ),
            align="center",
            spacing="3",
        ),
        on_click=lambda: AppState.set_page(page_key),
        # Garis kiri 2px hanya saat aktif (transparan saat tidak)
        border_left=rx.cond(
            active,
            "2px solid " + COLORS["accent"],
            "2px solid transparent",
        ),
        padding_left="0.75em",
        padding_top="0.5em",
        padding_bottom="0.5em",
        width="100%",
        cursor="pointer",
    )


def sidebar() -> rx.Component:
    """Sidebar kiri tetap: logo, menu navigasi, dan status sistem."""
    return rx.box(
        rx.vstack(
            # ── Header / logo ──
            rx.hstack(
                rx.icon("zap", color=COLORS["accent"], size=22),
                rx.text(
                    "AI-ORBIT",
                    font_size="20px",
                    weight="medium",
                    letter_spacing="1px",
                    color=COLORS["text_primary"],
                ),
                align="center",
                spacing="2",
            ),
            rx.text(
                "Solar Power Plant Anomaly Monitor",
                size="1",
                color=COLORS["text_secondary"],
            ),
            rx.box(height="1.5em"),

            # ── Menu navigasi ──
            nav_item("Live Monitor", "live_monitor", "activity"),
            nav_item("Realtime Feed", "realtime_feed", "radio"),
            nav_item("Statistik & Grafik", "statistics", "bar-chart-3"),
            nav_item("History Anomali", "history", "list"),
            nav_item("Demo Otomatis", "demo", "play"),

            rx.spacer(),
            rx.box(border_top="0.5px solid " + COLORS["border"], width="100%"),
            rx.box(height="0.5em"),

            # ── Status sistem (gaya stat_value) ──
            stat_value("Model", AppState.model_status, size="3"),
            stat_value(
                "Telegram",
                rx.cond(AppState.telegram_connected, "Terhubung", "Terputus"),
                color=rx.cond(
                    AppState.telegram_connected, COLORS["accent"], COLORS["high"]
                ),
                size="3",
            ),
            spacing="3",
            height="100vh",
            padding="1.5em",
            align="start",
        ),
        width="280px",
        bg=COLORS["bg_primary"],
        border_right="0.5px solid " + COLORS["border"],
        position="fixed",
        height="100vh",
    )
