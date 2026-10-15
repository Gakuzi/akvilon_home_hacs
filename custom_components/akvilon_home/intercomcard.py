"""Построение интерком-карточки калитки/домофона из штатных HA-карточек.

Задача: на одном экране собрать полноценный «интерком» для калитки/домофона:
  * живое видео привязанной камеры (picture-entity, camera_view: live);
  * КРУПНУЮ кнопку «Открыть» (tile с tap_action → button.press на button.otkryt_*);
  * сенсор статуса (sensor.kalitka_* / sensor.domofon_*, если найден).

Используются ТОЛЬКО штатные карточки Home Assistant (vertical-stack,
picture-entity, tile, entities), без зависимостей от custom JS, поэтому карточка
работает в любом браузере и в киоск-режиме планшета. Если нужные сущности не
найдены (нет камеры/статуса) — соответствующие блоки просто пропускаются, и
карточка не падает.

Модуль намеренно чистый (без импорта HA-платформ): возвращает только структуру
Lovelace-конфига, чтобы её можно было юнит-тестировать голым Python.
"""


def _picture_entity(cam: str, title: str) -> dict:
    """Живое видео привязанной камеры.

    picture-entity с camera_view=live игнорирует tap_action (это штатное
    ограничение HA), поэтому для полноэкранного просмотра можно дополнительно
    использовать tile-кнопку — но здесь видео служит фоном/окном для киоска.
    """
    card = {
        "type": "picture-entity",
        "entity": cam,
        "camera_view": "live",
        "show_state": False,
        "show_name": True,
        "name": title,
        "tap_action": {"action": "more-info"},
    }
    return card


def _open_tile(btn: str, name: str, icon: str, vertical: bool) -> dict:
    """Крупная кнопка открытия калитки/домофона.

    tile-карточка привязывает кнопку button.otkryt_* и явно задаёт
    tap_action → button.press (то же действие, что и нажатие сущности; указано
    явно по требованию интерком-карточки). vertical=True делает кнопку высокой —
    удобно для планшета/киоска.
    """
    return {
        "type": "tile",
        "entity": btn,
        "name": name,
        "icon": icon,
        "vertical": vertical,
        "tap_action": {
            "action": "perform-action",
            "perform_action": "button.press",
            "target": {"entity_id": btn},
        },
    }


def _status_entities(status: str, title: str) -> dict:
    """Строка со статусом калитки (сенсор состояния)."""
    return {
        "type": "entities",
        "title": title,
        "entities": [
            {"entity": status, "name": "Статус", "icon": "mdi:lock-open-variant"}
        ],
        "state_color": True,
    }


def build_intercom_card(
    title: str,
    btn: str,
    status: str = "",
    cam: str = "",
    open_name: str = "Открыть",
    open_icon: str = "mdi:door-open",
    kiosk: bool = False,
) -> dict:
    """Строит компактную интерком-карточку калитки/домофона.

    Аргументы:
      title       — заголовок (например «Калитка 1»).
      btn         — entity_id кнопки открытия (button.otkryt_kalitka_* /
                    button.otkryt_domofon_*). Обязателен.
      status      — entity_id сенсора статуса (sensor.kalitka_* / sensor.domofon_*),
                    может быть пустым.
      cam         — entity_id привязанной камеры (camera.kamera_*), может быть
                    пустым.
      open_name   — подпись на кнопке открытия.
      open_icon   — иконка кнопки открытия.
      kiosk       — True: сделать кнопку высокой (vertical) для планшета/киоска.

    Возвращает dict стандартной HA-карточки vertical-stack. Если btn пуст —
    вернёт {}, чтобы вид мог безопасно пропустить карточку.
    """
    if not btn:
        return {}
    cards = []
    if cam:
        cards.append(_picture_entity(cam, title))
    cards.append(_open_tile(btn, open_name, open_icon, vertical=kiosk))
    if status:
        cards.append(_status_entities(status, title))
    return {"type": "vertical-stack", "cards": cards}


def intercom_card(
    title: str,
    btn: str,
    status: str = "",
    cam: str = "",
    open_name: str = "Открыть",
    open_icon: str = "mdi:door-open",
) -> dict:
    """Контактная функция интерком-карточки для сборщика dashboard.py.

    dashboard.py (коллектор параллельных фич) вызывает опциональный модуль
    `intercomcard` именно по этому имени и сигнатуре:
      intercom_card(title, btn, status, cam, open_name, open_icon)

    Внутри просто делегирует полноценному построителю build_intercom_card
    (компактный вид; kiosk=False). Если btn пуст — возвращает {} и вид не
    ломается.
    """
    return build_intercom_card(
        title, btn, status, cam,
        open_name=open_name, open_icon=open_icon,
    )