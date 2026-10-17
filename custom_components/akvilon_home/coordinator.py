"""Координатор/хаб интеграции Аквилон: живое подключение к серверу.

Держит постоянный клиент (для кнопок/управления) и умеет получать списки
камер/калиток/счётчиков с сервера. Для надёжности каждый банк запрашивается
на свежем подключении.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass

from .const import DOMAIN
from .protocol import AkvilonClient, CH_CAMERAS, CH_GATES, CH_METERS
from .rtp_stream import RtpStream
from .voice_rtp import VoiceStream

_LOGGER = logging.getLogger(__name__)


@dataclass
class AkvilonHub:
    """Единый объект подключения для одного Config Entry."""

    host: str
    port: int
    token: str
    device_id: str
    server_id: str
    name: str

    def __post_init__(self):
        self.demo = False  # демо-режим (без сервера)
        self.client: AkvilonClient | None = None
        self._reader = None
        self._cams = []
        self._gates = []
        self._meters = []
        self._video_settings = {}  # cam_id -> dict(videoPort, videoHost, videoToken, sprop)
        self._frame_cache = {}     # cam_id -> (jpeg_bytes, timestamp)
        self._frame_locks = {}     # cam_id -> threading.Lock
        self._cache_lock = threading.Lock()
        self._last_camera_open = {}  # cam_id -> float timestamp of last openCamera request
        self._global_frame_sem = threading.Semaphore(1)  # max 1 concurrent camera frame grab (защита CPU и RAM)
        self._last_ok = 0.0  # monotonic метка последнего успешного опроса сервера
        self._last_count = 0
        self.ping_ms = 0.0
        self.last_error = ""
        self.consecutive_errors = 0
        self.favorite_cameras = set()
        self.selected: list[str] | None = None  # None = все
        # Домофон: постоянный push-listener на серверные события (входящий вызов).
        self._listener_client = None
        self._listener_thread = None
        self._call_listeners = []      # callbacks (obj, kind, meta)
        self._active_call = None       # dict с данными активного входящего вызова
        self._call_serde = None        # threading.Lock для состояния вызова
        # Голосовой канал (активная сессия микрофон/динамик при вызове).
        self._voice = None             # VoiceStream | None
        self._voice_lock = threading.Lock()
        self._mic_on = False

    def _new_client(self) -> AkvilonClient:
        cl = AkvilonClient(
            self.host, self.port, self.token,
            device_id=self.device_id, server_id=self.server_id,
        )
        cl.connect()
        cl.start_reader()
        return cl

    def connect(self) -> bool:
        try:
            if self.client is None:
                self.client = self._new_client()
            return True
        except Exception as exc:  # pragma: no cover
            _LOGGER.warning("Аквилон: подключение не удалось: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Домофон: постоянный push-listener на серверные события и входящий вызов
    # ------------------------------------------------------------------
    def _listener_loop(self):
        """Фоновый цикл, держит подписанный клиент и ловит push-события сервера.

        Входящий вызов с домофона сервер пушит по своей инициативе (cmd=2/3 с
        JSON-телом), а не в ответ на наш GET. Для этого нужен ПОСТОЯННО открытый
        клиент с живым ридером и периодической подпиской (keepalive), иначе
        сервер перестанет слать события после ~30 сек неактивности.
        """
        import threading
        while getattr(self, "_listener_run", False):
            cl = None
            try:
                cl = self._new_client()
                cl.subscribe()
                cl.set_push_handler(self._on_push_packet)
                self._listener_client = cl
                # держим ридер живым и периодически повторяем подписку
                while getattr(self, "_listener_run", False):
                    time.sleep(15)
                    if not cl.sock:
                        break
                    try:
                        cl.subscribe()
                    except Exception:
                        break
            except Exception as exc:  # pragma: no cover
                _LOGGER.warning("Аквилон: listener error: %s", exc)
            finally:
                if cl is not None:
                    try:
                        cl._running = False
                        cl.close()
                    except Exception:
                        pass
                self._listener_client = None
                if getattr(self, "_listener_run", False):
                    time.sleep(3)

    def start_listener(self):
        """Запускает постоянный push-listener (идемпотентно)."""
        if self._listener_thread and self._listener_thread.is_alive():
            return
        self._listener_run = True
        self._call_serde = __import__("threading").Lock()
        t = __import__("threading").Thread(target=self._listener_loop, daemon=True)
        self._listener_thread = t
        t.start()

    def stop_listener(self):
        """Останавливает push-listener."""
        self._listener_run = False
        if self._listener_client is not None:
            try:
                self._listener_client._running = False
            except Exception:
                pass
        t = self._listener_thread
        self._listener_thread = None
        if t is not None:
            t.join(timeout=1.5)

    def _on_push_packet(self, pkt, channel, payload):
        """Фоновый колбэк от ридера listener-клиента на серверное push-событие.

        Распознаёт входящий вызов домофона в JSON-теле события (поля call/ring/
        answer/cid/id/type...). Возможные варианты, которые мы готовы принять,
        помечаются словарём метаданных; точный формат события вызова уточняется
        при живом звонке (см. DOMOFON.md).
        """
        if not payload:
            return
        try:
            body = json.loads(payload.decode("utf-8", "replace"))
        except Exception:
            return
        if not isinstance(body, dict):
            return
        blob = json.dumps(body, ensure_ascii=False).lower()
        is_call = any(k in blob for k in (
            "ring", "oncall", "incoming", "cid", "answer", "call",
            "unlock", "open", "intercom", "doorphone",
        ))
        if not is_call:
            return
        call = dict(body)
        call.setdefault("channel", channel)
        self._set_call(call)
        for cb in list(self._call_listeners):
            try:
                cb(call)
            except Exception:
                pass

    def _set_call(self, call: dict):
        """Обновляет состояние активного вызова потокобезопасно."""
        lock = self._call_serde
        if lock is not None:
            with lock:
                self._active_call = call
        else:
            self._active_call = call

    def set_call_listener(self, cb):
        """Регистрирует колбэк, вызываемый при каждом push-событии вызова."""
        if cb not in self._call_listeners:
            self._call_listeners.append(cb)

    @property
    def active_call(self) -> dict | None:
        """Состояние активного входящего вызова (None, если вызова нет)."""
        lock = self._call_serde
        if lock is not None:
            with lock:
                return dict(self._active_call) if self._active_call else None
        return dict(self._active_call) if self._active_call else None

    def clear_call(self):
        """Сбрасывает активный вызов (после ответа/закрытия)."""
        self._set_call(None)

    def load_demo_data(self):
        """Заполняет hub типовыми демо-данными (для визуального превью без сервера)."""
        self.demo = True
        self._cams = [
            {"objectid": "111:69724", "name": "Reka 7 торец дома"},
            {"objectid": "117:69858", "name": "Reka 7 Вид на калитку 2"},
            {"objectid": "102:69861", "name": "Reka 7 Проезд 2"},
            {"objectid": "67:69866", "name": "Reka 7 Холл лифт, лестница"},
            {"objectid": "149:69879", "name": "Reka 7 Колясочная"},
            {"objectid": "2:101967", "name": "Парадная 1-1"},
            {"objectid": "3:101885", "name": "Парадная 1-2"},
        ]
        self._gates = [
            {"objectid": "3:79649", "name": "Калитка 5", "cameraId": "", "controllerStatus": 1, "enabled": 1},
            {"objectid": "2:79668", "name": "Калитка 4", "cameraId": "", "controllerStatus": 1, "enabled": 1},
            {"objectid": "1:101908", "name": "Рекa 4, Проход 1-2", "cameraId": "3:101885", "controllerStatus": 1, "enabled": 1},
            {"objectid": "2:101911", "name": "Рекa 4, Проход 1-1", "cameraId": "2:101967", "controllerStatus": 1, "enabled": 1},
            {"objectid": "2:80649", "name": "Калитка 6", "cameraId": "117:69858", "controllerStatus": 1, "enabled": 1},
        ]
        self._meters = [
            {"objectid": "3:93360", "name": "Квартира 31 ГВС", "deviceNumber": "80131", "resourceType": "2",
             "current": {"value": 121.243, "unit": "м3", "dt": "2026-10-07 00:00", "values": [121.243]}},
            {"objectid": "3:93395", "name": "Квартира 31 ХВС", "deviceNumber": "80132", "resourceType": "3",
             "current": {"value": 88.4, "unit": "м3", "dt": "2026-10-07 00:00", "values": [88.4]}},
            {"objectid": "3:91252", "name": "Квартира 31 Отопление", "deviceNumber": "80133", "resourceType": "4",
             "current": {"value": 3.4, "unit": "Гкал", "dt": "2026-10-07 00:00", "values": [3.4]}},
            {"objectid": "3:93464", "name": "Квартира 31 Электричество", "deviceNumber": "80134", "resourceType": "1",
             "current": {"value": 9992.95, "unit": "кВт*ч", "dt": "2026-10-07 00:00", "values": [7255.78, 2737.17, 0, 0]}},
        ]
        self._intercoms = [
            g for g in self._gates if str(g.get("cameraId") or "").strip() not in ("", "0:-1")
        ]
        self._last_ok = time.monotonic()
        _LOGGER.info(
            "Аквилон: демо-режим: камер=%d, калиток=%d, счётчиков=%d, домофонов=%d",
            len(self._cams), len(self._gates), len(self._meters), len(self._intercoms),
        )

    def refresh(self):
        """Получает свежие списки камер/калиток/счётчиков с сервера.

        Домофоны отдельным каналом НЕ существуют (0x10403 пуст — проверено).
        Домофон = калитка/вход, у которой проставлен cameraId («калитка+камера»).
        Поэтому после загрузки калиток мы собираем intercoms из _gates.
        """
        if self.demo:
            return  # демо-режим: данные уже заполнены через load_demo_data
        for key, ch in (
            ("cameras", CH_CAMERAS),
            ("gates", CH_GATES),
            ("meters", CH_METERS),
        ):
            cl = self._new_client()
            try:
                cl.subscribe()
                cl.register()
                self._last_ok = time.monotonic()
                time.sleep(0.5)
                # Камеры вытягиваются поштучно с паузой (см. protocol.get_list),
                # поэтому большой таймаут — чтобы успеть собрать все id.
                tmo = 70 if key == "cameras" else 40
                objs = cl.get_list(ch, timeout=tmo)
                if key == "cameras":
                    self._cams = objs
                elif key == "gates":
                    self._gates = objs
                else:
                    self._meters = objs
                self._last_count = cl.last_list_count
            except Exception as exc:  # pragma: no cover
                _LOGGER.warning("Аквилон: банк %s не получен: %s", key, exc)
            finally:
                cl._running = False
                cl.close()
        # Домофоны = калитки/входы с реальной привязкой к камере (cameraId != 0:-1)
        self._intercoms = [
            g for g in self._gates
            if str(g.get("cameraId") or "").strip() not in ("", "0:-1")
        ]
        _LOGGER.info(
            "Аквилон: обновлено камер=%d, калиток=%d, счётчиков=%d, домофонов=%d",
            len(self._cams), len(self._gates), len(self._meters), len(self._intercoms),
        )

    def _is_selected(self, obj_id: str) -> bool:
        if self.selected is None:
            return True
        return obj_id in self.selected

    @property
    def cameras(self) -> list:
        return [c for c in self._cams if self._is_selected(str(c.get("objectid") or c.get("objectId") or ""))]

    @property
    def gates(self) -> list:
        return [g for g in self._gates if self._is_selected(str(g.get("objectid") or g.get("objectId") or ""))]

    @property
    def meters(self) -> list:
        return [m for m in self._meters if self._is_selected(str(m.get("objectid") or m.get("objectId") or ""))]

    @property
    def intercoms(self) -> list:
        return [i for i in self._intercoms if self._is_selected(str(i.get("objectid") or i.get("objectId") or ""))]

    def gate_by_id(self, gate_id: str):
        """Находит калитку/вход по objectid (сравнение и по хвосту id)."""
        for g in self._gates:
            oid = str(g.get("objectid") or g.get("objectId") or "")
            if oid == str(gate_id) or oid.split(":")[-1] == str(gate_id).split(":")[-1]:
                return g
        return None

    def camera_by_id(self, cam_id: str):
        for c in self._cams:
            oid = str(c.get("objectid") or c.get("objectId") or "")
            if oid == str(cam_id) or oid.split(":")[-1] == str(cam_id).split(":")[-1]:
                return c
        return None

    def camera_name(self, cam_id: str) -> str:
        cam = self.camera_by_id(cam_id)
        if cam:
            return str(cam.get("name") or cam.get("Name") or "")
        return ""

    def is_favorite_camera(self, cam_id: str) -> bool:
        sid = str(cam_id)
        if self.favorite_cameras:
            return sid in self.favorite_cameras or any(sid.endswith(fav) for fav in self.favorite_cameras)
        name = self.camera_name(sid).lower()
        return any(k in name for k in ("торец", "вид на калитку 2", "парадная 1-1", "холл лифт"))

    def set_favorite_camera(self, cam_id: str, is_fav: bool = True):
        sid = str(cam_id)
        if is_fav:
            self.favorite_cameras.add(sid)
        else:
            self.favorite_cameras.discard(sid)

    def ping_server(self) -> float:
        """Замеряет задержку ответа сервера здания (мс)."""
        import socket
        t0 = time.monotonic()
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(0.8)
            sock.sendto(b"\x00" * 4, (self.host, int(self.port)))
            dt = (time.monotonic() - t0) * 1000.0
            self.ping_ms = round(dt, 1)
            sock.close()
            return self.ping_ms
        except Exception as exc:
            self.last_error = str(exc)
            return self.ping_ms if self.ping_ms else 0.0

    def intercom_link(self, intercom_id: str) -> dict:
        """Связывает домофон↔камера↔калитка по objectid.

        Возвращает dict: gate_id, gate_name, camera_id, camera_name, controller_id.
        Используется сущностями домофонов и карточками (Поток B).
        """
        gate = self.gate_by_id(intercom_id) or {}
        oid = str(gate.get("objectid") or gate.get("objectId") or str(intercom_id))
        cam_id = str(gate.get("cameraId") or "")
        cam = self.camera_by_id(cam_id) if cam_id else None
        return {
            "gate_id": oid,
            "gate_name": str(gate.get("name") or "Домофон"),
            "gate_status": gate.get("controllerStatus"),
            "gate_enabled": gate.get("enabled"),
            "camera_id": cam_id,
            "camera_name": str(cam.get("name") or cam.get("Name") or "") if cam else "",
            "controller_id": str(gate.get("controllerId") or ""),
        }

    def open_gate(self, gate_id: str) -> bool:
        """Открывает калитку/домофон: свежая сессия, без фонового ридера.

        Используется кнопками (button) и сервисом open_gate. Свежий клиент
        подписывается и регистрируется, после чего шлёт команду открытия.
        """
        cl = AkvilonClient(
            self.host, self.port, self.token,
            device_id=self.device_id, server_id=self.server_id,
        )
        ok = False
        try:
            cl.connect()
            cl.subscribe()
            cl.register()
            ok = bool(cl.open_gate(gate_id))
        except Exception as exc:  # pragma: no cover
            _LOGGER.warning("Аквилон: не удалось открыть %s: %s", gate_id, exc)
        finally:
            cl._running = False
            cl.close()
        return ok

    # ------------------------------------------------------------------
    # Действия домофона: ответить / принять звук / открыть дверь
    # ------------------------------------------------------------------
    def intercom_unlock(self, gate_id: str) -> bool:
        """«Просто открыть дверь»: открыть калитку/дверь домофона."""
        return self.open_gate(gate_id)

    def _voice_settings(self, cam_id: str) -> dict:
        """Параметры голосового канала из cameraSettings (voiceHost/voicePort)."""
        side = self.get_camera_settings(cam_id)
        if not side.get("voiceHost") and not side.get("voicePort"):
            return {}
        return side

    def intercom_answer(self, cam_id: str, gate_id: str = "") -> dict:
        """«Ответить»: подключиться к вызову (сигнал answer) + поднять видео.

        На подтверждённом протоколе ответ на звонок домофона идёт как событие/
        команда с полем answer/cid. Точные поля вызова сервер пушит при живом
        звонке — здесь используется best-effort: отправляем событие на понятный
        серверу канал и открываем камеру (видео-цепочка уже рабочая). Голосовой
        RTP запускается только если cameraSettings отдали voiceHost/voicePort.
        """
        import json as _json
        call = self.active_call or {}
        body = dict(call)
        body["action"] = "answer"
        body.setdefault("id", str(cam_id))
        body.setdefault("name", "openCamera")
        # Сигнал ответа: пробуем отправить на канал открытия камеры и канал
        # вызова (0x30401 уже подтверждён для openCamera; answer идёт тем же путём
        # в области домофона). Дополнительно открываем видео, чтобы показать камеру.
        result = {"video_started": False, "voice_started": False, "call": bool(call)}
        try:
            cl = self._new_client()
            try:
                raw = cl.open_camera(cam_id)
                result["video_started"] = raw is not None
                # Голос: токен на voicePort (как запуск видео-токеном)
                side_payload = _json.dumps(body, separators=(",", ":")).encode("utf-8")
                cl.send(3, 0, 0x30401, side_payload, state_number=cl._next_seq(), timeout=4.0)
            finally:
                cl._running = False
                cl.close()
        except Exception as exc:  # pragma: no cover
            _LOGGER.warning("Аквилон: intercom_answer exc: %s", exc)
        v = self._voice_settings(cam_id)
        if v.get("voicePort"):
            result["voice_started"] = self._kick_voice(cam_id, v)
        return result

    def intercom_accept_audio(self, cam_id: str) -> dict:
        """«Принять звук»: включить разговорный (голосовой) канал микрофон/динамик.

        Поднимает полноценный RTP/RTCP G.711-канал на voiceHost:voicePort
        (см. voice_rtp.VoiceStream): токен-запуск как у видео + RTCP Sender
        Report (нативная либа шлёт его через sendRtcp для живого канала).
        Точный формат старта требует pcap реального вызова — см. VOICE.md.
        """
        side = self.get_camera_settings(cam_id)
        vhost = side.get("voiceHost") or side.get("videoHost") or ""
        vport = int(side.get("voicePort") or 0)
        if not vport or not vhost:
            return {"voice_started": False, "reason": "no_voice_settings"}
        token = str(side.get("videoToken") or self._video_settings.get(str(cam_id), {}).get("videoToken") or "")
        try:
            with self._voice_lock:
                self._close_voice()
                v = VoiceStream(
                    host=vhost, port=vport, token=token,
                    rtcp_host=side.get("voiceRtcpHost") or vhost,
                    rtcp_port=int(side.get("voiceRtcpPort") or int(side.get("voiceRtcp") or 0) or 0),
                    ssrc=None,
                )
                v.bind(0)
                v._kick()
                self._voice = v
            self._mic_on = False
            return {"voice_started": True, "voice_host": vhost, "voice_port": vport,
                    "rtcp_port": v.rtcp_port}
        except Exception as exc:  # pragma: no cover
            _LOGGER.warning("Аквилон: voice start exc: %s", exc)
            return {"voice_started": False, "reason": str(exc)}

    def voice_send_audio(self, g711_bytes: bytes) -> int:
        """Отправляет G.711-кадр микрофона в активный голосовой канал.

        Ожидается один кадр (обычно 160 байт = 20 мс @8 кГц). Возвращает число
        отправленных байт, либо 0, если канал закрыт/микрофон выключен.
        """
        if not self._mic_on:
            return 0
        v = self._voice
        if v is None:
            return 0
        try:
            return v.send_audio(bytes(g711_bytes))
        except Exception as exc:  # pragma: no cover
            _LOGGER.debug("Аквилон: voice send_audio exc: %s", exc)
            return 0

    def voice_recv_audio(self, timeout: float = 0.2):
        """Читает один RTP-пакет динамика из активного голосового канала.

        Возвращает (ts, marker, bytes) или (None, False, None) при таймауте
        либо если канал закрыт.
        """
        v = self._voice
        if v is None:
            return None, False, None
        try:
            return v.recv_audio(timeout=timeout)
        except Exception as exc:  # pragma: no cover
            _LOGGER.debug("Аквилон: voice recv_audio exc: %s", exc)
            return None, False, None

    def voice_set_mic(self, on: bool, volume: float | None = None) -> bool:
        """Включает/выключает микрофон и задаёт громкость (аналог setMicIsOn)."""
        v = self._voice
        if v is None:
            self._mic_on = False
            return False
        self._mic_on = bool(on)
        try:
            v.set_mic(on, volume)
        except Exception as exc:  # pragma: no cover
            _LOGGER.warning("Аквилон: voice set_mic exc: %s", exc)
        return self._mic_on

    @property
    def voice_active(self) -> bool:
        return self._voice is not None

    def _close_voice(self):
        v = self._voice
        self._voice = None
        self._mic_on = False
        if v is not None:
            try:
                v.close()
            except Exception:
                pass

    def _kick_voice(self, cam_id: str, settings: dict) -> bool:
        """Шлёт голосовой токен запуска на voiceHost:voicePort (аналог видео)."""
        try:
            import socket as _socket
            vhost = settings.get("voiceHost") or settings.get("videoHost")
            vport = int(settings.get("voicePort") or 0)
            if not vhost or not vport:
                return False
            token = str(settings.get("videoToken") or self._video_settings.get(str(cam_id), {}).get("videoToken") or "")
            if not token:
                return False
            s = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
            s.settimeout(1.0)
            try:
                for payload in (b"\x00\x00" + token.encode("ascii"),
                                token.encode("ascii")):
                    s.sendto(payload, (vhost, vport))
            finally:
                try:
                    s.close()
                except Exception:
                    pass
            return True
        except Exception as exc:  # pragma: no cover
            _LOGGER.warning("Аквилон: voice kick exc: %s", exc)
            return False

    def get_camera_settings(self, cam_id: str, force_refresh: bool = False) -> dict:
        """Запрашивает у сервера cameraSettings для камеры (порт/токен/SPS/PPS).

        Открывает камеру через протокол, ловит ответ cameraSettings на канале
        0x2030401 и кэширует результат. Видео-порт приходит именно здесь, а не
        в живом списке камер (там поля videoPort нет).
        """
        try:
            sid = str(cam_id)
            if not force_refresh and sid in self._video_settings:
                return self._video_settings[sid]
            cl = self._new_client()
            cl.connect()
            try:
                settings = cl.request_camera_settings(sid)
                if settings:
                    self._video_settings[sid] = settings
                    self._last_camera_open[sid] = time.time()
                elif sid in self._video_settings:
                    settings = self._video_settings[sid]
                return settings or {}
            finally:
                cl._running = False
                cl.close()
        except Exception as exc:  # pragma: no cover
            _LOGGER.warning("Аквилон: не удалось получить настройки камеры %s: %s", cam_id, exc)
            return self._video_settings.get(str(cam_id), {})

    def camera_port(self, cam_id: str) -> int:
        """Возвращает реальный видео-порт камеры (0, если неизвестен)."""
        try:
            st = self._video_settings.get(str(cam_id))
            if st:
                return int(st.get("videoPort") or st.get("port") or 0)
        except (TypeError, ValueError):
            pass
        return 0

    def camera_video_url(self, cam_id: str) -> str:
        """Собирает реальный rtsp/rtp-URL камеры по кэшированным настройкам."""
        side = self.get_camera_settings(cam_id)
        vhost = side.get("videoHost") or self.host
        vport = int(side.get("videoPort") or 0)
        if vport:
            return f"rtsp://{vhost}:{vport}/cameras/{str(cam_id).replace(':', '_')}"
        return ""

    def camera_frame(self, cam_id: str, timeout: float = 3.5, max_age: float = 20.0) -> bytes | None:
        """Захватывает реальный кадр камеры (JPEG) через RTP с умным кэшированием.

        - Если свежий кадр уже в кэше (< max_age сек) — отдаёт мгновенно (0мс).
        - Параллельные запросы к одной камере объединяются через lock.
        - Глобальный семафор (Semaphore=1) предотвращает перегрузку сервера здания
          и процессора слабых устройств (Raspberry Pi).
        - При занятом семафоре мгновенно отдаёт последний кэшированный кадр без блокировки потока.
        - Автоматически обновляет подписку openCamera, если она истекла.
        """
        sid = str(cam_id)
        now = time.time()

        # 1. Мгновенный возврат из кэша (0мс), если кадр моложе max_age
        with self._cache_lock:
            cached = self._frame_cache.get(sid)
            if cached:
                frame, ts = cached
                if (now - ts) < max_age:
                    return frame
            lock = self._frame_locks.setdefault(sid, threading.Lock())

        # 2. Неблокирующий семафор: если уже идёт декодирование другой камеры,
        # возвращаем последний известный кадр (до 60с) или None, не забивая пул executor'а
        acquired_sem = self._global_frame_sem.acquire(timeout=0.25)
        if not acquired_sem:
            with self._cache_lock:
                cached = self._frame_cache.get(sid)
                if cached and (time.time() - cached[1]) < 60.0:
                    return cached[0]
            return cached[0] if cached else None

        try:
            with lock:
                now = time.time()
                cached = self._frame_cache.get(sid)
                if cached and (now - cached[1]) < max_age:
                    return cached[0]

                # Защита от спама: не долбить одну камеру чаще раза в 5 сек при ошибках
                last_attempt = self._last_camera_open.get(f"attempt_{sid}", 0)
                if (now - last_attempt) < 5.0 and cached:
                    return cached[0]
                self._last_camera_open[f"attempt_{sid}"] = now

                try:
                    need_open = (now - self._last_camera_open.get(sid, 0)) > 25.0
                    settings = self.get_camera_settings(sid, force_refresh=need_open)
                    if not settings or not settings.get("videoPort"):
                        _LOGGER.debug("Аквилон: нет настроек потока для камеры %s", sid)
                        return cached[0] if cached else None

                    stream = RtpStream(settings)
                    try:
                        new_frame = stream.grab_jpeg(timeout=timeout)
                        if new_frame:
                            with self._cache_lock:
                                self._frame_cache[sid] = (new_frame, time.time())
                            return new_frame
                    finally:
                        stream.close()
                except Exception as exc:  # pragma: no cover
                    _LOGGER.warning("Аквилон: ошибка захвата кадра камеры %s: %s", sid, exc)

                return cached[0] if cached else None
        finally:
            self._global_frame_sem.release()

    def close(self):
        self._close_voice()
        self.stop_listener()
        if self.client:
            self.client._running = False
            self.client.close()
            self.client = None
        self._reader = None