"""Tests for Langfuse pricing tier and cost mapping."""

from decimal import Decimal
from types import SimpleNamespace

from app.llm.pricing_for_langfuse import (
    build_langfuse_pricing_tiers,
    build_langfuse_tier_prices,
    compute_cost_details,
    resolve_model_pricing,
)


def _row(**kwargs):
    defaults = {
        "model_name": "bedrock.anthropic.claude-sonnet-4-6",
        "input_price_per_1m_tokens": Decimal("3"),
        "output_price_per_1m_tokens": Decimal("15"),
        "cache_read_price_per_1m_tokens": None,
        "cache_creation_price_per_1m_tokens": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_resolve_defaults_cache_from_input():
    pricing = resolve_model_pricing(_row())
    assert pricing["cache_read_price_per_1m_tokens"] == 0.3
    assert pricing["cache_creation_price_per_1m_tokens"] == 3.75


def test_build_langfuse_tier_prices_includes_cache_keys():
    prices = build_langfuse_tier_prices(_row())
    assert "input" in prices
    assert "cache_read_input_tokens" in prices
    assert "cache_creation_input_tokens" in prices
    assert prices["cache_read_input_tokens"] < prices["input"]


def test_build_pricing_tiers_structure():
    tiers = build_langfuse_pricing_tiers(_row())
    assert len(tiers) == 1
    assert tiers[0]["isDefault"] is True
    assert tiers[0]["prices"]["input"] > 0


def test_compute_cost_details_per_token_rates():
    usage = {
        "input": 100,
        "cache_read_input_tokens": 80,
        "output": 10,
    }
    costs = compute_cost_details(
        usage,
        model_name="test",
        catalog_pricing={
            "input_price_per_1m_tokens": 3.0,
            "output_price_per_1m_tokens": 15.0,
            "cache_read_price_per_1m_tokens": 0.3,
            "cache_creation_price_per_1m_tokens": 3.75,
        },
    )
    assert costs is not None
    assert costs["input"] == 3.0 / 1_000_000
    assert costs["cache_read_input_tokens"] == 0.3 / 1_000_000
