"""Камеры Аквилон: видео идёт через сервер здания по UDP/RTP с токеном.

Камеры создаются динамически из живого списка сервера (hub.cameras).
Видео-поток идёт UDP-RTP, но СЕРВЕР НЕ СТАРТУЕТ RTP без точного
«подписочного» пакета, который пока не найден (нужен pcap реального
приложения при живом просмотре). Поэтому:

  * атрибуты берутся ТОЛЬКО из уже загруженных списков и из кэша
    _video_settings (без сетевых вызовов в event loop);
  * async_camera_image пытается получить кадр через RtpStream (UDP-приёмник
    H.264 + декод ffmpeg) ЗАПУСКОМ в executor (не блокирует event loop) и
    возвращает None, если поток не пошёл (обычный случай сейчас);
  * stream_source возвращает гипотетический rtp:// URL, т.к. стандартного
    RTSP на сервере нет.

ffmpeg-декод кадра активируется только когда сервер начнёт реально слать RTP.
До этого картинка будет заглушкой/пустой, но сущности камер в HA уже есть.
"""
import logging

from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .rtp_stream import RtpStream

_LOGGER = logging.getLogger(__name__)


def _cam_name(cam) -> str:
    if isinstance(cam, dict):
        return str(cam.get("name") or cam.get("Name") or "Камера")
    return "Камера"


def _cam_id(cam) -> str:
    if isinstance(cam, dict):
        return str(cam.get("objectid") or cam.get("objectId") or cam.get("id") or "")
    return str(cam)


class AkvilonCamera(Camera):
    """Камера ЖК Аквилон (видео через UDP-RTP прокси сервера)."""

    def __init__(self, hub, cam_id, name):
        super().__init__()
        self._hub = hub
        self.cam_id = cam_id
        self._name = name
        self._attr_unique_id = f"{DOMAIN}_cam_{cam_id.replace(':', '_')}"

    @property
    def name(self):
        return f"Камера {self._name}"

    @property
    def icon(self):
        return "mdi:cctv"

    @property
    def extra_state_attributes(self):
        # ВАЖНО: никаких сетевых вызовов здесь. Видео-параметры - из кэша.
        cam = self._hub.camera_by_id(self.cam_id) or {}
        attrs = {
            "object_id": self.cam_id,
            "camera_name": self._name,
            "codec": "H.264",
            "integration": DOMAIN,
            # привязка калитки/домофона (если это камера домофона)
            "domofon": False,
        }
        # Если камера привязана к калитке (в списке калиток есть cameraId == этой камеры)
        for g in self._hub._gates:
            if str(g.get("cameraId") or "") == str(self.cam_id):
                attrs["domofon"] = True
                attrs["gate_id"] = str(g.get("objectid") or g.get("objectId") or "")
                attrs["gate_name"] = str(g.get("name") or "")
                break
        # Настройки потока — ТОЛЬКО из кэша (если уже получены), без сети.
        side = self._hub._video_settings.get(str(self.cam_id)) or {}
        if side:
            attrs["video_token"] = side.get("videoToken", "")
            attrs["vport"] = side.get("videoPort") or side.get("port") or 0
            attrs["vhost"] = side.get("videoHost", "")
            attrs["sprop"] = side.get("spropParameter", "")
            attrs["rtp_url"] = (
                f"rtp://{side.get('videoHost', self._hub.host)}:{side.get('videoPort') or 0}"
                f"/cameras/{str(self.cam_id).replace(':', '_')}"
            )
        return attrs

    def _settings(self):
        """Настройки ВИДЕО камеры ИЗ КЭША хаба (без сети в event loop).

        Кэш заполняется coordinator.get_camera_settings (например, самим этим
        методом при первом вызове — см. _grab_image_job). НЕ вызывать сеть
        напрямую при каждом кадре.
        """
        return self._hub._video_settings.get(str(self.cam_id)) or {}

    async def stream_source(self):
        # Стандартного RTSP/RTP-сервера, доступного для HA, нет: сервер ещё не
        # стартует RTP без точного «подписочного» пакета. ВОЗВРАЩАЕМ None, чтобы
        # HA НЕ пытался открыть несуществующий поток через stream-компонент и не
        # спамил в лог "Error opening stream". Картинка берётся только через
        # async_camera_image (см. ниже). Реальный rtp:// URL — в атрибутах.
        return None

    async def async_camera_image(self, width=None, height=None):
        """Пытается получить актуальный JPEG-кадр (запуском в executor).

        Если сервер ещё не шлёт RTP (обычный случай до нахождения «подписочного»
        пакета) — вернёт None, а HA покажет заглушку. Без блокировки event loop.
        """
        hass = self.hass
        if hass is None:
            return None
        try:
            return await hass.async_add_executor_job(
                self._grab_image_job, width, height
            )
        except Exception:  # pragma: no cover
            return None

    def _grab_image_job(self, width=None, height=None):
        """Блокирующая работа в executor: получить и декодировать кадр.

        Использует ТОЛЬКО кэш настроек. Если настроек ещё нет — первый вызов
        получает их с сервера и кэширует; вернёт None (RTP всё равно не идёт).
        Повторные вызовы используют кэш (быстро, без сети).
        """
        settings = self._settings()
        if not settings:
            try:
                settings = self._hub.get_camera_settings(self.cam_id) or {}
            except Exception:  # pragma: no cover
                return None
        if not settings:
            return None
        # ffmpeg обязателен для декода H.264 -> JPEG (есть в контейнере HA)
        try:
            import shutil
            if not shutil.which("ffmpeg"):
                return None
        except Exception:
            return None
        stream = None
        try:
            stream = RtpStream(settings)
            stream.bind(0)
            return stream.grab_jpeg(timeout=6.0, kick=True)
        except Exception:  # pragma: no cover
            return None
        finally:
            if stream:
                try:
                    stream.close()
                except Exception:
                    pass


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    """Создаёт камеры из живого списка сервера."""
    hub = hass.data[DOMAIN][entry.entry_id]
    cameras = [c for c in hub.cameras if _cam_id(c)]
    entities = [
        AkvilonCamera(hub, _cam_id(c), _cam_name(c)) for c in cameras
    ]
    async_add_entities(entities, True)
    _LOGGER.info("Аквилон: добавлено %d камер из сервера", len(entities))