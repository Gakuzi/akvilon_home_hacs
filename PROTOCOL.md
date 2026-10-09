# PROTOCOL.md — Полное описание UDP-протокола Аквилон InHome

> Назначение документа: чтобы ЛЮБОЙ агент (субагент) мог воспроизвести работу
> интеграции без гадания. Здесь: авторизация, формат пакета, получение списка
> камер, многосессийный сбор, видео-поток, записи.
>
> Ветка-источник рабочего кода: **`feature/video-viewer`** репозитория
> `Gakuzi/akvilon_home` (приватный dev) / `Gakuzi/akvilon_home_hacs` (публичный).
> Ключевые файлы: `custom_components/akvilon_home/protocol.py`, `coordinator.py`,
> `viewer.py`, `rtp_stream.py`.

---

## 0. Быстрый старт (TL;DR)

- Сервер здания: **`127.0.0.1:19090` (UDP)**. НЕ `192.168.0.31` — тот адрес
  ЛВС-планшета агента, а не сервер камер.
- Авторизация = **MD5-подпись** каждого UDP-пакета секретом PASS. Никакого
  TCP-handshake/логина. Неверная подпись → сервер отвечает `flag=0x82` (ERR).
- Камеры лежат на канале **`0x10401`**. GET-ALL даёт бинарный заголовок с
  перечнем (обычно **69 камер**), а JSON-тела надо докачивать поштучно на
  нескольких свежих UDP-сессиях.
- Рабочие креденшалы владельца (приватные, для теста): host `127.0.0.1`,
  port `19090`, device_id `0:0`, server_id `7:48390`, PASS `PASS_PLACEHOLDER`.

---

## 1. АВТОРИЗАЦИЯ (критичный раздел)

Каждый исходящий UDP-датаграмма = **`header(64 байта) + payload + подпись(16 байт)`**.

### 1.1 Секрет подписи = PASS (не SUID, не token_hex)

Подпись считается по **ASCII-строке PASS** из QR-кода, а НЕ по hex-байтам.
В конструкторе (protocol.py):

```python
def __init__(self, host, port, token_hex, device_id="0:0", server_id="0:0",
             device_flag=119, pass_hex="PASS_PLACEHOLDER"):
    self.token = pass_hex.encode("ascii") if pass_hex else b""
```

**Ловушка:** в `AkvilonClient` секрет подписи лежит в `self.token`, а заполняется
из 6-го параметра `pass_hex`. Не перепутать с `token_hex` (3-й параметр, почти
не используется для подписи). В координаторе это делается так:

```python
def _new_client(self) -> AkvilonClient:
    cl = AkvilonClient(
        self.host, self.port, self.token,      # 3-й = token_hex
        device_id=self.device_id, server_id=self.server_id,
        pass_hex=self.token,                   # 6-й = секрет подписи ← важно!
    )
    cl.connect()
    cl.start_reader()
    return cl
```

### 1.2 Формула подписи

```python
def sign_packet(header, payload, token: bytes) -> bytes:
    """MD5(header[0x2e:0x40] + payload + token)"""
    return hashlib.md5(header[0x2e:0x40] + payload + token).digest()
```

То есть берутся **байты header с 0x2e по 0x40** (18 байт: stateTime..stateNumber),
добавляется payload и ASCII-секрет PASS, всё это MD5 (16 байт), дописывается в
конец датаграммы.

Полный пакет:
```python
pkt = header + payload + sign_packet(header, payload, self.token)
```

### 1.3 Признак ошибки авторизации

Если подпись неверна (или канал неверный), сервер отвечает пакетом с
**`flag = 0x82`** (бит 0x80 ошибки + 0x02). Это **`FLAG_ERR`**. Успешный пакет
обычно `flag = 0x02` (`FLAG_OK`) для ответов, либо `flag=0` для запросов.

---

## 2. ФОРМАТ ПАКЕТА (header 64 байта)

| Смещение | Поле | Комментарий |
|---|---|---|
| `0x00..0x07` | MAGIC | `0x0005000200011004` (LE) |
| `0x08..0x09` | subheader | `0x0010` |
| `0x0a..0x0d` | sequence | u32 LE, растёт на каждый пакет |
| `0x0e..0x1d` | dst A7ID | device:flag, напр. `0:0` |
| `0x1e..0x2d` | src A7ID | реально `0:1` (устройство) |
| `0x2e..0x35` | stateTime | qint64 LE, у GET = 0; у OPEN = ms-epoch |
| `0x36` | cmd | 1=GET, 2=данные/ACK, 3=EVENT |
| `0x37` | flag | 0=запрос, 0x02=OK/ACK, 0x82=ERR |
| `0x38..0x3b` | channel | u32, напр. `0x10401` |
| `0x3c..0x3f` | stateNumber | u32 |

