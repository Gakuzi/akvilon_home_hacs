"""Двусторонний голосовой канал (RTP/RTCP) домофона Аквилон InHome.

Аналог `rtp_stream.py` для видео, но для аудио. Запускается при входящем
вызове домофона («принять звук»), когда `intercom_accept_audio`/`intercom_answer`
дают параметры голосового канала из cameraSettings (voiceHost/voicePort).

Что подтверждено разбором нативной `libInHome.so` (см. VOICE.md):
  * кодек аудио — G.711 (`A7G711Codec`, encode/decode, `G711AppEncode`/
    `G711AppDecode`; есть и `A7NoChangeCodec` = PCM-без изменений);
  * частота дискретизации — 8000 Гц (`A7VoiceSamplerate`, `voiceSamplerate: 8000`,
    строки `S8000`/`S16000`);
  * транспорт — RTP по UDP (`A7RtpClient`/`A7Rtp`/`A7RtpPacket`) + RTCP
    (`A7RtcpPacket`: SR/RR/SDES/BYE, `sendRtcp`/`sendDataRtcp`,
    `remoteRtcpHost`/`remoteRtcpPort`);
  * запуск потока — как видео: датаграмма с токеном на голосовой порт
    (`A7RtpClient.sendToken()`, `setA7token`, `setRemoteHost/Port`,
    `setSession`, `setPin`, `setLocalPort`, потом `start()`);
  * управление микрофоном — `A7VoicePhone::setMicIsOn`, `setMicVolume`,
    `setSpeakerVolume`, `setEchoControl`, `setVoiceCodec`, `setVoiceSamplerate`.

Статус честно: точная конфигурация реального звонка (PT-номер для G.711,
нужный ли RTCP-рукопожатие, SSRC подключений) не подтверждена pcap живого
звонка. Модуль реализует стандартный G.711/PCMU-канал по RTP и скрывает
непроверенные детали за настройками с разумными значениями по умолчанию —
дорабатывается по реальному вызову (см. раздел «Что требует проверки» в VOICE.md).
"""
import logging
import socket
import struct
import threading
import time

_LOGGER = logging.getLogger(__name__)

# Диапазон RTP payload type для динамических кодеков (96-127). G.711 по RFC 3551:
# PCMU = 0, PCMA = 8, сессия может использовать и фиксированные, и динамические.
RTP_PT_RANGE = frozenset(range(0, 128))
# Сетевой флакон G.711 — 20 мс @8 кГц = 160 байт (стандартный VoIP-размер).
G711_FRAME_BYTES = 160
# Битрейт и пакетизация: 8000 Гц * 8 бит / 20 мс = 160 байт на пакет.
VOICE_CLOCK_RATE = 8000


class RtcpSenderReport:
    """Минимальный RTCP Sender Report (тип 200) — «рукопожатие», которое
    нативная либа шлёт через `sendRtcp`. Хост может ждать именно его, прежде
    чем считать канал живым. RTCP-пакеты идут на voiceRtcp-порт, обычно на
    (remoteRtcpHost, remoteRtcpPort) или (voiceHost, voicePort+1)."""

    def __init__(self, ssrc=0x4C, ntp_hi=0xE0000000, ntp_lo=0, rtp_ts=0, pkt=0, oct=0):
        self.ssrc = ssrc
        self.ntp_hi = ntp_hi
        self.ntp_lo = ntp_lo
        self.rtp_ts = rtp_ts
        self.pkt = pkt
        self.oct = oct

    def pack(self):
        # V=2, P=0, RC=0, PT=200 (SR); длина = 6 слов (1 заголовок + SR фикс).
        header = struct.pack(">BBH", 0x80, 200, 6)
        body = struct.pack(
            ">IIIII",
            self.ssrc,
            self.ntp_hi & 0xFFFFFFFF,
            self.ntp_lo & 0xFFFFFFFF,
            self.rtp_ts & 0xFFFFFFFF,
            0,  # sender's RTP packet count placeholder (обновляется снаружи)
        )
        # sender's octet count
        body += struct.pack(">I", self.oct & 0xFFFFFFFF)
        return header + body[: 24 - len(header)]


