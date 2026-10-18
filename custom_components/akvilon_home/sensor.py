"""Сенсоры состояния калиток и приборов учёта Аквилон (из живых данных сервера)."""
from __future__ import annotations

import logging
from time import monotonic

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
    """Показание прибора учёта (счётчика) квартиры с контролем расхода и изменений."""

    _attr_has_entity_name = False

    def __init__(self, meter: dict, hub=None, tariffs: dict | None = None):
        self.meter = meter
        self.hub = hub
        self.tariffs = tariffs or {}
        dn = _or_val(meter.get("deviceNumber") or meter.get("device_number"))
        name = meter.get("name") or "Счётчик"
        self._attr_unique_id = f"{DOMAIN}_meter_{dn}"
        self._label = name
        self._device_number = dn
        self._object_id = str(meter.get("objectid") or meter.get("objectId") or "")

    def _get_meter(self) -> dict:
        if self.hub and hasattr(self.hub, "meter_by_id"):
            return self.hub.meter_by_id(self._device_number) or self.hub.meter_by_id(self._object_id) or self.meter
        return self.meter

    @property
    def name(self):
        return f"Счётчик {self._label}"

    @property
    def icon(self):
        return "mdi:counter"

    @property
    def native_value(self):
        m = self._get_meter()
        val = _meter_value(m)
        if val is None:
            return None
        return val

    @property
    def native_unit_of_measurement(self):
        m = self._get_meter()
        cur = _meter_current(m)
        if isinstance(cur, dict):
            raw_unit = (cur.get("unit") or "").strip()
            return _normalize_unit(raw_unit)
        return None

    @property
    def suggested_unit_of_measurement(self):
        return self.native_unit_of_measurement

    @property
    def device_class(self):
        m = self._get_meter()
        t = str(m.get("resourceType", ""))
        if t in ("1",):  # electricity
            return "energy"
        if t in ("2", "3"):  # water
            return "water"
        return None

    @property
    def state_class(self):
        # Счётчики — накопительные показания (total_increasing).
        return "total_increasing"

    def _get_tariff_rate(self) -> float:
        m = self._get_meter()
        t = str(m.get("resourceType", ""))
        name = str(m.get("name", "")).lower()
        tariffs = self.tariffs or (getattr(self.hub, "tariffs", {}) if self.hub else {})
        if t == "1":
            return float(tariffs.get("electricity_tariff_day", 8.67))
        if t == "2" or "хвс" in name:
            return float(tariffs.get("cold_water_tariff", 59.60)) + float(tariffs.get("sewage_tariff", 48.24))
        if t == "3" or "гвс" in name:
            return float(tariffs.get("hot_water_tariff", 210.00)) + float(tariffs.get("sewage_tariff", 48.24))
        if t == "4" or "отопление" in name:
            return float(tariffs.get("heating_tariff_gcal", 2550.00))
        return 0.0

    @property
    def extra_state_attributes(self):
        m = self._get_meter()
        attrs = {"integration": "akvilon_home"}
        attrs["device_number"] = self._device_number
        attrs["resource_type"] = m.get("resourceType")
        attrs["meter_type"] = m.get("meterType")
        attrs["object_id"] = self._object_id
        cur = _meter_current(m)
        dt = ""
        if isinstance(cur, dict):
            dt = cur.get("dt") or ""
            attrs["reading_date"] = dt
            if "values" in cur:
                attrs["tariffs"] = cur["values"]
            raw_val = cur.get("value")
            t = str(m.get("resourceType", ""))
            raw_unit = str(cur.get("unit") or "").lower()
            if t in ("4",) or "гкал" in raw_unit:
                attrs["raw_value_gcal"] = raw_val
                attrs["raw_unit"] = "Гкал"

        # Метрики отслеживания изменений и контроля расхода
        rate = self._get_tariff_rate()
        val = self.native_value
        unit = self.native_unit_of_measurement or ""
        ent_id = getattr(self, "entity_id", None)
        if self.hub and hasattr(self.hub, "meter_tracker"):
            metrics = self.hub.meter_tracker.update_reading(
                key=self._device_number,
                current_value=val,
                unit=unit,
                reading_date=dt,
                tariff_rate=rate,
                entity_id=ent_id,
                device_number=self._device_number,
            )
            attrs.update(metrics)
        return attrs


