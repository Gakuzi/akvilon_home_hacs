"""Автоматическая интеграция счётчиков Аквилон в энергосистему Home Assistant.

При настройке интеграции (add_to_energy=True) добавляет счётчики квартиры в
«Энергию» (Энергопанель): электричество (с тарифами день/ночь по умолчанию),
холодную и горячую воду. Использует EnergyManager — программно пишет
energy_sources, чтобы пользователю не пришлось настраивать вручную.

Отличия от ранних версий:
  * копилотская, надёжная привязка entity_id — через entity_registry по
    unique_id сенсора (falls back на скан состояний), поэтому в панель
    попадает ИМЕННО базовый счётчик дня и ночи, а не «первый, содержащий
    подстроку» (раньше ``_find_entity`` мог взять сразу тариф-_noch);
  * отопление НЕ добавляется в панель — Энергопанель HA не поддерживает
    теплосчётчики (единица Гкал) как источник: такой сенсор отклонялся с
    «класс устройства отличается от ожидаемого»;
  * битые/устаревшие источники Аквилон (сенсоры, которых больше нет, или
    прежние неверные grid/water) удаляются, чтобы панель не показывала
    «Не удалось определить объект».
"""
import logging

from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .tariffs import parse_tariffs
from .sensor import _meter_current

_LOGGER = logging.getLogger(__name__)

# Префиксы entity_id наших метер-сенсоров (для очистки устаревших источников,
# даже когда сенсор уже удалён из registry).
_AKVILON_METER_PREFIXES = ("sensor.schetchik", "sensor.pribory")


# ---------------------------------------------------------------------------
# Классификация счётчиков (чистые функции — тестируются голым Python)
# ---------------------------------------------------------------------------
def _unit_class(unit: str) -> str | None:
    """Канонический класс по единице измерения."""
    u = (unit or "").strip().lower()
    if "kwh" in u or "квт" in u:
        return "energy"
    if any(x in u for x in ("m3", "м3", "м³", "куб")):
        return "water"
    if "gcal" in u or "гкал" in u:
        return "heating"
    return None


def classify_meter(meter: dict) -> str | None:
    """Определяет роль счётчика для энергосистемы.

    Приоритет — единицы измерения (канонический класс), затем resourceType,
    затем имя. Возвращает ``electricity``, ``cold_water``, ``hot_water``,
    ``heating`` или ``None`` (не пригоден для панели).
    """
    cur = _meter_current(meter)
    unit = ""
    if isinstance(cur, dict):
        unit = (cur.get("unit") or "").strip()
    uclass = _unit_class(unit)
    rt = str(meter.get("resourceType", ""))
    name = str(meter.get("name") or "").lower()

    if uclass == "energy" or rt == "1" or "электр" in name or "electric" in name:
        return "electricity"
    if uclass == "heating" or rt == "4" or "отоп" in name or "тепло" in name:
        return "heating"
    if uclass == "water" or rt in ("2", "3"):
        if rt == "2" or "гвс" in name or "горяч" in name:
            return "hot_water"
        return "cold_water"
    return None


def _electricity_flows(day_id, night_id, base_id, price_day, price_night) -> list:
    """Строит канал grid для двух-тарифного счётчика.

    Если есть оба тарифа Т1/Т2 (день/ночь) — две записи с раздельными ценами.
    Иначе — единственный канал по полному показанию. Возвращает список dict.
    """
    if day_id and night_id:
        return [
            {"stat_energy_from": day_id, "number_energy_price": price_day},
            {"stat_energy_from": night_id, "number_energy_price": price_night},
        ]
    if base_id:
        return [{"stat_energy_from": base_id, "number_energy_price": price_day}]
    return []


def _is_akvilon_entity(reg, eid: str | None) -> bool:
    """Принадлежит ли entity_id нашей интеграции (для очистки старых источников).

    Сначала проверяет entity_registry (platform == DOMAIN); если реестра нет или
    сенсор уже удалён — по префиксу entity_id метер-сенсоров Аквилон.

    Дополнительно относим к «нашим» дублирующиеся базовые сущности, которые HA
    создал с суффиксом ``_2`` при коллизии имён (это артефакты старых версий
    интеграции). Иначе префиксный матч ловит только базовую версию, а орфанная
    ``_2`` навсегда остаётся в энергопанели.
    """
    if not eid:
        return False
    if reg is not None:
        try:
            entry = reg.entities.get(eid)
        except Exception:  # noqa: BLE001
            entry = None
        if entry is not None:
            return getattr(entry, "platform", "") == DOMAIN
    return eid.startswith(_AKVILON_METER_PREFIXES)


