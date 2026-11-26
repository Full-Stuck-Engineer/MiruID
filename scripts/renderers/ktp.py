"""Programmatic Pillow renderer for synthetic Indonesian e-KTP cards."""

from __future__ import annotations

from datetime import date

from PIL import Image, ImageDraw

from scripts.renderers import CARD_HEIGHT, CARD_WIDTH, KtpRecord, load_font


def _format_dmy(iso_date: str) -> str:
    """Format ISO YYYY-MM-DD date into Indonesian DD-MM-YYYY card format."""
    try:
        parsed = date.fromisoformat(iso_date)
    except ValueError:
        return iso_date
    return parsed.strftime("%d-%m-%Y")


def _draw_photo_box(draw: ImageDraw.ImageDraw, x0: int, y0: int, w: int, h: int) -> None:
    """Draw a synthetic studio portrait placeholder box on the right side of the card."""
    draw.rectangle((x0, y0, x0 + w, y0 + h), fill=(176, 46, 54), outline=(45, 70, 95), width=2)
    cx = x0 + w // 2
    head_r = w // 5
    draw.ellipse(
        (cx - head_r, y0 + 36, cx + head_r, y0 + 36 + head_r * 2),
        fill=(228, 198, 174),
        outline=(110, 82, 66),
        width=2,
    )
    draw.pieslice(
        (x0 + 24, y0 + 112, x0 + w - 24, y0 + h + 56),
        start=180,
        end=360,
        fill=(48, 62, 84),
    )
    label_font = load_font(13, bold=True)
    draw.text((x0 + 48, y0 + h - 24), "SYNTHETIC", fill=(235, 235, 235), font=label_font)


def render_ktp(record: KtpRecord) -> Image.Image:
    """Render an 856x540 synthetic Indonesian e-KTP card as a PIL Image."""
    image = Image.new("RGB", (CARD_WIDTH, CARD_HEIGHT), color=(184, 218, 238))
    draw = ImageDraw.Draw(image)

    # Subtle card frame and decorative top band
    draw.rectangle((12, 12, CARD_WIDTH - 12, CARD_HEIGHT - 12), outline=(42, 92, 134), width=3)
    draw.rectangle((15, 15, CARD_WIDTH - 15, 84), fill=(158, 202, 228))
    draw.line((15, 84, CARD_WIDTH - 15, 84), fill=(42, 92, 134), width=2)

    header_font = load_font(22, bold=True)
    sub_header_font = load_font(18, bold=True)
    nik_font = load_font(24, bold=True)
    label_font = load_font(14, bold=True)
    value_font = load_font(15, bold=False)

    draw.text(
        (CARD_WIDTH // 2, 34),
        f"PROVINSI {record.address.province}",
        fill=(18, 36, 56),
        font=header_font,
        anchor="mm",
    )
    draw.text(
        (CARD_WIDTH // 2, 64),
        f"KARTU TANDA PENDUDUK - {record.address.city_regency}",
        fill=(18, 36, 56),
        font=sub_header_font,
        anchor="mm",
    )

    draw.text((34, 102), "NIK", fill=(18, 36, 56), font=nik_font)
    draw.text((178, 102), f": {record.nik}", fill=(12, 24, 38), font=nik_font)

    rows: list[tuple[str, str]] = [
        ("Nama", record.full_name[:34]),
        ("Tempat/Tgl Lahir", f"{record.place_of_birth[:18]}, {_format_dmy(record.date_of_birth)}"),
        ("Jenis Kelamin", f"{record.gender}    Gol. Darah: {record.blood_type}"),
        ("Alamat", record.address.street[:36]),
        ("    RT/RW", record.address.rt_rw),
        ("    Kel/Desa", record.address.kelurahan_desa[:30]),
        ("    Kecamatan", record.address.kecamatan[:30]),
        ("Agama", record.religion),
        ("Status Perkawinan", record.marital_status),
        ("Pekerjaan", record.occupation),
        ("Kewarganegaraan", record.nationality),
        ("Berlaku Hingga", record.valid_until),
    ]

    y = 146
    for label, value in rows:
        draw.text((34, y), label, fill=(24, 44, 66), font=label_font)
        draw.text((200, y), f": {value}", fill=(14, 24, 36), font=value_font)
        y += 30

    _draw_photo_box(draw, 642, 118, 178, 224)

    # Issuing city & placeholder signature line below photo
    small_font = load_font(13, bold=False)
    draw.text(
        (731, 362),
        record.address.city_regency[:18],
        fill=(24, 44, 66),
        font=small_font,
        anchor="mm",
    )
    draw.line((666, 434, 796, 434), fill=(36, 56, 78), width=2)
    draw.arc((682, 396, 774, 436), start=180, end=350, fill=(24, 44, 66), width=2)

    return image


__all__ = ["render_ktp"]
