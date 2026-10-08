"""Автоматическое создание/удаление дашборда «Аквилон» в Home Assistant.

При setup интеграции регистрируется Lovelace-дашборд `akvilon` в сайдбаре,
при unload — удаляется. Дашборд строится АВТОМАТИЧЕСКИ из живых данных сервера
(камеры, калитки, домофоны, счётчики), поэтому новые устройства появляются
сами. Также подключается custom-карточка видеодомофона (akvilon-intercom-card)
и вкладка «Киоск» для полноэкранного режима на ТВ.

Стиль карточек использует переменные активной темы Home Assistant, поэтому
смена темы автоматически перестраивает внешний вид.
"""
import json
import logging
import os
from typing import Any

_LOGGER = logging.getLogger(__name__)

DASH_KEY = "lovelace.dashboard_akvilon"
STORAGE_DIR = "/config/.storage"

# Имя файла custom-карточки (кладут в /config/www/ для extra_module_url)
INTERCOM_CARD_RESOURCE = "local/akvilon/akvilon-intercom-card.js"
WWW_RESOURCE = "/config/www/akvilon/akvilon-intercom-card.js"

KIOSCK_URL = "/akvilon?kiosk"

_AUTO_SUFFIX = ("_2", "_3", "_4")  # суффиксы пересозданных сущностей


def _strip_suffix(eid: str) -> str:
    for suf in _AUTO_SUFFIX:
        if eid.endswith(suf):
            return eid[: -len(suf)]
    return eid


class _Resolver:
    """Резолвит сущности по реальному entity_registry (надёжно).

    Собирает список фактических entity_id интеграции и позволяет:
      * find(prefix, substr=None) — все id, начинающиеся с префикса (и, если
        задан substr, содержащие его);
      * resolve(base) — точное попадание или с суффиксами _2/_3/_4.
    """

    def __init__(self, hass: Any | None):
        self._entities = set()
        if hass is not None:
            try:
                for eid in hass.states.async_all():
                    self._entities.add(eid.entity_id)
            except Exception:
                pass
            try:
                from homeassistant.helpers import entity_registry as er
                reg = er.async_get(hass)
                for entry in reg.entities.values():
                    if entry.entity_id:
                        self._entities.add(entry.entity_id)
            except Exception:
                pass

    def _norm(self, s: str) -> str:
        return "".join(c if c.isalnum() else "_" for c in (s or "").lower()).strip("_")

    def find(self, prefix: str, substr: str = "") -> list:
        """Все реальные id, чей префикс совпадает (и при необходимости подстрока)."""
        out = []
        for e in self._entities:
            if e.startswith(prefix) and (not substr or substr.lower() in e.lower()):
                out.append(e)
        out.sort()
        return out

    def resolve(self, base: str) -> str:
        """Возвращает существующий entity_id по точному имени или с суффиксом _N."""
        if not base:
            return ""
        if base in self._entities:
            return base
        for suf in _AUTO_SUFFIX:
            cand = base + suf
            if cand in self._entities:
                return cand
        return base


def _cam_entity(cam_id: str) -> str:
    return f"camera.kamera_{cam_id}"


def _gate_button_entity(name: str) -> str:
    # нормализуем имя для entity_id (нижний регистр, нижние подчёркивания)
    slug = "".join(c if c.isalnum() else "_" for c in (name or "").lower())
    slug = "_".join([p for p in slug.split("_") if p])
    return f"button.otkryt_{slug}"


def _slugify(name: str) -> str:
    slug = "".join(c if c.isalnum() else " " for c in (name or "").lower())
    return "_".join(slug.split())


