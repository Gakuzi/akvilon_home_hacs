"""Пуш-звонок домофона (Feature C).

Механика: когда в домофон звонят — интеграция должна уметь ОТЛОВИТЬ событие
вызова от сервера здания и превратить его в HA-событие ``akvilon_home_ding``
(payload {"domain", "object_id", "type":"call", ...}), а автоматизация
пользователя уже решает, как показать уведомление/звонок (см. сервис
``akvilon_home.ding_notify``).

Как это работает:

* UDP-клиент (``protocol.AkvilonClient``) подписан на каналы (0x200) и держит
  фоновый ридер, который складывает ВСЕ входящие присылаемые сервером пакеты
  в ``client._inbox``.
* ``DingListener`` держит собственную постоянную подписанную сессию и в фоновом
  потоке просматривает ``_inbox``, распознавая событие вызова через
  ``classify_incoming``.
* При распознанном вызове слушатель вызывает обработчик, который постит
  HA-событие на event-loop через ``call_soon_threadsafe`` (не блокируя loop).
* ``async_setup_ding(hass, hub)`` — точка интеграции: регистрирует сервис
  ``ding_notify`` и запускает слушателя. Его вызывает ``__init__.async_setup_entry``.

Честность (AGENTS.md §8): на этом здании канал домофонов (0x10403) пуст
(домофонов 0), реальный формат события вызова НЕ измерен в трафике. Поэтому
детектор консервативен: он распознаёт только пакет, который по cmd=3 (EVENT) и
JSON-полям явно похож на вызов (см. ``DING_CALL_KEYS``). Всё остальное
возвращает ``None`` и ничего не эмитит — механика ГОТОВА и безопасно
деградирует при отсутствии данных вызова, ничего не роняя.
"""
import base64
import json
import logging
import struct
import threading

from .const import (
    DOMAIN,
    EVENT_DING,
    SERVICE_DING_NOTIFY,
    DING_TYPE_CALL,
    DING_CALL_KEYS,
)
from .protocol import HEADER_LEN, MD5_LEN, CMD_EVENT, AkvilonClient

_LOGGER = logging.getLogger(__name__)


