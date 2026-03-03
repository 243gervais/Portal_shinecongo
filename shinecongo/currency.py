from __future__ import annotations

import json
from datetime import datetime, timezone as dt_timezone
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.core.cache import cache
from django.utils import timezone

EXCHANGE_API_URL = "https://open.er-api.com/v6/latest/USD"
EXCHANGE_API_PROVIDER = "exchangerate-api (open.er-api.com)"
DEFAULT_USD_TO_CDF = Decimal("2216.615127")
DAILY_CACHE_TTL_SECONDS = 60 * 60 * 24 + 300
LAST_RATE_CACHE_TTL_SECONDS = 60 * 60 * 24 * 14


def _safe_decimal(value) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _cache_key_for_today() -> str:
    return f"fx:usd_to_cdf:{timezone.localdate().isoformat()}"


def _fetch_live_usd_to_cdf() -> dict | None:
    request = Request(
        EXCHANGE_API_URL,
        headers={"User-Agent": "portal-shinecongo/1.0"},
    )

    try:
        with urlopen(request, timeout=6) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (URLError, HTTPError, TimeoutError, ValueError, json.JSONDecodeError):
        return None

    if payload.get("result") != "success":
        return None

    rate = _safe_decimal(payload.get("rates", {}).get("CDF"))
    if not rate or rate <= 0:
        return None

    source_date = timezone.localdate()
    update_unix = payload.get("time_last_update_unix")
    if isinstance(update_unix, int):
        source_date = datetime.fromtimestamp(update_unix, dt_timezone.utc).date()

    return {
        "usd_to_cdf": str(rate),
        "source_date": source_date.isoformat(),
        "provider": EXCHANGE_API_PROVIDER,
    }


def get_usd_to_cdf_rate() -> dict:
    """
    Return USD->CDF rate data. Rate is refreshed daily and cached.
    """
    daily_key = _cache_key_for_today()
    cached = cache.get(daily_key)
    if cached:
        return cached

    live = _fetch_live_usd_to_cdf()
    if live:
        cache.set(daily_key, live, DAILY_CACHE_TTL_SECONDS)
        cache.set("fx:usd_to_cdf:last", live, LAST_RATE_CACHE_TTL_SECONDS)
        return live

    last_known = cache.get("fx:usd_to_cdf:last")
    if last_known:
        cache.set(daily_key, last_known, 60 * 60)
        return last_known

    fallback = {
        "usd_to_cdf": str(DEFAULT_USD_TO_CDF),
        "source_date": timezone.localdate().isoformat(),
        "provider": f"{EXCHANGE_API_PROVIDER} (fallback)",
    }
    cache.set(daily_key, fallback, 60 * 60)
    return fallback


def convert_cdf_to_usd(amount) -> dict:
    """
    Convert CDF amount to USD using cached daily rate.
    """
    amount_cdf = _safe_decimal(amount) or Decimal("0")
    rate_data = get_usd_to_cdf_rate()
    usd_to_cdf = _safe_decimal(rate_data.get("usd_to_cdf")) or DEFAULT_USD_TO_CDF

    if usd_to_cdf <= 0:
        usd_to_cdf = DEFAULT_USD_TO_CDF

    amount_usd = amount_cdf / usd_to_cdf
    return {
        "amount_cdf": amount_cdf,
        "amount_usd": amount_usd,
        "usd_to_cdf": usd_to_cdf,
        "source_date": rate_data.get("source_date"),
        "provider": rate_data.get("provider"),
    }
