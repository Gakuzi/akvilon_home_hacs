# Тестирование Akvilon InHome — «ворота качества»

Никакой код не считается готовым к слиянию (merge в `develop`/`main`) без
прохождения юнит-тестов. Это работает и для людей, и для агентов.

## Быстрый старт

Подготовка pytest (один раз, из WSL/Ubuntu):

```bash
./scripts/setup_test_env.sh        # создаёт /tmp/akv_test_venv с pytest
```

Запуск тестов:

```bash
./scripts/run_tests.sh             # из WSL/Linux
./scripts/run_tests.ps1            # из Windows (обёртка над WSL cmd.exe)

./scripts/run_coverage.sh          # с покрытием (отчёт по строкам + htmlcov/)
```

Из Windows: `scripts/run_tests.ps1` сам поднимет venv через WSL, если его нет.

## Что покрыто (на 2026-10-08)

| Модуль | Что тестируется |
|--------|-----------------|
| `protocol.py` | `parse_qr`, A7ID/header/sign/get_list_payload, разбор бинарного заголовка, `open_gate` |
| `rtp_stream.py` | `parse_sprop`, сборка кадра из одиночных NAL / FU-A / STAP-A, kick-пакет |
| `coordinator.py` | демо-данные, фильтр `selected`, поиск/связка камер-калиток-домофонов, кэш настроек |
| `viewer.py` | классификация камер по разделам, HTTP-роутинг `/`, `/snap/`, `/mjpeg/`, 404 |
| `sensor.py` | `_normalize_unit`, `_meter_current`, `_meter_value` |
| `dashboard.py` | `build_dashboard_payload` с фейковым резолвером: 6 видов, только `camera.kamera_*`, нет custom-карточек, скрытие пустых видов, `_views_titles` |

Покрытие по сетевым-независимым модулям: **≥ 60%** (порог в `tests/.coveragerc`,
проверяется в CI и в `run_coverage.sh`).

## Как это работает (ворота)

1. **CI (`.github/workflows/tests.yml`)** — запускается на каждый push в
   `feature/**`, `develop`, `main` и на каждый PR. Падает, если тесты красные
   или покрытие < 60%. Это первая стена.
2. **Git-хуки `.githooks/`** — `pre-commit` и `pre-merge-commit` гоняют тесты
   локально и отклоняют commit/merge, если они не прошли. Включение:
   ```bash
   git config core.hooksPath .githooks
   ```
   Хук запускает тесты только если найден `/tmp/akv_test_venv`; без него
   предупреждает, но не блокирует (чтобы не парализовать работу до установки).

Правило Tester (см. `.githooks` и `AGENTS.md`): **без зелёных тестов — merge
заблокирован.** Если тесты не прошли, изменения отправляются обратно в
feature-ветку до исправления.

## Среда (важно для OneDrive/Windows)

- Разработка ведётся на Windows, репозиторий в OneDrive. pytest запускается в
  **WSL Ubuntu** (Python 3.14 + pytest 9 в `/tmp/akv_test_venv`).
- `calm`/странные ошибки «имя не определено» после правок — почти всегда
  вторичный `__pycache__` (OneDrive-синхронизация). Лечится очисткой:
  ```bash
  find . -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null
  ```
- HA-платформы (`camera/sensor/button/binary_sensor/config_flow/__init__/
  dashboard`) требуют рантайм Home Assistant и вне CI не гоняются голым
  Python; из-под покрытия они исключены (`tests/.coveragerc`). Проверка их
  загрузки — отдельно на Raspberry Pi (`docker restart homeassistant` + журнал).

## Как запускать тесты у себя

Все тесты изолированы (фейковые сокеты, демо-данные, HTTP на loopback): они
НЕ ходят в сеть и НЕ трогают HA. Это позволяет гонять их на любой машине
разработчика и в CI, не имея доступа к серверу здания.