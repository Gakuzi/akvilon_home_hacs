"""Стресс-тесты стабильности UDP-ядра (SPEC-003): protocol + coordinator.

Покрывает: сбор всех тел по нескольким сессиям, устойчивость к одиночной
потере пакетов/ответов, ACK на каждый входящий пакет (и повтор при сбое),
keepalive-таймер подписки 0x200, а также не-падающий refresh координатора.
Голый Python, без homeassistant: сеть имитируется scripted-сокетом.
"""
import queue
import socket
import struct
import threading
import time

import pytest

from akvilon_home.coordinator import AkvilonHub
from akvilon_home import protocol as P
from akvilon_home.protocol import (
    AkvilonClient,
    HEADER_LEN,
    MD5_LEN,
    CMD_GET,
    CMD_DATA,
    FLAG_OK,
    CH_CAMERAS,
)


# ---------------------------------------------------------------------------
# Вспомогательный scripted-сокет: доставляет заголовок и тела в ответ на GET.
# recvfrom (читается фоновым ридером) выстраивает очередь по мере появления
# запросов, имитируя потерю ответа, если заголовок отдаётся не с первой попытки.
# ---------------------------------------------------------------------------
def _body_packet(channel, obj_id, name):
    hdr = bytearray(64)
    hdr[0x36] = CMD_GET
    hdr[0x37] = FLAG_OK
    struct.pack_into("<I", hdr, 0x38, channel)
    payload = ('{"objectid":"%s","name":"%s"}' % (obj_id, name)).encode("utf-8")
    return bytes(hdr) + payload + b"\x00" * MD5_LEN


def _header_packet(channel, count, records):
    hdr = bytearray(64)
    hdr[0x36] = CMD_GET
    hdr[0x37] = FLAG_OK
    struct.pack_into("<I", hdr, 0x38, channel)
    payload = struct.pack("<I", count)
    for oid, rflag in records:
        payload += b"\x00" * 4
        payload += struct.pack("<q", oid)
        payload += struct.pack("<I", rflag)
        payload += b"\x00" * 4
    return bytes(hdr) + payload + b"\x00" * MD5_LEN


class _ScriptedSock:
    """Сокет, отдающий заголовок GET-списка и JSON-тела по сценарию.

    header_delivery_after: сколько раз увидеть GET-ALL, прежде чем выдать
    заголовок (1 — норма, 2 — имитация потери первого ответа => retry у клиента).
    """

    def __init__(self, channel, count, records, bodies, header_delivery_after=1):
        # records: list[(oid:int, rflag:int)]
        # bodies: dict {oid_str: bytes}; только подмножество может быть доставлено
        self.channel = channel
        self.records = list(records)
        self.bodies = dict(bodies)
        self.count = count
        self.header_delivery_after = header_delivery_after
        self.sent = []
        self.timeout = None
        self.closed = False
        self._body_given = set()
        self._getall_seen = 0
        self._header_sent = False
        self._lock = threading.Lock()

    def settimeout(self, t):
        self.timeout = t

    def close(self):
        self.closed = True

    def _chan(self, data):
        try:
            return struct.unpack_from("<I", data, 0x38)[0]
        except Exception:
            return None

    def _is_getall(self, data):
        if len(data) < 64:
            return False
        if data[0x36] != CMD_GET or self._chan(data) != self.channel:
            return False
        pl = data[HEADER_LEN:len(data) - MD5_LEN]
        return len(pl) >= 1 and pl[0] == 1

    def _has_get2(self):
        """True, если клиент уже запросил хотя бы один type=2 GET (идёт сбор тел)."""
        for data, _ in self.sent:
            if len(data) < 64:
                continue
            if data[0x36] != CMD_GET or self._chan(data) != self.channel:
                continue
            pl = data[HEADER_LEN:len(data) - MD5_LEN]
            if len(pl) >= 1 and pl[0] == 2:
                return True
        return False

    def sendto(self, data, addr):
        self.sent.append((data, addr))
        if self._is_getall(data):
            with self._lock:
                self._getall_seen += 1

    def recvfrom(self, bufsize):
        deadline = time.monotonic() + 4.0
        while not self.closed and time.monotonic() < deadline:
            with self._lock:
                if not self._header_sent and self._getall_seen >= self.header_delivery_after:
                    self._header_sent = True
                    return self._build_header(), ("127.0.0.1", 19090)
                if self._header_sent and self._has_get2():
                    # отдаём ровно ОДИН ещё не выданный объект за вызов (порционно)
                    for key, body in self.bodies.items():
                        if key not in self._body_given:
                            self._body_given.add(key)
                            return body, ("127.0.0.1", 19090)
            time.sleep(0.005)
        raise socket.timeout()

    def _build_header(self):
        return _header_packet(self.channel, self.count, self.records)


def _make_client_top():
    return AkvilonClient("127.0.0.1", 19090, "x", device_id="0:0", server_id="0:0")


