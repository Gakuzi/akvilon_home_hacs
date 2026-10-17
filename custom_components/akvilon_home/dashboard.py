"""Автоматическое создание/удаление дашборда «Аквилон» в Home Assistant.

При setup интеграции регистрируется Lovelace-дашборд `akvilon` в сайдбаре,
при unload — удаляется. Дашборд строится АВТОМАТИЧЕСКИ из живых данных сервера
(камеры, калитки, домофоны, счётчики), поэтому новые устройства появляются
сами.

Включает виды:
  1. Обзор (overview): состояние сервера, пинг, быстрые калитки, избранные камеры, ЖКУ.
  2. Камеры (cameras): избранные камеры вверху + группировка по зонам (двор, парадные, улица).
  3. Калитки (gates): карточки открытия калиток с привязанным видеопотоком.
  4. Домофоны (intercoms): полноэкранный видеодомофон, документация потока, симулятор звонка.
  5. Счётчики (meters): детальные показания ЭЭ (день/ночь), ХВС, ГВС, отопления, расчет за месяц.
  6. Диагностика (diagnostics): мониторинг соединения, пинг, ошибки, сокеты, кнопка синхронизации.
  7. Киоск (kiosk): компактный режим для настенного планшета или ТВ.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
from typing import Any

_LOGGER = logging.getLogger(__name__)

DASH_KEY = "lovelace.dashboard_akvilon"
STORAGE_DIR = "/config/.storage"

INTERCOM_CARD_RESOURCE = "local/akvilon/akvilon-intercom-card.js"
CAMERA_CARD_RESOURCE = "local/akvilon/akvilon-camera-card.js"
WWW_RESOURCE = "/config/www/akvilon/akvilon-intercom-card.js"

_AUTO_SUFFIX = ("_2", "_3", "_4", "_5")


def _get_storage_dir(hass: Any = None) -> str:
    """Определяет актуальный путь к .storage."""
    if hass is not None and hasattr(hass, "config") and hasattr(hass.config, "path"):
        return hass.config.path(".storage")
    for cand in ("/config/.storage", "/Users/evgeniy/ha_test/config/.storage"):
        if os.path.exists(cand):
            return cand
    return STORAGE_DIR


def _get_www_dir(hass: Any = None) -> str:
    """Определяет актуальный путь к папке www для custom cards."""
    if hass is not None and hasattr(hass, "config") and hasattr(hass.config, "path"):
        return hass.config.path("www")
    for cand in ("/config/www", "/Users/evgeniy/ha_test/config/www"):
        if os.path.exists(cand):
            return cand
    return "/config/www"


class _Resolver:
    """Резолвит сущности по реальному entity_registry и states."""

    def __init__(self, hass: Any | None):
        self._entities = set()
        self._states = {}
        if hass is not None:
            try:
                for state in hass.states.async_all():
                    self._entities.add(state.entity_id)
                    self._states[state.entity_id] = state
            except Exception:
                pass
            try:
                from homeassistant.helpers import entity_registry as er
                reg = er.async_get(hass)
                for entry in reg.entities.values():
                    if entry.entity_id:
                        self._entities.add(entry.entity_id)
            except Exception:
                pass

        # Fallback: если hass не передан или пуст, читаем core.entity_registry напрямую
        if not self._entities:
            try:
                storage_dir = _get_storage_dir(hass)
                reg_file = os.path.join(storage_dir, "core.entity_registry")
                if os.path.exists(reg_file):
                    with open(reg_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    for item in data.get("data", {}).get("entities", []):
                        eid = item.get("entity_id")
                        if eid:
                            self._entities.add(eid)
            except Exception:
                pass

    def find(self, prefix: str, substr: str = "") -> list[str]:
        """Все реальные id, чей префикс совпадает (и при необходимости подстрока)."""
        out = []
        for e in self._entities:
            if e.startswith(prefix) and (not substr or substr.lower() in e.lower()):
                out.append(e)
        out.sort()
        return out

    def resolve(self, base: str) -> str:
        """Возвращает существующий entity_id по точному имени или с суффиксом _N."""
        if not base:
            return ""
        if base in self._entities:
            return base
        for suf in _AUTO_SUFFIX:
            cand = base + suf
            if cand in self._entities:
                return cand
        return ""

    def get_friendly_name(self, eid: str) -> str:
        st = self._states.get(eid)
        if st and st.attributes.get("friendly_name"):
            return st.attributes["friendly_name"]
        return eid.split(".")[-1].replace("_", " ").title()


def build_dashboard_payload(hass: Any = None, hub=None) -> dict:
    """Строит структуру Lovelace-дашборда на основе РЕАЛЬНОГО entity_registry."""
    r = _Resolver(hass)

    # 1. Системные и диагностические сенсоры
    online_entity = (
        r.resolve("binary_sensor.akvilon_server_onlain")
        or r.resolve("binary_sensor.server_zdaniia_onlain")
    )
    latency_entity = r.resolve("sensor.akvilon_zaderzhka_servera")
    status_entity = r.resolve("sensor.akvilon_sostoianie_sistemy")
    tc_sensors = r.find("sensor.akvilon_stoimost_zhku")
    total_cost_entity = tc_sensors[0] if tc_sensors else (
        r.resolve("sensor.akvilon_stoimost_zhku_za_mesiats")
        or r.resolve("sensor.akvilon_stoimost_zhku_za_mesiatc")
    )

    # 2. Вызовы домофона
    call_sensors = r.find("binary_sensor.akvilon_home_intercom_call")
    call_sensor = call_sensors[0] if call_sensors else r.resolve("binary_sensor.akvilon_home_intercom_call_1")

    # 3. Камеры
    cam_ids = r.find("camera.")

    # Определение избранных камер
    fav_cams = []
    # Сначала проверяем hub.favorite_cameras
    if hub and getattr(hub, "favorite_cameras", None):
        fav_set = set(hub.favorite_cameras)
        for c in cam_ids:
            st = r._states.get(c)
            cid = st.attributes.get("cam_id") or st.attributes.get("objectid") if st else None
            if cid and cid in fav_set:
                fav_cams.append(c)
            elif any(fav_part in c for fav_part in fav_set):
                fav_cams.append(c)

    # Если в стейтах есть флаг is_favorite
    if not fav_cams:
        for c in cam_ids:
            st = r._states.get(c)
            if st and st.attributes.get("is_favorite"):
                fav_cams.append(c)

    # Дефолтный fallback избранных камер (главные зоны)
    if not fav_cams and cam_ids:
        default_favorites = [
            "camera.kamera_dvor_2",
            "camera.kamera_paradnaia_1_1",
            "camera.kamera_reka_5_1",
            "camera.kamera_ul_sovetskaia",
            "camera.kamera_kholl_lifta_1p",
        ]
        for df in default_favorites:
            res = r.resolve(df)
            if res and res not in fav_cams:
                fav_cams.append(res)
        if not fav_cams:
            fav_cams = cam_ids[:4]

    # 4. Калитки и двери
    gate_btns = r.find("button.otkryt_kalitka")
    dom_btns = r.find("button.otkryt_domofon") + r.find("button.otkryt_reka")
    all_door_btns = gate_btns + dom_btns
    gate_state = r.find("sensor.kalitka")
    dom_sensors = r.find("sensor.domofon")

    # 5. Счётчики и тарифы (фильтруем служебные _cost, технический _gj и дубли общего электричества)
    all_meters = r.find("sensor.schetchik")
    has_day_night = any("_den" in m or "_noch" in m or "_t1" in m for m in all_meters)
    meter_entities = [
        m for m in all_meters
        if not m.endswith("_cost")
        and not any(m.endswith(sfx) for sfx in ("_gj", "_gdz", "_gdzh"))
        and not (has_day_night and m.endswith("_elektrichestvo"))
    ]

    all_tariffs = r.find("sensor.tarif")
    # Для пользователя на дашборде скрываем технический тариф ГДж, оставляем понятный тариф в Гкал
    tariff_entities = [
        t for t in all_tariffs
        if not any(t.endswith(sfx) for sfx in ("_gj", "_gdz", "_gdzh"))
    ]

    def intercom_card(title: str, btn: str, cam: str = "", status: str = "", intercom_call: str = ""):
        return {
            "type": "custom:akvilon-intercom-card",
            "title": title,
            "call_sensor": intercom_call or "",
            "gate_button": btn,
            "camera_entity": cam or "",
            "status_sensor": status or "",
            "show_fullscreen_button": True,
        }

    # =========================================================================
    # ВИД 1: ОБЗОР (Overview)
    # =========================================================================
    overview_cards = []

    # Заголовок
    overview_cards.append({
        "type": "heading",
        "heading": "ЖК «Река» · Akvilon InHome",
        "heading_style": "title",
        "icon": "mdi:home-city",
    })

    # Баннер статуса системы и сервера здания
    status_tiles = []
    if status_entity:
        status_tiles.append({
            "type": "tile",
            "entity": status_entity,
            "name": "Система здания",
            "icon": "mdi:shield-check",
            "color": "green",
        })
    if latency_entity:
        status_tiles.append({
            "type": "tile",
            "entity": latency_entity,
            "name": "Пинг сервера",
            "icon": "mdi:speedometer",
            "color": "blue",
        })
    if online_entity:
        status_tiles.append({
            "type": "tile",
            "entity": online_entity,
            "name": "Сервер онлайн",
            "icon": "mdi:server-network",
            "color": "cyan",
        })
    if total_cost_entity:
        status_tiles.append({
            "type": "tile",
            "entity": total_cost_entity,
            "name": "ЖКУ за месяц",
            "icon": "mdi:cash-multiple",
            "color": "orange",
        })

    if status_tiles:
        overview_cards.append({
            "type": "grid",
            "columns": 4,
            "square": False,
            "cards": status_tiles,
        })

    # Всплывающее предупреждение при активном вызове домофона
    if call_sensor:
        overview_cards.append({
            "type": "conditional",
            "conditions": [{"entity": call_sensor, "state": "on"}],
            "card": {
                "type": "vertical-stack",
                "cards": [
                    {
                        "type": "markdown",
                        "content": "### 🔔 Входящий вызов домофона!\nЗвонок в квартиру с панели вызова. Нажмите «Открыть», чтобы впустить посетителя.",
                    },
                    {
                        "type": "horizontal-stack",
                        "cards": [
                            {
                                "type": "button",
                                "name": "Открыть калитку",
                                "icon": "mdi:door-open",
                                "color": "green",
                                "tap_action": {
                                    "action": "call-service",
                                    "service": "akvilon_home.intercom_unlock",
                                },
                            },
                            {
                                "type": "button",
                                "name": "Ответить со звуком",
                                "icon": "mdi:phone",
                                "color": "blue",
                                "tap_action": {
                                    "action": "call-service",
                                    "service": "akvilon_home.intercom_answer",
                                },
                            },
                            {
                                "type": "button",
                                "name": "Сбросить вызов",
                                "icon": "mdi:phone-hangup",
                                "color": "red",
                                "tap_action": {
                                    "action": "call-service",
                                    "service": "akvilon_home.clear_call",
                                },
                            },
                        ],
                    },
                ],
            },
        })

    # Секция: ⭐ Избранные камеры
    overview_cards.append({
        "type": "heading",
        "heading": "⭐ Избранные камеры",
        "heading_style": "subtitle",
    })
    fav_cards = [
        {
            "type": "custom:akvilon-camera-card",
            "entity": c,
            "name": r.get_friendly_name(c),
            "lazy": True,
            "refresh_interval": 15,
        }
        for c in fav_cams
    ]
    if fav_cards:
        overview_cards.append({
            "type": "grid",
            "columns": 2,
            "square": False,
            "cards": fav_cards,
        })
    else:
        overview_cards.append({
            "type": "markdown",
            "content": "⭐ Камеры не выбраны в избранное. Выберите камеры в меню **Настройки → Устройства и службы → Аквилон → Настроить**.",
        })

    # Секция: Быстрые действия (Калитки в 1 клик)
    overview_cards.append({
        "type": "heading",
        "heading": "Быстрый доступ · Калитки и двери",
        "heading_style": "subtitle",
    })
    quick_gates = all_door_btns[:8] if all_door_btns else []
    quick_gate_cards = [
        {
            "type": "tile",
            "entity": b,
            "name": r.get_friendly_name(b).replace("Открыть ", ""),
            "icon": "mdi:gate",
            "color": "teal",
            "vertical": True,
            "tap_action": {"action": "call-service", "service": "button.press", "target": {"entity_id": b}},
        }
        for b in quick_gates
    ]
    if quick_gate_cards:
        overview_cards.append({
            "type": "grid",
            "columns": 4,
            "square": False,
            "cards": quick_gate_cards,
        })

    # Секция: Сводка ЖКУ
    overview_cards.append({
        "type": "heading",
        "heading": "Счётчики и коммунальные услуги",
        "heading_style": "subtitle",
    })
    meter_tiles = [
        {
            "type": "tile",
            "entity": m,
            "name": r.get_friendly_name(m).replace("Счётчик Квартира 31 ", ""),
            "icon": "mdi:counter",
        }
        for m in meter_entities
    ]
    if meter_tiles:
        overview_cards.append({
            "type": "grid",
            "columns": 5,
            "square": False,
            "cards": meter_tiles,
        })

    # =========================================================================
    # ВИД 2: КАМЕРЫ (Cameras)
    # =========================================================================
    # =========================================================================
    # ВИД 2: КАМЕРЫ (Cameras) — Интерактивный хаб с боковым меню и пагинацией
    # =========================================================================
    zone_dvor = []
    zone_ulitsa = []
    zone_paradnye = []
    zone_lift = []
    zone_kolias = []
    zone_reka7 = []
    zone_reka6 = []
    zone_reka5 = []
    zone_other = []

    for c in cam_ids:
        clow = c.lower()
        fn = r.get_friendly_name(c).lower()
        if any(k in clow or k in fn for k in ("lift", "лифт", "kholl_lifta", "холл лифта")):
            zone_lift.append(c)
        elif any(k in clow or k in fn for k in ("koliasochnaia", "колясочная", "prokhod", "проход")):
            zone_kolias.append(c)
        elif any(k in clow or k in fn for k in ("dvor", "двор", "detskaia", "детская")):
            zone_dvor.append(c)
        elif any(k in clow or k in fn for k in ("sovetskaia", "советская", "proezd", "проезд")):
            zone_ulitsa.append(c)
        elif any(k in clow or k in fn for k in ("paradnaia", "парадная", "podezd", "подъезд")):
            zone_paradnye.append(c)
        elif "reka_7" in clow or "река 7" in fn:
            zone_reka7.append(c)
        elif "reka_6" in clow or "река 6" in fn:
            zone_reka6.append(c)
        elif "reka_5" in clow or "река 5" in fn:
            zone_reka5.append(c)
        else:
            zone_other.append(c)

    def to_cam_objs(cams: list[str]) -> list[dict]:
        return [{"entity": c, "name": r.get_friendly_name(c)} for c in cams]

    camera_categories = [
        {
            "id": "fav",
            "title": "Избранные камеры",
            "icon": "⭐",
            "cameras": to_cam_objs(fav_cams),
        },
        {
            "id": "dvor",
            "title": "Двор и площадка",
            "icon": "🌳",
            "cameras": to_cam_objs(zone_dvor),
        },
        {
            "id": "ulica",
            "title": "Улица и въезды",
            "icon": "🚗",
            "cameras": to_cam_objs(zone_ulitsa),
        },
        {
            "id": "parad",
            "title": "Парадные и подъезды",
            "icon": "🚪",
            "cameras": to_cam_objs(zone_paradnye),
        },
        {
            "id": "lift",
            "title": "Лифты и холлы",
            "icon": "🛗",
            "cameras": to_cam_objs(zone_lift),
        },
        {
            "id": "kolias",
            "title": "Колясочные и проходы",
            "icon": "🚲",
            "cameras": to_cam_objs(zone_kolias),
        },
        {
            "id": "reka7",
            "title": "Корпус «Река 7»",
            "icon": "🏢",
            "cameras": to_cam_objs(zone_reka7),
        },
        {
            "id": "reka6",
            "title": "Корпус «Река 6»",
            "icon": "🏢",
            "cameras": to_cam_objs(zone_reka6),
        },
        {
            "id": "reka5",
            "title": "Корпус «Река 5»",
            "icon": "🏢",
            "cameras": to_cam_objs(zone_reka5),
        },
    ]

    if zone_other:
        camera_categories.append({
            "id": "other",
            "title": "Другие камеры",
            "icon": "📹",
            "cameras": to_cam_objs(zone_other),
        })

    camera_categories.append({
        "id": "all",
        "title": "Все камеры",
        "icon": "📹",
        "cameras": to_cam_objs(cam_ids),
    })

    camera_cards = [
        {
            "type": "custom:akvilon-camera-hub",
            "title": "Видеонаблюдение ЖК «Река»",
            "page_size": 6,
            "categories": camera_categories,
        }
    ]

    # =========================================================================
    # ВИД 3: КАЛИТКИ И ВОРОТА (Gates)
    # =========================================================================
    gate_cards = [
        {
            "type": "heading",
            "heading": "Калитки и проходы территории",
            "heading_style": "title",
            "icon": "mdi:gate",
        }
    ]

    intercom_gate_cards = []
    for btn in all_door_btns:
        core = btn.split("button.otkryt_")[-1]
        status = next((s for s in gate_state if core in s), "")
        cam = next((c for c in cam_ids if core in c or core.replace("kalitka_", "") in c), "")
        title = r.get_friendly_name(btn).replace("Открыть ", "")
        intercom_gate_cards.append(intercom_card(title, btn, cam, status, call_sensor))

    if intercom_gate_cards:
        gate_cards.append({
            "type": "grid",
            "columns": 2,
            "square": False,
            "cards": intercom_gate_cards,
        })
    else:
        gate_cards.append({"type": "markdown", "content": "Калитки не найдены в конфигурации."})

    # =========================================================================
    # ВИД 4: ДОМОФОНЫ (Intercoms)
    # =========================================================================
    intercom_cards = [
        {
            "type": "heading",
            "heading": "Видеодомофон и связь с парадными",
            "heading_style": "title",
            "icon": "mdi:phone-in-talk",
        },
        {
            "type": "markdown",
            "content": (
                "### Архитектура потока домофона Akvilon InHome\n\n"
                "▸ **Видеопоток:** RTP H.264 (RFC 6184) передается по UDP с сервера здания. При открытии домофона сервер выдает одноразовый `videoToken` и UDP-порт. Активация выполняется отправкой датаграммы `\\x00\\x00 + token`.\n\n"
                "▸ **Канал вызова:** Фоновый Push-Listener держит постоянный сокет (канал `0x200`) с интервалом keepalive 15 сек. При наборе квартиры сервер пушит событие вызова.\n\n"
                "▸ **Двустороннее аудио:** RTP-модуль `voice_rtp.py` с кодеком G.711 / Opus подключается к `voiceHost:voicePort`.\n\n"
                "▸ **Электрозамок:** Команда открытия `0x30301` передается напрямую в контроллер калитки."
            ),
        },
        {
            "type": "heading",
            "heading": "Тестирование вызова и автоматизаций",
            "heading_style": "subtitle",
        },
        {
            "type": "horizontal-stack",
            "cards": [
                {
                    "type": "button",
                    "name": "Симулировать входящий звонок",
                    "icon": "mdi:phone-ring",
                    "color": "amber",
                    "tap_action": {
                        "action": "call-service",
                        "service": "akvilon_home.simulate_call",
                    },
                },
                {
                    "type": "button",
                    "name": "Сбросить вызов",
                    "icon": "mdi:phone-hangup",
                    "color": "red",
                    "tap_action": {
                        "action": "call-service",
                        "service": "akvilon_home.clear_call",
                    },
                },
            ],
        },
    ]

    dom_specific_cards = []
    for btn in dom_btns:
        key = btn.split("button.otkryt_")[-1]
        status = next((s for s in dom_sensors if (key.replace("domofon_", "") in s)), "")
        cam = next((c for c in cam_ids if key.replace("domofon_", "") in c), "")
        title = r.get_friendly_name(btn).replace("Открыть ", "")
        dom_specific_cards.append(intercom_card(title, btn, cam, status, call_sensor))

    if dom_specific_cards:
        intercom_cards.append({
            "type": "grid",
            "columns": 2,
            "square": False,
            "cards": dom_specific_cards,
        })

    # =========================================================================
    # ВИД 5: СЧЁТЧИКИ (Meters & Tariffs)
    # =========================================================================
    meter_cards = [
        {
            "type": "heading",
            "heading": "Приборы учёта и начисления ЖКУ",
            "heading_style": "title",
            "icon": "mdi:counter",
        }
    ]

    if total_cost_entity:
        meter_cards.append({
            "type": "tile",
            "entity": total_cost_entity,
            "name": "Итоговая расчетная стоимость ЖКУ за текущий объем",
            "icon": "mdi:cash-check",
            "color": "green",
            "vertical": False,
        })

    # Тарифы
    meter_cards.append({
        "type": "heading",
        "heading": "Действующие тарифы ЖКУ (Архангельск)",
        "heading_style": "subtitle",
    })
    tariff_tiles = [
        {
            "type": "tile",
            "entity": t,
            "name": r.get_friendly_name(t).replace("Тариф ", ""),
            "icon": "mdi:currency-rub",
        }
        for t in tariff_entities
    ]
    if tariff_tiles:
        meter_cards.append({
            "type": "grid",
            "columns": 3,
            "square": False,
            "cards": tariff_tiles,
        })

    # Показания счётчиков
    meter_cards.append({
        "type": "heading",
        "heading": "Текущие показания приборов учёта",
        "heading_style": "subtitle",
    })
    readings = [
        {
            "type": "tile",
            "entity": m,
            "name": r.get_friendly_name(m).replace("Счётчик Квартира 31 ", ""),
            "icon": "mdi:numeric",
            "color": "cyan",
        }
        for m in meter_entities
    ]
    if readings:
        meter_cards.append({
            "type": "grid",
            "columns": 2,
            "square": False,
            "cards": readings,
        })

    # Аналитика затрат и учет энергоресурсов (Energy Dashboard)
    meter_cards.append({
        "type": "heading",
        "heading": "Аналитика затрат и начислений ЖКУ",
        "heading_style": "subtitle",
    })
    meter_cards.append({
        "type": "energy-date-selection",
    })
    meter_cards.append({
        "type": "energy-sources-table",
    })
    meter_cards.append({
        "type": "energy-cost-graph",
    })
    meter_cards.append({
        "type": "energy-gas-graph",
        "title": "🔥 Теплоснабжение (Отопление)",
    })
    meter_cards.append({
        "type": "energy-water-graph",
        "title": "💧 Водоснабжение (ХВС / ГВС)",
    })

    # Кнопка перехода в панель Энергия
    meter_cards.append({
        "type": "button",
        "name": "Открыть официальную панель «Энергия» Home Assistant",
        "icon": "mdi:lightning-bolt-circle",
        "color": "blue",
        "tap_action": {
            "action": "navigate",
            "navigation_path": "/energy",
        },
    })

    # =========================================================================
    # ВИД 6: ДИАГНОСТИКА СЕРВЕРА (Diagnostics)
    # =========================================================================
    diag_cards = [
        {
            "type": "heading",
            "heading": "Диагностика сервера здания и каналов связи",
            "heading_style": "title",
            "icon": "mdi:server-network",
        },
    ]

    status_cards = []
    if status_entity:
        status_cards.append({"type": "tile", "entity": status_entity, "name": "Состояние системы", "icon": "mdi:shield-check", "color": "green"})
    if latency_entity:
        status_cards.append({"type": "tile", "entity": latency_entity, "name": "Задержка сервера (пинг)", "icon": "mdi:speedometer", "color": "blue"})
    if online_entity:
        status_cards.append({"type": "tile", "entity": online_entity, "name": "Доступность сервера", "icon": "mdi:lan-connect", "color": "teal"})

    if status_cards:
        diag_cards.append({
            "type": "grid",
            "columns": 3,
            "square": False,
            "cards": status_cards,
        })

    host_val = getattr(hub, "host", "91.122.221.217") if hub else "91.122.221.217"
    port_val = getattr(hub, "port", 19090) if hub else 19090
    server_id_val = getattr(hub, "server_id", "7:48390") if hub else "7:48390"

    diag_cards.append({
        "type": "markdown",
        "content": (
            f"### Параметры подключения к зданию\n\n"
            f"▸ **Сервер здания:** `{host_val}:{port_val}`\n"
            f"▸ **Идентификатор здания:** `{server_id_val}`\n"
            f"▸ **Всего камер в сети:** {len(cam_ids)} (поток H.264 RTP)\n"
            f"▸ **Калиток и дверей:** {len(all_door_btns)}\n"
            f"▸ **Приборов учёта:** {len(meter_entities)}\n"
            f"▸ **Избранных камер:** {len(fav_cams)}\n"
            f"▸ **Фоновый поток событий (Push Listener):** Активен (Keepalive каждые 15 сек)\n"
            f"▸ **Декодер кадров:** Аппаратный FFmpeg IDR с защитой от зависаний (семафор на 2 потока)."
        ),
    })

    diag_cards.append({
        "type": "button",
        "name": "Принудительно обновить списки и данные с сервера",
        "icon": "mdi:sync",
        "color": "teal",
        "tap_action": {
            "action": "call-service",
            "service": "akvilon_home.refresh",
        },
    })

    # =========================================================================
    # ВИД 7: КИОСК (Kiosk для ТВ / Планшета)
    # =========================================================================
    kiosk_cards = [
        {
            "type": "heading",
            "heading": "Akvilon Kiosk · Настенная панель",
            "heading_style": "title",
        },
    ]
    if status_tiles:
        kiosk_cards.append({
            "type": "grid",
            "columns": 4,
            "square": False,
            "cards": status_tiles,
        })
    if fav_cards:
        kiosk_cards.append({
            "type": "heading",
            "heading": "Камеры быстрого обзора",
            "heading_style": "subtitle",
        })
        kiosk_cards.append({
            "type": "grid",
            "columns": 2,
            "square": False,
            "cards": fav_cards,
        })
    if quick_gate_cards:
        kiosk_cards.append({
            "type": "heading",
            "heading": "Открыть калитку",
            "heading_style": "subtitle",
        })
        kiosk_cards.append({
            "type": "grid",
            "columns": 4,
            "square": False,
            "cards": quick_gate_cards,
        })

    # =========================================================================
    # ФОРМИРОВАНИЕ ВИДОВ
    # =========================================================================
    views = [
        {
            "title": "Обзор",
            "icon": "mdi:home-analytics",
            "path": "overview",
            "cards": overview_cards,
        },
        {
            "title": "Камеры",
            "icon": "mdi:cctv",
            "path": "cameras",
            "type": "panel",
            "cards": camera_cards,
        },
        {
            "title": "Калитки",
            "icon": "mdi:gate",
            "path": "gates",
            "cards": gate_cards,
        },
        {
            "title": "Домофоны",
            "icon": "mdi:phone-in-talk",
            "path": "intercoms",
            "cards": intercom_cards,
        },
        {
            "title": "Счётчики",
            "icon": "mdi:counter",
            "path": "meters",
            "cards": meter_cards,
        },
        {
            "title": "Диагностика",
            "icon": "mdi:server-network",
            "path": "diagnostics",
            "cards": diag_cards,
        },
        {
            "title": "Киоск",
            "icon": "mdi:tablet-dashboard",
            "path": "kiosk",
            "cards": kiosk_cards,
        },
    ]

    return {
        "version": 1,
        "minor_version": 1,
        "key": DASH_KEY,
        "data": {"config": {"views": views}},
    }


def ensure_dashboard(hass: Any = None, hub=None):
    """Создаёт и регистрирует дашборд «Аквилон» (пересобирает, если он устарел)."""
    try:
        payload = build_dashboard_payload(hass, hub)
    except Exception as exc:  # pragma: no cover
        _LOGGER.warning("Аквилон: не удалось построить дашборд: %s", exc)
        return

    # Запись конфигурации дашборда
    storage_dir = _get_storage_dir(hass)
    try:
        os.makedirs(storage_dir, exist_ok=True)
        out_file = os.path.join(storage_dir, DASH_KEY)
        json.dump(payload, open(out_file, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        _LOGGER.info("Аквилон: дашборд успешно записан в %s", out_file)
    except Exception as exc:  # pragma: no cover
        _LOGGER.warning("Аквилон: не удалось записать дашборд-файл: %s", exc)

    # Регистрация в lovelace_dashboards
    _register_dashboard(storage_dir)

    # Установка JS-ресурса карточки домофона
    _install_resource(hass)


def _register_dashboard(storage_dir: str):
    """Регистрирует URL дашборда в общем реестре lovelace_dashboards."""
    try:
        reg_path = os.path.join(storage_dir, "lovelace_dashboards")
        reg = {"version": 1, "minor_version": 1, "key": "lovelace_dashboards", "data": {}}
        if os.path.exists(reg_path):
            try:
                reg = json.load(open(reg_path, encoding="utf-8"))
            except Exception:
                reg = {"version": 1, "minor_version": 1, "key": "lovelace_dashboards", "data": {}}
            reg.setdefault("version", 1)
            reg.setdefault("minor_version", 1)
            reg.setdefault("key", "lovelace_dashboards")
            reg.setdefault("data", {})
        data = reg["data"]
        items = data.setdefault("items", [])
        entry = {
            "id": "dashboard_akvilon",
            "title": "Аквилон",
            "icon": "mdi:video-wireless",
            "url_path": "akvilon",
            "mode": "storage",
            "require_admin": False,
            "show_in_sidebar": True,
        }
        if not any(x.get("id") == "dashboard_akvilon" for x in items):
            items.append(entry)
        data.pop("dashboards", None)
        json.dump(reg, open(reg_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        _LOGGER.info("Аквилон: дашборд зарегистрирован в lovelace_dashboards")
    except Exception as exc:  # pragma: no cover
        _LOGGER.warning("Аквилон: не удалось зарегистрировать дашборд: %s", exc)


def _install_resource(hass: Any = None):
    """Копирует custom-карточки (домофон, умная камера) в www/akvilon/ и регистрирует в lovelace_resources."""
    import uuid
    www_dir = _get_www_dir(hass)
    storage_dir = _get_storage_dir(hass)

    cards = [
        ("akvilon-intercom-card.js", INTERCOM_CARD_RESOURCE),
        ("akvilon-camera-card.js", CAMERA_CARD_RESOURCE),
    ]

    for fname, res_rel in cards:
        try:
            dest_dir = os.path.join(www_dir, "akvilon")
            os.makedirs(dest_dir, exist_ok=True)
            dest_file = os.path.join(dest_dir, fname)

            search_dirs = [
                os.path.join(os.path.dirname(__file__), "dashboard"),
                os.path.dirname(__file__),
                "/Users/evgeniy/akvilon_home/dashboard",
                "/config/custom_components/akvilon_home/dashboard",
            ]
            src_file = None
            for d in search_dirs:
                cand = os.path.join(d, fname)
                if os.path.exists(cand):
                    src_file = cand
                    break

            if src_file:
                shutil.copyfile(src_file, dest_file)
                _LOGGER.info("Аквилон: custom-карточка %s установлена в %s", fname, dest_file)
        except Exception as exc:  # pragma: no cover
            _LOGGER.warning("Аквилон: не удалось скопировать JS-ресурс %s: %s", fname, exc)

    # Регистрация в lovelace_resources с обязательным уникальным ID
    try:
        res_path = os.path.join(storage_dir, "lovelace_resources")
        res = {"version": 1, "minor_version": 1, "key": "lovelace_resources", "data": {"items": []}}
        if os.path.exists(res_path):
            try:
                res = json.load(open(res_path, encoding="utf-8"))
            except Exception:
                res = {"version": 1, "minor_version": 1, "key": "lovelace_resources", "data": {"items": []}}
            res.setdefault("data", {}).setdefault("items", [])
        items = res["data"]["items"]

        # Санитизация: гарантируем, что у каждого элемента есть id
        for it in items:
            if not it.get("id"):
                it["id"] = uuid.uuid4().hex

        changed = False
        for _, res_rel in cards:
            base_url = f"/{res_rel}"
            versioned_url = f"/{res_rel}?v=2.4"
            existing = next((i for i in items if i.get("url", "").startswith(base_url)), None)
            if existing:
                if existing.get("url") != versioned_url:
                    existing["url"] = versioned_url
                    changed = True
            else:
                items.append({
                    "id": uuid.uuid4().hex,
                    "type": "module",
                    "url": versioned_url,
                })
                changed = True
                _LOGGER.info("Аквилон: JS-ресурс %s зарегистрирован в lovelace_resources", versioned_url)

        if changed:
            json.dump(res, open(res_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    except Exception as exc:  # pragma: no cover
        _LOGGER.warning("Аквилон: не удалось зарегистрировать JS-ресурсы: %s", exc)


def remove_dashboard(hass: Any = None):
    """Удаляет дашборд «Аквилон» и его ресурсы при удалении интеграции."""
    storage_dir = _get_storage_dir(hass)
    try:
        f = os.path.join(storage_dir, DASH_KEY)
        if os.path.exists(f):
            os.remove(f)
    except Exception:  # pragma: no cover
        pass
    try:
        reg_path = os.path.join(storage_dir, "lovelace_dashboards")
        if os.path.exists(reg_path):
            reg = json.load(open(reg_path, encoding="utf-8"))
            data = reg.get("data", {})
            data.get("dashboards", {}).pop("dashboard_akvilon", None)
            items = data.get("items", [])
            items[:] = [x for x in items if x.get("id") != "dashboard_akvilon"]
            json.dump(reg, open(reg_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    except Exception:  # pragma: no cover
        pass