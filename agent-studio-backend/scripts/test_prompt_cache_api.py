#!/usr/bin/env python3
"""
Prove GenAI proxy prompt caching requires cache_control on Bedrock Anthropic models.

Fair test: identical long system text; only difference is cache_control on the block.

Expected:
  - long_no_cache_control: cache_read=0, cache_creation=0 on all 3 calls
  - long_with_cache_control: cache_creation>0 on call 1, cache_read>0 on calls 2-3
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = REPO_ROOT / ".env"

MODEL = "bedrock.anthropic.claude-opus-4-6"
ITERATIONS = 3
USER_MSG = "Reply with exactly: OK"

# Same payload for both arms (~8k cached tokens when cache_control is set).
LONG_SYSTEM = (
    "You are a helpful assistant for cache testing. "
    "Do not repeat the reference block. "
    + ("Y" * 32000)
)


def load_env() -> tuple[str, str]:
    if not ENV_PATH.exists():
        sys.exit(f"Missing .env at {ENV_PATH}")
    url = key = None
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k == "GENAI_PROXY_URL":
            url = v
        elif k == "GENAI_PROXY_API_KEY":
            key = v
    if not url or not key:
        sys.exit("GENAI_PROXY_URL and GENAI_PROXY_API_KEY required in .env")
    return url.rstrip("/"), key


def messages_long_plain_string() -> list[dict]:
    """Same long system text, NO cache_control (plain string content)."""
    return [
        {"role": "system", "content": LONG_SYSTEM},
        {"role": "user", "content": USER_MSG},
    ]


def messages_long_with_cache_control() -> list[dict]:
    """Same long system text WITH cache_control ephemeral (structured content)."""
    return [
        {
            "role": "system",
            "content": [
                {
                    "type": "text",
                    "text": LONG_SYSTEM,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
        },
        {"role": "user", "content": USER_MSG},
    ]


def extract_usage(data: dict) -> dict:
    usage = data.get("usage") or {}
    details = usage.get("prompt_tokens_details") or usage.get("input_token_details") or {}
    return {
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0) or 0,
        "cache_creation_input_tokens": usage.get("cache_creation_input_tokens", 0) or 0,
        "cached_tokens": (
            usage.get("cached_tokens")
            or details.get("cached_tokens")
            or usage.get("input_cached_tokens")
            or 0
        ),
        "prompt_cache_creation_tokens": details.get("cache_creation_tokens", 0) or 0,
    }


def call_chat(base_url: str, api_key: str, messages: list[dict]) -> dict:
    url = f"{base_url}/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "API-Key": api_key,
        "Content-Type": "application/json",
    }
    body = {
        "model": MODEL,
        "messages": messages,
        "max_tokens": 16,
        "temperature": 0,
    }
    with httpx.Client(timeout=120.0) as client:
        resp = client.post(url, headers=headers, json=body)
    if resp.status_code >= 400:
        return {"status": resp.status_code, "error": resp.text[:800]}
    data = resp.json()
    return {"status": resp.status_code, "usage": extract_usage(data)}


def run_series(base_url: str, api_key: str, messages_fn, label: str) -> list[dict]:
    rows = []
    for i in range(1, ITERATIONS + 1):
        result = call_chat(base_url, api_key, messages_fn())
        u = result.get("usage") or {}
        rows.append({"label": label, "iteration": i, **u, "status": result.get("status")})
        print(
            f"  [{i}] cache_read={u.get('cache_read_input_tokens', 0)} "
            f"cache_create={u.get('cache_creation_input_tokens', 0)} "
            f"prompt_tokens={u.get('prompt_tokens', 0)}"
        )
    return rows


def evaluate_proof(rows: list[dict], label: str) -> dict:
    reads = [r["cache_read_input_tokens"] for r in rows]
    creates = [r["cache_creation_input_tokens"] for r in rows]
    if label == "long_plain_no_cache_control":
        ok = all(v == 0 for v in reads) and all(v == 0 for v in creates)
        return {
            "passed": ok,
            "expectation": "All iterations: cache_read=0 AND cache_creation=0",
            "reads": reads,
            "creates": creates,
        }
    # long_with_cache_control
    ok = creates[0] > 0 and reads[1] > 0 and reads[2] > 0
    return {
        "passed": ok,
        "expectation": "Call 1: cache_creation>0; calls 2-3: cache_read>0",
        "reads": reads,
        "creates": creates,
    }


def main() -> None:
    base_url, api_key = load_env()
    print("GenAI proxy prompt-cache proof")
    print(f"  URL:   {base_url}")
    print(f"  Model: {MODEL}")
    print(f"  System text length: {len(LONG_SYSTEM)} chars (identical in both arms)")
    print()

    all_rows: list[dict] = []

    print("A) Long system, plain string — NO cache_control (3 identical calls)")
    a_rows = run_series(base_url, api_key, messages_long_plain_string, "long_plain_no_cache_control")
    all_rows.extend(a_rows)
    print()

    print("B) Long system, structured block — WITH cache_control ephemeral (3 identical calls)")
    b_rows = run_series(base_url, api_key, messages_long_with_cache_control, "long_with_cache_control")
    all_rows.extend(b_rows)
    print()

    proof_a = evaluate_proof(a_rows, "long_plain_no_cache_control")
    proof_b = evaluate_proof(b_rows, "long_with_cache_control")

    print("=== Summary ===")
    print(f"{'arm':<35} {'iter':<5} {'cache_read':<12} {'cache_create':<14} {'prompt_tokens'}")
    for r in all_rows:
        print(
            f"{r['label']:<35} {r['iteration']:<5} "
            f"{r['cache_read_input_tokens']:<12} {r['cache_creation_input_tokens']:<14} {r['prompt_tokens']}"
        )
    print()
    print("=== Proof verdict ===")
    print(f"A (no cache_control):  {'PASS' if proof_a['passed'] else 'FAIL'} — {proof_a['expectation']}")
    print(f"   cache_read per call:      {proof_a['reads']}")
    print(f"   cache_creation per call:  {proof_a['creates']}")
    print()
    print(f"B (with cache_control): {'PASS' if proof_b['passed'] else 'FAIL'} — {proof_b['expectation']}")
    print(f"   cache_read per call:      {proof_b['reads']}")
    print(f"   cache_creation per call:  {proof_b['creates']}")
    print()
    if proof_a["passed"] and proof_b["passed"]:
        print("PROVEN: cache_control is required for Bedrock prompt cache on this proxy.")
        print("       Same long prompt without it never populates cache_* usage fields.")
        sys.exit(0)
    print("INCONCLUSIVE or FAILED — check proxy/model support or prompt size.")
    sys.exit(1)


if __name__ == "__main__":
    main()
