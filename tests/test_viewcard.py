"""Юнит-тесты viewcard.py (интерактивные видеокарточки камер).

viewcard.py — чистый модуль построения интерактивной видеокарточки камеры из
штатных HA-карточек (без custom JS). Тестируется голым Python: фейковый
резолвер эмулирует entity_registry (по образцу test_dashboard.py).
"""
import pytest

from akvilon_home import viewcard


class FakeResolver:
    """Имитирует резолвер над заданным списком сущностей."""

    def __init__(self, entities):
        self.entities = set(entities)

    def find(self, prefix: str, substr: str = "") -> list:
        out = [e for e in self.entities
               if e.startswith(prefix)
               and (not substr or substr.lower() in e.lower())]
        return sorted(out)


FULL_ENTITIES = [
    "camera.kamera_1",
    "camera.kamera_3",
    "camera.kamera_4",
    "button.otkryt_kalitka_1",
    "button.otkryt_kalitka_4",
    "sensor.kalitka_1_sostoianie",
]

CAM_IDS = ["camera.kamera_1", "camera.kamera_3", "camera.kamera_4"]


def _all_cards(cards):
    """Рекурсивно собрать все dict-карточки (с ключом 'type')."""
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

    walk(cards)
    return out


def _named_cards_with_type(cards, card_type):
    return [c for c in _all_cards(cards) if c.get("type") == card_type]


class TestBuildCameraGrid:
    def test_empty_returns_empty_list(self):
        assert viewcard.build_camera_grid(FakeResolver([]), []) == []

    def test_no_cameras_returns_empty(self):
        # есть сущности, но камер нет — вид пустой, не падает
        r = FakeResolver(["button.otkryt_kalitka_1"])
        assert viewcard.build_camera_grid(r, []) == []

    def test_one_card_per_camera(self):
        r = FakeResolver(FULL_ENTITIES)
        cards = viewcard.build_camera_grid(r, CAM_IDS)
        assert len(cards) == 3
        for card in cards:
            assert card["type"] == "vertical-stack"

    def test_each_card_has_live_picture_entity(self, monkeypatch):
        r = FakeResolver(FULL_ENTITIES)
        cards = viewcard.build_camera_grid(r, CAM_IDS)
        picture = _named_cards_with_type(cards, "picture-entity")
        cam_entities = [c["entity"] for c in picture]
        assert "camera.kamera_1" in cam_entities
        assert "camera.kamera_4" in cam_entities
        # все picture-entity — живой просмотр
        for c in picture:
            assert c.get("camera_view") == "live"
            assert c.get("tap_action", {}).get("action") == "more-info"

    def test_activity_label_present(self):
        r = FakeResolver(FULL_ENTITIES)
        cards = viewcard.build_camera_grid(r, CAM_IDS)
        md = _named_cards_with_type(cards, "markdown")
        assert md, "нет markdown-подписи активности"
        assert any("трансляц" in m.get("content", "") for m in md)

    def test_gate_bound_camera_gets_open_button(self):
        r = FakeResolver(FULL_ENTITIES)
        # kamera_1 -> otkryt_kalitka_1; kamera_4 -> otkryt_kalitka_4; kamera_3 -> нет
        expected = {
            "camera.kamera_1": "button.otkryt_kalitka_1",
            "camera.kamera_3": None,
            "camera.kamera_4": "button.otkryt_kalitka_4",
        }
        for cam, btn in expected.items():
            cards = viewcard.build_camera_grid(r, [cam])
            buttons = _named_cards_with_type(cards, "button")
            if btn:
                assert any(b.get("entity") == btn for b in buttons), f"{cam} → {btn}"
            else:
                assert buttons == [], f"{cam} не должен иметь кнопку открытия"

    def test_no_gate_buttons_skips_open(self):
        r = FakeResolver(["camera.kamera_1"])
        cards = viewcard.build_camera_grid(r, ["camera.kamera_1"])
        buttons = _named_cards_with_type(cards, "button")
        assert buttons == []

    def test_gate_status_rendered_when_bound(self):
        r = FakeResolver(FULL_ENTITIES)
        # sensor.kalitka_1_sostoianie привязан к kamera_1 (ядро "1")
        cards1 = viewcard.build_camera_grid(r, ["camera.kamera_1"])
        tiles1 = _named_cards_with_type(cards1, "tile")
        assert any(t.get("entity") == "sensor.kalitka_1_sostoianie" for t in tiles1)
        # kamera_4 к этому сенсору не привязана
        cards4 = viewcard.build_camera_grid(r, ["camera.kamera_4"])
        tiles4 = _named_cards_with_type(cards4, "tile")
        assert all(t.get("entity") != "sensor.kalitka_1_sostoianie"
                   for t in tiles4)


class TestHelpers:
    def test_cam_core(self):
        assert viewcard._cam_core("camera.kamera_1") == "1"
        assert viewcard._cam_core("camera.kamera_dvor_2") == "dvor_2"
        # нестандартный id без префикса camera.kamera_
        assert viewcard._cam_core("camera.some_other_5") == "some_other_5"

    def test_friendly_name(self):
        assert viewcard._friendly("camera.kamera_dvor_2") == "Dvor 2"
        assert viewcard.camera_friendly("camera.kamera_1") == "1"

    def test_match(self):
        assert viewcard._match(
            ["button.otkryt_kalitka_1", "button.otkryt_kalitka_4"],
            "button.otkryt_kalitka", "4") == "button.otkryt_kalitka_4"
        assert viewcard._match(
            ["button.otkryt_kalitka_1"], "button.otkryt_kalitka", "9") == ""