Построение (protocol.py `build_header`):
```python
def build_header(cmd, flag, seq, channel, state_number=0, state_time=0,
                 src_id=None, dst_id=None):
    hdr = bytearray(64)
    struct.pack_into("<Q", hdr, 0x00, MAGIC)
    struct.pack_into("<H", hdr, 0x08, 0x0010)
    struct.pack_into("<I", hdr, 0x0a, seq & 0xFFFFFFFF)
    # dst
    f, oid = get_a7id(dst_id); hdr[0x0e:0x1e] = pack_a7id(f, oid)
    # src
    f, oid = get_a7id(src_id);  hdr[0x1e:0x2e] = pack_a7id(f, oid, version=0)
    struct.pack_into("<q", hdr, 0x2e, state_time)
    hdr[0x36] = cmd;  hdr[0x37] = flag
    struct.pack_into("<I", hdr, 0x38, channel & 0xFFFFFFFF)
    struct.pack_into("<I", hdr, 0x3c, state_number)
    return bytes(hdr)
```

A7ID = `pack_a7id(flag, oid, version)`:
```python
struct.pack("<q", oid) + struct.pack("<i", flag) + struct.pack("<i", version)
```

---

## 3. КАНАЛЫ (CRITICAL)

| Канал | Назначение |
|---|---|
| `0x200` | подписка на каналы (cmd=3 flag=0x01) |
| `0x10401` | **КАМЕРЫ** (GET-список) |
| `0xE0401` | калитки/двери (GET-список) |
| `0x20401` | счётчики (GET-список) |
| `0x90401` | пользователи (GET-список) |
| `0x10403` | домофоны (на этом здании = 0) |
| `0x30401` | openCamera / closeCamera |
| `0x2030401` | cameraSettings (ответ openCamera) |
| `0x30301` | кнопка открытия двери/калитки |
| `0x02020001` | регистрация приложения (иногда не нужна!) |

**Важно:** для камер (0x10401) регистрация `register()`/`subscribe()` не требуется
и даже ВРЕДНА: после `register()` сервер может отвечать `0x82` и камеры не
приходят. Достаточно подписанного GET.

---

## 4. ПОЛУЧЕНИЕ СПИСКА КАМЕР (почему 1, а не 69)

### 4.1 GET-ALL возвращает только бинарный заголовок

Payload GET-ALL (ровно 32 байта):
```python
def get_list_payload(req_type=1, object_id=-1, flag=0, counter=0):
    return (struct.pack("<I", req_type)
            + struct.pack("<q", object_id)
            + struct.pack("<I", flag)
            + struct.pack("<Q", 0)
            + struct.pack("<Q", counter))
```
- `req_type=1` → GET-ALL
- `object_id=-1` (0xFFFF...FF) → «все»

Ответ — бинарный заголовок:
- `u32 count` (например **69**)
- далее записи по **16 байт** `[u32 crc][u64 objectId][u32 flag]`

Парсинг заголовка (protocol.py `_get_header`):
```python
count = struct.unpack_from("<I", payload, 0)[0]
rec_total = min(count, (len(payload) - 4) // 16)
for i in range(rec_total):
    rec = payload[4 + i*16 : 4 + (i+1)*16]
    oid   = struct.unpack_from("<q", rec, 4)[0]
    rflag = struct.unpack_from("<I", rec, 12)[0]
    ids.append((oid, rflag))
```

### 4.2 JSON-тела докачиваются поштучно

Для каждого id отправляется `GET` с `req_type=2`:
```python
get_list_payload(2, oid, rflag, idx)
```
Ответ — JSON-объект с полем `objectid`. Сервер **надёжно** отдаёт тело только
на последовательный запрос по одному id (с паузой), а не на пачку сразу.

### 4.3 Главный секрет: НЕСКОЛЬКО СВЕЖИХ СЕССИЙ

Сервер за **одну UDP-сессию** отдаёт лишь ~18 тел, потом зависает. Поэтому
`get_list()` делает несколько раундов:
1. получить полный список id из заголовка (69);
2. запросить тела пачками по `batch=9`, собрать ответы;
3. если собрано не всё — **поднять новую сессию** (`_new_session()` = новый
   socket + заново) и запросить только недостающие id;
4. повторять, пока не соберём все (или не закончатся попытки).

Именно это даёт **все 69 камер**. Если сделать один GET и прочитать один ответ —
получится 1 камера/заголовок, что и происходило у других агентов.

### 4.4 Проверка работы

Рабочий сниппет (голый UDP, с правильной подписью):
```python
import socket, struct
def pack(host, port, payload, seq, ch=0x10401, cmd=1, flag=0,
         dst="0:0", src="0:1", secret=b"PASS_PLACEHOLDER"):
    hdr = build_header(cmd, flag, seq, ch, src_id=src, dst_id=dst)
    return hdr + payload + sign_packet(hdr, payload, secret)
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.sendto(pack("127.0.0.1",19090, get_list_payload(1,-1,0,0), 1),
         ("127.0.0.1",19090))
```

---

## 5. ВИДЕО-ПОТОК КАМЕРЫ (RTP/H.264)

### 5.1 Цепочка
1. `openCamera` (cmd=3, канал `0x30401`, JSON `{"id":"<flag>:<oid>","name":"openCamera"}`)
   с `state_time=int(time.time()*1000)` — БЕЗ state_time сервер отвечает пустым
   ACK и не присылает настройки.
