#!/usr/bin/env bash
# Запуск юнит-тестов с покрытием (pytest-cov). Требует: pip install pytest pytest-cov.
set -euo pipefail
BASE="$(cd "$(dirname "$0")/.." && pwd)"
VENV=/tmp/akv_test_venv
[ -x "$VENV/bin/python" ] || { echo "Нет venv: ./scripts/setup_test_env.sh"; exit 1; }
cd "$BASE"
"$VENV/bin/python" -m pytest tests -q \
  --cov=akvilon_home \
  --cov-config=tests/.coveragerc \
  --cov-report=term-missing \
  --cov-report=html:coverage_html \
  "$@"