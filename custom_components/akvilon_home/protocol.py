"""Реализация UDP-протокола Аквилон InHome (клиент).

Формат пакета (из реального трафика приложения):
    header(64 байта) + payload + MD5(header[0x2e:0x40] + payload + token)

Поля header:
    0x00..0x07  магия 04 10 01 00 02 00 05 00
    0x08..0x09  subheader 10 00
    0x0a..0x0d  sequence (4 байта LE)
    0x0e..0x1d  dst A7ID (DeviceId, напр. 0:0)
    0x1e..0x2d  src A7ID (реально 0:1 для устройства)
    0x2e..0x35  stateTime (qint64 ms; для GET=0)
    0x36        cmd (1=GET, 2=данные, 3=EVENT)
    0x37        flag (0=запрос, 0x02=OK/ACK)
    0x38..0x3b  channel
    0x3c..0x3f  stateNumber

Реальные каналы:
    0x200      подписка на каналы (cmd=3 flag=0x01, send каждые 15 сек)
    0x10401    камеры        (GET-список)
    0xE0401    калитки       (GET-список)
    0x20401    счётчики      (GET-список)
    0x90401    пользователи  (GET-список)
    0x2030401  cameraSettings (ответ на openCamera)
    0x30401    openCamera/closeCamera (cmd=3 flag=0, {"id":"...","name":"openCamera"})
"""
import hashlib
import logging
import queue
import socket
import struct
import time
import json
import threading

try:
    from .const import CHANNEL_DOOR_BUTTONS, SIGN_START, SIGN_LEN
except ImportError:
    CHANNEL_DOOR_BUTTONS = 0x30301
    SIGN_START = 0x2E
    SIGN_LEN = 0x12

_LOG = logging.getLogger(__name__)

MAGIC = 0x0005000200011004
MAX_UDP = 65535
MIN_PKT = 0x50       # 64 header + 16 md5
HEADER_LEN = 64
MD5_LEN = 16
CMD_GET = 1
CMD_EVENT = 3
CMD_DATA = 2
FLAG_OK = 0x02
FLAG_ERR = 0x82

# Каналы для подписки (на 0x200): РЕАЛЬНЫЕ каналы данных этого здания.
# Проверено по трафику приложения в4.0.229 (/tmp/ctrl_2.txt): bytes в payload
# подписки и ответа сервера = 01 04 01 00 / 01 04 02 00 / 01 04 0e 00 / 01 04 09 00
# (LE u32) = 0x10401(камеры), 0x20401(счётчики), 0xE0401(калитки), 0x90401(пользователи).
# НЕ 0x10402/0x1040e/0x10409 — это прошлая (неверная) интерпретация байт.
SUB_CHANNELS = [0x10401, 0x20401, 0xE0401, 0x90401, 0x10403]

# Реальные каналы данных
CH_CAMERAS = 0x10401
CH_INTERCOM = 0x10403
CH_GATES = 0xE0401
CH_METERS = 0x20401
CH_USERS = 0x90401
CH_CAMERA_SETTINGS = 0x2030401
CH_INITIAL = 0x02020001   # регистрация приложения


