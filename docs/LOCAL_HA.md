# Локальный тестовый Home Assistant (для агентов)

> ОБЯЗАТЕЛЬНО к прочтению любым агентом перед тестированием интеграции Akvilon.
> Логический принцип: тестируем НА ЛОКАЛЬНОМ HA, не на рабочем Pi, чтобы не
> ломать продакшен.

## Что это

На этом Windows-компьютере развёрнут чистейший локальный Home Assistant в Docker
контейнере `ha-local`. На нём устанавливается и тестируется интеграция Akvilon
перед тем, как что-то трогать на Raspberry Pi (владелец квартиры).

## Доступ

| Параметр | Значение |
|----------|----------|
| Адрес | `http://localhost:8123` |
| Логин | `admin` |
| Пароль | `admin1234` |
| Имя пользователя в HA | «Владелец квартиры» (создан при первой настройке) |

## Пути

- Конфиг (рабочий): `%LOCALAPPDATA%\gigatool\ha_local_config`
- Чистый бэкап: `%LOCALAPPDATA%\gigatool\ha_backup_clean`
  (копия всего конфига с учёткой и настройками; быстрое восстановление)

## Быстрое развёртывание чистого HA из бэкапа

Если нужен гарантированно чистый HA «с нуля» (без мусора, с готовым логином):

```powershell
# 1. Остановить и удалить старый контейнер
docker rm -f ha-local

# 2. Пересоздать конфиг из чистого бэкапа
Remove-Item -Recurse -Force %LOCALAPPDATA%\gigatool\ha_local_config
Copy-Item -Recurse %LOCALAPPDATA%\gigatool\ha_backup_clean %LOCALAPPDATA%\gigatool\ha_local_config

# 3. Запустить контейнер
docker run -d --name ha-local -e TZ=Europe/Moscow -p 8123:8123 `
  -v "%LOCALAPPDATA%\gigatool\ha_local_config:/config" `
  ghcr.io/home-assistant/home-assistant:stable

# 4. Подождать ~50 сек, открыть http://localhost:8123, войти admin/admin1234
```

Либо проще — запустить готовый скрипт:
```powershell
powershell -File %LOCALAPPDATA%\gigatool\ha_local_config\deploy_ha_local.ps1
```

## Как сделать свежий бэкап

После настройки чистой системы сохранить её состояние:

```powershell
# остановить HA, чтобы файлы были консистентны
docker stop ha-local
Remove-Item -Recurse -Force %LOCALAPPDATA%\gigatool\ha_backup_clean
Copy-Item -Recurse %LOCALAPPDATA%\gigatool\ha_local_config %LOCALAPPDATA%\gigatool\ha_backup_clean
docker start ha-local
```

## Интеграция Akvilon на этом HA

- Установлена локально: `custom_components/akvilon_home` и `custom_components/akvilon_dev`.
- Проверено: `config_flow` распознаёт строку, `ping` к серверу = True,
  загружает **93 устройства** (69 камер + 12 калиток + 8 домофонов + 4 счётчика).

## Напоминание про python -c и кавычки (частая ловушка)

Никогда не запускайте Python-код с двойными кавычками внутри через
`python -c "..."` из PowerShell — двойные кавычки внутри двойных ломают команду.
Правильно: писать код в `.py` файл и запускать его, либо использовать ТОЛЬКО
одинарные кавычки внутри Python, либо тройные кавычки.