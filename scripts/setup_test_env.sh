#!/usr/bin/env bash
# Создание WSL-venv с pytest для запуска юнит-тестов интеграции Akvilon InHome.
# Вызывать из WSL (Ubuntu). Папка venv: /tmp/akv_test_venv (пересоздаётся).
set -euo pipefail

if ! command -v wsl.exe >/dev/null 2>&1 && [ "$(uname -s)" != "Linux" ]; then
  echo "Ошибка: тесты рассчитаны на запуск в WSL (Ubuntu) или Linux."
  exit 1
fi

PY="python3"
[ -x /usr/bin/python3 ] && PY=/usr/bin/python3

VENV=/tmp/akv_test_venv
echo ">> Создаю venv: $VENV"
rm -rf "$VENV"
"$PY" -m venv "$VENV"
"$VENV/bin/pip" install --quiet pytest
"$VENV/bin/python" -c "import pytest; print('pytest', pytest.__version__)"
echo ">> Готово. Запуск тестов: scripts/run_tests.sh"