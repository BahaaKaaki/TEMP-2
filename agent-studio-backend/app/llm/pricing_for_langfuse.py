"""
Map catalog pricing to Langfuse model definitions and optional per-generation cost_details.

Langfuse matches usage_details keys to pricing tier ``prices`` keys exactly.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional

_TOKENS_PER_1M = Decimal("1000000")

# Default multipliers when cache prices are unset (Anthropic-style list pricing).
_DEFAULT_CACHE_READ_RATIO = Decimal("0.1")
_DEFAULT_CACHE_CREATION_RATIO = Decimal("1.25")

# usage_details key -> catalog column name (per 1M USD)
_USAGE_PRICE_FIELDS: Dict[str, str] = {
    "input": "input_price_per_1m_tokens",
    "output": "output_price_per_1m_tokens",
    "cache_read_input_tokens": "cache_read_price_per_1m_tokens",
    "input_cached_tokens": "cache_read_price_per_1m_tokens",
    "input_cache_read": "cache_read_price_per_1m_tokens",
    "cache_creation_input_tokens": "cache_creation_price_per_1m_tokens",
    "input_cache_creation": "cache_creation_price_per_1m_tokens",
    "output_reasoning_tokens": "output_price_per_1m_tokens",
    "output_reasoning": "output_price_per_1m_tokens",
}


def _decimal_to_float(value: Optional[Decimal]) -> Optional[float]:
    if value is None:
        return None
    return float(value)


def _price_per_token(price_per_1m: Optional[Decimal]) -> Optional[float]:
    if price_per_1m is None:
        return None
    return float(price_per_1m / _TOKENS_PER_1M)


def resolve_model_pricing(row: Any) -> Dict[str, Optional[float]]:
    """Effective USD per 1M tokens including defaults for cache when input is set."""
    input_p = getattr(row, "input_price_per_1m_tokens", None)
    output_p = getattr(row, "output_price_per_1m_tokens", None)
    cache_read = getattr(row, "cache_read_price_per_1m_tokens", None)
    cache_create = getattr(row, "cache_creation_price_per_1m_tokens", None)

    if cache_read is None and input_p is not None:
        cache_read = input_p * _DEFAULT_CACHE_READ_RATIO
    if cache_create is None and input_p is not None:
        cache_create = input_p * _DEFAULT_CACHE_CREATION_RATIO

    return {
        "input_price_per_1m_tokens": _decimal_to_float(input_p),
        "output_price_per_1m_tokens": _decimal_to_float(output_p),
        "cache_read_price_per_1m_tokens": _decimal_to_float(cache_read),
        "cache_creation_price_per_1m_tokens": _decimal_to_float(cache_create),
    }


def build_langfuse_tier_prices(row: Any) -> Dict[str, float]:
    """Per-token USD prices keyed for Langfuse usage_details / pricingTiers."""
    pricing = resolve_model_pricing(row)
    prices: Dict[str, float] = {}

    input_pt = _price_per_token(
        Decimal(str(pricing["input_price_per_1m_tokens"]))
        if pricing.get("input_price_per_1m_tokens") is not None
        else None
    )
    output_pt = _price_per_token(
        Decimal(str(pricing["output_price_per_1m_tokens"]))
        if pricing.get("output_price_per_1m_tokens") is not None
        else None
    )
    cache_read_pt = _price_per_token(
        Decimal(str(pricing["cache_read_price_per_1m_tokens"]))
        if pricing.get("cache_read_price_per_1m_tokens") is not None
        else None
    )
    cache_create_pt = _price_per_token(
        Decimal(str(pricing["cache_creation_price_per_1m_tokens"]))
        if pricing.get("cache_creation_price_per_1m_tokens") is not None
        else None
    )

    if input_pt is not None:
        prices["input"] = input_pt
    if output_pt is not None:
        prices["output"] = output_pt
        prices["output_reasoning_tokens"] = output_pt
        prices["output_reasoning"] = output_pt
    if cache_read_pt is not None:
        prices["cache_read_input_tokens"] = cache_read_pt
        prices["input_cached_tokens"] = cache_read_pt
        prices["input_cache_read"] = cache_read_pt
    if cache_create_pt is not None:
        prices["cache_creation_input_tokens"] = cache_create_pt
        prices["input_cache_creation"] = cache_create_pt

    return prices


def build_langfuse_pricing_tiers(row: Any) -> Optional[List[Dict[str, Any]]]:
    prices = build_langfuse_tier_prices(row)
    if not prices:
        return None
    return [
        {
            "name": "Standard",
            "isDefault": True,
            "priority": 0,
            "conditions": [],
            "prices": prices,
        }
    ]


def has_any_catalog_pricing(row: Any) -> bool:
    return (
        getattr(row, "input_price_per_1m_tokens", None) is not None
        or getattr(row, "output_price_per_1m_tokens", None) is not None
    )


def compute_cost_details(
    usage: Dict[str, int],
    *,
    model_name: str,
    catalog_pricing: Optional[Dict[str, Optional[float]]] = None,
) -> Optional[Dict[str, float]]:
    """
    Per-token USD rates for Langfuse cost_details (keys match usage_details).

    Langfuse multiplies these rates by ingested token counts. Rates mirror the
    catalog / pricingTiers synced via LangfuseModelSyncService.
    """
    if catalog_pricing is None:
        from app.llm.registry import LlmModelRegistry

        catalog_pricing = LlmModelRegistry.get_model_pricing(model_name)
    if not catalog_pricing:
        return None

    rates: Dict[str, float] = {}
    seen_fields: set[str] = set()
    for usage_key, token_count in usage.items():
        if token_count <= 0:
            continue
        field = _USAGE_PRICE_FIELDS.get(usage_key)
        if not field or field in seen_fields:
            continue
        price_per_1m = catalog_pricing.get(field)
        if price_per_1m is None:
            continue
        seen_fields.add(field)
        per_token = price_per_1m / 1_000_000
        rates[usage_key] = per_token
        # Mirror aliases Langfuse accepts on the same tier
        if field == "cache_read_price_per_1m_tokens":
            for alias in (
                "cache_read_input_tokens",
                "input_cached_tokens",
                "input_cache_read",
            ):
                if alias not in rates:
                    rates[alias] = per_token
        elif field == "cache_creation_price_per_1m_tokens":
            for alias in ("cache_creation_input_tokens", "input_cache_creation"):
                if alias not in rates:
                    rates[alias] = per_token
        elif field == "output_price_per_1m_tokens":
            for alias in ("output_reasoning_tokens", "output_reasoning"):
                if alias not in rates:
                    rates[alias] = per_token

    return rates or None