class AkvilonMeterTariffSensor(SensorEntity):
    """Отдельный сенсор тарифа двух-тарифного счётчика (День/Ночь) с контролем расхода."""

    _attr_has_entity_name = False
    _attr_device_class = "energy"
    _attr_state_class = "total_increasing"
    _attr_suggested_display_precision = 2

    def __init__(self, meter: dict, tariff_index: int, tariff_label: str, hub=None, tariffs: dict | None = None):
        self.meter = meter
        self.hub = hub
        self.tariffs = tariffs or {}
        self.tariff_index = tariff_index
        self._tariff_label = tariff_label
        self._label = (meter.get("name") or "Счётчик") + f" ({tariff_label})"
        dn = _or_val(meter.get("deviceNumber") or meter.get("device_number"))
        self._device_number = dn
        self._object_id = str(meter.get("objectid") or meter.get("objectId") or "")
        self._attr_unique_id = f"{DOMAIN}_meter_{dn}_tariff{tariff_index}"
        self._tariff_number = tariff_index + 1

    def _get_meter(self) -> dict:
        if self.hub and hasattr(self.hub, "meter_by_id"):
            return self.hub.meter_by_id(self._device_number) or self.hub.meter_by_id(self._object_id) or self.meter
        return self.meter

    @property
    def name(self):
        return f"Счётчик {self._label}"

    @property
    def icon(self):
        return "mdi:chart-bell-curve-cumulative"

    @property
    def native_value(self):
        m = self._get_meter()
        cur = _meter_current(m)
        if isinstance(cur, dict) and isinstance(cur.get("values"), list):
            vals = cur["values"]
            if self.tariff_index < len(vals):
                return vals[self.tariff_index]
        return None

    @property
    def native_unit_of_measurement(self):
        return "kWh"

    def _get_tariff_rate(self) -> float:
        tariffs = self.tariffs or (getattr(self.hub, "tariffs", {}) if self.hub else {})
        if self.tariff_index == 0:
            return float(tariffs.get("electricity_tariff_day", 8.67))
        return float(tariffs.get("electricity_tariff_night", 3.91))

    @property
    def extra_state_attributes(self):
        m = self._get_meter()
        cur = _meter_current(m)
        dt = cur.get("dt") if isinstance(cur, dict) else ""
        attrs = {
            "integration": "akvilon_home",
            "device_number": self._device_number,
            "object_id": self._object_id,
            "tariff": f"T{self._tariff_number}",
            "tariff_index": self.tariff_index,
            "reading_date": dt,
        }

        rate = self._get_tariff_rate()
        val = self.native_value
        ent_id = getattr(self, "entity_id", None)
        key = f"{self._device_number}_tariff{self.tariff_index}"
        if self.hub and hasattr(self.hub, "meter_tracker"):
            metrics = self.hub.meter_tracker.update_reading(
                key=key,
                current_value=val,
                unit="kWh",
                reading_date=dt,
                tariff_rate=rate,
                entity_id=ent_id,
                device_number=self._device_number,
            )
            attrs.update(metrics)
        return attrs


