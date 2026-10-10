"""Юнит-тесты protocol.py — чистая логика протокола Аквилон.

Тестируются функции, не требующие сети: parse_qr, pack_a7id, get_a7id,
build_header, sign_packet, get_list_payload, а также построение/разбор пакетов
AkvilonClient через мок сокета.
"""
import hashlib
import socket
import struct

import pytest

from akvilon_home import protocol as P
from akvilon_home.protocol import (
    AkvilonClient,
    MAGIC,
    HEADER_LEN,
    MD5_LEN,
    CMD_GET,
    FLAG_OK,
    build_header,
    get_a7id,
    get_list_payload,
    pack_a7id,
    parse_id,
    parse_qr,
    sign_packet,
)


# ---------------------------------------------------------------------------
# parse_qr
# ---------------------------------------------------------------------------
class TestParseQr:
    def test_full_realistic_qr(self):
        qr = (
            "CLEVERB;CODE;00000;VERSION;3;DEVICEID;0:0;"
            "PASS;a1b2c3d4;UDP;127.0.0.1;19090;SERVERID;0:0;SUID;cafebabe"
        )
        out = parse_qr(qr)
        assert out["HOST"] == "127.0.0.1"
        assert out["PORT"] == 19090
        assert out["DEVICE_ID"] == "0:0"
        assert out["PASS"] == "a1b2c3d4"
        assert out["SERVER_ID"] == "0:0"
        assert out["TOKEN"] == bytes.fromhex("cafebabe")

    def test_key_value_form(self):
        out = parse_qr("HOST=10.0.0.5;PORT=19090;PASS=abc123;DEVICEID=1:2;SERVERID=3:4")
        assert out["HOST"] == "10.0.0.5"
        # в форме КЛЮЧ=ЗНАЧЕНИЕ порт остаётся строкой (как в исходной строке)
        assert out["PORT"] == "19090"
        assert out["PASS"] == "abc123"
        assert out["DEVICE_ID"] == "1:2"

    def test_defaults(self):
        out = parse_qr("")
        assert out["HOST"] == "127.0.0.1"
        assert out["PORT"] == 19090
        assert out["TOKEN"] == b""

    def test_server_id_split(self):
        qr = "DEVICEID;0:0;PASS;x;SERVERID;7:1000;UDP;127.0.0.1;19090"
        out = parse_qr(qr)
        assert out["SERVERFLAG"] == "7"
        assert out["SERVERID_NUM"] == "1000"
        assert out["SERVER_ID"] == "7:1000"


# ---------------------------------------------------------------------------
# A7ID helpers
# ---------------------------------------------------------------------------
class TestA7id:
    def test_pack_a7id_length(self):
        b = pack_a7id(119, 101967)
        assert len(b) == 16
        obj_id = struct.unpack_from("<q", b, 0)[0]
        flag = struct.unpack_from("<i", b, 8)[0]
        assert obj_id == 101967
        assert flag == 119

    def test_get_a7id_with_flag(self):
        assert get_a7id("3:101885") == (3, 101885)

    def test_get_a7id_no_flag(self):
        assert get_a7id("101967") == (0, 101967)

    def test_get_a7id_invalid(self):
        assert get_a7id("abc") == (0, 0)

    def test_parse_id(self):
        assert parse_id("2:99798") == (2, 99798)


# ---------------------------------------------------------------------------
# build_header
# ---------------------------------------------------------------------------
class TestBuildHeader:
    def test_header_length_and_magic(self):
        h = build_header(CMD_GET, 0x00, 5, 0x10401, src_id="0:1", dst_id="0:0")
        assert len(h) == HEADER_LEN
        magic = struct.unpack_from("<Q", h, 0x00)[0]
        assert magic == MAGIC
        assert h[0x36] == CMD_GET
        assert h[0x37] == 0x00
        ch = struct.unpack_from("<I", h, 0x38)[0]
        assert ch == 0x10401

    def test_seq_roundtrip(self):
        h = build_header(1, 0, 4242, 0x200, src_id="0:1", dst_id="0:0")
        seq = struct.unpack_from("<I", h, 0x0a)[0]
        assert seq == 4242