def parse_qr(qr: str) -> dict:
    """Разбирает QR-строку подключения Аквилон (формат застройщика).

    Поддерживает два разделителя: 'КЛЮЧ=ЗНАЧЕНИЕ' и пары 'КЛЮЧ;ЗНАЧЕНИЕ'
    (как в реальной строке: CLEVERB;CODE;00000;VERSION;3;DEVICEID;0:0;
    PASS;PASS_PLACEHOLDER;UDP;127.0.0.1;19090;SERVERID;0:0;SUID;deadbeef...).
    Возвращает dict: HOST, PORT, DEVICE_ID, SERVER_ID, PASS (str), SUID, TOKEN(bytes).
    """
    out = {}
    qr = (qr or "").strip().strip('"\'')
    toks = qr.split(';')
    i = 0
    while i < len(toks):
        tok = toks[i].strip()
        if not tok:
            i += 1
            continue
        up = tok.upper()
        # 'КЛЮЧ=ЗНАЧЕНИЕ'
        if '=' in tok:
            k, v = tok.split('=', 1)
            out[k.strip().upper()] = v.strip()
            i += 1
            continue
        # шаблон: известный ключ без '=' -> следующая часть это значение
        if up in ('CLEVERB', 'CLEVERH', 'CODE', 'VERSION', 'DEVICEID', 'DEVICE_ID',
                  'PASS', 'UDP', 'JOOAPORT', 'JOOAPIN', 'SERVERID', 'USEJOOA',
                  'SPACE', 'USERDATA', 'USER', 'SUID', 'DEF_UDP', 'CODE='):
            if i + 1 < len(toks):
                value = toks[i + 1].strip()
                out[up] = value
                # UDP несёт адрес сервера: 'IP' или 'IP:PORT' (после может идти
                # отдельный токен порта: 'UDP;IP;PORT'). Если это IP — запомним
                # его как HOST, а следующий числовой токен как PORT.
                if up in ('UDP', 'DEF_UDP', 'HOST') and value and ':' not in value \
                        and not value.isdigit() and '.' in value:
                    out['HOST'] = value
                    if i + 2 < len(toks) and toks[i + 2].strip().isdigit():
                        out['PORT'] = int(toks[i + 2].strip())
                        i += 3
                        continue
                i += 2
            else:
                i += 1
            continue
        i += 1
    sid = out.get('SERVERID') or out.get('SERVERUID') or ""
    if sid:
        sep = sid.find(':')
        if sep > 0:
            left, right = sid[:sep], sid[sep + 1:]
            if left.isdigit() and right.isdigit() and int(left) < 1000:
                out['SERVERFLAG'], out['SERVERID_NUM'] = left, right
                out['SERVER_ID'] = sid
            elif left and right.isdigit():
                out['HOST'], out['PORT'] = left, int(right)
    # HOST/PORT могут прийти также в значении ключа с '=' (UDP=IP:PORT)
    for k in ('UDP', 'DEF_UDP'):
        v = out.get(k) or ""
        if ':' in v and not v.startswith('http'):
            host, _, port = v.partition(':')
            if _ and host and port.isdigit():
                out.setdefault('HOST', host)
                out.setdefault('PORT', int(port))
    out.setdefault('HOST', '127.0.0.1')
    out.setdefault('PORT', 19090)
    dev = out.get('DEVICE_ID') or out.get('DEVICEID') or out.get('DEVICE')
    if dev:
        out['DEVICE_ID'] = dev
    pwd = out.get('PASS') or out.get('PASSWORD') or ""
    out['PASS'] = pwd
    uid = out.get('SUID') or out.get('SUID=')
    try:
        out['TOKEN'] = bytes.fromhex(uid) if uid else b''
    except (ValueError, TypeError):
        out['TOKEN'] = b''
    return out


def pack_a7id(flag: int, obj_id: int, version: int = 1) -> bytes:
    """A7IDObject: int64 id LE + int32 flag LE + int32 version LE."""
    return struct.pack("<q", obj_id) + struct.pack("<i", flag) + struct.pack("<i", version)


def get_a7id(raw: str):
    """Парсит 'flag:id' -> (flag, id, version). Версия 1 для реальных id."""
    raw = str(raw).strip()
    if ":" in raw:
        flag_s, id_s = raw.split(":", 1)
    else:
        flag_s, id_s = "0", raw
    try:
        flag = int(flag_s)
    except ValueError:
        flag = 0
    try:
        obj_id = int(id_s)
    except ValueError:
        obj_id = 0
    return flag, obj_id


def parse_id(raw: str):
    """Упрощённый парсер: flag,id (для сброса всегда version=1)."""
    flag, oid = get_a7id(raw)
    return flag, oid


def build_header(cmd, flag, seq, channel, state_number=0, state_time=0,
                 src_id=None, dst_id=None):
    """Строит 64-байтовый header пакет.

    src_id/dst_id — строки 'flag:id'. По реальному трафику:
    src='0:1', dst=DeviceId ('0:0'). Без них сервер не принимает.
    """
    hdr = bytearray(64)
    struct.pack_into("<Q", hdr, 0x00, MAGIC)
    struct.pack_into("<H", hdr, 0x08, 0x0010)
    struct.pack_into("<I", hdr, 0x0a, seq & 0xFFFFFFFF)
    if dst_id:
        f, oid = get_a7id(dst_id)
        hdr[0x0e:0x1e] = pack_a7id(f, oid)  # dst
    if src_id:
        f, oid = get_a7id(src_id)
        hdr[0x1e:0x2e] = pack_a7id(f, oid, version=0)  # src (device: flag=0)
    struct.pack_into("<q", hdr, 0x2e, state_time)
    hdr[0x36] = cmd
    hdr[0x37] = flag
    struct.pack_into("<I", hdr, 0x38, channel & 0xFFFFFFFF)
    struct.pack_into("<I", hdr, 0x3c, state_number)
    return bytes(hdr)


