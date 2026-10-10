"""Config flow для интеграции Аквилон InHome (максимально простой).

Поток (всё на русском, минимум шагов):
  1) «user» — вставка строки подключения (ключ/QR) и нажатие «Продолжить».
  2) «check» — проверка соединения с сервером: показывает «Соединение с сервером
     установлено» или «Не удалось соединиться». При успехе сразу грузит все
     найденные устройства и создаёт конфигурацию.

Ошибки на русском:
  - invalid_qr         -> не удалось распознать строку (неполный/неверный ключ);
  - server_unreachable -> сервер здания недоступен (нет сети / сервер выключен);
  - cannot_connect     -> ошибка при подключении/загрузке;
  - no_devices         -> сервер доступен, но не вернул устройств.
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
from .energy import (
    DEFAULT_EL_DAY,
    DEFAULT_EL_NIGHT,
    DEFAULT_WATER_COLD,
    DEFAULT_WATER_HOT,
)

_LOGGER = logging.getLogger(__name__)

QR_SCHEMA = vol.Schema(
    {
        vol.Required("connection_string"): str,
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
    }
)


class AkvilonHomeFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Обработчик конфигурации интеграции Аквилон InHome."""

    VERSION = 2
    MINOR_VERSION = 1

    def __init__(self) -> None:
        self._params = {}
        self._devices = []

    # ------------------------------------------------------------------
    # Шаг 1: ввод ключа
    # ------------------------------------------------------------------
    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            qr = (user_input.get("connection_string") or "").strip()
            if not qr:
                return self._form_user("invalid_qr")
            params = parse_qr(qr)
            if not params.get("HOST") or not params.get("DEVICE_ID") or not params.get("PASS"):
                _LOGGER.error("[akvilon_home][flow] Недостаточно полей: %s", params)
                return self._form_user("invalid_qr")
            self._params = {
                CONF_HOST: params["HOST"],
                CONF_PORT: int(params.get("PORT", 19090)),
                CONF_TOKEN: params.get("SUID", ""),
                CONF_DEVICE_ID: params["DEVICE_ID"],
                CONF_SERVER_ID: params.get(
                    "SERVER_ID",
                    params.get("SERVERFLAG", "") + ":" + params.get("SERVERID_NUM", ""),
                ),
                CONF_NAME: user_input.get(CONF_NAME) or DEFAULT_NAME,
                "_PASS": params.get("PASS", ""),
                "connection_string": qr,
            }
            # Уникальный идентификатор по DEVICE_ID+HOST: при повторной настройке
            # HA перенастроит существующий entry, а не создаст новый (иначе плодит
            # дубли entity с суффиксами _2, _3...).
            await self.async_set_unique_id(
                f"{params['DEVICE_ID']}@{params['HOST']}"
            )
            self._abort_if_unique_id_configured()
            # Ключ распознан — переходим к проверке соединения и загрузке
            return await self.async_step_check()

        return self._form_user(None)

    def _form_user(self, error: str | None) -> FlowResult:
        return self.async_show_form(
            step_id="user",
            data_schema=QR_SCHEMA,
            errors={"base": error} if error else None,
        )

    # ------------------------------------------------------------------
    # Шаг 2: проверка соединения с сервером + загрузка устройств
    # ------------------------------------------------------------------
    async def async_step_check(self, user_input: dict | None = None) -> FlowResult:
        """Проверяет соединение с сервером. Успех -> сразу создаёт entry."""
        # Быстрая проверка доступности сервера (UDP ping)
        ping_ok = False
        try:
            ping_ok = await self.hass.async_add_executor_job(self._ping_server)
        except Exception as exc:  # pragma: no cover
            _LOGGER.warning("[akvilon_home][flow] ping error: %s", exc)

        if not ping_ok:
            return await self._abort_or_form("server_unreachable")

        # Сервер доступен — грузим устройства
        devices = []
        try:
            devices = await self.hass.async_add_executor_job(self._load_devices_list)
        except Exception as exc:  # pragma: no cover
            _LOGGER.warning("[akvilon_home][flow] load error: %s", exc)

        if not devices:
            return await self._abort_or_form("no_devices")

        self._devices = devices
        return await self.async_step_tariffs()

    async def _abort_or_form(self, code: str) -> FlowResult:
        # Показываем понятную ошибку на шаге проверки
        return self.async_show_form(
            step_id="check",
            data_schema=vol.Schema({}),
            errors={"base": code},
        )

    # ------------------------------------------------------------------
    # Шаг 3: тарифы (Энергия) — Архангельск по умолчанию, можно изменить
    # ------------------------------------------------------------------
    async def async_step_tariffs(self, user_input: dict | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        has_meters = any(d.get("type") == "meter" for d in self._devices)

        if user_input is not None:
            data = dict(self._params)
            data["selected"] = [d["id"] for d in self._devices]
            data["devices"] = self._devices
            data["create_dashboard"] = True
            data["add_to_energy"] = True
            data["electricity_tariff_day"] = user_input.get("electricity_tariff_day", DEFAULT_EL_DAY)
            data["electricity_tariff_night"] = user_input.get("electricity_tariff_night", DEFAULT_EL_NIGHT)
            data["cold_water_tariff"] = user_input.get("cold_water_tariff", DEFAULT_WATER_COLD)
            data["hot_water_tariff"] = user_input.get("hot_water_tariff", DEFAULT_WATER_HOT)
            title = self._params.get(CONF_NAME) or DEFAULT_NAME
            return self.async_create_entry(title=title, data=data)

        # Если счётчиков нет — просто создаём entry без шага тарифов.
        if not has_meters:
            data = dict(self._params)
            data["selected"] = [d["id"] for d in self._devices]
            data["devices"] = self._devices
            data["create_dashboard"] = True
            data["add_to_energy"] = True
            data["electricity_tariff_day"] = DEFAULT_EL_DAY
            data["electricity_tariff_night"] = DEFAULT_EL_NIGHT
            data["cold_water_tariff"] = DEFAULT_WATER_COLD
            data["hot_water_tariff"] = DEFAULT_WATER_HOT
            title = self._params.get(CONF_NAME) or DEFAULT_NAME
            return self.async_create_entry(title=title, data=data)

        schema = vol.Schema(
            {
                vol.Required("electricity_tariff_day", default=DEFAULT_EL_DAY): vol.Coerce(float),
                vol.Required("electricity_tariff_night", default=DEFAULT_EL_NIGHT): vol.Coerce(float),
                vol.Optional("cold_water_tariff", default=DEFAULT_WATER_COLD): vol.Coerce(float),
                vol.Optional("hot_water_tariff", default=DEFAULT_WATER_HOT): vol.Coerce(float),
            }
        )
        note = (
            "Тарифы квартиры (по умолчанию — Архангельск, без газа). "
            "День/ночь электроэнергия, холодная и горячая вода. "
            "Можно изменить — значения попадут в «Энергию»."
        )
        return self.async_show_form(
            step_id="tariffs",
            data_schema=schema,
            errors=errors,
            description_placeholders={"note": note},
        )

    # ------------------------------------------------------------------
    # Клиент / загрузка (executor — не блокирует event loop)
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
        cl = self._build_client()
        try:
            return cl.ping(timeout=4.0)
        finally:
            cl._running = False
            cl.close()

    def _load_devices_list(self):
        from .protocol import CH_CAMERAS, CH_GATES, CH_METERS

        cl = self._build_client()
        cl.connect()
        cl.start_reader()
        try:
            # НЕ вызываем subscribe()/register() для списков — register() портит
            # UDP-сессию (сервер отвечает flag=0x82). Достаточно подписи PASS.
            import time

            time.sleep(0.5)
            cams = cl.get_list(CH_CAMERAS, timeout=25, sessions=3, batch=9)
            gates = cl.get_list(CH_GATES, timeout=15, sessions=2, batch=8)
            mets = cl.get_list(CH_METERS, timeout=15, sessions=2, batch=8)
        finally:
            cl._running = False
            cl.close()

        devices = []
        for c in cams:
            oid = str(c.get("objectid") or c.get("objectId") or "")
            if oid:
                devices.append({"id": oid, "name": self._clean(c, "Камера", oid), "type": "camera"})
        for g in gates:
            oid = str(g.get("objectid") or g.get("objectId") or "")
            if oid:
                cam = str(g.get("cameraId") or "")
                kind = "intercom" if cam and cam != "0:-1" else "gate"
                label = "Домофон" if kind == "intercom" else "Калитка"
                devices.append({"id": oid, "name": self._clean(g, label, oid), "type": kind})
        for m in mets:
            oid = str(m.get("objectid") or m.get("objectId") or "")
            if oid:
                devices.append({"id": oid, "name": self._clean(m, "Счётчик", oid), "type": "meter"})

        _LOGGER.info("[akvilon_home][flow] Загружено устройств: %d", len(devices))
        return devices

    @staticmethod
    def _clean(obj: dict, fallback: str, oid: str) -> str:
        raw = str(obj.get("name") or obj.get("Name") or "").strip()
        return " ".join(raw.split()) if raw else f"{fallback} {oid}"

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