def _is_active(value) -> bool:
    """True, если значение поля «активно» (звонок идёт), а не пусто/выкл."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        s = value.strip().lower()
        if s in ("", "0", "false", "off", "no", "none", "null"):
            return False
        return True
    if isinstance(value, (dict, list)):
        return bool(value)
    return value is not None


def _looks_like_call(obj: dict) -> bool:
    """Эвристика: является ли JSON-объект событием «вызов домофона».

    Консервативно: True только при явном признаке вызова (одно из полей
    ``DING_CALL_KEYS`` активно, либо поле name/type явно указывает на вызов).
    Иначе False — пакет игнорируется (безопасная деградация).
    """
    for key in DING_CALL_KEYS:
        if key in obj and _is_active(obj[key]):
            return True
    typ = str(obj.get("type") or obj.get("name") or obj.get("action") or "").lower()
    if any(t in typ for t in ("call", "calling", "ring", "vcall", "intercom")):
        return True
    return False


def _safe_summary(obj: dict) -> str:
    """Краткое безопасное описание для логов/названия (без личных данных)."""
    for k in ("name", "Name", "title", "gateName", "camName", "deviceName"):
        v = obj.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()[:80]
    return ""


def _object_id(obj: dict, channel: int) -> str:
    """Извлекает идентификатор вызывающего устройства из полей JSON."""
    for k in ("objectid", "objectId", "id", "gateId", "camId", "cameraId",
              "deviceId", "intercomId"):
        v = obj.get(k)
        if v is not None and str(v) not in ("", "0", "0:-1", "None"):
            return str(v)
    # fallback: канал + хвост объекта (как в остальной интеграции)
    return f"{channel:x}"


def classify_incoming(data: bytes):
    """Распознаёт событие вызова домофона во входящем UDP-пакете.

    Возвращает payload-словарь:
        {"type": "call", "domain": "akvilon_home", "object_id": "<id>",
         "channel": <int>, "label": "<имя или пусто>"}
    либо ``None``, если пакет не является распознаваемым событием вызова.

    Типы пакетов, которые игнорируются (не события вызова): бинарные списки
    (cmd=1), ACK (cmd=2), JSON без признаков вызова (cmd=3), короткие пакеты.
    """
    if not data or len(data) < HEADER_LEN + MD5_LEN:
        return None
    hdr = data[:HEADER_LEN]
    if hdr[0x36] != CMD_EVENT:  # cmd=3 (EVENT) — только события
        return None
    channel = struct.unpack_from("<I", hdr, 0x38)[0]
    payload = data[HEADER_LEN:len(data) - MD5_LEN]
    if not payload.startswith(b'{'):
        return None
    try:
        obj = json.loads(payload.decode("utf-8", "replace"))
    except Exception:
        return None
    if not isinstance(obj, dict) or not _looks_like_call(obj):
        return None
    return {
        "type": DING_TYPE_CALL,
        "domain": DOMAIN,
        "object_id": _object_id(obj, channel),
        "channel": channel,
        "label": _safe_summary(obj),
    }


def build_ding_message(payload: dict) -> str:
    """Собирает текст уведомления о вызове из payload события.

    Чистая функция (тестируемая). Пример: «Звонок в домофон <имя/ид>».
    """
    label = str(payload.get("label") or "").strip()
    oid = str(payload.get("object_id") or "").strip()
    who = label or oid or "домофон"
    return f"Звонок в домофон {who}"


class DingListener:
    """Фоновый слушатель событий вызова домофона на постоянной UDP-сессии.

    Держит собственную подписанную сессию (без ``register()``, чтобы не
    портить UDP-сессию — см. ``coordinator.open_gate``/``get_camera_settings``)
    и фоновый поток, просматривающий ``client._inbox``. Изолирован от
    короткоживущих сессий, которые создают refresh/open_gate/camera_frame.
    """

    def __init__(self, hub, handler=None, client_factory=None):
        self._hub = hub
        self._handler = handler          # callable(payload) — вызывается из фонового потока
        self._client_factory = client_factory  # для тестов (фейковый клиент)
        self._client = None
        self._stop = threading.Event()
        self._thread = None
        self._watermark = 0              # монотонный индекс рассмотренных пакетов _inbox

    def start(self):
        """Поднимает постоянную подписанную сессию и запускает фоновый поток.

        Повторный вызов идемпотентен (если поток уже жив — ничего не делает).
        """
        if self._thread and self._thread.is_alive():
            return self
        if self._client_factory is not None:
            self._client = self._client_factory()
        else:
            cl = AkvilonClient(
                self._hub.host, self._hub.port, self._hub.token,
                device_id=self._hub.device_id,
                server_id=self._hub.server_id,
                pass_hex=self._hub.token,
            )
            cl.connect()
            cl.subscribe()      # 0x200 — получаем push-события сервера
            cl.start_reader()   # фоновый ридер складывает пакеты в _inbox
            self._client = cl
        self._stop.clear()
        self._watermark = 0
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="akvilon-ding"
        )
        self._thread.start()
        return self

    def stop(self):
        """Останавливает слушателя и закрывает его UDP-сессию (идемпотентно)."""
        self._stop.set()
        if self._client is not None:
            try:
                self._client._running = False
            except Exception:  # pragma: no cover
                pass
            try:
                self._client.close()
            except Exception:  # pragma: no cover
                pass
            self._client = None
        if self._thread is not None and self._thread.is_alive():
            try:
                self._thread.join(timeout=1.0)
            except Exception:  # pragma: no cover
                pass
        self._thread = None
        return self

    @property
    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _run(self):
        while not self._stop.is_set():
            try:
                self._scan_inbox()
            except Exception as exc:  # pragma: no cover
                _LOGGER.debug("[akvilon_home] ding: ошибка сканирования: %s", exc)
            self._stop.wait(0.5)

    def _scan_inbox(self):
        """Просматривает новые пакеты ``client._inbox`` и реагирует на вызов.

        Использует монотонный ``_watermark``: каждый пакет обрабатывается ровно
        один раз, повторная эмиссия события исключена.
        """
        cl = self._client
        if cl is None:
            return
        try:
            inbox = getattr(cl, "_inbox", None) or []
            total = len(inbox)
        except Exception:  # pragma: no cover
            return
        for i in range(self._watermark, total):
            try:
                d = inbox[i]
            except IndexError:  # pragma: no cover
                break
            payload = classify_incoming(d)
            if payload is None:
                continue
            _LOGGER.info("[akvilon_home] вызов домофона: %s", payload)
            if self._handler is not None:
                try:
                    self._handler(payload)
                except Exception as exc:  # pragma: no cover
                    _LOGGER.warning("[akvilon_home] обработка звонка: %s", exc)
        self._watermark = total


def _jpeg_to_data_uri(jpg: bytes) -> str:
    """Превращает JPEG-bytes в data-URI (для push-уведомлений с картинкой)."""
    return "data:image/jpeg;base64," + base64.b64encode(jpg).decode("ascii")


async def async_ding_notify(hass, hub, call):
    """Сервис ``akvilon_home.ding_notify`` — пуш о вызове домофона.

    Автоматизация-дружественный мостик: пользователь сам решает, когда и куда
    слать. Поддерживаемые поля (``call.data``):

    * ``title`` — заголовок (по умолчанию «Звонок в домофон <имя>»);
    * ``message`` — текст (по умолчанию build_ding_message от payload);
    * ``target`` — имя notify-платформы, например ``mobile_app_iphone``.
      БЕЗ target уведомление не отправляется (безопасная деградация, только лог);
    * ``camera_id`` — если задан, захватываем кадр камеры в executor и кладём
      как ``data.image`` (data-URI);
    * ``image`` — готовый путь/URL картинки (приоритетнее camera_id);
    * ``data`` — произвольный dict, пробрасывается в notify.data.

    НЕ делает жёсткой привязки: не эмитит событие и не требует сервера. Если
    нужен именно кадр с видеокамеры — передайте ``camera_id``, захват уйдёт в
    executor (async_add_executor_job), event-loop не блокируется.
    """
    data = dict((call.data or {}).get("data") or {}) if hasattr(call, "data") else {}
    # call.data — плоский dict в HA; но поддерживаем и вложенную 'data'
    flat = dict(getattr(call, "data", {}) or {})
    try:
        n_data = dict(flat.get("data") or {})
    except Exception:  # pragma: no cover
        n_data = {}
    n_data.update(data)

    title = flat.get("title") or f"Звонок в домофон {str(getattr(hub, 'name', '') or 'домофон')}"
    message = flat.get("message") or build_ding_message(flat)
    target = flat.get("target")
    camera_id = flat.get("camera_id")
    image = flat.get("image")

    # Картинка кадра камеры — захват в executor (не блокируем event-loop).
    if not image and camera_id:
        try:
            jpg = await hass.async_add_executor_job(
                hub.camera_frame, str(camera_id), 7.0
            )
            if jpg:
                image = _jpeg_to_data_uri(jpg)
        except Exception as exc:  # pragma: no cover
            _LOGGER.warning("[akvilon_home] кадр для звонка %s: %s", camera_id, exc)
    if image:
        n_data["image"] = image

    if not target:
        _LOGGER.info(
            "[akvilon_home] ding_notify: уведомление не отправлено (нет target): %s", title
        )
        return {"notification": False, "title": title, "reason": "no_target"}

    if not message:
        message = "Кто-то звонит в домофон"
    await hass.services.async_call(
        "notify", target,
        {"title": title, "message": message, "data": n_data or None},
        blocking=False,
    )
    _LOGGER.info("[akvilon_home] ding_notify → %s: %s", target, title)
    return {"notification": True, "title": title, "target": target}


def _post_event_to_loop(hass, payload):
    """Обёртка: постит HA-событие ``akvilon_home_ding`` на event-loop.

    Вызывается из фонового потока слушателя, поэтому использует
    ``call_soon_threadsafe`` — event-loop не блокируется.
    """

    def _fire():
        try:
            hass.bus.async_fire(EVENT_DING, payload)
        except Exception as exc:  # pragma: no cover
            _LOGGER.warning("[akvilon_home] async_fire(ding): %s", exc)

    try:
        hass.loop.call_soon_threadsafe(_fire)
    except Exception as exc:  # pragma: no cover
        _LOGGER.warning("[akvilon_home] post ding event: %s", exc)


async def async_setup_ding(hass, hub):
    """Интеграция пуша звонка: регистрирует сервис и запускает слушателя.

    Вызывается из ``__init__.async_setup_entry`` (либо автоматизацией владельца
    после мержа, т.к. ``__init__`` вне зоны этого фича-агента). Идемпотентна:
    повторная регистрация сервиса и повторный старт слушателя безопасны.
    Возвращает запущенный ``DingListener`` (или None, если сервер недоступен).
    """
    # Сервис регистрируется перезаписью — HA допускает повторную регистрацию.
    async def _service_handler(call):
        return await async_ding_notify(hass, hub, call)

    hass.services.async_register(DOMAIN, SERVICE_DING_NOTIFY, _service_handler)
    _LOGGER.info("[akvilon_home] сервис %s.%s зарегистрирован", DOMAIN, SERVICE_DING_NOTIFY)

    listener = DingListener(hub, handler=lambda p: _post_event_to_loop(hass, p))
    try:
        listener.start()
    except Exception as exc:  # pragma: no cover
        _LOGGER.warning("[akvilon_home] не удалось запустить слушатель звонка: %s", exc)
        return None
    _LOGGER.info(
        "[akvilon_home] слушатель вызова домофона запущен (домофонов с данными может быть 0)"
    )
    return listener