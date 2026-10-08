"""conftest.py — настройка тестовой среды для интеграции Аквилон.

Модули protocol/rtp_stream/coordinator/viewer/const не импортируют homeassistant
и тестируются голым Python. sensor.py (чистые функции _normalize_unit и т.д.)
после импорта класса SensorEntity проходит дальше — поэтому здесь поднимается
минимальная заглушка пакета `homeassistant`, достаточная чтобы импортировать
модули, которые лишь наследуюются от HA-классов, но не инстанцируют их.

Важно: мы НЕ выполняем настоящий __init__.py пакета akvilon_home (он тянет
домашний Assistant). Реестрируем фиктивный пакет с правильным __path__.
"""
import os
import sys
import types

_COMPONENT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "custom_components", "akvilon_home")
)


def _install_hass_stub():
    """Заглушка homeassistant.* только если модуль реально не установлен."""
    def mk(pkg, parent=None, path=None):
        name = f"{parent}.{pkg}" if parent else pkg
        if name in sys.modules:
            return sys.modules[name]
        m = types.ModuleType(name)
        m.__package__ = name
        if path:
            m.__path__ = path
        sys.modules[name] = m
        return m

    root = mk("homeassistant", None, [])
    root.__path__ = []
    computers = mk("components", "homeassistant", [])
    sensors = mk("sensor", "homeassistant.components")
    binary = mk("binary_sensor", "homeassistant.components")
    camera = mk("camera", "homeassistant.components")
    button = mk("button", "homeassistant.components")

    class _EntityBase:
        def __init__(self, *a, **kw):
            self._attr_unique_id = None
            self._attr_has_entity_name = False
            self._attr_device_class = None
            self._attr_state_class = None
            self._attr_should_poll = False

        async def async_added_to_hass(self):
            pass

        async def async_will_remove_from_hass(self):
            pass

    class SensorEntity(_EntityBase):
        pass

    class BinarySensorEntity(_EntityBase):
        pass

    class BinarySensorDeviceClass:
        CONNECTIVITY = "connectivity"

    class Camera(_EntityBase):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self._attr_unique_id = None

    class ButtonEntity(_EntityBase):
        pass

    sensors.SensorEntity = SensorEntity
    binary.BinarySensorEntity = BinarySensorEntity
    binary.BinarySensorDeviceClass = BinarySensorDeviceClass
    camera.Camera = Camera
    button.ButtonEntity = ButtonEntity

    # homeassistant.config_entries и core — для импорта сигнатур
    core = mk("core", "homeassistant")
    class HomeAssistant:
        pass
    core.HomeAssistant = HomeAssistant

    ce = mk("config_entries", "homeassistant")
    class ConfigEntry:
        def __init__(self, *a, **kw):
            self.data = kw.pop("data", {}) or {}
    ce.ConfigEntry = ConfigEntry


if "homeassistant" not in sys.modules:
    _install_hass_stub()

# Пакет-стаб вместо настоящего __init__.py
if "akvilon_home" not in sys.modules:
    pkg = types.ModuleType("akvilon_home")
    pkg.__path__ = [_COMPONENT]
    pkg.__package__ = "akvilon_home"
    sys.modules["akvilon_home"] = pkg

# Подмодули доступны для прямого импорта
sys.path.insert(0, _COMPONENT)