def build_dashboard_payload(hass: Any = None, hub=None) -> dict:
    """Строит структуру Lovelace-дашборда на основе РЕАЛЬНОГО entity_registry.

    Возвращает dict вида {"version":1,"data":{"config":{"views":[...]}}}.
    Все entity_id берутся из фактической регистрации сущностей, поэтому
    карточки указывают на реально существующие устройства (камеры, калитки,
    домофоны, счётчики), а не на угаданные имена.
    """
    r = _Resolver(hass)

    online_entity = r.resolve("binary_sensor.akvilon_server_onlain") or r.resolve("binary_sensor.server_zdaniia_onlain")

    # Камеры — все camera.*
    cam_ids = r.find("camera.")
    # Кнопки калиток
    gate_btns = r.find("button.otkryt_kalitka")
    # Кнопки домофонов (включая подъездные проходы)
    dom_btns = r.find("button.otkryt_domofon") + r.find("button.otkryt_reka")
    # Сенсоры состояния калиток
    gate_state = r.find("sensor.kalitka")
    # Сенсоры домофонов
    dom_sensors = r.find("sensor.domofon")
    # Счётчики
    meters = r.find("sensor.schetchik")

    def intercom_card(title, btn, cam=None, status=None):
        return {
            "type": "custom:akvilon-intercom-card",
            "title": title,
            "gate_button": btn,
            "camera_entity": cam or "",
            "status_sensor": status or "",
            "show_fullscreen_button": True,
        }

    # --- Обзор ---
    overview_cards = [{"type": "heading", "heading": "Аквилон InHome", "heading_style": "title"}]
    if online_entity:
        overview_cards.append({
            "type": "grid", "grid_options": {"columns": "full"}, "cards": [
                {"type": "tile", "entity": online_entity, "name": "Сервер здания",
                 "icon": "mdi:server-network", "vertical": False},
            ]
        })
    overview_cards.append({"type": "markdown",
        "content": "▸ **Калитки** — карточки с камерой и кнопкой «Открыть»\n"
                   "▸ **Домофоны** — полноэкранный видеодомофон (Ответить/Открыть)\n"
                   "▸ **Камеры** — все камеры двора и подъездов\n"
                   "▸ **Счётчики** — ГВС, ХВС, отопление, электричество (День/Ночь)",
        "grid_options": {"columns": "full"}})

    # --- Калитки: карточка домофона (кнопка + статус + камера, если найдена) ---
    gate_cards = []
    used_status = set()
    for btn in gate_btns:
        core = btn.split("button.otkryt_kalitka_")[-1]
        status = next((s for s in gate_state if core in s), "")
        cam = next((c for c in cam_ids if core in c), "")
        gate_cards.append(intercom_card(f"Калитка {core}", btn, cam, status))
        if status:
            used_status.add(status)
    # Калитки, у которых нет отдельной кнопки, но есть сенсор состояния
    for s in gate_state:
        if s not in used_status:
            gate_cards.append({"type": "entities",
                               "entities": [{"entity": s, "name": s.split("_")[-1]}],
                               "state_color": True})

    # --- Домофоны (полноэкранные карточки) ---
    dom_cards = []
    for btn in dom_btns:
        key = btn.split("button.otkryt_")[-1]           # напр. domofon_kalitka_14
        status = next((s for s in dom_sensors if (key.replace("domofon_", "") in s)), "")
        cam = next((c for c in cam_ids if key.replace("domofon_", "") in c), "")
        title = key.replace("domofon_", "").replace("_", " ").title()
        dom_cards.append(intercom_card(title, btn, cam, status))

    # --- Камеры ---
    cam_cards = [{"type": "picture-entity", "entity": c, "camera_view": "live",
                  "show_state": False, "show_name": True, "name": c.split(".")[-1]}
                 for c in cam_ids]

    # --- Счётчики ---
    meter_cards = [{"type": "tile", "entity": m, "name": m.split(".")[-1],
                    "icon": "mdi:counter"} for m in meters]

    views = [
        {"type": "sections", "title": "Обзор", "path": "overview",
         "sections": [{"type": "grid", "cards": overview_cards}]},
        {"type": "sections", "title": "Калитки", "path": "gates",
         "sections": [{"type": "grid", "cards": [
             {"type": "heading", "heading": "Калитки", "heading_style": "title"},
         ] + (gate_cards or [{"type": "markdown", "content": "Калитки не найдены."}])}]},
        {"type": "sections", "title": "Домофоны", "path": "intercoms",
         "sections": [{"type": "grid", "cards": [
             {"type": "heading", "heading": "Домофоны", "heading_style": "title"},
         ] + (dom_cards or [{"type": "markdown", "content": "Домофоны не найдены."}])}]},
        {"type": "sections", "title": "Камеры", "path": "cameras",
         "sections": [{"type": "grid", "cards": [
             {"type": "heading", "heading": "Камеры", "heading_style": "title"},
         ] + cam_cards}]},
        {"type": "sections", "title": "Счётчики", "path": "meters",
         "sections": [{"type": "grid", "cards": [
             {"type": "heading", "heading": "Счётчики", "heading_style": "title"},
         ] + meter_cards}]},
        {"type": "sections", "title": "Киоск", "path": "kiosk",
         "sections": [{"type": "grid", "cards": [
             {"type": "markdown",
              "content": "**Киоск-режим для ТВ**\n\nПолноэкранный интерфейс для телевизора. Карточки калиток/домофонов открывают видеодомофон на весь экран.",
              "grid_options": {"columns": "full"}},
         ]}]},
    ]

    return {"version": 1, "minor_version": 1, "key": DASH_KEY,
            "data": {"config": {"views": views}}}


def ensure_dashboard(hass: Any = None, hub=None):
    """Создаёт и регистрирует дашборд «Аквилон» (пересобирает, если он устарел)."""
    try:
        payload = build_dashboard_payload(hass, hub)
    except Exception as exc:  # pragma: no cover
        _LOGGER.warning("Аквилон: не удалось построить дашборд: %s", exc)
        return
    # Пишем файл дашборда
    try:
        os.makedirs(STORAGE_DIR, exist_ok=True)
        json.dump(payload, open(_storage_path(), "w"), ensure_ascii=False)
    except Exception as exc:  # pragma: no cover
        _LOGGER.warning("Аквилон: не удалось записать дашборд-файл: %s", exc)
    # Регистрируем в lovelace_dashboards
    _register_dashboard()
    # Подключаем custom-карточку (копируем JS в /config/www/)
    _install_resource()


