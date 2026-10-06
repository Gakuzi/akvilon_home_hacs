"""Сенсоры состояния калиток и приборов учёта Аквилон (из живых данных сервера)."""
import logging

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


def _meter_current(meter: dict):
    """Извлекает показание: 'current' может быть вложенным JSON-строкой."""
    cur = meter.get("current")
    if isinstance(cur, str):
        import json
        try:
            cur = json.loads(cur)
        except Exception:
            pass
    if isinstance(cur, dict):
        return cur
    return None


def _meter_value(meter: dict):
    cur = _meter_current(meter)
    if isinstance(cur, dict):
        return cur.get("value")
    return None


def _normalize_unit(unit: str):
    """Приводит единицы из сервера к каноническому виду HA."""
    if not unit:
        return None
    m = {
        "м3": "m³", "м³": "m³", "куб.м": "m³", "куб м": "m³", "M3": "m³",
        "квт*ч": "kWh", "квтч": "kWh", "квт·ч": "kWh", "кВт*ч": "kWh",
        "кВт·ч": "kWh", "КВт*ч": "kWh", "kwt": "kWh", "kWt": "kWh",
        "гкал": "Gcal", "Гкал": "Gcal", "ккал": "kcal", "Ккал": "kcal",
    }
    return m.get(unit, unit)


class AkvilonMeterSensor(SensorEntity):
    """Показание прибора учёта (счётчика) квартиры."""

    _attr_has_entity_name = False

    def __init__(self, meter: dict):
        self.meter = meter
        dn = meter.get("deviceNumber") or meter.get("device_number") or "",
        name = meter.get("name") or "Счётчик"
        self._attr_unique_id = f"{DOMAIN}_meter_{or_val(dn)}"
        self._label = name

    @property
    def name(self):
        return f"Счётчик {self._label}"

    @property
    def icon(self):
        return "mdi:counter"

    @property
    def native_value(self):
        return _meter_value(self.meter)

    @property
    def native_unit_of_measurement(self):
        cur = _meter_current(self.meter)
        if isinstance(cur, dict):
            unit = (cur.get("unit") or "").strip()
            return _normalize_unit(unit)
        return None

    @property
    def device_class(self):
        t = str(self.meter.get("resourceType", ""))
        if t in ("1",):  # electricity
            return "energy"
        if t in ("2", "3"):  # water
            return "water"
        return None

    @property
    def state_class(self):
        # Счётчики — накопительные показания (total_increasing), т.к. sensor.
        # Для energy/water HA требует total/total_increasing, не measurement.
        return "total_increasing"

    @property
    def extra_state_attributes(self):
        attrs = {"integration": "akvilon_home"}
        if "deviceNumber" in self.meter:
            attrs["device_number"] = self.meter["deviceNumber"]
        cur = _meter_current(self.meter)
        if isinstance(cur, dict):
            attrs["reading_date"] = cur.get("dt")
            if "values" in cur:
                attrs["tariffs"] = cur["values"]
        return attrs


class AkvilonGateSensor(SensorEntity):
    """Состояние калитки."""

    _attr_has_entity_name = False

    def __init__(self, hub, gate_id, name):
        self._hub = hub
        self.gate_id = str(gate_id)
        self._name = name
        self._attr_unique_id = f"{DOMAIN}_gatestate_{self.gate_id.replace(':', '_')}"

    @property
    def name(self):
        return f"Калитка {self._name} состояние"

    @property
    def icon(self):
        return "mdi:door"

    @property
    def native_value(self):
        for g in self._hub.gates:
            gid = str(g.get("objectid") or g.get("objectId") or "")
            if gid == self.gate_id:
                st = g.get("currentState", g.get("controllerStatus"))
                return "open" if st == 1 else ("closed" if st == 0 else "unknown")
        return "unknown"

    @property
    def extra_state_attributes(self):
        return {"integration": "akvilon_home", "gate_id": self.gate_id}


def or_val(val):
    if isinstance(val, tuple):
        val = val[0]
    return val or "unknown"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    """Создаёт сенсоры из живых списков сервера."""
    hub = hass.data[DOMAIN][entry.entry_id]
    sens = []
    for m in hub.meters:
        sens.append(AkvilonMeterSensor(m))
    for g in hub.gates:
        gid = str(g.get("objectid") or g.get("objectId") or "")
        if gid:
            sens.append(AkvilonGateSensor(hub, gid, g.get("name") or "Калитка"))
    async_add_entities(sens, True)
    _LOGGER.info("Аквилон: добавлено %d сенсоров из сервера", len(sens))