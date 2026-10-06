#!/usr/bin/env bash
# ============================================================
# Сборка релиза для HACS-репозитория.
#
# Использование (на Raspberry Pi):
#   DEV_SRC=<path> ./scripts/release.sh <версия> [--beta]
#
# Примеры:
#   ./scripts/release.sh 1.1.0          # стабильный релиз -> тег v1.1.0
#   DEV_SRC=/home/pi/akvilon_home_dev ./scripts/release.sh 1.2.0 --beta
#
# Логика:
#   - исходники берутся из DEV_SRC (по умолчанию /home/pi/akvilon_home_dev)
#   - копируются в HACS-структуру (custom_components/akvilon_home/)
#   - обновляется версия в manifest.json
#   - коммит + git-тег, пуш в origin (main или develop)
#   - GitHub Actions по тегу создаёт github-release (HACS увидит обновление)
# ============================================================
set -euo pipefail

VERSION="${1:-}"
BETA="${2:-}"

if [ -z "$VERSION" ]; then
  echo "Ошибка: укажите версию, например ./scripts/release.sh 1.1.0"
  exit 1
fi

DEV_SRC="${DEV_SRC:-/home/pi/akvilon_home_dev}"
HACS_ROOT="/home/pi/akvilon_home_hacs"
DEST="$HACS_ROOT/custom_components/akvilon_home"

if [ ! -d "$DEST" ]; then
  echo "Ошибка: не найдена HACS-структура $DEST"
  exit 1
fi

# 1) Определяем целевую ветку и тег
if [ "$BETA" = "--beta" ]; then
  BRANCH="develop"
  BASE_TAG="v${VERSION}-beta"
  EXISTS=1; N=0
  while [ "$EXISTS" -eq 1 ]; do
    N=$((N+1))
    if git ls-remote --tags origin "${BASE_TAG}${N}" 2>/dev/null | grep -q "refs/tags/${BASE_TAG}${N}"; then
      EXISTS=1
    else
      EXISTS=0
    fi
  done
  TAG="${BASE_TAG}${N}"
else
  BRANCH="main"
  TAG="v${VERSION}"
fi
echo ">> Целевая ветка: $BRANCH, тег: $TAG"

cd "$HACS_ROOT"
git fetch --all --prune 2>/dev/null || true

# 2) Копируем исходники из dev-репозитория (если он существует)
if [ -d "$DEV_SRC" ]; then
  echo ">> Копирую исходники из $DEV_SRC в HACS-структуру..."
  cp -f "$DEV_SRC"/*.py "$DEST/" 2>/dev/null || true
  cp -f "$DEV_SRC"/*.json "$DEST/" 2>/dev/null || true
  cp -f "$DEV_SRC"/*.yaml "$DEST/" 2>/dev/null || true
  cp -f "$DEV_SRC"/AGENTS.md "$DEST/" 2>/dev/null || true
else
  echo ">> DEV_SRC не найдена; использую текущий код HACS-репозитория."
fi

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
git commit -m "release: ${TAG}" || echo ">> нечего коммитить"
git tag -f "$TAG"
git push origin "$BRANCH" --tags

echo
echo ">> Готово. Релиз $TAG на ветке $BRANCH опубликован."
echo ">> GitHub Actions создаст github-release автоматически."
echo ">> В HACS появится уведомление об обновлении."