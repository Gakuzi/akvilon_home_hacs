"""Камеры Аквилон: видео идёт через сервер здания по UDP/RTP с токеном.

Камеры создаются динамически из живого списка сервера (hub.cameras).
Видео-поток идёт через UDP-RTP на порт сервера с токеном; пока RTP-прокси
не настроен, камера хранит реальные параметры (host, port, token, object_id)
в атрибутах.
"""
import logging

from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, DEFAULT_HOST

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
        host = DEFAULT_HOST
        side = self._hub.get_camera_settings(self.cam_id)
        vport = int(side.get("videoPort") or side.get("port") or 0)
        vhost = side.get("videoHost") or host
        vtok = side.get("videoToken") or ""
        sprop = side.get("spropParameter") or ""
        return {
            "object_id": self.cam_id,
            "vhost": vhost,
            "vport": vport,
            "video_token": vtok,
            "sprop": sprop,
            "codec": "H.264",
            "integration": "akvilon_home",
            "stream_url": f"rtsp://{vhost}:{vport}/cameras/{self.cam_id.replace(':', '_')}" if vport else "",
        }

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