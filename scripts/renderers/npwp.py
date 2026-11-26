"""Programmatic Pillow renderer for synthetic Indonesian NPWP tax cards."""

from __future__ import annotations

from datetime import date

from PIL import Image, ImageDraw

from scripts.renderers import CARD_HEIGHT, CARD_WIDTH, NpwpRecord, load_font


def _format_dmy(iso_date: str) -> str:
    """Format ISO YYYY-MM-DD date into Indonesian DD-MM-YYYY card format."""
    try:
        parsed = date.fromisoformat(iso_date)
    except ValueError:
        return iso_date
    return parsed.strftime("%d-%m-%Y")


def render_npwp(record: NpwpRecord) -> Image.Image:
    """Render an 856x540 synthetic Indonesian NPWP card as a PIL Image."""
    image = Image.new("RGB", (CARD_WIDTH, CARD_HEIGHT), color=(204, 220, 226))
    draw = ImageDraw.Draw(image)

    # Outer border and Ministry of Finance / DJP navy + gold banner
    draw.rectangle((12, 12, CARD_WIDTH - 12, CARD_HEIGHT - 12), outline=(28, 52, 84), width=3)
    draw.rectangle((15, 15, CARD_WIDTH - 15, 114), fill=(24, 52, 92))
    draw.rectangle((15, 114, CARD_WIDTH - 15, 126), fill=(214, 172, 54))

    header_font = load_font(19, bold=True)
    sub_font = load_font(16, bold=True)
    title_font = load_font(20, bold=True)
    number_font = load_font(24, bold=True)
    label_font = load_font(15, bold=True)
    value_font = load_font(16, bold=False)

    draw.text(
        (38, 34),
        "KEMENTERIAN KEUANGAN REPUBLIK INDONESIA",
        fill=(236, 236, 236),
        font=header_font,
    )
    draw.text(
        (38, 66),
        "DIREKTORAT JENDERAL PAJAK",
        fill=(238, 206, 102),
        font=sub_font,
    )

    # Decorative emblem box on top right
    draw.rectangle((724, 28, 822, 102), fill=(36, 72, 120), outline=(214, 172, 54), width=2)
    draw.text((773, 65), "DJP", fill=(238, 206, 102), font=title_font, anchor="mm")

    draw.text(
        (38, 148),
        "NOMOR POKOK WAJIB PAJAK (NPWP)",
        fill=(22, 44, 72),
        font=title_font,
    )

    y = 192
    if record.npwp_16 is not None:
        draw.text((38, y), f"NPWP16 : {record.npwp_16}", fill=(14, 28, 48), font=number_font)
        y += 38
    if record.npwp_15 is not None:
        draw.text((38, y), f"NPWP   : {record.npwp_15}", fill=(14, 28, 48), font=number_font)
        y += 42

    draw.line((38, y, 818, y), fill=(52, 82, 116), width=2)
    y += 20

    rows: list[tuple[str, str]] = [
        ("NAMA", record.taxpayer_name[:42]),
        ("ALAMAT", record.address[:46]),
        ("KPP", f"{record.kpp_name[:36]} ({record.kpp_code})"),
        ("TERDAFTAR", _format_dmy(record.registered_date)),
    ]

    for label, value in rows:
        draw.text((38, y), label, fill=(28, 52, 84), font=label_font)
        draw.text((178, y), f": {value}", fill=(14, 26, 40), font=value_font)
        y += 38

    draw.rectangle((38, 468, 818, 506), fill=(182, 202, 212), outline=(42, 72, 104), width=1)
    draw.text(
        (428, 487),
        "SYNTHETIC TAXPAYER CARD - FOR AUTOMATED TESTING ONLY",
        fill=(32, 52, 76),
        font=load_font(13, bold=True),
        anchor="mm",
    )

    return image


__all__ = ["render_npwp"]
