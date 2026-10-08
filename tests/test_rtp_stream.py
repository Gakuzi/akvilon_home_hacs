"""Юнит-тесты rtp_stream.py — сборка H.264 кадра из RTP-пакетов камер.

Проверяем детерминированную логику (без реальной сети и ffmpeg):
  * parse_sprop — разбор base64 SPS/PPS из cameraSettings;
  * сборку одиночных NAL, STAP-A и фрагментации FU-A в картинку;
  * grab_jpeg — что IDR-кадр корректно собран и подан на декодер (мок ffmpeg);
  * _kick — запускающий RTP подписочный пакет.
"""
import base64

from akvilon_home.rtp_stream import RtpStream, parse_sprop


def _rtp(pt=96, ts=1000, marker=False, payload=b""):
    """Собирает минимальный RTP-пакет (v=2, без расширения, без CSRC)."""
    b = bytearray(12)
    b[0] = 0x80  # version=2
    b[1] = (0x80 if marker else 0x00) | (pt & 0x7F)
    b[3] = 1  # sequence
    b[4:8] = ts.to_bytes(4, "big")
    return bytes(b) + payload


class _FakeSock:
    """Поставляет заранее подготовленные RTP-датаграммы."""

    def __init__(self, datagrams):
        self.datagrams = list(datagrams)
        self.sent = []
        self.my_port = 50000

    def recvfrom(self, bufsize):
        if not self.datagrams:
            raise OSError("end")
        return self.datagrams.pop(0), ("cam", 0)

    def sendto(self, data, addr):
        self.sent.append(data)

    def close(self):
        pass

    def bind(self, *a):
        pass

    def settimeout(self, t):
        pass

    def getsockname(self):
        return ("0.0.0.0", self.my_port)


# NAL header (1 байт); тип в нижних 5 битах.
def _nal(ntype, payload=b""):
    return bytes([(ntype & 0x1F)]) + payload


def _stream_with(**kw):
    kw.setdefault("videoHost", "127.0.0.1")
    kw.setdefault("videoPort", 5010)
    kw.setdefault("videoToken", "tok")
    kw.setdefault("spropParameter", "")
    stream = RtpStream(kw)
    stream._bps = []
    return stream


class TestParseSprop:
    def test_empty(self):
        assert parse_sprop("") == []
        assert parse_sprop(None) == []

    def test_single(self):
        assert parse_sprop("YWJj") == [b"abc"]

    def test_two_entries(self):
        assert parse_sprop("YWJj,ZA==") == [b"abc", b"d"]

    def test_invalid_base64_skips(self):
        assert parse_sprop("???!!!") == []

    def test_sps_pps_decoded(self):
        sps, pps = b"\x67abc", b"\x68def"
        b64 = lambda b: base64.b64encode(b).decode()
        out = parse_sprop(f"{b64(sps)},{b64(pps)}")
        assert out == [sps, pps]


class TestFeedPicture:
    def test_feed_requires_idr(self):
        stream = _stream_with()
        stream._decode_ffmpeg = lambda annexb: b"\xff\xd8x"
        # non-IDR NAL (type=1) — декодер не должен вызываться
        assert stream._feed_picture([_nal(1, b"p")]) is None

    def test_feed_prepends_sps_pps(self):
        sps, pps = b"\x67sps", b"\x68pps"
        stream = _stream_with()
        stream._bps = [sps, pps]
        seen = {}
        stream._decode_ffmpeg = lambda annexb: (seen.__setitem__("a", annexb) or b"\xff\xd8ok")
        pic = stream._feed_picture([_nal(5, b"idr")])
        assert pic == b"\xff\xd8ok"
        assert seen["a"].startswith(b"\x00\x00\x00\x01" + sps + b"\x00\x00\x00\x01" + pps)


class TestGrabJpeg:
    def test_single_idr(self):
        stream = _stream_with()
        stream._decode_ffmpeg = lambda annexb: b"\xff\xd8ok"
        stream.sock = _FakeSock([_rtp(pt=96, ts=1, payload=_nal(5, b"idr"))])
        assert stream.grab_jpeg(timeout=1, kick=False) == b"\xff\xd8ok"

    def test_fu_a_fragmented_idr_assembles(self):
        """IDR (type 5), нарезанный FU-A на 3 сегмента с одним тайммаркером."""
        stream = _stream_with()
        seen = {}
        stream._decode_ffmpeg = lambda annexb: (seen.__setitem__("a", annexb) or b"\xff\xd8fu")
        nal = _nal(5, b"0123456789")
        fh = nal[0]           # оригинальный NAL header (type 5)
        data = nal[1:]
        frags = []
        hdr = (0x80 | 28)     # FU-A
        frags.append(_rtp(pt=96, ts=7, payload=bytes([hdr, (0x80 | (fh & 0x1F))]) + data[:3]))   # S
        frags.append(_rtp(pt=96, ts=7, payload=bytes([hdr, (fh & 0x1F)]) + data[3:7]))           # mid
        frags.append(_rtp(pt=96, ts=7, payload=bytes([hdr, (0x40 | (fh & 0x1F))]) + data[7:]))   # E
        stream.sock = _FakeSock(frags)
        assert stream.grab_jpeg(timeout=1, kick=False) == b"\xff\xd8fu"
        # собранная картинка должна воспроизводить исходный NAL
        assert b"0123456789" in seen["a"]

    def test_stap_a_with_idr(self):
        """STAP-A (type 24) с несколькими NAL, среди них IDR."""
        stream = _stream_with()
        stream._decode_ffmpeg = lambda annexb: b"\xff\xd8stap"
        n1 = _nal(9, b"aud")
        n2 = _nal(5, b"idrpays")
        stap = bytearray([0x80 | 24])
        for n in (n1, n2):
            stap += len(n).to_bytes(2, "big")
            stap += n
        stream.sock = _FakeSock([_rtp(pt=96, ts=3, payload=bytes(stap))])
        assert stream.grab_jpeg(timeout=1, kick=False) == b"\xff\xd8stap"

    def test_wrong_payload_type_ignored(self):
        """Служебные RTP с pt вне диапазона 96..127 отбрасываются."""
        stream = _stream_with()
        stream._decode_ffmpeg = lambda annexb: b"\xff\xd8ok"
        stream.sock = _FakeSock([
            _rtp(pt=0, ts=1, payload=_nal(5, b"vid")),   # аудио / прочее
            _rtp(pt=96, ts=1, payload=_nal(5, b"idr")),
        ])
        out = stream.grab_jpeg(timeout=1, kick=False)
        assert out is not None

    def test_non_idr_only_returns_none(self):
        stream = _stream_with()
        stream._decode_ffmpeg = lambda annexb: b"\xff\xd8x"
        stream.sock = _FakeSock([_rtp(pt=96, ts=1, payload=_nal(1, b"pframe"))])
        assert stream.grab_jpeg(timeout=1, kick=False) is None


class TestKick:
    def test_kick_sends_zero_token(self):
        stream = RtpStream({"videoHost": "127.0.0.1", "videoPort": 5010,
                            "videoToken": "tok123", "spropParameter": ""})
        s = _FakeSock([])
        stream.sock = s
        stream._kick()
        assert s.sent and s.sent[0] == b"\x00\x00" + b"tok123"

    def test_kick_skips_without_token(self):
        stream = RtpStream({"videoHost": "127.0.0.1", "videoPort": 5010,
                            "videoToken": "", "spropParameter": ""})
        s = _FakeSock([])
        stream.sock = s
        stream._kick()
        assert s.sent == []