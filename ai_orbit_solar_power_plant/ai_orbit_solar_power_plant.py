"""
ai_orbit_solar_power_plant/ai_orbit_solar_power_plant.py
────────────────────────────────────────────────────────────
Titik masuk aplikasi Reflex AI-ORBIT Solar Monitor.

Layout dasar (sidebar + area konten) dan routing antar halaman via
AppState.current_page. Kelima halaman (Live Monitor, Realtime Feed,
Statistik & Grafik, History Anomali, Demo Otomatis) sudah terpasang.
"""

# Muat variabel lingkungan dari .env (SUPABASE_DB_URL, TELEGRAM_TOKEN, dll)
# SEBELUM import .state -> backend.agent_bridge -> db_client yang membaca
# os.environ. Penting untuk deploy Reflex Cloud (Secrets fitur Pro-only),
# di mana .env di-bundle ke dalam folder app ini.
from dotenv import load_dotenv
load_dotenv()

import reflex as rx

from .state import AppState
from .components.sidebar import sidebar
from .components.theme import COLORS, FONT_SANS
from .pages.live_monitor import live_monitor_page
from .pages.realtime_feed import realtime_feed_page
from .pages.statistics import statistics_page
from .pages.history import history_page
from .pages.ethical_guardian import ethical_guardian_page
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
                            rx.cond(
                                AppState.current_page == "ethical_guardian",
                                ethical_guardian_page(),
                                demo_page(),
                            ),
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
app.add_page(
    index,
    route="/",
    # check_telegram: status koneksi; guardian_escalation_monitor: monitor
    # eskalasi bertingkat (Opsi C) cross-page — menjaga badge pending akurat di
    # halaman manapun SEKALIGUS menggerakkan eskalasi & auto-execute timeout.
    on_load=[AppState.check_telegram, AppState.guardian_escalation_monitor],
)
