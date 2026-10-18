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
    hub.favorite_cameras = set(entry.options.get("favorite_cameras", entry.data.get("favorite_cameras", [])))
    entry.async_on_unload(entry.add_update_listener(async_update_options))
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = hub
    _LOGGER.info(
        "Аквилон: setup_entry name='%s' host=%s:%s selected=%s favorites=%s",
        entry.title, hub.host, hub.port, hub.selected, hub.favorite_cameras,
    )

    # Домофон: сервисы действий при входящем вызове.
    async def _handle_open_gate(call):
        gate_id = call.data.get("gate_id", "")
        if not gate_id:
            raise vol.Invalid("gate_id обязателен")
        ok = await hass.async_add_executor_job(hub.open_gate, str(gate_id))
        return {"ok": ok}

    async def _handle_intercom_answer(call):
        cam_id = str(call.data.get("camera_id", ""))
        gate_id = str(call.data.get("gate_id", ""))
        if not cam_id:
            call_data = hub.active_call or {}
            cam_id = str(call_data.get("camId") or call_data.get("cameraId") or call_data.get("id") or "")
        if not cam_id:
            raise vol.Invalid("camera_id обязателен (или активен входящий вызов)")
        res = await hass.async_add_executor_job(hub.intercom_answer, cam_id, gate_id)
        return res

    async def _handle_intercom_accept_audio(call):
        cam_id = str(call.data.get("camera_id", ""))
        if not cam_id:
            call_data = hub.active_call or {}
            cam_id = str(call_data.get("camId") or call_data.get("cameraId") or call_data.get("id") or "")
        if not cam_id:
            raise vol.Invalid("camera_id обязателен")
        res = await hass.async_add_executor_job(hub.intercom_accept_audio, cam_id)
        return res

    async def _handle_intercom_unlock(call):
        gate_id = str(call.data.get("gate_id", ""))
        if not gate_id:
            call_data = hub.active_call or {}
            # берём калитку, связанную с активным вызовом
            link = {}
            cam_id = str(call_data.get("camId") or call_data.get("cameraId") or "")
            for g in hub._gates:
                if str(g.get("cameraId") or "") == cam_id:
                    gate_id = str(g.get("objectid") or g.get("objectId") or "")
                    break
        if not gate_id:
            raise vol.Invalid("gate_id обязателен")
        ok = await hass.async_add_executor_job(hub.intercom_unlock, str(gate_id))
        return {"ok": ok}

    async def _handle_voice_mic(call):
        """Управление микрофоном активного голосового канала (аналог setMicIsOn)."""
        on = bool(call.data.get("mic_on", True))
        volume = call.data.get("volume")
        if volume is not None:
            volume = float(volume)
        ok = await hass.async_add_executor_job(hub.voice_set_mic, on, volume)
        return {"mic_on": ok, "voice_active": hub.voice_active}

    async def _handle_voice_stop(call):
        """Закрыть голосовой канал (положить трубку)."""
        await hass.async_add_executor_job(hub._close_voice)
        return {"voice_active": hub.voice_active}

    async def _handle_simulate_call(call):
        """Симуляция входящего вызова домофона для проверки автоматизаций и всплывающего окна."""
        gate_id = str(call.data.get("gate_id") or "2:80649")
        cam_id = str(call.data.get("camera_id") or "117:69858")
        call_payload = {
            "call": "incoming",
            "gate_id": gate_id,
            "camera_id": cam_id,
            "caller": "Вход / Калитка 6",
            "time": time.time(),
        }
        hub._set_call(call_payload)
        for cb in list(hub._call_listeners):
            try:
                cb(call_payload)
            except Exception:
                pass
        return {"ok": True, "call": call_payload}

    async def _handle_clear_call(call):
        """Сброс активного вызова."""
        hub.clear_call()
        for cb in list(hub._call_listeners):
            try:
                cb(None)
            except Exception:
                pass
        return {"ok": True}

    async def _handle_set_favorite_camera(call):
        """Добавить или удалить камеру из избранных (поддерживает camera_id и entity_id, toggle)."""
        cam_id = str(call.data.get("camera_id") or "")
        entity_id = str(call.data.get("entity_id") or "")

        # Если передан entity_id (например, camera.kamera_dvor_2), извлекаем cam_id из attributes
        if not cam_id and entity_id:
            st = hass.states.get(entity_id)
            if st and st.attributes:
                cam_id = str(st.attributes.get("object_id") or st.attributes.get("cam_id") or "")
            if not cam_id:
                for c in hub.cameras:
                    cid = str(c.get("objectid") or c.get("objectId") or c.get("id") or "")
                    cname = str(c.get("name") or "").lower()
                    if cid in entity_id or (cname and cname in entity_id.lower()):
                        cam_id = cid
                        break

        if not cam_id:
            _LOGGER.warning("Аквилон: не удалось определить ID камеры для избранного: %s", call.data)
            return {"ok": False}

        is_fav = hub.is_favorite_camera(cam_id)
        if "favorite" in call.data:
            target_fav = bool(call.data.get("favorite"))
        else:
            target_fav = not is_fav

        hub.set_favorite_camera(cam_id, target_fav)
        new_favs = list(hub.favorite_cameras)
        new_options = dict(entry.options)
        new_options["favorite_cameras"] = new_favs
        hass.config_entries.async_update_entry(entry, options=new_options)

        # Обновляем состояние сущности камеры в HA, чтобы UI среагировал мгновенно
        if entity_id:
            st = hass.states.get(entity_id)
            if st:
                new_attrs = dict(st.attributes)
                new_attrs["is_favorite"] = target_fav
                hass.states.async_set(entity_id, st.state, new_attrs)

        # Перестраиваем Lovelace-дашборд с обновленным списком избранных камер
        try:
            from .dashboard import ensure_dashboard
            await hass.async_add_executor_job(ensure_dashboard, hass, hub)
        except Exception as exc:  # pragma: no cover
            _LOGGER.debug("Аквилон: обновление дашборда после изменения избранного: %s", exc)

        _LOGGER.info("Аквилон: камера %s %s в избранное", cam_id, "добавлена" if target_fav else "удалена из")
        return {"camera_id": cam_id, "is_favorite": target_fav, "favorite_cameras": new_favs}

    async def _handle_refresh(call):
        """Принудительно обновить списки и данные с сервера."""
        await hass.async_add_executor_job(hub.refresh)
        return {"ok": True}

    hass.services.async_register(DOMAIN, "open_gate", _handle_open_gate)
    hass.services.async_register(DOMAIN, "intercom_answer", _handle_intercom_answer)
    hass.services.async_register(DOMAIN, "intercom_accept_audio", _handle_intercom_accept_audio)
    hass.services.async_register(DOMAIN, "intercom_unlock", _handle_intercom_unlock)
    hass.services.async_register(DOMAIN, "voice_mic", _handle_voice_mic)
    hass.services.async_register(DOMAIN, "voice_stop", _handle_voice_stop)
    hass.services.async_register(DOMAIN, "simulate_call", _handle_simulate_call)
    hass.services.async_register(DOMAIN, "clear_call", _handle_clear_call)
    hass.services.async_register(DOMAIN, "set_favorite_camera", _handle_set_favorite_camera)
    hass.services.async_register(DOMAIN, "toggle_favorite_camera", _handle_set_favorite_camera)
    hass.services.async_register(DOMAIN, "refresh", _handle_refresh)

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

        # Автоматическая настройка раздела «Энергия»
        try:
            from .energy import async_configure_energy_dashboard
            await async_configure_energy_dashboard(hass, entry, hub)
        except Exception as exc:  # pragma: no cover
            _LOGGER.warning("Аквилон: не удалось настроить раздел «Энергия»: %s", exc)

        # Регистрация глобального JS-патча для страницы /energy
        try:
            from homeassistant.components.frontend import add_extra_js_url
            add_extra_js_url(hass, "/local/akvilon/akvilon-energy-patch.js?v=1.1")
        except Exception:  # pragma: no cover
            pass

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


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Обновляет настройки интеграции при сохранении опций."""
    hub = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if hub:
        hub.favorite_cameras = set(entry.options.get("favorite_cameras", []))
    try:
        from .dashboard import ensure_dashboard
        await hass.async_add_executor_job(ensure_dashboard, hass, hub)
    except Exception as exc:  # pragma: no cover
        _LOGGER.warning("Аквилон: не удалось обновить дашборд: %s", exc)

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
    hass.config_entries.async_update_entry(
        entry, data=new_data, version=2, minor_version=1
    )
    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Очистка данных при удалении интеграции."""
    _LOGGER.info("Аквилон: удаление интеграции %s", entry.entry_id)
    hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)