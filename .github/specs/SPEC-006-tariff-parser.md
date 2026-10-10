# SPEC-006 — Парсер цен тарифов (feature/tariff-parser)

- **Статус:** план (к исполнению).
- **Роль-исполнитель:** developer.
- **Гейты:** qa-gatekeeper → documentation-gate → doc-gatekeeper.
- **Дата:** 2026-10-10.
- **База ветки:** `feature/entities-device-energy` (HEAD `dab1f5d`) — здесь уже живёт
  tariff-код (`energy.py`, шаг tariffs в `config_flow.py`), который рефакторим.
- **Зона файлов:** `tariffs.py` (новый), `energy.py`, `config_flow.py`,
  `tests/test_tariffs.py` (новый). **НЕ трогать** чужие ветки/модули
  (`protocol.py`, `coordinator.py`, `camera.py`, `sensor.py`, `dashboard.py` и т.д.).

## Цель
Вынести **цены тарифов** (электроэнергия день/ночь, холодная/горячая вода,
отопление) из захардкоженных констант `energy.py`/`config_flow.py` в отдельный
чистый Python-модуль `tariffs.py` с встроенной таблицей по умолчанию (регион —
Архангельск), функцией парсинга/валидации пользовательского ввода и нормализованным
контрактом для блока «Энергия».

«Парсер» в значении: разбирает и валидирует произвольный ввод тарифов (словарь,
строки, числа, `0.0`/пусто) и приводит к канонической структуре с
значениями по умолчанию — чтобы UI (`config_flow`) и подсистема Энергии
(`energy.py`) работали с единым источником цен, а не с магическими числами.

## Объём
- **`tariffs.py`** (новый):
  - `DEFAULT_TARIFFS` / `DEFAULT_TARIFF_REGION` — каноническая таблица региона
    по умолчанию (Архангельск): `electricity_tariff_day=8.67`,
    `electricity_tariff_night=3.91`, `cold_water_tariff=0.0`,
    `hot_water_tariff=0.0`. (УДЕРЖИВАЕТ существующие значения — не меняет их.)
  - `parse_tariffs(raw: dict | None) -> dict` — принимает произвольный словарь
    пользователя, приводит к ключам `electricity_tariff_day`,
    `electricity_tariff_night`, `cold_water_tariff`, `hot_water_tariff`,
    нормализует в `float >= 0.0`, отсутствующие/битые ключи → default.
  - `region_tariffs(region: str | None) -> dict` — точка выбора тарифного
    региона; пока только «Архангельск» + unknown → fallback на Архангельск.
  - `TARIFF_FIELDS` — структура ключей для построения схемы config_flow
    (единый источник имени/дефолта поля).
- **`energy.py`** — заменить локальные `DEFAULT_EL_DAY`/`DEFAULT_EL_NIGHT`/
  `DEFAULT_WATER_COLD`/`DEFAULT_WATER_HOT` на импорт из `tariffs.py`; читать цены
  из `entry.data` через `parse_tariffs(entry.data)` (обратная совместимость: поля
  уже есть в entry, миграция не нужна).
- **`config_flow.py`** — шаг `tariffs`: брать defaults и имена полей из
  `tariffs.py` (`TARIFF_FIELDS`), сохранять результат через `parse_tariffs`.
  Текущая схема и тексты не меняются жёстко — только источники значений.
- **`tests/test_tariffs.py`** (новый) — unit-тесты на чистую функцию парсера:
  валидный ввод, пропущенные ключи → defaults, строки → float, `0.0`/пусто,
  отрицательные числа → default, `region_tariffs` для известного/неизвестного.
- **Вне scope:** показания по тарифам счётчика (`sensor.py` T1/T2 — НЕ трогать),
  живое видео, камеры, калитки, протокол, дашборд, релиз-пайплайн.

## Точки интеграции / Контракт
- Модуль `tariffs.py` — чистый, без импорта `homeassistant` (тестируется голым
  Python, попадает под покрытие `tests/.coveragerc`).
- Контракт возврата `parse_tariffs` — словарь ключей, которые уже пишутся в
  `entry.data` (`electricity_tariff_day/night`, `cold_water_tariff`,
  `hot_water_tariff`). Обратная совместимость полей сохранена — ре-мастер/миграция
  НЕ требуется.
- Схема config_flow строится поверх `TARIFF_FIELDS` (ключи + default).

## Edge Cases
- Ввод = `None` / `{}` → все поля = defaults региона.
- Ключ приходит строкой `"8.67"` → нормализуется в `float`.
- Ключ приходит `0` / `0.0` / `""` / `None` → трактуется как «нет цены» (default 0.0),
  не падает (вода без цены — допустимо, см. SPEC-001).
- Отрицательная цена / не-число → подставляется default (защита от мусора).
- Неизвестный регион при `region_tariffs` → fallback на регион по умолчанию
  (не исключение в рабочем пути); функция остаётся обёрткой для будущего расширения.

## Зависимости / тесты
- Нет внешних зависимостей (голый Python). `parse_tariffs` без сети/HA.
- Тесты: новый `tests/test_tariffs.py` (>= 12 кейсов). Полный прогон `python3 -m
  pytest tests -q` — все зелёные (baseline 97 + новые). Покрытие >= 60%
  (`tests/.coveragerc`), `compileall` чисто.

## Критерии готовности (qa + doc)
- [ ] `python3 -m compileall custom_components/akvilon_home` чисто.
- [ ] `pytest tests -q` — 97 + новые зелёные; покрытие >= 60%.
- [ ] `energy.py`/`config_flow.py` не содержат захардкоженных цен тарифов,
      используют `tariffs.py`.
- [ ] `tariffs.py` имеет docstring; CHANGELOG/README дополнены записью про парсер.
- [ ] Секретов нет (плейсхолдеры); чужие ветки/модули не затронуты.