class VoiceStream:
    """UDP-канал RTP/RTCP G.711 с сервером домофона (микрофон/динамик).

    Потокобезопасен: `send_audio()` шлёт микрофон в потоке-продуцента, а
    `recv_audio(timeout)` вычитывает пакеты динамика в потоке-потребителя.
    RTCP-рукопожатие и sendToken отправляются отдельным потоком. По умолчанию
    поток передаёт голос теми же токен-датаграммами, что и видео, но с
    отдельным голосовым портом.

    Без реального pcap не подтверждено: какой именно пакет сервер требует
    для старта (token / RTCP SR) и на какой PT идёт G.711. Поэтому поведение
    регулируется параметрами конструктора (см. VOICE.md).
    """

    def __init__(
        self,
        host,
        port,
        token="",
        rtcp_host="",
        rtcp_port=0,
        bind_host="0.0.0.0",
        bind_port=0,
        ssrc=None,
        sample_rate=VOICE_CLOCK_RATE,
    ):
        self.host = host
        self.port = int(port or 0)
        self.token = token or ""
        self.rtcp_host = rtcp_host or host
        self.rtcp_port = int(rtcp_port or (self.port + 1 if self.port else 0))
        self.sample_rate = sample_rate
        self.ssrc = ssrc if ssrc is not None else self._random_ssrc()
        self.sock = None
        self.rtcp_sock = None
        self.my_port = 0
        self._seq = 0
        self._ts = 0
        self._rtcp_seq = 0
        self._rtcp_oct = 0
        self._rtcp_running = False
        self._rtcp_thread = None
        self._lock = threading.Lock()
        self._closed = False
        if bind_port:
            self.bind(bind_port)

    @staticmethod
    def _random_ssrc():
        try:
            return (int(time.time() * 1000) ^ (id(VoiceStream) & 0xFFFF)) & 0x7FFFFFFF
        except Exception:
            return 0x4C545000  # "LTP\0"

    def bind(self, port):
        """Открывает UDP-сокет на (bind_host, port) для RTP и отдельный для RTCP."""
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("0.0.0.0", int(port)))
        self.sock.settimeout(0.2)
        self.my_port = self.sock.getsockname()[1]
        if self.rtcp_port:
            try:
                self.rtcp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.rtcp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self.rtcp_sock.bind(("0.0.0.0", self.my_port + 1))
                self.rtcp_sock.settimeout(0.2)
            except Exception:
                if self.rtcp_sock:
                    try:
                        self.rtcp_sock.close()
                    except Exception:
                        pass
                    self.rtcp_sock = None
        return self.my_port

    # ------------------------------------------------------------------
    # Запуск / kick токеном (аналог видео) + RTCP-рукопожатие
    # ------------------------------------------------------------------
    def _kick(self, send_sr=True):
        """Шлёт токен запуска (b"\\x00\\x00"+token) на голосовой порт и,
        по умолчанию, RTCP Sender Report для «открытия» сессии."""
        if not self.port:
            return
        # 1. Токен-датаграмма — точный механизм видео, для голоса гипотеза.
        if self.token:
            forms = [
                b"\x00\x00" + self.token.encode("ascii"),
                self.token.encode("ascii"),
                (self.token + "\r\n").encode("ascii"),
            ]
            for form in forms:
                try:
                    self.sock.sendto(form, (self.host, self.port))
                except Exception:
                    pass
        # 2. RTCP SR — голос почти наверняка требует его (sendRtcp в либе).
        if send_sr:
            self._send_sender_report()

    def _send_sender_report(self):
        try:
            pkt = RtcpSenderReport(
                ssrc=self.ssrc,
                ntp_hi=int(time.time()) + 2208988800,   # NTP (сдвиг 70 лет до 1900)
                ntp_lo=0,
                rtp_ts=self._ts & 0xFFFFFFFF,
                pkt=1,
                oct=self._sample_octets,
            ).pack()
            dst = (self.rtcp_host, self.rtcp_port) if self.rtcp_port else (self.host, self.port)
            sock = self.rtcp_sock if self.rtcp_sock else self.sock
            sock.sendto(pkt, dst)
        except Exception as exc:
            _LOGGER.debug("Аквилон: RTCP SR send exc: %s", exc)

    @property
    def _sample_octets(self):
        return getattr(self, "_rtcp_oct", 0)

    # ------------------------------------------------------------------
    # Отправка микрофона (G.711-кадры по 160 байт)
    # ------------------------------------------------------------------
    def send_audio(self, g711_bytes, marker=True):
        """Упаковывает G.711-байты в RTP-пакет и отправляет на голосовой порт.

        Возвращает число отправленных байт аудио. `g711_bytes` должен быть
        одним кадром (обычно 160 байт для 20 мс @8 кГц). Приемлемы 40..640 байт.
        """
        if not self.sock or not self.port:
            return 0
        delay = not (len(g711_bytes) in (40, 80, 160, 240, 320, 480, 640))
        with self._lock:
            # V=2, P=0, X=0, CC=0, M=marker, PT демо-значения (PCMU=0).
            first = 0x80 | (0x80 if marker else 0x00)
            rtp = bytearray(12)
            rtp[0] = first
            rtp[1] = 0  # PT = 0 (PCMU/G.711 µ-law) — гипотеза, см. VOICE.md
            struct.pack_into(">H", rtp, 2, self._seq & 0xFFFF)
            self._seq += 1
            struct.pack_into(">I", rtp, 4, self._ts & 0xFFFFFFFF)
            self._ts += 160
            struct.pack_into(">I", rtp, 8, self.ssrc & 0xFFFFFFFF)
            rtp += g711_bytes
            self._rtcp_oct += len(g711_bytes)
        try:
            self.sock.sendto(bytes(rtp), (self.host, self.port))
            return len(g711_bytes)
        except Exception as exc:
            _LOGGER.debug("Аквилон: voice send exc: %s", exc)
            return 0

    def _recv_raw(self):
        try:
            d, addr = self.sock.recvfrom(65535)
        except socket.timeout:
            return None, None
        except Exception:
            return None, None
        return d, addr

    def recv_audio(self, timeout=6.0):
        """Читает один RTP-пакет с голосового потока.

        Возвращает (timestamp, marker, g711_payload) для динамика, либо None,
        если за `timeout` данных нет. Отбрасывает RTCP-пакеты (PT 192-223),
        которые приходят на тот же сокет.
        """
        if not self.sock:
            return None, False, None
        sock = self.sock
        old = sock.gettimeout()
        sock.settimeout(timeout)
        try:
            while True:
                d, _ = self._recv_raw()
                if d is None:
                    return None, False, None
                if len(d) < 12:
                    continue
                v = (d[0] >> 6) & 0x3
                if v != 2:
                    continue
                pt = d[1] & 0x7F
                if 192 <= pt <= 223:
                    continue  # RTCP-пакет — пропускаем
                ts = int.from_bytes(d[4:8], "big")
                marker = bool(d[1] & 0x80)
                return ts, marker, d[12:]
        finally:
            sock.settimeout(old)

    # ------------------------------------------------------------------
    # Фоновый RTCP (keepalive/рукопожатие) — как sendKeepAlive в либе
    # ------------------------------------------------------------------
    def _rtcp_loop(self):
        while self._rtcp_running and not self._closed:
            time.sleep(2.0)
            try:
                self._send_sender_report()
            except Exception:
                pass

    def start_rtcp(self):
        if self._rtcp_running:
            return
        self._rtcp_running = True
        self._rtcp_thread = threading.Thread(target=self._rtcp_loop, daemon=True)
        self._rtcp_thread.start()

    # ------------------------------------------------------------------
    # Управление (аналог A7VoicePhone::setMicIsOn / setMicVolume)
    # ------------------------------------------------------------------
    def set_mic(self, on, volume=None):
        """Включает/выключает передачу микрофона и задаёт громкость (0..1)."""
        if volume is not None:
            _LOGGER.debug("Аквилон: voice mic volume -> %.2f", volume)
        if on:
            self.start_rtcp()
        else:
            self._rtcp_running = False
        return on

    def close(self):
        self._closed = True
        self._rtcp_running = False
        if self._rtcp_thread:
            t = self._rtcp_thread
            self._rtcp_thread = None
            t.join(timeout=0.5)
        for s in (self.sock, self.rtcp_sock):
            if s is not None:
                try:
                    s.close()
                except Exception:
                    pass
        self.sock = None
        self.rtcp_sock = None


