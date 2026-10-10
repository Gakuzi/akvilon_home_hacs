"""Сенсоры состояния калиток и приборов учёта Аквилон (из живых данных сервера)."""
import logging

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    DOMAIN,
    meter_dev_id,
    gate_dev_id,
    intercom_dev_id,
)

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
    _attr_state_class = "total_increasing"

    def __init__(self, meter: dict):
        self.meter = meter
        dn = _or_val(meter.get("deviceNumber") or meter.get("device_number"))
        name = meter.get("name") or "Счётчик"
        self._attr_unique_id = f"{DOMAIN}_meter_{dn}"
        self._label = name
        self._device_number = dn
        # Привязка к устройству «Счётчик <название>»
        self._attr_device_info = {
            "identifiers": {meter_dev_id(dn)},
            "name": f"Счётчик {name}",
            "manufacturer": "Аквилон InHome",
            "model": "Прибор учёта квартиры",
        }

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
        # Счётчики — накопительные показания (total_increasing).
        return "total_increasing"

    @property
    def extra_state_attributes(self):
        attrs = {"integration": "akvilon_home"}
        attrs["device_number"] = self._device_number
        attrs["resource_type"] = self.meter.get("resourceType")
        attrs["meter_type"] = self.meter.get("meterType")
        attrs["object_id"] = self.meter.get("objectid") or self.meter.get("objectId") or ""
        cur = _meter_current(self.meter)
        if isinstance(cur, dict):
            attrs["reading_date"] = cur.get("dt")
            if "values" in cur:
                attrs["tariffs"] = cur["values"]
        return attrs


class AkvilonMeterTariffSensor(SensorEntity):
    """Отдельный сенсор тарифа двух-тарифного счётчика (День/Ночь).

    Электричество приходит одним счётчиком с current.values = [T1, T2, T3, T4],
    где value = сумма тарифов, а T1/T2 — тарифы «День»/«Ночь». Создаём по одному
    сенсору на тариф с привязкой к тому же device_number.
    """

    _attr_has_entity_name = False
    _attr_device_class = "energy"
    _attr_state_class = "total_increasing"

    def __init__(self, meter: dict, tariff_index: int, tariff_label: str):
        self.meter = meter
        self.tariff_index = tariff_index
        self._label = (meter.get("name") or "Счётчик") + f" ({tariff_label})"
        dn = _or_val(meter.get("deviceNumber") or meter.get("device_number"))
        self._device_number = dn
        self._attr_unique_id = f"{DOMAIN}_meter_{dn}_tariff{tariff_index}"
        self._tariff_number = tariff_index + 1
        # Тот же device, что и основной счётчик (для Энергии: Т1/Т2 на одном приборе)
        self._attr_device_info = {
            "identifiers": {meter_dev_id(dn)},
            "name": f"Счётчик {(meter.get('name') or 'Счётчик')}",
            "manufacturer": "Аквилон InHome",
            "model": "Прибор учёта квартиры",
        }

    @property
    def name(self):
        return f"Счётчик {self._label}"

    @property
    def icon(self):
        return "mdi:chart-bell-curve-cumulative"

    @property
    def native_value(self):
        cur = _meter_current(self.meter)
        if isinstance(cur, dict) and isinstance(cur.get("values"), list):
            vals = cur["values"]
            if self.tariff_index < len(vals):
                return vals[self.tariff_index]
        return None

    @property
    def native_unit_of_measurement(self):
        cur = _meter_current(self.meter)
        if isinstance(cur, dict):
            return _normalize_unit((cur.get("unit") or "").strip())
        return None

    @property
    def extra_state_attributes(self):
        return {
            "integration": "akvilon_home",
            "device_number": self._device_number,
            "object_id": self.meter.get("objectid") or self.meter.get("objectId") or "",
            "tariff": f"T{self._tariff_number}",
            "tariff_index": self.tariff_index,
        }