def sign_packet(header, payload, token: bytes) -> bytes:
    """MD5(header[0x2e:0x40] + payload + token)."""
    return hashlib.md5(header[SIGN_START:SIGN_START + SIGN_LEN] + payload + token).digest()


def _safe_str(v):
    """Безопасное строковое представление значения (для ключей/логов)."""
    if v is None:
        return ""
    if isinstance(v, (dict, list, tuple, set)):
        return str(v)[:200]
    return str(v)


def get_list_payload(req_type=1, object_id=-1, flag=0, counter=0):
    """32-байтный payload GET по реальному трафику приложения в4.0.229.

    Схема (проверено по /tmp/ctrl_2.txt): u32 тип + u64 objectId + u32 flag
    + u64(0) + u64(counter). РОВНО 32 байта — сервер молча игнорирует более
    короткий 12-байтный вариант (мы это уже видели).

    req_type=1 -> GET-ALL (object_id=-1, adr 0xFF..FF), payload:
        01 00 00 00 ff ff ff ff ff ff ff ff 00 00 00 00 <8x00> <8x00>
    req_type=2 -> GET одного объекта: в object_id реальный id, в flag —
        вторая (flag) часть A7ID из бинарного заголовка списка:
        02 00 00 00 <u64 oid> <u32 flag> <8x00> <u64 counter>
    """
    return (struct.pack("<I", req_type)
            + struct.pack("<q", object_id)
            + struct.pack("<I", flag)
            + struct.pack("<Q", 0)
            + struct.pack("<Q", counter))


