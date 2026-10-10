"""Юнит-тесты живого видеопотока (rtp_stream.LiveStream / StreamManager) и
camera.stream_source.

Покрываем без сети и без runtime Home Assistant:
  * живой цикл LiveStream.run — отдаёт свежие JPEG через on_frame и
    останавливается по stop-event;
  * генератор RtpStream._iter_frames — та же сборка кадра, что в grab_jpeg;
  * StreamManager — refcount (один источник на камеру), лимит одновременных
    сессий (eviction LRU), освобождение при снятии последнего зрителя;
  * camera.stream_source — MJPEG-URL живого окна либо None (graceful fallback).
"""
import asyncio
import threading

import akvilon_home.rtp_stream as rtp_stream
from akvilon_home.rtp_stream import RtpStream, parse_sprop, StreamManager, LiveStream


# ---------- helpers (повторы фабрик из test_rtp_stream.py) ----------

def _rtp(pt=96, ts=1000, marker=False, payload=b""):
    b = bytearray(12)
    b[0] = 0x80
    b[1] = (0x80 if marker else 0x00) | (pt & 0x7F)
    b[3] = 1
    b[4:8] = ts.to_bytes(4, "big")
    return bytes(b) + payload


def _nal(ntype, payload=b""):
    return bytes([(ntype & 0x1F)]) + payload


class _FakeSock:
    def __init__(self, datagrams):
        self.datagrams = list(datagrams)
        self.my_port = 50000

    def recvfrom(self, bufsize):
        if not self.datagrams:
            raise OSError("end")
        return self.datagrams.pop(0), ("cam", 0)

    def sendto(self, data, addr):
        pass

    def close(self):
        pass

    def bind(self, *a):
        pass

    def settimeout(self, t):
        pass

    def getsockname(self):
        return ("0.0.0.0", self.my_port)


def _stream_with(**kw):
    kw.setdefault("videoHost", "127.0.0.1")
    kw.setdefault("videoPort", 5010)
    kw.setdefault("videoToken", "tok")
    kw.setdefault("spropParameter", "")
    stream = RtpStream(kw)
    stream._bps = []
    return stream


# ---------- RtpStream._iter_frames ----------

class TestIterFrames:
    def test_yields_single_idr(self):
        stream = _stream_with()
        stream.sock = _FakeSock([_rtp(ts=1, payload=_nal(5, b"idr"))])
        frames = list(stream._iter_frames(timeout=1))
        assert len(frames) == 1
        picture, got_idr = frames[0]
        assert got_idr is True
        assert any((n[0] & 0x1F) == 5 for n in picture)

    def test_non_idr_not_flagged(self):
        stream = _stream_with()
        stream.sock = _FakeSock([_rtp(ts=1, payload=_nal(1, b"pf"))])
        frames = list(stream._iter_frames(timeout=1))
        assert frames and frames[0][1] is False

    def test_two_frames_split_by_ts(self):
        stream = _stream_with()
        stream.sock = _FakeSock([
            _rtp(ts=1, payload=_nal(5, b"a")),
            _rtp(ts=2, payload=_nal(1, b"b")),
        ])
        frames = list(stream._iter_frames(timeout=1))
        assert len(frames) == 2

    def test_stop_event_shortcuts(self):
        stream = _stream_with()
        # сокет бросает OSError сразу -> без stop это не завершится
        # только из-за исключения; проверим, что на stop генератор заканчивается
        stop = threading.Event()
        stream.sock = _FakeSock([])
        stop.set()
        frames = list(stream._iter_frames(timeout=10, stop=stop))
        assert frames == []

    def test_fu_a_assembles_into_frame(self):
        stream = _stream_with()
        nal = _nal(5, b"0123456789")
        fh = nal[0]
        data = nal[1:]
        hdr = 0x80 | 28
        stream.sock = _FakeSock([
            _rtp(ts=7, payload=bytes([hdr, (0x80 | (fh & 0x1F))]) + data[:3]),
            _rtp(ts=7, payload=bytes([hdr, (fh & 0x1F)]) + data[3:7]),
            _rtp(ts=7, payload=bytes([hdr, (0x40 | (fh & 0x1F))]) + data[7:]),
        ])
        frames = list(stream._iter_frames(timeout=1))
        assert len(frames) == 1
        picture, got_idr = frames[0]
        assert got_idr is True
        assert any(b"0123456789" in n for n in picture)


# ---------- LiveStream.run ----------

class TestLiveStreamRun:
    def test_emits_jpeg_and_stops(self):
        seen = []
        stop = threading.Event()

        class FakeStream:
            def bind(self, port):
                pass

            def _kick(self):
                pass

            def _iter_frames(self, timeout, stop=None):
                yield [_nal(5, b"idr")], True
                yield [_nal(5, b"idr2")], True

            def _feed_picture(self, picture):
                if picture:
                    return b"\xff\xd8" + picture[0][1:] + b"\xff\xd9"
                return None

            def close(self):
                pass

        def cb(jpg):
            seen.append(jpg)
            stop.set()

        saved = rtp_stream.RtpStream
        rtp_stream.RtpStream = lambda settings: FakeStream()
        try:
            LiveStream({}, retry_interval=1.0).run(on_frame=cb, total=5.0, stop=stop)
        finally:
            rtp_stream.RtpStream = saved

        assert seen, "on_frame должен быть вызван с JPEG"
        assert all(j[:2] == b"\xff\xd8" for j in seen)

    def test_respects_total_zero_exits(self):
        rtp_stream.RtpStream = _Noop
        _Noop.reset()
        try:
            LiveStream({}, retry_interval=0.0).run(on_frame=lambda jpg: None, total=0.0)
        finally:
            rtp_stream.RtpStream = RtpStream
        # total=0 -> выход сразу, без открытия сокета/цикла
        assert _Noop.count == 0

    def test_retries_reopen_when_stop_not_set(self):
        rtp_stream.RtpStream = _CountingStream
        _CountingStream.reset()
        stop = threading.Event()
        try:
            # total>0, stop не ставится -> цикл хотя бы раз открывает сессию
            LiveStream({}, retry_interval=0.0).run(on_frame=lambda jpg: None, total=0.05, stop=stop)
        finally:
            rtp_stream.RtpStream = RtpStream
        assert _CountingStream.count >= 1


