"""Автоматическое создание/удаление дашборда «Аквилон» в Home Assistant.

При setup интеграции регистрируется Lovelace-дашборд `akvilon` в сайдбаре,
при unload — удаляется. Дашборд содержит красивые секции: статус сервера,
калитки с камерой, все калитки, счётчики, камеры, подъезды.
"""
import json
import logging
import os

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

DASH_KEY = "lovelace.dashboard_akvilon"
STORAGE_DIR = "/config/.storage"

# Публичная копия дашборда (встроена в модуль, без личных данных).
DASH_PAYLOAD = """{"version": 1, "minor_version": 1, "key": "lovelace.dashboard_akvilon", "data": {"config": {"views": [{"type": "sections", "title": "Аквилон", "path": "akvilon", "sections": [{"type": "grid", "cards": [{"type": "heading", "heading": "Статус сервера", "heading_style": "title"}, {"type": "markdown", "content": "**Аквилон InHome** — серверный концентратор ЖК\\n\\nСостояние подключения к серверу здания:", "grid_options": {"columns": "full"}}, {"type": "tile", "entity": "binary_sensor.akvilon_server_onlain", "name": "Сервер здания", "icon": "mdi:server-network", "color": "blue", "vertical": false, "grid_options": {"columns": "full"}}, {"type": "markdown", "content": "▸ **Калитки:** карточки с камерой и кнопкой «Открыть»\\n▸ **Камеры:** все 69 камер двора и подъездов\\n▸ **Счётчики:** квартира 31 (ГВС, ХВС, отопление, электричество)", "grid_options": {"columns": "full"}}]}, {"type": "grid", "cards": [{"type": "heading", "heading": "Калитки с камерой", "heading_style": "title"}, {"type": "vertical-stack", "cards": [{"type": "picture-entity", "entity": "camera.kamera_kalitka_12_reka_7", "camera_view": "live", "show_state": false, "show_name": true, "name": "Калитка 12 · Река 7", "grid_options": {"columns": "full"}}, {"type": "entities", "entities": [{"entity": "sensor.kalitka_kalitka_12_sostoianie", "name": "Состояние"}, {"entity": "button.otkryt_kalitka_12", "name": "Открыть калитку 12"}], "state_color": true}]}, {"type": "vertical-stack", "cards": [{"type": "picture-entity", "entity": "camera.kamera_kalitka_11_reka_7", "camera_view": "live", "show_state": false, "show_name": true, "name": "Калитка 11 · Река 7"}, {"type": "entities", "entities": [{"entity": "sensor.kalitka_kalitka_11_sostoianie", "name": "Состояние"}, {"entity": "button.otkryt_kalitka_11", "name": "Открыть калитку 11"}], "state_color": true}]}, {"type": "vertical-stack", "cards": [{"type": "picture-entity", "entity": "camera.kamera_kalitka_10_reka_6", "camera_view": "live", "show_state": false, "show_name": true, "name": "Калитка 10 · Река 6"}, {"type": "entities", "entities": [{"entity": "sensor.kalitka_kalitka_10_sostoianie", "name": "Состояние"}, {"entity": "button.otkryt_kalitka_10", "name": "Открыть калитку 10"}], "state_color": true}]}, {"type": "vertical-stack", "cards": [{"type": "picture-entity", "entity": "camera.kamera_kalitka_9_reka_6", "camera_view": "live", "show_state": false, "show_name": true, "name": "Калитка 9 · Река 6"}, {"type": "entities", "entities": [{"entity": "sensor.kalitka_kalitka_9_sostoianie", "name": "Состояние"}, {"entity": "button.otkryt_kalitka_9", "name": "Открыть калитку 9"}], "state_color": true}]}, {"type": "vertical-stack", "cards": [{"type": "picture-entity", "entity": "camera.kamera_kalitka_8_reka_5", "camera_view": "live", "show_state": false, "show_name": true, "name": "Калитка 8 · Река 5"}, {"type": "entities", "entities": [{"entity": "sensor.kalitka_kalitka_8_sostoianie", "name": "Состояние"}, {"entity": "button.otkryt_kalitka_8", "name": "Открыть калитку 8"}], "state_color": true}]}, {"type": "vertical-stack", "cards": [{"type": "picture-entity", "entity": "camera.kamera_kalitka_6_reka_4", "camera_view": "live", "show_state": false, "show_name": true, "name": "Калитка 6 · Река 4"}, {"type": "entities", "entities": [{"entity": "sensor.kalitka_kalitka_6_sostoianie", "name": "Состояние"}, {"entity": "button.otkryt_kalitka_6", "name": "Открыть калитку 6"}], "state_color": true}]}]}, {"type": "grid", "cards": [{"type": "heading", "heading": "Все калитки", "heading_style": "title"}, {"type": "grid", "columns": 3, "square": false, "cards": [{"type": "custom:mushroom-entity-card", "entity": "button.otkryt_kalitka_1", "icon": "mdi:gate", "name": "Калитка 1", "primary_info": "name", "secondary_info": "none", "tap_action": {"action": "call-service", "service": "button.press", "service_data": {"entity_id": "button.otkryt_kalitka_1"}}}, {"type": "custom:mushroom-entity-card", "entity": "sensor.kalitka_kalitka_1_sostoianie", "icon": "mdi:gate", "name": "Статус 1", "secondary_info": "last-changed"}, {"type": "custom:mushroom-entity-card", "entity": "button.otkryt_kalitka_2", "icon": "mdi:gate", "name": "Калитка 2", "primary_info": "name", "secondary_info": "none", "tap_action": {"action": "call-service", "service": "button.press", "service_data": {"entity_id": "button.otkryt_kalitka_2"}}}, {"type": "custom:mushroom-entity-card", "entity": "sensor.kalitka_kalitka_2_sostoianie", "icon": "mdi:gate", "name": "Статус 2", "secondary_info": "last-changed"}, {"type": "custom:mushroom-entity-card", "entity": "button.otkryt_kalitka_3", "icon": "mdi:gate", "name": "Калитка 3", "primary_info": "name", "secondary_info": "none", "tap_action": {"action": "call-service", "service": "button.press", "service_data": {"entity_id": "button.otkryt_kalitka_3"}}}, {"type": "custom:mushroom-entity-card", "entity": "sensor.kalitka_kalitka_3_sostoianie", "icon": "mdi:gate", "name": "Статус 3", "secondary_info": "last-changed"}, {"type": "custom:mushroom-entity-card", "entity": "button.otkryt_kalitka_4", "icon": "mdi:gate", "name": "Калитка 4", "primary_info": "name", "secondary_info": "none", "tap_action": {"action": "call-service", "service": "button.press", "service_data": {"entity_id": "button.otkryt_kalitka_4"}}}, {"type": "custom:mushroom-entity-card", "entity": "sensor.kalitka_kalitka_4_sostoianie", "icon": "mdi:gate", "name": "Статус 4", "secondary_info": "last-changed"}, {"type": "custom:mushroom-entity-card", "entity": "button.otkryt_kalitka_5", "icon": "mdi:gate", "name": "Калитка 5", "primary_info": "name", "secondary_info": "none", "tap_action": {"action": "call-service", "service": "button.press", "service_data": {"entity_id": "button.otkryt_kalitka_5"}}}, {"type": "custom:mushroom-entity-card", "entity": "sensor.kalitka_kalitka_5_sostoianie", "icon": "mdi:gate", "name": "Статус 5", "secondary_info": "last-changed"}, {"type": "custom:mushroom-entity-card", "entity": "button.otkryt_kalitka_7", "icon": "mdi:gate", "name": "Калитка 7", "primary_info": "name", "secondary_info": "none", "tap_action": {"action": "call-service", "service": "button.press", "service_data": {"entity_id": "button.otkryt_kalitka_7"}}}, {"type": "custom:mushroom-entity-card", "entity": "sensor.kalitka_kalitka_7_sostoianie", "icon": "mdi:gate", "name": "Статус 7", "secondary_info": "last-changed"}, {"type": "custom:mushroom-entity-card", "entity": "button.otkryt_kalitka_13", "icon": "mdi:gate", "name": "Калитка 13", "primary_info": "name", "secondary_info": "none", "tap_action": {"action": "call-service", "service": "button.press", "service_data": {"entity_id": "button.otkryt_kalitka_13"}}}, {"type": "custom:mushroom-entity-card", "entity": "sensor.kalitka_kalitka_13_sostoianie", "icon": "mdi:gate", "name": "Статус 13", "secondary_info": "last-changed"}, {"type": "custom:mushroom-entity-card", "entity": "button.otkryt_kalitka_14", "icon": "mdi:gate", "name": "Калитка 14", "primary_info": "name", "secondary_info": "none", "tap_action": {"action": "call-service", "service": "button.press", "service_data": {"entity_id": "button.otkryt_kalitka_14"}}}, {"type": "custom:mushroom-entity-card", "entity": "sensor.kalitka_kalitka_14_sostoianie", "icon": "mdi:gate", "name": "Статус 14", "secondary_info": "last-changed"}, {"type": "custom:mushroom-entity-card", "entity": "button.otkryt_kalitka_15", "icon": "mdi:gate", "name": "Калитка 15", "primary_info": "name", "secondary_info": "none", "tap_action": {"action": "call-service", "service": "button.press", "service_data": {"entity_id": "button.otkryt_kalitka_15"}}}, {"type": "custom:mushroom-entity-card", "entity": "sensor.kalitka_kalitka_15_sostoianie", "icon": "mdi:gate", "name": "Статус 15", "secondary_info": "last-changed"}, {"type": "custom:mushroom-entity-card", "entity": "button.otkryt_kalitka_16", "icon": "mdi:gate", "name": "Калитка 16", "primary_info": "name", "secondary_info": "none", "tap_action": {"action": "call-service", "service": "button.press", "service_data": {"entity_id": "button.otkryt_kalitka_16"}}}, {"type": "custom:mushroom-entity-card", "entity": "sensor.kalitka_kalitka_16_sostoianie", "icon": "mdi:gate", "name": "Статус 16", "secondary_info": "last-changed"}, {"type": "custom:mushroom-entity-card", "entity": "button.otkryt_kalitka_17", "icon": "mdi:gate", "name": "Калитка 17", "primary_info": "name", "secondary_info": "none", "tap_action": {"action": "call-service", "service": "button.press", "service_data": {"entity_id": "button.otkryt_kalitka_17"}}}, {"type": "custom:mushroom-entity-card", "entity": "sensor.kalitka_kalitka_17_sostoianie", "icon": "mdi:gate", "name": "Статус 17", "secondary_info": "last-changed"}, {"type": "custom:mushroom-entity-card", "entity": "button.otkryt_kalitka_18", "icon": "mdi:gate", "name": "Калитка 18", "primary_info": "name", "secondary_info": "none", "tap_action": {"action": "call-service", "service": "button.press", "service_data": {"entity_id": "button.otkryt_kalitka_18"}}}, {"type": "custom:mushroom-entity-card", "entity": "sensor.kalitka_kalitka_18_sostoianie", "icon": "mdi:gate", "name": "Статус 18", "secondary_info": "last-changed"}]}]}, {"type": "grid", "cards": [{"type": "heading", "heading": "Счётчики · квартира 31", "heading_style": "title"}, {"type": "grid", "columns": 2, "cards": [{"type": "tile", "entity": "sensor.schetchik_elektrichestvo_2", "name": "Электричество", "icon": "mdi:lightning-bolt", "color": "yellow", "vertical": false}, {"type": "tile", "entity": "sensor.schetchik_gvs_goriachaia_voda_2", "name": "ГВС", "icon": "mdi:thermometer", "color": "red", "vertical": false}, {"type": "tile", "entity": "sensor.schetchik_khvs_kholodnaia_voda_2", "name": "ХВС", "icon": "mdi:water", "color": "blue", "vertical": false}, {"type": "tile", "entity": "sensor.schetchik_otoplenie_2", "name": "Отопление", "icon": "mdi:radiator", "color": "orange", "vertical": false}]}, {"type": "markdown", "content": "**Тарифы** доступны в карточке счётчика (нажмите на счётчик, чтобы посмотреть ГВС/ХВС по тарифам)."}]}]}, {"type": "panel", "title": "Камеры", "path": "cameras", "cards": [{"type": "glance", "title": "Все камеры", "entities": ["camera.kamera_kalitka_12_reka_7", "camera.kamera_kalitka_11_reka_7", "camera.kamera_kalitka_10_reka_6", "camera.kamera_kalitka_9_reka_6", "camera.kamera_kalitka_8_reka_5", "camera.kamera_kalitka_6_reka_4", "camera.kamera_reka_7_torets_doma", "camera.kamera_reka_7_vid_na_kalitku_2", "camera.kamera_reka_7_proezd_2", "camera.kamera_reka_7_kholl_lift_lestnitsa", "camera.kamera_reka_7_koliasochnaia", "camera.kamera_reka_7_vid_na_kalitku", "camera.kamera_reka_7_detskaia_ploshchadka", "camera.kamera_reka_7_proezd", "camera.kamera_reka_7_podezd_1", "camera.kamera_lift_reka_7", "camera.kamera_reka_5_16", "camera.kamera_reka_5_15", "camera.kamera_reka_5_14", "camera.kamera_reka_5_13", "camera.kamera_reka_5_12", "camera.kamera_reka_5_11", "camera.kamera_reka_5_10", "camera.kamera_reka_5_9", "camera.kamera_reka_5_8", "camera.kamera_reka_5", "camera.kamera_reka_5_2", "camera.kamera_reka_5_5", "camera.kamera_reka_5_3", "camera.kamera_reka_5_2_2", "camera.kamera_reka_5_1", "camera.kamera_reka_5_koliasochnaia", "camera.kamera_reka_5_podezd_2_2", "camera.kamera_reka_5_podezd_2_1", "camera.kamera_reka_5_podezd_1", "camera.kamera_reka_6_cam_19", "camera.kamera_reka_6_cam_18", "camera.kamera_reka_6_cam_17", "camera.kamera_reka_6_cam_16", "camera.kamera_reka_6_cam_15", "camera.kamera_reka_6_cam_14", "camera.kamera_reka_6_cam_13", "camera.kamera_reka_6_cam_11", "camera.kamera_reka_6_koliasochnaia", "camera.kamera_reka_6_podezd_1", "camera.kamera_ul_sovetskaia", "camera.kamera_ul_sovetskaia_2pod", "camera.kamera_ul_sovetskaia_2", "camera.kamera_ul_sovetskaia_3", "camera.kamera_ul_sovetskaia_3_pod", "camera.kamera_ul_sovetskaia_4", "camera.kamera_dvor_4", "camera.kamera_dvor_3", "camera.kamera_dvor_2", "camera.kamera_dvor_5", "camera.kamera_dvor_1", "camera.kamera_detskaia_komnata", "camera.kamera_prokhod_3_i_4_kor", "camera.kamera_prokhod_4_i_5_kor", "camera.kamera_4", "camera.kamera_kholl_lifta_2p", "camera.kamera_kholl_lifta_3p", "camera.kamera_kholl_lifta_1p", "camera.kamera_paradnaia_3_2", "camera.kamera_paradnaia_3_1", "camera.kamera_paradnaia_2_2", "camera.kamera_paradnaia_2_1", "camera.kamera_paradnaia_1_2", "camera.kamera_paradnaia_1_1"], "show_name": true, "show_state": false, "columns": 4}]}, {"type": "sections", "title": "Подъезды", "path": "podezdy", "sections": [{"type": "grid", "cards": [{"type": "heading", "heading": "Домофонные входы", "heading_style": "title"}, {"type": "vertical-stack", "cards": [{"type": "picture-entity", "entity": "camera.kamera_paradnaia_1_2", "camera_view": "live", "show_state": false, "show_name": true, "name": "Река 4 · Проход 1-2"}, {"type": "entities", "entities": [{"entity": "sensor.kalitka_reka_4_prokhod_1_2_sostoianie", "name": "Состояние"}, {"entity": "button.otkryt_reka_4_prokhod_1_2", "name": "Открыть дверь"}], "state_color": true}]}, {"type": "vertical-stack", "cards": [{"type": "picture-entity", "entity": "camera.kamera_paradnaia_1_1", "camera_view": "live", "show_state": false, "show_name": true, "name": "Река 4 · Проход 1-1"}, {"type": "entities", "entities": [{"entity": "sensor.kalitka_reka4_prohod_1_1_sostoianie", "name": "Состояние"}, {"entity": "button.otkryt_reka4_prohod_1_1", "name": "Открыть дверь"}], "state_color": true}]}]}]}]}}}"""