# ---------------------------------------------------------------------------
# get_list: сбор всех тел (несколько сессий накопления)
# ---------------------------------------------------------------------------
class TestGetListRobust:
    def _records_and_bodies(self, n, channel=CH_CAMERAS):
        records = [(1000 + i, 2) for i in range(n)]
        bodies = {"%d" % (1000 + i): _body_packet(channel, "%d" % (1000 + i), "cam%d" % i)
                  for i in range(n)}
        return records, bodies

    def test_single_session_full_collection(self):
        cl = _make_client_top()
        sock = _ScriptedSock(CH_CAMERAS, 3, [(1000, 2), (1001, 2), (1002, 2)],
                             {"1000": _body_packet(CH_CAMERAS, "1000", "a"),
                              "1001": _body_packet(CH_CAMERAS, "1001", "b"),
                              "1002": _body_packet(CH_CAMERAS, "1002", "c")})
        cl.sock = sock
        got = cl.get_list(CH_CAMERAS, timeout=15, sessions=1, batch=9)
        assert len(got) == 3
        names = {o.get("name") for o in got}
        assert names == {"a", "b", "c"}
        cl.close()

    def test_accumulates_across_sessions(self):
        """Сессия 1 отдаёт только 2 тела из 3, сессия 2 — недостающее."""
        cl = _make_client_top()
        sessions = [
            _ScriptedSock(CH_CAMERAS, 3, [(1000, 2), (1001, 2), (1002, 2)],
                          {"1000": _body_packet(CH_CAMERAS, "1000", "a"),
                           "1001": _body_packet(CH_CAMERAS, "1001", "b")}),
            _ScriptedSock(CH_CAMERAS, 3, [(1000, 2), (1001, 2), (1002, 2)],
                          {"1002": _body_packet(CH_CAMERAS, "1002", "c")}),
        ]
        cl.sock = sessions[0]
        state = {"i": 0}

        def _fake_new_session():
            # только переключаем scripted-сокет, без реальной сети
            state["i"] += 1
            if state["i"] < len(sessions):
                cl.sock = sessions[state["i"]]
            cl._running = False
            cl._running = True
            cl.start_reader()

        cl._new_session = _fake_new_session
        got = cl.get_list(CH_CAMERAS, timeout=15, sessions=2, batch=1)
        names = {o.get("name") for o in got}
        assert names == {"a", "b", "c"}
        assert state["i"] >= 1
        cl.close()

    def test_partial_bank_returns_without_crash(self):
        """count=5, но сервер отдаёт только 2 тела -> вернуть 2, не упасть."""
        cl = _make_client_top()
        sock = _ScriptedSock(CH_CAMERAS, 5,
                             [(1000, 2), (1001, 2), (1002, 2), (1003, 2), (1004, 2)],
                             {"1000": _body_packet(CH_CAMERAS, "1000", "a"),
                              "1001": _body_packet(CH_CAMERAS, "1001", "b")})
        cl.sock = sock
        state = {"i": 0}

        def _fake_new_session():
            state["i"] += 1
            cl._running = False
            cl._running = True
            cl.start_reader()

        cl._new_session = _fake_new_session
        got = cl.get_list(CH_CAMERAS, timeout=12, sessions=3, batch=2)
        assert len(got) == 2
        ids = {str(o.get("objectid")) for o in got}
        assert ids == {"1000", "1001"}
        cl.close()


class TestGetHeaderRetry:
    def test_retries_lost_getall(self):
        """Заголовок отдаётся только со 2-го GET-ALL => клиент повторяет, не падая."""
        cl = _make_client_top()
        q = cl._channel_queue(CH_CAMERAS)
        # header_delivery_after=2: первый GET-ALL «теряется», заголовок придёт
        # только после повторного GET-ALL (ретрай на одиночную потерю).
        sock = _ScriptedSock(CH_CAMERAS, 2, [(1000, 2), (1001, 2)], {},
                             header_delivery_after=2)
        cl._new_session = lambda: None
        cl.sock = sock
        cl.start_reader = lambda: None
        deadline = time.monotonic() + 6.0

        def _feed():
            while time.monotonic() < deadline:
                try:
                    d, _ = sock.recvfrom(P.MAX_UDP)
                except socket.timeout:
                    break
                q.put(d)

        t = threading.Thread(target=_feed, daemon=True)
        t.start()
        count, ids = cl._get_header(CH_CAMERAS, header_timeout=4.0, retries=2)
        getall_sends = sum(
            1 for d, _ in sock.sent
            if len(d) > 64 and d[0x36] == CMD_GET
            and struct.unpack_from("<I", d, 0x38)[0] == CH_CAMERAS
            and d[HEADER_LEN:len(d) - MD5_LEN][:1] == b"\x01"
        )
        assert count == 2
        assert len(ids) == 2
        assert getall_sends >= 2  # была потеря первой попытки -> повтор
        cl.close()


