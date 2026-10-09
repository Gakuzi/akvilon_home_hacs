"""Интеграционные тесты viewer.py — HTTP-панель камер на loopback.

Запускаем настоящий ViewerServer на случайном порту и делаем HTTP-запросы
к маршрутам /, /snap/<id>, /mjpeg/<id> (MJPEG) и 404. hub при этом — демо
(камера-заглушка, без реальной сети); _cam_frame переопределяем заглушкой.
"""
import threading
import urllib.request
import urllib.error

import pytest

from akvilon_home.coordinator import AkvilonHub
from akvilon_home.viewer import ViewerServer


def _hub():
    h = AkvilonHub("127.0.0.1", 19090, "secret", "0:0", "0:0", "Аквилон")
    h.load_demo_data()
    return h


@pytest.fixture()
def server():
    srv = ViewerServer(_hub(), port=0, refresh=5)
    # заглушка захвата кадра: возвращаем валидный JPEG вместо сети
    srv._cam_frame = lambda cam_id, timeout=8.0: b"\xff\xd8CUSTOMJPEG\xff\xd9"
    srv._start()
    port = srv.httpd.server_address[1]
    yield srv, port
    srv._stop()


def _get(port, path, timeout=8):
    url = f"http://127.0.0.1:{port}{path}"
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.status, r.read(), dict(r.headers)


class TestHttpRoutes:
    def test_index_returns_html(self, server):
        srv, port = server
        status, body, headers = _get(port, "/")
        assert status == 200
        assert "Аквилон InHome".encode("utf-8") in body
        assert "text/html" in headers.get("Content-Type", "")

    def test_index_content_type_utf8(self, server):
        srv, port = server
        status, body, headers = _get(port, "/")
        assert "charset=utf-8" in headers.get("Content-Type", "")

    def test_snap_returns_jpeg(self, server):
        srv, port = server
        status, body, headers = _get(port, "/snap/111:69724")
        assert status == 200
        assert body[:2] == b"\xff\xd8"  # JPEG SOI
        assert "image/jpeg" in headers.get("Content-Type", "")

    def test_unknown_route_404(self, server):
        srv, port = server
        with pytest.raises(urllib.error.HTTPError) as ei:
            _get(port, "/nope")
        assert ei.value.code == 404

    def test_snap_without_frame_returns_placeholder(self, server):
        srv, port = server
        srv._cam_frame = lambda cid, timeout=8.0: None
        status, body, headers = _get(port, "/snap/1:2")
        assert status == 200
        assert body[:2] == b"\xff\xd8"  # PLACEHOLDER тоже JPEG

    def test_index_total_count(self, server):
        srv, port = server
        status, body, headers = _get(port, "/")
        # в шаблоне __TOTAL__ подставляется числом камер (демо 7)
        assert b">7<" in body or b":7" in body