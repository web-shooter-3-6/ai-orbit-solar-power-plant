"""
ai_orbit_solar_power_plant/ai_orbit_solar_power_plant.py
────────────────────────────────────────────────────────────
Titik masuk aplikasi Reflex AI-ORBIT Solar Monitor.

Layout dasar (sidebar + area konten) dan routing antar halaman via
AppState.current_page. Kelima halaman (Live Monitor, Realtime Feed,
Statistik & Grafik, History Anomali, Demo Otomatis) sudah terpasang.
"""

import reflex as rx

from .state import AppState
from .components.sidebar import sidebar
from .components.theme import COLORS, FONT_SANS
from .pages.live_monitor import live_monitor_page
from .pages.realtime_feed import realtime_feed_page
from .pages.statistics import statistics_page
from .pages.history import history_page
from .pages.demo import demo_page


def index() -> rx.Component:
    """Halaman utama: sidebar tetap + area konten yang berganti per menu."""
    return rx.box(
        sidebar(),
        rx.box(
            rx.cond(
                AppState.current_page == "live_monitor",
                live_monitor_page(),
                rx.cond(
                    AppState.current_page == "realtime_feed",
                    realtime_feed_page(),
                    rx.cond(
                        AppState.current_page == "statistics",
                        statistics_page(),
                        rx.cond(
                            AppState.current_page == "history",
                            history_page(),
                            demo_page(),
                        ),
                    ),
                ),
            ),
            margin_left="280px",
            padding="2.5em",
            bg=COLORS["bg_primary"],
            min_height="100vh",
            color=COLORS["text_primary"],
        ),
        bg=COLORS["bg_primary"],
    )


app = rx.App(
    theme=rx.theme(appearance="dark"),
    stylesheets=[
        "https://fonts.googleapis.com/css2?family=Inter:wght@400;500&"
        "family=JetBrains+Mono:wght@400;500&display=swap"
    ],
    style={
        "font_family": FONT_SANS,
        "background_color": COLORS["bg_primary"],
    },
)
app.add_page(index, route="/", on_load=AppState.check_telegram)