# ---------------------------------------------------------------------------
# sign_packet — детерминированная MD5
# ---------------------------------------------------------------------------
class TestSignPacket:
    def test_md5_of_ascii_pass(self):
        hdr = bytes(64)
        payload = b"hello"
        token = b"deadbeef"
        sig = sign_packet(hdr, payload, token)
        expected = hashlib.md5(hdr[0x2E:0x40] + payload + token).digest()
        assert sig == expected
        assert len(sig) == 16

    def test_token_changes_signature(self):
        hdr = bytes(64)
        s1 = sign_packet(hdr, b"data", b"tok-a")
        s2 = sign_packet(hdr, b"data", b"tok-b")
        assert s1 != s2


# ---------------------------------------------------------------------------
# get_list_payload
# ---------------------------------------------------------------------------
class TestGetListPayload:
    def test_all_type_length(self):
        p = get_list_payload(1, -1, 0, 0)
        assert len(p) == 32
        t = struct.unpack_from("<I", p, 0)[0]
        assert t == 1

    def test_one_object(self):
        p = get_list_payload(2, 101967, 119, 0)
        assert len(p) == 32
        t = struct.unpack_from("<I", p, 0)[0]
        oid = struct.unpack_from("<q", p, 4)[0]
        assert t == 2
        assert oid == 101967


# ---------------------------------------------------------------------------
# AkvilonClient: построение и разбор через мок сокета
# ---------------------------------------------------------------------------
class _FakeSock:
    """Мок UDP-сокета: отдаёт заранее заданные ответы."""

    def __init__(self, responses=()):
        self.sent = []
        self.responses = list(responses)
        self.timeout = None
        self.closed = False

    def settimeout(self, t):
        self.timeout = t

    def sendto(self, data, addr):
        self.sent.append((data, addr))

    def recvfrom(self, bufsize):
        if not self.responses:
            raise socket.timeout()
        return self.responses.pop(0), ("127.0.0.1", 19090)

    def close(self):
        self.closed = True


def _make_client(**kw):
    kw.setdefault("host", "127.0.0.1")
    kw.setdefault("port", 19090)
    kw.setdefault("token_hex", "x")
    kw.setdefault("device_id", "0:0")
    kw.setdefault("server_id", "0:0")
    return AkvilonClient(**kw)


class TestAkvilonClientBuild:
    def test_build_has_signature_tail(self):
        cl = _make_client()
        pkt = cl._build(CMD_GET, 0x00, 0x10401, get_list_payload(1, -1, 0, 0))
        assert len(pkt) > HEADER_LEN + 16
        sig = pkt[-MD5_LEN:]
        hdr = pkt[:HEADER_LEN]
        payload = pkt[HEADER_LEN:-MD5_LEN]
        expected = hashlib.md5(hdr[0x2E:0x40] + payload + b"PASS_PLACEHOLDER").digest()
        assert sig == expected

    def test_send_builds_correct_datagram(self):
        """Проверяем, что send() собирает корректную датаграмму и шлёт на сокет."""
        cl = _make_client()
        cl.sock = _FakeSock(responses=[bytes(64) + b"\x00" * 16])
        out = cl.send(CMD_GET, 0x00, 0x10401, get_list_payload(1, -1, 0, 0))
        assert out is not None
        # отправлен ровно один пакет на (host, port)
        assert len(cl.sock.sent) == 1
        data, addr = cl.sock.sent[0]
        assert addr == ("127.0.0.1", 19090)
        # структура: header(64) + payload(32) + md5(16)
        assert len(data) == 64 + 32 + 16
        ch = struct.unpack_from("<I", data, 0x38)[0]
        assert ch == 0x10401
        cmd = data[0x36]
        assert cmd == CMD_GET

    def test_get_a7id_parse_in_header_roundtrip(self):
        # проверка: src='0:1' даёт flag=0 oid=1
        h = build_header(1, 0, 1, 0x200, src_id="0:1", dst_id="0:0")
        # dst A7ID в 0x0e..0x1e
        dflag = struct.unpack_from("<i", h, 0x0e + 8)[0]
        doid = struct.unpack_from("<q", h, 0x0e)[0]
        assert doid == 0
        assert dflag == 0