def _normalize_flow_entry(f: dict) -> dict | None:
    """Приводит одну FLOW-запись grid-канала к схеме, которую принимает HA.

    Убирает «битые» записи, где цена задана одновременно и числом, и полем
    (``stat_cost``/``entity_energy_price`` рядом с ``number_energy_price``) —
    EnergyManager отклоняет такую запись как ``invalid_format`` (это и есть
    «ошибка при удалении счётчика» в Энергопанели). Если запись не содержит ни
    одного валидного источника энергии — возвращает None (запись выбрасывается).
    """
    if not isinstance(f, dict):
        return None
    eid = f.get("stat_energy_from")
    if not isinstance(eid, str) or not eid:
        return None
    result = {"stat_energy_from": eid}
    # Одиночный способ задания цены: приоритет у числовой цены за кВт·ч/м³.
    num = f.get("number_energy_price")
    ent = f.get("entity_energy_price")
    cost = f.get("stat_cost")
    if num is not None:
        result["number_energy_price"] = num
    elif ent is not None and isinstance(ent, str) and ent:
        result["entity_energy_price"] = ent
    elif cost is not None and isinstance(cost, str) and cost:
        result["stat_cost"] = cost
    # stat_energy_to / flow_to-подобные поля не переносим — они не входят в FLOW.
    return result


# ---------------------------------------------------------------------------
# Резолв entity_id
# ---------------------------------------------------------------------------
def _uid_to_eid(reg) -> dict:
    """Маппинг unique_id -> entity_id наших sensor-сущностей из registry."""
    out: dict = {}
    if reg is None:
        return out
    try:
        for ent in reg.entities.values():
            platform = getattr(ent, "platform", "")
            uid = getattr(ent, "unique_id", "")
            eid = getattr(ent, "entity_id", "") or ""
            if platform == DOMAIN and "sensor" in eid and uid:
                out[uid] = eid
    except Exception:  # noqa: BLE001
        pass
    return out


def _resolve_meter_eids(reg, hass, device_number: str) -> dict:
    """Возвращает entity_id базового/тарифных сенсоров для device_number.

    Ключи: ``base``, ``day``, ``night``. Надежный путь — entity_registry по
    unique_id; запасной — скан состояний по совпадению уникального id.
    """
    base_uid = f"{DOMAIN}_meter_{device_number}"
    day_uid = f"{DOMAIN}_meter_{device_number}_tariff0"
    night_uid = f"{DOMAIN}_meter_{device_number}_tariff1"

    uid_map = _uid_to_eid(reg)
    result = {
        "base": uid_map.get(base_uid),
        "day": uid_map.get(day_uid),
        "night": uid_map.get(night_uid),
    }

    # Fallback: скан состояний (senosur может быть зарегистрирован, но ещё не
    # попасть в наш _uid_to_eid — например, при частичном reload).
    if not any(result.values()):
        try:
            for rec in hass.states.async_all():
                if rec.entity_id.startswith(DOMAIN + ".sensor."):
                    attrs = getattr(rec, "attributes", {}) or {}
                    if attrs.get("unique_id") == base_uid:
                        result["base"] = rec.entity_id
                    elif attrs.get("unique_id") == day_uid:
                        result["day"] = rec.entity_id
                    elif attrs.get("unique_id") == night_uid:
                        result["night"] = rec.entity_id
        except Exception:  # noqa: BLE001
            pass
    return result


