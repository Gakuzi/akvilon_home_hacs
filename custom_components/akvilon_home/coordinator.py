"""Координатор/хаб интеграции Аквилон: живое подключение к серверу.

Держит постоянный клиент (для кнопок/управления) и умеет получать списки
камер/калиток/счётчиков с сервера. Для надёжности каждый банк запрашивается
на свежем подключении.
"""
import logging
import time
from dataclasses import dataclass

from .const import DOMAIN
from .protocol import AkvilonClient, CH_CAMERAS, CH_GATES, CH_METERS
from .rtp_stream import RtpStream

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
        self._intercoms = []  # домофоны: выводим из калиток, у которых есть cameraId
        self._video_settings = {}  # cam_id -> dict(videoPort, videoHost, videoToken, sprop)
        self._last_ok = 0.0  # monotonic метка последнего успешного опроса сервера
        self._last_count = 0
        self._online = False  # запасной онлайн-признак (по refresh)
        self.last_refresh_error = None
        self.selected: list[str] | None = None  # None = все

    def _new_client(self) -> AkvilonClient:
        cl = AkvilonClient(
            self.host, self.port, self.token,
            device_id=self.device_id, server_id=self.server_id,
            pass_hex=self.token,  # подпись строится из pass_hex (иначе дефолт PASS_PLACEHOLDER)
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
        self._online = True
        _LOGGER.info(
            "Аквилон: демо-режим: камер=%d, калиток=%d, счётчиков=%d, домофонов=%d",
            len(self._cams), len(self._gates), len(self._meters), len(self._intercoms),
        )

    def refresh(self):
        """Получает свежие списки камер/калиток/счётчиков с сервера.

        УСТОЙЧИВО: метод никогда не бросает исключение — каждый банк оборачивается
        в try/except, а неуспех лишь логируется. `self._last_ok` обновляется ТОЛЬКО
        при реальном получении данных от сервера, поэтому сенсор «_last_ok» не
        врёт об онлайне при падении банка. Возвращает bool: получили ли хоть
        какой-то банк (для онлайн-статуса).

        Домофоны отдельным каналом НЕ существуют (0x10403 пуст — проверено).
        Домофон = калитка/вход, у которой проставлен cameraId («калитка+камера»).
        Поэтому после загрузки калиток мы собираем intercoms из _gates.
        """
        if self.demo:
            self._online = True
            return True  # демо-режим: данные уже заполнены через load_demo_data
        self.last_refresh_error = None
        got_any = False
        try:
            for key, ch in (
                ("cameras", CH_CAMERAS),
                ("gates", CH_GATES),
                ("meters", CH_METERS),
            ):
                cl = self._new_client()
                try:
                    # ВАЖНО: НЕ вызываем subscribe()/register() для получения списков.
                    # register() портит UDP-сессию: сервер начинает отвечать flag=0x82
                    # (ERR) на GET, и камеры не приходят. Подписи PASS достаточно.
                    time.sleep(0.5)
                    # Камеры вытягиваются поштучно с паузой (см. protocol.get_list),
                    # поэтому большой таймаут — чтобы успеть собрать все id.
                    tmo = 70 if key == "cameras" else 40
                    objs = cl.get_list(ch, timeout=tmo)
                    if cl._last_rx > 0:
                        # сервер реально что-то прислал — это признак онлайна
                        self._last_ok = time.monotonic()
                        self._online = True
                        got_any = True
                    if key == "cameras":
                        self._cams = objs
                    elif key == "gates":
                        self._gates = objs
                    else:
                        self._meters = objs
                    self._last_count = cl.last_list_count
                except Exception as exc:  # pragma: no cover
                    self.last_refresh_error = exc
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
        except Exception as exc:  # pragma: no cover
            # нижний предохранитель: refresh никогда не роняет setup_entry
            self.last_refresh_error = exc
            _LOGGER.warning("Аквилон: refresh прерван: %s", exc)
        if not got_any:
            self._online = False
        return got_any

    @property
    def is_online(self) -> bool:
        """Онлайн ли сервер по последнему refresh (запасной признак)."""
        return bool(self._online)

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
            pass_hex=self.token,  # подпись из pass_hex (иначе сервер отвечает 0x82)
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

    def get_camera_settings(self, cam_id: str, force: bool = False) -> dict:
        """Запрашивает у сервера cameraSettings для камеры (порт/токен/SPS/PPS).

        Открывает камеру через протокол, ловит ответ cameraSettings на канале
        0x2030401 и кэширует результат на ~30 секунд. Видео-порт приходит именно
        здесь, а не в живом списке камер (там поля videoPort нет).

        ВАЖНО: НЕ вызываем register() — он портит UDP-сессию и сервер отвечает
        на GET flag=0x82 (ERR). Подпись PASS в openCamera/GET достаточна.

        force=True — принудительно переоткрывает камеру (свежий token), что нужно
        перед реальным захватом кадра: сервер инвалидирует сессию видео со временем.
        """
        try:
            sid = str(cam_id)
            # кэш годен ~30 сек; для захвата кадра (force) всегда переоткрываем
            if not force and sid in self._video_settings:
                st = self._video_settings[sid]
                if time.time() - st.get("_ts", 0) < 30.0:
                    return st
            cl = self._new_client()
            try:
                settings = cl.request_camera_settings(sid)
                if settings:
                    settings = {**settings, "_ts": time.time()}
                    self._video_settings[sid] = settings
                return settings or {}
            finally:
                cl._running = False
                cl.close()
        except Exception as exc:  # pragma: no cover
            _LOGGER.warning("Аквилон: не удалось получить настройки камеры %s: %s", cam_id, exc)
            return {}

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

    def camera_frame(self, cam_id: str, timeout: float = 7.0) -> bytes | None:
        """Захватывает реальный кадр камеры (JPEG) через RTP.

        Вызывается ТОЛЬКО из executor (не на event loop): делает сетевые
        операции и блокирующий декод ffmpeg. Возвращает JPEG-bytes или None.

        Цепочка: openCamera -> cameraSettings (videoPort/videoToken) ->
        отправить b"\x00\x00"+videoToken на videoPort -> принять RTP/H.264 ->
        собрать IDR-кадр -> декодить в JPEG через ffmpeg.
        """
        try:
            settings = self.get_camera_settings(cam_id, force=True)
            if not settings or not settings.get("videoPort"):
                _LOGGER.debug("Аквилон: нет настроек потока для камеры %s", cam_id)
                return None
            stream = RtpStream(settings)
            try:
                jpg = stream.grab_jpeg(timeout=timeout)
            finally:
                stream.close()
            # освобождаем видео-сессию на сервере (иначе накопится лимит
            # активных камер и сервер перестанет отдавать cameraSettings для новых)
            self._close_camera_session(cam_id)
            return jpg
        except Exception as exc:  # pragma: no cover
            _LOGGER.warning("Аквилон: не удалось захватить кадр камеры %s: %s", cam_id, exc)
            return None

    def _close_camera_session(self, cam_id: str):
        """Отправляет closeCamera, чтобы освободить видео-сессию на сервере."""
        try:
            cl = self._new_client()
            try:
                cl.close_camera(str(cam_id))
            finally:
                cl._running = False
                cl.close()
        except Exception as exc:  # pragma: no cover
            _LOGGER.debug("Аквилон: closeCamera %s: %s", cam_id, exc)

    def close(self):
        if self.client:
            self.client._running = False
            self.client.close()
            self.client = None
        self._reader = None