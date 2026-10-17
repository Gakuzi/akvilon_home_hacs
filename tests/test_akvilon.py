"""Unit tests for Akvilon InHome integration."""
import sys
import types
import unittest
import base64
from unittest.mock import MagicMock

# Мок окружения Home Assistant для изолированного модульного тестирования
if "homeassistant" not in sys.modules:
    def _make_mock_pkg(name):
        m = types.ModuleType(name)
        sys.modules[name] = m
        return m

    ha = _make_mock_pkg("homeassistant")
    ha_comp = _make_mock_pkg("homeassistant.components")
    ha.components = ha_comp
    ha_sensor = _make_mock_pkg("homeassistant.components.sensor")
    ha_comp.sensor = ha_sensor
    ha_sensor.SensorEntity = type("SensorEntity", (), {})
    ha_sensor.SensorDeviceClass = type("SensorDeviceClass", (), {
        "ENERGY": "energy", "POWER": "power", "MONETARY": "monetary", "WATER": "water", "GAS": "gas"
    })
    ha_sensor.SensorStateClass = type("SensorStateClass", (), {
        "TOTAL_INCREASING": "total_increasing", "MEASUREMENT": "measurement"
    })

    ha_bs = _make_mock_pkg("homeassistant.components.binary_sensor")
    ha_comp.binary_sensor = ha_bs
    ha_bs.BinarySensorEntity = type("BinarySensorEntity", (), {})
    ha_bs.BinarySensorDeviceClass = type("BinarySensorDeviceClass", (), {
        "CONNECTIVITY": "connectivity", "DOOR": "door", "OCCUPANCY": "occupancy"
    })

    ha_cam = _make_mock_pkg("homeassistant.components.camera")
    ha_comp.camera = ha_cam
    ha_cam.Camera = type("Camera", (), {})

    ha_btn = _make_mock_pkg("homeassistant.components.button")
    ha_comp.button = ha_btn
    ha_btn.ButtonEntity = type("ButtonEntity", (), {})

    ha_ce = _make_mock_pkg("homeassistant.config_entries")
    ha.config_entries = ha_ce
    ha_ce.ConfigEntry = type("ConfigEntry", (), {})

    ha_core = _make_mock_pkg("homeassistant.core")
    ha.core = ha_core
    ha_core.HomeAssistant = type("HomeAssistant", (), {})
    ha_core.callback = lambda f: f

    ha_hlp = _make_mock_pkg("homeassistant.helpers")
    ha.helpers = ha_hlp
    ha_ep = _make_mock_pkg("homeassistant.helpers.entity_platform")
    ha_hlp.entity_platform = ha_ep
    ha_cv = MagicMock()
    ha_hlp.config_validation = ha_cv
    sys.modules["homeassistant.helpers.config_validation"] = ha_cv
    ha_ec = _make_mock_pkg("homeassistant.helpers.entity_component")
    ha_hlp.entity_component = ha_ec
    ha_er = _make_mock_pkg("homeassistant.helpers.entity_registry")
    ha_hlp.entity_registry = ha_er

    sys.modules["voluptuous"] = MagicMock()

from custom_components.akvilon_home.protocol import (
    pack_a7id,
    parse_id,
    parse_qr,
    CH_CAMERAS,
    CH_METERS,
    CH_GATES,
)
from custom_components.akvilon_home.rtp_stream import parse_sprop
from custom_components.akvilon_home.tariffs import (
    DEFAULT_TARIFFS,
    get_tariffs_for_city,
    calc_utility_cost,
)
from custom_components.akvilon_home.sensor import _normalize_unit


class TestTariffs(unittest.TestCase):
    def test_default_tariffs_exist(self):
        self.assertIn("electricity_tariff_day", DEFAULT_TARIFFS)
        self.assertIn("electricity_tariff_night", DEFAULT_TARIFFS)
        self.assertIn("cold_water_tariff", DEFAULT_TARIFFS)
        self.assertIn("hot_water_tariff", DEFAULT_TARIFFS)
        self.assertIn("heating_tariff_gj", DEFAULT_TARIFFS)

    def test_city_tariffs_fallback(self):
        tariffs = get_tariffs_for_city("Архангельск")
        self.assertEqual(tariffs["electricity_tariff_day"], DEFAULT_TARIFFS["electricity_tariff_day"])

    def test_cost_calculation(self):
        # 100 kWh * 8.67 = 867.0
        cost = calc_utility_cost("electricity_tariff_day", 100.0, DEFAULT_TARIFFS)
        self.assertAlmostEqual(cost, 867.0, places=2)


