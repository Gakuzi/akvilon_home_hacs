#!/usr/bin/env bash
# Запуск юнит-тестов интеграции Akvilon InHome в WSL-venv.
set -euo pipefail
BASE="$(cd "$(dirname "$0")/.." && pwd)"
VENV=/tmp/akv_test_venv
[ -x "$VENV/bin/python" ] || { echo "Venv нет: сначала ./scripts/setup_test_env.sh"; exit 1; }
cd "$BASE"
"$VENV/bin/python" -m pytest tests -q --cov-config=tests/.coveragerc "$@"