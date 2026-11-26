"""Indonesian document plugins (e-KTP, SIM, NPWP)."""

from app.plugins.idn.ktp import IndonesiaKtpPlugin, KtpAddress, KtpData
from app.plugins.idn.nik_validator import ParsedNik, normalize_gender, parse_nik, validate_nik
from app.plugins.idn.province_codes import PROVINCE_NAMES, VALID_PROVINCE_CODES

__all__ = [
    "IndonesiaKtpPlugin",
    "KtpAddress",
    "KtpData",
    "PROVINCE_NAMES",
    "ParsedNik",
    "VALID_PROVINCE_CODES",
    "normalize_gender",
    "parse_nik",
    "validate_nik",
]
