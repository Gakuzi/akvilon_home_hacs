"""Приём и декод H.264 RTP-потока камер Аквилон InHome.

Видео камер идёт от сервера здания (videoHost:videoPort) на UDP-порт клиента
в формате RTP/H.264 (payload type 96/97/98, срочный: FU-A для нарезки NAL).
Параметры кодека (SPS/PPS) берутся из cameraSettings.spropParameter.

Статус (2026-10-08): РАБОТАЕТ. РПР-поток запускается отправкой подписочного
пакета b"\x00\x00"+videoToken на videoHost:videoPort (см. _kick). Этот модуль
— приёмник: слушает RTP, за 1-2 сек собирает IDR-кадр и отдаёт JPEG через
ffmpeg. Если поток не пошёл — методы вернут None, не блокируя HA.

Использование (в executor):
    stream = RtpStream(settings)
    jpg = stream.grab_jpeg(timeout=6.0)   # bytes | None
    stream.close()
"""
import base64
import logging
import socket
import subprocess
import time

_LOGGER = logging.getLogger(__name__)

RTP_MAX = 65535
# H.264 RTP payload type (динамический диапазон 96-127; обычно 96..98)
RTP_PT_RANGE = frozenset(range(96, 128))


def parse_sprop(sprop: str):
    """spropParameter 'Z00AHukCwS0IAAAfSAAGHBAg,aOqPIA==' -> [(type,data), ...]."""
    out = []
    if not sprop:
        return out
    for part in sprop.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            data = base64.b64decode(part)
        except Exception:
            continue
        if data:
            out.append(data)
    return out


