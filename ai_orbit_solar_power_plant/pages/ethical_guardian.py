"""
ai_orbit_solar_power_plant/pages/ethical_guardian.py
────────────────────────────────────────────────────────────
Halaman Ethical Guardian: memvisualisasikan kendali etis (guardrail) di atas
sistem deteksi anomali. Tiga bagian:
  A. Status panel  — status guardian, counter harian, toggle Safety Interlock.
  B. Pending banner — aksi irreversibel yang menunggu konfirmasi manusia.
  C. Audit log     — riwayat keputusan guardian (EXECUTE / BLOCKED / pending).

Gaya "Modern Minimalist": tanpa emoji, tanpa gradient, badge garis tipis,
angka monospace, aksen hijau. Logic ada di AppState (state.py) & backend.
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
    th,
)


# ─────────────────────────────────────────────────────────
# Helper warna badge (pola nested rx.cond seperti level_color)
# ─────────────────────────────────────────────────────────
def _verdict_color(verdict_var) -> rx.Component:
    """EXECUTE=hijau, REQUIRE_HUMAN_CONFIRMATION=kuning, BLOCKED=merah."""
    return rx.cond(
        verdict_var == "EXECUTE",
        COLORS["accent"],
        rx.cond(
            verdict_var == "BLOCKED",
            COLORS["critical"],
            rx.cond(
                verdict_var == "REQUIRE_HUMAN_CONFIRMATION",
                COLORS["medium"],
                COLORS["text_secondary"],
            ),
        ),
    )


def _reversibility_color(rev_var) -> rx.Component:
    """reversible=hijau, semi_reversible=kuning, irreversible=merah."""
    return rx.cond(
        rev_var == "reversible",
        COLORS["accent"],
        rx.cond(
            rev_var == "semi_reversible",
            COLORS["medium"],
            rx.cond(
                rev_var == "irreversible",
                COLORS["critical"],
                COLORS["text_secondary"],
            ),
        ),
    )


def _escalation_color(level_var) -> rx.Component:
    """Eskalasi (Opsi C): level 0/1=kuning, 2=oranye, 3=merah. Terima Var int."""
    return rx.cond(
        level_var >= 3,
        COLORS["critical"],
        rx.cond(
            level_var >= 2,
            COLORS["high"],
            COLORS["medium"],
        ),
    )


def _escalation_color_str(s_var) -> rx.Component:
    """Versi untuk sel tabel (nilai level berupa string '0'..'3')."""
    return rx.cond(
        s_var == "3",
        COLORS["critical"],
        rx.cond(
            s_var == "2",
            COLORS["high"],
            COLORS["medium"],
        ),
    )


def _outcome_color(o_var) -> rx.Component:
    """Warna badge Outcome: confirmed=hijau, cancelled=merah, auto=oranye, lainnya=abu."""
    return rx.cond(
        o_var == "human_confirmed",
        COLORS["accent"],
        rx.cond(
            o_var == "human_cancelled",
            COLORS["critical"],
            rx.cond(
                o_var == "auto_executed_after_timeout",
                COLORS["high"],
                COLORS["text_secondary"],
            ),
        ),
    )


def _escalation_title(level_var) -> rx.Component:
    """Judul banner sesuai level eskalasi (kontak yang sudah dihubungi)."""
    return rx.cond(
        level_var >= 2,
        "Eskalasi Level 2 — kontak ketiga telah dihubungi",
        rx.cond(
            level_var >= 1,
            "Eskalasi Level 1 — kontak kedua telah dihubungi",
            "Menunggu Konfirmasi Manusia",
        ),
    )


def _pill(text_var, color_var) -> rx.Component:
    """Badge pill minimalis: teks berwarna + border tipis sewarna."""
    return rx.box(
        rx.text(
            text_var,
            font_size="11px",
            weight="medium",
            color=color_var,
            white_space="nowrap",
        ),
        border_width="0.5px",
        border_style="solid",
        border_color=color_var,
        border_radius="6px",
        padding_left="0.6em",
        padding_right="0.6em",
        padding_top="0.15em",
        padding_bottom="0.15em",
        display="inline-block",
    )


# ─────────────────────────────────────────────────────────
# A. Status panel
# ─────────────────────────────────────────────────────────
def _status_panel() -> rx.Component:
    """Panel atas: status guardian, counter harian, toggle interlock."""
    return rx.box(
        rx.vstack(
            # Baris: badge status + tombol refresh
            rx.hstack(
                _pill("Ethical Guardian: Active", COLORS["accent"]),
                rx.spacer(),
                rx.button(
                    rx.icon("refresh-cw", size=14),
                    "Refresh",
                    on_click=AppState.load_guardian,
                    variant="outline",
                    color_scheme="gray",
                    size="1",
                ),
                width="100%",
                align="center",
            ),
            section_divider(),
            # Counter harian
            rx.grid(
                stat_value(
                    "Aksi Diblokir Hari Ini",
                    AppState.guardian_blocked_today,
                    color=COLORS["critical"],
                ),
                stat_value(
                    "Aksi Otonom Dieksekusi Hari Ini",
                    AppState.guardian_executed_today,
                    color=COLORS["accent"],
                ),
                columns="2",
                spacing="6",
                width="100%",
            ),
            section_divider(),
            # Toggle Safety Interlock
            rx.hstack(
                rx.vstack(
                    rx.text(
                        "Safety Interlock (Maintenance Mode)",
                        font_size="13px",
                        weight="medium",
                        color=COLORS["text_primary"],
                    ),
                    rx.cond(
                        AppState.guardian_interlock_active,
                        rx.text(
                            "Mode ini akan memblokir semua aksi otonom HIGH/CRITICAL",
                            font_size="11px",
                            color=COLORS["medium"],
                        ),
                        rx.text(
                            "Nonaktif — aksi otonom berjalan sesuai kebijakan guardian",
                            font_size="11px",
                            color=COLORS["text_secondary"],
                        ),
                    ),
                    spacing="1",
                    align="start",
                ),
                rx.spacer(),
                rx.switch(
                    checked=AppState.guardian_interlock_active,
                    on_change=AppState.toggle_interlock,
                    color_scheme="green",
                ),
                width="100%",
                align="center",
            ),
            spacing="4",
            width="100%",
        ),
        border="0.5px solid " + COLORS["border"],
        border_radius="12px",
        padding="1.75em",
        bg=COLORS["bg_secondary"],
        width="100%",
    )


# ─────────────────────────────────────────────────────────
# B. Pending confirmation banner (kondisional)
# ─────────────────────────────────────────────────────────
def _pending_banner() -> rx.Component:
    """Banner mencolok bila ada aksi irreversibel menunggu konfirmasi manusia.

    Warna & judul berubah mengikuti level eskalasi (Opsi C): kuning (level 0/1) →
    oranye (level 2) → merah (level 3). Countdown menunjukkan SISA window saat ini
    (reset tiap naik level), didorong server-side oleh guardian_escalation_monitor.
    """
    esc_color = _escalation_color(AppState.guardian_pending_escalation_level)
    return rx.box(
        rx.hstack(
            rx.icon("triangle-alert", size=22, color=esc_color),
            rx.vstack(
                rx.text(
                    _escalation_title(AppState.guardian_pending_escalation_level),
                    font_size="15px",
                    weight="medium",
                    color=COLORS["text_primary"],
                ),
                rx.text(
                    "Fault: " + AppState.guardian_pending_fault
                    + "  |  Aksi: " + AppState.guardian_pending_action
                    + "  |  Severity: " + AppState.guardian_pending_severity,
                    font_size="13px",
                    color=COLORS["text_secondary"],
                ),
                rx.text(
                    AppState.guardian_pending_reason,
                    font_size="12px",
                    color=COLORS["text_secondary"],
                ),
                # Peringatan auto-eksekusi yang menonjol mulai level 2.
                rx.cond(
                    AppState.guardian_pending_escalation_level >= 2,
                    rx.text(
                        "Tanpa respon, sistem akan MENGEKSEKUSI aksi ini secara "
                        "OTOMATIS saat hitung mundur habis.",
                        font_size="12px",
                        weight="medium",
                        color=COLORS["critical"],
                    ),
                    rx.box(),
                ),
                spacing="1",
                align="start",
            ),
            rx.spacer(),
            rx.vstack(
                rx.text(
                    AppState.guardian_pending_countdown.to_string() + " s",
                    # Lebih besar saat eskalasi sudah tinggi (lebih mencolok).
                    font_size=rx.cond(
                        AppState.guardian_pending_escalation_level >= 2,
                        "36px",
                        "28px",
                    ),
                    weight="medium",
                    color=esc_color,
                    font_family=FONT_MONO,
                    line_height="1",
                ),
                rx.hstack(
                    rx.button(
                        "Konfirmasi & Eksekusi",
                        on_click=AppState.confirm_pending,
                        color_scheme="green",
                        size="1",
                    ),
                    rx.button(
                        "Batalkan",
                        on_click=AppState.cancel_pending,
                        variant="outline",
                        color_scheme="red",
                        size="1",
                    ),
                    spacing="2",
                ),
                spacing="2",
                align="end",
            ),
            width="100%",
            align="center",
            spacing="4",
        ),
        border_width="1.5px",
        border_style="solid",
        border_color=esc_color,
        border_radius="12px",
        padding="1.5em",
        bg=COLORS["bg_secondary"],
        width="100%",
    )


# ─────────────────────────────────────────────────────────
# C. Audit log table
# ─────────────────────────────────────────────────────────
def _audit_table() -> rx.Component:
    """Tabel keputusan guardian (terbaru di atas) dengan badge berwarna."""
    return rx.table.root(
        rx.table.header(
            rx.table.row(
                th("Timestamp"),
                th("Fault Terdeteksi"),
                th("Action Type"),
                th("Severity"),
                th("Confidence"),
                th("Reversibility"),
                th("Verdict"),
                th("Eskalasi"),
                th("Outcome"),
                th("Reason"),
            )
        ),
        rx.table.body(
            rx.foreach(
                AppState.guardian_audit_rows,
                lambda row: rx.table.row(
                    rx.table.cell(
                        row[0], color=COLORS["text_secondary"], font_size="12px"
                    ),
                    rx.table.cell(row[1], weight="medium"),
                    rx.table.cell(row[2]),
                    rx.table.cell(
                        row[3], color=level_color(row[3]), weight="medium"
                    ),
                    rx.table.cell(row[4], font_family=FONT_MONO),
                    rx.table.cell(_pill(row[5], _reversibility_color(row[5]))),
                    rx.table.cell(_pill(row[6], _verdict_color(row[6]))),
                    # Eskalasi (Opsi C): level 0..3 sebagai badge "L{n}".
                    rx.table.cell(
                        _pill("L" + row[8], _escalation_color_str(row[8]))
                    ),
                    # Outcome akhir aksi pending.
                    rx.table.cell(_pill(row[9], _outcome_color(row[9]))),
                    rx.table.cell(
                        rx.tooltip(
                            rx.text(
                                row[7],
                                no_of_lines=1,
                                max_width="240px",
                                color=COLORS["text_secondary"],
                                font_size="12px",
                            ),
                            content=row[7],
                        )
                    ),
                ),
            )
        ),
        variant="ghost",
        width="100%",
    )


def _empty_state() -> rx.Component:
    """Empty state minimalis saat audit log kosong."""
    return rx.box(
        rx.vstack(
            rx.icon("shield-check", size=28, color=COLORS["text_tertiary"]),
            rx.text(
                "Belum ada keputusan guardian yang tercatat.",
                color=COLORS["text_secondary"],
                size="2",
            ),
            rx.text(
                "Keputusan akan muncul di sini setiap kali aksi otonom dievaluasi.",
                color=COLORS["text_tertiary"],
                size="1",
            ),
            spacing="2",
            align="center",
        ),
        width="100%",
        padding="3em",
        display="flex",
        justify_content="center",
    )


# ─────────────────────────────────────────────────────────
# Indikator interlock aktif (mencolok, biar operator sadar)
# ─────────────────────────────────────────────────────────
def _interlock_active_indicator() -> rx.Component:
    """Banner peringatan menonjol saat Safety Interlock sedang AKTIF.

    Mencegah footgun: operator harus sadar bahwa SEMUA aksi otonom sedang
    ditahan, dan interlock perlu dimatikan MANUAL setelah perawatan selesai.
    """
    return rx.box(
        rx.hstack(
            rx.icon("shield-alert", size=20, color=COLORS["critical"]),
            rx.vstack(
                rx.text(
                    "Safety Interlock AKTIF — Aksi otonom ditahan",
                    font_size="14px",
                    weight="medium",
                    color=COLORS["critical"],
                ),
                rx.text(
                    "Semua aksi HIGH/CRITICAL diblokir selama mode ini menyala. "
                    "Matikan toggle secara manual setelah perawatan selesai.",
                    font_size="12px",
                    color=COLORS["text_secondary"],
                ),
                spacing="1",
                align="start",
            ),
            rx.spacer(),
            rx.button(
                "Matikan Interlock",
                on_click=lambda: AppState.toggle_interlock(False),
                variant="outline",
                color_scheme="red",
                size="1",
            ),
            width="100%",
            align="center",
            spacing="3",
        ),
        border_width="1.5px",
        border_style="solid",
        border_color=COLORS["critical"],
        border_radius="12px",
        padding="1.25em",
        bg=COLORS["bg_secondary"],
        width="100%",
    )


# ─────────────────────────────────────────────────────────
# Halaman Ethical Guardian (komponen utama)
# ─────────────────────────────────────────────────────────
def ethical_guardian_page() -> rx.Component:
    """Susun halaman Ethical Guardian lengkap."""
    return rx.vstack(
        page_header("Ethical Guardian", "Kendali etis & audit"),
        rx.text(
            "Guardrail deterministik di atas deteksi anomali: memutuskan apakah "
            "aksi otonom boleh dieksekusi, diblokir, atau perlu konfirmasi manusia.",
            color=COLORS["text_secondary"],
            size="2",
        ),
        # Indikator menonjol hanya tampil saat interlock sedang aktif.
        rx.cond(
            AppState.guardian_interlock_active,
            _interlock_active_indicator(),
            rx.box(),
        ),
        _status_panel(),
        # Banner pending hanya tampil bila ada aksi menunggu konfirmasi.
        rx.cond(
            AppState.guardian_pending_active,
            _pending_banner(),
            rx.box(),
        ),
        # Audit log atau empty state.
        rx.box(
            rx.text(
                "Audit Log",
                font_size="11px",
                letter_spacing="2px",
                text_transform="uppercase",
                color=COLORS["text_secondary"],
                margin_bottom="0.75em",
            ),
            rx.cond(
                AppState.guardian_has_log,
                _audit_table(),
                _empty_state(),
            ),
            width="100%",
        ),
        on_mount=AppState.load_guardian,
        spacing="6",
        width="100%",
        max_width="1100px",
    )


print("[ethical_guardian] OK - Halaman Ethical Guardian (Modern Minimalist)")
