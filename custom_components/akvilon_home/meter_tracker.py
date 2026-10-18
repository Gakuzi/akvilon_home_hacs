"""Модуль отслеживания изменений показаний счётчиков Аквилон.

Реализует прозрачный контроль приборов учёта:
- Дата и время последнего изменения показания (когда сервер реально обновил данные).
- Величина изменения показаний относительно последней проверки (последняя дельта Δ).
- Изменение показаний с 0:00 часов текущего дня (суточный расход).
- Расчет стоимости расхода с 0:00 в рублях по тарифам Архангельска.
- Дата и время пакета самого прибора учёта (АСКУЭ «Пульсар»).
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import sqlite3
import time
from typing import Any

_LOGGER = logging.getLogger(__name__)

STORAGE_FILE = "akvilon_meter_history.json"


def _format_unit_ru(unit: str) -> str:
    m = {
        "kWh": "кВт·ч",
        "kwh": "кВт·ч",
        "m³": "м³",
        "m3": "м³",
        "Gcal": "Гкал",
        "gcal": "Гкал",
        "GJ": "ГДж",
        "gj": "ГДж",
    }
    return m.get(unit, unit)


def _format_dt(dt_val: Any) -> str:
    if not dt_val:
        return ""
    if isinstance(dt_val, (int, float)):
        try:
            return datetime.datetime.fromtimestamp(dt_val).strftime("%d.%m.%Y %H:%M:%S")
        except Exception:
            return str(dt_val)
    if isinstance(dt_val, str):
        if "T" in dt_val:
            try:
                parts = dt_val.split("T")
                date_p = parts[0].split("-")
                time_p = parts[1].split(".")[0]
                if len(date_p) == 3:
                    return f"{date_p[2]}.{date_p[1]}.{date_p[0]} {time_p}"
            except Exception:
                pass
        return dt_val
    return str(dt_val)


ENTITY_KEY_MAP = {
    "10748182728594": "sensor.schetchik_kvartira_31_elektrichestvo",
    "10748182728594_tariff0": "sensor.schetchik_kvartira_31_elektrichestvo_den",
    "10748182728594_tariff1": "sensor.schetchik_kvartira_31_elektrichestvo_noch",
    "8992049": "sensor.schetchik_kvartira_31_khvs",
    "8992064": "sensor.schetchik_kvartira_31_gvs",
    "22059787": "sensor.schetchik_kvartira_31_otoplenie",
    "22059787_gj": "sensor.schetchik_kvartira_31_otoplenie_gdzh",
}


class MeterTracker:
    """Хранит и обновляет исторические срезы показаний счётчиков."""

    def __init__(self, storage_dir: str | None = None, db_path: str | None = None):
        self._storage_dir = storage_dir or "/home/pi/homeassistant/.storage"
        if not os.path.isdir(self._storage_dir):
            # Fallback для тестовой среды
            self._storage_dir = "/tmp"
        self._storage_file = os.path.join(self._storage_dir, STORAGE_FILE)
        self._db_path = db_path
        if not self._db_path:
            standard_db = "/home/pi/homeassistant/home-assistant_v2.db"
            if os.path.exists(standard_db):
                self._db_path = standard_db
        self._data: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if os.path.exists(self._storage_file):
            try:
                with open(self._storage_file, encoding="utf-8") as f:
                    self._data = json.load(f)
            except Exception as exc:
                _LOGGER.warning("Аквилон: ошибка загрузки истории счётчиков: %s", exc)
                self._data = {}

    def _save(self) -> None:
        import threading
        threading.Thread(target=self._save_sync, daemon=True).start()

    def _save_sync(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._storage_file), exist_ok=True)
            with open(self._storage_file, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            _LOGGER.debug("Аквилон: не удалось сохранить историю счётчиков: %s", exc)

    def _query_db_history(self, entity_id: str) -> dict[str, Any]:
        """Инициализация из базы данных SQLite Home Assistant при первом запуске."""
        res = {
            "midnight_value": None,
            "prev_value": None,
            "last_changed_ts": None,
        }
        if not self._db_path or not os.path.exists(self._db_path):
            return res

        try:
            now = datetime.datetime.now()
            today_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
            midnight_ts = today_midnight.timestamp()

            uri = f"file:{os.path.abspath(self._db_path)}?mode=ro"
            con = sqlite3.connect(uri, uri=True, timeout=2.0)
            cur = con.cursor()

            # 1. Значение на полночь (самое позднее до 00:00 сегодня)
            cur.execute("""
                SELECT s.state, s.last_updated_ts 
                FROM states s 
                JOIN states_meta sm ON s.metadata_id = sm.metadata_id 
                WHERE sm.entity_id = ? AND s.last_updated_ts <= ? AND s.state NOT IN ('unknown', 'unavailable')
                ORDER BY s.last_updated_ts DESC LIMIT 1
            """, (entity_id, midnight_ts))
            mid_row = cur.fetchone()
            if mid_row and mid_row[0] is not None:
                try:
                    res["midnight_value"] = float(mid_row[0])
                except (ValueError, TypeError):
                    pass

            # 2. Текущее и предыдущее значение
            cur.execute("""
                SELECT s.state, s.last_updated_ts 
                FROM states s 
                JOIN states_meta sm ON s.metadata_id = sm.metadata_id 
                WHERE sm.entity_id = ? AND s.state NOT IN ('unknown', 'unavailable')
                ORDER BY s.last_updated_ts DESC LIMIT 1
            """, (entity_id,))
            cur_row = cur.fetchone()

            if cur_row and cur_row[0] is not None:
                cur.execute("""
                    SELECT s.state, s.last_updated_ts 
                    FROM states s 
                    JOIN states_meta sm ON s.metadata_id = sm.metadata_id 
                    WHERE sm.entity_id = ? AND s.state != ? AND s.state NOT IN ('unknown', 'unavailable') AND s.last_updated_ts < ?
                    ORDER BY s.last_updated_ts DESC LIMIT 1
                """, (entity_id, cur_row[0], cur_row[1]))
                prev_row = cur.fetchone()
                if prev_row and prev_row[0] is not None:
                    try:
                        res["prev_value"] = float(prev_row[0])
                        res["last_changed_ts"] = float(cur_row[1])
                    except (ValueError, TypeError):
                        pass

            con.close()
        except Exception as exc:
            _LOGGER.debug("Аквилон: ошибка запроса истории из БД для %s: %s", entity_id, exc)

        return res

    def update_reading(
        self,
        key: str,
        current_value: float | None,
        unit: str = "",
        reading_date: str = "",
        tariff_rate: float = 0.0,
        entity_id: str | None = None,
        device_number: str = "",
    ) -> dict[str, Any]:
        """Обновляет показание счётчика и возвращает актуальный словарь метрик."""
        now = datetime.datetime.now()
        now_ts = now.timestamp()
        today_str = now.strftime("%Y-%m-%d")

        item = self._data.setdefault(key, {
            "key": key,
            "current_value": None,
            "prev_value": None,
            "last_changed_ts": None,
            "last_check_ts": now_ts,
            "midnight_value": None,
            "midnight_date": today_str,
            "last_delta": 0.0,
            "daily_delta": 0.0,
            "daily_cost": 0.0,
            "reading_date": reading_date,
            "unit": unit,
            "device_number": device_number,
        })

        item["last_check_ts"] = now_ts
        if unit:
            item["unit"] = unit
        if reading_date:
            item["reading_date"] = reading_date
        if device_number:
            item["device_number"] = device_number

        if current_value is None:
            return self.get_attributes(key, unit, tariff_rate)

        val = round(float(current_value), 4)

        # Смена календарного дня -> сброс суточного отсчёта на 00:00
        if item.get("midnight_date") != today_str:
            item["midnight_value"] = item.get("current_value") if item.get("current_value") is not None else val
            item["midnight_date"] = today_str
            item["daily_delta"] = 0.0
            item["daily_cost"] = 0.0

        # Если данные для ключа новые (первый опрос) — пытаемся достать историю из БД
        if item.get("current_value") is None:
            target_entity = entity_id or ENTITY_KEY_MAP.get(key)
            if target_entity:
                db_hist = self._query_db_history(target_entity)
                if db_hist.get("midnight_value") is not None:
                    item["midnight_value"] = db_hist["midnight_value"]
                if db_hist.get("prev_value") is not None:
                    item["prev_value"] = db_hist["prev_value"]
                    item["last_changed_ts"] = db_hist["last_changed_ts"]
                    item["last_delta"] = round(val - db_hist["prev_value"], 4)

            if item.get("midnight_value") is None:
                item["midnight_value"] = val
            if item.get("prev_value") is None:
                item["prev_value"] = val
            if item.get("last_changed_ts") is None:
                item["last_changed_ts"] = now_ts

            item["current_value"] = val
            self._save()
        elif val != item.get("current_value"):
            # Реальное изменение показания на сервере УК!
            prev = item["current_value"]
            item["prev_value"] = prev
            item["last_delta"] = round(val - prev, 4)
            item["last_changed_ts"] = now_ts
            item["current_value"] = val
            self._save()

        # Суточный расход с 0:00
        mid = item.get("midnight_value")
        if mid is not None:
            delta_day = round(val - mid, 4)
            item["daily_delta"] = max(0.0, delta_day)
        else:
            item["daily_delta"] = 0.0

        # Стоимость за сегодня
        if tariff_rate > 0:
            item["daily_cost"] = round(item["daily_delta"] * tariff_rate, 2)
        else:
            item["daily_cost"] = 0.0

        return self.get_attributes(key, unit, tariff_rate)

    def get_attributes(self, key: str, unit: str = "", tariff_rate: float = 0.0) -> dict[str, Any]:
        """Возвращает готовый словарь атрибутов для SensorEntity."""
        item = self._data.get(key)
        if not item:
            unit_ru = _format_unit_ru(unit)
            return {
                "last_changed_time": "Ожидание данных",
                "last_changed_str": "Ожидание данных",
                "last_check_str": _format_dt(time.time()),
                "reading_date": "",
                "reading_date_str": "Ожидание данных",
                "last_delta": 0.0,
                "last_delta_str": f"0 {unit_ru}",
                "daily_delta": 0.0,
                "daily_delta_str": f"0 {unit_ru}",
                "daily_cost": 0.0,
                "daily_cost_str": "0,00 ₽",
                "midnight_value": None,
                "prev_value": None,
            }

        unit_str = item.get("unit") or unit
        unit_ru = _format_unit_ru(unit_str)

        last_changed_ts = item.get("last_changed_ts")
        last_changed_str = _format_dt(last_changed_ts) or "Ожидание данных"
        last_check_str = _format_dt(item.get("last_check_ts")) or _format_dt(time.time())

        reading_dt = item.get("reading_date") or ""
        reading_date_str = _format_dt(reading_dt) or last_changed_str

        last_delta = float(item.get("last_delta", 0.0) or 0.0)
        daily_delta = float(item.get("daily_delta", 0.0) or 0.0)
        daily_cost = float(item.get("daily_cost", 0.0) or 0.0)

        # Знаковые строки
        if last_delta > 0:
            last_delta_str = f"+{last_delta:g} {unit_ru}"
        elif last_delta < 0:
            last_delta_str = f"{last_delta:g} {unit_ru}"
        else:
            last_delta_str = f"0 {unit_ru}"

        if daily_delta > 0:
            daily_delta_str = f"+{daily_delta:g} {unit_ru}"
        elif daily_delta < 0:
            daily_delta_str = f"{daily_delta:g} {unit_ru}"
        else:
            daily_delta_str = f"0 {unit_ru}"

        daily_cost_str = f"{daily_cost:.2f} ₽".replace(".", ",")

        return {
            "last_changed_time": last_changed_str,
            "last_changed_str": last_changed_str,
            "last_check_str": last_check_str,
            "reading_date": reading_dt,
            "reading_date_str": reading_date_str,
            "last_delta": last_delta,
            "last_delta_str": last_delta_str,
            "daily_delta": daily_delta,
            "daily_delta_str": daily_delta_str,
            "daily_cost": daily_cost,
            "daily_cost_str": daily_cost_str,
            "midnight_value": item.get("midnight_value"),
            "prev_value": item.get("prev_value"),
        }