class TestGateOpenPayload:
    def test_open_gate_payload_sent(self):
        cl = _make_client()
        resp_hdr = bytearray(64)
        resp_hdr[0x36] = P.CMD_DATA
        resp_hdr[0x37] = P.FLAG_OK
        cl.sock = _FakeSock(responses=[bytes(resp_hdr) + b"\x00" * 16])
        ok = cl.open_gate("1:101908")
        assert ok is True
        # ищем отправленный пакет с каналом открытия калитки
        sent, _ = cl.sock.sent[0]
        ch = struct.unpack_from("<I", sent, 0x38)[0]
        assert ch == P.CHANNEL_DOOR_BUTTONS
        payload = sent[HEADER_LEN:-MD5_LEN]
        assert b'"action": "open"' in payload
        assert b"1:101908" in payload


def _header_packet(channel, count, records):
    """Собирает валидный бинарный заголовок GET-списка (cmd=1, flag=0x02).

    records: list[(oid:int, rflag:int)]. payload = u32 count + records*16.
    Каждая запись: 4 байта crc + q u64 oid + u32 flag (+ 4 неиспользуемых).
    """
    hdr = bytearray(64)
    hdr[0x36] = CMD_GET
    hdr[0x37] = FLAG_OK
    struct.pack_into("<I", hdr, 0x38, channel)
    payload = struct.pack("<I", count)
    for oid, rflag in records:
        payload += b"\x00" * 4          # crc
        payload += struct.pack("<q", oid)
        payload += struct.pack("<I", rflag)
        payload += b"\x00" * 4
    return bytes(hdr) + payload + b"\x00" * 16


class TestHeaderParsing:
    def test_is_header_true(self):
        cl = _make_client()
        recs = [(101967, 2), (101968, 3)]
        pkt = _header_packet(0x10401, 2, recs)
        assert cl._is_header(pkt, 0x10401)

    def test_is_header_wrong_channel(self):
        cl = _make_client()
        recs = [(1, 0)]
        pkt = _header_packet(0x10401, 1, recs)
        assert not cl._is_header(pkt, 0xE0401)

    def test_is_header_json_body_not_header(self):
        cl = _make_client()
        hdr = bytearray(64)
        hdr[0x36] = CMD_GET
        hdr[0x37] = FLAG_OK
        struct.pack_into("<I", hdr, 0x38, 0x10401)
        pkt = bytes(hdr) + b'{"objectid":"1"}' + b"\x00" * 16
        assert not cl._is_header(pkt, 0x10401)

    def test_header_count(self):
        cl = _make_client()
        recs = [(1, 0), (2, 0), (3, 0)]
        pkt = _header_packet(0x10401, 3, recs)
        assert cl._header_count(pkt) == 3


