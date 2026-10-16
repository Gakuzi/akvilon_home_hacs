"""Config flow для интеграции Аквилон InHome.

Пошаговый мастер настройки:
  1) ввод строки подключения (QR) + название. Сразу после распознания ключа
     выполняется проверка сервера: доступен ли он, вернул ли устройства.
     Результат показывается прямо на первом шаге (понятная ошибка на русском),
     затем идёт выбор ТИПОВ устройств (камеры/калитки/домофоны/счётчики),
     выбор конкретных устройств и финальные опции (дашборд/Энергия/тарифы).

Обработка ошибок (показываются на первом шаге):
  - invalid_qr        -> не удалось распознать строку;
  - server_unreachable-> сервер здания недоступен;
  - cannot_connect    -> ошибка при подключении/загрузке;
  - no_devices        -> сервер доступен, но не вернул устройств.

Документация: https://github.com/Gakuzi/akvilon_home_hacs/blob/main/README.md
"""
import logging

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    DOMAIN,
    CONF_HOST,
    CONF_PORT,
    CONF_TOKEN,
    CONF_DEVICE_ID,
    CONF_SERVER_ID,
    CONF_NAME,
    CONF_FAVORITE_CAMERAS,
    DEFAULT_NAME,
    CAMERAS,
)
from .protocol import parse_qr

_LOGGER = logging.getLogger(__name__)

QR_SCHEMA = vol.Schema(
    {
        vol.Required("connection_string"): str,
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
    }
)

TYPE_META = {
    "camera": ("Камеры", "mdi:cctv"),
    "gate": ("Калитки", "mdi:gate"),
    "intercom": ("Домофоны", "mdi:phone-in-talk"),
    "meter": ("Счётчики", "mdi:counter"),
}
TYPE_ORDER = ["camera", "gate", "intercom", "meter"]


class AkvilonHomeFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Обработчик конфигурации интеграции Аквилон InHome."""

    VERSION = 2
    MINOR_VERSION = 1

    def __init__(self) -> None:
        self._params = {}
        self._devices = []
        self._cur_selected = []
        self._entry_title = None

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            qr = (user_input.get("connection_string") or "").strip()
            if not qr:
                errors["base"] = "invalid_qr"
            else:
                params = parse_qr(qr)
                if not params.get("HOST") or not params.get("DEVICE_ID") or not params.get("PASS"):
                    _LOGGER.error("[akvilon_home][flow] Недостаточно полей: %s", params)
                    errors["base"] = "invalid_qr"
                else:
                    self._params = {
                        CONF_HOST: params["HOST"],
                        CONF_PORT: int(params.get("PORT", 19090)),
                        CONF_TOKEN: params.get("SUID", ""),
                        CONF_DEVICE_ID: params["DEVICE_ID"],
                        CONF_SERVER_ID: params.get(
                            "SERVER_ID", params.get("SERVERFLAG", "") + ":" + params.get("SERVERID_NUM", "")
                        ),
                        CONF_NAME: user_input.get(CONF_NAME) or DEFAULT_NAME,
                        "_PASS": params.get("PASS", ""),
                    }
                    # Проверка сервера: пробуем загрузить устройства.
                    # Сервер сейчас недоступен — методами подключения нельзя
                    # отличить «нет сети» от «сервер не отвечает», поэтому
                    # при исключении показываем понятное сообщение.
                    devices = []
                    try:
                        devices = await self._load_devices()
                    except Exception as exc:  # pragma: no cover
                        _LOGGER.warning("[akvilon_home][flow] ошибка проверки сервера: %s", exc)
                        devices = []
                    if devices:
                        self._devices = devices
                        return await self.async_step_select_types()
                    errors["base"] = "no_devices"

        return self.async_show_form(
            step_id="user",
            data_schema=QR_SCHEMA,
            errors=errors,
            description_placeholders={
                "note": (
                    "Вставьте строку подключения от застройщика или QR-код. "
                    "После распознания ключа выполняется проверка соединения."
                )
            },
        )

    # ------------------------------------------------------------------
    # Шаг 2: выбор типов устройств (с иконками)
    # ------------------------------------------------------------------
    async def async_step_select_types(self, user_input: dict | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        type_count: dict[str, int] = {}
        for d in self._devices:
            type_count[d["type"]] = type_count.get(d["type"], 0) + 1
        default_types = [t for t in TYPE_ORDER if type_count.get(t, 0) > 0]

        if user_input is not None:
            chosen = user_input.get("types") or []
            chosen_set = set(chosen)
            self._devices = [d for d in self._devices if d["type"] in chosen_set]
            if self._devices:
                return await self.async_step_select()
            errors["base"] = "no_selection"

        from homeassistant.helpers import selector

        options = []
        for t in TYPE_ORDER:
            if type_count.get(t, 0) > 0:
                group_name, icon = TYPE_META.get(t, (t, "mdi:view-grid"))
                options.append(
                    {"value": t, "label": f"{group_name} · {type_count[t]}", "icon": icon}
                )
        schema = vol.Schema(
            {
                vol.Optional("types", default=default_types): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=options, multiple=True, custom_value=False, mode="list"
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="select_types",
            data_schema=schema,
            errors=errors,
            description_placeholders={"total": str(len(self._devices))},
        )

    # ------------------------------------------------------------------
    # Шаг 3: выбор конкретных устройств
    # ------------------------------------------------------------------
    async def async_step_select(self, user_input: dict | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            selected = user_input.get("devices") or []
            if self._devices:
                self._cur_selected = selected
                data = dict(self._params)
                data["selected"] = selected
                self._entry_title = data.get(CONF_NAME) or DEFAULT_NAME
                return await self.async_step_tariffs()
            errors["base"] = "no_selection"

        from homeassistant.helpers import selector

        option_list = []
        for dev in sorted(
            self._devices,
            key=lambda d: (TYPE_ORDER.index(d["type"]) if d["type"] in TYPE_ORDER else 9,
                           dev_name(d).lower()),
        ):
            group_name, icon = TYPE_META.get(dev["type"], (dev["type"], "mdi:view-grid"))
            option_list.append(
                {"value": dev["id"], "label": dev_name(dev), "icon": icon, "group": group_name}
            )
        default_sel = [d["id"] for d in self._devices]
        schema = vol.Schema(
            {
                vol.Optional("devices", default=default_sel): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=option_list, multiple=True, custom_value=False, mode="list"
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="select",
            data_schema=schema,
            errors=errors,
            description_placeholders={"count": str(len(self._devices))},
        )

    # ------------------------------------------------------------------
    # Шаг 4: проверка и настройка тарифов ЖКУ (парсер Архангельск)
    # ------------------------------------------------------------------
    async def async_step_tariffs(self, user_input: dict | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        from .tariffs import async_fetch_tariffs, DEFAULT_TARIFFS, GCAL_TO_GJ

        if user_input is not None:
            gcal = user_input.get("heating_tariff_gcal", DEFAULT_TARIFFS["heating_tariff_gcal"])
            self._params.update({
                "electricity_tariff_day": user_input.get("electricity_tariff_day", DEFAULT_TARIFFS["electricity_tariff_day"]),
                "electricity_tariff_night": user_input.get("electricity_tariff_night", DEFAULT_TARIFFS["electricity_tariff_night"]),
                "cold_water_tariff": user_input.get("cold_water_tariff", DEFAULT_TARIFFS["cold_water_tariff"]),
                "hot_water_tariff": user_input.get("hot_water_tariff", DEFAULT_TARIFFS["hot_water_tariff"]),
                "sewage_tariff": user_input.get("sewage_tariff", DEFAULT_TARIFFS["sewage_tariff"]),
                "heating_tariff_gcal": gcal,
                "heating_tariff_gj": round(float(gcal) / GCAL_TO_GJ, 2),
            })
            return await self.async_step_finish()

        # Автоматический парсинг/загрузка тарифов онлайн
        tariffs = await async_fetch_tariffs()

        schema = vol.Schema(
            {
                vol.Required(
                    "electricity_tariff_day",
                    default=tariffs.get("electricity_tariff_day", 8.67),
                ): vol.All(vol.Coerce(float), vol.Range(min=0)),
                vol.Required(
                    "electricity_tariff_night",
                    default=tariffs.get("electricity_tariff_night", 3.91),
                ): vol.All(vol.Coerce(float), vol.Range(min=0)),
                vol.Required(
                    "cold_water_tariff",
                    default=tariffs.get("cold_water_tariff", 59.60),
                ): vol.All(vol.Coerce(float), vol.Range(min=0)),
                vol.Required(
                    "hot_water_tariff",
                    default=tariffs.get("hot_water_tariff", 210.00),
                ): vol.All(vol.Coerce(float), vol.Range(min=0)),
                vol.Required(
                    "sewage_tariff",
                    default=tariffs.get("sewage_tariff", 48.24),
                ): vol.All(vol.Coerce(float), vol.Range(min=0)),
                vol.Required(
                    "heating_tariff_gcal",
                    default=tariffs.get("heating_tariff_gcal", 2550.00),
                ): vol.All(vol.Coerce(float), vol.Range(min=0)),
            }
        )
        return self.async_show_form(
            step_id="tariffs",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "info": "Тарифы получены автоматически для ЖК «Река» (Архангельск). Вы можете скорректировать их при необходимости."
            },
        )

    # ------------------------------------------------------------------
    # Шаг 5: финальные опции (дашборд и раздел «Энергия»)
    # ------------------------------------------------------------------
    async def async_step_finish(self, user_input: dict | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            data = dict(self._params)
            data["selected"] = self._cur_selected
            data["create_dashboard"] = user_input.get("create_dashboard", True)
            data["add_to_energy"] = user_input.get("add_to_energy", True)
            title = self._entry_title or data.get(CONF_NAME) or DEFAULT_NAME
            return self.async_create_entry(title=title, data=data)

        schema = vol.Schema(
            {
                vol.Optional("create_dashboard", default=True): bool,
                vol.Optional("add_to_energy", default=True): bool,
            }
        )
        return self.async_show_form(
            step_id="finish",
            data_schema=schema,
            errors=errors,
            description_placeholders={"note": "Создать автоматический дашборд «Аквилон» и связать счётчики с разделом «Энергия»?"},
        )

    # ------------------------------------------------------------------
    # Загрузка списков устройств с сервера
    # ------------------------------------------------------------------
    def _build_client(self):
        from .protocol import AkvilonClient

        return AkvilonClient(
            self._params[CONF_HOST], self._params[CONF_PORT],
            self._params.get("_PASS", ""),
            device_id=self._params[CONF_DEVICE_ID],
            server_id=self._params[CONF_SERVER_ID],
        )

    def _load_devices_sync(self):
        from .protocol import CH_CAMERAS, CH_GATES, CH_METERS

        cl = self._build_client()
        cl.connect()
        cl.start_reader()
        try:
            cl.subscribe()
            cl.register()
            import time

            time.sleep(0.5)
            cams = cl.get_list(CH_CAMERAS, timeout=25, sessions=3, batch=9)
            gates = cl.get_list(CH_GATES, timeout=15, sessions=2, batch=8)
            mets = cl.get_list(CH_METERS, timeout=15, sessions=2, batch=8)
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
                devices.append({"id": oid, "name": clean_name(c, "Камера", oid), "type": "camera"})
        for g in gates:
            oid = str(g.get("objectid") or g.get("objectId") or "")
            if oid:
                cam = str(g.get("cameraId") or "")
                kind = "intercom" if cam and cam != "0:-1" else "gate"
                label = "Домофон" if kind == "intercom" else "Калитка"
                devices.append({"id": oid, "name": clean_name(g, label, oid), "type": kind})
        for m in mets:
            oid = str(m.get("objectid") or m.get("objectId") or "")
            if oid:
                devices.append({"id": oid, "name": clean_name(m, "Счётчик", oid), "type": "meter"})
        return devices

    async def async_step_reconfigure(self, user_input: dict | None = None) -> FlowResult:
        entry = self._get_reconfigure_entry()
        current = entry.data if entry else {}
        schema = vol.Schema(
            {
                vol.Required("connection_string", default=current.get("connection_string", "")): str,
                vol.Optional(CONF_NAME, default=entry.title if entry else DEFAULT_NAME): str,
            }
        )
        if user_input is not None:
            return await self.async_step_user(user_input)
        return self.async_show_form(step_id="reconfigure", data_schema=schema)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        """Получить обработчик опций интеграции."""
        return AkvilonOptionsFlowHandler(config_entry)


class AkvilonOptionsFlowHandler(config_entries.OptionsFlow):
    """Настройка параметров и опций интеграции Аквилон InHome."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(self, user_input: dict | None = None) -> FlowResult:
        """Основной шаг управления опциями (избранные камеры, тарифы)."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        hub = self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id)
        current_favs = list(self.config_entry.options.get(CONF_FAVORITE_CAMERAS, self.config_entry.data.get(CONF_FAVORITE_CAMERAS, [])))

        # Формируем список всех доступных камер для выбора
        camera_options = []
        if hub and hub.cameras:
            for c in hub.cameras:
                cid = str(c.get("objectid") or c.get("objectId") or "")
                cname = clean_name(c, "Камера", cid)
                if cid:
                    camera_options.append({"value": cid, "label": cname})
        else:
            for cid, cname, _ in CAMERAS:
                camera_options.append({"value": cid, "label": cname})

        from homeassistant.helpers import selector

        schema = vol.Schema({
            vol.Optional(CONF_FAVORITE_CAMERAS, default=current_favs): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=camera_options,
                    multiple=True,
                    custom_value=False,
                    mode="list",
                )
            ),
            vol.Optional(
                "electricity_tariff_day",
                default=float(self.config_entry.options.get("electricity_tariff_day", self.config_entry.data.get("electricity_tariff_day", 8.67))),
            ): vol.All(vol.Coerce(float), vol.Range(min=0)),
            vol.Optional(
                "electricity_tariff_night",
                default=float(self.config_entry.options.get("electricity_tariff_night", self.config_entry.data.get("electricity_tariff_night", 3.91))),
            ): vol.All(vol.Coerce(float), vol.Range(min=0)),
            vol.Optional(
                "cold_water_tariff",
                default=float(self.config_entry.options.get("cold_water_tariff", self.config_entry.data.get("cold_water_tariff", 59.60))),
            ): vol.All(vol.Coerce(float), vol.Range(min=0)),
            vol.Optional(
                "hot_water_tariff",
                default=float(self.config_entry.options.get("hot_water_tariff", self.config_entry.data.get("hot_water_tariff", 210.00))),
            ): vol.All(vol.Coerce(float), vol.Range(min=0)),
            vol.Optional(
                "sewage_tariff",
                default=float(self.config_entry.options.get("sewage_tariff", self.config_entry.data.get("sewage_tariff", 48.24))),
            ): vol.All(vol.Coerce(float), vol.Range(min=0)),
            vol.Optional(
                "heating_tariff_gcal",
                default=float(self.config_entry.options.get("heating_tariff_gcal", self.config_entry.data.get("heating_tariff_gcal", 2550.00))),
            ): vol.All(vol.Coerce(float), vol.Range(min=0)),
        })

        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            description_placeholders={"fav_count": str(len(current_favs))},
        )


def clean_name(obj: dict, fallback_label: str, oid: str) -> str:
    """Возвращает чистое читаемое название устройства с сервера."""
    raw = str(obj.get("name") or obj.get("Name") or "").strip()
    raw = " ".join(raw.split())
    return raw if raw else f"{fallback_label} {oid}"


def dev_name(dev: dict) -> str:
    """Имя устройства для отображения в списке выбора."""
    return dev.get("name") or dev["id"]