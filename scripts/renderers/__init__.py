"""Shared font helpers and deterministic synthetic Indonesian identity generators.

All generated data is 100% synthetic (zero real PII) and mathematically valid
according to MiruID's e-KTP, SIM, and NPWP plugin validators.
"""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal

from faker import Faker
from PIL import ImageFont

from app.domain.schemas import ExtractedField
from app.plugins.idn.ktp import KtpAddress, KtpData
from app.plugins.idn.npwp import NpwpData
from app.plugins.idn.province_codes import PROVINCE_NAMES, VALID_PROVINCE_CODES
from app.plugins.idn.sim import SimData
from app.plugins.idn.sim_validator import SimClass

CARD_WIDTH = 856
CARD_HEIGHT = 540

SimVariant = Literal["legacy", "nik_linked"]
NpwpVariant = Literal["legacy_15", "individual_16", "corporate_16"]
FontType = ImageFont.FreeTypeFont | ImageFont.ImageFont

_SORTED_PROVINCE_CODES: tuple[str, ...] = tuple(sorted(VALID_PROVINCE_CODES))
_SIM_CLASSES: tuple[str, ...] = tuple(member.value for member in SimClass)
_BLOOD_TYPES: tuple[str, ...] = ("A", "B", "AB", "O")
_RELIGIONS: tuple[str, ...] = ("ISLAM", "KRISTEN", "KATOLIK", "HINDU", "BUDDHA", "KONGHUCU")
_MARITAL_STATUSES: tuple[str, ...] = ("BELUM KAWIN", "KAWIN", "CERAI HIDUP", "CERAI MATI")
_OCCUPATIONS: tuple[str, ...] = (
    "KARYAWAN SWASTA",
    "WIRASWASTA",
    "PEGAWAI NEGERI SIPIL",
    "PELAJAR/MAHASISWA",
    "DOKTER",
    "GURU",
)
_ISSUING_OFFICES: tuple[str, ...] = (
    "METRO JAYA",
    "JAWA BARAT",
    "JAWA TENGAH",
    "JAWA TIMUR",
    "BALI",
    "SUMATERA UTARA",
)

_REGULAR_FONT_CANDIDATES: tuple[str, ...] = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/Library/Fonts/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "DejaVuSans.ttf",
)
_BOLD_FONT_CANDIDATES: tuple[str, ...] = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "DejaVuSans-Bold.ttf",
)


def load_font(size: int, *, bold: bool = False) -> FontType:
    """Load a TrueType sans-serif font with graceful fallback to Pillow's default."""
    candidates = _BOLD_FONT_CANDIDATES if bold else _REGULAR_FONT_CANDIDATES
    for candidate in candidates:
        path = Path(candidate)
        if path.is_absolute() and not path.exists():
            continue
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _create_faker(seed: int) -> Faker:
    """Create an isolated, deterministically seeded Indonesian Faker instance."""
    fake = Faker("id_ID")
    fake.seed_instance(seed)
    return fake


def _clean_upper(text: str) -> str:
    """Normalize generated text to single-line uppercase ASCII-friendly strings."""
    return " ".join(text.replace("\n", " ").strip().split()).upper()


def _generate_birth_date(rng: random.Random) -> date:
    """Generate a deterministic adult birth date (age >= 21 in 2026)."""
    year = rng.randint(1965, 2004)
    month = rng.randint(1, 12)
    day = rng.randint(1, 28)
    return date(year, month, day)


def generate_valid_nik(
    rng: random.Random,
    *,
    birth_date: date,
    gender: Literal["LAKI-LAKI", "PEREMPUAN"],
    province_code: str | None = None,
) -> tuple[str, str]:
    """Generate a mathematically valid 16-digit Indonesian NIK and its province code."""
    prov = (
        province_code
        if province_code in VALID_PROVINCE_CODES
        else rng.choice(_SORTED_PROVINCE_CODES)
    )
    regency = f"{rng.randint(1, 79):02d}"
    district = f"{rng.randint(1, 25):02d}"
    day_encoded = birth_date.day + (40 if gender == "PEREMPUAN" else 0)
    ddmmyy = f"{day_encoded:02d}{birth_date.month:02d}{birth_date.year % 100:02d}"
    serial = f"{rng.randint(1, 9999):04d}"
    return f"{prov}{regency}{district}{ddmmyy}{serial}", prov


def _field(value: str | None) -> ExtractedField[str]:
    """Build a full-confidence synthetic ExtractedField."""
    return ExtractedField[str](value=value, confidence=1.0, source="synthetic")


@dataclass(frozen=True, slots=True)
class KtpAddressRecord:
    """Synthetic e-KTP address ground-truth fields."""

    street: str
    rt_rw: str
    kelurahan_desa: str
    kecamatan: str
    city_regency: str
    province: str


