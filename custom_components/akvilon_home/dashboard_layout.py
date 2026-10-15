"""Переиспользуемые помощники раскладки панели «Аквилон».

Набор чистых функций, которые строят конфиги ТОЛЬКО штатных карточек Home
Assistant (`sections` / `grid` / `tile` / `picture-entity` / `entities` /
`heading` / `markdown` / `vertical-stack`). Никаких custom JS-карточек, поэтому
панель работает в любом браузере и после обновления HA.

Функции не зависят от Home Assistant: они принимают plain-data и возвращают
plain-dict, поэтому их можно тестировать голым Python и использовать повторно
как в `dashboard.py`, так и в отдельных «видовых» модулях (например, для
видеокарточек камер или интерком-карточек калиток/домофонов).
"""
from typing import Any


def heading(text: str, style: str = "title") -> dict:
    """Заголовок-карточка `heading` (стили: title / subtitle)."""
    return {"type": "heading", "heading": text, "heading_style": style}


def markdown(content: str) -> dict:
    """Карточка `markdown` с контентом во всю ширину."""
    return {"type": "markdown", "content": content, "grid_options": {"columns": "full"}}


def tile(entity: str, name: str = "", icon: str = "",
         vertical: bool = False,
         action: dict | None = None) -> dict:
    """Карточка `tile` с опциональным `tap_action`.

    `action` — готовый конфиг tap_action (например
    `{"action": "perform-action", "perform_action": "button.press",
      "target": {"entity_id": entity}}`). Если передан — приклеивается к карточке.
    """
    cfg: dict[str, Any] = {"type": "tile", "entity": entity,
                           "vertical": vertical}
    if name:
        cfg["name"] = name
    if icon:
        cfg["icon"] = icon
    if action:
        cfg["tap_action"] = action
    return cfg


def tile_button(entity: str, name: str, icon: str) -> dict:
    """Крупная tile-кнопка для киоск-режима.

    Через `tap_action: perform-action` вызывает сервис `button.press` для кнопки
    открытия калитки/домофона — это надёжнее, чем полагаться на tap по tile
    (для button-домена accepted, но perform-action явнее и работает на планшете).
    """
    return tile(
        entity=entity,
        name=name,
        icon=icon,
        vertical=False,
        action={
            "action": "perform-action",
            "perform_action": "button.press",
            "target": {"entity_id": entity},
        },
    )


def picture_camera(cam: str, title: str) -> dict:
    """Стандартная `picture-entity` видеокарточка камеры."""
    return {
        "type": "picture-entity",
        "entity": cam,
        "camera_view": "live",
        "show_state": False,
        "show_name": True,
        "name": title,
    }


def grid(cards: list, columns: str | None = None, full: bool = False) -> dict:
    """Обёртка `grid` с карточками.

    `columns` — значение grid_options.columns («full», «1/2», «1/3», число...).
    `full=True` даёт «full». Если ни то, ни другое не задано — сетка авто-разметки.
    """
    go = {}
    if full:
        go["columns"] = "full"
    elif columns:
        go["columns"] = columns
    cfg: dict[str, Any] = {"type": "grid", "cards": cards}
    if go:
        cfg["grid_options"] = go
    return cfg


def section_grid(cards: list, columns: str | None = None, full: bool = False) -> dict:
    """Секция `sections`-вида: один grid с карточками.

    Используется как строительный блок вида (`sections` → `sections` → `grid`).
    """
    grid_cards = cards if columns in (None, "") and not full else cards
    return {"type": "grid",
            "grid_options": ({"columns": columns} if columns and not full else
                             ({"columns": "full"} if full else {})),
            "cards": grid_cards}


def vertical_stack(cards: list, title: str = "") -> dict:
    """vertical-stack видеокарточки: камера + entities (кнопка/статус)."""
    cfg: dict[str, Any] = {"type": "vertical-stack", "cards": cards}
    if title:
        cfg["title"] = title
    return cfg


def entities_card(entities: list, title: str = "",
                  state_color: bool = True) -> dict:
    """Стандартная `entities`-карточка."""
    cfg: dict[str, Any] = {"type": "entities", "entities": entities,
                           "state_color": state_color}
    if title:
        cfg["title"] = title
    return cfg


def entity_ref(entity: str, name: str = "", icon: str = "") -> dict:
    """Описание сущности внутри entities-карточки."""
    cfg = {"entity": entity}
    if name:
        cfg["name"] = name
    if icon:
        cfg["icon"] = icon
    return cfg


def section_view(title: str, path: str, heading_text: str, cards: list,
                 columns: str | None = None) -> dict:
    """Полный `sections`-вид: заголовок + grid с карточками.

    Это замена прежнего компактного вида: вид оборачивается в sections-структуру
    с одним grid, а карточки ложатся сеткой (aut-flow). Пустые виды решает
    вызывающий код — эта функция просто строит структуру.
    """
    return {
        "type": "sections",
        "title": title,
        "path": path,
        "sections": [section_grid(cards, columns=columns)],
    }