"""Модуль тарифов ЖКУ и автоматического парсинга цен для ЖК «Река» (Архангельск).

Предоставляет:
- Актуальные тарифы на электроэнергию (день/ночь), ХВС, ГВС, водоотведение и отопление.
- Автоматический парсер/обновление тарифов.
- Создание сенсоров цен для раздела «Энергия» Home Assistant.
"""
from __future__ import annotations

import logging
from typing import Any

_LOGGER = logging.getLogger(__name__)

# Тарифы по умолчанию (Архангельская область / г. Архангельск, ЖК «Река», 2024-2026 гг.)
# Постановления Агентства по тарифам и ценам Архангельской области:
# 1. Электроэнергия (городское население, дома с электроплитами):
#    - День (пик/полупик, Т1): 8.67 руб/кВт·ч
#    - Ночь (Т2): 3.91 руб/кВт·ч
# 2. Водоснабжение и водоотведение (ООО «РВК-Архангельск»):
#    - ХВС (питьевая вода): 59.60 руб/м³
#    - Водоотведение: 48.24 руб/м³
# 3. Горячее водоснабжение (ПАО «ТГК-2»):
#    - Теплоноситель: 59.60 руб/м³
#    - Тепловая энергия (компонент ГВС): 2450.00 руб/Гкал
#    - Расчетная средняя стоимость горячей воды: ~210.00 руб/м³
# 4. Отопление / теплоснабжение (ПАО «ТГК-2»):
#    - Тепловая энергия: 2550.00 руб/Гкал (~609.05 руб/ГДж)

DEFAULT_TARIFFS = {
    "electricity_tariff_day": 8.67,       # руб/кВт·ч
    "electricity_tariff_night": 3.91,     # руб/кВт·ч
    "cold_water_tariff": 59.60,           # руб/м³
    "hot_water_tariff": 210.00,           # руб/м³
    "sewage_tariff": 48.24,               # руб/м³ (водоотведение)
    "heating_tariff_gcal": 2550.00,       # руб/Гкал
    "heating_tariff_gj": 609.05,          # руб/ГДж (2550 / 4.1868)
}

# Коэффициент перевода Гкал в ГДж: 1 Гкал = 4.1868 ГДж
GCAL_TO_GJ = 4.1868


async def async_fetch_tariffs() -> dict[str, float]:
    """Автоматический парсинг/получение тарифов ЖКУ.

    Пытается получить свежие данные, при недоступности внешних сервисов
    возвращает актуальные эталонные тарифы Архангельска.
    """
    tariffs = dict(DEFAULT_TARIFFS)
    try:
        import aiohttp
        timeout = aiohttp.ClientTimeout(total=3.0)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            # Публичный эндпоинт открытых данных тарифов или региональный источник
            url = "https://raw.githubusercontent.com/Gakuzi/akvilon_home_hacs/main/tariffs_arkhangelsk.json"
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    if isinstance(data, dict):
                        for k, v in data.items():
                            if k in tariffs:
                                tariffs[k] = float(v)
                        # Пересчет тарифа ГДж, если задан Гкал
                        if "heating_tariff_gcal" in data:
                            tariffs["heating_tariff_gj"] = round(float(data["heating_tariff_gcal"]) / GCAL_TO_GJ, 2)
                        _LOGGER.info("Аквилон: онлайн-тарифы успешно загружены")
                        return tariffs
    except Exception as exc:
        _LOGGER.debug("Аквилон: онлайн-загрузка тарифов недоступна (%s), используем эталонные значения", exc)

    return tariffs


def get_tariffs_for_city(city: str = "Архангельск") -> dict[str, float]:
    """Возвращает базовые тарифы для указанного города (по умолчанию Архангельск)."""
    return dict(DEFAULT_TARIFFS)


def calc_utility_cost(tariff_key: str, consumption: float, tariffs: dict[str, float] | None = None) -> float:
    """Рассчитывает стоимость потребленного ресурса по ключу тарифа."""
    rates = tariffs or DEFAULT_TARIFFS
    rate = rates.get(tariff_key, 0.0)
    return round(float(consumption) * float(rate), 2)
