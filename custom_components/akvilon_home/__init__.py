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
    CONF_GO2RTC_ENABLED,
    CONF_GO2RTC_BASE_URL,
    CONF_FRIGATE_ENABLED,
    CONF_FRIGATE_BASE_URL,
    CONF_FRIGATE_API_URL,
    CONF_FRIGATE_LABELS,
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_NAME,
    DEFAULT_DEVICE_ID,
    DEFAULT_SERVER_ID,
    DEFAULT_GO2RTC_BASE_URL,
    DEFAULT_FRIGATE_BASE_URL,
    DEFAULT_FRIGATE_API_URL,
    DEFAULT_FRIGATE_LABELS,
    CAMERAS,
    GATES,
    METERS,
)
from .camera import AkvilonCamera
from .button import AkvilonGateButton
from .sensor import AkvilonMeterSensor, AkvilonGateSensor
from .binary_sensor import AkvilonOnlineSensor
from .coordinator import AkvilonHub
from .viewer import ViewerServer

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

    # ---- сервисы управления веб-панелью камер (viewer) ----
    async def _async_start_viewer(call):
        port = call.data.get("port", 8090)
        refresh = call.data.get("refresh", 12)
        v = ViewerServer(hub, port=port, refresh=refresh)
        await hass.async_add_executor_job(v._start)
        hass.data.setdefault("akvilon_viewers", {})[entry.entry_id] = v
        _LOGGER.info("Аквилон: веб-панель камер запущена на порту %d", port)

    async def _async_stop_viewer(call):
        v = hass.data.get("akvilon_viewers", {}).pop(entry.entry_id, None)
        if v:
            await hass.async_add_executor_job(v._stop)
            _LOGGER.info("Аквилон: веб-панель камер остановлена")

    hass.services.async_register(DOMAIN, "start_viewer", _async_start_viewer)
    hass.services.async_register(DOMAIN, "stop_viewer", _async_stop_viewer)

    # ---- сервисы go2rtc/WebRTC (живой поток домофона/камер, опционально) ----
    from . import go2rtc as _go2rtc

    def _hub_for_entry():
        return hass.data.get(DOMAIN, {}).get(entry.entry_id)

    def _camera_ids_for_media(hub_obj) -> list[str]:
        """Ид камер для go2rtc/Frigate: приоритет — камеры домофонов, фолбэк — все."""
        intercoms = getattr(hub_obj, "intercoms", None) or []
        ids = [str(i.get("cameraId") or "") for i in intercoms if str(i.get("cameraId") or "") not in ("", "0:-1")]
        if not ids:
            ids = [str(c.get("objectid") or c.get("objectId") or "")
                   for c in (getattr(hub_obj, "cameras", None) or [])]
        return list(dict.fromkeys(x for x in ids if x))

    async def _async_go2rtc_config(call):
        """Возвращает готовый YAML-блок ``streams:`` для go2rtc.yaml."""
        hub = _hub_for_entry()
        if hub is None:
            return {"error": "hub unavailable"}
        py = call.data.get("python", "python3")
        only = str(call.data.get("cam_id") or "").strip()
        specs = []
        for cid in _camera_ids_for_media(hub):
            if only and cid != only:
                continue
            specs.append({
                "cam_id": cid,
                "settings": (hub._video_settings or {}).get(cid) or {},
            })
        if not specs:
            return {"error": "no cameras"}
        yaml_block = _go2rtc.build_config(
            specs,
            host=hub.host, port=hub.port,
            passwd=hub.token, device_id=hub.device_id, server_id=hub.server_id,
            python=py,
        )
        return {"cameras": len(specs), "yaml": yaml_block}

    async def _async_go2rtc_stream_url(call):
        """Возвращает webrtc-адрес потока для карточки custom:webrtc-camera."""
        hub = _hub_for_entry()
        if hub is None:
            return {"error": "hub unavailable"}
        cid = str(call.data.get("cam_id") or "").strip()
        base = str(call.data.get("base_url") or
                   (dict(entry.options or {}).get(CONF_GO2RTC_BASE_URL) or DEFAULT_GO2RTC_BASE_URL))
        if not cid:
            return {"error": "cam_id required"}
        return {
            "cam_id": cid,
            "stream": _go2rtc.go2rtc_stream_name(cid),
            "webrtc_url": _go2rtc.webrtc_url(base, cid),
            "api_url": _go2rtc.api_stream_url(base, cid),
        }

    async def _async_go2rtc_proxy_cmd(call):
        """Возвращает ``exec:``-команду для go2rtc (диагностика/ручная настройка)."""
        hub = _hub_for_entry()
        if hub is None:
            return {"error": "hub unavailable"}
        cid = str(call.data.get("cam_id") or "").strip()
        if not cid:
            return {"error": "cam_id required"}
        py = call.data.get("python", "python3")
        return {
            "cam_id": cid,
            "exec": _go2rtc.build_exec_cmd(
                cid, hub.host, hub.port, hub.token, hub.device_id, hub.server_id, py,
            ),
        }

    hass.services.async_register(DOMAIN, "go2rtc_config", _async_go2rtc_config)
    hass.services.async_register(DOMAIN, "go2rtc_stream_url", _async_go2rtc_stream_url)
    hass.services.async_register(DOMAIN, "go2rtc_proxy_cmd", _async_go2rtc_proxy_cmd)

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
        # Авто-запуск веб-панели камер (viewer) на порту 8090 — чтобы панель
        # сразу работала после настройки, без ручного сервиса start_viewer.
        try:
            if entry.data.get("start_viewer", True):
                v = ViewerServer(hub, port=8090, refresh=12)
                await hass.async_add_executor_job(v._start)
                hass.data.setdefault("akvilon_viewers", {})[entry.entry_id] = v
                _LOGGER.info("Аквилон: веб-панель камер авто-запущена на порту 8090")
        except Exception as exc:  # pragma: no cover
            _LOGGER.warning("Аквилон: не удалось авто-запустить viewer: %s", exc)
        # Интегрируем счётчики в «Энергию» (после создания сущностей).
        try:
            from .energy import async_setup_energy
            await async_setup_energy(hass, entry)
        except Exception as exc:  # pragma: no cover
            _LOGGER.warning("Аквилон: не удалось настроить энергосистему: %s", exc)
        # Создаём/обновляем дашборд «Аквилон». Сущности регистрируются асинхронно,
        # поэтому пересобираем панель несколько раз с паузой, чтобы успеть собрать
        # реальные entity_id (иначе первый запуск видит пустой registry).
        try:
            from .dashboard import ensure_dashboard
            await hass.async_add_executor_job(ensure_dashboard, hass, hub)
            for _ in range(3):
                await asyncio.sleep(2)
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
    # остановить веб-панель камер, если запущена
    v = hass.data.get("akvilon_viewers", {}).pop(entry.entry_id, None)
    if v is not None:
        await hass.async_add_executor_job(v._stop)
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
    # Опции go2rtc/WebRTC и Frigate (актуально для старых entry без этих полей).
    new_data.setdefault(CONF_GO2RTC_ENABLED, False)
    new_data.setdefault(CONF_GO2RTC_BASE_URL, DEFAULT_GO2RTC_BASE_URL)
    new_data.setdefault(CONF_FRIGATE_ENABLED, False)
    new_data.setdefault(CONF_FRIGATE_BASE_URL, DEFAULT_FRIGATE_BASE_URL)
    new_data.setdefault(CONF_FRIGATE_API_URL, DEFAULT_FRIGATE_API_URL)
    new_data.setdefault(CONF_FRIGATE_LABELS, DEFAULT_FRIGATE_LABELS)
    entry.data = new_data
    entry.version = 2
    entry.minor_version = 1
    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Очистка данных при удалении интеграции."""
    _LOGGER.info("Аквилон: удаление интеграции %s", entry.entry_id)
    hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)