class _Noop:
    count = 0

    def __init__(self, *a, **kw):
        type(self).count += 1

    def bind(self, *a):
        pass

    def _kick(self):
        pass

    def _iter_frames(self, timeout, stop=None):
        return iter(())

    def close(self):
        pass

    @classmethod
    def reset(cls):
        cls.count = 0


class _CountingStream(_Noop):
    count = 0

    @classmethod
    def reset(cls):
        cls.count = 0


# ---------- StreamManager: refcount + лимит сессий ----------

class _SafeManager(StreamManager):
    """Менеджер без реальных сетевых фоновых потоков (ручное управление кадрами)."""

    def _run_session(self, sess):  # noqa: D401
        pass


class TestStreamManager:
    def _manager(self, max_concurrent):
        return _SafeManager(max_concurrent=max_concurrent)

    def test_subscribe_returns_token_and_shares_source(self):
        m = self._manager(2)
        t1 = m.subscribe("111:69724", {"videoPort": 5010})
        t2 = m.subscribe("111:69724", {"videoPort": 5010})
        try:
            assert t1 != t2
            # камера шарится между зрителями: одна сессия на камеру
            assert len(m._sessions) == 1
            assert len(m._sessions["111:69724"].refs) == 2
            assert m.latest("111:69724") is None
        finally:
            m.unsubscribe("111:69724", t1)
            m.unsubscribe("111:69724", t2)
        assert m.active_count() == 0

    def test_unsubscribe_last_closes_session(self):
        m = self._manager(2)
        t = m.subscribe("2:101967", {"videoPort": 5020})
        assert m.active_count() == 1
        m._sessions["2:101967"].latest = b"\xff\xd8frame\xff\xd9"
        assert m.latest("2:101967") is not None
        m.unsubscribe("2:101967", t)
        assert m.active_count() == 0
        assert m.latest("2:101967") is None

    def test_max_concurrent_evicts_lru(self):
        m = self._manager(1)
        t1 = m.subscribe("111:69724", {"videoPort": 5010})
        assert m.active_count() == 1
        # 2-я камера выселяет первую (лимит == 1)
        t2 = m.subscribe("3:101885", {"videoPort": 5204})
        try:
            assert m.active_count() == 1
            assert "3:101885" in m._sessions
            assert "111:69724" not in m._sessions
            assert m.latest("111:69724") is None
        finally:
            m.unsubscribe("3:101885", t2)
            m.unsubscribe("111:69724", t1)  # не падает

    def test_close_all(self):
        m = self._manager(4)
        tokens = [m.subscribe(str(i), {"videoPort": 5000 + i}) for i in range(3)]
        assert m.active_count() == 3
        m.close()
        assert m.active_count() == 0
        for cam, t in zip(("0", "1", "2"), tokens):
            m.unsubscribe(cam, t)  # not raise

    def test_on_release_fires_on_last_unsubscribe(self):
        released = []
        m = StreamManager(max_concurrent=3, on_release=released.append)
        m._run_session = lambda sess: None  # без фоновых сетевых потоков
        t1 = m.subscribe("A", {"videoPort": 1})
        t2 = m.subscribe("A", {"videoPort": 1})
        m.unsubscribe("A", t1)
        assert released == []  # есть ещё зритель
        m.unsubscribe("A", t2)
        assert released == ["A"]  # последний зритель ушёл -> closeCamera

    def test_on_release_fires_on_eviction(self):
        released = []
        m = StreamManager(max_concurrent=1, on_release=released.append)
        m._run_session = lambda sess: None
        m.subscribe("A", {"videoPort": 1})
        m.subscribe("B", {"videoPort": 2})  # выселяет A
        assert released == ["A"]
        m.close()


# ---------- camera.stream_source ----------

class TestCameraStreamSource:
    def test_returns_mjpeg_url_when_viewer_running(self):
        from urllib.parse import quote

        import akvilon_home.viewer as viewer_mod

        cam = self._camera()
        viewer_mod._set_live_base("http://127.0.0.1:8091")
        try:
            url = asyncio.run(cam.stream_source())
            assert url.startswith("http://127.0.0.1:8091/mjpeg/")
            # cam_id содержит ':', который в пути корректно экранируется как %3A
            assert quote("111:69724", safe="") in url
        finally:
            viewer_mod._set_live_base(None)

    def test_returns_none_without_viewer(self):
        import akvilon_home.viewer as viewer_mod
        cam = self._camera()
        viewer_mod._set_live_base(None)
        assert asyncio.run(cam.stream_source()) is None

    def _camera(self):
        from akvilon_home.coordinator import AkvilonHub
        from akvilon_home.camera import AkvilonCamera

        hub = AkvilonHub("127.0.0.1", 19090, "secret", "0:0", "0:0", "Аквилон")
        hub.load_demo_data()
        return AkvilonCamera(None, hub, "111:69724", "Reka 7 торец дома")