@dataclass(frozen=True, slots=True)
class KtpRecord:
    """Synthetic e-KTP ground-truth record."""

    nik: str
    full_name: str
    place_of_birth: str
    date_of_birth: str
    gender: Literal["LAKI-LAKI", "PEREMPUAN"]
    blood_type: str
    address: KtpAddressRecord
    religion: str
    marital_status: str
    occupation: str
    nationality: str
    valid_until: str

    def to_dict(self) -> dict[str, Any]:
        """Serialize record to a JSON-compatible dictionary."""
        return asdict(self)

    def to_schema(self) -> KtpData:
        """Convert synthetic ground truth to a KtpData model for plugin validation."""
        return KtpData(
            nik=_field(self.nik),
            full_name=_field(self.full_name),
            place_of_birth=_field(self.place_of_birth),
            date_of_birth=_field(self.date_of_birth),
            gender=_field(self.gender),
            blood_type=_field(self.blood_type),
            address=KtpAddress(
                street=_field(self.address.street),
                rt_rw=_field(self.address.rt_rw),
                kelurahan_desa=_field(self.address.kelurahan_desa),
                kecamatan=_field(self.address.kecamatan),
                city_regency=_field(self.address.city_regency),
                province=_field(self.address.province),
            ),
            religion=_field(self.religion),
            marital_status=_field(self.marital_status),
            occupation=_field(self.occupation),
            nationality=_field(self.nationality),
            valid_until=_field(self.valid_until),
        )


@dataclass(frozen=True, slots=True)
class SimRecord:
    """Synthetic SIM ground-truth record."""

    sim_number: str
    sim_class: str
    full_name: str
    place_of_birth: str
    date_of_birth: str
    blood_type: str
    gender: Literal["LAKI-LAKI", "PEREMPUAN"]
    address: str
    occupation: str
    issuing_office: str
    valid_until: str
    variant: SimVariant

    def to_dict(self) -> dict[str, Any]:
        """Serialize record to a JSON-compatible dictionary."""
        return asdict(self)

    def to_schema(self) -> SimData:
        """Convert synthetic ground truth to a SimData model for plugin validation."""
        return SimData(
            sim_number=_field(self.sim_number),
            sim_class=_field(self.sim_class),
            full_name=_field(self.full_name),
            place_of_birth=_field(self.place_of_birth),
            date_of_birth=_field(self.date_of_birth),
            blood_type=_field(self.blood_type),
            gender=_field(self.gender),
            address=_field(self.address),
            occupation=_field(self.occupation),
            issuing_office=_field(self.issuing_office),
            valid_until=_field(self.valid_until),
        )


@dataclass(frozen=True, slots=True)
class NpwpRecord:
    """Synthetic NPWP ground-truth record."""

    npwp_15: str | None
    npwp_16: str | None
    taxpayer_name: str
    address: str
    kpp_name: str
    kpp_code: str
    registered_date: str
    variant: NpwpVariant

    def to_dict(self) -> dict[str, Any]:
        """Serialize record to a JSON-compatible dictionary."""
        return asdict(self)

    def to_schema(self) -> NpwpData:
        """Convert synthetic ground truth to an NpwpData model for plugin validation."""
        return NpwpData(
            npwp_15=_field(self.npwp_15),
            npwp_16=_field(self.npwp_16),
            taxpayer_name=_field(self.taxpayer_name),
            address=_field(self.address),
            kpp_name=_field(self.kpp_name),
            kpp_code=_field(self.kpp_code),
            registered_date=_field(self.registered_date),
        )


def generate_ktp_record(seed: int = 42) -> KtpRecord:
    """Generate a deterministic, validator-compliant synthetic e-KTP record."""
    rng = random.Random(seed)
    fake = _create_faker(seed)

    birth_date = _generate_birth_date(rng)
    gender: Literal["LAKI-LAKI", "PEREMPUAN"] = rng.choice(("LAKI-LAKI", "PEREMPUAN"))
    nik, prov_code = generate_valid_nik(rng, birth_date=birth_date, gender=gender)
    city = _clean_upper(fake.city())

    return KtpRecord(
        nik=nik,
        full_name=_clean_upper(fake.name()),
        place_of_birth=city,
        date_of_birth=birth_date.isoformat(),
        gender=gender,
        blood_type=rng.choice(_BLOOD_TYPES),
        address=KtpAddressRecord(
            street=_clean_upper(fake.street_address()),
            rt_rw=f"{rng.randint(1, 20):03d}/{rng.randint(1, 15):03d}",
            kelurahan_desa=_clean_upper(fake.city_name()),
            kecamatan=_clean_upper(fake.city_name()),
            city_regency=city,
            province=PROVINCE_NAMES[prov_code].upper(),
        ),
        religion=rng.choice(_RELIGIONS),
        marital_status=rng.choice(_MARITAL_STATUSES),
        occupation=rng.choice(_OCCUPATIONS),
        nationality="WNI",
        valid_until="SEUMUR HIDUP",
    )


