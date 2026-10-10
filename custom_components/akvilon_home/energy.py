"""Автоматическая интеграция счётчиков Аквилон в энергосистему Home Assistant.

При настройке интеграции (add_to_energy=True) добавляет счётчики квартиры в
«Энергия» (Энергопанель): электричество (с тарифами день/ночь по умолчанию),
горячую/холодную воду и отопление. Использует EnergyManager — программно
пишет energy_sources, чтобы пользователю не пришлось настраивать вручную.
"""
import logging

from homeassistant.core import HomeAssistant

from .tariffs import parse_tariffs

_LOGGER = logging.getLogger(__name__)


async def async_setup_energy(hass: HomeAssistant, entry) -> None:
    """Добавляет счётчики Аквилон в Энергосистему (energy_sources)."""
    data = entry.data or {}
    if not data.get("add_to_energy", True):
        _LOGGER.info("Аквилон: add_to_energy=False, пропускаю энергосистему")
        return

    # Единый источник цен тарифов (defaults региона — из tariffs.py).
    tariffs = parse_tariffs(data)
    price_day = tariffs["electricity_tariff_day"]
    price_night = tariffs["electricity_tariff_night"]
    price_cold = tariffs["cold_water_tariff"]
    price_hot = tariffs["hot_water_tariff"]

    # Находим entity_id наших сенсоров по префиксу (домен akvilon_home)
    elec_from = _find_entity(hass, "sensor", "schetchik_elektrichestvo")
    elec_to = _find_entity(hass, "sensor", "schetchik_elektrichestvo_noch")
    water_cold = _find_entity(hass, "sensor", "schetchik_khvs")
    water_hot = _find_entity(hass, "sensor", "schetchik_gvs")
    heat = _find_entity(hass, "sensor", "schetchik_otoplenie")

    try:
        from homeassistant.components.energy import async_get_manager
        manager = await async_get_manager(hass)
    except Exception as exc:  # pragma: no cover
        _LOGGER.warning("Аквилон: энергосистема недоступна: %s", exc)
        return

    # Читаем текущие источники (нужно сохранить чужие!).
    current = manager.data.get("energy_sources", []) if manager.data else []
    sources = list(current) if current else []

    # Электричество (день + ночь) — grid-source
    if elec_from:
        grid = _find_source(sources, "grid")
        flow_from = [
            {
                "stat_energy_from": elec_from,
                "stat_cost": None,
                "entity_energy_price": None,
                "number_energy_price": price_day,
            }
        ]
        if elec_to:
            flow_from.append({
                "stat_energy_from": elec_to,
                "stat_cost": None,
                "entity_energy_price": None,
                "number_energy_price": price_night,
            })
        if grid is None:
            sources.append({
                "type": "grid",
                "flow_from": flow_from,
                "flow_to": [],
                "cost_adjustment_day": 0.0,
            })
        # иначе — добавить канал в существующий grid (не перетираем чужие)
        else:
            existing = grid.get("flow_from", [])
            existing_keys = {f.get("stat_energy_from") for f in existing}
            for f in flow_from:
                if f["stat_energy_from"] not in existing_keys:
                    existing.append(f)
            grid["flow_from"] = existing

    # Холодная и горячая вода (добавляем всегда, цена опциональна)
    if water_cold:
        _upsert_source(sources, "water", water_cold, price_cold)
    if water_hot:
        _upsert_source(sources, "water", water_hot, price_hot)

    # Отопление (статистика Гкал)
    if heat:
        _upsert_source(sources, "water", heat, 0.0, name="Отопление")

    try:
        await manager.async_update({"energy_sources": sources})
        _LOGGER.info(
            "Аквилон: счётчики добавлены в Энергию (элек-во %s, вода %s/%s, тепло %s)",
            elec_from or "—", water_cold or "—", water_hot or "—", heat or "—",
        )
    except Exception as exc:  # pragma: no cover
        _LOGGER.warning("Аквилон: не удалось обновить энергосистему: %s", exc)


def _find_entity(hass: HomeAssistant, domain: str, substr: str) -> str | None:
    """Возвращает entity_id сенсора по подстроке, либо None."""
    try:
        for eid in hass.states.async_all():
            if eid.entity_id.startswith(f"{domain}.") and substr in eid.entity_id:
                return eid.entity_id
    except Exception:  # pragma: no cover
        pass
    return None


def _find_source(sources, stype: str):
    """Ищет source заданного типа, возвращает dict или None."""
    for s in sources:
        if isinstance(s, dict) and s.get("type") == stype:
            return s
    return None


def _upsert_source(sources, stype: str, stat_id: str, price: float, name: str | None = None):
    """Добавляет/обновляет source воды/газа со счётчиком.

    HA позволяет несколько источников одного типа (например, две линии воды).
    Поэтому для каждого РАЗНОГО счётчика создаём отдельный источник; если такой
    stat_id уже есть — просто обновляем цену/имя, без дублей.
    """
    for s in sources:
        if isinstance(s, dict) and s.get("type") == stype and s.get("stat_energy_from") == stat_id:
            if price > 0:
                s["number_energy_price"] = price
            if name:
                s["name"] = name
            return
    src: dict = {"type": stype, "stat_energy_from": stat_id}
    if price > 0:
        src["number_energy_price"] = price
    if name:
        src["name"] = name
    sources.append(src)