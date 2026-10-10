"""Юнит-тесты dashboard.py (build_dashboard_payload).

Панель строится ТОЛЬКО штатными HA-карточками и возвращает структуру Lovelace
без custom JS-карточек. Тесты используют фейковый резолвер (монкипатч
dashboard._Resolver), чтобы эмулировать entity_registry без домашнего Assistant.

Сборка идёт голым Python: conftest.py ставит заглушку пакета homeassistant.
"""
import pytest

from akvilon_home import dashboard as dash


# ---------------------------------------------------------------------------
# Фейковый резолвер
# ---------------------------------------------------------------------------
class FakeResolver:
    """Имитирует _Resolver над заданным списком сущностей."""

    def __init__(self, entities):
        self.entities = set(entities)

    def find(self, prefix: str, substr: str = "") -> list:
        out = [e for e in self.entities
               if e.startswith(prefix)
               and (not substr or substr.lower() in e.lower())]
        return sorted(out)

    def resolve(self, base: str) -> str:
        if not base:
            return ""
        if base in self.entities:
            return base
        for suf in dash._AUTO_SUFFIX:
            if base + suf in self.entities:
                return base + suf
        return base


def _use_resolver(monkeypatch, entities):
    def _factory(hass=None):
        return FakeResolver(entities)
    monkeypatch.setattr(dash, "_Resolver", _factory)


FULL_ENTITIES = [
    "binary_sensor.akvilon_server_onlain",
    "camera.kamera_1",
    "camera.kamera_3",
    "camera.kamera_4",
    "camera.chuzhaia_kamera",
    "button.otkryt_kalitka_1",
    "button.otkryt_kalitka_3",
    "sensor.kalitka_1_sostoianie",
    "sensor.schetchik_elektrichestvo",
    "sensor.schetchik_elektrichestvo_den",
    "sensor.schetchik_elektrichestvo_noch",
    "sensor.schetchik_gvs",
    "sensor.schetchik_xvs",
    "sensor.schetchik_otoplenie",
    "button.otkryt_domofon_2",
    "sensor.domofon_2_sostoianie",
]


def _all_cards(payload):
    """Рекурсивно собрать все dict-карточки из payload."""
    cards = []

    def walk(node):
        if isinstance(node, dict):
            if "type" in node:
                cards.append(node)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(payload)
    return cards


def _view_titles(payload):
    return [v.get("title") for v in payload["data"]["config"]["views"]]


def _views(payload):
    return {v.get("title"): v for v in payload["data"]["config"]["views"]}


class TestBuildPayload:
    def test_all_views_present(self, monkeypatch):
        _use_resolver(monkeypatch, FULL_ENTITIES)
        payload = dash.build_dashboard_payload(None)
        assert payload["version"] == 1
        titles = _view_titles(payload)
        assert {dash.VIEW_OVERVIEW, dash.VIEW_CAMERAS, dash.VIEW_GATES,
                dash.VIEW_METERS, dash.VIEW_INTERCOM, dash.VIEW_KIOSK} <= set(titles)

    def test_only_our_cameras(self, monkeypatch):
        _use_resolver(monkeypatch, FULL_ENTITIES)
        payload = dash.build_dashboard_payload(None)
        cam_view = _views(payload)[dash.VIEW_CAMERAS]
        cam_entities = [c["entity"] for c in _all_cards(cam_view)
                        if c.get("type") == "picture-entity"]
        assert "camera.kamera_1" in cam_entities
        assert "camera.chuzhaia_kamera" not in cam_entities

    def test_no_custom_js_cards(self, monkeypatch):
        _use_resolver(monkeypatch, FULL_ENTITIES)
        payload = dash.build_dashboard_payload(None)
        for card in _all_cards(payload):
            card_type = card.get("type", "")
            assert not card_type.startswith("custom:"), f"найден custom: {card_type}"

    def test_kiosk_has_gate_buttons(self, monkeypatch):
        _use_resolver(monkeypatch, FULL_ENTITIES)
        payload = dash.build_dashboard_payload(None)
        kiosk = _views(payload)[dash.VIEW_KIOSK]
        tiles = [c for c in _all_cards(kiosk) if c.get("type") == "tile"]
        assert tiles
        for t in tiles:
            assert t["entity"].startswith("button.otkryt_kalitka")

    def test_meters_include_tariffs(self, monkeypatch):
        _use_resolver(monkeypatch, FULL_ENTITIES)
        payload = dash.build_dashboard_payload(None)
        meters_view = _views(payload)[dash.VIEW_METERS]
        tiles = [c.get("entity") for c in _all_cards(meters_view)
                 if c.get("type") == "tile"]
        assert "sensor.schetchik_elektrichestvo_den" in tiles
        assert "sensor.schetchik_elektrichestvo_noch" in tiles
        assert "sensor.schetchik_gvs" in tiles

    def test_gate_view_has_button_and_status(self, monkeypatch):
        _use_resolver(monkeypatch, FULL_ENTITIES)
        payload = dash.build_dashboard_payload(None)
        gates_view = _views(payload)[dash.VIEW_GATES]
        entities = [c for c in _all_cards(gates_view) if c.get("type") == "entities"]
        # хотя бы в одной entities-карточке есть кнопка и статус
        assert any("button.otkryt_kalitka_1" in str(e.get("entity", ""))
                   for card in entities for e in card.get("entities", []))
        assert any("sensor.kalitka_1_sostoianie" in str(e.get("entity", ""))
                   for card in entities for e in card.get("entities", []))

    def test_no_intercom_hides_view(self, monkeypatch):
        no_intercom = [e for e in FULL_ENTITIES
                       if not (e.startswith("button.otkryt_domofon")
                               or e.startswith("sensor.domofon"))]
        _use_resolver(monkeypatch, no_intercom)
        payload = dash.build_dashboard_payload(None)
        assert dash.VIEW_INTERCOM not in _view_titles(payload)

    def test_no_gates_hides_gates_and_kiosk(self, monkeypatch):
        no_gates = [e for e in FULL_ENTITIES
                    if not e.startswith("button.otkryt_kalitka")
                    and not e.startswith("sensor.kalitka")]
        _use_resolver(monkeypatch, no_gates)
        payload = dash.build_dashboard_payload(None)
        titles = _view_titles(payload)
        assert dash.VIEW_GATES not in titles
        assert dash.VIEW_KIOSK not in titles

    def test_empty_registry_only_overview(self, monkeypatch):
        _use_resolver(monkeypatch, [])
        payload = dash.build_dashboard_payload(None)
        assert _view_titles(payload) == [dash.VIEW_OVERVIEW]

    def test_resolve_with_suffix(self, monkeypatch):
        # сущность пересоздана -> суффикс _2, должен резолвиться
        _use_resolver(monkeypatch, ["binary_sensor.akvilon_server_onlain_2"])
        payload = dash.build_dashboard_payload(None)
        grid_cards = _all_cards(payload)
        assert any("server_onlain_2" in str(c.get("entity", "")) for c in grid_cards)


class TestEmptyDetection:
    def test_views_titles_parses(self):
        payload = {"data": {"config": {"views": [
            {"title": "Обзор"}, {"title": "Камеры"}]}}}
        assert dash._views_titles(payload) == {"Обзор", "Камеры"}

    def test_views_titles_handles_bad_payload(self):
        assert dash._views_titles({"nope": True}) == set()
        assert dash._views_titles(None) == set()