# Akvilon InHome — Home Assistant integration

Интеграция Аквилон InHome для Home Assistant (Raspberry Pi, хост `klim`).
UDP-протокол к серверу здания `127.0.0.1:19090`.

## Ветки
- `main` — стабильная рабочая версия (первый коммит `0fdd8f7`)
- `develop` — разработка
- `feature/video-stream` — задача: запустить RTP-видео камер
- `feature/cleanup-entities` — задача: очистить дубли сущностей `_2`

## Структура
- `protocol.py` — UDP-клиент (подписка, регистрация, GET-списки, open_gate)
- `coordinator.py` — `AkvilonHub`: загрузка камер/калиток/счётчиков/домофонов
- `camera.py` — платформа камер
- `button.py` — кнопки открытия калиток
- `sensor.py` — счётчики и состояние калиток
- `binary_sensor.py` — онлайн-статус сервера
- `config_flow.py` — мастер настройки

## Статус (2026-10-06)
- 69 камер, калитки, 4 счётчика загружаются
- Открытие калиток через канал 0x30301 работает
- Видео-поток RTP камер: требует pcap реального приложения inHome (см. feature/video-stream)