class AkvilonMeterHeatingEnergySensor(SensorEntity):
    """Сенсор отопления/теплоснабжения в ГДж (GJ) для раздела «Энергия» с контролем расхода."""

    _attr_has_entity_name = False
    _attr_device_class = "gas"
    _attr_state_class = "total_increasing"
    _attr_native_unit_of_measurement = "GJ"
    _attr_icon = "mdi:radiator"

    def __init__(self, meter: dict, hub=None, tariffs: dict | None = None):
        self.meter = meter
        self.hub = hub
        self.tariffs = tariffs or {}
        dn = _or_val(meter.get("deviceNumber") or meter.get("device_number"))
        name = meter.get("name") or "Счётчик Теплоснабжение"
        self._attr_unique_id = f"{DOMAIN}_meter_{dn}_gj"
        self._label = f"Теплоснабжение (ГДж)"
        self._device_number = dn
        self._object_id = str(meter.get("objectid") or meter.get("objectId") or "")
        self._attr_suggested_object_id = "schetchik_kvartira_31_otoplenie_gdzh"

    def _get_meter(self) -> dict:
        if self.hub and hasattr(self.hub, "meter_by_id"):
            return self.hub.meter_by_id(self._device_number) or self.hub.meter_by_id(self._object_id) or self.meter
        return self.meter

    @property
    def name(self):
        return f"Счётчик {self._label}"

    @property
    def native_value(self):
        m = self._get_meter()
        val = _meter_value(m)
        if val is None:
            return None
        try:
            return round(float(val) * 4.1868, 4)
        except (ValueError, TypeError):
            return None

    @property
    def native_unit_of_measurement(self):
        return "GJ"

    @property
    def device_class(self):
        return "gas"

    @property
    def state_class(self):
        return "total_increasing"

    def _get_tariff_rate(self) -> float:
        tariffs = self.tariffs or (getattr(self.hub, "tariffs", {}) if self.hub else {})
        return float(tariffs.get("heating_tariff_gj", 609.05))

    @property
    def extra_state_attributes(self):
        m = self._get_meter()
        cur = _meter_current(m) or {}
        dt = cur.get("dt") or ""
        attrs = {
            "integration": DOMAIN,
            "device_number": self._device_number,
            "raw_value_gcal": cur.get("value"),
            "conversion": "1 Gcal = 4.1868 GJ",
            "reading_date": dt,
        }

        rate = self._get_tariff_rate()
        val = self.native_value
        ent_id = getattr(self, "entity_id", None)
        key = f"{self._device_number}_gj"
        if self.hub and hasattr(self.hub, "meter_tracker"):
            metrics = self.hub.meter_tracker.update_reading(
                key=key,
                current_value=val,
                unit="GJ",
                reading_date=dt,
                tariff_rate=rate,
                entity_id=ent_id,
                device_number=self._device_number,
            )
            attrs.update(metrics)
        return attrs


class AkvilonTariffPriceSensor(SensorEntity):
    """Сенсор стоимости тарифа ЖКУ (для автоматического расчета затрат в разделе «Энергия»)."""

    _attr_has_entity_name = False
    _attr_icon = "mdi:cash"

    def __init__(self, key: str, label: str, unit: str, val: float):
        self._key = key
        self._label = label
        self._unit = unit
        self._val = val
        self._attr_unique_id = f"{DOMAIN}_tariff_{key}"
        if key == "heating_tariff_gj":
            self._attr_suggested_object_id = "tarif_otoplenie_gdzh"
        elif key == "heating_tariff_gcal":
            self._attr_suggested_object_id = "tarif_otoplenie"

    @property
    def name(self):
        return f"Тариф {self._label}"

    @property
    def native_value(self):
        return self._val

    @property
    def native_unit_of_measurement(self):
        return self._unit

    @property
    def extra_state_attributes(self):
        attrs = {
            "integration": "akvilon_home",
            "tariff_key": self._key,
        }
        if self._key == "heating_tariff_gj":
            attrs["price_per_gcal"] = round(self._val * 4.1868, 2)
        return attrs


class AkvilonGateSensor(SensorEntity):
    """Состояние калитки (статус контроллера)."""

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


class AkvilonServerLatencySensor(SensorEntity):
    """Сенсор задержки ответа (пинга) сервера здания в мс."""

    _attr_has_entity_name = False
    _attr_icon = "mdi:speedometer"
    _attr_native_unit_of_measurement = "ms"

    def __init__(self, hub):
        self._hub = hub
        self._attr_unique_id = f"{DOMAIN}_server_latency"

    @property
    def name(self):
        return "Аквилон Задержка сервера"

    @property
    def native_value(self):
        return self._hub.ping_ms if self._hub.ping_ms is not None else 0.0

    async def async_update(self):
        """Неблокирующий замер задержки через пул потоков."""
        await self.hass.async_add_executor_job(self._hub.ping_server)

    @property
    def extra_state_attributes(self):
        return {
            "host": self._hub.host,
            "port": self._hub.port,
            "server_id": self._hub.server_id,
            "consecutive_errors": self._hub.consecutive_errors,
            "last_error": self._hub.last_error or "none",
        }


