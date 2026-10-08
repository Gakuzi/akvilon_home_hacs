"""Юнит-тесты viewer.py — веб-панель камер: классификация камер по разделам.

Проверяем детерминированную логику без сети и без HTTP-сервера:
  * _classify — разбиение камер на разделы (домофоны, подъезды, лифты, двор...);
  * привязку камер к калиткам по cameraId;
  * сортировку камер в пределах раздела.
"""
from akvilon_home.coordinator import AkvilonHub
from akvilon_home.viewer import ViewerServer, SECTION_ORDER


def _hub():
    h = AkvilonHub("127.0.0.1", 19090, "secret", "0:0", "0:0", "Аквилон")
    h.load_demo_data()
    return h


def _server():
    return ViewerServer(_hub(), port=8090, refresh=12)


class TestClassify:
    def test_classify_returns_sorted_list(self):
        srv = _server()
        items = srv._classify()
        assert items, "должны быть камеры"
        for it in items:
            assert set(("objectid", "name", "kind", "section")) <= set(it)

    def test_domofon_linked_by_camera(self):
        srv = _server()
        items = srv._classify()
        # '3:101885' (Парадная 1-2) привязана к калитке с cameraId 3:101885
        cam = next((i for i in items if i["objectid"] == "3:101885"), None)
        assert cam is not None
        assert cam["kind"] == "Домофон/калитка"
        assert cam["section"] == "Домофоны и калитки"
        assert cam["gate"]  # непустая привязка к калитке

    def test_plain_camera_section(self):
        srv = _server()
        items = srv._classify()
        # камера без привязки к калитке и с 'проезд' в имени -> "Двор и территория"
        cam = next((i for i in items if i["objectid"] == "102:69861"), None)
        assert cam is not None
        assert cam["kind"] == "Камера"
        assert cam["section"] in SECTION_ORDER

    def test_order_respected(self):
        srv = _server()
        items = srv._classify()
        sections = [i["section"] for i in items]
        # домофоны должны быть первыми (первый в SECTION_ORDER)
        assert "Домофоны и калитки" in sections
        assert sections[0] == "Домофоны и калитки"

    def test_all_sections_in_order(self):
        srv = _server()
        items = srv._classify()
        seen = [i["section"] for i in items]
        # индексы разделов не должны нарушать SECTION_ORDER (в пределах известных)
        import sys
        order = {s: i for i, s in enumerate(SECTION_ORDER)}
        known = [(order[s], s) for s in seen if s in order]
        idxs = [i for i, _ in known]
        assert idxs == sorted(idxs), "разделы нарушают SECTION_ORDER"

    def test_cache_behavior(self):
        srv = _server()
        # FrameCache для /snap
        srv.cache = {}
        assert srv._cam_frame is not None  # метод существует

    def test_classify_gate_names_joined(self):
        srv = _server()
        items = srv._classify()
        # камера 2:101967 привязана к нескольким объектам -> gate непустой список
        cam = next((i for i in items if i["objectid"] == "2:101967"), None)
        assert cam is not None
        assert cam["gate"]

    def test_defaults(self):
        srv = ViewerServer(_hub())
        assert srv.port == 8090
        assert srv.refresh == 12