class AkvilonGateSensor(SensorEntity):
    """Состояние калитки (статус контроллера)."""

    _attr_has_entity_name = False

    def __init__(self, hub, gate_id, name):
        self._hub = hub
        self.gate_id = str(gate_id)
        self._name = name
        self._attr_unique_id = f"{DOMAIN}_gatestate_{self.gate_id.replace(':', '_')}"
        # Привязка к устройству «Калитка <имя>»
        self._attr_device_info = {
            "identifiers": {gate_dev_id(self.gate_id)},
            "name": f"Калитка {self._name}",
            "manufacturer": "Аквилон InHome",
            "model": "Калитка / вход",
        }

    @property
    def name(self):
        return f"Калитка {self._name} состояние"

    @property
    def icon(self):
        return "mdi:door"

    @property
    def native_value(self):
        g = self._hub.gate_by_id(self.gate_id)
        if g:
            # Сервер не присылает открыта/закрыта — только статус контроллера
            st = g.get("controllerStatus")
            if st is None:
                return "unknown"
            return "online" if int(st) else "offline"
        return "unknown"

    @property
    def extra_state_attributes(self):
        g = self._hub.gate_by_id(self.gate_id) or {}
        cam_id = g.get("cameraId") or ""
        cam = self._hub.camera_by_id(cam_id) if cam_id else None
        return {
            "integration": "akvilon_home",
            "gate_id": self.gate_id,
            "controller_status": g.get("controllerStatus"),
            "enabled": g.get("enabled"),
            "controller_id": str(g.get("controllerId") or ""),
            "camera_id": cam_id,
            "camera_name": str(cam.get("name") or "") if cam else "",
        }


class AkvilonIntercomSensor(SensorEntity):
    """Домофон: сенсор-состояние с привязкой домофон↔камера↔калитка.

    Сервер не шлёт события вызова как часть списков, поэтому основной смысл
    сенсора — отдать состояние (статус входа) и связку с камерой для карточек.
    Кнопка вызова/открытия — в button.py (AkvilonIntercomButton).
    """

    _attr_has_entity_name = False

    def __init__(self, hub, intercom_id, name):
        self._hub = hub
        self.intercom_id = str(intercom_id)
        self._name = name
        self._attr_unique_id = f"{DOMAIN}_intercom_{self.intercom_id.replace(':', '_')}"
        # Привязка к устройству «Домофон <имя>»
        self._attr_device_info = {
            "identifiers": {intercom_dev_id(self.intercom_id)},
            "name": f"Домофон {self._name}",
            "manufacturer": "Аквилон InHome",
            "model": "Домофон / калитка с камерой",
        }

    @property
    def name(self):
        return f"Домофон {self._name}"

    @property
    def icon(self):
        return "mdi:doorbell-video"

    @property
    def native_value(self):
        g = self._hub.gate_by_id(self.intercom_id)
        if g:
            st = g.get("controllerStatus")
            if st is None:
                return "unknown"
            return "online" if int(st) else "offline"
        return "unknown"

    @property
    def extra_state_attributes(self):
        link = self._hub.intercom_link(self.intercom_id)
        link["integration"] = "akvilon_home"
        return link


def _or_val(val):
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
        # Двух-тарифный счётчик (электричество): значения T1/T2 -> День/Ночь
        cur = _meter_current(m)
        vals = cur.get("values") if isinstance(cur, dict) else None
        if isinstance(vals, list) and len(vals) >= 2:
            sens.append(AkvilonMeterTariffSensor(m, 0, "День"))
            sens.append(AkvilonMeterTariffSensor(m, 1, "Ночь"))
    # Домофоны (intercoms) — подмножество калиток (gates с cameraId). Чтобы не
    # плодить дубли «калитка+домофон» на одну дверь, создаём для двери с камерой
    # ТОЛЬКО домофон, а для обычной калитки (без камеры) — калитку.
    intercom_ids = set(str(i.get("objectid") or i.get("objectId") or "") for i in hub.intercoms)
    for g in hub.gates:
        gid = str(g.get("objectid") or g.get("objectId") or "")
        if gid and gid not in intercom_ids:
            sens.append(AkvilonGateSensor(hub, gid, g.get("name") or "Калитка"))
    for ic in hub.intercoms:
        iid = str(ic.get("objectid") or ic.get("objectId") or "")
        if iid:
            sens.append(AkvilonIntercomSensor(hub, iid, ic.get("name") or "Домофон"))
    async_add_entities(sens, True)
    _LOGGER.info("Аквилон: добавлено %d сенсоров из сервера", len(sens))