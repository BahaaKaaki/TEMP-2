#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

docker build -t agent-studio-sandbox:latest .
echo "Built agent-studio-sandbox:latest"