def generate_sim_record(seed: int = 42, *, variant: SimVariant | None = None) -> SimRecord:
    """Generate a deterministic, validator-compliant synthetic SIM record."""
    rng = random.Random(seed)
    fake = _create_faker(seed)

    chosen_variant: SimVariant = (
        variant if variant is not None else rng.choice(("legacy", "nik_linked"))
    )
    birth_date = _generate_birth_date(rng)
    gender: Literal["LAKI-LAKI", "PEREMPUAN"] = rng.choice(("LAKI-LAKI", "PEREMPUAN"))

    if chosen_variant == "nik_linked":
        sim_number, _ = generate_valid_nik(rng, birth_date=birth_date, gender=gender)
    else:
        digit_len = rng.choice((12, 13, 14))
        first_digit = str(rng.randint(1, 9))
        rest = "".join(str(rng.randint(0, 9)) for _ in range(digit_len - 1))
        sim_number = first_digit + rest

    future_year = max(date.today().year + 2, 2030) + rng.randint(0, 3)
    valid_until = date(future_year, birth_date.month, birth_date.day).isoformat()

    return SimRecord(
        sim_number=sim_number,
        sim_class=rng.choice(_SIM_CLASSES),
        full_name=_clean_upper(fake.name()),
        place_of_birth=_clean_upper(fake.city()),
        date_of_birth=birth_date.isoformat(),
        blood_type=rng.choice(_BLOOD_TYPES),
        gender=gender,
        address=_clean_upper(f"{fake.street_address()}, {fake.city()}"),
        occupation=rng.choice(_OCCUPATIONS),
        issuing_office=rng.choice(_ISSUING_OFFICES),
        valid_until=valid_until,
        variant=chosen_variant,
    )


def _format_npwp_15(digits: str) -> str:
    """Format 15 ASCII digits as XX.XXX.XXX.X-XXX.XXX."""
    return f"{digits[0:2]}.{digits[2:5]}.{digits[5:8]}.{digits[8]}-{digits[9:12]}.{digits[12:15]}"


def generate_npwp_record(seed: int = 42, *, variant: NpwpVariant | None = None) -> NpwpRecord:
    """Generate a deterministic, validator-compliant synthetic NPWP record."""
    rng = random.Random(seed)
    fake = _create_faker(seed)

    chosen_variant: NpwpVariant = (
        variant
        if variant is not None
        else rng.choice(("legacy_15", "individual_16", "corporate_16"))
    )

    prefix_2 = f"{rng.randint(1, 99):02d}"
    mid_6 = f"{rng.randint(100000, 999999):06d}"
    check_1 = str(rng.randint(0, 9))
    kpp_code = f"{rng.randint(1, 999):03d}"
    branch_3 = "000"
    digits_15 = f"{prefix_2}{mid_6}{check_1}{kpp_code}{branch_3}"
    formatted_15 = _format_npwp_15(digits_15)

    city = _clean_upper(fake.city())
    reg_date = date(rng.randint(2015, 2024), rng.randint(1, 12), rng.randint(1, 28)).isoformat()

    if chosen_variant == "legacy_15":
        npwp_15: str | None = formatted_15
        npwp_16: str | None = None
        taxpayer_name = _clean_upper(fake.name())
    elif chosen_variant == "individual_16":
        birth_date = _generate_birth_date(rng)
        gender: Literal["LAKI-LAKI", "PEREMPUAN"] = rng.choice(("LAKI-LAKI", "PEREMPUAN"))
        nik, _ = generate_valid_nik(rng, birth_date=birth_date, gender=gender)
        npwp_15 = formatted_15
        npwp_16 = nik
        taxpayer_name = _clean_upper(fake.name())
    else:
        npwp_15 = formatted_15
        npwp_16 = f"0{digits_15}"
        taxpayer_name = _clean_upper(f"PT {fake.company()}")

    return NpwpRecord(
        npwp_15=npwp_15,
        npwp_16=npwp_16,
        taxpayer_name=taxpayer_name,
        address=_clean_upper(f"{fake.street_address()}, {city}"),
        kpp_name=f"KPP PRATAMA {city}",
        kpp_code=kpp_code,
        registered_date=reg_date,
        variant=chosen_variant,
    )


__all__ = [
    "CARD_HEIGHT",
    "CARD_WIDTH",
    "FontType",
    "KtpAddressRecord",
    "KtpRecord",
    "NpwpRecord",
    "NpwpVariant",
    "SimRecord",
    "SimVariant",
    "generate_ktp_record",
    "generate_npwp_record",
    "generate_sim_record",
    "generate_valid_nik",
    "load_font",
]
