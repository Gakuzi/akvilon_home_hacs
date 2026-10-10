"""Автоматическое создание/удаление дашборда «Аквилон» в Home Assistant.

При setup интеграции регистрируется Lovelace-дашборд `akvilon` в сайдбаре,
при unload — удаляется. Дашборд строится АВТОМАТИЧЕСКИ из живых данных сервера
(камеры, калитки, домофоны, счётчики), поэтому новые устройства появляются сами.

Панель использует ТОЛЬКО штатные карточки Home Assistant
(vertical-stack / picture-entity / entities / grid / tile / markdown / heading),
без зависимостей от custom JS-карточек, поэтому работает в любом браузере и не
ломается после обновления HA. Виды повторяют функции приложения InHome:
Обзор / Камеры / Калитки / Счётчики / Домофон / Киоск. Пустые виды (например,
когда домофонов на сервере 0) скрываются.

Стиль карточек использует переменные активной темы Home Assistant, поэтому
смена темы автоматически перестраивает внешний вид.
"""
import json
import logging
import os
import time
from typing import Any

_LOGGER = logging.getLogger(__name__)

DASH_KEY = "lovelace.dashboard_akvilon"
STORAGE_DIR = "/config/.storage"

# Предупреждение: custom-карточка домофона больше НЕ используется панелью.
# Имя оставлено только для очистки ресурса, если он был установлен прежними
# версиями интеграции.
INTERCOM_CARD_RESOURCE = "local/akvilon/akvilon-intercom-card.js"

_AUTO_SUFFIX = ("_2", "_3", "_4")  # суффиксы пересозданных сущностей

# Названия видов панели (для скрытия пустых и для логики пересборки)
VIEW_OVERVIEW = "Обзор"
VIEW_CAMERAS = "Камеры"
VIEW_GATES = "Калитки"
VIEW_METERS = "Счётчики"
VIEW_INTERCOM = "Домофон"
VIEW_KIOSK = "Киоск"

# Виды, которые существуют только если найдены соответствующие сущности
# (используется для retry-пересборки при асинхронной регистрации сущностей).
_ENTITY_VIEWS = {VIEW_CAMERAS, VIEW_GATES, VIEW_METERS, VIEW_INTERCOM}


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


def _friendly(eid: str) -> str:
    """Человекочитаемое короткое имя из entity_id."""
    name = eid.split(".")[-1]
    for pfx in (
        "kamera_", "otkryt_kalitka_", "otkryt_domofon_",
        "otkryt_reka_", "schetchik_", "kalitka_", "domofon_",
    ):
        if name.startswith(pfx):
            name = name[len(pfx):]
            break
    return name.replace("_", " ").strip().title()


def _entity(entity: str, name: str = "", icon: str = "") -> dict:
    """Стандартная ссылка на сущность для entities-карточки."""
    cfg = {"entity": entity}
    if name:
        cfg["name"] = name
    if icon:
        cfg["icon"] = icon
    return cfg


def _picture_camera(cam: str, title: str) -> dict:
    return {
        "type": "picture-entity",
        "entity": cam,
        "camera_view": "live",
        "show_state": False,
        "show_name": True,
        "name": title,
    }


def _video_stack(title: str, btn: str, status: str, cam: str,
                 open_name: str, open_icon: str) -> dict:
    """vertical-stack (видео-панель): камера + кнопка + статус."""
    cards = []
    if cam:
        cards.append(_picture_camera(cam, title))
    items = [_entity(btn, open_name, open_icon)]
    if status:
        items.append(_entity(status, "Статус", "mdi:lock-open-variant"))
    cards.append({"type": "entities", "title": title,
                  "entities": items, "state_color": True})
    return {"type": "vertical-stack", "cards": cards}