class TestProtocol(unittest.TestCase):
    def test_pack_a7id(self):
        b = pack_a7id(119, 50957, version=1)
        self.assertEqual(len(b), 16)

    def test_parse_id(self):
        flag, obj_id = parse_id("111:69724")
        self.assertEqual(flag, 111)
        self.assertEqual(obj_id, 69724)

    def test_parse_qr(self):
        qr_str = "HOST=192.168.0.6;PORT=8080;PASS=secret123;DEVICE_ID=100"
        data = parse_qr(qr_str)
        self.assertEqual(data.get("HOST"), "192.168.0.6")
        self.assertEqual(int(data.get("PORT")), 8080)
        self.assertEqual(data.get("PASS"), "secret123")


class TestRtpStream(unittest.TestCase):
    def test_parse_sprop(self):
        # Valid SPS/PPS base64 pair
        sprop = "Z00AHukCwS0IAAAfSAAGHBAg,aOqPIA=="
        bps = parse_sprop(sprop)
        self.assertEqual(len(bps), 2)
        self.assertTrue(len(bps[0]) > 0)
        self.assertTrue(len(bps[1]) > 0)

    def test_parse_sprop_empty(self):
        self.assertEqual(parse_sprop(""), [])


class TestSensorUnits(unittest.TestCase):
    def test_normalize_unit(self):
        self.assertEqual(_normalize_unit("м3"), "m³")
        self.assertEqual(_normalize_unit("квт*ч"), "kWh")
        self.assertEqual(_normalize_unit("гкал"), "Gcal")

    def test_heating_conversion(self):
        # 1 Gcal = 4.1868 GJ
        val_gcal = 10.0
        val_gj = round(val_gcal * 4.1868, 4)
        self.assertAlmostEqual(val_gj, 41.868, places=3)

    def test_meter_sensors_arkhangelsk(self):
        from custom_components.akvilon_home.sensor import (
            AkvilonMeterSensor,
            AkvilonMeterHeatingEnergySensor,
            AkvilonUtilityTotalCostSensor,
        )
        fake_meter = {
            "deviceNumber": "22059787",
            "name": "Квартира 31 Отопление",
            "resourceType": "4",
            "current": {"value": 12.0872, "unit": "Гкал"},
        }
        user_sensor = AkvilonMeterSensor(fake_meter)
        self.assertEqual(user_sensor.native_value, 12.0872)
        self.assertEqual(user_sensor.native_unit_of_measurement, "Gcal")
        self.assertIsNone(user_sensor.device_class)

        energy_sensor = AkvilonMeterHeatingEnergySensor(fake_meter)
        self.assertAlmostEqual(energy_sensor.native_value, round(12.0872 * 4.1868, 4), places=4)
        self.assertEqual(energy_sensor.native_unit_of_measurement, "GJ")
        self.assertEqual(energy_sensor.device_class, "energy")


class TestDashboardAndFavorites(unittest.TestCase):
    def test_dashboard_views_structure(self):
        from custom_components.akvilon_home.dashboard import build_dashboard_payload
        payload = build_dashboard_payload(hass=None, hub=None)
        self.assertIn("data", payload)
        self.assertIn("config", payload["data"])
        views = payload["data"]["config"]["views"]
        view_paths = [v["path"] for v in views]
        self.assertIn("overview", view_paths)
        self.assertIn("cameras", view_paths)
        self.assertIn("gates", view_paths)
        self.assertIn("intercoms", view_paths)
        self.assertIn("meters", view_paths)
        self.assertIn("diagnostics", view_paths)
        self.assertIn("kiosk", view_paths)

    def test_dashboard_cameras_lazy_loading(self):
        from custom_components.akvilon_home.dashboard import build_dashboard_payload
        payload = build_dashboard_payload(hass=None, hub=None)
        views = payload["data"]["config"]["views"]
        cam_view = next(v for v in views if v["path"] == "cameras")
        self.assertIsNotNone(cam_view)
        # Проверяем карточки камер
        cards = cam_view.get("cards", [])
        grid_cards = [c for c in cards if c.get("type") == "grid"]
        for g in grid_cards:
            for card in g.get("cards", []):
                if card.get("type") == "custom:akvilon-camera-card":
                    self.assertTrue(card.get("lazy"))

    def test_favorite_cameras_coordinator(self):
        from custom_components.akvilon_home.coordinator import AkvilonHub
        hub = AkvilonHub("127.0.0.1", 19090, "token", "dev1", "serv1", name="Тест")
        self.assertFalse(hub.is_favorite_camera("111:69724"))
        hub.set_favorite_camera("111:69724", True)
        self.assertTrue(hub.is_favorite_camera("111:69724"))
        hub.set_favorite_camera("111:69724", False)
    def test_camera_grid_columns_large_preview(self):
        from custom_components.akvilon_home.dashboard import build_dashboard_payload
        payload = build_dashboard_payload(hass=None, hub=None)
        views = payload["data"]["config"]["views"]
        cam_view = next(v for v in views if v["path"] == "cameras")
        cards = cam_view.get("cards", [])
        grid_cards = [c for c in cards if c.get("type") == "grid"]
        for g in grid_cards:
            self.assertEqual(g.get("columns"), 2)


if __name__ == "__main__":
    unittest.main()
