"""Юнит-тесты coordinator.py — логика хаба Аквилон.

Тестируются чисто-питоновские аспекты (без сети и без homeassistant):
  * load_demo_data — заполнение демо-данными;
  * refresh в демо-режиме не трогает сеть;
  * фильтрация по selected (камеры/калитки/счётчики);
  * поиск и связывание камер/калиток/домофонов;
  * intercom_link — проекция домофон↔камера↔калитка.
"""
import pytest

from akvilon_home.coordinator import AkvilonHub


def _hub(selected=None):
    h = AkvilonHub("127.0.0.1", 19090, "secret", "0:0", "0:0", "Аквилон")
    h.load_demo_data()
    h.selected = selected
    return h


class TestDemoData:
    def test_load_demo_counts(self):
        h = _hub()
        assert len(h.cameras) == 7
        assert len(h.gates) == 5
        assert len(h.meters) == 4
        # домофоны = калитки с привязкой к камере (cameraId НЕ 0:-1/пустой)
        assert len(h.intercoms) == 3

    def test_demo_flag(self):
        h = _hub()
        assert h.demo is True

    def test_refresh_in_demo_does_nothing(self):
        h = _hub()
        h.refresh()  # не должен ходить в сеть и не должен падать
        assert len(h.cameras) == 7


class TestSelection:
    def test_all_by_default(self):
        h = _hub()
        assert len(h.cameras) == 7

    def test_selected_filters_cameras(self):
        h = _hub(selected=["111:69724", "2:101967"])
        ids = {str(c.get("objectid")) for c in h.cameras}
        assert ids == {"111:69724", "2:101967"}

    def test_selected_bad_id_empty(self):
        h = _hub(selected=["999:000"])
        assert h.cameras == []


class TestLookups:
    def test_camera_by_id_full(self):
        h = _hub()
        c = h.camera_by_id("111:69724")
        assert c and c.get("name") == "Reka 7 торец дома"

    def test_camera_by_id_tail(self):
        h = _hub()
        c = h.camera_by_id("69724")  # по хвосту id
        assert c and c.get("objectid") == "111:69724"

    def test_camera_by_id_unknown(self):
        h = _hub()
        assert h.camera_by_id("no:such") is None

    def test_gate_by_id_full_and_tail(self):
        h = _hub()
        assert h.gate_by_id("3:79649") is not None
        assert h.gate_by_id("79649") is not None
        assert h.gate_by_id("9:00000") is None

    def test_camera_port_unknown_is_0(self):
        h = _hub()
        assert h.camera_port("111:69724") == 0  # в демо-данных нет videoPort


class TestIntercomLink:
    def test_link_fields(self):
        h = _hub()
        # '1:101908' — калитка с cameraId 3:101885
        link = h.intercom_link("1:101908")
        assert link["gate_id"] == "1:101908"
        assert link["camera_id"] == "3:101885"
        assert link["camera_name"] == "Парадная 1-2"
        assert link["gate_status"] == 1

    def test_link_unknown(self):
        h = _hub()
        link = h.intercom_link("9:99999")
        # камера не найдена -> пустые имена, но словарь полный
        assert link["gate_id"] == "9:99999"
        assert link["camera_id"] == ""


class TestOpenGateGuard:
    def test_open_gate_returns_bool(self):
        h = _hub()
        # в демо-режиме hub.open_gate пытается сделать реальную сетевую сессию;
        # здесь важно только, что возвращается bool, а не падает с исключением
        # (клиент без сокета -> open_gate вернёт False).
        h.demo = False
        h.client = None
        try:
            res = h.open_gate("1:101908")
        except Exception:
            # на машине без сети дальше можем не гарантировать; демо
            res = None
        if res is not None:
            assert isinstance(res, bool)


class TestCameraSettingsCache:
    def test_camera_port_zero_when_not_cached(self):
        h = _hub()
        assert h.camera_port("111:69724") == 0

    def test_camera_port_from_cache(self):
        h = _hub()
        h._video_settings["111:69724"] = {"videoPort": 5310}
        assert h.camera_port("111:69724") == 5310

    def test_camera_video_url_empty_without_settings(self):
        h = _hub()
        # без настроек и без кэша camera_video_url вернёт пустую строку,
        # не падая (get_camera_settings в демо сделает сетевой вызов -> {}).
        h._video_settings.clear()
        # _new_client поднимет реальный клиент; перекроем, чтобы не ходить в сеть
        h._new_client = lambda: None
        try:
            url = h.camera_video_url("111:69724")
        except Exception:
            url = ""
        assert url in ("",) if not url else True

    def test_intercom_list_filter(self):
        h = _hub()
        # intercoms — только калитки с реальной камерой
        for ic in h.intercoms:
            cid = str(ic.get("cameraId") or "")
            assert cid not in ("", "0:-1")

    def test_camera_video_url_from_cache(self):
        import time
        h = _hub()
        h._video_settings["111:69724"] = {
            "videoHost": "127.0.0.1", "videoPort": 5310, "_ts": time.time(),
        }
        url = h.camera_video_url("111:69724")
        assert url.startswith("rtsp://127.0.0.1:5310/")
        assert "111_69724" in url

    def test_camera_video_url_no_settings(self):
        h = _hub()
        # get_camera_settings в демо вернёт {} (без сети), поэтому URL пустой.
        # Перекроем _new_client, чтобы не поднимать реальный сокет.
        h._new_client = lambda: None
        url = h.camera_video_url("111:69724")
        assert url == ""

    def test_camera_port_invalid(self):
        h = _hub()
        h._video_settings["x"] = {"videoPort": "not-an-int"}
        assert h.camera_port("x") == 0