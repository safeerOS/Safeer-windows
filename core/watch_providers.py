"""Country selection and lawful TMDB watch-provider link helpers."""
from __future__ import annotations

import ctypes
import locale
import os
import re


_LANGUAGE_COUNTRIES = {
    "sl": "SI", "de": "DE", "en": "US", "fr": "FR", "es": "ES", "it": "IT",
    "pt": "PT", "nl": "NL", "pl": "PL", "hr": "HR", "sr": "RS", "da": "DK",
    "sv": "SE", "no": "NO", "fi": "FI", "cs": "CZ", "sk": "SK", "hu": "HU",
    "ro": "RO", "bg": "BG", "el": "GR", "tr": "TR", "uk": "UA", "ru": "RU",
    "ja": "JP", "ko": "KR", "zh": "CN", "ar": "SA",
}


def _valid_country(value: str | None) -> str | None:
    candidate = str(value or "").strip().upper()
    return candidate if re.fullmatch(r"[A-Z]{2}", candidate) else None


def _windows_geo_country(ctypes_module=None) -> str | None:
    """Read Windows' user-selected region without any network geolocation."""
    c = ctypes_module or ctypes
    try:
        kernel = c.WinDLL("kernel32", use_last_error=True)
        geo_id = kernel.GetUserGeoID(16)  # GEOCLASS_NATION
        if geo_id <= 0:
            return None
        buffer = c.create_unicode_buffer(3)
        result = kernel.GetGeoInfoW(geo_id, 4, buffer, len(buffer), 0)  # GEO_ISO2
        return _valid_country(buffer.value) if result else None
    except Exception:
        return None


def country_from_locale(value: str | None) -> str | None:
    """Extract ISO-3166 alpha-2 region from a locale or map its language."""
    raw = str(value or "").strip()
    if not raw:
        return None
    normalized = raw.split(".", 1)[0].split("@", 1)[0].replace("-", "_")
    parts = normalized.split("_")
    if len(parts) > 1:
        region = _valid_country(parts[1])
        if region:
            return region
    return _LANGUAGE_COUNTRIES.get(parts[0].lower())


def detect_country(app_language: str = "", *, platform_name: str | None = None,
                   ctypes_module=None, locale_values=None) -> str:
    """Windows geo ID, system locale/LANG, app language, then US."""
    platform_name = platform_name or os.name
    if platform_name == "nt":
        country = _windows_geo_country(ctypes_module)
        if country:
            return country
    values = locale_values
    if values is None:
        values = [os.environ.get(name, "") for name in ("LC_ALL", "LC_MESSAGES", "LANG")]
        try:
            values.append(locale.getlocale()[0] or "")
        except Exception:
            pass
    for value in values:
        country = country_from_locale(value)
        if country:
            return country
    return country_from_locale(app_language) or "US"
