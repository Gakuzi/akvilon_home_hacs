"""Кнопки открытия калиток/дверей и вызова домофонов Аквилон."""
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

    @property
    def extra_state_attributes(self):
        return {"integration": "akvilon_home", "gate_id": self.gate_id}

    async def async_press(self):
        """Отправить команду открытия калитки через сервер здания.
        Выполняется в executor: hub.open_gate поднимает свежую сессию с
        подпиской+регистрацией (без блокировки event loop)."""
        try:
            ok = await self.hass.async_add_executor_job(
                self._hub.open_gate, self.gate_id
            )
            _LOGGER.info(
                "Аквилон: открытие калитки %s -> %s", self.gate_id, "OK" if ok else "FAIL",
            )
        except Exception as exc:  # pragma: no cover
            _LOGGER.warning("Аквилон: ошибка открытия калитки %s: %s", self.gate_id, exc)


class AkvilonIntercomButton(ButtonEntity):
    """Кнопка открытия/вызова домофона (та же команда, что для калитки)."""

    _attr_has_entity_name = False

    def __init__(self, hub, intercom_id, name):
        self._hub = hub
        self.intercom_id = str(intercom_id)
        self._name = name
        self._attr_unique_id = f"{DOMAIN}_intercom_open_{self.intercom_id.replace(':', '_')}"

    @property
    def name(self):
        return f"Открыть домофон {self._name}"

    @property
    def icon(self):
        return "mdi:door-bell"

    @property
    def extra_state_attributes(self):
        return {"integration": "akvilon_home", "intercom_id": self.intercom_id}

    async def async_press(self):
        try:
            ok = await self.hass.async_add_executor_job(
                self._hub.open_gate, self.intercom_id
            )
            _LOGGER.info(
                "Аквилон: открытие домофона %s -> %s", self.intercom_id, "OK" if ok else "FAIL",
            )
        except Exception as exc:  # pragma: no cover
            _LOGGER.warning("Аквилон: ошибка открытия домофона %s: %s", self.intercom_id, exc)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    """Создаёт кнопки калиток и домофонов из живого списка сервера."""
    hub = hass.data[DOMAIN][entry.entry_id]
    entities = []
    for g in hub.gates:
        gid = _gate_id(g)
        if gid:
            entities.append(AkvilonGateButton(hub, gid, _gate_name(g)))
    for ic in hub.intercoms:
        iid = _gate_id(ic)
        if iid:
            entities.append(AkvilonIntercomButton(hub, iid, _gate_name(ic)))
    async_add_entities(entities, True)
    _LOGGER.info("Аквилон: добавлено %d калиток и %d домофонов из сервера",
                 len(hub.gates), len(hub.intercoms))
