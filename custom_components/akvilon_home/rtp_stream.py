"""Приём и декод H.264 RTP-потока камер Аквилон InHome (кадр и живой поток).

Видео камер идёт от сервера здания (videoHost:videoPort) на UDP-порт клиента
в формате RTP/H.264 (payload type 96/97/98, срочный: FU-A для нарезки NAL).
Параметры кодека (SPS/PPS) берутся из cameraSettings.spropParameter.

Статус (2026-10-08): РАБОТАЕТ. РПР-поток запускается отправкой подписочного
пакета b"\x00\x00"+videoToken на videoHost:videoPort (см. _kick). Этот модуль
— приёмник: слушает RTP, за 1-2 сек собирает IDR-кадр и отдаёт JPEG через
ffmpeg. Если поток не пошёл — методы вернут None, не блокируя HA.

Высокоуровневое API (в executor):
    stream = RtpStream(settings)
    jpg = stream.grab_jpeg(timeout=6.0)   # один кадр: bytes | None
    stream.close()

Непрерывный поток (для свежего окна/HA stream) — см. LiveStream/StreamManager
в конце модуля: один RTP-приёмник на камеру шарится между зрителями (refcount),
соблюдается лимит одновременных видео-сессий сервера.
"""
import base64
import logging
import socket
import subprocess
import threading
import time

_LOGGER = logging.getLogger(__name__)

RTP_MAX = 65535
# H.264 RTP payload type (динамический диапазон 96-127; обычно 96..98)
RTP_PT_RANGE = frozenset(range(96, 128))

# Значение по умолчанию: сколько живых UDP/RTP-сессий одновременно держим.
LIVE_MAX_CONCURRENT = 2
# Срок жизни одной сессии (переустановка/закрытие), сек.
LIVE_SESSION_TTL = 600.0
# Интервал переоткрытия сессии, если сервер замолчал (UDP-таймаут), сек.
LIVE_RETRY_INTERVAL = 30.0


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

    def _iter_frames(self, timeout, stop=None):
        """Генератор полных картинок из RTP-потока до timeout (или __stop__).

        Отдаёт (picture: list[NAL], got_idr: bool) для каждого завершённого
        кадра. Полная сборка: одиночные NAL, STAP-A и фрагментация FU-A
        (сегменты сливаются по временному маркеру RTP). Кадр считается
        завершённым, когда из сокета приходит RTP-пакет с новым тайммаркером,
        либо по истечении timeout (последний остаток тоже отдаётся).

        stop — threading.Event: если установлен, генератор завершается досрочно.
        """
        deadline = time.time() + timeout
        picture = []        # NAL-юниты текущей картинки (по одному ts)
        fu_acc = None       # буфер текущего FU-A фрагмента (bytearray + base header)
        cur_ts = None
        got_idr = False
        while time.time() < deadline:
            if stop is not None and stop.is_set():
                break
            r = self._recv_rtp()
            if r is None:
                continue
            ts, pt, marker, payload = r
            # новый RTP-тайммаркер = начало нового кадра -> отдаём старый
            if cur_ts is not None and ts != cur_ts:
                if picture:
                    yield picture, got_idr
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
        if picture:
            yield picture, got_idr

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
        for picture, got_idr in self._iter_frames(timeout):
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


class LiveStream:
    """Непрерывный UDP/RTP-приёмник камеры, отдающий свежие JPEG по мере поступления.

    Это «продлеваемый» вариант RtpStream.grab_jpeg: вместо «послушал timeout и
    вернул один кадр» он держит UDP-сессию открытой окно retry_interval и через
    on_frame отдаёт каждый новый собранный IDR. Если сервер замолчал (за
    retry_interval не пришло ни одного полного IDR), сессия переоткрывается:
    close -> заново bind и _kick (запускающий подписочный пакет).

    Использование (в executor-потоке, не на event loop HA):
        live = LiveStream(settings)
        live.run(on_frame=cb, stop=event)   # блокирует до stop/итога
    """

    def __init__(self, settings, retry_interval=LIVE_RETRY_INTERVAL):
        self.settings = settings or {}
        self.retry_interval = retry_interval

    def run(self, on_frame, total=LIVE_SESSION_TTL, stop=None):
        """Циклически открывает RTP-сессию и зовёт on_frame(jpg) на каждый кадр.

        Возвращается после истечения total или установки stop (Event). Каждый
        цикл длится retry_interval: открываем свежий сокет, кикаем, собираем
        кадры; по таймауту цикла переоткрываемся — это и есть «переустановка
        сессии» при уходе UDP-потока.
        """
        start = time.time()
        while _is_set(stop) is False:
            if time.time() - start >= total:
                break
            stream = RtpStream(self.settings)
            stream.bind(0)
            stream._kick()
            try:
                for picture, got_idr in stream._iter_frames(self.retry_interval, stop=stop):
                    if picture and got_idr:
                        jpg = stream._feed_picture(picture)
                        if jpg:
                            on_frame(jpg)
            finally:
                stream.close()


