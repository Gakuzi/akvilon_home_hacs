"""Бинарные сенсоры Аквилон: онлайн-статус сервера и входящий вызов домофона."""
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


class AkvilonIntercomCallSensor(BinarySensorEntity):
    """Входящий вызов с домофона.

    Включается, когда push-listener координитора получает от сервера событие
    вызова (звонок с домофона). Значение и атрибуты читаются из hub.active_call.
    Актуальность зависит от того, что сервер реально пушит при живом звонке.
    """

    _attr_has_entity_name = False
    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY
    _attr_should_poll = False

    def __init__(self, hub):
        self._hub = hub
        self._attr_unique_id = f"{DOMAIN}_intercom_call_1"

    @property
    def name(self):
        return "Домофон входящий вызов"

    @property
    def icon(self):
        return "mdi:doorbell-video" if self.is_on else "mdi:doorbell"

    @property
    def is_on(self):
        call = self._hub.active_call
        return bool(call)

    @property
    def extra_state_attributes(self):
        call = self._hub.active_call
        if not call:
            return {"integration": DOMAIN, "call": False}
        cam_id = str(call.get("camId") or call.get("cameraId") or call.get("id") or "")
        gate_id = ""
        gate_name = ""
        cam_name = ""
        link = {}
        # пытаемся связать вызов с известной калиткой/домофоном по cameraId
        if cam_id:
            cam = self._hub.camera_by_id(cam_id)
            if cam:
                cam_name = str(cam.get("name") or "")
            for g in self._hub._gates:
                if str(g.get("cameraId") or "") == cam_id:
                    gate_id = str(g.get("objectid") or g.get("objectId") or "")
                    gate_name = str(g.get("name") or "")
                    break
            if gate_id:
                link = self._hub.intercom_link(gate_id)
        attrs = {"integration": DOMAIN, "call": True}
        attrs["camera_id"] = cam_id
        attrs["camera_name"] = cam_name
        attrs["gate_id"] = gate_id
        attrs["gate_name"] = gate_name
        attrs["call_data"] = {k: str(v) for k, v in call.items()
                              if k not in ("channel",)}
        attrs["channel"] = call.get("channel", 0)
        if link:
            attrs.update({f"link_{k}": v for k, v in link.items()})
        return attrs

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        hub = self._hub

        def _on_call(_call):
            try:
                self.schedule_update_ha_state()
            except Exception:
                pass

        # Перевешиваем колбэк в main loop через experimental helper-парадигму:
        # schedule_update_ha_state потокобезопасен — можно вызывать напрямую.
        hub.set_call_listener(_on_call)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    """Создаёт онлайн-сенсор сервера и сенсор входящего вызова."""
    hub = hass.data[DOMAIN][entry.entry_id]
    hub.start_listener()
    async_add_entities(
        [AkvilonOnlineSensor(hub), AkvilonIntercomCallSensor(hub)], True
    )