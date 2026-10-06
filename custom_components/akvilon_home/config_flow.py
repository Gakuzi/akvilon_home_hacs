"""Config flow для интеграции Аквилон InHome.

Пользователь вводит ОДНУ строку подключения от застройщика (или QR-код).
Строка автоматически распознаётся (host/port/device_id/server_id/PASS/SUID),
затем с сервера загружается список устройств (камеры/калитки/датчики),
пользователь отмечает нужные, и создаётся Config Entry.
"""
import logging

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import (
    DOMAIN,
    CONF_HOST,
    CONF_PORT,
    CONF_TOKEN,
    CONF_DEVICE_ID,
    CONF_SERVER_ID,
    CONF_NAME,
    DEFAULT_NAME,
)
from .protocol import parse_qr

_LOGGER = logging.getLogger(__name__)

# Поле для ввода строки подключения
QR_SCHEMA = vol.Schema(
    {
        vol.Required("connection_string"): str,
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
    }
)

# Шаг выбора устройств (после загрузки списка)
SELECT_SCHEMA = vol.Schema(
    {
        vol.Required("devices"): vol.All(list),
    }
)


class AkvilonHomeFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Обработчик конфигурации интеграции Аквилон InHome."""

    VERSION = 1
    MINOR_VERSION = 1

    def __init__(self) -> None:
        self._params = {}
        self._devices = []

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            qr = (user_input.get("connection_string") or "").strip()
            _LOGGER.info("[akvilon_home][flow] step_user: введена строка len=%d, name=%s",
                         len(qr), user_input.get(CONF_NAME))
            if not qr:
                errors["base"] = "invalid_qr"
            else:
                params = parse_qr(qr)
                _LOGGER.info("[akvilon_home][flow] parse_qr -> HOST=%s PORT=%s DEVICE_ID=%s SERVER_ID=%s PASS=%s",
                             params.get("HOST"), params.get("PORT"), params.get("DEVICE_ID"),
                             params.get("SERVER_ID"), "***" if params.get("PASS") else "")
                if not params.get("HOST") or not params.get("DEVICE_ID") or not params.get("PASS"):
                    masked = {k: ("***" if k == "PASS" else v) for k, v in params.items()}
                    _LOGGER.error("[akvilon_home][flow] Недостаточно полей после parse_qr: %s", masked)
                    errors["base"] = "invalid_qr"
                else:
                    self._params = {
                        CONF_HOST: params["HOST"],
                        CONF_PORT: int(params.get("PORT", 19090)),
                        CONF_TOKEN: params.get("SUID", ""),
                        CONF_DEVICE_ID: params["DEVICE_ID"],
                        CONF_SERVER_ID: params.get("SERVER_ID", params.get("SERVERFLAG", "") + ":" + params.get("SERVERID_NUM", "")),
                        CONF_NAME: user_input.get(CONF_NAME) or DEFAULT_NAME,
                        "_PASS": params.get("PASS", ""),
                    }
                    _LOGGER.info("[akvilon_home][flow] self._params = %s", {k: v for k, v in self._params.items() if k != "_PASS"})
                    # Пробуем подключиться и загрузить список устройств
                    try:
                        devices = await self._load_devices()
                        _LOGGER.info("[akvilon_home][flow] загружено устройств: %d", len(devices))
                        if devices:
                            self._devices = devices
                            return await self.async_step_select()
                        errors["base"] = "no_devices"
                    except Exception as exc:  # pragma: no cover
                        import traceback
                        _LOGGER.error("[akvilon_home][flow] ошибка загрузки устройств:\n%s", traceback.format_exc())
                        errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=QR_SCHEMA,
            errors=errors,
            description_placeholders={"note": "Вставьте строку подключения или отсканируйте QR-code от застройщика."},
        )

    def _build_client(self):
        from .protocol import AkvilonClient
        return AkvilonClient(
            self._params[CONF_HOST], self._params[CONF_PORT],
            self._params.get("_PASS", ""),  # cекрет подписи = PASS
            device_id=self._params[CONF_DEVICE_ID],
            server_id=self._params[CONF_SERVER_ID],
        )

    def _load_devices_sync(self):
        from .protocol import CH_CAMERAS, CH_GATES, CH_METERS
        cl = self._build_client()
        cl.connect()
        th = cl.start_reader()
        try:
            cl.subscribe()
            cl.register()
            import time
            time.sleep(0.5)
            cams = cl.get_list(CH_CAMERAS, timeout=80)
            gates = cl.get_list(CH_GATES, timeout=40)
            mets = cl.get_list(CH_METERS, timeout=40)
        finally:
            cl._running = False
            cl.close()
        return cams, gates, mets

    async def _load_devices(self):
        cams, gates, mets = await self.hass.async_add_executor_job(self._load_devices_sync)
        devices = []
        for c in cams:
            oid = str(c.get("objectid") or c.get("objectId") or "")
            if oid:
                devices.append({"id": oid, "name": f"Камера {c.get('name','')}", "type": "camera"})
        for g in gates:
            oid = str(g.get("objectid") or g.get("objectId") or "")
            if oid:
                # калитка с реальной привязкой к камере помечается как домофон
                cam = str(g.get("cameraId") or "")
                kind = "intercom" if cam and cam != "0:-1" else "gate"
                label = "Домофон" if kind == "intercom" else "Калитка"
                devices.append({"id": oid, "name": f"{label} {g.get('name','')}", "type": kind})
        for m in mets:
            oid = str(m.get("objectid") or m.get("objectId") or "")
            if oid:
                devices.append({"id": oid, "name": f"Счётчик {m.get('name','')}", "type": "meter"})
        return devices

    async def async_step_select(self, user_input: dict | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            selected = user_input.get("devices") or []
            if self._devices:
                data = dict(self._params)
                data["selected"] = selected
                title = data.get(CONF_NAME) or DEFAULT_NAME
                return self.async_create_entry(title=title, data=data)
            errors["base"] = "no_selection"

        # Мультивыбор устройств через HA SelectSelector (множественный выбор).
        # Проверено: именно через этот шаг пользователь успешно создавал entry.
        from homeassistant.helpers import selector
        options = {d["id"]: f"{d['name']} ({d['type']})" for d in self._devices}
        default_sel = list(options.keys())
        schema = vol.Schema({
            vol.Optional("devices", default=default_sel): selector.SelectSelector(
                selector.SelectSelectorConfig(options=default_sel, multiple=True)
            ),
        })
        return self.async_show_form(
            step_id="select",
            data_schema=schema,
            errors=errors,
            description_placeholders={"count": str(len(self._devices))},
        )

    async def async_step_reconfigure(self, user_input: dict | None = None) -> FlowResult:
        entry = self._get_reconfigure_entry()
        current = entry.data if entry else {}
        qr = current.get("connection_string") or ""
        schema = vol.Schema(
            {
                vol.Required("connection_string", default=qr): str,
                vol.Optional(CONF_NAME, default=entry.title if entry else DEFAULT_NAME): str,
            }
        )
        if user_input is not None:
            return await self.async_step_user(user_input)
        return self.async_show_form(step_id="reconfigure", data_schema=schema)