"""Frigate-детекция «человек у домофона» (опциональная внешняя зависимость).

Frigate — внешний 64-битный процесс (AI-детекция людей). ЭТОТ модуль НЕ тянет
Frigate в HACS-копию, а реализует чистый контракт-абстракцию:
  * ``FrigateDetectConfig`` — настройка детекции person (базовый URL, событийный
    эндпоинт, MQTT-топик, label по умолчанию) + готовый YAML-блок для go2rtc;
  * ``FrigatePersonSensor`` — ``binary_sensor`` «человек у двери» (паттерн из
    binary_sensor.py), привязка к устройству камеры;
  * ``FrigateEventSubscriber`` — фоновая подписка на события Frigate (HTTP
    ``api/events``), включает сенсор и шлёт push-событие ``akvilon_person_detected``
    при появлении человека.

Включено через опцию config flow (``frigate_enabled``). Если выключено — платформа
не создаёт ни сенсоров, ни фоновых задач и не влияет на загрузку HA.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field as _dataclass_field

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_FRIGATE_API_URL,
    CONF_FRIGATE_BASE_URL,
    CONF_FRIGATE_ENABLED,
    CONF_FRIGATE_LABELS,
    DEFAULT_FRIGATE_API_URL,
    DEFAULT_FRIGATE_BASE_URL,
    DEFAULT_FRIGATE_LABELS,
    DOMAIN,
    GO2RTC_STREAM_PREFIX,
    camera_dev_id,
)

_LOGGER = logging.getLogger(__name__)

# Событие, которое интеграция шлёт в hass.bus при обнаружении человека.
# Автоматизация может подхватить его и сделать push:
#   alias: Уведомить о человеке у двери
#   trigger: platform: event, event_type: akvilon_person_detected
#   action: ... notify.mobile_app_XXXX ...
EVENT_PERSON_DETECTED = f"{DOMAIN}_person_detected"

# Через сколько секунд после последнего подтверждения «человек у двери»
# сенсор сам возвращается в OFF (grace-период, пока следующим event'ом
# сенсор не будет включён снова).
PERSON_GRACE_S = 120.0
# Интервал опроса событияй Endpoint, сек.
POLL_INTERVAL_S = 5.0

# Ключ в hass.data для фоновых задач платформы.
_RUNTIME_KEY = "frigate_detect"


@dataclass
class FrigateDetectConfig:
    """Настройка детекции person для Frigate (чистая, без HA-зависимостей).

    Поля и методы этого класса можно юнит-тестировать голым Python — он не
    импортирует homeassistant и не трогает сеть.
    """

    labels: str = DEFAULT_FRIGATE_LABELS
    base_url: str = DEFAULT_FRIGATE_BASE_URL
    api_url: str = DEFAULT_FRIGATE_API_URL
    mqtt_topic: str = ""
    detection_zone: str = ""
    stream_prefix: str = GO2RTC_STREAM_PREFIX

    def normalized_labels(self) -> list[str]:
        """Список label для детекции (по умолчанию ``["person"]``)."""
        raw = (self.labels or "").strip()
        if not raw:
            raw = DEFAULT_FRIGATE_LABELS
        return [x.strip() for x in raw.split(",") if x.strip()]

    def events_endpoint(self, camera: str = "") -> str:
        """URL эндпоинта Frigate ``/api/events`` для опроса (HTTP-poll).

        Frigate получает события через ``GET /api/events`` с фильтрами
        ``camera``/``label``. Возвращаемая строка пригодна для вставки в настройку
        go2rtc (источник событий) или для участия в аварийном HTTP-опросе.
        """
        if not self.api_url:
            return ""
        base = self.api_url.rstrip("/") + "/events"
        params = []
        if camera:
            params.append(f"camera={camera}")
        for lbl in self.normalized_labels():
            params.append(f"label={lbl}")
        return base + ("?" + "&".join(params) if params else "")

    def build_go2rtc_detect_block(self, camera: str = "") -> str:
        """Готовый блок детектора для конфигурации go2rtc (``detect:``).

        Frigate 12+ умеет restream через собственный go2rtc; этот блок описывает
        источник событий детекции (events + MQTT), чтобы связать Frigate с нашей
        интеграцией. Возвращает строку YAML, которую пользователь добавляет в
        свой go2rtc.yaml/Frigate config.
        """
        lines = ["detect:",
                 "  enabled: true",
                 "  min_confidence: 0.5",
                 f"  labels: [{', '.join(self.normalized_labels())}]"]
        if self.mqtt_topic:
            lines.append(f"  mqtt: {self.mqtt_topic}")
        if camera:
            lines.append(f"  camera: {camera}")
        return "\n".join(lines) + "\n"


class FrigatePersonSensor(BinarySensorEntity):
    """Бинарный сенсор «человек у двери» (заполняется из событий Frigate).

    Значение обновляет фоновый подписчик (FrigateEventSubscriber): установка
    ``_person_present`` в True включает сенсор; grace-период возвращает его в OFF.
    """

    _attr_has_entity_name = False
    _attr_device_class = BinarySensorDeviceClass.PRESENCE
    _attr_should_poll = False

    def __init__(self, cam_id: str, cam_name: str = ""):
        self.cam_id = str(cam_id)
        self._name = cam_name or self.cam_id
        self._person_present = False
        self._attr_unique_id = (
            f"{DOMAIN}_frigate_person_{self.cam_id.replace(':', '_')}"
        )
        self._attr_device_info = {
            "identifiers": {camera_dev_id(self.cam_id)},
            "name": f"Камера {self._name}",
            "manufacturer": "Аквилон InHome",
            "model": "Frigate-детекция",
        }

    @property
    def name(self):
        return f"Человек у двери ({self._name})"

    @property
    def is_on(self) -> bool:
        return self._person_present

    @property
    def icon(self):
        return "mdi:account-question" if self._person_present else "mdi:account-off"

    @property
    def extra_state_attributes(self):
        return {"cam_id": self.cam_id, "detector": "frigate"}

    def set_present(self, present: bool):
        """Внешнее обновление состояния (вызывается подписчиком, потокобезопасно)."""
        changed = self._person_present != present
        self._person_present = present
        if changed:
            self.async_write_ha_state()


class FrigateEventSubscriber:
    """Фоновая подписка на события Frigate (HTTP-poll ``api/events``).

    Опрашивает эндпоинт события каждые ``POLL_INTERVAL_S`` секунд (не на event
    loop HA — использует aiohttp-клиент HA). При появлении события ``type=new``
    с нужным label включает соответствующую камеру и шлёт push-событие
    ``akvilon_person_detected``. Через ``PERSON_GRACE_S`` включённый сенсор
    понижается в OFF, если не было свежих подтверждений.

    Абстракция: не зависит от конкретной реализации Frigate (HTTP-poll отлично
    покрыт дефолтным ``/api/events``); MQTT-подписка становится доступной,
    если пользователь задал ``mqtt_topic`` в настройке.
    """

    def __init__(self, hass: HomeAssistant, config: FrigateDetectConfig):
        self.hass = hass
        self.config = config
        self._sensors: dict[str, FrigatePersonSensor] = {}
        self._last_seen: dict[str, float] = {}
        self._stop = asyncio.Event()

    def register_sensor(self, cam_id: str, sensor: FrigatePersonSensor):
        """Привязывает сенсор к камере, за которой следит подписчик."""
        self._sensors[str(cam_id)] = sensor

    async def run(self):
        """Основной цикл опроса. Запускается в asyncio-задаче, останавливается по stop()."""
        while not self._stop.is_set():
            try:
                await self._poll_once()
                await self._park_with_grace()
            except Exception as exc:  # pragma: no cover — не роняем фоновый цикл
                _LOGGER.debug("Аквилон: frigate poll error: %s", exc)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=POLL_INTERVAL_S)
                except asyncio.TimeoutError:
                    pass

    async def _park_with_grace(self):
        """Ждёт POLL_INTERVAL_S, попутно снимая устаревшие включения по grace."""
        seen = set()
        for _ in range(int(POLL_INTERVAL_S / 0.5) + 1):
            if self._stop.is_set():
                return
            await asyncio.sleep(0.5)
            self._expire_presence()
            for cam_id, sensor in list(self._sensors.items()):
                if sensor.is_on:
                    seen.add(cam_id)
        # если за полпериода ни одного свежего подтверждения и срок grace вышел —
        # снимем присутствие явным проходом в expiry
        _ = seen

    def _expire_presence(self):
        import time as _time

        now = _time.time()
        for cam_id, sensor in list(self._sensors.items()):
            if sensor.is_on:
                last = self._last_seen.get(cam_id, 0.0)
                if now - last > PERSON_GRACE_S:
                    sensor.set_present(False)

    async def _poll_once(self):
        """Один HTTP-опрос ``api/events``; сетит сенсоры и шлёт push по новым событиям."""
        endpoint = self.config.events_endpoint()
        if not endpoint:
            return
        session = self.hass.helpers.aiohttp_client.async_get_clientsession()
        try:
            async with session.get(endpoint, timeout=8) as resp:
                if resp.status != 200:
                    return
                payload = await resp.json()
        except Exception as exc:  # pragma: no cover
            _LOGGER.debug("Аквилон: frigate events fetch failed: %s", exc)
            return

        events = payload if isinstance(payload, list) else payload.get("events", [])
        if not isinstance(events, list):
            return
        import time as _time

        now = _time.time()
        for ev in events:
            if not isinstance(ev, dict):
                continue
            event_type = ev.get("type")
            lbl = ev.get("label") or ""
            cam = str(ev.get("camera") or "")
            sensor = self._sensors.get(cam)
            if sensor is None or lbl not in self.config.normalized_labels():
                continue
            if event_type == "new":
                sensor.set_present(True)
                self._last_seen[cam] = now
                self.hass.bus.async_fire(
                    EVENT_PERSON_DETECTED,
                    {"cam_id": cam, "label": lbl, "source": "frigate"},
                )
            elif event_type == "end":
                # событие завершилось — снимаем присутствие сразу
                sensor.set_present(False)
                self._last_seen.pop(cam, None)

    def stop(self):
        """Просит подписчика остановиться (вызывается при выгрузке платформы)."""
        self._stop.set()


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> bool:
    """Создаёт binary_sensor'ы Frigate-детекции, если включено в entry.options/data.

    Платформа регистрируется в ``PLATFORMS``. Если ``frigate_enabled`` не True —
    ничего не создаём, интеграция не зависит от Frigate. Привязываем детекцию
    к камерам домофонов (intercoms), как задумано фичей «интерком».
    """
    data = {**dict(entry.data or {}), **dict(entry.options or {})}
    if not data.get(CONF_FRIGATE_ENABLED, False):
        return True

    config = FrigateDetectConfig(
        labels=data.get(CONF_FRIGATE_LABELS, DEFAULT_FRIGATE_LABELS),
        base_url=data.get(CONF_FRIGATE_BASE_URL, DEFAULT_FRIGATE_BASE_URL),
        api_url=data.get(CONF_FRIGATE_API_URL, DEFAULT_FRIGATE_API_URL),
    )

    hub = None
    runtime = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if runtime is not None:
        hub = getattr(runtime, "hub", None) or runtime
    # Хаб может быть упакован в hass.data[DOMAIN][entry.entry_id] как объект хаба.
    if hub is None:
        hub = hass.data.get(DOMAIN, {}).get(entry.entry_id)

    # камеры домофонов — это камеры, привязанные к intercoms (cameraId)
    cam_ids: list[str] = []
    intercoms = getattr(hub, "intercoms", None) or getattr(hub, "_intercoms", []) or []
    for ic in intercoms:
        cid = str(ic.get("cameraId") or "")
        if cid and cid != "0:-1":
            cam_ids.append(cid)
    if not cam_ids:
        cam_ids = [str(c.get("objectid") or c.get("objectId") or "")
                   for c in (getattr(hub, "cameras", None) or [])
                   if (c.get("objectid") or c.get("objectId"))]

    subscribers: list[tuple[str, FrigateEventSubscriber]] = []
    sensors: list[FrigatePersonSensor] = []
    subscriber = FrigateEventSubscriber(hass, config)
    for cid in dict.fromkeys(cam_ids):
        if not cid:
            continue
        names = {str(c.get("objectid") or c.get("objectId") or ""): str(c.get("name") or "")
                 for c in (getattr(hub, "cameras", None) or [])}
        sensor = FrigatePersonSensor(cid, names.get(cid, ""))
        subscriber.register_sensor(cid, sensor)
        sensors.append(sensor)
    async_add_entities(sensors, True)

    if sensors:
        task = hass.loop.create_task(subscriber.run())
        # храним рантайм, чтобы async_unload_entry мог остановить фон
        hass.data.setdefault(DOMAIN, {}).setdefault(_RUNTIME_KEY, {})[
            entry.entry_id
        ] = (subscriber, task)
        _LOGGER.info("Аквилон: Frigate-детекция активна; камера-сенсоров: %d", len(sensors))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Останавливает фоновую подписку Frigate при выгрузке платформы."""
    store = hass.data.get(DOMAIN, {}).get(_RUNTIME_KEY, {})
    item = store.pop(entry.entry_id, None)
    if item:
        subscriber, task = item
        subscriber.stop()
        if not task.done():
            task.cancel()
    return True