def build_dashboard_payload(hass: Any = None, hub=None) -> dict:
    """Строит структуру Lovelace-дашборда на основе РЕАЛЬНОГО entity_registry.

    Возвращает dict вида {"version":1,"data":{"config":{"views":[...]}}}.
    Все entity_id берутся из фактической регистрации сущностей, поэтому
    карточки указывают на реально существующие устройства. Виды строятся
    ТОЛЬКО штатными карточками HA; пустые виды (нет сущностей) скрываются.
    """
    r = _Resolver(hass)

    online_entity = (
        r.resolve("binary_sensor.akvilon_server_onlain")
        or r.resolve("binary_sensor.server_zdaniia_onlain")
    )
    # Только НАШИ камеры (camera.kamera_*), а не чужие интеграции.
    cam_ids = [c for c in r.find("camera.kamera_")]
    # Кнопки калиток
    gate_btns = r.find("button.otkryt_kalitka")
    # Кнопки домофонов (включая подъездные проходы)
    dom_btns = r.find("button.otkryt_domofon") + r.find("button.otkryt_reka")
    # Сенсоры состояния калиток
    gate_state = r.find("sensor.kalitka")
    # Сенсоры домофонов
    dom_sensors = r.find("sensor.domofon")
    # Счётчики (включая тарифы День/Ночь)
    meters = r.find("sensor.schetchik")

    # --- Обзор: заголовок + статус сервера + краткая справка ---
    overview_cards = [
        {"type": "heading", "heading": "Аквилон InHome", "heading_style": "title"}
    ]
    if online_entity:
        overview_cards.append({
            "type": "grid", "grid_options": {"columns": "full"}, "cards": [
                {"type": "tile", "entity": online_entity, "name": "Сервер здания",
                 "icon": "mdi:server-network", "vertical": False},
            ],
        })
    summary = []
    if cam_ids:
        summary.append(f"▸ **Камеры** — {len(cam_ids)} камер")
    if gate_btns:
        summary.append(f"▸ **Калитки** — {len(gate_btns)} кнопок открытия")
    if meters:
        summary.append(f"▸ **Счётчики** — {len(meters)} показаний")
    if dom_btns:
        summary.append(f"▸ **Домофон** — {len(dom_btns)} панелей вызова")
    if summary:
        overview_cards.append({
            "type": "markdown",
            "content": "\n".join(summary),
            "grid_options": {"columns": "full"},
        })

    # --- Калитки: кнопка + статус (и камера, если найдена) ---
    gate_cards = []
    used_status = set()
    for btn in gate_btns:
        core = btn.split("button.otkryt_kalitka_")[-1]
        status = next((s for s in gate_state if core in s), "")
        cam = next((c for c in cam_ids if core in c), "")
        gate_cards.append(_video_stack(
            f"Калитка {core}", btn, status, cam,
            "Открыть", "mdi:door-open"))
        if status:
            used_status.add(status)
    # Калитки, у которых нет отдельной кнопки, но есть сенсор состояния
    for s in gate_state:
        if s not in used_status:
            gate_cards.append({"type": "entities",
                               "entities": [_entity(s, _friendly(s))],
                               "state_color": True})

    # --- Домофон: видео-панели (камера + кнопка + статус) ---
    dom_cards = []
    for btn in dom_btns:
        key = btn.split("button.otkryt_")[-1]
        core = key.replace("domofon_", "").replace("reka_", "")
        status = next((s for s in dom_sensors if core in s), "")
        cam = next((c for c in cam_ids if core in c), "")
        title = core.replace("_", " ").title() or "Домофон"
        dom_cards.append(_video_stack(
            title, btn, status, cam,
            "Открыть", "mdi:door-bell"))

    # --- Камеры ---
    cam_cards = [_picture_camera(c, _friendly(c)) for c in cam_ids]

    # --- Счётчики ---
    meter_cards = [{"type": "tile", "entity": m, "name": _friendly(m),
                    "icon": "mdi:counter"} for m in meters]

    # --- Киоск: крупные кнопки открытия калиток для планшета ---
    kiosk_cards = [{"type": "tile", "entity": btn, "name": f"Открыть {_friendly(btn)}",
                    "icon": "mdi:door-open", "vertical": False}
                   for btn in gate_btns]

    def _view(title: str, path: str, heading: str, cards: list) -> dict:
        return {
            "type": "sections", "title": title, "path": path,
            "sections": [{"type": "grid", "cards": [
                {"type": "heading", "heading": heading, "heading_style": "title"},
            ] + cards}],
        }

    views = [_view(VIEW_OVERVIEW, "overview", "Аквилон InHome", overview_cards)]

    # Пустые виды не добавляются.
    if cam_cards:
        views.append(_view(VIEW_CAMERAS, "cameras", "Камеры", cam_cards))
    if gate_cards:
        views.append(_view(VIEW_GATES, "gates", "Калитки", gate_cards))
    if meter_cards:
        views.append(_view(VIEW_METERS, "meters", "Счётчики", meter_cards))
    if dom_cards:
        views.append(_view(VIEW_INTERCOM, "intercom", "Домофон", dom_cards))
    if kiosk_cards:
        views.append(_view(VIEW_KIOSK, "kiosk", "Киоск", kiosk_cards))

    return {"version": 1, "minor_version": 1, "key": DASH_KEY,
            "data": {"config": {"views": views}}}


def _views_titles(payload: dict) -> set:
    """Множество заголовков видов внутри payload (для проверки пустоты)."""
    titles = set()
    try:
        for v in payload["data"]["config"]["views"]:
            t = v.get("title")
            if t:
                titles.add(t)
    except Exception:
        pass
    return titles


def ensure_dashboard(hass: Any = None, hub=None, retries: int = 3, delay: float = 2.0):
    """Создаёт и регистрирует дашборд «Аквилон».

    Сущности регистрируются в Home Assistant асинхронно, поэтому на первом
    вызове резолвер может не увидеть ни одной сущности (пустая панель из одного
    «Обзора»). Панель пересобирается с паузами (обычно в executor-потоке), пока
    не найдёт хотя бы один вид с сущностями. Если retries исчерпаны — оставляем
    последний результат (не блокируя загрузку HA).
    """
    payload = None
    for attempt in range(max(1, retries)):
        try:
            payload = build_dashboard_payload(hass, hub)
        except Exception as exc:  # pragma: no cover
            _LOGGER.warning("Аквилон: не удалось построить дашборд: %s", exc)
            return
        if _views_titles(payload) & _ENTITY_VIEWS:
            break
        if attempt < retries - 1:
            _LOGGER.info(
                "Аквилон: сущности ещё не зарегистрированы, повтор пересборки "
                "дашборда через %.1fс (попытка %d/%d)",
                delay, attempt + 2, retries,
            )
            time.sleep(delay)
    # Пишем файл дашборда
    try:
        os.makedirs(STORAGE_DIR, exist_ok=True)
        json.dump(payload, open(_storage_path(), "w"), ensure_ascii=False)
    except Exception as exc:  # pragma: no cover
        _LOGGER.warning("Аквилон: не удалось записать дашборд-файл: %s", exc)
    # Регистрируем в lovelace_dashboards
    _register_dashboard()


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