class AkvilonServerStatusSensor(SensorEntity):
    """Сенсор общего состояния системы и доступности оборудования."""

    _attr_has_entity_name = False
    _attr_icon = "mdi:shield-check"

    def __init__(self, hub):
        self._hub = hub
        self._attr_unique_id = f"{DOMAIN}_system_status"

    @property
    def name(self):
        return "Аквилон Состояние системы"

    @property
    def native_value(self):
        is_on = bool(self._hub._last_ok and (monotonic() - self._hub._last_ok < 1800))
        if not is_on:
            return "Сбой связи"
        if self._hub.consecutive_errors > 2:
            return "Предупреждение"
        return "В норме"

    @property
    def extra_state_attributes(self):
        gates_on = sum(1 for g in self._hub.gates if g.get("controllerStatus") == 1)
        return {
            "cameras_total": len(self._hub.cameras),
            "cameras_online": len(self._hub.cameras),
            "gates_total": len(self._hub.gates),
            "gates_online": gates_on,
            "gates_offline": len(self._hub.gates) - gates_on,
            "intercoms_total": len(self._hub.intercoms),
            "meters_total": len(self._hub.meters),
            "listener_active": bool(self._hub._listener_thread and self._hub._listener_thread.is_alive()),
            "favorite_cameras_count": len(self._hub.favorite_cameras),
            "server_address": f"{self._hub.host}:{self._hub.port}",
        }