def _storage_path():
    return os.path.join(STORAGE_DIR, DASH_KEY)


def _register_dashboard():
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
            reg.setdefault("version", 1)
            reg.setdefault("minor_version", 1)
            reg.setdefault("key", "lovelace_dashboards")
            reg.setdefault("data", {})
        data = reg["data"]
        items = data.setdefault("items", [])
        entry = {
            "id": "dashboard_akvilon", "title": "Аквилон",
            "icon": "mdi:video-wireless", "url_path": "akvilon",
            "mode": "storage", "require_admin": False, "show_in_sidebar": True,
        }
        if not any(x.get("id") == "dashboard_akvilon" for x in items):
            items.append(entry)
        dashboards = data.setdefault("dashboards", {})
        dashboards["dashboard_akvilon"] = {
            "mode": "storage", "title": "Аквилон", "icon": "mdi:video-wireless",
        }
        json.dump(reg, open(reg_path, "w"), ensure_ascii=False)
        _LOGGER.info("Аквилон: дашборд зарегистрирован в lovelace_dashboards")
    except Exception as exc:  # pragma: no cover
        _LOGGER.warning("Аквилон: не удалось зарегистрировать дашборд: %s", exc)


def _install_resource():
    """Копирует custom-карточку домофона в /config/www/ и регистрирует resource."""
    # 1) файл JS
    try:
        os.makedirs(os.path.dirname(WWW_RESOURCE), exist_ok=True)
        js_path = os.path.join(os.path.dirname(__file__), "dashboard",
                               "akvilon-intercom-card.js")
        if not os.path.exists(js_path):
            # если интеграция не в custom_components, пробуем рядом
            js_path = os.path.join(os.path.dirname(__file__),
                                   "akvilon-intercom-card.js")
        if os.path.exists(js_path):
            with open(js_path, "r", encoding="utf-8") as f:
                content = f.read()
            with open(WWW_RESOURCE, "w", encoding="utf-8") as f:
                f.write(content)
            _LOGGER.info("Аквилон: custom-карточка установлена в /config/www/akvilon/")
    except Exception as exc:  # pragma: no cover
        _LOGGER.warning("Аквилон: не удалось установить JS-ресурс: %s", exc)

    # 2) регистрируем в lovelace_resources
    try:
        res_path = os.path.join(STORAGE_DIR, "lovelace_resources")
        res = {"version": 1, "minor_version": 1,
               "key": "lovelace_resources", "data": {"items": []}}
        if os.path.exists(res_path):
            try:
                res = json.load(open(res_path))
            except Exception:
                res = {"version": 1, "minor_version": 1,
                       "key": "lovelace_resources", "data": {"items": []}}
            res.setdefault("data", {}).setdefault("items", [])
        items = res["data"]["items"]
        if not any(i.get("url") == f"/{INTERCOM_CARD_RESOURCE}" for i in items):
            items.append({"type": "js", "url": f"/{INTERCOM_CARD_RESOURCE}"})
            json.dump(res, open(res_path, "w"), ensure_ascii=False)
            _LOGGER.info("Аквилон: JS-ресурс %s зарегистрирован", INTERCOM_CARD_RESOURCE)
    except Exception as exc:  # pragma: no cover
        _LOGGER.warning("Аквилон: не удалось зарегистрировать JS-ресурс: %s", exc)


def remove_dashboard(hass: Any = None):
    """Удаляет дашборд «Аквилон» и его ресурсы при удалении интеграции."""
    try:
        if os.path.exists(_storage_path()):
            os.remove(_storage_path())
    except Exception:  # pragma: no cover
        pass
    try:
        reg_path = os.path.join(STORAGE_DIR, "lovelace_dashboards")
        if os.path.exists(reg_path):
            reg = json.load(open(reg_path))
            data = reg.get("data", {})
            data.get("dashboards", {}).pop("dashboard_akvilon", None)
            items = data.get("items", [])
            items[:] = [x for x in items if x.get("id") != "dashboard_akvilon"]
            json.dump(reg, open(reg_path, "w"), ensure_ascii=False)
    except Exception:  # pragma: no cover
        pass
    try:
        res_path = os.path.join(STORAGE_DIR, "lovelace_resources")
        if os.path.exists(res_path):
            res = json.load(open(res_path))
            items = res.get("data", {}).get("items", [])
            res["data"]["items"] = [i for i in items if INTERCOM_CARD_RESOURCE not in (i.get("url") or "")]
            json.dump(res, open(res_path, "w"), ensure_ascii=False)
    except Exception:  # pragma: no cover
        pass