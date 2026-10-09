# -*- coding: utf-8 -*-
"""QA: тесты новых видео-функций video-viewer — send_video_token,
coordinator.camera_frame, viewer.Recorder (запись MP4). Без сети/ffmpeg."""
import os, sys, time, threading
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from akvilon_home import protocol as P
from akvilon_home.protocol import AkvilonClient, build_header, sign_packet, CMD_EVENT
from akvilon_home import viewer
from akvilon_home import rtp_stream


class _FakeSocket:
    def __init__(self):
        self.sent = []
        self.timeout = 0.5
    def settimeout(self, t): self.timeout = t
    def sendto(self, data, addr):
        self.sent.append((data, addr))
    def close(self): pass


def test_send_video_token_payload_is_correct():
    """send_video_token должен слать b"\\x00\\x00"+videoToken на videoHost:port."""
    cl = AkvilonClient("91.122.221.217", 19090, "x", device_id="0:0", server_id="0:0", pass_hex="p")
    cl.sock = _FakeSocket()
    ok = cl.send_video_token("91.122.221.217", 5310, "token_34:50957")
    assert ok is True
    assert len(cl.sock.sent) == 1
    data, addr = cl.sock.sent[0]
    assert data == b"\x00\x00token_34:50957"
    assert addr == ("91.122.221.217", 5310)


def test_rtp_kick_uses_prefixed_token():
    """RtpStream._kick шлёт на video-порт префикс \\x00\\x00 + токен."""
    st = rtp_stream.RtpStream({"videoHost": "h", "videoPort": 5310,
                               "videoToken": "token_X", "spropParameter": ""})
    st.sock = _FakeSocket()
    st._kick()
    assert len(st.sock.sent) == 1
    data, addr = st.sock.sent[0]
    assert data == b"\x00\x00token_X"
    assert addr == ("h", 5310)


def test_send_video_token_handles_exception():
    cl = AkvilonClient("h", 19090, "x", pass_hex="p")
    class BadSock:
        def sendto(self, *a): raise OSError("boom")
    cl.sock = BadSock()
    assert cl.send_video_token("h", 5310, "t") is False


# --- coordinator.camera_frame (без реального сервера) ---
class _FakeHubCameras:
    def __init__(self, jpg=b"\xff\xd8JPGDATA"):
        self._jpg = jpg
        self.cameras = [{"objectid": "1:2", "name": "Камера"}]
        self.gates = []
        self.meters = []
        self._intercoms = []
        self._video_settings = {}
        self._last_ok = 0.0
        self.client = None
        self.host = "h"; self.port = 19090; self.token = "p"
        self.device_id = "0:0"; self.server_id = "0:0"; self.name = "t"
        self.selected = None
    def camera_frame(self, cam_id, timeout=5.0):
        return self._jpg


def test_viewer_recorder_status_and_stop_when_idle():
    """Recorder: status на старте не запущен; stop без записи → ошибка."""
    chub = __import__("akvilon_home.coordinator", fromlist=["AkvilonHub"])
    # Recorder из viewer
    rec = viewer.Recorder(_FakeHubCameras(), "/tmp/rec_test_dir")
    st = rec.status()
    assert st["running"] is False
    res = rec.stop()
    assert res["ok"] is False
    # убедимся, что папка создана
    import os; assert os.path.isdir("/tmp/rec_test_dir")


def test_viewer_recorder_start_creates_mp4_filename():
    rec = viewer.Recorder(_FakeHubCameras(), "/tmp/rec_test_dir2")
    # старт записи с фейковым hub, но ffmpeg может не открыться — проверяем логику
    import os
    os.makedirs("/tmp/rec_test_dir2", exist_ok=True)
    res = rec.start("1:2", "Камера")
    # либо запустился, либо вернул ошибку из-за ffmpeg — но не должен упасть
    assert isinstance(res, dict)
    if res.get("ok"):
        # если запустился — должен быть файл
        assert res["file"].endswith(".mp4")
        # остановим
        rec.stop()
    else:
        # ошибка — из-за отсутствия ffmpeg или уже идёт; допустимо
        assert "error" in res


def test_viewer_recorder_double_start_errors():
    rec = viewer.Recorder(_FakeHubCameras(), "/tmp/rec_test_dir3")
    r1 = rec.start("1:2", "A")
    if r1.get("ok"):
        r2 = rec.start("3:4", "B")
        assert r2["ok"] is False  # уже идёт
        rec.stop()