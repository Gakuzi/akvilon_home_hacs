"""Автоматическая настройка раздела «Энергия» в Home Assistant для интеграции Аквилон.

Автоматически связывает:
- Счётчики электроэнергии (День/Ночь) с сенсорами тарифов электроэнергии.
- Счётчики холодной и горячей воды с тарифами на воду.
- Счётчик отопления (ГДж) с тарифом на отопление.
"""
from __future__ import annotations

import logging
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import entity_registry as er
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_configure_energy_dashboard(hass: HomeAssistant, entry: ConfigEntry, hub) -> bool:
    """Создаёт или дополняет конфигурацию панели «Энергия» через менеджер энергии HA."""
    if not entry.data.get("add_to_energy", True):
        return False

    try:
        from homeassistant.components.energy import async_get_manager
        manager = await async_get_manager(hass)
    except Exception as err:
        _LOGGER.warning("Аквилон: не удалось получить менеджер энергии HA: %s", err)
        return False

    ent_reg = er.async_get(hass)

    def _resolve(unique_id: str) -> str | None:
        return ent_reg.async_get_entity_id("sensor", DOMAIN, unique_id)

    sources = list(manager.data.get("energy_sources", [])) if manager.data else []

    # Удаляем устаревшие записи со сломанными id вида sensor.akvilon_home_meter_*
    valid_sources = []
    for s in sources:
        stat_from = s.get("stat_energy_from", "")
        if stat_from.startswith("sensor.akvilon_home_meter_"):
            continue
        valid_sources.append(s)
    sources = valid_sources

    # 1. Электроэнергия: T1 (День) и T2 (Ночь)
    for m in hub.meters:
        dn = str(m.get("deviceNumber") or m.get("device_number") or "")
        rtype = str(m.get("resourceType") or "")
        if rtype == "1":
            for idx, tname in enumerate(["day", "night"]):
                uniq = f"{DOMAIN}_meter_{dn}_tariff{idx}"
                price_uniq = f"{DOMAIN}_tariff_electricity_tariff_{tname}"
                stat_id = _resolve(uniq)
                price_entity = _resolve(price_uniq)
                if not stat_id:
                    continue

                existing = next(
                    (s for s in sources if s.get("type") == "grid" and s.get("stat_energy_from") == stat_id),
                    None
                )
                if not existing:
                    sources.append({
                        "type": "grid",
                        "cost_adjustment_day": 0.0,
                        "stat_energy_from": stat_id,
                        "stat_cost": None,
                        "entity_energy_price": price_entity,
                        "number_energy_price": None,
                        "stat_energy_to": None,
                        "stat_compensation": None,
                        "entity_energy_price_export": None,
                        "number_energy_price_export": None,
                    })
                else:
                    if price_entity:
                        existing["entity_energy_price"] = price_entity

    # 2. Водоснабжение (ХВС / ГВС)
    for m in hub.meters:
        dn = str(m.get("deviceNumber") or m.get("device_number") or "")
        rtype = str(m.get("resourceType") or "")
        name = str(m.get("name") or "").lower()
        if rtype in ("2", "3") or "хвс" in name or "гвс" in name:
            uniq = f"{DOMAIN}_meter_{dn}"
            stat_id = _resolve(uniq)
            if not stat_id:
                continue
            is_hot = "гвс" in name or rtype == "3"
            price_uniq = f"{DOMAIN}_tariff_hot_water_tariff" if is_hot else f"{DOMAIN}_tariff_cold_water_tariff"
            price_entity = _resolve(price_uniq)

            existing_water = next((s for s in sources if s.get("type") == "water" and s.get("stat_energy_from") == stat_id), None)
            if not existing_water:
                sources.append({
                    "type": "water",
                    "stat_energy_from": stat_id,
                    "stat_cost": None,
                    "entity_energy_price": price_entity,
                    "number_energy_price": None
                })
            else:
                if price_entity:
                    existing_water["entity_energy_price"] = price_entity

    # 3. Газ / Отопление (в HA Energy раздел «Газ» поддерживает сенсоры energy в GJ)
    for m in hub.meters:
        dn = str(m.get("deviceNumber") or m.get("device_number") or "")
        rtype = str(m.get("resourceType") or "")
        name = str(m.get("name") or "").lower()
        if rtype == "4" or "отопление" in name:
            uniq = f"{DOMAIN}_meter_{dn}"
            stat_id = _resolve(uniq)
            if not stat_id:
                continue
            price_uniq = f"{DOMAIN}_tariff_heating_tariff_gj"
            price_entity = _resolve(price_uniq)

            existing_gas = next((s for s in sources if s.get("type") == "gas" and s.get("stat_energy_from") == stat_id), None)
            if not existing_gas:
                sources.append({
                    "type": "gas",
                    "stat_energy_from": stat_id,
                    "stat_cost": None,
                    "entity_energy_price": price_entity,
                    "number_energy_price": None
                })
            else:
                if price_entity:
                    existing_gas["entity_energy_price"] = price_entity

    try:
        await manager.async_update({"energy_sources": sources})
        _LOGGER.info("Аквилон: раздел «Энергия» успешно настроен (%d источников)", len(sources))
        return True
    except Exception as exc:
        _LOGGER.warning("Аквилон: не удалось обновить данные менеджера энергии: %s", exc)
        return False
