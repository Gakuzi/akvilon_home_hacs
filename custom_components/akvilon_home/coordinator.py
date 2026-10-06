"""Координатор/хаб интеграции Аквилон: живое подключение к серверу.

Держит постоянный клиент (для кнопок/управления) и умеет получать списки
камер/калиток/счётчиков с сервера. Для надёжности каждый банк запрашивается
на свежем подключении.
"""
import logging
import time
from dataclasses import dataclass

from .const import DOMAIN
import json
from .protocol import AkvilonClient, CH_CAMERAS, CH_INTERCOM, CH_GATES, CH_METERS

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
        self.client: AkvilonClient | None = None
        self._reader = None
        self._cams = []
        self._gates = []
        self._meters = []
        self._intercoms = []
        self._video_settings = {}  # cam_id -> dict(videoPort, videoHost, videoToken, sprop)
        self._last_ok = 0.0  # monotonic метка последнего успешного опроса сервера
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

    def refresh(self):
        """Получает свежие списки камер/калиток/счётчиков с сервера."""
        for key, ch in (
            ("cameras", CH_CAMERAS),
            ("gates", CH_GATES),
            ("meters", CH_METERS),
            ("intercoms", CH_INTERCOM),
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
                elif key == "meters":
                    self._meters = objs
                else:
                    self._intercoms = objs
                self._last_count = cl.last_list_count
            except Exception as exc:  # pragma: no cover
                _LOGGER.warning("Аквилон: банк %s не получен: %s", key, exc)
            finally:
                cl._running = False
                cl.close()
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

    def camera_by_id(self, cam_id: str):
        for c in self._cams:
            oid = str(c.get("objectid") or c.get("objectId") or "")
            if oid == str(cam_id) or oid.split(":")[-1] == str(cam_id).split(":")[-1]:
                return c
        return None

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