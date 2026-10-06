"""Интеграция Аквилон InHome для Home Assistant.

Поддерживаются два способа настройки:

1. Config flow — через меню «Настройки -> Устройства и службы -> Добавить
   интеграцию». Параметры подключения (host/port/token/device_id/server_id)
   вводятся в мастере, создаётся Config Entry, сущности создаются через
   async_forward_entry_setups.

2. configuration.yaml (устаревший, для совместимости):
   ```yaml
   akvilon_home:
     host: "91.122.221.217"
     port: 19090
   ```
   Работает по-старому через async_setup. При желании конфиг из yaml можно
   удалить и полностью перейти на config flow.
"""
import logging
import asyncio
import time

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, entity_component
import voluptuous as vol

from .const import (
    DOMAIN,
    PLATFORMS,
    CONF_HOST,
    CONF_PORT,
    CONF_TOKEN,
    CONF_DEVICE_ID,
    CONF_SERVER_ID,
    CONF_NAME,
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_NAME,
    DEFAULT_DEVICE_ID,
    DEFAULT_SERVER_ID,
    CAMERAS,
    GATES,
    METERS,
)
from .camera import AkvilonCamera
from .button import AkvilonGateButton
from .sensor import AkvilonMeterSensor, AkvilonGateSensor
from .binary_sensor import AkvilonOnlineSensor
from .coordinator import AkvilonHub

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Optional("host", default=DEFAULT_HOST): cv.string,
                vol.Optional("port", default=DEFAULT_PORT): cv.port,
            },
            extra=vol.ALLOW_EXTRA,
        )
    },
    extra=vol.ALLOW_EXTRA,
)


# ---------------------------------------------------------------------------
# Устаревший путь через configuration.yaml — отключён (включите при необходимости)
# ---------------------------------------------------------------------------
async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Настройка через configuration.yaml. Отключён: используйте config flow."""
    return True


# ---------------------------------------------------------------------------
# Config flow путь
# ---------------------------------------------------------------------------
async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Настройка интеграции из Config Entry."""
    hub = AkvilonHub(
        host=entry.data.get(CONF_HOST, DEFAULT_HOST),
        port=entry.data.get(CONF_PORT, DEFAULT_PORT),
        token=entry.data.get("_PASS", entry.data.get(CONF_TOKEN, "")),
        device_id=entry.data.get(CONF_DEVICE_ID, DEFAULT_DEVICE_ID),
        server_id=entry.data.get(CONF_SERVER_ID, DEFAULT_SERVER_ID),
        name=entry.data.get(CONF_NAME, DEFAULT_NAME),
    )
    hub.selected = entry.data.get("selected")  # список выбранных устройств
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = hub
    _LOGGER.info(
        "Аквилон: setup_entry name='%s' host=%s:%s selected=%s",
        entry.title, hub.host, hub.port, hub.selected,
    )

    # Подключаемся к серверу и получаем списки ДО создания сущностей
    def _connect_refresh():
        hub.connect()
        for attempt in range(2):
            hub.refresh()
            if hub.cameras or hub.meters:
                break
            time.sleep(2)

    await hass.async_add_executor_job(_connect_refresh)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Периодическое обновление данных с сервера (камеры/калитки/счётчики)
    prev = {"cameras": set(), "gates": set(), "meters": set()}

    def _known(key, items):
        return set(str(x.get("objectid") or x.get("objectId") or "") for x in items if x.get("objectid") or x.get("objectId"))

    async def _periodic():
        while True:
            await asyncio.sleep(180)
            try:
                await hass.async_add_executor_job(hub.refresh)
                new_items = {
                    "cameras": _known("cameras", hub.cameras),
                    "gates": _known("gates", hub.gates),
                    "meters": _known("meters", hub.meters),
                }
                discovered = []
                for kind, ids in new_items.items():
                    for oid in ids:
                        if oid not in prev[kind]:
                            discovered.append(f"{kind}:{oid}")
                if discovered:
                    _LOGGER.info("Аквилон: найдены новые устройства: %s", discovered)
                    hass.bus.async_fire(f"{DOMAIN}_new_devices", {"entry_id": entry.entry_id, "devices": discovered})
                prev.update(new_items)
            except Exception:  # noqa: BLE001
                pass

    hass.loop.create_task(_periodic())
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Выгрузить интеграцию (удаляет сущности и закрывает соединение)."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    hub = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if hub is not None:
        await hass.async_add_executor_job(hub.close)
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Перезапуск интеграции (после изменения опций)."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Очистка данных при удалении интеграции."""
    _LOGGER.info("Аквилон: удаление интеграции %s", entry.entry_id)
    hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)