"""Юнит-тесты device-id хелперов (const.py) и чистой логики energy.py.

Эти функции не требуют runtime Home Assistant и тестируются голым Python.
Стаб пакета akvilon_home создаётся в conftest.py (без загрузки __init__.py).
"""
import akvilon_home.const as C  # noqa: E402


def test_server_dev_id():
    ids = C.server_dev_id()
    assert ids == ("akvilon_home", "server", "1")


def test_camera_dev_id():
    assert C.camera_dev_id("111:69724") == ("akvilon_home", "camera", "111:69724")


def test_gate_dev_id():
    assert C.gate_dev_id("3:79649") == ("akvilon_home", "gate", "3:79649")


def test_intercom_dev_id():
    assert C.intercom_dev_id("1:101908") == ("akvilon_home", "intercom", "1:101908")


def test_meter_dev_id():
    assert C.meter_dev_id("8992064") == ("akvilon_home", "meter", "8992064")


def test_dev_id_normalizes_missing():
    assert C._devid("camera", "") == ("akvilon_home", "camera", "unknown")


def test_energy_constants():
    # Тарифы по умолчанию существуют и числовые
    assert C is not None
    # const не содержит energy-тарifов (они в energy.py), но проверим базовые константы
    assert C.DOMAIN == "akvilon_home"
    assert C.PLATFORMS == ["camera", "button", "sensor", "binary_sensor"]


def test_energy_module_functions():
    # Проверим чистые функции энерго-модуля (не требуют HA).
    import akvilon_home.energy as E

    sources = []
    # upsert воды — первый счётчик
    E._upsert_source(sources, "water", "sensor.a", 5.0)
    assert len(sources) == 1
    assert sources[0]["type"] == "water"
    assert sources[0]["stat_energy_from"] == "sensor.a"
    assert sources[0]["number_energy_price"] == 5.0

    # повторный upsert того же счётчика — обновляет цену, без дубля
    E._upsert_source(sources, "water", "sensor.a", 6.0)
    assert len(sources) == 1
    assert sources[0]["number_energy_price"] == 6.0

    # РАЗНЫЙ счётчик воды — добавляется отдельный источник (несколько линий воды)
    E._upsert_source(sources, "water", "sensor.b", 4.0, name="ГВС")
    assert len(sources) == 2
    assert sources[1]["stat_energy_from"] == "sensor.b"

    # ищем source по типу
    found = E._find_source(sources, "water")
    assert found is not None
    assert E._find_source(sources, "gas") is None