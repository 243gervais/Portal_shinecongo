from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django import template
from django.utils.dateparse import parse_date

from shinecongo.currency import convert_cdf_to_usd, get_usd_to_cdf_rate

register = template.Library()


def _to_decimal(value) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def _format_number_without_decimals(value: Decimal) -> str:
    rounded = value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    sign = "-" if rounded < 0 else ""
    absolute = abs(int(rounded))
    return f"{sign}{absolute:,}".replace(",", " ")


@register.filter
def fc_amount(value):
    return _format_number_without_decimals(_to_decimal(value))


@register.filter
def usd_equivalent(value):
    conversion = convert_cdf_to_usd(value)
    amount_usd = conversion["amount_usd"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{amount_usd:,.2f}"


@register.simple_tag
def fx_rate_label():
    rate_data = get_usd_to_cdf_rate()
    usd_to_cdf = _to_decimal(rate_data.get("usd_to_cdf"))
    source_date = parse_date(rate_data.get("source_date") or "")
    source_date_label = source_date.strftime("%d/%m/%Y") if source_date else "aujourd'hui"
    return f"Taux du {source_date_label}: 1 USD = {_format_number_without_decimals(usd_to_cdf)} FC (mise a jour quotidienne)"
