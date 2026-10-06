#!/usr/bin/env bash
# ============================================================
# Установка/обновление интеграции Akvilon InHome прямо из релиза GitHub
# (резервный путь без HACS; работает по SSH на Raspberry Pi).
#
# Использование:
#   ./install_from_github.sh [версия|ветка]
# Примеры:
#   ./install_from_github.sh              # последний стабильный (main)
#   ./install_from_github.sh latest       # то же, main
#   ./install_from_github.sh beta         # develop (бета)
#   ./install_from_github.sh v1.1.0       # тег стабильной версии
#   ./install_from_github.sh v1.2.0-beta1 # тег бета-версии
# ============================================================
set -euo pipefail

REPO="Gakuzi/akvilon_home_hacs"
ARG="${1:-latest}"
DEST="/home/pi/homeassistant/custom_components/akvilon_home"

# Определяем источник (ветка или тег)
case "$ARG" in
  beta|develop)
    REF="heads/develop"; LABEL="develop (beta)";;
  main|latest|"")
    REF="heads/main"; LABEL="main (stable)";;
  v*)
    REF="tags/$ARG"; LABEL="tag $ARG";;
  *)
    echo "Неизвестный аргумент: $ARG (допустимо: latest, beta, v1.1.0, v1.2.0-beta1)"
    exit 1;;
esac

echo ">> Установка Akvilon InHome из $REPO [$LABEL]"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

URL="https://github.com/$REPO/archive/refs/$REF.tar.gz"
echo ">> Скачиваю $URL"
AUTH=()
if [ -n "${GH_TOKEN:-}" ]; then
  AUTH=(-H "Authorization: Bearer $GH_TOKEN")
fi
curl -fsSL "${AUTH[@]}" "$URL" -o "$TMP/repo.tar.gz" || { echo "Ошибка скачивания (проверь доступ/токен)"; exit 1; }
mkdir -p "$TMP/extracted"
tar -xzf "$TMP/repo.tar.gz" -C "$TMP/extracted"

SRC="$(find "$TMP/extracted" -type d -path "*custom_components/akvilon_home" | head -1)"
if [ -z "$SRC" ]; then
  echo "Ошибка: в архиве нет custom_components/akvilon_home"; exit 1
fi

if [ -d "$DEST" ]; then
  mkdir -p /home/pi/akvilon_backups
  cp -r "$DEST" "/home/pi/akvilon_backups/akvilon_home.bak_$(date +%s)"
  echo ">> Создан бэкап текущей версии"
  # снимаем root-права, чтобы можно было перезаписать
  chown -R pi:pi "$DEST" 2>/dev/null || true
fi

rm -rf "$DEST" 2>/dev/null || true
mkdir -p "$(dirname "$DEST")"
cp -r "$SRC" "$DEST"
echo ">> Файлы установлены в $DEST"

chown -R pi:pi "$DEST" 2>/dev/null || true
echo ">> Перезапуск Home Assistant..."
docker restart homeassistant

echo ">> Готово. Проверь журнал: docker logs homeassistant --since 2m | grep -i akvilon"