"""Юнит-тесты ding.py — пуш-звонок домофона (Feature C).

Тестируются чисто-питоновские части, не требующие сети и Home Assistant:
  * classify_incoming — распознавание события вызова во входящем UDP-пакете;
  * _looks_like_call / _is_active — эвристика;
  * build_ding_message — текст уведомления;
  * DingListener._scan_inbox — реакция на «звонок» через фейковый клиент
    (обработчик вызывается, watermark исключает повторную эмиссию);
  * _jpeg_to_data_uri — картинка в data-URI.
"""
import json
import struct

import pytest

from akvilon_home import ding as D
from akvilon_home.protocol import HEADER_LEN, MD5_LEN, CMD_GET, CMD_DATA, CMD_EVENT, build_header


def _packet(channel, payload_bytes, cmd=CMD_EVENT, flag=0x01):
    """Собирает UDP-пакет: header(64) + payload + md5."""
    hdr = build_header(cmd, flag, 1, channel, src_id="0:1", dst_id="0:0")
    md5 = b"\x00" * MD5_LEN
    return hdr + payload_bytes + md5


def _json_packet(channel, obj, cmd=CMD_EVENT):
    return _packet(channel, json.dumps(obj, separators=(",", ":")).encode("utf-8"),
                   cmd=cmd)


class TestClassifyIncoming:
    def test_short_packet_is_none(self):
        assert D.classify_incoming(b"\x00") is None

    def test_binary_get_is_none(self):
        # бинарный список (cmd=1) — не событие вызова
        pkt = _packet(0x10401, struct.pack("<I", 2) + b"\x00" * 32, cmd=CMD_GET)
        assert D.classify_incoming(pkt) is None

    def test_ack_data_is_none(self):
        # cmd=2 (данные/ACK)
        pkt = _packet(0x200, b"{}", cmd=CMD_DATA)
        assert D.classify_incoming(pkt) is None

    def test_json_without_call_indicator_is_none(self):
        pkt = _json_packet(0x10403, {"hello": "world"})
        assert D.classify_incoming(pkt) is None

    def test_call_active_field_detected(self):
        pkt = _json_packet(0x10403, {"call": 1, "id": "3:101885"})
        out = D.classify_incoming(pkt)
        assert out is not None
        assert out["type"] == "call"
        assert out["domain"] == "akvilon_home"
        assert out["object_id"] == "3:101885"

    def test_call_inactive_zero_is_none(self):
        pkt = _json_packet(0x30000, {"call": 0})
        assert D.classify_incoming(pkt) is None

    def test_name_ring_detected(self):
        pkt = _json_packet(0x200, {"name": "ring", "cameraId": "2:101967"})
        out = D.classify_incoming(pkt)
        assert out is not None
        assert out["object_id"] == "2:101967"

    def test_label_extracted(self):
        pkt = _json_packet(0x10403, {"call": True, "name": "Парадная 1", "gateId": "1:101908"})
        out = D.classify_incoming(pkt)
        assert out["label"] == "Парадная 1"
        assert out["object_id"] == "1:101908"


class TestLooksLikeCall:
    def test_active_int(self):
        assert D._looks_like_call({"call": 1}) is True

    def test_active_string(self):
        assert D._looks_like_call({"callStatus": "ringing"}) is True

    def test_empty_string_inactive(self):
        assert D._looks_like_call({"call": ""}) is False

    def test_false_string_inactive(self):
        assert D._looks_like_call({"call": "false"}) is False

    def test_zero_inactive(self):
        assert D._looks_like_call({"call": 0}) is False


class TestBuildDingMessage:
    def test_with_label(self):
        msg = D.build_ding_message({"label": "Парадная 1", "object_id": "1"})
        assert msg == "Звонок в домофон Парадная 1"

    def test_with_id_fallback(self):
        msg = D.build_ding_message({"label": "", "object_id": "3:101885"})
        assert msg == "Звонок в домофон 3:101885"

    def test_blank_fallback(self):
        msg = D.build_ding_message({})
        assert msg == "Звонок в домофон домофон"


class _FakeClient:
    """Фейковый UDP-клиент: только `_inbox` список для закачки пакетов."""

    def __init__(self, packets=None):
        self._inbox = list(packets or [])
        self._running = True
        self.closed = False

    def close(self):
        self.closed = True
        self._running = False


class TestDingListener:
    def _make_listener(self, packets, handler=None):
        listener = D.DingListener(None, handler=handler, client_factory=_FakeClient)
        listener.start()
        # подменяем клиент: сразу готовый с нужными пакетами
        listener._client = _FakeClient(packets)
        listener._watermark = 0
        return listener

    def test_calls_handler_on_ding(self):
        called = []
        pkt = _json_packet(0x10403, {"call": 1, "id": "3:101885"})
        listener = self._make_listener([pkt], handler=called.append)
        listener._scan_inbox()
        assert len(called) == 1
        assert called[0]["object_id"] == "3:101885"
        listener.stop()

    def test_no_handler_for_non_call(self):
        called = []
        pkt = _json_packet(0x10403, {"hello": "world"})
        listener = self._make_listener([pkt], handler=called.append)
        listener._scan_inbox()
        assert called == []
        listener.stop()

    def test_watermark_prevents_reemit(self):
        called = []
        pkt = _json_packet(0x200, {"call": 1, "cameraId": "2:101967"})
        listener = self._make_listener([pkt], handler=called.append)
        listener._scan_inbox()
        listener._scan_inbox()  # повторный вызов не должен эмитить повторно
        assert len(called) == 1
        listener.stop()

    def test_stop_is_idempotent(self):
        listener = self._make_listener([])
        listener.stop()
        listener.stop()
        assert listener.is_running is False


class TestJpegDataUri:
    def test_prefix(self):
        uri = D._jpeg_to_data_uri(b"\xff\xd8\xff")
        assert uri.startswith("data:image/jpeg;base64,")
        import base64
        assert base64.b64decode(uri.split(",", 1)[1]) == b"\xff\xd8\xff"


class _FakeListener:
    """Минимальный объект со stop(), как у DingListener — для hub-хуков."""

    def __init__(self):
        self.stopped = False

    def stop(self):
        self.stopped = True


class TestHubDingHooks:
    """Хуки хаба для пуш-звонка (coordinator.AkvilonHub)."""

    def _hub(self):
        from akvilon_home.coordinator import AkvilonHub
        return AkvilonHub("127.0.0.1", 19090, "secret", "0:0", "0:0", "Аквилон")

    def test_default_listener_none(self):
        h = self._hub()
        assert h.ding_listener is None

    def test_set_and_get(self):
        h = self._hub()
        fake = _FakeListener()
        h.set_ding_listener(fake)
        assert h.ding_listener is fake

    def test_stop_is_idempotent_when_none(self):
        h = self._hub()
        h.stop_ding_listener()  # не падает и ничего не делает

    def test_stop_calls_listener_stop(self):
        h = self._hub()
        fake = _FakeListener()
        h.set_ding_listener(fake)
        h.stop_ding_listener()
        assert fake.stopped is True
        assert h.ding_listener is None
        # повторный вызов безопасен
        h.stop_ding_listener()