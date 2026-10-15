"""Интерактивные видеокарточки камер для дашборда «Аквилон».

Строит вид «Камеры» ТОЛЬКО штатными карточками Home Assistant
(picture-entity / vertical-stack / markdown / button / tile), без зависимостей
от custom JS-карточек, поэтому панель работает в любом браузере и не ломается
после обновления HA.

Каждая камера представляется вертикальной видеокарточкой:

* ``picture-entity`` с ``camera_view: live`` — живая/обновляемая картинка;
  ``tap_action: {"action": "more-info"}`` открывает камеру в штатном большом
  диалоге HA (полноэкранный просмотр).
* markdown-подпись активности («живая трансляция») — видно, что камера активна;
* кнопка «Открыть», если камера привязана к калитке
  (``button.otkryt_kalitka_<core>``) — открытие калитки по кнопке рядом с видео.

Модуль не зависит от ``dashboard.py``: все помощники локальные, поэтому его
можно переиспользовать независимо (импортировать как ``from . import viewcard``).
Имена сущностей берутся только из реального entity_registry через резолвер
(никаких выдуманных сущностей не создаём).
"""
from typing import Any

# Иконка/подпись кнопки открытия калитки, привязанной к камере.
_OPEN_ICON = "mdi:door-open"
_OPEN_NAME = "Открыть"

# Префиксы для обратного сопоставления сущностей.
_CAM_PREFIX = "camera.kamera_"
_GATE_BTN_PREFIX = "button.otkryt_kalitka"
_GATE_STATE_PREFIX = "sensor.kalitka"


def _cam_core(cam: str) -> str:
    """Возвращает «ядро» камеры (часть entity_id после camera.kamera_)."""
    if _CAM_PREFIX in cam:
        return cam.split(_CAM_PREFIX)[-1]
    return cam.split(".")[-1]


def _friendly(cam: str) -> str:
    """Человекочитаемое имя камеры из entity_id."""
    name = _cam_core(cam).replace("_", " ").strip().title()
    return name or "Камера"


def _match(entities, prefix: str, core: str) -> str:
    """Возвращает первую сущность, привязанную к ядру камеры.

    Привязка определяется по остатку entity_id после префикса: совпадение с
    core как целиком (кнопки ``button.otkryt_kalitka_<core>``), так и как часть
    (сенсоры ``sensor.kalitka_<core>_sostoianie``) — соответствует подстроковой
    логике, уже принятой в dashboard.py.
    """
    for e in entities:
        body = e.split(prefix)[-1].lstrip("_")
        if body == core or core in body:
            return e
    return ""


def _camera_card(cam: str, gate_btns, gate_states) -> dict:
    """Одна интерактивная видеокарточка камеры (только штатные HA-карточки).

    Возвращает vertical-stack: живое видео (picture-entity), подпись
    активности (markdown) и, при привязке к калитке, кнопку «Открыть».
    """
    core = _cam_core(cam)
    name = _friendly(cam)
    open_btn = _match(gate_btns, _GATE_BTN_PREFIX, core)
    open_state = _match(gate_states, _GATE_STATE_PREFIX, core)

    cards = [
        # Видео: camera_view: live отдаёт поток (если viewer активен) либо
        # последний кадр; тап открывает большой диалог просмотра камеры.
        {
            "type": "picture-entity",
            "entity": cam,
            "camera_view": "live",
            "show_state": False,
            "show_name": True,
            "name": name,
            "tap_action": {"action": "more-info"},
        },
        # Подпись активности: явно видно, что камера показывает живое видео.
        {
            "type": "markdown",
            "content": "🟢 **живая трансляция** — нажмите для полного просмотра",
            "grid_options": {"columns": "full"},
        },
    ]

    # Интерактивы: кнопка «Открыть», если камера привязана к калитке.
    if open_btn:
        cards.append({
            "type": "button",
            "entity": open_btn,
            "name": _OPEN_NAME,
            "icon": _OPEN_ICON,
            "show_name": True,
        })
        if open_state:
            cards.append({
                "type": "tile",
                "entity": open_state,
                "name": "Статус калитки",
                "icon": "mdi:lock-open-variant",
                "vertical": False,
            })

    return {"type": "vertical-stack", "cards": cards}


def build_camera_grid(resolver, cam_ids) -> list:
    """Строит список штатных карточек вид «Камеры».

    Параметры:
      * resolver — резолвер сущностей (похож на dashboard._Resolver): нужны
        методы ``find(prefix)`` и ``resolve(base)``;
      * cam_ids  — список реальных entity_id камер (``camera.kamera_*``).

    Возвращает список карточек (по одной на камеру). Если камер нет —
    возвращает пустой список, и вид скрывается (дашборд не ломается).
    """
    if not cam_ids:
        return []
    try:
        gate_btns = resolver.find(_GATE_BTN_PREFIX)
    except Exception:
        gate_btns = []
    try:
        gate_states = resolver.find(_GATE_STATE_PREFIX)
    except Exception:
        gate_states = []
    return [_camera_card(cam, gate_btns, gate_states) for cam in cam_ids]


# Переиспользуемый помощник для обратной совместимости: имя камеры.
def camera_friendly(cam: str, resolver: Any = None) -> str:
    """Возвращает дружелюбное имя камеры (public-обёртка над _friendly)."""
    return _friendly(cam)