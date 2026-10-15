"""Юнит-тесты intercomcard.py (построение интерком-карточки калитки/домофона).

Модуль чистый (не импортирует HA-платформы), поэтому тестируется голым Python.
Проверяем, что карточка:
  * строится только из штатных HA-карточек (vertical-stack/picture-entity/
    tile/entities), без custom:;
  * включает живое видео камеры (camera_view: live), когда камера найдена;
  * включает крупную кнопку «Открыть» (tile + tap_action button.press);
  * включает сенсор статуса, когда он есть;
  * не падает и не выдумывает сущности при отсутствии камеры/статуса/кнопки.
"""
import pytest

from akvilon_home import intercomcard as ic


def _all_cards(card):
    """Рекурсивно собрать все dict-карточки (с ключом "type") из структуры."""
    out = []

    def walk(node):
        if isinstance(node, dict):
            if "type" in node:
                out.append(node)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(card)
    return out


class TestBuildIntercomCard:
    def test_full_card_structure(self):
        card = ic.build_intercom_card(
            "Калитка 1", "button.otkryt_kalitka_1",
            status="sensor.kalitka_1_sostoianie", cam="camera.kamera_1",
        )
        assert card["type"] == "vertical-stack"
        types = [c.get("type") for c in card["cards"]]
        assert "picture-entity" in types
        assert "tile" in types
        assert "entities" in types

    def test_only_standard_cards(self):
        card = ic.build_intercom_card(
            "Калитка 1", "button.otkryt_kalitka_1", status="sensor.kalitka_1_sostoianie",
            cam="camera.kamera_1",
        )
        for c in _all_cards(card):
            assert not c["type"].startswith("custom:"), f"custom-карточка: {c['type']}"

    def test_live_camera_view(self):
        card = ic.build_intercom_card(
            "Домофон 2", "button.otkryt_domofon_2", cam="camera.kamera_2",
        )
        pics = [c for c in _all_cards(card) if c.get("type") == "picture-entity"]
        assert any(p.get("entity") == "camera.kamera_2"
                   and p.get("camera_view") == "live" for p in pics)

    def test_open_tile_calls_button_press(self):
        card = ic.build_intercom_card("Калитка 3", "button.otkryt_kalitka_3")
        tiles = [c for c in _all_cards(card) if c.get("type") == "tile"]
        assert len(tiles) == 1
        t = tiles[0]
        assert t["entity"] == "button.otkryt_kalitka_3"
        ta = t.get("tap_action", {})
        assert ta["action"] == "perform-action"
        assert ta["perform_action"] == "button.press"
        assert ta["target"]["entity_id"] == "button.otkryt_kalitka_3"

    def test_status_shown_when_present(self):
        card = ic.build_intercom_card(
            "Калитка 1", "button.otkryt_kalitka_1",
            status="sensor.kalitka_1_sostoianie",
        )
        entities = [c for c in _all_cards(card) if c.get("type") == "entities"]
        assert any("sensor.kalitka_1_sostoianie" in str(e.get("entity", ""))
                   for card_ in entities for e in card_.get("entities", []))

    def test_no_camera_no_status_is_safe(self):
        card = ic.build_intercom_card("Калитка 1", "button.otkryt_kalitka_1")
        types = [c.get("type") for c in card["cards"]]
        assert "tile" in types
        assert "picture-entity" not in types
        assert "entities" not in types

    def test_empty_button_returns_empty(self):
        assert ic.build_intercom_card("Калитка 1", "") == {}

    def test_open_button_custom_label_and_icon(self):
        card = ic.build_intercom_card(
            "Домофон 2", "button.otkryt_domofon_2",
            open_name="Открыть", open_icon="mdi:door-bell",
        )
        tiles = [c for c in _all_cards(card) if c.get("type") == "tile"]
        t = tiles[0]
        assert t["name"] == "Открыть"
        assert t["icon"] == "mdi:door-bell"

    def test_kiosk_mode_makes_button_vertical(self):
        compact = ic.build_intercom_card("К", "button.otkryt_kalitka_1")
        tall = ic.build_intercom_card("К", "button.otkryt_kalitka_1", kiosk=True)
        c_tile = next(c for c in compact["cards"] if c.get("type") == "tile")
        t_tile = next(c for c in tall["cards"] if c.get("type") == "tile")
        assert c_tile["vertical"] is False
        assert t_tile["vertical"] is True


class TestIntercomCardContract:
    """Проверка контактной функции `intercom_card`, которую ждёт dashboard.py."""

    def test_contract_function_present(self):
        assert callable(getattr(ic, "intercom_card", None))

    def test_contract_delegates_to_builder(self):
        card = ic.intercom_card(
            "Калитка 1", "button.otkryt_kalitka_1",
            "sensor.kalitka_1_sostoianie", "camera.kamera_1",
            "Открыть", "mdi:door-open",
        )
        # То же самое, что и build_intercom_card (без kiosk).
        expected = ic.build_intercom_card(
            "Калитка 1", "button.otkryt_kalitka_1",
            "sensor.kalitka_1_sostoianie", "camera.kamera_1",
            "Открыть", "mdi:door-open",
        )
        assert card == expected
        types = [c.get("type") for c in card["cards"]]
        assert "picture-entity" in types and "tile" in types and "entities" in types

    def test_contract_empty_button_returns_empty(self):
        assert ic.intercom_card("Калитка 1", "") == {}