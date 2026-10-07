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
        self.selected: list[str] | None = None  # None = все

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

    def get_camera_settings(self, cam_id: str) -> dict:
        """Запрашивает у сервера cameraSettings для камеры (порт/токен/SPS/PPS).

        Открывает камеру через протокол, ловит ответ cameraSettings на канале
        0x2030401 и кэширует результат. Видео-порт приходит именно здесь, а не
        в живом списке камер (там поля videoPort нет).
        """
        try:
            sid = str(cam_id)
            if sid in self._video_settings:
                return self._video_settings[sid]
            cl = self._new_client()
            try:
                cl.subscribe()
                cl.register()
                settings = cl.request_camera_settings(sid)
                if settings:
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

    def close(self):
        if self.client:
            self.client._running = False
            self.client.close()
            self.client = None
        self._reader = None