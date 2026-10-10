"""Парсер и каноническая таблица цен тарифов (Энергия Home Assistant).

Чистый модуль БЕЗ импорта ``homeassistant``: тестируется голым Python и
попадает под покрытие ``tests/.coveragerc``.

Назначение — единый источник цен тарифов для блока «Энергия» вместо
захардкоженных констант в ``energy.py``/``config_flow.py``. Модуль задаёт:

* ``DEFAULT_TARIFF_REGION`` — регион по умолчанию (Архангельск);
* ``DEFAULT_TARIFFS`` — каноническая таблица цен региона по умолчанию;
* ``parse_tariffs`` — нормализация/валидация произвольного пользовательского
  ввода в ``float >= 0.0`` (с подстановкой дефолтов вместо мусора);
* ``region_tariffs`` — точка выбора тарифного региона (пока Архангельск +
  fallback для unknown);
* ``TARIFF_FIELDS`` — порядок и дефолты полей для построения схемы config_flow.

Поля пишутся в ``entry.data`` интеграции и читаются энергосистемой:
``electricity_tariff_day``, ``electricity_tariff_night``,
``cold_water_tariff``, ``hot_water_tariff``.
"""
from __future__ import annotations

# Регион по умолчанию, для которого собрана таблица DEFAULT_TARIFFS.
DEFAULT_TARIFF_REGION = "Архангельск"

# Каноническая таблица цен тарифов (регион по умолчанию — Архангельск).
# УДЕРЖИВАЕТ существующие значения (8.67 / 3.91 / 0.0 / 0.0) — не меняет их.
DEFAULT_TARIFFS: dict[str, float] = {
    "electricity_tariff_day": 8.67,
    "electricity_tariff_night": 3.91,
    "cold_water_tariff": 0.0,
    "hot_water_tariff": 0.0,
}

# Упорядоченная структура полей тарифов: (ключ, значение-по-умолчанию).
# Служит единым источником имён полей и дефолтов для построения схемы
# config_flow (шаг «tariffs»).
TARIFF_FIELDS: tuple[tuple[str, float], ...] = tuple(
    (key, DEFAULT_TARIFFS[key]) for key in DEFAULT_TARIFFS
)


def _normalize_price(value: object, default: float) -> float:
    """Приводит произвольное значение к ``float >= 0.0``.

    Строки вида ``"8.67"`` парсятся в float. ``0``/``0.0``/``""``/``None``
    трактуются как «нет цены» (возвращается ``0.0``, воды без цены —
    допустимо). Отрицательные числа и не-числа (мусор) заменяются значением
    по умолчанию, чтобы не сломать энергосистему.
    """
    if value is None or value == "":
        return 0.0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number < 0:
        return default
    return number


def parse_tariffs(raw: dict | None) -> dict:
    """Нормализует пользовательский ввод тарифов в канонический словарь.

    Принимает произвольный словарь (или ``None``): отсутствующие, битые или
    отрицательные ключи заменяются значениями по умолчанию из
    ``DEFAULT_TARIFFS``. Возвращает словарь ровно с теми ключами, что
    описывает ``TARIFF_FIELDS``, все значения — ``float >= 0.0``.

    Возвращённый контракт совпадает с полями, которые пишутся в
    ``entry.data`` интеграции, поэтому обратная совместимость полей
    сохраняется и ре-мастер/миграция не требуется.
    """
    data = DEFAULT_TARIFFS.copy()
    if not raw:
        return data
    for key, default in TARIFF_FIELDS:
        if key in raw:
            data[key] = _normalize_price(raw[key], default)
    return data


def region_tariffs(region: str | None) -> dict:
    """Возвращает таблицу цен тарифов для региона.

    Пока существует только Архангельск; для ``None``/пустого/неизвестного
    региона возвращается fallback на регион по умолчанию (не исключение в
    рабочем пути). Функция — точка расширения для будущих регионов.
    """
    if region and region.strip().lower() == DEFAULT_TARIFF_REGION.lower():
        return dict(DEFAULT_TARIFFS)
    return dict(DEFAULT_TARIFFS)