class StreamManager:
    """Менеджер живых RTP-сессий с лимитом одновременных потоков и шарингом.

    Решает две проблемы из SPEC-002:
      1. Лимит активных видео-сессий на сервере здания — ведём бюджет
         max_concurrent: если он исчерпан, выселяем самый давний сеанс (LRU).
      2. Несколько зрителей одной камеры — ОДИН сетевой источник на всех
         (refcount): последний подписчик закрывает сессию и шлёт closeCamera.

    Фоновый поток на активную сессию слушает UDP и обновляет latest.
    Работает вне event loop HA. Потоко-безопасен.
    """

    def __init__(self, max_concurrent=LIVE_MAX_CONCURRENT,
                 retry_interval=LIVE_RETRY_INTERVAL, session_ttl=LIVE_SESSION_TTL,
                 on_release=None):
        self._lock = threading.Lock()
        self._sessions = {}
        self._token = 0
        self.max_concurrent = int(max_concurrent)
        self.retry_interval = retry_interval
        self.session_ttl = session_ttl
        # opциональный колбэк при полном освобождении сессии (напр. closeCamera):
        # вызывается как on_release(cam_id) после shutdown, вне lock.
        self._on_release = on_release

    def active_count(self) -> int:
        """Сколько сессий сейчас открыто (в т.ч. без зрителей)."""
        with self._lock:
            return len(self._sessions)

    def subscribe(self, cam_id: str, settings: dict) -> int:
        """Регистрирует зрителя камеры; запускает живой поток при первом зрителе.

        Возвращает токен подписки (передаётся в unsubscribe). Если активных
        сессий уже max_concurrent — выселяется самая давняя.
        """
        sid = str(cam_id)
        token = 0
        with self._lock:
            if len(self._sessions) >= self.max_concurrent and sid not in self._sessions:
                self._evict_lru()
            sess = self._sessions.get(sid)
            if sess is None:
                sess = _LiveSession(sid, settings)
                self._sessions[sid] = sess
            self._token += 1
            token = self._token
            sess.refs.add(token)
            sess.bump()
            if sess.thread is None or not sess.thread.is_alive():
                sess.stop = threading.Event()
                sess.thread = threading.Thread(
                    target=self._run_session, args=(sess,), daemon=True,
                )
                sess.thread.start()
        return token

    def _evict_lru(self):
        """Выселяет самую давнюю сессию и сигналит освобождение (on_release)."""
        if not self._sessions:
            return
        oldest = min(self._sessions.values(), key=lambda s: s.last_access)
        evicted_id = oldest.cam_id
        self._shutdown_session(oldest)
        self._sessions.pop(evicted_id, None)
        self._notify_release([evicted_id])

    def unsubscribe(self, cam_id: str, token: int):
        """Снимает зрителя; закрывает сессию, когда зрителей не осталось."""
        sid = str(cam_id)
        released = []
        with self._lock:
            sess = self._sessions.get(sid)
            if sess is None:
                return
            sess.refs.discard(token)
            if not sess.refs:
                self._shutdown_session(sess)
                self._sessions.pop(sid, None)
                released.append(sid)
        self._notify_release(released)

    def latest(self, cam_id: str) -> bytes | None:
        """Последний готовый JPEG камеры (None, если кадр ещё не собран)."""
        with self._lock:
            sess = self._sessions.get(str(cam_id))
            if sess is None:
                return None
            sess.bump()
            return sess.latest

    def close(self, cam_id: str | None = None):
        """Останавливает все сессии (или одну камеру). Зовётся при выгрузке."""
        released = []
        with self._lock:
            if cam_id is None:
                ids = list(self._sessions)
            else:
                ids = [str(cam_id)]
            for sid in ids:
                sess = self._sessions.get(sid)
                if sess is not None:
                    self._shutdown_session(sess)
                    self._sessions.pop(sid, None)
                    released.append(sid)
        self._notify_release(released)

    def _run_session(self, sess):
        def emit(jpg):
            with self._lock:
                sess.latest = jpg
                sess.bump()

        live = LiveStream(sess.settings, retry_interval=self.retry_interval)
        live.run(on_frame=emit, total=self.session_ttl, stop=sess.stop)
        # поток-приёмник завершился (TTL/stop) без зрителей — сама сессия пока
        # остаётся в _sessions; уборку сделает unsubscribe/close/LRU.

    def _shutdown_session(self, sess):
        if sess.stop is not None:
            sess.stop.set()
        sess.refs.clear()

    def _notify_release(self, released):
        if not released or self._on_release is None:
            return
        cb = self._on_release
        for sid in released:
            try:
                cb(sid)
            except Exception:  # pragma: no cover — не роняем управление
                _LOGGER.warning("Аквилон: on_release(%s) упал", sid, exc_info=True)


def _is_set(ev) -> bool:
    """Безопасная проверка threading.Event (None = не останавливать)."""
    return ev is not None and ev.is_set()


class _LiveSession:
    """Внутреннее состояние одной живой сессии камеры (не для прямого вызова)."""

    __slots__ = ("cam_id", "settings", "refs", "thread", "stop", "latest", "last_access")

    def __init__(self, cam_id, settings):
        self.cam_id = cam_id
        self.settings = settings
        self.refs = set()
        self.thread = None
        self.stop = threading.Event()
        self.latest = None
        self.last_access = time.monotonic()

    def bump(self):
        self.last_access = time.monotonic()