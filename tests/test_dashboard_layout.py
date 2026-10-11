"""Юнит-тесты dashboard_layout.py и нейтральной интеграции в dashboard.py.

Сборщик Фичи D (перестройка панели «Аквилон»):
  * помощники раскладки (dashboard_layout) — чистые функции, тестируются голым
    Python: tile, tile_button (tap_action -> button.press), grid, section_view
    и т.д.;
  * нейтральная интеграция параллельных модулей (viewcard / intercomcard /
    ding) в dashboard.py: при отсутствии модуля/функции сборка панели не падает
    и фолбэчится на собственные карточки; при наличии — используется модуль.

Тесты используют фейковый резолвер (монкипатч dashboard._Resolver), как и
test_dashboard.py. Модули viewcard/intercomcard/ding физически присутствуют в
рабочем дереве (параллельные фичи), поэтому проверяется и реальный их вызов, и
фолбэк при «отсутствии» (monkeypatch _optional_fn -> None).
"""
import pytest

from akvilon_home import dashboard as dash
from akvilon_home import dashboard_layout as layout


# ---------------------------------------------------------------------------
# Фейковый резолвер
# ---------------------------------------------------------------------------
class FakeResolver:
    """Эмулирует _Resolver над заданным списком сущностей."""

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


def _all_cards(payload):
    """Рекурсивно собрать все dict-карточки (с ключом 'type')."""
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


def _view(payload, title):
    for v in payload["data"]["config"]["views"]:
        if v.get("title") == title:
            return v
    raise KeyError(title)


# ---------------------------------------------------------------------------
# Помощники раскладки (dashboard_layout)
# ---------------------------------------------------------------------------
class TestLayoutHelpers:
    def test_heading(self):
        assert layout.heading("Тест") == {
            "type": "heading", "heading": "Тест", "heading_style": "title"}
        assert layout.heading("Тест", style="subtitle")["heading_style"] == "subtitle"

    def test_tile_basic(self):
        cfg = layout.tile("button.otkryt_kalitka_1", "Открыть", icon="mdi:door")
        assert cfg["type"] == "tile"
        assert cfg["entity"] == "button.otkryt_kalitka_1"
        assert cfg["name"] == "Открыть"
        assert cfg["icon"] == "mdi:door"
        assert "tap_action" not in cfg

    def test_tile_action(self):
        cfg = layout.tile("b", "x", action={"action": "more-info"})
        assert cfg["tap_action"] == {"action": "more-info"}

    def test_tile_button_perform_action(self):
        cfg = layout.tile_button("button.otkryt_kalitka_2", "Открыть", "mdi:door")
        assert cfg["type"] == "tile"
        assert cfg["entity"] == "button.otkryt_kalitka_2"
        ta = cfg["tap_action"]
        assert ta["action"] == "perform-action"
        assert ta["perform_action"] == "button.press"
        assert ta["target"]["entity_id"] == "button.otkryt_kalitka_2"

    def test_picture_camera(self):
        cfg = layout.picture_camera("camera.kamera_1", "Камера 1")
        assert cfg["type"] == "picture-entity"
        assert cfg["entity"] == "camera.kamera_1"
        assert cfg["camera_view"] == "live"

    def test_grid_full_and_columns(self):
        g_full = layout.grid([], full=True)
        assert g_full["type"] == "grid"
        assert g_full["grid_options"]["columns"] == "full"
        g_col = layout.grid([], columns="1/2")
        assert g_col["grid_options"]["columns"] == "1/2"
        g_auto = layout.grid([])
        assert "grid_options" not in g_auto

    def test_section_view_structure(self):
        v = layout.section_view("Калитки", "gates", "Калитки", [
            {"type": "tile", "entity": "x"},
        ])
        assert v["type"] == "sections"
        assert v["title"] == "Калитки"
        assert v["path"] == "gates"
        assert v["sections"][0]["type"] == "grid"

    def test_entities_card_and_stack(self):
        ec = layout.entities_card([{"entity": "x"}], title="T")
        assert ec["type"] == "entities"
        assert ec["title"] == "T"
        vs = layout.vertical_stack([ec], title="V")
        assert vs["type"] == "vertical-stack"
        assert vs["title"] == "V"


