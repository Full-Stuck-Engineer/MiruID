"""Official Kemendagri 2-digit Indonesian province codes (all 38 provinces)."""

from __future__ import annotations

PROVINCE_NAMES: dict[str, str] = {
    # Sumatra (10)
    "11": "Aceh",
    "12": "Sumatera Utara",
    "13": "Sumatera Barat",
    "14": "Riau",
    "15": "Jambi",
    "16": "Sumatera Selatan",
    "17": "Bengkulu",
    "18": "Lampung",
    "19": "Kepulauan Bangka Belitung",
    "21": "Kepulauan Riau",
    # Java (6)
    "31": "DKI Jakarta",
    "32": "Jawa Barat",
    "33": "Jawa Tengah",
    "34": "DI Yogyakarta",
    "35": "Jawa Timur",
    "36": "Banten",
    # Bali & Nusa Tenggara (3)
    "51": "Bali",
    "52": "Nusa Tenggara Barat",
    "53": "Nusa Tenggara Timur",
    # Kalimantan (5)
    "61": "Kalimantan Barat",
    "62": "Kalimantan Tengah",
    "63": "Kalimantan Selatan",
    "64": "Kalimantan Timur",
    "65": "Kalimantan Utara",
    # Sulawesi (6)
    "71": "Sulawesi Utara",
    "72": "Sulawesi Tengah",
    "73": "Sulawesi Selatan",
    "74": "Sulawesi Tenggara",
    "75": "Gorontalo",
    "76": "Sulawesi Barat",
    # Maluku (2)
    "81": "Maluku",
    "82": "Maluku Utara",
    # Papua (6, including 2022 new autonomous provinces 93-96)
    "91": "Papua",
    "92": "Papua Barat",
    "93": "Papua Selatan",
    "94": "Papua Tengah",
    "95": "Papua Pegunungan",
    "96": "Papua Barat Daya",
}

VALID_PROVINCE_CODES: frozenset[str] = frozenset(PROVINCE_NAMES)

__all__ = ["PROVINCE_NAMES", "VALID_PROVINCE_CODES"]