def _storage_path():
    return os.path.join(STORAGE_DIR, DASH_KEY)


def _dashboard_exists() -> bool:
    return os.path.exists(_storage_path())


def _registered() -> bool:
    try:
        reg_path = os.path.join(STORAGE_DIR, "lovelace_dashboards")
        if not os.path.exists(reg_path):
            return False
        reg = json.load(open(reg_path))
        data = reg.get("data", {})
        dashboards = data.get("dashboards", {}) if isinstance(data, dict) else {}
        return "dashboard_akvilon" in dashboards
    except Exception:
        return False


def ensure_dashboard(hass: HomeAssistant):
    """Создаёт и регистрирует дашборд «Аквилон», если его ещё нет."""
    try:
        payload = json.loads(DASH_PAYLOAD)
    except Exception as exc:  # pragma: no cover
        _LOGGER.warning("Аквилон: повреждён встроенный дашборд: %s", exc)
        return
    if not _dashboard_exists():
        try:
            os.makedirs(STORAGE_DIR, exist_ok=True)
            json.dump(payload, open(_storage_path(), "w"), ensure_ascii=False)
            _LOGGER.info("Аквилон: создан файл дашборда %s", DASH_KEY)
        except Exception as exc:  # pragma: no cover
            _LOGGER.warning("Аквилон: не удалось создать дашборд-файл: %s", exc)
            return
    if not _registered():
        try:
            reg_path = os.path.join(STORAGE_DIR, "lovelace_dashboards")
            reg = {"version": 1, "minor_version": 1,
                   "key": "lovelace_dashboards", "data": {}}
            if os.path.exists(reg_path):
                try:
                    reg = json.load(open(reg_path))
                except Exception:
                    reg = {"version": 1, "minor_version": 1,
                           "key": "lovelace_dashboards", "data": {}}
                # гарантируем служебные ключи
                reg.setdefault("version", 1)
                reg.setdefault("minor_version", 1)
                reg.setdefault("key", "lovelace_dashboards")
                reg.setdefault("data", {})
            data = reg["data"]
            # items (список) — основной формат реестра
            items = data.setdefault("items", [])
            entry = {
                "id": "dashboard_akvilon",
                "title": "Аквилон",
                "icon": "mdi:video-wireless",
                "url_path": "akvilon",
                "mode": "storage",
                "require_admin": False,
                "show_in_sidebar": True,
            }
            if not any(x.get("id") == "dashboard_akvilon" for x in items):
                items.append(entry)
            # dashboards (dict) — для совместимости
            dashboards = data.setdefault("dashboards", {})
            dashboards["dashboard_akvilon"] = {
                "mode": "storage", "title": "Аквилон", "icon": "mdi:video-wireless",
            }
            json.dump(reg, open(reg_path, "w"), ensure_ascii=False)
            _LOGGER.info("Аквилон: дашборд зарегистрирован в lovelace_dashboards")
        except Exception as exc:  # pragma: no cover
            _LOGGER.warning("Аквилон: не удалось зарегистрировать дашборд: %s", exc)


def remove_dashboard(hass: HomeAssistant):
    """Удаляет дашборд «Аквилон» при удалении интеграции."""
    try:
        dash_path = _storage_path()
        if os.path.exists(dash_path):
            os.remove(dash_path)
            _LOGGER.info("Аквилон: удалён дашборд-файл %s", DASH_KEY)
    except Exception as exc:  # pragma: no cover
        _LOGGER.warning("Аквилон: не удалось удалить дашборд-файл: %s", exc)
    try:
        reg_path = os.path.join(STORAGE_DIR, "lovelace_dashboards")
        if not os.path.exists(reg_path):
            return
        reg = json.load(open(reg_path))
        data = reg.get("data", {})
        dashboards = data.get("dashboards", {})
        if "dashboard_akvilon" in dashboards:
            del dashboards["dashboard_akvilon"]
        items = data.get("items", [])
        items[:] = [x for x in items if x.get("id") != "dashboard_akvilon"]
        json.dump(reg, open(reg_path, "w"), ensure_ascii=False)
        _LOGGER.info("Аквилон: дашборд удалён из реестра lovelace_dashboards")
    except Exception as exc:  # pragma: no cover
        _LOGGER.warning("Аквилон: не удалось удалить регистрацию дашборда: %s", exc)
