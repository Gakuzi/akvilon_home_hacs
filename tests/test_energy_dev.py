"""Юнит-тесты device-id хелперов (const.py) и чистой логики energy.py.

Эти функции не требуют runtime Home Assistant и тестируются голым Python.
Стаб пакета akvilon_home создаётся в conftest.py (без загрузки __init__.py).
"""
import akvilon_home.const as C  # noqa: E402
import akvilon_home.energy as E  # noqa: E402


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
    assert C.PLATFORMS == ["camera", "button", "sensor", "binary_sensor", "frigate_detect"]


# ---------------------------------------------------------------------------
# Чистые функции energy.py
# ---------------------------------------------------------------------------
def test_upsert_source():
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


def test_find_source():
    sources = []
    E._upsert_source(sources, "water", "sensor.a", 5.0)
    found = E._find_source(sources, "water")
    assert found is not None
    assert E._find_source(sources, "gas") is None


# ---------------------------------------------------------------------------
# Классификация счётчиков (по единицам / resourceType / имени)
# ---------------------------------------------------------------------------
def test_unit_class():
    assert E._unit_class("кВт*ч") == "energy"
    assert E._unit_class("kWh") == "energy"
    assert E._unit_class("м³") == "water"
    assert E._unit_class("m3") == "water"
    assert E._unit_class("Гкал") == "heating"
    assert E._unit_class("см") is None
    assert E._unit_class("") is None


def test_classify_electricity_by_unit():
    m = {"name": "Квартира 31 Электричество",
         "current": {"unit": "кВт*ч", "value": 9984.0}}
    assert E.classify_meter(m) == "electricity"


def test_classify_electricity_no_unit_but_resource_type():
    m = {"name": "X", "resourceType": "1", "current": {"unit": "", "value": 1}}
    assert E.classify_meter(m) == "electricity"


def test_classify_cold_water():
    m = {"name": "ХВС", "resourceType": "3", "current": {"unit": "м³"}}
    assert E.classify_meter(m) == "cold_water"


def test_classify_hot_water():
    m = {"name": "ГВС", "resourceType": "2", "current": {"unit": "м³"}}
    assert E.classify_meter(m) == "hot_water"


def test_classify_heating():
    m = {"name": "Отопление", "resourceType": "4", "current": {"unit": "Гкал"}}
    assert E.classify_meter(m) == "heating"


def test_classify_unknown():
    assert E.classify_meter({"current": {"unit": "см"}}) is None


# ---------------------------------------------------------------------------
# Сборка grid-каналов
# ---------------------------------------------------------------------------
def test_electricity_flows_both_tariffs():
    flows = E._electricity_flows("sensor.day", "sensor.night", "sensor.base", 8.0, 4.0)
    assert len(flows) == 2
    assert flows[0] == {"stat_energy_from": "sensor.day", "number_energy_price": 8.0}
    assert flows[1] == {"stat_energy_from": "sensor.night", "number_energy_price": 4.0}


def test_electricity_flows_base_only():
    flows = E._electricity_flows(None, None, "sensor.base", 8.0, 4.0)
    assert len(flows) == 1
    assert flows[0] == {"stat_energy_from": "sensor.base", "number_energy_price": 8.0}


def test_electricity_flows_empty():
    assert E._electricity_flows(None, None, None, 8.0, 4.0) == []


def test_upsert_water_price_zero_adds_no_price():
    sources = []
    E._upsert_source(sources, "water", "sensor.a", 0.0)
    assert sources[0]["stat_energy_from"] == "sensor.a"
    assert "number_energy_price" not in sources[0]


# ---------------------------------------------------------------------------
# Принадлежность entity нашей интеграции
# ---------------------------------------------------------------------------
def test_is_akvilon_entity_prefix_no_registry():
    assert E._is_akvilon_entity(None, "sensor.schetchik_kvartira_31_gvs") is True
    assert E._is_akvilon_entity(None, "sensor.temperatura") is False


def test_is_akvilon_entity_via_registry_platform():
    class Ent:
        platform = "akvilon_home"

    class Reg:
        entities = {"sensor.schetchik_x": Ent()}

    assert E._is_akvilon_entity(Reg(), "sensor.schetchik_x") is True


def test_is_akvilon_entity_foreign_platform():
    class Ent:
        platform = "some_other"

    class Reg:
        entities = {"sensor.chuzhoi": Ent()}

    # entity в реестре, но НЕ наша платформа
    assert E._is_akvilon_entity(Reg(), "sensor.chuzhoi") is False


# ---------------------------------------------------------------------------
# Очистка битых grid-каналов (регрессия: отопление, ошибочно добавленное как
# электричество, должно вычищаться из панели; чужие каналы сохраняются).
# ---------------------------------------------------------------------------
def test_split_flows_separates_akvilon_and_foreign():
    class Ent:
        platform = "akvilon_home"

    class Reg:
        entities = {
            "sensor.schetchik_otoplenie": Ent(),
            "sensor.pribory_ucheta_kv_31_electrichstvo_i1_den": Ent(),
        }

    flows = [
        # Отопление, ошибочно застрявшее в электросети (наша платформа)
        {"stat_energy_from": "sensor.schetchik_otoplenie", "number_energy_price": 0.0},
        # Битый/переименованный счётчик электричества (наша платформа)
        {"stat_energy_from": "sensor.pribory_ucheta_kv_31_electrichstvo_i1_den",
         "number_energy_price": 0.0},
        # Чужой счётчик (не наша платформа) — сохранить
        {"stat_energy_from": "sensor.energy_maps_grid", "number_energy_price": 5.0},
    ]

    theirs, ours = E._split_flows(flows, Reg())

    # наши битые каналы из grid вычищаются
    assert {f["stat_energy_from"] for f in ours} == {
        "sensor.schetchik_otoplenie",
        "sensor.pribory_ucheta_kv_31_electrichstvo_i1_den",
    }
    # чужие сохраняются нетронутыми
    assert [f["stat_energy_from"] for f in theirs] == ["sensor.energy_maps_grid"]


def test_split_flows_no_registry_uses_prefix():
    # Без реестра (или сенсор уже удалён) — по префиксу entity_id.
    flows = [
        {"stat_energy_from": "sensor.schetchik_gvs", "number_energy_price": 0.0},
        {"stat_energy_from": "sensor.other_integration", "number_energy_price": 0.0},
    ]
    theirs, ours = E._split_flows(flows, None)
    assert [f["stat_energy_from"] for f in ours] == ["sensor.schetchik_gvs"]
    assert [f["stat_energy_from"] for f in theirs] == ["sensor.other_integration"]