# ---------------------------------------------------------------------------
# Нейтральная интеграция: фолбэк при отсутствии модуля
# ---------------------------------------------------------------------------
class TestNeutralFallback:
    def test_optional_fn_missing(self, monkeypatch):
        # модуля, которого нет, функция не существует
        assert dash._optional_fn("nonexistent_module_xyz", "fn") is None

    def test_cameras_empty_hides_view(self, monkeypatch):
        # нет камер — вид «Камеры» не добавляется
        _use_resolver(monkeypatch, ["binary_sensor.akvilon_server_onlain"])
        payload = dash.build_dashboard_payload(None)
        titles = [v.get("title") for v in payload["data"]["config"]["views"]]
        assert dash.VIEW_CAMERAS not in titles

    def test_cameras_fallback_when_viewcard_missing(self, monkeypatch):
        # убираем модуль viewcard -> фолбэк на picture-entity сетку
        monkeypatch.setattr(dash, "_optional_fn", lambda m, f: None)
        _use_resolver(monkeypatch, ["camera.kamera_1"])
        payload = dash.build_dashboard_payload(None)
        cam_view = _view(payload, dash.VIEW_CAMERAS)
        pics = [c for c in _all_cards(cam_view)
                if c.get("type") == "picture-entity"]
        assert any(c.get("entity") == "camera.kamera_1" for c in pics)

    def test_gates_fallback_when_intercomcard_has_button_tap(self, monkeypatch):
        # убираем intercomcard -> фолбэк `_video_stack`, где кнопка — tile с
        # button.press, а статус лежит в entities-карточке.
        def _no_intercomcard(m, f):
            return None
        monkeypatch.setattr(dash, "_optional_fn", _no_intercomcard)
        entities = [
            "button.otkryt_kalitka_1",
            "sensor.kalitka_1_sostoianie",
        ]
        _use_resolver(monkeypatch, entities)
        payload = dash.build_dashboard_payload(None)
        gates_view = _view(payload, dash.VIEW_GATES)
        tiles = [c for c in _all_cards(gates_view) if c.get("type") == "tile"]
        assert any(
            t.get("entity") == "button.otkryt_kalitka_1"
            and t.get("tap_action", {}).get("action") == "perform-action"
            for t in tiles
        )
        entities_cards = [c for c in _all_cards(gates_view)
                          if c.get("type") == "entities"]
        assert any("sensor.kalitka_1_sostoianie" in str(e.get("entity", ""))
                   for card in entities_cards for e in card.get("entities", []))

    def test_uses_viewcard_when_present(self, monkeypatch):
        # модуль viewcard реально есть -> вид строится его карточками
        _use_resolver(monkeypatch, [
            "camera.kamera_1",
            "button.otkryt_kalitka_1",
        ])
        payload = dash.build_dashboard_payload(None)
        cam_view = _view(payload, dash.VIEW_CAMERAS)
        stacks = [c for c in _all_cards(cam_view)
                  if c.get("type") == "vertical-stack"]
        assert stacks, "viewcard должен дать vertical-stack видеокарточки"

    def test_uses_intercomcard_when_present(self, monkeypatch):
        # модуль intercomcard реально есть -> tile с perform-action в калитках
        _use_resolver(monkeypatch, [
            "button.otkryt_kalitka_1",
            "sensor.kalitka_1_sostoianie",
        ])
        payload = dash.build_dashboard_payload(None)
        gates_view = _view(payload, dash.VIEW_GATES)
        tiles = [c for c in _all_cards(gates_view) if c.get("type") == "tile"]
        assert any(
            t.get("entity") == "button.otkryt_kalitka_1"
            and t.get("tap_action", {}).get("action") == "perform-action"
            for t in tiles
        )

    def test_no_custom_cards(self, monkeypatch):
        _use_resolver(monkeypatch, [
            "camera.kamera_1", "button.otkryt_kalitka_1",
        ])
        payload = dash.build_dashboard_payload(None)
        for card in _all_cards(payload):
            assert not str(card.get("type", "")).startswith("custom:")

    def test_ding_hint_none_when_no_module(self, monkeypatch):
        monkeypatch.setattr(dash, "_optional_fn",
                            lambda m, f: None)
        assert dash._ding_hint(None, None) is None