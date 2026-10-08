"""Константы интеграции Аквилон InHome.

Реальные данные камер/калиток собраны из работающего приложения в эмуляторе.
Видео всех камер идёт через сервер здания 127.0.0.1 на разных UDP-портах с токеном.
"""

DOMAIN = "akvilon_home"
PLATFORMS = ["camera", "button", "sensor", "binary_sensor"]

CONF_HOST = "host"
CONF_PORT = "port"
CONF_TOKEN = "token"
CONF_DEVICE_ID = "device_id"
CONF_SERVER_ID = "server_id"
CONF_NAME = "name"

# Заголовок по умолчанию для Config Entry
DEFAULT_NAME = "Аквилон InHome"
DEFAULT_DEVICE_ID = "0:0"
DEFAULT_SERVER_ID = "0:0"

# Сервер здания (реальный, из строки подключения)
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 19090
VIDEO_TOKEN = "token_0:0"  # токен для всех видео-RTP потоков
SIGN_KEY_HEX = "SUID_PLACEHOLDER"  # SUID building

# Каналы протокола (из нативки libInHome)
CHANNEL_CAMERAS = 0x10401    # список камер
CHANNEL_GATES = 0xE0401      # список калиток
CHANNEL_DOOR_BUTTONS = 0x30301  # команда открытия калитки
CH_INTERCOM = 0x10403        # домофоны / панели вызова

# Реальные камеры: id -> (название, видео-порт на сервере здания)
CAMERAS = [
    ("2:101967", "Парадная 1-1", 5010),
    ("3:101885", "Парадная 1-2", 5204),
    ("1:101865", "Холл лифта 2п.", 5024),
    ("1:101866", "Двор 2", 5052),
    ("2:99798", "Двор 3", 5060),
    ("13:99754", "ул. Советская 2под.", 5068),
    ("14:99732", "ул. Советская", 5072),
    ("2:99787", "Проход 3 и 4 кор.", 5084),
    ("1:80754", "Reka 5", 5136),
    ("1:80755", "Reka 5 (2)", 5132),
    ("111:69724", "Reka 7 торец дома", 5310),
]

# Калитки/двери: id -> название (id получаются из списка gatesList сервера)
GATES = [
    ("1", "Калитка 1"),
    ("3", "Калитка 3"),
    ("4", "Калитка 4"),
    ("5", "Калитка 5"),
    ("6", "Калитка 6"),
    ("12", "Калитка 12"),
    ("13", "Калитка 13"),
    ("14", "Калитка 14"),
    ("15", "Калитка 15"),
    ("16", "Калитка 16"),
]

# Счётчики/приборы учёта квартиры 31 (реальные показания из приложения 05.10.2026)
METERS = [
    {
        "name": "ГВС (горячая вода)",
        "device_number": "8992064",
        "value": 121.243,
        "unit": "m³",
        "device_class": "water",
        "icon": "mdi:water-boiler",
        "dt": "2026-10-05T03:17:30",
    },
    {
        "name": "Отопление",
        "device_number": "22059787",
        "value": 12.087,
        "unit": "Gcal",
        "device_class": "energy",
        "icon": "mdi:radiator",
        "dt": "2026-10-05T02:09:27",
    },
    {
        "name": "ХВС (холодная вода)",
        "device_number": "8992049",
        "value": 332.001,
        "unit": "m³",
        "device_class": "water",
        "icon": "mdi:water",
        "dt": "2026-10-05T03:17:32",
    },
    {
        "name": "Электричество",
        "device_number": "10748182728594",
        "value": 9984.45,
        "unit": "kWh",
        "values": [7248.99, 2735.46, 0, 0],
        "device_class": "energy",
        "icon": "mdi:lightning-bolt",
        "dt": "2026-10-05T01:31:32",
    },
]

SIGN_START = 0x2E
SIGN_LEN = 0x12
GATE_OPEN_DELAY = 5