"""Бинарные сенсоры Аквилон: онлайн-статус сервера здания."""
import logging

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class AkvilonOnlineSensor(BinarySensorEntity):
    """Онлайн-статус сервера здания."""

    _attr_has_entity_name = False
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, hub):
        self._hub = hub
        self._attr_unique_id = f"{DOMAIN}_server_online_1"

    @property
    def name(self):
        return "Сервер здания онлайн"

    @property
    def is_on(self):
        # Онлайн, если последний успешный опрос сервера был менее 10 минут назад
        from time import monotonic
        return bool(self._hub._last_ok and (monotonic() - self._hub._last_ok < 600))

    @property
    def icon(self):
        return "mdi:cloud-check" if self.is_on else "mdi:cloud-off-outline"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    """Создаёт онлайн-сенсор сервера из Config Entry."""
    hub = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([AkvilonOnlineSensor(hub)], True)
