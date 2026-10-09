"""Config flow для интеграции Аквилон InHome (улучшенный мастер).

Пошаговый мастер настройки (всё на русском):
  1) «user» — вставка строки подключения (QR/ключ) + название. Сразу после
     ввода выполняется автоматический разбор строки, и показывается, что
     распознано (хост, порт, устройство, сервер, пароль) с индикатором
     «распознано / не распознано»;
  2) «check_server» — проверка доступности сервера здания (быстрый UDP-тест).
     Пользователь сразу видит: «Сервер доступен», «Сервер недоступен» или
     «Сервер доступен, но не вернул устройства», с понятными подсказками;
  3) «select_types» — выбор ТИПОВ устройств (камеры/калитки/домофоны/счётчики)
     с иконками и количеством;
  4) «select» — выбор конкретных устройств (сгруппированы по типам, реальные
     имена);
  5) «finish» — доп. опции (создать дашборд, добавить в «Энергию», тарифы).

Обработка ошибок (понятные сообщения на русском):
  - invalid_qr         -> не удалось распознать строку (чего не хватает);
  - server_unreachable -> сервер здания недоступен (нет сети / сервер выключен);
  - cannot_connect     -> ошибка при подключении/загрузке;
  - no_devices         -> сервер доступен, но вернул пустой список.
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

# Метаданные типов устройств: (название группы, иконка, подсказка)
TYPE_META = {
    "camera": ("Камеры", "mdi:cctv", "Видеонаблюдение комплекса"),
    "gate": ("Калитки", "mdi:gate", "Проходы / двери, открываемые кнопкой"),
    "intercom": ("Домофоны", "mdi:phone-in-talk", "Калитки с привязанной камерой"),
    "meter": ("Счётчики", "mdi:counter", "Показания ГВС, ХВС, отопления, электричества"),
}
TYPE_ORDER = ["camera", "gate", "intercom", "meter"]

# Ключевые поля, которые должны быть распознаны из строки (для индикатора разбора)
QR_REQUIRED = [
    ("HOST", "хост сервера"),
    ("PORT", "порт"),
    ("DEVICE_ID", "устройство (DEVICE_ID)"),
    ("PASS", "пароль (PASS)"),
    ("SERVER_ID", "сервер (SERVER_ID)"),
]


class AkvilonHomeFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Обработчик конфигурации интеграции Аквилон InHome."""

    VERSION = 2
    MINOR_VERSION = 1

    def __init__(self) -> None:
        self._params = {}
        self._devices = []
        self._cur_selected = []
        self._entry_title = None

    # ------------------------------------------------------------------
    # Шаг 1: ввод ключа + разбор с индикатором
    # ------------------------------------------------------------------
    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        parsed: dict | None = None
        missing: list[str] = []

        if user_input is not None:
            qr = (user_input.get("connection_string") or "").strip()
            if not qr:
                errors["base"] = "invalid_qr"
                missing = ["строку подключения (поле пустое)"]
            else:
                parsed = parse_qr(qr)
                # что не распознано — соберём список для индикатора
                missing = [
                    label
                    for key, label in QR_REQUIRED
                    if key != "PORT" and not parsed.get(key)
                ]
                if not parsed.get("PORT"):
                    missing.append("порт")
                if not parsed.get("HOST") or not parsed.get("DEVICE_ID") or not parsed.get("PASS"):
                    _LOGGER.error("[akvilon_home][flow] Недостаточно полей: %s", parsed)
                    errors["base"] = "invalid_qr"
                else:
                    self._params = {
                        CONF_HOST: parsed["HOST"],
                        CONF_PORT: int(parsed.get("PORT", 19090)),
                        CONF_TOKEN: parsed.get("SUID", ""),
                        CONF_DEVICE_ID: parsed["DEVICE_ID"],
                        CONF_SERVER_ID: parsed.get(
                            "SERVER_ID",
                            parsed.get("SERVERFLAG", "") + ":" + parsed.get("SERVERID_NUM", ""),
                        ),
                        CONF_NAME: user_input.get(CONF_NAME) or DEFAULT_NAME,
                        "_PASS": parsed.get("PASS", ""),
                        "connection_string": qr,
                    }
                    # Строка распознана корректно — переходим к проверке сервера
                    return await self.async_step_check_server()

        # Ключевые поля для индикатора (что распознано). Без эмодзи — они
        # ломают отображение формы в HA на части устройств.
        checks = []
        if parsed:
            for key, label in QR_REQUIRED:
                val = parsed.get(key)
                ok = bool(val)
                disp = str(val) if ok else "—"
                checks.append((label, ok, disp))
        else:
            checks = [(label, False, "—") for _, label in QR_REQUIRED]

        mark_ok = "\u2713"  # ✓
        mark_bad = "\u2717"  # ✗
        indicator_lines = "; ".join(
            f"{mark_ok if ok else mark_bad} {label}: {disp}" for label, ok, disp in checks
        )
        note = (
            "Вставьте строку подключения от застройщика или QR-код — она будет "
            "автоматически распознана. Что распознано: " + indicator_lines
            + (" . Не хватает: " + ", ".join(missing) + "." if missing else "")
        )

        return self.async_show_form(
            step_id="user",
            data_schema=QR_SCHEMA,
            errors=errors,
            description_placeholders={"note": note},
        )

    # ------------------------------------------------------------------
    # Шаг 2: проверка доступности сервера (диагностика)
    # ------------------------------------------------------------------
    async def async_step_check_server(self, user_input: dict | None = None) -> FlowResult:
        """Быстрая проверка доступности сервера здания и понятный результат.

        Если сервер доступен и устройства получены — сразу переходим к выбору.
        Иначе показываем понятную причину на русском (без эмодзи — они ломают
        отрисовку формы на части устройств).
        """
        try:
            # Сначала быстрая проверка доступности (ping)
            ping_ok = await self.hass.async_add_executor_job(self._ping_server)
            if not ping_ok:
                return self.async_show_form(
                    step_id="check_server",
                    data_schema=vol.Schema({}),
                    errors={"base": "server_unreachable"},
                )
            # Сервер ответил — пробуем загрузить устройства
            devices, load_ok = await self.hass.async_add_executor_job(self._load_devices_full)
            if load_ok and devices:
                self._devices = devices
                return await self.async_step_select_types()
            return self.async_show_form(
                step_id="check_server",
                data_schema=vol.Schema({}),
                errors={"base": "no_devices"},
            )
        except Exception as exc:  # pragma: no cover
            _LOGGER.warning("[akvilon_home][flow] ошибка при проверке сервера: %s", exc)
            return self.async_show_form(
                step_id="check_server",
                data_schema=vol.Schema({}),
                errors={"base": "cannot_connect"},
            )

    # ------------------------------------------------------------------
    # Шаг 3: выбор типов устройств (с иконками и подсказками)
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
                group_name, icon, hint = TYPE_META.get(t, (t, "mdi:view-grid", ""))
                options.append(
                    {
                        "value": t,
                        "label": f"{group_name} · {type_count[t]} — {hint}",
                        "icon": icon,
                    }
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
    # Шаг 4: выбор конкретных устройств
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
                return await self.async_step_finish()
            errors["base"] = "no_selection"

        from homeassistant.helpers import selector

        option_list = []
        for dev in sorted(
            self._devices,
            key=lambda d: (TYPE_ORDER.index(d["type"]) if d["type"] in TYPE_ORDER else 9,
                           dev_name(d).lower()),
        ):
            group_name, icon, _hint = TYPE_META.get(dev["type"], (dev["type"], "mdi:view-grid", ""))
            option_list.append(
                {
                    "value": dev["id"],
                    "label": dev_name(dev),
                    "icon": icon,
                    "group": group_name,
                }
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
    # Шаг 5: финальные опции
    # ------------------------------------------------------------------
    async def async_step_finish(self, user_input: dict | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            data = dict(self._params)
            data["selected"] = self._cur_selected
            data["create_dashboard"] = user_input.get("create_dashboard", True)
            data["add_to_energy"] = user_input.get("add_to_energy", True)
            data["electricity_tariff_day"] = user_input.get("electricity_tariff_day")
            data["electricity_tariff_night"] = user_input.get("electricity_tariff_night")
            data["cold_water_tariff"] = user_input.get("cold_water_tariff")
            data["hot_water_tariff"] = user_input.get("hot_water_tariff")
            title = self._entry_title or data.get(CONF_NAME) or DEFAULT_NAME
            return self.async_create_entry(title=title, data=data)

        schema = vol.Schema(
            {
                vol.Optional("create_dashboard", default=True): bool,
                vol.Optional("add_to_energy", default=True): bool,
                vol.Optional("electricity_tariff_day", default=8.67): vol.All(
                    vol.Coerce(float), vol.Range(min=0)
                ),
                vol.Optional("electricity_tariff_night", default=3.91): vol.All(
                    vol.Coerce(float), vol.Range(min=0)
                ),
                vol.Optional("cold_water_tariff", default=0.0): vol.All(
                    vol.Coerce(float), vol.Range(min=0)
                ),
                vol.Optional("hot_water_tariff", default=0.0): vol.All(
                    vol.Coerce(float), vol.Range(min=0)
                ),
            }
        )
        return self.async_show_form(
            step_id="finish",
            data_schema=schema,
            errors=errors,
            description_placeholders={"note": "Настройте дополнительные возможности."},
        )

    # ------------------------------------------------------------------
    # Загрузка / проверка сервера (executor — не блокирует event loop)
    # ------------------------------------------------------------------
    def _build_client(self):
        from .protocol import AkvilonClient

        _pass = self._params.get("_PASS", "")
        return AkvilonClient(
            self._params[CONF_HOST], self._params[CONF_PORT],
            _pass,
            device_id=self._params[CONF_DEVICE_ID],
            server_id=self._params[CONF_SERVER_ID],
            pass_hex=_pass,  # подпись строится из pass_hex (иначе дефолт PASS_PLACEHOLDER)
        )

    def _ping_server(self) -> bool:
        """Быстрая проверка доступности сервера по UDP."""
        cl = self._build_client()
        try:
            return cl.ping(timeout=4.0)
        finally:
            cl._running = False
            cl.close()

    def _load_devices_sync(self):
        from .protocol import CH_CAMERAS, CH_GATES, CH_METERS

        cl = self._build_client()
        cl.connect()
        cl.start_reader()
        try:
            # ВАЖНО: НЕ вызываем subscribe()/register() для списков — register()
            # портит UDP-сессию (сервер отвечает flag=0x82 на GET). Подпись PASS ок.
            import time

            time.sleep(0.5)
            cams = cl.get_list(CH_CAMERAS, timeout=25, sessions=3, batch=9)
            gates = cl.get_list(CH_GATES, timeout=15, sessions=2, batch=8)
            mets = cl.get_list(CH_METERS, timeout=15, sessions=2, batch=8)
        finally:
            cl._running = False
            cl.close()
        return cams, gates, mets

    def _load_devices_full(self):
        """Возвращает (devices, ok). Загрузка всех списков и сборка устройств."""
        try:
            cams, gates, mets = self._load_devices_sync()
            devices = self._build_devices(cams, gates, mets)
            return devices, True
        except Exception as exc:  # pragma: no cover
            _LOGGER.warning("[akvilon_home][flow] загрузка устройств не удалась: %s", exc)
            return [], False

    @staticmethod
    def _build_devices(cams, gates, mets):
        devices = []
        for c in cams:
            oid = str(c.get("objectid") or c.get("objectId") or "")
            if oid:
                devices.append(
                    {"id": oid, "name": clean_name(c, "Камера", oid), "type": "camera"}
                )
        for g in gates:
            oid = str(g.get("objectid") or g.get("objectId") or "")
            if oid:
                cam = str(g.get("cameraId") or "")
                kind = "intercom" if cam and cam != "0:-1" else "gate"
                label = "Домофон" if kind == "intercom" else "Калитка"
                devices.append(
                    {"id": oid, "name": clean_name(g, label, oid), "type": kind}
                )
        for m in mets:
            oid = str(m.get("objectid") or m.get("objectId") or "")
            if oid:
                devices.append(
                    {"id": oid, "name": clean_name(m, "Счётчик", oid), "type": "meter"}
                )
        return devices

    async def _load_devices(self):
        devices, _ok = await self.hass.async_add_executor_job(self._load_devices_full)
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


def clean_name(obj: dict, fallback_label: str, oid: str) -> str:
    """Возвращает чистое читаемое название устройства с сервера."""
    raw = str(obj.get("name") or obj.get("Name") or "").strip()
    raw = " ".join(raw.split())
    return raw if raw else f"{fallback_label} {oid}"


def dev_name(dev: dict) -> str:
    """Имя устройства для отображения в списке выбора."""
    return dev.get("name") or dev["id"]