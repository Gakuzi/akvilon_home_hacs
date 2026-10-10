"""Юнит-тесты чистого парсера цен тарифов (tariffs.py).

Модуль tariffs.py не импортирует homeassistant, поэтому тестируется голым
Python: валидный ввод, None/пустой -> defaults, строки -> float, 0.0/пусто,
отрицательные/не-числа -> default, region_tariffs для известного/неизвестного
региона и структура TARIFF_FIELDS.
"""
import akvilon_home.tariffs as T


def test_default_constants():
    assert T.DEFAULT_TARIFF_REGION == "Архангельск"
    assert T.DEFAULT_TARIFFS["electricity_tariff_day"] == 8.67
    assert T.DEFAULT_TARIFFS["electricity_tariff_night"] == 3.91
    assert T.DEFAULT_TARIFFS["cold_water_tariff"] == 0.0
    assert T.DEFAULT_TARIFFS["hot_water_tariff"] == 0.0


def test_parse_valid_input():
    res = T.parse_tariffs({
        "electricity_tariff_day": 7.5,
        "electricity_tariff_night": 3.0,
        "cold_water_tariff": 42.0,
        "hot_water_tariff": 120.0,
    })
    assert res["electricity_tariff_day"] == 7.5
    assert res["electricity_tariff_night"] == 3.0
    assert res["cold_water_tariff"] == 42.0
    assert res["hot_water_tariff"] == 120.0


def test_parse_none_returns_defaults():
    assert T.parse_tariffs(None) == T.DEFAULT_TARIFFS


def test_parse_empty_dict_returns_defaults():
    assert T.parse_tariffs({}) == T.DEFAULT_TARIFFS


def test_parse_missing_keys_fill_defaults():
    res = T.parse_tariffs({"electricity_tariff_day": 6.0})
    assert res["electricity_tariff_day"] == 6.0
    assert res["electricity_tariff_night"] == T.DEFAULT_TARIFFS["electricity_tariff_night"]
    assert res["cold_water_tariff"] == 0.0
    assert res["hot_water_tariff"] == 0.0


def test_parse_string_to_float():
    res = T.parse_tariffs({"electricity_tariff_day": "8.67"})
    assert res["electricity_tariff_day"] == 8.67
    assert isinstance(res["electricity_tariff_day"], float)


def test_parse_zero_values():
    res = T.parse_tariffs({
        "electricity_tariff_day": 0,
        "electricity_tariff_night": 0.0,
        "cold_water_tariff": "",
        "hot_water_tariff": None,
    })
    assert res["electricity_tariff_day"] == 0.0
    assert res["electricity_tariff_night"] == 0.0
    assert res["cold_water_tariff"] == 0.0
    assert res["hot_water_tariff"] == 0.0


def test_parse_empty_string_is_zero():
    assert T.parse_tariffs({"electricity_tariff_day": ""})["electricity_tariff_day"] == 0.0


def test_parse_negative_uses_default():
    res = T.parse_tariffs({"electricity_tariff_day": -5.0})
    assert res["electricity_tariff_day"] == T.DEFAULT_TARIFFS["electricity_tariff_day"]


def test_parse_non_number_uses_default():
    res = T.parse_tariffs({"electricity_tariff_day": "abc"})
    assert res["electricity_tariff_day"] == T.DEFAULT_TARIFFS["electricity_tariff_day"]
    assert T.parse_tariffs({"cold_water_tariff": [1, 2]})["cold_water_tariff"] == 0.0


def test_parse_unknown_keys_ignored():
    res = T.parse_tariffs({"unrelated": 999, "electricity_tariff_day": 5.0})
    assert "unrelated" not in res
    assert res["electricity_tariff_day"] == 5.0


def test_region_tariffs_known():
    assert T.region_tariffs("Архангельск") == T.DEFAULT_TARIFFS


def test_region_tariffs_known_case_insensitive():
    assert T.region_tariffs("архангельск") == T.DEFAULT_TARIFFS


def test_region_tariffs_unknown_falls_back():
    assert T.region_tariffs("Москва") == T.DEFAULT_TARIFFS


def test_region_tariffs_none_falls_back():
    assert T.region_tariffs(None) == T.DEFAULT_TARIFFS


def test_region_tariffs_returns_copy():
    got = T.region_tariffs("Архангельск")
    got["electricity_tariff_day"] = 999.0
    assert T.DEFAULT_TARIFFS["electricity_tariff_day"] == 8.67


def test_tariff_fields_structure():
    keys = [key for key, _ in T.TARIFF_FIELDS]
    assert keys == [
        "electricity_tariff_day",
        "electricity_tariff_night",
        "cold_water_tariff",
        "hot_water_tariff",
    ]


def test_tariff_fields_defaults_match():
    for key, default in T.TARIFF_FIELDS:
        assert T.DEFAULT_TARIFFS[key] == default