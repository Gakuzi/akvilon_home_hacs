"""Бинарные сенсоры Аквилон: онлайн-статус сервера здания."""
import logging
from time import monotonic

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

_ONLINE_WINDOW_S = 1800  # сервер считается онлайн, если последний опрос был < 30 мин


class AkvilonOnlineSensor(BinarySensorEntity):
    """Онлайн-статус сервера здания.

    Значение читается из hub._last_ok (monotonic-метка последнего успешного
    опроса сервера в coordinator.refresh). Чтобы сенсор сам переключался между
    online/offline в реальном времени, он планирует своё переобновление.
    """

    _attr_has_entity_name = False
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_should_poll = False

    def __init__(self, hub):
        self._hub = hub
        self._attr_unique_id = f"{DOMAIN}_server_online_1"

    @property
    def name(self):
        return "Сервер здания онлайн"

    @property
    def is_on(self):
        return bool(self._hub._last_ok and (monotonic() - self._hub._last_ok < _ONLINE_WINDOW_S))

    @property
    def icon(self):
        return "mdi:cloud-check" if self.is_on else "mdi:cloud-off-outline"

    async def async_added_to_hass(self):
        """Само-переобновление: дожидаемся истечения окна, затем обновляемся."""
        await super().async_added_to_hass()

        async def _poll():
            import asyncio
            while True:
                try:
                    await asyncio.sleep(60)
                    self.async_write_ha_state()
                except asyncio.CancelledError:
                    break
                except Exception:  # noqa: BLE001
                    break

        self._poll_task = self.hass.loop.create_task(_poll())

    async def async_will_remove_from_hass(self):
        if getattr(self, "_poll_task", None):
            self._poll_task.cancel()


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    """Создаёт онлайн-сенсор сервера из Config Entry."""
    hub = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([AkvilonOnlineSensor(hub)], True)
