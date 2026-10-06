"""Кнопки открытия калиток/дверей Аквилон."""
import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


def _gate_name(gate) -> str:
    if isinstance(gate, dict):
        return gate.get("name") or gate.get("Name") or "Калитка"
    return "Калитка"


def _gate_id(gate) -> str:
    if isinstance(gate, dict):
        return str(gate.get("objectid") or gate.get("objectId") or gate.get("id") or "")
    return str(gate)


class AkvilonGateButton(ButtonEntity):
    """Кнопка открытия конкретной калитки."""

    _attr_has_entity_name = False

    def __init__(self, hub, gate_id, name):
        self._hub = hub
        self.gate_id = str(gate_id)
        self._name = name
        self._attr_unique_id = f"{DOMAIN}_gate_{self.gate_id.replace(':', '_')}"

    @property
    def name(self):
        return f"Открыть {self._name}"

    @property
    def icon(self):
        return "mdi:door-open"

    async def async_press(self):
        """Отправить команду открытия калитки через сервер здания."""
        hub = self._hub
        cl = hub._new_client()
        try:
            ok = await self.hass.async_add_executor_job(cl.open_gate, self.gate_id)
            _LOGGER.info(
                "Аквилон: открытие калитки %s -> %s", self.gate_id, "OK" if ok else "FAIL",
            )
        finally:
            cl._running = False
            cl.close()


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    """Создаёт кнопки калиток из живого списка сервера."""
    hub = hass.data[DOMAIN][entry.entry_id]
    gates = list(hub.gates)
    entities = [
        AkvilonGateButton(hub, _gate_id(g), _gate_name(g))
        for g in gates if _gate_id(g)
    ]
    async_add_entities(entities, True)
    _LOGGER.info("Аквилон: добавлено %d калиток из сервера", len(entities))
