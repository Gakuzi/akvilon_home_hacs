#!/usr/bin/env bash
# ============================================================
# sanitize.sh — очистка ПЕРСОНАЛЬНЫХ ДАННЫХ из кода интеграции
# перед копированием в ПУБЛИЧНЫЙ HACS-репозиторий.
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

HOST="${AKVILON_HOST:-127.0.0.1}"
DEVICE_ID="${AKVILON_DEVICE_ID:-0:0}"
SERVER_ID="${AKVILON_SERVER_ID:-0:0}"
PASS="${AKVILON_PASS:-PASS_PLACEHOLDER}"
SUID="${AKVILON_SUID:-SIGN_KEY_PLACEHOLDER}"
TOKEN="${AKVILON_TOKEN:-token_placeholder}"

P_HOST="127.0.0.1"
P_DEVICE="0:0"
P_SERVER="0:0"
P_PASS="PASS_PLACEHOLDER"
P_SUID="SUID_PLACEHOLDER"
P_TOKEN="token_placeholder"

echo ">> Очистка: $SRC -> $DST"
mkdir -p "$DST"

# Копируем ТОЛЬКО исходники, не трогаем .git внутри dst (не rm -rf DST)
cp -f "$SRC"/__init__.py "$DST"/ 2>/dev/null || true
for ext in py json yaml; do
  cp -f "$SRC"/*.$ext "$DST"/ 2>/dev/null || true
done

# Замены по текстовым файлам
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

rm -f "$DST/secrets.local"
rm -rf "$DST/__pycache__"
find "$DST" -name "*.pyc" -delete 2>/dev/null || true

echo ">> Проверка остатков личных данных:"
grep -rn "$HOST\|$PASS\|$SUID\|$TOKEN\|$DEVICE_ID\|$SERVER_ID" "$DST" 2>/dev/null || echo "  чисто"
echo ">> Очистка завершена."
# Рекурсивно удаляем пустые директории (артефакты вроде вложенной akvilon_home)
find "$DST" -type d -empty -delete 2>/dev/null || true