class TestAckRobust:
    def test_reader_acks_every_packet(self):
        """Ридер шлёт ACK на каждый входящий пакет (cmd=2, flag|=0x02)."""
        n = 5
        pkts = [_body_packet(CH_CAMERAS, "%d" % i, "x%d" % i) for i in range(n)]

        class _Sock:
            def __init__(self):
                self.sent = []
                self.timeout = None
                self.closed = False
                self._i = 0
            def settimeout(self, t): self.timeout = t
            def close(self): self.closed = True
            def sendto(self, d, a): self.sent.append(d)
            def recvfrom(self, b):
                if self._i < len(pkts):
                    p = pkts[self._i]
                    self._i += 1
                    return p, ("127.0.0.1", 19090)
                raise socket.timeout()

        cl = _make_client_top()
        cl.sock = _Sock()
        cl.start_reader()
        # даём ридеру обработать все пакеты
        time.sleep(0.5)
        acks = [d for d in cl.sock.sent if len(d) >= 64 and d[0x36] == CMD_DATA
                and (d[0x37] & FLAG_OK)]
        assert len(acks) == n
        cl._running = False
        cl.close()

    def test_send_ack_retries_on_error(self):
        """Сбой первого sendto не теряет ACK — повторная попытка."""
        calls = {"n": 0}

        class _Flaky:
            def __init__(self): self.closed = False
            def sendto(self, d, a):
                calls["n"] += 1
                if calls["n"] == 1:
                    raise OSError("transient")
            def close(self): self.closed = True

        cl = _make_client_top()
        cl.sock = _Flaky()
        hdr = bytearray(64)
        hdr[0x36] = CMD_DATA
        cl._send_ack(bytes(hdr))
        assert calls["n"] == 2  # первая ошибка + успешный повтор


class TestKeepalive:
    def test_keepalive_sends_subscribe(self):
        """Фоновый таймер подписки 0x200 шлёт подписочный пакет на сокет."""

        class _Sock:
            def __init__(self):
                self.sent = []
                self.timeout = None
                self.closed = False
            def settimeout(self, t): self.timeout = t
            def close(self): self.closed = True
            def sendto(self, d, a): self.sent.append(d)
            def recvfrom(self, b): raise socket.timeout()

        cl = _make_client_top()
        cl.sock = _Sock()
        cl._running = True
        t = cl._start_keepalive(interval=0.1)
        assert t is not None
        time.sleep(0.45)
        cl._running = False
        cl._stop_keepalive()
        sub = [d for d in cl.sock.sent if len(d) > 64
               and struct.unpack_from("<I", d, 0x38)[0] == 0x200
               and d[0x36] == P.CMD_EVENT and d[0x37] == 0x01]
        assert len(sub) >= 1


# ---------------------------------------------------------------------------
# coordinator.refresh: не роняет setup_entry
# ---------------------------------------------------------------------------
class _FakeBankClient:
    """Фейковый клиент банка: отдаёт заданный список и признак приёма."""

    def __init__(self, objs, last_rx=1.0, last_list_count=None, raises=None):
        self.objs = objs
        self._last_rx = last_rx
        self.last_list_count = last_list_count if last_list_count is not None else len(objs)
        self._running = True
        self.raises = raises
        self.closed = False

    def get_list(self, channel, timeout=30.0, **kw):
        if self.raises:
            raise self.raises
        return self.objs

    def close(self):
        self.closed = True


class TestCoordinatorRefresh:
    def _hub_offline(self):
        return AkvilonHub("127.0.0.1", 19090, "secret", "0:0", "0:0", "Аквилон")

    def test_refresh_success_sets_online(self):
        h = self._hub_offline()
        cam = {"objectid": "111:1", "name": "cam1"}
        h._new_client = lambda: _FakeBankClient([cam], last_rx=time.monotonic())
        ok = h.refresh()
        assert ok is True
        assert h.is_online is True
        assert h._last_ok > 0
        assert h.cameras[0]["name"] == "cam1"

    def test_refresh_failure_does_not_raise_and_offline(self):
        h = self._hub_offline()
        h._new_client = lambda: _FakeBankClient([], raises=OSError("boom"))
        ok = h.refresh()  # не должно бросить исключение
        assert ok is False
        assert h.is_online is False
        assert h._last_ok == 0

    def test_refresh_demo_returns_true(self):
        h = self._hub_offline()
        h.load_demo_data()
        assert h.refresh() is True
        assert h.is_online is True

    def test_refresh_no_data_marks_offline(self):
        h = self._hub_offline()
        # клиент отвечает, но _last_rx == 0 (ничего не прислал) => не считаем онлайн
        h._new_client = lambda: _FakeBankClient([], last_rx=0.0)
        ok = h.refresh()
        assert ok is False
        assert h.is_online is False