"""Юнит-тесты sensor.py — чистые функции нормализации показаний.

`_normalize_unit`, `_meter_current`, `_meter_value` не зависят от homeassistant
и покрываются голым Python. Классы-сущности требуют HA и покрываются отдельно.
"""
import json

from akvilon_home.sensor import _meter_current, _meter_value, _normalize_unit


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