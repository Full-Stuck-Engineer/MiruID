"""Programmatic Pillow renderer for synthetic Indonesian Driver's License (SIM) cards."""

from __future__ import annotations

from datetime import date

from PIL import Image, ImageDraw

from scripts.renderers import CARD_HEIGHT, CARD_WIDTH, SimRecord, load_font


def _format_dmy(iso_date: str) -> str:
    """Format ISO YYYY-MM-DD date into Indonesian DD-MM-YYYY card format."""
    try:
        parsed = date.fromisoformat(iso_date)
    except ValueError:
        return iso_date
    return parsed.strftime("%d-%m-%Y")


def _draw_sim_photo(draw: ImageDraw.ImageDraw, x0: int, y0: int, w: int, h: int) -> None:
    """Draw a blue-background portrait placeholder box for Smart SIM layout."""
    draw.rectangle((x0, y0, x0 + w, y0 + h), fill=(46, 98, 168), outline=(34, 48, 72), width=2)
    cx = x0 + w // 2
    head_r = w // 5
    draw.ellipse(
        (cx - head_r, y0 + 34, cx + head_r, y0 + 34 + head_r * 2),
        fill=(228, 198, 174),
        outline=(98, 74, 58),
        width=2,
    )
    draw.pieslice(
        (x0 + 22, y0 + 108, x0 + w - 22, y0 + h + 52),
        start=180,
        end=360,
        fill=(38, 48, 66),
    )
    label_font = load_font(12, bold=True)
    draw.text((x0 + 42, y0 + h - 22), "SYNTHETIC", fill=(232, 238, 244), font=label_font)


def render_sim(record: SimRecord) -> Image.Image:
    """Render an 856x540 synthetic Indonesian SIM card as a PIL Image."""
    image = Image.new("RGB", (CARD_WIDTH, CARD_HEIGHT), color=(212, 224, 234))
    draw = ImageDraw.Draw(image)

    # Outer border and Korlantas-style red/navy header
    draw.rectangle((12, 12, CARD_WIDTH - 12, CARD_HEIGHT - 12), outline=(42, 54, 78), width=3)
    draw.rectangle((15, 15, CARD_WIDTH - 15, 64), fill=(176, 36, 44))
    draw.rectangle((15, 64, CARD_WIDTH - 15, 108), fill=(32, 52, 88))

    title_font = load_font(19, bold=True)
    subtitle_font = load_font(16, bold=True)
    badge_font = load_font(26, bold=True)
    number_font = load_font(22, bold=True)
    field_font = load_font(16, bold=False)
    bold_field_font = load_font(16, bold=True)

    draw.text(
        (36, 30),
        "KEPOLISIAN NEGARA REPUBLIK INDONESIA",
        fill=(238, 238, 238),
        font=title_font,
    )
    draw.text(
        (36, 76),
        "SURAT IZIN MENGEMUDI / DRIVING LICENSE",
        fill=(238, 222, 150),
        font=subtitle_font,
    )

    # Prominent SIM class badge on top right
    draw.rectangle((664, 22, 826, 98), fill=(236, 212, 120), outline=(28, 36, 52), width=2)
    draw.text(
        (745, 60),
        f"SIM {record.sim_class}",
        fill=(22, 32, 48),
        font=badge_font,
        anchor="mm",
    )

    _draw_sim_photo(draw, 36, 134, 174, 222)

    # SIM Number and numbered Smart SIM fields
    draw.text((236, 134), f"NO. SIM : {record.sim_number}", fill=(16, 28, 44), font=number_font)
    draw.line((236, 168, 820, 168), fill=(52, 74, 102), width=2)

    gender_short = "PRIA" if record.gender == "LAKI-LAKI" else "WANITA"
    numbered_rows: list[str] = [
        f"1. {record.full_name[:34]}",
        f"2. {record.place_of_birth[:18]}, {_format_dmy(record.date_of_birth)}",
        f"3. {record.blood_type} - {gender_short}",
        f"4. {record.address[:40]}",
        f"5. {record.occupation}",
        f"6. {record.issuing_office}",
    ]

    y = 186
    for row in numbered_rows:
        draw.text((236, y), row, fill=(18, 28, 42), font=field_font)
        y += 38

    # Expiry footer
    draw.rectangle((36, 442, 820, 502), fill=(192, 208, 222), outline=(52, 74, 102), width=1)
    draw.text(
        (56, 462),
        f"POLRI - GOL. SIM: {record.sim_class}",
        fill=(24, 38, 58),
        font=bold_field_font,
    )
    draw.text(
        (540, 462),
        f"BERLAKU S/D: {_format_dmy(record.valid_until)}",
        fill=(146, 26, 34),
        font=bold_field_font,
    )

    return image


__all__ = ["render_sim"]
