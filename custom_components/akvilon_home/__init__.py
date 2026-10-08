"""Интеграция Аквилон InHome для Home Assistant.

Поддерживаются два способа настройки:

1. Config flow — через меню «Настройки -> Устройства и службы -> Добавить
   интеграцию». Параметры подключения (host/port/token/device_id/server_id)
   вводятся в мастере, создаётся Config Entry, сущности создаются через
   async_forward_entry_setups.

2. configuration.yaml (устаревший, для совместимости):
   ```yaml
   akvilon_home:
     host: "127.0.0.1"
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

    # Устанавливаем флаг "setup завершается фоном" — создаём сущности,
    # как только сервер ответит данными, НЕ блокируя загрузку HA.
    # Это решает проблему зависания bootstrap при медленном сервере здания.
    async def _setup_after_data():
        try:
            if entry.data.get("demo"):
                await hass.async_add_executor_job(hub.load_demo_data)
            else:
                await hass.async_add_executor_job(hub.refresh)
        except Exception as exc:  # pragma: no cover
            _LOGGER.warning("Аквилон: первичная загрузка данных не удалась: %s", exc)
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        # Создаём/обновляем дашборд «Аквилон» после появления сущностей.
        try:
            from .dashboard import ensure_dashboard
            await hass.async_add_executor_job(ensure_dashboard, hass, hub)
        except Exception as exc:  # pragma: no cover
            _LOGGER.warning("Аквилон: не удалось настроить дашборд: %s", exc)

    hass.loop.create_task(_setup_after_data())
    # Периодическое обновление данных с сервера (камеры/калитки/счётчики/домофоны)
    prev = {"cameras": set(), "gates": set(), "meters": set(), "intercoms": set()}
    stable = {"cameras": set(), "gates": set(), "meters": set(), "intercoms": set()}

    def _known(key, items):
        return set(str(x.get("objectid") or x.get("objectId") or "") for x in items if x.get("objectid") or x.get("objectId"))

    async def _periodic():
        while True:
            # Редкий опрос — только чтобы замечать появление/исчезновение
            # устройств на сервере. Актуальные значения приходят push-ом,
            # поэтому часто опрашивать сервер списками не нужно (как на
            # телефоне: списки грузятся по требованию, события — пушатся).
            await asyncio.sleep(300)
            try:
                await hass.async_add_executor_job(hub.refresh)
                new_items = {
                    "cameras": _known("cameras", hub.cameras),
                    "gates": _known("gates", hub.gates),
                    "meters": _known("meters", hub.meters),
                    "intercoms": _known("intercoms", hub.intercoms),
                }
                # Устройство считаем «новым» только если оно объявляется в двух
                # опросах подряд (сервер иногда недопередаёт список в одном из
                # циклов). Собираем кандидатов между опросами.
                confirmed = set()
                for kind in new_items:
                    fresh = new_items[kind] - prev[kind]  # ещё не было у нас
                    # если элемент был кандидатом и снова свежий — подтверждён
                    confirmed |= (fresh & stable[kind])
                    stable[kind] = fresh  # кандидаты текущего цикла
                if confirmed:
                    _LOGGER.info("Аквилон: подтверждены новые устройства: %s — перезагружаю платформы", confirmed)
                    await hass.config_entries.async_reload(entry.entry_id)
                    return
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
    # При удалении интеграции удаляем дашборд «Аквилон».
    try:
        from .dashboard import remove_dashboard
        await hass.async_add_executor_job(remove_dashboard, hass)
    except Exception:  # pragma: no cover
        pass
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Перезапуск интеграции (после изменения опций)."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)




async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Миграция конфигурации со старой версии (1) на новую (2).

    v1 -> v2: добавлены поля create_dashboard/add_to_energy и тарифы.
    Если поля отсутствуют — подставляем значения по умолчанию.
    """
    version = entry.version
    _LOGGER.info("Аквилон: миграция entry %s с версии %s на %s",
                 getattr(entry, "entry_id", "?"), version, 2)
    new_data = dict(getattr(entry, "data", {}) or {})
    new_data.setdefault("create_dashboard", True)
    new_data.setdefault("add_to_energy", True)
    new_data.setdefault("electricity_tariff_day", 8.67)
    new_data.setdefault("electricity_tariff_night", 3.91)
    new_data.setdefault("cold_water_tariff", 0.0)
    new_data.setdefault("hot_water_tariff", 0.0)
    entry.data = new_data
    entry.version = 2
    entry.minor_version = 1
    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Очистка данных при удалении интеграции."""
    _LOGGER.info("Аквилон: удаление интеграции %s", entry.entry_id)
    hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)