2. Сервер отвечает на канал `0x2030401` **cameraSettings**:
   ```json
   { "name": "...", "objectid": "1:0",
     "spropParameter": "Z00A...", "videoCodec": "264",
     "videoHost": "127.0.0.1", "videoPort": "5310",
     "videoToken": "token_0:0" }
   ```
3. Запуск RTP: на `videoHost:videoPort` отправить UDP-датаграмму
   **`b"\x00\x00" + ascii(videoToken)`**.
4. RTP/H.264 (payload type 96, FU-A/STAP-A) приходит на клиентский порт, с
   которого был отправлен токен. Собираем IDR-кадр (type 5), добавляем SPS/PPS
   из `spropParameter`, декодим через ffmpeg в JPEG.

### 5.2 Ключевые методы
- `open_camera()` — в protocol.py.
- `request_camera_settings()` — ловит cameraSettings на `0x2030401`.
- `send_video_token(vhost, vport, video_token)` — шлёт `b"\x00\x00"+token`.
- `RtpStream._kick()` — то же (в rtp_stream.py).
- `hub.camera_frame(cam_id, timeout)` — полный захват кадра (open→settings→RTP→JPEG),
  см. coordinator.py. Вызывать строго в executor (блокирующий).

### 5.3 Риски / лимиты
- Сервер ограничивает частые `openCamera` (rate-limit). Не открывать десятки камер
  одновременно. Панель сериализует захваты через `grab_lock`.
- `state_time` обязателен в openCamera (иначе нет cameraSettings).

---

## 6. ЗАПИСЬ ВИДЕО (MP4)

Реализовано в `viewer.py` класс `Recorder`:
- `/record/start?id=<cam>` — POST: поднимает ffmpeg (`-f image2pipe -framerate 2 -c:v mjpeg`
  на stdin → `libx264` → `.mp4`), фоновый поток циклически тянет `hub.camera_frame(cam)`
  и пишет JPEG в stdin ffmpeg.
- `/record/stop` — POST: закрывает stdin, ffmpeg финализирует `.mp4`.
- `/record/status` — GET: `{running, cam, name, file, secs}`.
- `/recordings` — GET: JSON-список записей (имя + размер).
- `/file/<name>` — GET: скачивание mp4.

Запись привязана к **камере**, а не к выбранной в UI: переключение камер в
панели не прерывает текущую запись.

Папка записей по умолчанию: `C:\Users\eklim\Videos\Аквилон` (в WSL —
`/mnt/c/Users/eklim/Videos/Аквилон`), задаётся env `AKVILON_REC_DIR`.

---

## 7. ВЕБ-ПАНЕЛЬ (viewer.py)

- HTTP-сервер `http://0.0.0.0:8090/`.
- `/snap/<camId>` — одиночный JPEG (с кэшем ~8с; для живого используй `force`).
- `/mjpeg/<camId>` — живой MJPEG-поток (с `force=True` у `_cam_frame`, иначе
  кэш «замораживает» картинку).
- `/record/*`, `/recordings`, `/file/*` — запись (см. §6).
- Фронтенд: современный тёмный UI, ленивая загрузка снимков (IntersectionObserver),
  индикаторы LIVE/FPS/часы, кнопка записи с REC-таймером.

**Важный фикс:** в `/snap/` и `/mjpeg/` id из URL надо декодировать через
`unquote()`, потому что фронтенд кодирует `:` как `%3A`:
```python
from urllib.parse import urlparse, unquote
self._snap(unquote(path[len("/snap/"):]))
```

---

## 8. ТИПОВЫЕ ОШИБКИ И ИХ ПРИЧИНЫ

| Симптом | Причина | Решение |
|---|---|---|
| Сервер отвечает `flag=0x82` | неверная подпись | передать PASS в `pass_hex` |
| Получается 1 камера вместо 69 | один GET без многосессий | использовать `get_list()` целиком |
| Камеры не приходят после register | `register()` ломает сессию | убрать subscribe/register для камер |
| videoSettings нет | нет `state_time` в openCamera | добавить `state_time=int(time.time()*1000)` |
| В браузере no картинки | не декодируется `%3A` | `unquote` в `/snap/` и `/mjpeg/` |
| MJРEG «заморожен» | кэш в `_cam_frame` | `force=True` для mjpeg |
| Камера даёт пусто | нет SPS/PPS на сервере | принять как особенность камеры |

---

## 9. СВЯЗАННЫЕ ФАЙЛЫ И КЛАССЫ

- `protocol.py` — AkvilonClient: подпись, build_header, get_list, open_camera.
- `coordinator.py` — AkvilonHub: _new_client, refresh, camera_frame.
- `rtp_stream.py` — RtpStream: приём RTP/H.264, _kick.
- `viewer.py` — ViewerServer, Recorder, HTTP-панель.
- `camera.py` — сущность AkvilonCamera в HA.

Классы из разобранного APK (для углубления):
`A7RtpClient` (sendToken/sendKeepAlive), `A7VideoRtp`, `ProxyConnection`
(videoPortRtp/voicePortRtp), `A7VoicePhone` (голос), `JooaWSProxyConnector`.