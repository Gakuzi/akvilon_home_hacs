#!/usr/bin/env bash
# ============================================================
# Сборка релиза для HACS-репозитория из рабочей ветки разработки.
#
# Использование (на Raspberry Pi):
#   ./scripts/release.sh <версия> [--beta]
#
# Примеры:
#   ./scripts/release.sh 1.1.0          # стабильный релиз -> тег v1.1.0
#   ./scripts/release.sh 1.2.0 --beta   # бета -> тег v1.2.0-beta1
#
# Логика:
#   - исходники берутся из /home/pi/homeassistant/custom_components/akvilon_home
#     (рабочий dev-репозиторий)
#   - копируются в HACS-структуру (custom_components/akvilon_home/)
#   - обновляется версия в manifest.json
#   - коммит + git-тег, пуш в origin (main или develop)
# ============================================================
set -euo pipefail

VERSION="${1:-}"
BETA="${2:-}"

if [ -z "$VERSION" ]; then
  echo "Ошибка: укажите версию, например ./scripts/release.sh 1.1.0"
  exit 1
fi

DEV_SRC="/home/pi/homeassistant/custom_components/akvilon_home"
HACS_ROOT="/home/pi/akvilon_home_hacs"
DEST="$HACS_ROOT/custom_components/akvilon_home"

if [ ! -d "$DEV_SRC" ] || [ ! -d "$DEST" ]; then
  echo "Ошибка: не найдены каталоги. Убедитесь, что пути существуют."
  exit 1
fi

# 1) Определяем целевую ветку
if [ "$BETA" = "--beta" ]; then
  BRANCH="develop"
  TAG="v${VERSION}-beta1"
else
  BRANCH="main"
  TAG="v${VERSION}"
fi
echo ">> Целевая ветка: $BRANCH, тег: $TAG"

cd "$HACS_ROOT"

# 2) Актуализируем HACS-структуру из dev-исходников
echo ">> Копирую исходники из $DEV_SRC в HACS-структуру..."
cp -f "$DEV_SRC"/*.py "$DEST/" 2>/dev/null || true
cp -f "$DEV_SRC"/*.json "$DEST/" 2>/dev/null || true
cp -f "$DEV_SRC"/*.yaml "$DEST/" 2>/dev/null || true
cp -f "$DEV_SRC"/AGENTS.md "$DEST/" 2>/dev/null || true

# 3) Обновляем версию в manifest.json
python3 - "$VERSION" "$DEST/manifest.json" <<'PY'
import json, sys
ver, path = sys.argv[1], sys.argv[2]
d = json.load(open(path))
d["version"] = ver
json.dump(d, open(path, "w"), ensure_ascii=False, indent=2)
print("  version ->", ver)
PY

# 4) Коммит и тег
git checkout "$BRANCH"
git add -A
git commit -m "release: v${TAG}" || echo ">> нечего коммитить"
git tag -f "$TAG"
git push origin "$BRANCH" --tags

echo ">> Готово. Релиз $TAG на ветке $BRANCH опубликован."