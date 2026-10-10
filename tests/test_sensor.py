"""Юнит-тесты sensor.py — чистые функции нормализации показаний.

`_normalize_unit`, `_meter_current`, `_meter_value` не зависят от homeassistant
и покрываются голым Python. Классы-сущности требуют HA и покрываются отдельно.
"""
import json

from akvilon_home.sensor import _meter_current, _meter_value, _normalize_unit
from akvilon_home.sensor import AkvilonMeterSensor


class TestNormalizeUnit:
    def test_recognized(self):
        assert _normalize_unit("м3") == "m³"
        assert _normalize_unit("м³") == "m³"
        assert _normalize_unit("кВт*ч") == "kWh"
        assert _normalize_unit("квт*ч") == "kWh"
        assert _normalize_unit("Гкал") == "Gcal"
        assert _normalize_unit("M3") == "m³"

    def test_unknown_passthrough(self):
        assert _normalize_unit("см") == "см"

    def test_empty_is_none(self):
        assert _normalize_unit("") is None
        assert _normalize_unit(None) is None


class TestMeterCurrent:
    def test_dict_current(self):
        m = {"current": {"value": 121.2, "unit": "m³"}}
        assert _meter_current(m) == {"value": 121.2, "unit": "m³"}

    def test_string_current_parsed(self):
        m = {"current": json.dumps({"value": 5, "unit": "kWh"})}
        assert _meter_current(m) == {"value": 5, "unit": "kWh"}

    def test_invalid_string(self):
        m = {"current": "not-json{"}
        assert _meter_current(m) is None

    def test_no_current(self):
        assert _meter_current({}) is None
        assert _meter_value({}) is None
        assert _meter_value({"current": {"value": 88.4}}) == 88.4


class TestMeterDeviceClass:
    """Детерминированный device_class (по единицам, без resourceType на сервере)."""

    def test_electricity_by_unit(self):
        m = {"name": "Электричество", "current": {"unit": "кВт*ч", "value": 9992.95}}
        assert AkvilonMeterSensor._meter_device_class(m) == "energy"

    def test_water_by_unit(self):
        m = {"name": "ГВС", "current": {"unit": "м³", "value": 121.2}}
        assert AkvilonMeterSensor._meter_device_class(m) == "water"

    def test_heating_by_unit(self):
        m = {"name": "Отопление", "current": {"unit": "Гкал", "value": 3.4}}
        # Гкал -> энергия (счётчик), не вода
        assert AkvilonMeterSensor._meter_device_class(m) == "energy"

    def test_resource_type_fallback(self):
        m = {"name": "Счётчик", "resourceType": "1", "current": {"unit": "", "value": 1}}
        assert AkvilonMeterSensor._meter_device_class(m) == "energy"

    def test_unknown_unit_no_class(self):
        m = {"name": "Счётчик", "current": {"unit": "см", "value": 1}}
        assert AkvilonMeterSensor._meter_device_class(m) is None

    def test_no_current_no_class(self):
        assert AkvilonMeterSensor._meter_device_class({}) is None