# ---------------------------------------------------------------------------
# Сборка источников
# ---------------------------------------------------------------------------
async def async_setup_energy(hass: HomeAssistant, entry) -> None:
    """Добавляет счётчики Аквилон в Энергосистему (energy_sources)."""
    data = entry.data or {}
    if not data.get("add_to_energy", True):
        _LOGGER.info("Аквилон: add_to_energy=False, пропускаю энергосистему")
        return

    # Единый источник цен тарифов (defaults региона — из tariffs.py).
    tariffs = parse_tariffs(data)
    price_day = tariffs["electricity_tariff_day"]
    price_night = tariffs["electricity_tariff_night"]
    price_cold = tariffs["cold_water_tariff"]
    price_hot = tariffs["hot_water_tariff"]

    try:
        from homeassistant.components.energy import async_get_manager
        manager = await async_get_manager(hass)
    except Exception as exc:  # pragma: no cover
        _LOGGER.warning("Аквилон: энергосистема недоступна: %s", exc)
        return

    try:
        from homeassistant.helpers import entity_registry as er
        reg = er.async_get(hass)
    except Exception:  # pragma: no cover
        reg = None

    # Живой hub: берём реально выбранные счётчики.
    hub = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    meters = list(hub.meters) if hub is not None else []

    grid_flows: list = []
    water_entries: list = []  # {"type":"water", "stat_energy_from", price}

    for meter in meters:
        role = classify_meter(meter)
        dn = str(meter.get("deviceNumber") or meter.get("device_number") or "").strip()
        if not dn:
            continue
        ids = _resolve_meter_eids(reg, hass, dn)
        if role == "electricity":
            flows = _electricity_flows(
                ids.get("day"), ids.get("night"), ids.get("base"),
                price_day, price_night,
            )
            if flows:
                grid_flows = flows
        elif role in ("cold_water", "hot_water") and ids.get("base"):
            price = price_cold if role == "cold_water" else price_hot
            we = {"type": "water", "stat_energy_from": ids["base"]}
            if price > 0:
                we["number_energy_price"] = price
            water_entries.append(we)
        # role == heating — не добавляем: панель HA не поддерживает Гкал.

    # Читаем текущие источники (нужно сохранить чужие!).
    current = manager.data.get("energy_sources", []) if manager.data else []
    sources = list(current) if current else []

    # --- Электричество (grid) ---
    grid = _find_source(sources, "grid")
    if grid_flows and grid is None:
        # Нет источника — создаём с чистым набором каналов.
        sources.append({
            "type": "grid",
            "flow_from": list(grid_flows),
            "flow_to": [],
            "cost_adjustment_day": 0.0,
        })
    elif grid is not None:
        # Убираем наши (аквилоновские) flow-каналы и заменяем на свежие,
        # чужие каналы сохраняем как есть (но нормализуем их от битых полей).
        theirs, ours = _split_flows(grid.get("flow_from", []), reg)
        merged = [n for f in theirs if (n := _normalize_flow_entry(f)) is not None]
        seen = {n.get("stat_energy_from") for n in merged}
        for entry_flow in grid_flows:
            nf = _normalize_flow_entry(entry_flow)
            if nf and nf["stat_energy_from"] not in seen:
                merged.append(nf)
                seen.add(nf["stat_energy_from"])
        if grid_flows:
            # Есть живые каналы — кладём их даже если старых «наших» не было.
            grid["flow_from"] = merged
        else:
            # Счётчиков электричества нет — остаются только чужие нормализованные.
            grid["flow_from"] = merged

    # --- Вода: удаляем прежние источники Аквилон (в т.ч. отопление) и добавляем свежие ---
    kept = [
        s for s in sources
        if not (isinstance(s, dict) and s.get("type") == "water"
                and _is_akvilon_entity(reg, s.get("stat_energy_from")))
    ]
    # Убираем дубли water-источников: если одна и та же our-сущность указана
    # несколько раз (могла накопиться при коллизии имён _2) — оставляем одну.
    kept = _dedupe_sources(kept)
    sources = kept
    for we in water_entries:
        _upsert_source(
            sources, we["type"], we["stat_energy_from"],
            we.get("number_energy_price", 0.0),
        )

    try:
        await manager.async_update({"energy_sources": sources})
        _LOGGER.info(
            "Аквилон: счётчики добавлены в Энергию (grid-каналов %d, вода %d)",
            len(grid_flows), len(water_entries),
        )
    except Exception as exc:  # pragma: no cover
        _LOGGER.warning("Аквилон: не удалось обновить энергосистему: %s", exc)


def _split_flows(flows, reg):
    """Разделяет flow-записи grid на (наши, чужие) по принадлежности entity."""
    ours, theirs = [], []
    for f in flows:
        eid = f.get("stat_energy_from")
        (ours if _is_akvilon_entity(reg, eid) else theirs).append(f)
    return theirs, ours


def _find_source(sources, stype: str):
    """Ищет source заданного типа, возвращает dict или None."""
    for s in sources:
        if isinstance(s, dict) and s.get("type") == stype:
            return s
    return None


def _dedupe_sources(sources: list) -> list:
    """Убирает дубли источников по (type, stat_energy_from).

    Исторические версии интеграции могли оставить по одной записи и на базовую
    сущность, и на её дубль с суффиксом ``_2`` (один и тот же счётчик). Такие
    пары панель «Энергия» показывает как дубликаты и мешает нормально удалить.
    Сливаем в одну запись (берём первую), остальные отбрасываем.
    """
    seen: set = set()
    out: list = []
    for s in sources:
        if not isinstance(s, dict):
            continue
        key = (s.get("type"), s.get("stat_energy_from"))
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def _upsert_source(sources, stype: str, stat_id: str, price: float, name: str | None = None):
    """Добавляет/обновляет source воды/газа со счётчиком.

    HA позволяет несколько источников одного типа (например, две линии воды).
    Поэтому для каждого РАЗНОГО счётчика создаём отдельный источник; если такой
    stat_id уже есть — просто обновляем цену/имя, без дублей.
    """
    for s in sources:
        if isinstance(s, dict) and s.get("type") == stype and s.get("stat_energy_from") == stat_id:
            if price > 0:
                s["number_energy_price"] = price
            if name:
                s["name"] = name
            return
    src: dict = {"type": stype, "stat_energy_from": stat_id}
    if price > 0:
        src["number_energy_price"] = price
    if name:
        src["name"] = name
    sources.append(src)