class AkvilonClient:
    """UDP-клиент к серверу здания."""

    def __init__(self, host, port, token_hex, device_id="0:0", server_id="0:0",
                 device_flag=119, pass_hex="PASS_PLACEHOLDER"):
        self.host = host
        self.port = port
        # Секрет подписи = PASS из QR (напр. PASS_PLACEHOLDER), а не SUID.
        # ВАЖНО: в MD5 участвует АСКИ-строка "PASS_PLACEHOLDER", а НЕ hex-байты 0x9C 0x5E 0xDC 0xB9.
        # Проверено по трафику: MD5(header[0x2e:0x40]+payload+ASCII(PASS)) — совпадает с приложением.
        self.token = pass_hex.encode("ascii") if pass_hex else b""
        # src для устройства всегда '0:1', dst = DeviceId
        self.server_id = "0:1"
        self.device_id = device_id
        self.device_flag = device_flag
        self.seq = 0
        self.sock = None
        self.keepalive_timer = None
        self.keepalive_thread = None
        self._running = False
        self._inbox = []
        self._inbox_lock = threading.Lock()
        # Один поток последовательно пишет в сокет: ридер (ACK), keepalive и
        # основной поток get_list делят self.seq и сокет. Блокировка защищает
        # и порядковые номера, и целостность датаграмм (без неё seq мог бы
        # «разъехаться» между потоками, и сервер бы отбрасывал пакеты).
        self._send_lock = threading.Lock()
        # Побочные очереди по каналу: НА них работает всё чтение get_list.
        # Единственный поток (фоновый ридер) владеет сокетом и раскладывает
        # входящие пакеты по очередям — это устраняет гонку двух recvfrom,
        # из-за которой пакеты раньше терялись.
        self._queues = {}
        self._reader_thread = None
        self.last_list_count = None
        self._last_rx = 0.0  # monotonic-метка последнего успешного входящего пакета

    def connect(self) -> bool:
        try:
            if self.sock:
                try:
                    self.sock.close()
                except Exception:
                    pass
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.settimeout(5.0)
            return True
        except Exception:
            return False

    def ping(self, timeout: float = 4.0) -> bool:
        """Быстрая проверка доступности сервера: шлёт подписочный пакет и ждёт ответа.

        Используется мастером настройки на шаге проверки соединения, чтобы сразу
        понять, доступен ли сервер здания, не дожидаясь полной загрузки списков.
        """
        try:
            if not self.sock:
                self.connect()
            if not self.sock:
                return False
            self.sock.settimeout(timeout)
            # подписочный пакет на канал 0x200 (один канал) — сервер обязан ответить ACK
            payload = struct.pack("<I", 1) + struct.pack("<II", 0x10401, 0)
            self.sock.sendto(self._build(CMD_EVENT, 0x01, 0x200, payload),
                             (self.host, self.port))
            data, _ = self.sock.recvfrom(MAX_UDP)
            return data is not None and len(data) >= MIN_PKT
        except socket.timeout:
            return False
        except Exception:
            return False

    def ensure_session(self):
        """Идемпотентная инициализация сессии: connect + subscribe + register + reader."""
        if self.sock is None:
            self.connect()
        if not self._reader_thread or not self._reader_thread.is_alive():
            self.start_reader()
        return self

    def _new_session(self):
        """Закрывает старый сокет и поднимает СВЕЖУЮ сессию.

        Сервер отвечает на GET-списки по каналу ТОЛЬКО один раз за UDP-сессию.
        Повторный GET в той же сессии молча игнорируется (пустой ACK). Поэтому
        при «мёртвой» сессии создаём новый сокет + подписку + регистрацию + ридер.
        """
        self._running = False
        self._stop_keepalive()
        if self._reader_thread and self._reader_thread.is_alive():
            try:
                self._reader_thread.join(timeout=1.0)
            except Exception:
                pass
        self._reader_thread = None
        try:
            self.sock.close()
        except Exception:
            pass
        self.sock = None
        self.connect()
        self.subscribe()
        self.register()
        self.start_reader()
        return self

    def close(self):
        self._running = False
        self._stop_keepalive()
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
        self.sock = None


    def _send_ack(self, hdr: bytes):
        """ACK на входящий пакет: эхо заголовка, cmd=2, flag|=0x02.

        Сервер продолжает поток частей списка ТОЛЬКО после ACK на предыдущий
        пакет, поэтому ACK нельзя терять при перегрузке: при сбое сокета делаем
        одну повторную попытку, прежде чем сдаться.
        """
        if not self.sock:
            return
        try:
            ack = bytearray(hdr)
            ack[0x36] = CMD_DATA
            ack[0x37] |= FLAG_OK
            pkt = bytes(ack) + sign_packet(bytes(ack), b"", self.token)
            with self._send_lock:
                self.sock.sendto(pkt, (self.host, self.port))
        except Exception:
            try:
                with self._send_lock:
                    self.sock.sendto(pkt, (self.host, self.port))
            except Exception:  # pragma: no cover
                pass

    def _next_seq(self) -> int:
        with self._send_lock:
            self.seq += 1
            return self.seq

    def _build(self, cmd, flag, channel, payload=b"", state_number=0, state_time=0,
               src_id=None, dst_id=None) -> bytes:
        seq = self._next_seq()
        if src_id is None:
            src_id = self.server_id
        if dst_id is None:
            dst_id = self.device_id
        hdr = build_header(cmd, flag, seq, channel, state_number, state_time, src_id, dst_id)
        return hdr + payload + sign_packet(hdr, payload, self.token)

    def send(self, cmd, flag, channel, payload=b"", state_number=0, src_id=None, dst_id=None,
             timeout=5.0, state_time=0):
        """Отправляет пакет и возвращает сырой ответ (или None при таймауте)."""
        if not self.sock:
            return None
        try:
            self.sock.settimeout(timeout)
            pkt = self._build(cmd, flag, channel, payload, state_number, state_time, src_id, dst_id)
            with self._send_lock:
                self.sock.sendto(pkt, (self.host, self.port))
            data, _ = self.sock.recvfrom(MAX_UDP)
            return data
        except Exception:
            return None

    def send_and_ack(self, cmd, flag, channel, payload=b"", timeout=5.0,
                     src_id=None, dst_id=None):
        """Отправляет пакет, обрабатывает первый ответ: возвращает payload данных
        (или b'' если это ACK), отвечая ACK на входящие cmd=2/3."""
        data = self.send(cmd, flag, channel, payload, timeout=timeout, src_id=src_id, dst_id=dst_id)
        if not data:
            return b""
        return self._dispatch_incoming(data)

    def _dispatch_incoming(self, data) -> bytes:
        if len(data) < MIN_PKT:
            return b""


    def _subscribe_payload(self) -> bytes:
        """Payload подписки 0x200: количество каналов + пары (channel, 0)."""
        payload = struct.pack("<I", len(SUB_CHANNELS))
        for ch in SUB_CHANNELS:
            payload += struct.pack("<I", ch) + struct.pack("<I", 0)
        return payload

    def subscribe(self):
        """Подписка на каналы данных (cmd=3 flag=0x01 на канал 0x200)."""
        return self.send(CMD_EVENT, 0x01, 0x200, self._subscribe_payload())


    def register(self, device_uuid="2::device_uuid_placeholder"):
        """Регистрация приложения на сервере (канал 0x02020001).

        Без неё сервер молча игнорирует GET-запросы списков.
        """
        body = json.dumps({
            "app": "inHome",
            "buildtime": "Dec 15 2025 17:10:43",
            "connectionStatus": "building",
            "deviceType": "phone",
            "deviceUuid": device_uuid,
            "hgrevision": "62f31597",
            "os": "android",
            "os_api": "android 13.0",
            "version": "4.0.229",
        }, separators=(",", ":")).encode("utf-8")
        _LOG.debug("[akvilon_home] register ch=0x02020001")
        r = self.send(CMD_EVENT, 0x00, CH_INITIAL, body,
                      state_number=self._next_seq(), state_time=int(time.time() * 1000))
        _LOG.debug("[akvilon_home] register ответ: %s", ("OK "+str(len(r)) if r else "нет (timeout)"))
        return r


    def _channel_queue(self, channel):
        """Возвращает очередь пакетов для канала (создаёт при необходимости)."""
        q = self._queues.get(channel)
        if q is None:
            q = queue.Queue()
            self._queues[channel] = q
        return q

    def _start_keepalive(self, interval=15.0):
        """Фоновый поток повторной подписки (0x200) каждые ~interval сек.

        Сервер «отписывает» клиента, если долго не видит повторной подписки,
        и перестаёт пушить. Таймер держит подписку живой на время долгих
        GET-опросов и активных сессий. Гейтится по `_running` — при close()
        или смене сессии останавливается.
        """
        if self.keepalive_thread and self.keepalive_thread.is_alive():
            return self.keepalive_thread
        if not self._running or not self.sock:
            return None

        def loop():
            while self._running and self.sock is not None:
                time.sleep(interval)
                if not self._running or self.sock is None:
                    break
                try:
                    pkt = self._build(CMD_EVENT, 0x01, 0x200, self._subscribe_payload())
                    with self._send_lock:
                        self.sock.sendto(pkt, (self.host, self.port))
                except Exception:  # pragma: no cover
                    continue

        t = threading.Thread(target=loop, daemon=True, name="akvilon-keepalive")
        self.keepalive_thread = t
        t.start()
        return t

    def _stop_keepalive(self):
        if self.keepalive_thread and self.keepalive_thread.is_alive():
            try:
                self.keepalive_thread.join(timeout=0.5)
            except Exception:
                pass
        self.keepalive_thread = None

    def start_reader(self):
        """Запускает ЕДИНСТВЕННЫЙ фоновый поток, который владеет сокетом.

        Он читает ВСЕ входящие пакеты, отвечает ACK на пуш-сообщения (cmd=2/3),
        чтобы сервер продолжал слать, и раскладывает пакеты по очередям выбранных
        каналов. get_list НЕ читает сокет напрямую — только эти очереди.
        Это ключ к надёжности: нет двух recvfrom, нет потери пакетов.
        """
        if self._reader_thread and self._reader_thread.is_alive():
            return self._reader_thread
        self._running = True
        self._start_keepalive()

        def loop():
            try:
                self.sock.settimeout(1.5)
            except Exception:
                pass
            while self._running:
                try:
                    d, _ = self.sock.recvfrom(MAX_UDP)
                except socket.timeout:
                    continue
                except Exception:
                    continue
                if len(d) < MIN_PKT:
                    continue
                h = d[:HEADER_LEN]
                self._last_rx = time.monotonic()
                self._send_ack(h)
                with self._inbox_lock:
                    self._inbox.append(d)
                ch = struct.unpack_from("<I", h, 0x38)[0]
                q = self._queues.get(ch)
                if q is not None:
                    q.put(d)

        t = threading.Thread(target=loop, daemon=True)
        self._reader_thread = t
        t.start()
        return t

    def _pop_inbox(self, channel, timeout=0):
        """Достаёт пакет из очереди целевого канала (blocking до timeout сек).

        Идём через очередь канала, которую наполняет фоновый ридер. Если ридер
        не запущен, читаем сокет напрямую (обратная совместимость).
        """
        self.start_reader()
        q = self._channel_queue(channel)
        try:
            return q.get(timeout=timeout) if timeout > 0 else q.get_nowait()
        except queue.Empty:
            return None

    def _is_header(self, d, channel):
        """True, если пакет — бинарный заголовок списка канала (u32 count + записи)."""
        if len(d) < HEADER_LEN + 4 + MD5_LEN:
            return False
        h = d[:HEADER_LEN]
        if h[0x36] != CMD_GET or h[0x37] != FLAG_OK:
            return False
        if struct.unpack_from("<I", h, 0x38)[0] != channel:
            return False
        payload = d[HEADER_LEN:len(d) - MD5_LEN]
        if payload.startswith(b'{') or payload.startswith(b'['):
            return False
        if len(payload) < 4:
            return False
        cand = struct.unpack_from("<I", payload, 0)[0]
        # count должен укладываться в полезную длину заголовка: 4 + count*16 + хвост
        return 0 < cand < 5000 and len(payload) >= 4 + cand * 16

    def _header_count(self, d):
        payload = d[HEADER_LEN:len(d) - MD5_LEN]
        return struct.unpack_from("<I", payload, 0)[0]

    def _get_header(self, channel, header_timeout=4.0, retries=2):
        """GET-ALL на текущей сессии, возвращает (count, [(oid, rflag), ...]).

        Повторяет GET-ALL при одиночной потере датаграммы (retries раз), не
        поднимая свежую сессию — сервер обычно отвечает на повтор сразу.
        """
        self.start_reader()
        q = self._channel_queue(channel)
        try:
            while True:
                q.get_nowait()
        except queue.Empty:
            pass
        for _ in range(max(1, retries + 1)):
            try:
                pkt = self._build(CMD_GET, 0x00, channel, get_list_payload(1, -1, 0, 0))
                with self._send_lock:
                    self.sock.sendto(pkt, (self.host, self.port))
            except Exception:
                return None, []
            deadline = time.time() + header_timeout / max(1, retries + 1)
            while time.time() < deadline:
                try:
                    d = q.get(timeout=0.5)
                except queue.Empty:
                    continue
                if self._is_header(d, channel):
                    payload = d[HEADER_LEN:len(d) - MD5_LEN]
                    count = struct.unpack_from("<I", payload, 0)[0]
                    rec_total = min(count, (len(payload) - 4) // 16)
                    ids = []
                    for i in range(rec_total):
                        rec = payload[4 + i * 16: 4 + (i + 1) * 16]
                        if len(rec) < 16:
                            continue
                        oid = struct.unpack_from("<q", rec, 4)[0]
                        rflag = struct.unpack_from("<I", rec, 12)[0]
                        ids.append((oid, rflag))
                    return count, ids
        return None, []

    def _fetch_one(self, channel, oid, rflag, idx, wait=1.6):
        """Шлёт type=2 GET по одному id и ждёт JSON-тело ответа.

        Сервер Аквилон отвечает на последовательные type=2 GET заметно
        надёжнее, чем на пачку сразу: поэтому запрашиваем по одному, ждём
        тело, и только потом шлём следующий.
        """
        self.sock.sendto(self._build(CMD_GET, 0x00, channel,
                                     get_list_payload(2, oid, rflag, idx)),
                         (self.host, self.port))
        q = self._channel_queue(channel)
        start = time.time()
        while time.time() - start < wait:
            try:
                d = q.get(timeout=0.25)
            except queue.Empty:
                continue
            if len(d) < MIN_PKT:
                continue
            p = d[HEADER_LEN:len(d) - MD5_LEN]
            if not (p.startswith(b'{') or p.startswith(b'[')):
                continue
            try:
                return json.loads(p.decode("utf-8", "replace"))
            except Exception:
                return None
        return None

    def get_list(self, channel, timeout=30.0, sessions=6, batch=9) -> list:
        """GET-ALL списка по каналу. Возвращает список JSON-объектов.

        Сервер объявляет в бинарном заголовке полный count (напр. 69 камер),
        но по-настоящему надёжно отдаёт тело на последовательный type=2 GET
        (по одному, с маленькой паузой), и только ~18 тел за одну UDP-сессию.
        Поэтому:

          * получаем полный список id из заголовка и НАКАПЛИВАЕМ id по сессиям
            (объединение — более поздний, более полный заголовок не затирает
            ранее известные id);
          * запрашиваем по одному телу для каждого id (пачками по batch);
          * если за сессию что-то не пришло — повторяем недостающие в свежей
            сессии (сервер отдаёт список снова); внутри сессии тоже повторяем
            проспанную порцию один раз (устойчивость к одиночной потере);
          * НЕ отдаём неполный банк как «финальный» молча: если объявленный
            count не был собран, обязательно логируем предупреждение.

        Возвращаем только реально полученные объекты (в порядке появления id).
        """
        if self.sock is None:
            self._new_session()
        self.last_list_count = None
        seen = {}
        order = []
        declared_max = 0
        known_ids = {}  # oid -> rflag, объединяем по сессиям

        start_wall = time.monotonic()
        attempts = max(1, sessions)
        # Общий бюджет времени: не даём get_list висеть дольше timeout даже при
        # большом sessions (защита от «вечного» цикла на полуживом сервере).
        budget = max(5.0, min(timeout, attempts * 12.0))
        for attempt in range(attempts):
            if time.monotonic() - start_wall > budget:
                break
            count, ids = self._get_header(channel)
            if count:
                declared_max = max(declared_max, count)
            for oid, rflag in ids:
                known_ids.setdefault(_safe_str(oid), (oid, rflag))

            # Идём от объявленного count: если запросили больше id, чем сервер
            # реально прислал в заголовке — это уже все известные id.
            if not known_ids:
                # сессия не ответила заголовком — свежая сессия и повтор
                if attempt < attempts - 1 and time.monotonic() - start_wall <= budget:
                    self._new_session()
                continue

            self._collect_bank(channel, seen, order, known_ids, declared_max, batch)
            if declared_max and len(seen) >= declared_max:
                break
            if all(_safe_str(o) in seen for o in list(known_ids)):
                break
            if attempt < attempts - 1 and time.monotonic() - start_wall <= budget:
                self._new_session()
        result = [seen[o] for o in order]
        self.last_list_count = declared_max or len(result)
        if declared_max and len(result) < declared_max:
            _LOG.warning(
                "[akvilon_home] get_list ch=0x%X собрано %d/%d тел за %d сессий",
                channel, len(result), declared_max, attempts,
            )
        return result

    def _collect_bank(self, channel, seen, order, known_ids, declared_max, batch):
        """Собирает JSON-тела для известных id пачками; повтор проспанного раза.

        `known_ids`: dict {str_oid: (int_oid, rflag)}. Накопление (`seen`/`order`)
        переживает сессии: объекты, уже полученные в прошлых сессиях, не
        запрашиваются повторно.
        """
        q = self._channel_queue(channel)

        def _drain(deadline):
            """Вычитывает JSON-тела из очереди до deadline, возвращает найденные."""
            added = 0
            while time.monotonic() < deadline:
                try:
                    d = q.get(timeout=0.1)
                except queue.Empty:
                    continue
                if len(d) < MIN_PKT:
                    continue
                p = d[HEADER_LEN:len(d) - MD5_LEN]
                if not (p.startswith(b'{') or p.startswith(b'[')):
                    continue
                try:
                    o = json.loads(p.decode("utf-8", "replace"))
                except Exception:
                    continue
                if isinstance(o, dict) and o.get("objectid"):
                    oid_s = _safe_str(o.get("objectid") or o.get("objectId"))
                    if oid_s and oid_s not in seen:
                        seen[oid_s] = o
                        order.append(oid_s)
                        added += 1
            return added

        def _missing():
            return [(oid_int, rflag) for oid_s, (oid_int, rflag) in known_ids.items()
                    if oid_s not in seen]

        def _send_ids(items, idx_base):
            for i, (oid_int, rflag) in enumerate(items):
                try:
                    pkt = self._build(CMD_GET, 0x00, channel,
                                      get_list_payload(2, oid_int, rflag, idx_base + i + 1))
                    with self._send_lock:
                        self.sock.sendto(pkt, (self.host, self.port))
                except Exception:  # pragma: no cover
                    continue

        initial_missing = _missing()
        if not initial_missing:
            return
        for i in range(0, len(initial_missing), batch):
            chunk = initial_missing[i:i + batch]
            _send_ids(chunk, i)
            time.sleep(0.05)
            _drain(time.monotonic() + 0.6)
            if declared_max and len(seen) >= declared_max:
                return
        # повторное дослат проспанных id (одиночная потеря): если за первую
        # волну что-то не пришло — шлём ещё раз перед сменой сессии.
        still = _missing()
        if still and not (declared_max and len(seen) >= declared_max):
            for i in range(0, len(still), batch):
                chunk = still[i:i + batch]
                _send_ids(chunk, i)
                time.sleep(0.05)
                _drain(time.monotonic() + 0.6)
                if declared_max and len(seen) >= declared_max:
                    return

    def open_camera(self, cam_id):
        """Открыть камеру: cmd=3 flag=0 на 0x30401, {"id":"...","name":"openCamera"}."""
        payload = json.dumps({"id": str(cam_id), "name": "openCamera"},
                             separators=(",", ":")).encode("utf-8")
        return self.send(CMD_EVENT, 0x00, 0x30401, payload, state_number=self._next_seq(),
                         timeout=6.0)

    def request_camera_settings(self, cam_id):
        """Открывает камеру и возвращает cameraSettings (порт/токен/SPS/PPS).

        Отправляет openCamera на 0x30401 и ловит JSON c videoPort в ответе
        (приходит на канал 0x2030401). Именно здесь сервер отдаёт реальные
        параметры RTP-потока: videoPort, videoHost, videoToken, spropParameter.
        """
        self.start_reader()
        payload = json.dumps({"id": str(cam_id), "name": "openCamera"},
                             separators=(",", ":")).encode("utf-8")
        self.sock.sendto(self._build(CMD_EVENT, 0x00, 0x30401, payload,
                                     state_number=self._next_seq(),
                                     state_time=int(time.time() * 1000)),
                         (self.host, self.port))
        target = str(cam_id)
        # Собираем ВСЕ входящие JSON-пакеты после запроса ищем объект с videoPort
        # (канал может отличаться, поэтому сканируем общий inbox, а не одну очередь)
        deadline = time.time() + 8.0
        while time.time() < deadline:
            pkts = list(self._queues.values())
            for q in pkts:
                try:
                    while True:
                        d = q.get_nowait()
                        if len(d) < MIN_PKT:
                            continue
                        pd = d[HEADER_LEN:len(d) - MD5_LEN]
                        if not pd.startswith(b'{'):
                            continue
                        obj = json.loads(pd.decode("utf-8", "replace"))
                        if not isinstance(obj, dict):
                            continue
                        if "videoPort" in obj or "spropParameter" in obj:
                            return obj
                except Exception:
                    pass
            if self._inbox:
                with self._inbox_lock:
                    for d in self._inbox:
                        if len(d) < MIN_PKT:
                            continue
                        pd = d[HEADER_LEN:len(d) - MD5_LEN]
                        if pd.startswith(b'{'):
                            try:
                                obj = json.loads(pd.decode("utf-8", "replace"))
                                if isinstance(obj, dict) and ("videoPort" in obj or "spropParameter" in obj):
                                    return obj
                            except Exception:
                                pass
            time.sleep(0.2)
        return None

    def send_video_token(self, vhost: str, vport: int, video_token: str):
        """Запускает RTP-поток камеры: шлёт подписочный пакет на видео-порт.

        Точный формат подписки (восстановлен по pcap приложения inHome):
        UDP-датаграмма = b"\\x00\\x00" + ascii(videoToken), отправляемая на
        videoHost:videoPort. После этого сервер стримит RTP/H.264 на тот же
        клиентский UDP-порт, с которого был отправлен пакет.
        """
        payload = b"\x00\x00" + str(video_token).encode("ascii")
        try:
            self.sock.sendto(payload, (vhost, int(vport)))
            return True
        except Exception as exc:  # pragma: no cover
            _LOG.debug("[akvilon_home] send_video_token err: %s", exc)
            return False

    def close_camera(self, cam_id="0:-1"):
        payload = json.dumps({"id": str(cam_id), "name": "closeCamera"},
                             separators=(",", ":")).encode("utf-8")
        return self.send(CMD_EVENT, 0x00, 0x30401, payload,
                         state_number=self._next_seq(), timeout=6.0)

    def open_gate(self, gate_id) -> bool:
        """Открывает проход/калитку/домофон по реальному трафику приложения.

        Реальное открытие калитки идёт НЕ через open_camera (0x30401), а через
        канал 0x30301 (door buttons / CHANNEL_DOOR_BUTTONS) с JSON
        {"action":"open","id":"<флаг:id>","type":65536}.
        Подтверждено рабочим скриптом akvilon_sync.py (поле GATE_PAYLOAD).
        """
        payload = json.dumps({
            "action": "open",
            "id": str(gate_id),
            "type": 65536,
        }, ensure_ascii=False).encode("utf-8")
        resp = self.send(CMD_EVENT, 0x00, CHANNEL_DOOR_BUTTONS, payload,
                         state_number=self._next_seq(), timeout=6.0)
        return resp is not None

    def send_keepalive(self):
        """Keepalive каждые 15 сек: повтор подписки ch=0x200."""
        return self.subscribe()