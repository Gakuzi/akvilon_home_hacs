#!/usr/bin/env bash
# ============================================================
# sanitize.sh — очистка ПЕРСОНАЛЬНЫХ ДАННЫХ из кода интеграции
# перед копированием в ПУБЛИЧНЫЙ HACS-репозиторий.
#
# ПРИВАТНЫЙ каталог (разработка)  -> /home/pi/homeassistant/custom_components/akvilon_home
# ПУБЛИЧНЫЙ каталог (публикация)  -> /home/pi/akvilon_home_hacs/custom_components/akvilon_home
#
# Использование:
#   ./sanitize.sh <src_dir> <dst_dir>
# Пример:
#   ./sanitize.sh /home/pi/homeassistant/custom_components/akvilon_home \
#                 /home/pi/akvilon_home_hacs/custom_components/akvilon_home
#
# ВАЖНО: этот скрипт не должен содержать реальные секреты; они передаются
# через файл secrets.local (см. ниже) или переменные окружения.
# ============================================================
set -euo pipefail

SRC="${1:-}"
DST="${2:-}"
if [ -z "$SRC" ] || [ -z "$DST" ]; then
  echo "Ошибка: требуется <src_dir> <dst_dir>"; exit 1
fi

# --- Секреты: читаем из локального файла (не коммитится в git) ---
SECRETS_FILE="$(dirname "$0")/secrets.local"
if [ -f "$SECRETS_FILE" ]; then
  # shellcheck disable=SC1090
  source "$SECRETS_FILE"
fi

# Значения по умолчанию (если не заданы в secrets.local)
HOST="${AKVILON_HOST:-91.122.221.217}"
DEVICE_ID="${AKVILON_DEVICE_ID:-34:50957}"
SERVER_ID="${AKVILON_SERVER_ID:-7:48390}"
PASS="${AKVILON_PASS:-9c5edcb9}"
SUID="${AKVILON_SUID:-fec8df007bfd4e368d92a67a152840df}"
TOKEN="${AKVILON_TOKEN:-token_34:50957}"

# Плейсхолдеры (безопасные, публичные)
P_HOST="127.0.0.1"
P_DEVICE="0:0"
P_SERVER="0:0"
P_PASS="PASS_PLACEHOLDER"
P_SUID="SUID_PLACEHOLDER"
P_TOKEN="token_placeholder"

echo ">> Очистка: $SRC -> $DST"
mkdir -p "$DST"
rm -rf "$DST"/*
cp -r "$SRC"/. "$DST/"

# Замены по всем текстовым файлам
find "$DST" -type f \( -name "*.py" -o -name "*.json" -o -name "*.yaml" -o -name "*.md" -o -name "*.txt" \) | while read -r f; do
  sed -i \
    -e "s/${HOST}/${P_HOST}/g" \
    -e "s/${TOKEN}/${P_TOKEN}/g" \
    -e "s/${PASS}/${P_PASS}/g" \
    -e "s/${SUID}/${P_SUID}/g" \
    -e "s/${DEVICE_ID}/${P_DEVICE}/g" \
    -e "s/${SERVER_ID}/${P_SERVER}/g" \
    "$f" 2>/dev/null || true
done

# Удаляем внутренние служебные файлы, не нужные для публикации
rm -f "$DST/secrets.local"
rm -rf "$DST/__pycache__"
find "$DST" -name "*.pyc" -delete

# Ищем остатки реальных данных (диагностика)
echo ">> Проверка остатков личных данных:"
grep -rn "$HOST\|$PASS\|$SUID\|$TOKEN\|$DEVICE_ID\|$SERVER_ID" "$DST" 2>/dev/null || echo "  чистo"

echo ">> Очистка завершена. Готово к публикации."