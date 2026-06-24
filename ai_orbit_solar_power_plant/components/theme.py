"""
ai_orbit_solar_power_plant/components/theme.py
────────────────────────────────────────────────────────────
Design tokens & helper komponen untuk gaya "Modern Minimalist".

Prinsip: angka besar sebagai focal point, label kecil uppercase di atas
nilai, card nyaris tanpa border (beda elevasi lewat warna background),
spacing lega, dan separator garis 0.5px alih-alih kotak terpisah.
"""

import reflex as rx

# ── Palet warna global ──
COLORS = {
    "bg_primary": "#0e1011",
    "bg_secondary": "#161819",
    "border": "#22262a",
    "text_primary": "#f5f5f5",
    "text_secondary": "#6b7280",
    "text_tertiary": "#4b5563",
    "accent": "#00FF88",
    "low": "#00FF88",
    "medium": "#FFD23F",
    "high": "#FF6B35",
    "critical": "#FF3B3B",
}

# ── Keluarga font ──
FONT_MONO = "JetBrains Mono, monospace"
FONT_SANS = "Inter, sans-serif"

# ── Lebar maksimum konten halaman ──
# Satu sumber kebenaran agar SEMUA halaman punya lebar kontainer yang konsisten
# (sebelumnya Live Monitor 900px, halaman lain 1100px — kini seragam).
PAGE_MAX_WIDTH = "1100px"


# ─────────────────────────────────────────────────────────
# Helper komponen
# ─────────────────────────────────────────────────────────
def page_header(label: str, title: str) -> rx.Component:
    """Header 2-baris: label kecil uppercase + judul besar."""
    return rx.vstack(
        rx.text(
            label,
            size="1",
            color=COLORS["text_secondary"],
            letter_spacing="2px",
            text_transform="uppercase",
        ),
        rx.heading(title, size="8", weight="medium", color=COLORS["text_primary"]),
        spacing="1",
        margin_bottom="1.5em",
    )


def stat_value(label: str, value, color: str = "#f5f5f5",
               size: str = "5") -> rx.Component:
    """Label kecil uppercase di atas + value besar monospace, tanpa card."""
    return rx.vstack(
        rx.text(
            label,
            size="1",
            color=COLORS["text_secondary"],
            letter_spacing="1px",
            text_transform="uppercase",
        ),
        rx.text(value, size=size, weight="medium", color=color, font_family=FONT_MONO),
        spacing="1",
        align="start",
    )


def section_divider() -> rx.Component:
    """Separator garis tipis 0.5px dengan ruang di atas-bawahnya."""
    return rx.box(
        border_top="0.5px solid " + COLORS["border"],
        padding_top="1.5em",
        margin_top="1.5em",
        width="100%",
    )


def section_label(text: str, margin_bottom: str = "0.75em") -> rx.Component:
    """Label kecil uppercase di atas sebuah section/grafik/tabel.

    Sumber tunggal gaya label section (sebelumnya diduplikasi di tiap halaman
    dengan spacing yang sedikit berbeda) → konsisten antar halaman.
    """
    return rx.text(
        text,
        font_size="11px",
        letter_spacing="2px",
        text_transform="uppercase",
        color=COLORS["text_secondary"],
        margin_bottom=margin_bottom,
    )


def level_color(level_var) -> rx.Component:
    """Petakan Var risk_level (LOW/MEDIUM/HIGH/CRITICAL) ke warna token."""
    return rx.cond(
        level_var == "CRITICAL",
        COLORS["critical"],
        rx.cond(
            level_var == "HIGH",
            COLORS["high"],
            rx.cond(
                level_var == "MEDIUM",
                COLORS["medium"],
                COLORS["low"],
            ),
        ),
    )


def th(label: str) -> rx.Component:
    """Sel header tabel bergaya minimalis (uppercase kecil, abu-abu)."""
    return rx.table.column_header_cell(
        label,
        font_size="11px",
        letter_spacing="1px",
        text_transform="uppercase",
        color=COLORS["text_secondary"],
    )


def analysis_table(rows_var) -> rx.Component:
    """Tabel analisis 4 kolom (Waktu, Risk Score, Level, Fault).

    Dipakai bersama oleh Realtime Feed dan History. Tanpa background
    bergantian — hanya garis pemisah halus bawaan varian ghost.
    Kolom Level diwarnai sesuai tingkat risiko.
    """
    return rx.table.root(
        rx.table.header(
            rx.table.row(
                th("Waktu"),
                th("Risk Score"),
                th("Level"),
                th("Fault"),
            )
        ),
        rx.table.body(
            rx.foreach(
                rows_var,
                lambda row: rx.table.row(
                    rx.table.cell(row[0], color=COLORS["text_secondary"]),
                    rx.table.cell(row[1], font_family=FONT_MONO),
                    rx.table.cell(
                        row[2], color=level_color(row[2]), weight="medium"
                    ),
                    rx.table.cell(row[3]),
                ),
            )
        ),
        variant="ghost",
        width="100%",
    )
