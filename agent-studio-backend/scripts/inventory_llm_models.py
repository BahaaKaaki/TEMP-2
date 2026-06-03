#!/usr/bin/env python3
"""
Repo-wide LLM model inventory tool (Task 0).

Usage:
  python scripts/inventory_llm_models.py scan
  python scripts/inventory_llm_models.py verify
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "config" / "llm_models_inventory.yaml"
APP = ROOT / "app"

MODEL_PATTERNS = [
    re.compile(r'^[A-Z][A-Z0-9_]*_MODEL\s*=\s*["\']([^"\']+)["\']'),
    re.compile(r'get_client\(\s*[^)]*model\s*=\s*["\']([^"\']+)["\']'),
    re.compile(r'model\s*=\s*["\']([^"\']+)["\']'),
]

SKIP_DIRS = {"__pycache__", ".venv", "venv", "node_modules"}


def scan_py_files() -> list[tuple[str, int, str, str]]:
    findings = []
    for path in APP.rglob("*.py"):
        if any(p in path.parts for p in SKIP_DIRS):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        rel = str(path.relative_to(ROOT))
        for i, line in enumerate(text.splitlines(), 1):
            for pat in MODEL_PATTERNS:
                m = pat.search(line)
                if m:
                    val = m.group(1)
                    if any(
                        x in val.lower()
                        for x in ("gpt", "claude", "gemini", "o1", "o3", "o4", "openai.", "bedrock.", "vertex")
                    ):
                        findings.append((rel, i, line.strip(), val))
    return findings


def load_inventory_models() -> set[str]:
    import yaml

    if not INVENTORY.exists():
        return set()
    data = yaml.safe_load(INVENTORY.read_text(encoding="utf-8")) or {}
    models = {m["model_name"] for m in data.get("models", []) if m.get("model_name")}
    for b in data.get("bindings", []):
        if b.get("primary_model_name"):
            models.add(b["primary_model_name"])
        fb = data.get("fallback_model_name") or (data.get("models") and None)
    for m in data.get("models", []):
        if m.get("fallback_model_name"):
            models.add(m["fallback_model_name"])
    return models


def cmd_scan() -> int:
    findings = scan_py_files()
    print(f"Found {len(findings)} potential hardcoded model references in app/:\n")
    for rel, line_no, line, val in sorted(findings):
        print(f"  {rel}:{line_no}  {val}")
        print(f"    {line[:100]}")
    print(f"\nInventory file: {INVENTORY}")
    inv_models = load_inventory_models()
    print(f"Inventory lists {len(inv_models)} model names")
    return 0


def cmd_verify() -> int:
    import yaml

    if not INVENTORY.exists():
        print("ERROR: inventory YAML missing", file=sys.stderr)
        return 1

    data = yaml.safe_load(INVENTORY.read_text(encoding="utf-8")) or {}
    registered = set()
    for m in data.get("models", []):
        registered.add(m["model_name"])
        if m.get("fallback_model_name"):
            registered.add(m["fallback_model_name"])
    for b in data.get("bindings", []):
        registered.add(b["primary_model_name"])

    findings = scan_py_files()
    errors = []
    for rel, line_no, _line, val in findings:
        if "registry" in rel or "llm_config" in rel:
            continue
        # Unprefixed short names may differ from catalog — flag for review
        if val not in registered and not val.startswith(("openai.", "bedrock.", "vertex_ai.")):
            # try normalized — still report
            errors.append(f"{rel}:{line_no} model '{val}' not in inventory YAML")

    if errors:
        print("VERIFY FAILED — unregistered hardcoded models:", file=sys.stderr)
        for e in errors[:30]:
            print(f"  {e}", file=sys.stderr)
        if len(errors) > 30:
            print(f"  ... and {len(errors) - 30} more", file=sys.stderr)
        return 1

    print("VERIFY OK — scan findings are covered or use registry (post-refactor).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="LLM model inventory")
    parser.add_argument("command", choices=["scan", "verify"], nargs="?", default="scan")
    args = parser.parse_args()
    if args.command == "verify":
        return cmd_verify()
    return cmd_scan()


if __name__ == "__main__":
    sys.exit(main())