class AkvilonUtilityTotalCostSensor(SensorEntity):
    """Сенсор суммарной расчетной стоимости ЖКУ за текущий объем."""

    _attr_has_entity_name = False
    _attr_icon = "mdi:cash-multiple"
    _attr_native_unit_of_measurement = "RUB"
    _attr_device_class = "monetary"

    def __init__(self, hub, tariffs: dict):
        self._hub = hub
        self._tariffs = tariffs
        self._attr_unique_id = f"{DOMAIN}_utility_total_cost"

    @property
    def name(self):
        return "Аквилон Стоимость ЖКУ за месяц"

    @property
    def native_value(self):
        breakdown = self._calc_costs()
        return round(sum(breakdown.values()), 2)

    def _calc_costs(self) -> dict[str, float]:
        res = {"electricity": 0.0, "cold_water": 0.0, "hot_water": 0.0, "heating": 0.0}
        for m in self._hub.meters:
            rtype = str(m.get("resourceType") or "")
            name = str(m.get("name") or "").lower()
            val = _meter_value(m)
            if val is None:
                continue
            try:
                v = float(val)
            except (ValueError, TypeError):
                continue

            if rtype == "1":
                cur = _meter_current(m)
                vals = cur.get("values") if isinstance(cur, dict) else None
                if isinstance(vals, list) and len(vals) >= 2:
                    t1_val = float(vals[0])
                    t2_val = float(vals[1])
                    t1_rate = float(self._tariffs.get("electricity_tariff_day", 8.67))
                    t2_rate = float(self._tariffs.get("electricity_tariff_night", 3.91))
                    res["electricity"] = round(t1_val * t1_rate + t2_val * t2_rate, 2)
                else:
                    t1_rate = float(self._tariffs.get("electricity_tariff_day", 8.67))
                    res["electricity"] = round(v * t1_rate, 2)
            elif rtype == "2" or "хвс" in name:
                rate = float(self._tariffs.get("cold_water_tariff", 59.60))
                sewage = float(self._tariffs.get("sewage_tariff", 48.24))
                res["cold_water"] = round(v * (rate + sewage), 2)
            elif rtype == "3" or "гвс" in name:
                rate = float(self._tariffs.get("hot_water_tariff", 210.00))
                sewage = float(self._tariffs.get("sewage_tariff", 48.24))
                res["hot_water"] = round(v * (rate + sewage), 2)
            elif rtype == "4" or "отопление" in name:
                rate = float(self._tariffs.get("heating_tariff_gcal", 2550.00))
                res["heating"] = round(v * rate, 2)
        return res

    @property
    def extra_state_attributes(self):
        breakdown = self._calc_costs()
        return {
            "electricity_rub": breakdown.get("electricity", 0.0),
            "cold_water_rub": breakdown.get("cold_water", 0.0),
            "hot_water_rub": breakdown.get("hot_water", 0.0),
            "heating_rub": breakdown.get("heating", 0.0),
        }


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    """Создаёт сенсоры из живых списков сервера."""
    hub = hass.data[DOMAIN][entry.entry_id]

    # Настройка путей хранения и базы данных для MeterTracker
    if hasattr(hub, "meter_tracker") and hasattr(hass, "config"):
        import os
        hub.meter_tracker._storage_dir = hass.config.path(".storage")
        hub.meter_tracker._storage_file = os.path.join(hub.meter_tracker._storage_dir, "akvilon_meter_history.json")
        hub.meter_tracker._db_path = hass.config.path("home-assistant_v2.db")
        hub.meter_tracker._load()

    # Тарифные сенсоры стоимости ЖКУ (г. Архангельск, все валюты в рублях)
    from .tariffs import DEFAULT_TARIFFS
    tariff_defs = [
        ("electricity_tariff_day", "Электроэнергия (День)", "RUB/kWh"),
        ("electricity_tariff_night", "Электроэнергия (Ночь)", "RUB/kWh"),
        ("cold_water_tariff", "Холодная вода (ХВС)", "RUB/m³"),
        ("hot_water_tariff", "Горячая вода (ГВС)", "RUB/m³"),
        ("sewage_tariff", "Водоотведение", "RUB/m³"),
        ("heating_tariff_gcal", "Отопление", "RUB/Гкал"),
        ("heating_tariff_gj", "Отопление (ГДж)", "RUB/GJ"),
    ]
    cur_tariffs = {}
    sens = []
    for key, label, unit in tariff_defs:
        val = float(entry.data.get(key, DEFAULT_TARIFFS.get(key, 0.0)) or DEFAULT_TARIFFS.get(key, 0.0))
        cur_tariffs[key] = val
        sens.append(AkvilonTariffPriceSensor(key, label, unit, val))

    hub.tariffs = cur_tariffs

    for m in hub.meters:
        sens.append(AkvilonMeterSensor(m, hub=hub, tariffs=cur_tariffs))
        # Двух-тарифный счётчик (электричество): значения T1/T2 -> День/Ночь
        cur = _meter_current(m)
        vals = cur.get("values") if isinstance(cur, dict) else None
        if isinstance(vals, list) and len(vals) >= 2:
            sens.append(AkvilonMeterTariffSensor(m, 0, "День", hub=hub, tariffs=cur_tariffs))
            sens.append(AkvilonMeterTariffSensor(m, 1, "Ночь", hub=hub, tariffs=cur_tariffs))
        rtype = str(m.get("resourceType") or "")
        name = str(m.get("name") or "").lower()
        if rtype == "4" or "отопление" in name:
            sens.append(AkvilonMeterHeatingEnergySensor(m, hub=hub, tariffs=cur_tariffs))
    for g in hub.gates:
        gid = str(g.get("objectid") or g.get("objectId") or "")
        if gid:
            sens.append(AkvilonGateSensor(hub, gid, g.get("name") or "Калитка"))
    for ic in hub.intercoms:
        iid = str(ic.get("objectid") or ic.get("objectId") or "")
        if iid:
            sens.append(AkvilonIntercomSensor(hub, iid, ic.get("name") or "Домофон"))

    # Диагностические и системные сенсоры
    sens.append(AkvilonServerLatencySensor(hub))
    sens.append(AkvilonServerStatusSensor(hub))
    sens.append(AkvilonUtilityTotalCostSensor(hub, cur_tariffs))

    async_add_entities(sens, True)
    _LOGGER.info("Аквилон: добавлено %d сенсоров из сервера", len(sens))