# MANIFEST_SUBAGENTS.md — Манифест субагентов для параллельной разработки

> Создан: 2026-10-10. Источник плана: `docs/MULTIAGENT_PLAN.md`.
> Модель: **ветка на задачу, агенты автономны, наработки передаются основному
> агенту**. Не блокируют друг друга; сведение веток в `main` делает основной агент
> после зелёных гейтов. Релиз — только с одобрения владельца.

## Назначение агентов: фича → ветка → роль

| Ветка | Задача | спека | Роль-исполнитель | Гейты |
|-------|--------|-------|------------------|-------|
| `feature/video-go2rtc` | Живой видеопоток (go2rtc) | `SPEC-002-video-go2rtc.md` | developer (видео) | qa → doc |
| `feature/core-stability` | Стабильность UDP-ядра | `SPEC-003-core-stability.md` | developer (ядро) | qa → doc |
| `feature/dashboard-views` | Автопанель видами InHome | `SPEC-004-dashboard-views.md` | developer (фронт) | qa → doc |
| `feature/entities-device-energy` | Энергетика + устройства | `SPEC-001-energy-devices.md` | **уже зафиксирована (0216ee6)** — приёмка/доводка | qa → doc |
| `feature/release-pipeline` | Релиз-пайплайн и чистка | `SPEC-005-release-pipeline.md` | release-orchestrator + владелец | doc → qa |

## Зоны файлов (не пересекаются → параллельна безопасна)

- **video-go2rtc:** `rtp_stream.py`, `camera.py`, `viewer.py`, `manifest.json`, `docs/ADR/ADR-002`.
- **core-stability:** `protocol.py`, `coordinator.py`.
- **dashboard-views:** `dashboard.py`, `strings.json` (+ `__init__.py` — только своя вставка).
- **energy-devices:** `energy.py`, `sensor.py`, `config_flow.py`, `const.py` (+ `__init__.py`).
- **release-pipeline:** `.github/workflows`, `scripts/*`, `RELEASE_POLICY.md`, `CHANGELOG.md`, `version`.

> Пересечения есть только в `__init__.py` и `manifest.json`/`version`. Их трогают
> фичи 1–4 (своя вставка кода) и фича 5 (версия). Правило: **release-pipeline
> берётся последним** и решает конфликты версии. Если две фичи правили одну строку
> `__init__.py` — конфликт разрешает основной агент при сведении.

## Каждый субагент при старте обязан (из AGENTS.md §9)

1. Прочитать `AGENTS.md` (корень + `custom_components/akvilon_home/AGENTS.md`) и `README.md`.
2. `git fetch --all --prune`; проверить, что ветки ещё нет (`git branch -a | grep feature/`).
3. Создать свою `feature/*` **от `main`** (НЕ от `develop` — он отстал).
4. Писать маленькие коммиты по Conventional Commits. НЕ коммить в `main`/`develop`.
5. Документация — ДО коммита. Проверить `python3 -m py_compile *.py`.
6. В финальном отчёте: ветка, изменённые файлы, что сделано/проверено, что НЕ сделано,
   готовность к слиянию (да/нет, почему).

## Гейты перед сведением (не пропускаем)

1. `qa-gatekeeper` — тесты зелёные, покрытие >= 60%, секреты чисты.
2. `documentation-gate` — доки вместе с кодом (CHANGELOG/README/ADR/docstring).
3. `doc-gatekeeper` — документация согласована, версия и описания актуальны.
4. Релиз (`release-orchestrator`) — только с одобрения владельца, `sanitize.sh` + `release.sh`.

Пробел в гейте — ветка возвращается, а не «вливается с оговорками».
Исключение — только явный waiver `Doc-Exempt: <причина>`.

## Команды-памятка (Windows-машина, WSL)

```bash
# тесты
wsl bash -lc "cd '/mnt/c/Users/eklim/OneDrive/Документы/MultiTool/akvilon_home_hacs' && /tmp/akv_test_venv/bin/python -m pytest tests -q --cov=akvilon_home --cov-config=tests/.coveragerc --cov-report=term"
# компиляция
wsl bash -lc "cd '/mnt/c/Users/eklim/OneDrive/Документы/MultiTool/akvilon_home_hacs' && python3 -m compileall -q custom_components/akvilon_home"
```

## Скелет SPEC (по planner.md) — единый для всех `SPEC-*.md`

- **Цель**: что делает фича (приёмка «готово»).
- **Объём**: что входит / что вне scope.
- **Точки интеграции**: файлы и стыки с существующим кодом.
- **API/Контракт**: для видео — каналы/пакеты; для энергетики — схема `energy_sources`; и т.д.
- **Edge Cases**: ошибки, таймауты, невалидные данные, ретраи, отсутствие устройств.
- **Зависимости**: требуется ли go2rtc/ffmpeg/др.; тесты.
- **Критерии готовности**: чек-лист для qa-gate + doc-gate.