class RtpStream:
    """UDP-приёмник RTP/H.264 с одной камеры + декод кадра через ffmpeg."""

    def __init__(self, settings, bind_host="0.0.0.0", bind_port=0):
        self.settings = settings or {}
        self.host = self.settings.get("videoHost") or ""
        self.port = int(self.settings.get("videoPort") or 0)
        self.token = str(self.settings.get("videoToken") or "")
        self.sprop = str(self.settings.get("spropParameter") or "")
        self.sock = None
        self.my_port = 0
        self._bps = parse_sprop(self.sprop)  # SPS/PPS bytes
        # Reorder НЕ требуется: практически это локальная сеть, пакеты приходят
        # по порядку, а потерянные сегменты FU-A просто не соберутся в кадр.
        if bind_port:
            self.bind(bind_port)

    def bind(self, port):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("0.0.0.0", int(port)))
        self.sock.settimeout(0.3)
        self.my_port = self.sock.getsockname()[1]
        return self.my_port

    def _kick(self):
        """Запускает RTP: шлёт подписочный пакет на видео-порт.

        Точный формат (из pcap приложения inHome): UDP-датаграмма =
        b"\\x00\\x00" + ascii(videoToken), отправляемая на videoHost:videoPort.
        Сервер стримит RTP/H.264 на тот же клиентский UDP-порт, с которого
        отправлен пакет.
        """
        if not self.port or not self.token:
            return
        payload = b"\x00\x00" + self.token.encode("ascii")
        try:
            self.sock.sendto(payload, (self.host, self.port))
        except Exception:
            pass

    def _decode_ffmpeg(self, annexb):
        """Декодит annexb H.264 в JPEG через ffmpeg -f h264. Возвращает bytes|None.

        ffmpeg обязан быть на PATH в окружении HA (в контейнере homeassistant
        он есть: /usr/bin/ffmpeg, Docker-образ Alpine с ffmpeg 8.x).
        """
        if not annexb:
            return None
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-f", "h264", "-i", "-", "-frames:v", "1",
            "-an", "-f", "mjpeg", "-y", "-",
        ]
        proc = None
        try:
            proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            out, err = proc.communicate(annexb, timeout=15.0)
            if proc.returncode == 0 and out and out[:2] == b"\xff\xd8":
                return out
            _LOGGER.debug("ffmpeg decode fail: %s", err.decode("utf-8", "replace")[:200])
        except Exception as e:  # pragma: no cover
            _LOGGER.debug("ffmpeg decode exc: %s", e)
        finally:
            if proc:
                try:
                    proc.kill()
                except Exception:
                    pass
        return None

    def _recv_rtp(self):
        """Читает один RTP-пакет. Возвращает (ts, pt, marker, payload) или None."""
        try:
            d, addr = self.sock.recvfrom(RTP_MAX)
        except socket.timeout:
            return None
        except Exception:
            return None
        if len(d) < 12:
            return None
        v = (d[0] >> 6) & 0x3
        if v != 2:
            return None
        ts = int.from_bytes(d[4:8], "big")
        pt = d[1] & 0x7F
        # Валидация payload type: принимаем только H.264 из динамического ряда.
        # Сервер может слать посторонние служебные RTP-пакеты (другие pt) — их
        # отбрасываем, чтобы они не испортили сборку кадра.
        if pt not in RTP_PT_RANGE:
            return None
        marker = bool(d[1] & 0x80)
        return ts, pt, marker, d[12:]

    def _feed_picture(self, picture):
        """Пытается декодить собранную картинку (list of NAL bytes) в JPEG.

        Возвращает JPEG-bytes при успехе либо None.
        """
        if not picture:
            return None
        has_idr = any((n[0] & 0x1F) == 5 for n in picture)
        if not has_idr:
            return None
        parts = []
        if self._bps:                      # SPS/PPS из cameraSettings — гарантия
            for b in self._bps:
                parts.append(b"\x00\x00\x00\x01" + b)
        for nal in picture:
            parts.append(b"\x00\x00\x00\x01" + nal)
        annexb = b"".join(parts)
        return self._decode_ffmpeg(annexb)

    def grab_jpeg(self, timeout=6.0, kick=True):
        """Слушает RTP до timeout, собирает полную картинку (IDR) и декодит в JPEG.

        Возвращает bytes (JPEG) при успехе или None, если поток не пошёл/нет IDR
        (сервер не стартует RTP — обычный случай без точной подписки).

        Полная сборка: корректно обрабатываются одиночные NAL, STAP-A и
        фрагментация FU-A (сегменты сливаются по временному маркеру RTP).
        """
        if not self.sock:
            self.bind(0)
        if not self.port:
            return None
        if kick:
            self._kick()
        deadline = time.time() + timeout
        picture = []        # NAL-юниты текущей картинки (по одному ts)
        fu_acc = None       # буфер текущего FU-A фрагмента (bytearray + base header)
        cur_ts = None
        got_idr = False
        while time.time() < deadline:
            r = self._recv_rtp()
            if r is None:
                continue
            ts, pt, marker, payload = r
            # новый RTP-тайммаркер = начало нового кадра -> пробуем декод старого
            if cur_ts is not None and ts != cur_ts:
                if picture and got_idr:
                    jpg = self._feed_picture(picture)
                    if jpg:
                        return jpg
                picture = []
                got_idr = False
                fu_acc = None
            cur_ts = ts
            if not payload:
                continue
            nalh = payload[0]
            ntype = nalh & 0x1F
            if ntype == 28:                       # FU-A: фрагментация NAL
                if len(payload) < 2:
                    continue
                sbit = payload[1] & 0x80
                ebit = payload[1] & 0x40
                real_type = payload[1] & 0x1F
                hdr = bytes([(nalh & 0xE0) | real_type])
                if sbit:
                    fu_acc = bytearray(hdr + payload[2:])
                elif fu_acc is not None:
                    fu_acc += payload[2:]
                if ebit and fu_acc is not None:
                    nal = bytes(fu_acc)
                    fu_acc = None
                    if real_type == 5:
                        got_idr = True
                    picture.append(nal)
                continue
            if ntype == 24:                       # STAP-A: несколько NAL
                off = 1
                while off < len(payload):
                    if off + 2 > len(payload):
                        break
                    nalen = int.from_bytes(payload[off:off + 2], "big")
                    off += 2
                    if off + nalen > len(payload):
                        break
                    nal = payload[off:off + nalen]
                    off += nalen
                    if nal and (nal[0] & 0x1F) == 5:
                        got_idr = True
                    if nal:
                        picture.append(nal)
                continue
            # одиночный NAL (SPS=7, PPS=8, IDR=5, non-IDR=1, SEI=6...)
            if ntype == 5:
                got_idr = True
            picture.append(payload)
        # финальная попытка
        if picture and got_idr:
            jpg = self._feed_picture(picture)
            if jpg:
                return jpg
        return None

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None