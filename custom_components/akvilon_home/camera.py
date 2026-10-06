"""Камеры Аквилон: видео идёт через сервер здания по UDP/RTP с токеном.

Камеры создаются динамически из живого списка сервера (hub.cameras).
Видео-поток идёт UDP-RTP и пока отложен (нет pcap приложения). Поэтому
camera.py НЕ обращается к серверу при чтении атрибутов — это блокировало
event loop (Caught blocking call to sleep). Атрибуты берутся ТОЛЬКО из
уже загруженных списков и из кэша _video_settings (если настройки были
получены заранее через coordinator.get_camera_settings в executor).
"""
import logging

from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

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
        # ВАЖНО: никаких сетевых вызовов здесь. Сервер может вообще не отдавать
        # cameraSettings (video игнорируется). Берём только кэш и статику.
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
        return attrs

    async def stream_source(self):
        # Стандартного RTSP-сервера на здании нет; поток — UDP/RTP с токеном.
        return None

    async def async_camera_image(self, width=None, height=None):
        return None


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