class TestCameraMethods:
    """Покрытие методов open/close camera и запуска видео-токена."""

    def test_open_camera_sends_packet(self):
        cl = _make_client()
        resp_hdr = bytearray(64)
        resp_hdr[0x36] = P.CMD_EVENT
        resp_hdr[0x37] = P.FLAG_OK
        cl.sock = _FakeSock(responses=[bytes(resp_hdr) + b"\x00" * 16])
        r = cl.open_camera("111:69724")
        assert r is not None
        sent, _ = cl.sock.sent[0]
        ch = struct.unpack_from("<I", sent, 0x38)[0]
        assert ch == 0x30401
        payload = sent[HEADER_LEN:-MD5_LEN]
        assert b"openCamera" in payload
        assert b"111:69724" in payload

    def test_close_camera_sends_packet(self):
        cl = _make_client()
        resp_hdr = bytearray(64)
        resp_hdr[0x36] = P.CMD_EVENT
        resp_hdr[0x37] = P.FLAG_OK
        cl.sock = _FakeSock(responses=[bytes(resp_hdr) + b"\x00" * 16])
        r = cl.close_camera("111:69724")
        assert r is not None
        sent, _ = cl.sock.sent[0]
        payload = sent[HEADER_LEN:-MD5_LEN]
        assert b"closeCamera" in payload

    def test_send_video_token(self):
        cl = _make_client()
        cl.sock = _FakeSock(responses=[])
        ok = cl.send_video_token("127.0.0.1", 5010, "token_x")
        assert ok is True
        data, addr = cl.sock.sent[0]
        assert data == b"\x00\x00" + b"token_x"
        assert addr == ("127.0.0.1", 5010)

    def test_send_video_token_no_sock_returns_false(self):
        cl = _make_client()
        cl.sock = None
        # отсутствующий сокет -> False без исключения
        assert cl.send_video_token("127.0.0.1", 5010, "tok") is False

    def test_send_keepalive_calls_subscribe(self):
        cl = _make_client()
        resp_hdr = bytearray(64)
        resp_hdr[0x36] = P.CMD_EVENT
        resp_hdr[0x37] = P.FLAG_OK
        cl.sock = _FakeSock(responses=[bytes(resp_hdr) + b"\x00" * 16])
        r = cl.send_keepalive()
        assert r is not None
        sent, _ = cl.sock.sent[0]
        ch = struct.unpack_from("<I", sent, 0x38)[0]
        assert ch == 0x200

    def test_subscribe_sends_sub_channels(self):
        cl = _make_client()
        resp_hdr = bytearray(64)
        resp_hdr[0x36] = P.CMD_EVENT
        resp_hdr[0x37] = P.FLAG_OK
        cl.sock = _FakeSock(responses=[bytes(resp_hdr) + b"\x00" * 16])
        r = cl.subscribe()
        assert r is not None
        sent, _ = cl.sock.sent[0]
        ch = struct.unpack_from("<I", sent, 0x38)[0]
        assert ch == 0x200
        # payload содержит количество каналов == число SUB_CHANNELS
        payload = sent[HEADER_LEN:-MD5_LEN]
        cnt = struct.unpack_from("<I", payload, 0)[0]
        assert cnt == len(P.SUB_CHANNELS)

    def test_register_sends_initial_channel(self):
        cl = _make_client()
        resp_hdr = bytearray(64)
        resp_hdr[0x36] = P.CMD_EVENT
        resp_hdr[0x37] = P.FLAG_OK
        cl.sock = _FakeSock(responses=[bytes(resp_hdr) + b"\x00" * 16])
        r = cl.register()
        assert r is not None
        sent, _ = cl.sock.sent[0]
        ch = struct.unpack_from("<I", sent, 0x38)[0]
        assert ch == 0x02020001
        payload = sent[HEADER_LEN:-MD5_LEN]
        assert b"inHome" in payload

    def test_get_list_payload_lengths(self):
        # Проверка всех веток get_list_payload (req_type=1 и =2)
        p1 = bytes(P.get_list_payload(1, -1, 0, 0))
        assert len(p1) == 32
        t1 = struct.unpack_from("<I", p1, 0)[0]
        assert t1 == 1
        p2 = bytes(P.get_list_payload(2, 101967, 3, 5))
        assert len(p2) == 32
        t2 = struct.unpack_from("<I", p2, 0)[0]
        assert t2 == 2
        oid = struct.unpack_from("<q", p2, 4)[0]
        assert oid == 101967

    def test_channel_queue_creates_and_reuses(self):
        cl = _make_client()
        # первое обращение создаёт очередь
        q1 = cl._channel_queue(0x10401)
        assert q1 is not None
        # повторное обращение возвращает ту же очередь
        q2 = cl._channel_queue(0x10401)
        assert q2 is q1

    def test_header_count_and_is_header(self):
        cl = _make_client()
        recs = [(101967, 2), (101968, 3)]
        pkt = _header_packet(0x10401, 2, recs)
        assert cl._header_count(pkt) == 2