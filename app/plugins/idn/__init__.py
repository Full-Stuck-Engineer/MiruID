"""Indonesian document plugins (e-KTP, SIM, NPWP)."""

from app.plugins.idn.ktp import IndonesiaKtpPlugin, KtpAddress, KtpData
from app.plugins.idn.nik_validator import ParsedNik, normalize_gender, parse_nik, validate_nik
from app.plugins.idn.npwp import IndonesiaNpwpPlugin, NpwpData
from app.plugins.idn.npwp_validator import (
    extract_kpp_code,
    normalize_npwp_15,
    normalize_npwp_16,
    validate_npwp,
)
from app.plugins.idn.province_codes import PROVINCE_NAMES, VALID_PROVINCE_CODES
from app.plugins.idn.sim import IndonesiaSimPlugin, SimClass, SimData, normalize_sim_class
from app.plugins.idn.sim_validator import clean_sim_number, validate_sim

__all__ = [
    "IndonesiaKtpPlugin",
    "IndonesiaNpwpPlugin",
    "IndonesiaSimPlugin",
    "KtpAddress",
    "KtpData",
    "NpwpData",
    "PROVINCE_NAMES",
    "ParsedNik",
    "SimClass",
    "SimData",
    "VALID_PROVINCE_CODES",
    "clean_sim_number",
    "extract_kpp_code",
    "normalize_gender",
    "normalize_npwp_15",
    "normalize_npwp_16",
    "normalize_sim_class",
    "parse_nik",
    "validate_nik",
    "validate_npwp",
    "validate_sim",
]
